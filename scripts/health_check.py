#!/usr/bin/env python3
"""Site data watchdog. Validates internal consistency of src/data.js and exits
non-zero on a hard failure, so a stale or broken publish turns the GitHub Action
RED (and emails the repo owner) instead of being silently swallowed.

It exists because the props race once froze for two days while the workflow kept
reporting success: the failure was non-fatal and the stale data still looked
plausible. These checks are wall-clock independent — they compare the data
against itself (does the props board cover as many matches as have been played?),
which is exactly the silent-staleness class a green/red CI status cannot see.

HARD failures (exit 1):
  - propsLive missing entirely
  - props boards lag the played matches by more than PROPS_LAG_TOLERANCE
  - matches have been played but Golden Boot or team-goals board is empty
  - enough matches played but the assists board is empty
WARN (printed, exit 0):
  - propsLive.asOf older than meta.asOf
  - completed matches still missing xG (legitimately lags ~15 min)

Stdlib only. Run as the final workflow step, after publish.
"""
import json, os, re, sys

# TheStatsAPI feed was dropped on 20 Jun 2026 (Starter monthly quota exhausted;
# the backtest had already shown its market odds were no sharper than the model).
# The props race + xG are intentionally frozen at their 19 Jun final state, so the
# freshness checks below (props-lag, propsLive.asOf, missing-xG) no longer apply;
# the structural checks (propsLive present, boards non-empty) stay armed to protect
# the frozen panel. Set this True again to re-arm freshness if the feed is revived.
STATSAPI_ENABLED = False

PROPS_LAG_TOLERANCE = 2          # props may trail scores by up to 2 matches (latest
                                 # match's player-stats can lag the final whistle)
ASSISTS_EXPECTED_AFTER = 5       # by this many counted matches, assists must be present

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "src", "data.js")

raw = open(DATA).read()
m0 = re.search(r"const WC_DATA = (\{.*?\});\nif \(typeof module", raw, re.S)
if not m0:
    print("FAIL: could not parse WC_DATA out of src/data.js"); sys.exit(1)
data = json.loads(m0.group(1))

fails, warns = [], []

completed = [m for m in data.get("matches", []) if m.get("status") == "completed" and m.get("score")]
ncomp = len(completed)
meta_asof = (data.get("meta") or {}).get("asOf")
pl = data.get("propsLive")

if pl is None:
    fails.append("propsLive block is missing entirely")
else:
    counted = pl.get("matchesCounted", 0)
    lag = ncomp - counted
    # Freshness checks apply only while the StatsAPI feed is live.
    if STATSAPI_ENABLED and lag > PROPS_LAG_TOLERANCE:
        fails.append(f"props race is stale: {counted} matches counted but {ncomp} have been "
                     f"played (lag {lag} > tolerance {PROPS_LAG_TOLERANCE}). The props harvest "
                     f"is not keeping up — this is the silent-staleness failure the watchdog exists for.")
    # Structural checks stay armed: the frozen props panel must still render.
    if ncomp > 0 and not pl.get("topScorers"):
        fails.append("matches have been played but the Golden Boot board is empty")
    if ncomp > 0 and not pl.get("teamGoals"):
        fails.append("matches have been played but the team-goals board is empty")
    if counted >= ASSISTS_EXPECTED_AFTER and not pl.get("topAssists"):
        fails.append(f"{counted} matches counted but the assists board is empty")
    if STATSAPI_ENABLED and meta_asof and pl.get("asOf") and pl["asOf"] < meta_asof:
        warns.append(f"propsLive.asOf ({pl['asOf']}) is behind meta.asOf ({meta_asof})")

if STATSAPI_ENABLED:
    missing_xg = [m for m in completed if not m.get("xg")]
    if missing_xg:
        warns.append(f"{len(missing_xg)} completed match(es) still lack xG (usually fills within ~15 min)")

for w in warns: print("WARN:", w)
for f in fails: print("FAIL:", f)

if fails:
    print(f"\nwatchdog: FAILED ({len(fails)} hard issue(s), {len(warns)} warning(s)) — "
          f"{ncomp} matches played.")
    sys.exit(1)
print(f"watchdog: OK ({ncomp} matches played, props counts {pl.get('matchesCounted') if pl else 'n/a'}; "
      f"{len(warns)} warning(s)).")
