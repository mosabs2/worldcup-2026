#!/usr/bin/env node
// Emit the league board's current rank per (non-exhibition) entry, as JSON
// {entry name: rank}. This MIRRORS ui.js leagueStandings() exactly — the same
// sort (resolved pts, then provisional pts, then expected pts) using the SAME
// engine the board runs — so the server-computed movement arrows match what the
// board displays, and they move as often as the live model does (the expected-
// points term shifts with every model recompute, which is what made the arrows
// feel "live"). Run from anywhere; paths are resolved against this file.
//
// Keep in sync with src/ui.js leagueStandings() if the league scoring changes.
const path = require('path');
const { WC_DATA } = require(path.join(__dirname, '..', 'src', 'data.js'));
const E = require(path.join(__dirname, '..', 'src', 'engine.js'));

const D = WC_DATA;
const sc = D.league.scoring;
const T = Object.fromEntries(D.teams.map(t => [t.code, t]));
const GROUPS = [...new Set(D.teams.map(t => t.group).filter(Boolean))].sort();

const sim = E.simulateTournament(D, { runs: 10000 });
const resolved = E.resolvedOutcomes(D);
const prov = E.provisionalOutcomes(D);
const P = c => (sim.teams[c] || {});

const rows = (D.league.entries || []).map(e => {
  let pts = 0, exp = 0;
  GROUPS.forEach(g => {
    const pick = e.w && e.w[g];
    if (!pick || !T[pick]) return;
    const win = resolved.groupWinners[g];
    if (win) { const hit = win === pick ? sc.groupWinner : 0; pts += hit; exp += hit; }
    else { exp += (P(pick).groupWin || 0) * sc.groupWinner; }
  });
  (e.f || []).forEach(fc => {
    if (!T[fc]) return;
    if (resolved.finalists) { const hit = resolved.finalists.includes(fc) ? sc.finalist : 0; pts += hit; exp += hit; }
    else { exp += (P(fc).fin || 0) * sc.finalist; }
  });
  if (e.c && T[e.c]) {
    if (resolved.champion) { const hit = resolved.champion === e.c ? sc.champion : 0; pts += hit; exp += hit; }
    else { exp += (P(e.c).champ || 0) * sc.champion; }
  }
  const provPts = E.scoreEntry(e, prov, sc).pts;
  return { n: e.n, exhibition: !!e.exhibition, pts, exp, prov: provPts };
}).sort((a, b) => b.pts - a.pts || b.prov - a.prov || b.exp - a.exp);

const ranks = {};
let rk = 0;
rows.forEach(r => { if (!r.exhibition) { rk++; ranks[r.n] = rk; } });
process.stdout.write(JSON.stringify(ranks));
