/* THE BOARD LIST (C5, 2026-09-23): the Saved half of the board route.
 *
 * B12 split Saved into Houses and Harbor, which said the level but left a wall of rows once
 * a card had many boards. So a house's boards are grouped by CARD (its id in its space's
 * colour, its title, the tracker story id when it carries one), newest board first with the
 * live one marked, the groups ordered by the sort and the card in context first; Harbor's
 * boards are grouped by TOPIC under a Harbor heading.
 *
 * FINDING (lane FIND, 2026-09-24) is the deck's one find bar (app/ui.find.js, the table in
 * app/ui.findpages.js): the words go to the server search (`GET /api/boards?q=`,
 * `keel/boardlist.py`, which reads the board files directly) and a hit shows its snippet
 * and opens the board with that node lit; the facets (Source, Card, State, Updated) and
 * the sort (Latest activity, Newest created, Title) run here. The list follows the GLOBAL
 * space switch, with All spaces in the panel, and Include deleted ADDS the trash under a
 * Deleted heading with Restore on every row (app/ui.boarddelete.js), rather than swapping
 * the list for it. A board whose card is done or archived is off the list the same way, and
 * Include done ADDS those under a Done heading, grouped and stacked like Houses (c-562).
 *
 * DELETE (lane BD): every row and every stack carries a small menu whose one item deletes
 * (app/ui.boarddelete.js draws it and its confirm).
 *
 * `groups` is pure and exported, so the grouping is tested outside a browser
 * (`tests/fixtures/board-list.js`). The page state lives in ui.board.js's `B`, handed here
 * through `K.boardApi`.
 */
(function (K) {
  'use strict';

  var SEARCH_WAIT = 250;

  function sourceOf(row) { return (row.source || {}).kind === 'card' ? 'house' : 'harbor'; }

  /* How the sort orders the rows inside a group and the groups themselves: by the newest
     activity or creation in them, or by title. */
  function stamp(field) {
    return {
      row: function (a, b) { return String(b[field] || '').localeCompare(String(a[field] || '')); },
      group: function (g) { return g.rows.reduce(function (m, r) { return String(r[field] || '') > m ? String(r[field]) : m; }, ''); },
      desc: true
    };
  }
  var ORDERS = {
    activity: stamp('updated'),
    newest: stamp('created'),
    title: { row: function (a, b) { return String(a.title || '').localeCompare(String(b.title || '')); },
             group: function (g) { return String(g.title || g.card || '').toLowerCase(); }, desc: false }
  };
  function groupCmp(order) {
    return function (a, b) {
      var ka = order.group(a), kb = order.group(b);
      return order.desc ? kb.localeCompare(ka) : ka.localeCompare(kb);
    };
  }

  /* [{section, key, card, title, story, space, rows}] in the order the page shows them:
     every house group (the card in context first, then by the sort), then every Harbor
     topic group by the sort. The rows have already been through the find bar. */
  function groups(rows, context, sort) {
    var order = ORDERS[sort] || ORDERS.activity;
    var byCard = {}, byTopic = {}, cards = [], topics = [];
    (rows || []).forEach(function (r) {
      if (sourceOf(r) === 'house') {
        var id = r.source.card;
        if (!byCard[id]) { byCard[id] = []; cards.push(id); }
        byCard[id].push(r);
      } else {
        var topic = r.topic || r.id;
        if (!byTopic[topic]) { byTopic[topic] = []; topics.push(topic); }
        byTopic[topic].push(r);
      }
    });
    var houses = cards.map(function (id) {
      var list = byCard[id].slice().sort(order.row), card = list[0].card || {};
      return { section: 'Houses', key: 'c:' + id, card: id, title: card.title || '',
               story: card.story || '', space: card.space || '', rows: list };
    });
    var cmp = groupCmp(order);
    houses.sort(function (a, b) {
      if (a.card === context) return -1;
      if (b.card === context) return 1;
      return cmp(a, b);
    });
    var harbor = topics.map(function (topic) {
      var list = byTopic[topic].slice().sort(order.row);
      return { section: 'Harbor', key: 't:' + topic, card: null, title: list[0].title || 'Untitled board',
               story: '', space: '', rows: list };
    });
    harbor.sort(cmp);
    return houses.concat(harbor);
  }

  /* W1 to W3 (2026-09-24): each group of more than one board is a STACK, one row until he
     opens it. Open when a search is showing its hits (a hit is never hidden in a stack),
     else what he last chose for that group, else only the card in context. The find bar has
     already run before `groups`, so the count is of what passes. A one-board group is its row. */
  function stacks(gs, opts) {
    var o = opts || {}, mine = o.remembered || {};
    return (gs || []).map(function (g) {
      var stacked = g.rows.length > 1, chose = mine[g.key];
      var open = !stacked || !!o.searching ||
                 (typeof chose === 'boolean' ? chose : !!g.card && g.card === o.context);
      var live = g.rows.some(function (r) { return r.live && !r.closed; });
      return Object.assign({}, g, { stacked: stacked, open: open, count: g.rows.length,
                                    newest: g.rows[0], live: live });
    });
  }
  /* The remembered set is {group key: open}, kept by the page in localStorage. Anything
     that is not that shape reads as nothing remembered. */
  function readOpen(text) {
    var out = {};
    try {
      var got = JSON.parse(text);
      if (!got || typeof got !== 'object' || Array.isArray(got)) return out;
      Object.keys(got).forEach(function (k) { if (typeof got[k] === 'boolean') out[k] = got[k]; });
    } catch (e) { /* nothing remembered */ }
    return out;
  }
  function toggled(mine, key, open) {
    var out = Object.assign({}, mine || {});
    out[key] = !!open;
    return out;
  }

  /* ---------- the page ---------- */
  var searchTimer = null;

  /* Called from inside a render pass (the find bar's words changed), so it never paints
     itself: the pass it is in draws what it just set, and the answer repaints when it comes. */
  function search(B, text) {
    B.query = text;
    clearTimeout(searchTimer);
    var words = text.trim();
    if (!words) { B.hits = null; return; }
    searchTimer = setTimeout(function () {
      fetch('/api/boards?q=' + encodeURIComponent(words), { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (B.query.trim() !== words) return;          // a later keystroke owns the page now
          B.hits = d.rows || [];
          K.renderBody();
        })
        .catch(function () { B.hits = []; K.renderBody(); });
    }, SEARCH_WAIT);
  }

  /* A row is its button and, beside it, its menu (a button cannot hold another button). */
  function row(api, r) {
    if (!K.boardDelete) return rowButton(api, r, r.id);
    var main = rowButton(api, r, 'open');
    return K.el('div', { class: 'bsaved-row', 'data-key': r.id }, main, K.boardDelete.rowMenu(r));
  }
  function rowButton(api, r, key) {
    var hit = r.hit;
    return K.el('button', { class: 'bsaved-item' + (K.App.board === r.id ? ' on' : ''), 'data-key': key,
      onclick: function () { api.open(r.id, hit ? hit.node : null); } },
      K.el('div', { class: 'bsaved-head' },
        K.el('span', { class: 't ellip', text: r.title || 'Untitled board' }),
        r.live && !r.closed ? K.el('span', { class: 'bchip on', text: 'live' }) : null,
        r.closed ? K.el('span', { class: 'bchip', text: 'closed' }) : null,
        K.el('span', { class: 'mono t11 ink3', text: (r.updated || '').slice(0, 10) })),
      hit ? K.el('div', { class: 'sub blist-hit' },
              K.el('span', { class: 'mono t11 ink3', text: hit.field + (hit.node ? ' · ' + hit.node : '') + ' ' }),
              K.el('span', { text: hit.snippet }))
          : (r.summary ? K.el('div', { class: 'sub ellip', text: r.summary }) : null),
      K.el('div', { class: 'bsaved-chips' },
        K.el('span', { class: 'bchip', text: r.nodes + (r.nodes === 1 ? ' node' : ' nodes') }),
        K.el('span', { class: 'bchip', text: r.attachments + ' attached' }),
        K.el('span', { class: 'bchip', text: r.id })));
  }

  function countText(n) { return n + (n === 1 ? ' board' : ' boards'); }

  /* The group's own facts: a card's id in its space colour, its title and story; a topic's
     title. The count is drawn by the caller, since a stack puts it in its own place. */
  function headFacts(api, g) {
    if (!g.card) return [K.el('span', { class: 't ellip', text: g.title })];
    return [api.chip({ source: { kind: 'card', card: g.card } }, g.space),
            K.el('span', { class: 't ellip', text: g.title || g.card }),
            g.story ? K.el('span', { class: 'mono t11 ink2', text: g.story }) : null];
  }

  /* What he chose per group lives in localStorage; the page works when it cannot. */
  var OPEN_KEY = 'board-list.open';
  function remembered() {
    try { return readOpen(K.stored(OPEN_KEY)); } catch (e) { return {}; }
  }
  function remember(key, open) {
    try { K.store(OPEN_KEY, JSON.stringify(toggled(remembered(), key, open))); } catch (e) { /* kept for this pass only */ }
  }

  /* The toggle is ONE button in both states, keyed the same, so a repaint keeps his focus on
     it: collapsed it is the stack itself, open it is the group's header. A native button
     takes Enter and Space. */
  function toggle(api, s) {
    var n = s.newest || {};
    var attrs = { 'data-key': 'toggle', type: 'button', 'aria-expanded': s.open ? 'true' : 'false',
      'aria-label': (s.open ? 'collapse ' : 'expand ') + (s.card || s.title) + ', ' + countText(s.count),
      onclick: function () { remember(s.key, !s.open); K.renderBody(); } };
    var count = K.el('span', { class: 'bchip blist-count', text: countText(s.count) });
    var live = s.live ? K.el('span', { class: 'bchip on', text: 'live' }) : null;
    var newest = s.open ? null : [K.el('span', { class: 'ellip', text: n.title || 'Untitled board' }),
                                  K.el('span', { class: 'mono t11 ink3', text: K.ago(n.updated) })];
    attrs.class = s.open ? 'blist-toggle' : 'blist-stack';
    return K.el('button', attrs,
      K.el('div', { class: 'blist-head' }, headFacts(api, s)),
      K.el('div', { class: 'blist-newest' }, count, live, newest));
  }

  /* A searched group shows its hits under a plain header; a one-board card group keeps its
     header; a one-board topic is just that board, its heading would say it twice. */
  function plainHead(api, s) {
    if (!s.card && s.count === 1) return null;
    return K.el('div', { class: 'blist-head' }, headFacts(api, s),
      K.el('span', { class: 'mono t11 ink3', text: countText(s.count) }));
  }

  function group(api, s) {
    var head = s.stacked && !api.state.hits ? toggle(api, s) : plainHead(api, s);
    /* A STACK'S OWN MENU sits beside its toggle, open or shut: Delete all N boards. */
    if (s.stacked && !api.state.hits && K.boardDelete) {
      head = K.el('div', { class: 'blist-headrow', 'data-key': 'headrow' }, head, K.boardDelete.stackMenu(s));
    }
    var rows = s.open ? s.rows.map(function (r) { return row(api, r); }) : null;
    return K.el('div', { class: 'blist-group' + (s.stacked && !s.open ? ' shut' : ''), 'data-key': s.key },
      head, rows);
  }

  /* The words in the find bar go to the server; a new set of words starts a new search. */
  function followWords(B, words) {
    if ((B.query || '') !== words) search(B, words);
  }
  /* Without the find bar (a page that did not load it) the list is simply every row. */
  function findRows(api, rows) {
    if (!K.find) return { items: rows, total: rows.length, sort: 'activity', bar: null };
    var st = K.find.state('boards'), open = K.App.findUi && K.App.findUi.open && K.App.findUi.open.page === 'boards';
    var trash = K.boardDelete ? K.boardDelete.trashRows(st.inc.indexOf('deleted') >= 0 || !!open) : [];
    var found = K.find.run('boards', rows.concat(trash));
    return { items: found.items, total: found.total, sort: st.sort, bar: K.find.bar('boards', found),
             deleted: st.inc.indexOf('deleted') >= 0 };
  }

  /* A finished card's board (c-562) is drawn under Done; the find bar lets it through only
     with Include done on (and whatever else hides it), so the bar's count is what is drawn. */
  function isDone(r) { return !r.deleted && !!(r.card || {}).done; }

  /* One heading and its groups, stacked the way the list stacks them. */
  function section(api, name, gs) {
    return K.el('section', { class: 'bsaved-section', 'data-key': name },
      K.el('h3', { class: 'label', text: name }),
      gs.map(function (s) { return group(api, s); }));
  }

  function view(api) {
    var B = api.state;
    if (K.find) followWords(B, K.find.state('boards').q.trim());
    if (!B.list && !B.hits) { api.load(); }
    var rows = B.hits || B.list;
    var found = findRows(api, rows || []);
    var out = [found.bar];
    var live = found.items.filter(function (r) { return !r.deleted && !isDone(r); });
    var done = found.items.filter(isDone);
    var gone = found.items.filter(function (r) { return r.deleted; });
    var context = api.context();
    var how = { context: context, searching: !!B.hits, remembered: remembered() };
    var gs = rows ? stacks(groups(live, context, found.sort), how) : [];
    var finished = rows ? stacks(groups(done, context, found.sort), how) : [];
    if (!rows) out.push(K.el('div', { class: 'empty', text: 'reading the boards...' }));
    else if (!gs.length && !finished.length && !found.deleted) {
      out.push(K.el('div', { class: 'empty', text: B.hits ? 'no board says that' : (B.list || []).length ? 'no board matches' : 'nothing has been drawn yet' }));
    }
    ['Houses', 'Harbor'].forEach(function (name) {
      var mine = gs.filter(function (g) { return g.section === name; });
      if (mine.length) out.push(section(api, name, mine));
    });
    if (finished.length) out.push(section(api, 'Done', finished));
    if (found.deleted && K.boardDelete) out.push(K.boardDelete.trashSection(api, gone));
    return [K.el('div', { class: 'bsaved' }, out)];
  }

  K.boardList = { groups: groups, stacks: stacks, readOpen: readOpen, toggled: toggled, view: view };
})(window.Keel);
