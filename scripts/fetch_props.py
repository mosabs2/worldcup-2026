#!/usr/bin/env python3
"""Build the live props-race leaderboards (Golden Boot, assists, Dirty Trophy
cards, most team goals) and patch a `propsLive` block into src/data.js.

Incremental + cached so it stays fast on the Starter tier (~12 req/min). Each
finished match is harvested exactly once — shotmap for goals/pens, player-stats
for assists/cards — and its per-match contribution is stored in
src/props-cache.json. Subsequent runs only touch matches not yet cached, so a
run does ~2 API calls per NEW match instead of re-harvesting the whole
tournament every time. The old --full harvest re-fetched every player's season
stats every run (hundreds of calls), which blew past the 12-minute CI timeout
and was silently killed, leaving every board frozen. Team goals come from the
scoreline (no API). The --full flag is now a no-op (kept for back-compat).

src/props-cache.json is a harvest cache only; it is not inlined into index.html.
Key from STATSAPI_KEY (Action) or ~/.worldcup-statsapi.key (local). Stdlib only.
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from statsapi_common import api, paged_matches

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "src", "data.js")
MAP = os.path.join(ROOT, "src", "statsapi-map.json")
CACHE = os.path.join(ROOT, "src", "props-cache.json")

raw = open(DATA).read()
m0 = re.search(r"const WC_DATA = (\{.*?\});\nif \(typeof module", raw, re.S)
if not m0:
    sys.exit("ERROR: could not parse WC_DATA from src/data.js (shape changed?)")
data = json.loads(m0.group(1))
codemap = json.load(open(MAP))["teamIds"]          # their tm_id -> our code

cache = {}
if os.path.exists(CACHE):
    try: cache = json.load(open(CACHE))
    except Exception: cache = {}

# ---- team goals from the scoreline (no API) -------------------------------
team_goals = {}
for m in data["matches"]:
    if m.get("status") == "completed" and m.get("score"):
        team_goals[m["team1"]] = team_goals.get(m["team1"], 0) + m["score"]["team1"]
        team_goals[m["team2"]] = team_goals.get(m["team2"], 0) + m["score"]["team2"]
goals_board = sorted([{"team": t, "goals": g} for t, g in team_goals.items() if g],
                     key=lambda x: -x["goals"])

# ---- harvest any finished match not already cached ------------------------
# One shotmap call (goals + pens, own goals excluded) and one player-stats call
# (assists + cards) per match, then cache the per-match contribution. A match is
# only cached once its data is ready (xg_available and both endpoints return),
# so an unready match is simply retried on the next run.
finals_done = [m for m in paged_matches() if m["status"] in ("finished", "completed")]
# Guard against wiping live boards: if the StatsAPI match list came back empty (endpoint
# down / rate-limited) but we already have published boards, keep them rather than
# overwriting src/data.js with blank leaderboards. A transient outage should be a no-op,
# not a regression that blanks the Golden Boot / assists / cards races.
if not finals_done and data.get("propsLive"):
    print("props: match list empty (API down?); keeping existing boards, no write")
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as f: f.write("changed=false\n")
    sys.exit(0)
done_ids = {m["id"] for m in finals_done}
newly = 0
for sm in finals_done:
    mid = sm["id"]
    if mid in cache: continue
    if not sm.get("xg_available"): continue        # data not ready yet; retry next run

    shot = api(f"/matches/{mid}/shotmap")
    if not shot: continue
    ev = shot.get("event") or {}
    hc = codemap.get((sm.get("home_team") or {}).get("id"))
    ac = codemap.get((sm.get("away_team") or {}).get("id"))
    if not hc or not ac: continue   # unmappable match (feed shape / non-WC fixture); skip safely
    side_code = {ev.get("home_team_id"): hc, ev.get("away_team_id"): ac}
    scorers = {}
    for s in (shot.get("data") or []):
        if not s.get("is_goal") or s.get("goal_type") == "own": continue
        pid = s.get("player_id") or s.get("player_name")
        rec = scorers.setdefault(pid, {"pid": pid, "player": s.get("player_name"),
                                       "team": side_code.get(s.get("team_id")),
                                       "goals": 0, "pens": 0})
        rec["goals"] += 1
        if s.get("is_penalty"): rec["pens"] += 1

    ps = api(f"/matches/{mid}/player-stats")
    if not ps: continue
    rows = ps.get("data", ps)
    assists, cards = {}, {}
    for r in (rows or []):
        tcode = codemap.get(r.get("team_id"))
        a = (r.get("passing") or {}).get("assists") or 0
        if a:
            pid = r.get("player_id")
            assists[pid] = {"pid": pid, "player": r.get("player_name"), "team": tcode, "assists": a}
        g = r.get("general") or {}
        y = g.get("yellow_cards") or 0; rd = g.get("red_cards") or 0
        if tcode and (y or rd):
            tc = cards.setdefault(tcode, {"yellow": 0, "red": 0})
            tc["yellow"] += y; tc["red"] += rd

    cache[mid] = {"scorers": list(scorers.values()),
                  "assists": list(assists.values()),
                  "cards": cards}
    newly += 1

# ---- aggregate the cache (counted matches only) into the boards -----------
counted = [mid for mid in cache if mid in done_ids]
agg_goals, agg_assists, agg_cards = {}, {}, {}
for mid in counted:
    c = cache[mid]
    for s in c["scorers"]:
        r = agg_goals.setdefault(s["pid"], {"player": s["player"], "team": s["team"], "goals": 0, "pens": 0})
        r["goals"] += s["goals"]; r["pens"] += s["pens"]
    for a in c["assists"]:
        r = agg_assists.setdefault(a["pid"], {"player": a["player"], "team": a["team"], "assists": 0, "goals": 0})
        r["assists"] += a["assists"]
    for t, v in c["cards"].items():
        r = agg_cards.setdefault(t, {"yellow": 0, "red": 0})
        r["yellow"] += v["yellow"]; r["red"] += v["red"]
for pid, r in agg_assists.items():        # carry each assister's goal tally for the readout
    gr = agg_goals.get(pid)
    if gr: r["goals"] = gr["goals"]

scorers_board = sorted(agg_goals.values(), key=lambda x: (-x["goals"], -x["pens"], x["player"] or ""))[:15]
assists_board = sorted(agg_assists.values(), key=lambda x: (-x["assists"], -x["goals"], x["player"] or ""))[:15]
cards_board = sorted([{"team": t, "yellow": v["yellow"], "red": v["red"], "points": v["yellow"] + 3 * v["red"]}
                      for t, v in agg_cards.items()], key=lambda x: -x["points"])[:12]

new_props = {
    "asOf": data.get("meta", {}).get("asOf"),
    "matchesCounted": len(counted),
    "topScorers": scorers_board,
    "topAssists": assists_board,
    "teamCards": cards_board,
    "teamGoals": goals_board[:12],
    "note": ("Golden Boot from shot data; assists and cards from official match "
             "player stats; team goals from results. MENA and host props resolve "
             "on the bracket."),
}

# No-op cleanly when nothing changed, so running this every cycle never churns a
# commit (the auto-update job commits unconditionally when a step reports changed).
if newly == 0 and data.get("propsLive") == new_props:
    print("props: no change (" + str(len(counted)) + " matches counted)")
    sys.exit(0)

data["propsLive"] = new_props
if newly:
    json.dump(cache, open(CACHE, "w"), ensure_ascii=False, indent=0)
out = "// Generated by transform.py — do not edit by hand. Patch results here, then rebuild.\n"
out += "const WC_DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n"
out += "if (typeof module !== 'undefined') module.exports = { WC_DATA };\n"
open(DATA, "w").write(out)
print(f"props: {len(counted)} matches counted ({newly} newly harvested) | "
      f"{len(scorers_board)} scorers, {len(assists_board)} assisters, {len(cards_board)} carded teams | "
      f"top scorer: {scorers_board[0] if scorers_board else 'none'}")
gh = os.environ.get("GITHUB_OUTPUT")
if gh:
    with open(gh, "a") as f: f.write("changed=true\n")
