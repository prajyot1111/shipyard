/* The find bar as the pages draw it (app/ui.find.js), under node against the deck's DOM
 * stand-in: Cards on the desk and the phone, and the board list.
 *
 * Usage: node find-ui.js <path to app/>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const MODULES = ['ui.core.js', 'ui.findcore.js', 'ui.findpages.js', 'ui.find.js', 'ui.tips.js', 'ui.modal.js',
                 'ui.cards.js', 'ui.tree.js', 'ui.views.js', 'ui.board.js', 'ui.boardlist.js', 'ui.boarddelete.js'];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }
const ev = { stopPropagation() {}, preventDefault() {} };

function memory() {
  const m = {};
  return { getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); }, removeItem: (k) => { delete m[k]; }, m };
}
function page(cards, opts) {
  opts = opts || {};
  const K = deck.load(APP, MODULES, Object.assign({ storage: memory() }, opts));
  K.App.data = deck.state(cards, opts.extra);
  K.App.space = 'personal';
  K.render = K.renderBody = function () {};
  K.App.view = 'now';
  K.go('cards');
  return K;
}
const byKey = (root, key) => deck.all(root, (n) => n.getAttribute && n.getAttribute('data-key') === key);
const findBar = (root) => deck.byClass(root, 'find')[0];
const btnLabels = (root) => deck.byClass(findBar(root), 'find-btn').map((b) => deck.byClass(b, 'find-lbl')[0].textContent);
function listed(root) {
  return deck.all(root, (n) => (deck.hasClass(n, 'compact') || deck.hasClass(n, 'card')) && n.getAttribute('data-key'))
    .map((n) => n.getAttribute('data-key'));
}
function openPanel(K) { K.find.open('cards', 'filter'); return deck.wrap(K.viewCards(), K); }
function row(root, key) { return byKey(root, key).filter((n) => deck.hasClass(n, 'find-row'))[0]; }

const cards = [
  deck.card('c-1', { stage: 'inbox', topic: 'home', repo: 'keel' }),
  deck.card('c-2', { stage: 'building', repo: 'api', topic: 'voice', created_at: '2026-09-21T10:00:00+00:00' }),
  deck.card('c-3', { stage: 'review', repo: 'api', derived: { needs_you: true, outcome_gate: true } }),
  deck.card('c-4', { stage: 'done', repo: 'keel' }),
  deck.card('c-5', { stage: 'review', repo: 'keel', derived: { archived: true } }),
  deck.card('c-6', { stage: 'review', repo: 'keel', derived: { backlog: true, outcome_gate: true } }),
  deck.card('c-7', { stage: 'building', repo: null, blocked_reason: 'which key?', derived: { needs_you: true, kind: 'errand' } }),
];

/* ---------- desk: the bar, and the old controls gone ---------- */
(function () {
  const K = page(cards, { desk: true });
  const body = deck.wrap(K.viewCards(), K);
  check('desk: one find bar on Cards', deck.byClass(body, 'find').length === 1);
  check('desk: the buttons carry short fixed labels', JSON.stringify(btnLabels(body)) === '["Views","Filter","Sort","View"]');
  check('desk: the old chips, the topic select and the group chips are gone',
        deck.byClass(body, 'fchip').length === 0 && deck.byClass(body, 'lanechip').length === 0 &&
        deck.all(body, (n) => n.tagName === 'SELECT').length === 0 && body.textContent.indexOf('group by') < 0);
  check('desk: done, archived and backlog are out of the list', JSON.stringify(listed(body).sort()) === '["c-1","c-2","c-3","c-7"]');
  check('desk: the quiet line says the sort', deck.byClass(body, 'find-now')[0].textContent === 'Queue order');
  const search = deck.all(body, (n) => n.tagName === 'INPUT' && n.getAttribute('role') === 'combobox')[0];
  check('desk: the search is a combobox over a listbox', !!search && search.getAttribute('aria-controls') === 'find-cards-sug');
  const filter = deck.byClass(body, 'find-btn').filter((b) => b.getAttribute('aria-haspopup') === 'dialog')[0];
  check('desk: Filter says it opens a dialog and is closed', !!filter && filter.getAttribute('aria-expanded') === 'false');
})();

/* ---------- the panel: multi-select with counts, zero dimmed, include adds ---------- */
(function () {
  const K = page(cards, { desk: true });
  let body = openPanel(K);
  const panel = deck.byClass(body, 'find-panel')[0];
  check('panel: the desk draws a dropdown dialog', !!panel && panel.getAttribute('role') === 'dialog');
  const heads = deck.byClass(panel, 'find-sechead').map((n) => n.textContent);
  check('panel: the facets and Include, in the table\'s order', JSON.stringify(heads) === '["Stage","Needs","Repo","Topic","Kind","Include"]');
  const review = row(panel, 'v-review');
  check('panel: a value carries its count', /1$/.test(review.textContent) && review.getAttribute('role') === 'checkbox');
  check('panel: a value with nothing is dimmed, not hidden', deck.hasClass(row(panel, 'v-shipping'), 'zero'));
  review.onclick(ev);
  row(openPanel(K), 'v-building').onclick(ev);
  body = openPanel(K);
  check('multi-select: two stages are either one', JSON.stringify(listed(body).sort()) === '["c-2","c-3","c-7"]');
  check('multi-select: the facet\'s own values keep their counts', /1$/.test(row(body, 'v-inbox').textContent));
  check('multi-select: the Filter button counts the values on', deck.byClass(body, 'find-n')[0].textContent === '2');
  check('url: the filter is in the URL, in the grammar', /f=stage%3Areview%2Cbuilding/.test(K._win.location.search));
  const toks = deck.byClass(body, 'find-token').map((n) => n.getAttribute('title'));
  check('tokens: one token per facet, naming its values', JSON.stringify(toks) === '["Stage: Review, Building"]');
  row(body, 'i-archived').onclick(ev);
  body = openPanel(K);
  check('include ADDS: archived joins the list', JSON.stringify(listed(body).sort()) === '["c-2","c-3","c-5","c-7"]');
  check('include: the switch is a switch, on', row(body, 'i-archived').getAttribute('aria-checked') === 'true');
  const show = deck.byClass(body, 'find-show')[0];
  check('panel: Show N counts what the list holds', show.textContent === 'Show 4 cards');
  deck.byClass(body, 'find-clear')[0].onclick(ev);
  body = deck.wrap(K.viewCards(), K);
  check('Clear takes every filter off', listed(body).length === 4 && deck.byClass(body, 'find-token').length === 0);
})();

/* ---------- typed filters ---------- */
(function () {
  const K = page(cards, { desk: true });
  let body = deck.wrap(K.viewCards(), K);
  const input = deck.all(body, (n) => n.getAttribute && n.getAttribute('role') === 'combobox')[0];
  const target = { value: 'repo:api stage:review ' };
  input.oninput({ target });
  body = deck.wrap(K.viewCards(), K);
  check('typed: finished filters leave the field', target.value === '');
  check('typed: and apply', JSON.stringify(listed(body)) === '["c-3"]');
  check('typed: as tokens', deck.byClass(body, 'find-token').length === 2);
  input.oninput({ target: { value: 'sta' } });
  body = deck.wrap(K.viewCards(), K);
  const opts = deck.all(body, (n) => n.getAttribute && n.getAttribute('role') === 'option');
  check('typed: the suggestion list offers the field then its values with counts',
        opts.length > 2 && /stage:/.test(opts[0].textContent) && opts.slice(1).every((o) => /stage:\w+\d+$/.test(o.textContent)));
  input.oninput({ target: { value: 'stage:bui' } });
  body = deck.wrap(K.viewCards(), K);
  check('typed: a half-typed filter does not empty the list', listed(body).length === 1);
  const pick = deck.all(body, (n) => n.getAttribute && n.getAttribute('role') === 'option')[0];
  check('typed: after the colon, the values it starts', !!pick && /stage:building/.test(pick.textContent));
  pick.onmousedown(ev);
  body = deck.wrap(K.viewCards(), K);
  check('typed: taking a suggestion applies it', JSON.stringify(listed(body).sort()) === '["c-2","c-3"]' &&
        /Stage: Review, Building/.test(deck.byClass(body, 'find-token').map((n) => n.getAttribute('title')).join()));
})();

/* ---------- sort, views, the View menu ---------- */
(function () {
  const K = page(cards, { desk: true });
  K.find.open('cards', 'sort');
  let body = deck.wrap(K.viewCards(), K);
  const items = deck.all(body, (n) => n.getAttribute && n.getAttribute('role') === 'menuitemradio');
  check('sort: a menu of the page\'s sorts, the current one ticked',
        items.map((n) => n.getAttribute('title')).join('|') === 'Queue order|Recently updated|Newest created|Oldest created|Stage' &&
        items[0].getAttribute('aria-checked') === 'true');
  items[2].onclick(ev);
  body = deck.wrap(K.viewCards(), K);
  check('sort: newest created puts c-2 first', listed(body)[0] === 'c-2');
  check('sort: the quiet line says it', deck.byClass(body, 'find-now')[0].textContent === 'Newest created');

  K.find.open('cards', 'views');
  body = deck.wrap(K.viewCards(), K);
  const needs = deck.all(body, (n) => n.getAttribute && n.getAttribute('title') === 'Needs me')[0];
  needs.onclick(ev);
  body = deck.wrap(K.viewCards(), K);
  check('views: Needs me shows what waits on him', JSON.stringify(listed(body).sort()) === '["c-3","c-7"]');
  check('views: the quiet line names the view and the sort', deck.byClass(body, 'find-now')[0].textContent === 'Needs me · Queue order');
  K.find.open('cards', 'views');
  body = deck.wrap(K.viewCards(), K);
  deck.byClass(body, 'find-save')[0].onclick(ev);
  body = deck.wrap(K.viewCards(), K);
  const form = deck.byClass(body, 'find-saveform')[0];
  deck.all(form, (n) => n.tagName === 'INPUT')[0].oninput({ target: { value: 'Mine' } });
  form.onsubmit(ev);
  K.find.open('cards', 'views');
  body = deck.wrap(K.viewCards(), K);
  const del = deck.byClass(body, 'find-del');
  check('views: his view is listed with a delete', del.length === 1 && del[0].getAttribute('aria-label') === 'Delete view Mine');
  del[0].onclick(ev);
  body = deck.wrap(K.viewCards(), K);
  check('views: and deleting it removes it', deck.byClass(body, 'find-del').length === 0);

  K.find.open('cards', 'view');
  body = deck.wrap(K.viewCards(), K);
  let secs = deck.byClass(body, 'find-sec').map((n) => n.getAttribute('aria-label'));
  check('view: the desk table offers the layout and the grouping', JSON.stringify(secs) === '["Layout","Group by"]');
  const kanban = deck.all(body, (n) => n.getAttribute && n.getAttribute('title') === 'Kanban')[0];
  kanban.onclick(ev);
  K.find.open('cards', 'view');
  body = deck.wrap(K.viewCards(), K);
  secs = deck.byClass(body, 'find-sec').map((n) => n.getAttribute('aria-label'));
  check('view: kanban offers no grouping, it IS the grouping', JSON.stringify(secs) === '["Layout"]');
  check('view: kanban draws the lanes', deck.byClass(body, 'lane').length === 7);
  check('url: the layout is in the URL', /layout=kanban/.test(K._win.location.search));
})();

/* ---------- the phone: two rows, grouped by stage, a sheet ---------- */
(function () {
  const K = page(cards, { desk: false });
  let body = deck.wrap(K.viewCards(), K);
  check('phone: the same four buttons', JSON.stringify(btnLabels(body)) === '["Views","Filter","Sort","View"]');
  check('phone: grouped by stage with counts',
        deck.byClass(body, 'fgroup-head').map((n) => n.textContent).join('|') === 'inbox1|building2|review1');
  K.find.open('cards', 'view');
  body = deck.wrap(K.viewCards(), K);
  const titles = deck.all(body, (n) => n.getAttribute && n.getAttribute('role') === 'menuitemradio').map((n) => n.getAttribute('title'));
  check('phone: no kanban, and the grouping is offered', titles.indexOf('Kanban') < 0 && titles.indexOf('Topic') >= 0);
  K.find.close(false);
  body = openPanel(K);
  const sheet = deck.byClass(body, 'find-sheet')[0];
  check('phone: Filter is a modal bottom sheet', !!sheet && sheet.getAttribute('aria-modal') === 'true');
  check('phone: the sheet has its Clear and Show N foot', deck.byClass(sheet, 'find-clear').length === 1 && deck.byClass(sheet, 'find-show').length === 1);
  check('phone: no desk dropdown', deck.byClass(body, 'find-panel').length === 0);
})();

/* ---------- remembered per page, and the URL wins ---------- */
(function () {
  const storage = memory();
  let K = page(cards, { desk: true, storage });
  K.find.toggleValue('cards', 'repo', 'api');
  K = page(cards, { desk: true, storage });
  check('memory: a new visit comes back to the same filters', JSON.stringify(listed(deck.wrap(K.viewCards(), K)).sort()) === '["c-2","c-3"]');
  K._win.location.search = '?view=cards&sort=queue';
  K.readRoute();
  K.App.space = 'personal';
  check('url: a URL that says a state wins over the memory', listed(deck.wrap(K.viewCards(), K)).length === 4);
})();

/* ---------- the board list: the global space, All spaces, Include deleted adds ---------- */
async function boards() {
  const board = (id, space, extra) => Object.assign({ id, title: id + ' title', updated: '2026-09-23T10:00:00+00:00',
    created: '2026-09-20T10:00:00+00:00', live: false, closed: null, nodes: 1, attachments: 0, topic: id,
    source: space ? { kind: 'card', card: 'c-' + id.slice(2) } : { kind: 'talker', card: null },
    card: space ? { title: 'card ' + id, space, story: '' } : null }, extra || {});
  const rows = [board('b-1', 'personal'), board('b-2', 'work'), board('b-3', null, { title: 'Harbor board' }),
                board('b-4', 'personal', { closed: '2026-09-22', updated: '2026-08-01T10:00:00+00:00' }),
                /* lane FC, FC-4: a review card's board, off the list until it is included */
                board('b-5', 'personal', { title: 'Review path', card: { title: 'Review: x', space: 'personal', story: '', review: true } }),
                /* c-562: a done or archived card's boards, off the list until Include done */
                board('b-6', 'personal', { title: 'Finished work', card: { title: 'Shipped', space: 'personal', story: '', done: true } }),
                board('b-7', 'work', { title: 'Finished elsewhere', card: { title: 'Work shipped', space: 'work', story: '', done: true } })];
  const trash = [board('b-9', 'personal', { deleted: { by: 'human', at: '2026-09-23T09:00:00+00:00' } })];
  const fetch = (url) => Promise.resolve({ json: () => (/deleted=1/.test(url) ? { rows: trash } : { rows }) });
  const K = deck.load(APP, MODULES, { desk: true, storage: memory(), fetch });
  K.App.data = deck.state([]);
  K.App.space = 'personal';
  K.render = K.renderBody = function () {};
  K.App.view = 'now';
  K.go('board');
  K.boardState.list = rows;
  const ids = (root) => deck.byClass(root, 'bsaved-item').map((n) => (deck.byClass(n, 't')[0] || n).textContent);
  let body = deck.wrap(K.viewBoard(), K);
  check('boards: the list has the find bar, and no View button (it has no modes)',
        JSON.stringify(btnLabels(body)) === '["Views","Filter","Sort"]');
  check('boards: the old chip strip is gone', deck.byClass(body, 'blist-chips').length === 0 && deck.byClass(body, 'lanechip').length === 0);
  check('boards: the global space applies: the work board is hidden, Harbor\'s is not',
        JSON.stringify(ids(body).sort()) === '["Harbor board","b-1 title","b-4 title"]');
  check('boards: Live and Saved stay a page tab, and it says Saved on the saved list',
        deck.byClass(body, 'bswitch').length === 1 &&
        deck.byClass(deck.byClass(body, 'bswitch')[0], 'on').map((n) => n.getAttribute('data-key')).join() === 'saved');
  check('boards: a review board is off the list, its search and its stacks', ids(body).indexOf('Review path') < 0
        && body.textContent.indexOf('Review: x') < 0);
  K.find.toggleInc('boards', 'review');
  body = deck.wrap(K.viewBoard(), K);
  check('boards: Include review boards brings it back', ids(body).indexOf('Review path') >= 0);
  K.find.toggleInc('boards', 'review');
  const sectionsOf = (root) => deck.all(root, (n) => deck.hasClass(n, 'bsaved-section')).map((n) => n.getAttribute('data-key'));
  check('boards: a done card\'s board is off the list by default', ids(body).indexOf('Finished work') < 0
        && sectionsOf(body).indexOf('Done') < 0);
  K.find.toggleInc('boards', 'done');
  body = deck.wrap(K.viewBoard(), K);
  check('boards: Include done ADDS its boards under a Done heading, after Harbor',
        JSON.stringify(sectionsOf(body)) === '["Houses","Harbor","Done"]' && ids(body).indexOf('Finished work') >= 0);
  check('boards: Include done keeps the other space out until All spaces', ids(body).indexOf('Finished elsewhere') < 0);
  K.find.toggleInc('boards', 'done');
  K.find.toggleInc('boards', 'allspaces');
  body = deck.wrap(K.viewBoard(), K);
  check('boards: All spaces brings the other space back', ids(body).indexOf('b-2 title') >= 0);
  check('boards: All spaces alone does not bring a done board back', ids(body).indexOf('Finished elsewhere') < 0
        && ids(body).indexOf('Finished work') < 0);
  check('boards: the bar counts what is drawn, with a done board of the other space hidden',
        K.find.run('boards', rows).total === ids(body).length);
  K.find.toggleInc('boards', 'done');
  body = deck.wrap(K.viewBoard(), K);
  const doneSection = deck.all(body, (n) => deck.hasClass(n, 'bsaved-section') && n.getAttribute('data-key') === 'Done')[0];
  check('boards: All spaces and Include done together bring the other space\'s done board, under Done',
        !!doneSection && JSON.stringify(ids(doneSection).sort()) === '["Finished elsewhere","Finished work"]'
        && K.find.run('boards', rows).total === ids(body).length);
  K.find.toggleInc('boards', 'done');
  K.find.toggleValue('boards', 'state', 'closed');
  body = deck.wrap(K.viewBoard(), K);
  check('boards: State closed keeps the closed boards', JSON.stringify(ids(body)) === '["b-4 title"]');
  K.find.clearAll('boards');
  K.find.toggleInc('boards', 'deleted');
  deck.wrap(K.viewBoard(), K);
  await new Promise((r) => setImmediate(r));
  body = deck.wrap(K.viewBoard(), K);
  const sections = deck.all(body, (n) => deck.hasClass(n, 'bsaved-section')).map((n) => n.getAttribute('data-key'));
  check('boards: Include deleted ADDS the trash under its own heading', JSON.stringify(sections) === '["Houses","Harbor","Deleted"]');
  check('boards: a deleted row offers Restore', body.textContent.indexOf('Restore') >= 0 && body.textContent.indexOf('b-9 title') >= 0);
  K.find.toggleValue('boards', 'source', 'harbor');
  body = deck.wrap(K.viewBoard(), K);
  check('boards: the facets filter the trash too', body.textContent.indexOf('b-9 title') < 0 && ids(body).indexOf('Harbor board') >= 0);
  K.find.open('boards', 'views');
  body = deck.wrap(K.viewBoard(), K);
  const views = deck.all(body, (n) => n.getAttribute && n.getAttribute('role') === 'menuitemradio').map((n) => n.getAttribute('title'));
  check('boards: the built-in views', JSON.stringify(views) === '["Mine this week","From houses","From Harbor","Review boards"]');
  check('boards: the URL is the board route\'s own path', K._win.location.pathname === '/board');
}

/* ---------- Reviews: the review cards through the bar ---------- */
const rc = (id, state, author, created, extra) => deck.card(id, Object.assign({ space: 'work', repo: 'api',
  stage: { waiting: 'inbox', reviewing: 'building', gate: 'review', posted: 'done', 'new': 'done', closed: 'done' }[state],
  title: 'Review ' + id, updated_at: created,
  options: { review_key: 'api:' + id, kind: 'review', pr: 1, review_pr: { author, created, updated: created, activity: created } },
  derived: { review: state } }, extra || {}));
const reviewList = [rc('c-801', 'waiting', 'A. Mehta', '2026-09-24T08:00:00+00:00'),
                    rc('c-802', 'gate', 'R. Iyer', '2026-09-22T08:00:00+00:00'),
                    rc('c-803', 'new', 'A. Mehta', '2026-09-10T08:00:00+00:00', { derived: { review: 'new', review_severity: 'high' } }),
                    rc('c-804', 'waiting', 'R. Iyer', '2026-08-01T08:00:00+00:00', { derived: { review: 'waiting', backlog: true } }),
                    rc('c-805', 'posted', 'A. Mehta', '2026-09-20T08:00:00+00:00', { derived: { review: 'posted', archived: true } }),
                    deck.card('c-806', { space: 'work', repo: 'api', title: 'not a review card' }),
                    rc('c-807', 'reviewing', 'A. Mehta', '2026-09-23T08:00:00+00:00'),
                    rc('c-808', 'closed', 'R. Iyer', '2026-09-21T08:00:00+00:00', { options: { review_key: 'api:c-808', kind: 'review', pr: 1,
                       review_posted: { head: 'h1' }, review_closed: 'merged', review_pr: { author: 'R. Iyer', created: '2026-09-21T08:00:00+00:00' } } }),
                    rc('c-809', 'posted', 'R. Iyer', '2026-09-19T08:00:00+00:00')];
function reviewsPage(opts) {
  const K = deck.load(APP, MODULES.concat(['ui.reviews.js']), Object.assign({ desk: true, storage: memory() }, opts || {}));
  K.App.data = deck.state(reviewList, { spaces: {
    personal: { adapter: null, repos: [], options: [], verbs: { card: [] }, topics: [], counts: {}, terms: deck.TERMS.personal },
    work: { adapter: 'work', repos: ['api'], options: [], verbs: { card: [] }, topics: [], counts: {}, terms: deck.TERMS.work } },
    providers: { work: { reviews: { route: 'reviews', settings: { auto_review: false, review_model: 'sonnet' } } } } });
  K.App.space = 'work';
  K.render = K.renderBody = function () {};
  K.App.view = 'now';
  K.go('reviews');
  return K;
}
const reviewRows = (v) => deck.all(v, (n) => deck.hasClass(n, 'row') && /^c-8/.test(n.getAttribute('data-key') || '')).map((n) => n.getAttribute('data-key'));
function reviews() {
  const K = reviewsPage();
  const rows = reviewRows;
  let view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews: the find bar, with its View button on the desk', JSON.stringify(btnLabels(view)) === '["Views","Filter","Sort","View"]');
  check('reviews: newest raised first, the backlog, the closed and the dismissed out', rows(view).join() === 'c-801,c-807,c-802,c-809,c-803');
  check('reviews: the gear stays at the title', deck.all(view, (n) => n.getAttribute && n.getAttribute('data-key') === 'review-gear').length === 1);
  {
    /* his Scan now (2026-09-25): only where the adapter offers the verb; its tip says when
       the fetcher last looked, and a scan already asked is shown and not asked twice */
    const scanBtn = (v) => deck.all(v, (n) => n.getAttribute && n.getAttribute('data-key') === 'review-scan')[0];
    check('reviews: no Scan now without the verb', !scanBtn(view));
    const settings = K.App.data.providers.work.reviews.settings;
    settings.verbs = [{ verb: 'scan_now', label: 'Scan now', to: null }];
    settings.last_scan = new Date(Date.now() - 4 * 60000).toISOString();
    let b = scanBtn(deck.wrap(K.viewRoute('reviews'), K));
    check('reviews: Scan now at the title, saying when it last looked',
          !!b && b.textContent === 'Scan now' && /last scanned /.test(b.getAttribute('title')) && b.getAttribute('disabled') === null);
    settings.scan_asked = true;
    b = scanBtn(deck.wrap(K.viewRoute('reviews'), K));
    check('reviews: a scan already asked reads Scanning and cannot be asked again', b.textContent === 'Scanning' && b.getAttribute('disabled') !== null);
    delete settings.verbs; delete settings.last_scan; delete settings.scan_asked;
  }
  K.find.toggleValue('reviews', 'author', 'A. Mehta');
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews: Author filters', rows(view).join() === 'c-801,c-807,c-803');
  K.find.toggleInc('reviews', 'dismissed');
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews: Include dismissed ADDS the dismissed card', rows(view).join() === 'c-801,c-807,c-805,c-803');
  K.find.clearAll('reviews');
  K.find.toggleInc('reviews', 'closed');
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews: Include closed ADDS the closed card', rows(view).indexOf('c-808') >= 0);
  K.find.clearAll('reviews');
  K.find.toggleValue('reviews', 'severity', 'high');
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews: Highest finding filters', rows(view).join() === 'c-803');
  K.find.clearAll('reviews');
  K.find.open('reviews', 'views');
  view = deck.wrap(K.viewRoute('reviews'), K);
  deck.all(view, (n) => n.getAttribute && n.getAttribute('title') === 'Held')[0].onclick(ev);
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews: the Held view shows the quiet review cards', rows(view).join() === 'c-804');
  K.find.clearAll('reviews');
  K.find.open('reviews', 'views');
  view = deck.wrap(K.viewRoute('reviews'), K);
  deck.all(view, (n) => n.getAttribute && n.getAttribute('title') === 'New commits')[0].onclick(ev);
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews: the New commits view', rows(view).join() === 'c-803');
  K.find.clearAll('reviews');
  K.find.toggleValue('reviews', 'state', 'posted');
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews: State Posted holds the new commits too', rows(view).join() === 'c-809,c-803');
  const chips = deck.byClass(view, 'spill').map((n) => n.textContent);
  check('reviews: a row says its column, and new commits as a badge', chips.indexOf('Posted') >= 0 && chips.indexOf('new commits') >= 0);
  K.find.clearAll('reviews');
  K.find.open('reviews', 'sort');
  view = deck.wrap(K.viewRoute('reviews'), K);
  deck.all(view, (n) => n.getAttribute && n.getAttribute('title') === 'Oldest raised')[0].onclick(ev);
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews: Oldest raised', rows(view).join() === 'c-803,c-809,c-802,c-807,c-801');
  check('reviews: the URL says it', /sort=oldest/.test(K._win.location.search) && /view=reviews/.test(K._win.location.search));
}
try { reviews(); } catch (e) { fails.push('reviews threw: ' + e.message); }

/* ---------- Reviews: the kanban, back (2026-09-24) ---------- */
function reviewsKanban() {
  const storage = memory();
  let K = reviewsPage({ storage });
  const lanes = (v) => deck.byClass(v, 'lane').map((n) => n.getAttribute('data-key'));
  const laneIds = (v, key) => {
    const lane = deck.byClass(v, 'lane').filter((n) => n.getAttribute('data-key') === key)[0];
    return lane ? deck.byClass(lane, 'tile').map((n) => n.getAttribute('data-key')) : null;
  };
  K.find.open('reviews', 'view');
  let view = deck.wrap(K.viewRoute('reviews'), K);
  const secs = deck.byClass(view, 'find-sec').map((n) => n.getAttribute('aria-label'));
  const titles = deck.all(view, (n) => n.getAttribute && n.getAttribute('role') === 'menuitemradio').map((n) => n.getAttribute('title'));
  check('reviews kanban: View offers the layout, List or Kanban', JSON.stringify(secs) === '["Layout"]' &&
        JSON.stringify(titles) === '["List","Kanban"]');
  deck.all(view, (n) => n.getAttribute && n.getAttribute('title') === 'Kanban')[0].onclick(ev);
  K.find.close(false);
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews kanban: the old board\'s columns, in its order, Held always',
        JSON.stringify(lanes(view)) === '["detected","assigned","inbox","held","posted"]');
  check('reviews kanban: the columns carry the old names',
        deck.byClass(view, 'lane-head').map((n) => deck.byClass(n, 'lbl10')[0].textContent).join('|') ===
        'Detected|Assigned|Inbox|Held|Posted');
  check('reviews kanban: each column says what it means', deck.byClass(view, 'lane-said').length === 5 &&
        deck.byClass(view, 'lane-said')[2].textContent.indexOf('Approve') >= 0);
  check('reviews kanban: each card in its column', JSON.stringify(laneIds(view, 'detected')) === '["c-801"]' &&
        JSON.stringify(laneIds(view, 'assigned')) === '["c-807"]' && JSON.stringify(laneIds(view, 'inbox')) === '["c-802"]' &&
        JSON.stringify(laneIds(view, 'held')) === '["c-804"]' && JSON.stringify(laneIds(view, 'posted')) === '["c-809","c-803"]');
  const fresh = deck.all(view, (n) => deck.hasClass(n, 'tile') && n.getAttribute('data-key') === 'c-803')[0];
  check('reviews kanban: a posted card with new commits says so on its tile', !!fresh && fresh.textContent.indexOf('new commits') >= 0);
  check('reviews kanban: no list rows', reviewRows(view).length === 0);
  check('url: the review layout is in the URL', /layout=kanban/.test(K._win.location.search));
  K.find.toggleValue('reviews', 'author', 'R. Iyer');
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews kanban: a filter applies within the columns', JSON.stringify(laneIds(view, 'posted')) === '["c-809"]' &&
        JSON.stringify(laneIds(view, 'detected')) === '[]' && JSON.stringify(laneIds(view, 'inbox')) === '["c-802"]' &&
        JSON.stringify(laneIds(view, 'held')) === '["c-804"]');
  K.find.clearAll('reviews');
  K.find.toggleValue('reviews', 'state', 'posted');
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews kanban: a column its filter empties is still drawn', JSON.stringify(laneIds(view, 'inbox')) === '[]' &&
        JSON.stringify(laneIds(view, 'held')) === '[]');
  K.find.clearAll('reviews');
  const more = reviewList.concat([rc('c-810', 'posted', 'A. Mehta', '2026-09-18T08:00:00+00:00')]);
  K.App.data.cards = more;
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews kanban: the sort applies within a column (newest raised first)', JSON.stringify(laneIds(view, 'posted')) === '["c-809","c-810","c-803"]');
  K.find.open('reviews', 'sort');
  view = deck.wrap(K.viewRoute('reviews'), K);
  deck.all(view, (n) => n.getAttribute && n.getAttribute('title') === 'Oldest raised')[0].onclick(ev);
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews kanban: and turns with it', JSON.stringify(laneIds(view, 'posted')) === '["c-803","c-810","c-809"]');
  K.App.data.cards = reviewList;
  K.find.clearAll('reviews');
  K.find.toggleInc('reviews', 'dismissed');
  K.find.toggleInc('reviews', 'closed');
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews kanban: Dismissed is a column only with Include dismissed',
        JSON.stringify(lanes(view)) === '["detected","assigned","inbox","held","posted","dismissed"]' &&
        JSON.stringify(laneIds(view, 'dismissed')) === '["c-805"]');
  const closed = deck.all(view, (n) => deck.hasClass(n, 'tile') && n.getAttribute('data-key') === 'c-808')[0];
  check('reviews kanban: Include closed puts a closed one in its column, saying closed',
        JSON.stringify(laneIds(view, 'posted')) === '["c-803","c-809","c-808"]' && closed.textContent.indexOf('closed') >= 0);
  K.App.card = 'c-802';
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews kanban: a tapped tile opens the card pane beside the lanes',
        deck.byClass(view, 'lane').length > 0 && deck.all(view, (n) => n.getAttribute && n.getAttribute('data-key') === 'row-detail').length === 1);
  K.App.card = null;
  /* remembered: a new visit comes back to the kanban */
  K = reviewsPage({ storage });
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews kanban: remembered per page', deck.byClass(view, 'lane').length >= 5);
  K._win.location.search = '?view=reviews&space=work&sort=raised&layout=list';
  K.readRoute();
  K.App.space = 'work';
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews kanban: a URL that says list wins over the memory', deck.byClass(view, 'lane').length === 0 && reviewRows(view).length > 0);
  /* the phone: a list whatever was chosen, and no View button */
  K = reviewsPage({ storage, desk: false });
  K._win.location.search = '?view=reviews&space=work&sort=raised&layout=kanban';
  K.readRoute();
  K.App.space = 'work';
  view = deck.wrap(K.viewRoute('reviews'), K);
  check('reviews kanban: the phone stays a list', deck.byClass(view, 'lane').length === 0 && reviewRows(view).length > 0);
  check('reviews kanban: the phone has no View button', JSON.stringify(btnLabels(view)) === '["Views","Filter","Sort"]');
}
try { reviewsKanban(); } catch (e) { fails.push('reviews kanban threw: ' + e.message); }

/* ---------- Cards never lists a review card (2026-09-24) ---------- */
function cardsWithoutReviews() {
  const mixed = cards.concat([
    rc('c-901', 'waiting', 'A. Mehta', '2026-09-24T08:00:00+00:00', { space: 'personal', repo: 'keel' }),
    rc('c-902', 'gate', 'A. Mehta', '2026-09-24T08:00:00+00:00', { space: 'personal', repo: 'keel',
       derived: { review: 'gate', needs_you: true, outcome_gate: true } }),
    rc('c-903', 'reviewing', 'A. Mehta', '2026-09-24T08:00:00+00:00', { space: 'personal', repo: 'keel' })]);
  for (const desk of [true, false]) {
    const K = page(mixed, { desk });
    const body = deck.wrap(K.viewCards(), K);
    const ids = listed(body);
    check('cards (' + (desk ? 'desk' : 'phone') + '): no review card is listed', ids.every((id) => !/^c-90/.test(id)) && ids.length > 0);
    check('cards (' + (desk ? 'desk' : 'phone') + '): the count leaves them out', body.textContent.indexOf('Cards · 4') >= 0);
    if (!desk) {
      check('cards (phone): the stage counts leave them out',
            deck.byClass(body, 'fgroup-head').map((n) => n.textContent).join('|') === 'inbox1|building2|review1');
    }
  }
  let K = page(mixed, { desk: true });
  K.find.toggleInc('cards', 'done');
  K.find.toggleInc('cards', 'archived');
  K.find.toggleInc('cards', 'backlog');
  K.find.open('cards', 'view');
  let body = deck.wrap(K.viewCards(), K);
  deck.all(body, (n) => n.getAttribute && n.getAttribute('title') === 'Kanban')[0].onclick(ev);
  K.find.close(false);
  body = deck.wrap(K.viewCards(), K);
  check('cards kanban: no review card in any lane, whatever is included',
        deck.byClass(body, 'tile').length > 0 && deck.byClass(body, 'tile').every((n) => !/^c-90/.test(n.getAttribute('data-key'))));
  K = page(mixed, { desk: true });
  body = openPanel(K);
  const inbox = row(body, 'v-inbox'), review = row(body, 'v-review');
  check('cards: the facet counts leave review cards out', /1$/.test(inbox.textContent) && /1$/.test(review.textContent));
  K.find.toggleValue('cards', 'kind', 'review');
  check('cards: kind:review finds nothing', listed(deck.wrap(K.viewCards(), K)).length === 0);
}
try { cardsWithoutReviews(); } catch (e) { fails.push('cards without reviews threw: ' + e.message); }


boards().catch((e) => fails.push('boards threw: ' + e.message)).then(() => {
  process.stdout.write(JSON.stringify(fails.length ? { ok: false, fails } : { ok: true }) + '\n');
});
