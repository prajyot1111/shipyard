/* The board list's grouping (C5), checked outside a browser.
 *
 * Usage: node board-list.js <path to ui.boardlist.js>
 * Output: {"ok": true}, or a JSON object naming the checks that failed.
 */
'use strict';
const fs = require('fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
const win = { Keel: {} };
new Function('window', source)(win);
const L = win.Keel.boardList;
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

const card = (id, space, title, story) => ({ kind: 'card', card: id, _c: { space, title, story } });
function row(id, source, updated, extra) {
  const r = Object.assign({ id, title: id + ' title', updated, live: false, closed: null,
                            nodes: 1, attachments: 0, topic: id }, extra || {});
  if (source.kind === 'card') { r.source = { kind: 'card', card: source.card }; r.card = source._c; }
  else { r.source = { kind: 'talker', card: null }; r.card = null; }
  return r;
}
const rows = [
  row('b-1', card('c-1', 'personal', 'Old card', ''), '2026-09-20T10:00'),
  row('b-2', card('c-2', 'work', 'Work card', 'st-7'), '2026-09-22T10:00', { live: true }),
  row('b-3', card('c-1', 'personal', 'Old card', ''), '2026-09-21T10:00', { live: true }),
  row('b-4', { kind: 'talker' }, '2026-09-23T10:00', { topic: 'memory', title: 'Memory' }),
  row('b-5', { kind: 'talker' }, '2026-09-19T10:00', { topic: 'memory', title: 'memory.', closed: '2026-09-19' }),
  row('b-6', { kind: 'talker' }, '2026-09-22T12:00', { topic: 'drain', title: 'Drain' }),
];

let gs = L.groups(rows, null);
check('houses come before Harbor', gs.map(g => g.section).join() === 'Houses,Houses,Harbor,Harbor');
check('house groups are ordered by their latest activity', gs[0].card === 'c-2' && gs[1].card === 'c-1');
check('a card group names its title and story', gs[0].title === 'Work card' && gs[0].story === 'st-7');
check('newest board first inside a group', gs[1].rows.map(r => r.id).join() === 'b-3,b-1');
check('Harbor is grouped by topic, newest topic first',
      gs[2].key === 't:memory' && gs[2].rows.map(r => r.id).join() === 'b-4,b-5' && gs[3].key === 't:drain');

gs = L.groups(rows, 'c-1');
check('the card in context leads', gs[0].card === 'c-1');

/* FS-3: the sort orders the groups and the rows in them (the facets are the find bar's,
   tests/fixtures/find-ui.js) */
gs = L.groups(rows, null, 'title');
check('sorted by title, the groups and their rows go by title',
      gs.filter(g => g.section === 'Harbor').map(g => g.key).join() === 't:drain,t:memory' &&
      gs[0].card === 'c-1' && gs[1].card === 'c-2');
const created = rows.map((r, i) => Object.assign({}, r, { created: '2026-09-0' + (i + 1) }));
gs = L.groups(created, null, 'newest');
check('sorted by newest created, the newest creation leads', gs[0].card === 'c-1' && gs[0].rows[0].id === 'b-3');

/* W1 to W3 (2026-09-24): a group of more than one board is a stack, collapsed unless it is
   the card in context, he opened it, or a search is showing its hits. */
const many = rows.concat([
  row('b-7', card('c-3', 'work', 'Lone card', ''), '2026-09-18T10:00'),
  row('b-8', card('c-1', 'personal', 'Old card', ''), '2026-09-22T11:00', { title: 'Newest of c-1' }),
]);
let st = L.stacks(L.groups(many, null), { context: null, searching: false, remembered: {} });
const by = key => st.find(s => s.key === key);
check('a one-board group is no stack, and is drawn open as its row',
      by('c:c-3').stacked === false && by('c:c-3').open === true && by('t:drain').stacked === false);
check('a group of more than one board is a stack, collapsed by default',
      by('c:c-1').stacked === true && by('c:c-1').open === false && by('t:memory').open === false);
check('a stack counts its boards and names the newest',
      by('c:c-1').count === 3 && by('c:c-1').newest.id === 'b-8' && by('c:c-1').newest.title === 'Newest of c-1');
check('a stack is live when any of its boards is live and open',
      by('c:c-1').live === true && by('t:memory').live === false);

st = L.stacks(L.groups(many, 'c-1'), { context: 'c-1', searching: false, remembered: {} });
check('the card in context starts expanded, every other stack collapsed',
      by('c:c-1').open === true && by('t:memory').open === false);

st = L.stacks(L.groups(many, 'c-1'), { context: 'c-1', searching: false,
                                          remembered: { 'c:c-1': false, 't:memory': true } });
check('what he chose is remembered per group, over the context default',
      by('c:c-1').open === false && by('t:memory').open === true);

const hits = [
  row('b-3', card('c-1', 'personal', 'Old card', ''), '2026-09-21T10:00', { hit: { field: 'label', snippet: 'x', node: 'n' } }),
  row('b-1', card('c-1', 'personal', 'Old card', ''), '2026-09-20T10:00', { hit: { field: 'title', snippet: 'y', node: null } }),
];
st = L.stacks(L.groups(hits, null), { context: null, searching: true, remembered: { 'c:c-1': false } });
check('a search expands every group with a hit and shows only its hits',
      st.length === 1 && st[0].open === true && st[0].rows.map(r => r.id).join() === 'b-3,b-1');

st = L.stacks(L.groups(many.filter(r => r.live), null), { context: null, searching: false, remembered: {} });
check('the find bar runs before stacking: the count is of what passes',
      by('c:c-1').count === 1 && by('c:c-1').stacked === false && !by('t:memory'));

let mem = L.readOpen('not json');
check('a remembered set that will not parse is an empty one', JSON.stringify(mem) === '{}');
mem = L.toggled(L.toggled(mem, 'c:c-1', true), 't:memory', false);
check('a toggle is written and read back', JSON.stringify(L.readOpen(JSON.stringify(mem))) === '{"c:c-1":true,"t:memory":false}');
check('a remembered set that is not an object is an empty one', JSON.stringify(L.readOpen('[1]')) === '{}' && JSON.stringify(L.readOpen(null)) === '{}');

/* The page itself, drawn with a stand-in for K.el that builds plain objects. */
function fakeEl(tag, attrs) {
  const kids = [];
  (function flat(list) { list.forEach(c => { if (Array.isArray(c)) flat(c); else if (c != null) kids.push(c); }); })(
    Array.prototype.slice.call(arguments, 2));
  return { tag, attrs: attrs || {}, kids };
}
function walk(n, out) { if (typeof n !== 'object') return out; out.push(n); (n.kids || []).forEach(k => walk(k, out)); return out; }
function textOf(n) { return typeof n !== 'object' ? String(n) : (n.attrs.text || '') + ' ' + (n.kids || []).map(textOf).join(' '); }
const K = win.Keel;
let saved = null, painted = 0;
Object.assign(K, { el: fakeEl, App: { board: null }, ago: () => '2d', renderBody: () => { painted++; },
                   stored: () => saved, store: (k, v) => { if (k === 'board-list.open') saved = v; } });
const api = { state: { list: many }, load() {}, context: () => 'c-1',
              chip: () => fakeEl('span', { class: 'bchip' }), open() {} };
let all = walk({ attrs: {}, kids: L.view(api) }, []);
const groupOf = key => all.find(n => /\bblist-group\b/.test(n.attrs.class || '') && n.attrs['data-key'] === key);
const toggleOf = key => (groupOf(key) || { kids: [] }).kids.find(n => n.attrs['data-key'] === 'toggle');
const itemsOf = key => walk(groupOf(key), []).filter(n => /\bbsaved-item\b/.test(n.attrs.class || ''));
check('a collapsed stack is one button with aria-expanded false, its count, newest title and age',
      toggleOf('t:memory') && toggleOf('t:memory').tag === 'button' &&
      toggleOf('t:memory').attrs['aria-expanded'] === 'false' && /stack/.test(toggleOf('t:memory').attrs.class) &&
      /2 boards/.test(textOf(toggleOf('t:memory'))) && /Memory/.test(textOf(toggleOf('t:memory'))) &&
      /2d/.test(textOf(toggleOf('t:memory'))) && itemsOf('t:memory').length === 0);
check('the card in context is drawn open, its header a toggle with aria-expanded true',
      toggleOf('c:c-1').attrs['aria-expanded'] === 'true' && itemsOf('c:c-1').length === 3 &&
      /3 boards/.test(textOf(toggleOf('c:c-1'))));
check('a live stack carries the live marker', /live/.test(textOf(toggleOf('c:c-1'))));
check('a one-board group is its row with no toggle',
      !toggleOf('c:c-3') && itemsOf('c:c-3').length === 1 && !toggleOf('t:drain') && itemsOf('t:drain').length === 1);
toggleOf('t:memory').attrs.onclick();
check('opening a stack is remembered and repaints', painted === 1 && JSON.parse(saved)['t:memory'] === true);
all = walk({ attrs: {}, kids: L.view(api) }, []);
check('the opened stack draws its rows', itemsOf('t:memory').length === 2 &&
      toggleOf('t:memory').attrs['aria-expanded'] === 'true');
toggleOf('c:c-1').attrs.onclick();
all = walk({ attrs: {}, kids: L.view(api) }, []);
check('the header collapses the card in context again', itemsOf('c:c-1').length === 0 &&
      toggleOf('c:c-1').attrs['aria-expanded'] === 'false');
api.state.hits = hits; api.state.query = 'x';
all = walk({ attrs: {}, kids: L.view(api) }, []);
check('during a search a group shows its hits and no toggle',
      itemsOf('c:c-1').length === 2 && !toggleOf('c:c-1') && !all.some(n => /stack/.test(n.attrs.class || '')));
K.stored = () => { throw new Error('storage refused'); };
K.store = () => { throw new Error('storage refused'); };
api.state.hits = null; api.state.query = '';
all = walk({ attrs: {}, kids: L.view(api) }, []);
check('the page draws without storage', itemsOf('c:c-1').length === 3);

process.stdout.write(JSON.stringify(fails.length ? { ok: false, failed: fails } : { ok: true }));
