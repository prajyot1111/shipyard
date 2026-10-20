/* c-644 r2.F3: a context page whose record is in the plan format, sent on by the server
 * (`{"redirect": "outcome"}`), replaces itself with the Outcome page: the URL, the doc, and a
 * fresh read with no stale tag.
 *
 * Usage: node viewer-redirect.js <path to app/> <outcome payload.json>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const fs = require('fs');
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const OUTCOME = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const MODULES = ['ui.core.js', 'ui.boardlayout.js', 'ui.board.js', 'ui.planlook.js', 'ui.plandiagram.js', 'ui.plancode.js',
                 'ui.planfinding.js', 'ui.receipt.js', 'ui.planblocks.js', 'ui.plan.js'];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }
const id = OUTCOME.card.id;
const asked = [];
function answer(body, tag) {
  return Promise.resolve({ ok: true, status: 200, headers: { get: (h) => (h === 'ETag' ? tag : null) },
                           json: () => Promise.resolve(body) });
}
function fetch(url, opts) {
  asked.push({ url: String(url), tag: ((opts || {}).headers || {})['If-None-Match'] || null });
  if (String(url).indexOf('doc=context') >= 0) return answer({ redirect: 'outcome', card: { id: id } }, '"ctx"');
  if (String(url).indexOf('/api/plan/') === 0) return answer(OUTCOME, '"out"');
  return answer({});
}

globalThis.location = { pathname: '/context/' + id, search: '' };
const K = deck.load(APP, MODULES, { desk: true, fetch: fetch });
K.render = K.renderBody = function () {};
K.openStream = function () {};
K._win.scrollTo = function () {};      /* a browser has it; the stand-in does not */
K.App.data = deck.state([]);
K.App.space = 'personal';
K.readPlanRoute();
K.loadPlan();
const tick = () => new Promise((resolve) => setImmediate(resolve));
(async function () {
  for (let i = 0; i < 4; i++) await tick();
  /* the replaced page's first draw asks for the outcome */
  K.viewPlan();
  for (let i = 0; i < 4; i++) await tick();
  check('the page is now the outcome\'s: ' + K._win.location.pathname, K._win.location.pathname === '/outcome/' + id);
  check('the doc is the outcome', K.planState.doc === 'outcome');
  check('the page holds no error: ' + K.planState.error, !K.planState.error);
  const plans = asked.filter((a) => a.url.indexOf('/api/plan/') === 0);
  check('the outcome is read next: ' + JSON.stringify(plans), (plans[1] || {}).url === '/api/plan/' + id + '?doc=outcome');
  check('with no stale tag', (plans[1] || {}).tag === null);
  check('the outcome is drawn', !!K.planState.data && K.planState.data.doc_name === 'outcome');
  process.stdout.write(JSON.stringify(fails.length ? { fails: fails } : { ok: true }));
})().catch((e) => { process.stdout.write(JSON.stringify({ fails: fails.concat(['threw: ' + e.stack]) })); });
