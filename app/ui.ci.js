/* A card's CI page (c-642, keel/ciroute.py, docs/atlas/66-ci.md).
 *
 * `/ci/<c-id>`, drawn on the plan page's shell (app/plan.html) so its header switches to the
 * card's plan and outcome as they switch to each other (`K.docTabs`, c-644). Its data is
 * `/api/ci/<id>`: the card's pull requests' checks, and the CI server's builds of the shared
 * branches that carry its work, each with its stages and, for a failed one, the end of the
 * failed step's log. It is read when the page opens and on Refresh, never polled: the
 * server reads two services for it, and nothing here is kept between looks.
 */
(function (K) {
  'use strict';
  var el = K.el;

  var STYLE = [
    '.ci-sum{font-size:15px;line-height:1.5;margin:8px 0 18px}',
    '.ci-sec{margin:20px 0}',
    '.ci-sec>h2{font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);margin:0 0 8px}',
    '.ci-row{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;padding:10px 12px;border:1px solid var(--hair);border-radius:var(--r);background:var(--s1);margin-bottom:8px}',
    '.ci-row .ci-what{font-weight:600}',
    '.ci-row .ci-when{font-family:var(--mono);font-size:11px;color:var(--ink-3)}',
    '.ci-row .ci-why{flex-basis:100%;font-size:12px;color:var(--ink-2)}',
    '.ci-stages{flex-basis:100%;display:flex;flex-wrap:wrap;gap:4px}',
    '.ci-stage{font-size:11px;padding:2px 8px;border-radius:var(--pill);background:var(--s2);color:var(--ink-2)}',
    '.ci-stage.ok{background:var(--good-soft);color:var(--good)}',
    '.ci-stage.bad{background:var(--crit-soft);color:var(--crit)}',
    '.ci-log{flex-basis:100%;margin:6px 0 0;max-height:320px;overflow:auto;font-family:var(--mono);font-size:11px;line-height:1.45;white-space:pre-wrap;word-break:break-word;background:var(--canvas);border:1px solid var(--hair);border-radius:var(--r);padding:8px}',
    '.ci-notes{font-size:12px;color:var(--ink-3)}',
    '.ci-notes li{margin:2px 0}',
    '@media (max-width:719px){.ci-row{padding:10px}.ci-refresh{min-height:44px}}'
  ].join('');

  var S = { id: null, data: null, error: null, loading: false, pending: null };
  var RESULT = { SUCCESS: ['passed', 'tone-good'], SUCCESSFUL: ['passed', 'tone-good'], FAILURE: ['failed', 'tone-crit'],
                 FAILED: ['failed', 'tone-crit'], STOPPED: ['stopped', 'tone-warn'], ABORTED: ['stopped', 'tone-warn'],
                 UNSTABLE: ['unstable', 'tone-warn'], INPROGRESS: ['running', 'tone-accent'] };

  function style() {
    if (document.getElementById('ci-style')) return;
    var s = document.createElement('style');
    s.id = 'ci-style';
    s.textContent = STYLE;
    document.head.appendChild(s);
  }

  function load(id) {
    /* one read at a time: a second tap, or the shell's own load, waits on the first */
    if (S.loading && S.id === id) return S.pending;
    S.id = id; S.loading = true; S.error = null;
    S.pending = fetch('/api/ci/' + id, { cache: 'no-store' })
      .then(function (r) {
        /* a proxy's HTML error page is said as its status, not as a parser's complaint */
        return r.json().catch(function () { throw new Error('the deck answered HTTP ' + r.status); })
          .then(function (d) { if (!r.ok) throw new Error(d.error || 'the CI page did not load'); return d; });
      })
      .then(function (d) {
        /* the card's space's words (c-630), as the plan page sets them */
        if (d.card && d.card.space && d.card.terms) K.cardTerms[d.card.space] = d.card.terms;
        /* and its palette, as the plan page wears it (r2.F7) */
        if (d.card && d.card.space && K.wearSpace) K.wearSpace(d.card.space);
        S.data = d; S.loading = false; document.title = id + ' CI'; K.renderBody();
      })
      .catch(function (e) { S.error = e.message; S.loading = false; K.renderBody(); });
    return S.pending;
  }

  function word(state) { return RESULT[String(state || '').toUpperCase()] || [String(state || 'unknown').toLowerCase(), '']; }
  function chip(state, building) {
    var w = building ? ['running', 'tone-accent'] : word(state);
    return el('span', { class: 'chip ' + w[1], text: w[0] });
  }
  function ms(n) {
    if (!n) return '';
    var m = Math.round(n / 60000);
    return m < 1 ? Math.round(n / 1000) + 's' : m + ' min';
  }
  function at(stamp) {
    if (!stamp) return '';
    var iso = typeof stamp === 'number' ? new Date(stamp).toISOString() : stamp;
    return K.ago ? K.ago(iso) : iso;
  }

  function say(space, template) { return K.say ? K.say(space, template) : template; }

  function summary(ci, space) {
    var b = ci.builds || [], checks = ci.checks || [];
    var parts = [];
    if (b.length) {
      var last = b[0];
      parts.push(last.branch + ' #' + last.number + ' ' + (last.building ? 'running' : word(last.result)[0]) +
        (last.started ? ' ' + at(last.started) : ''));
    } else {
      parts.push('no build of a shared branch carries this card yet');
    }
    var states = [].concat.apply([], checks.map(function (c) { return c.statuses || []; })).map(function (s) { return word(s.state)[0]; });
    if (checks.length) parts.push(say(space, 'the {change}\'s checks: ') + (states.length ? counted(states) : 'none report'));
    return el('p', { class: 'ci-sum', 'data-key': 'ci-sum', text: parts.join('; ') + '.' });
  }

  /* "2 passed, 1 failed, 1 running": each word counted, in that order, then any other */
  function counted(states) {
    var n = {};
    states.forEach(function (s) { n[s] = (n[s] || 0) + 1; });
    var order = ['failed', 'running', 'passed'].concat(Object.keys(n).filter(function (s) { return ['failed', 'running', 'passed'].indexOf(s) < 0; }));
    return order.filter(function (s) { return n[s]; }).map(function (s) { return n[s] + ' ' + s; }).join(', ');
  }

  function checkRows(ci) {
    var rows = [];
    (ci.checks || []).forEach(function (c) {
      /* a node per row: one node in two rows is drawn in the last only */
      function head() { return el('a', { class: 'ci-what', href: c.url, target: '_blank', rel: 'noopener', text: c.repo + ' #' + c.pr }); }
      if (!(c.statuses || []).length) {
        rows.push(el('div', { class: 'ci-row', 'data-key': 'check-' + c.repo }, head(), el('span', { class: 'ci-why', text: 'no check reports on its head' })));
      }
      (c.statuses || []).forEach(function (s, i) {
        rows.push(el('div', { class: 'ci-row', 'data-key': 'check-' + c.repo + '-' + i }, head(), chip(s.state),
          s.url ? el('a', { href: s.url, target: '_blank', rel: 'noopener', text: s.name || 'check' }) : el('span', { text: s.name || 'check' }),
          el('span', { class: 'ci-when', text: at(s.updated) })));
      });
    });
    return rows;
  }

  function why(m) {
    if (!m) return '';
    var said = [];
    if (m.commits) said.push('carries ' + m.commits + ' of the card\'s commits');
    if (m.ref) said.push('names ' + m.ref);
    return said.join(', ');
  }

  function buildRow(b) {
    var stages = (b.stages || []).map(function (s) {
      var tone = s.status === 'SUCCESS' ? ' ok' : s.status === 'FAILED' ? ' bad' : '';
      return el('span', { class: 'ci-stage' + tone, title: s.status + (s.ms ? ', ' + ms(s.ms) : ''), text: s.name });
    });
    return el('div', { class: 'ci-row', 'data-key': 'build-' + b.repo + '-' + b.branch + '-' + b.number },
      el('a', { class: 'ci-what', href: b.url, target: '_blank', rel: 'noopener', text: b.repo + ' ' + b.branch + ' #' + b.number }),
      chip(b.result, b.building),
      el('span', { class: 'ci-when', text: [at(b.started), ms(b.duration)].filter(Boolean).join(' · ') }),
      el('span', { class: 'ci-why', text: why(b.matched) }),
      stages.length ? el('div', { class: 'ci-stages' }, stages) : null,
      (b.log || []).length ? el('pre', { class: 'ci-log', 'data-key': 'log-' + b.number, text: b.log.join('\n') }) : null,
      b.log_note ? el('span', { class: 'ci-why', 'data-key': 'log-note-' + b.number, text: b.log_note }) : null);
  }

  function head(d) {
    var card = d.card;
    return el('header', { class: 'phead', 'data-key': 'head' },
      K.docTabs ? K.docTabs(card, d.docs || [], 'ci') : null,
      el('div', { class: 'phead-line' },
        el('a', { class: 'pback', href: '/?view=cards&card=' + card.id + (card.space ? '&space=' + card.space : ''),
          'aria-label': 'back to ' + card.id + ' in the deck' }, '‹ ' + card.id),
        card.space ? el('span', { class: 'chip space-' + card.space, text: card.space }) : null,
        el('span', { class: 'pdocword label', text: 'CI' }),
        el('span', { class: 'spacer' }),
        el('button', { class: 'btn sm ci-refresh', 'data-key': 'ci-refresh', disabled: S.loading ? true : null,
          onclick: function () { load(card.id); K.renderBody(); } }, S.loading ? 'Reading…' : 'Refresh')),
      el('h1', { class: 'ptitle', text: card.title }),
      K.flowBar ? K.flowBar(card, d.moves) : null);
  }

  function viewCi(id) {
    style();
    if (S.id !== id) { S.data = null; S.error = null; S.loading = false; S.id = id; }
    if (!S.data && !S.error && !S.loading) load(id);
    var d = S.data;
    /* a first read that failed still has the header: back to the deck, and Refresh (r2.F3) */
    /* the card's space is not known until a read answers: no chip, and the deck picks it */
    if (S.error && !d) return page(head({ card: { id: id, space: '', title: '' }, docs: [] }),
      el('div', { class: 'empty', 'data-key': 'ci-error', text: 'The CI page did not load: ' + S.error }));
    var failed = S.error ? el('div', { class: 'empty', 'data-key': 'ci-error', text: 'The last read failed: ' + S.error }) : null;
    if (!d) return page(el('div', { class: 'empty', text: 'reading the builds of ' + id + '…' }));
    if (!d.ci) return page(head(d), failed, el('div', { class: 'empty', 'data-key': 'ci-why', text: d.why || 'nothing to show' }));
    var ci = d.ci, builds = ci.builds || [];
    return page(head(d), failed, summary(ci, d.card.space),
      el('section', { class: 'ci-sec', 'data-key': 'ci-checks' }, el('h2', { text: say(d.card.space, '{Change} checks') }),
        (ci.checks || []).length ? checkRows(ci) : el('div', { class: 'ci-notes', text: 'none yet' })),
      el('section', { class: 'ci-sec', 'data-key': 'ci-builds' }, el('h2', { text: 'Builds that carry it' }),
        builds.length ? builds.map(buildRow) : el('div', { class: 'ci-notes', text: say(d.card.space, 'none yet: a build shows here once a shared branch carries the card\'s commits or names its {ticket}') })),
      (ci.notes || []).length ? el('ul', { class: 'ci-notes', 'data-key': 'ci-notes' }, ci.notes.map(function (n) { return el('li', { text: n }); })) : null,
      el('div', { class: 'ci-notes', text: 'Read ' + at(d.at) + '.' }));
  }
  function page() {
    return el('section', { class: 'planroute', 'data-doc': 'ci' },
      el('div', { class: 'plan-body' }, Array.prototype.slice.call(arguments)));
  }

  K.viewCi = viewCi;
  K.loadCi = function () { return S.id ? load(S.id) : Promise.resolve(); };
  K.ciState = S;      /* for the node fixture */
})(window.Keel);
