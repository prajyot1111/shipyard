/* The Bosun page (`app/ui.console.js`, c-519, c-591), rendered under node and read back.
 *
 * Usage: node console-page.js <path to app/>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 *
 * The page's own modules (the deck's core and the page) against the DOM stand-in, with a
 * state document built here: what the session panel offers when Bosun is up, stopped or
 * away, and what each of the four sections (Now, Queue, Shipped, Journal) draws.
 */
'use strict';
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

/* console.html's own list, in its order: the deck's core and the page (no Inspector, c-591) */
const MODULES = ['ui.core.js', 'ui.console.asks.js', 'ui.console.js'];
let replaced = null;
function page(cards, bosun, desk, search, path, extra) {
  replaced = null;
  globalThis.location = { pathname: path || '/console', search: search || '', hash: '',
                          replace(url) { replaced = url; } };
  const K = deck.load(APP, MODULES, { desk: !!desk });
  K.App.data = deck.state(cards, Object.assign({ console: bosun }, extra || {}));
  K.render();
  return K;
}
function body(K) { return K._doc.getElementById('body'); }
function dock(K) { return K._doc.getElementById('dock'); }
function rail(K) { return K._doc.getElementById('rail'); }
function buttonNamed(K, word) {
  return deck.all(body(K), (n) => n.tagName === 'BUTTON' && n.textContent.trim() === word)[0] || null;
}
function enabled(button) { return !!button && button.getAttribute('disabled') === null; }

const UP = { state: 'idle', up: true, session_id: 's1', app_link: 'https://claude.ai/code/session_x',
             attach: '/home/me/shipyard/bin/keel console attach',
             up_since: '2026-09-24T09:00:00+00:00', last_turn: '2026-09-24T09:50:00+00:00', model: 'claude-opus-5-5',
             context: { used: 410000, window: 1000000, percent: 41, compact_at: 70 }, history: [] };

[false, true].forEach(function (desk) {
  const where = desk ? 'desk' : 'phone';
  let K = page([], UP, desk);
  check(where + ': up offers Restart', enabled(buttonNamed(K, 'Restart')));
  check(where + ': up offers Stop', enabled(buttonNamed(K, 'Stop')));
  check(where + ': up has no Start', !buttonNamed(K, 'Start'));
  const link = deck.all(body(K), (n) => n.tagName === 'A' && n.getAttribute('href') === UP.app_link);
  check(where + ': up links the Claude app', link.length === 1);
  check(where + ': the meter says 41%', /41%/.test(body(K).textContent));
  check(where + ': the strip says the model', /opus-5\.5/.test(body(K).textContent));

  K = page([], Object.assign({}, UP, { state: 'stopped', up: false, app_link: null }), desk);
  check(where + ': stopped offers Start', enabled(buttonNamed(K, 'Start')));
  check(where + ': stopped cannot Stop', !enabled(buttonNamed(K, 'Stop')));
  check(where + ': stopped has no app link', deck.all(body(K), (n) => n.tagName === 'A' && /claude\.ai/.test(n.getAttribute('href') || '')).length === 0);

  /* a config with no Bosun session: the state carries the board's half alone, as `bosun` */
  K = page([], null, desk, '', '', { bosun: { counts: {}, asks: [], requests: [], journal: [] } });
  check(where + ': no session says away', /away/.test(body(K).textContent));
  check(where + ': no session offers Start, which the deck answers with why not', enabled(buttonNamed(K, 'Start')));
});

/* ---------- c-591: the four sections and what each draws ---------- */
function his(id, extra) {
  const e = extra || {};
  return deck.card(id, Object.assign({}, e, { derived: Object.assign({ bosun: true }, e.derived || {}) }));
}
const AT = '2026-09-24T09:40:00+00:00';
const plan = his('c-10', { stage: 'planning', plan_ref: '/x/plan.md', derived: { plan_gate: true, needs_you: true } });
const held = his('c-11', { stage: 'assigned', blocked_reason: 'Held: he wants to discuss the shape\nmore', derived: { needs_you: true } });
const doing = his('c-12', { stage: 'building', options: { bosun: { batch: 'b-2', branch: 'bosun/c-12-thing' } } });
const will = his('c-13', { stage: 'assigned' });
const landed = his('c-14', { stage: 'done' });
const other = deck.card('c-15', { space: 'personal', stage: 'assigned', options: { driver: 'bosun' } });
const CARDS = [plan, held, doing, will, landed, other];
const ASK = { id: 'a-3', kind: 'decision', state: 'open', card: 'c-12', question: 'Which name?', why: 'w', created_at: AT,
              options: [{ letter: 'A', label: 'short', does: 'renames it' }, { letter: 'B', label: 'long', does: 'keeps it' }] };
const DEPLOY = { id: 'a-4', kind: 'approval', state: 'open', card: null, question: 'Deploy next to main?', why: 'w', created_at: AT,
                 options: [{ letter: 'A', label: 'Deploy', does: 'Keel runs the suite', deploy: { sha: 'abcdef1234' } },
                           { letter: 'B', label: 'Not yet', does: 'nothing' }] };
const SHIPPED = {
  pending: { ask: 'a-4', target: 'next', trunk: 'main', sha: 'abcdef1234', cards: ['c-14', 'c-99'], at: AT, result: null },
  last: { ask: 'a-2', target: 'next', trunk: 'main', sha: '1234567890', cards: ['c-8'], at: AT,
          result: { move: 'deployed', text: 'main is at 12345678; the box restarts on it', at: AT, sha: '1234567890' } },
  live: [{ ask: 'a-2', target: 'next', trunk: 'main', sha: '1234567890', cards: ['c-8'], at: AT,
           result: { move: 'deployed', text: 't', at: AT, sha: '1234567890' } }] };
const FULL = Object.assign({}, UP, { asks: [ASK, DEPLOY], counts: { asks: 2, requests: 1 }, shipped: SHIPPED,
  requests: [{ id: 'r-5', n: 5, actor: 'house', card: 'c-12', what: 'a gap', detail: '', key: null, seen: 1, state: 'open', created_at: AT }] });
const hrefs = (K) => deck.all(body(K), (n) => n.tagName === 'A').map((n) => n.getAttribute('href') || '');

[false, true].forEach(function (desk) {
  const where = desk ? 'desk' : 'phone';
  let K = page(CARDS, FULL, desk);
  let text = body(K).textContent;
  check(where + ': now is the default', K.App.tab === 'now');
  /* c-634: the install's own command from the state, run here; no machine to ssh into */
  check(where + ': now: the attach command, with Copy', text.indexOf('/home/me/shipyard/bin/keel console attach') >= 0
    && !/ssh|keel-box|from the Mac/.test(text) && !!buttonNamed(K, 'Copy'));
  check(where + ': now: one machine names no host', !/ · on mac/.test(text));
  check(where + ': now: the batch in hand names its batch and branch', /batch b-2/.test(text) && /bosun\/c-12-thing/.test(text));
  check(where + ': now: his plan gate', deck.all(body(K), (n) => deck.hasClass(n, 'crow') && deck.hasClass(n, 'need')
    && n.getAttribute('data-key') === 'c-10').length === 1);
  check(where + ': now: the held discussion, its first line', /Held: he wants to discuss the shape/.test(text) && !/more$/.test(text));
  check(where + ': now: Bosun\'s ask with its options', /Which name\?/.test(text) && deck.byClass(body(K), 'copt').length === 2);
  check(where + ': now: the deploy ask is not here', !/Deploy next to main/.test(text));
  check(where + ': now: no board, no lanes, no driven cards, no strikes', !deck.byClass(body(K), 'clane').length
    && !/Driven cards|Strikes/.test(text) && !/c-15/.test(text));
  check(where + ': now: a card opens in the deck\'s Inspector', hrefs(K).indexOf('/?view=cards&card=c-10&space=personal') >= 0
    && !hrefs(K).some((h) => /^\/console\?.*card=/.test(h)));
  /* the counts: Now 3 (plan, held, ask), Queue 1 (open request), Shipped 2 (the deploy's cards) */
  const nav = desk ? rail(K) : dock(K);
  const navText = nav.textContent;
  check(where + ': four sections in the ' + (desk ? 'rail' : 'bar'), ['Now', 'Queue', 'Shipped', 'Journal'].every((w) => navText.indexOf(w) >= 0));
  const badges = deck.all(nav, (n) => deck.hasClass(n, desk ? 'badge' : 'dock-badge')).map((n) => n.textContent);
  check(where + ': the counts on the sections', badges.join() === '3,1,2');

  K.App.tab = 'queue'; K.render(); text = body(K).textContent;
  const group = (label) => deck.all(body(K), (n) => n.getAttribute && n.getAttribute('data-key') === 'q-' + label)[0];
  const ids = (g) => g ? deck.all(g, (n) => deck.hasClass(n, 'crow')).map((n) => n.getAttribute('data-key')).join() : '';
  check(where + ': queue: waiting on him', ids(group('Waiting on you')) === 'c-10,c-11');
  check(where + ': queue: doing, with batch and branch', ids(group('Doing')) === 'c-12' && /batch b-2 · bosun\/c-12-thing/.test(text));
  check(where + ': queue: will do', ids(group('Will do')) === 'c-13');
  check(where + ': queue: only Bosun\'s cards', !/c-15/.test(text));
  check(where + ': queue: intake is the open requests', /Intake/.test(text) && /a gap/.test(text) && !!buttonNamed(K, 'Copy for chat'));

  K.App.tab = 'shipped'; K.render(); text = body(K).textContent;
  check(where + ': shipped: the cards on next', /c-14 title/.test(text) && /c-99/.test(text));
  check(where + ': shipped: Deploy', enabled(buttonNamed(K, 'Deploy')));
  check(where + ': shipped: the last deploy', /deployed/.test(text) && /main is at 12345678/.test(text));
  check(where + ': shipped: recently live', /Recently live/.test(text) && /c-8/.test(text));
});

/* Deploy answers the open deploy ask with A, through the Console's own answer verb */
(function () {
  const posted = [];
  const K = page(CARDS, FULL, false, '', '/console/shipped');
  check('shipped: its route', K.App.tab === 'shipped');
  K.act = function (b) { posted.push(b); };
  const deploy = buttonNamed(K, 'Deploy');
  deploy.onclick({ currentTarget: deploy, stopPropagation() {} });
  check('shipped: Deploy answers the deploy ask with A', posted.length === 1 && posted[0].verb === 'console'
    && posted[0].sub === 'answer' && posted[0].target === 'a-4' && posted[0].choice === 'A');
})();

/* c-665: every branch the Shipped section names is the deploy ask's own (`target`, `trunk`),
   and with no deploy to read them from it names none */
(function () {
  const named = JSON.parse(JSON.stringify(SHIPPED));
  [named.pending, named.last, named.live[0]].forEach((d) => { d.target = 'staging'; d.trunk = 'release'; });
  named.last.result.text = 'live';
  const asked = [];
  let K = page(CARDS, Object.assign({}, FULL, { shipped: named }), false, '', '/console/shipped');
  K._win.confirm = (said) => { asked.push(said); return true; };
  let said = null;
  K.act = function (b, done) { said = done({ kick: 'kicked' }); };
  let text = body(K).textContent;
  check('c-665: shipped names the ask\'s own branches: ' + text.slice(0, 300), /On staging, not live/.test(text)
    && /release moves only on this Yes/.test(text) && /landed on staging/.test(text) && !/\b(next|main)\b/.test(text));
  const deploy = buttonNamed(K, 'Deploy');
  deploy.onclick({ currentTarget: deploy, stopPropagation() {} });
  check('c-665: Deploy asks and answers in the ask\'s own names: ' + asked[0] + ' / ' + said,
    /^Deploy staging at abcdef12 to release\?/.test(asked[0] || '') && /release moves only if the suite is green/.test(said || ''));
  K = page(CARDS, Object.assign({}, FULL, { shipped: { pending: null, last: null, live: [] } }), false, '', '/console/shipped');
  text = body(K).textContent;
  check('c-665: with no deploy to read a name from, none is guessed: ' + text.slice(0, 300),
    /Nothing waiting/.test(text) && !/\b(next|main)\b/.test(text));
  const bare = { ask: 'a-4', sha: 'abcdef1234', cards: [], at: AT, result: null };
  K = page(CARDS, Object.assign({}, FULL, { shipped: { pending: bare, last: null, live: [] } }), false, '', '/console/shipped');
  K._win.confirm = (words) => { asked.push(words); return false; };
  const again = buttonNamed(K, 'Deploy');
  again.onclick({ currentTarget: again, stopPropagation() {} });
  check('c-665: an ask that names no branch is asked without one: ' + asked[1],
    !/\b(next|main)\b/.test(asked[1] || 'main') && !/\b(next|main)\b/.test(body(K).textContent));
})();

/* c-591 review: a held card Bosun asks about shows once in Needs you, as the ask */
(function () {
  const asked = Object.assign({}, ASK, { id: 'a-6', card: 'c-11', question: 'Discuss the shape?' });
  const K = page(CARDS, Object.assign({}, FULL, { asks: [asked] }), false);
  check('now: a held card with an open ask is not also a held row',
    deck.all(body(K), (n) => deck.hasClass(n, 'crow') && n.getAttribute('data-key') === 'c-11').length === 0
    && /Discuss the shape\?/.test(body(K).textContent));
  check('now: its count is the ask, once', deck.all(dock(K), (n) => deck.hasClass(n, 'dock-badge'))[0].textContent === '2');
})();

/* c-591 review: no console session (c-593 removes the console space), and the page still
   draws Shipped and the asks from the state's board half, `bosun` */
(function () {
  const K = page(CARDS, null, false, '', '/console/shipped', { bosun: { asks: [ASK, DEPLOY], counts: { asks: 2, requests: 1 },
    shipped: SHIPPED, requests: [], journal: [] } });
  check('no console: shipped still draws', /c-14 title/.test(body(K).textContent) && enabled(buttonNamed(K, 'Deploy')));
  K.App.tab = 'now'; K.render();
  check('no console: the asks still draw', /Which name\?/.test(body(K).textContent));
})();

/* c-591 review: Cmd/Ctrl-K opens the new-card modal on the deck; this page has none */
(function () {
  const K = page([], UP, true);
  let threw = null;
  try {
    (K._doc._on.keydown || []).forEach((fn) => fn({ metaKey: true, key: 'k', preventDefault() {} }));
  } catch (error) { threw = error; }
  check('ctrl-k on the Bosun page does not throw', threw === null && (K._doc._on.keydown || []).length > 0);
})();

/* Nothing waiting says so, and no count */
(function () {
  const K = page([], Object.assign({}, UP, { asks: [], counts: {}, shipped: { pending: null, last: null, live: [] } }), false);
  check('now: nothing needs you says so', /Nothing needs you/.test(body(K).textContent));
  check('now: nothing in hand says so', /Nothing in hand/.test(body(K).textContent));
  check('no counts when nothing waits', deck.byClass(dock(K), 'dock-badge').length === 0);
  K.App.tab = 'shipped'; K.render();
  check('shipped: nothing waiting, no Deploy', !buttonNamed(K, 'Deploy') && /Nothing waiting/.test(body(K).textContent));
})();
(function () {
  const open = { id: 'r-2', n: 2, actor: 'drain', card: null, what: 'rotate upkeep failed', detail: '',
                 key: 'drain:step:rotate-upkeep', seen: 4, state: 'open', created_at: '2026-09-24T09:40:00+00:00' };
  const taken = { id: 'r-1', n: 1, actor: 'house', card: 'c-9', what: 'kb stage refuses a repo', detail: 'the trace',
                  key: null, seen: 1, state: 'taken', taken_by: 'bosun', created_at: '2026-09-24T09:30:00+00:00' };
  const journal = [
    { id: 3, card: 'r-1', at: '2026-09-24T09:45:00+00:00', actor: 'bosun', text: 'fixed: listed the repo', move: 'resolved', gap: 'unlisted-repo', how: 'fixed' },
    { id: 2, card: 'r-1', at: '2026-09-24T09:35:00+00:00', actor: 'bosun', text: 'taken by Bosun', move: 'taken', gap: null, how: null }];
  const history = [{ at: '2026-09-24T09:40:00+00:00', what: 'started', by: 'human', session: 's1' }];
  [false, true].forEach(function (desk) {
    const where = desk ? 'desk' : 'phone';
    const K = page([], Object.assign({}, UP, { requests: [open, taken], journal: journal, history: history,
                                                counts: { requests: 1 } }), desk);
    K.App.tab = 'queue';
    K.render();
    const rows = deck.all(body(K), (n) => deck.hasClass(n, 'creq'));
    check(where + ': requests: both rows', rows.map((n) => n.getAttribute('data-key')).join() === 'r-2,r-1');
    check(where + ': requests: an open one offers Copy for chat', !!buttonNamed(K, 'Copy for chat')
      && deck.all(body(K), (n) => n.tagName === 'BUTTON' && n.textContent.trim() === 'Copy for chat').length === 1);
    check(where + ': requests: a repeat says how often', /seen 4 times/.test(body(K).textContent));
    check(where + ': requests: a taken one says so', rows.length === 2 && deck.hasClass(rows[1], 'taken')
      && /Taken by Bosun/.test(rows[1].textContent));
    check(where + ': requests: the tab counts the open one', /1 open, 1 taken/.test(body(K).textContent));
    K.App.tab = 'journal';
    K.render();
    const lines = deck.all(body(K), (n) => deck.hasClass(n, 'cjournal')).map((n) => n.textContent);
    check(where + ': journal: newest first, taps and requests merged', lines.length === 3
      && /r-1 resolved/.test(lines[0]) && /started/.test(lines[1]) && /r-1 taken/.test(lines[2]));
    check(where + ': journal: the ending wears its gap tag', deck.all(body(K), (n) => deck.hasClass(n, 'cgap')
      && n.textContent === 'unlisted-repo').length === 1);
  });
  const K = page([], Object.assign({}, UP, { requests: [], journal: [], counts: {} }), true);
  K.App.tab = 'queue';
  K.render();
  check('requests: none says so', /No open requests/.test(body(K).textContent));
})();

/* The Journal's head (c-524): done by space (personal and work), then the gaps. */
[false, true].forEach(function (desk) {
  const where = desk ? 'desk' : 'phone';
  const gaps = [
    { gap: 'unlisted-repo', count: 3, recurring: true, hows: { fixed: 2, filed: 1 },
      last: '2026-09-25T10:00:00+00:00', requests: ['r-1', 'r-2', 'r-3'] },
    { gap: 'house-resources', count: 1, recurring: false, hows: { declined: 1 },
      last: '2026-09-24T10:00:00+00:00', requests: ['r-7'] }];
  const through = { days: 7, done: { personal: 6, console: 1, work: 3 }, console_in_flight: 3,
    console_waiting: 2, console_max: 3 };
  const compacted = Object.assign({}, UP, { history: [{ at: '2026-09-24T09:40:00+00:00',
    what: 'compacted (auto) at 71%, handoff written', by: 'harness', session: 's1' }] });
  let K = page([], Object.assign({}, compacted, { requests: [], journal: [], counts: {}, throughput: through, gaps: gaps }), desk);
  K.App.tab = 'journal';
  K.render();
  const tiles = deck.all(body(K), (n) => deck.hasClass(n, 'stat'));
  check(where + ': journal: two tiles, personal and work, no console space', tiles.length === 2
    && /^6Personal/.test(tiles[0].textContent) && /^3Work/.test(tiles[1].textContent)
    && !/in flight/.test(body(K).textContent));
  const rows = deck.all(body(K), (n) => deck.hasClass(n, 'cgaprow'));
  check(where + ': journal: one row per gap', rows.length === 2);
  check(where + ': journal: a gap on three requests is recurring, with how it ended', /recurring/.test(rows[0].textContent)
    && /3 requests/.test(rows[0].textContent) && /2 fixed, 1 filed/.test(rows[0].textContent));
  check(where + ': journal: a gap seen once is folded away', /Seen once \(1\)/.test(body(K).textContent)
    && !/recurring/.test(rows[1].textContent));
  check(where + ': journal: the compaction is a session row', deck.all(body(K), (n) => deck.hasClass(n, 'cjournal')
    && /compacted \(auto\) at 71%, handoff written/.test(n.textContent) && /by harness/.test(n.textContent)).length === 1);
  K = page([], Object.assign({}, UP, { requests: [], journal: [], counts: {}, throughput: through, gaps: [] }), desk);
  K.App.tab = 'journal';
  K.render();
  check(where + ': journal: no gaps, no gaps panel', !/Recurring gaps/.test(body(K).textContent));
});
/* ---------- c-591: each section is a route, and the old links still land ---------- */
(function () {
  let K = page([], UP, false, '', '/console/queue');
  check('route: /console/queue is Queue', K.App.tab === 'queue');
  K = page([], UP, false, '', '/console/journal');
  check('route: /console/journal is Journal', K.App.tab === 'journal');
  K = page([], UP, false, '?tab=requests');
  check('route: the old Requests tab lands on Queue', K.App.tab === 'queue');
  K = page([], UP, false, '?tab=board');
  check('route: the old Board tab lands on Queue', K.App.tab === 'queue');
  K = page([], UP, false, '?tab=needs');
  check('route: the old Needs you tab lands on Now', K.App.tab === 'now');
  K = page([], UP, false);
  const bar = deck.all(dock(K), (n) => deck.hasClass(n, 'dock-item'));
  bar[2].onclick({});
  check('route: a tap on Shipped pushes /console/shipped', K.App.tab === 'shipped' && K._pushed === 1
    && K._win.location.pathname === '/console/shipped');
  page([], UP, false, '?tab=board&card=c-2');
  check('route: an old card link goes to the deck\'s Inspector', replaced === '/?view=cards&card=c-2');
})();
process.stdout.write(JSON.stringify(fails.length ? { ok: false, failed: fails } : { ok: true }));
