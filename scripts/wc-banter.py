#!/usr/bin/env python3
"""Commissioner banter — witty, data-grounded live comments to the Telegram channel.

Cron-launched on the Mac mini every 20 min during the match window. Finds a match
that's in play (and hasn't been bantered in the last ~25 min), builds a factual
context (score, minute, group, the league's group-winner pick tallies, the
finalist/champion pick counts for the two teams, and the live provisional league
leader), and asks the mini's Claude to write ONE short, good-natured comment
grounded strictly in those facts. Posts it to @MoSabsWC26.

Anti-repetition: each post rotates a different lead ANGLE, and the script feeds
Claude its own recent posts and tells it not to echo them. The Golden Boot was
dropped (once a leader is uncatchable it is a stale, repetitive hook).

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

# Rotated lead angle, so successive posts don't fixate on one hook.
ANGLES = [
    "the action on the pitch — the scoreline, the drama, the clock",
    "how the league's GROUP-WINNER picks for these two teams are faring on this result",
    "who in the league has one of these teams as a FINALIST or CHAMPION pick",
    "the LIVE LEAGUE TABLE — who is on top right now and who is chasing",
]

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

def prov_leader(d):
    """Top entrant on the live provisional table (current group leaders -> points)."""
    teams = d["teams"]; groups = sorted({t["group"] for t in teams})
    leaders = {}
    for g in groups:
        codes = [t["code"] for t in teams if t["group"] == g]
        tb = {c: {"P": 0, "pts": 0, "gf": 0, "ga": 0} for c in codes}
        for mt in d["matches"]:
            if mt.get("group") != g:
                continue
            sc = mt.get("score")
            if mt.get("status") == "completed" and sc and mt["team1"] in tb and mt["team2"] in tb:
                a, b, ga, gb = mt["team1"], mt["team2"], sc["team1"], sc["team2"]
                tb[a]["P"] += 1; tb[b]["P"] += 1
                tb[a]["gf"] += ga; tb[a]["ga"] += gb; tb[b]["gf"] += gb; tb[b]["ga"] += ga
                if ga > gb: tb[a]["pts"] += 3
                elif gb > ga: tb[b]["pts"] += 3
                else: tb[a]["pts"] += 1; tb[b]["pts"] += 1
        if any(tb[c]["P"] >= 1 for c in codes):
            leaders[g] = sorted(codes, key=lambda c: (-tb[c]["pts"], -(tb[c]["gf"] - tb[c]["ga"]), -tb[c]["gf"], c))[0]
    if not leaders:
        return None
    gw = d["league"]["scoring"]["groupWinner"]
    best = None
    for e in d["league"]["entries"]:
        if e.get("exhibition"):
            continue
        pts = sum(gw for g, w in leaders.items() if (e.get("w") or {}).get(g) == w)
        if best is None or pts > best[1]:
            best = (e["n"], pts)
    return best

def league_context(d, code_a, code_b, group):
    T = {t["code"]: t for t in d["teams"]}
    nm = lambda c: (T.get(c) or {}).get("name", c)
    ents = d["league"]["entries"]
    N = len(ents)
    lines = []
    if group:
        c = Counter((e.get("w") or {}).get(group) for e in ents)
        lines.append("Group %s winner picks: %s %d, %s %d (of %d entrants)." %
                     (group, nm(code_a), c.get(code_a, 0), nm(code_b), c.get(code_b, 0), N))
    for code in (code_a, code_b):
        fin = sum(1 for e in ents if code in (e.get("f") or []))
        ch = sum(1 for e in ents if e.get("c") == code)
        if fin or ch:
            lines.append("%s: %d entrant(s) have them as a finalist, %d as champion." % (nm(code), fin, ch))
    lead = prov_leader(d)
    if lead:
        lines.append("Live provisional league leader right now: %s on %d pts." % (lead[0], lead[1]))
    return " ".join(lines)

def claude_comment(context, angle, recent):
    recent_block = ""
    if recent:
        recent_block = ("\n\nYour RECENT posts — do NOT repeat their wording or their angle:\n"
                        + "\n".join("- " + r for r in recent))
    prompt = (
        "You are the witty Commissioner of a family World Cup 2026 predictions league, "
        "posting ONE short live comment to the family Telegram channel.\n\n"
        "FACTS (the only things you may use — do NOT invent goals, stats, players or events):\n"
        + context +
        "\n\nFor THIS post, lead with: " + angle + ". "
        "If the facts above don't support that angle, pick another angle that they do support."
        + recent_block +
        "\n\nWrite ONE comment, maximum two short sentences, good-natured and either funny or sharp. "
        "British English. At most one emoji. No hashtags. Do NOT mention the Golden Boot or any top-scorer race. "
        "You may name a league participant only if given in the facts. Output ONLY the comment text, nothing else."
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

def load_state():
    try:
        s = json.load(open(STATE))
    except Exception:
        s = {}
    if "m" not in s:  # migrate the old flat {eid: ts} format
        s = {"m": {k: v for k, v in s.items() if isinstance(v, (int, float))}, "recent": [], "n": 0}
    s.setdefault("m", {}); s.setdefault("recent", []); s.setdefault("n", 0)
    return s

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
    state = load_state()
    cand = []
    for eid, e in events.items():
        comp = e["competitions"][0]
        st = ((comp.get("status") or {}).get("type") or {}).get("state")
        if test or (st == "in" and time.time() - state["m"].get(eid, 0) > GAP):
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
    angle = ANGLES[state["n"] % len(ANGLES)]
    comment = claude_comment(ctx, angle, state.get("recent", []))
    if not comment:
        return
    if test:
        print("ANGLE  :", angle)
        print("CONTEXT:", ctx)
        print("COMMENT:", comment)
        return
    post(comment)
    state["m"][eid] = time.time()
    state["n"] = state.get("n", 0) + 1
    state["recent"] = (state.get("recent", []) + [comment])[-4:]
    json.dump(state, open(STATE, "w"))
    log("posted [%s]: %s" % (angle.split(" — ")[0][:24], comment.replace("\n", " ")))

if __name__ == "__main__":
    main()
