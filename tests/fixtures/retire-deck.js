/* Lane RETIRE (RT-1): the deck has no PRs page, and an old link to one lands on Cards with
 * the Shipping view of the find bar, under node against the deck's DOM stand-in.
 *
 * Usage: node retire-deck.js <path to app/>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const MODULES = ['ui.core.js', 'ui.findcore.js', 'ui.findpages.js', 'ui.find.js', 'ui.tips.js', 'ui.modal.js',
                 'ui.cards.js', 'ui.tree.js', 'ui.views.js', 'ui.reviews.js'];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

function memory(seed) {
  const m = Object.assign({}, seed || {});
  return { getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); }, removeItem: (k) => { delete m[k]; }, m };
}
const cards = [
  deck.card('c-1', { space: 'work', stage: 'shipping', repo: 'api',
                     options: { pr: 41, shipping: { facts: { state: 'open', comments: 2, approvals: 0, ci: 'passed', waiting: 0 } } } }),
  deck.card('c-2', { space: 'work', stage: 'building', repo: 'api' }),
];
/* A stale push from an older laptop could still carry the watcher's route: it must draw nothing. */
const stale = { providers: { work: { reviews: { route: 'reviews', settings: { auto_review: false, review_model: 'opus', models: ['opus', 'sonnet'] }, items: [] },
                                    prs: { route: 'prs', columns: ['open'], items: [{ repo: 'api', pr: 42, kanbanState: 'open' }] } } } };
function page(search, storage) {
  const K = deck.load(APP, MODULES, { desk: true, storage: storage || memory() });
  K.App.data = deck.state(cards, stale);
  K.App.data.spaces.work.adapter = 'work';
  K.render = K.renderBody = function () {};
  K._win.location.search = search;
  K.readRoute();
  return K;
}
const shipping = (K) => JSON.stringify(K.find.state('cards').f) === JSON.stringify({ stage: ['shipping'] });

(function () {
  const K = page('?view=now&space=work');
  check('rail: there is no PRs view to draw', !K.VIEWS.some((v) => v.key === 'prs' || v.name === 'PRs'));
  check('counts: nothing counts pull requests', !('prs' in K.counts()));
  const more = deck.wrap(K.viewMore(), K);
  check('more: no row counts watched pull requests', more.textContent.indexOf('watched') < 0
        && deck.all(more, (n) => n.getAttribute && n.getAttribute('data-key') === 'prs').length === 0);
})();

(function () {
  const K = page('?view=prs&space=work');
  check('link: ?view=prs lands on Cards', K.App.view === 'cards');
  check('link: with the Shipping view of the find bar', shipping(K));
  const q = K._win.location.search;
  check('link: the URL now says Cards and the Shipping filter', /view=cards/.test(q) && /f=stage%3Ashipping/.test(q) && !/view=prs/.test(q));
  check('link: the space it named is kept', K.App.space === 'work' && /space=work/.test(q));
  const body = deck.wrap(K.viewCards(), K);
  const listed = deck.all(body, (n) => (deck.hasClass(n, 'compact') || deck.hasClass(n, 'card')) && n.getAttribute('data-key'))
    .map((n) => n.getAttribute('data-key'));
  check('link: the shipping card is what Cards lists', JSON.stringify(listed) === '["c-1"]');
})();

(function () {
  const K = page('', memory({ 'keel.view': 'prs', 'keel.space': 'work' }));
  check('memory: a remembered PRs view lands on Cards with Shipping too', K.App.view === 'cards' && shipping(K));
})();

console.log(JSON.stringify(fails.length ? { ok: false, fails } : { ok: true }));
