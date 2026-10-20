/* A diagram in a plan (P2-1, round 2), checked against the REAL vendored ELK.
 *
 * The plan passes a LOOK on the model (`model.look = 'plan'`, app/ui.planlook.js): labels
 * wrapped whole (no ellipsis), a 13px label, an icon only where the source names one, and a
 * layout chosen for the COLUMN rather than for a pannable stage. What is held here: no label
 * is cut, a path breaks at its separators, a mermaid node carries no icon, a long chain on a
 * wide column is folded into rows rather than drawn as a tower, a wide grouped board reads
 * whole in the column, a board with no look is sized exactly as the board page sizes it.
 *
 * Text is measured by `textWidth`'s linear estimate (no canvas under node): the sizes differ
 * a little from a browser's, the shapes do not. Every label here is filler.
 *
 * Usage: node plan-diagram.js <path to the app directory> <path to board-b009.txt>
 * Output: {"ok": true, seen}, or a JSON object naming the checks that failed.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const app = path.resolve(process.argv[2]);
const ELK = require(path.join(app, 'vendor', 'elk.bundled.js'));
const win = { Keel: {}, addEventListener() {}, matchMedia: () => ({ matches: true }), innerHeight: 900 };
const doc = {
  visibilityState: 'hidden',
  createElement: () => ({ getContext: () => null }),
  createElementNS: () => ({ setAttribute() {}, appendChild() {} }),
  addEventListener() {}, getElementById: () => null, querySelector: () => null
};
const fails = [], seen = {};
function check(name, ok) { if (!ok) fails.push(name); }
function done() { process.stdout.write(JSON.stringify(fails.length ? { ok: false, failed: fails, seen } : { ok: true, seen })); }
for (const name of ['ui.boardlayout.js', 'ui.board.js', 'ui.planlook.js']) {
  const file = path.join(app, name);
  if (!fs.existsSync(file)) { fails.push(name + ' is missing'); continue; }
  new Function('window', 'document', 'setInterval', 'requestAnimationFrame', 'fetch', 'history',
               fs.readFileSync(file, 'utf8'))(
    win, doc, () => 0, () => 0, () => Promise.resolve(), { pushState() {}, replaceState() {} });
}
const K = win.Keel, B = K.board, D = K.boardDraw, P = K.planLook;
if (!P || !D || !D.layoutOnce) { fails.push('no plan look, or ui.board.js exports no layoutOnce'); done(); process.exit(0); }

const engine = new ELK();
function planModel(lines, icons) {
  const m = B.foldInto(B.newModel(), lines);
  m.look = 'plan';
  m.icons = icons !== false;
  return m;
}
const LONG = 'filler words for a label that runs well past one line of a node';
const PATH = 'state/cards/c-001/board-files/a_very_long_file_name_here.py';

/* ---------- labels wrap whole ---------- */
(function () {
  const room = P.MAX_W - 2 * P.PAD_X;
  const lines = P.wrap(LONG, room, P.LABEL, P.SANS);
  check('wrap: a long label takes more than one line', lines.length > 1);
  check('wrap: nothing is cut, every word is kept', lines.join(' ') === LONG);
  check('wrap: no ellipsis', lines.every(l => l.indexOf('…') < 0));
  check('wrap: every line fits the box', lines.every(l => B.textWidth(l, P.LABEL, P.SANS) <= room + 0.01));
  const parts = P.wrap(PATH, room, P.LABEL, P.SANS);
  check('wrap: a path is kept whole across its lines', parts.join('') === PATH);
  check('wrap: a path breaks after a separator', parts.slice(0, -1).every(l => '/_.-:'.indexOf(l.charAt(l.length - 1)) >= 0));
  seen.path = parts;
})();

/* ---------- an icon only where the source names one ---------- */
(function () {
  const named = planModel(['node a database "' + LONG + '"']), mermaid = planModel(['node a database "' + LONG + '"'], false);
  const fallback = planModel(['node a box "' + LONG + '"']);
  const h = m => P.nodeSize(m, m.nodes[0]).height;
  check('icons: a named icon takes room', h(named) > h(mermaid));
  check('icons: a mermaid node has none', h(mermaid) === h(fallback));
  check('icons: the board fallback `box` is drawn as none', !P.nodeText(fallback, fallback.nodes[0]).icon);
  const board = B.buildGraph(B.foldInto(B.newModel(), ['node a database "short"', 'node b box "' + LONG + '" "sub"']), 'RIGHT', 0);
  const sizes = board.root.children.map(c => [c.width, c.height]);
  check('board page: a model with no look is sized as before (64 and 80 tall, 184 at most)',
    sizes[0][1] === 64 && sizes[1][1] === 80 && sizes[1][0] === 184);
  /* c-602: a node and a group sharing an id hung the page (the node was its own parent). A
     board stored that way still lays out, and its edge sits in the group both nodes are in. */
  const clash = B.buildGraph(B.foldInto(B.newModel(), ['group lint "the lint"', 'node lint box "A" in lint',
    'node rules box "B" in lint', 'edge lint -> rules "call()"']), 'DOWN', 0);
  const g = clash.root.children.filter(c => c.id === 'g_lint')[0];
  check('clash: a node named like its group lays out, its edge inside the group',
    g && g.children.length === 2 && g.edges.length === 1 && clash.root.edges.length === 0);
})();

(async () => {
  /* ---------- the column chooses the shape ---------- */
  const chain = planModel(['board "filler"']
    .concat([0, 1, 2, 3, 4, 5, 6, 7].map(i => 'node s' + i + ' box "filler step number ' + i + ' of the chain"'))
    .concat([0, 1, 2, 3, 4, 5, 6].map(i => 'edge s' + i + ' -> s' + (i + 1))), false);
  const b009 = planModel(fs.readFileSync(process.argv[3], 'utf8').split('\n'));
  async function choose(model, w, h) {
    const list = await Promise.all(P.candidates(w, h).map(c => D.layoutOnce(engine, model, c.direction, c.aspect)));
    const best = P.chooseForColumn(list, w);
    const down = list.filter(c => c.choice.direction === 'DOWN')[0];
    return { best, down: P.measure(down, w), shape: best.choice.direction + (best.choice.aspect ? ':folded' : '') };
  }
  const desk = await choose(chain, 746, 630);
  seen.chain_desk = { shape: desk.shape, drawnH: Math.round(desk.best.fit.drawnH), downH: Math.round(desk.down.drawnH) };
  check('column: a long chain on the desk column is not a tower', desk.shape === 'RIGHT:folded');
  check('column: and it is shorter than the tower', desk.best.fit.drawnH < desk.down.drawnH * 0.8);
  check('column: and it reads at the font floor or better', desk.best.fit.readable);
  const phone = await choose(chain, 330, 590);
  seen.chain_phone = { shape: phone.shape, scale: +phone.best.fit.scale.toFixed(3) };
  check('column: on the phone the chain reads at the floor', phone.best.fit.readable);
  const grouped = await choose(b009, 746, 630);
  seen.b009_desk = { shape: grouped.shape, scale: +grouped.best.fit.scale.toFixed(3), drawnW: Math.round(grouped.best.fit.drawnW) };
  check('column: a wide grouped board reads whole in the desk column', grouped.best.fit.readable && grouped.best.fit.drawnW <= 746 + 0.5);
  check('column: never drawn above its natural size', grouped.best.fit.scale <= 1 && desk.best.fit.scale <= 1);
  /* none readable: the floor, and the least sideways scroll */
  const narrow = await choose(b009, 120, 400);
  check('column: past the floor it keeps the floor (it scrolls, it is not shrunk)', narrow.best.fit.scale === P.SCALE_FLOOR);
  done();
})().catch(e => { fails.push('threw: ' + e.message); done(); });
