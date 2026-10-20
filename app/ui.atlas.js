/* The Atlas route: the repo's own documentation, read on the deck.
 *
 * Two fetches, both cached for the life of the tab: `/api/atlas` is the page list and
 * `/api/atlas/<slug>` is one page already rendered to HTML by the server (the same
 * markdown renderer a card's context file goes through). The page is documentation, not
 * live state, so it is fetched once and never refetched. Neither scroller here is thrown
 * back to the top by a redraw either: the render pass morphs, so the list and the reader
 * are the same nodes from one pass to the next and hold their own offsets.
 *
 * `?view=atlas&page=<slug>` is the whole route, so every page is a link the human can send
 * himself, and a link from one page to the next is rewritten server side to that shape.
 *
 * The document's own styles are injected once, scoped under `.atlas-doc`, because the
 * deck's stylesheet deliberately strips margins and list markers from bare elements and
 * the server hands back bare elements. Every value is one of the deck's own tokens, so
 * the palette follows the space switch like everything else. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el;
  var pages = null, loading = false;
  var docs = {};                 /* slug -> {title, html} */
  var wanted = null;             /* the slug a fetch is in flight for */

  var STYLE = [
    '.atlas{display:flex;gap:12px;flex:1;min-height:0}',
    '.atlas-list{width:232px;flex:0 0 232px;overflow:auto;display:flex;flex-direction:column;gap:2px}',
    '.atlas-item{display:block;width:100%;padding:8px;border-radius:var(--r);color:var(--ink-2)}',
    '.atlas-item:hover{background:var(--s2);color:var(--ink)}',
    '.atlas-item.on{background:var(--s2);color:var(--ink);box-shadow:inset 2px 0 0 var(--accent)}',
    '.atlas-item .t{display:block;font-size:13px;font-weight:600}',
    '.atlas-item .s{display:block;font-size:11px;color:var(--ink-3);margin-top:2px}',
    '.atlas-item.gone .t{color:var(--crit)}',
    '.atlas-read{flex:1;min-width:0;overflow:auto;border-left:1px solid var(--hair);padding-left:14px}',
    '.atlas-doc{max-width:760px}',
    '.atlas-doc h1{font-size:15px;font-weight:600;letter-spacing:-.02em;margin:0 0 10px}',
    '.atlas-doc h2{font-size:13px;font-weight:600;margin:20px 0 6px;padding-top:10px;border-top:1px solid var(--hair)}',
    '.atlas-doc h3{font-size:13px;font-weight:600;color:var(--ink-2);margin:14px 0 4px}',
    '.atlas-doc p{margin:0 0 10px;color:var(--ink-2)}',
    '.atlas-doc ul,.atlas-doc ol{margin:0 0 10px;padding-left:18px;color:var(--ink-2)}',
    '.atlas-doc ul{list-style:disc}.atlas-doc ol{list-style:decimal}',
    '.atlas-doc li{margin:3px 0}',
    '.atlas-doc strong{color:var(--ink);font-weight:600}',
    '.atlas-doc code{font-family:var(--mono);font-size:11px;background:var(--s3);padding:1px 4px;color:var(--ink)}',
    '.atlas-doc pre{background:var(--s2);border:1px solid var(--hair);padding:10px;overflow-x:auto;margin:0 0 10px}',
    '.atlas-doc pre code{background:transparent;padding:0;color:var(--ink-2);line-height:1.5}',
    '.atlas-doc hr{border:0;border-top:1px solid var(--hair);margin:14px 0}',
    '.atlas-doc table{border-collapse:collapse;width:100%;margin:0 0 12px;font-size:11px}',
    '.atlas-doc th,.atlas-doc td{border:1px solid var(--hair);padding:6px 8px;text-align:left;vertical-align:top;color:var(--ink-2)}',
    '.atlas-doc th{background:var(--s2);color:var(--ink);font-weight:600;white-space:nowrap}',
    '.atlas-doc .tablewrap{overflow-x:auto;margin:0 0 12px}',
    '.atlas-doc .tablewrap table{margin:0}',
    '.atlas-doc img{display:block;max-width:100%;height:auto;border:1px solid var(--hair);margin:0 0 10px}',
    '.atlas-doc .unserved{color:var(--ink-2);border-bottom:1px dotted var(--hair-hi)}',
    /* A link in a sentence cannot be 44px TALL without wrecking the line, but vertical
       padding on an inline element grows its HIT BOX and leaves the line where it is: an
       11px line at 1.5 plus 14px on each side measures 44.5. That holds inside a table cell
       too, and the block a cell used to get instead (`display:inline-block;line-height:44px`)
       cut the sentence it sat in into three stacked pieces with blank lines through it. One
       rule for every link in the document. */
    '@media (max-width:899px){.atlas-doc a{padding:16px 4px;margin:0 -4px}',
    /* The padding above grows the hit box past the LINE box, which in a 6px-padded table
       cell means it grows past the cell's border too. The cell gives it the room instead:
       16px of its own padding takes the first and last line's overhang, and a taller line
       keeps the middle ones off each other. */
    '  .atlas-doc td,.atlas-doc th{padding:16px 8px;line-height:2}}',
    '@media (max-width:899px){.atlas{flex-direction:column}',
    '  .atlas-list{width:auto;flex:0 0 auto;max-height:none;overflow:visible}',
    '  .atlas-read{border-left:0;border-top:1px solid var(--hair);padding-left:0;padding-top:12px;overflow:visible}',
    '  .atlas-item{min-height:44px}}'
  ].join('\n');

  function styleOnce() {
    if (document.getElementById('atlas-style')) return;
    var node = document.createElement('style');
    node.id = 'atlas-style';
    node.textContent = STYLE;
    document.head.appendChild(node);
  }

  /* The list and a page are fetched once each and kept: documentation does not change
     under the reader, and a refetch on every poll would be noise on the wire. */
  function loadPages() {
    if (pages || loading) return;
    loading = true;
    fetch('/api/atlas', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (d) {
      loading = false;
      pages = d.pages || [];
      K.renderBody();
    }).catch(function () { loading = false; pages = []; K.renderBody(); });
  }
  function loadPage(slug) {
    if (docs[slug] || wanted === slug) return;
    wanted = slug;
    fetch('/api/atlas/' + encodeURIComponent(slug), { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        wanted = null;
        docs[slug] = d.error ? { title: slug, html: '', error: d.error } : d;
        K.renderBody();
      })
      .catch(function (e) { wanted = null; docs[slug] = { title: slug, html: '', error: e.message }; K.renderBody(); });
  }

  /* The desk shows a page beside the list, so it always has one open: the asked-for page,
     or the first. The phone shows one thing at a time, list or page, so no page is asked
     for means the list, which is what makes a page a route the dock's Back walks out of. */
  function currentSlug() {
    var asked = new URLSearchParams(location.search).get('page');
    if (!pages || !pages.length) return asked || null;
    for (var i = 0; i < pages.length; i++) if (pages[i].slug === asked) return asked;
    return K.isDesk() ? pages[0].slug : null;
  }
  /* Its own history entry, so Back walks the pages read and the link is sendable. The
     page scroll is reset because a new document starts at its own top; each slug builds
     its own reader (`data-key` carries the slug), so the desk's pane is a new node already
     at zero and only the phone, where the whole body scrolls, needs saying. */
  function open(slug) {
    var q = new URLSearchParams();
    q.set('view', 'atlas');
    q.set('page', slug);
    history.pushState(null, '', '?' + q.toString());
    loadPage(slug);
    K.renderBody();
    document.getElementById('body').scrollTop = 0;
  }
  K.openAtlasPage = open;

  function listOf(slug) {
    return el('nav', { class: 'atlas-list', 'data-key': 'atlas-list' }, pages.map(function (p) {
      return el('button', {
        class: 'atlas-item' + (p.slug === slug ? ' on' : '') + (p.present ? '' : ' gone'),
        'data-key': p.slug, onclick: function () { open(p.slug); }
      }, el('span', { class: 't', text: p.title }),
         el('span', { class: 's', text: p.present ? p.summary : 'listed, but the file is missing' }));
    }));
  }

  function readerOf(slug) {
    var doc = docs[slug];
    var inner;
    if (!slug) inner = el('div', { class: 'empty', text: 'the atlas has no pages' });
    else if (!doc) inner = el('div', { class: 'empty', text: 'reading ' + slug + '...' });
    else if (doc.error) inner = el('div', { class: 'empty', text: doc.error });
    /* The HTML is this server's own render of a file in this repo, escaped by the same
       renderer the card views use; there is no path by which a browser puts markup here. */
    else inner = el('article', { class: 'atlas-doc', html: doc.html });
    return el('div', { class: 'atlas-read', 'data-key': 'atlas-read-' + (slug || 'none') }, inner);
  }

  function viewAtlas() {
    styleOnce();
    loadPages();
    if (!pages) return el('div', { class: 'empty', text: 'reading the atlas...' });
    var desk = K.isDesk(), slug = currentSlug();
    if (slug) loadPage(slug);
    var doc = slug ? docs[slug] : null;
    var title = doc && !doc.error ? doc.title : (slug || '');
    var inner;
    if (!pages.length) inner = el('div', { class: 'empty', text: 'the atlas index lists no pages' });
    else if (desk) inner = el('div', { class: 'atlas' }, listOf(slug), readerOf(slug));
    else inner = el('div', { class: 'atlas' }, slug ? readerOf(slug) : listOf(slug));
    return el('section', { class: 'panel grow' },
      el('div', { class: 'panel-head' },
        !desk && slug ? el('button', { class: 'btn sm', onclick: function () { K.go('atlas'); } }, '‹ pages')
          : el('span', { class: 'label', text: 'Atlas · ' + pages.length + ' pages' }),
        el('span', { class: 'spacer' }),
        el('span', { class: 'mono t11 ink2', text: title })),
      el('div', { class: 'panel-body' }, inner));
  }

  K.viewAtlas = viewAtlas;

  /* The phone reaches the Atlas under More. This decorates `viewMore` rather than editing
     it, because the dock has no room for a sixth item and the Atlas is not an adapter
     route, which is the only kind More lists on its own. The modules read a name at call
     time, so this holds whatever ui.views.js does with its own. */
  var baseMore = K.viewMore;
  K.viewMore = function () {
    var out = baseMore ? baseMore() : [];
    if (!Array.isArray(out)) out = [out];
    out.splice(1, 0, el('section', { class: 'panel' },
      el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'Documentation' })),
      el('div', { class: 'panel-body' },
        el('button', { class: 'row', onclick: function () { K.go('atlas'); } },
          el('div', { class: 'row-head' }, el('span', { class: 't', text: 'Atlas' }),
            el('span', { class: 'spacer' }),
            el('span', { class: 'mono t11 ink3', text: 'how all of this works' }))))));
    return out;
  };
})(window.Keel);
