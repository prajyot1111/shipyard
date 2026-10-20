/* The full-screen board's mode switch (C6), checked outside a browser.
 *
 * Usage: node board-full.js <path to ui.boardfull.js>
 * Output: {"ok": true}, or a JSON object naming the checks that failed.
 */
'use strict';
const fs = require('fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

function world(desk, hasApi) {
  const listeners = {};
  const classes = new Set();
  const calls = { request: 0, exit: 0, render: 0 };
  const doc = {
    fullscreenElement: null, fullscreenEnabled: true,
    body: { classList: { add: c => classes.add(c), remove: c => classes.delete(c) } },
    documentElement: hasApi ? { requestFullscreen: () => { calls.request++; doc.fullscreenElement = {}; return Promise.resolve(); } } : {},
    exitFullscreen: () => { calls.exit++; doc.fullscreenElement = null; return Promise.resolve(); },
    addEventListener: (name, fn) => { listeners[name] = fn; },
    querySelectorAll: () => []
  };
  const K = { boardState: { open: { id: 'b-1' } }, App: { view: 'board', board: 'b-1' },
              isDesk: () => desk, renderBody: () => { calls.render++; }, el: () => ({}) };
  const win = { Keel: K, addEventListener: (name, fn) => { listeners[name] = fn; } };
  new Function('window', 'document', 'requestAnimationFrame', source)(win, doc, fn => fn());
  return { K, doc, listeners, classes, calls };
}

let w = world(true, true);
w.K.boardFull.toggle();
check('the desk asks the Fullscreen API', w.calls.request === 1);
check('and hides the chrome', w.classes.has('board-full') && w.K.boardState.full === true);
check('and draws the diagram again at its new size', w.calls.render >= 1);
w.doc.fullscreenElement = null;
w.listeners.fullscreenchange();
check('Esc out of the browser fullscreen leaves the mode too', !w.classes.has('board-full') && !w.K.boardState.full);

w = world(false, true);
w.K.boardFull.toggle();
check('the phone is a focus mode: no Fullscreen API', w.calls.request === 0 && w.classes.has('board-full'));
w.K.boardFull.toggle();
check('and the same tap leaves it', !w.classes.has('board-full'));

w = world(true, false);
w.K.boardFull.toggle();
check('a desk with no API falls back to the focus mode', w.calls.request === 0 && w.classes.has('board-full'));

w = world(true, true);
let prevented = 0;
w.listeners.keydown({ key: 'f', target: { tagName: 'DIV' }, preventDefault: () => prevented++ });
check('f toggles it on an open board', w.K.boardState.full === true && prevented === 1);
w.listeners.keydown({ key: 'f', target: { tagName: 'INPUT' }, preventDefault: () => prevented++ });
check('but not while he is typing', w.K.boardState.full === true && prevented === 1);
w.listeners.keydown({ key: 'f', metaKey: true, target: { tagName: 'DIV' }, preventDefault: () => prevented++ });
check('and not with a modifier', prevented === 1);
w.K.App.view = 'cards';
w.listeners.keydown({ key: 'f', target: { tagName: 'DIV' }, preventDefault: () => prevented++ });
check('and not off the board route', prevented === 1);

/* Round 3 of lane K: full screen exists to make the board BIGGER, so entering or leaving
   it chooses the layout again. The kept shapes of THIS board are forgotten on the toggle;
   another board's are not, and nothing else here (the rail, the views) forgets them. */
w = world(true, true);
w.K.boardState.layouts = { 'b-1:diagram': { version: 3 }, 'b-1:walk': { version: 3 }, 'b-2:diagram': { version: 1 } };
w.K.boardFull.toggle();
check('entering full screen forgets this board\'s kept shapes',
      !('b-1:diagram' in w.K.boardState.layouts) && !('b-1:walk' in w.K.boardState.layouts));
check('and keeps another board\'s', 'b-2:diagram' in w.K.boardState.layouts);
w.K.boardState.layouts['b-1:diagram'] = { version: 3 };
w.K.boardFull.toggle();
check('leaving it forgets them again', !('b-1:diagram' in w.K.boardState.layouts));

// F2 of the lane C review: focus mode can never outlive the board.
w = world(true, true);
w.K.boardFull.toggle();
w.K.App.view = 'cards';
w.K.App.board = null;
(w.listeners.popstate || (() => fails.push('no popstate listener')))();
check('Back off the board leaves the mode', !w.classes.has('board-full') && !w.K.boardState.full && w.calls.exit === 1);

w = world(false, false);
w.K.boardFull.toggle();
w.K.App.board = 'b-2';
w.K.boardFull.sync();
check('a move to another board leaves the mode', !w.classes.has('board-full') && !w.K.boardState.full);

w = world(false, false);
w.K.boardFull.toggle();
w.K.boardState.error = 'that board is not there';
w.K.boardFull.sync();
check('the error page leaves the mode', !w.classes.has('board-full'));

w = world(false, false);
w.K.boardFull.toggle();
w.classes.delete('board-full');
w.K.boardFull.sync();
check('the class is derived from the state on every render', w.classes.has('board-full'));

process.stdout.write(JSON.stringify(fails.length ? { ok: false, failed: fails } : { ok: true }));
