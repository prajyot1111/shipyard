/* THE WALK YOU READ: the lit step as a callout from its node (Z1 of lane Z, card c-453).
 *
 * The walk used to show its step as a raw line under the diagram, and his eye had to go
 * from the words at the bottom to the lit node and back. He dropped voiced walks
 * ("lets not overengineer something which will be gimmicky"): the board is looked at when
 * it suits him and the walk is visual, so it has to read on its own. The step's words now
 * FLOW OUT OF THE LIT NODE: a card with a leader line, on the side of the node with room,
 * placed from the laid-out coordinates and placed again on every pan and zoom
 * (`follow`, called from the board's `applyView`).
 *
 * THE CALLOUT NEVER COVERS ITS NODE. It is placed beyond one of the node's four edges or
 * not at all, and where no side has room, where the node is cut by the stage's edge, where
 * the step hangs on the board rather than a node, or where the stage is narrower than
 * `MIN_STAGE` (a phone), the words are a CAPTION BAR along the bottom of the stage instead.
 * `place` is arithmetic on boxes, so `tests/fixtures/board-callout.js` runs it under node.
 *
 * VIEW STATE ONLY (B3). Where the walk is, and what is lit, live on the page state
 * (`K.boardState.step`) and in this layer's DOM. Nothing here can write: no request, no
 * op, no fold. The keyboard steps (the arrows) and leaves (Escape, to the diagram) exactly
 * as the buttons do.
 *
 * Every string goes in with `textContent`, like everything else a board shows.
 */
(function (K) {
  'use strict';

  var MIN_STAGE = 480;      /* narrower than this is a phone's stage: a caption bar */
  var WIDTH = 288;          /* the callout's width, at most */
  var GAP = 24;             /* between the node and the callout: the leader's length */
  var MARGIN = 8;           /* kept clear at the stage's edge */
  var EDGE = 4;             /* a node closer than this to the edge counts as cut by it */
  var SIDES = ['right', 'left', 'below', 'above'];
  var SVGNS = 'http://www.w3.org/2000/svg';

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function overlapArea(a, b) {
    var w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
    var h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
    return w > 0 && h > 0 ? w * h : 0;
  }

  /* One side's box, or null when the callout does not fit there. `room` is what is left
     over on that side once the callout is in, which is how the side with room wins. */
  function sideBox(side, n, stage, w, h) {
    var cx = n.x + n.w / 2, cy = n.y + n.h / 2, box;
    if (side === 'right' || side === 'left') {
      if (h > stage.h - 2 * MARGIN) return null;
      var y = clamp(cy - h / 2, MARGIN, stage.h - MARGIN - h);
      box = { x: side === 'right' ? n.x + n.w + GAP : n.x - GAP - w, y: y, w: w, h: h };
    } else {
      if (w > stage.w - 2 * MARGIN) return null;
      var x = clamp(cx - w / 2, MARGIN, stage.w - MARGIN - w);
      box = { x: x, y: side === 'below' ? n.y + n.h + GAP : n.y - GAP - h, w: w, h: h };
    }
    var room = side === 'right' ? stage.w - MARGIN - (box.x + w)
      : side === 'left' ? box.x - MARGIN
      : side === 'below' ? stage.h - MARGIN - (box.y + h) : box.y - MARGIN;
    return room >= 0 ? { side: side, box: box, room: room } : null;
  }

  /* The leader: from the middle of the node's facing edge to the nearest point of the
     callout's facing edge, kept 12px in from the callout's corners. */
  function leaderOf(side, n, box) {
    var cx = n.x + n.w / 2, cy = n.y + n.h / 2;
    if (side === 'right' || side === 'left') {
      var y2 = clamp(cy, box.y + 12, box.y + box.h - 12);
      var y1 = clamp(y2, n.y + 4, n.y + n.h - 4);
      return side === 'right' ? { x1: n.x + n.w, y1: y1, x2: box.x, y2: y2 }
                              : { x1: n.x, y1: y1, x2: box.x + box.w, y2: y2 };
    }
    var x2 = clamp(cx, box.x + 12, box.x + box.w - 12);
    var x1 = clamp(x2, n.x + 4, n.x + n.w - 4);
    return side === 'below' ? { x1: x1, y1: n.y + n.h, x2: x2, y2: box.y }
                            : { x1: x1, y1: n.y, x2: x2, y2: box.y + box.h };
  }

  /* WHERE THE STEP GOES. `node` is the lit node's box on the SCREEN (the stage's own
     pixels, after the view), `stage` the stage's size, `size` the callout's measured size,
     `others` the other nodes' and the edge labels' screen boxes. A side that would cover
     more of them loses to one that covers less; among the rest the one with the most room wins. */
  function place(spec) {
    var stage = spec.stage, n = spec.node;
    if (!stage || stage.w < MIN_STAGE) return { mode: 'caption', why: 'narrow' };
    if (!n) return { mode: 'caption', why: 'board' };
    if (n.x < EDGE || n.y < EDGE || n.x + n.w > stage.w - EDGE || n.y + n.h > stage.h - EDGE) {
      return { mode: 'caption', why: 'edge' };
    }
    var w = Math.min(spec.size.w || WIDTH, stage.w - 2 * MARGIN), h = spec.size.h;
    var best = null;
    SIDES.forEach(function (side) {
      var got = sideBox(side, n, stage, w, h);
      if (!got) return;
      got.covers = (spec.others || []).reduce(function (sum, o) { return sum + overlapArea(got.box, o); }, 0);
      if (!best || got.covers < best.covers || (got.covers === best.covers && got.room > best.room)) best = got;
    });
    if (!best) return { mode: 'caption', why: 'room' };
    return { mode: 'callout', side: best.side, box: best.box, leader: leaderOf(best.side, n, best.box) };
  }

  /* A box in the stage's coordinates, through the view's one transform. */
  function onScreen(box, view) {
    return { x: view.tx + box.x * view.scale, y: view.ty + box.y * view.scale,
             w: box.w * view.scale, h: box.h * view.scale };
  }

  /* ---------- the layer ----------
   * It lives inside the graph's host, which is `data-morph="skip"`: the render pass never
   * touches it, and the drawing (this) decides what it shows. */
  function nodeBox(el) {
    var t = /translate\(([-\d.]+),([-\d.]+)\)/.exec(el.getAttribute('transform') || '');
    var rect = el.querySelector('rect.card');
    if (!t || !rect) return null;
    return { x: parseFloat(t[1]), y: parseFloat(t[2]),
             w: parseFloat(rect.getAttribute('width')) || 0, h: parseFloat(rect.getAttribute('height')) || 0 };
  }

  function layerOf(host) {
    var layer = host.querySelector(':scope > .wcall-layer');
    if (layer) return layer;
    layer = document.createElement('div');
    layer.className = 'wcall-layer';
    var lead = document.createElementNS(SVGNS, 'svg');
    lead.setAttribute('class', 'wcall-lead');
    var line = document.createElementNS(SVGNS, 'line');
    var dot = document.createElementNS(SVGNS, 'circle');
    dot.setAttribute('r', '4');
    lead.appendChild(line);
    lead.appendChild(dot);
    layer.appendChild(lead);
    var card = document.createElement('div');
    card.className = 'wcall';
    card.setAttribute('role', 'note');
    card.appendChild(document.createElement('div')).className = 'wcall-n';
    card.appendChild(document.createElement('div')).className = 'wcall-text';
    layer.appendChild(card);
    layer.appendChild(captionBar());
    host.appendChild(layer);
    return layer;
  }

  /* The caption bar carries the steppers in full screen, where the phone's sheet starts
     folded and would otherwise leave him no way to step. */
  function captionBar() {
    var bar = document.createElement('div');
    bar.className = 'wcall-caption';
    bar.setAttribute('role', 'note');
    var prev = document.createElement('button');
    prev.className = 'bnav wcall-prev';
    prev.setAttribute('aria-label', 'the step before this one');
    prev.textContent = '‹';
    prev.addEventListener('click', function () { step(-1); });
    var next = document.createElement('button');
    next.className = 'bnav wcall-next';
    next.setAttribute('aria-label', 'the next step');
    next.textContent = '›';
    next.addEventListener('click', function () { step(1); });
    var words = document.createElement('div');
    words.className = 'wcall-words';
    words.appendChild(document.createElement('div')).className = 'wcall-n';
    words.appendChild(document.createElement('div')).className = 'wcall-text';
    bar.appendChild(prev);
    bar.appendChild(words);
    bar.appendChild(next);
    return bar;
  }

  function fill(box, walk) {
    box.querySelector('.wcall-n').textContent = 'Step ' + walk.n + ' of ' + walk.of +
      (walk.label ? ' · ' + walk.label : '');
    box.querySelector('.wcall-text').textContent = walk.text;
  }

  /* Show the host's step: as a callout from its lit node, or as the caption bar. */
  function show(host) {
    var walk = host && host._walk;
    var old = host && host.querySelector(':scope > .wcall-layer');
    if (!walk) { if (old) old.remove(); return; }
    var wrap = host.querySelector('.graphwrap');
    var svg = wrap && wrap.querySelector('svg');
    if (!wrap || !svg || !svg._view) return;
    var layer = layerOf(host), card = layer.querySelector('.wcall'),
        bar = layer.querySelector('.wcall-caption'), lead = layer.querySelector('.wcall-lead');
    var stage = { w: wrap.clientWidth, h: wrap.clientHeight };
    var lit = null, others = [];
    Array.prototype.forEach.call(host.querySelectorAll('.gnode'), function (el) {
      var b = nodeBox(el);
      if (!b) return;
      if (el.getAttribute('data-nid') === host._focus) lit = onScreen(b, svg._view);
      else others.push(onScreen(b, svg._view));
    });
    /* an edge's label is words too: a callout over it hides what the edge says */
    Array.prototype.forEach.call(host.querySelectorAll('rect.elabel'), function (r) {
      others.push(onScreen({ x: +r.getAttribute('x'), y: +r.getAttribute('y'),
                             w: +r.getAttribute('width'), h: +r.getAttribute('height') }, svg._view));
    });
    fill(card, walk);
    fill(bar, walk);
    card.style.width = Math.min(WIDTH, Math.max(0, stage.w - 2 * MARGIN)) + 'px';
    card.hidden = false;
    var got = place({ node: lit, stage: stage, size: { w: WIDTH, h: card.offsetHeight }, others: others });
    layer.setAttribute('data-mode', got.mode);
    layer.classList.toggle('nav', !!walk.nav);
    bar.querySelector('.wcall-prev').disabled = walk.n <= 1;
    bar.querySelector('.wcall-next').disabled = walk.n >= walk.of;
    if (got.mode !== 'callout') { card.hidden = true; bar.hidden = false; lead.style.display = 'none'; return; }
    bar.hidden = true;
    card.style.left = got.box.x + 'px';
    card.style.top = got.box.y + 'px';
    card.setAttribute('data-side', got.side);
    lead.style.display = '';
    var line = lead.querySelector('line'), dot = lead.querySelector('circle');
    line.setAttribute('x1', got.leader.x1); line.setAttribute('y1', got.leader.y1);
    line.setAttribute('x2', got.leader.x2); line.setAttribute('y2', got.leader.y2);
    dot.setAttribute('cx', got.leader.x1); dot.setAttribute('cy', got.leader.y1);
  }

  /* Every pan and zoom goes through the board's `applyView`, which calls this with the
     stage it moved; a host with no walk on it is left alone. */
  function follow(stageEl) {
    var host = stageEl && stageEl.closest ? stageEl.closest('.kind-graph') : null;
    if (host && host._walk) show(host);
  }

  /* ---------- stepping ----------
   * The same move as the buttons: the page state's `step`, and a render. Never a request. */
  function walking() {
    var I = K.boardInner, B = K.boardState;
    return !!(I && B && B.open && K.App && K.App.view === 'board' && K.App.board &&
              I.viewOf() === 'walk');
  }
  function step(delta) {
    var I = K.boardInner, B = K.boardState;
    if (!I || !B || !B.open) return false;
    var count = I.stepsOf(B.open.model).length;
    var to = clamp((B.step || 0) + delta, 0, Math.max(0, count - 1));
    if (to === B.step) return true;
    B.step = to;
    K.renderBody();
    return true;
  }

  var KEYS = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
  function onKey(ev) {
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if (!(ev.key in KEYS) && ev.key !== 'Escape') return;
    var t = ev.target, tag = t && t.tagName ? t.tagName.toLowerCase() : '';
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || (t && t.isContentEditable)) return;
    if (!walking()) return;
    ev.preventDefault();
    if (ev.key === 'Escape') { K.boardInner.setView('diagram'); return; }
    step(KEYS[ev.key]);
  }
  document.addEventListener('keydown', onKey);

  K.boardCallout = { place: place, onScreen: onScreen, show: show, follow: follow, step: step,
                     MIN_STAGE: MIN_STAGE, WIDTH: WIDTH, GAP: GAP };
})(window.Keel);
