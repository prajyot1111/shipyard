/* The card pane's controls by phase (c-601), rendered under node and read back.
 *
 * Usage: node deck-phases.js <path to app/>
 * Output: {"table": <K.CONTROL_PHASES>, "drawn": {<case>: [keys]}, "fails": [names]}.
 *
 * `tests/test_deck_phases.py` pins the table against its own copy and against the Atlas,
 * checks every drawn key is a row of it, and reads the named checks below.
 */
'use strict';
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const MODULES = ['ui.core.js', 'ui.idle.js', 'ui.findcore.js', 'ui.findpages.js', 'ui.find.js', 'ui.tips.js', 'ui.modal.js', 'ui.shipping.js', 'ui.shipsendback.js',
                 'ui.cards.js', 'ui.tree.js', 'ui.reviews.js', 'ui.views.js', 'ui.atlas.js', 'ui.board.js'];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

function page(cards, opts, extra) {
  const K = deck.load(APP, MODULES, opts || {});
  K.App.data = deck.state(cards, extra);
  K.App.space = 'personal';
  K.render = K.renderBody = function () {};
  return K;
}
function keysOf(K, c) {
  return deck.wrap(K.gateActions(c).concat(K.cardItems(c)), K).childNodes
    .map((n) => n.getAttribute && n.getAttribute('data-key')).filter(Boolean);
}
const SESSION = 'aaaaaaaa-1111-4000-8000-000000000001';
const LIVE = { bg_id: 'aaaaaaaa', status: 'idle', kind: 'background', session_id: SESSION, recorded: true, working: false };
const VOICE_OFF = { health: { level: 'green', reasons: [], services: [{ name: 'voice', state: 'not installed here', level: 'off', at: null }] } };
const drawn = {};

/* ---------- each phase, the way the e2e run met it ---------- */
const cases = {
  inbox: deck.card('c-1', { stage: 'inbox' }),
  'blocked-never-started': deck.card('c-2', { stage: 'assigned', blocked_reason: 'Workspace not trusted',
                                              derived: { needs_you: true } }),
  building: deck.card('c-3', { stage: 'building', session_id: SESSION, house: LIVE,
                               options: { app_link: 'https://claude.ai/code/session_x' } }),
  review: deck.card('c-4', { stage: 'review', session_id: SESSION, house: LIVE, plan_ref: 'p.md', output_ref: 'o',
                             derived: { needs_you: true, outcome_gate: true } }),
  /* c-605: a work card whose outcome has its own page */
  'review-outcome-page': deck.card('c-7', { space: 'work', stage: 'review', session_id: SESSION, house: LIVE,
                                            plan_ref: 'p.md', output_ref: 'https://example.invalid/pr/2',
                                            links: { formats: { outcome: true }, context: '/a/context.md' },
                                            derived: { needs_you: true, outcome_gate: true } }),
  done: deck.card('c-5', { stage: 'done', session_id: SESSION, plan_ref: 'p.md', output_ref: 'o',
                           links: { plan: '/a/plan.md', output: 'https://example.invalid/pr/1', context: '/a/context.md' },
                           options: { app_link: 'https://claude.ai/code/session_x' } }),
  'done-blocked': deck.card('c-6', { stage: 'done', session_id: SESSION, blocked_reason: 'x',
                                     derived: { needs_you: true } })
};
Object.keys(cases).forEach((name) => {
  const K = page([cases[name]], { desk: true });
  drawn[name] = keysOf(K, cases[name]);
});

const never = drawn['blocked-never-started'];
check('a card that never started draws no Resume house', never.indexOf('resume') < 0 && never.indexOf('resume-house') < 0);
check('a card that never started still draws Retry', never.indexOf('retry') >= 0);
['resume-house', 'resume-app', 'talk', 'talk-voice', 'open-app', 'retry', 'resume', 'answer', 'logs', 'stop', 'rotate']
  .forEach((k) => check('a done card draws no ' + k, drawn.done.indexOf(k) < 0 && drawn['done-blocked'].indexOf(k) < 0));
check('a done card keeps its reads and Archive', ['open-plan', 'open-output', 'archive'].every((k) => drawn.done.indexOf(k) >= 0));
check('c-787: a done card draws Drop in', drawn.done.indexOf('dropin') >= 0);
check('a review card draws no Split', drawn.review.indexOf('split') < 0);
/* c-605: at review the outcome's page is one tap from the pane, and leads */
(function () {
  const c = cases['review-outcome-page'];
  const K = page([c], { desk: true });
  const nodes = deck.wrap(K.gateActions(c), K).childNodes;
  const open = nodes.filter((n) => n.getAttribute && n.getAttribute('data-key') === 'open-outcome')[0];
  check('c-605: Open outcome is drawn at review', !!open && open.textContent === 'Open outcome');
  check('c-605: Open outcome is the primary, Approve outcome is not', !!open && deck.hasClass(open, 'primary')
        && nodes.filter((n) => n.getAttribute && n.getAttribute('data-key') === 'approve-outcome' && deck.hasClass(n, 'primary')).length === 0);
  check('c-605: a card with no outcome page draws none', drawn.review.indexOf('open-outcome') < 0);
  /* c-605 review: an unpublished outcome has one primary, Open outcome */
  const u = Object.assign({}, c, { unpublished: 'no pull request yet' });
  const prim = deck.wrap(page([u], { desk: true }).gateActions(u), K).childNodes
    .filter((n) => n.getAttribute && deck.hasClass(n, 'primary')).map((n) => n.getAttribute('data-key'));
  check('c-605 review: unpublished at review: Open outcome is the one primary', prim.join() === 'open-outcome');
})();
check('a building card with a live house draws Logs and Stop', ['logs', 'stop', 'talk-voice'].every((k) => drawn.building.indexOf(k) >= 0));

/* ---------- c-601 review ---------- */
(function () {
  /* a tracking card he sent back with every slice done reads at review (parent_stage) */
  const regate = deck.card('c-10', { stage: 'building', children: ['c-11'],
                                     derived: { tracking: true, regate: true, parent_stage: 'review' } });
  check('Back to your gate is drawn on a regate card that reads at review',
        keysOf(page([regate], { desk: true }), regate).indexOf('regate') >= 0);
  /* a done card whose session the harness still lists keeps its post-mortem Logs, nothing more */
  const lingering = deck.card('c-12', { stage: 'done', session_id: SESSION, lingering: true });
  const lk = keysOf(page([lingering], { desk: true }), lingering);
  check('a done card still listed offers Logs', lk.indexOf('logs') >= 0);
  check('and no Stop', lk.indexOf('stop') < 0);
  /* two live sessions named for the card: the stale one gets its own Stop */
  const twinned = deck.card('c-13', { stage: 'building', session_id: SESSION,
                                      house: Object.assign({}, LIVE, { twins: ['bbbbbbbb'] }) });
  const tk = keysOf(page([twinned], { desk: true }), twinned);
  check('a stale twin session can be stopped from the pane', tk.indexOf('stop-twin') >= 0 && tk.indexOf('stop') >= 0);
  check('no twin, no such Stop', drawn.building.indexOf('stop-twin') < 0);
  /* a Now tile asks the same table */
  const K = page([cases['done-blocked'], cases['blocked-never-started']], { desk: true });
  const tile = (c) => K.actionSources.tile(c).map((n) => n.getAttribute('data-key'));
  check('a done card\'s tile draws no Retry or Resume', tile(cases['done-blocked']).every((k) => ['retry', 'resume', 'resume-app'].indexOf(k) < 0));
  check('a never-started card\'s tile draws no Resume', tile(cases['blocked-never-started']).indexOf('resume') < 0
        && tile(cases['blocked-never-started']).indexOf('retry') >= 0);
})();

/* ---------- c-604 review: the shipping column is asked by the Now tile ---------- */
(function () {
  const ship = deck.card('c-30', { stage: 'shipping', space: 'work', repo: 'api', session_id: SESSION,
    house: Object.assign({}, LIVE, { status: 'busy', working: true }),
    options: { app_link: 'https://claude.ai/code/session_x', shipping: { facts: {}, local: {} } } });
  const K = page([ship], { desk: true });
  const tile = K.actionSources.tile(ship).map((n) => n.getAttribute('data-key'));
  check('a working shipping house\'s Now tile draws Open in app, Logs and Stop',
        ['open-app', 'logs', 'stop'].every((k) => tile.indexOf(k) >= 0));
  const blocked = Object.assign({}, ship, { blocked_reason: 'x' });
  const bt = K.actionSources.tile(blocked).map((n) => n.getAttribute('data-key'));
  check('a blocked shipping house\'s tile is Unblock alone', bt.join() === 'unblock');
})();

/* ---------- Talk only where voice is installed ---------- */
(function () {
  const K = page([cases.building], { desk: true }, VOICE_OFF);
  check('Talk to this house is not drawn where voice is not installed', keysOf(K, cases.building).indexOf('talk-voice') < 0);
})();

/* ---------- c-642: CI, on a card with a repo whose space has `ci` ready, from the build on ---------- */
(function () {
  function keysWithCi(c, ready) {
    const K = page([c], { desk: true });
    K.App.data.readiness = { install: {}, spaces: { personal: { ci: { ready: ready, why: 'x', step: 'integrations' } } } };
    return keysOf(K, c);
  }
  const atReview = deck.card('c-30', { stage: 'review', repo: 'keel', session_id: SESSION, house: LIVE, plan_ref: 'p.md', output_ref: 'o' });
  check('c-642: CI is drawn at review where the space reads builds', keysWithCi(atReview, true).indexOf('open-ci') >= 0);
  check('c-642: not where the space does not', keysWithCi(atReview, false).indexOf('open-ci') < 0);
  check('c-642: not before the build', keysWithCi(deck.card('c-31', { stage: 'planning', repo: 'keel' }), true).indexOf('open-ci') < 0);
  check('c-642: not on a card with no repo', keysWithCi(deck.card('c-32', { stage: 'review', repo: null, plan_ref: 'p.md', output_ref: 'o' }), true).indexOf('open-ci') < 0);
  const shipping = deck.card('c-33', { stage: 'shipping', repo: 'keel', session_id: SESSION, house: LIVE });
  check('c-642: and at shipping', keysWithCi(shipping, true).indexOf('open-ci') >= 0);
})();

/* ---------- c-640: a move he makes is a button at its stages, on a card with a house ---------- */
(function () {
  const FLOW = { name: 'Ours', moves: [{ id: 'to-dev', label: 'Merge to dev review', by: 'you', from: 'card', to: 'dev',
                                         stages: ['review', 'shipping'], group: 'Try it live', about: 'try it live' },
                                       { id: 'pr', label: 'Draft pull request', by: 'house', from: 'card', to: 'base',
                                         stages: ['review'], step: 'pr' }] };
  function keysWithFlow(c, extra) {
    const K = page([c].concat(extra || []), { desk: true });
    K.App.data.spaces.personal.flow = FLOW;
    return keysOf(K, c);
  }
  const atReview = deck.card('c-20', { stage: 'review', session_id: SESSION, house: LIVE, plan_ref: 'p.md', output_ref: 'o' });
  const reviewKeys = keysWithFlow(atReview);
  check('c-640: his move is drawn at review', reviewKeys.indexOf('flow-to-dev') >= 0);
  check('c-640: a house move is not a button', reviewKeys.indexOf('flow-pr') < 0);
  check('c-640: not at building', keysWithFlow(deck.card('c-21', { stage: 'building', session_id: SESSION, house: LIVE }))
    .indexOf('flow-to-dev') < 0);
  check('c-640: not without a house', keysWithFlow(deck.card('c-22', { stage: 'review', plan_ref: 'p.md', output_ref: 'o' }))
    .indexOf('flow-to-dev') < 0);
  /* the card's own stage decides, as the server does, not its parent's */
  const parent = deck.card('c-23', { stage: 'review', derived: { tracking: true } });
  const child = deck.card('c-24', { stage: 'building', parent: 'c-23', session_id: SESSION, house: LIVE,
                                     derived: { parent_stage: 'review' } });
  const K = page([parent, child], { desk: true });
  K.App.data.spaces.personal.flow = FLOW;
  check('c-640: a building child of a parent at review offers none', K.flowMoves(child).length === 0);
  check('c-640: K.flowMoves names his move at review', K.flowMoves(atReview).map((m) => m.id).join() === 'to-dev');
  /* c-732: a move that names `bases` is offered by the base the SERVER says applies (`base`,
     `merging.card_base`), never the option as stored: a card on an integrated repo holding
     base=main is offered no move for main; one whose base applies is */
  const early = { id: 'early', label: 'Early merge', by: 'you', from: 'card', to: 'base', stages: ['review'], bases: ['main'] };
  const K2 = page([atReview], { desk: true });
  K2.App.data.spaces.personal.flow = Object.assign({}, FLOW, { moves: FLOW.moves.concat([early]) });
  const holding = Object.assign({}, atReview, { options: { base: 'main' }, base: '' });
  const applies = Object.assign({}, atReview, { options: { base: 'main' }, base: 'main' });
  check('c-732: an integrated card holding base=main is offered no move for main: ' + K2.flowMoves(holding).map((m) => m.id).join(),
        K2.flowMoves(holding).map((m) => m.id).indexOf('early') < 0);
  check('c-732: a card whose base applies is', K2.flowMoves(applies).map((m) => m.id).indexOf('early') >= 0);
  /* c-644: at shipping too (c-641's moves run there; the shipping card items never drew them) */
  const atShipping = deck.card('c-25', { stage: 'shipping', session_id: SESSION, house: LIVE, repo: 'keel' });
  check('c-644: his move is drawn at shipping', keysWithFlow(atShipping).indexOf('flow-to-dev') >= 0);
})();

/* ---------- c-644: the flow names the groups its moves are drawn in ---------- */
(function () {
  const FLOW = { name: 'Ours', moves: [
    { id: 'to-dev', label: 'Merge to dev review', by: 'you', stages: ['review'], group: 'Try it live' },
    { id: 'early', label: 'Early merge to master', by: 'you', stages: ['review'], group: 'Early to master' },
    { id: 'redo', label: 'Rebuild the preview', by: 'you', stages: ['review'], group: 'Try it live' },
    { id: 'sign', label: 'Sign off', by: 'you', stages: ['review'], group: 'Decide' },
    { id: 'tidy', label: 'Tidy the branch', by: 'you', stages: ['review'] },
    { id: 'pr', label: 'Draft pull request', by: 'house', stages: ['review'], group: 'Pull request' }] };
  const c = deck.card('c-60', { stage: 'review', session_id: SESSION, house: LIVE, plan_ref: 'p.md', output_ref: 'o' });
  const K = page([c], { desk: true });
  K.App.data.spaces.personal.flow = FLOW;
  const nodes = K.gateActions(c).concat(K.cardItems(c));
  const groups = K.grouped(c, nodes).map((x) => [x.group.name, x.nodes.map((n) => n.getAttribute('data-key'))]);
  const named = (name) => (groups.filter((g) => g[0] === name)[0] || [null, []])[1];
  check('c-644: a flow group holds its moves in the flow\'s order', named('Try it live').join() === 'flow-to-dev,flow-redo');
  check('c-644: each group the flow names is its own', named('Early to master').join() === 'flow-early');
  check('c-644: a move named into Decide joins the card\'s Decide', named('Decide').indexOf('flow-sign') >= 0);
  const gate = deck.card('c-61', { stage: 'review', session_id: SESSION, house: LIVE, plan_ref: 'p.md', output_ref: 'o',
                                   derived: { needs_you: true, outcome_gate: true } });
  const KG = page([gate], { desk: true });
  KG.App.data.spaces.personal.flow = FLOW;
  const decide = KG.grouped(gate, KG.gateActions(gate).concat(KG.cardItems(gate))).filter((x) => x.group.key === 'decide')[0];
  check('c-644: the gate\'s primary stays Decide\'s button beside a flow move: ' + (decide ? decide.nodes.map((n) => n.getAttribute('data-key')).join() : ''),
        !!decide && decide.nodes[0].getAttribute('data-key') === 'approve-outcome' && decide.nodes.some((n) => n.getAttribute('data-key') === 'flow-sign'));
  check('c-644: a move that names no group is drawn under Flow', named('Flow').join() === 'flow-tidy');
  check('c-644: a house move names no group of his', groups.every((g) => g[0] !== 'Pull request'));
  const order = groups.map((g) => g[0]);
  check('c-644: the flow\'s groups sit where Flow did, in the flow\'s order: ' + order.join(),
        order.indexOf('Try it live') > order.indexOf('Links') && order.indexOf('Early to master') === order.indexOf('Try it live') + 1
        && order.indexOf('Flow') === order.indexOf('Early to master') + 1);
  const row = deck.wrap(K.groupRow(c, nodes, 'pane'), K);
  const live = deck.all(row, (n) => n.getAttribute && n.getAttribute('aria-label') === 'Try it live')[0];
  check('c-644: a flow group of two is a split button named for it', !!live && deck.labelOf(deck.buttons(live)[0]) === 'Merge to dev review');
})();

/* ---------- Logs and Stop only for the card's own live session ---------- */
(function () {
  const orphan = deck.card('c-7', { stage: 'building', session_id: SESSION,
                                    house: Object.assign({}, LIVE, { recorded: false, bg_id: 'bbbbbbbb' }) });
  const keys = keysOf(page([orphan], { desk: true }), orphan);
  check('an orphan listed by name draws no Logs or Stop', keys.indexOf('logs') < 0 && keys.indexOf('stop') < 0);
  const ended = deck.card('c-8', { stage: 'building', session_id: SESSION, house: null });
  const endedKeys = keysOf(page([ended], { desk: true }), ended);
  check('an ended session draws no Logs or Stop', endedKeys.indexOf('logs') < 0 && endedKeys.indexOf('stop') < 0);
})();

/* ---------- a landed action whose redraw fails is not "did not reach the server" ---------- */
(function () {
  const fetch = () => Promise.resolve({ status: 200, json: () => ({ ok: true, result: { id: 'c-9' } }) });
  const K = page([cases.inbox], { fetch: fetch });
  K.act({ verb: 'create', space: 'personal', title: 'x' }, function () { throw new Error("Failed to execute 'removeChild'"); })
    .then(function (result) {
      const t = K._doc.getElementById('toast');
      check('a landed Create does not say it did not reach the server', t.textContent.indexOf('did not reach the server') < 0);
      check('it says the page did not redraw', t.textContent.indexOf('did not redraw') >= 0);
      check('it is not an error toast', (t.className || '').indexOf('err') < 0);
      check('it hands back the result', !!result && result.id === 'c-9');
      finish();
    }, function (e) { fails.push('the act rejected: ' + e.message); finish(); });
})();

function finish() {
  process.stdout.write(JSON.stringify({ table: page([]).CONTROL_PHASES, drawn: drawn, fails: fails }));
}
