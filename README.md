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

## Update routine (after results)

1. Patch scores into `src/data.js` (`status: "completed"`, `score: {team1, team2}`)
   and bump `meta.asOf`.
2. `node update.js --date YYYY-MM-DD` — recomputes the model, appends the timeline snapshot.
3. `python3 build.py` — rebuilds `index.html`.
4. Commit and push; GitHub Pages refreshes for everyone.

Viewers can also enter results or run what-ifs in the page itself; those apply locally in
their browser only.

## Honesty notes

No fabricated data: head-to-head blurbs, weather, and cosmetic simulation counters from
the source projects were dropped. The "model xG" figures are rating-derived, not shot
data, and are labelled as such. The 11 June timeline baseline is an external blend
(market plus rating models) and is labelled as such; every later point is this engine.
Model estimates, not betting advice. Unofficial and unaffiliated with FIFA.
