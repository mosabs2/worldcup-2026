#!/usr/bin/env python3
"""World Cup match-start + goal web-push alerts, sent via OneSignal.

Runs on the always-on Mac mini every minute during the match window. Polls the
ESPN scoreboard (same free feed the site uses), diffs against a saved state file,
and fires a OneSignal push on each new kick-off and each goal. Dedupe is via the
state file so nothing is ever sent twice; on the first sighting of an in-play
match it sets a baseline and does NOT emit phantom goals for the existing score.

OneSignal REST key from ~/.claude/onesignal-rest-key (0600, machine-local, never
vault/git). App ID is public. Stdlib only. Deployed copy: ~/.claude/jobs/wc-notify.py
Cron (mini, London local): * 17-23,0-7 * * *  = every minute across 16:00-06:59 UTC.
Self-terminates after the 19 July final. With zero subscribers OneSignal returns a
benign 400 ("not subscribed"), which is logged, not an error.
"""
import json, os, sys, time, urllib.request, urllib.error, datetime as dt

APP_ID = "c86b42d9-2e6b-40b5-8512-0f11c857decf"
KEY_FILE = os.path.expanduser("~/.claude/onesignal-rest-key")
STATE = os.path.expanduser("~/.claude/jobs/wc-notify-state.json")
LOGDIR = os.path.expanduser("~/.claude/jobs/logs")
SITE = "https://mosabs2.github.io/worldcup-2026/"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=%s"

def log(m):
    os.makedirs(LOGDIR, exist_ok=True)
    with open(os.path.join(LOGDIR, "wc-notify-%s.log" % dt.date.today().isoformat()), "a") as f:
        f.write(time.strftime("%H:%M") + " " + m + "\n")

if dt.date.today().isoformat() > "2026-07-20":
    sys.exit(0)
if not os.path.exists(KEY_FILE):
    log("no OneSignal key; skip"); sys.exit(0)
KEY = open(KEY_FILE).read().strip()

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "wc-notify/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)

def send(title, body):
    payload = json.dumps({
        "app_id": APP_ID,
        "target_channel": "push",
        "included_segments": ["Subscribed Users"],
        "headings": {"en": title},
        "contents": {"en": body},
        "url": SITE,
    }).encode()
    req = urllib.request.Request("https://api.onesignal.com/notifications", data=payload,
        headers={"Authorization": "Key " + KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.load(r)
            log("SENT '%s | %s' -> id=%s recipients=%s" % (title, body, j.get("id"), j.get("recipients")))
    except urllib.error.HTTPError as e:
        log("send '%s' HTTP %s %s" % (title, e.code, e.read().decode()[:160]))
    except Exception as e:
        log("send '%s' err %s" % (title, e))

try:
    state = json.load(open(STATE))
except Exception:
    state = {}

now = dt.datetime.now(dt.timezone.utc)
events = {}
for d in [now.strftime("%Y%m%d"), (now - dt.timedelta(days=1)).strftime("%Y%m%d")]:
    try:
        for e in fetch(ESPN % d).get("events", []):
            events[e["id"]] = e
    except Exception as ex:
        log("fetch %s err %s" % (d, ex))

for eid, e in events.items():
    try:
        comp = e["competitions"][0]
        statename = ((comp.get("status") or e.get("status") or {}).get("type") or {}).get("state")  # pre/in/post
        clock = (((comp.get("status") or e.get("status") or {}).get("type") or {}).get("shortDetail")) or ""
        cs = comp["competitors"]
        a = next((c for c in cs if c.get("homeAway") == "home"), cs[0])
        b = next((c for c in cs if c.get("homeAway") == "away"), cs[1])
        an = a["team"].get("shortDisplayName") or a["team"].get("displayName")
        bn = b["team"].get("shortDisplayName") or b["team"].get("displayName")
        asc, bsc = int(a.get("score") or 0), int(b.get("score") or 0)
        prev = state.get(eid, {})

        if statename == "in":
            if not prev.get("kickoff"):
                send("🟢 Kick-off", "%s v %s — under way" % (an, bn))
                prev["kickoff"] = True
                prev["total"] = asc + bsc          # baseline; no phantom goals
            else:
                tot = asc + bsc
                if tot > prev.get("total", tot):
                    scorer = an if asc > prev.get("a", asc) else bn
                    send("⚽ GOAL — %s" % scorer, "%s %d - %d %s  (%s)" % (an, asc, bsc, bn, clock))
                prev["total"] = tot
            prev["a"], prev["b"] = asc, bsc
        prev["state"] = statename
        state[eid] = prev
    except Exception as ex:
        log("event %s err %s" % (eid, ex))

try:
    json.dump(state, open(STATE, "w"))
except Exception as ex:
    log("state write err %s" % ex)
