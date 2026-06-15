#!/usr/bin/env python3
"""Build the live props-race leaderboards and patch a `propsLive` block into
src/data.js. Powers the dashboard's Props Race panel (Golden Boot, assists,
Dirty Trophy cards, most team goals) for the family props league.

Two modes, because the Starter tier is ~12 requests/minute:
  default : Golden Boot from shotmaps (~1 call per played match) + team goals
            from the scoreline (free). Fast and robust — safe every run.
  --full  : additionally harvest lineups -> per-player WC stats for the assists
            and cards boards (~hundreds of calls, paced; for the daily cron).

Key from STATSAPI_KEY (Action) or ~/.worldcup-statsapi.key (local). Stdlib only.
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from statsapi_common import api, paged_matches, SEASON_ID

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "src", "data.js")
MAP = os.path.join(ROOT, "src", "statsapi-map.json")
FULL = "--full" in sys.argv or os.environ.get("PROPS_FULL") == "1"

raw = open(DATA).read()
m0 = re.search(r"const WC_DATA = (\{.*?\});\nif \(typeof module", raw, re.S)
data = json.loads(m0.group(1))
codemap = json.load(open(MAP))["teamIds"]          # their tm_id -> our code

# ---- team goals from the scoreline (no API) -------------------------------
team_goals = {}
for m in data["matches"]:
    if m.get("status") == "completed" and m.get("score"):
        team_goals[m["team1"]] = team_goals.get(m["team1"], 0) + m["score"]["team1"]
        team_goals[m["team2"]] = team_goals.get(m["team2"], 0) + m["score"]["team2"]
goals_board = sorted([{"team": t, "goals": g} for t, g in team_goals.items() if g],
                     key=lambda x: -x["goals"])

finals_done = [m for m in paged_matches() if m["status"] in ("finished", "completed")]

# ---- Golden Boot from shotmaps (cheap, ~1 call/match) ---------------------
# Shot team_ids live in their own namespace; resolve via each match's event ids.
scorer_goals = {}   # (player_id) -> {"player","team","goals","pens"}
for sm in finals_done:
    if not sm.get("xg_available"): continue
    shot = api(f"/matches/{sm['id']}/shotmap")
    if not shot: continue
    ev = shot.get("event") or {}
    hc = codemap.get(sm["home_team"]["id"]); ac = codemap.get(sm["away_team"]["id"])
    side_code = {ev.get("home_team_id"): hc, ev.get("away_team_id"): ac}
    for s in (shot.get("data") or []):
        if not s.get("is_goal"): continue
        if s.get("goal_type") == "own": continue
        pid = s.get("player_id") or s.get("player_name")
        rec = scorer_goals.setdefault(pid, {"player": s.get("player_name"),
                                             "team": side_code.get(s.get("team_id")),
                                             "goals": 0, "pens": 0})
        rec["goals"] += 1
        if s.get("is_penalty"): rec["pens"] += 1
scorers = sorted(scorer_goals.values(), key=lambda x: (-x["goals"], -x["pens"], x["player"] or ""))

top_assists, team_cards_board = [], []
note = ("Golden Boot from shot data; team goals from results. Assists, cards, "
        "MENA and host props resolve over the tournament.")

# ---- optional heavy harvest: assists + cards from player stats ------------
if FULL:
    players = {}
    for sm in finals_done:
        lu = api(f"/matches/{sm['id']}/lineups")
        if not lu: continue
        d = lu.get("data", lu)
        for side in ("home", "away"):
            sd = d.get(side) or {}
            tcode = codemap.get(sd.get("id"))
            for grp in ("starting_xi", "substitutes", "bench", "subs"):
                for p in (sd.get(grp) or []):
                    pid = p.get("id")
                    if pid and pid not in players:
                        players[pid] = {"name": p.get("name"), "team": tcode}
    assisters, team_cards = [], {}
    for pid, info in players.items():
        st = api(f"/players/{pid}/stats?season_id={SEASON_ID}")
        if not st: continue
        c = st.get("data", st); sc = c.get("scoring") or {}; disc = c.get("discipline") or {}
        tcode = info["team"] or codemap.get(c.get("team_id"))
        a = sc.get("assists") or 0
        if a: assisters.append({"player": info["name"], "team": tcode, "assists": a, "goals": sc.get("goals") or 0})
        y = disc.get("yellow_cards") or disc.get("yellows") or 0
        r = disc.get("red_cards") or disc.get("reds") or 0
        if tcode and (y or r):
            tc = team_cards.setdefault(tcode, {"yellow": 0, "red": 0})
            tc["yellow"] += y; tc["red"] += r
    top_assists = sorted(assisters, key=lambda x: (-x["assists"], -x["goals"], x["player"] or ""))[:15]
    team_cards_board = sorted(
        [{"team": t, "yellow": v["yellow"], "red": v["red"], "points": v["yellow"] + 3 * v["red"]}
         for t, v in team_cards.items()], key=lambda x: -x["points"])[:12]
    note = ("Golden Boot from shot data; assists and cards from official player "
            "stats (may lag a match); team goals from results. MENA and host "
            "props resolve on the bracket.")

# preserve a prior --full harvest if this was a light (default) run
prior = data.get("propsLive") or {}
data["propsLive"] = {
    "asOf": data.get("meta", {}).get("asOf"),
    "matchesCounted": len(finals_done),
    "topScorers": scorers[:15],
    "topAssists": top_assists if FULL else prior.get("topAssists", []),
    "teamCards": team_cards_board if FULL else prior.get("teamCards", []),
    "teamGoals": goals_board[:12],
    "note": note,
}

new = "// Generated by transform.py — do not edit by hand. Patch results here, then rebuild.\n"
new += "const WC_DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n"
new += "if (typeof module !== 'undefined') module.exports = { WC_DATA };\n"
open(DATA, "w").write(new)
print(f"props ({'FULL' if FULL else 'light'}): {len(scorers)} scorers"
      + (f", {len(top_assists)} assisters, {len(team_cards_board)} carded teams" if FULL else "")
      + f" | top: {scorers[0] if scorers else 'none'}")
gh = os.environ.get("GITHUB_OUTPUT")
if gh:
    with open(gh, "a") as f: f.write("changed=true\n")
