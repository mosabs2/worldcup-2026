#!/usr/bin/env python3
"""World Cup match-start + goal alerts, posted to a Telegram channel.

Runs on the always-on Mac mini every minute during the match window. Polls the
ESPN scoreboard (the same free feed the site uses), diffs against a saved state
file, and posts to the family Telegram channel on each new kick-off and each goal.
Dedupe is via the state file so nothing posts twice; on the first sighting of an
in-play match it sets a baseline so no phantom goals are announced.

Bot token from ~/.claude/telegram-bot-token (0600, machine-local, never vault/git).
Channel is public (@MoSabsWC26). Stdlib only. Deployed copy: ~/.claude/jobs/wc-notify.py
Cron (mini, London local): * 17-23,0-7 * * *  = every minute across 16:00-06:59 UTC.
Self-terminates after the 19 July final.
"""
import json, os, re, sys, time, urllib.request, urllib.parse, urllib.error, datetime as dt

CHAT = "@MoSabsWC26"
TOKEN_FILE = os.path.expanduser("~/.claude/telegram-bot-token")
STATE = os.path.expanduser("~/.claude/jobs/wc-notify-state.json")
LOGDIR = os.path.expanduser("~/.claude/jobs/logs")
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=%s"
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event=%s"

def log(m):
    os.makedirs(LOGDIR, exist_ok=True)
    with open(os.path.join(LOGDIR, "wc-notify-%s.log" % dt.date.today().isoformat()), "a") as f:
        f.write(time.strftime("%H:%M") + " " + m + "\n")

if dt.date.today().isoformat() > "2026-07-20":
    sys.exit(0)
if not os.path.exists(TOKEN_FILE):
    log("no telegram token; skip"); sys.exit(0)
TOKEN = open(TOKEN_FILE).read().strip()

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "wc-notify/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)

def latest_goal(eid):
    """Most recent scoring play (scorer, minute, tag) from the ESPN summary feed."""
    try:
        s = fetch(SUMMARY % eid)
    except Exception:
        return None
    goals = [k for k in (s or {}).get("keyEvents", []) if k.get("scoringPlay")]
    if not goals:
        return None
    k = goals[-1]
    parts = k.get("participants") or []
    scorer = ((parts[0].get("athlete") or {}).get("displayName")) if parts else None
    minute = (k.get("clock") or {}).get("displayValue")
    ttext = ((k.get("type") or {}).get("text") or "")
    tag = " (pen)" if "Penalty" in ttext else (" (OG)" if "Own" in ttext else "")
    return (scorer, minute, tag)

def post(text):
    data = urllib.parse.urlencode({"chat_id": CHAT, "text": text, "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % TOKEN, data=data, timeout=20) as r:
            j = json.load(r)
            log("POST ok=%s '%s'" % (j.get("ok"), text.replace("\n", " ")))
    except urllib.error.HTTPError as e:
        log("post HTTP %s %s" % (e.code, e.read().decode()[:160]))
    except Exception as e:
        log("post err %s" % e)

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
        sttype = ((comp.get("status") or e.get("status") or {}).get("type") or {})
        statename = sttype.get("state")          # pre / in / post
        clock = sttype.get("shortDetail") or ""
        cs = comp["competitors"]
        a = next((c for c in cs if c.get("homeAway") == "home"), cs[0])
        b = next((c for c in cs if c.get("homeAway") == "away"), cs[1])
        an = a["team"].get("shortDisplayName") or a["team"].get("displayName")
        bn = b["team"].get("shortDisplayName") or b["team"].get("displayName")
        asc, bsc = int(a.get("score") or 0), int(b.get("score") or 0)
        prev = state.get(eid, {})

        if statename == "in":
            if not prev.get("kickoff"):
                # First sighting of this match in-play. Suppress the kick-off post ONLY when
                # the clock positively shows we're already deep in the match (minute > 2) —
                # a cron gap / restart first seeing an already-running game. An empty or
                # non-numeric shortDetail ("Live", "KO") is treated as the start and DOES
                # post, so a real kick-off is never silently dropped.
                mm = re.match(r"\s*(\d+)", clock)
                deep = bool(mm and int(mm.group(1)) > 2)
                if not deep:
                    post("🟢 Kick-off — %s v %s" % (an, bn))
                prev["kickoff"] = True
                prev["total"] = asc + bsc           # baseline; no phantom goals
            else:
                tot = asc + bsc
                if tot > prev.get("total", tot):
                    g = latest_goal(eid)
                    line = "⚽ GOAL!  %s %d - %d %s" % (an, asc, bsc, bn)
                    if g and g[0]:
                        line += "\n%s%s%s" % (g[0], (" " + g[1] + "'") if g[1] else "", g[2])
                    elif clock:
                        line += "   (%s)" % clock
                    post(line)
                prev["total"] = tot
            prev["a"], prev["b"] = asc, bsc
        elif statename == "post":
            if prev.get("kickoff") and not prev.get("ft"):
                post("🏁 Full time — %s %d - %d %s" % (an, asc, bsc, bn))
                prev["ft"] = True
        prev["state"] = statename
        state[eid] = prev
    except Exception as ex:
        log("event %s err %s" % (eid, ex))

try:
    json.dump(state, open(STATE, "w"))
except Exception as ex:
    log("state write err %s" % ex)
