#!/usr/bin/env node
// Update routine: recompute the model from current src/data.js and append/replace
// today's snapshot in src/history.json (the published probability timeline).
// Usage: node update.js --date 2026-06-12
// Then: python3 build.py && git commit/push.

const fs = require('fs');
const path = require('path');
const { WC_DATA } = require('./src/data.js');
const E = require('./src/engine.js');

const args = process.argv.slice(2);
const di = args.indexOf('--date');
if (di === -1 || !args[di + 1]) {
  console.error('Pass --date YYYY-MM-DD (verified against the workstation clock).');
  process.exit(1);
}
const date = args[di + 1];

const sim = E.simulateTournament(WC_DATA, { runs: 10000 });
const probs = {};
Object.entries(sim.teams)
  .sort((a, b) => b[1].champ - a[1].champ)
  .slice(0, 16)
  .forEach(([c, v]) => { probs[c] = +(v.champ * 100).toFixed(2); });

const hp = path.join(__dirname, 'src', 'history.json');
const hist = JSON.parse(fs.readFileSync(hp, 'utf8'));
const existing = hist.findIndex(h => h.date === date);
const completed = WC_DATA.matches.filter(m => m.status === 'completed').length;
const entry = { date, label: `Model v${WC_DATA.meta.version} · after ${completed} matches`, probs };
if (existing >= 0) hist[existing] = entry; else hist.push(entry);
fs.writeFileSync(hp, JSON.stringify(hist, null, 1));

console.log(`Snapshot ${date} written (${completed} matches completed).`);
console.log('Top 8:', Object.entries(probs).slice(0, 8).map(([c, p]) => `${c} ${p}%`).join('  '));
if (hist.length > 1) {
  const prev = hist[hist.length - 2].probs;
  const movers = Object.keys(probs)
    .map(c => ({ c, d: probs[c] - (prev[c] || 0) }))
    .sort((a, b) => Math.abs(b.d) - Math.abs(a.d)).slice(0, 5);
  console.log('Movers vs previous snapshot:', movers.map(m => `${m.c} ${m.d >= 0 ? '+' : ''}${m.d.toFixed(2)}`).join('  '));
}
