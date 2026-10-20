/* The plan page's renderers, run under node against the DOM stand-in and read back.
 *
 * Usage: node plan-render.js <path to app/> <payload.json>
 * The payload is what `GET /api/plan/<id>` answers, built by tests/test_planrender.py from
 * the sample plan. Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const fs = require('fs');
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const PAYLOAD = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const MODULES = ['ui.core.js', 'ui.boardlayout.js', 'ui.board.js', 'ui.planlook.js', 'ui.plandiagram.js', 'ui.plancode.js', 'ui.planfinding.js', 'ui.receipt.js', 'ui.planblocks.js', 'ui.plan.js'];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

function page(pane, desk, path) {
  /* the plan route reads its own path and query; node has URLSearchParams, not a location */
  globalThis.location = { pathname: path || '/plan/c-900', search: pane ? '?pane=' + pane : '' };
  const K = deck.load(APP, MODULES, { desk: !!desk });
  K.render = K.renderBody = function () {};
  K.App.data = deck.state([]);
  K.App.space = 'personal';
  K.readPlanRoute();
  K.planState.data = JSON.parse(JSON.stringify(PAYLOAD));
  return K;
}
function attr(node, name) { return node.getAttribute(name); }

/* ---------- the phone opens on Decide, and Decide is what waits on him ---------- */
(function () {
  const K = page('decide');
  const view = deck.wrap(K.viewPlan(), K);
  const frames = deck.byClass(view, 'pblock');
  check('decide: only answerable blocks are drawn', frames.length && frames.every((f) => deck.hasClass(f, 'answerable')));
  check('decide: the pane switch is there', deck.byClass(view, 'ppane').length === 1);
  const radios = deck.all(view, (n) => attr(n, 'role') === 'radio' && deck.hasClass(n, 'pd-opt'));
  const on = radios.filter((n) => attr(n, 'aria-checked') === 'true');
  check('decide: the recommendation is pre-selected', on.length === 1 && attr(on[0], 'data-key') === 'card');
  check('decide: "something else" is offered', radios.some((n) => attr(n, 'data-key') === '__other'));
  check('decide: an option says its cost', deck.byClass(view, 'pd-cost').length >= 2);
  const rows = deck.byClass(view, 'pb-choice').filter((n) => deck.hasClass(n, 'on'));
  check('decide: each batch row has its recommendation selected', rows.length === 2);
  const labels = deck.labels(view);
  check('decide: Approve is there', labels.indexOf('Approve with these answers') >= 0);
  /* c-604: with nothing said, Send back is absent (not drawn disabled) and the line says why */
  check('decide: no Send back before a reason', labels.indexOf('Send back with notes') < 0
        && deck.all(view, (n) => n.getAttribute('data-key') === 'sendback-empty').length === 0
        && deck.all(view, (n) => n.getAttribute('data-key') === 'sendback-why').length === 1);
  K.planState.data.state = Object.assign({ answers: {}, rows: {}, replies: {} }, K.planState.data.state || {},
    { comments: [{ id: 'n1', block: null, text: 'why this way?' }] });
  const noted = deck.wrap(K.viewPlan(), K);
  check('decide: a note brings Send back with notes', deck.labels(noted).indexOf('Send back with notes') >= 0);
  check('decide: one note is "1 note"', noted.textContent.indexOf('1 notes') < 0 && noted.textContent.indexOf('1 note') >= 0);
  check('decide: a question can be answered differently', labels.indexOf('Answer differently') >= 0);
})();

/* ---------- his pick shows as his, and the count says so ---------- */
(function () {
  const K = page('decide');
  K.planState.data.state.answers = { store: { option: 'file', other: null } };
  const view = deck.wrap(K.viewPlan(), K);
  const on = deck.all(view, (n) => deck.hasClass(n, 'pd-opt') && attr(n, 'aria-checked') === 'true');
  check('mine: his pick is the checked option', on.length === 1 && attr(on[0], 'data-key') === 'file');
  check('mine: the decision says it is his answer', view.textContent.indexOf('Your answer, not the recommendation') >= 0);
  check('mine: the send panel counts one changed', deck.byClass(view, 'psend-count')[0].textContent.indexOf('1 changed') >= 0);
})();

/* ---------- RC-3: a row at edit carries a field, opened with the draft or his words ---------- */
(function () {
  const K = page('read', true);
  const doc = K.planState.data.doc;
  doc.blocks.push({ type: 'copy', id: 'x.copy1', section: 'x', title: 'reply f1', text: 'THE HOUSE DRAFT' });
  K.planState.data.state.rows = { triage: { f1: 'edit', f2: 'edit' } };
  K.planState.data.state.edits = { triage: { f2: 'HIS OWN WORDS' } };
  const view = deck.wrap(K.viewPlan(), K);
  const fields = deck.all(view, (n) => n.tagName === 'TEXTAREA' && /^edit-triage-/.test(attr(n, 'data-fk') || ''));
  const byRow = {};
  fields.forEach((f) => { byRow[attr(f, 'data-fk')] = f; });
  check('RC-3: each row at edit draws its field', fields.length === 2);
  check('RC-3: the field opens with the house draft', (byRow['edit-triage-f1'] || {}).value === 'THE HOUSE DRAFT');
  check('RC-3: his kept words win over the draft', (byRow['edit-triage-f2'] || {}).value === 'HIS OWN WORDS');
  check('RC-3: the field says Approve sends his words', view.textContent.indexOf('Approve sends these words') >= 0);
  check('RC-3: a row not at edit draws no field', deck.labels(view).filter((l) => l === 'Keep these words').length === 2);
})();

/* ---------- P4-4: many decisions on a phone are rows, opened in place ---------- */
function many(K) {
  const doc = K.planState.data.doc, store = doc.blocks.filter((b) => b.type === 'decision')[0];
  for (let i = 0; i < 10; i++) {
    const copy = JSON.parse(JSON.stringify(store));
    copy.id = 'd' + i;
    doc.blocks.push(copy);
  }
  doc.counts.decisions += 10;
  return doc;
}
(function () {
  let K = page('decide');
  many(K);
  K.planState.data.state.answers = { d3: { option: 'file', other: null } };
  let view = deck.wrap(K.viewPlan(), K);
  const rows = deck.byClass(view, 'pdrow');
  const d0 = rows.filter((r) => attr(r, 'data-key') === 'row-d0')[0];
  check('P4-4: over eight decisions, each is one row', rows.length === 12);
  check('P4-4: no decision card is drawn whole until opened',
        deck.all(view, (n) => deck.hasClass(n, 'pd-opt')).length === 0);
  check('P4-4: a row says the recommendation', d0.textContent.indexOf('recommended: As events on the card') >= 0);
  const mine = rows.filter((r) => deck.hasClass(r, 'mine'));
  check('P4-4: his change is marked on its row', mine.length === 1 && mine[0].textContent.indexOf('changed') >= 0
        && mine[0].textContent.indexOf('yours: In a file beside the plan') >= 0);
  check('P4-4: the questions stay whole', deck.labels(view).indexOf('Answer differently') >= 0);
  check('P4-4: one send, as before', deck.labels(view).filter((l) => l === 'Approve with these answers').length === 1);
  d0.onclick();
  view = deck.wrap(K.viewPlan(), K);
  check('P4-4: a tapped row opens its full card in place',
        deck.byClass(view, 'pdrow').length === 11 && deck.all(view, (n) => deck.hasClass(n, 'pd-opt')).length >= 2
        && deck.labels(view).indexOf('Fold') >= 0);
  K = page('decide', true);
  many(K);
  view = deck.wrap(K.viewPlan(), K);
  check('P4-4: the desk draws every decision whole', deck.byClass(view, 'pdrow').length === 0);
  K = page('decide');
  view = deck.wrap(K.viewPlan(), K);
  check('P4-4: eight or fewer stay whole on the phone', deck.byClass(view, 'pdrow').length === 0);
})();

/* ---------- Read all is the whole document, in order ---------- */
(function () {
  const K = page('read');
  const view = deck.wrap(K.viewPlan(), K);
  const kinds = deck.byClass(view, 'pblock').map((f) => classesOf(f));
  check('read: every kind the sample carries is drawn', ['t-compare', 't-table', 't-callout', 't-code', 't-diagram', 't-steps', 't-checklist', 't-decision', 't-batch', 't-questions']
    .every((k) => kinds.indexOf(k) >= 0));
  check('read: the table chip says its tone', deck.byClass(view, 'tone-ok').length >= 1);
  check('read: the diagram host is left to its owner', deck.byClass(view, 'pdiagram').every((n) => attr(n, 'data-morph') === 'skip'));
  check('read: a card ref is a link to the card', deck.all(view, (n) => n.tagName === 'A' && deck.hasClass(n, 'card')).length >= 1);
  check('read: the lede is drawn once', view.textContent.split('He is deciding').length === 2);
})();
function classesOf(f) { return deck.classes(f).filter((c) => c.indexOf('t-') === 0)[0]; }

/* ---------- the desk: the document and the round side by side ---------- */
(function () {
  const K = page(null, true);
  const view = deck.wrap(K.viewPlan(), K);
  check('desk: a grid of two', deck.byClass(view, 'pgrid').length === 1 && deck.byClass(view, 'pside').length === 1);
  check('desk: no pane switch', deck.byClass(view, 'ppane').length === 0);
  const side = deck.byClass(view, 'pside')[0];
  check('desk: the side lists every decision', deck.byClass(side, 'pdl-row').length === 2);
  check('desk: send is in the side', deck.labels(side).indexOf('Approve with these answers') >= 0);
})();

/* ---------- nothing a house wrote becomes markup ---------- */
(function () {
  const K = page('read');
  K.planState.data.doc.blocks.push({ type: 'paragraph', id: 'x.p1', section: 'x',
    text: [{ t: 'text', v: '<img src=x onerror=alert(1)>' }] });
  const view = deck.wrap(K.viewPlan(), K);
  check('safe: the tag is words', view.textContent.indexOf('<img src=x onerror=alert(1)>') >= 0);
  check('safe: no element was made from it', deck.all(view, (n) => n.tagName === 'IMG').length === 0);
})();

/* ---------- a finding sits under its block, and a broken ref is marked ---------- */
(function () {
  const K = page('read');
  K.planState.data.lint = { ok: false, findings: [{ rule: 'C7', level: 'error', block: 'goal.p1',
    text: '`keel/prompts.py:12` does not resolve at HEAD: no such file' }] };
  const view = deck.wrap(K.viewPlan(), K);
  check('lint: the badge says there is a break', view.textContent.indexOf('1 contract break') >= 0);
  const goal = deck.all(view, (n) => attr(n, 'data-bid') === 'goal.p1')[0];
  check('lint: the finding is under its block', goal && deck.byClass(goal, 'pfindings').length === 1);
  check('lint: the path is drawn broken', deck.byClass(view, 'broken').length >= 1);
  check('lint: its title says where it was read and why', attr(deck.byClass(view, 'broken')[0], 'title') === 'does not resolve at HEAD: no such file');
})();


/* ---------- a compare cell holding code and words flows as ONE line of text (P2-4) ---------- */
(function () {
  const K = page('read');
  const cmp = K.planState.data.doc.blocks.filter((b) => b.type === 'compare')[0];
  cmp.rows.push({ aspect: [{ t: 'text', v: 'Rerun' }],
    left: [{ t: 'text', v: 'one run per machine (machine_id unique, ' }, { t: 'ref', kind: 'path', code: true, v: 'app/models/rule_test_run.py:32' },
           { t: 'text', v: '); a new run silently deletes the old one.' }],
    right: [{ t: 'text', v: 'kept' }] });
  const view = deck.wrap(K.viewPlan(), K);
  const cells = deck.byClass(view, 'pcmp-cell').filter((c) => deck.hasClass(c, 'left'));
  const last = cells[cells.length - 1];
  const kids = last ? last.childNodes.filter((n) => n.nodeType === 1 || String(n.textContent).trim()) : [];
  check('compare: a cell is its side label and ONE text run', kids.length === 2 && deck.hasClass(kids[1], 'pcmp-text'));
  check('compare: the code sits inside the text run', kids[1] && deck.all(kids[1], (n) => deck.hasClass(n, 'pref')).length === 1);
})();


/* ---------- P2-5: a page of its own, with a slim header ---------- */
(function () {
  const K = page('read');
  K.planState.data.docs = ['plan', 'outcome'];
  const view = deck.wrap(K.viewPlan(), K);
  const root = deck.byClass(view, 'planroute')[0];
  check('page: not inside a deck panel', root && !deck.hasClass(root, 'panel') && deck.byClass(view, 'panel').length === 0);
  const links = deck.all(view, (n) => n.tagName === 'A').map((a) => attr(a, 'href'));
  check('page: a link back to the card in the deck', links.indexOf('/?view=cards&card=c-900&space=personal') >= 0);
  check('page: a link to the other document', links.indexOf('/outcome/c-900') >= 0);
  const out = page('read', false, '/outcome/c-900');
  check('page: /outcome/<id> is the outcome', out.planState.doc === 'outcome' && out.planState.id === 'c-900');
})();

/* ---------- P2-6: notes are visible without instructions ---------- */
(function () {
  const K = page('read');
  const view = deck.wrap(K.viewPlan(), K);
  const frames = deck.byClass(view, 'pblock').filter((f) => !deck.hasClass(f, 'pb-h'));
  check('notes: every block carries a note button', frames.length > 5 &&
    frames.every((f) => f.childNodes.some((n) => n.nodeType === 1 && deck.hasClass(n, 'pnote-add'))));
  check('notes: a one-line hint says how, the first time', deck.byClass(view, 'phint').length === 1);
})();
(function () {
  const K = page(null, true);
  K.planState.data.state.comments = [{ event: 41, block: 'goal.p1', quote: 'the words', text: 'change this' }];
  const view = deck.wrap(K.viewPlan(), K);
  const goal = deck.all(view, (n) => attr(n, 'data-bid') === 'goal.p1')[0];
  const pinned = goal ? deck.byClass(goal, 'pnote') : [];
  check('notes: his note is pinned on its block', pinned.length === 1 && pinned[0].textContent.indexOf('change this') >= 0);
  check('notes: a pinned note can be edited and removed', pinned[0] && deck.labels(pinned[0]).join(',') === 'Edit,Remove');
  const button = goal && goal.childNodes.filter((n) => n.nodeType === 1 && deck.hasClass(n, 'pnote-add'))[0];
  check('notes: the block\'s note button says it holds one', button && deck.hasClass(button, 'has'));
  const side = deck.byClass(view, 'pside')[0];
  const jumps = deck.all(side, (n) => n.tagName === 'A' && attr(n, 'href') === '#b-goal.p1');
  check('notes: the round lists it with a jump to its block', jumps.length === 1);
})();


/* ---------- P2-2: an embedded board keeps its walk ---------- */
(function () {
  const K = page('read');
  K.planState.data.doc.blocks.push({ type: 'board', id: 'proposal.board9', section: 'proposal', ref: 'b-009',
    title: [], board_title: 'filler board',
    ops: ['node a server "A"', 'node b box "B"', 'edge a -> b', 'step a "first filler step"',
          'step b "second filler step"', 'note a "a filler note"'] });
  const view = deck.wrap(K.viewPlan(), K);
  const frame = deck.all(view, (n) => attr(n, 'data-bid') === 'proposal.board9')[0];
  const walk = frame ? deck.byClass(frame, 'pwalk') : [];
  check('embed: the board\'s walk is under the diagram', walk.length === 1);
  check('embed: it says what hangs on the board', walk[0] && walk[0].textContent.indexOf('2 steps, 1 note') >= 0);
  check('embed: the steps are in it', walk[0] && walk[0].textContent.indexOf('second filler step') >= 0);
  /* R3-1: one button per diagram. "Full screen" and "Open b-NNN" went to the same place. */
  const head = frame ? deck.byClass(frame, 'pdia-title')[0] : null;
  const buttons = head ? deck.all(head, (n) => n.tagName === 'A' || n.tagName === 'BUTTON') : [];
  check('embed: exactly one button on an embedded board', buttons.length === 1);
  check('embed: it says Open board', buttons[0] && buttons[0].textContent === 'Open board');
  check('embed: it opens the board full screen, with its walk', buttons[0] && attr(buttons[0], 'href') === '/board/b-009?full=1');
  check('embed: no Full screen and no Open b-NNN beside it', frame && deck.labels(frame).indexOf('Full screen') < 0 &&
    deck.labels(frame).indexOf('Open b-009') < 0);
})();
/* ---------- c-602: a board the outcome carried over from the plan says so ---------- */
(function () {
  const K = page('read');
  const ops = ['node a server "A"', 'node b box "B"', 'edge a -> b "call()"'];
  K.planState.data.doc.blocks.push({ type: 'board', id: 'why.board1', section: 'why', ref: 'b-156', title: [],
    board_title: 'plan flow', ops: ops, carried: 'from the plan, not updated' });
  K.planState.data.doc.blocks.push({ type: 'board', id: 'why.board2', section: 'why', ref: 'b-160', title: [],
    board_title: 'Code flow: read it in this order', ops: ops });
  const view = deck.wrap(K.viewPlan(), K);
  const frame = (bid) => deck.all(view, (n) => attr(n, 'data-bid') === bid)[0];
  const chip = (f) => f ? deck.byClass(f, 'pdia-carried') : [];
  check('carried: the plan\'s board is tagged in its head', chip(frame('why.board1')).length === 1 &&
    chip(frame('why.board1'))[0].textContent === 'from the plan, not updated');
  check('carried: the tag sits in the title, beside Open board',
    frame('why.board1') && deck.byClass(deck.byClass(frame('why.board1'), 'pdia-title')[0], 'pdia-carried').length === 1);
  check('carried: a board drawn after the plan carries no tag', frame('why.board2') && chip(frame('why.board2')).length === 0);
})();
(function () {
  const K = page('read');
  K.planState.data.doc.blocks.push({ type: 'diagram', id: 'proposal.inline9', section: 'proposal', source: 'board',
    kind: 'graph', title: [], ops: ['node a server "A"', 'node b box "B"', 'edge a -> b'] });
  const view = deck.wrap(K.viewPlan(), K);
  const frame = deck.all(view, (n) => attr(n, 'data-bid') === 'proposal.inline9')[0];
  const head = frame ? deck.byClass(frame, 'pdia-title')[0] : null;
  const buttons = head ? deck.all(head, (n) => n.tagName === 'A' || n.tagName === 'BUTTON') : [];
  check('inline diagram: exactly one button, Full screen', buttons.length === 1 && buttons[0].textContent === 'Full screen');
})();


/* ---------- P2-9: his question, and the house's answer pinned under it ---------- */
(function () {
  const K = page(null, true);
  K.planState.data.state.asks = [
    { event: 51, block: 'goal.p1', quote: null, text: 'why not a file?', reply: { event: 52, text: 'one store is the rule' } },
    { event: 53, block: 'goal.p1', quote: 'the words', text: 'and this?', reply: null }];
  const view = deck.wrap(K.viewPlan(), K);
  const goal = deck.all(view, (n) => attr(n, 'data-bid') === 'goal.p1')[0];
  const pinned = goal ? deck.byClass(goal, 'pask-q') : [];
  check('ask: his questions are pinned on their block', pinned.length === 2);
  check('ask: the answer is under its question', pinned[0] && deck.byClass(pinned[0], 'pask-answer')[0] &&
    deck.byClass(pinned[0], 'pask-answer')[0].textContent === 'one store is the rule');
  check('ask: an open one says it is waiting', pinned[1] && pinned[1].textContent.indexOf('waiting for the house') >= 0);
  const side = deck.byClass(view, 'pside')[0];
  check('ask: the round lists them with a jump', deck.all(side, (n) => n.tagName === 'A' && attr(n, 'href') === '#b-goal.p1').length === 2);
})();

/* ---------- c-537: once the gate is answered, a receipt and no buttons ---------- */
(function () {
  [false, true].forEach(function (desk) {
    const where = desk ? 'desk' : 'phone';
    const K = page('decide', desk);
    K.planState.data.answerable = false;
    K.planState.data.receipt = { gate: 'plan', mode: 'approve', actor: 'human', at: '2026-09-24T17:08:00+00:00',
      said: 'Approved by you', now: 'house resumed, building', tone: 'accent', log: null, link: null, again: false };
    const view = deck.wrap(K.viewPlan(), K);
    const labels = deck.labels(view);
    check(where + ': answered: no Approve', labels.indexOf('Approve with these answers') < 0);
    check(where + ': answered: no Send back', labels.indexOf('Send back with notes') < 0);
    check(where + ': answered: the receipt says who and when', /Approved by you/.test(view.textContent) && /at \d\d:\d\d/.test(view.textContent));
    check(where + ': answered: and what is happening now', /house resumed, building/.test(view.textContent));
    check(where + ': answered: no red no-gate line', !/no gate open/.test(view.textContent) && !/gate open/.test(view.textContent));
    check(where + ': answered: a decision cannot be changed after it', deck.all(view, (n) => deck.hasClass(n, 'pd-opt')
      && n.getAttribute('disabled') === null && n.tagName === 'BUTTON').length === 0);
  });
})();
(function () {
  const K = page('read', true, '/outcome/c-900');
  K.planState.data.gate = 'outcome';
  K.planState.data.answerable = true;
  K.planState.data.receipt = { gate: 'outcome', mode: 'approve', actor: 'human', at: '2026-09-24T17:08:00+00:00',
    said: 'Approved by you', now: 'refused: failed: tests.test_x', tone: 'crit', log: '/api/artifact/tok', link: null, again: true };
  const view = deck.wrap(K.viewPlan(), K);
  check('refused: Approve is offered again', deck.labels(view).indexOf('Approve again') >= 0);
  check('refused: the receipt names the failures', /refused: failed: tests\.test_x/.test(view.textContent));
  check('refused: the log is a link', deck.all(view, (n) => n.tagName === 'A' && n.getAttribute('href') === '/api/artifact/tok').length === 1);
})();
(function () {
  const K = page('read', true);
  K.planState.data.gate = null;
  K.planState.data.answerable = false;
  K.planState.data.receipt = null;
  const view = deck.wrap(K.viewPlan(), K);
  check('no gate: no buttons', deck.labels(view).indexOf('Approve with these answers') < 0);
  check('no gate: no red line', deck.byClass(view, 'crit').length === 0);
})();

/* ---------- c-604 review: an approved plan's board links the board as approved ---------- */
(function () {
  const K = page('read');
  const ops = ['board "Flow"', 'node a box "a"', 'node b box "b"', 'edge a -> b', 'step a "one"'];
  const hrefs = (b) => deck.all(deck.wrap(K.planBlocks.block(b), K), (n) => n.tagName === 'A').map((n) => n.getAttribute('href'));
  const pinned = hrefs({ type: 'board', id: 'x1', ref: 'b-7', ops: ops, upto: 6 });
  check('c-604: a pinned embed opens its board as approved', pinned.length && pinned.every((h) => h.indexOf('upto=6') >= 0));
  const redrawn = hrefs({ type: 'board', id: 'x2', ref: 'b-7', ops: ops, planned_upto: 6 });
  check('c-604: an outcome board redrawn since offers the plan\'s picture',
        redrawn.indexOf('/board/b-7?full=1&upto=6') >= 0 && redrawn.indexOf('/board/b-7?full=1') >= 0);
})();

/* ---------- c-605: the sandbox's third run ---------- */
(function () {
  /* a plan with nothing to decide is approved plainly */
  const K = page('read', true);
  K.planState.data.doc.blocks = K.planState.data.doc.blocks.filter((b) => !K.planBlocks.ANSWERABLE[b.type]);
  const view = deck.wrap(K.viewPlan(), K);
  const labels = deck.labels(view);
  check('c-605: 0 decisions: plain Approve', labels.indexOf('Approve') >= 0 && labels.indexOf('Approve with these answers') < 0);
  check('c-605: 0 decisions: the line says there is nothing to decide', /Nothing to decide/.test(view.textContent));
})();
(function () {
  /* while his send is in flight, a receipt that says "house resumed" is not yet known */
  const K = page('decide', true);
  K.planState.data.answerable = false;
  K.planState.data.receipt = { gate: 'plan', mode: 'approve', actor: 'human', at: '2026-09-24T17:08:00+00:00',
    said: 'Approved by you', now: 'house resumed, building', tone: 'accent', log: null, link: null, again: false };
  K.App.pending[K.pendKey({ verb: 'plan.send', id: K.planState.id })] = { label: 'Sending…', subject: K.planState.id, at: 0 };
  const inFlight = deck.wrap(K.viewPlan(), K).textContent;
  check('c-605: in flight: no "house resumed"', inFlight.indexOf('house resumed') < 0 && /sending your answer/.test(inFlight));
  K.App.pending = {};
  K.planState.settling = true;
  check('c-605: answered, before the load after it: still not "house resumed"',
        deck.wrap(K.viewPlan(), K).textContent.indexOf('house resumed') < 0);
  K.planState.settling = false;
  check('c-605: once a load after the send has landed, the receipt says what the server says',
        /house resumed, building/.test(deck.wrap(K.viewPlan(), K).textContent));
  K.planState.data.receipt.now = "held until the house's turn ends, then building";
  K.App.pending[K.pendKey({ verb: 'plan.send', id: K.planState.id })] = { label: 'Sending…', subject: K.planState.id, at: 0 };
  check('c-605: a held receipt is never covered', /held until the house/.test(deck.wrap(K.viewPlan(), K).textContent));
})();
(function () {
  /* a toast with its node gone makes it again rather than throwing inside the answer */
  const K = page('read');
  const doc = K._doc, made = [];
  doc.getElementById = () => null;
  doc.body = { appendChild: (n) => { made.push(n); return n; } };
  let threw = null;
  try { K.toast('shipped'); } catch (e) { threw = e.message; }
  check('c-605: a missing toast is made again, not a throw', threw === null && made.length === 1 && made[0].textContent === 'shipped');
})();

/* ---------- c-667: the outcome page's send panel says Adopt for a proposal ---------- */
(function () {
  const K = page('read', false, '/outcome/c-900');
  const words = K.plan.approveWords || function () { return {}; };
  const said = K.plan.sentWord || function () { return null; };
  const card = (extra) => Object.assign({ id: 'c-900', space: 'personal', repo: null }, extra);
  const tier = words(card({ options: { tier_proposal: 'personal/api' } }), {}, false, true);
  check('c-667: a proposal\'s outcome page says Adopt and asks the Adopt confirm: ' + JSON.stringify(tier),
        tier.word === 'Adopt' && tier.confirm === 'Adopt c-900? This writes its draft into the tier (the rules) of the api repo in the personal space.');
  const plain = words(card({}), {}, false, true);
  check('c-667: research keeps Done on its page: ' + JSON.stringify(plain), plain.word === 'Done' && plain.confirm === 'Mark c-900 done?');
  const repo = words(card({ repo: 'keel' }), {}, false, false);
  check('c-667: a repo card keeps Approve outcome on its page: ' + JSON.stringify(repo),
        repo.word === 'Approve outcome' && repo.confirm === 'Approve the outcome of c-900? This publishes it.');
  /* c-719: research is known by its kind on either side, so a work research card's page
     says Done and never "This publishes it" */
  const isResearch = K.plan.isResearch || function () { return false; };
  check('c-719: a work research card is research on its page',
        isResearch(card({ space: 'work', repo: 'api', kind: 'research' }), false) === true
        && isResearch(card({ space: 'work', repo: 'api', kind: 'feature' }), false) === false
        && isResearch(card({}), false) === true && isResearch(card({}), true) === false);
  const work = words(card({ space: 'work', repo: 'api', kind: 'research' }), {}, false,
                     isResearch(card({ space: 'work', repo: 'api', kind: 'research' }), false));
  check('c-719: a work research card\'s page says Done: ' + JSON.stringify(work),
        work.word === 'Done' && work.confirm === 'Mark c-900 done?');
  const held = said({ where: '/t/CLAUDE.md', stage: 'review', note: 'adopted into /t/CLAUDE.md, but c-900 was not moved to done: held' });
  check('c-667: adopted but not moved is an error on the outcome page too: ' + JSON.stringify(held),
        !!held && held.err === true && /was not moved to done/.test(held.text));
  const done = said({ where: '/t/CLAUDE.md', stage: 'done', note: 'adopted into /t/CLAUDE.md' });
  check('c-667: an adopted outcome says where', !!done && done.err === false && done.text === 'adopted into /t/CLAUDE.md');
  check('c-667: any other send says what it said', said({ resumed: {} }) === 'sent, house resumed' && said({ relayed: 'x', note: 'n' }) === 'n');
})();

process.stdout.write(JSON.stringify(fails.length ? { ok: false, failed: fails } : { ok: true }));
