/* A review outcome's finding cards, and syntax colour on every code block, run under node
 * against the DOM stand-in and read back (lane FC, FC-2 and FC-3).
 *
 * Usage: node plan-finding.js <path to app/> <payloads.json>
 * The payloads are what `GET /api/plan/<id>` answers, built by
 * tests/test_planfinding_render.py: `review` and `feature` (outcomes with finding blocks and
 * their excerpts), `plan` (the sample plan, with a code block) and `words` (no code at all).
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const PAYLOADS = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const MODULES = ['ui.core.js', 'ui.plancode.js', 'ui.planfinding.js', 'ui.planblocks.js', 'ui.plan.js'];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }
function attr(node, name) { return node.getAttribute(name); }

/* The highlighter is imported from the vendored files themselves, and every import is
   counted, so "loaded only when a page has code" is a number. */
const imports = [];
function page(which, opts) {
  opts = opts || {};
  globalThis.location = { pathname: '/outcome/c-900', search: opts.pane ? '?pane=' + opts.pane : '' };
  const K = deck.load(APP, MODULES, { desk: !!opts.desk });
  K.render = K.renderBody = function () {};
  K.App.data = deck.state([]);
  K.App.space = 'work';
  K.planCode.importModule = function (url) {
    imports.push(url);
    return import(pathToFileURL(path.join(APP, url)).href);
  };
  K.posted = [];
  K.post = function (url, init) {
    K.posted.push(JSON.parse(init.body));
    return Promise.resolve({ json: function () { return { ok: true }; } });
  };
  K.toast = function () {};
  K.readPlanRoute();
  K.planState.data = JSON.parse(JSON.stringify(PAYLOADS[which]));
  return K;
}
function view(K) { return deck.wrap(K.viewPlan(), K); }
function cards(v) { return deck.byClass(v, 'pfinding'); }
function cardOf(v, id) { return cards(v).filter((n) => attr(n, 'data-fid') === id)[0]; }
function textareas(n) { return deck.all(n, (x) => x.tagName === 'TEXTAREA'); }
function buttonNamed(n, label) { return deck.buttons(n).filter((b) => deck.labelOf(b) === label)[0]; }

async function main() {
  /* ---------- one card per finding, on the phone ---------- */
  let K = page('review', { pane: 'read' });
  let v = view(K);
  check('one card per finding', cards(v).length === 3);
  check('no batch and no copy block is drawn for a finding', deck.byClass(v, 'pbatch').length === 0
        && deck.byClass(v, 't-copy').length === 0);
  const f1 = cardOf(v, 'r1-f1');
  check('the head says the severity', !!f1 && deck.byClass(f1, 'pf-sev')[0].textContent === 'high');
  check('the head says the claim', !!f1 && deck.byClass(f1, 'pf-claim')[0].textContent.indexOf('before the settings load') >= 0);
  const at = f1 && deck.all(f1, (n) => n.tagName === 'A' && deck.hasClass(n, 'pf-at'))[0];
  check('the path:line is a link to the pull request', !!at && at.textContent === 'app/loader.py:40'
        && attr(at, 'href') === 'https://example.invalid/api/pr/4150');
  const lines = f1 ? deck.byClass(f1, 'cl') : [];
  check('the code is the lines around it: four either side', lines.length === 9);
  const marked = lines.filter((n) => deck.hasClass(n, 'hit'));
  check('the finding\'s own line is marked', marked.length === 1 && deck.byClass(marked[0], 'ln')[0].textContent === '40');
  check('each line carries its number', deck.byClass(lines[0] || new deck.Element('x'), 'ln')[0].textContent === '36');
  const f2 = cardOf(v, 'r1-f2');
  check('a range marks each of its lines', !!f2 && deck.byClass(f2, 'cl').filter((n) => deck.hasClass(n, 'hit')).length === 2);
  check('a disputed finding shows both sides', !!f2 && f2.textContent.indexOf('the two cannot disagree') >= 0
        && f2.textContent.indexOf('a literal in effect') >= 0);
  check('the why is drawn', !!f1 && f1.textContent.indexOf('the settings are loaded later') >= 0);
  const field = f1 ? textareas(f1)[0] : null;
  check('the comment is a field opened with the draft', !!field && String(field.value).indexOf('The cap is read at import time') === 0);
  const on = f1 ? deck.all(f1, (n) => deck.hasClass(n, 'pb-choice') && deck.hasClass(n, 'on')) : [];
  check('the recommended choice is picked', on.length === 1 && attr(on[0], 'data-key') === 'post');
  check('the phone stacks the card', !!f1 && !deck.hasClass(f1, 'pf-cols'));
  const f3 = cardOf(v, 'r1-f3');
  check('a low finding starts folded on the phone', !!f3 && deck.hasClass(f3, 'folded') && textareas(f3).length === 0);
  const head3 = f3 && deck.all(f3, (n) => deck.hasClass(n, 'pf-toggle'))[0];
  check('its head says it is folded', !!head3 && attr(head3, 'aria-expanded') === 'false');
  if (head3) head3.onclick({ stopPropagation() {}, preventDefault() {} });
  v = view(K);
  check('a tap on its head opens it', !deck.hasClass(cardOf(v, 'r1-f3'), 'folded') && textareas(cardOf(v, 'r1-f3')).length === 1);

  /* ---------- keeping his words is the edit mark Approve posts ---------- */
  const mine = textareas(cardOf(v, 'r1-f1'))[0];
  mine.oninput({ target: { value: 'Could the cap be read per call?' } });
  buttonNamed(cardOf(v, 'r1-f1'), 'Keep these words').onclick({ stopPropagation() {} });
  const kept = K.posted.filter((p) => p.verb === 'mark').map((p) => p.data);
  check('keeping his words is an edit mark on the finding', kept.length === 1 && kept[0].block === 'r1-f1'
        && kept[0].row === 'r1-f1' && kept[0].choice === 'edit' && kept[0].other === 'Could the cap be read per call?');
  v = view(K);
  const now = deck.all(cardOf(v, 'r1-f1'), (n) => deck.hasClass(n, 'pb-choice') && deck.hasClass(n, 'on'));
  check('the card then says edit', now.length === 1 && attr(now[0], 'data-key') === 'edit');
  check('and that Approve posts his words', cardOf(v, 'r1-f1').textContent.indexOf('Approve posts your words') >= 0);
  const drop = deck.all(cardOf(v, 'r1-f2'), (n) => deck.hasClass(n, 'pb-choice') && attr(n, 'data-key') === 'drop')[0];
  drop.onclick({ stopPropagation() {} });
  const last = K.posted[K.posted.length - 1].data;
  check('drop is a row mark on its own block', last.block === 'r1-f2' && last.row === 'r1-f2' && last.choice === 'drop');

  /* ---------- the desk: code left, comment right; Decide carries the cards ---------- */
  K = page('review', { desk: true });
  v = view(K);
  check('the desk draws every card in two columns', cards(v).length === 3 && cards(v).every((n) => deck.hasClass(n, 'pf-cols')));
  check('the desk folds nothing', cards(v).every((n) => !deck.hasClass(n, 'folded')));
  const side = deck.byClass(v, 'pside')[0];
  check('the round lists each finding', !!side && deck.byClass(side, 'pdl-row').filter((n) => /^r1-f/.test(attr(n, 'data-key'))).length === 3);
  K = page('review', { pane: 'decide' });
  check('Decide carries every finding', cards(view(K)).length === 3);

  /* ---------- a feature card names the member and links its own pull request ---------- */
  K = page('feature', { pane: 'read' });
  v = view(K);
  const g1 = cardOf(v, 'r1-f2');
  check('a feature finding names its member', !!g1 && deck.byClass(g1, 'pf-member')[0].textContent === 'web#2200');
  const gat = g1 && deck.all(g1, (n) => n.tagName === 'A' && deck.hasClass(n, 'pf-at'))[0];
  check('and links that member\'s pull request', !!gat && attr(gat, 'href') === 'https://example.invalid/web/pr/2200');

  /* ---------- FC-3: the highlighter loads only when a page has code ---------- */
  const cores = () => imports.filter((u) => /core\.min\.js$/.test(u)).length;
  let seen = imports.length;
  K = page('words', { pane: 'read' });
  view(K);
  check('a page with no code never asks for the highlighter', imports.length === seen);
  seen = cores();
  K = page('plan', { pane: 'read' });
  const doc = K.planState.data.doc;
  doc.blocks.push({ type: 'diff', id: 'x.diff1', section: 'x', lang: 'diff', path: 'app/loader.py', why: [],
                    text: '@@ -1,2 +1,2 @@\n-CAP = 40\n+CAP = settings.page_size()  # read once\n def page(rows):' });
  view(K);
  view(K);
  check('a page with code asks for it once', cores() === seen + 1);
  await K.planCode.ready();
  check('the languages it needs come with it', ['python', 'javascript', 'xml', 'sql', 'yaml', 'json', 'bash']
        .every((l) => imports.some((u) => u.indexOf('/languages/' + l + '.min.js') >= 0)));
  v = view(K);
  const py = deck.byClass(v, 't-code')[0];
  check('a python block is coloured', !!py && deck.byClass(py, 'hl-kw').length >= 1);
  const diff = deck.byClass(v, 't-diff')[0];
  const add = diff ? deck.byClass(diff, 'add')[0] : null;
  check('a diff keeps its tints under the colours', !!add && deck.byClass(add, 'hl-com').length === 1
        && add.textContent.indexOf('+CAP = settings.page_size()') === 0);
  check('a removed line keeps its tint', !!diff && deck.byClass(diff, 'del').length === 1);

  K = page('review', { pane: 'read' });
  view(K);
  await K.planCode.ready();
  const before = imports.length;
  v = view(K);
  const code1 = cardOf(v, 'r1-f1');
  check('a finding\'s code is coloured', deck.byClass(code1, 'hl-kw').length >= 1 && deck.byClass(code1, 'hl-com').length >= 1);
  const line40 = deck.byClass(code1, 'cl').filter((n) => deck.hasClass(n, 'hit'))[0];
  check('colouring keeps the words of the line', !!line40 && line40.textContent.indexOf('CAP = settings.page_size()  # read at import') >= 0);
  view(K);
  check('a page asks for it once, however often it draws', imports.length === before);
  K = page('feature', { pane: 'read' });
  view(K);
  await K.planCode.ready();
  const js = cardOf(view(K), 'r1-f2');
  check('a javascript finding is coloured too', deck.all(js, (n) => /^hl-/.test(n.className || '')).length > 0);

  /* ---------- nothing a house wrote becomes markup, in code either ---------- */
  K = page('review', { pane: 'read' });
  K.planState.data.doc.blocks.filter((b) => b.id === 'r1-f1')[0].code.lines[4] = 'x = "<img src=x onerror=alert(1)>"';
  v = view(K);
  check('safe: a tag in code is words', cardOf(v, 'r1-f1').textContent.indexOf('<img src=x onerror=alert(1)>') >= 0
        && deck.all(v, (n) => n.tagName === 'IMG').length === 0);

  process.stdout.write(JSON.stringify(fails.length ? { ok: false, fails: fails } : { ok: true }) + '\n');
}

main().catch(function (e) { process.stdout.write(JSON.stringify({ ok: false, error: String(e && e.stack || e) }) + '\n'); });
