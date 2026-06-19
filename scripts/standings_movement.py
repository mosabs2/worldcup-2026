#!/usr/bin/env python3
"""
Provisional-standings MOVEMENT: server-side, persistent rank-change arrows.

Why this exists
---------------
The league board's ▲▼ arrows used to be a per-browser localStorage diff keyed by
the build timestamp, so they vanished between publishes and reset every build —
nobody saw consistent movement, and the bot had no access to it. This computes the
movement once, server-side, against a stable baseline, and bakes it into the
published data so the board, the league bot and the Commissioner banter all read
the SAME numbers, and the arrows stay on the board between matches.

Baseline semantics: "movement since the last completed match."
The baseline is the provisional ranks snapshot taken at the START of the current
(or most recent) match — re-baselined each time a new match kicks off. So:
  - during a live match, arrows show that match's live movement;
  - after it ends and between matches, the arrows HOLD that match's net effect
    (constantly on the board) until the next match kicks off and resets them.

A match counts as "started" once it is completed OR carries a score (in-play),
so the baseline rolls forward exactly when a new game begins.

Run in the pipeline AFTER fetch_scores (so `status`/`score` are current) and
BEFORE build.py (so the movement is bundled into index.html). State persists in
src/standings-state.json (committed); the movement is written to
data.league.movement = {entry name: signed places moved, + up / - down}.
"""
import re, json, pathlib, datetime, sys, subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "src" / "data.js"
STATE = ROOT / "src" / "standings-state.json"
RANK_JS = ROOT / "scripts" / "league_rank.js"

def load_data():
    raw = DATA.read_text()
    m = re.search(r"const WC_DATA = (\{.*?\});\nif", raw, re.S)
    if not m:
        m = re.search(r"WC_DATA\s*=\s*(\{.*?\});", raw, re.S)
    return raw, m, json.loads(m.group(1))

def prov_leaders(d):
    """Current leader per group that has played >=1 game (no completion gate)."""
    out = {}
    for g in sorted({t["group"] for t in d["teams"] if t.get("group")}):
        codes = [t["code"] for t in d["teams"] if t.get("group") == g]
        tbl = {c: {"P": 0, "pts": 0, "gf": 0, "ga": 0} for c in codes}
        for mt in d["matches"]:
            if mt.get("group") != g:
                continue
            sc = mt.get("score")
            if mt.get("status") == "completed" and sc and mt["team1"] in tbl and mt["team2"] in tbl:
                a, b, ga, gb = mt["team1"], mt["team2"], sc["team1"], sc["team2"]
                tbl[a]["P"] += 1; tbl[b]["P"] += 1
                tbl[a]["gf"] += ga; tbl[a]["ga"] += gb; tbl[b]["gf"] += gb; tbl[b]["ga"] += ga
                if ga > gb: tbl[a]["pts"] += 3
                elif gb > ga: tbl[b]["pts"] += 3
                else: tbl[a]["pts"] += 1; tbl[b]["pts"] += 1
        if any(tbl[c]["P"] >= 1 for c in codes):
            out[g] = sorted(codes, key=lambda c: (-tbl[c]["pts"], -(tbl[c]["gf"] - tbl[c]["ga"]), -tbl[c]["gf"], c))[0]
    return out

def prov_ranks(d):
    """{entry name: rank} by provisional points (current group leaders), ties shared.
    Mirrors wc-bot.py prov_standings so board, bot and banter agree."""
    sc = d["league"]["scoring"]; pl = prov_leaders(d)
    rows = []
    for e in d["league"]["entries"]:
        if e.get("exhibition"):
            continue
        pts = sum(sc["groupWinner"] for g, win in pl.items() if (e.get("w") or {}).get(g) == win)
        rows.append((e["n"], pts))
    rows.sort(key=lambda r: -r[1])
    ranks, rank, last, n = {}, 0, None, 0
    for name, pts in rows:
        n += 1
        if pts != last:
            rank = n; last = pts
        ranks[name] = rank
    return ranks

def started_count(d):
    return sum(1 for m in d["matches"] if m.get("status") == "completed" or m.get("score"))

def board_ranks(d):
    """Full board rank {name: rank} via the real engine (scripts/league_rank.js):
    resolved pts -> provisional pts -> expected pts, mirroring ui.js leagueStandings.
    This is what the board displays and it shifts with every model recompute, so the
    arrows move as often as the live model does. Falls back to the coarse group-winner
    rank if Node/the engine is unavailable, so movement degrades rather than breaking."""
    try:
        out = subprocess.run(["node", str(RANK_JS)], capture_output=True, text=True, timeout=120, check=True)
        ranks = json.loads(out.stdout)
        if ranks:
            return ranks
        raise ValueError("empty ranks")
    except Exception as e:
        print(f"[standings_movement] board_ranks via node failed ({e}); falling back to coarse group-winner rank", file=sys.stderr)
        return prov_ranks(d)

def compute(d):
    cur = board_ranks(d)
    started = started_count(d)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    baseline = state.get("baseline") or {}
    # movement = baseline rank - current rank (positive = moved UP)
    movement = {}
    for name, r in cur.items():
        b = baseline.get(name)
        movement[name] = (b - r) if b is not None else 0
    rolled = started > state.get("startedCount", -1) and bool(state)
    # roll the baseline forward when a NEW match has started (or on first init)
    new_state = dict(state)
    if started > state.get("startedCount", -1):
        new_state["baseline"] = cur
        new_state["startedCount"] = started
    new_state.setdefault("baseline", cur)
    new_state.setdefault("startedCount", started)
    return movement, cur, new_state, rolled, started

def main():
    dry = "--dry-run" in sys.argv
    raw, m, d = load_data()
    movement, cur, new_state, rolled, started = compute(d)
    nonzero = {k: v for k, v in movement.items() if v}
    print(f"[standings_movement] started={started} entries={len(cur)} "
          f"baseline_rolled={rolled} nonzero_moves={len(nonzero)}")
    if nonzero:
        ups = sorted([(k, v) for k, v in nonzero.items() if v > 0], key=lambda x: -x[1])[:5]
        dns = sorted([(k, v) for k, v in nonzero.items() if v < 0], key=lambda x: x[1])[:5]
        print("  up:  ", ", ".join(f"{k} +{v}" for k, v in ups) or "none")
        print("  down:", ", ".join(f"{k} {v}" for k, v in dns) or "none")
    if dry:
        print("[standings_movement] dry run — no files written")
        return
    # bake movement into data.js, writing the EXACT same format fetch_scores.py uses
    # (const WC_DATA = <json indent=1>; + the module.exports line) so the two scripts
    # never fight over formatting. league.movement = {name: signed places moved}.
    d.setdefault("league", {})["movement"] = movement
    new = "const WC_DATA = " + json.dumps(d, ensure_ascii=False, indent=1) + ";\n"
    new += "if (typeof module !== 'undefined') module.exports = { WC_DATA };\n"
    DATA.write_text(new)
    STATE.write_text(json.dumps(new_state, ensure_ascii=False, indent=1) + "\n")
    print("[standings_movement] wrote data.js league.movement + standings-state.json")

if __name__ == "__main__":
    main()
