/* The plan page: a house's plan (or its outcome) rendered by the deck, answered in place.
 *
 * The route is a PATH, `/plan/<c-id>`, `/outcome/<c-id>` for the card's record or
 * `/context/<c-id>` for a record not in the plan format (c-644), the way
 * the board's route is a path: a plan is a thing he opens from a notification or sends
 * himself. One request, `GET /api/plan/<id>` (keel/planroute.py), carries the parsed
 * document, the contract lint, and his round so far; the blocks are drawn by
 * app/ui.planblocks.js and the diagrams by app/ui.plandiagram.js.
 *
 * ONE STORE, NO POLL. Every tap (an option, a batch row, a reply, a note) is written at once
 * as a `mark` event on the card (`kb mark`, his token), the page shows it before the write
 * returns, and the event stream says `card <id>` when it lands, so another screen follows.
 * `Approve with these answers` and `Send back with notes` are ONE verb, `plan.send`, and the
 * server composes the prompt from the stored marks (keel/planactions.py): the page never
 * writes words a house reads.
 *
 * NOTES PIN TO WHAT HE POINTS AT, and are visible without instructions (P2-6): a note
 * button beside every block, "+ Add note" beside any words he selects, every note pinned
 * under its block and listed in the round. The block id is the anchor, the selected words
 * ride beside it as a quote, and what he types is kept apart from both (c-175 relayed the
 * selection as his words).
 *
 * A PAGE OF ITS OWN (P2-5): `/plan`, `/outcome` and `/context/<c-id>` are served from
 * app/plan.html and booted by app/ui.planpage.js, with none of the deck's chrome; so are
 * the CI and review comments pages (app/ui.ci.js, app/ui.comments.js), and the tabs switch
 * each to all the others (c-644, `docTabs`).
 *
 * THE SHAPE (mobile-first-design): on the phone the route has two panes, Decide and Read,
 * as a segmented switch in the query (`?pane=`): Decide is what waits on him (decisions,
 * the batch, the open questions, his notes, Send), Read is the whole document. On the desk
 * the same two are side by side: the document, and a sticky column with the round and Send.
 */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';
  var el = K.el, App = K.App;

  var S = {
    id: null, doc: 'plan', data: null, tag: null, error: null, loading: false,
    sel: null, quote: '', other: {}, otherText: {}, reply: {}, replyText: {}, editText: {},
    local: { answers: {}, rows: {}, replies: {}, edits: {} }, noteDraft: '', noteFor: null,
    showLint: false, lastSent: null, timings: {}, openRow: {}, findOpen: {}
  };
  K.planState = S;

  /* ---------- the route ----------
     A page of its own per document (P2-5): `/plan`, `/outcome` and `/context/<c-id>`, served
     from app/plan.html with no deck around it. `/plan/<c-id>?doc=outcome` (round 1's link)
     still opens the outcome, and is rewritten to its own path. */
  /* c-642 and c-643: the CI and review comments pages share the shell; c-719: so do the
     card's files, listed at `/files/<c-id>` and each read at `/file/<c-id>/<name>` */
  var PLAN_PATH = /^\/(plan|outcome|context|files|ci|comments)\/(c-\d+)\/?$/;
  var FILE_PATH = /^\/file\/(c-\d+)\/(.+)$/;
  function planPath() {
    var f = FILE_PATH.exec(location.pathname);
    if (f) return f[1];
    var m = PLAN_PATH.exec(location.pathname);
    return m ? m[2] : null;
  }
  function fileOfPath() {
    var f = FILE_PATH.exec(location.pathname);
    try { return f ? decodeURIComponent(f[2]) : null; } catch (e) { return f[2]; }
  }
  /* a card file and the list of them are read only: no gate, no note, no contract (c-719) */
  function readOnly() { return S.doc === 'file' || S.doc === 'files'; }
  function docOfPath() {
    if (FILE_PATH.test(location.pathname)) return 'file';
    var m = PLAN_PATH.exec(location.pathname);
    if (m && m[1] !== 'plan') return m[1];
    return new URLSearchParams(location.search).get('doc') === 'outcome' ? 'outcome' : 'plan';
  }
  /* `file` is the card file's name; the page's own (`S.file`) when it is not given (r2.F9) */
  function docPath(id, doc, file) {
    if (doc === 'file') return '/file/' + id + '/' + String(file || S.file || '').split('/').map(encodeURIComponent).join('/');
    return '/' + (DOC_WORDS[doc] ? doc : 'plan') + '/' + id;
  }
  /* THE VIEWER'S TABS (c-644): the card's pages in one fixed order, the current one marked
     and every other a link, at the top of each page on this shell (plan, outcome, context,
     comments, CI), so each switches to all the others. The order never moves with the
     stage: the stage only picks which page a Pages button opens. `keel/planroute.PAGES`
     holds the same order. A card with one page has no tabs. */
  var DOC_WORDS = { plan: 'Plan', outcome: 'Outcome', context: 'Context', files: 'Files', comments: 'Comments', ci: 'CI', file: 'File' };
  var TAB_ORDER = ['plan', 'outcome', 'context', 'files', 'comments', 'ci'];
  function docTabs(card, docs, current) {
    /* a card file is one of the Files: that tab is marked, and still a link back to the list */
    var inFile = current === 'file';
    if (inFile) current = 'files';
    var have = TAB_ORDER.filter(function (doc) { return doc === current || (docs || []).indexOf(doc) >= 0; });
    /* one file, one tab: Outcome and Context are the same record, so never both (r1.F1, F7) */
    if (have.indexOf('outcome') >= 0 && have.indexOf('context') >= 0) {
      have.splice(have.indexOf(current === 'context' ? 'outcome' : 'context'), 1);
    }
    if (have.length < 2) return null;
    return el('nav', { class: 'ptabs', 'data-key': 'tabs', 'aria-label': card.id + '\'s pages' }, have.map(function (doc) {
      if (doc === current && inFile) {
        return el('a', { class: 'ptab on', 'data-key': 'doc-' + doc, href: docPath(card.id, doc), text: DOC_WORDS[doc] });
      }
      return doc === current
        ? el('span', { class: 'ptab on', 'data-key': 'doc-' + doc, 'aria-current': 'page', text: DOC_WORDS[doc] })
        : el('a', { class: 'ptab', 'data-key': 'doc-' + doc, href: docPath(card.id, doc), text: DOC_WORDS[doc] });
    }));
  }
  /* THE FLOW'S MOVES on the page (c-644): what he may do to the card's branch now, in the
     groups the flow names, the same `flow.move` the pane's buttons send. */
  function flowBar(card, moves) {
    if (!(moves || []).length) return null;
    var groups = [];
    moves.forEach(function (m) {
      var g = groups.filter(function (x) { return x.name === m.group; })[0];
      if (!g) groups.push(g = { name: m.group, moves: [] });
      g.moves.push(m);
    });
    return el('div', { class: 'pflows', 'data-key': 'flows' }, groups.map(function (g) {
      return el('div', { class: 'pflow', role: 'group', 'aria-label': g.name, 'data-key': 'flowg-' + g.name },
        el('span', { class: 'label', text: g.name }),
        g.moves.map(function (m) {
          return K.actionBtn(m.label, { verb: 'flow.move', id: card.id, move: m.id },
            { cls: 'sm', done: function (r) { return (r && r.note) || m.label + ': the house was told'; } });
        }));
    }));
  }
  K.docTabs = docTabs; K.flowBar = flowBar;
  function paneOf() {
    var q = new URLSearchParams(location.search).get('pane');
    if (q === 'read' || q === 'decide') return q;
    var d = S.data;
    var asks = d && d.doc && (d.doc.counts.decisions || d.doc.counts.questions);
    return asks && d.gate ? 'decide' : 'read';
  }
  function goPlan(id, doc, pane, replace) {
    var q = new URLSearchParams(location.search);
    q.delete('doc');
    if (pane) q.set('pane', pane); else q.delete('pane');
    var url = docPath(id, doc) + (q.toString() ? '?' + q.toString() : '');
    if (replace) history.replaceState(null, '', url); else history.pushState(null, '', url);
    App.view = 'plan';
    readPlanRoute();
    K.openStream();
    K.render();
    window.scrollTo(0, 0);
    var body = document.getElementById('body');
    if (body) body.scrollTop = 0;
  }
  function readPlanRoute() {
    var id = planPath();
    if (!id) return false;
    var doc = docOfPath(), file = fileOfPath();
    if (new URLSearchParams(location.search).get('doc') && history.replaceState) {
      var q = new URLSearchParams(location.search);
      q.delete('doc');
      history.replaceState(null, '', docPath(id, doc, file) + (q.toString() ? '?' + q.toString() : ''));
    }
    if (id !== S.id || doc !== S.doc || file !== S.file) {
      S.id = id; S.doc = doc; S.file = file; S.data = null; S.tag = null; S.error = null; S.sel = null;
      S.local = { answers: {}, rows: {}, replies: {}, edits: {} }; S.openRow = {}; S.findOpen = {};
    }
    App.view = 'plan';
    return true;
  }

  /* ---------- loading ---------- */
  /* c-605: a load asked for while one is in flight runs again once it lands (`S.again`),
     so the load after his send is never swallowed by one that started before the server had
     written what the send did (the held relay), which would stand until the next event. */
  function load(quiet) {
    if (S.id && S.loading) { S.again = true; return Promise.resolve(); }
    if (!S.id) return Promise.resolve();
    /* the CI page reads its own data on its first draw and on Refresh, never on a board
     * event: each read costs the code host and the CI server several calls (c-642 r1.F1) */
    if (S.doc === 'ci') return Promise.resolve();
    /* the comments page's data is the board's alone, so a board event reads it again (c-643) */
    if (S.doc === 'comments') return K.loadComments ? K.loadComments(S.id, quiet) : Promise.resolve();
    S.loading = true;
    var started = performance.now(), settles = !!S.settling;
    var url = '/api/plan/' + S.id + (S.doc === 'outcome' || S.doc === 'context' || S.doc === 'files' ? '?doc=' + S.doc
      : S.doc === 'file' ? '?doc=file&name=' + encodeURIComponent(S.file || '') : '');
    return fetch(url, { cache: 'no-store', headers: S.tag ? { 'If-None-Match': S.tag } : {} })
      .then(function (r) {
        if (r.status === 304) return null;
        S.tag = r.headers.get('ETag');
        return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || 'the plan did not load'); return d; });
      })
      .then(function (d) {
        S.loading = false;
        if (S.again) { S.again = false; load(true); }
        var settled = settles && S.settling;
        if (settles) S.settling = false;
        if (!d) { if (settled) K.renderBody(); return; }
        S.timings.fetch_ms = performance.now() - started;
        /* a record in the plan format is the Outcome page (c-644 r1.F1) */
        if (d.redirect) { S.tag = null; goPlan(S.id, d.redirect, null, true); return; }
        S.data = d; S.error = null;
        /* the card's space's words (c-630), for a page that has no state to read them from */
        if (d.card && d.card.space && d.card.terms) K.cardTerms[d.card.space] = d.card.terms;
        App.stripGot = Date.now();      /* the payload's live strip facts are this old (ui.live.js) */
        /* the plan wears its CARD's palette (T1): a work card's plan is drawn in work's,
           unless the URL pins one for a screenshot */
        if (d.card && d.card.space && !new URLSearchParams(location.search).get('space')) wear(d.card.space);
        document.title = d.card.id + ' ' + (S.doc === 'file' ? S.file : (DOC_WORDS[S.doc] || 'Plan').toLowerCase()) + ' \u00b7 ' + (d.doc.title || d.card.title || '');
        S.local = { answers: {}, rows: {}, replies: {}, edits: {} };      /* the server has caught up */
        var t0 = performance.now();
        K.renderBody();
        S.timings.render_ms = performance.now() - t0;
        requestAnimationFrame(function () {
          S.timings.painted_at = performance.now();
          document.documentElement.setAttribute('data-plan-ready', S.id);
        });
      })
      .catch(function (e) {
        S.loading = false; S.error = e.message;
        if (settles) S.settling = false;
        if (S.again) { S.again = false; load(true); }
        if (!quiet) K.renderBody();
      });
  }

  /* The page wears the card's palette without touching the deck's remembered one: this
     is a page of its own, and opening a work plan must not turn the deck work. */
  /* the card's palette, unless ?space= pins one for a screenshot (also the CI page's, c-642) */
  function wearSpace(space) {
    if (space && !new URLSearchParams(location.search).get('space')) wear(space);
  }
  function wear(space) {
    if (!space) return;
    App.space = space;
    document.documentElement.setAttribute('data-mode', K.palette(space));
    var tc = document.querySelector('meta[name="theme-color"]');
    if (tc) tc.setAttribute('content', K.palette(space) === 'work' ? '#101418' : '#161412');
  }

  /* ---------- the round: what he has answered, shown before the server has it ---------- */
  function st() { return (S.data && S.data.state) || { answers: {}, rows: {}, replies: {}, comments: [] }; }
  function answerOf(b) {
    var mine = S.local.answers[b.id] !== undefined ? S.local.answers[b.id] : st().answers[b.id];
    if (mine) return { option: mine.option, other: mine.other, mine: true };
    return { option: b.rec, other: null, mine: false };
  }
  function rowsOf(id) {
    var out = {}, server = st().rows[id] || {}, local = S.local.rows[id] || {};
    Object.keys(server).forEach(function (k) { out[k] = server[k]; });
    Object.keys(local).forEach(function (k) { out[k] = local[k]; });
    return out;
  }
  function replyOf(id, i) {
    var local = (S.local.replies[id] || {})[i];
    if (local !== undefined) return local;
    return ((st().replies || {})[id] || {})[String(i)] || '';
  }
  /* Open to an answer only while the board has this document's gate open AND nobody has
     answered it since it opened (c-537, `keel/receipt.py`): an outcome approve leaves the
     card at review while it lands, and the buttons used to come back for it. */
  function gateOpen() {
    var d = S.data;
    return !!(d && d.gate && d.gate === (S.doc === 'plan' ? 'plan' : 'outcome') && d.answerable !== false);
  }
  function canAnswer() { return gateOpen(); }

  function mark(data) {
    return K.post('/api/action', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ verb: 'mark', id: S.id, data: Object.assign({ doc: markDoc() }, data) }) })
      .then(function (r) { return r.json(); })
      .then(function (d) { if (!d.ok) K.toast(d.error || 'that was not kept', true); else load(true); return d; })
      .catch(function (e) { K.toast('that did not reach the deck: ' + e.message, true); });
  }
  function answer(b, option) {
    S.other[b.id] = false;
    S.local.answers[b.id] = { option: option };
    K.renderBody();
    mark({ what: 'answer', block: b.id, option: option });
  }
  function openOther(id) { S.other[id] = true; K.renderBody(); focus('other-' + id); }
  function otherOpen(id) { return !!S.other[id]; }
  function otherField(b) {
    var key = 'other-' + b.id;
    return el('div', { class: 'pd-otherfield' },
      el('textarea', { 'data-fk': key, rows: 3, placeholder: 'What should it be instead?',
        value: S.otherText[b.id] || (answerOf(b).other || ''),
        oninput: function (ev) { S.otherText[b.id] = ev.target.value; } }),
      el('div', { class: 'row-actions' },
        el('button', { class: 'btn sm', onclick: function (ev) { ev.stopPropagation(); S.other[b.id] = false; K.renderBody(); } }, 'Cancel'),
        el('button', { class: 'btn sm primary', onclick: function (ev) {
          ev.stopPropagation();
          var text = (S.otherText[b.id] || '').trim();
          if (!text) return;
          S.other[b.id] = false;
          S.local.answers[b.id] = { option: null, other: text };
          K.renderBody();
          mark({ what: 'answer', block: b.id, other: text });
        } }, 'Keep this answer')));
  }
  function answerRow(b, row, choice) {
    (S.local.rows[b.id] = S.local.rows[b.id] || {})[row.id] = choice;
    var data = { what: 'answer', block: b.id, row: row.id, choice: choice };
    /* RC-3: picking edit keeps the words the field opens with (his last words, else the
       house's draft), so an edit he never touched sends what he saw, never nothing */
    if (choice === EDIT) {
      var words = shownEdit(b, row).trim();
      if (words) { data.other = words; (S.local.edits[b.id] = S.local.edits[b.id] || {})[row.id] = words; }
    }
    K.renderBody();
    mark(data);
  }
  /* ---------- edit wording (RC-3) ----------
     A batch row he sets to `edit` gets a field, opened with the house's draft for it (the
     `copy reply <id>` or `copy comment <id>` block) or his own words once he kept some. His
     words are the row's mark (`other`, ONE store), and Approve sends them in place of the
     draft; an edit left empty is refused there, never posted. */
  var EDIT = 'edit', DRAFT_TITLES = ['reply ', 'comment '];
  function editOf(bid, rid) {
    var local = (S.local.edits[bid] || {})[rid];
    if (local !== undefined) return local;
    return ((st().edits || {})[bid] || {})[rid] || '';
  }
  function draftFor(rid) {
    var found = '', stack = ((S.data && S.data.doc && S.data.doc.blocks) || []).slice();
    while (stack.length && !found) {
      var b = stack.shift();
      if (b.type === 'copy' && DRAFT_TITLES.some(function (t) { return b.title === t + rid; })) found = b.text || '';
      /* a review finding carries its own draft (lane FC) */
      if (b.type === 'finding' && b.id === rid) found = b.comment || '';
      if (b.blocks) stack = stack.concat(b.blocks);
    }
    return found;
  }
  function shownEdit(b, row) {
    var key = b.id + ':' + row.id;
    if (S.editText[key] !== undefined) return S.editText[key];
    return editOf(b.id, row.id) || draftFor(row.id);
  }
  function editField(b, row) {
    var key = b.id + ':' + row.id, kept = editOf(b.id, row.id);
    return el('div', { class: 'pd-otherfield pb-edit', 'data-key': 'edit-' + row.id },
      el('textarea', { 'data-fk': 'edit-' + b.id + '-' + row.id, rows: 4, placeholder: 'The words to send',
        'aria-label': 'your words for ' + row.id, value: shownEdit(b, row), disabled: canAnswer() ? null : true,
        oninput: function (ev) { S.editText[key] = ev.target.value; } }),
      el('div', { class: 'row-actions' },
        el('span', { class: 't11 ink2', text: kept ? 'Approve sends these words' : 'Nothing kept yet: Approve refuses an edit with no words' }),
        el('span', { class: 'spacer' }),
        el('button', { class: 'btn sm primary', disabled: canAnswer() ? null : true, onclick: function (ev) {
          ev.stopPropagation();
          keepWords(b, row);
        } }, 'Keep these words')));
  }
  /* His words in the field become the row's edit mark: what Approve sends in place of the
     draft. The finding card's comment field keeps its words the same way (lane FC). */
  function keepWords(b, row) {
    var key = b.id + ':' + row.id;
    var text = (S.editText[key] !== undefined ? S.editText[key] : shownEdit(b, row)).trim();
    if (!text) { K.toast('type the words to send, or pick another choice', true); return; }
    delete S.editText[key];
    (S.local.edits[b.id] = S.local.edits[b.id] || {})[row.id] = text;
    (S.local.rows[b.id] = S.local.rows[b.id] || {})[row.id] = EDIT;
    K.renderBody();
    mark({ what: 'answer', block: b.id, row: row.id, choice: EDIT, other: text });
  }
  function typeWords(b, row, text) { S.editText[b.id + ':' + row.id] = text; }
  function resetRows(b) {
    var picks = rowsOf(b.id);
    b.rows.forEach(function (row) {
      if (picks[row.id] && picks[row.id] !== row.rec) answerRow(b, row, row.rec);
    });
  }
  function replyOpen(id, i) { return !!S.reply[id + ':' + i]; }
  function openReply(id, i) { S.reply[id + ':' + i] = true; K.renderBody(); focus('reply-' + id + '-' + i); }
  function replyField(b, i) {
    var key = id2(b.id, i);
    return el('div', { class: 'pd-otherfield' },
      el('textarea', { 'data-fk': 'reply-' + b.id + '-' + i, rows: 3, placeholder: 'Your answer',
        value: S.replyText[key] !== undefined ? S.replyText[key] : replyOf(b.id, i),
        oninput: function (ev) { S.replyText[key] = ev.target.value; } }),
      el('div', { class: 'row-actions' },
        el('button', { class: 'btn sm', onclick: function (ev) { ev.stopPropagation(); S.reply[key] = false; K.renderBody(); } }, 'Cancel'),
        el('button', { class: 'btn sm primary', onclick: function (ev) {
          ev.stopPropagation();
          var text = (S.replyText[key] || '').trim();
          S.reply[key] = false;
          (S.local.replies[b.id] = S.local.replies[b.id] || {})[i] = text;
          K.renderBody();
          mark({ what: 'answer', block: b.id, item: i, other: text });
        } }, 'Keep this answer')));
  }
  function id2(id, i) { return id + ':' + i; }
  function focus(key) {
    setTimeout(function () {
      var node = document.querySelector('[data-fk="' + key + '"]');
      if (node) { node.focus(); if (node.scrollIntoView) node.scrollIntoView({ block: 'center' }); }
    }, 30);
  }

  /* ---------- notes (P2-6): visible without instructions ----------
     Three ways in, none of which needs explaining: a note button beside every block (on
     hover on the desk, always there but quiet on the phone), "Add note" beside any words he
     selects, and a note on the whole document in the round. Every note he leaves is pinned
     under its block and listed in the round with a jump to it, and until Send it can be
     edited or removed. ONE STORE, as before: a note is a `comment` mark on the card,
     removing it is a `drop`, and an edit is the new note followed by the old one's drop. */
  function notes() { return st().comments || []; }
  function notesOn(id) { return notes().filter(function (n) { return n.block === id; }); }
  /* ASK (P2-9): a question he wants cleared without sending the plan back. It goes to the
     house at once (`plan.ask`, keel/planask.py); the house's `kb reply` lands as an event on
     the card, the stream reloads the page, and the answer is pinned under the question. */
  function asks() { return st().asks || []; }
  function asksOn(id) { return asks().filter(function (a) { return a.block === id; }); }
  function askChip(a, withJump) {
    return el('div', { class: 'pask-q' + (a.reply ? ' answered' : ''), 'data-key': 'a' + a.event },
      el('div', { class: 'pnote-head' },
        withJump && a.block ? el('a', { class: 'pnote-at mono t11', href: '#b-' + a.block, onclick: jump(a.block),
          text: blockName(a.block) }) : el('span', { class: 'pnote-at t11', text: 'You asked' }),
        el('span', { class: 'spacer' }),
        el('span', { class: 't11 ' + (a.reply ? 'ink2' : 'pask-wait'), text: a.reply ? 'answered' : 'waiting for the house' })),
      a.quote ? el('div', { class: 'pnote-quote', text: '\u201c' + a.quote + '\u201d' }) : null,
      el('div', { class: 'pnote-text', text: a.text }),
      a.reply ? el('div', { class: 'pask-reply' }, el('span', { class: 'k', text: 'House: ' }),
        el('span', { class: 'pask-answer', text: a.reply.text })) : null);
  }
  function sendAsk(f, text) {
    return K.post('/api/action', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ verb: 'plan.ask', id: S.id, doc: markDoc(), block: f.block, quote: f.quote || null, text: text }) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { K.toast(d.error || 'the question was not sent', true); return d; }
        K.toast((d.result && d.result.note) || 'asked');
        load(true);
        return d;
      })
      .catch(function (e) { K.toast('that did not reach the deck: ' + e.message, true); });
  }
  function noteChip(n, withJump) {
    return el('div', { class: 'pnote', 'data-key': 'n' + n.event },
      el('div', { class: 'pnote-head' },
        withJump && n.block ? el('a', { class: 'pnote-at mono t11', href: '#b-' + n.block, onclick: jump(n.block),
          text: blockName(n.block) }) : el('span', { class: 'pnote-at t11', text: n.block ? 'Your note' : 'On the whole ' + S.doc }),
        el('span', { class: 'spacer' }),
        el('button', { class: 'btn sm ghost', 'aria-label': 'edit this note', onclick: function (ev) {
          ev.stopPropagation(); openNote(n.block, n.quote, n);
        } }, 'Edit'),
        el('button', { class: 'btn sm ghost', 'aria-label': 'remove this note', onclick: function (ev) {
          ev.stopPropagation(); mark({ what: 'drop', target: n.event });
        } }, 'Remove')),
      n.quote ? el('div', { class: 'pnote-quote', text: '\u201c' + n.quote + '\u201d' }) : null,
      el('div', { class: 'pnote-text', text: n.text }));
  }
  /* The margin button every block carries. It says "Note" in words, not an icon he has to
     learn, and shows how many notes the block already holds. */
  function noteButton(b) {
    if (readOnly()) return null;
    var count = notesOn(b.id).length;
    return el('button', { class: 'pnote-add' + (count ? ' has' : ''), 'data-key': 'note-add',
      'aria-label': 'add a note on ' + blockName(b.id), title: 'Add a note on this',
      onclick: function (ev) { ev.stopPropagation(); openNote(b.id, ''); } },
      el('span', { class: 'pnote-plus', 'aria-hidden': 'true', text: '+' }),
      el('span', { class: 'pnote-word', text: count ? String(count) : 'Note' }));
  }
  function selected() { return S.sel; }
  function blockOfNode(node) {
    while (node && node.nodeType !== 1) node = node.parentNode;
    var frame = node && node.closest ? node.closest('.pblock[data-bid]') : null;
    return frame ? frame.getAttribute('data-bid') : null;
  }
  /* SELECTING WORDS puts "Add note" right beside them. The button is painted on its own,
     outside the render pass, which would morph the text under his thumb and lose the
     selection; it acts on pointerdown, because on a phone the tap that reaches for it
     collapses the selection before any click arrives. */
  document.addEventListener('selectionchange', function () {
    if (App.view !== 'plan' || !S.data || S.noteFor || readOnly()) return;
    var sel = window.getSelection();
    var text = sel && !sel.isCollapsed ? String(sel).replace(/\s+/g, ' ').trim() : '';
    var id = text ? blockOfNode(sel.anchorNode) : null;
    if (!text || !id || id !== blockOfNode(sel.focusNode)) { S.sel = null; S.quote = ''; paintPop(); return; }
    S.sel = id;
    S.quote = text.slice(0, 480);
    paintPop();
  });
  window.addEventListener('scroll', function () { if (S.quote) paintPop(); }, { passive: true });
  function selectionRect() {
    try {
      var sel = window.getSelection();
      if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
      var r = sel.getRangeAt(0).getBoundingClientRect();
      return r && (r.width || r.height) ? r : null;
    } catch (e) { return null; }
  }
  function selectionPop() {
    var rect = S.quote ? selectionRect() : null;
    if (!rect) return null;
    /* below the words on both: the phone's own copy menu sits above a selection */
    var top = Math.min(window.innerHeight - 56, rect.bottom + 8);
    var left = Math.max(8, Math.min(window.innerWidth - 216, rect.left + rect.width / 2 - 104));
    var open = function (kind) {
      return function (ev) { ev.preventDefault(); ev.stopPropagation(); openNote(S.sel, S.quote, null, kind); };
    };
    return el('div', { class: 'pselpop', style: 'top:' + Math.round(top) + 'px;left:' + Math.round(left) + 'px' },
      el('button', { class: 'btn primary', onpointerdown: open('note'), onclick: open('note') }, '+ Add note'),
      el('button', { class: 'btn', onpointerdown: open('ask'), onclick: open('ask') }, '? Ask'));
  }
  function paintPop() {
    var host = document.querySelector('.pselpop-host');
    if (host && App.view === 'plan') paintInto(host, selectionPop());
  }
  function paintInto(host, node) {
    while (host.firstChild) host.removeChild(host.firstChild);
    if (node) host.appendChild(node);
  }
  function blockName(id) {
    var d = S.data && S.data.doc, found = null;
    (function walk(list) { (list || []).forEach(function (b) { if (b.id === id) found = b; walk(b.blocks); }); })(d && d.blocks);
    if (!found) return id;
    var section = (d.sections || []).filter(function (s) { return s.id === found.section; })[0];
    return (section ? section.text + ' \u00b7 ' : '') + found.type;
  }
  function clearSelection() { try { window.getSelection().removeAllRanges(); } catch (e) { /* nothing selected */ } }
  function openNote(block, quote, editing, kind) {
    S.noteFor = { block: block || null, quote: quote || '', replaces: editing ? editing.event : null,
                  kind: editing ? 'note' : (kind || 'note') };
    S.noteDraft = editing ? editing.text : '';
    S.sel = null; S.quote = '';
    paintPop();
    App.sheet = { kind: 'plannote' };
    K.renderSheet();
    focus('plannote');
  }
  function keepNote(f, text) {
    return mark({ what: 'comment', block: f.block, quote: f.quote || null, text: text }).then(function (d) {
      if (d && d.ok && f.replaces) return mark({ what: 'drop', target: f.replaces });
      return d;
    });
  }
  /* ONE SHEET, TWO KINDS: a Note waits for his Send; an Ask goes to the house now and its
     answer comes back under the question, with the plan and the gate left as they are. */
  K.planNoteSheet = function () {
    var f = S.noteFor || {}, asking = f.kind === 'ask';
    var close = function () { S.noteFor = null; App.sheet = null; K.renderSheet(); K.renderBody(); };
    var kind = function (k) {
      return el('button', { class: f.kind === k ? 'on' : '', role: 'tab', 'aria-selected': f.kind === k ? 'true' : 'false',
        onclick: function () { f.kind = k; K.renderSheet(); } }, k === 'ask' ? 'Ask the house' : 'Note');
    };
    return el('div', { class: 'sheet say pnote-sheet', 'data-key': 'sheet-plannote' },
      el('div', { class: 'sheet-head' }, el('button', { onclick: close }, '\u2039 close'), el('span', { class: 'spacer' }),
        el('span', { class: 'mono t11 ink2', text: S.id + ' \u00b7 ' + (f.replaces ? 'edit note' : asking ? 'ask' : 'note') })),
      el('div', { class: 'sheet-body' },
        f.replaces || !gateOpen() ? null : el('div', { class: 'pseg wide', role: 'tablist' }, kind('note'), kind('ask')),
        el('div', { class: 'label', text: f.block ? 'On ' + blockName(f.block) : 'On the whole ' + S.doc }),
        f.quote ? el('blockquote', { class: 'pnote-quote', text: '\u201c' + f.quote + '\u201d' }) : null,
        el('textarea', { 'data-fk': 'plannote', rows: 4,
          placeholder: asking ? 'What do you want the house to clear up?' : 'What should change, or what you want to know',
          value: S.noteDraft, oninput: function (ev) { S.noteDraft = ev.target.value; } }),
        el('p', { class: 't11 ink2', text: asking
          ? 'Goes to the house now. It answers here, under your question, without changing the plan; your notes and answers still wait for your send.'
          : 'Kept on the card now; the house reads it when you send.' }),
        el('div', { class: 'row-actions' },
          el('button', { class: 'btn', onclick: close }, 'Cancel'),
          el('button', { class: 'btn primary', onclick: function () {
            var text = S.noteDraft.trim();
            if (!text) return;
            (asking ? sendAsk(f, text) : keepNote(f, text)).then(function (d) {
              if (d && d.ok) { S.noteDraft = ''; clearSelection(); close(); }
            });
          } }, f.replaces ? 'Keep the edit' : asking ? 'Ask now' : 'Keep note'))));
  };
  /* The one line that says how, the first time he reads a plan here; gone once he says so. */
  function hint() {
    if (readOnly() || K.stored('planhint') === 'seen') return null;
    return el('div', { class: 'phint', 'data-key': 'hint', role: 'note' },
      /* c-604: past the gate there is no Ask (the sheet offers Note alone) and no Send, so
         the line offers only what is there */
      el('span', { text: gateOpen()
        ? 'Select any words, or tap + Note beside a block, to leave a note (it reaches the house when you send) or to ask the house a question now.'
        : 'Select any words, or tap + Note beside a block, to leave a note on the card.' }),
      el('button', { class: 'btn sm ghost', onclick: function () { K.store('planhint', 'seen'); K.renderBody(); } }, 'Got it'));
  }

  /* ---------- the contract ---------- */
  function findings() { return (S.data && S.data.lint && S.data.lint.findings) || []; }
  function findingsOn(id) { return S.doc === 'context' ? [] : findings().filter(function (f) { return f.block === id; }); }
  /* the context page is the outcome's file read plainly: a note on it is the outcome's (r1.F2) */
  function markDoc() { return S.doc === 'context' ? 'outcome' : S.doc; }
  function brokenRef(v) {
    var hit = findings().filter(function (f) { return f.rule === 'C7' && f.text.indexOf('`' + v + '`') === 0; })[0];
    return hit ? hit.text.slice(('`' + v + '`').length).trim() : null;   /* "does not resolve at <HEAD or the plan's commit>: why" */
  }
  function contractBadge() {
    var lint = S.data.lint, errs = findings().filter(function (f) { return f.level === 'error'; }).length;
    var warns = findings().length - errs;
    return el('button', { class: 'chip contract ' + (lint.ok ? 'tone-good' : 'tone-bad'), 'aria-expanded': S.showLint ? 'true' : 'false',
      onclick: function () { S.showLint = !S.showLint; K.renderBody(); } },
      lint.ok ? (warns ? 'contract holds · ' + warns + (warns === 1 ? ' note' : ' notes') : 'contract holds') : errs + ' contract ' + (errs === 1 ? 'break' : 'breaks'));
  }
  function lintList() {
    if (!S.showLint || !findings().length) return null;
    return el('ul', { class: 'pfindings all' }, findings().map(function (f, i) {
      return el('li', { class: 'lvl-' + f.level, 'data-key': 'f' + i },
        el('span', { class: 'mono', text: f.rule + ' ' }), f.text,
        f.block ? el('a', { href: '#b-' + f.block, class: 'mono t11', onclick: function (ev) {
          ev.preventDefault(); var n = document.getElementById('b-' + f.block); if (n) n.scrollIntoView({ block: 'center' });
        } }, ' → ' + f.block) : null);
    }));
  }

  /* ---------- send ---------- */
  function roundCounts() {
    var d = S.data, doc = d.doc, changed = 0, decisions = 0;
    (function walk(list) {
      (list || []).forEach(function (b) {
        if (b.type === 'decision') {
          decisions++;
          var a = answerOf(b);
          if (a.mine && (a.option !== b.rec || a.other)) changed++;
        } else if (b.type === 'batch') {
          var picks = rowsOf(b.id);
          b.rows.forEach(function (r) { decisions++; if (picks[r.id] && picks[r.id] !== r.rec) changed++; });
        } else if (b.type === 'finding') {
          var pick = rowsOf(b.id)[b.id];
          decisions++;
          if (pick && pick !== b.rec) changed++;
        }
        walk(b.blocks);
      });
    })(doc.blocks);
    return { decisions: decisions, changed: changed, notes: notes().length };
  }
  /* THE SEND PANEL, or the RECEIPT once the gate is answered (c-537). The buttons are
     drawn only while the gate is really open; after an answer they never come back, and the
     panel says who answered, when, and what is happening now, redrawn on every card event
     (`app/ui.receipt.js`). A refused landing is the one answer that offers Approve again. */
  /* c-605: WHILE HIS SEND IS IN FLIGHT the receipt cannot say "house resumed": the gate's
     move lands first and the server only then finds the house working and holds his answer
     (`actions.gate_answer`), so a load in between read "house resumed" for about a second
     before "held". Until the send has answered and a load after it has landed, a receipt
     that says so reads as what is known: his answer is on its way to the house. */
  var SENDING = 'sending your answer to the house…';
  function sending() {
    return !!S.settling || (!!K.isPending && K.isPending(K.pendKey({ verb: 'plan.send', id: S.id })));
  }
  function receiptNow(r) {
    if (!r || !sending() || !/^house resumed/.test(r.now || '')) return r;
    return Object.assign({}, r, { now: SENDING, tone: 'accent' });
  }
  function sendPanel() {
    var open = gateOpen(), r = receiptNow(S.data.receipt), card = S.data.card;
    var said = S.lastSent ? el('details', { class: 'psent' }, el('summary', { class: 't11 ink2', text: 'What the house was sent' }),
      el('pre', { class: 'pcode-pre wrap', text: S.lastSent })) : null;
    if (!open) {
      return el('section', { class: 'psend done', 'data-key': 'send', 'aria-label': 'what happened' },
        r ? K.receipt(r, { card: card.id }) : el('p', { class: 't11 ink2', text: card.id + ' is at ' + card.stage + '; nothing here waits on you' }),
        said);
    }
    var c = roundCounts(), again = !!(r && r.again);
    /* c-551: an outcome his Approve could not publish says what is missing in its place */
    var unpublished = S.doc === 'outcome' && card.unpublished;
    /* c-592: research, a plan or an errand (personal, no repo) publishes nothing: his read is
       Done. A tracking card keeps its own outcome gate, repo or none. */
    var tracks = !!((card.derived && card.derived.tracking) || (S.data.children && S.data.children.length));
    var research = S.doc === 'outcome' && isResearch(card, tracks);
    /* c-605: "with these answers" only where there are answers: a plan with no decision
       is approved plainly */
    var approve = approveWords(card, c, again, research);
    return el('section', { class: 'psend', 'data-key': 'send', 'aria-label': 'send your answers' },
      again ? K.receipt(r, { card: card.id }) : null,
      el('div', { class: 'psend-count' },
        el('span', { class: 'pcount' }, el('strong', { text: String(c.decisions) }), c.decisions === 1 ? ' decision' : ' decisions'),
        el('span', { class: 'pcount' + (c.changed ? ' mine' : '') }, el('strong', { text: String(c.changed) }), ' changed'),
        el('span', { class: 'pcount' + (c.notes ? ' mine' : '') }, el('strong', { text: String(c.notes) }), c.notes === 1 ? ' note' : ' notes')),
      el('p', { class: 't11 ink2', text: again ? 'Approve again clears the refusal and lands it once more.'
        : c.changed || c.notes
        ? 'One send carries every answer and note to the house; a recommendation you left is sent as standing.'
        : S.doc === 'plan' && !c.decisions ? 'Nothing to decide: Approve sends the plan to be built as it is.'
        : 'Nothing changed: Approve takes every recommendation, and says so to the house.' }),
      el('button', { class: 'btn ghost wide', onclick: function () { openNote(null, ''); } }, 'Note on the whole ' + S.doc),
      el('div', { class: 'psend-row' },
        sendBackBtn(c),
        unpublished ? el('p', { class: 'blockbox', 'data-key': 'unpublished', text: unpublished })
          : K.actionBtn(approve.word, { verb: 'plan.send', id: S.id, mode: 'approve', doc: S.doc },
            { cls: 'primary wide', done: sent, confirm: approve.confirm })),
      c.changed || c.notes ? null : el('p', { class: 't11 ink2', 'data-key': 'sendback-why',
        text: 'Send back needs your reason: leave a note (or change an answer) first.' }),
      said);
  }
  /* c-600: a send back carries his reason, as the pane's does: with nothing said it is not
     offered (the server refuses it too), and with notes it asks once before it goes. c-604:
     ABSENT, as the Atlas says, not drawn disabled: the line under the row says what it needs */
  function sendBackBtn(c) {
    if (!(c.changed || c.notes)) return null;
    return K.actionBtn('Send back with notes', { verb: 'plan.send', id: S.id, mode: 'sendback', doc: S.doc },
      { cls: 'wide', done: sent, confirm: 'Send the ' + S.doc + ' back to the house with ' +
        (c.notes ? c.notes + (c.notes === 1 ? ' note' : ' notes') : 'your changed answers') + '?' });
  }
  /* c-719: research on either side, as the pane's `K.research` says it (this page has no
     ui.cards.js): a personal card with no repo, or any card whose kind is research (the
     payload's `card.kind`). Its approve publishes nothing, so it is Done. */
  function isResearch(card, tracks) {
    if (tracks) return false;
    return (card.space === 'personal' && !card.repo) || card.kind === 'research';
  }
  /* c-600: the same guard as the pane's Approve outcome (the e2e run found the page's had none) */
  /* the approve button's word and its confirm, for this document and this card (c-667: a
     proposal's outcome is Adopt, which writes its draft) */
  function approveWords(card, c, again, research) {
    var word = S.doc === 'plan' ? (c.decisions ? 'Approve with these answers' : 'Approve') : again ? 'Approve again'
      : S.doc === 'outcome' && K.proposalOf(card) ? 'Adopt' : research ? 'Done' : 'Approve outcome';
    return { word: word, confirm: approveConfirm(card, research) };
  }
  function approveConfirm(card, research) {
    if (S.doc !== 'outcome') return null;
    if (K.proposalOf(card)) return K.adoptConfirm(card);     /* c-667: this tap writes its draft */
    if (research) return 'Mark ' + card.id + ' done?';
    if (card.derived && card.derived.review) return K.say(card.space, 'Post this review on the {change}? The findings you kept go inline at their lines, then one summary and your verdict.');
    return 'Approve the outcome of ' + card.id + '? This publishes it.';
  }
  function sent(result) {
    S.lastSent = result && result.composed;
    S.settling = true;          /* until a load started after this answer lands (receiptNow) */
    load(true);
    return sentWord(result);
  }
  /* c-667: an adopting approve (it carries `where`) is said as the card's own Adopt says it,
     so "adopted, but not moved to done" is an error here too (`K.sentence`) */
  function sentWord(result) {
    if (result && result.where) return K.sentence({ verb: 'approve', gate: 'outcome', id: S.id }, result);
    if (result && result.relayed) return result.note;
    return result && result.resumed ? 'sent, house resumed' : (result && result.note) || 'sent';
  }

  /* ---------- the page ---------- */
  /* THE SLIM HEADER (P2-5): which card, which space, back to the card in the deck, and the
     card's other document when it has one. Links, not buttons: this page is a page, and
     the deck is another one. */
  function head() {
    var d = S.data, card = d.card, doc = d.doc;
    var meta = doc.meta || {};
    var context = S.doc === 'context' || readOnly();
    return el('header', { class: 'phead', 'data-key': 'head' },
      docTabs(card, d.docs, S.doc),
      el('div', { class: 'phead-line' },
        el('a', { class: 'pback', href: '/?view=cards&card=' + card.id + '&space=' + card.space,
          'aria-label': 'back to ' + card.id + ' in the deck' }, '\u2039 ' + card.id),
        el('span', { class: 'chip space-' + card.space, text: card.space }),
        el('span', { class: 'pdocword label', text: DOC_WORDS[S.doc] || 'Plan' }),
        S.doc === 'file' ? el('span', { class: 'pfilename mono t11 ellip', 'data-key': 'filename', text: S.file }) : null,
        el('span', { class: 'spacer' }),
        /* c-565: the outcome's pull requests, one per repo, each on the code host */
        S.doc === 'outcome' ? (card.pulls || []).map(function (p) {
          return el('a', { class: 'pother', 'data-key': 'pr-' + p.repo, href: p.url, target: '_blank', rel: 'noopener' },
            p.repo + ' #' + p.pr + ' \u203a');
        }) : null),
      el('h1', { class: 'ptitle', text: doc.title || (S.doc === 'file' ? S.file : card.title) }),
      flowBar(card, d.moves),
      readOnly() ? null : el('div', { class: 'pmeta' },
        gateOpen() ? el('span', { class: 'chip tone-accent', text: d.gate + ' gate open' }) : el('span', { class: 'chip', text: card.stage }),
        context ? null : contractBadge(),
        el('span', { class: 'pmeta-line mono t11 ink2', text: Object.keys(meta).filter(function (k) {
          return ['title', 'card', 'kind', 'space'].indexOf(k) < 0;
        }).map(function (k) { return k + ' ' + meta[k]; }).join(' \u00b7 ') })),
      houseStrip(),
      context ? null : lintList());
  }
  /* c-599: what the card's house is doing now, the deck's live strip (app/ui.live.js), so a
     question in flight or a plan being rewritten shows the house at work, not only "waiting
     for the house". The stream's `live` line redraws it (`K.planLive`). */
  function houseStrip() {
    var d = S.data;
    if (!K.liveStrip || !d) return null;
    return K.liveStrip({ id: d.card.id, live: d.live || null, notice: d.notice || null,
                         derived: { relays: [] }, last_said: null });
  }
  K.planLive = function (id) { if (S.id === id && S.data) K.renderBody(); };
  function summaryCard() {
    var d = S.data, doc = d.doc, c = doc.counts;
    if (!doc.summary && !c.decisions && !c.questions) return null;
    return el('section', { class: 'psummary', 'data-key': 'summary' },
      doc.summary ? el('p', { class: 'plede' }, K.planBlocks.spans(doc.summary)) : null,
      el('div', { class: 'pasks' },
        c.decisions ? el('span', { class: 'pask' }, el('strong', { text: String(c.decisions) }), c.decisions === 1 ? ' decision' : ' decisions') : null,
        c.questions ? el('span', { class: 'pask' }, el('strong', { text: String(c.questions) }), c.questions === 1 ? ' question' : ' questions') : null,
        c.diagrams ? el('span', { class: 'pask' }, el('strong', { text: String(c.diagrams) }), c.diagrams === 1 ? ' diagram' : ' diagrams') : null,
        notes().length ? el('span', { class: 'pask mine' }, el('strong', { text: String(notes().length) }), ' your notes') : null));
  }
  function paneSwitch(pane) {
    var c = S.data.doc.counts;
    return el('div', { class: 'pseg wide ppane', role: 'tablist', 'data-key': 'pane' },
      [['decide', 'Decide' + (c.decisions + c.questions ? ' (' + (c.decisions + c.questions) + ')' : '')], ['read', 'Read all']].map(function (p) {
        return el('button', { class: pane === p[0] ? 'on' : '', role: 'tab', 'aria-selected': pane === p[0] ? 'true' : 'false',
          onclick: function () { goPlan(S.id, S.doc, p[0], true); } }, p[1]);
      }));
  }
  function blocksFor(pane) {
    var all = S.data.doc.blocks, summary = S.data.doc.summary;
    if (pane === 'decide') return all.filter(function (b) { return K.planBlocks.ANSWERABLE[b.type]; });
    /* the lede is drawn once, in the summary card */
    var dropped = false;
    return all.filter(function (b) {
      if (!dropped && summary && b.type === 'paragraph' && b.text === summary) { dropped = true; return false; }
      if (!dropped && summary && b.type === 'paragraph' && JSON.stringify(b.text) === JSON.stringify(summary)) { dropped = true; return false; }
      return true;
    });
  }
  /* Every note in the round, each with a jump to its block, editable and removable. */
  function noteList() {
    var list = notes(), questions = asks();
    return el('section', { class: 'pnotes', 'data-key': 'notes' },
      el('div', { class: 'label', text: list.length ? 'Your notes (' + list.length + ')' : 'Your notes' }),
      list.length ? list.map(function (n) { return noteChip(n, true); })
        : el('p', { class: 't11 ink2', text: 'None yet. Select words, or + Note beside a block.' }),
      questions.length ? el('div', { class: 'label', text: 'Your questions (' + questions.length + ')' }) : null,
      questions.map(function (a) { return askChip(a, true); }));
  }
  /* The desk's side column names every decision and where it stands, one line each, so the
     round can be read without scrolling the document; a tap takes him to the block. */
  function decideList() {
    var rows = [];
    (function walk(list) {
      (list || []).forEach(function (b) {
        if (b.type === 'decision') {
          var a = answerOf(b), mine = a.mine && (a.option !== b.rec || a.other);
          rows.push(el('a', { class: 'pdl-row' + (mine ? ' mine' : ''), href: '#b-' + b.id, 'data-key': b.id, onclick: jump(b.id) },
            el('span', { class: 'mono t11 ink2', text: b.id }),
            el('span', { class: 'pdl-q ellip', text: K.planBlocks.words(b.q) }),
            el('span', { class: 'pdl-a mono t11', text: a.other ? 'your words' : (a.option || '?') + (mine ? '' : ' \u00b7 rec') })));
        } else if (b.type === 'batch') {
          var picks = rowsOf(b.id), n = b.rows.filter(function (r) { return picks[r.id] && picks[r.id] !== r.rec; }).length;
          rows.push(el('a', { class: 'pdl-row' + (n ? ' mine' : ''), href: '#b-' + b.id, 'data-key': b.id, onclick: jump(b.id) },
            el('span', { class: 'mono t11 ink2', text: b.id }),
            el('span', { class: 'pdl-q ellip', text: K.planBlocks.words(b.q) || 'each row' }),
            el('span', { class: 'pdl-a mono t11', text: n ? n + ' changed' : 'all rec' })));
        } else if (b.type === 'finding') {
          var fpick = rowsOf(b.id)[b.id] || b.rec, fmine = fpick !== b.rec;
          rows.push(el('a', { class: 'pdl-row' + (fmine ? ' mine' : ''), href: '#b-' + b.id, 'data-key': b.id, onclick: jump(b.id) },
            el('span', { class: 'mono t11 ink2', text: b.id }),
            el('span', { class: 'pdl-q ellip', text: K.planBlocks.words(b.claim) }),
            el('span', { class: 'pdl-a mono t11', text: fpick + (fmine ? '' : ' \u00b7 rec') })));
        }
        walk(b.blocks);
      });
    })(S.data.doc.blocks);
    if (!rows.length) return null;
    return el('section', { class: 'pdl', 'data-key': 'dl' }, el('div', { class: 'label', text: 'Decisions' }), rows);
  }
  function jump(id) {
    return function (ev) {
      ev.preventDefault();
      var n = document.getElementById('b-' + id);
      if (n) n.scrollIntoView({ block: 'start', behavior: 'smooth' });
    };
  }
  function docColumn(pane) {
    var compact = pane === 'decide' && !K.isDesk() && S.data.doc.counts.decisions > COMPACT_OVER;
    return el('div', { class: 'pdoc' + (compact ? ' compact' : ''), 'data-key': 'doc-' + pane },
      pane === 'read' ? hint() : null,
      blocksFor(pane).map(function (b) {
        if (!compact || !ROWED[b.type] || S.openRow[b.id]) return compact && ROWED[b.type] ? openBlock(b) : K.planBlocks.block(b);
        return decideRow(b);
      }));
  }
  /* MANY DECISIONS ON A PHONE (P4-4). Over about eight, every decision drawn whole made
     Decide a wall (the voice plan's 37 were 20 screens); so each is ONE row: what it asks,
     where it stands (the recommendation, or his pick), and a marker when he changed it. A
     tap opens that decision's full card in place and Fold puts the row back. One Send as
     before, at the foot: a row he never opened is the recommendation left standing. The
     questions stay whole: they are one line each already. */
  var COMPACT_OVER = 8;
  var ROWED = { decision: 1, batch: 1 };
  function standing(b) {
    if (b.type === 'batch') {
      var picks = rowsOf(b.id), n = b.rows.filter(function (r) { return picks[r.id] && picks[r.id] !== r.rec; }).length;
      return { text: n ? n + ' of ' + b.rows.length + ' changed' : b.rows.length + ' rows, each recommended', mine: n > 0 };
    }
    var a = answerOf(b), mine = a.mine && (a.option !== b.rec || !!a.other);
    if (a.other) return { text: 'your words', mine: true };
    var o = (b.options || []).filter(function (x) { return x.id === a.option; })[0];
    var label = o ? K.planBlocks.words(o.label) : (a.option || 'no recommendation');
    return { text: (mine ? 'yours: ' : 'recommended: ') + label, mine: mine };
  }
  function decideRow(b) {
    var where = standing(b), extra = notesOn(b.id).length + asksOn(b.id).length;
    return el('button', { class: 'pdrow' + (where.mine ? ' mine' : ''), id: 'b-' + b.id, 'data-key': 'row-' + b.id,
      'aria-expanded': 'false', onclick: function () { S.openRow[b.id] = true; K.renderBody(); } },
      el('span', { class: 'pdrow-q' }, K.planBlocks.words(b.q) || b.id),
      el('span', { class: 'pdrow-a' },
        where.mine ? el('span', { class: 'pdrow-mark', 'aria-label': 'changed' }, 'changed') : null,
        el('span', { class: 'ellip', text: where.text }),
        extra ? el('span', { class: 'pdrow-n', text: extra + (extra === 1 ? ' note' : ' notes') }) : null));
  }
  function openBlock(b) {
    return el('div', { class: 'pdrow-open', 'data-key': 'open-' + b.id }, K.planBlocks.block(b),
      el('button', { class: 'btn sm ghost wide', 'aria-expanded': 'true',
        onclick: function () { S.openRow[b.id] = false; K.renderBody(); } }, 'Fold'));
  }

  function viewPlan() {
    if (!S.id) readPlanRoute();
    if (S.doc === 'ci') return K.viewCi ? K.viewCi(S.id) : el('div', { class: 'empty', text: 'the CI page did not load' });
    if (S.doc === 'comments') return K.viewComments ? K.viewComments(S.id) : el('div', { class: 'empty', text: 'the comments page did not load' });
    if (!S.data && !S.error) { load(); return panel(el('div', { class: 'empty', text: 'reading the plan of ' + S.id + '…' })); }
    if (S.error) return panel(el('div', { class: 'empty', text: S.error }));
    if (S.data.empty) {
      return panel(head(), el('div', { class: 'empty', text: S.data.empty }),
        S.data.card.plan_ref ? el('button', { class: 'btn', onclick: function () { K.openPlan && K.openPlan(K.byId(S.id)); } }, 'Open the plan file') : null);
    }
    /* a context that is not in the plan format: the record, to read, with no gate (c-644);
       a card file the same way, and the list of them (c-719) */
    if (S.doc === 'context' || S.doc === 'file') return panel(head(), summaryCard(), docColumn('read'));
    if (S.doc === 'files') return panel(head(), filesList());
    var desk = K.isDesk(), pane = paneOf();
    /* an answered gate's receipt LEADS (c-537): it is the news, and on the phone the foot of
       a long document is where nobody looks for it */
    var told = !gateOpen() && S.data.receipt;
    if (desk) {
      return panel(el('div', { class: 'pgrid' },
        el('div', { class: 'pmain' }, head(), summaryCard(), docColumn('read')),
        el('aside', { class: 'pside', 'aria-label': 'your round' }, told ? sendPanel() : null, decideList(),
          told ? null : sendPanel(), noteList())));
    }
    return panel(head(), told ? sendPanel() : null, summaryCard(), paneSwitch(pane), docColumn(pane),
      pane === 'decide' ? noteList() : null, told ? null : sendPanel());
  }
  /* THE CARD'S FILES (c-719): every markdown file it wrote beyond its plan and record, one
     row each, a link to its page on this shell, newest writes said by when. */
  function filesList() {
    var files = S.data.files || [];
    if (!files.length) return el('div', { class: 'empty', 'data-key': 'nofiles', text: S.id + ' has written no other markdown file' });
    return el('ul', { class: 'pfiles', 'data-key': 'files', 'aria-label': S.id + '\'s files' }, files.map(function (f) {
      return el('li', { 'data-key': 'f:' + f.name },
        el('a', { class: 'pfile', href: f.url },
          el('span', { class: 'pfile-name mono', text: f.name }),
          el('span', { class: 'pfile-meta t11 ink2', text: sizeWord(f.bytes) + (f.at ? ' \u00b7 ' + String(f.at).slice(0, 16).replace('T', ' ') : '') })));
    }));
  }
  function sizeWord(n) { return n < 1024 ? n + ' B' : Math.round(n / 1024) + ' KB'; }

  /* THE PAGE, not a panel (P2-3): round 1 drew the document inside the deck's `.panel`,
     whose grey fill and border were sized to the first viewport and stopped there while
     the document scrolled on past it. This page has no panel and no fill of its own: the
     canvas is the page's background, all the way down. */
  function panel() {
    var parts = Array.prototype.slice.call(arguments);
    return el('section', { class: 'planroute', 'data-doc': S.doc,
      'data-kind': S.data && S.data.doc ? S.data.doc.kind : null },
      el('div', { class: 'plan-body' }, parts),
      el('div', { class: 'pselpop-host', 'data-morph': 'skip' }));
  }

  /* A finding's path links to the pull request it is posted on (lane FC): its member's on a
     feature card, else the card's own (`card.prs`, keel/planroute.py). */
  function prOf(member) {
    var prs = (S.data && S.data.card && S.data.card.prs) || {};
    return (member && prs[member]) || prs.pr || null;
  }
  /* On the phone a low finding starts folded to its head; a tap opens or folds any one. */
  function findingOpen(b) {
    if (S.findOpen[b.id] !== undefined) return S.findOpen[b.id];
    return K.isDesk() || b.severity !== 'low';
  }
  function toggleFinding(b) { S.findOpen[b.id] = !findingOpen(b); K.renderBody(); }

  function drawn(host) {
    S.timings.diagrams = (S.timings.diagrams || 0) + 1;
    S.timings.diagram_ms = Math.max(S.timings.diagram_ms || 0, host._ms || 0);
  }

  K.viewPlan = viewPlan;
  K.goPlan = goPlan;
  K.readPlanRoute = readPlanRoute;
  K.loadPlan = load;
  K.wearSpace = wearSpace;
  K.planPath = planPath;
  K.plan = { answerOf: answerOf, otherOpen: otherOpen, canAnswer: canAnswer, answer: answer,
             openOther: openOther, otherField: otherField, rowsOf: rowsOf, answerRow: answerRow, editField: editField, editOf: editOf,
             resetRows: resetRows, replyOf: replyOf, asksOn: asksOn, askChip: askChip, replyOpen: replyOpen, replyField: replyField,
             openReply: openReply, notesOn: notesOn, noteChip: noteChip, findingsOn: findingsOn,
             brokenRef: brokenRef, selected: selected, noteButton: noteButton, drawn: drawn,
             shownEdit: shownEdit, keepWords: keepWords, typeWords: typeWords, prOf: prOf,
             findingOpen: findingOpen, toggleFinding: toggleFinding, keepNote: keepNote,
             space: function () { return S.data && S.data.card ? S.data.card.space : null; },
             approveWords: approveWords, sentWord: sentWord, isResearch: isResearch,
             state: S, COMPACT_OVER: COMPACT_OVER };
})(window.Keel);
