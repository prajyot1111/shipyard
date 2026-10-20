/* THE FIND BAR (lane FIND, 2026-09-24): one component on every page that lists things.
 *
 *   [Views ▾] [ search, or stage:review repo:keel ] [Filter 2 ▾] [Sort ▾] [View ▾]
 *   Needs me · Queue order   Stage: Review, Building ×   Repo: cloud ×   Clear all
 *
 * The desk draws that as one row; the phone as TWO (the search across the width, then the
 * four buttons sharing the next row), never a sideways scroller. The buttons carry SHORT
 * FIXED LABELS everywhere: the current choice is never crammed into a button, where it
 * would be clipped at 390. The chosen view and the sort are the first, quiet item of the
 * token line instead, and each menu ticks its own choice.
 *
 * - The search takes free words AND typed filters (`field:value`, the grammar in
 *   ui.findcore.js) with a suggestion list under it: the fields first, then that field's
 *   values with counts; arrows move, Enter takes, Escape closes. A finished filter leaves
 *   the field and becomes a token.
 * - Filter opens the panel: every facet multi-select with its counts, a value that would
 *   give nothing dimmed and still there, the Include switches at the bottom in the same
 *   words on every page. The desk's is a dropdown applying live; the phone's a bottom
 *   sheet with a sticky Clear and "Show N".
 * - Sort and View are small menus; View holds the layout and the grouping, and offers only
 *   what works in the layout in force (the page's `modes`).
 * - Views holds the page's built-in presets, his own ("Save current view..."), and a delete
 *   for each of his.
 * - All of it is in the URL (shareable, and Back walks it) and remembered per page.
 *
 * Buttons and menus are real ones: `aria-haspopup`, `aria-expanded`, `role="menu"` with
 * `menuitemradio` entries, a `combobox` and `listbox` for the search, a `dialog` for the
 * panel. Which thing is open is page state (`App.findUi`), so a repaint draws it open again.
 */
(function (K) {
  'use strict';

  var el = K.el, App = K.App, C = K.findCore;
  /* which route draws which page's bar */
  var ROUTES = { cards: 'cards', board: 'boards', reviews: 'reviews' };
  App.find = App.find || {};
  App.findUi = { open: null, sug: null, saving: false, saveName: '', text: {}, facetQ: {} };
  var store = { get: function (k) { return K.stored(k); }, set: function (k, v) { K.store(k, v); } };

  function spec(page) { return K.findPages[page]; }
  function ctx() {
    var now = App.data && App.data.now ? Date.parse(App.data.now) : Date.now();
    return { desk: K.isDesk(), space: App.space, now: isNaN(now) ? Date.now() : now };
  }
  function pageOf(view) { return ROUTES[view] || null; }
  function route(view, page) { ROUTES[view] = page; }

  /* ---------- state, the URL and the memory ---------- */
  function state(page) {
    if (!App.find[page]) App.find[page] = C.recall(page, spec(page), store) || C.blank(spec(page));
    return App.find[page];
  }
  function text(page) {
    if (!(page in App.findUi.text)) App.findUi.text[page] = state(page).q;
    return App.findUi.text[page];
  }
  /* The route's URL is the state when it carries this system's parameters (every URL the
     deck writes for a page does); a bare `?view=cards` gets the remembered state. */
  function fromRoute(view) {
    var page = pageOf(view);
    if (!page) return;
    var q = new URLSearchParams(location.search);
    var st = C.fromParams(function (k) { return q.get(k); }, spec(page));
    if (st) { App.find[page] = st; App.findUi.text[page] = st.q; } else state(page);
  }
  function modeKeys() {
    var out = [];
    Object.keys(K.findPages).forEach(function (p) {
      (spec(p).modes || []).forEach(function (m) { if (out.indexOf(m.key) < 0) out.push(m.key); });
    });
    return out;
  }
  /* what go() puts in a route's URL: the page's state, so the URL always says it */
  function params(view) {
    var page = pageOf(view);
    return page ? C.toParams(state(page), spec(page)) : [];
  }
  function writeUrl(page, push) {
    var q = new URLSearchParams(location.search);
    C.PARAMS.concat(modeKeys()).forEach(function (k) { q.delete(k); });
    C.toParams(state(page), spec(page)).forEach(function (pair) { q.set(pair[0], pair[1]); });
    var url = location.pathname + '?' + q.toString();
    if (push) history.pushState(null, '', url); else history.replaceState(null, '', url);
  }
  function set(page, st, push) {
    App.find[page] = st;
    C.remember(page, st, store);
    writeUrl(page, push !== false);
    K.renderBody();
  }
  function edit(page, fn, push) { var st = C.clone(state(page)); fn(st); set(page, st, push); }
  /* One of the page's built-in views, applied without a render or a URL write: the caller
     is the route reader, which writes the URL itself (an old PRs link, lane RETIRE). */
  function preset(page, key) {
    var v = (spec(page).views || []).filter(function (x) { return x.key === key; })[0];
    if (!v) return;
    App.find[page] = C.applyView(state(page), v, spec(page));
    App.findUi.text[page] = App.find[page].q;
    C.remember(page, App.find[page], store);
  }
  function run(page, items) { return C.run(items, state(page), spec(page), ctx()); }
  function mode(page, key) { return C.modeOf(state(page), spec(page), ctx(), key); }

  function toggleValue(page, key, value) {
    edit(page, function (st) {
      var list = st.f[key] || (st.f[key] = []), at = list.indexOf(value);
      if (at >= 0) list.splice(at, 1); else list.push(value);
      if (!list.length) delete st.f[key];
    });
  }
  function toggleInc(page, key) {
    edit(page, function (st) {
      var at = st.inc.indexOf(key);
      if (at >= 0) st.inc.splice(at, 1); else st.inc.push(key);
    });
  }
  function include(page, key) { if (state(page).inc.indexOf(key) < 0) toggleInc(page, key); }
  function clearAll(page) {
    App.findUi.text[page] = '';
    edit(page, function (st) { st.q = ''; st.f = {}; st.inc = []; });
  }

  /* ---------- opening and closing ---------- */
  function openId(page, what) { return 'find-' + page + '-' + what; }
  function isOpen(page, what) { return !!(App.findUi.open && App.findUi.open.page === page && App.findUi.open.what === what); }
  function focusSoon(selector) {
    var node = document.querySelector(selector);
    if (node && node.focus) node.focus();
  }
  function open(page, what) {
    App.findUi.open = { page: page, what: what };
    App.findUi.saving = false;
    K.renderBody();
    var first = what === 'filter' ? '#' + openId(page, 'filter') + ' [role="checkbox"],#' + openId(page, 'filter') + ' [role="switch"]'
      : '#' + openId(page, what) + ' [aria-checked="true"],#' + openId(page, what) + ' [role^="menuitem"]';
    focusSoon(first);
  }
  function close(refocus) {
    var o = App.findUi.open;
    if (!o) return false;
    App.findUi.open = null;
    App.findUi.saving = false;
    K.renderBody();
    if (refocus) focusSoon('#' + openId(o.page, o.what) + '-btn');
    return true;
  }
  function toggle(page, what) { if (isOpen(page, what)) close(true); else open(page, what); }

  /* Escape closes the innermost find thing first, before the deck's own Escape runs. */
  document.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Escape') return;
    /* the suggestion list first, and only when it is actually showing something */
    if (App.findUi.sug && document.querySelector('.find-sug')) {
      App.findUi.sug = null; K.renderBody(); ev.stopPropagation(); ev.preventDefault(); return;
    }
    if (close(true)) { ev.stopPropagation(); ev.preventDefault(); }
  }, true);
  /* a click anywhere outside the open control's own host closes it */
  document.addEventListener('click', function (ev) {
    var o = App.findUi.open, t = ev.target;
    if (!o || !t || !t.closest) return;
    if (t.closest('[data-find-pop="' + o.page + '-' + o.what + '"]')) return;
    close(false);
  });

  /* ---------- the search field and its suggestions ---------- */
  function onInput(page, found, ev) {
    var raw = ev.target.value, got = C.absorb(raw, spec(page), false);
    var took = Object.keys(got.f).length || got.inc.length;
    if (took) { ev.target.value = got.text; raw = got.text; }
    App.findUi.text[page] = raw;
    App.findUi.sug = { page: page, at: -1 };
    var st = C.clone(state(page));
    st.q = C.wordsOf(raw, spec(page));
    Object.keys(got.f).forEach(function (k) {
      var list = st.f[k] || (st.f[k] = []);
      got.f[k].forEach(function (v) { if (list.indexOf(v) < 0) list.push(v); });
    });
    got.inc.forEach(function (k) { if (st.inc.indexOf(k) < 0) st.inc.push(k); });
    set(page, st, !!took);
  }
  function suggestions(page, found) {
    var s = App.findUi.sug;
    if (!s || s.page !== page) return [];
    return C.suggest(C.fragmentOf(text(page)), spec(page), found);
  }
  function takeSuggestion(page, found, row) {
    var input = document.getElementById(openId(page, 'search'));
    var next = C.replaceFragment(text(page), row.insert);
    if (input) input.value = next;
    onInput(page, found, { target: input || { value: next } });
    if (input) input.focus();
  }
  function onSearchKey(page, found, ev) {
    var list = suggestions(page, found), s = App.findUi.sug;
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      if (!list.length) return;
      ev.preventDefault();
      if (!s) s = App.findUi.sug = { page: page, at: -1 };
      s.at = (s.at + (ev.key === 'ArrowDown' ? 1 : -1) + list.length + 1) % (list.length + 1);
      if (s.at === list.length) s.at = -1;
      K.renderBody();
    } else if (ev.key === 'Enter') {
      ev.preventDefault();
      if (s && s.at >= 0 && list[s.at]) { takeSuggestion(page, found, list[s.at]); return; }
      var got = C.absorb(ev.target.value, spec(page), true);
      ev.target.value = got.text;
      onInput(page, found, { target: ev.target });
      App.findUi.sug = null;
      K.renderBody();
    } else if (ev.key === 'Tab') {
      App.findUi.sug = null;
    }
  }
  function suggestList(page, found) {
    var list = suggestions(page, found), s = App.findUi.sug, lid = openId(page, 'sug');
    if (!list.length) return null;
    var heads = {}, rows = [];
    list.forEach(function (row, i) {
      var head = row.kind === 'field' ? 'Fields' : C.facetOf(spec(page), row.field) ? C.facetOf(spec(page), row.field).label : 'Include';
      if (!heads[head]) {
        heads[head] = true;
        rows.push(el('div', { class: 'find-sughead', role: 'presentation', 'data-key': 'h-' + head, text: head }));
      }
      var label = row.kind === 'field' ? row.field + ':' : row.insert;
      rows.push(el('div', { class: 'find-sugrow' + (s && s.at === i ? ' hi' : ''), role: 'option', id: lid + '-' + i,
        'data-key': 'o-' + row.insert, 'aria-selected': s && s.at === i ? 'true' : 'false',
        title: row.label, 'aria-label': row.kind === 'field' ? row.label + ', a field' : row.label + ', ' + (row.count || 0),
        onmousedown: function (ev) { ev.preventDefault(); takeSuggestion(page, found, row); } },
        el('span', { class: 'find-sugval mono', text: label }),
        row.kind === 'field' ? el('span', { class: 'find-sugname', text: row.label })
          : el('span', { class: 'find-cnt mono', text: String(row.count || 0) })));
    });
    return el('div', { class: 'find-sug', id: lid, role: 'listbox', 'data-key': 'sug', 'aria-label': 'Suggestions' }, rows);
  }
  function searchField(page, found) {
    var s = App.findUi.sug, list = suggestions(page, found), lid = openId(page, 'sug');
    return el('div', { class: 'find-search', 'data-key': 'search' },
      el('span', { class: 'find-ic', 'aria-hidden': 'true', text: '⌕' }),
      el('input', { type: 'search', id: openId(page, 'search'), 'data-fk': 'find-' + page, value: text(page),
        placeholder: spec(page).placeholder, 'aria-label': 'Search ' + spec(page).noun[1] + ' or type a filter',
        role: 'combobox', 'aria-autocomplete': 'list', 'aria-expanded': list.length ? 'true' : 'false',
        'aria-controls': lid, 'aria-activedescendant': s && s.at >= 0 && list.length ? lid + '-' + s.at : null,
        autocomplete: 'off', spellcheck: 'false',
        oninput: function (ev) { onInput(page, found, ev); },
        onfocus: function () { App.findUi.sug = { page: page, at: -1 }; K.renderBody(); },
        onblur: function () { if (App.findUi.sug) { App.findUi.sug = null; K.renderBody(); } },
        onkeydown: function (ev) { onSearchKey(page, found, ev); } }),
      suggestList(page, found));
  }

  /* ---------- the buttons ---------- */
  function trigger(page, what, label, badge, popup) {
    var on = isOpen(page, what);
    return el('button', { class: 'find-btn' + (on ? ' open' : ''), id: openId(page, what) + '-btn', type: 'button',
      'data-key': 'btn', 'aria-haspopup': popup || 'menu', 'aria-expanded': on ? 'true' : 'false',
      'aria-controls': on ? openId(page, what) : null,
      'aria-label': badge ? label + ', ' + badge + ' on' : label,
      onclick: function (ev) { ev.stopPropagation(); toggle(page, what); } },
      el('span', { class: 'find-lbl', text: label }),
      badge ? el('span', { class: 'find-n mono', 'aria-hidden': 'true', text: String(badge) }) : null,
      el('span', { class: 'find-chev', 'aria-hidden': 'true', text: '▾' }));
  }
  function pop(page, what, cls, children) {
    return el('div', { class: 'find-pop ' + cls, 'data-key': what, 'data-find-pop': page + '-' + what }, children);
  }
  function menuKeys(ev) {
    var items = Array.prototype.slice.call(ev.currentTarget.querySelectorAll('[role^="menuitem"]'));
    var at = items.indexOf(document.activeElement), to = null, n = items.length;
    if (ev.key === 'ArrowDown') to = (at + 1) % n;
    else if (ev.key === 'ArrowUp') to = (at - 1 + n) % n;
    else if (ev.key === 'Home') to = 0;
    else if (ev.key === 'End') to = n - 1;
    else if (ev.key === 'Tab' && !ev.target.closest('form')) { close(false); return; }
    if (to === null || !n) return;
    ev.preventDefault();
    items[to].focus();
  }
  function radio(label, on, onclick, key) {
    return el('button', { class: 'find-item' + (on ? ' on' : ''), role: 'menuitemradio', type: 'button',
      'aria-checked': on ? 'true' : 'false', tabindex: '-1', 'data-key': key, title: label, onclick: onclick },
      el('span', { class: 'find-itemlbl', text: label }),
      el('span', { class: 'find-tick', 'aria-hidden': 'true', text: on ? '✓' : '' }));
  }
  function menu(page, what, label, children) {
    return el('div', { class: 'find-menu', id: openId(page, what), role: 'menu', 'aria-label': label,
      'data-key': 'menu', onkeydown: menuKeys }, children);
  }

  /* Sort: one tick. */
  function sortControl(page) {
    var st = state(page), sp = spec(page);
    return pop(page, 'sort', 'find-sortpop', [trigger(page, 'sort', 'Sort'),
      isOpen(page, 'sort') ? menu(page, 'sort', 'Sort ' + sp.noun[1], sp.sorts.map(function (s) {
        return radio(s.label, st.sort === s.key, function () {
          App.findUi.open = null;
          edit(page, function (x) { x.sort = s.key; });
          focusSoon('#' + openId(page, 'sort') + '-btn');
        }, s.key);
      })) : null]);
  }

  /* View: the layout and the grouping, only what works here; no button when nothing does. */
  function viewSections(page) {
    var sp = spec(page), st = state(page), c = ctx();
    return (sp.modes || []).map(function (m) {
      var options = m.options(st, c);
      if (options.length < 2) return null;
      var now_ = C.modeOf(st, sp, c, m.key);
      return el('div', { class: 'find-sec', role: 'group', 'aria-label': m.label, 'data-key': m.key },
        el('div', { class: 'find-sechead', role: 'presentation', text: m.label }),
        options.map(function (o) {
          return radio(o.label, now_ === o.key, function () { edit(page, function (x) { x.mode[m.key] = o.key; }); }, o.key);
        }));
    }).filter(Boolean);
  }
  function viewControl(page) {
    var secs = viewSections(page);
    if (!secs.length) return null;
    return pop(page, 'view', 'find-viewpop', [trigger(page, 'view', 'View'),
      isOpen(page, 'view') ? menu(page, 'view', 'View', secs) : null]);
  }

  /* Views: the built-ins, his own with a delete each, and "Save current view..." */
  function viewsMenu(page) {
    var sp = spec(page), st = state(page), on = C.chosen(st, sp, store), own = C.ownViews(page, store);
    function pick(v) {
      return function () { App.findUi.open = null; App.findUi.text[page] = v.state.q || ''; set(page, C.applyView(st, v, sp), true); };
    }
    var rows = sp.views.map(function (v) { return radio(v.label, !!on && on.key === v.key, pick(v), v.key); });
    if (own.length) {
      rows.push(el('div', { class: 'find-sechead', role: 'presentation', 'data-key': 'own-head', text: 'Your views' }));
      own.forEach(function (v) {
        rows.push(el('div', { class: 'find-ownrow', role: 'presentation', 'data-key': 'own-' + v.key },
          radio(v.label, !!on && on.key === v.key, pick(v), 'pick'),
          el('button', { class: 'find-del', role: 'menuitem', type: 'button', tabindex: '-1', 'data-key': 'del',
            'aria-label': 'Delete view ' + v.label, title: 'Delete view ' + v.label,
            onclick: function (ev) { ev.stopPropagation(); C.deleteView(page, v.key, store); K.renderBody(); } }, '×')));
      });
    }
    rows.push(App.findUi.saving ? saveForm(page) : el('button', { class: 'find-item find-save', role: 'menuitem', type: 'button',
      tabindex: '-1', 'data-key': 'save', onclick: function (ev) {
        ev.stopPropagation(); App.findUi.saving = true; App.findUi.saveName = ''; K.renderBody();
        focusSoon('#' + openId(page, 'savename'));
      } }, 'Save current view...'));
    return menu(page, 'views', 'Views', rows);
  }
  function saveForm(page) {
    function save(ev) {
      ev.preventDefault();
      var name = App.findUi.saveName.trim();
      if (!name) return;
      C.saveView(page, name, state(page), store);
      App.findUi.saving = false;
      K.renderBody();
      K.toast('saved as a view: ' + name);
    }
    return el('form', { class: 'find-saveform', 'data-key': 'saveform', onsubmit: save },
      el('input', { type: 'text', id: openId(page, 'savename'), 'aria-label': 'Name for this view',
        placeholder: 'Name this view', value: App.findUi.saveName,
        oninput: function (ev) { App.findUi.saveName = ev.target.value; } }),
      el('button', { class: 'find-savebtn', type: 'submit' }, 'Save'));
  }
  function viewsControl(page) {
    return pop(page, 'views', 'find-viewspop', [trigger(page, 'views', 'Views'), isOpen(page, 'views') ? viewsMenu(page) : null]);
  }

  /* ---------- the filter panel (desk) and sheet (phone) ---------- */
  function facetRow(page, facet, v, found) {
    var chosen = (state(page).f[facet.key] || []).indexOf(v.value) >= 0;
    var n = (found.counts[facet.key] || {})[v.value] || 0;
    return el('button', { class: 'find-row' + (n || chosen ? '' : ' zero'), type: 'button', role: 'checkbox',
      'aria-checked': chosen ? 'true' : 'false', 'data-key': 'v-' + v.value, title: v.label + ', ' + n,
      'aria-label': v.label + ', ' + n + (n ? '' : ', nothing matches'),
      onclick: function () { toggleValue(page, facet.key, v.value); } },
      el('span', { class: 'find-box', 'aria-hidden': 'true', text: chosen ? '✓' : '' }),
      el('span', { class: 'find-rowlbl', text: v.label }),
      el('span', { class: 'find-cnt mono', 'aria-hidden': 'true', text: String(n) }));
  }
  var FACET_SEARCH_AT = 7;
  function facetBlock(page, facet, found) {
    var values = found.values[facet.key] || [], key = page + '.' + facet.key, q = (App.findUi.facetQ[key] || '').toLowerCase();
    var searchable = facet.search && values.length >= FACET_SEARCH_AT;
    var shown = searchable && q ? values.filter(function (v) { return v.label.toLowerCase().indexOf(q) >= 0; }) : values;
    if (!values.length) return null;
    return el('div', { class: 'find-facet', role: 'group', 'aria-label': facet.label, 'data-key': 'f-' + facet.key },
      el('div', { class: 'find-sechead', text: facet.label }),
      searchable ? el('input', { type: 'search', class: 'find-facetq', value: App.findUi.facetQ[key] || '',
        placeholder: 'Find a ' + facet.label.toLowerCase(), 'aria-label': 'Find a ' + facet.label.toLowerCase(),
        oninput: function (ev) { App.findUi.facetQ[key] = ev.target.value; K.renderBody(); } }) : null,
      shown.map(function (v) { return facetRow(page, facet, v, found); }));
  }
  /* Archived cards are not in the page's state until a switch asks for them (c-540), so
     while they are out the count is not known here: the switch says none rather than a
     wrong +0. `scope.archived` is the server's word for whether they are held. */
  var NOT_LOADED = ['archived', 'dismissed'];
  function countKnown(key) {
    var held = App.data && App.data.scope;
    /* the same for done cards until the done part lands behind the first draw (c-549) */
    if (key === 'done' && !K.doneHeld()) return false;
    return !held || held.name === 'all' || !!held.archived || NOT_LOADED.indexOf(key) < 0;
  }
  function switchRow(page, inc, found) {
    var on = state(page).inc.indexOf(inc.key) >= 0, n = found.incCounts[inc.key] || 0, known = countKnown(inc.key);
    return el('button', { class: 'find-row find-switch', type: 'button', role: 'switch', 'aria-checked': on ? 'true' : 'false',
      'data-key': 'i-' + inc.key, title: known ? inc.label + ', ' + n : inc.label,
      'aria-label': known ? inc.label + ', adds ' + n : inc.label,
      onclick: function () { toggleInc(page, inc.key); } },
      el('span', { class: 'find-rowlbl', text: inc.label }),
      known ? el('span', { class: 'find-cnt mono', 'aria-hidden': 'true', text: '+' + n }) : null,
      el('span', { class: 'find-toggle', 'aria-hidden': 'true' }));
  }
  function includeBlocks(page, found) {
    var groups = {}, order = [];
    (spec(page).include || []).forEach(function (inc) {
      var g = inc.group || 'Include';
      if (!groups[g]) { groups[g] = []; order.push(g); }
      groups[g].push(inc);
    });
    return order.map(function (g) {
      return el('div', { class: 'find-facet', role: 'group', 'aria-label': g, 'data-key': 'g-' + g },
        el('div', { class: 'find-sechead', text: g === 'Space' ? 'Space: ' + App.space : g }),
        groups[g].map(function (inc) { return switchRow(page, inc, found); }));
    });
  }
  function showWord(page, n) { var noun = spec(page).noun; return 'Show ' + n + ' ' + (n === 1 ? noun[0] : noun[1]); }
  function panelBody(page, found) {
    return [spec(page).facets.map(function (f) { return facetBlock(page, f, found); }), includeBlocks(page, found)];
  }
  function panelFoot(page, found) {
    return el('div', { class: 'find-foot', 'data-key': 'foot' },
      el('button', { class: 'btn find-clear', type: 'button', onclick: function () { clearAll(page); } }, 'Clear'),
      el('button', { class: 'btn primary find-show', type: 'button', onclick: function () { close(true); } },
        showWord(page, found.total)));
  }
  function filterPanel(page, found) {
    var label = 'Filter ' + spec(page).noun[1];
    if (ctx().desk) {
      return el('div', { class: 'find-panel', id: openId(page, 'filter'), role: 'dialog', 'aria-label': label, 'data-key': 'panel' },
        el('div', { class: 'find-panelbody' }, panelBody(page, found)), panelFoot(page, found));
    }
    return el('div', { class: 'find-sheetwrap', 'data-key': 'sheet' },
      el('div', { class: 'find-scrim', onclick: function () { close(true); } }),
      el('div', { class: 'find-sheet', id: openId(page, 'filter'), role: 'dialog', 'aria-modal': 'true', 'aria-label': label,
        onkeydown: trapTab },
        el('div', { class: 'find-grab', 'aria-hidden': 'true' }, el('span', {})),
        el('div', { class: 'find-sheethead' }, el('span', { class: 'find-sheettitle', text: 'Filter' }),
          el('button', { class: 'find-close', type: 'button', 'aria-label': 'Close the filter', onclick: function () { close(true); } }, '×')),
        el('div', { class: 'find-sheetbody' }, panelBody(page, found)),
        panelFoot(page, found)));
  }
  /* the sheet keeps Tab inside itself while it is up */
  function trapTab(ev) {
    if (ev.key !== 'Tab') return;
    var f = Array.prototype.slice.call(ev.currentTarget.querySelectorAll('button, input'));
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
    else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
  }
  function filterControl(page, found) {
    var n = C.active(state(page));
    return pop(page, 'filter', 'find-filterpop', [trigger(page, 'filter', 'Filter', n, 'dialog'),
      isOpen(page, 'filter') ? filterPanel(page, found) : null]);
  }

  /* ---------- the token line ---------- */
  function labelOf(page, key, value) {
    var facet = C.facetOf(spec(page), key), v = null;
    if (facet && facet.values) v = facet.values([]).filter(function (x) { return x.value === value; })[0];
    return v ? v.label : value;
  }
  function token(key, text, aria, onclick) {
    return el('button', { class: 'find-token', type: 'button', 'data-key': key, title: text,
      'aria-label': aria, onclick: onclick },
      el('span', { class: 'find-toklbl', text: text }), el('span', { class: 'find-x', 'aria-hidden': 'true', text: '×' }));
  }
  function tokens(page) {
    var st = state(page), sp = spec(page), out = [];
    sp.facets.forEach(function (facet) {
      var vals = st.f[facet.key] || [];
      if (!vals.length) return;
      var text = facet.label + ': ' + vals.map(function (v) { return labelOf(page, facet.key, v); }).join(', ');
      out.push(token('t-' + facet.key, text, 'Remove filter ' + text, function () {
        edit(page, function (x) { delete x.f[facet.key]; });
      }));
    });
    (sp.include || []).forEach(function (inc) {
      if (st.inc.indexOf(inc.key) < 0) return;
      out.push(token('t-inc-' + inc.key, inc.label, 'Remove ' + inc.label, function () { toggleInc(page, inc.key); }));
    });
    return out;
  }
  /* The quiet first item: the chosen view and the sort, which the buttons never carry. */
  function nowLine(page) {
    var st = state(page), sp = spec(page), v = C.chosen(st, sp, store);
    var sort = sp.sorts.filter(function (s) { return s.key === st.sort; })[0] || sp.sorts[0];
    var words = (v ? v.label + ' · ' : '') + sort.label;
    return el('span', { class: 'find-now', 'data-key': 'now', title: 'Now showing: ' + words, text: words });
  }
  function tokenLine(page) {
    var list = tokens(page), st = state(page), any = list.length || st.q;
    return el('div', { class: 'find-tokens', 'data-key': 'tokens', role: 'group', 'aria-label': 'Active filters' },
      nowLine(page), list,
      any ? el('button', { class: 'find-clearall', type: 'button', 'data-key': 'clear', onclick: function () { clearAll(page); } }, 'Clear all') : null);
  }

  /* ---------- the whole block ---------- */
  function bar(page, found) {
    return el('div', { class: 'find', 'data-key': 'find-' + page, 'data-find': page },
      el('div', { class: 'find-bar', 'data-key': 'bar' },
        viewsControl(page), searchField(page, found), filterControl(page, found), sortControl(page), viewControl(page)),
      tokenLine(page));
  }
  /* Leaving a route closes whatever was open in its bar. */
  function leave() { App.findUi.open = null; App.findUi.sug = null; App.findUi.saving = false; }

  K.find = { bar: bar, run: run, state: state, mode: mode, include: include, params: params, fromRoute: fromRoute,
             pageOf: pageOf, route: route, leave: leave, close: close, open: open, set: set, clearAll: clearAll,
             toggleValue: toggleValue, toggleInc: toggleInc, store: store, ctx: ctx, preset: preset };
})(window.Keel);
