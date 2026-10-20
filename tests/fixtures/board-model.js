/* Fold one board with the DECK's half of the model, and print what it built.
 *
 * The grammar fixture says what each LINE means. This says what a whole board means: one
 * diagram, and the attachments hanging off its nodes and off the board, in push order.
 * `tests/test_boards.py` folds the same lines with `keel/boards.py` and compares, so a
 * model rule added on one side alone fails `make test` rather than his phone.
 *
 * Usage: node board-model.js <path to ui.board.js> [<a JSON file of lines to fold instead>]
 * Output: {lines, nodes, groups, attachments: [[kind, at], ...], steps}
 */
'use strict';
const fs = require('fs');

const [, , modulePath, linesPath] = process.argv;
const source = fs.readFileSync(modulePath, 'utf8');

const win = { Keel: {}, addEventListener() {}, matchMedia: () => ({ matches: true }) };
const doc = {
  visibilityState: 'hidden',
  createElement: () => ({ getContext: () => null }),
  createElementNS: () => ({ setAttribute() {}, appendChild() {} }),
  addEventListener() {},
  getElementById: () => null,
  querySelector: () => null
};
win.setInterval = () => 0;
new Function('window', 'document', 'setInterval', 'requestAnimationFrame', 'fetch', 'history', source)(
  win, doc, () => 0, () => 0, () => Promise.resolve(), { pushState() {}, replaceState() {} });

const board = win.Keel.board;
if (!board || typeof board.foldInto !== 'function') {
  console.error('ui.board.js did not export a model on Keel.board');
  process.exit(1);
}

/* One board that exercises every rule the two halves share: a group, a node in it, a node
   outside it, a re-declaration, a mark, an edge, every attachment kind, a continuation that
   belongs to the attachment before it, and three lines that the server refuses and this
   half therefore has to drop rather than draw. */
const LINES = [
  '# the marker the store writes, which is a comment to both halves',
  'board "The memory tier system"',
  'group always "Injected every session"',
  'node global file "~/.claude/CLAUDE.md" in always "machine wide"',
  'node index file "MEMORY.md index" in always',
  'node body folder "the memory bodies" "recall on demand"',
  'node body folder "the memory bodies" "pulled, never pushed"',
  'edge index -> body "points to"',
  'edge index -> ghost "no such node, so no edge"',
  'mark index accent',
  'note board "Two tiers: what is **pushed** and what is `pulled`."',
  'note body "a body file only loads if the model follows a pointer"',
  'note ghost "hangs on nothing, so it is dropped"',
  'step board "The injected files load with no recall step"',
  'step body "A body file waits for a pointer"',
  'table global "What is always there"',
  'cols Surface | When',
  'row ~/.claude/CLAUDE.md | every session',
  'code index "one index line"',
  'lang markdown',
  'line "- [drawing-on-the-board](drawing-on-the-board.md): you draw."',
  'path body "state/boards/b-002/notes.md" size "2 KB" from talker',
  '```'
];

const lines = linesPath ? JSON.parse(fs.readFileSync(linesPath, 'utf8')) : LINES;
const model = board.foldInto(board.newModel(), lines);
process.stdout.write(JSON.stringify({
  lines: lines,
  nodes: model.nodes.map((n) => n.id),
  groups: model.groups.map((g) => g.id),
  attachments: model.attachments.map((a) => [a.kind, a.at]),
  steps: model.attachments.filter((a) => a.kind === 'step').map((a) => a.text)
}));
