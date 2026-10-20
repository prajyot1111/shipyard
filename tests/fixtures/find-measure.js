/* What `bin/keel-find-audit` asks a real browser, on the deck's real page: is any text in
 * the find bar's controls clipped or overflowing, is anything wider than the screen, and
 * does the bar keep the design budgets (sizes, weights, the 4px grid, 44px targets on the
 * phone). Evaluated as one expression by the browser tool's `eval`, which awaits it.
 *
 * It opens every surface the bar has in turn (the Filter panel or sheet, Sort, View,
 * Views and its save form, the suggestion list) and measures each one open, with the
 * filters the audit put in the URL applied. Every control counts: a button, a menu item,
 * a token, a facet row, a suggestion row. A control fails when
 *   - its own content is wider than it (`scrollWidth > clientWidth`), or
 *   - any box inside it reaches past its edges, or
 *   - it ellipsises text without its full text in a title (the one designed ellipsis, a
 *     token's value, carries it), or
 *   - on the phone, it is under 44px either way.
 * The page fails when the document or the #body scroller is wider than the window.
 */
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function until(fn, ms) {
    const t = Date.now();
    while (Date.now() - t < (ms || 5000)) { const v = fn(); if (v) return v; await sleep(50); }
    return null;
  }
  const host = await until(() => document.querySelector('.find'));
  if (!host) return JSON.stringify({ error: 'no find bar on ' + location.href });
  const page = host.getAttribute('data-find');
  const phone = innerWidth < 900;
  const CONTROLS = ['.find-btn', '.find-item', '.find-token', '.find-row', '.find-sugrow', '.find-clearall',
                    '.find-show', '.find-clear', '.find-close', '.find-del', '.find-savebtn', '.find-now'].join(',');
  const TARGETS = CONTROLS.replace(',.find-now', '') + ',.find input';

  function desc(el, why) {
    const text = (el.getAttribute('title') || el.textContent || '').trim().slice(0, 40);
    return (el.className || el.tagName).toString().split(' ')[0] + ' "' + text + '": ' + why;
  }
  function inside(c, r) {
    const b = c.getBoundingClientRect();
    if (!b.width && !b.height) return true;
    return b.left >= r.left - 1 && b.right <= r.right + 1 && b.top >= r.top - 1 && b.bottom <= r.bottom + 1;
  }
  function scrolled(el) {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      if (p.id === 'body') return false;
      if (/(auto|scroll)/.test(getComputedStyle(p).overflowX)) return true;
    }
    return false;
  }
  function controls(out) {
    document.querySelectorAll(CONTROLS).forEach((el) => {
      if (!el.getClientRects().length) return;
      out.controls++;
      const r = el.getBoundingClientRect();
      if (el.scrollWidth > el.clientWidth + 1) out.overflow.push(desc(el, el.scrollWidth + ' > ' + el.clientWidth));
      /* a control inside a sideways scroller (the phone's token line) may sit past the
         window: the scroller is what is measured against the window, as #body is */
      if ((r.right > innerWidth + 1 || r.left < -1) && !scrolled(el)) out.overflow.push(desc(el, 'past the window edge'));
      el.querySelectorAll('*').forEach((c) => {
        if (!inside(c, r)) out.clipped.push(desc(el, 'a child reaches past its edge'));
        const cs = getComputedStyle(c);
        if (c.scrollWidth > c.clientWidth + 1 && cs.textOverflow === 'ellipsis' && !el.getAttribute('title')) {
          out.clipped.push(desc(el, 'text cut with no title'));
        }
      });
    });
    if (phone) {
      document.querySelectorAll(TARGETS).forEach((el) => {
        if (!el.getClientRects().length) return;
        const r = el.getBoundingClientRect();
        if (r.height < 44 || r.width < 44) out.small.push(desc(el, Math.round(r.width) + 'x' + Math.round(r.height)));
      });
    }
  }
  /* the design budgets, over the bar and everything it opens */
  function budget(out) {
    const sizes = {}, weights = {}, off = [];
    const PROPS = ['paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'marginTop', 'marginRight',
                   'marginBottom', 'marginLeft', 'rowGap', 'columnGap'];
    document.querySelectorAll('.find, .find *').forEach((el) => {
      if (!el.getClientRects().length) return;
      const cs = getComputedStyle(el);
      let own = '';
      el.childNodes.forEach((n) => { if (n.nodeType === 3) own += n.textContent.trim(); });
      if (own) { sizes[cs.fontSize] = 1; weights[cs.fontWeight] = 1; }
      PROPS.forEach((p) => {
        const m = /^(-?[\d.]+)px$/.exec(cs[p]);
        if (!m) return;
        const v = Math.abs(parseFloat(m[1]));
        if (v && v > 3 && v % 4 !== 0) off.push(desc(el, p + ' ' + cs[p]));
      });
    });
    out.sizes = Object.keys(sizes).sort();
    out.weights = Object.keys(weights).sort();
    out.offGrid = off.slice(0, 10);
    out.offGridCount = off.length;
  }
  function measure(name) {
    const out = { name, controls: 0, overflow: [], clipped: [], small: [] };
    controls(out);
    budget(out);
    out.doc = document.documentElement.scrollWidth - innerWidth;
    const body = document.getElementById('body');
    out.body = body ? body.scrollWidth - body.clientWidth : 0;
    return out;
  }
  function escape() { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); }
  async function openThen(what, name, ready) {
    const btn = document.getElementById('find-' + page + '-' + what + '-btn');
    if (!btn) return null;
    btn.click();
    await until(ready || (() => document.getElementById('find-' + page + '-' + what)), 3000);
    await sleep(150);
    const got = measure(name);
    return got;
  }

  const results = [measure('bar with tokens')];
  results.push(await openThen('filter', phone ? 'filter sheet' : 'filter panel'));
  escape(); await sleep(150);
  results.push(await openThen('sort', 'sort menu'));
  escape(); await sleep(150);
  const view = await openThen('view', 'view menu');
  if (view) results.push(view);
  escape(); await sleep(150);
  results.push(await openThen('views', 'views menu'));
  const save = document.querySelector('.find-save');
  if (save) {
    save.click();
    await until(() => document.querySelector('.find-saveform'), 2000);
    await sleep(100);
    results.push(measure('views save form'));
  }
  escape(); await sleep(150);
  const input = document.getElementById('find-' + page + '-search');
  input.focus();
  input.value = 'sta';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  await until(() => document.querySelector('.find-sug'), 2000);
  await sleep(100);
  results.push(measure('suggestions'));
  return JSON.stringify({ page, width: innerWidth, height: innerHeight, results: results.filter(Boolean) });
})()
