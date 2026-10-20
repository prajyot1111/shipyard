/* A card's markdown files in the viewer (c-719), on the real plan shell: one file drawn
 * from the payload the route answered, through the plan's own block renderer, read only;
 * then the list of the card's files.
 *
 * Usage: node cardfiles.js <path to app/> <file payload.json> <files payload.json>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const fs = require('fs');
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const FILE = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const LIST = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
const MODULES = ['ui.core.js', 'ui.boardlayout.js', 'ui.board.js', 'ui.planlook.js', 'ui.plandiagram.js', 'ui.plancode.js',
                 'ui.planfinding.js', 'ui.receipt.js', 'ui.planblocks.js', 'ui.plan.js', 'ui.ci.js', 'ui.shipping.js', 'ui.shipsendback.js',
                 'ui.comments.js'];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }
const id = FILE.card.id;
function fetch() {
  return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ ok: true, result: {} }) });
}
const cls = (re) => (n) => re.test(n.getAttribute && (n.getAttribute('class') || ''));

globalThis.location = { pathname: '/file/' + id + '/report.md', search: '' };
const K = deck.load(APP, MODULES, { desk: true, fetch: fetch });
K.render = K.renderBody = function () {};
K.App.data = deck.state([]);
K.App.space = 'personal';
K.readPlanRoute();
check('the route reads the file\'s name', K.planState.doc === 'file' && K.planState.file === 'report.md');
K.planState.data = FILE;

/* ---------- one file, in the plan's renderer ---------- */
let view = deck.wrap(K.viewPlan(), K);
const text = view.textContent;
check('the file is drawn', text.indexOf('a third of what the pilot did') >= 0);
check('its table is the plan\'s table', deck.all(view, cls(/\bptable\b/)).length === 1);
check('its board is the plan\'s board block', deck.all(view, cls(/\bt-board\b/)).length === 1);
check('its callout is the plan\'s callout', deck.all(view, cls(/\bt-callout\b/)).length === 1);
check('a file has no gate', deck.labels(view).every((w) => !/^Approve|^Send back|^Done/.test(w)));
check('a file takes no notes', deck.all(view, cls(/\bpnote-add\b/)).length === 0);
const word = deck.all(view, cls(/\bpdocword\b/))[0];
check('the header word is File', !!word && word.textContent === 'File');
const tabs = deck.all(view, (n) => n.getAttribute && n.getAttribute('data-key') === 'tabs')[0];
const files = tabs ? deck.all(tabs, (n) => n.getAttribute('data-key') === 'doc-files')[0] : null;
check('the Files tab is marked and links back to the list',
      !!files && /\bon\b/.test(files.getAttribute('class')) && files.tagName === 'A' && files.getAttribute('href') === '/files/' + id);

/* ---------- the list ---------- */
globalThis.location.pathname = '/files/' + id;
K.readPlanRoute();
K.planState.data = LIST;
view = deck.wrap(K.viewPlan(), K);
const links = deck.all(view, cls(/(^|\s)pfile(\s|$)/)).map((n) => n.getAttribute('href'));
check('the list links each file to its page: ' + links.join(),
      links.join() === ['/file/' + id + '/report.md', '/file/' + id + '/results/B0.md'].join());
const here = deck.all(view, (n) => n.getAttribute && n.getAttribute('aria-current') === 'page');
check('the list is the current tab', here.length === 1 && here[0].textContent === 'Files');
/* ---------- r2.F9: a /file/ URL that carries ?doc= keeps its name when it is rewritten ---------- */
/* the stand-in history moves the stand-in location (tests/fixtures/deck-dom.js) */
globalThis.location.pathname = '/file/' + id + '/results/B0.md';
globalThis.location.search = '?doc=file';
K.readPlanRoute();
const replaced = globalThis.location.pathname + globalThis.location.search;
check('r2.F9: the rewritten URL keeps the file: ' + replaced, replaced === '/file/' + id + '/results/B0.md');
process.stdout.write(JSON.stringify(fails.length ? { fails: fails } : { ok: true }));
