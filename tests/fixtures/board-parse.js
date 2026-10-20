/* Run the deck's parser over the shared fixture, and print one verdict per row.
 *
 * `app/ui.board.js` is the page's module and the page is the only place it ever runs, so
 * this harness gives it the two globals it touches at load (`window` and `document`) and
 * nothing else. It is deliberately a few lines of stubs rather than a DOM library: the
 * module does no DOM work at load, and a harness that needed one would be saying the
 * module does something it must not.
 *
 * Usage: node board-parse.js <path to ui.board.js> <path to board-lines.txt>
 * Output: a JSON array of "OK" and "BAD", one per fixture row, in the fixture's order.
 */
'use strict';
const fs = require('fs');

const [, , modulePath, fixturePath] = process.argv;
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
/* The module's own IIFE takes `window.Keel`; handing it window and document as arguments
   keeps every one of its names inside this function rather than on node's globals. */
new Function('window', 'document', 'setInterval', 'requestAnimationFrame', 'fetch', 'history', source)(
  win, doc, () => 0, () => 0, () => Promise.resolve(), { pushState() {}, replaceState() {} });

const board = win.Keel.board;
if (!board || typeof board.parseLine !== 'function') {
  console.error('ui.board.js did not export a parser on Keel.board');
  process.exit(1);
}

const answers = [];
for (const raw of fs.readFileSync(fixturePath, 'utf8').split('\n')) {
  if (!raw.trim() || raw.startsWith('#')) continue;
  /* The same split Python's `partition` gives: a row with no tab is the blank line, and
     its line is empty. Getting this wrong makes the two harnesses disagree about a row
     rather than about the grammar, which is the one failure this file must not produce. */
  const tab = raw.indexOf('\t');
  const line = tab < 0 ? '' : raw.slice(tab + 1);
  const op = board.parseLine(line);
  answers.push(op && op.bad ? 'BAD' : 'OK');
}
process.stdout.write(JSON.stringify(answers));
