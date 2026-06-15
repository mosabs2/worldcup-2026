#!/usr/bin/env python3
"""Phase-1 recon for the TheStatsAPI integration. LOCAL ONLY.

Reads the key from ~/.worldcup-statsapi.key (never committed), discovers the
2026 World Cup finals matches under FIFA World Cup (comp_6107, season_id
sn_118868), builds a tm_<id>/name -> our 3-letter code map, and caches per-match
closing odds (vig-removed -> implied probabilities) plus per-team match xG.

Writes:
  src/statsapi-map.json     team-id -> our code (committed; no secrets)
  .cache/statsapi.json      raw odds/xg cache (gitignored)
Prints a coverage report and any unmapped teams.
"""
import json, os, sys, time, unicodedata, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_FILE = os.path.expanduser("~/.worldcup-statsapi.key")
BASE = "https://api.thestatsapi.com/api/football"
COMP = "comp_6107"
SEASON_ID = "sn_118868"          # the 2026 finals edition
DATA = os.path.join(ROOT, "src", "data.js")
MAP_OUT = os.path.join(ROOT, "src", "statsapi-map.json")
CACHE_DIR = os.path.join(ROOT, ".cache")
CACHE_OUT = os.path.join(CACHE_DIR, "statsapi.json")

KEY = open(KEY_FILE).read().strip()
HDR = {"Authorization": "Bearer " + KEY, "User-Agent": "worldcup-2026/1.0"}

def api(path):
    url = BASE + path
    req = urllib.request.Request(url, headers=HDR)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:           # rate limit: back off
                time.sleep(2 * (attempt + 1)); continue
            raise
    raise RuntimeError("retries exhausted: " + path)

def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return "".join(c for c in s if c.isalnum())

# ---- our teams ------------------------------------------------------------
raw = open(DATA).read()
import re
m0 = re.search(r"const WC_DATA = (\{.*?\});\nif \(typeof module", raw, re.S)
ours = json.loads(m0.group(1))["teams"]
by_norm = {norm(t["name"]): t["code"] for t in ours}
by_code = {t["code"]: t["code"] for t in ours}
# aliases: their name -> our code (only where normalised names differ)
ALIAS = {
    "southkorea": "KOR", "korearepublic": "KOR", "republicofkorea": "KOR",
    "ivorycoast": "CIV", "cotedivoire": "CIV",
    "turkiye": "TUR", "turkey": "TUR",
    "capeverde": "CPV", "caboverde": "CPV",
    "bosniaherzegovina": "BIH", "bosniaandherzegovina": "BIH",
    "curacao": "CUW", "usa": "USA", "unitedstates": "USA",
    "iranislamicrepublicof": "IRN", "iran": "IRN",
}
def to_code(name):
    n = norm(name)
    return by_norm.get(n) or ALIAS.get(n) or by_code.get(name.upper().strip())

# ---- fetch all matches, isolate the 2026 finals ---------------------------
all_m, page = [], 1
while True:
    d = api(f"/matches?competition_id={COMP}&season=2026&per_page=50&page={page}")
    items = d.get("data", [])
    if not items: break
    all_m += items
    meta = d.get("meta") or {}
    if page >= meta.get("total_pages", 1): break
    page += 1
finals = [m for m in all_m if m.get("season_id") == SEASON_ID]
print(f"fetched {len(all_m)} WC matches; {len(finals)} in the 2026 finals (season {SEASON_ID})")

# ---- build team map -------------------------------------------------------
teammap, unmapped = {}, set()
for m in finals:
    for side in ("home_team", "away_team"):
        t = m[side]
        if t["id"] in teammap: continue
        code = to_code(t["name"])
        if code: teammap[t["id"]] = {"code": code, "name": t["name"]}
        else: unmapped.add((t["id"], t["name"]))
print(f"mapped {len(teammap)} team-ids; unmapped: {len(unmapped)}")
for tid, nm in sorted(unmapped): print("  UNMAPPED:", tid, nm)

json.dump({"teamIds": {k: v["code"] for k, v in teammap.items()},
           "names": {k: v["name"] for k, v in teammap.items()}},
          open(MAP_OUT, "w"), indent=1, ensure_ascii=False)
print("wrote", os.path.relpath(MAP_OUT, ROOT))

# ---- helpers: vig-removed implied probs from 1X2 closing odds -------------
def _f(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def implied_1x2(odds_payload):
    """Vig-removed 1X2 implied probs from match_odds last_seen (closing) price.
    Shape: data.bookmakers[].markets.match_odds.{home,draw,away}.{opening,last_seen}.
    Prefers Pinnacle, then Betfair, then Bet365, then any."""
    bms = (odds_payload.get("data") or {}).get("bookmakers") or []
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
    h, x, a = best[1]
    inv = [1.0/h, 1.0/x, 1.0/a]; s = sum(inv)
    return {"h": inv[0]/s, "x": inv[1]/s, "a": inv[2]/s, "book": best[2]}

def team_xg(shotmap_payload):
    """Sum expected_goals by team_id, assign to home/away via event ids."""
    shots = shotmap_payload.get("data") or []
    ev = shotmap_payload.get("event") or {}
    home_id, away_id = ev.get("home_team_id"), ev.get("away_team_id")
    agg = {}
    for sh in shots:
        tid, xg = sh.get("team_id"), _f(sh.get("expected_goals"))
        if tid and xg is not None: agg[tid] = agg.get(tid, 0.0) + xg
    out = {}
    if home_id in agg: out["home"] = round(agg[home_id], 2)
    if away_id in agg: out["away"] = round(agg[away_id], 2)
    return out or None

# ---- pull odds (all) + xG (finished) --------------------------------------
os.makedirs(CACHE_DIR, exist_ok=True)
cache = {"matches": {}}
finished = [m for m in finals if m["status"] in ("finished", "completed")]
upcoming = [m for m in finals if m["status"] not in ("finished", "completed")]
print(f"\npulling odds+xg: {len(finished)} finished, {len(upcoming)} upcoming")
for m in finals:
    mid = m["id"]
    rec = {"home": teammap.get(m["home_team"]["id"], {}).get("code"),
           "away": teammap.get(m["away_team"]["id"], {}).get("code"),
           "status": m["status"], "utc": m["utc_date"],
           "score": m.get("score")}
    if m.get("odds_available"):
        try: rec["odds_prob"] = implied_1x2(api(f"/matches/{mid}/odds"))
        except Exception as e: rec["odds_err"] = str(e)[:80]
    if m.get("xg_available"):
        try: rec["xg"] = team_xg(api(f"/matches/{mid}/shotmap"))
        except Exception as e: rec["xg_err"] = str(e)[:80]
    cache["matches"][mid] = rec
json.dump(cache, open(CACHE_OUT, "w"), indent=1, ensure_ascii=False)
print("wrote", os.path.relpath(CACHE_OUT, ROOT))

# ---- coverage report ------------------------------------------------------
got_odds = [r for r in cache["matches"].values() if r.get("odds_prob")]
got_xg = [r for r in cache["matches"].values() if r.get("xg")]
print(f"\nCOVERAGE: odds parsed {len(got_odds)}/{len(finals)} | xg parsed {len(got_xg)}/{len(finished)}")
print("\n--- our 12 played games: closing-odds implied probs + xG ---")
for r in sorted([r for r in cache['matches'].values() if r['status'] in ('finished','completed') and r['utc'][:10]<='2026-06-15'], key=lambda x:x['utc']):
    op = r.get("odds_prob"); xg = r.get("xg") or {}
    s = r.get("score") or {}
    op_s = f"H{op['h']:.0%}/D{op['x']:.0%}/A{op['a']:.0%}" if op else "no-odds"
    print(f"  {r['utc'][:16]} {r['home']} {s.get('home')}-{s.get('away')} {r['away']} | {op_s} | xG {xg.get('home','?')}-{xg.get('away','?')}")
