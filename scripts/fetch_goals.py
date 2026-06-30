#!/usr/bin/env python3
"""Populate per-match goal events (scorer, minute, penalty/own-goal flags) from
ESPN's free summary feed and patch src/data.js. The timely source: runs in the
2-hourly auto-update after the score sync, so a finished match's scorers appear
within the cycle. The daily StatsAPI shotmap pass (fetch_statsapi.py) later
overwrites these with the authoritative version and marks goals_src='statsapi';
this script never overwrites a statsapi-sourced list. Stdlib only.

Usage: fetch_goals.py [--all]
  default: only completed matches that have no goals yet (or are espn-sourced).
  --all:   refresh every completed match (skips statsapi-sourced ones).
"""
import json, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "src", "data.js")
MAP = os.path.join(ROOT, "src", "espn-map.json")
SB = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates={d}"
SUM = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={e}"
HDR = {"User-Agent": "worldcup-2026-goals/1.0"}
ALL = "--all" in sys.argv

def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=30) as r:
            return json.load(r)
    except Exception:
        return None

raw = open(DATA).read()
m0 = re.search(r"const WC_DATA = (\{.*?\});\nif \(typeof module", raw, re.S)
if not m0:
    sys.exit("ERROR: could not parse WC_DATA from src/data.js (shape changed?)")
data = json.loads(m0.group(1))
idmap = json.load(open(MAP))["teamIds"]   # ESPN team id (str) -> our code

def parse_goals(summary):
    out = []
    for k in (summary or {}).get("keyEvents", []):
        if not k.get("scoringPlay"):
            continue
        if k.get("shootout"):       # penalty-shootout conversions are not match goals;
            continue                # excluding them keeps the Golden Boot correct in the KO rounds
        ttext = ((k.get("type") or {}).get("text") or "")
        tid = str((k.get("team") or {}).get("id") or "")
        code = idmap.get(tid)
        parts = k.get("participants") or []
        scorer = ((parts[0].get("athlete") or {}).get("displayName")) if parts else None
        minute = (k.get("clock") or {}).get("displayValue")
        if not code or not scorer:
            continue
        g = {"t": code, "p": scorer, "m": minute}
        is_pen = "Penalty" in ttext
        if is_pen: g["pen"] = True
        if "Own" in ttext: g["og"] = True
        # Assister: the second participant on an open-play goal (penalties and own
        # goals carry no assist). Free, from the same summary feed — feeds the
        # ESPN props-race Assists board (fetch_props_espn.py).
        if not is_pen and "Own" not in ttext and len(parts) > 1:
            assister = (parts[1].get("athlete") or {}).get("displayName")
            if assister and assister != scorer:
                g["a"] = assister
        out.append(g)
    return out

# completed matches we want goals for. ESPN is the primary source, so process any
# match not already ESPN-sourced (a prior shotmap backfill is replaced once ESPN
# has it); --all refreshes everything. Converges to zero calls once all are espn.
played = [m for m in data["matches"] if m["status"] == "completed" and m.get("score")]
todo = [m for m in played if ALL or m.get("goals_src") != "espn"]

# group by ET date, fetch each date's scoreboard once, map event by team-pair
by_date = {}
for m in todo:
    by_date.setdefault(m["dateET"][:10].replace("-", ""), []).append(m)

n = 0
for d, ms in by_date.items():
    sb = get(SB.format(d=d))
    if not sb:
        continue
    # map ESPN event id -> set of our codes
    ev_by_pair = {}
    for e in sb.get("events", []):
        try:
            comp = e["competitions"][0]
            codes = frozenset(idmap.get(str(c["team"]["id"])) or c["team"].get("abbreviation") for c in comp["competitors"])
            ev_by_pair[codes] = e["id"]
        except Exception:
            continue
    for m in ms:
        eid = ev_by_pair.get(frozenset((m["team1"], m["team2"])))
        if not eid:
            continue
        summary = get(SUM.format(e=eid))
        if summary is None:         # fetch failed (timeout/5xx); leave for next cycle
            continue                # rather than writing [] and marking it espn-done forever
        goals = parse_goals(summary)
        scoresum = m["score"]["team1"] + m["score"]["team2"]
        # Each goal in the stored scoreline is one non-shootout scoring play, so a complete
        # summary has len(goals) == scoresum. Guard two bad states that would otherwise
        # freeze a wrong list espn-done forever and silently under-count the Golden Boot:
        #   * a 200-but-empty summary against a non-zero score (feed not built yet) -> skip;
        #   * a PARTIALLY built summary (some goals, fewer than the score) -> write the
        #     best-so-far for display but do NOT mark it espn-done, so a later cycle
        #     re-fetches and overwrites with the fuller list once ESPN finishes the summary.
        # A genuine 0-0 has scoresum 0 and records [] as complete.
        if not goals and scoresum > 0:
            continue
        complete = len(goals) == scoresum
        prev_goals, prev_src = m.get("goals"), m.get("goals_src")
        m["goals"] = goals          # best-so-far; [] only for a genuine goalless match
        if complete:
            m["goals_src"] = "espn"
        else:
            m.pop("goals_src", None)   # leave un-sourced so the next cycle re-fetches
        if m.get("goals") != prev_goals or m.get("goals_src") != prev_src:
            n += 1

new = "// Generated by transform.py — do not edit by hand. Patch results here, then rebuild.\n"
new += "const WC_DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n"
new += "if (typeof module !== 'undefined') module.exports = { WC_DATA };\n"
tmp = DATA + ".tmp"
with open(tmp, "w") as f:
    f.write(new)
os.replace(tmp, DATA)            # atomic: a crash mid-write can't corrupt data.js
print(f"ESPN goals: set on {n} match(es)")
gh = os.environ.get("GITHUB_OUTPUT")
if gh:
    with open(gh, "a") as f: f.write(f"changed={'true' if n else 'false'}\n")
