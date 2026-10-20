/* The deck's views from one manifest (c-634), under node against the deck's DOM stand-in:
 * every script app/views.json lists is loaded in its order, as the served page loads them,
 * and the checks below hold the rail, the dock, the body's dispatch and the drain line to
 * the manifest. Every check that did not hold is named.
 *
 * Usage: node views-deck.js <path to app/>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const MANIFEST = JSON.parse(fs.readFileSync(path.join(APP, 'views.json'), 'utf8'));
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

const ready = (why) => ({ ready: true, why: why, step: null });
const not = (why, step) => ({ ready: false, why: why, step: step === undefined ? 'integrations' : step });
function readiness(segments) {
  return { install: { prerequisites: ready('ok'), voice: ready('ok'), builder: ready('ok'),
                      segments: segments ? ready('1 segment') : not('no segment is installed', null) },
           spaces: { personal: { repos: ready('1 repo: keel'), tracker: ready('x'), codehost: ready('x'), reviews: ready('x') },
                     work: { repos: ready('x'), tracker: ready('x'), codehost: ready('x'), reviews: ready('x') } } };
}
function page(view, opts) {
  opts = opts || {};
  const K = deck.load(APP, MANIFEST.scripts, { desk: true, fetch: () => new Promise(() => {}), views: opts.views });
  K.App.data = deck.state([], opts.extra);
  K.App.data.readiness = readiness(opts.segments !== false);
  K.App.space = 'personal';
  K.App.view = view;
  K.App.card = null;
  /* the full-screen board's class sync reaches for document.body, which the stand-in has not */
  K.boardFull = null;
  return K;
}
const railNames = (K) => { K.renderRail(); return deck.byClass(K._doc.getElementById('rail'), 'rail-item').map((n) => n.textContent); };

/* every row's render is defined by the scripts the manifest lists */
(function () {
  const K = page('now');
  MANIFEST.views.forEach(function (v) {
    check('render: K.' + v.render + ' is defined for ' + v.key, typeof K[v.render] === 'function');
  });
  check('rows: every row', K.ROWS.length === MANIFEST.views.length);
  check('rail: every row but More', JSON.stringify(K.VIEWS.map((v) => v.key))
    === JSON.stringify(MANIFEST.views.filter((v) => v.nav !== false).map((v) => v.key)));
  check('dock: the dock rows, in order', JSON.stringify(K.DOCK) === JSON.stringify(['now', 'attention', 'cards', 'segments', 'more']));
  check('more: its name and icon are the row\'s', K.viewOf('more').name === 'More' && K.viewOf('more').icon === '⋯');
})();

/* the body draws the route's own render, with its arg */
(function () {
  const K = page('reviews');
  let asked = null;
  const was = K.viewRoute;
  K.viewRoute = function (arg) { asked = arg; return was(arg); };
  K.renderBody();
  check('dispatch: reviews draws viewRoute with its arg', asked === 'reviews');
  const L = page('nowhere');
  L.renderBody();
  check('dispatch: a route no row names draws Now', L._doc.getElementById('body').textContent.indexOf('Now') >= 0);
})();

/* a view `keel new view demo` made (tests/test_scaffold.py runs this against its copy): the
   phone reaches it under More */
(function () {
  const K = page('more');
  if (!K.viewOf('demo')) return;
  check('scaffolded: its render is defined', typeof K.viewDemo === 'function');
  check('scaffolded: More lists it', deck.wrap(K.viewMore(), K).textContent.indexOf('Demo') >= 0);
  const D = page('demo');
  D.renderBody();
  check('scaffolded: its panel draws', D._doc.getElementById('body').textContent.indexOf('Nothing here yet') >= 0);
})();

/* a new row is a new view: on the rail, opened by its key, with no other list edited */
(function () {
  const views = JSON.parse(JSON.stringify(MANIFEST));
  views.views.push({ key: 'demo', name: 'Demo', icon: '◇', render: 'viewDemo', script: 'ui.js', needs: [] });
  const K = page('demo', { views: views });
  K.viewDemo = function () { return K.el('section', { class: 'panel', 'data-key': 'demo' }, 'the demo panel'); };
  check('new row: on the rail', railNames(K).indexOf('Demo') >= 0);
  K.renderBody();
  check('new row: its body is its render', K._doc.getElementById('body').textContent.indexOf('the demo panel') >= 0);
  K.renderHeader();
  check('new row: the header names it', K._doc.getElementById('header').textContent.indexOf('Demo') >= 0);
})();

/* the dock leaves Segments out until a segment is installed (S3), and Start the rail after Finish (S4) */
(function () {
  const K = page('now', { segments: false });
  check('dock: no Segments before a segment', K.dockKeys().indexOf('segments') < 0 && K.dockKeys().length === 4);
  const done = page('now', { extra: { firstrun: { install: true, finished: true } } });
  check('rail: Start leaves after Finish', railNames(done).indexOf('Start') < 0);
  const fresh = page('now', { extra: { firstrun: { install: true, finished: false } } });
  check('rail: Start before Finish', railNames(fresh).indexOf('Start') >= 0);
})();

/* one machine never names itself: not on the drain line (c-634, c-622) */
(function () {
  const K = page('now');
  const one = K.drainLine();
  check('drain: one machine names no host: ' + one, one.indexOf('mac') < 0 && /^drain: polled /.test(one));
})();

/* nor on a Logins row (c-634, c-622) */
(function () {
  const login = { id: 'claude-personal', label: 'Claude personal', host: 'mac', state: 'good', where: '/x' };
  const one = page('now', { extra: { health: { level: 'green', reasons: [], services: [], logins: [login] } } });
  check('logins: one machine names no host', one.loginsBlock().textContent.indexOf('mac') < 0);
})();

/* a page that is not the deck has no manifest, and no views */
(function () {
  const K = deck.load(APP, ['ui.core.js'], { views: null });
  check('no manifest: no views', K.VIEWS.length === 0 && K.DOCK.length === 0);
})();

process.stdout.write(JSON.stringify(fails.length ? { ok: false, failed: fails } : { ok: true }));
