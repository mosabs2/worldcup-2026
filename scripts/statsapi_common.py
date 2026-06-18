#!/usr/bin/env python3
"""Shared TheStatsAPI client: key resolution + a header-aware rate limiter.

The Starter tier allows ~12 requests per minute (x-ratelimit-limit: 12). This
client reads x-ratelimit-remaining / x-ratelimit-reset from each response and
sleeps until the window resets when the budget is spent, so callers can fire as
many requests as they like without tripping 429s. Stdlib only.

Used by fetch_statsapi.py (xG + market) and fetch_props.py (props race).
"""
import json, os, sys, time, urllib.request, urllib.error

BASE = "https://api.thestatsapi.com/api/football"
COMP = "comp_6107"
SEASON_ID = "sn_118868"        # the 2026 finals edition
_state = {"remaining": None, "reset": 0}

def get_key():
    k = os.environ.get("STATSAPI_KEY")
    if k: return k.strip()
    p = os.path.expanduser("~/.worldcup-statsapi.key")
    if os.path.exists(p): return open(p).read().strip()
    print("No STATSAPI_KEY (env or ~/.worldcup-statsapi.key); leaving data untouched.")
    sys.exit(0)

_HDR = {"Authorization": "Bearer " + get_key(), "User-Agent": "worldcup-2026/1.0"}

def _sleep_to_reset(buffer=1.5):
    wait = max(0, _state["reset"] - time.time()) + buffer
    if wait > 0: time.sleep(min(wait, 65))

def api(path, soft=True):
    """GET BASE+path with adaptive pacing. Returns parsed JSON, or None on a
    soft failure (404/400, or exhausted retries) when soft=True."""
    # proactively wait if we know the budget is spent
    if _state["remaining"] is not None and _state["remaining"] <= 0:
        _sleep_to_reset()
    for attempt in range(5):
        req = urllib.request.Request(BASE + path, headers=_HDR)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                rem = r.headers.get("x-ratelimit-remaining")
                rst = r.headers.get("x-ratelimit-reset")
                if rem is not None: _state["remaining"] = int(rem)
                if rst is not None: _state["reset"] = float(rst)
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                rst = e.headers.get("x-ratelimit-reset")
                ra = e.headers.get("retry-after")
                if rst: _state["reset"] = float(rst); _sleep_to_reset()
                elif ra: time.sleep(min(float(ra) + 1, 65))
                else: time.sleep(5)
                _state["remaining"] = None
                continue
            if e.code in (400, 404) and soft: return None
            if attempt == 4 and soft: return None
            if attempt == 4: raise
            time.sleep(2)
        except Exception:
            if attempt == 4: return None if soft else (_ for _ in ()).throw(RuntimeError("fail: " + path))
            time.sleep(2)
    return None

def paged_matches():
    """All 2026 finals matches (season_id SEASON_ID)."""
    allm, page = [], 1
    while True:
        d = api(f"/matches?competition_id={COMP}&season=2026&per_page=50&page={page}")
        if d is None:   # request failed (retries exhausted) — not a genuine empty page;
            # surface the partial harvest rather than silently treating it as the end
            sys.stderr.write(f"paged_matches: page {page} request failed; "
                             f"returning {len(allm)} match(es) harvested so far\n")
            break
        items = d.get("data", [])
        if not items: break
        allm += items
        meta = d.get("meta") or {}
        if page >= meta.get("total_pages", 1): break
        page += 1
    return [m for m in allm if m.get("season_id") == SEASON_ID]

def _f(x):
    try: return float(x)
    except (TypeError, ValueError): return None
