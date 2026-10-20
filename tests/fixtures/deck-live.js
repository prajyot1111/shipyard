/* The live strip (c-599), run under node and read back.
 *
 * Usage: node deck-live.js <path to app/>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 *
 * Each block draws a card the way the page would, with the facts a house's machine would
 * send (keel/livestrip.py), and reads what the strip, the house word and the Now tile say:
 * a card working, one waiting on a prompt, one idle, one exited, a Mac card known only from
 * the stream, and a `live` line patching a card without a fetch.
 */
'use strict';
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const MODULES = ['ui.core.js', 'ui.live.js', 'ui.idle.js', 'ui.findcore.js', 'ui.findpages.js', 'ui.find.js', 'ui.tips.js',
                 'ui.modal.js', 'ui.cards.js', 'ui.tree.js', 'ui.reviews.js', 'ui.views.js'];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

/* The reading machine's clock: the facts were read at T, and every other time is that
   machine's too, so what the page says is T minus the fact, whatever the phone's clock is. */
const T = Date.parse('2026-09-30T10:00:00Z');
function iso(secondsBefore) { return new Date(T - secondsBefore * 1000).toISOString(); }
function facts(extra) {
  return Object.assign({
    at: iso(0), host: 'mac', status: 'working',
    house: { bg_id: 'abcd1234', status: 'busy', state: 'working', working: true, started_at: T - 3600000 },
    detail: 'running the unit tests for the parser', detail_at: iso(5), agents: [], jobs: [],
    tool: { name: 'Bash', what: 'run the unit tests', at: iso(12), done: false },
    todos: { done: 2, total: 4, active: 'Writing tests' },
    turn_at: iso(240), turn_ended_at: null, wrote_at: iso(3)
  }, extra || {});
}
const BUILDING = { stage: 'building', session_id: 'abcd1234-0000-4000-8000-000000000001', autonomy: 'autonomous' };
function page(cards) {
  let fetched = 0;
  const K = deck.load(APP, MODULES, { fetch: () => { fetched++; return Promise.resolve({ json: () => ({}) }); } });
  K.App.data = deck.state(cards, { houses: cards.map((c) => c.id) });
  K.App.space = 'personal';
  K.App.stripGot = Date.now();
  K.render = K.renderBody = function () {};
  K.fetched = () => fetched;
  return K;
}
function strip(K, c) { const node = K.liveStrip(c); return node ? deck.wrap(node, K).textContent : ''; }
function said(K, c) {
  const node = K.liveStrip(c);
  const found = node ? deck.byClass(deck.wrap(node, K), 'lv-said') : [];
  return found.length ? found[0].textContent : '';
}

/* ---------- working ---------- */
(function () {
  const c = deck.card('c-1', Object.assign({ live: facts(), house: facts().house }, BUILDING));
  const K = page([c]);
  const text = strip(K, c);
  check('working: the house word says working', K.houseWord(c).text === 'working');
  check('working: the strip says working', text.indexOf('working') === 0);
  check('working: how long its turn has run', text.indexOf('in turn 4m') >= 0);
  check('working: its last tool, running, with its age', text.indexOf('Bash: run the unit tests · running 12s') >= 0);
  check('working: todo progress and the task in hand', text.indexOf('todos 2/4: Writing tests') >= 0);
  check('working: which machine and how old the read is', text.indexOf('mac · read 0s ago') >= 0);
  check('working: the harness says what it is doing', said(K, c) === 'running the unit tests for the parser');
  check('working: no verdict anywhere', !/stuck|hung|wedged/.test(text));
  const tile = deck.wrap(K.viewNow(), K).textContent;
  check('working: the Now tile carries the strip', tile.indexOf('Bash: run the unit tests') >= 0);
  check('working: under the house word the strip does not say working again',
        deck.wrap(K.liveStrip(c, true), K).textContent.indexOf('working') !== 0);
  const pane = deck.wrap(K.detailPane(c), K).textContent;
  check('working: the card pane carries it too', pane.indexOf('todos 2/4') >= 0);
})();

/* ---------- a finished tool, jobs and subagents ---------- */
(function () {
  const f = facts({ tool: { name: 'Edit', what: 'keel/livetail.py', at: iso(30), done: true },
                    jobs: [{ id: 'j', label: 'npm test', started_at: 1 }],
                    agents: [{ label: 'review', started_at: 1 }, { label: 'probe', started_at: 1 }] });
  const c = deck.card('c-2', Object.assign({ live: f, house: f.house }, BUILDING));
  const text = strip(page([c]), c);
  check('done tool: says how long ago it finished', text.indexOf('Edit: keel/livetail.py · 30s ago') >= 0);
  check('done tool: subagents and jobs are counted', text.indexOf('2 subagents, 1 job') >= 0);
})();

/* ---------- waiting on a prompt: the board's Notification, shown at once ---------- */
(function () {
  const notice = { type: 'permission_prompt', message: 'Claude needs your permission to use Bash', at: iso(20) };
  const f = facts({ wrote_at: iso(21) });
  const c = deck.card('c-3', Object.assign({ live: f, house: f.house, notice }, BUILDING));
  const K = page([c]);
  check('prompt: the house word says waiting on a prompt', K.houseWord(c).text === 'waiting on a prompt');
  check('prompt: the strip leads with it', strip(K, c).indexOf('waiting on a prompt') === 0);
  check('prompt: the question itself is the second line', said(K, c) === 'Claude needs your permission to use Bash');
  /* the house wrote after it: the prompt was answered, and it is working again */
  const later = deck.card('c-4', Object.assign({ live: facts({ wrote_at: iso(2) }), house: f.house, notice }, BUILDING));
  check('prompt: answered once the transcript moved past it', K.houseWord(later).text === 'working');
  /* the idle prompt is not a question for him */
  const idle = deck.card('c-5', Object.assign({ live: f, house: f.house, notice: Object.assign({}, notice, { type: 'idle_prompt' }) }, BUILDING));
  check('prompt: the idle prompt is not a prompt', K.houseWord(idle).text === 'working');
  /* with no live facts at all the notice is still the newest thing known */
  const bare = deck.card('c-6', Object.assign({ notice }, BUILDING));
  check('prompt: shown with no strip at all', K.houseWord(bare).text === 'waiting on a prompt');
})();

/* ---------- idle: its turn over, what it last said ---------- */
(function () {
  const f = facts({ status: 'idle', turn_ended_at: iso(90), detail: 'responded to the plan',
                    tool: { name: 'Bash', what: 'kb stage review', at: iso(95), done: true },
                    house: { bg_id: 'abcd1234', status: 'idle', state: 'done', working: false } });
  const c = deck.card('c-7', Object.assign({ live: f, house: f.house, last_said: 'Staged for review.\nmore' }, BUILDING));
  const K = page([c]);
  const text = strip(K, c);
  check('idle: the house word says idle', K.houseWord(c).text === 'idle');
  check('idle: the strip says idle', text.indexOf('idle') === 0);
  check('idle: how long since its turn ended (c-607: "idle 2m")', text.indexOf('idle 2m') === 0);
  check('idle: what Stop last said', said(K, c) === 'last said: Staged for review.');
})();

/* ---------- exited ---------- */
(function () {
  const f = facts({ status: 'exited', house: null, turn_ended_at: iso(600) });
  const c = deck.card('c-8', Object.assign({ live: f }, BUILDING));
  check('exited: the strip says so', strip(page([c]), c).indexOf('exited') === 0);
  /* c-606: a session that exited mid-turn left no turn end, and its tile read "exited in turn 6m" */
  const cut = facts({ status: 'exited', house: null, tool: null, todos: null, turn_at: iso(360), turn_ended_at: null });
  const b = deck.card('c-8', Object.assign({ live: cut, blocked_reason: 'session exited' }, BUILDING));
  const K = page([b]);
  const now = deck.wrap(K.viewNow(), K).textContent;
  check('c-606: the exited tile is drawn, with its reason', now.indexOf('exited') >= 0 && now.indexOf('why: session exited') >= 0);
  check('c-606: an exited house is in no turn', !/in turn/.test(now));
})();

/* ---------- c-606: a blocked tile says why, its last words and blocked, each once ---------- */
(function () {
  const count = (text, word) => text.split(word).length - 1;
  const lines = (K) => deck.byClass(deck.wrap(K.viewNow(), K), 'house-log').map((n) => n.textContent);
  const base = { blocked_reason: 'waiting on his answer', last_said: 'I ran the tests and they pass',
                 updated_at: iso(60) };
  /* no strip: two labelled lines, never one sentence */
  const a = deck.card('c-11', Object.assign({}, BUILDING, base));
  a.derived.gate_since = '2020-01-01T00:00:00Z'; a.updated_at = '2021-01-01T00:00:00Z';  // the fixture's clock is its own: two far dates differ on any
  let K = page([a]);
  let text = deck.wrap(K.viewNow(), K).textContent;
  check('c-606: why and last said are two lines',
        lines(K).indexOf('why: waiting on his answer') >= 0 && lines(K).indexOf('last said: I ran the tests and they pass') >= 0);
  check('c-606: blocked once', count(text, 'blocked') === 1);
  const age = deck.byClass(deck.wrap(K.viewNow(), K), 'age')[0].textContent;
  check('c-606: the head dates the block, not the last note',
        age === K.ago(a.derived.gate_since) && age !== K.ago(a.updated_at));
  /* a strip busy with a working detail does not carry the last words, so the tile does */
  const b = deck.card('c-12', Object.assign({ live: facts() }, BUILDING, base));
  K = page([b]);
  text = deck.wrap(K.viewNow(), K).textContent;
  check('c-606: last words kept beside a working strip', count(text, 'last said: I ran the tests') === 1);
  /* an idle strip already says them: once */
  const c = deck.card('c-13', Object.assign({ live: facts({ status: 'idle', detail: null, turn_ended_at: iso(30) }) }, BUILDING, base));
  K = page([c]);
  text = deck.wrap(K.viewNow(), K).textContent;
  check('c-606: last words once beside a strip that says them', count(text, 'last said: I ran the tests') === 1);
  /* a relay in flight takes the house word: the head says blocked */
  const d = deck.card('c-14', Object.assign({}, BUILDING, base));
  d.derived.relays = [{ what: 'resume', to: 'mac', at: iso(5) }];
  K = page([d]);
  text = deck.wrap(K.viewNow(), K).textContent;
  check('c-606: blocked once with a relay in flight', count(text, 'blocked') === 1);
})();

/* ---------- a Mac card known from the stream, patched without a fetch ---------- */
(function () {
  const c = deck.card('c-9', Object.assign({}, BUILDING));
  const K = page([c]);
  check('stream: nothing before the line', K.liveStrip(c) === null && K.houseWord(c) === null);
  K.heardLive('live c-9 ' + JSON.stringify(facts()));
  check('stream: the house word reads the streamed row', K.houseWord(c) && K.houseWord(c).text === 'working');
  check('stream: the strip is drawn from it', strip(K, c).indexOf('Bash: run the unit tests') >= 0);
  check('stream: nothing was fetched', K.fetched() === 0);
  K.heardLive('live c-9 null');
  check('stream: a gone card has no strip', K.liveStrip(c) === null && K.houseWord(c) === null);
  K.heardLive('live c-9 {not json');
  check('stream: a broken line changes nothing', K.liveStrip(c) === null);
})();

/* ---------- the newer read wins, whichever way it came ---------- */
(function () {
  const c = deck.card('c-10', Object.assign({ live: facts({ at: iso(0), status: 'idle' }) }, BUILDING));
  const K = page([c]);
  K.App.strip['c-10'] = { facts: facts({ at: iso(10), status: 'working' }), got: K.App.stripGot - 5000 };
  check('newer: an older streamed read loses to the document', K.liveOf(c).facts.status === 'idle');
  K.heardLive('live c-10 ' + JSON.stringify(facts({ at: new Date(T + 3000).toISOString(), status: 'working' })));
  check('newer: a newer streamed read wins', K.liveOf(c).facts.status === 'working');
})();

/* ---------- a tap in flight rides the strip ---------- */
(function () {
  const c = deck.card('c-11', Object.assign({ live: facts() }, BUILDING,
    { derived: { relays: [{ what: 'resume', to: 'mac', at: '2026-09-24T09:59:40+00:00' }] } }));
  check('tap: the relay is on the strip', strip(page([c]), c).indexOf('resume asked of mac') >= 0);
})();

/* ---------- c-599 review: a reading gone stale ---------- */
(function () {
  const old = facts({ at: iso(0) });
  const stale = deck.card('c-13', Object.assign({ live: old }, BUILDING));
  const K2 = page([stale]);
  K2.App.stripGot = Date.now() - 300000;      /* this page has held it five minutes */
  const text = strip(K2, stale);
  check('review: a stale reading is said as the past', text.indexOf('was working') === 0);
  check('review: with its honest age', text.indexOf('read 5m ago') >= 0);
})();

/* ---------- c-605: the ages tick between readings ---------- */
(function () {
  const c = deck.card('c-7', Object.assign({ live: facts({ status: 'idle', turn_ended_at: iso(0), tool: null,
    house: { bg_id: 'abcd1234', status: 'idle', state: 'idle', working: false } }) }, BUILDING));
  const K = page([c]);
  const node = K.liveStrip(c);
  check('c-605: drawn at the reading, the turn ended 0s ago', node.textContent.indexOf('idle 0s') >= 0);
  K.App.stripGot -= 16000;                       /* the page has held that reading 16 s */
  if (K.tickLive) K.tickLive([node]);
  check('c-605: a second tick later the same node says 16s, with no new reading',
        node.textContent.indexOf('idle 16s') >= 0 && node.textContent.indexOf('read 16s ago') >= 0);
})();

/* ---------- c-605: a merged card's pane keeps Stop when the strip lets it go ---------- */
(function () {
  const house = { bg_id: 'abcd1234', status: 'idle', kind: 'background', session_id: BUILDING.session_id,
                  recorded: true, working: false };
  const c = deck.card('c-8', Object.assign({}, BUILDING, { stage: 'done', house: house, lingering: true, output_ref: 'o' }));
  const K = page([c]);
  K.heardLive('live c-8 null');                  /* the strip dropped it the moment it was done */
  const keys = deck.wrap(K.gateActions(c).concat(K.cardItems(c)), K).childNodes
    .map((n) => n.getAttribute && n.getAttribute('data-key')).filter(Boolean);
  check('c-605: done, the strip silent: the house row stands', K.houseOf(c) === house);
  check('c-605: done, the strip silent: Stop session is there at once', keys.indexOf('stop') >= 0);
  const b = deck.card('c-9', Object.assign({ live: facts(), house: facts().house }, BUILDING));
  const K2 = page([b]);
  K2.heardLive('live c-9 null');
  check('c-605: at building, a null still says the house is gone', K2.houseOf(b) === null);
})();

/* ---------- c-607: what a live house holds, and closing an idle one ---------- */
function idleFacts(mb, ended) {
  return facts({ status: 'idle', turn_ended_at: iso(ended), tool: null, mem_mb: mb, detail: null,
    house: { bg_id: 'abcd1234', status: 'idle', state: 'idle', working: false, kind: 'background', recorded: true } });
}
(function () {
  const f = idleFacts(820, 42 * 60);
  const c = deck.card('c-20', Object.assign({ live: f, house: f.house }, BUILDING, { stage: 'review' }));
  const K = page([c]);
  check('c-607: the strip says idle age and memory', strip(K, c).indexOf('idle 42m, 0.8 GB') === 0);
  const w = facts({ mem_mb: 1450 });
  const busy = deck.card('c-21', Object.assign({ live: w, house: w.house }, BUILDING));
  const K2 = page([busy]);
  check('c-607: a working house says its memory too', strip(K2, busy).indexOf('1.4 GB') >= 0);
  const none = facts({ status: 'idle', turn_ended_at: iso(60), mem_mb: null, house: f.house });
  const bare = deck.card('c-22', Object.assign({ live: none, house: none.house }, BUILDING));
  check('c-607: no reading, no memory shown (never a guess)', !/GB|MB/.test(strip(page([bare]), bare)));
})();
function keysOf(K, c) {
  return deck.wrap(K.gateActions(c).concat(K.cardItems(c)), K).childNodes
    .map((n) => n.getAttribute && n.getAttribute('data-key')).filter(Boolean);
}
(function () {
  const f = idleFacts(820, 600);
  const idle = deck.card('c-23', Object.assign({ live: f, house: f.house }, BUILDING, { stage: 'review' }));
  const K = page([idle]);
  check('c-607: an idle house at review is offered Close idle house', keysOf(K, idle).indexOf('close-idle') >= 0);
  const w = facts();
  const busy = deck.card('c-24', Object.assign({ live: w, house: Object.assign({ recorded: true }, w.house) }, BUILDING, { stage: 'review' }));
  check('c-607: a working house is never offered it', keysOf(page([busy]), busy).indexOf('close-idle') < 0);
  const jobs = deck.card('c-25', Object.assign({ live: f, house: f.house, jobs: [{ label: 'poll' }] }, BUILDING, { stage: 'review' }));
  check('c-607: nor an idle house with a job of its own running', keysOf(page([jobs]), jobs).indexOf('close-idle') < 0);
  const building = deck.card('c-27', Object.assign({ live: f, house: f.house }, BUILDING));
  check('c-607 review: an idle house at building is not offered it (nothing would bring it back)',
        keysOf(page([building]), building).indexOf('close-idle') < 0);
  const closedReview = deck.card('c-28', Object.assign({}, BUILDING, { stage: 'review', derived: { closed_idle: true } }));
  check('c-607 review: at review the card says his gate answer brings it back',
        K.houseWord(closedReview).text === 'closed while idle: your answer at the gate or your Resume brings it back (about 5 to 15 s)');
  const closed = deck.card('c-26', Object.assign({}, BUILDING, { stage: 'shipping', derived: { closed_idle: true } }));
  check('c-607: a closed card says how it comes back',
        K.houseWord(closed).text === 'closed while idle: the next review or your tap resumes it (about 5 to 15 s)');
})();
(function () {
  const a = idleFacts(800, 600), b = idleFacts(1300, 3600), w = facts({ mem_mb: 900 });
  const cards = [
    deck.card('c-30', Object.assign({ live: a, house: a.house }, BUILDING, { stage: 'review' })),
    deck.card('c-31', Object.assign({ live: b, house: b.house }, BUILDING, { stage: 'shipping' })),
    deck.card('c-32', Object.assign({ live: w, house: Object.assign({ recorded: true }, w.house) }, BUILDING))
  ];
  const K = deck.load(APP, MODULES, {});
  K.App.data = deck.state(cards, { houses: ['c-30', 'c-32'], idle: ['c-30', 'c-31'] });
  K.App.space = 'personal';
  K.App.stripGot = Date.now();
  K.render = K.renderBody = function () {};
  const list = K.idleHouses().map((c) => c.id);
  check('c-607: Now lists the idle houses, a shipping one with no tile too, never the working one',
        list.join() === 'c-30,c-31');
  check('c-607: Now totals them', K.idleLine(K.idleHouses()) === '2 idle houses holding about 2.1 GB');
  const panel = deck.wrap(K.idlePanel(), K);
  const all = deck.byClass(panel, 'btn').filter((n) => /Close all idle/.test(n.textContent));
  check('c-607: one Close all idle for the review and shipping houses', all.length === 1 && /\(2\)/.test(all[0].textContent));
  check('c-607: each row names its stage and idle age', /review · idle 10m · 0.8 GB/.test(panel.textContent)
        && /shipping · idle 1h · 1.3 GB/.test(panel.textContent));
})();

/* ---------- a-72: a shipping house says when the drain closes it ---------- */
(function () {
  const f = idleFacts(820, 100 * 60);
  const since = new Date(Date.now() - 100 * 60 * 1000).toISOString();
  const c = deck.card('c-40', Object.assign({ live: f, house: f.house }, BUILDING,
    { stage: 'shipping', derived: { ship_idle: { since: since, close_at: null, hours: 2 } } }));
  const K = page([c]);
  check('a-72: the strip says idle 1h40m, closes at 2h', strip(K, c).indexOf('idle 1h40m, closes at 2h, 0.8 GB') === 0);
  K.App.data.idle = ['c-40'];
  check('a-72: so does its Now row', /shipping · idle 1h40m, closes at 2h · 0.8 GB/.test(deck.wrap(K.idlePanel(), K).textContent));
  const r = deck.card('c-41', Object.assign({ live: f, house: f.house }, BUILDING, { stage: 'review' }));
  check('a-72: a review house is never said to close', strip(page([r]), r).indexOf('closes') < 0);
})();

process.stdout.write(JSON.stringify(fails.length ? { ok: false, failed: fails } : { ok: true }));
