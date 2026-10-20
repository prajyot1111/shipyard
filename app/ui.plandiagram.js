/* A diagram inside a plan: the board's own drawing, in the plan's look, fitted to the column.
 *
 * A plan's ```mermaid block arrives as board ops (keel/planmermaid.py translated it on the
 * server), and a ```board block arrives as board ops too (inline, or the lines of the board
 * it names). Either way it is folded into the board's model and drawn by the board's own
 * functions (`K.boardDraw`, app/ui.board.js): the same boxes, edges and group titles as the
 * Board route, in the same theme. There is no second renderer and no third-party parser on
 * this origin (decision B2).
 *
 * What is the plan's own (P2-1, round 2) is the LOOK and the FIT, both passed to the
 * board's drawing on the model rather than changed in it, so the board page draws as it
 * always has:
 *
 * - The look (`model.look = 'plan'`, app/ui.planlook.js): labels wrapped whole onto as many
 *   lines as they need, a 13px label, and an icon only where the source names one (a
 *   mermaid diagram gets none).
 * - The fit: three shapes are laid out (as written, folded into rows at the column's shape,
 *   and down) and `K.planLook.chooseForColumn` picks the one that reads best in THIS column.
 *   It is drawn at the column's width, never above natural size and never under a 10px
 *   label. A drawing that cannot reach the floor keeps it and scrolls sideways in its own
 *   frame, with a fade on the side there is more of and a line saying so; it is never cut.
 * - A tap or a click opens it full screen: an embedded board opens the board's own full
 *   screen view (`/board/<id>?full=1`, with its walk and its notes), and an inline diagram
 *   opens a layer drawn by the board's own stage (`K.boardDraw.drawGraph`), with its pan,
 *   zoom and Fit.
 *
 * The host is `data-morph="skip"`: the render pass builds it empty and this module owns
 * what is inside, off the lines' own signature, exactly as the board's stage does. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var MAX_H_SHARE = 0.7, MAX_H = 640;

  function signature(lines) { return lines.join('\n'); }

  function modelOf(lines, icons) {
    var D = K.boardDraw, model = D.foldInto(D.newModel(), lines);
    model.look = 'plan';
    model.icons = icons !== false;
    return model;
  }
  function targetHeight() { return Math.min(MAX_H, Math.round((window.innerHeight || 800) * MAX_H_SHARE)); }

  function draw(host, lines, opts) {
    var D = K.boardDraw;
    if (!D || !K.planLook) return;
    var engine = D.layoutEngine();
    if (!engine) {
      /* ELK is fetched the first time a graph needs it; try again once it has run */
      setTimeout(function () { if (host.isConnected) draw(host, lines, opts); }, 150);
      return;
    }
    var model = modelOf(lines, opts.icons);
    if (!model.nodes.length) { host.textContent = 'this diagram draws nothing'; return; }
    var width = Math.max(200, host.clientWidth || 340), height = targetHeight();
    var started = performance.now();
    Promise.all(K.planLook.candidates(width, height).map(function (c) {
      return D.layoutOnce(engine, model, c.direction, c.aspect).catch(function () { return null; });
    })).then(function (list) {
      list = list.filter(Boolean);
      if (!list.length) throw new Error('no layout');
      var best = K.planLook.chooseForColumn(list, width);
      /* what was weighed, readable from the page (the screenshots and the fixture read it) */
      host._weighed = list.map(function (c) {
        var m = K.planLook.measure(c, width);
        return { shape: c.choice.direction + (c.choice.aspect ? '-folded' : ''), w: Math.round(c.laid.width),
                 h: Math.round(c.laid.height), cost: +c.cost.toFixed(2), scale: +m.scale.toFixed(3),
                 readable: m.readable, drawnH: Math.round(m.drawnH) };
      });
      paint(host, model, best, width);
      host._ms = performance.now() - started;
      host.setAttribute('data-drawn', '1');
      host.setAttribute('data-shape', best.choice.direction + (best.choice.aspect ? '-folded' : ''));
      if (K.plan && K.plan.drawn) K.plan.drawn(host);
    }).catch(function () { host.textContent = 'the layout engine could not draw this'; });
  }

  function paint(host, model, best, width) {
    var D = K.boardDraw, laid = best.laid, box = {}, edges = [];
    D.absolute(laid, 0, 0, box);
    D.edgesAbsolute(laid, 0, 0, edges);
    var w = laid.width || 200, h = laid.height || 120, scale = best.fit.scale;
    var svg = D.svgEl('svg', { class: 'graph pdgraph look-plan', width: Math.ceil(w * scale), height: Math.ceil(h * scale),
      viewBox: '0 0 ' + w + ' ' + h, role: 'img', 'aria-label': model.nodes.map(function (n) { return n.label; }).join(', ') });
    svg.appendChild(D.arrowDefs());
    var stage = D.svgEl('g', { class: 'gstage' });
    svg.appendChild(stage);
    var mirror = {};                  /* the drawing's bookkeeping lives on its host */
    D.drawGroups(stage, model, box);
    D.drawEdges(stage, model, mirror, edges, best.meta);
    D.drawNodes(stage, model, mirror, box);
    D.raiseTitles(stage);
    while (host.firstChild) host.removeChild(host.firstChild);
    host.appendChild(svg);
    var wide = w * scale > width + 1;
    host.classList.toggle('wide', wide);
    host.setAttribute('data-more', wide ? 'x' : 'none');
    host.onscroll = wide ? function () {
      var end = host.scrollLeft + host.clientWidth >= host.scrollWidth - 2;
      host.setAttribute('data-more', end ? 'none' : 'x');
    } : null;
  }

  /* ---------- full screen, for a diagram with no board of its own ---------- */
  var layer = null;
  function closeLayer() {
    if (!layer) return;
    layer.remove();
    layer = null;
    document.removeEventListener('keydown', onKey);
    document.documentElement.classList.remove('pdia-full');
  }
  function onKey(ev) { if (ev.key === 'Escape') closeLayer(); }
  function openLayer(title, lines, icons) {
    closeLayer();
    var D = K.boardDraw, el = K.el;
    var stageHost = el('div', { class: 'pfull-stage kind-graph' });
    var fit = el('button', { class: 'btn sm fitbtn', 'aria-label': 'fit the whole diagram', onclick: function () {
      var svg = stageHost.querySelector('svg');
      if (svg && svg._fit) svg._fit();
    } }, 'Fit');
    layer = el('div', { class: 'pfull', role: 'dialog', 'aria-label': 'the diagram, full screen' },
      el('div', { class: 'pfull-head' },
        el('span', { class: 'pfull-title ellip', text: title || 'Diagram' }), el('span', { class: 'spacer' }), fit,
        el('button', { class: 'btn sm', 'aria-label': 'close full screen', onclick: closeLayer }, 'Close')),
      stageHost);
    document.body.appendChild(layer);
    document.documentElement.classList.add('pdia-full');
    document.addEventListener('keydown', onKey);
    /* the board's own stage: its layout choice for this size, its pan, pinch and Fit */
    requestAnimationFrame(function () { D.drawGraph(stageHost, modelOf(lines, icons), true); });
  }

  /* The host the render pass builds, EMPTY, and the draw it schedules. A host that is still
     drawing the same lines is left alone; a width that changed (a rotate, a resize) draws
     it again. What a tap does rides in `opts` (`board`, `title`, `icons`). */
  function host(key, lines, opts) {
    opts = opts || {};
    var node = K.el('div', { class: 'pdiagram', 'data-key': key, 'data-morph': 'skip', tabindex: '0',
      role: 'button', 'aria-label': 'open this diagram full screen',
      onclick: function () { full(opts, lines); },
      onkeydown: function (ev) { if (ev.key === 'Enter') full(opts, lines); } });
    setTimeout(function () {
      var live = document.querySelector('.pdiagram[data-key="' + key + '"]');
      if (!live) return;
      var sig = signature(lines) + '@' + (live.clientWidth || 0);
      if (live._sig === sig) return;
      live._sig = sig;
      draw(live, lines, opts);
    }, 0);
    return node;
  }
  function full(opts, lines) {
    if (opts.board) { location.href = '/board/' + opts.board + '?full=1' + (opts.upto ? '&upto=' + opts.upto : ''); return; }
    openLayer(opts.title, lines, opts.icons);
  }

  K.planDiagram = { host: host, draw: draw, full: full, closeLayer: closeLayer };
})(window.Keel);
