#!/usr/bin/env python3
"""Commissioner banter — witty, data-grounded live comments to the Telegram channel.

Cron-launched on the Mac mini every 20 min during the match window. Finds a match
that's in play (and hasn't been bantered in the last ~25 min), builds a factual
context (score, minute, group, the league's group-winner pick tallies for the two
teams, the live Golden Boot leader), and asks the mini's Claude to write ONE short,
good-natured comment grounded strictly in those facts. Posts it to @MoSabsWC26.

Deliberately infrequent and grounded so it never spams or invents. Bot token from
~/.claude/telegram-bot-token; Claude auth from ~/.claude/oauth-token. Stdlib only.
  Live cron:   python3 wc-banter.py
  Tone test:   python3 wc-banter.py --test   (generates from the latest match, PRINTS, does not post)
"""
import json, os, sys, time, subprocess, urllib.request, urllib.parse, datetime as dt
from collections import Counter

CHAT = "@MoSabsWC26"
TOKEN_FILE = os.path.expanduser("~/.claude/telegram-bot-token")
OAUTH_FILE = os.path.expanduser("~/.claude/oauth-token")
CLAUDE = os.path.expanduser("~/.local/bin/claude")
STATE = os.path.expanduser("~/.claude/jobs/wc-banter-state.json")
LOGDIR = os.path.expanduser("~/.claude/jobs/logs")
DATA_URL = "https://raw.githubusercontent.com/mosabs2/worldcup-2026/main/src/data.js"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=%s"
GAP = 1500  # don't banter the same match within 25 min

def log(m):
    os.makedirs(LOGDIR, exist_ok=True)
    with open(os.path.join(LOGDIR, "wc-banter-%s.log" % dt.date.today().isoformat()), "a") as f:
        f.write(time.strftime("%H:%M") + " " + m + "\n")

def fetch(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "wc-banter/1.0"}), timeout=20))

def get_data():
    raw = urllib.request.urlopen(urllib.request.Request(DATA_URL, headers={"User-Agent": "wc-banter/1.0"}), timeout=20).read().decode()
    import re
    return json.loads(re.search(r"const WC_DATA = (\{.*?\});\nif", raw, 16).group(1))

def league_context(d, code_a, code_b, group):
    T = {t["code"]: t for t in d["teams"]}
    nm = lambda c: (T.get(c) or {}).get("name", c)
    lines = []
    if group:
        c = Counter((e.get("w") or {}).get(group) for e in d["league"]["entries"])
        a, b = c.get(code_a, 0), c.get(code_b, 0)
        lines.append("Group %s winner picks: %s %d, %s %d (of %d entrants)." %
                     (group, nm(code_a), a, nm(code_b), b, len(d["league"]["entries"])))
    pl = d.get("propsLive") or {}
    ls = (pl.get("topScorers") or [None])[0]
    if ls:
        lines.append("Golden Boot leader: %s on %d." % (ls["player"], ls["goals"]))
    return " ".join(lines)

def claude_comment(context):
    prompt = (
        "You are the witty Commissioner of a family World Cup 2026 predictions league, "
        "posting ONE short live comment to the family Telegram channel.\n\n"
        "FACTS (the only things you may use — do NOT invent goals, stats, players or events):\n"
        + context +
        "\n\nWrite ONE comment, maximum two short sentences, good-natured and either funny or sharp. "
        "British English. At most one emoji. No hashtags. You may name a league participant only if given in the facts. "
        "Output ONLY the comment text, nothing else."
    )
    env = os.environ.copy()
    try:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = open(OAUTH_FILE).read().strip()
    except Exception:
        return None
    env["PATH"] = os.path.expanduser("~/.local/bin") + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + env.get("PATH", "")
    try:
        r = subprocess.run([CLAUDE, "-p", prompt, "--model", "opus"], env=env,
                           capture_output=True, text=True, timeout=120)
    except Exception as e:
        log("claude err %s" % e); return None
    out = (r.stdout or "").strip().strip('"').strip()
    if not out or len(out) > 320:
        log("claude bad output (%d chars)" % len(out)); return None
    return out

def post(text):
    data = urllib.parse.urlencode({"chat_id": CHAT, "text": text, "disable_web_page_preview": "true"}).encode()
    urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % open(TOKEN_FILE).read().strip(), data=data, timeout=20)

def pick_match(test=False):
    d = get_data()
    now = dt.datetime.now(dt.timezone.utc)
    events = {}
    for dd in [now.strftime("%Y%m%d"), (now - dt.timedelta(days=1)).strftime("%Y%m%d")]:
        try:
            for e in fetch(ESPN % dd).get("events", []):
                events[e["id"]] = e
        except Exception as ex:
            log("fetch err %s" % ex)
    try:
        state = json.load(open(STATE))
    except Exception:
        state = {}
    cand = []
    for eid, e in events.items():
        comp = e["competitions"][0]
        st = ((comp.get("status") or {}).get("type") or {}).get("state")
        if test or (st == "in" and time.time() - state.get(eid, 0) > GAP):
            cand.append((eid, e))
    if not cand:
        return None
    eid, e = cand[0]
    comp = e["competitions"][0]; cs = comp["competitors"]
    a = next((c for c in cs if c.get("homeAway") == "home"), cs[0])
    b = next((c for c in cs if c.get("homeAway") == "away"), cs[1])
    an = a["team"].get("shortDisplayName") or a["team"].get("displayName")
    bn = b["team"].get("shortDisplayName") or b["team"].get("displayName")
    asc, bsc = a.get("score") or 0, b.get("score") or 0
    clock = ((comp.get("status") or {}).get("type") or {}).get("shortDetail") or ""
    ca, cb = a["team"].get("abbreviation"), b["team"].get("abbreviation")
    grp = next((x.get("group") for x in d["matches"] if {x.get("team1"), x.get("team2")} == {ca, cb}), None)
    ctx = "Live: %s %s-%s %s, %s, Group %s. %s" % (an, asc, bsc, bn, clock, grp or "?", league_context(d, ca, cb, grp))
    return eid, ctx, state

def main():
    test = "--test" in sys.argv
    picked = pick_match(test=test)
    if not picked:
        return
    eid, ctx, state = picked
    comment = claude_comment(ctx)
    if not comment:
        return
    if test:
        print("CONTEXT:", ctx)
        print("COMMENT:", comment)
        return
    post(comment)
    state[eid] = time.time()
    json.dump(state, open(STATE, "w"))
    log("posted: " + comment.replace("\n", " "))

if __name__ == "__main__":
    main()
