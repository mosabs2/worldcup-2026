#!/usr/bin/env python3
"""Enrich src/data.js with per-match xG and market implied probabilities from
TheStatsAPI. Runs in the GitHub Action (key from the STATSAPI_KEY secret) and
locally (key from ~/.worldcup-statsapi.key). Stdlib only.

For every 2026 finals match it can match to our fixture list it writes:
  m['xg']     = {"team1": x, "team2": y}   (completed games only)
  m['market'] = {"h": p1, "x": pX, "a": p2, "book": "..."}  (oriented to team1)
Never touches scores, status, or anything else. Used by the model
(xG-tempered Elo) and the UI (market-line reference).
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from statsapi_common import api, paged_matches, _f

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "src", "data.js")
MAP = os.path.join(ROOT, "src", "statsapi-map.json")

# --only-missing-xg: light, self-healing mode for the 15-minute auto-update flow.
# Enriches ONLY completed group matches that still lack xG, and skips the full
# market/odds sweep and the props harvest. Short-circuits with no API call at all
# when nothing is missing, so it is free to run every cycle; when a match is
# missing xG it retries each cycle until TheStatsAPI publishes the shotmap.
ONLY_XG = "--only-missing-xg" in sys.argv

def implied_1x2(payload):
    if not payload: return None
    bms = (payload.get("data") or {}).get("bookmakers") or []
    best = None
    for bm in bms:
        name = (bm.get("bookmaker") or "").lower()
        mo = ((bm.get("markets") or {}).get("match_odds")) or {}
        try:
            h = _f(mo["home"]["last_seen"]) or _f(mo["home"]["opening"])
            x = _f(mo["draw"]["last_seen"]) or _f(mo["draw"]["opening"])
            a = _f(mo["away"]["last_seen"]) or _f(mo["away"]["opening"])
        except (KeyError, TypeError):
            continue
        if not (h and x and a): continue
        rank = 0 if "pinnacle" in name else 1 if "betfair" in name else 2 if "bet365" in name else 3
        if best is None or rank < best[0]: best = (rank, (h, x, a), bm.get("bookmaker"))
    if not best: return None
    h, x, a = best[1]; inv = [1/h, 1/x, 1/a]; s = sum(inv)
    return {"h": round(inv[0]/s, 4), "x": round(inv[1]/s, 4), "a": round(inv[2]/s, 4), "book": best[2]}

def team_xg(payload):
    if not payload: return None
    shots = payload.get("data") or []
    ev = payload.get("event") or {}
    home_id, away_id = ev.get("home_team_id"), ev.get("away_team_id")
    agg = {}
    for sh in shots:
        tid, xg = sh.get("team_id"), _f(sh.get("expected_goals"))
        if tid and xg is not None: agg[tid] = agg.get(tid, 0.0) + xg
    out = {}
    if home_id in agg: out["home"] = round(agg[home_id], 2)
    if away_id in agg: out["away"] = round(agg[away_id], 2)
    return out or None

def shotmap_goals(payload, home_is_t1, t1, t2):
    """Backfill goals from the shotmap (is_goal shots), oriented to t1/t2 via the
    event's home/away ids. ESPN (fetch_goals.py) is primary; this is only used to
    fill a match ESPN could not cover."""
    if not payload: return None
    ev = payload.get("event") or {}
    home_id, away_id = ev.get("home_team_id"), ev.get("away_team_id")
    out = []
    for sh in (payload.get("data") or []):
        if not sh.get("is_goal"): continue
        tid = sh.get("team_id")
        code = (t1 if home_is_t1 else t2) if tid == home_id else (t2 if home_is_t1 else t1) if tid == away_id else None
        player, mn = sh.get("player_name"), sh.get("minute")
        if not code or not player: continue
        g = {"t": code, "p": player, "m": (str(mn) + "'" if mn is not None else None)}
        if sh.get("is_penalty"): g["pen"] = True
        if sh.get("goal_type") == "own" or sh.get("is_own_goal"): g["og"] = True
        out.append(g)
    return out

# ---- load our data + map --------------------------------------------------
raw = open(DATA).read()
m0 = re.search(r"const WC_DATA = (\{.*?\});\nif \(typeof module", raw, re.S)
if not m0:
    sys.exit("ERROR: could not parse WC_DATA from src/data.js (shape changed?)")
data = json.loads(m0.group(1))
codemap = json.load(open(MAP))["teamIds"]    # their tm_id -> our code
our_by_pair = {frozenset((m["team1"], m["team2"])): m for m in data["matches"] if m.get("stage") == "group"}

# Light mode short-circuit: if no completed match is missing xG, make no API call.
if ONLY_XG:
    missing = [m for m in our_by_pair.values()
               if m.get("status") == "completed" and m.get("score") and "xg" not in m]
    if not missing:
        print("only-missing-xg: all completed matches already have xG; no API call made")
        gh = os.environ.get("GITHUB_OUTPUT")
        if gh:
            with open(gh, "a") as f: f.write("changed=false\n")
        sys.exit(0)
    print(f"only-missing-xg: {len(missing)} completed match(es) lack xG; enriching those")

# ---- fetch finals matches -------------------------------------------------
finals = paged_matches()

enriched_xg = enriched_mkt = enriched_goals = 0
for sm in finals:
    hc = codemap.get((sm.get("home_team") or {}).get("id"))
    ac = codemap.get((sm.get("away_team") or {}).get("id"))
    if not hc or not ac: continue
    ours = our_by_pair.get(frozenset((hc, ac)))
    if not ours: continue
    if ONLY_XG and "xg" in ours: continue   # already enriched; skip (no shotmap call)
    home_is_t1 = (hc == ours["team1"])
    mid = sm["id"]
    if sm.get("odds_available") and not ONLY_XG:
        op = implied_1x2(api(f"/matches/{mid}/odds"))
        if op:
            ours["market"] = (op if home_is_t1 else
                              {"h": op["a"], "x": op["x"], "a": op["h"], "book": op["book"]})
            enriched_mkt += 1
    if sm.get("xg_available") and sm["status"] in ("finished", "completed"):
        shot = api(f"/matches/{mid}/shotmap")
        xg = team_xg(shot)
        if xg and "home" in xg and "away" in xg:
            ours["xg"] = ({"team1": xg["home"], "team2": xg["away"]} if home_is_t1 else
                          {"team1": xg["away"], "team2": xg["home"]})
            enriched_xg += 1
        # goals: shotmap is a BACKFILL only — fill a match ESPN has not covered
        if "goals" not in ours:
            g = shotmap_goals(shot, home_is_t1, ours["team1"], ours["team2"])
            if g is not None:
                ours["goals"] = g; ours["goals_src"] = "statsapi"; enriched_goals += 1

# ---- write back (mirror fetch_scores.py format) ---------------------------
new = "// Generated by transform.py — do not edit by hand. Patch results here, then rebuild.\n"
new += "const WC_DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n"
new += "if (typeof module !== 'undefined') module.exports = { WC_DATA };\n"
open(DATA, "w").write(new)
print(f"enriched: {enriched_mkt} market, {enriched_xg} xG, {enriched_goals} goals-backfill (of {len(finals)} finals matches)")
gh = os.environ.get("GITHUB_OUTPUT")
if gh:
    with open(gh, "a") as f: f.write(f"changed={'true' if (enriched_mkt or enriched_xg or enriched_goals) else 'false'}\n")
