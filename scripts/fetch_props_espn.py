#!/usr/bin/env python3
"""Rebuild the live props-race leaderboards (Golden Boot, assists, Dirty Trophy
cards, most team goals) entirely from ESPN's FREE feeds and patch a `propsLive`
block into src/data.js. Replaces the StatsAPI-only fetch_props.py, dropped when
TheStatsAPI feed was cancelled (20 Jun 2026), which left the whole props panel
frozen at its 19 Jun state even though three of the four boards never needed a
paid feed.

Sources, all free, same provider as the scores (no cross-provider seam):
  - team goals  : from the scoreline already in data.js          (no API call)
  - Golden Boot : aggregated from each match's `goals` list,      (no API call)
                  which fetch_goals.py populates every cycle
  - assists     : from the assister (`a`) on each open-play goal, (no API call)
                  captured by fetch_goals.py from the summary feed
  - cards       : yellowCards / redCards from ESPN's core per-competitor
                  statistics endpoint (the same endpoint fetch_xg.py uses),
                  cached per match in src/props-cache-espn.json so a finished
                  match's cards are fetched exactly once.

Only the cards board touches the network, and only for matches not yet cached,
so a steady-state run does ~0 calls. Stdlib only.

Usage: fetch_props_espn.py [--all]
  --all: re-fetch cards for every completed match (ignore the cache).
"""
import json, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "src", "data.js")
MAP = os.path.join(ROOT, "src", "espn-map.json")
CACHE = os.path.join(ROOT, "src", "props-cache-espn.json")
SB = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates={d}"
STAT = ("https://sports.core.api.espn.com/v2/sports/soccer/leagues/fifa.world/"
        "events/{e}/competitions/{e}/competitors/{t}/statistics")
HDR = {"User-Agent": "worldcup-2026-props/1.0"}
ALL = "--all" in sys.argv


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=30) as r:
            return json.load(r)
    except Exception:
        return None


def find_stat(obj, name):
    """Depth-first search for a stat object {'name': name, 'value': <number>}."""
    stack = [obj]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            if x.get("name") == name and isinstance(x.get("value"), (int, float)):
                return float(x["value"])
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
    return None


raw = open(DATA).read()
m0 = re.search(r"const WC_DATA = (\{.*?\});\nif \(typeof module", raw, re.S)
if not m0:
    sys.exit("ERROR: could not parse WC_DATA from src/data.js (shape changed?)")
data = json.loads(m0.group(1))
idmap = json.load(open(MAP))["teamIds"]            # ESPN team id (str) -> our code

completed = [m for m in data["matches"] if m.get("status") == "completed" and m.get("score")]

# ---- team goals from the scoreline (no API) -------------------------------
team_goals = {}
for m in completed:
    team_goals[m["team1"]] = team_goals.get(m["team1"], 0) + m["score"]["team1"]
    team_goals[m["team2"]] = team_goals.get(m["team2"], 0) + m["score"]["team2"]
goals_board = sorted([{"team": t, "goals": g} for t, g in team_goals.items() if g],
                     key=lambda x: -x["goals"])[:12]

# ---- Golden Boot + assists from each match's goal list (no API) -----------
# fetch_goals.py lands m["goals"] = [{"t":code,"p":scorer,"m":min,"pen":?,"og":?,"a":assister?}]
scorers, assisters = {}, {}
for m in completed:
    for g in (m.get("goals") or []):
        if g.get("og"):                            # own goals credit no scorer
            continue
        sk = (g.get("p"), g.get("t"))
        if sk[0] and sk[1]:
            r = scorers.setdefault(sk, {"player": g["p"], "team": g["t"], "goals": 0, "pens": 0})
            r["goals"] += 1
            if g.get("pen"):
                r["pens"] += 1
        a = g.get("a")
        if a and g.get("t"):                       # assister already excludes pens/OGs
            ak = (a, g["t"])
            r = assisters.setdefault(ak, {"player": a, "team": g["t"], "assists": 0, "goals": 0})
            r["assists"] += 1
for (name, team), r in assisters.items():          # carry the assister's own goal tally
    gr = scorers.get((name, team))
    if gr:
        r["goals"] = gr["goals"]

scorers_board = sorted(scorers.values(), key=lambda x: (-x["goals"], -x["pens"], x["player"] or ""))[:15]
assists_board = sorted(assisters.values(), key=lambda x: (-x["assists"], -x["goals"], x["player"] or ""))[:15]

# ---- cards from ESPN core stats (cached per match) ------------------------
cache = {}
if os.path.exists(CACHE):
    try:
        cache = json.load(open(CACHE))
    except Exception:
        cache = {}

def mkey(m):
    return f"{m['team1']}-{m['team2']}-{m['dateET'][:10]}"

todo = [m for m in completed if ALL or mkey(m) not in cache]
# group by ET date; one scoreboard call per date resolves event id + ESPN team ids
by_date = {}
for m in todo:
    by_date.setdefault(m["dateET"][:10].replace("-", ""), []).append(m)

newly = 0
for d, ms in by_date.items():
    sb = get(SB.format(d=d))
    if not sb:
        continue
    ev_by_pair = {}
    for e in sb.get("events", []):
        try:
            comp = e["competitions"][0]
            cmap = {}
            for c in comp["competitors"]:
                tid = str(c["team"]["id"])
                cmap[idmap.get(tid) or c["team"].get("abbreviation")] = tid
            ev_by_pair[frozenset(cmap)] = (e["id"], cmap)
        except Exception:
            continue
    for m in ms:
        hit = ev_by_pair.get(frozenset((m["team1"], m["team2"])))
        if not hit:
            continue
        eid, cmap = hit
        rec, ok = {}, True
        for side in ("team1", "team2"):
            code = m[side]
            tid = cmap.get(code)
            st = get(STAT.format(e=eid, t=tid)) if tid else None
            if st is None:                         # fetch failed; retry whole match next run
                ok = False
                break
            yv = find_stat(st, "yellowCards")
            rv = find_stat(st, "redCards")
            # Distinguish "stat absent" from "genuinely zero": the per-competitor stats
            # resource can return 200 before cards populate (or with an empty statistics
            # array). If NEITHER card stat is present, treat it as a soft failure and retry
            # next run rather than caching 0/0 forever (which would permanently under-count
            # the Dirty Trophy board). A real 0-card team still reports the stat as 0.
            if yv is None and rv is None:
                ok = False
                break
            rec[code] = {"y": int(yv or 0), "r": int(rv or 0)}
        if ok and len(rec) == 2:
            cache[mkey(m)] = rec
            newly += 1

# aggregate cards over the cached matches that are still completed in the data
valid_keys = {mkey(m) for m in completed}
agg_cards = {}
for k, rec in cache.items():
    if k not in valid_keys:
        continue
    for code, v in rec.items():
        r = agg_cards.setdefault(code, {"yellow": 0, "red": 0})
        r["yellow"] += v["y"]
        r["red"] += v["r"]
cards_board = sorted([{"team": t, "yellow": v["yellow"], "red": v["red"],
                       "points": v["yellow"] + 3 * v["red"]}
                      for t, v in agg_cards.items()], key=lambda x: -x["points"])[:12]

new_props = {
    "asOf": data.get("meta", {}).get("asOf"),
    "matchesCounted": len(completed),
    "topScorers": scorers_board,
    "topAssists": assists_board,
    "teamCards": cards_board,
    "teamGoals": goals_board,
    "note": ("Golden Boot, assists and team goals from ESPN goal events; cards from "
             "ESPN match statistics. MENA and host props resolve on the bracket."),
}

# No-op cleanly when nothing changed, so running every cycle never churns a commit.
if newly == 0 and data.get("propsLive") == new_props:
    print(f"props: no change ({len(completed)} matches counted)")
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as f:
            f.write("changed=false\n")
    sys.exit(0)

data["propsLive"] = new_props
if newly:
    json.dump(cache, open(CACHE, "w"), ensure_ascii=False, indent=0)
out = "// Generated by transform.py — do not edit by hand. Patch results here, then rebuild.\n"
out += "const WC_DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n"
out += "if (typeof module !== 'undefined') module.exports = { WC_DATA };\n"
tmp = DATA + ".tmp"
with open(tmp, "w") as f:
    f.write(out)
os.replace(tmp, DATA)            # atomic: a crash mid-write can't corrupt data.js
print(f"props: {len(completed)} matches counted ({newly} new card harvest) | "
      f"{len(scorers_board)} scorers, {len(assists_board)} assisters, "
      f"{len(cards_board)} carded teams | "
      f"top scorer: {scorers_board[0] if scorers_board else 'none'}")
gh = os.environ.get("GITHUB_OUTPUT")
if gh:
    with open(gh, "a") as f:
        f.write("changed=true\n")
