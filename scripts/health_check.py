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

# TheStatsAPI feed was dropped on 20 Jun 2026 (Starter monthly quota exhausted).
# This flag now only gates the StatsAPI-specific missing-xG warn below; the props
# race no longer depends on it.
STATSAPI_ENABLED = False

# The props race was revived from ESPN's free feeds on 22 Jun 2026
# (fetch_props_espn.py), after the StatsAPI drop left it silently frozen 8 matches
# behind (28 counted vs 36 played) — the exact silent-staleness this watchdog
# exists to catch, missed because only the empty-board check was armed, not the
# lag check. With props live again, the freshness checks (props-lag, propsLive.asOf)
# are re-armed under this flag instead of the dead StatsAPI one.
PROPS_ENABLED = True

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

# Group stage complete but no knockout bracket built: the 28 Jun 2026 failure, where
# the bracket build aborted on a half-published feed and the swallowed (continue-on-
# error) step left the Matches/Bracket tabs empty for hours behind a green check. This
# is a hard fail so a recurrence turns the run red and fires the phone alert instead of
# hiding. Self-clears the moment the bracket is built (32 knockout matches appear).
group_matches = [m for m in data.get("matches", []) if m.get("stage") == "group"]
groups_done = group_matches and all(m.get("status") == "completed" and m.get("score") for m in group_matches)
ko_count = len([m for m in data.get("matches", []) if m.get("stage") and m.get("stage") != "group"])
if groups_done and ko_count == 0:
    fails.append("group stage is complete but the knockout bracket has not been built "
                 "(0 knockout matches in the data) — the Matches and Bracket tabs are empty. "
                 "Run scripts/generate_knockout.py --from-feed.")

if pl is None:
    fails.append("propsLive block is missing entirely")
else:
    counted = pl.get("matchesCounted", 0)
    lag = ncomp - counted
    # Freshness checks are armed whenever the props race is being fed (now ESPN).
    if PROPS_ENABLED and lag > PROPS_LAG_TOLERANCE:
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
    if PROPS_ENABLED and meta_asof and pl.get("asOf") and pl["asOf"] < meta_asof:
        warns.append(f"propsLive.asOf ({pl['asOf']}) is behind meta.asOf ({meta_asof})")

if STATSAPI_ENABLED:
    missing_xg = [m for m in completed if not m.get("xg")]
    if missing_xg:
        warns.append(f"{len(missing_xg)} completed match(es) still lack xG (usually fills within ~15 min)")

# xG is now sourced from ESPN's free core API (fetch_xg.py, replacing the dropped
# StatsAPI feed) and retried every auto-update cycle. This is a WARN, never a hard
# FAIL: ESPN occasionally never publishes a given match's xG (e.g. TUR-PAR, 19 Jun),
# and a hard fail would alarm forever on a gap we cannot fill. The WARN surfaces any
# standing gap in the run log without crying wolf; transient lags self-heal on retry.
XG_ENABLED = True
if XG_ENABLED:
    missing_xg = [f"{m['team1']}-{m['team2']}" for m in completed if not m.get("xg")]
    if missing_xg:
        warns.append(f"{len(missing_xg)} completed match(es) lack xG from ESPN "
                     f"(retried each cycle; some are permanent source gaps): {', '.join(missing_xg)}")

for w in warns: print("WARN:", w)
for f in fails: print("FAIL:", f)

if fails:
    print(f"\nwatchdog: FAILED ({len(fails)} hard issue(s), {len(warns)} warning(s)) — "
          f"{ncomp} matches played.")
    sys.exit(1)
print(f"watchdog: OK ({ncomp} matches played, props counts {pl.get('matchesCounted') if pl else 'n/a'}; "
      f"{len(warns)} warning(s)).")
