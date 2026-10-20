/* One viewer for a card's pages (c-644), on the real plan shell: the plan modules loaded
 * whole under the DOM stand-in, the context page drawn from the payload the route answered,
 * then the tabs read on each of the shell's pages, and the flow's moves on the page.
 *
 * Usage: node viewer.js <path to app/> <payload.json>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const fs = require('fs');
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const PAYLOAD = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const MODULES = ['ui.core.js', 'ui.boardlayout.js', 'ui.board.js', 'ui.planlook.js', 'ui.plandiagram.js', 'ui.plancode.js',
                 'ui.planfinding.js', 'ui.receipt.js', 'ui.planblocks.js', 'ui.plan.js', 'ui.ci.js', 'ui.shipping.js', 'ui.shipsendback.js',
                 'ui.comments.js'];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }
const id = PAYLOAD.card.id;
const acted = [];
function fetch(url, opts) {
  if (String(url) === '/api/action') acted.push(JSON.parse(opts.body));
  return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ ok: true, result: {} }) });
}

globalThis.location = { pathname: '/context/' + id, search: '' };
const K = deck.load(APP, MODULES, { desk: true, fetch: fetch });
K.render = K.renderBody = function () {};
K.App.data = deck.state([]);
K.App.space = 'personal';
K.readPlanRoute();
/* a finding on a block, as the outcome's contract would attach one: never drawn here (r1.F5) */
const firstBlock = (PAYLOAD.doc.blocks || [])[0];
if (firstBlock) PAYLOAD.lint = Object.assign({}, PAYLOAD.lint, { findings: [{ rule: 'C3', level: 'error', block: firstBlock.id, text: 'x' }] });
K.planState.data = PAYLOAD;
const keyed = (view, re) => deck.all(view, (n) => n.getAttribute && re.test(n.getAttribute('data-key') || ''));

/* ---------- the context page ---------- */
let view = deck.wrap(K.viewPlan(), K);
const text = view.textContent;
check('the context is drawn as the record\'s text', text.indexOf('The export retries now.') >= 0 && text.indexOf('with jitter') >= 0);
const word = deck.all(view, (n) => /\bpdocword\b/.test(n.getAttribute('class') || ''))[0];
check('the context page\'s header word is Context', !!word && word.textContent === 'Context');
check('the context page has no gate', deck.labels(view).every((w) => !/^Approve|^Send back/.test(w)));
check('the context page draws no contract findings, even when the answer had one',
      !!firstBlock && deck.all(view, (n) => /\bpfindings\b/.test(n.getAttribute('class') || '')).length === 0);

/* ---------- the tabs: every page, one order, the current marked ---------- */
const tabs = keyed(view, /^tabs$/)[0];
const words = tabs ? deck.all(tabs, (n) => /\bptab\b/.test(n.getAttribute('class') || '')).map((n) => n.textContent) : [];
check('the tabs are the card\'s pages in order: ' + words.join(), words.join() === 'Plan,Context,Comments,CI');
const here = tabs ? deck.all(tabs, (n) => n.getAttribute('aria-current') === 'page') : [];
check('the current page is marked and is not a link', here.length === 1 && here[0].textContent === 'Context' && here[0].tagName !== 'A');
const hrefs = tabs ? deck.all(tabs, (n) => n.tagName === 'A').map((n) => n.getAttribute('href')) : [];
check('every other page is a link: ' + hrefs.join(), hrefs.join() === ['/plan/', '/comments/', '/ci/'].map((p) => p + id).join());
/* the same tabs on the CI and comments pages, in the same order */
const ci = deck.wrap(K.docTabs(PAYLOAD.card, PAYLOAD.docs, 'ci'), K);
check('the CI page\'s tabs keep the order', deck.all(ci, (n) => /\bptab\b/.test(n.getAttribute('class') || '')).map((n) => n.textContent).join() === 'Plan,Context,Comments,CI');
check('a card with one page has no tabs', K.docTabs(PAYLOAD.card, ['plan'], 'plan') === null);
/* Outcome and Context are one record: never both tabs (r1.F1, F7) */
check('one record, one tab', deck.wrap(K.docTabs(PAYLOAD.card, ['plan', 'outcome'], 'context'), K).textContent === 'PlanContext'
      && deck.wrap(K.docTabs(PAYLOAD.card, ['plan', 'outcome', 'context'], 'plan'), K).textContent === 'PlanOutcome');
check('the current page is a tab even when the list misses it', deck.wrap(K.docTabs(PAYLOAD.card, ['plan'], 'comments'), K).textContent === 'PlanComments');

/* ---------- the flow's moves, in the groups the flow names ---------- */
const flows = keyed(view, /^flows$/)[0];
const groups = flows ? deck.all(flows, (n) => n.getAttribute('role') === 'group').map((g) => [g.getAttribute('aria-label'), deck.labels(g)]) : [];
check('the moves are grouped by the flow\'s names: ' + JSON.stringify(groups),
      JSON.stringify(groups) === JSON.stringify([['Try it live', ['Merge to dev review', 'Rebuild the preview']],
                                                 ['Early to master', ['Early merge to master']]]));
const move = flows ? deck.buttons(flows).filter((b) => b.textContent === 'Merge to dev review')[0] : null;
if (move) move.onclick({ preventDefault() {}, stopPropagation() {} });
/* a note from the context page is a mark on the outcome, the same file (r1.F2) */
K.plan.keepNote({ block: firstBlock ? firstBlock.id : 'top', quote: null }, 'a note');
setImmediate(() => {
  const noted = acted.filter((a) => a.verb === 'mark')[0] || {};
  check('a note from the context page is the outcome\'s: ' + JSON.stringify(noted), noted.data && noted.data.doc === 'outcome');
  acted.splice(acted.indexOf(noted), 1);
  const sent = acted[0] || {};
  check('a move sends the pane\'s flow.move: ' + JSON.stringify(sent), sent.verb === 'flow.move' && sent.id === id && sent.move === 'to-dev');
  check('a page with no moves draws none', K.flowBar(PAYLOAD.card, []) === null);
  process.stdout.write(JSON.stringify(fails.length ? { fails: fails } : { ok: true }));
});
