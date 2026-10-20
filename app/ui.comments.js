/* A card's review comments page (c-643, keel/commentsroute.py, docs/atlas/67-comments.md).
 *
 * `/comments/<c-id>`, drawn on the plan page's shell (app/plan.html), so its header switches
 * to the card's plan, outcome and CI as they switch to it (`K.docTabs`, c-644). Its data is
 * `/api/comments/<id>`: every item the card's house was told at shipping, grouped by the round
 * it was told in, newest first, each with the house's verdict, its commits and the reply it
 * drafted. The rows and Ship are the pane's own (`K.shipping.row`, `K.shipping.shipButton`,
 * app/ui.shipping.js), so Post, Edit, Drop and Ship send exactly what the pane sent. Send back
 * (c-663) is the pane's too: his own notes for the house, which wait here in his words until
 * it is told and then are a row marked as his, with its answer and nothing to post. The data
 * is the board's alone, so a board event reads it again (`K.loadPlan` hands it here).
 */
(function (K) {
  'use strict';
  var el = K.el;

  var STYLE = [
    '.cm-sum{font-size:15px;line-height:1.5;margin:8px 0 14px}',
    '.cm-ship{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;margin:10px 0 18px}',
    '.cm-round{margin:22px 0}',
    '.cm-round>h2{font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);margin:0 0 8px}',
    '.cm-round .shiprow{padding:12px;border:1px solid var(--hair);border-radius:var(--r);background:var(--s1);margin-bottom:10px}',
    /* a long comment scrolls in its own box, so the verdict and the reply stay in reach */
    '.cm-round .shiprow .reading.quote{white-space:pre-wrap;word-break:break-word;max-height:360px;overflow:auto}',
    '.cm-notes{font-size:12px;color:var(--ink-3)}',
    '@media (max-width:719px){.cm-round .shiprow{padding:10px}.cm-ship .btn{min-height:44px}}'
  ].join('');

  var S = { id: null, data: null, error: null, loading: false, pending: null, again: false };

  function style() {
    if (document.getElementById('cm-style')) return;
    var s = document.createElement('style');
    s.id = 'cm-style';
    s.textContent = STYLE;
    document.head.appendChild(s);
  }

  /* One read at a time; a board event while one is on its way reads once more after it.
     A re-read keeps the header's pages it has (`again=1`), so the plan is not read on every
     event; they are read again when the card's stage moves (an outcome is written at a
     gate), when the last list was empty (a plan read that failed), and on `whole`. */
  function load(id, whole) {
    if (S.loading && S.id === id) { S.again = true; return S.pending; }
    /* a whole read that failed is owed: the next read is whole (never retried at once) */
    whole = whole || S.owed;
    var again = !whole && !!(S.data && S.id === id && (S.data.docs || []).length);
    S.id = id; S.loading = true; S.error = null;
    S.pending = fetch('/api/comments/' + id + (again ? '?again=1' : ''), { cache: 'no-store' })
      .then(function (r) {
        return r.json().catch(function () { throw new Error('the deck answered HTTP ' + r.status); })
          .then(function (d) { if (!r.ok) throw new Error(d.error || 'the comments page did not load'); return d; });
      })
      .then(function (d) {
        if (d.card && d.card.space && d.card.terms) K.cardTerms[d.card.space] = d.card.terms;
        if (d.card && d.card.space && K.wearSpace) K.wearSpace(d.card.space);
        var moved = d.docs === null && S.data && S.data.card.stage !== d.card.stage;
        if (d.docs === null && S.data) d.docs = S.data.docs;
        S.data = d; S.loading = false; document.title = id + ' comments'; K.renderBody();
        if (whole) S.owed = false;
        if (moved) S.whole = true;
      })
      .catch(function (e) { if (whole) S.owed = true; S.error = e.message; S.loading = false; K.renderBody(); })
      .then(function () {
        if (S.again || S.whole) { var w = S.whole; S.again = false; S.whole = false; return load(id, w); }
      });
    return S.pending;
  }

  function head(d) {
    var card = d.card;
    return el('header', { class: 'phead', 'data-key': 'head' },
      K.docTabs ? K.docTabs(card, d.docs || [], 'comments') : null,
      el('div', { class: 'phead-line' },
        el('a', { class: 'pback', href: '/?view=cards&card=' + card.id + (card.space ? '&space=' + card.space : ''),
          'aria-label': 'back to ' + card.id + ' in the deck' }, '‹ ' + card.id),
        card.space ? el('span', { class: 'chip space-' + card.space, text: card.space }) : null,
        el('span', { class: 'pdocword label', text: 'Comments' }),
        el('span', { class: 'spacer' })),
      card.title ? el('h1', { class: 'ptitle', text: card.title }) : null,
      K.flowBar ? K.flowBar(card, d.moves) : null);
  }

  /* Ship, with the confirm the pane's has, where there is something to ship; else why not */
  function ship(d, key) {
    var c = d.card, sh = K.shipping;
    if (!sh || c.stage !== 'shipping') return null;
    if (c.blocked_reason) return el('div', { class: 'cm-notes', 'data-key': key, text: 'Blocked: ' + c.blocked_reason + '. The deck has Unblock.' });
    if (sh.declined(c)) return el('div', { class: 'blockbox', 'data-key': key, text: K.say(c.space, 'The {change} was declined: nothing ships from this card.') });
    /* c-653: the button named for what it sends, or the line saying why there is none */
    return el('div', { class: 'cm-ship', 'data-key': key }, sh.bar(c, d.shipping));
  }

  /* c-663: Send back, his own notes for the house, where a shipping card can be told them */
  function sendBack(d) {
    var c = d.card, sh = K.shipping;
    if (!sh || !sh.sendBackOffered || !sh.sendBackOffered(c)) return null;
    return el('div', { class: 'cm-ship', 'data-key': 'cm-sendback' }, sh.sendBackButton(c),
      el('span', { class: 'cm-notes', text: 'Your own notes for the house: told as its next item, nothing posted.' }));
  }

  function when(stamp) { return stamp ? (K.ago ? K.ago(stamp) : stamp) : ''; }

  function closed(d) { return d.card.stage !== 'shipping'; }
  function round(d, r) {
    var c = d.card;
    return el('section', { class: 'cm-round', 'data-key': 'round-' + r.round },
      el('h2', { text: (r.round ? 'Round ' + r.round : 'Told') + (r.told_at ? ', told ' + when(r.told_at) : '') }),
      r.rows.map(function (row) { return K.shipping.row(c, row, closed(d)); }));
  }

  function summary(d) {
    var rows = [].concat.apply([], (d.rounds || []).map(function (r) { return r.rows; }));
    var commits = rows.reduce(function (n, row) { return n + ((row.verdict && row.verdict.commits) || []).length; }, 0);
    var line = K.shipping.countLine(rows, closed(d)) + (commits ? '; the house made ' + commits + (commits === 1 ? ' commit' : ' commits') : '') + '.';
    return el('div', null, el('p', { class: 'cm-sum', 'data-key': 'cm-sum', text: line }),
      closed(d) ? el('p', { class: 'cm-notes', 'data-key': 'cm-closed',
        text: 'The review is closed: the card is ' + d.card.stage + ', so no reply is posted from here.' }) : null);
  }

  function viewComments(id) {
    style();
    if (S.id !== id) { S.data = null; S.error = null; S.loading = false; S.id = id; }
    if (!S.data && !S.error && !S.loading) load(id);
    var d = S.data;
    if (S.error && !d) return page(head({ card: { id: id, space: '', title: '' }, docs: [] }),
      el('div', { class: 'empty', 'data-key': 'cm-error', text: 'The comments page did not load: ' + S.error }));
    if (!d) return page(el('div', { class: 'empty', text: 'reading the review of ' + id + '…' }));
    var failed = S.error ? el('div', { class: 'empty', 'data-key': 'cm-error', text: 'The last read failed: ' + S.error }) : null;
    if (d.why) return page(head(d), failed, el('div', { class: 'empty', 'data-key': 'cm-why', text: d.why }));
    var c = d.card, rounds = d.rounds || [];
    return page(head(d), failed, summary(d), ship(d, 'ship-top'), sendBack(d),
      K.shipping.waitingLine(c),
      /* c-663: what he sent back that the house has not been told yet, in his words */
      K.shipping.sentBackLines(c),
      /* c-655: each kind's automatic handling, on or off, with what waits and its tap, as the pane says it */
      K.shipping.autoLines(c),
      rounds.length ? rounds.map(function (r) { return round(d, r); })
        : el('div', { class: 'cm-notes', 'data-key': 'no-rows', text: 'The house has been told no review yet.' }),
      rounds.length ? ship(d, 'ship-foot') : null,
      el('div', { class: 'cm-notes', text: 'Read ' + when(d.at) + '.' }));
  }
  function page() {
    return el('section', { class: 'planroute', 'data-doc': 'comments' },
      el('div', { class: 'plan-body' }, Array.prototype.slice.call(arguments)));
  }

  K.viewComments = viewComments;
  /* a mark or a Ship from this page reads it again, whether the stream is open or not */
  if (K.shipping) K.shipping.onActed = function () { if (S.id) load(S.id); };
  K.loadComments = function (id) { return load(id || S.id); };
  K.commentsState = S;      /* for the node fixture */
})(window.Keel);
