/* HOW READABLE A LAID-OUT BOARD IS, and which of two layouts is drawn (K1 to K3, 2026-09-24).
 *
 * `layoutBest` in ui.board.js used to score a layout only on whether it FIT the stage, and
 * tried DOWN only when the folded RIGHT layout did not. A wide full-screen stage let a folded
 * layout of three groups fit, so DOWN was never tried, and every edge between the groups was
 * routed in a long loop around the whole drawing: it fit, and nobody could follow it. So fit
 * is the GATE and readability is the CHOICE. Both candidates are laid out, the ones that fit
 * readably (W4's floor) are kept, and among those the one with the lowest cost here is drawn.
 *
 * Everything in this file is pure: it reads an ELK result (plain objects) and numbers, and it
 * draws nothing, so `tests/fixtures/board-layout.js` runs it under node against the real
 * vendored ELK.
 */
(function (K) {
  'use strict';

  /* How far an edge may stray past the box around its two ends before it counts as routed
     AROUND the drawing: 48px, or a fifth of the drawing's longer side if that is more. ELK's
     own detours for a port on the far side are 12 to 30px, and a fold's wrap edge steps one
     lane past the end of its row (about 100px in W1's chain, whose rows read as a snake);
     b-009's edge ran 800px out, to the far side of the whole drawing and back. */
  var OUTSIDE_MARGIN = 48, OUTSIDE_SHARE = 0.2;

  /* The weights. An edge routed around the outside is what made b-009 unreadable, so one of
     those costs more than any tidy difference elsewhere; a crossing is the next worst thing
     an eye can meet; a bend is small; and the length term is a tie breaker in the units of
     "the drawing's own half perimeter", so a layout does not win by being drawn tiny. */
  var WEIGHTS = { outside: 30, crossings: 6, bends: 0.5, length: 2 };

  function point(p, ox, oy) { return { x: p.x + ox, y: p.y + oy }; }

  function boxesOf(node, x, y, out) {
    var ax = x + (node.x || 0), ay = y + (node.y || 0);
    out[node.id] = { x: ax, y: ay, width: node.width || 0, height: node.height || 0 };
    (node.children || []).forEach(function (c) { boxesOf(c, ax, ay, out); });
    return out;
  }

  /* Every edge as one polyline in the drawing's own coordinates. An edge declared inside a
     group is positioned in that group's local space, as ui.board.js's `edgesAbsolute` says. */
  function routesOf(node, ax, ay, out) {
    (node.edges || []).forEach(function (e) {
      var points = [];
      (e.sections || []).forEach(function (s) {
        points.push(point(s.startPoint, ax, ay));
        (s.bendPoints || []).forEach(function (b) { points.push(point(b, ax, ay)); });
        points.push(point(s.endPoint, ax, ay));
      });
      if (points.length > 1) {
        out.push({ id: e.id, source: (e.sources || [])[0], target: (e.targets || [])[0],
                   points: points, bends: points.length - 2 });
      }
    });
    (node.children || []).forEach(function (c) { routesOf(c, ax + (c.x || 0), ay + (c.y || 0), out); });
    return out;
  }

  function cross(a, b, c) { return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x); }

  /* A PROPER crossing: each segment's ends on strictly opposite sides of the other. Two
     edges that only touch (a shared port, one running along the other) are not crossing. */
  function segmentsCross(p1, p2, q1, q2) {
    var d1 = cross(q1, q2, p1), d2 = cross(q1, q2, p2);
    var d3 = cross(p1, p2, q1), d4 = cross(p1, p2, q2);
    return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0));
  }

  function crossingsBetween(a, b) {
    if (a.source === b.source || a.source === b.target || a.target === b.source || a.target === b.target) return 0;
    var count = 0;
    for (var i = 1; i < a.points.length; i++) {
      for (var j = 1; j < b.points.length; j++) {
        if (segmentsCross(a.points[i - 1], a.points[i], b.points[j - 1], b.points[j])) count++;
      }
    }
    return count;
  }

  function crossings(routes) {
    var total = 0;
    for (var i = 0; i < routes.length; i++) {
      for (var j = i + 1; j < routes.length; j++) total += crossingsBetween(routes[i], routes[j]);
    }
    return total;
  }

  function lengthOf(route) {
    var total = 0;
    for (var i = 1; i < route.points.length; i++) {
      total += Math.hypot(route.points[i].x - route.points[i - 1].x, route.points[i].y - route.points[i - 1].y);
    }
    return total;
  }

  /* ROUTED AROUND THE OUTSIDE: some point of the route lies further than the margin outside
     the box that holds both of its ends. That is a back edge sent round a row, or a wrap-cut
     edge taken the long way, and it is the one thing an eye cannot follow at all. */
  function strays(route, boxes, margin) {
    var a = boxes[route.source], b = boxes[route.target];
    if (!a || !b) return false;
    var left = Math.min(a.x, b.x) - margin, top = Math.min(a.y, b.y) - margin;
    var right = Math.max(a.x + a.width, b.x + b.width) + margin;
    var bottom = Math.max(a.y + a.height, b.y + b.height) + margin;
    return route.points.some(function (p) { return p.x < left || p.x > right || p.y < top || p.y > bottom; });
  }

  /* THE READABILITY COST of one laid-out graph: lower is easier to read. It returns its
     parts as well as the sum, so a test (and anyone asking why) can see what decided it. */
  function readability(laid) {
    var boxes = boxesOf(laid, -(laid.x || 0), -(laid.y || 0), {});
    var routes = routesOf(laid, 0, 0, []);
    var size = Math.max(1, (laid.width || 0) + (laid.height || 0));
    var margin = Math.max(OUTSIDE_MARGIN, OUTSIDE_SHARE * Math.max(laid.width || 0, laid.height || 0));
    var parts = {
      outside: routes.filter(function (r) { return strays(r, boxes, margin); }).length,
      crossings: crossings(routes),
      bends: routes.reduce(function (sum, r) { return sum + r.bends; }, 0),
      length: routes.reduce(function (sum, r) { return sum + lengthOf(r); }, 0) / size
    };
    parts.cost = Object.keys(WEIGHTS).reduce(function (sum, k) { return sum + WEIGHTS[k] * parts[k]; }, 0);
    return parts;
  }

  /* FIT IS THE GATE, COST IS THE CHOICE. Each candidate carries its `fit` (ui.board.js's
     `layoutScore`: over 1000 when it can be read whole at the floor), its `cost`, and
     `shown`, the share of it on the stage at the scale it is drawn at. Among those that fit
     readably the cheapest wins, and within half a point of cost the one drawn bigger
     (`scale`), the earlier on a full tie. When none does, the one that shows the
     most of itself wins, cost breaking a tie (round 2, reversing W3's "the bigger drawn
     wins": on b-009's 1138 x 528 page stage that rule chose a DOWN column drawn at 2.5 and
     showing 18% of itself over a RIGHT row at the floor showing all but a sliver). */
  var SHOWN_TIE = 0.01;
  /* Between readable layouts, cost first and size second (round 3): two that cost within a
     bend of each other are as easy to follow, and then the one drawn bigger wins. */
  var COST_TIE = 0.5;
  function better(c, best, readable) {
    if (readable) {
      if (Math.abs(c.cost - best.cost) > COST_TIE) return c.cost < best.cost;
      return (c.scale || 0) > (best.scale || 0);
    }
    if (Math.abs(c.shown - best.shown) > SHOWN_TIE) return c.shown > best.shown;
    return c.cost < best.cost;
  }
  function choose(candidates) {
    var readable = candidates.filter(function (c) { return c.fit >= 1000; });
    var pool = readable.length ? readable : candidates;
    return pool.reduce(function (best, c) {
      return !best || better(c, best, readable.length > 0) ? c : best;
    }, null);
  }

  /* WHETHER A CHAIN IS FOLDED (K2). `MULTI_EDGE` wrapping exists for W1's long single chain;
     a graph of several groups folded into rows sends every edge between the groups round
     the rows, so it is laid out unwrapped and K1 chooses between that and DOWN. "Few" cross
     edges is at most two: an ungrouped node or two hanging off one group is still a chain. */
  var FOLD_CROSS_MAX = 2;
  function shouldFold(model) {
    var groupOf = {}, used = {};
    var known = {};
    (model.groups || []).forEach(function (g) { known[g.id] = true; });
    (model.nodes || []).forEach(function (n) {
      groupOf[n.id] = n.group && known[n.group] ? n.group : '';
      if (groupOf[n.id]) used[groupOf[n.id]] = true;
    });
    if (Object.keys(used).length > 1) return false;
    var crossing = (model.edges || []).filter(function (e) {
      return e.a in groupOf && e.b in groupOf && groupOf[e.a] !== groupOf[e.b];
    }).length;
    return crossing <= FOLD_CROSS_MAX;
  }

  K.boardLayout = { readability: readability, choose: choose, shouldFold: shouldFold,
                    OUTSIDE_MARGIN: OUTSIDE_MARGIN, OUTSIDE_SHARE: OUTSIDE_SHARE, WEIGHTS: WEIGHTS, COST_TIE: COST_TIE, FOLD_CROSS_MAX: FOLD_CROSS_MAX };
})(window.Keel);
