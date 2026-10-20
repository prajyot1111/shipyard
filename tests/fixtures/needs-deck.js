/* Pages that say what they need (c-631), under node against the deck's DOM stand-in: the
 * page modules and the boot (ui.js, with a fetch that never answers) render Reviews, Cards,
 * Segments, More, Now, the dock and the New card form against readiness rows, and every
 * check that did not hold is named.
 *
 * Usage: node needs-deck.js <path to app/>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const MODULES = ['ui.core.js', 'ui.findcore.js', 'ui.findpages.js', 'ui.find.js', 'ui.tips.js', 'ui.modal.js',
                 'ui.shipping.js', 'ui.shipsendback.js', 'ui.cards.js', 'ui.tree.js', 'ui.reviews.js', 'ui.views.js', 'ui.js'];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

const ready = (why) => ({ ready: true, why: why, step: null });
const not = (why, step) => ({ ready: false, why: why, step: step === undefined ? 'integrations' : step });
const NO_PACK = 'no connection is turned on for personal';
function rows(over) {
  const out = {
    install: { prerequisites: ready('everything it needs is installed'), voice: ready('voice is answering'),
               builder: ready('the builder is on'), segments: ready('1 segment') },
    spaces: { personal: { repos: ready('1 repo: keel'), tracker: not(NO_PACK), codehost: not(NO_PACK), reviews: not(NO_PACK) },
              work: { repos: ready('1 repo: api'), tracker: ready('x'), codehost: ready('x'), reviews: ready('x') } }
  };
  (over || []).forEach((o) => { out[o[0]][o[1]] = Object.assign({}, out[o[0]][o[1]], o[2]); });
  return out;
}
function page(view, readiness, cards, extra) {
  const K = deck.load(APP, MODULES, { desk: true, fetch: () => new Promise(() => {}) });
  K.App.data = deck.state(cards || [], extra);
  if (readiness !== null) K.App.data.readiness = readiness;
  K.App.space = 'personal';
  K.App.view = view;
  K.App.card = null;
  return K;
}
const body = (K) => { K.renderBody(); return K._doc.getElementById('body'); };
const panels = (node) => deck.byClass(node, 'needs');
const links = (node) => deck.all(node, (n) => n.tagName === 'A').map((n) => n.getAttribute('href'));

/* Reviews, on a space with no pack: in the rail, and its page explains itself */
(function () {
  const K = page('reviews', rows());
  K.renderRail();
  const rail = K._doc.getElementById('rail');
  check('reviews: in the rail with no pack', rail.textContent.indexOf('Reviews') >= 0);
  const b = body(K), p = panels(b);
  check('reviews: one panel', p.length === 1);
  check('reviews: the why, said once', p.length === 1 && p[0].textContent.split('No connection is turned on for personal.').length === 2);
  check('reviews: what it unlocks', p.length === 1 && p[0].textContent.indexOf('A code host lets Approve open a pull request') >= 0);
  check('reviews: Set it up opens its step (c-632)', JSON.stringify(links(b)) === JSON.stringify(['?view=start&step=integrations&space=personal']));
  check('reviews: no false "nothing to review"', b.textContent.indexOf('needs your review') < 0);
  check('reviews: the page stays on reviews', K.App.view === 'reviews');
  K.setSpace('personal');
  check('reviews: a space switch does not send it away', K.App.view === 'reviews');
})();

/* Reviews where it is set up: no panel, and the empty line is back */
(function () {
  const K = page('reviews', rows([['spaces', 'personal', { codehost: ready('x'), reviews: ready('x') }]]));
  const b = body(K);
  check('reviews ready: no panel', panels(b).length === 0);
  check('reviews ready: the empty line', b.textContent.indexOf('no pull request needs your review') >= 0);
})();

/* c-730: Reviews shows only while some space can file review cards: a space whose readiness
   row says it cannot use review scanning at all (`declared` false) does not count, so on a
   fresh install with nothing that can fill it, it is not in the rail, More or the glance */
(function () {
  const off = (why) => Object.assign(not(why), { declared: false });
  const none = rows([['spaces', 'personal', off(NO_PACK)], ['spaces', 'work', off('review scanning is off for work')]]);
  none.spaces.personal.reviews = off(NO_PACK);
  none.spaces.work.reviews = off('review scanning is off for work');
  const K = page('now', none);
  K.renderRail();
  check('reviews hidden: not in the rail while no space can file review cards',
        K._doc.getElementById('rail').textContent.indexOf('Reviews') < 0);
  const more = deck.wrap(K.viewMore(), K);
  check('reviews hidden: not in More', deck.all(more, (n) => n.getAttribute('data-key') === 'reviews').length === 0);
  check('reviews hidden: no glance row', !deck.all(body(K), (n) => n.nodeType === 1 && n.getAttribute('data-key') === 'reviews').length);
  K.App.view = 'reviews';
  K.renderRail();
  check('reviews hidden: kept in the rail while its page is the one open',
        K._doc.getElementById('rail').textContent.indexOf('Reviews') >= 0);
  const some = rows();
  some.spaces.personal.reviews = off(NO_PACK);
  some.spaces.work.reviews = Object.assign(ready('x'), { declared: true });
  const J = page('now', some);
  J.renderRail();
  check('reviews shown: one space that can file them is enough', J._doc.getElementById('rail').textContent.indexOf('Reviews') >= 0);
  const held = rows();
  held.spaces.work.reviews = Object.assign(not('gh is not set up'), { declared: true });
  held.spaces.personal.reviews = off(NO_PACK);
  const H = page('now', held);
  H.renderRail();
  check('reviews shown: a space held up only by a failing check still counts', H._doc.getElementById('rail').textContent.indexOf('Reviews') >= 0);
})();

/* The dock: Segments only while a segment is installed; More lists it until then */
(function () {
  const K = page('now', rows([['install', 'segments', not('no segment is installed', null)]]));
  K.renderDock();
  const items = deck.byClass(K._doc.getElementById('dock'), 'dock-item');
  check('dock: four items without a segment', items.length === 4);
  check('dock: the full list is still five', K.DOCK.length === 5);
  const more = deck.wrap(K.viewMore(), K);
  const listed = deck.all(more, (n) => n.getAttribute('data-key') === 'segments' || n.getAttribute('data-key') === 'reviews');
  check('more: lists Segments and Reviews', listed.length === 2);
  check('more: each says not set up', more.textContent.split('not set up').length === 3);
  K.App.view = 'segments';
  const seg = body(K);
  check('segments: the panel', panels(seg).length === 1 && seg.textContent.indexOf('No segment is installed.') >= 0);
  check('segments: no Set it up without a step', links(seg).length === 0);
  check('segments: no "no segment has a summary" under it', seg.textContent.indexOf('no segment has a summary') < 0);
})();
(function () {
  const K = page('now', rows());
  K.renderDock();
  check('dock: five items with a segment', deck.byClass(K._doc.getElementById('dock'), 'dock-item').length === 5);
  const more = deck.wrap(K.viewMore(), K);
  check('more: Segments leaves More once in the dock',
        deck.all(more, (n) => n.getAttribute('data-key') === 'segments').length === 0);
})();

/* Segments: one installed and never fetched is drawn by name and says so (c-742) */
(function () {
  const segs = [
    { name: 'tides', summary: { tiles: [{ label: 'high tide', value: '04:12' }], notes: [] }, has_app: false, app_url: null, generated_at: null, fetched: true },
    { name: 'almanac', summary: { tiles: [], notes: [] }, has_app: false, app_url: null, generated_at: null, fetched: false, fetch_said: 'not fetched yet' }
  ];
  const K = page('segments', rows([['install', 'segments', ready('2 segments')]]), [], { segments: segs });
  const b = body(K), cards = deck.byClass(b, 'seg');
  check('segments: a never-fetched one is a card too', cards.length === 2);
  check('segments: it carries its name', cards.length === 2 && cards[1].textContent.indexOf('almanac') >= 0);
  check('segments: it says not fetched yet', cards.length === 2 && cards[1].textContent.indexOf('not fetched yet') >= 0
        && cards[1].textContent.indexOf('no tiles') < 0);
  check('segments: the fetched one does not', cards.length === 2 && cards[0].textContent.indexOf('not fetched yet') < 0);
  check('segments: never "No segment is installed"', b.textContent.indexOf('No segment is installed') < 0);
  K.App.view = 'now';
  check('now: its row says so too', body(K).textContent.indexOf('almanac not fetched yet') >= 0);
})();

/* Cards: a space with no repo, and an empty space said as such */
(function () {
  const K = page('cards', rows([['spaces', 'personal', { repos: not('no repo is cloned for personal yet', 'repos') }]]));
  K.App.data.spaces.personal.counts = { cards: 0 };
  const b = body(K);
  check('cards: the repos panel', panels(b).length === 1 && b.textContent.indexOf('No repo is cloned for personal yet.') >= 0);
  check('cards: an empty space says so', b.textContent.indexOf('no card in this space yet') >= 0);
  check('cards: and not "no card matches"', b.textContent.indexOf('no card matches') < 0);
})();
(function () {
  const K = page('cards', rows(), [deck.card('c-1', { stage: 'done' })]);
  K.App.data.spaces.personal.counts = { cards: 1 };
  const b = body(K);
  check('cards: repos ready, no panel', panels(b).length === 0);
  check('cards: a hidden card is a filter, "no card matches"', b.textContent.indexOf('no card matches') >= 0);
})();

/* The New card form: an empty repo field draws the one-line form */
(function () {
  const K = page('now', rows([['spaces', 'personal', { repos: not('no repo is cloned for personal yet', 'repos') }]]));
  K.App.data.spaces.personal.repos = [];
  K.App.data.spaces.personal.options = [{ key: 'repo', label: 'Repo', type: 'multiselect', options: [], default: [] }];
  K.openModal();
  const modal = K._doc.getElementById('modal');
  const line = deck.byClass(modal, 'needs-line');
  check('modal: the repo line', line.length === 1 && line[0].textContent.indexOf('No repo is cloned for personal yet.') >= 0);
  check('modal: with Set it up', links(modal).indexOf('?view=start&step=repos&space=personal') >= 0);
  check('modal: no empty chip row', deck.byClass(modal, 'chips').length === 0);
})();

/* The card pane's row, desk and phone (c-662: the lines were put and no row drew them) */
(function () {
  const lacks = [['spaces', 'personal', { tracker: not('no tracker is set up'), codehost: not('no code host is set up') }]];
  const rowKeys = (desk, c, readiness) => {
    const K = deck.load(APP, MODULES, { desk: desk, fetch: () => new Promise(() => {}) });
    K.App.data = deck.state([c]);
    K.App.data.readiness = readiness;
    K.App.space = 'personal';
    const bar = deck.byClass(deck.wrap([K.detailPane(c)], K), 'actionbar')[0];
    return bar ? bar.childNodes.map((n) => n.getAttribute && n.getAttribute('data-key')).filter(Boolean) : [];
  };
  const at = (stage) => deck.card('c-1', { stage: stage, options: { tracker_ref: 'T-1' } });
  [true, false].forEach((desk) => {
    const where = desk ? 'desk' : 'phone';
    const building = rowKeys(desk, at('building'), rows(lacks)), shipping = rowKeys(desk, at('shipping'), rows(lacks));
    check('pane row, ' + where + ': the tracker line while building', building[0] === 'need-tracker');
    check('pane row, ' + where + ': no code host line before shipping', building.indexOf('need-codehost') < 0);
    check('pane row, ' + where + ': the code host line leads at shipping', shipping[0] === 'need-codehost');
    check('pane row, ' + where + ': the tracker line at shipping too', shipping.indexOf('need-tracker') > 0);
    const same = rowKeys(desk, at('shipping'), rows());
    check('pane row, ' + where + ': one reason for both is said once',
          same[0] === 'need-codehost' && same.indexOf('need-tracker') < 0);
    /* a blocked card draws no Ship and no code host line, so the tracker's stays (c-662 F4) */
    const blocked = rowKeys(desk, deck.card('c-1', { stage: 'shipping', blocked_reason: 'x', options: { tracker_ref: 'T-1' } }), rows());
    check('pane row, ' + where + ': a blocked shipping card keeps the tracker line',
          blocked.indexOf('need-tracker') >= 0 && blocked.indexOf('need-codehost') < 0);
    const set = [['spaces', 'personal', { tracker: ready('x'), codehost: ready('x') }]];
    check('pane row, ' + where + ': no line where both are set up',
          rowKeys(desk, at('shipping'), rows(set)).filter((k) => /^need-/.test(k)).length === 0);
  });
})();

/* Now: the install's own rows */
(function () {
  const K = page('now', rows([['install', 'voice', not('voice is installed but not answering', 'phone')]]));
  const b = body(K);
  check('now: a Not set up panel for voice', panels(b).length === 1 && b.textContent.indexOf('Voice is installed but not answering.') >= 0);
  check('now: the glance row says Reviews is not set up', b.textContent.indexOf('not set up') >= 0);
})();

/* c-729: voice has no step (its row names none), so the panel sends the user to Bosun: its
   page, and its session's attach command with Copy while that session can run */
(function () {
  const ATTACH = '/i/bin/keel console attach';
  const K = page('now', rows([['install', 'voice', not('voice is installed but not answering', null)]]), [],
                 { bosun: { attach: ATTACH }, console: null });
  const b = body(K), p = panels(b);
  const ask = p.length === 1 ? deck.all(p[0], (n) => n.nodeType === 1 && n.getAttribute('data-key') === 'needs-ask')[0] : null;
  check('now: voice asks Bosun how, with no link to a step that does not set it up: ' + JSON.stringify(links(b)),
    !!ask && ask.textContent.indexOf('Ask Bosun how to set up voice') >= 0 &&
    JSON.stringify(links(b)) === JSON.stringify(['/console']) && b.textContent.indexOf('Set it up') < 0);
  check('now: and gives its session\'s command with Copy', !!ask && deck.all(ask, (n) => n.tagName === 'CODE' && n.textContent === ATTACH).length === 1 &&
    deck.labels(ask).indexOf('Copy') >= 0);
})();

/* An older server sends no readiness: nothing is drawn */
(function () {
  const K = page('reviews', null);
  check('no readiness: no panel', panels(body(K)).length === 0);
  K.App.view = 'cards';
  check('no readiness: no panel on Cards', panels(body(K)).length === 0);
  K.renderDock();
  check('no readiness: the dock is five', deck.byClass(K._doc.getElementById('dock'), 'dock-item').length === 5);
})();

process.stdout.write(JSON.stringify(fails.length ? { fails } : { ok: true }));
