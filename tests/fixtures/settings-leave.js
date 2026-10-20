/* Leaving Settings with a change pending, through the deck's REAL routing (c-661): app/ui.core.js
 * (`go`, its popstate listener), app/ui.leave.js (the question, the stamps, the walk back) and
 * app/ui.settings.js (`K.beforeLeave`) loaded together on the deck's DOM stand-in, with a
 * history that has what a browser's has: a state per entry, Back, Forward and `go(n)`, each
 * firing popstate. Two things a browser does that the checks need are switches on it:
 * `raw(url)` adds an entry with no state, as a `#fragment` link does, and `defer` holds each
 * move until `flush()`, as a browser's `history.go` lands later than its call.
 *
 * Usage: node settings-leave.js <path to app/> <report.json>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const fs = require('fs');
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const report = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const fails = [];
function check(name, ok, got) { if (!ok) fails.push(got === undefined ? name : name + ': ' + JSON.stringify(got)); }
const tick = () => new Promise((done) => setImmediate(done));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/* the clock app/ui.leave.js reads, so a walk can be left waiting past its limit */
const realNow = Date.now;
let skew = 0;
Date.now = () => realNow() + skew;

function historyOf(win, moveTo) {
  const entries = [{ url: win.location.pathname + win.location.search, state: null }];
  const queue = [];
  let at = 0;
  function move(n) {
    if (at + n < 0 || at + n >= entries.length) return;
    at += n;
    moveTo(entries[at].url);
    win._pop.forEach((fn) => fn({ state: entries[at].state }));
  }
  function add(url, state) { entries.splice(at + 1); entries.push({ url: String(url), state }); at += 1; moveTo(url); }
  const h = {
    defer: false,
    get state() { return entries[at].state; },
    pushState(state, title, url) { add(url, state); },
    replaceState(state, title, url) { entries[at] = { url: String(url), state }; moveTo(url); },
    go(n) { if (h.defer) queue.push(n); else move(n); },
    back() { h.go(-1); },
    forward() { h.go(1); },
    flush() { if (queue.length) move(queue.shift()); },
    raw(url) { add(url, null); },
    /* the entry at `i` is no longer the one that was noted: its stamp is another */
    restamp(i, k) { entries[i].state = Object.assign({}, entries[i].state, { k }); },
    stamps: () => entries.map((e) => (e.state && e.state.k) || null),
    urls: () => entries.map((e) => e.url),
    at: () => at
  };
  return h;
}

/* A deck loaded on `search`, with the report read: what a check drives and reads back. */
async function page(search) {
  globalThis.location = { pathname: '/', search };
  skew = 0;
  const p = { answers: [], asked: [] };
  const K = deck.load(APP, ['ui.core.js', 'ui.leave.js', 'ui.settings.js'], {
    desk: true,
    fetch: () => Promise.resolve({ json: () => Promise.resolve(JSON.parse(JSON.stringify(report))) }),
    history: (win, moveTo) => (p.history = historyOf(win, moveTo))
  });
  K._win.confirm = (words) => { p.asked.push(words); return p.answers.length ? p.answers.shift() : false; };
  K.App.data = deck.state([]);
  K.render = function () { K.enterRoute(); };      /* the pass's own first step (app/ui.js) */
  K.renderBody = function () {};
  K.readRoute();
  K.render();
  K.viewSettings();                                /* asks for the report */
  await tick();
  p.K = K;
  p.tree = () => deck.wrap(K.viewSettings(), K);
  p.turn = () => {
    const box = deck.all(p.tree(), (n) => n.getAttribute('type') === 'checkbox' && String(n.getAttribute('data-fk')).indexOf('work|') === 0)[0];
    box.onchange({ target: { checked: !box.checked } });
  };
  p.pending = () => deck.byClass(p.tree(), 'set-unsaved').length;
  p.bar = () => deck.byClass(p.tree(), 'bar').length;
  p.where = () => ({ view: K.App.view, search: K._win.location.search, at: p.history.at(), urls: p.history.urls() });
  /* an entry with no stamp, drawn: what a `#fragment` link leaves behind */
  p.raw = (url) => { p.history.raw(url); K.readRoute(); K.render(); };
  return p;
}

const CARDS = '/?view=cards&space=work', NOW = '/?view=now', SETTINGS = '/?view=settings';

async function taps() {
  /* a tap on another view, refused: `go` returns before it moves anything */
  const p = await page('?view=cards&space=work');
  p.K.go('settings');
  p.turn();
  const before = p.where();
  p.K.go('cards');
  check('go refused: he is still on Settings, nothing pushed, the change still pending',
        same(p.where(), before) && p.asked.length === 1 && p.pending() === 1 && p.bar() === 1, p.where());
  /* a yes: the move happens and the changes are dropped */
  p.answers.push(true);
  p.K.go('cards');
  check('go accepted: he is on Cards', p.K.App.view === 'cards' && p.asked.length === 2, p.where());
  p.K.go('settings');
  check('go accepted: nothing is pending when he comes back', p.pending() === 0 && p.bar() === 0, [p.pending(), p.bar()]);
}

async function backAndForward() {
  /* every entry the page makes is stamped, the one it loaded on included */
  let p = await page('?view=cards&space=work');
  p.K.go('now');
  p.K.go('settings');
  const stamps = p.history.stamps();
  check('stamps: every entry has one, and they grow', stamps.every((k) => typeof k === 'number')
        && stamps[0] < stamps[1] && stamps[1] < stamps[2], stamps);
  /* Back, refused: walked back to the very entry, no second copy */
  p.turn();
  let before = p.where();
  p.history.back();
  check('back refused: the same entry, the same list of entries', same(p.where(), before)
        && p.asked.length === 1 && p.pending() === 1, p.where());
  check('back refused: the route was not read (the space, the card)', p.K.App.space === 'work' && p.K.App.card === null);
  /* accepted: Back goes where it was going */
  p.answers.push(true);
  p.history.back();
  check('back accepted: he is on Now and nothing is pending', p.K.App.view === 'now' && p.history.at() === 1 && p.pending() === 0, p.where());

  /* Forward, refused: no duplicate Settings entry, and the entry ahead is still ahead */
  p = await page('?view=cards&space=work');
  p.K.go('settings');
  p.K.go('cards');
  p.history.back();                                /* nothing pending: not asked */
  check('forward setup: back on Settings unasked', p.K.App.view === 'settings' && p.asked.length === 0, p.where());
  p.turn();
  before = p.where();
  p.history.forward();
  check('forward refused: the same entry, the same list of entries', same(p.where(), before)
        && p.asked.length === 1 && before.urls.filter((u) => /view=settings/.test(u)).length === 1, p.where());

  /* Back onto the entry the page loaded on, from a Settings entry that carries more than its
     view: he is on the same entry, with the search string it had */
  p = await page('?view=cards&space=work');
  p.history.pushState(null, '', '/?view=settings&space=work&d=deep');
  p.K.readRoute();
  p.K.render();
  p.turn();
  before = p.where();
  p.history.back();
  check('back refused onto the loaded entry: the same entry and search string', same(p.where(), before)
        && before.search === '?view=settings&space=work&d=deep' && p.K.App.density === 'deep' && p.pending() === 1, p.where());

  /* two steps back at once, over an entry with no stamp: walked back across it */
  p = await page('?view=cards&space=work');
  p.raw(NOW);
  p.K.go('settings');
  p.turn();
  before = p.where();
  p.history.go(-2);
  check('two-step back refused, an unstamped entry between: the same entry, the same list', same(p.where(), before)
        && same(before.urls, [CARDS, NOW, SETTINGS]) && p.asked.length === 1, p.where());
}

/* What is left imperfect, exactly as app/ui.leave.js and the Atlas admit it. */
async function unstampedLandings() {
  /* Back ONTO an entry with no stamp: Settings is pushed again, which drops the old Settings
     entry and the one that lay ahead of it */
  let p = await page('?view=cards&space=work');
  p.raw(NOW);
  p.K.go('settings');
  p.K.go('cards');
  p.history.back();
  p.turn();
  p.history.back();
  check('back refused onto an unstamped entry: Settings pushed again, the entry ahead dropped',
        same(p.where(), { view: 'settings', search: '?view=settings', at: 2, urls: [CARDS, NOW, SETTINGS] }) && p.pending() === 1, p.where());

  /* Forward ONTO one: a second copy of Settings after it, and what lay ahead of it dropped */
  p = await page('?view=cards&space=work');
  p.K.go('settings');
  p.raw(NOW);
  p.K.go('cards');
  p.history.go(-2);
  p.turn();
  p.history.forward();
  check('forward refused onto an unstamped entry: a second Settings entry after it, the entry ahead dropped',
        same(p.where(), { view: 'settings', search: '?view=settings', at: 3, urls: [CARDS, SETTINGS, NOW, SETTINGS] }) && p.pending() === 1, p.where());

  /* a refusal that STARTS on an entry with no stamp (Settings reached by a `#fragment`
     link), Back onto a stamped one: no direction either, so Settings is pushed again */
  p = await page('?view=cards&space=work');
  p.raw(SETTINGS);
  p.turn();
  p.history.back();
  check('back refused from an unstamped Settings entry: Settings pushed again after the entry he landed on',
        same(p.where(), { view: 'settings', search: '?view=settings', at: 1, urls: [CARDS, SETTINGS] }) && p.pending() === 1, p.where());

  /* the walk passes the stamp it is looking for (the entry is no longer what was noted):
     it stops there and pushes Settings rather than walking on */
  p = await page('?view=cards&space=work');
  p.K.go('now');
  p.K.go('settings');
  p.turn();
  p.history.restamp(2, p.history.stamps()[2] + 5);
  p.history.back();
  check('walk overshoots: it stops and pushes Settings',
        same(p.where(), { view: 'settings', search: '?view=settings', at: 3, urls: [CARDS, NOW, SETTINGS, SETTINGS] }) && p.asked.length === 1, p.where());
}

/* A browser's `history.go` lands later than its call: the moves are held and let go one by one. */
async function deferred() {
  /* a render pass between the refusal's `history.go` and its popstate must not take the
     entry he is passing through for the one he is on */
  let p = await page('?view=cards&space=work');
  p.K.go('now');
  p.K.go('settings');
  p.turn();
  const before = p.where();
  p.history.defer = true;
  p.history.back();
  p.history.flush();                               /* lands on Now: refused, the walk is asked for */
  p.K.render();                                    /* a pass while the address is still Now's */
  p.history.flush();                               /* the walk lands on Settings */
  check('deferred: the first refused Back is back on Settings', same(p.where(), before) && p.asked.length === 1, p.where());
  p.history.back();
  p.history.flush();
  p.history.flush();
  check('a pass during the walk: a second refused Back still returns to the same entry', same(p.where(), before) && p.asked.length === 2, p.where());

  /* a walk whose popstate comes too late is forgotten: that popstate is an ordinary one,
     and the next Back is asked about, not swallowed */
  p = await page('?view=cards&space=work');
  p.K.go('now');
  p.K.go('settings');
  p.turn();
  const start = p.where();
  p.history.defer = true;
  p.history.back();
  p.history.flush();                               /* refused: the walk is asked for */
  skew = 3000;                                     /* and lands three seconds later */
  p.history.flush();
  check('timed-out walk: its late popstate is read as an ordinary one, on Settings', same(p.where(), start) && p.asked.length === 1 && p.pending() === 1, p.where());
  p.history.back();
  p.history.flush();
  check('timed-out walk: the next Back is asked about', p.asked.length === 2, p.asked.length);
  p.history.flush();
  check('timed-out walk: and refused back onto the same entry', same(p.where(), start), p.where());
  skew = 0;
}

(async function () {
  await taps();
  await backAndForward();
  await unstampedLandings();
  await deferred();
  console.log(JSON.stringify(fails.length ? { ok: false, fails } : { ok: true }));
})().catch((e) => { console.log(JSON.stringify({ ok: false, fails: [String(e && e.stack || e)] })); });
