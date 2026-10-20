/* Cutting a node's label to the box it is drawn in, checked outside a browser.
 *
 * A node box is sized to its own text and then CLAMPED (`NODE_MAX_W`), so a long label or
 * a long sub label used to be painted past the edge of its own card: a house that wrote
 * `state/cards/c-001/board-files` got a path lying across the diagram. The cut is the one
 * piece of that which is arithmetic rather than layout, so it is a pure function in
 * `app/ui.board.js` and this runs it, the way `board-zoom.js` runs the zoom clamp.
 *
 * Under node there is no canvas, so `textWidth` falls back to its linear estimate
 * (`length * size * 0.55`). That is what makes the numbers here predictable, and the
 * property being checked is true either way: what comes back FITS.
 *
 * Usage: node board-fit.js <path to ui.board.js>
 * Output: {"ok": true}, or a JSON object naming the first check that failed.
 */
'use strict';
const fs = require('fs');

const source = fs.readFileSync(process.argv[2], 'utf8');
const win = { Keel: {}, addEventListener() {}, matchMedia: () => ({ matches: true }) };
const doc = {
  visibilityState: 'hidden',
  createElement: () => ({ getContext: () => null }),
  createElementNS: () => ({ setAttribute() {}, appendChild() {} }),
  addEventListener() {}, getElementById: () => null, querySelector: () => null
};
new Function('window', 'document', 'setInterval', 'requestAnimationFrame', 'fetch', 'history', source)(
  win, doc, () => 0, () => 0, () => Promise.resolve(), { pushState() {}, replaceState() {} });

const B = win.Keel.board;
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

if (!B || typeof B.fitText !== 'function' || typeof B.textWidth !== 'function') {
  process.stdout.write(JSON.stringify({ ok: false, failed: ['ui.board.js exports no fitText'] }));
  process.exit(0);
}
const SANS = '-apple-system, BlinkMacSystemFont, Inter, system-ui, sans-serif';
const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';
const fit = (text, room, size, family) => B.fitText(text, room, size, family || SANS);
const wide = (text, size, family) => B.textWidth(text, size, family || SANS);

/* 1. What already fits is not touched. A cut that fires on a label that was never too
      long would put an ellipsis on almost every node in a small diagram. */
check('a label that fits is returned as it is', fit('The Mac', 152, 15) === 'The Mac');
check('a label exactly at the room is not cut',
      fit('abcd', wide('abcd', 15), 15) === 'abcd');

/* 2. What does not fit comes back FITTING. This is the property the bug broke, and it
      holds whatever the measurement says, so it is the one checked over a spread. */
const long = 'a state directory with a very long name indeed';
for (const room of [20, 40, 80, 120, 152, 184]) {
  const cut = fit(long, room, 15);
  check('a cut label fits its room (' + room + ')', wide(cut, 15) <= room);
  check('a cut label says it was cut (' + room + ')', cut.indexOf('…') >= 0);
}

/* 3. A PATH is cut in the MIDDLE, because the end of it is the part that says which file
      this is. A prefix cut leaves every file in a directory looking identical. */
const path = 'state/cards/c-001/board-files/probe.py';
const cutPath = fit(path, 140, 13, MONO);
check('a path keeps its tail', cutPath.endsWith('probe.py'));
check('a path is cut in the middle', cutPath.startsWith('state/') && cutPath.indexOf('…') > 0);
check('a cut path fits its room', wide(cutPath, 13, MONO) <= 140);
check('a path that fits is left whole', fit(path, 999, 13, MONO) === path);

/* 4. Text with no slash in it is cut at the END: the front of a sentence is what says
      what it is about, which is the opposite of a path. */
const sentence = fit('the drain claims a card for this host', 120, 15);
check('a sentence keeps its head', sentence.startsWith('the drain'));
check('a sentence ends in the ellipsis', sentence.endsWith('…'));

/* 5. The degenerate rooms. A node 24px wide is not a thing the layout makes, but a cut
      that looped forever or returned nothing at all on one would take the whole frame. */
check('no room at all is just the ellipsis', fit(path, 0, 13, MONO) === '…');
check('a negative room is just the ellipsis', fit(path, -50, 13, MONO) === '…');
check('an empty label is empty', fit('', 100, 15) === '');

process.stdout.write(JSON.stringify(fails.length ? { ok: false, failed: fails } : { ok: true }));
