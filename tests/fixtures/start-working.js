/* The page never blanks (c-729), under node: a setup action on the first run keeps what the
 * screen shows, marks the row it was pressed in as working, waits out a deck that restarts
 * (the report asked for until a new `boot` answers), and then reads the state again, so the
 * step's Done and Next follow without a reload. A Look again keeps the screen too.
 *
 * Usage: node start-working.js <path to app/>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const APP = process.argv[2];
const { check, fails, firstrun, REPORT, page, body, keyed, deck } = require('./start-page.js')(APP);

const OLD = Object.assign({}, REPORT, { boot: 'old' });
const NEW = Object.assign({}, REPORT, { boot: 'new' });
/* a turn of the event loop, for the answers already resolved; the page's own timers are
   held and run by the check (`K._setTimeout`), never on the wall clock */
const turn = () => new Promise((done) => setImmediate(done));
function timers(K) {
  const held = [];
  K._setTimeout = (fn, ms) => { held.push(fn); K._waits = (K._waits || []).concat([ms]); return held.length; };
  return async function run() { const now = held.splice(0); now.forEach((fn) => fn()); for (let i = 0; i < 5; i++) await turn(); };
}
const blank = (b) => b.textContent.indexOf('reading the setup') >= 0;
const marked = (node) => !!node && /(^|\s)setup-working(\s|$)/.test(node.className) && node.getAttribute('aria-busy') === 'true';
/* a click the page hears, as the browser sends it, then the button's own handler */
function press(K, node) {
  (K._doc._on.click || []).forEach((fn) => fn({ target: node }));
  node._on.onclick({ target: node });
}

async function restarting() {
  const K = page(firstrun(null, true), 'start', OLD);
  K.App.step = 'choose-builder';
  const tick = timers(K);
  body(K);
  await turn();
  let b = body(K);
  check('restart: the screen is drawn from the report', !blank(b) && !!keyed(b, 'builder-full'));
  const loads = [];
  K.load = () => { loads.push(K._report ? K._report.boot : 'old'); return Promise.resolve(); };
  K.act = () => Promise.resolve({ restarting: true });
  const row = keyed(b, 'builder-full');
  const pick = row && row.childNodes.filter((n) => n.tagName === 'BUTTON')[0];
  if (!pick) { check('restart: the Full card has its button', false); return; }
  press(K, pick);
  await turn();
  b = body(K);
  check('restart: nothing blanks while the action runs', !blank(b));
  check('restart: the row pressed in is marked working', marked(keyed(b, 'builder-full')));
  await tick();
  b = body(K);
  check('restart: still the old process, still shown and still working', !blank(b) && marked(keyed(b, 'builder-full')));
  check('restart: the state is not read from the old process', loads.length === 0);
  K._report = NEW;
  await tick();
  await tick();
  b = body(K);
  check('restart: the new process answered, the state is read again: ' + JSON.stringify(loads), loads.join() === 'new');
  check('restart: the mark is gone once it has', !marked(keyed(b, 'builder-full')));
  check('restart: and nothing blanked', !blank(b));
}

/* r1.F3: a read of the report already on its way when the action lands is not the end of
   it: the action's own read follows it, then the state, and the mark goes */
async function inFlight() {
  const K = page(firstrun(null, true), 'start', NEW);
  K.App.step = 'choose-builder';
  body(K);
  await turn();
  const b = body(K);
  let loads = 0;
  K.load = () => { loads += 1; return Promise.resolve(); };
  K.act = () => Promise.resolve({ reloaded: true });
  const reads = () => K._fetched.filter((u) => u === '/api/setup').length;
  const before = reads();
  K._hold = [];
  K.loadSetup(0);
  const row = keyed(b, 'builder-full');
  const pick = row && row.childNodes.filter((n) => n.tagName === 'BUTTON')[0];
  if (!pick) { check('in flight: the Full card has its button', false); return; }
  press(K, pick);
  for (let i = 0; i < 5; i++) await turn();
  check('in flight: marked while the earlier read is out', marked(keyed(body(K), 'builder-full')));
  const held = K._hold;
  K._hold = null;
  held.forEach((land) => land());
  for (let i = 0; i < 10; i++) await turn();
  check('in flight: the action is read after the earlier read: ' + (reads() - before), reads() - before === 2);
  check('in flight: then the state, once: ' + loads, loads === 1);
  check('in flight: and the mark is gone', !marked(keyed(body(K), 'builder-full')));
}

/* r1.F4: Add repo marks the repo it queued, never the form: the next address can be typed
   and added while a copy runs, pressed as the browser presses it (the page's click first) */
async function addWhileCopying() {
  const K = page(firstrun(null, true), 'start', REPORT);
  K.App.step = 'repos';
  body(K);
  await turn();
  let b = body(K);
  const sent = [];
  K.act = (one) => { sent.push(one); return new Promise(() => {}); };
  const type = (label, value) => {
    const input = deck.all(body(K), (n) => n.tagName === 'INPUT' && n.getAttribute('aria-label') === label)[0];
    if (input) input._on.oninput({ target: { value: value } });
    return !!input;
  };
  const addButton = () => deck.buttons(keyed(body(K), 'repo-add')).filter((n) => deck.labelOf(n) === 'Add repo')[0];
  if (!type('Repo address or folder', 'https://example.com/you/api.git') || !addButton()) { check('add: the form is drawn', false); return; }
  press(K, addButton());
  await turn();
  b = body(K);
  check('add: the copy is sent: ' + sent.length, sent.length === 1);
  check('add: the repo it copies is marked working', marked(keyed(b, 'adding-1')));
  check('add: the form is not, so the next address can be typed', !marked(keyed(b, 'repo-add')));
  type('Repo address or folder', 'https://example.com/you/web.git');
  press(K, addButton());
  await turn();
  b = body(K);
  check('add: the next one waits its turn on the list', !!keyed(b, 'adding-2') && sent.length === 1);
  check('add: and the form is still free', !marked(keyed(b, 'repo-add')));
}

async function lookAgain() {
  const K = page(firstrun(null, true), 'start', NEW);
  K.App.step = 'prerequisites';
  body(K);
  await turn();
  let loaded = 0;
  K.load = () => { loaded += 1; return Promise.resolve(); };
  K.setupParts.again();
  check('again: the screen stays while the report is read again', !blank(body(K)));
  for (let i = 0; i < 5; i++) await turn();
  check('again: and the state after it', loaded === 1);
}

/* Meet Bosun watches for the hello while it waits on it, and stops once it has it */
async function hello() {
  const fr = firstrun(null, true);
  const step = fr.steps.filter((s) => s.id === 'builder')[0];
  step.running = true; step.hello = false;
  const K = page(fr, 'start', NEW, { state: { console: { up: true, attach: '/i/bin/keel console attach' } } });
  K.App.step = 'builder';
  const tick = timers(K);
  K._answers['/api/hello'] = { hello: false };
  let loads = 0;
  K.load = () => { loads += 1; return Promise.resolve(); };
  body(K);
  await turn();
  /* r2.F1: drawn once. A no moves nothing on the deck (r1.F7), so nothing redraws the page:
     the watch asks again by itself, one timer at a time, with only the held timers run */
  const asks = () => K._fetched.filter((u) => u === '/api/hello').length;
  await tick();
  check('hello: the page asks whether the user has said hello: ' + asks(), asks() === 1);
  check('hello: by a read, not an action (r1.F6)', K._fetched.indexOf('/api/action') < 0);
  await tick();
  check('hello: and again after a no, with no redraw: ' + asks(), asks() === 2);
  check('hello: every three seconds at first: ' + K._waits.slice(-1), K._waits.slice(-1)[0] === 3000);
  for (let i = 0; i < 30; i++) await tick();
  check('hello: it keeps asking: ' + asks(), asks() === 32);
  check('hello: one timer at a time: ' + K._waits.length, K._waits.length === asks() + 1);
  check('hello: every ten seconds after the first minute: ' + K._waits.slice(-1), K._waits.slice(-1)[0] === 10000);
  check('hello: no state read while the answer is no: ' + loads, loads === 0);
  K._answers['/api/hello'] = { hello: true };
  await tick();
  check('hello: a yes reads the state: ' + loads, loads === 1);
  const after = asks();
  await tick();
  check('hello: and the watch stops: ' + (asks() - after), asks() === after);
  /* leaving the step stops it too */
  K._answers['/api/hello'] = { hello: false };
  body(K);
  await tick();
  K.App.view = 'now';
  const left = asks();
  await tick();
  await tick();
  check('hello: not once the page has left the step: ' + (asks() - left), asks() === left);
}

(async function () {
  await restarting();
  await inFlight();
  await addWhileCopying();
  await lookAgain();
  await hello();
  process.stdout.write(JSON.stringify(fails.length ? { fails } : { ok: true }));
})();
