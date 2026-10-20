/* Lane GRP, GR-5: the Reviews page's feature card and held card, rendered under node
 * against the deck's DOM stand-in and read back.
 *
 * Usage: node review-groups.js <path to app/>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 *
 * A feature card shows its members (repo and number, each opening its own pull request) on
 * the row, the Repo facet matches it for each of its repos, and a held card says its wait
 * line and offers "Review now anyway" in the Continue group, not Review. Every pull request
 * here is invented.
 */
'use strict';
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const MODULES = ['ui.core.js', 'ui.findcore.js', 'ui.findpages.js', 'ui.find.js', 'ui.tips.js', 'ui.modal.js',
                 'ui.cards.js', 'ui.tree.js', 'ui.reviews.js', 'ui.views.js'];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

function memory() {
  const m = {};
  return { getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); }, removeItem: (k) => { delete m[k]; } };
}
const MEMBERS = [
  { label: 'api#4150', repo: 'api', pr: 4150, url: 'https://example.invalid/api/pr/4150', author: 'A. Mehta' },
  { label: 'web#2200', repo: 'web', pr: 2200, url: 'https://example.invalid/web/pr/2200', author: 'R. Iyer' }];
const created = '2026-09-24T08:00:00+00:00';
const feature = deck.card('c-901', { space: 'work', repo: 'api,web', stage: 'inbox',
  title: 'Review: st-41001 · Tell the user which machines were refused',
  options: { review_key: 'feature:st-41001', kind: 'review', review_group: 'st-41001', review_members: MEMBERS,
             review_pr: { author: 'A. Mehta, R. Iyer', created, activity: created } },
  derived: { review: 'waiting' } });
const held = deck.card('c-902', { space: 'work', repo: 'web', stage: 'inbox', title: 'Review: Untick refused machines',
  options: { review_key: 'web:2210', kind: 'review', pr: 2210,
             review_wait: { story: 'st-41002', sibling_repo: 'api', since: created, hours: 48 },
             review_pr: { author: 'R. Iyer', created, activity: created } },
  derived: { review: 'held', review_wait: { story: 'st-41002', sibling_repo: 'api', since: created, hours: 48, hours_left: 31 } } });
const single = deck.card('c-903', { space: 'work', repo: 'api', stage: 'inbox', title: 'Review: Tidy the loader',
  options: { review_key: 'api:4160', kind: 'review', pr: 4160, review_pr: { author: 'A. Mehta', created, activity: created } },
  derived: { review: 'waiting' } });

const sent = [];
function capture(url, init) {
  if (init && init.body) sent.push(JSON.parse(init.body));
  return Promise.resolve({ status: 200, json: () => ({ ok: true, result: {} }) });
}
function page(desk) {
  const K = deck.load(APP, MODULES, { desk: desk, storage: memory(), fetch: capture });
  K.App.data = deck.state([feature, held, single], { spaces: {
    personal: { adapter: null, repos: [], options: [], verbs: { card: [] }, topics: [], counts: {}, terms: deck.TERMS.personal },
    work: { adapter: 'work', repos: ['api', 'web'], options: [], verbs: { card: [] }, topics: [], counts: {},
            terms: deck.TERMS.work } },
    providers: { work: { reviews: { route: 'reviews', settings: { auto_review: false, review_model: 'sonnet' } } } } });
  K.App.space = 'work';
  K.render = K.renderBody = function () {};
  K.App.view = 'now';
  K.opened = [];
  K.openLink = function (url) { K.opened.push(url); };
  K.go('reviews');
  return K;
}
const rows = (v) => deck.all(v, (n) => deck.hasClass(n, 'row') && /^c-9/.test(n.getAttribute('data-key') || ''))
  .map((n) => n.getAttribute('data-key'));
const byKey = (root, key) => deck.all(root, (n) => n.getAttribute && n.getAttribute('data-key') === key);
const ev = { stopPropagation() {}, preventDefault() {} };

for (const desk of [true, false]) {
  const where = desk ? 'desk' : 'phone';
  const K = page(desk);
  let view = deck.wrap(K.viewRoute('reviews'), K);
  const row = byKey(view, 'c-901')[0];
  check(where + ': the feature card is listed', !!row);
  const chips = row ? deck.all(row, (n) => deck.hasClass(n, 'member')) : [];
  check(where + ': the row names both members, repo and number',
        JSON.stringify(chips.map((c) => c.textContent)) === '["api #4150","web #2200"]');
  if (chips[1]) chips[1].onclick(ev);
  check(where + ': a member opens its own pull request', K.opened[0] === MEMBERS[1].url);
  const heldRow = byKey(view, 'c-902')[0];
  check(where + ': the held card says its wait line',
        !!heldRow && heldRow.textContent.indexOf('waiting for the api PR (st-41002 has a branch there), 31h left') >= 0);
  check(where + ': the held card reads held', !!heldRow && /held/i.test(heldRow.textContent));
  K.find.toggleValue('reviews', 'repo', 'web');
  view = deck.wrap(K.viewRoute('reviews'), K);
  check(where + ': the Repo facet matches the feature card for web', rows(view).sort().join() === 'c-901,c-902');
  K.find.clearAll('reviews');
  K.find.toggleValue('reviews', 'repo', 'api');
  view = deck.wrap(K.viewRoute('reviews'), K);
  check(where + ': and for api', rows(view).sort().join() === 'c-901,c-903');
  K.find.clearAll('reviews');
  K.find.toggleValue('reviews', 'state', 'held');
  view = deck.wrap(K.viewRoute('reviews'), K);
  check(where + ': the State facet finds the held card', rows(view).join() === 'c-902');
  K.find.clearAll('reviews');
}

/* the held card's actions: Review now anyway, in Continue, with its line; no Review tap */
(function () {
  const K = page(true);
  const items = K.cardItems(held).concat(K.gateActions(held));
  const keys = items.map((n) => n.getAttribute('data-key'));
  check('held: Review now anyway is offered', keys.indexOf('review-now') >= 0);
  check('held: the Review tap is not, the wait is ended one way', keys.indexOf('assign') < 0);
  const now = items[keys.indexOf('review-now')];
  check('held: it is in the Continue group', (K.groupOf('review-now') || {}).key === 'continue');
  check('held: it carries its line', !!now && /Review now anyway: /.test(now.getAttribute('title') || ''));
  const plain = K.cardItems(single).map((n) => n.getAttribute('data-key'));
  check('single: no Review now anyway, and the Review tap', plain.indexOf('review-now') < 0 && plain.indexOf('assign') >= 0);
  check('held: the outcome word is the wait', /waiting for the api PR/.test((K.outcomeWord(held) || {}).text || ''));
  if (now) {
    const btn = now.tagName === 'BUTTON' ? now : deck.all(now, (n) => n.tagName === 'BUTTON')[0];
    if (btn && btn.onclick) btn.onclick(ev);
  }
  const body = sent[sent.length - 1];
  check('held: the tap ends the wait and marks it alone', !!body && body.verb === 'set' && body.id === 'c-902' &&
        body.fields['options.review_wait'] === null && body.fields['options.review_alone'] === true);
})();

process.stdout.write(JSON.stringify(fails.length ? { ok: false, fails } : { ok: true }) + '\n');
