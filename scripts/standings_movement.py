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

Baseline semantics: "movement since the last result."
Ranks come from the full board engine (scripts/league_rank.js), recomputed after each
completed match. The baseline is the board-rank snapshot taken when the match count last
advanced; movement = baseline rank - current rank (+ = moved up), and it HOLDS on the
board between matches until a new match advances the count and re-baselines. The ESPN feed
only writes a score at full-time, so in practice the baseline rolls forward per completed
match, not mid-play.

A match counts as "started" once it is completed (or, defensively, carries a score), so the
baseline rolls forward when a new result lands.

Run in the pipeline AFTER fetch_scores (so `status`/`score` are current) and
BEFORE build.py (so the movement is bundled into index.html). State persists in
src/standings-state.json (committed); the movement is written to
data.league.movement = {entry name: signed places moved, + up / - down}.
"""
import re, json, os, pathlib, datetime, sys, subprocess

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

def started_count(d):
    return sum(1 for m in d["matches"] if m.get("status") == "completed" or m.get("score"))

def board_ranks(d):
    """Full board rank {name: rank} via the real engine (scripts/league_rank.js):
    resolved pts -> provisional pts -> expected pts, mirroring ui.js leagueStandings.
    This is what the board displays and it shifts with every model recompute, so the
    arrows move as often as the live model does. Returns None if Node/the engine is
    unavailable — the caller then leaves the prior movement/baseline untouched. We do
    NOT fall back to the coarse group-winner rank: mixing two different rank systems
    into the baseline would publish garbage arrows and poison the next run too."""
    try:
        out = subprocess.run(["node", str(RANK_JS)], capture_output=True, text=True, timeout=120, check=True)
        ranks = json.loads(out.stdout)
        if ranks:
            return ranks
        raise ValueError("empty ranks")
    except Exception as e:
        print(f"[standings_movement] board_ranks via node failed ({e}); "
              f"leaving prior movement/baseline untouched (no write)", file=sys.stderr)
        return None

def compute(d, cur):
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
    cur = board_ranks(d)
    if cur is None:
        # rank engine unavailable — preserve the prior movement/baseline rather than
        # poisoning them; the existing data.league.movement stays as last published.
        print("[standings_movement] rank computation unavailable; left movement/baseline untouched")
        return
    movement, cur, new_state, rolled, started = compute(d, cur)
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
    # atomic writes (temp + rename) so a crash mid-write can't corrupt either file.
    # data.js first, then state — if data.js fails we never advance the baseline.
    data_tmp = DATA.with_name(DATA.name + ".tmp")
    data_tmp.write_text(new)
    os.replace(data_tmp, DATA)
    state_tmp = STATE.with_name(STATE.name + ".tmp")
    state_tmp.write_text(json.dumps(new_state, ensure_ascii=False, indent=1) + "\n")
    os.replace(state_tmp, STATE)
    print("[standings_movement] wrote data.js league.movement + standings-state.json")

if __name__ == "__main__":
    main()
