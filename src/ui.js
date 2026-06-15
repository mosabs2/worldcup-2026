// UI layer. Reads WC_DATA + WC_HISTORY (baked) and ENGINE (model).
(function () {
  const D = WC_DATA, E = ENGINE, H = (typeof WC_HISTORY !== 'undefined' ? WC_HISTORY : []);
  const T = {}; D.teams.forEach(t => T[t.code] = t);
  const V = {}; D.venues.forEach(v => V[v.id] = v);
  const VC = {}; D.venues.forEach(v => VC[v.id] = v.country);
  const KWT = 'Asia/Kuwait';
  const localTZ = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const GROUPS = [...new Set(D.teams.map(t => t.group))].sort();
  const PALETTE = ['#0E1E91', '#1C62B7', '#B3261E', '#1A7F4E', '#9A6B00', '#7B2D8E', '#0E7490', '#C2410C', '#5A5A5A', '#BE185D'];

  // ---------- state ----------
  const LS = { ov: 'wc26.overrides.v1', league: 'wc26.league.v1', tab: 'wc26.tab.v1' };
  let localOv = lsGet(LS.ov, {});
  let whatIf = { on: false, ov: {} };
  let leagueLocal = lsGet(LS.league, []);
  let SIM = null, RT = null, TABLES = null;
  let activeTab = lsGet(LS.tab, 'today');
  let teamSort = { key: 'champ', dir: -1 };

  function lsGet(k, fb) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : fb; } catch (e) { return fb; } }
  function lsSet(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }

  function activeOv() { return whatIf.on ? Object.assign({}, localOv, whatIf.ov) : localOv; }
  function effData() {
    const ov = activeOv();
    if (!Object.keys(ov).length) return D;
    return Object.assign({}, D, {
      matches: D.matches.map(m => ov[m.id]
        ? Object.assign({}, m, { status: 'completed', score: { team1: ov[m.id][0], team2: ov[m.id][1], winner: ov[m.id][2] } })
        : m),
    });
  }

  // drop local overrides once the published data carries the same match as completed
  (function pruneOverrides() {
    let changed = false;
    for (const id in localOv) {
      const m = D.matches.find(x => x.id === id);
      if (m && m.status === 'completed') { delete localOv[id]; changed = true; }
    }
    if (changed) lsSet(LS.ov, localOv);
  })();

  function recompute() {
    const data = effData();
    SIM = E.simulateTournament(data, { runs: 10000 });
    RT = E.liveRatings(data);
    TABLES = E.currentTables(data);
  }

  // ---------- helpers ----------
  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    if (attrs) for (const k in attrs) {
      if (k === 'class') n.className = attrs[k];
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), attrs[k]);
      else if (k === 'html') n.innerHTML = attrs[k];
      else n.setAttribute(k, attrs[k]);
    }
    for (const k of kids.flat()) if (k != null) n.append(k.nodeType ? k : document.createTextNode(k));
    return n;
  }
  const pct = (x, dp) => (x * 100).toFixed(dp == null ? 1 : dp) + '%';
  function fmtT(iso, tz) { return new Intl.DateTimeFormat('en-GB', { timeZone: tz, hour: '2-digit', minute: '2-digit' }).format(new Date(iso)); }
  function fmtD(iso, tz) { return new Intl.DateTimeFormat('en-GB', { timeZone: tz, weekday: 'short', day: 'numeric', month: 'short' }).format(new Date(iso)); }
  const todayKWT = () => new Intl.DateTimeFormat('en-CA', { timeZone: KWT }).format(new Date());
  // Card kickoff: the visitor's local time, with Kuwait time in parentheses for non-Kuwait visitors.
  function kt(iso) {
    const loc = fmtT(iso, localTZ);
    return localTZ === KWT ? loc + ' Kuwait' : loc + ' (' + fmtT(iso, KWT) + ' KWT)';
  }
  function dayLocal(iso) { return new Intl.DateTimeFormat('en-CA', { timeZone: localTZ }).format(new Date(iso)); }
  const todayLocal = () => new Intl.DateTimeFormat('en-CA', { timeZone: localTZ }).format(new Date());
  // Whole-site kickoff: visitor-local day and time, with Kuwait time appended (in parentheses for non-Kuwait visitors).
  function kickoff(m) {
    return fmtD(m.dateET, localTZ) + ' · ' + kt(m.dateET);
  }
  function odds(m) {
    const ra = RT.ratings[m.team1] + E.hostEdge(m.team1, m.venueId, VC);
    const rb = RT.ratings[m.team2] + E.hostEdge(m.team2, m.venueId, VC);
    return E.predict(ra, rb);
  }
  function effScore(m) {
    const ov = activeOv()[m.id];
    if (ov) return { team1: ov[0], team2: ov[1], local: true };
    return m.status === 'completed' && m.score ? m.score : null;
  }
  function flagName(c, bold) {
    const t = T[c];
    return el('span', { class: 'teamcell' }, el('span', { class: 'fl' }, t.flag), el('span', { class: 'nm', title: t.name }, t.name));
  }

  function pbarRow(p) {
    return el('div', null,
      el('div', { class: 'pbar' },
        el('div', { class: 'p1', style: 'width:' + p.p1 * 100 + '%' }),
        el('div', { class: 'pd', style: 'width:' + p.draw * 100 + '%' }),
        el('div', { class: 'p2', style: 'width:' + p.p2 * 100 + '%' })),
      el('div', { class: 'plabels' }, el('span', null, pct(p.p1)), el('span', null, 'draw ' + pct(p.draw)), el('span', null, pct(p.p2))));
  }

  function matchCard(m, opts) {
    const sc = effScore(m);
    const live = !sc && liveNow[m.id];
    const p = odds(m);
    const tag = sc ? el('span', { class: 'tag ' + (sc.local ? 'whatif' : 'ft') }, sc.local ? (whatIf.on ? 'what-if' : 'local') : 'FT')
                   : live ? el('span', { class: 'tag live' }, 'LIVE ' + (live.clock || ''))
                   : el('span', { class: 'tag up' }, 'upcoming');
    const card = el('div', { class: 'card match click', onclick: () => matchModal(m) },
      el('div', { class: 'row' },
        el('div', { class: 'team' }, el('span', { class: 'fl' }, T[m.team1].flag), T[m.team1].name),
        sc ? el('div', { class: 'score' }, sc.team1 + ' – ' + sc.team2)
           : live ? el('div', { class: 'score' }, live.g1 + ' – ' + live.g2)
           : el('div', { class: 'vs' }, 'v'),
        el('div', { class: 'team away' }, T[m.team2].name, el('span', { class: 'fl' }, T[m.team2].flag))),
      (sc && m.xg) ? el('div', { class: 'xg-line' }, el('span', { class: 'lab' }, 'xG '), m.xg.team1.toFixed(2) + ' – ' + m.xg.team2.toFixed(2)) : null,
      (sc || live) ? null : pbarRow(p),
      el('div', { class: 'meta' }, tag,
        el('span', null, 'Group ' + m.group),
        el('span', null, V[m.venueId].city),
        (!opts || opts.times !== false) ? el('span', null, sc ? fmtD(m.dateET, localTZ) : kt(m.dateET)) : null));
    return card;
  }

  // ---------- modals ----------
  function openModal(...kids) {
    closeModal();
    const bg = el('div', { class: 'modal-bg', onclick: e => { if (e.target === bg) closeModal(); } },
      el('div', { class: 'modal' }, el('button', { class: 'close', onclick: closeModal }, '×'), ...kids));
    document.body.append(bg);
  }
  function closeModal() { document.querySelectorAll('.modal-bg').forEach(n => n.remove()); }

  // Plain-language read of actual xG against the scoreline (played games).
  function xgRead(m, sc) {
    const x1 = m.xg.team1, x2 = m.xg.team2, g1 = sc.team1, g2 = sc.team2;
    const c1 = T[m.team1].code, c2 = T[m.team2].code;
    const xgFav = x1 > x2 + 0.3 ? c1 : x2 > x1 + 0.3 ? c2 : null;
    const winner = g1 > g2 ? c1 : g2 > g1 ? c2 : null;
    if (winner && xgFav && winner !== xgFav)
      return 'The chances favoured ' + xgFav + ' (' + Math.max(x1, x2).toFixed(2) + ' xG); the scoreline flattered ' + winner + '.';
    if ((g1 - x1) >= 1.5 || (g2 - x2) >= 1.5) {
      const c = (g1 - x1) >= (g2 - x2) ? c1 : c2;
      const gg = c === c1 ? g1 : g2, xx = c === c1 ? x1 : x2;
      return c + ' scored ' + gg + ' from ' + xx.toFixed(2) + ' xG — clinical finishing on a flattering margin.';
    }
    return 'The scoreline broadly matched the chances created.';
  }

  function matchModal(m) {
    const p = odds(m);
    const sc = effScore(m);
    const tops = E.topScorelines(p.xg1, p.xg2, 5);
    const maxp = tops[0].p;
    const v = V[m.venueId];
    const s1 = el('input', { type: 'number', min: 0, max: 9, style: 'width:62px', value: sc ? sc.team1 : '' });
    const s2 = el('input', { type: 'number', min: 0, max: 9, style: 'width:62px', value: sc ? sc.team2 : '' });
    openModal(
      el('h2', null, T[m.team1].flag + ' ' + T[m.team1].name + (sc ? ' ' + sc.team1 + ' – ' + sc.team2 + ' ' : ' v ') + T[m.team2].name + ' ' + T[m.team2].flag),
      el('div', { class: 'muted', style: 'margin-bottom:14px' }, 'Group ' + m.group + ' · ' + v.name + ', ' + v.city + (v.elev > 800 ? ' (' + v.elev + ' m altitude)' : '') + ' · ' + kickoff(m)),
      el('h2', { class: 'section' }, sc ? 'Pre-result model read' : 'Model odds'),
      pbarRow(p),
      m.market ? el('p', { class: 'tiny', style: 'margin-top:8px' },
        el('b', null, 'Market line'), ' (' + (m.market.book || 'closing') + ', vig removed): ' +
        pct(m.market.h) + ' ' + T[m.team1].code + ' / ' + pct(m.market.x) + ' draw / ' + pct(m.market.a) + ' ' + T[m.team2].code +
        '. Shown for comparison; the model runs on its own ratings.') : null,
      m.xg ? el('h2', { class: 'section' }, 'Expected goals (xG) — from shot data') : null,
      m.xg ? (function () {
        const x1 = m.xg.team1, x2 = m.xg.team2, mx = Math.max(x1, x2, 0.1);
        const row = (code, goals, xg) => el('div', { class: 'frow' },
          el('span', { class: 'fl-label' }, T[code].flag + ' ' + T[code].name + (goals != null ? '  ·  ' + goals + ' scored' : '')),
          el('div', { class: 'hbar' }, el('div', { style: 'width:' + (xg / mx * 100) + '%' })),
          el('span', { class: 'num' }, xg.toFixed(2)));
        return el('div', { class: 'xg-block' }, row(m.team1, sc ? sc.team1 : null, x1), row(m.team2, sc ? sc.team2 : null, x2));
      })() : null,
      m.xg && sc ? el('p', { class: 'tiny', style: 'margin-top:6px' }, xgRead(m, sc)) : null,
      el('p', { class: 'tiny', style: 'margin-top:8px' },
        m.xg ? 'Model xG (rating-derived, for comparison): ' + p.xg1.toFixed(2) + ' – ' + p.xg2.toFixed(2)
             : 'Model xG (synthetic, derived from current Elo ratings, not shot data): ' + p.xg1.toFixed(2) + ' – ' + p.xg2.toFixed(2)),
      el('h2', { class: 'section' }, 'Most likely scorelines'),
      el('div', { class: 'funnel' }, tops.map(s => el('div', { class: 'frow' },
        el('span', { class: 'fl-label' }, s.s),
        el('div', { class: 'hbar' }, el('div', { style: 'width:' + (s.p / maxp * 100) + '%' })),
        el('span', { class: 'num' }, pct(s.p))))),
      el('h2', { class: 'section' }, whatIf.on ? 'Enter what-if result' : 'Enter result (local until published)'),
      el('div', { class: 'formrow' },
        el('span', null, T[m.team1].code), s1, el('span', null, '–'), s2, el('span', null, T[m.team2].code),
        m.stage !== 'group' ? (function () {
          const w = el('select', null,
            el('option', { value: '' }, 'pens: winner…'),
            el('option', { value: m.team1 }, T[m.team1].code), el('option', { value: m.team2 }, T[m.team2].code));
          w.id = 'koWinnerSel';
          return w;
        })() : null,
        el('button', {
          class: 'btn small', onclick: () => {
            const a = parseInt(s1.value, 10), b = parseInt(s2.value, 10);
            if (isNaN(a) || isNaN(b)) return;
            const wSel = document.getElementById('koWinnerSel');
            const entry = [a, b];
            if (m.stage !== 'group' && a === b) {
              if (!wSel || !wSel.value) { toast('Level knockout score: pick the shootout winner.'); return; }
              entry.push(wSel.value);
            }
            if (whatIf.on) whatIf.ov[m.id] = entry;
            else { localOv[m.id] = entry; lsSet(LS.ov, localOv); }
            closeModal(); refresh();
          }
        }, 'Apply'),
        activeOv()[m.id] ? el('button', {
          class: 'btn small ghost', onclick: () => {
            if (whatIf.on) delete whatIf.ov[m.id];
            if (!whatIf.on) { delete localOv[m.id]; lsSet(LS.ov, localOv); }
            closeModal(); refresh();
          }
        }, 'Clear') : null),
      el('p', { class: 'tiny' }, whatIf.on
        ? 'What-if mode is on: this result is hypothetical and every probability on the site will shift with it until you exit what-if.'
        : 'Applies on this device only and recomputes all probabilities. The published site updates when Mohammed runs the update routine.'));
  }

  function teamModal(code) {
    const t = T[code], s = SIM.teams[code];
    const stages = [
      ['Reach R32', s.r32], ['Reach R16', s.r16], ['Reach QF', s.qf],
      ['Reach SF', s.sf], ['Reach final', s.fin], ['Champion', s.champ]];
    const sched = D.matches.filter(m => m.team1 === code || m.team2 === code)
      .sort((a, b) => a.dateET.localeCompare(b.dateET));
    const d = RT.delta[code];
    openModal(
      el('h2', null, t.flag + ' ' + t.name),
      el('div', { class: 'muted', style: 'margin-bottom:12px' },
        'Group ' + t.group + ' · FIFA rank ' + t.fifaRank + ' · Elo ' + Math.round(RT.ratings[code]) +
        (Math.abs(d) >= 0.5 ? ' (' + (d > 0 ? '+' : '') + d.toFixed(0) + ' since matchday 1)' : '') +
        ' · ' + t.confed),
      el('h2', { class: 'section' }, 'Glory funnel — 10,000-run Monte Carlo'),
      el('div', { class: 'funnel' }, stages.map(([lbl, p]) => el('div', { class: 'frow' },
        el('span', { class: 'fl-label' }, lbl),
        el('div', { class: 'hbar' }, el('div', { style: 'width:' + Math.max(p * 100, 0.4) + '%' })),
        el('span', { class: 'num' }, pct(p))))),
      el('p', { class: 'tiny', style: 'margin-top:6px' },
        'Champion band: ' + pct(s.champ) + ' ± ' + pct(s.band) + ' (95% interval from simulation count). ' +
        (t.preProb ? 'Pre-tournament external blend had ' + t.preProb.toFixed(1) + '%.' : '')),
      el('h2', { class: 'section' }, 'Group fixtures'),
      el('div', { class: 'grid' }, sched.map(m => matchCard(m, { times: false }))));
  }

  // ---------- tabs ----------
  const tabs = [
    ['today', 'Today'], ['matches', 'Matches'], ['groups', 'Groups'], ['bracket', 'Bracket'],
    ['teams', 'Teams'], ['mena', 'MENA'], ['join', 'Join'], ['league', 'League'], ['compare', 'Compare'], ['timeline', 'Timeline'],
    ['venues', 'Venues'], ['model', 'Model & Updates'], ['about', 'About'], ['geeks', 'For Geeks']];

  function renderToday(root) {
    const today = todayLocal();
    const todays = D.matches.filter(m => dayLocal(m.dateET) === today).sort((a, b) => a.dateET.localeCompare(b.dateET));
    const done = D.matches.filter(m => effScore(m) && dayLocal(m.dateET) < today).sort((a, b) => b.dateET.localeCompare(a.dateET)).slice(0, 6);
    const next = D.matches.filter(m => !effScore(m) && dayLocal(m.dateET) > today).sort((a, b) => a.dateET.localeCompare(b.dateET));

    root.append(el('h2', { class: 'section' }, 'Today — ' + new Intl.DateTimeFormat('en-GB', { timeZone: localTZ, weekday: 'long', day: 'numeric', month: 'long' }).format(new Date())));
    if (todays.length) root.append(el('div', { class: 'grid g2' }, todays.map(m => matchCard(m))));
    else root.append(el('p', { class: 'muted' }, 'No matches today.'),
      el('h2', { class: 'section' }, 'Next matchday'),
      el('div', { class: 'grid g2' }, next.slice(0, 6).map(m => matchCard(m))));

    // title race
    const top = Object.entries(SIM.teams).sort((a, b) => b[1].champ - a[1].champ).slice(0, 8);
    root.append(el('h2', { class: 'section' }, 'Title race — live model'),
      el('div', { class: 'card' }, el('div', { class: 'funnel' }, top.map(([c, s]) => el('div', { class: 'frow' },
        el('span', { class: 'fl-label' }, T[c].flag + ' ' + T[c].name),
        el('div', { class: 'hbar' }, el('div', { style: 'width:' + (s.champ / top[0][1].champ * 100) + '%' })),
        el('span', { class: 'num' }, pct(s.champ)))))));

    if (done.length) root.append(el('h2', { class: 'section' }, 'Latest results'),
      el('div', { class: 'grid g2' }, done.map(m => matchCard(m))));

    // MENA strip
    const mena = D.mena.slice().sort((a, b) => SIM.teams[b].champ - SIM.teams[a].champ);
    root.append(el('h2', { class: 'section' }, 'MENA watch'),
      el('div', { class: 'mena-strip' }, mena.map(c => el('div', { class: 'mena-chip', onclick: () => teamModal(c) },
        el('span', null, T[c].flag), T[c].code,
        el('span', { class: 'pct' }, 'R32 ' + pct(SIM.teams[c].r32, 0))))));

    // Watchlist
    root.append(el('h2', { class: 'section' }, 'Player watch'),
      el('div', { class: 'grid g3' }, D.watchlist.map(w => {
        const nxt = D.matches.filter(m => !effScore(m) && (m.team1 === w.team || m.team2 === w.team))
          .sort((a, b) => a.dateET.localeCompare(b.dateET))[0];
        return el('div', { class: 'card' },
          el('h3', null, w.player, el('span', { class: 'right' }, w.note)),
          el('div', { class: 'teamcell', style: 'margin-bottom:6px' }, T[w.team].flag + ' ' + T[w.team].name),
          el('div', { class: 'muted' }, 'Title ' + pct(SIM.teams[w.team].champ) + ' · reach final ' + pct(SIM.teams[w.team].fin)),
          nxt ? el('div', { class: 'tiny', style: 'margin-top:6px' }, 'Next: v ' + T[nxt.team1 === w.team ? nxt.team2 : nxt.team1].name + ' · ' + kickoff(nxt)) : null);
      })));
  }

  function renderMatches(root) {
    const sel = el('select', { onchange: () => draw(sel.value) },
      el('option', { value: '' }, 'All groups'),
      GROUPS.map(g => el('option', { value: g }, 'Group ' + g)));
    const wrap = el('div');
    root.append(el('div', { class: 'formrow no-print' }, sel), wrap);
    function draw(g) {
      wrap.innerHTML = '';
      const ms = D.matches.filter(m => !g || m.group === g);
      const byDay = {};
      ms.forEach(m => { (byDay[dayLocal(m.dateET)] = byDay[dayLocal(m.dateET)] || []).push(m); });
      for (const day of Object.keys(byDay).sort()) {
        wrap.append(el('h2', { class: 'section' }, fmtD(byDay[day][0].dateET, localTZ)),
          el('div', { class: 'grid g2' }, byDay[day].sort((a, b) => a.dateET.localeCompare(b.dateET)).map(m => matchCard(m))));
      }
    }
    draw('');
  }

  function renderGroups(root) {
    root.append(el('div', { class: 'grid g2' }, GROUPS.map(g => {
      const rows = TABLES[g];
      return el('div', { class: 'card' },
        el('h3', null, 'Group ' + g),
        el('table', null,
          el('tr', null, ['Team', 'P', 'GD', 'Pts', 'xPts', '1st', 'Qual'].map((h, i) => el('th', { class: i ? 'num' : '' }, h))),
          rows.map((r, i) => {
            const s = SIM.teams[r.team];
            const qual = s.top2 + s.thirdQual;
            return el('tr', { class: 'click ' + (i < 2 ? 'qual' : i === 2 ? 'third' : ''), onclick: () => teamModal(r.team) },
              el('td', null, flagName(r.team)),
              el('td', { class: 'num' }, r.P), el('td', { class: 'num' }, r.GD > 0 ? '+' + r.GD : r.GD),
              el('td', { class: 'num' }, el('b', null, r.Pts)),
              el('td', { class: 'num' }, s.xPts.toFixed(1)),
              el('td', { class: 'num' }, pct(s.groupWin, 0)),
              el('td', { class: 'num' }, pct(Math.min(qual, 1), 0)));
          })));
    })),
      el('p', { class: 'tiny', style: 'margin-top:10px' },
        'xPts: expected final points. 1st: probability of winning the group. Qual: reaching the R32 by any route (top two or one of the eight best third-placed sides). Blue edge: currently in a qualifying position.'));
  }

  function renderBracket(root) {
    // most-likely single path
    const rank = {};
    GROUPS.forEach(g => {
      rank[g] = D.teams.filter(t => t.group === g).map(t => t.code)
        .sort((a, b) => SIM.teams[b].groupWin - SIM.teams[a].groupWin || SIM.teams[b].top2 - SIM.teams[a].top2 || SIM.teams[b].xPts - SIM.teams[a].xPts);
    });
    const thirdsPool = GROUPS.map(g => rank[g][2]).sort((a, b) => SIM.teams[b].thirdQual - SIM.teams[a].thirdQual).slice(0, 8);
    const pool = thirdsPool.slice();
    const r32 = D.r32Template.map(slot => {
      const pick = side => {
        if (side.type === 'group') return rank[side.group][side.place - 1];
        const oppSide = slot.a.type === 'group' ? rank[slot.a.group][slot.a.place - 1] : null;
        const og = oppSide ? T[oppSide].group : null;
        let i = pool.findIndex(c => (!side.groups || side.groups.indexOf(T[c].group) !== -1) && T[c].group !== og);
        if (i < 0) i = pool.findIndex(c => T[c].group !== og);
        if (i < 0) i = 0;
        return pool.splice(i, 1)[0];
      };
      const a = pick(slot.a), b = pick(slot.b);
      return { a, b, label: slot.label, venue: slot.venueId, date: slot.date };
    });
    function koP(a, b) {
      const p = E.predict(RT.ratings[a], RT.ratings[b]);
      const tilt = Math.max(0.35, Math.min(0.65, 0.5 + (RT.ratings[a] - RT.ratings[b]) / 4000));
      return p.p1 + p.draw * tilt;
    }
    const cols = [{ name: 'Round of 32', pairs: r32 }];
    let cur = r32;
    for (const name of ['Round of 16', 'Quarter-finals', 'Semi-finals', 'Final']) {
      const nxt = [];
      for (let i = 0; i < cur.length; i += 2) {
        const w1 = koP(cur[i].a, cur[i].b) >= 0.5 ? cur[i].a : cur[i].b;
        const o = cur[i + 1];
        const w2 = o ? (koP(o.a, o.b) >= 0.5 ? o.a : o.b) : null;
        if (w2) nxt.push({ a: w1, b: w2 });
      }
      if (!nxt.length) break;
      cols.push({ name, pairs: nxt });
      cur = nxt;
    }
    const fin = cols[cols.length - 1].pairs[0];
    const champ = koP(fin.a, fin.b) >= 0.5 ? fin.a : fin.b;
    root.append(
      el('p', { class: 'muted', style: 'margin-bottom:12px' },
        'One most-likely path through the tournament, taking the modal qualifier in every slot and the favourite in every tie. Real distributions are wider; see the Teams tab for every side’s full funnel.'),
      el('div', { class: 'bracket' },
        cols.map(c => el('div', { class: 'round' }, el('h4', null, c.name),
          c.pairs.map(p => {
            const pa = koP(p.a, p.b);
            return el('div', { class: 'bk' },
              p.label ? el('div', { class: 'lbl' }, p.label + (p.date ? ' · ' + p.date : '')) : null,
              el('div', { class: 't ' + (pa >= .5 ? 'w' : '') }, T[p.a].flag, ' ', T[p.a].name, el('span', { class: 'pct' }, pct(pa, 0))),
              el('div', { class: 't ' + (pa < .5 ? 'w' : '') }, T[p.b].flag, ' ', T[p.b].name, el('span', { class: 'pct' }, pct(1 - pa, 0))));
          }))),
        el('div', { class: 'round' }, el('h4', null, 'Champion'),
          el('div', { class: 'bk', style: 'border-color:var(--blue)' },
            el('div', { class: 't w', style: 'font-size:15px' }, T[champ].flag, ' ', T[champ].name),
            el('div', { class: 'lbl' }, 'Model title probability ' + pct(SIM.teams[champ].champ))))));
  }

  function renderTeams(root) {
    const cols = [
      ['team', 'Team'], ['group', 'Grp'], ['fifaRank', 'FIFA'], ['elo', 'Elo'],
      ['champ', 'Title'], ['fin', 'Final'], ['sf', 'SF'], ['qf', 'QF'], ['r16', 'R16'], ['r32', 'R32']];
    const tbl = el('table');
    function draw() {
      tbl.innerHTML = '';
      tbl.append(el('tr', null, cols.map(([k, h], i) => el('th', {
        class: (i > 0 ? 'num ' : '') + 'sortable' + (teamSort.key === k ? ' sorted' : ''),
        onclick: () => { teamSort = { key: k, dir: teamSort.key === k ? -teamSort.dir : -1 }; draw(); }
      }, h + (teamSort.key === k ? (teamSort.dir < 0 ? ' ↓' : ' ↑') : '')))));
      const rows = D.teams.map(t => ({
        t, team: t.name, group: t.group, fifaRank: t.fifaRank,
        elo: RT.ratings[t.code], ...SIM.teams[t.code],
      })).sort((a, b) => {
        const va = a[teamSort.key], vb = b[teamSort.key];
        return (typeof va === 'string' ? va.localeCompare(vb) : va - vb) * teamSort.dir;
      });
      rows.forEach(r => {
        const d = RT.delta[r.t.code];
        tbl.append(el('tr', { class: 'click', onclick: () => teamModal(r.t.code) },
          el('td', null, flagName(r.t.code)),
          el('td', { class: 'num' }, r.group),
          el('td', { class: 'num' }, r.fifaRank),
          el('td', { class: 'num' }, Math.round(r.elo) + (Math.abs(d) >= 0.5 ? ' ' : ''), Math.abs(d) >= 0.5 ? el('span', { class: 'tiny', style: 'color:' + (d > 0 ? 'var(--green)' : 'var(--red)') }, (d > 0 ? '+' : '') + d.toFixed(0)) : ''),
          el('td', { class: 'num' }, el('b', null, pct(r.champ)), el('span', { class: 'tiny' }, ' ±' + (r.band * 100).toFixed(1))),
          el('td', { class: 'num' }, pct(r.fin)),
          el('td', { class: 'num' }, pct(r.sf)),
          el('td', { class: 'num' }, pct(r.qf)),
          el('td', { class: 'num' }, pct(r.r16)),
          el('td', { class: 'num' }, pct(r.r32))));
      });
    }
    draw();
    root.append(el('div', { class: 'card' }, tbl),
      el('p', { class: 'tiny', style: 'margin-top:8px' }, 'Elo updates live with every result entered (K=40, margin-weighted). Click any column to sort, any row for the team’s glory funnel.'));
  }

  function renderMena(root) {
    const mena = D.mena.slice().sort((a, b) => SIM.teams[b].champ - SIM.teams[a].champ);
    root.append(el('p', { class: 'muted', style: 'margin-bottom:12px' },
      'The nine MENA sides at the 48-team World Cup.'),
      el('div', { class: 'grid g3' }, mena.map(c => {
        const s = SIM.teams[c];
        const tb = TABLES[T[c].group];
        const posn = tb.findIndex(r => r.team === c) + 1;
        const nxt = D.matches.filter(m => !effScore(m) && (m.team1 === c || m.team2 === c))
          .sort((a, b) => a.dateET.localeCompare(b.dateET))[0];
        return el('div', { class: 'card click', onclick: () => teamModal(c) },
          el('h3', null, T[c].flag + ' ' + T[c].name, el('span', { class: 'right' }, 'Group ' + T[c].group + ' · ' + posn + (posn === 1 ? 'st' : posn === 2 ? 'nd' : posn === 3 ? 'rd' : 'th'))),
          el('div', { class: 'funnel' },
            [['Out of group', Math.min(s.top2 + s.thirdQual, 1)], ['Reach QF', s.qf], ['Title', s.champ]].map(([l, p]) =>
              el('div', { class: 'frow' }, el('span', { class: 'fl-label' }, l),
                el('div', { class: 'hbar' }, el('div', { style: 'width:' + Math.max(p * 100, 0.5) + '%' })),
                el('span', { class: 'num' }, pct(p))))),
          nxt ? el('div', { class: 'tiny', style: 'margin-top:8px' }, 'Next: v ' + T[nxt.team1 === c ? nxt.team2 : nxt.team1].name + ' · ' + kickoff(nxt)) : null);
      })));
  }

  // ---------- league ----------
  function encodeEntry(o) { return btoa(unescape(encodeURIComponent(JSON.stringify(o)))).replace(/=+$/, ''); }
  function decodeEntry(s) { return JSON.parse(decodeURIComponent(escape(atob(s.trim())))); }

  function renderJoin(root) {
    const sc = D.league.scoring;
    root.append(el('div', { class: 'card', style: 'margin-bottom:14px' },
      el('h3', null, 'How it works'),
      el('p', { class: 'muted' },
        'Pick a winner for each of the twelve groups, two finalists, and the champion. Send the code this page generates to Mohammed on WhatsApp; the published leaderboard updates with the site. Scoring: ' +
        sc.groupWinner + ' points per correct group winner, ' + sc.finalist + ' per correct finalist, ' + sc.champion + ' for the champion. Two rules the form enforces: your champion must be one of your finalists, and your two finalists must be able to reach the final from opposite halves of the official bracket given your own group winners — the form will tell you if a pair cannot meet in the final.')));

    // picks form
    const name = el('input', { placeholder: 'Your name', style: 'min-width:180px' });
    const gSel = {};
    const pickGrid = el('div', { class: 'picks-grid' }, GROUPS.map(g => {
      gSel[g] = el('select', null,
        el('option', { value: '' }, '— choose —'),
        D.teams.filter(t => t.group === g).map(t => el('option', { value: t.code }, t.flag + ' ' + t.name)));
      return el('div', null, el('label', null, 'Group ' + g + ' winner'), gSel[g]);
    }));
    const allOpts = () => [el('option', { value: '' }, '— choose —')]
      .concat(D.teams.slice().sort((a, b) => a.name.localeCompare(b.name)).map(t => el('option', { value: t.code }, t.flag + ' ' + t.name)));
    const f1 = el('select', null, allOpts()), f2 = el('select', null, allOpts()), ch = el('select', null, allOpts());
    const out = el('div');
    root.append(el('div', { class: 'card no-print', style: 'margin-bottom:14px' },
      el('h3', null, 'Make your picks'),
      el('div', { class: 'formrow' }, name),
      pickGrid,
      el('div', { class: 'formrow', style: 'margin-top:10px' },
        el('div', null, el('label', { class: 'tiny' }, 'Finalist 1'), f1),
        el('div', null, el('label', { class: 'tiny' }, 'Finalist 2'), f2),
        el('div', null, el('label', { class: 'tiny' }, 'Champion'), ch),
        el('button', {
          class: 'btn', onclick: () => {
            if (!name.value.trim()) { out.replaceChildren(el('p', { class: 'muted' }, 'Add your name first.')); return; }
            const unpicked = GROUPS.filter(g => !gSel[g].value);
            if (unpicked.length) { out.replaceChildren(el('p', { class: 'muted' }, 'Pick a winner for every group — still missing: ' + unpicked.join(', ') + '.')); return; }
            if (!f1.value || !f2.value || !ch.value) { out.replaceChildren(el('p', { class: 'muted' }, 'Pick both finalists and a champion.')); return; }
            if (f1.value === f2.value) { out.replaceChildren(el('p', { class: 'muted' }, 'The two finalists must be different teams.')); return; }
            if (ch.value !== f1.value && ch.value !== f2.value) {
              out.replaceChildren(el('p', { class: 'muted' }, 'Your champion has to be one of your two finalists — a team cannot win the cup without reaching the final.'));
              return;
            }
            const w = {}; GROUPS.forEach(g => w[g] = gSel[g].value);
            const fz = E.finalFeasible({ w, f: [f1.value, f2.value] }, D);
            if (!fz.ok) {
              const sameHalf = (fz.h1[0] === 0 && fz.h2[0] === 0) ? 'top' : 'bottom';
              out.replaceChildren(el('p', { class: 'muted' },
                T[f1.value].name + ' and ' + T[f2.value].name + ' cannot meet in the final on your own picks: given your group winners, both sides of that pairing land in the ' + sameHalf + ' half of the official bracket, so they would knock each other out before the final. Change one finalist, or change a group winner so they end up on opposite sides of the draw.'));
              return;
            }
            const code = encodeEntry({ v: 1, n: name.value.trim(), w, f: [f1.value, f2.value], c: ch.value });
            out.replaceChildren(
              el('code', { class: 'codebox' }, code),
              el('div', { class: 'formrow', style: 'margin-top:8px' },
                el('button', { class: 'btn small ghost', onclick: () => navigator.clipboard.writeText(code) }, 'Copy code'),
                el('a', { class: 'btn small', href: 'https://wa.me/?text=' + encodeURIComponent('My World Cup picks: ' + code), target: '_blank', style: 'display:inline-block;text-decoration:none' }, 'Share on WhatsApp')));
          }
        }, 'Generate code')),
      out));

    // ---------- round 2: the props ----------
    root.append(el('h2', { class: 'section' }, 'Round 2 — The Props'));
    root.append(el('div', { class: 'card', style: 'margin-bottom:14px' },
      el('h3', null, 'Six side prizes', el('span', { class: 'right' }, (function(){ var d = D.league.propsDeadline || '16 June'; return /open|tbc/i.test(d) ? 'entries open — deadline TBC' : 'entries close ' + d + ', 23:59 Kuwait'; })())),
      el('p', { class: 'muted' },
        'Separate from the main league, separate prizes, everyone starts equal. Pick the Golden Boot winner, the top assist provider, the team that collects the most cards (the Dirty Trophy), the team that scores the most goals, the MENA side that goes furthest, and the host nation that survives longest. Your total-goals number doubles as the official tiebreaker for the main league. Send the code to Mohammed as before.')));

    const pName = el('input', { placeholder: 'Your name (same as your main entry)', style: 'min-width:220px' });
    const teamOpts = sel => [el('option', { value: '' }, '— choose —')]
      .concat(D.teams.slice().sort((a, b) => a.name.localeCompare(b.name)).map(t => el('option', { value: t.code }, t.flag + ' ' + t.name)));
    const gbP = el('input', { placeholder: 'Player name' }), gbT = el('select', null, teamOpts());
    const asP = el('input', { placeholder: 'Player name' }), asT = el('select', null, teamOpts());
    const cardsT = el('select', null, teamOpts());
    const goalsT = el('select', null, teamOpts());
    const menaT = el('select', null, [el('option', { value: '' }, '— choose —')]
      .concat(D.mena.map(c => el('option', { value: c }, T[c].flag + ' ' + T[c].name))));
    const hostT = el('select', null, [el('option', { value: '' }, '— choose —')]
      .concat(['MEX', 'USA', 'CAN'].map(c => el('option', { value: c }, T[c].flag + ' ' + T[c].name))));
    const tg = el('input', { type: 'number', min: 50, max: 400, placeholder: 'e.g. 172', style: 'width:110px' });
    const pOut = el('div');
    const row = (label, ...controls) => el('div', { class: 'formrow' }, el('span', { class: 'muted', style: 'min-width:190px' }, label), ...controls);
    root.append(el('div', { class: 'card no-print', style: 'margin-bottom:14px' },
      el('h3', null, 'Make your props picks'),
      el('div', { class: 'formrow' }, pName),
      row('Golden Boot (top scorer)', gbP, gbT),
      row('Most assists', asP, asT),
      row('Dirty Trophy (most cards)', cardsT),
      row('Top-scoring team', goalsT),
      row('Best MENA run', menaT),
      row('Furthest host', hostT),
      row('Total tournament goals (tiebreaker)', tg),
      el('div', { class: 'formrow' }, el('button', {
        class: 'btn', onclick: () => {
          const fail = msg => pOut.replaceChildren(el('p', { class: 'muted' }, msg));
          if (!pName.value.trim()) return fail('Add your name first.');
          if (!gbP.value.trim() || !gbT.value) return fail('Golden Boot needs a player name and his team.');
          if (!asP.value.trim() || !asT.value) return fail('Most assists needs a player name and his team.');
          if (!cardsT.value || !goalsT.value || !menaT.value || !hostT.value) return fail('Pick a team for every category.');
          const n = parseInt(tg.value, 10);
          if (isNaN(n) || n < 50 || n > 400) return fail('Total goals needs a number between 50 and 400 — there are 104 matches.');
          const code = encodeEntry({
            v: 2, t: 'props', n: pName.value.trim(),
            gb: { p: gbP.value.trim(), t: gbT.value }, as: { p: asP.value.trim(), t: asT.value },
            cards: cardsT.value, goals: goalsT.value, mena: menaT.value, host: hostT.value, tg: n,
          });
          pOut.replaceChildren(
            el('code', { class: 'codebox' }, code),
            el('div', { class: 'formrow', style: 'margin-top:8px' },
              el('button', { class: 'btn small ghost', onclick: () => navigator.clipboard.writeText(code) }, 'Copy code'),
              el('a', { class: 'btn small', href: 'https://wa.me/?text=' + encodeURIComponent('My World Cup props: ' + code), target: '_blank', style: 'display:inline-block;text-decoration:none' }, 'Share on WhatsApp')));
        }
      }, 'Generate props code')),
      pOut));

    root.append(el('p', { class: 'muted', style: 'margin-top:14px' },
      'Sent your code? Watch the standings, the selections board and the live props race on the ', el('b', null, 'League'), ' tab.'));
  }

  function renderLeague(root) {
    const sc = D.league.scoring;
    root.append(el('div', { class: 'card no-print', style: 'margin-bottom:14px' },
      el('p', { class: 'muted', style: 'margin:0' },
        'Not entered yet? Make your picks on the ', el('b', null, 'Join'), ' tab, then send Mohammed the code.')));

    // import + leaderboard
    const ta = el('textarea', { placeholder: 'Paste one or more codes, one per line' });
    root.append(el('div', { class: 'card no-print', style: 'margin-bottom:14px' },
      el('h3', null, 'Add entries'),
      ta,
      el('div', { class: 'formrow', style: 'margin-top:8px' },
        el('button', {
          class: 'btn small', onclick: () => {
            let added = 0;
            ta.value.split(/\s+/).filter(Boolean).forEach(line => {
              try {
                const e = decodeEntry(line);
                if (e && e.n && e.w) {
                  leagueLocal = leagueLocal.filter(x => x.n !== e.n).concat([e]);
                  added++;
                }
              } catch (err) {}
            });
            lsSet(LS.league, leagueLocal); ta.value = '';
            if (added) refresh();
          }
        }, 'Add to leaderboard'),
        leagueLocal.length ? el('button', { class: 'btn small ghost', onclick: () => { leagueLocal = []; lsSet(LS.league, leagueLocal); refresh(); } }, 'Clear local entries') : null)));

    const pubNames = new Set((D.league.entries || []).map(e => e.n.toLowerCase()));
    const entries = (D.league.entries || []).map(e => ({ ...e, src: 'published' }))
      .concat(leagueLocal.filter(e => !pubNames.has((e.n || '').toLowerCase())).map(e => ({ ...e, src: 'local' })));
    if (!entries.length) { root.append(el('p', { class: 'muted' }, 'No entries yet. Make your picks on the Join tab and send the code round.')); return; }
    const resolved = E.resolvedOutcomes(effData());
    const allGroupsDone = Object.keys(resolved.groupWinners).length === 12;
    const elim = c => {
      // eliminated only once its group is fully played: 4th is out; 3rd stays alive until all groups resolve the best-third race
      if (!T[c] || !resolved.groupWinners[T[c].group]) return false;
      const posn = TABLES[T[c].group].findIndex(r => r.team === c);
      if (posn === 3) return true;
      if (posn === 2 && allGroupsDone) return SIM.teams[c].r32 === 0;
      return false;
    };
    const rows = entries.map(e => {
      let pts = 0, exp = 0, max = 0;
      GROUPS.forEach(g => {
        const pick = e.w && e.w[g];
        if (!pick || !T[pick]) return;
        const win = resolved.groupWinners[g];
        if (win) { const hit = win === pick ? sc.groupWinner : 0; pts += hit; exp += hit; max += hit; }
        else { exp += SIM.teams[pick].groupWin * sc.groupWinner; max += sc.groupWinner; }
      });
      (e.f || []).forEach(fc => {
        if (!T[fc]) return;
        exp += SIM.teams[fc].fin * sc.finalist;
        if (!elim(fc)) max += sc.finalist;
      });
      if (e.c && T[e.c]) { exp += SIM.teams[e.c].champ * sc.champion; if (!elim(e.c)) max += sc.champion; }
      return { e, pts, exp, max };
    }).sort((a, b) => b.pts - a.pts || b.exp - a.exp);
    // exhibition entries (the commissioner) are ranked for display but carry no prize position
    let rankNo = 0;
    root.append(el('div', { class: 'card', style: 'margin-bottom:14px' },
      el('h3', null, 'Leaderboard', el('span', { class: 'right' }, Object.keys(resolved.groupWinners).length + ' of 12 groups resolved')),
      el('table', null,
        el('tr', null,
          el('th', null, '#'), el('th', null, 'Name'), el('th', null, 'Champion pick'),
          el('th', { class: 'num' }, 'Points'), el('th', { class: 'num' }, 'Expected'), el('th', { class: 'num' }, 'Max')),
        rows.map(r => {
          const exh = r.e.exhibition;
          if (!exh) rankNo++;
          return el('tr', { class: exh ? 'exhibition-row' : '' },
            el('td', null, exh ? '★' : rankNo),
            el('td', null, el('b', null, r.e.n),
              exh ? el('span', { class: 'exh-badge' }, 'EXHIBITION') : (r.e.src === 'local' ? el('span', { class: 'tiny' }, ' (local)') : '')),
            el('td', null, el('span', { class: 'teamcell' }, T[r.e.c] ? el('span', { class: 'fl' }, T[r.e.c].flag) : '', el('span', { class: 'nm' }, T[r.e.c] ? T[r.e.c].name : '—'))),
            el('td', { class: 'num' }, el('b', null, r.pts)),
            el('td', { class: 'num' }, r.exp.toFixed(1)),
            el('td', { class: 'num' }, r.max));
        })),
      el('p', { class: 'tiny', style: 'margin-top:8px' },
        'Points: locked in from resolved outcomes. Expected: the model weighs every pick by its current probability; this number moves with each result. Max: the ceiling if every still-alive pick lands. ★ The commissioner’s exhibition entry is shown for interest only and does not compete for prizes.')));

    // selections board: everyone's picks side by side
    const cell = (code, win) => {
      if (!code || !T[code]) return el('td', { class: 'num muted' }, '—');
      const cls = win ? (win === code ? 'pick-hit' : 'pick-miss') : (elim(code) ? 'pick-miss' : '');
      return el('td', { class: cls }, el('span', { class: 'teamcell', style: 'font-weight:500' }, el('span', { class: 'fl' }, T[code].flag), el('span', { class: 'nm' }, T[code].code)));
    };
    root.append(el('div', { class: 'card' },
      el('h3', null, 'The selections board'),
      el('div', { class: 'chart-wrap' }, el('table', { class: 'selections' },
        el('tr', null, el('th', null, ''), rows.map(r => el('th', { class: r.e.exhibition ? 'exh-col' : '' },
          (r.e.exhibition ? '★ ' : '') + r.e.n,
          el('span', { class: 'tiny', style: 'display:block;font-weight:400;text-transform:none;letter-spacing:0' },
            r.e.exhibition ? 'exhibition' : (r.e.locked ? 'locked ' + r.e.locked : (r.e.src === 'local' ? 'local' : '')))))),
        GROUPS.map(g => el('tr', null,
          el('td', { class: 'muted', style: 'white-space:nowrap' }, 'Group ' + g),
          rows.map(r => cell(r.e.w && r.e.w[g], resolved.groupWinners[g])))),
        el('tr', null, el('td', { class: 'muted' }, 'Finalists'),
          rows.map(r => el('td', null, (r.e.f || []).filter(fc => T[fc]).map(fc =>
            el('span', { class: 'teamcell', style: 'font-weight:500;display:inline-flex;margin-right:8px' + (elim(fc) ? ';opacity:.45;text-decoration:line-through' : '') },
              el('span', { class: 'fl' }, T[fc].flag), T[fc].code)),
            E.finalFeasible(r.e, D).ok ? null : el('span', { class: 'tiny', title: 'On this entry’s own group picks, these two finalists sit in the same half of the bracket and cannot meet in the final. The entry predates the bracket rule and stands as submitted.' }, '†')))),
        el('tr', null, el('td', { class: 'muted' }, 'Champion'),
          rows.map(r => cell(r.e.c, null))))),
      el('p', { class: 'tiny', style: 'margin-top:8px' },
        'Green: called it. Red: pick eliminated or group went elsewhere. Locked dates show when each entry reached the published board.')));

    const props = (D.league.props || []);
    if (props.length) {
      root.append(el('div', { class: 'card' },
        el('h3', null, 'The props board', el('span', { class: 'right' }, props.length + ' in')),
        el('div', { class: 'chart-wrap' }, el('table', { class: 'selections' },
          el('tr', null, ['Name', 'Golden Boot', 'Assists', 'Dirty Trophy', 'Top scorers', 'MENA run', 'Host', 'Goals'].map(h => el('th', null, h))),
          props.map(p => el('tr', null,
            el('td', null, el('b', null, p.n)),
            el('td', null, p.gb.p + ' ' + (T[p.gb.t] ? T[p.gb.t].flag : '')),
            el('td', null, p.as.p + ' ' + (T[p.as.t] ? T[p.as.t].flag : '')),
            el('td', null, T[p.cards] ? T[p.cards].flag + ' ' + T[p.cards].code : '—'),
            el('td', null, T[p.goals] ? T[p.goals].flag + ' ' + T[p.goals].code : '—'),
            el('td', null, T[p.mena] ? T[p.mena].flag + ' ' + T[p.mena].code : '—'),
            el('td', null, T[p.host] ? T[p.host].flag + ' ' + T[p.host].code : '—'),
            el('td', { class: 'num' }, p.tg))))),
        el('p', { class: 'tiny', style: 'margin-top:8px' },
          'Standings per category are updated through the tournament; each category is its own prize. The Goals column is also the main league’s official tiebreaker (closest wins).')));
    }

    const pl = D.propsLive;
    if (pl) {
      const board = (title, rows, cols, fmt) => el('div', { class: 'card', style: 'margin-bottom:14px' },
        el('h3', null, title, el('span', { class: 'right' }, 'after ' + pl.matchesCounted + ' matches')),
        (rows && rows.length) ? el('div', { class: 'chart-wrap' }, el('table', null,
          el('tr', null, cols.map((h, i) => el('th', { class: i ? 'num' : '' }, h))),
          rows.map((r, i) => fmt(r, i)))) : el('p', { class: 'muted' }, 'No data yet — fills in as games are played.'));
      const teamCell = c => T[c] ? T[c].flag + ' ' + T[c].name : (c || '—');
      root.append(el('h2', { class: 'section' }, 'Props race — live leaderboards'));
      root.append(board('Golden Boot race', pl.topScorers, ['#', 'Player', 'Team', 'Goals'], (r, i) => el('tr', null,
        el('td', { class: 'num' }, String(i + 1)), el('td', null, el('b', null, r.player || '—')),
        el('td', null, T[r.team] ? T[r.team].flag + ' ' + r.team : '—'),
        el('td', { class: 'num' }, el('b', null, r.goals + (r.pens ? ' (' + r.pens + 'p)' : ''))))));
      root.append(board('Assists race', pl.topAssists, ['#', 'Player', 'Team', 'Assists'], (r, i) => el('tr', null,
        el('td', { class: 'num' }, String(i + 1)), el('td', null, el('b', null, r.player || '—')),
        el('td', null, T[r.team] ? T[r.team].flag + ' ' + r.team : '—'),
        el('td', { class: 'num' }, el('b', null, r.assists)))));
      root.append(board('Dirty Trophy — most cards', pl.teamCards, ['#', 'Team', 'Yellow', 'Red', 'Pts'], (r, i) => el('tr', null,
        el('td', { class: 'num' }, String(i + 1)), el('td', null, teamCell(r.team)),
        el('td', { class: 'num' }, r.yellow), el('td', { class: 'num' }, r.red), el('td', { class: 'num' }, el('b', null, r.points)))));
      root.append(board('Most team goals', pl.teamGoals, ['#', 'Team', 'Goals'], (r, i) => el('tr', null,
        el('td', { class: 'num' }, String(i + 1)), el('td', null, teamCell(r.team)),
        el('td', { class: 'num' }, el('b', null, r.goals)))));
      root.append(el('p', { class: 'tiny' }, pl.note + ' As of ' + (pl.asOf || D.meta.asOf) + '.'));
    }
  }

  function renderCompare(root) {
    const pubNames = new Set((D.league.entries || []).map(e => (e.n || '').toLowerCase()));
    const entries = (D.league.entries || []).map(e => ({ ...e }))
      .concat(leagueLocal.filter(e => !pubNames.has((e.n || '').toLowerCase())));
    if (!entries.length) { root.append(el('h2', { class: 'section' }, 'Compare picks'), el('p', { class: 'muted' }, 'No entries yet. Add yours on the League tab.')); return; }
    const n = entries.length;

    // pick-frequency maps across the field
    const champFreq = {}, finFreq = {}, grpFreq = {};
    GROUPS.forEach(g => grpFreq[g] = {});
    entries.forEach(e => {
      if (e.c) champFreq[e.c] = (champFreq[e.c] || 0) + 1;
      (e.f || []).forEach(fc => { finFreq[fc] = (finFreq[fc] || 0) + 1; });
      GROUPS.forEach(g => { const p = e.w && e.w[g]; if (p) grpFreq[g][p] = (grpFreq[g][p] || 0) + 1; });
    });
    const team = (code) => T[code] ? T[code] : null;

    root.append(el('h2', { class: 'section' }, 'Compare picks'));
    root.append(el('p', { class: 'muted', style: 'margin-bottom:14px' },
      n + ' entries, side by side. A 🐺 marks a lone-wolf pick: the only entry in the league making that call.'));

    // --- Title-race split: who backed whom to win it ---
    const champs = Object.keys(champFreq).sort((a, b) => champFreq[b] - champFreq[a] || a.localeCompare(b));
    const maxC = Math.max.apply(null, champs.map(c => champFreq[c]));
    root.append(el('div', { class: 'card champ-split', style: 'margin-bottom:16px' },
      el('h3', null, 'Who backed whom to lift the trophy', el('span', { class: 'right' }, champs.length + ' different champions')),
      champs.map(c => el('div', { class: 'row' },
        el('span', { class: 'cell-team', style: 'min-width:128px;flex:none' }, el('span', { class: 'fl' }, team(c) ? team(c).flag : ''), el('span', { class: 'nm' }, team(c) ? team(c).name : c), champFreq[c] === 1 ? el('span', { class: 'lone-badge' }, ' 🐺') : ''),
        el('span', { class: 'ct' }, champFreq[c]),
        el('span', { class: 'bar', style: 'width:' + Math.max(6, Math.round(champFreq[c] / maxC * 130)) + 'px' }),
        el('span', { class: 'who' }, entries.filter(e => e.c === c).map(e => e.n).join(', '))))));

    // --- Mavericks vs the flock (boldness from pick rarity) ---
    const bold = entries.map(e => {
      let s = 0, lones = 0;
      if (e.c && champFreq[e.c] === 1) { s += 3; lones++; }
      (e.f || []).forEach(fc => { if (finFreq[fc] === 1) { s += 2; lones++; } });
      GROUPS.forEach(g => { const p = e.w && e.w[g]; if (p && grpFreq[g][p] === 1) { s += 1; lones++; } });
      return { n: e.n, exhibition: e.exhibition, s, lones };
    });
    const mavericks = bold.slice().sort((a, b) => b.s - a.s).filter(b => b.s > 0).slice(0, 3);
    const flock = bold.slice().sort((a, b) => a.s - b.s).slice(0, 3);
    root.append(el('div', { class: 'card', style: 'margin-bottom:16px' },
      el('h3', null, 'Mavericks & the flock'),
      el('div', { class: 'grid g2' },
        el('div', null,
          el('div', { class: 'subh' }, 'Biggest gamblers'),
          mavericks.length ? mavericks.map(b => el('div', { class: 'tiny', style: 'padding:3px 0' }, el('b', null, b.n), ' — ' + b.lones + ' lone-wolf pick' + (b.lones === 1 ? '' : 's'))) : el('div', { class: 'tiny' }, 'Everyone is still playing it safe.')),
        el('div', null,
          el('div', { class: 'subh' }, 'Safest hands'),
          flock.map(b => el('div', { class: 'tiny', style: 'padding:3px 0' }, el('b', null, b.n), ' — ' + (b.lones === 0 ? 'all consensus picks' : b.lones + ' lone pick' + (b.lones === 1 ? '' : 's'))))))));

    // --- The full grid: every pick side by side ---
    const cellTeam = (code, freq) => {
      if (!code) return el('td', null, '—');
      const lone = freq === 1;
      return el('td', { class: lone ? 'lone' : '' }, el('span', { class: 'cell-team' },
        el('span', { class: 'fl' }, team(code) ? team(code).flag : ''),
        team(code) ? team(code).code : code,
        lone ? el('span', { class: 'lone-badge' }, ' 🐺') : ''));
    };
    const header = el('tr', null,
      el('th', { class: 'nm-cell' }, 'Name'), el('th', null, 'Champ'), el('th', null, 'Finalists'),
      GROUPS.map(g => el('th', null, g)));
    const gridRows = entries.slice()
      .sort((a, b) => (a.exhibition ? 1 : 0) - (b.exhibition ? 1 : 0) || (a.n || '').toLowerCase().localeCompare((b.n || '').toLowerCase()))
      .map(e => el('tr', { class: e.exhibition ? 'exhibition-row' : '' },
        el('td', { class: 'nm-cell' }, e.n, e.exhibition ? el('span', { class: 'exh-badge' }, '★') : ''),
        cellTeam(e.c, champFreq[e.c]),
        el('td', null, (e.f || []).map((fc, i) => el('span', { class: 'cell-team', style: i ? 'margin-left:8px' : '' },
          el('span', { class: 'fl' }, team(fc) ? team(fc).flag : ''), team(fc) ? team(fc).code : fc,
          finFreq[fc] === 1 ? el('span', { class: 'lone-badge' }, ' 🐺') : ''))),
        GROUPS.map(g => { const p = e.w && e.w[g]; return cellTeam(p, p ? grpFreq[g][p] : 0); })));
    root.append(el('div', { class: 'card' },
      el('h3', null, 'Every pick, side by side', el('span', { class: 'right' }, n + ' entries · scroll sideways →')),
      el('div', { class: 'compare-wrap' }, el('table', { class: 'compare-table' }, header, gridRows)),
      el('p', { class: 'tiny', style: 'margin-top:8px' }, '🐺 = lone wolf (the only entry making that pick). Scroll sideways for all twelve groups. ★ = the commissioner’s exhibition entry.')));
  }

  function renderTimeline(root) {
    const hist = H.slice();
    const liveProbs = {};
    Object.entries(SIM.teams).forEach(([c, s]) => liveProbs[c] = +(s.champ * 100).toFixed(2));
    const points = hist.concat([{ date: todayKWT(), label: 'Live (this browser)', probs: liveProbs, live: true }]);
    const series = Object.entries(SIM.teams).sort((a, b) => b[1].champ - a[1].champ).slice(0, 8).map(([c]) => c);
    const W = Math.max(560, points.length * 90 + 120), Hh = 300, padL = 46, padB = 40, padT = 16;
    const maxY = Math.max(...points.flatMap(p => series.map(c => p.probs[c] || 0))) * 1.15;
    const x = i => padL + i * ((W - padL - 20) / Math.max(points.length - 1, 1));
    const y = v => padT + (Hh - padB - padT) * (1 - v / maxY);
    let svg = '<svg class="vmap" viewBox="0 0 ' + W + ' ' + Hh + '" style="background:#fff">';
    for (let gy = 0; gy <= 4; gy++) {
      const v = maxY * gy / 4;
      svg += '<line x1="' + padL + '" x2="' + (W - 20) + '" y1="' + y(v) + '" y2="' + y(v) + '" stroke="#EDEFF6"/>' +
        '<text x="6" y="' + (y(v) + 3) + '">' + v.toFixed(0) + '%</text>';
    }
    points.forEach((p, i) => { svg += '<text x="' + (x(i) - 24) + '" y="' + (Hh - 18) + '">' + p.date.slice(5) + (p.live ? ' ·live' : '') + '</text>'; });
    series.forEach((c, si) => {
      const col = PALETTE[si % PALETTE.length];
      const pts = points.map((p, i) => x(i) + ',' + y(p.probs[c] || 0)).join(' ');
      svg += '<polyline points="' + pts + '" fill="none" stroke="' + col + '" stroke-width="2"/>';
      points.forEach((p, i) => { svg += '<circle cx="' + x(i) + '" cy="' + y(p.probs[c] || 0) + '" r="3" fill="' + col + '"/>'; });
    });
    svg += '</svg>';
    root.append(el('div', { class: 'card' },
      el('h3', null, 'Title probability over the tournament'),
      el('div', { class: 'chart-wrap', html: svg }),
      el('div', { class: 'legend' }, series.map((c, i) => el('span', null, el('i', { style: 'background:' + PALETTE[i % PALETTE.length] }), T[c].flag + ' ' + T[c].name))),
      el('p', { class: 'tiny', style: 'margin-top:10px' },
        'Each point is a published snapshot of the model after that day’s results; the final point is this browser’s live recompute. The 11 June point is the pre-tournament external blend (market plus rating models) the site launched from; all later points are this site’s own engine.')));
    root.append(el('div', { class: 'card', style: 'margin-top:14px' },
      el('h3', null, 'Snapshots'),
      el('table', null, points.map(p => el('tr', null,
        el('td', null, p.date), el('td', { class: 'muted' }, p.label),
        el('td', { class: 'num' }, Object.entries(p.probs).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([c, v]) => T[c].flag + ' ' + v.toFixed(1) + '%').join('  ')))))));
  }

  function venueModal(v) {
    const fixtures = D.matches.filter(m => m.venueId === v.id).sort((a, b) => a.dateET.localeCompare(b.dateET));
    openModal(
      el('h2', null, v.name),
      el('div', { class: 'muted', style: 'margin-bottom:12px' },
        v.city + ', ' + v.country + ' · ' + v.capacity.toLocaleString() + ' capacity' +
        (v.elev > 500 ? ' · ' + v.elev + ' m altitude' + (v.elev > 2000 ? ' (the thin-air venue)' : '') : '')),
      el('h2', { class: 'section' }, 'Matches here'),
      el('table', null, fixtures.map(m => {
        const sc = effScore(m);
        return el('tr', { class: 'click', onclick: () => matchModal(m) },
          el('td', { style: 'white-space:nowrap' }, fmtD(m.dateET, localTZ)),
          el('td', null, el('span', { class: 'teamcell', style: 'font-weight:500' },
            T[m.team1].flag + ' ' + T[m.team1].code + (sc ? ' ' + sc.team1 + '–' + sc.team2 + ' ' : ' v ') + T[m.team2].code + ' ' + T[m.team2].flag)),
          el('td', { class: 'num tiny' }, sc ? 'FT' : kt(m.dateET)));
      })));
  }

  function renderVenues(root) {
    const P = WC_MAP.proj;
    const px = lon => (lon - P.lon0) * P.k * P.scale;
    const py = lat => (P.lat0 - lat) * P.scale;
    const xs = D.venues.map(v => px(v.lon)), ys = D.venues.map(v => py(v.lat));
    const M = 58;
    const x0 = Math.min(...xs) - M, y0 = Math.min(...ys) - M;
    const w = Math.max(...xs) - x0 + 2 * M, h = Math.max(...ys) - y0 + 2 * M;
    const shortCity = v => {
      const seg = v.city.split('/').map(s => s.trim());
      const name = (seg.length > 1 ? seg[1] : seg[0]).replace(' Bay Area', '').replace(' New Jersey', '');
      return name;
    };
    const today = todayLocal();
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'geomap');
    svg.setAttribute('viewBox', [x0, y0, w, h].join(' '));
    svg.style.aspectRatio = (w / h).toFixed(3);
    svg.innerHTML = WC_MAP.paths.map(d => '<path class="land" d="' + d + '"/>').join('');
    D.venues.forEach(v => {
      const n = D.matches.filter(m => m.venueId === v.id).length;
      const playingToday = D.matches.some(m => m.venueId === v.id && dayLocal(m.dateET) === today);
      const cx = px(v.lon), cy = py(v.lat);
      if (playingToday) {
        const ring = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        ring.setAttribute('class', 'today-ring'); ring.setAttribute('cx', cx); ring.setAttribute('cy', cy); ring.setAttribute('r', 7);
        svg.append(ring);
      }
      const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      c.setAttribute('class', 'venue'); c.setAttribute('cx', cx); c.setAttribute('cy', cy);
      c.setAttribute('r', 3.5 + n * 0.45);
      c.addEventListener('click', () => venueModal(v));
      const tip = document.createElementNS('http://www.w3.org/2000/svg', 'title');
      tip.textContent = v.name + ' — ' + v.city + ' (' + n + ' matches)';
      c.append(tip);
      svg.append(c);
      const label = shortCity(v);
      const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      t.setAttribute('class', 'vlabel');
      const left = ['Vancouver', 'Los Angeles', 'Boston', 'Philadelphia'].includes(label);
      t.setAttribute('x', cx + (left ? -8 : 8)); t.setAttribute('y', cy + 3);
      t.setAttribute('text-anchor', left ? 'end' : 'start');
      t.textContent = label;
      svg.append(t);
    });
    root.append(
      el('div', { class: 'card' },
        el('h3', null, 'The sixteen stadiums', el('span', { class: 'right' }, 'marker size = matches hosted · pulse = playing today')),
        svg,
        el('p', { class: 'tiny', style: 'margin-top:8px' }, 'Tap any marker for the venue’s full fixture list. Times shown in your local timezone' + (localTZ === KWT ? '.' : ' (Kuwait time in brackets).'))),
      el('div', { class: 'grid g3', style: 'margin-top:14px' }, D.venues.map(v => {
        const fixtures = D.matches.filter(m => m.venueId === v.id);
        const next = fixtures.filter(m => !effScore(m)).sort((a, b) => a.dateET.localeCompare(b.dateET))[0];
        return el('div', { class: 'card click', onclick: () => venueModal(v) },
          el('h3', null, v.city, el('span', { class: 'right' }, v.country)),
          el('div', null, el('b', null, v.name)),
          el('div', { class: 'muted' }, v.capacity.toLocaleString() + ' capacity' + (v.elev > 500 ? ' · ' + v.elev + ' m altitude' : '')),
          el('div', { class: 'tiny', style: 'margin-top:4px' }, fixtures.length + ' matches' +
            (next ? ' · next: ' + T[next.team1].code + ' v ' + T[next.team2].code + ', ' + fmtD(next.dateET, localTZ) : '')));
      })));
  }

  function renderGeeks(root) {
    const P = (...k) => el('p', { class: 'muted' }, ...k);
    const card = (title, ...k) => el('div', { class: 'card', style: 'margin-bottom:14px' }, el('h3', null, title), ...k);
    const played = D.matches.filter(m => m.status === 'completed' && m.score).length;

    root.append(card('For the curious',
      P('None of this is needed to play. It is here because a few people asked how the site actually works, and how much sits under a number like “Spain 7%”. Everything below is the real engine and the real homework behind it, parameters and all.')));

    root.append(card('The model, end to end',
      P('One engine produces every probability on the site, in five steps. ',
        el('b', null, '1. Rate every team. '), 'Each side carries an Elo-style strength rating, seeded from the FIFA rankings. ',
        el('b', null, '2. Update on every result. '), 'After each match the ratings shift (winner up, loser down), weighted by the margin and now tempered by expected goals (below). ',
        el('b', null, '3. Turn a rating gap into match odds. '), 'A logistic curve converts the rating difference between two teams into win/draw/loss probabilities, and into an expected goals figure for each side. ',
        el('b', null, '4. Roll the dice for goals. '), 'Those expected-goal figures feed a Poisson model that produces a plausible scoreline. ',
        el('b', null, '5. Play the whole tournament 10,000 times. '), 'Every remaining match, the group tables, the bracket, extra time and penalties are simulated end to end, ten thousand times. A team lifting the trophy in 700 of those runs is exactly what “7%” means.'),
      el('table', null,
        el('tr', null, ['Parameter', 'Value', 'What it does'].map((h, i) => el('th', { class: i === 1 ? 'num' : '' }, h))),
        [['Elo K-factor', String(E.ELO_K), 'How hard one result moves a rating (World Football Elo convention)'],
         ['Logistic divisor', String(E.LOGISTIC_DIV), 'How sharply a rating gap becomes a win probability'],
         ['Host bonus', '+' + E.HOST_BONUS, 'Rating points for a host nation playing at home'],
         ['xG temper weight', String(E.XG_TEMPER), 'How much the chances created (not the scoreline) drive a rating update'],
         ['Monte-Carlo runs', '10,000', 'Tournaments simulated per refresh'],
         ['Random seed', 'fixed', 'So the published numbers are stable and what-if deltas are real, not noise']].map(r =>
          el('tr', null, el('td', null, r[0]), el('td', { class: 'num' }, el('b', null, r[1])), el('td', { class: 'muted' }, r[2]))))));

    root.append(card('The Elo ratings, and the xG twist',
      P('Ratings update with the World Football Elo rule: the change is the K-factor (', String(E.ELO_K), ') times a goal-difference multiplier times the gap between the result and what the ratings expected. Beating a much stronger side moves you more than beating a minnow, because the model expected you to lose.'),
      P(el('b', null, 'The twist we added. '), 'A scoreline can lie. Germany beat Curaçao 7-1, but the shots were worth only about 3.9 expected goals. Rewarding that as a true six-goal rout would over-rate Germany. So the margin that drives the rating update is now a blend of the actual goal difference and the expected-goal difference (weighted ', String(E.XG_TEMPER), ' toward xG). The winner is still the winner; only how much it moves the ratings is tempered by how many real chances were created.')));

    root.append(card('From a rating gap to a result',
      P(el('b', null, 'Match odds. '), 'The win probability is a logistic function of the rating difference; the draw probability rises as two sides get closer (bounded between 17% and 30%, because real draw rates live in that band). ',
        el('b', null, 'Goals. '), 'Each side’s expected goals come from the same rating gap, then a Poisson distribution turns that into scoreline probabilities. This is where “most likely scorelines” on each match card come from.')));

    root.append(card('Why simulate 10,000 times (Monte Carlo)',
      P('You cannot calculate the future of a 104-match tournament directly; there are far too many branching paths. So the computer simply plays it out, ten thousand times, and counts. Each run plays every remaining group game, ranks the tables, draws the 32-team bracket (third-place qualifiers and all), and resolves every knockout tie including extra time and a penalty shootout, all the way to a champion. The percentages are just how often each outcome happened across the ten thousand runs, and the “±” you see is the give-or-take from running ten thousand experiments rather than infinity. A fixed random seed keeps the published figures stable and makes the what-if mode’s changes real rather than simulation jitter.')));

    root.append(card('Did we need to buy the market? The backtest',
      P('A subscription to a professional data feed gives us the bookmakers’ own probabilities (their closing odds, with the bookmaker’s margin removed). The bookmakers, Pinnacle especially, are the sharpest forecasters in football. So the honest question was: does our homemade model add anything, or should we just show the market’s numbers?'),
      P('We tested it properly. For each of the ', String(played), ' matches played so far, we took the model’s pre-match probabilities (using only earlier results, no peeking) and the market’s closing probabilities, and scored both against what actually happened, using log-loss and the Brier score. Both reward confident correct calls and punish confident wrong ones; lower is sharper.'),
      el('table', null,
        el('tr', null, ['Metric (lower = sharper)', 'Our model', 'Market'].map((h, i) => el('th', { class: i ? 'num' : '' }, h))),
        el('tr', null, el('td', null, 'Log-loss'), el('td', { class: 'num' }, el('b', null, '0.98')), el('td', { class: 'num' }, '1.04')),
        el('tr', null, el('td', null, 'Brier score'), el('td', { class: 'num' }, el('b', null, '0.58')), el('td', { class: 'num' }, '0.64'))),
      P(el('b', null, 'The honest verdict. '), 'The market was not sharper than our model. It was actually a touch worse on these games, but the sample is tiny (about ten matches) and that gap is well within noise, so the truthful claim is that the two are comparable, not that we beat Pinnacle. That a homemade model can sit level with the sharpest book in the world is the result worth bragging about.'),
      P(el('b', null, 'Why it can. '), 'Two reasons. First, our base ratings are themselves seeded from data the market has already digested, so we are not starting from scratch. Second, the opening round was chaos: the market had Switzerland firm favourites against Qatar (it finished 1-1) and Türkiye over Australia (Australia won), and a confident wrong call is punished hard, so the market’s very confidence cost it on the upsets. ',
        el('b', null, 'What we did with the finding. '), 'We did not throw away our model to chase the market. Instead the market line is shown on each match as a reference, and the paid feed’s real value, the expected-goals data, is used to temper the rating updates as described above. We bought sharper inputs, not a replacement brain.')));

    root.append(card('Where the data comes from, and what the model cannot see',
      P('Live scores come from a free public feed (ESPN), checked every couple of hours during the match window. Expected goals, bookmaker odds and player stats come from a paid feed (TheStatsAPI), refreshed once a day. The site itself is a single self-contained page that updates in the background automatically. ',
        el('b', null, 'Its blind spots, stated plainly: '), 'the model knows only results. It cannot see injuries, suspensions, team-sheets, travel, weather or morale, which is one honest reason its numbers differ a little from the bookmakers’. It does not pretend otherwise.')));

    root.append(P('Built by Mohammed with Claude. Questions, corrections and arguments all welcome.'));
  }

  function renderModel(root) {
    const nLocal = Object.keys(localOv).length;
    // methodology
    root.append(el('div', { class: 'card', style: 'margin-bottom:14px' },
      el('h3', null, 'How the numbers are made'),
      el('p', { class: 'muted', style: 'margin-bottom:8px' },
        'One engine produces every probability on this site. Each team carries an Elo-style rating (seeded from FIFA rankings as of 11 June 2026). Every completed result updates ratings live (K=' + E.ELO_K + ', margin-weighted), so form flows through the tournament. Match odds come from a logistic curve on the rating difference with a strength-dependent draw rate; goals are Poisson with rating-derived expected goals; hosts get +' + E.HOST_BONUS + ' rating points at home. The whole tournament — remaining group games, third-place qualification, the full bracket, extra time, penalties — is then simulated 10,000 times with a fixed seed, and the title, stage and qualification percentages are simply counts over those runs, quoted with a 95% band.'),
      el('p', { class: 'muted' },
        'What the model does not know: injuries, suspensions, lineups, or anything not visible in results. For upcoming games the "model xG" is synthetic (rating-derived); played games also show actual xG from shot data (TheStatsAPI), which now tempers the Elo update so a flattering scoreline like 7-1 moves ratings by the chances created rather than by the goals. Each match also shows the market’s closing line for comparison, though the model runs on its own ratings (a backtest on the first 12 games found the market no sharper than the model, so it informs rather than drives). The 11 June timeline baseline is an external blend (market and rating models) and is labelled as such; everything after it is this engine.')),
      el('div', { class: 'card', style: 'margin-bottom:14px' },
        el('h3', null, 'Model v market', el('span', { class: 'right' }, 'pre-tournament reference')),
        el('table', null,
          el('tr', null, ['Team', 'Model now', 'Blend 11 Jun', 'Market 11 Jun'].map((h, i) => el('th', { class: i ? 'num' : '' }, h))),
          Object.entries(SIM.teams).sort((a, b) => b[1].champ - a[1].champ).slice(0, 15).map(([c, s]) =>
            el('tr', null, el('td', null, flagName(c)),
              el('td', { class: 'num' }, el('b', null, pct(s.champ))),
              el('td', { class: 'num' }, T[c].preProb ? T[c].preProb.toFixed(1) + '%' : '—'),
              el('td', { class: 'num' }, T[c].marketProb ? T[c].marketProb.toFixed(1) + '%' : '—')))),
        el('p', { class: 'tiny', style: 'margin-top:8px' },
          'A pure rating simulation spreads probability more evenly than markets do; the gap is the model’s scepticism about favourites, not an error. Both columns are kept so you can judge.')));

    // update console
    const sel = el('select', null, D.matches.filter(m => m.status !== 'completed')
      .sort((a, b) => a.dateET.localeCompare(b.dateET))
      .map(m => el('option', { value: m.id }, m.id + ' · ' + T[m.team1].code + ' v ' + T[m.team2].code + ' · ' + fmtD(m.dateET, localTZ))));
    const a = el('input', { type: 'number', min: 0, max: 9, style: 'width:60px', placeholder: '0' });
    const b = el('input', { type: 'number', min: 0, max: 9, style: 'width:60px', placeholder: '0' });
    const ta = el('textarea', { placeholder: '{"M003": [2, 1], "M004": [0, 0]}' });
    root.append(el('div', { class: 'card no-print', style: 'margin-bottom:14px' },
      el('h3', null, 'Update console', el('span', { class: 'right' }, nLocal + ' local result' + (nLocal === 1 ? '' : 's'))),
      el('div', { class: 'formrow' }, sel, a, el('span', null, '–'), b,
        el('button', {
          class: 'btn small', onclick: () => {
            const g1 = parseInt(a.value, 10), g2 = parseInt(b.value, 10);
            if (isNaN(g1) || isNaN(g2)) return;
            const tgt = whatIf.on ? whatIf.ov : localOv;
            tgt[sel.value] = [g1, g2];
            if (!whatIf.on) lsSet(LS.ov, localOv);
            refresh();
          }
        }, 'Apply result')),
      el('div', { class: 'formrow' }, ta),
      el('div', { class: 'formrow' },
        el('button', {
          class: 'btn small ghost', onclick: () => {
            try {
              const o = JSON.parse(ta.value);
              const tgt = whatIf.on ? whatIf.ov : localOv;
              for (const k in o) if (Array.isArray(o[k]) && o[k].length === 2) tgt[k] = o[k];
              if (!whatIf.on) lsSet(LS.ov, localOv);
              ta.value = ''; refresh();
            } catch (e) { alert('Could not parse that JSON.'); }
          }
        }, 'Apply JSON patch'),
        nLocal ? el('button', { class: 'btn small ghost', onclick: () => { localOv = {}; lsSet(LS.ov, localOv); refresh(); } }, 'Clear local results') : null,
        el('button', {
          class: 'btn small ghost', onclick: () => {
            const blob = new Blob([JSON.stringify({ asOf: new Date().toISOString(), localResults: localOv }, null, 1)], { type: 'application/json' });
            const u = URL.createObjectURL(blob);
            const link = el('a', { href: u, download: 'wc26-local-results.json' }); document.body.append(link); link.click(); link.remove();
          }
        }, 'Export local results'),
        el('button', { class: 'btn small ghost', onclick: () => window.print() }, 'Print this view')),
      el('p', { class: 'tiny' },
        'Results entered here apply on this device immediately (every probability recomputes). The published site is updated by Mohammed: scores are patched into the data, the engine re-runs, a timeline snapshot is recorded, and the new build goes live for everyone.')));

    root.append(el('div', { class: 'card' },
      el('h3', null, 'Data'),
      el('p', { class: 'muted' }, 'Snapshot: ' + D.meta.asOf + ' · ' + D.meta.asOfNote),
      el('div', { class: 'muted', style: 'margin-top:6px' }, 'Sources: ',
        D.meta.sources.map((s, i) => el('span', null, i ? ' · ' : '', el('a', { href: s.url, target: '_blank' }, s.name))))));
  }

  function renderAbout(root) {
    const P = (...kids) => el('p', { class: 'muted', style: 'margin-bottom:9px' }, ...kids);
    root.append(
      el('div', { class: 'card', style: 'margin-bottom:14px' },
        el('h3', null, 'What this site is'),
        P('A live probability centre for the 2026 World Cup. Every number on it comes from one statistical model that re-runs whenever a result comes in, so the percentages you see always reflect the tournament as it actually stands. It is a personal analytics project (the MAS monogram in the corner), not an official FIFA product, and the numbers are estimates for following the tournament, not betting advice.')),

      el('div', { class: 'card', style: 'margin-bottom:14px' },
        el('h3', null, 'The tabs, in one line each'),
        el('table', null, [
          ['Today', 'today’s fixtures in your local time, the latest results, the title race, the MENA strip and the player watch'],
          ['Matches', 'every fixture day by day; click any match for its detailed odds and most likely scorelines'],
          ['Groups', 'all twelve group tables: real standings plus the model’s projected points and qualification chances'],
          ['Bracket', 'one most-likely path from the Round of 32 to the champion; the favourite in every tie'],
          ['Teams', 'all 48 teams, sortable; click a team for its "glory funnel" from group stage to trophy'],
          ['MENA', 'the nine Middle East and North Africa sides, tracked together'],
          ['League', 'the family predictions game: make picks, send the code, follow the leaderboard'],
          ['Timeline', 'how each contender’s title chance has risen and fallen across the tournament'],
          ['Venues', 'the sixteen stadiums across the three host countries'],
          ['Model & Updates', 'the technical description of the model, the model-versus-market table, and the console for entering results'],
        ].map(([k, v]) => el('tr', null, el('td', { style: 'white-space:nowrap' }, el('b', null, k)), el('td', { class: 'muted' }, v))))),

      el('div', { class: 'card', style: 'margin-bottom:14px' },
        el('h3', null, 'The probabilities, explained simply'),
        P(el('b', null, '1. Every team has a strength number. '), 'Like a chess rating: Spain’s is high, New Zealand’s is low. The starting numbers come from the FIFA world rankings. Every match changes them: win and your number goes up, lose and it goes down, and a thrashing moves it more than a narrow squeak. Beating a giant earns far more than beating a minnow. So the ratings quietly learn from the tournament as it happens; South Korea’s rating already rose for their comeback win.'),
        P(el('b', null, '2. The gap between two strength numbers sets the odds of one match. '), 'When two teams meet, the model compares their numbers. A big gap means the stronger side wins most of the time; a small gap means it is close to a coin flip, with a healthy chance of a draw. The gap also says how many goals each side should expect to score, on average.'),
        P(el('b', null, '3. Goals are dice rolls. '), 'Football is low-scoring and luck matters. So instead of declaring "this will finish 2-1", the model treats goals like rolls of a loaded dice: a team expected to score 1.8 goals sometimes scores 0, usually 1 or 2, occasionally 4. (The mathematical name for this is a Poisson distribution; the dice picture is honestly all you need.)'),
        P(el('b', null, '4. Then we play the whole World Cup 10,000 times. '), 'This is the heart of it, and it is called a Monte Carlo simulation, named after the casino. Nobody can calculate the future of a 104-match tournament directly; there are too many combinations. So the computer simply plays it out: every remaining match decided by those dice rolls, group tables computed, the bracket drawn, extra time and penalty shootouts included, all the way to a champion being crowned. Then it does that again. And again, ten thousand times. Spain lifting the trophy in roughly 700 of those 10,000 imaginary tournaments is exactly what "Spain 7%" means on the Today tab. No mystery: the percentage is just counting.'),
        P(el('b', null, '5. The small print, honestly. '), 'Host nations get a modest ratings boost when playing at home, because history says it is real. The "±" you see next to title chances is the give-or-take from running 10,000 experiments rather than infinity. And the model only knows results: it cannot see injuries, suspensions, team sheets or dressing-room moods, which is one reason its numbers differ a little from the bookmakers’ (the Model tab shows both side by side, so you can judge).')),

      el('div', { class: 'card' },
        el('h3', null, 'Where the data comes from'),
        P('Fixtures, rankings and venues were loaded from FIFA’s published schedule. Results flow in automatically three ways: while a match is being played, the page itself checks the public scores feed every few minutes and shows a red LIVE tag with the score; when a match finishes, the final score is applied and every probability recomputes on the spot; and a small robot republishes the site for everyone every couple of hours during the match window. The “↻ Scores” button forces an immediate check any time you ask. Built and maintained by Mohammed Al-Sabah’s analytics setup, June 2026.')));
  }

  // ---------- live overlay: the page keeps itself current during match windows ----------
  let liveNow = {};   // matchId -> {g1, g2, clock} display-only; finals flow through localOv
  const etDate = m => m.dateET.slice(0, 10).replace(/-/g, '');   // dateET already carries the Eastern offset

  async function pollLive() {
    // only bother when a fixture is near: kickoff within the last 4h or the next hour
    const now = Date.now();
    const near = D.matches.filter(m => {
      if (effScore(m)) return false;
      const ko = new Date(m.dateET).getTime();
      return now >= ko - 3600e3 && now <= ko + 4 * 3600e3;
    });
    if (!near.length) { if (Object.keys(liveNow).length) { liveNow = {}; renderHeader(); renderTab(); } return; }
    try {
      const days = [...new Set(near.map(etDate))].sort();
      const rng = days.length === 1 ? days[0] : days[0] + '-' + days[days.length - 1];
      const r = await fetch('https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=' + rng);
      const js = await r.json();
      const ids = (typeof WC_ESPNMAP !== 'undefined' && WC_ESPNMAP.teamIds) || {};
      const fresh = {};
      let finals = 0;
      for (const e of (js.events || [])) {
        const st = e.status && e.status.type;
        if (!st) continue;
        const sc = {};
        for (const c of e.competitions[0].competitors) {
          const code = ids[String(c.team.id)] || c.team.abbreviation;
          sc[code] = parseInt(c.score, 10);
        }
        const match = near.find(m => sc[m.team1] != null && sc[m.team2] != null);
        if (!match) continue;
        if (st.state === 'in') {
          fresh[match.id] = { g1: sc[match.team1], g2: sc[match.team2], clock: st.shortDetail || '' };
        } else if (st.name === 'STATUS_FULL_TIME' && st.completed && !localOv[match.id]) {
          const g1 = sc[match.team1], g2 = sc[match.team2];
          if (g1 >= 0 && g1 <= 15 && g2 >= 0 && g2 <= 15) { localOv[match.id] = [g1, g2]; finals++; }
        }
      }
      const changedLive = JSON.stringify(fresh) !== JSON.stringify(liveNow);
      liveNow = fresh;
      if (finals) { lsSet(LS.ov, localOv); refresh(); toast(finals + ' final score' + (finals === 1 ? '' : 's') + ' came in; probabilities recomputed.'); }
      else if (changedLive) { renderHeader(); renderTab(); }
    } catch (err) { /* silent: the live overlay is best-effort */ }
  }
  setInterval(pollLive, 180000);

  // ---------- live score refresh (ESPN public feed, CORS-open) ----------
  let toastTimer = null;
  function toast(msg) {
    document.querySelectorAll('.toast').forEach(n => n.remove());
    const t = el('div', { class: 'toast' }, msg);
    document.body.append(t);
    requestAnimationFrame(() => t.classList.add('show'));
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.classList.remove('show'); setTimeout(() => t.remove(), 300); }, 4200);
  }

  async function refreshScores() {
    const btn = document.getElementById('refresh');
    btn.disabled = true; btn.textContent = 'Checking…';
    try {
      const now = new Date();
      const pending = D.matches.filter(m => m.status !== 'completed' && !localOv[m.id] &&
        new Date(m.dateET) <= now && (now - new Date(m.dateET)) < 96 * 3600e3);
      if (!pending.length) { toast('No matches awaiting results right now.'); return; }
      const days = [...new Set(pending.map(etDate))].sort();
      const rng = days.length === 1 ? days[0] : days[0] + '-' + days[days.length - 1];
      const r = await fetch('https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=' + rng);
      const js = await r.json();
      const ids = (typeof WC_ESPNMAP !== 'undefined' && WC_ESPNMAP.teamIds) || {};
      let n = 0;
      for (const e of (js.events || [])) {
        const st = e.status && e.status.type;
        if (!st || st.name !== 'STATUS_FULL_TIME' || !st.completed) continue;
        const sc = {};
        for (const c of e.competitions[0].competitors) {
          const code = ids[String(c.team.id)] || c.team.abbreviation;
          sc[code] = parseInt(c.score, 10);
        }
        const match = pending.find(m => sc[m.team1] != null && sc[m.team2] != null);
        if (!match) continue;
        const g1 = sc[match.team1], g2 = sc[match.team2];
        if (!(g1 >= 0 && g1 <= 15 && g2 >= 0 && g2 <= 15)) continue;
        localOv[match.id] = [g1, g2]; n++;
      }
      if (n) { lsSet(LS.ov, localOv); refresh(); }
      toast(n ? n + ' new result' + (n === 1 ? '' : 's') + ' pulled; all probabilities recomputed.'
              : 'Feed reached; no new final scores yet.');
    } catch (err) {
      toast('Could not reach the scores feed; try again in a minute.');
    } finally {
      btn.disabled = false; btn.textContent = '↻ Scores';
    }
  }

  // ---------- shell ----------
  function refresh() {
    recompute();
    renderHeader();
    renderTab();
  }
  function renderHeader() {
    const asof = document.getElementById('asof');
    const nLocal = Object.keys(localOv).length;
    const nLive = Object.keys(liveNow).length;
    asof.innerHTML = 'Data as of ' + D.meta.asOf +
      (nLocal && !whatIf.on ? '<br>+' + nLocal + ' local result' + (nLocal === 1 ? '' : 's') : '') +
      (nLive ? '<br><b>● LIVE: ' + nLive + ' match' + (nLive === 1 ? '' : 'es') + '</b>' : '<br>10,000-run Monte Carlo');
    const wbtn = document.getElementById('whatif');
    wbtn.textContent = whatIf.on ? 'What-if mode ON — exit' : 'What-if';
    wbtn.className = 'whatif-pill' + (whatIf.on ? '' : ' off');
    const ban = document.getElementById('banner');
    if (whatIf.on) {
      const n = Object.keys(whatIf.ov).length;
      ban.style.display = 'flex';
      ban.replaceChildren(
        el('span', null, '⚠︎ What-if mode: ' + n + ' hypothetical result' + (n === 1 ? '' : 's') + ' applied. Nothing is saved; exit to snap back to reality.'),
        el('button', { class: 'btn small ghost', onclick: () => { whatIf.ov = {}; refresh(); } }, 'Reset what-ifs'));
    } else ban.style.display = 'none';
  }
  function renderTab() {
    const root = document.getElementById('view');
    root.innerHTML = '';
    document.querySelectorAll('nav button').forEach(b => b.classList.toggle('active', b.dataset.tab === activeTab));
    ({
      today: renderToday, matches: renderMatches, groups: renderGroups, bracket: renderBracket,
      teams: renderTeams, mena: renderMena, join: renderJoin, league: renderLeague, compare: renderCompare, timeline: renderTimeline,
      venues: renderVenues, model: renderModel, about: renderAbout, geeks: renderGeeks,
    })[activeTab](root);
    window.scrollTo(0, 0);
  }

  function init() {
    const nav = document.getElementById('nav');
    tabs.forEach(([id, label]) => nav.append(el('button', {
      'data-tab': id, onclick: () => { activeTab = id; lsSet(LS.tab, id); history.replaceState(null, '', '#' + id); renderTab(); }
    }, label)));
    // shareable tab links: #league opens the league directly
    const fromHash = (location.hash || '').slice(1);
    if (tabs.some(([id]) => id === fromHash)) activeTab = fromHash;
    window.addEventListener('hashchange', () => {
      const h = (location.hash || '').slice(1);
      if (tabs.some(([id]) => id === h) && h !== activeTab) { activeTab = h; renderTab(); }
    });
    setTimeout(pollLive, 2500);
    document.getElementById('refresh').addEventListener('click', refreshScores);
    document.getElementById('whatif').addEventListener('click', () => {
      whatIf.on = !whatIf.on;
      if (!whatIf.on) whatIf.ov = {};
      refresh();
    });
    document.getElementById('view').append(el('div', { class: 'spin' }, 'Running 10,000 tournament simulations…'));
    setTimeout(refresh, 30);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
