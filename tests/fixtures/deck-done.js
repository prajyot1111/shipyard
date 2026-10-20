/* Live cards first, done cards behind the draw (c-549), run under node and read back.
 *
 * Usage: node deck-done.js <path to app/>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 *
 * The first load asks for the live part alone and draws; the done part is asked for after
 * the draw and merged in, the live copy winning on an id in both. Every later load asks for
 * both and draws once, so a card moving to done is never missing from a draw. A door that
 * answers the whole scope is asked nothing more. The views that show done cards say they are
 * loading them until they land.
 */
'use strict';
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const MODULES = ['ui.core.js', 'ui.findcore.js', 'ui.findpages.js', 'ui.find.js', 'ui.tips.js', 'ui.modal.js',
                 'ui.cards.js', 'ui.tree.js', 'ui.views.js'];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }
const settle = () => new Promise((r) => setImmediate(r));

function answer(status, body, tag) {
  return { status, ok: status >= 200 && status < 300,
           headers: { get: (name) => (name === 'ETag' ? tag || '"t"' : null) },
           json: () => Promise.resolve(body) };
}
const DONE = { stage: 'done' };
function live(cards) {
  return deck.state(cards, { scope: { name: 'deck', archived: false, card: null, part: 'live' } });
}
function done(cards) {
  return { now: '2026-09-27T10:00:00+00:00', cards, scope: { name: 'deck', archived: false, card: null, part: 'done' } };
}
/* A door whose two parts are whatever `board` holds now, split by stage; `tags` lets a test
   answer a part with a 304. */
function door(board) {
  const asked = [], tags = { live: '"l0"', done: '"d0"' };
  const fetch = (url, opts) => {
    asked.push(url);
    const part = /part=done/.test(url) ? 'done' : 'live';
    const sent = opts && opts.headers && opts.headers['If-None-Match'];
    if (sent && sent === tags[part]) return Promise.resolve(answer(304, null, tags[part]));
    const cards = board.cards.filter((c) => (c.stage === 'done') === (part === 'done'));
    return Promise.resolve(answer(200, part === 'done' ? done(cards) : live(cards), tags[part]));
  };
  return { asked, fetch, tags, states: () => asked.filter((u) => u.indexOf('/api/state') === 0) };
}
function page(srv, desk) {
  const K = deck.load(APP, MODULES, { fetch: srv.fetch, desk: !!desk });
  K.App.space = 'personal';
  K.draws = [];
  K.render = K.renderBody = function () { K.draws.push(K.App.data.cards.map((c) => c.id).sort().join(',')); };
  /* the fixture's timers never fire, so the page's "after the paint" is a microtask here */
  const later = [];
  K.afterDraw = (fn) => { later.push(fn); };
  K.paint = () => Promise.all(later.splice(0).map((fn) => fn()));
  /* and the done part's retry is a queue the test runs by hand */
  const retries = [];
  K.later = (fn) => { retries.push(fn); };
  K.retry = () => Promise.all(retries.splice(0).map((fn) => fn()));
  K.retries = () => retries.length;
  return K;
}
function key(node, k) {
  return deck.all(node, (n) => n.getAttribute && n.getAttribute('data-key') === k);
}

async function main() {
  /* ---------- the first load draws live, then merges done behind it ---------- */
  {
    const board = { cards: [deck.card('c-1'), deck.card('c-2', DONE), deck.card('c-3', DONE)] };
    const srv = door(board);
    const K = page(srv);
    await K.load();
    check('first: only the live part is asked before the draw',
          JSON.stringify(srv.states()) === '["/api/state?scope=deck&part=live"]');
    check('first: it drew the live cards', K.draws.length === 1 && K.draws[0] === 'c-1');
    check('first: done cards are not held yet', K.doneHeld() === false);
    await K.paint(); await settle();
    check('first: the done part is asked after the draw', srv.states()[1] === '/api/state?scope=deck&part=done');
    check('first: and merged in', K.draws.length === 2 && K.draws[1] === 'c-1,c-2,c-3');
    check('first: now they are held', K.doneHeld() === true && K.App.data.scope.done === true);
    check('first: the live part as it came is kept apart', K.App.live.cards.length === 1);

    /* ---------- a later load asks for both and draws once ---------- */
    board.cards[0] = deck.card('c-1', DONE);        // c-1 reaches done
    srv.tags.live = '"l1"'; srv.tags.done = '"d1"';
    await K.load();
    const last = srv.states().slice(-2).sort();
    check('refresh: both parts asked together',
          JSON.stringify(last) === '["/api/state?scope=deck&part=done","/api/state?scope=deck&part=live"]');
    check('refresh: one draw, and the card that moved to done is in it',
          K.draws.length === 3 && K.draws[2] === 'c-1,c-2,c-3');

    /* ---------- a live change with no done change: the done part is a 304 and kept ---------- */
    board.cards.push(deck.card('c-4'));
    srv.tags.live = '"l2"';
    await K.load();
    check('304: the done cards are kept', K.draws.length === 4 && K.draws[3] === 'c-1,c-2,c-3,c-4');
    await K.load();
    check('304: nothing moved, nothing drawn', K.draws.length === 4);
  }

  /* ---------- the live copy wins on an id in both ---------- */
  {
    const srv = { asked: [] };
    srv.fetch = (url) => {
      srv.asked.push(url);
      return Promise.resolve(/part=done/.test(url)
        ? answer(200, done([deck.card('c-5', { stage: 'done', title: 'old' })]), '"d"')
        : answer(200, live([deck.card('c-5', { title: 'new' })]), '"l"'));
    };
    const K = page(srv);
    await K.load(); await K.paint(); await settle();
    check('merge: one copy of a card in both parts', K.App.data.cards.length === 1);
    check('merge: and it is the live one', K.byId('c-5').title === 'new');
  }

  /* ---------- a door that answers the whole scope is asked nothing more ---------- */
  {
    const srv = { asked: [], fetch: (url) => { srv.asked.push(url); return Promise.resolve(answer(200,
      deck.state([deck.card('c-1'), deck.card('c-2', DONE)], { scope: { name: 'deck', archived: false, card: null } }))); } };
    const K = page(srv);
    await K.load(); await K.paint(); await settle();
    await K.load();
    check('old door: no done part is ever asked', srv.asked.every((u) => !/part=done/.test(u)));
    check('old door: its done cards count as held', K.doneHeld() === true);
  }

  /* ---------- a done card opened by link waits for the done part ---------- */
  {
    const board = { cards: [deck.card('c-1'), deck.card('c-2', DONE)] };
    const srv = door(board);
    const K = page(srv);
    K.App.card = 'c-2';
    await K.load();
    K.followScope(); await settle();
    check('open done card: no card= while the done part is on its way', srv.states().length === 1);
    await K.paint(); await settle();
    K.followScope(); await settle();
    check('open done card: held once it lands, nothing more asked',
          !!K.byId('c-2') && srv.states().every((u) => u.indexOf('card=') < 0));
  }

  /* ---------- a done part that fails or answers an error is asked for again ---------- */
  for (const how of ['rejects', 'answers 500']) {
    let broken = true;
    const board = { cards: [deck.card('c-1'), deck.card('c-2', DONE)] };
    const good = door(board);
    const srv = { fetch: (url, opts) => {
      if (broken && /part=done/.test(url)) {
        return how === 'rejects' ? Promise.reject(new Error('gone')) : Promise.resolve(answer(500, { ok: false, error: 'boom' }));
      }
      return good.fetch(url, opts);
    } };
    const K = page(srv);
    await K.load(); await K.paint(); await settle();
    check(how + ': not taken as a done part', K.doneHeld() === false && !K.byId('c-2'));
    check(how + ': a retry is waiting', K.retries() === 1);
    /* a refresh meanwhile still takes the live part, and does not stack a second retry */
    board.cards.push(deck.card('c-3')); good.tags.live = '"l9"';
    await K.load(); await settle();
    check(how + ': the live part is not held back', !!K.byId('c-3'));
    check(how + ': one retry, not two', K.retries() === 1);
    broken = false;
    await K.retry(); await settle();
    check(how + ': the retry lands it', K.doneHeld() === true && !!K.byId('c-2'));
    check(how + ': and nothing more is waiting', K.retries() === 0);
  }

  /* ---------- a live error body is never the page's state ---------- */
  {
    const board = { cards: [deck.card('c-1'), deck.card('c-2', DONE)] };
    const good = door(board);
    let broken = false;
    const K = page({ fetch: (url, opts) => broken && /part=live/.test(url)
      ? Promise.resolve(answer(503, { ok: false, error: 'down' })) : good.fetch(url, opts) });
    await K.load(); await K.paint(); await settle();
    broken = true; good.tags.live = '"l7"';
    await K.load(); await settle();
    check('live 503: the page keeps what it had', !!K.byId('c-1') && K.App.live.cards.length === 1);
  }

  /* ---------- the tree names a done card as loading, not elsewhere ---------- */
  {
    const tree = { steps: [{ step: 1, cards: [{ id: 'c-7', title: 'a slice', stage: 'done', after: ['c-8'], waiting_for: [],
                                                 next: false, unblocks: '', blocked: false }] }],
                   follow_ups: ['c-9'], unassigned: 0 };
    const big = deck.card('c-6', { stage: 'building', derived: { tree: tree, tracking: true } });
    const slice = deck.card('c-7', { parent: 'c-6', stage: 'building' });
    const K = page({ fetch: () => Promise.resolve(answer(200, {})) }, true);
    K.render = K.renderBody = function () {};
    K.App.data = live([big, slice]);
    let text = deck.wrap(K.treeSection(big), K).textContent;
    check('tree: a done follow-up says loading', /loading/.test(text) && !/not in this space/.test(text));
    K.App.data = live([big, slice, deck.card('c-9', { stage: 'done', title: 'the follow-up' })]);
    K.App.data.scope = Object.assign({}, K.App.data.scope, { done: true });
    text = deck.wrap(K.treeSection(big), K).textContent;
    check('tree: and its title once it lands', /the follow-up/.test(text));
  }

  /* ---------- the views say they are loading, never an empty lane or a wrong count ---------- */
  {
    const K = page({ fetch: () => Promise.resolve(answer(200, {})) }, true);
    K.render = K.renderBody = function () {};
    K.App.data = live([deck.card('c-1')]);
    K.App.view = 'now';
    K.go('cards');
    K.find.open('cards', 'filter');
    let body = deck.wrap(K.viewCards(), K);
    const sw = key(body, 'i-done').filter((n) => deck.hasClass(n, 'find-row'))[0];
    check('switch: Include done shows no count while done cards load',
          !!sw && deck.byClass(sw, 'find-cnt').length === 0);
    K.App.find.cards.inc = ['done'];
    body = deck.wrap(K.viewCards(), K);
    check('list: Include done on says it is loading them', key(body, 'loading-done').length === 1);
    K.App.find.cards.mode = { layout: 'kanban' };
    body = deck.wrap(K.viewCards(), K);
    const lane = key(body, 'done').filter((n) => deck.hasClass(n, 'lane'))[0];
    check('kanban: the Done lane says loading, not empty',
          !!lane && key(lane, 'loading-done').length === 1 && /loading/.test(lane.textContent));
    K.App.data.scope = Object.assign({}, K.App.data.scope, { done: true });
    body = deck.wrap(K.viewCards(), K);
    check('kanban: and draws its cards once they are held', key(body, 'loading-done').length === 0);
    const sw2 = key(body, 'i-done').filter((n) => deck.hasClass(n, 'find-row'))[0];
    check('switch: and the count comes back', !!sw2 && deck.byClass(sw2, 'find-cnt').length === 1);
  }

  process.stdout.write(JSON.stringify(fails.length ? { ok: false, fails } : { ok: true }) + '\n');
}

main().catch((e) => { process.stdout.write(JSON.stringify({ ok: false, fails: ['threw: ' + e.stack] }) + '\n'); });
