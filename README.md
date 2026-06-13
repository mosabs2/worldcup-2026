# World Cup 2026 — Probability Centre

A single-file World Cup 2026 dashboard: match-winner odds, group projections, knockout
bracket, and title probabilities from a 10,000-run Monte Carlo simulation, in the MAS
brand. Live at https://mosabs2.github.io/worldcup-2026/

Amalgamated on 12 June 2026 from two earlier projects (the Forecast Lab v1-v4 lineage and
the Prestige Analytics site), keeping the Lab's engine and the best features of both.

## Architecture

- `index.html` — the built site, fully self-contained (open it anywhere, no server).
- `src/data.js` — teams, fixtures, venues, results. The only file touched on a results update.
- `src/engine.js` — the model: live-updating Elo (K=40, margin-weighted), logistic match
  odds, Poisson goals, full-tournament Monte Carlo with extra time and penalties.
  Runs in the browser and in Node.
- `src/ui.js`, `src/style.css`, `src/shell.html` — interface.
- `src/history.json` — published snapshots of title probabilities (the Timeline tab).

## How results flow in

**Automatic (primary).** `.github/workflows/auto-update.yml` runs every two hours during
the North American match window (16:00-06:00 UTC only; matches kick off 16:00-03:00 UTC,
so nothing runs in the quiet hours). It calls `scripts/fetch_scores.py`, which pulls
completed matches from ESPN's open JSON feed, validates them against the fixture list
(known matches only, full-time only, sane scores only), patches `src/data.js`, re-runs
the model, rebuilds, and pushes. No key, no cost; if the feed is unreachable or returns
nothing new, the run is a no-op.

**In-page refresh.** The "(refresh) Scores" button pulls the same feed in the visitor's
browser (it is CORS-open) and applies new finals as a local overlay with a full recompute.
Local to that browser; the published build catches up on the next workflow run.

**Manual (fallback).** Patch scores into `src/data.js`, then
`node update.js --date YYYY-MM-DD && python3 build.py`, commit and push. This is the
editorial path if the ESPN feed changes shape mid-tournament.

## The knockout transition (early July)

The data ships only the 72 group matches plus `r32Template` (the official R32 pairings,
in bracket order, FIFA match numbers 73-88). `scripts/generate_knockout.py` builds the
remaining 32 knockout fixtures (R32 with real teams, then R16/QF/SF/3rd/Final as a routed
skeleton) and resolves each round's teams from completed results. The R32 to Final routing
is the sequential pairing of `r32Template`, the same routing `engine.js` uses and the one
`meta.bracketNote` records as verified against the published schedule.

It runs automatically: the workflow calls it (`--from-feed`) after each score sync, so it
no-ops until the group stage finishes, then builds the bracket (reading the official
third-place assignment from the ESPN feed, since the allow-lists alone do not determine it
— all 495 qualifying combinations are ambiguous) and fills knockout teams as rounds
complete. It never overwrites a recorded score and is safe to run repeatedly.

Manual options if the feed lags the draw: supply the official third assignment directly,
`python3 scripts/generate_knockout.py --thirds '{"R32-3":"CRO", ...}'` (validated against
each slot's allow-list and the qualifying thirds), or `--force` to build a teams-TBD
skeleton, or `--selftest` to exercise the whole machinery on simulated results without
writing. Per-match venues and dates for R16 and later are nominal (`scheduleApprox: true`)
until confirmed against FIFA's published bracket.

## Honesty notes

No fabricated data: head-to-head blurbs, weather, and cosmetic simulation counters from
the source projects were dropped. The "model xG" figures are rating-derived, not shot
data, and are labelled as such. The 11 June timeline baseline is an external blend
(market plus rating models) and is labelled as such; every later point is this engine.
Model estimates, not betting advice. Unofficial and unaffiliated with FIFA.
