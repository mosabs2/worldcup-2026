// World Cup 2026 probability engine.
// Runs in the browser (page recompute, what-if mode) and in Node (update.js snapshots).
// One model end to end: live-updated Elo ratings -> logistic match odds -> Poisson goals
// -> full-tournament Monte Carlo (group stage, R32..Final, extra time, penalties).

(function (root, factory) {
  if (typeof module !== 'undefined') module.exports = factory();
  else root.ENGINE = factory();
})(typeof self !== 'undefined' ? self : this, function () {

  // Deterministic PRNG (mulberry32) so the published numbers are stable run-to-run
  // and what-if deltas are not simulation noise.
  function rngFactory(seed) {
    let a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  const HOSTS = { MEX: 1, USA: 1, CAN: 1 };
  const HOST_BONUS = 55;          // rating points when a host plays in its own country
  const ELO_K = 40;               // World Cup K-factor (World Football Elo convention)
  const LOGISTIC_DIV = 420;       // inherited calibration from the v4 lab
  const ET_LAMBDA_SCALE = 1 / 3;  // 30 min of extra time vs 90 min
  const XG_TEMPER = 0.6;          // weight on the xG margin (vs scoreline) when tempering
                                  // Elo updates. A 7-1 worth only ~3.9 xG should not move
                                  // ratings like a true 6-goal rout. The winner is still the
                                  // winner (result unchanged); only the margin is tempered.

  function marginMult(gd) {       // World Football Elo goal-difference multiplier
    if (gd <= 1) return 1;
    if (gd === 2) return 1.5;
    return (11 + gd) / 8;
  }

  // Effective goal difference for the Elo margin multiplier: blend the actual
  // scoreline GD with the xG GD when per-team xG is available, so flattering
  // blowouts (and undeserved narrow wins) update ratings by what was created,
  // not just what was scored. Falls back to the raw scoreline when no xG.
  function effectiveGD(g1, g2, xg) {
    const actual = Math.abs(g1 - g2);
    if (!xg || xg.team1 == null || xg.team2 == null) return actual;
    const xgd = Math.abs(xg.team1 - xg.team2);
    return Math.max(1, Math.round((1 - XG_TEMPER) * actual + XG_TEMPER * xgd));
  }

  // --- Ratings: base + Elo updates from every completed match, in date order ---
  function liveRatings(data, extraResults) {
    const r = {}, delta = {};
    data.teams.forEach(t => { r[t.code] = t.baseRating; delta[t.code] = 0; });
    const done = data.matches
      .filter(m => m.status === 'completed' && m.score)
      .map(m => ({ ...m }))
      .concat(extraResults || [])
      .sort((a, b) => (a.dateET || '').localeCompare(b.dateET || ''));
    const venueCountry = {};
    data.venues.forEach(v => { venueCountry[v.id] = v.country; });
    for (const m of done) {
      const ra = r[m.team1], rb = r[m.team2];
      if (ra == null || rb == null) continue;
      const ha = hostEdge(m.team1, m.venueId, venueCountry);
      const hb = hostEdge(m.team2, m.venueId, venueCountry);
      const exp = 1 / (1 + Math.pow(10, -((ra + ha) - (rb + hb)) / LOGISTIC_DIV));
      const g1 = m.score.team1, g2 = m.score.team2;
      const w = g1 > g2 ? 1 : g1 < g2 ? 0 : 0.5;
      const ch = ELO_K * marginMult(effectiveGD(g1, g2, m.xg)) * (w - exp);
      r[m.team1] += ch; r[m.team2] -= ch;
      delta[m.team1] += ch; delta[m.team2] -= ch;
    }
    return { ratings: r, delta };
  }

  function hostEdge(code, venueId, venueCountry) {
    if (!HOSTS[code] || !venueId) return 0;
    const c = venueCountry[venueId] || '';
    const map = { MEX: 'Mexico', USA: 'United States', CAN: 'Canada' };
    return c === map[code] ? HOST_BONUS : 0;
  }

  // --- Single-match model ---
  function predict(ra, rb) {
    const diff = ra - rb;
    const pAwin = 1 / (1 + Math.pow(10, -diff / LOGISTIC_DIV));
    const draw = Math.max(0.17, Math.min(0.30, 0.27 - Math.abs(diff) / 2600));
    const p1 = (1 - draw) * pAwin, p2 = (1 - draw) * (1 - pAwin);
    const xg1 = clamp(1.22 + diff / 780, 0.35, 2.65);
    const xg2 = clamp(1.22 - diff / 780, 0.35, 2.65);
    return { p1, draw, p2, xg1, xg2 };
  }
  function clamp(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }

  function poissonPmf(k, lambda) {
    let f = 1; for (let i = 2; i <= k; i++) f *= i;
    return Math.pow(lambda, k) * Math.exp(-lambda) / f;
  }
  function topScorelines(xg1, xg2, n) {
    const out = [];
    for (let a = 0; a <= 5; a++) for (let b = 0; b <= 5; b++)
      out.push({ s: a + '-' + b, a, b, p: poissonPmf(a, xg1) * poissonPmf(b, xg2) });
    out.sort((x, y) => y.p - x.p);
    return out.slice(0, n || 5);
  }
  function sampleGoals(lambda, rng) {
    const L = Math.exp(-lambda); let k = 0, p = 1;
    do { k++; p *= rng(); } while (p > L);
    return k - 1;
  }

  // --- Full tournament Monte Carlo ---
  // overrides: {matchId: {team1: g, team2: g}} hypothetical/actual results (what-if mode).
  // koActuals: completed knockout matches [{round, team1, team2, winner}] pin the bracket.
  function simulateTournament(data, opts) {
    const o = opts || {};
    const N = o.runs || 10000;
    const rng = rngFactory(o.seed != null ? o.seed : 20260612);
    const overrides = o.overrides || {};
    const koActuals = indexKoActuals(o.koActuals || []);
    // completed knockout matches in the data pin the bracket in every run
    for (const m of data.matches) {
      if (m.stage === 'group' || m.status !== 'completed' || !m.score) continue;
      const w = m.score.winner ||
        (m.score.team1 > m.score.team2 ? m.team1 : m.score.team2 > m.score.team1 ? m.team2 : null);
      if (w) koActuals[pairKey(m.team1, m.team2)] = w;
    }
    const venueCountry = {};
    data.venues.forEach(v => { venueCountry[v.id] = v.country; });
    const { ratings } = liveRatings(data, o.extraResults);
    if (o.shocks) for (const c in o.shocks) ratings[c] = (ratings[c] || 1500) + o.shocks[c];

    const codes = data.teams.map(t => t.code);
    const groupOf = {}; data.teams.forEach(t => { groupOf[t.code] = t.group; });
    const groups = {};
    data.teams.forEach(t => { (groups[t.group] = groups[t.group] || []).push(t.code); });
    const groupNames = Object.keys(groups).sort();

    // Pre-split matches: fixed (completed or overridden) vs to-sample
    const fixed = [], open = [];
    for (const m of data.matches) {
      if (m.stage !== 'group') continue;
      const ov = overrides[m.id];
      if (ov) fixed.push({ m, g1: ov.team1, g2: ov.team2 });
      else if (m.status === 'completed' && m.score) fixed.push({ m, g1: m.score.team1, g2: m.score.team2 });
      else open.push(m);
    }
    // Pre-compute lambdas for open matches once (ratings fixed across sims)
    const openPre = open.map(m => {
      const ra = ratings[m.team1] + hostEdge(m.team1, m.venueId, venueCountry);
      const rb = ratings[m.team2] + hostEdge(m.team2, m.venueId, venueCountry);
      const p = predict(ra, rb);
      return { m, xg1: p.xg1, xg2: p.xg2 };
    });

    const tally = {}; // per team: stage reach counts
    codes.forEach(c => { tally[c] = { r32: 0, r16: 0, qf: 0, sf: 0, fin: 0, champ: 0, pts: 0, win: 0, top2: 0, third: 0 }; });

    for (let run = 0; run < N; run++) {
      // group stage
      const st = {};
      codes.forEach(c => { st[c] = { pts: 0, gd: 0, gf: 0 }; });
      const apply = (t1, t2, g1, g2) => {
        st[t1].gf += g1; st[t1].gd += g1 - g2;
        st[t2].gf += g2; st[t2].gd += g2 - g1;
        if (g1 > g2) st[t1].pts += 3; else if (g2 > g1) st[t2].pts += 3;
        else { st[t1].pts++; st[t2].pts++; }
      };
      for (const f of fixed) apply(f.m.team1, f.m.team2, f.g1, f.g2);
      for (const p of openPre) apply(p.m.team1, p.m.team2, sampleGoals(p.xg1, rng), sampleGoals(p.xg2, rng));

      const rank = {};   // group -> ordered codes
      const thirds = [];
      for (const g of groupNames) {
        const order = groups[g].slice().sort((a, b) =>
          st[b].pts - st[a].pts || st[b].gd - st[a].gd || st[b].gf - st[a].gf || rng() - 0.5);
        rank[g] = order;
        tally[order[0]].win++; tally[order[0]].top2++; tally[order[1]].top2++;
        thirds.push(order[2]);
        groups[g].forEach(c => { tally[c].pts += st[c].pts; });
      }
      thirds.sort((a, b) =>
        st[b].pts - st[a].pts || st[b].gd - st[a].gd || st[b].gf - st[a].gf || rng() - 0.5);
      const qualThirds = thirds.slice(0, 8);
      qualThirds.forEach(c => tally[c].third++);

      // R32 from template; thirds assigned greedily avoiding same-group pairings
      const pool = qualThirds.slice();
      const r32 = [];
      for (const slot of data.r32Template) {
        const a = slot.a.type === 'group' ? rank[slot.a.group][slot.a.place - 1] : takeThird(pool, rank, slot, rng);
        const b = slot.b.type === 'group' ? rank[slot.b.group][slot.b.place - 1] : takeThird(pool, rank, slot, rng);
        r32.push([a, b]);
      }
      r32.flat().forEach(c => tally[c].r32++);

      // knockout rounds: winners of each round are re-paired sequentially.
      // 16 pairs -> winners reach R16 -> ... -> 2 -> finalists -> 1 -> champion.
      let pairs = r32;
      const stages = ['r16', 'qf', 'sf', 'fin', 'champ'];
      let si = 0;
      while (pairs.length >= 1) {
        const winners = pairs.map(p => koWin(p[0], p[1], ratings, rng, koActuals));
        const stage = stages[si++];
        winners.forEach(c => tally[c][stage]++);
        if (stage === 'champ') break;
        pairs = [];
        for (let i = 0; i < winners.length; i += 2) pairs.push([winners[i], winners[i + 1]]);
      }
    }

    // assemble results
    const teams = {};
    for (const c of codes) {
      const t = tally[c];
      teams[c] = {
        champ: t.champ / N, fin: t.fin / N, sf: t.sf / N, qf: t.qf / N,
        r16: t.r16 / N, r32: t.r32 / N,
        groupWin: t.win / N, top2: t.top2 / N, thirdQual: t.third / N,
        xPts: t.pts / N,
        band: 1.96 * Math.sqrt(Math.max(t.champ / N * (1 - t.champ / N), 1e-9) / N),
      };
    }
    return { teams, runs: N, ratings };
  }

  function takeThird(pool, rank, slot, rng) {
    // honour the slot's allowed-groups list where possible, and avoid same-group pairings
    const side = slot.a.type === 'third' ? slot.a : slot.b;
    const grpOf = c => Object.keys(rank).find(g => rank[g].includes(c));
    const opp = slot.a.type === 'group' ? rank[slot.a.group][slot.a.place - 1] : null;
    const oppGroup = opp ? grpOf(opp) : null;
    let idx = pool.findIndex(c => (!side.groups || side.groups.indexOf(grpOf(c)) !== -1) && grpOf(c) !== oppGroup);
    if (idx === -1) idx = pool.findIndex(c => grpOf(c) !== oppGroup);
    if (idx === -1) idx = 0;
    return pool.splice(idx, 1)[0];
  }

  // --- bracket-half feasibility for league entries ---
  // Which halves of the official bracket (0 = top, feeds SF1; 1 = bottom, feeds SF2)
  // a team can occupy, given the entry's own twelve group-winner picks.
  function entryHalves(code, entry, data) {
    const team = data.teams.find(t => t.code === code);
    if (!team) return [];
    const g = team.group;
    const pickedWinner = entry.w && entry.w[g] === code;
    const halves = new Set();
    data.r32Template.forEach((slot, i) => {
      const half = i < 8 ? 0 : 1;
      [slot.a, slot.b].forEach(sd => {
        if (sd.type === 'group' && sd.group === g) {
          if (sd.place === 1 && pickedWinner) halves.add(half);
          if (sd.place === 2 && !pickedWinner) halves.add(half);
        } else if (sd.type === 'third' && !pickedWinner) {
          if (!sd.groups || sd.groups.indexOf(g) !== -1) halves.add(half);
        }
      });
    });
    return Array.from(halves);
  }

  // Can this entry's two finalists actually meet in the final?
  function finalFeasible(entry, data) {
    const f = entry.f || [];
    if (f.length !== 2 || f[0] === f[1]) return { ok: false, h1: [], h2: [] };
    const h1 = entryHalves(f[0], entry, data);
    const h2 = entryHalves(f[1], entry, data);
    const ok = h1.some(a => h2.some(b => a !== b));
    return { ok, h1, h2 };
  }

  function indexKoActuals(list) {
    const map = {};
    for (const a of list) map[pairKey(a.team1, a.team2)] = a.winner;
    return map;
  }
  function pairKey(a, b) { return a < b ? a + '|' + b : b + '|' + a; }

  function koWin(a, b, ratings, rng, koActuals, fieldSize) {
    const pinned = koActuals[pairKey(a, b)];
    if (pinned) return pinned;
    const p = predict(ratings[a], ratings[b]);
    let g1 = sampleGoals(p.xg1, rng), g2 = sampleGoals(p.xg2, rng);
    if (g1 !== g2) return g1 > g2 ? a : b;
    g1 = sampleGoals(p.xg1 * ET_LAMBDA_SCALE, rng); g2 = sampleGoals(p.xg2 * ET_LAMBDA_SCALE, rng);
    if (g1 !== g2) return g1 > g2 ? a : b;
    // penalties: slight tilt to the stronger side
    const tilt = clamp(0.5 + (ratings[a] - ratings[b]) / 4000, 0.35, 0.65);
    return rng() < tilt ? a : b;
  }

  // --- Current group tables from actual results ---
  function currentTables(data, overrides) {
    const st = {};
    data.teams.forEach(t => { st[t.code] = { P: 0, W: 0, D: 0, L: 0, GF: 0, GA: 0, Pts: 0 }; });
    for (const m of data.matches) {
      if (m.stage !== 'group') continue;
      const ov = overrides && overrides[m.id];
      const sc = ov || (m.status === 'completed' ? m.score : null);
      if (!sc) continue;
      const a = st[m.team1], b = st[m.team2];
      a.P++; b.P++; a.GF += sc.team1; a.GA += sc.team2; b.GF += sc.team2; b.GA += sc.team1;
      if (sc.team1 > sc.team2) { a.W++; b.L++; a.Pts += 3; }
      else if (sc.team2 > sc.team1) { b.W++; a.L++; b.Pts += 3; }
      else { a.D++; b.D++; a.Pts++; b.Pts++; }
    }
    const groups = {};
    data.teams.forEach(t => { (groups[t.group] = groups[t.group] || []).push(t.code); });
    const out = {};
    for (const g in groups) {
      out[g] = groups[g].slice().sort((x, y) =>
        st[y].Pts - st[x].Pts || (st[y].GF - st[y].GA) - (st[x].GF - st[x].GA) || st[y].GF - st[x].GF)
        .map(c => ({ team: c, ...st[c], GD: st[c].GF - st[c].GA }));
    }
    return out;
  }

  // --- Predictions-league scoring ---
  // entry: {n: name, w: {A:'MEX',...}, f: ['ESP','ARG'], c: 'ESP'}
  function scoreEntry(entry, resolved, scoring) {
    let pts = 0; const detail = [];
    for (const g in (entry.w || {})) {
      if (resolved.groupWinners[g]) {
        const hit = resolved.groupWinners[g] === entry.w[g];
        if (hit) pts += scoring.groupWinner;
        detail.push({ what: 'Group ' + g, pick: entry.w[g], actual: resolved.groupWinners[g], pts: hit ? scoring.groupWinner : 0 });
      }
    }
    if (resolved.finalists) {
      for (const f of (entry.f || [])) {
        const hit = resolved.finalists.includes(f);
        if (hit) pts += scoring.finalist;
        detail.push({ what: 'Finalist', pick: f, actual: resolved.finalists.join('/'), pts: hit ? scoring.finalist : 0 });
      }
    }
    if (resolved.champion) {
      const hit = resolved.champion === entry.c;
      if (hit) pts += scoring.champion;
      detail.push({ what: 'Champion', pick: entry.c, actual: resolved.champion, pts: hit ? scoring.champion : 0 });
    }
    return { pts, detail };
  }

  // which group winners are mathematically resolved (all 6 matches played)
  function resolvedOutcomes(data, overrides) {
    const tables = currentTables(data, overrides);
    const played = {};
    for (const m of data.matches) {
      if (m.stage !== 'group') continue;
      const done = (overrides && overrides[m.id]) || (m.status === 'completed' && m.score);
      played[m.group] = (played[m.group] || 0) + (done ? 1 : 0);
    }
    const groupWinners = {};
    for (const g in tables) if (played[g] === 6) groupWinners[g] = tables[g][0].team;
    // finalists and champion resolve from completed knockout rounds
    const winOf = m => m.score.winner ||
      (m.score.team1 > m.score.team2 ? m.team1 : m.score.team2 > m.score.team1 ? m.team2 : null);
    const done = data.matches.filter(m => m.stage !== 'group' && m.status === 'completed' && m.score);
    let finalists = null, champion = null;
    const fin = done.find(m => m.round === 'final');
    if (fin) { finalists = [fin.team1, fin.team2]; champion = winOf(fin); }
    else {
      const sfs = done.filter(m => m.round === 'sf');
      if (sfs.length === 2) finalists = sfs.map(winOf).filter(Boolean);
    }
    return { groupWinners, finalists, champion };
  }

  return {
    rngFactory, liveRatings, predict, topScorelines, poissonPmf, sampleGoals,
    simulateTournament, currentTables, scoreEntry, resolvedOutcomes, hostEdge,
    entryHalves, finalFeasible,
    LOGISTIC_DIV, ELO_K, HOST_BONUS,
  };
});
