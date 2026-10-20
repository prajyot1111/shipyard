/* The readability cost and the choice (K1, K2, 2026-09-24), as pure functions.
 *
 * `app/ui.boardlayout.js` reads an ELK result and numbers and draws nothing, so these
 * hand-built layouts pin each part of the cost on its own: an edge sent round the outside,
 * a crossing, a bend, the length, and the edge declared inside a group that carries the
 * group's offset. Then the choice (fit is the gate, cost decides) and the fold rule.
 *
 * Usage: node board-readability.js <path to ui.boardlayout.js>
 * Output: {"ok": true}, or a JSON object naming the checks that failed.
 */
'use strict';
const fs = require('fs');
const win = { Keel: {} };
new Function('window', fs.readFileSync(process.argv[2], 'utf8'))(win);
const L = win.Keel.boardLayout;
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }
function near(a, b) { return Math.abs(a - b) < 1e-6; }

if (!L || typeof L.readability !== 'function') {
  process.stdout.write(JSON.stringify({ ok: false, failed: ['ui.boardlayout.js exports no readability'] }));
  process.exit(0);
}

function node(id, x, y, w, h) { return { id: id, x: x, y: y, width: w || 100, height: h || 60 }; }
function edge(id, a, b, points) {
  return { id: id, sources: [a], targets: [b], sections: [{ startPoint: points[0],
    bendPoints: points.slice(1, -1), endPoint: points[points.length - 1] }] };
}
function graph(width, height, children, edges) {
  return { id: 'root', x: 0, y: 0, width: width, height: height, children: children, edges: edges };
}
const P = (x, y) => ({ x: x, y: y });

/* 1. A straight edge between neighbours costs only its length. */
const straight = L.readability(graph(300, 100, [node('a', 0, 20), node('b', 200, 20)],
  [edge('e', 'a', 'b', [P(100, 50), P(200, 50)])]));
check('a straight edge has no bends, crossings or strays',
      straight.bends === 0 && straight.crossings === 0 && straight.outside === 0);
check('its length is measured against the half perimeter', near(straight.length, 100 / 400));
check('and the cost is only the length term', near(straight.cost, L.WEIGHTS.length * 100 / 400));

/* 2. Two edges that cross in an X count once; two that share a node never do. */
const four = [node('a', 0, 0), node('b', 300, 0), node('c', 0, 200), node('d', 300, 200)];
const x = L.readability(graph(400, 260, four, [
  edge('e1', 'a', 'd', [P(100, 30), P(300, 230)]),
  edge('e2', 'c', 'b', [P(100, 230), P(300, 30)])]));
check('an X is one crossing', x.crossings === 1);
const fan = L.readability(graph(400, 260, four, [
  edge('e1', 'a', 'd', [P(100, 30), P(300, 230)]),
  edge('e2', 'a', 'b', [P(100, 30), P(300, 30)])]));
check('edges that share a node do not cross', fan.crossings === 0);

/* 3. Bends are counted per bend point, across every edge. */
const dogleg = L.readability(graph(300, 200, [node('a', 0, 0), node('b', 200, 120)],
  [edge('e', 'a', 'b', [P(100, 30), P(150, 30), P(150, 150), P(200, 150)])]));
check('a dogleg is two bends', dogleg.bends === 2);
check('and staying inside its ends it is not routed around', dogleg.outside === 0);

/* 4. ROUTED AROUND THE OUTSIDE: b-009's own shape. An edge from the end of the first row to
      the start of the second that runs out to the far side of the whole drawing first. */
const around = L.readability(graph(1400, 420,
  [node('api', 400, 40, 160, 80), node('ctrl', 60, 240, 180, 80), node('far', 1200, 300, 150, 60)],
  [edge('e', 'api', 'ctrl', [P(560, 80), P(1360, 80), P(1360, 170), P(16, 170), P(16, 280), P(60, 280)])]));
check('an edge sent round the whole drawing is routed around the outside', around.outside === 1);
check('and it costs more than any tidy layout of the same size', around.cost > L.WEIGHTS.outside);
/* W1's snake: a wrap edge that steps one lane past its row's end is how a fold reads. */
const snake = L.readability(graph(550, 640, [node('d1', 283, 12, 148, 64), node('d2', 44, 149, 148, 64)],
  [edge('w', 'd1', 'd2', [P(431, 44), P(534, 44), P(534, 112), P(16, 112), P(16, 181), P(44, 181)])]));
check("a fold's wrap edge one lane past its row is not sent round the outside", snake.outside === 0);

/* 5. An edge declared inside a group is in that group's local space. Read in the drawing's
      space it would appear to stray hundreds of pixels; read correctly it is a stub. */
const group = { id: 'g', x: 500, y: 300, width: 300, height: 100,
  children: [node('a', 10, 20), node('b', 180, 20)],
  edges: [edge('e', 'a', 'b', [P(110, 50), P(180, 50)])] };
const inGroup = L.readability(graph(900, 500, [group], []));
check('a group edge carries its group offset', inGroup.outside === 0 && inGroup.bends === 0);
check('and it is measured', near(inGroup.length, 70 / 1400));

/* 6. FIT IS THE GATE, COST IS THE CHOICE. */
const readableCheap = { name: 'down', fit: 1000.7, cost: 2 };
const readableDear = { name: 'right', fit: 1000.9, cost: 36 };
const unreadable = { name: 'flat', fit: 0.55, cost: 0.1 };
check('among readable layouts the cheapest wins, however much bigger the other is drawn',
      L.choose([readableDear, readableCheap]).name === 'down');
check('an unreadable layout never wins on cost', L.choose([unreadable, readableDear]).name === 'right');
/* Round 2: when nothing reads whole, the one showing the most of itself wins, whatever its
   width fit, and cost breaks a tie. b-009 on the 1138 x 528 page: DOWN's width fit is 4 and
   it shows 18%, RIGHT's is 0.6 and it shows 99.8%. */
check('when nothing is readable the one showing the most of itself wins',
      L.choose([{ name: 'down', fit: 4.06, shown: 0.18, cost: 1 }, { name: 'right', fit: 0.6, shown: 0.998, cost: 9 }]).name === 'right');
check('and between two showing as much, the cheaper',
      L.choose([{ name: 'dear', fit: 0.5, shown: 0.9, cost: 30 }, { name: 'cheap', fit: 0.5, shown: 0.895, cost: 2 }]).name === 'cheap');
check('a tie goes to the earlier candidate',
      L.choose([{ name: 'first', fit: 1001, cost: 5 }, { name: 'second', fit: 1002, cost: 5 }]).name === 'first');
check('one candidate is itself', L.choose([readableDear]).name === 'right');

/* 7. K2: only a simple chain is folded. */
const nodes = ids => ids.map(([id, g]) => ({ id: id, group: g || null }));
check('no groups folds', L.shouldFold({ groups: [], nodes: nodes([['a'], ['b']]), edges: [{ a: 'a', b: 'b' }] }));
check('one group folds', L.shouldFold({ groups: [{ id: 'g' }], nodes: nodes([['a', 'g'], ['b', 'g'], ['c']]),
                                        edges: [{ a: 'a', b: 'b' }, { a: 'b', b: 'c' }] }));
check('two groups do not', !L.shouldFold({ groups: [{ id: 'g' }, { id: 'h' }],
                                           nodes: nodes([['a', 'g'], ['b', 'h']]), edges: [{ a: 'a', b: 'b' }] }));
check('one group with many edges leaving it does not',
      !L.shouldFold({ groups: [{ id: 'g' }], nodes: nodes([['a', 'g'], ['b'], ['c'], ['d']]),
                      edges: [{ a: 'a', b: 'b' }, { a: 'a', b: 'c' }, { a: 'a', b: 'd' }] }));
check('a declared group nobody is in does not count',
      L.shouldFold({ groups: [{ id: 'g' }, { id: 'empty' }], nodes: nodes([['a', 'g'], ['b', 'g']]),
                     edges: [{ a: 'a', b: 'b' }] }));

process.stdout.write(JSON.stringify(fails.length ? { ok: false, failed: fails } : { ok: true }));
