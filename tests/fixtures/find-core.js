/* The find system's pure half (app/ui.findcore.js), checked outside a browser.
 *
 * Usage: node find-core.js <path to app/>
 * Output: {"ok": true}, or a JSON object naming the checks that failed.
 *
 * The page tables (app/ui.findpages.js) are loaded too, so each page's own facets, sorts
 * and views are checked against the same engine the deck runs.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const app = process.argv[2];
const win = { Keel: {} };
for (const name of ['ui.findcore.js', 'ui.findpages.js']) {
  new Function('window', fs.readFileSync(path.join(app, name), 'utf8'))(win);
}
const K = win.Keel;
const F = K.findCore;
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/* ---------- a small page of its own, so the engine is read apart from any real page ---------- */
const items = [
  { id: 'a', stage: 'review', repo: 'api', words: 'rotate the backup key', done: false, n: 3 },
  { id: 'b', stage: 'building', repo: 'api', words: 'narrated walks', done: false, n: 1 },
  { id: 'c', stage: 'building', repo: 'keel', words: 'voice gateway', done: false, n: 2 },
  { id: 'd', stage: 'inbox', repo: 'keel,api', words: 'two repos', done: false, n: 5 },
  { id: 'e', stage: 'review', repo: 'keel', words: 'old one', done: true, n: 4 },
  { id: 'f', stage: 'inbox', repo: 'api', words: 'filed away', archived: true, n: 6 },
];
const spec = {
  page: 'test', noun: ['item', 'items'],
  facets: [
    { key: 'stage', label: 'Stage', values: () => ['inbox', 'building', 'review'].map((v) => ({ value: v, label: v })),
      match: (it, v) => it.stage === v },
    { key: 'repo', label: 'Repo', values: (list) => F.distinct(list, (it) => it.repo.split(',')),
      match: (it, v) => it.repo.split(',').indexOf(v) >= 0 },
    { key: 'topic', label: 'Topic', values: () => [{ value: 'big ideas', label: 'big ideas' }], match: () => false },
  ],
  include: [{ key: 'archived', label: 'Include archived' }, { key: 'done', label: 'Include done' }],
  hidden: (it) => it.archived ? 'archived' : it.done ? 'done' : null,
  text: (it) => it.id + ' ' + it.words,
  sorts: [{ key: 'order', label: 'Order', cmp: () => 0 },
          { key: 'n', label: 'By n', cmp: (a, b) => a.n - b.n }],
  modes: [],
  views: [{ key: 'build', label: 'Building', state: { f: { stage: ['building'] } } }],
};

/* ---------- the parser ---------- */
let p = F.parse('stage:review,building repo:api words', spec);
check('parser: a field with two values becomes one filter with both',
      same(p.f.stage, ['review', 'building']));
check('parser: a second field is its own filter', same(p.f.repo, ['api']));
check('parser: what is not a filter stays as the words', p.words === 'words');
p = F.parse('Stage:REVIEW hello there', spec);
check('parser: field and value are matched without case, to the value the page knows',
      same(p.f.stage, ['review']) && p.words === 'hello there');
p = F.parse('topic:"big ideas" http://x c-12: note:this', spec);
check('parser: a quoted value keeps its space', same(p.f.topic, ['big ideas']));
check('parser: an unknown field and a url are words, never filters',
      p.words === 'http://x c-12: note:this' && !p.f.note && !p.f.http);
p = F.parse('include:done,archived stage:', spec);
check('parser: include: takes the page\'s own include keys', same(p.inc, ['done', 'archived']));
check('parser: a field with no value yet is not a filter', !p.f.stage && p.words === 'stage:');
p = F.parse('stage:review stage:building', spec);
check('parser: the same field twice gathers its values', same(p.f.stage, ['review', 'building']));
p = F.parse('repo:newrepo', spec);
check('parser: a value the page does not list is kept as typed (it simply matches nothing)', same(p.f.repo, ['newrepo']));

/* absorbing: a filter is lifted out of the field once it is finished (a space after it) */
let a = F.absorb('stage:review rot', spec, false);
check('absorb: a finished filter leaves the field, the unfinished word stays',
      same(a.f.stage, ['review']) && a.text === 'rot');
a = F.absorb('rot stage:rev', spec, false);
check('absorb: the filter still being typed is left alone', a.text === 'rot stage:rev' && !a.f.stage);
a = F.absorb('rot stage:review', spec, true);
check('absorb: Enter finishes the last one too', same(a.f.stage, ['review']) && a.text === 'rot');

check('words: a filter still being typed does not filter the list as a word',
      F.wordsOf('rotate stage:rev', spec) === 'rotate' && F.wordsOf('rotate key', spec) === 'rotate key' &&
      F.wordsOf('http://x', spec) === 'http://x');

/* the grammar written back out, and read again */
const st = F.blank(spec);
st.f = { stage: ['review', 'building'], topic: ['big ideas'] };
check('format: filters are written in the grammar they are typed in',
      F.format(st.f, spec) === 'stage:review,building topic:"big ideas"');
check('format: what format writes, parse reads back', same(F.parse(F.format(st.f, spec), spec).f, st.f));

/* ---------- the URL ---------- */
function urlOf(pairs) {
  const m = {};
  pairs.forEach(([k, v]) => { m[k] = v; });
  return (k) => (k in m ? m[k] : null);
}
const full = { q: 'rotate key', f: { stage: ['review', 'building'], repo: ['api'] }, inc: ['done'], sort: 'n', mode: {} };
let pairs = F.toParams(full, spec);
let back = F.fromParams(urlOf(pairs), spec);
check('url: a state goes into the URL and comes back whole',
      back && back.q === full.q && same(back.f, full.f) && same(back.inc, full.inc) && back.sort === 'n');
pairs = F.toParams(F.blank(spec), spec);
check('url: even the default state writes its sort, so the URL always says which state it is',
      pairs.some(([k, v]) => k === 'sort' && v === 'order'));
check('url: a URL with no find parameters says nothing (the remembered state is used)',
      F.fromParams(urlOf([['view', 'cards']]), spec) === null);
back = F.fromParams(urlOf([['sort', 'bogus'], ['inc', 'done,nope']]), spec);
check('url: a sort or include the page does not have is dropped', back.sort === 'order' && same(back.inc, ['done']));

/* ---------- running: multi-select with counts, zero values, include adds ---------- */
let s = F.blank(spec);
let r = F.run(items, s, spec, {});
check('run: done and archived are out of the list until included', same(r.items.map((i) => i.id), ['a', 'b', 'c', 'd']));
check('run: a count is beside every value', r.counts.stage.review === 1 && r.counts.stage.building === 2 && r.counts.stage.inbox === 1);
check('run: a value in a comma list counts for each of its repos', r.counts.repo.keel === 2 && r.counts.repo.api === 3);
check('run: include counts say how many each switch would add', r.incCounts.done === 1 && r.incCounts.archived === 1);
s.f = { stage: ['review', 'building'] };
r = F.run(items, s, spec, {});
check('multi-select: two values of one facet are either one', same(r.items.map((i) => i.id), ['a', 'b', 'c']));
check('multi-select: a facet\'s own counts ignore its own choice', r.counts.stage.inbox === 1);
check('multi-select: another facet\'s counts follow this choice', r.counts.repo.api === 2 && r.counts.repo.keel === 1);
s.f.repo = ['keel'];
r = F.run(items, s, spec, {});
check('multi-select: two facets are both', same(r.items.map((i) => i.id), ['c']));
check('zero: a value that would give nothing is counted zero, not dropped',
      r.counts.stage.inbox === 1 && r.counts.stage.review === 0 && 'review' in r.counts.stage);
s = F.blank(spec); s.inc = ['archived'];
r = F.run(items, s, spec, {});
check('include ADDS: archived joins the list rather than replacing it',
      same(r.items.map((i) => i.id).sort(), ['a', 'b', 'c', 'd', 'f']));
s.inc = ['archived', 'done'];
check('include: both switches add both', F.run(items, s, spec, {}).items.length === 6);
/* c-562: an item hidden for several reasons needs every one on, and a switch counts only
   what it would add with the others as they are */
{
  const two = Object.assign({}, spec, { facets: [], include: [{ key: 'x', label: 'X' }, { key: 'y', label: 'Y' }], hidden: (i) => i.why || null });
  const list = [{ id: 'p' }, { id: 'q', why: 'x' }, { id: 'r', why: ['x', 'y'] }];
  let t = F.blank(two); t.inc = ['x'];
  let got = F.run(list, t, two, {});
  check('several reasons: one switch on is not enough', same(got.items.map((i) => i.id).sort(), ['p', 'q']));
  check('several reasons: a switch counts only what it would add alone',
        F.run(list, F.blank(two), two, {}).incCounts.x === 1 && got.incCounts.y === 1);
  t.inc = ['x', 'y'];
  check('several reasons: every one on shows it', F.run(list, t, two, {}).items.length === 3);
}
s = F.blank(spec); s.q = 'ROTATE key';
check('search: every word must be somewhere, without case', same(F.run(items, s, spec, {}).items.map((i) => i.id), ['a']));
s = F.blank(spec); s.sort = 'n';
check('sort: the chosen sort orders the list', same(F.run(items, s, spec, {}).items.map((i) => i.id), ['b', 'c', 'a', 'd']));
s.sort = 'order';
check('sort: a sort that ties keeps the list\'s own order', same(F.run(items, s, spec, {}).items.map((i) => i.id), ['a', 'b', 'c', 'd']));
check('count: active filters count values, not facets', F.active({ q: '', f: { stage: ['a', 'b'], repo: ['c'] }, inc: ['done'] }) === 4);

/* ---------- views: built-ins, his own, saved and deleted ---------- */
const mem = {};
const store = { get: (k) => (k in mem ? mem[k] : null), set: (k, v) => { mem[k] = v; } };
s = F.blank(spec); s.f = { stage: ['building'] };
check('views: the built-in whose state matches is the chosen one', (F.chosen(s, spec, store) || {}).key === 'build');
s.f.repo = ['keel'];
check('views: editing past a view un-chooses it', F.chosen(s, spec, store) === null);
const saved = F.saveView('test', 'Keel builds', s, store);
check('views: his own view is saved with his name for it', saved && F.ownViews('test', store).length === 1 &&
      F.ownViews('test', store)[0].label === 'Keel builds');
check('views: his own view is chosen when the state matches it', (F.chosen(s, spec, store) || {}).label === 'Keel builds');
const applied = F.applyView(F.blank(spec), F.ownViews('test', store)[0], spec);
check('views: applying his view brings its filters back', same(applied.f, { stage: ['building'], repo: ['keel'] }));
F.saveView('test', 'Keel builds', s, store);
check('views: saving under a name he already used replaces it', F.ownViews('test', store).length === 1);
F.deleteView('test', F.ownViews('test', store)[0].key, store);
check('views: his own view can be deleted', F.ownViews('test', store).length === 0);
check('views: a built-in cannot be deleted', F.deleteView('test', 'build', store) === false);
const broken = { get: () => { throw new Error('refused'); }, set: () => { throw new Error('refused'); } };
check('views: storage that refuses reads as no views and saves nothing, without throwing',
      same(F.ownViews('test', broken), []) && F.saveView('test', 'x', s, broken) === null);
mem['find.test.views'] = 'not json';
check('views: storage holding junk reads as no views', same(F.ownViews('test', store), []));

/* remembered per page */
F.remember('test', full, store);
const recalled = F.recall('test', spec, store);
check('memory: a page\'s state is remembered and read back', recalled && recalled.q === 'rotate key' && recalled.sort === 'n');
check('memory: storage that refuses reads as nothing remembered', F.recall('test', spec, broken) === null);

/* ---------- suggestions ---------- */
r = F.run(items, F.blank(spec), spec, {});
let sug = F.suggest('sta', spec, r);
check('suggest: the field comes first, then that field\'s values with counts',
      sug[0].kind === 'field' && sug[0].field === 'stage' &&
      sug.slice(1).every((x) => x.kind === 'value' && x.field === 'stage') &&
      sug.find((x) => x.value === 'building').count === 2);
sug = F.suggest('stage:b', spec, r);
check('suggest: after the colon, the values that start with what is typed',
      sug.length === 1 && sug[0].value === 'building' && sug[0].insert === 'stage:building');
sug = F.suggest('stage:review,b', spec, r);
check('suggest: after a comma, the next value joins the ones already typed', sug[0].insert === 'stage:review,building');
sug = F.suggest('ap', spec, r);
check('suggest: a word that starts a value offers that value under its field',
      sug.some((x) => x.field === 'repo' && x.value === 'api' && x.insert === 'repo:api'));
check('suggest: nothing typed offers nothing', F.suggest('', spec, r).length === 0);
sug = F.suggest('inc', spec, r);
check('suggest: include is a field too', sug[0].kind === 'field' && sug[0].field === 'include');

/* ---------- the modes: only what works in this layout is offered ---------- */
const modeSpec = { modes: [
  { key: 'layout', label: 'Layout', options: (st, ctx) => ctx.desk ? ['table', 'kanban'] : ['list'], fallback: (ctx) => ctx.desk ? 'table' : 'list' },
  { key: 'group', label: 'Group by', options: (st, ctx) => F.modeOf(st, modeSpec, ctx, 'layout') === 'kanban' ? [] : ['none', 'stage'],
    fallback: (ctx) => ctx.desk ? 'none' : 'stage' }] };
let ms = { mode: { layout: 'kanban', group: 'stage' } };
check('modes: a choice the layout cannot use falls back', F.modeOf(ms, modeSpec, { desk: false }, 'layout') === 'list' &&
      F.modeOf(ms, modeSpec, { desk: false }, 'group') === 'stage');
check('modes: kanban offers no grouping', F.modeOf(ms, modeSpec, { desk: true }, 'group') === null);

/* ---------- each page's own table ---------- */
const P = K.findPages;
const expect = {
  cards: { facets: ['stage', 'needs', 'repo', 'topic', 'kind'], include: ['done', 'backlog', 'archived'],
           sorts: ['queue', 'updated', 'newest', 'oldest', 'stage'],
           views: ['Needs me', 'In flight', 'Shipping', 'Backlog'] },
  boards: { facets: ['source', 'card', 'state', 'updated'], include: ['deleted', 'done', 'review', 'allspaces'],
            sorts: ['activity', 'newest', 'title'], views: ['Mine this week', 'From houses', 'From Harbor', 'Review boards'] },
  reviews: { facets: ['state', 'commits', 'author', 'repo', 'severity', 'raised'], include: ['backlog', 'closed', 'dismissed'],
             sorts: ['raised', 'oldest', 'activity'],
             views: ['Waiting for me', 'At my gate', 'New commits', 'Held'] },
};
Object.keys(expect).forEach((page) => {
  const t = P[page], e = expect[page];
  check(page + ': has its table', !!t);
  if (!t) return;
  check(page + ': facets', same(t.facets.map((f) => f.key), e.facets));
  check(page + ': include switches', same(t.include.map((f) => f.key), e.include));
  check(page + ': sorts, default first', same(t.sorts.map((f) => f.key), e.sorts));
  check(page + ': built-in views', same(t.views.map((f) => f.label), e.views));
  t.views.forEach((v) => check(page + ': view ' + v.key + ' names only real facets',
    Object.keys((v.state || {}).f || {}).every((k) => t.facets.some((f) => f.key === k))));
});
check('cards: the Stage facet offers shipping and not done',
      same(P.cards.facets[0].values([]).map((v) => v.value), ['inbox', 'assigned', 'planning', 'building', 'review', 'shipping']));
check('cards: the Include switches say the same words as every page',
      same(P.cards.include.map((i) => i.label), ['Include done', 'Include backlog', 'Include archived']) &&
      P.boards.include[0].label === 'Include deleted');
/* a review card is never on Cards (2026-09-24): Reviews is its only list */
check('cards: the Kind facet, with no Review', same(P.cards.facets[4].values([]).map((v) => v.value), ['house', 'errand', 'research', 'tracking']));
/* the old review board's six columns, the same names on the facet and the kanban (2026-09-24) */
check('reviews: the State facet is the board\'s columns',
      same(P.reviews.facets[0].values([]).map((v) => v.label), ['Detected', 'Assigned', 'Inbox', 'Held', 'Posted', 'Dismissed']));
check('reviews: Highest finding and Raised', same(P.reviews.facets[4].values([]).map((v) => v.value), ['critical', 'high', 'medium', 'low']) &&
      P.reviews.facets[4].label === 'Highest finding' && same(P.reviews.facets[5].values([]).map((v) => v.value), ['today', 'week', 'older']));
{
  const rc = (review, extra, options) => ({ options: Object.assign({ review_key: 'k' }, options || {}),
                                           derived: Object.assign({ review }, extra || {}) });
  const lane = P.reviews.laneOf;
  check('reviews: each card has one column', lane(rc('waiting')) === 'detected' && lane(rc('reviewing')) === 'assigned' &&
        lane(rc('gate')) === 'inbox' && lane(rc('posted')) === 'posted' && lane(rc('new')) === 'posted' &&
        lane(rc('waiting', { backlog: true })) === 'held' && lane(rc('posted', { archived: true })) === 'dismissed' &&
        lane(rc('closed', {}, { review_posted: { head: 'h' } })) === 'posted' && lane(rc('closed')) === 'detected');
  check('reviews: a card held for its other side is in Held', lane(rc('held')) === 'held');
  check('reviews: the facet matches the column', P.reviews.facets[0].match(rc('new'), 'posted') &&
        !P.reviews.facets[0].match(rc('new'), 'inbox'));
  check('reviews: every column says what it means', P.reviews.lanes.every((l) => l.said && l.said.length > 10));
}
check('reviews: Include says the same words', same(P.reviews.include.map((i) => i.label), ['Include backlog', 'Include closed', 'Include dismissed']));
check('reviews: the layout is List or Kanban on the desk, and a list on the phone',
      same(P.reviews.modes.map((m) => m.key), ['layout']) &&
      same(P.reviews.modes[0].options({}, { desk: true }).map((o) => o.key), ['list', 'kanban']) &&
      same(P.reviews.modes[0].options({}, { desk: false }).map((o) => o.key), ['list']) &&
      F.modeOf({ mode: { layout: 'kanban' } }, P.reviews, { desk: false }, 'layout') === 'list' &&
      F.modeOf({ mode: {} }, P.reviews, { desk: true }, 'layout') === 'list');
{
  const at = (review, extra) => Object.assign({ options: { review_key: 'k' }, derived: Object.assign({ review }, extra || {}) });
  check('reviews: hidden says which switch shows a card', P.reviews.hidden(at('closed')) === 'closed' &&
        P.reviews.hidden(at('closed', { archived: true })) === 'dismissed' && P.reviews.hidden(at('waiting', { backlog: true })) === 'backlog' &&
        P.reviews.hidden(at('posted')) === null);
}
check('boards: the Updated facet', same(P.boards.facets[3].values([]).map((v) => v.value), ['today', 'week', 'month']));
/* lane FC, FC-4: a review card's boards describe colleagues' code, so the list hides them
   until Include review boards is on; Harbor's and every other house's boards are as before */
{
  const row = (card, extra) => Object.assign({ id: 'b-1', source: card ? { kind: 'card', card: 'c-1' } : { kind: 'talker' },
                                               card: card || null }, extra || {});
  const review = row({ title: 'Review: x', space: 'work', review: true });
  const house = row({ title: 'A build', space: 'work' });
  const harbor = row(null);
  check('boards: the board of a review card is hidden by default', P.boards.hidden(review, { space: 'work' }) === 'review');
  check('boards: a house board and a Harbor board are not', P.boards.hidden(house, { space: 'work' }) === null &&
        P.boards.hidden(harbor, { space: 'work' }) === null);
  /* c-562: a done card's board is hidden for done, and for the space too when it is the other one */
  const done = row({ title: 'Shipped', space: 'work', done: true });
  check('boards: a done card\'s board names done, and the space beside it on the other space',
        P.boards.hidden(done, { space: 'work' }) === 'done' &&
        same(P.boards.hidden(done, { space: 'personal' }), ['allspaces', 'done']));
  check('boards: the switch says the same words as every Include',
        P.boards.include.filter((i) => i.key === 'review')[0].label === 'Include review boards');
  check('boards: Source knows a review board', P.boards.facets[0].values([]).some((v) => v.value === 'review') &&
        P.boards.facets[0].match(review, 'review') && !P.boards.facets[0].match(review, 'house') &&
        P.boards.facets[0].match(house, 'house'));
  const view = P.boards.views.filter((v) => v.label === 'Review boards')[0];
  check('boards: the Review boards view turns the switch on and shows only them',
        !!view && same(view.state.inc, ['review']) && same(view.state.f.source, ['review']));
  const found = F.run([review, house, harbor], F.blank(P.boards), P.boards, { space: 'work' });
  check('boards: hidden from the list and its counts', found.items.length === 2 && found.total === 2);
  const shown = F.run([review, house, harbor], Object.assign(F.blank(P.boards), { inc: ['review'] }), P.boards, { space: 'work' });
  check('boards: shown with the include', shown.items.length === 3);
}

process.stdout.write(JSON.stringify(fails.length ? { ok: false, fails } : { ok: true }) + '\n');
