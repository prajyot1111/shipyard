/* THE PLAN LOOK: how a diagram in a plan or an outcome is sized, drawn and laid out (P2-1).
 *
 * A diagram in a plan is drawn by the board's own functions (`K.boardDraw`, B2: one
 * renderer), but a plan page is not the board page. The board's look is for a stage he pans
 * and zooms: 15px labels, a 24px icon on every node, a label CUT with an ellipsis at 184px
 * and the rest on hover. In a document he scrolls that read as bulky and cut off (round 2,
 * 2026-09-24): labels he could not read without a hover, the same box icon on every mermaid
 * node, a long flowchart drawn as a narrow tower, and a wide board clipped on the right.
 *
 * So the plan passes a LOOK on the model (`model.look = 'plan'`) and the board's drawing
 * asks this file for three things when it sees one: a node's size, how to paint a node, and
 * an edge label's size and text. A model with no look (every board on the board page) never
 * reaches this file, so the board page draws exactly as before.
 *
 * - Labels WRAP onto as many lines as they need, and the box is sized to its text: no
 *   ellipsis anywhere on a plan page. A word longer than the box (a path) breaks after a
 *   `/`, `_` or `.`, and only then anywhere.
 * - A smaller font: 13px labels, 11px sub labels and edge labels.
 * - An icon only where the SOURCE names one: a mermaid diagram gets none (`model.icons =
 *   false`), and on a board `box` (the grammar's fallback for "no icon") is drawn as none.
 * - The layout is chosen for the COLUMN (`chooseForColumn`): scaled to its width, never
 *   above natural size, with a floor on the font; among the layouts readable at that floor
 *   and nearly as easy to follow as the best, the shortest wins, so a long chain is folded
 *   into rows on a wide column rather than drawn as a tower.
 *
 * Everything but `paintNode` and `paintEdgeLabel` is pure, so tests/fixtures/plan-diagram.js
 * runs it under node against the real vendored ELK.
 */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var SANS = '-apple-system, BlinkMacSystemFont, Inter, system-ui, sans-serif';
  var MONO = 'ui-monospace, "SF Mono", Menlo, monospace';
  var LABEL = 13, LABEL_LINE = 17, SUB = 11, SUB_LINE = 14, EDGE = 11, EDGE_LINE = 14;
  var PAD_X = 12, PAD_Y = 10, ICON = 16, ICON_GAP = 6;
  var MIN_W = 64, MAX_W = 176, EDGE_MAX_W = 152;
  /* The font floor: a 13px label is never drawn under 10px. Below that the drawing keeps
     the floor and scrolls sideways inside its own frame, with a cue, and is never clipped. */
  var FONT_FLOOR = 10;
  var SCALE_FLOOR = FONT_FLOOR / LABEL;

  function width(text, size, family) { return K.board.textWidth(text, size, family); }

  /* ---------- wrapping ---------- */
  /* A word too wide for the box is broken where it can be read: after a path's `/`, a
     name's `_` or a file's `.`, and only when none of those is left, anywhere. */
  function breakWord(word, room, size, family) {
    var out = [], rest = word;
    while (rest && width(rest, size, family) > room) {
      var cut = 0;
      for (var i = 1; i < rest.length; i++) {
        if (width(rest.slice(0, i + 1), size, family) > room) break;
        if ('/_.-:'.indexOf(rest.charAt(i)) >= 0) cut = i + 1;
      }
      if (!cut) {
        cut = 1;
        while (cut < rest.length && width(rest.slice(0, cut + 1), size, family) <= room) cut++;
      }
      out.push(rest.slice(0, cut));
      rest = rest.slice(cut);
    }
    if (rest) out.push(rest);
    return out;
  }
  function wrap(text, room, size, family) {
    var words = String(text === null || text === undefined ? '' : text).split(/\s+/).filter(Boolean);
    var lines = [], line = '';
    words.forEach(function (word) {
      var next = line ? line + ' ' + word : word;
      if (width(next, size, family) <= room) { line = next; return; }
      if (line) lines.push(line);
      if (width(word, size, family) <= room) { line = word; return; }
      var parts = breakWord(word, room, size, family);
      line = parts.pop();
      parts.forEach(function (p) { lines.push(p); });
    });
    if (line) lines.push(line);
    return lines.length ? lines : [''];
  }

  /* ---------- a node ---------- */
  function hasIcon(model, n) { return model.icons !== false && !!n.icon && n.icon !== 'box'; }
  function nodeText(model, n) {
    var room = MAX_W - 2 * PAD_X;
    var label = wrap(n.label, room, LABEL, SANS), sub = n.sub ? wrap(n.sub, room, SUB, MONO) : [];
    var widest = 0;
    label.forEach(function (l) { widest = Math.max(widest, width(l, LABEL, SANS)); });
    sub.forEach(function (l) { widest = Math.max(widest, width(l, SUB, MONO)); });
    return { label: label, sub: sub, widest: widest, icon: hasIcon(model, n) };
  }
  function nodeSize(model, n) {
    var t = nodeText(model, n);
    var w = Math.max(MIN_W, Math.min(MAX_W, Math.ceil((t.widest + 2 * PAD_X) / 4) * 4));
    var h = PAD_Y * 2 + (t.icon ? ICON + ICON_GAP : 0) + t.label.length * LABEL_LINE +
            (t.sub.length ? 2 + t.sub.length * SUB_LINE : 0);
    return { width: w, height: Math.ceil(h / 4) * 4 };
  }
  function lines(text, parent, x, y, step, cls) {
    text.forEach(function (line, i) {
      var span = K.boardDraw.svgEl('tspan', { x: x, y: y + i * step });
      span.textContent = line;
      if (cls) span.setAttribute('class', cls);
      parent.appendChild(span);
    });
  }
  /* The board made the node's elements (title, card, icon group, label, sub); this fills
     them in the plan's look, every line whole. */
  function paintNode(model, node, n, at) {
    var t = nodeText(model, n), D = K.boardDraw;
    var icon = node.querySelector('.gicon');
    while (icon.firstChild) icon.removeChild(icon.firstChild);
    var y = PAD_Y;
    if (t.icon) {
      icon.setAttribute('fill', 'none');
      icon.setAttribute('stroke', 'currentColor');
      icon.setAttribute('stroke-width', '2');
      icon.setAttribute('stroke-linecap', 'round');
      icon.setAttribute('stroke-linejoin', 'round');
      icon.setAttribute('transform', 'translate(' + (at.width / 2 - ICON / 2) + ',' + y + ') scale(' + (ICON / 24) + ')');
      D.iconShapes(n.icon).forEach(function (shape) { icon.appendChild(shape); });
      y += ICON + ICON_GAP;
    }
    var label = node.querySelector('text.lbl'), sub = node.querySelector('text.sub');
    label.textContent = '';
    label.removeAttribute('y');
    lines(t.label, label, at.width / 2, y + LABEL - 2, LABEL_LINE);
    y += t.label.length * LABEL_LINE;
    sub.textContent = '';
    if (t.sub.length) {
      sub.removeAttribute('hidden');
      lines(t.sub, sub, at.width / 2, y + 2 + SUB - 1, SUB_LINE);
    } else sub.setAttribute('hidden', '');
  }

  /* ---------- an edge's label ---------- */
  function edgeLines(text) { return wrap(text, EDGE_MAX_W - 16, EDGE, MONO); }
  function edgeLabelSize(text) {
    var list = edgeLines(text), widest = 0;
    list.forEach(function (l) { widest = Math.max(widest, width(l, EDGE, MONO)); });
    return { width: Math.ceil(widest) + 12, height: list.length * EDGE_LINE + 6 };
  }
  function paintEdgeLabel(textNode, label, x, y) {
    textNode.textContent = '';
    textNode.removeAttribute('y');
    lines(edgeLines(label.text), textNode, x + label.width / 2, y + 3 + EDGE, EDGE_LINE);
  }

  /* ---------- the layout, chosen for the column ---------- */
  /* What each laid-out candidate is drawn at in a column `innerW` wide: fitted to the
     width, never above natural size, never under the font floor. */
  function scaleFor(w, innerW) { return Math.min(1, innerW / w); }
  function measure(c, innerW) {
    var w = c.laid.width || 200, h = c.laid.height || 120;
    var fit = scaleFor(w, innerW);
    var scale = Math.max(SCALE_FLOOR, fit);
    return { readable: fit >= SCALE_FLOOR, scale: scale, drawnW: w * scale, drawnH: h * scale };
  }
  /* HOW A COLUMN CHOOSES. The candidates are `{laid, meta, cost, choice}` as
     `K.boardDraw.layoutOnce` answers them.
     1. Readable at the font floor comes first: a layout that must scroll sideways loses to
        one that fits the column.
     2. Among the readable ones, only those within `COST_SLACK` of the cheapest are kept: an
        edge routed round the outside (30) never gets in, two crossings or a fold's bends do.
     3. Of those the SHORTEST drawn wins, and within `HEIGHT_TIE` of it the cheaper. A long
        chain folded into rows is shorter than the same chain as a tower, which is the
        tower he pointed at; a board that only reads down stays down.
     When none is readable, the one that needs the least sideways scroll wins. */
  var COST_SLACK = 12, HEIGHT_TIE = 0.1;
  function chooseForColumn(list, innerW) {
    var rows = list.map(function (c) { return { c: c, m: measure(c, innerW) }; });
    var readable = rows.filter(function (r) { return r.m.readable; });
    if (!readable.length) {
      rows.sort(function (a, b) { return a.m.drawnW - b.m.drawnW || a.c.cost - b.c.cost; });
      return Object.assign({ fit: rows[0].m }, rows[0].c);
    }
    var cheapest = Math.min.apply(null, readable.map(function (r) { return r.c.cost; }));
    var near = readable.filter(function (r) { return r.c.cost <= cheapest + COST_SLACK; });
    near.sort(function (a, b) {
      var tall = Math.max(a.m.drawnH, b.m.drawnH) || 1;
      if (Math.abs(a.m.drawnH - b.m.drawnH) / tall > HEIGHT_TIE) return a.m.drawnH - b.m.drawnH;
      return a.c.cost - b.c.cost;
    });
    return Object.assign({ fit: near[0].m }, near[0].c);
  }
  /* Which layouts are worth trying in a column: as written (RIGHT), folded into rows at two
     shapes (about as tall as the screen allows, and half that), and DOWN. Four ELK runs on
     at most twelve nodes. */
  function candidates(innerW, innerH) {
    var h = Math.max(200, innerH);
    return [{ direction: 'RIGHT', aspect: 0 }, { direction: 'RIGHT', aspect: innerW / h },
            { direction: 'RIGHT', aspect: innerW / (h / 2) }, { direction: 'DOWN', aspect: 0 }];
  }

  K.boardLooks = K.boardLooks || {};
  K.boardLooks.plan = { nodeSize: nodeSize, paintNode: paintNode, edgeLabelSize: edgeLabelSize,
                        paintEdgeLabel: paintEdgeLabel };
  K.planLook = { wrap: wrap, nodeText: nodeText, nodeSize: nodeSize, edgeLabelSize: edgeLabelSize,
                 chooseForColumn: chooseForColumn, candidates: candidates, measure: measure,
                 SCALE_FLOOR: SCALE_FLOOR, FONT_FLOOR: FONT_FLOOR, LABEL: LABEL, MAX_W: MAX_W, PAD_X: PAD_X,
                 SANS: SANS, MONO: MONO };
})(window.Keel);
