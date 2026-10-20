/* The CI page on the real plan shell (c-642 r1.F1, F2, F11, F14): the plan modules and
 * app/ui.ci.js loaded whole under the DOM stand-in, `fetch` counted.
 *
 * Usage: node ci-shell.js <path to app/> <payload.json>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const fs = require('fs');
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const PAYLOAD = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const MODULES = ['ui.core.js', 'ui.boardlayout.js', 'ui.board.js', 'ui.planlook.js', 'ui.plandiagram.js', 'ui.plancode.js',
                 'ui.planfinding.js', 'ui.receipt.js', 'ui.planblocks.js', 'ui.plan.js', 'ui.ci.js'];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

const fetched = [];
let answer = () => Promise.resolve({ ok: true, json: () => Promise.resolve(JSON.parse(JSON.stringify(PAYLOAD))) });
function fetch(url) { fetched.push(String(url)); return answer(); }

globalThis.location = { pathname: '/ci/c-001', search: '' };
/* r2.F3: the first read fails (a proxy's HTML page), then Refresh reads it */
const K = deck.load(APP, MODULES, { desk: true, fetch: fetch });
K.render = K.renderBody = function () {};
K.App.data = deck.state([]);
K.App.space = 'personal';
K.readPlanRoute();
const worn = {};
K._doc.documentElement.setAttribute = function (k, v) { worn[k] = v; };
const tick = () => new Promise((resolve) => setImmediate(resolve));

(async function () {
  answer = () => Promise.resolve({ ok: false, status: 502, json: () => Promise.reject(new SyntaxError('Unexpected token <')) });
  K.viewPlan();
  await tick(); await tick();
  let first = deck.wrap(K.viewPlan(), K);
  const err = deck.all(first, (n) => n.getAttribute('data-key') === 'ci-error')[0];
  check('a failed first read says the status', !!err && err.textContent.indexOf('HTTP 502') >= 0);
  const retry = deck.all(first, (n) => n.getAttribute('data-key') === 'ci-refresh')[0];
  check('a failed first read still has Refresh', !!retry);
  check('a failed first read links back to the card', deck.all(first, (n) => (n.getAttribute('href') || '').indexOf('card=c-001') >= 0).length === 1);
  answer = () => Promise.resolve({ ok: true, json: () => Promise.resolve(JSON.parse(JSON.stringify(PAYLOAD))) });
  fetched.length = 0;
  if (retry) retry.onclick();
  await tick(); await tick();
  check('Refresh after a failed first read draws the page', deck.all(deck.wrap(K.viewPlan(), K),
    (n) => /^build-/.test(n.getAttribute('data-key') || '')).length === 1);
  fetched.length = 0;
  check('the page wears its card\'s palette', worn['data-mode'] === K.palette('personal'));

  K.viewPlan();                                   /* drawn again: no read */
  check('a draw with data does not read again', fetched.length === 0);
  fetched.push('/api/ci/c-001');                  /* counted as the one read so far */

  let view = deck.wrap(K.viewPlan(), K);
  check('the builds are drawn', deck.all(view, (n) => /^build-/.test(n.getAttribute('data-key') || '')).length === 1);
  /* the real K.docTabs: the header switches to the plan and the outcome, and marks CI as here */
  const hrefs = deck.all(view, (n) => n.tagName === 'A').map((n) => n.getAttribute('href') || '');
  check('the header links the plan', hrefs.indexOf('/plan/c-001') >= 0);
  check('the header links the outcome', hrefs.indexOf('/outcome/c-001') >= 0);
  check('the header does not link CI to itself', hrefs.indexOf('/ci/c-001') < 0);

  /* a board event, or the tab coming back, reloads the plan shell: never the CI read */
  await K.loadPlan(true);
  await K.loadPlan();
  check('a board event does not read CI again', fetched.length === 1);

  /* Refresh twice in a row: one read */
  const refresh = () => deck.all(deck.wrap(K.viewPlan(), K), (n) => n.getAttribute('data-key') === 'ci-refresh')[0];
  answer = () => Promise.reject(new Error('the deck did not answer'));
  refresh().onclick();
  refresh().onclick();
  check('a second tap while reading does not read again', fetched.length === 2);
  await tick(); await tick();

  /* a failed read keeps what was read, its header and Refresh, and says it failed */
  view = deck.wrap(K.viewPlan(), K);
  check('a failed Refresh says so', deck.all(view, (n) => n.getAttribute('data-key') === 'ci-error').length === 1);
  check('a failed Refresh keeps Refresh', !!refresh());
  check('a failed Refresh keeps the builds', deck.all(view, (n) => /^build-/.test(n.getAttribute('data-key') || '')).length === 1);

  answer = () => Promise.resolve({ ok: true, json: () => Promise.resolve(JSON.parse(JSON.stringify(PAYLOAD))) });
  refresh().onclick();
  await tick(); await tick();
  view = deck.wrap(K.viewPlan(), K);
  check('Refresh after a failure reads again and clears it', fetched.length === 3 &&
        deck.all(view, (n) => n.getAttribute('data-key') === 'ci-error').length === 0);

  /* the summary counts each state apart */
  const sum = deck.all(view, (n) => n.getAttribute('data-key') === 'ci-sum')[0];
  check('the summary counts passed, failed and running apart: ' + (sum && sum.textContent),
        !!sum && sum.textContent.indexOf('1 failed, 1 running, 1 passed') >= 0);
  process.stdout.write(JSON.stringify(fails.length ? { fails: fails } : { ok: true }));
})().catch((e) => { process.stdout.write(JSON.stringify({ fails: fails.concat(['threw: ' + e.message]) })); });
