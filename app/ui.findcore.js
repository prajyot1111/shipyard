/* THE FIND SYSTEM'S ENGINE (lane FIND, 2026-09-24): pure, no DOM, loadable under node.
 *
 * One find bar on every page that lists things (Cards, the board list, Reviews). A page
 * declares its facets, include switches, sorts, built-in views and view modes in ONE table
 * (app/ui.findpages.js); this file does everything that table implies, and app/ui.find.js
 * draws it. Nothing in here knows which page it is serving.
 *
 * THE STATE of one page is {q, f, inc, sort, mode}:
 *   q     the free words of the search field (every word must be somewhere in the item)
 *   f     {facet key: [values]}; values of one facet are EITHER, facets are BOTH
 *   inc   the include switches that are on ("Include done"): an item a page hides by
 *         default (`spec.hidden(item)` names why) is ADDED to the list when its reason is
 *         on, never swapped for it; an item hidden for SEVERAL reasons (a list of keys)
 *         needs every one of them on
 *   sort  a key of `spec.sorts`; the first one is the default
 *   mode  {mode key: choice} (layout, group by); a choice the current layout cannot use
 *         falls back rather than doing nothing (`modeOf`)
 *
 * THE GRAMMAR is typed in the search field and written in the URL, one grammar for both:
 *   stage:review,building repo:cloud topic:"big ideas" include:done  words
 * A field is a facet key (or `include`), matched without case; a value is matched without
 * case to a value the page knows and kept as typed when it knows none (it then matches
 * nothing, which the zero count says). Anything else, a url or `c-12:` included, is words.
 *
 * STORAGE is passed in as {get(key), set(key, value)} so this file never touches the
 * browser; every read and write is in try/catch and a refusal reads as nothing kept.
 */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var INCLUDE = 'include';
  /* the URL parameters this system owns; `sort` is ALWAYS written, so a URL that carries
     none of them is one that says nothing (the remembered state is used) */
  var PARAMS = ['q', 'f', 'inc', 'sort'];

  function lower(s) { return String(s === null || s === undefined ? '' : s).toLowerCase(); }
  function copyF(f) {
    var out = {};
    Object.keys(f || {}).forEach(function (k) { if ((f[k] || []).length) out[k] = f[k].slice(); });
    return out;
  }
  function blank(spec) {
    return { q: '', f: {}, inc: [], sort: spec.sorts && spec.sorts.length ? spec.sorts[0].key : '', mode: {} };
  }
  function clone(st) {
    return { q: st.q || '', f: copyF(st.f), inc: (st.inc || []).slice(), sort: st.sort || '',
             mode: Object.assign({}, st.mode || {}) };
  }
  function facetOf(spec, key) {
    return (spec.facets || []).filter(function (f) { return f.key === key; })[0] || null;
  }
  function includeKeys(spec) { return (spec.include || []).map(function (i) { return i.key; }); }
  function sortKeys(spec) { return (spec.sorts || []).map(function (s) { return s.key; }); }

  /* The distinct values a list holds, for a facet whose values come from the data:
     `pick(item)` returns one value or an array of them; empty ones are skipped. */
  function distinct(list, pick) {
    var seen = {}, out = [];
    (list || []).forEach(function (item) {
      var got = pick(item);
      (Array.isArray(got) ? got : [got]).forEach(function (v) {
        v = String(v === null || v === undefined ? '' : v).trim();
        if (v && !seen[v]) { seen[v] = true; out.push({ value: v, label: v }); }
      });
    });
    return out.sort(function (a, b) { return a.label.localeCompare(b.label); });
  }
  function valuesOf(facet, items) { return facet.values ? facet.values(items || []) : []; }

  /* ---------- the grammar ---------- */
  /* Pieces split on whitespace outside double quotes, each with where it ends in the text. */
  function pieces(text) {
    var out = [], cur = '', quoted = false, i, ch;
    text = String(text || '');
    for (i = 0; i < text.length; i++) {
      ch = text[i];
      if (ch === '"') { quoted = !quoted; cur += ch; continue; }
      if (!quoted && /\s/.test(ch)) { if (cur) out.push({ raw: cur, end: i }); cur = ''; continue; }
      cur += ch;
    }
    if (cur) out.push({ raw: cur, end: text.length });
    return out;
  }
  /* `review,"big ideas",x` -> ['review', 'big ideas', 'x'] */
  function splitValues(rest) {
    var out = [], cur = '', quoted = false, i, ch;
    for (i = 0; i < rest.length; i++) {
      ch = rest[i];
      if (ch === '"') { quoted = !quoted; continue; }
      if (!quoted && ch === ',') { if (cur.trim()) out.push(cur.trim()); cur = ''; continue; }
      cur += ch;
    }
    if (cur.trim()) out.push(cur.trim());
    return out;
  }
  /* The value the page knows for what was typed, else what was typed. */
  function canon(spec, field, typed, items) {
    var want = lower(typed);
    if (field === INCLUDE) {
      var inc = includeKeys(spec).filter(function (k) { return lower(k) === want; })[0];
      return inc || null;
    }
    var hit = valuesOf(facetOf(spec, field), items).filter(function (v) {
      return lower(v.value) === want || lower(v.label) === want;
    })[0];
    return hit ? hit.value : typed;
  }
  function fieldOf(spec, name) {
    var n = lower(name);
    if (n === INCLUDE) return INCLUDE;
    var f = (spec.facets || []).filter(function (x) { return lower(x.key) === n; })[0];
    return f ? f.key : null;
  }
  /* One piece read as a filter: {field, values} or null when it is words. */
  function asFilter(raw, spec, items) {
    var m = /^([A-Za-z][\w-]*):(.+)$/.exec(raw);
    if (!m) return null;
    var field = fieldOf(spec, m[1]);
    if (!field) return null;
    var values = splitValues(m[2]).map(function (v) { return canon(spec, field, v, items); })
      .filter(function (v) { return v !== null; });
    return values.length ? { field: field, values: values } : null;
  }
  function addValues(target, field, values) {
    var list = target[field] || (target[field] = []);
    values.forEach(function (v) { if (list.indexOf(v) < 0) list.push(v); });
  }
  /* The whole text read: {f, inc, words}. */
  function parse(text, spec, items) {
    var out = { f: {}, inc: [], words: [] };
    pieces(text).forEach(function (p) {
      var got = asFilter(p.raw, spec, items);
      if (!got) { out.words.push(p.raw); return; }
      if (got.field === INCLUDE) got.values.forEach(function (v) { if (out.inc.indexOf(v) < 0) out.inc.push(v); });
      else addValues(out.f, got.field, got.values);
    });
    out.words = out.words.join(' ');
    return out;
  }
  /* What the search field holds after a keystroke: every FINISHED filter is lifted out into
     `f`/`inc` (finished = something follows it, or `all` for Enter), the rest stays as typed. */
  function absorb(text, spec, all, items) {
    var out = { f: {}, inc: [], text: '' }, kept = [], list = pieces(text), trailing = /\s$/.test(String(text || ''));
    list.forEach(function (p, i) {
      var last = i === list.length - 1;
      var got = (all || !last || trailing) ? asFilter(p.raw, spec, items) : null;
      if (!got) { kept.push(p.raw); return; }
      if (got.field === INCLUDE) got.values.forEach(function (v) { if (out.inc.indexOf(v) < 0) out.inc.push(v); });
      else addValues(out.f, got.field, got.values);
    });
    out.text = kept.join(' ') + (trailing && kept.length && !all ? ' ' : '');
    return out;
  }
  /* The words the list is filtered by while he types: the field's text less a filter he is
     still in the middle of typing (`stage:rev` would otherwise match nothing as a word). */
  function wordsOf(text, spec) {
    var list = pieces(text);
    if (!list.length) return '';
    var last = list[list.length - 1].raw, m = /^([A-Za-z][\w-]*):/.exec(last);
    if (m && fieldOf(spec, m[1]) && !/\s$/.test(String(text))) list.pop();
    return list.map(function (p) { return p.raw; }).join(' ');
  }
  function quote(v) { return /[\s,"]/.test(v) ? '"' + String(v).replace(/"/g, '') + '"' : String(v); }
  /* filters in the grammar they are typed in, facets in the page's own order */
  function format(f, spec) {
    return (spec.facets || []).filter(function (x) { return (f[x.key] || []).length; })
      .map(function (x) { return x.key + ':' + f[x.key].map(quote).join(','); }).join(' ');
  }

  /* ---------- the URL ---------- */
  function toParams(st, spec) {
    var out = [];
    if (st.q) out.push(['q', st.q]);
    var f = format(st.f || {}, spec);
    if (f) out.push(['f', f]);
    if ((st.inc || []).length) out.push(['inc', st.inc.join(',')]);
    out.push(['sort', st.sort || blank(spec).sort]);
    (spec.modes || []).forEach(function (m) {
      if (st.mode && st.mode[m.key]) out.push([m.key, st.mode[m.key]]);
    });
    return out;
  }
  /* `get(name)` reads one parameter (URLSearchParams.get). null when the URL carries none
     of this system's parameters. */
  function fromParams(get, spec) {
    var any = PARAMS.some(function (k) { return get(k) !== null; });
    if (!any) return null;
    var st = blank(spec);
    st.q = get('q') || '';
    st.f = parse(get('f') || '', spec).f;
    var incs = includeKeys(spec);
    st.inc = String(get('inc') || '').split(',').filter(function (k) { return incs.indexOf(k) >= 0; });
    if (sortKeys(spec).indexOf(get('sort')) >= 0) st.sort = get('sort');
    (spec.modes || []).forEach(function (m) { if (get(m.key)) st.mode[m.key] = get(m.key); });
    return st;
  }
  K.FIND_PARAMS = PARAMS;

  /* ---------- the modes ---------- */
  /* The choice in force for a mode: his, when this layout offers it, else the fallback.
     null when the mode offers nothing here (kanban has no grouping: it is the grouping). */
  function modeOf(st, spec, ctx, key) {
    var m = (spec.modes || []).filter(function (x) { return x.key === key; })[0];
    if (!m) return null;
    var options = m.options(st, ctx || {}).map(function (o) { return typeof o === 'string' ? o : o.key; });
    if (!options.length) return null;
    var want = st.mode && st.mode[key];
    if (options.indexOf(want) >= 0) return want;
    var fb = m.fallback(ctx || {});
    return options.indexOf(fb) >= 0 ? fb : options[0];
  }

  /* ---------- running ---------- */
  /* Every reason an item is hidden, as a list ([] when it is shown by default). */
  function hiddenBy(spec, item, ctx) {
    var why = spec.hidden ? spec.hidden(item, ctx) : null;
    return why ? [].concat(why) : [];
  }
  function allOn(st, keys) {
    return keys.every(function (k) { return (st.inc || []).indexOf(k) >= 0; });
  }
  function visible(spec, st, item, ctx) { return allOn(st, hiddenBy(spec, item, ctx)); }
  function textPasses(spec, st, item) {
    var words = lower(st.q).trim();
    if (!words) return true;
    if (spec.textMatch) return spec.textMatch(item, words);
    var hay = lower(spec.text ? spec.text(item) : '');
    return words.split(/\s+/).every(function (w) { return hay.indexOf(w) >= 0; });
  }
  function facetPasses(spec, st, item, except, ctx) {
    return (spec.facets || []).every(function (facet) {
      if (facet.key === except) return true;
      var chosen = (st.f || {})[facet.key];
      if (!chosen || !chosen.length) return true;
      return chosen.some(function (v) { return facet.match(item, v, ctx); });
    });
  }
  function sorted(list, spec, st, ctx) {
    var s = (spec.sorts || []).filter(function (x) { return x.key === st.sort; })[0] || (spec.sorts || [])[0];
    var at = list.map(function (item, i) { return { item: item, i: i }; });
    if (s && s.cmp) at.sort(function (a, b) { return s.cmp(a.item, b.item, ctx) || a.i - b.i; });
    return at.map(function (x) { return x.item; });
  }
  /* {items, counts: {facet: {value: n}}, values: {facet: [{value,label}]}, incCounts, total}.
     A value's count is what the list would hold with that value chosen and every OTHER
     facet as it is, so a facet's own choice never zeroes its siblings; a value that would
     give nothing is still listed with 0 (the panel dims it, never hides it). */
  function run(items, st, spec, ctx) {
    items = items || [];
    ctx = ctx || {};
    var shown = items.filter(function (it) { return visible(spec, st, it, ctx) && textPasses(spec, st, it); });
    var out = { counts: {}, values: {}, incCounts: {} };
    (spec.facets || []).forEach(function (facet) {
      var base = shown.filter(function (it) { return facetPasses(spec, st, it, facet.key, ctx); });
      var values = valuesOf(facet, items).slice();
      /* a value chosen by hand (typed, or off the URL) is listed even when the data has none */
      ((st.f || {})[facet.key] || []).forEach(function (v) {
        if (!values.some(function (x) { return x.value === v; })) values.push({ value: v, label: v });
      });
      var counts = {};
      values.forEach(function (v) {
        counts[v.value] = base.filter(function (it) { return facet.match(it, v.value, ctx); }).length;
      });
      out.counts[facet.key] = counts;
      out.values[facet.key] = values;
    });
    /* what a switch would ADD: an item it hides whose other reasons are already on */
    (spec.include || []).forEach(function (inc) {
      out.incCounts[inc.key] = items.filter(function (it) {
        var why = hiddenBy(spec, it, ctx);
        return why.indexOf(inc.key) >= 0 && allOn(st, why.filter(function (k) { return k !== inc.key; })) &&
               textPasses(spec, st, it) && facetPasses(spec, st, it, null, ctx);
      }).length;
    });
    out.items = sorted(shown.filter(function (it) { return facetPasses(spec, st, it, null, ctx); }), spec, st, ctx);
    out.total = out.items.length;
    return out;
  }
  /* how many filters are on: each chosen value and each include switch counts once */
  function active(st) {
    var n = (st.inc || []).length;
    Object.keys(st.f || {}).forEach(function (k) { n += (st.f[k] || []).length; });
    return n;
  }

  /* ---------- views: the built-ins and his own ---------- */
  function sameSet(a, b) {
    a = (a || []).slice().sort(); b = (b || []).slice().sort();
    return a.length === b.length && a.every(function (v, i) { return v === b[i]; });
  }
  function sameFilters(a, b) {
    a = copyF(a); b = copyF(b);
    var ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length && ka.every(function (k) { return sameSet(a[k], b[k]); });
  }
  /* A view is a saved {q, f, inc, sort}; the view MODES (layout, group) are left as he has
     them, because a preset says what to look at, not how to lay it out. */
  function viewState(v, spec) {
    var s = v.state || {};
    return { q: s.q || '', f: copyF(s.f), inc: (s.inc || []).slice(), sort: s.sort || blank(spec).sort };
  }
  function matchesView(st, v, spec) {
    var w = viewState(v, spec);
    return (st.q || '') === w.q && sameFilters(st.f, w.f) && sameSet(st.inc, w.inc) && (st.sort || blank(spec).sort) === w.sort;
  }
  function applyView(st, v, spec) {
    var w = viewState(v, spec), out = clone(st);
    out.q = w.q; out.f = w.f; out.inc = w.inc; out.sort = w.sort;
    return out;
  }
  function viewsKey(page) { return 'find.' + page + '.views'; }
  function ownViews(page, store) {
    try {
      var got = JSON.parse(store.get(viewsKey(page)) || '[]');
      if (!Array.isArray(got)) return [];
      return got.filter(function (v) { return v && typeof v.key === 'string' && typeof v.label === 'string' && v.state; })
        .map(function (v) { return { key: v.key, label: v.label, state: v.state, own: true }; });
    } catch (e) { return []; }
  }
  function writeViews(page, list, store) {
    try {
      store.set(viewsKey(page), JSON.stringify(list.map(function (v) { return { key: v.key, label: v.label, state: v.state }; })));
      return true;
    } catch (e) { return false; }
  }
  /* Saved under his name; a name he already used is replaced rather than doubled. */
  function saveView(page, label, st, store) {
    label = String(label || '').trim();
    if (!label) return null;
    var list = ownViews(page, store).filter(function (v) { return lower(v.label) !== lower(label); });
    var view = { key: 'own-' + Date.now().toString(36), label: label,
                 state: { q: st.q || '', f: copyF(st.f), inc: (st.inc || []).slice(), sort: st.sort || '' }, own: true };
    list.push(view);
    return writeViews(page, list, store) ? view : null;
  }
  function deleteView(page, key, store) {
    var list = ownViews(page, store), kept = list.filter(function (v) { return v.key !== key; });
    if (kept.length === list.length) return false;
    return writeViews(page, kept, store);
  }
  function allViews(spec, store) { return (spec.views || []).concat(ownViews(spec.page, store)); }
  /* The view the state IS, when it is one: a built-in first, then his own. The chosen
     preset is therefore carried by the URL without a parameter of its own. */
  function chosen(st, spec, store) {
    return allViews(spec, store).filter(function (v) { return matchesView(st, v, spec); })[0] || null;
  }

  /* ---------- remembered per page ---------- */
  function memKey(page) { return 'find.' + page; }
  function remember(page, st, store) {
    try { store.set(memKey(page), JSON.stringify(clone(st))); } catch (e) { /* kept for this visit only */ }
  }
  function recall(page, spec, store) {
    try {
      var got = JSON.parse(store.get(memKey(page)) || 'null');
      if (!got || typeof got !== 'object') return null;
      var st = blank(spec);
      st.q = typeof got.q === 'string' ? got.q : '';
      st.f = parse(format(got.f || {}, spec), spec).f;
      var incs = includeKeys(spec);
      st.inc = (Array.isArray(got.inc) ? got.inc : []).filter(function (k) { return incs.indexOf(k) >= 0; });
      if (sortKeys(spec).indexOf(got.sort) >= 0) st.sort = got.sort;
      if (got.mode && typeof got.mode === 'object') {
        (spec.modes || []).forEach(function (m) { if (typeof got.mode[m.key] === 'string') st.mode[m.key] = got.mode[m.key]; });
      }
      return st;
    } catch (e) { return null; }
  }

  /* ---------- suggestions under the search field ---------- */
  var SUGGEST_MAX = 8;
  function fields(spec) {
    var out = (spec.facets || []).map(function (f) { return { key: f.key, label: f.label }; });
    if ((spec.include || []).length) out.push({ key: INCLUDE, label: 'Include' });
    return out;
  }
  function fieldValues(spec, found, field) {
    if (field === INCLUDE) {
      return (spec.include || []).map(function (i) { return { value: i.key, label: i.label, count: found.incCounts[i.key] }; });
    }
    return (found.values[field] || []).map(function (v) {
      return { value: v.value, label: v.label, count: (found.counts[field] || {})[v.value] };
    });
  }
  function valueRow(field, v, prefix) {
    return { kind: 'value', field: field, value: v.value, label: v.label, count: v.count,
             insert: field + ':' + (prefix || '') + quote(v.value) };
  }
  /* What to offer for the fragment he is typing (the last piece of the field):
     no colon yet: the FIELDS it starts, then the first such field's values, then any value
     of any field that starts with it; after `field:`: that field's values starting with
     what follows the last comma. Each value carries its count and what it inserts. */
  function suggest(fragment, spec, found) {
    var frag = String(fragment || '');
    if (!frag.trim()) return [];
    var m = /^([A-Za-z][\w-]*):(.*)$/.exec(frag), out = [];
    if (m) {
      var field = fieldOf(spec, m[1]);
      if (!field) return [];
      var parts = m[2].split(','), typed = lower(parts.pop()), before = parts.filter(Boolean);
      var prefix = before.length ? before.join(',') + ',' : '';
      fieldValues(spec, found, field).forEach(function (v) {
        if (before.indexOf(v.value) >= 0) return;
        if (lower(v.value).indexOf(typed) === 0 || lower(v.label).indexOf(typed) === 0) out.push(valueRow(field, v, prefix));
      });
      return out.slice(0, SUGGEST_MAX);
    }
    var low = lower(frag);
    var hits = fields(spec).filter(function (f) { return lower(f.key).indexOf(low) === 0 || lower(f.label).indexOf(low) === 0; });
    hits.forEach(function (f) { out.push({ kind: 'field', field: f.key, label: f.label, insert: f.key + ':' }); });
    if (hits.length) fieldValues(spec, found, hits[0].key).forEach(function (v) { out.push(valueRow(hits[0].key, v)); });
    if (low.length >= 2) {
      fields(spec).forEach(function (f) {
        if (hits.length && f.key === hits[0].key) return;
        fieldValues(spec, found, f.key).forEach(function (v) {
          if (lower(v.value).indexOf(low) === 0 || lower(v.label).indexOf(low) === 0) out.push(valueRow(f.key, v));
        });
      });
    }
    return out.slice(0, SUGGEST_MAX);
  }
  /* The fragment the caret is in: the last piece, unless the text ends in a space. */
  function fragmentOf(text) {
    text = String(text || '');
    if (!text || /\s$/.test(text)) return '';
    var list = pieces(text);
    return list.length ? list[list.length - 1].raw : '';
  }
  /* The text with its last fragment replaced by `insert` (a value ends with a space, so
     the next keystroke lifts it into a token; a field waits for its value). */
  function replaceFragment(text, insert) {
    text = String(text || '');
    var frag = fragmentOf(text), head = frag ? text.slice(0, text.length - frag.length) : text;
    return head + insert + (/:$/.test(insert) ? '' : ' ');
  }

  K.findCore = {
    blank: blank, clone: clone, distinct: distinct, facetOf: facetOf,
    parse: parse, absorb: absorb, format: format, quote: quote, wordsOf: wordsOf,
    toParams: toParams, fromParams: fromParams, PARAMS: PARAMS,
    modeOf: modeOf, run: run, active: active,
    views: allViews, ownViews: ownViews, saveView: saveView, deleteView: deleteView,
    applyView: applyView, chosen: chosen, matchesView: matchesView,
    remember: remember, recall: recall,
    suggest: suggest, fragmentOf: fragmentOf, replaceFragment: replaceFragment, fields: fields
  };
})(window.Keel);
