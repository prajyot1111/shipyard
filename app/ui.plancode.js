/* Code on the plan pages, in colour (lane FC, FC-3): a `code` block, a `diff`, a copy block,
 * and a review finding's lines (app/ui.planfinding.js) all come through here.
 *
 * THE HIGHLIGHTER IS VENDORED AND FETCHED ONLY WHEN A PAGE HAS CODE. highlight.js 11 (its
 * core, and python, javascript with xml for JSX, sql, yaml, json and bash) sits in
 * app/vendor/highlight/, served by the deck like ELK: no CDN at runtime, because the phone
 * may have no route to one. The plan page's shell does not name it; the first code block a
 * render meets asks for it (`need`), draws its lines plain meanwhile, and renders the page
 * again once it is in. A page with no code never fetches a byte of it.
 *
 * NOTHING BECOMES MARKUP. highlight.js answers HTML; that string is never used. Its token
 * tree (`_emitter.rootNode`: text, or `{scope, children}`) is walked and every run of text
 * becomes a text node, in a span whose class names its scope, so a house's code is words
 * the way every other thing it writes is.
 *
 * THE COLOURS are six, each a token of the deck in both space palettes (app/ui.plan.css,
 * `.hl-*`), and each reads at 4.5:1 on the code background, on the diff tints and on a
 * finding's marked line (tests/test_planfinding_render.py measures them).
 */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';
  var el = K.el;

  var BASE = '/vendor/highlight/';
  /* xml first: javascript's JSX leans on it */
  var GRAMMARS = ['xml', 'python', 'javascript', 'sql', 'yaml', 'json', 'bash'];
  var ALIAS = { python: 'python', py: 'python', javascript: 'javascript', js: 'javascript', jsx: 'javascript',
                mjs: 'javascript', cjs: 'javascript', ts: 'javascript', tsx: 'javascript', typescript: 'javascript',
                sql: 'sql', yaml: 'yaml', yml: 'yaml', json: 'json', bash: 'bash', sh: 'bash', shell: 'bash',
                zsh: 'bash', console: 'bash', html: 'xml', xml: 'xml' };
  /* a highlight.js scope's first word, to one of the six colours; anything else is plain */
  var SCOPE = { keyword: 'kw', built_in: 'kw', type: 'kw', tag: 'kw', name: 'kw', 'selector-tag': 'kw',
                'template-tag': 'kw', doctag: 'kw', literal: 'num', number: 'num', bullet: 'num',
                string: 'str', regexp: 'str', symbol: 'str', char: 'str', link: 'str',
                comment: 'com', quote: 'com', meta: 'com', title: 'fn', section: 'fn', 'function': 'fn',
                attr: 'attr', attribute: 'attr', property: 'attr', 'template-variable': 'attr', variable: 'attr' };

  var hl = null, loading = null;
  /* `import()` of a vendored ES module; tests swap it for one that counts */
  var api = { importModule: function (url) { return import(url); } };

  function langOf(name) {
    var key = String(name || '').toLowerCase();
    if (ALIAS[key]) return ALIAS[key];
    var dot = key.lastIndexOf('.');
    return dot >= 0 ? (ALIAS[key.slice(dot + 1).split(':')[0]] || null) : null;
  }
  /* the core and every grammar, once per page; then the page is drawn again */
  function need() {
    if (hl) return Promise.resolve(hl);
    if (loading) return loading;
    loading = api.importModule(BASE + 'core.min.js').then(function (core) {
      var engine = core['default'];
      return GRAMMARS.reduce(function (chain, name) {
        return chain.then(function () {
          return api.importModule(BASE + 'languages/' + name + '.min.js').then(function (mod) {
            engine.registerLanguage(name, mod['default']);
          });
        });
      }, Promise.resolve()).then(function () {
        hl = engine;
        if (K.renderBody) K.renderBody();
        return engine;
      });
    })['catch'](function () { loading = null; return null; });
    return loading;
  }
  function ready() { return hl ? Promise.resolve(hl) : (loading || need()); }

  /* The text as lines of runs `{v, c}` (c: a colour class or ''), or null when it cannot
     be coloured (no language, the highlighter not in yet, or it choked). */
  function runs(text, lang) {
    if (!lang) return null;
    if (!hl) { need(); return null; }
    var result;
    try { result = hl.highlight(text, { language: lang, ignoreIllegals: true }); } catch (e) { return null; }
    var root = result && result._emitter && (result._emitter.rootNode || result._emitter.root);
    if (!root) return null;
    var out = [[]];
    (function walk(node, colour) {
      (node.children || []).forEach(function (child) {
        if (typeof child === 'string') {
          child.split('\n').forEach(function (part, i) {
            if (i) out.push([]);
            if (part) out[out.length - 1].push({ v: part, c: colour });
          });
        } else {
          walk(child, SCOPE[String(child.scope || '').split('.')[0]] || colour);
        }
      });
    })(root, '');
    return out;
  }
  function paint(parts) {
    return parts.map(function (r) { return r.c ? el('span', { class: 'hl-' + r.c, text: r.v }) : document.createTextNode(r.v); });
  }
  function plainRun(line) { return [{ v: line, c: '' }]; }

  /* Lines of code as `.cl` rows: coloured when it can be, with a line number when `first`
     is given and the `mark` bar on the lines from `start` to `end`. */
  function lines(list, lang, opts) {
    opts = opts || {};
    var coloured = runs(list.join('\n'), lang);
    return list.map(function (line, i) {
      var n = opts.first ? opts.first + i : null;
      var marked = n !== null && opts.start && n >= opts.start && n <= (opts.end || opts.start);
      return el('div', { class: 'cl' + (marked ? ' hit' : ''), 'data-key': 'l' + i },
        n !== null ? el('span', { class: 'ln', 'aria-hidden': 'true', text: String(n) }) : null,
        el('span', { class: 'ct' }, paint(coloured && coloured[i] ? coloured[i] : (line ? plainRun(line) : [{ v: ' ', c: '' }]))));
    });
  }
  /* A diff keeps its line tints (added, removed, hunk) UNDER the colours: each line's marker
     stays plain and its content is coloured in the file's language. */
  function diffLines(list, lang) {
    return list.map(function (line, i) {
      var mark = line.charAt(0), hunk = mark === '@', body = hunk ? line : line.slice(1);
      var cls = mark === '+' ? 'add' : mark === '-' ? 'del' : hunk ? 'hunk' : '';
      var coloured = hunk ? null : runs(body, lang);
      return el('div', { class: 'cl ' + cls, 'data-key': 'l' + i },
        hunk ? null : el('span', { class: 'dm', text: mark === '+' || mark === '-' ? mark : ' ' }),
        el('span', { class: 'ct' }, paint(coloured && coloured[0] ? coloured[0] : plainRun(body || ' '))));
    });
  }

  function copyButton(text) {
    return el('button', { class: 'btn sm pcopy', onclick: function (ev) {
      ev.stopPropagation();
      var btn = ev.currentTarget;
      var done = function () { btn.textContent = 'Copied'; setTimeout(function () { btn.textContent = 'Copy'; }, 1400); };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, function () {});
    } }, 'Copy');
  }
  function code(b) {
    var list = String(b.text || '').split('\n'), diff = b.type === 'diff';
    var lang = diff ? langOf(b.path) : (langOf(b.lang) || langOf(b.path));
    return el('div', { class: 'pcode' + (diff ? ' diff' : '') },
      el('div', { class: 'pcode-head' },
        el('span', { class: 'mono t11 ink2', text: b.lang || 'text' }),
        b.path ? el('span', { class: 'mono t11 pcode-path' + (K.plan && K.plan.brokenRef(b.path) ? ' broken' : ''), text: b.path }) : null,
        el('span', { class: 'spacer' }), copyButton(b.text || '')),
      b.why && b.why.length ? el('div', { class: 'pcode-why' }, K.planBlocks.spans(b.why)) : null,
      el('pre', { class: 'pcode-pre' }, el('code', {}, diff ? diffLines(list, lang) : lines(list, lang))));
  }
  function copyBlock(b) {
    return el('div', { class: 'pcode copy' },
      el('div', { class: 'pcode-head' }, el('span', { class: 'label', text: b.title }), el('span', { class: 'spacer' }), copyButton(b.text)),
      el('pre', { class: 'pcode-pre wrap', text: b.text }));
  }

  K.planCode = { code: code, copyBlock: copyBlock, lines: lines, diffLines: diffLines, langOf: langOf,
                 need: need, ready: ready, copyButton: copyButton,
                 get importModule() { return api.importModule; },
                 set importModule(fn) { api.importModule = fn; } };
})(window.Keel);
