/* The walk's callout (Z1, Z3 of lane Z), checked outside a browser.
 *
 * Usage: node board-callout.js <path to ui.boardcallout.js>
 * Output: {"ok": true}, or a JSON object naming the checks that failed.
 *
 * Two halves. `place` is arithmetic on the laid-out boxes, so it is run over many shapes:
 * the callout never covers its node, it goes on the side with room, and it gives way to the
 * caption bar under a width or at the stage's edge. The keyboard is run against a fake page
 * state: stepping and leaving are VIEW STATE (B3), so nothing it does may reach the board.
 */
'use strict';
const fs = require('fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

function load(K, doc) {
  const listeners = {};
  const win = { Keel: K, addEventListener: (name, fn) => { listeners[name] = fn; } };
  const d = doc || { addEventListener: (name, fn) => { listeners[name] = fn; } };
  new Function('window', 'document', source)(win, d);
  return { C: K.boardCallout, listeners };
}

function overlaps(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}
function inside(box, stage) {
  return box.x >= 0 && box.y >= 0 && box.x + box.w <= stage.w && box.y + box.h <= stage.h;
}

const { C } = load({});
check('the module exports place', C && typeof C.place === 'function');
if (!C || typeof C.place !== 'function') {
  process.stdout.write(JSON.stringify({ ok: false, failed: fails }));
  process.exit(0);
}

/* ---------- it never covers its node, and stays on the stage ---------- */
let seed = 7;
function rand() { seed = (seed * 16807) % 2147483647; return seed / 2147483647; }
let placed = 0, captions = 0;
for (let i = 0; i < 4000; i++) {
  const stage = { w: 400 + Math.round(rand() * 1600), h: 200 + Math.round(rand() * 900) };
  const node = { x: Math.round(rand() * stage.w) - 40, y: Math.round(rand() * stage.h) - 20,
                 w: 60 + Math.round(rand() * 200), h: 40 + Math.round(rand() * 60) };
  const size = { w: 288, h: 60 + Math.round(rand() * 120) };
  const got = C.place({ node, stage, size, others: [] });
  if (got.mode === 'callout') {
    placed++;
    if (overlaps(got.box, node)) { check('never over its node: ' + JSON.stringify({ stage, node, size, got }), false); break; }
    if (!inside(got.box, stage)) { check('always on the stage: ' + JSON.stringify({ stage, node, size, got }), false); break; }
  } else captions++;
}
check('the fuzz placed callouts at all', placed > 1000);
check('and fell back to captions too', captions > 100);

/* ---------- the side with room ---------- */
const stage = { w: 1200, h: 600 };
const size = { w: 288, h: 96 };
let got = C.place({ node: { x: 100, y: 250, w: 180, h: 64 }, stage, size, others: [] });
check('a node on the left gets its callout on the right', got.mode === 'callout' && got.side === 'right');
got = C.place({ node: { x: 960, y: 250, w: 180, h: 64 }, stage, size, others: [] });
check('a node on the right gets its callout on the left', got.mode === 'callout' && got.side === 'left');
got = C.place({ node: { x: 60, y: 40, w: 560, h: 64 }, stage: { w: 640, h: 600 }, size, others: [] });
check('a node with no room either side gets it below', got.mode === 'callout' && got.side === 'below');
got = C.place({ node: { x: 60, y: 480, w: 560, h: 64 }, stage: { w: 640, h: 600 }, size, others: [] });
check('and above when below has no room', got.mode === 'callout' && got.side === 'above');

/* It stays off the other nodes when a side lets it. */
const lit = { x: 440, y: 250, w: 180, h: 64 };
got = C.place({ node: lit, stage, size, others: [{ x: 660, y: 200, w: 300, h: 160 }] });
check('a side that would cover another node loses to one that does not',
      got.mode === 'callout' && got.side !== 'right' && !overlaps(got.box, { x: 660, y: 200, w: 300, h: 160 }));

/* The leader runs from the node's edge to the callout's. */
got = C.place({ node: { x: 100, y: 250, w: 180, h: 64 }, stage, size, others: [] });
check('the leader starts on the node\'s facing edge', got.leader && got.leader.x1 === 280 &&
      got.leader.y1 >= 250 && got.leader.y1 <= 314);
check('and ends on the callout\'s', got.leader && got.leader.x2 === got.box.x &&
      got.leader.y2 >= got.box.y && got.leader.y2 <= got.box.y + got.box.h);

/* ---------- the caption bar ---------- */
got = C.place({ node: { x: 100, y: 100, w: 160, h: 64 }, stage: { w: 390, h: 300 }, size, others: [] });
check('under the width the step is a caption bar', got.mode === 'caption' && got.why === 'narrow');
got = C.place({ node: { x: 100, y: 100, w: 160, h: 64 }, stage: { w: C.MIN_STAGE - 1, h: 600 }, size, others: [] });
check('one pixel under MIN_STAGE is a caption too', got.mode === 'caption');
got = C.place({ node: { x: 1150, y: 250, w: 180, h: 64 }, stage, size, others: [] });
check('a node cut by the stage edge gets the caption bar', got.mode === 'caption' && got.why === 'edge');
got = C.place({ node: { x: 500, y: -30, w: 180, h: 64 }, stage, size, others: [] });
check('the top edge too', got.mode === 'caption' && got.why === 'edge');
got = C.place({ node: null, stage, size, others: [] });
check('a step on the board has no node to point at: a caption', got.mode === 'caption' && got.why === 'board');
got = C.place({ node: { x: 20, y: 20, w: 1160, h: 560 }, stage, size, others: [] });
check('a node that fills the stage leaves no room: a caption', got.mode === 'caption' && got.why === 'room');

/* ---------- the node on the screen, from the view ---------- */
const at = C.onScreen({ x: 100, y: 50, w: 200, h: 80 }, { tx: 10, ty: -20, scale: 0.5 });
check('a node\'s screen box is its stage box through the view', at.x === 60 && at.y === 5 && at.w === 100 && at.h === 40);

/* ---------- the keyboard is view state (B3) ---------- */
function world(view, steps, typing) {
  const calls = { render: 0, view: [], net: 0 };
  const model = { version: 4, attachments: steps.map((t, i) => ({ kind: 'step', at: 'n' + i, text: t, n: i })) };
  const frozen = JSON.stringify(model);
  const B = { open: { id: 'b-1', model, record: { lines: 9 } }, step: 0 };
  const K = {
    boardState: B, App: { view: 'board', board: 'b-1' },
    renderBody: () => { calls.render++; },
    post: () => { calls.net++; return Promise.resolve(); },
    boardInner: { viewOf: () => view, stepsOf: (m) => m.attachments.filter((a) => a.kind === 'step'),
                  setView: (name) => { calls.view.push(name); } }
  };
  const realFetch = global.fetch;
  global.fetch = () => { calls.net++; return Promise.resolve(); };
  const { listeners } = load(K);
  const press = (key, extra) => {
    let prevented = false;
    const target = { tagName: typing ? 'INPUT' : 'DIV' };
    (listeners.keydown || (() => {}))(Object.assign({ key, target, preventDefault: () => { prevented = true; } }, extra || {}));
    return prevented;
  };
  return { B, K, calls, press, model, frozen, restore: () => { global.fetch = realFetch; } };
}

let w = world('walk', ['one', 'two', 'three']);
check('ArrowRight steps on', w.press('ArrowRight') && w.B.step === 1 && w.calls.render === 1);
w.press('ArrowDown');
check('ArrowDown too', w.B.step === 2);
w.press('ArrowRight');
check('and stops at the last step', w.B.step === 2);
w.press('ArrowLeft');
check('ArrowLeft steps back', w.B.step === 1);
w.press('ArrowUp'); w.press('ArrowUp');
check('ArrowUp too, and stops at the first', w.B.step === 0);
check('Escape leaves the walk for the diagram', w.press('Escape') && w.calls.view.join() === 'diagram');
check('stepping never reaches the board: no request', w.calls.net === 0);
check('and never changes the model', JSON.stringify(w.model) === w.frozen && w.model.version === 4);
check('and never touches the record', w.B.open.record.lines === 9);
w.restore();

w = world('diagram', ['one', 'two']);
check('the arrows do nothing off the walk', !w.press('ArrowRight') && w.B.step === 0 && w.calls.render === 0);
check('nor does Escape', !w.press('Escape') && w.calls.view.length === 0);
w.restore();

w = world('walk', ['one', 'two'], true);
check('not while he is typing', !w.press('ArrowRight') && w.B.step === 0);
w.restore();

w = world('walk', ['one', 'two']);
check('not with a modifier', !w.press('ArrowRight', { metaKey: true }) && w.B.step === 0);
w.K.App.view = 'cards';
check('not off the board route', !w.press('ArrowRight') && w.B.step === 0);
w.restore();

process.stdout.write(JSON.stringify(fails.length ? { ok: false, failed: fails } : { ok: true }));
