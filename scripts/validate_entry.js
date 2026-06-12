#!/usr/bin/env node
// Bake-side gate: validate a league code (or all baked entries) against the
// same rules the picks form enforces. Usage:
//   node scripts/validate_entry.js <code>      validate one WhatsApp code
//   node scripts/validate_entry.js --baked     re-validate every published entry
const path = require('path');
const { WC_DATA } = require(path.join(__dirname, '..', 'src', 'data.js'));
const E = require(path.join(__dirname, '..', 'src', 'engine.js'));

const teams = {}; WC_DATA.teams.forEach(t => teams[t.code] = t);

function verdict(e) {
  const problems = [];
  const w = e.w || {};
  const groups = [...new Set(WC_DATA.teams.map(t => t.group))].sort();
  if (Object.keys(w).length !== 12) problems.push('needs 12 group winners');
  for (const g of groups) {
    if (!w[g] || !teams[w[g]] || teams[w[g]].group !== g) problems.push(`group ${g} pick invalid`);
  }
  const f = e.f || [];
  if (f.length !== 2 || f[0] === f[1] || !teams[f[0]] || !teams[f[1]]) problems.push('finalists invalid');
  if (!e.c || !teams[e.c]) problems.push('champion invalid');
  else if (e.c !== f[0] && e.c !== f[1]) problems.push('champion is not one of the finalists');
  const fz = E.finalFeasible(e, WC_DATA);
  if (!fz.ok) problems.push(`finalists ${f.join(' and ')} cannot meet in the final on this entry's own group picks (halves ${JSON.stringify(fz.h1)} vs ${JSON.stringify(fz.h2)})`);
  return problems;
}

const arg = process.argv[2];
if (!arg) { console.error('pass a code or --baked'); process.exit(1); }
const entries = arg === '--baked'
  ? WC_DATA.league.entries
  : [JSON.parse(Buffer.from(arg.trim(), 'base64').toString('utf8'))];
let bad = 0;
for (const e of entries) {
  const p = verdict(e);
  console.log(`${e.n}: ${p.length ? 'REJECT — ' + p.join('; ') : 'VALID'}`);
  if (p.length) bad++;
}
process.exit(bad ? 2 : 0);
