/* The board stage's zoom arithmetic, checked outside a browser.
 *
 * Pan and zoom is mostly layout, which no stdlib test can judge; the CLAMP is arithmetic,
 * and it is the part that decides whether he can zoom a diagram into illegibility or past
 * the point where it is one node filling the screen. So the clamp, the fitted view and
 * the zoom-about-a-point are pure functions in `app/ui.board.js`, and this runs them.
 *
 * Usage: node board-zoom.js <path to ui.board.js>
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
function near(a, b) { return Math.abs(a - b) < 1e-6; }

const fitted = 2;
check('a scale inside the band is left alone', near(B.clampScale(3, fitted), 3));
check('four times the fitted scale is the ceiling', near(B.clampScale(99, fitted), fitted * 4));
check('a quarter of the fitted scale is the floor', near(B.clampScale(0.001, fitted), fitted * 0.25));
check('the band is relative to the fitted scale', near(B.clampScale(99, 0.5), 2));
check('a fitted scale of zero clamps nothing', near(B.clampScale(7, 0), 7));

/* The desk fits both axes and the phone fits the width, and the ceiling is 2.5 on both:
   over that a small graph is two huge boxes. The FLOORS differ, because the two fits do:
   see `DESK_FIT_MIN` and `PHONE_FIT_MIN` in ui.board.js. */
/* Fitted inside an 8px margin on each side, so the width it fits to is 800 - 16. */
const desk = B.fittedView(1000, 500, 800, 600, true);
check('the desk fits the tighter axis, inside its margin', near(desk.scale, 0.784));
check('the fitted view is not a zoom he set', desk.user === false);
const phone = B.fittedView(1000, 2000, 858, 600, false);
check('the phone fits the width and ignores the height', near(phone.scale, 0.842));
const narrow = B.fittedView(1000, 2000, 358, 600, false);
check('the phone floor is 0.75, because it never showed everything and legibility wins',
      near(narrow.scale, 0.75));
const tiny = B.fittedView(100, 50, 800, 600, true);
check('a small graph is not blown up past 2.5', near(tiny.scale, 2.5));

/* WHOLE, INSIDE ITS MARGIN, on both axes, for every layout that CAN be read whole. `Fit`
   is this same function, so this is also what the button promises: a right or bottom edge
   past the stage means Fit does not fit. */
function whole(name, w, h, iw, ih) {
  const v = B.fittedView(w, h, iw, ih, true);
  check(name, v.tx + w * v.scale <= iw - 8 + 1e-6 && v.ty + h * v.scale <= ih - 8 + 1e-6);
}
whole('the whole of a wrapped chain is inside the stage, margin and all', 632, 700, 862, 542);
whole('and of a board wrapped to four rows', 952, 551, 862, 542);
whole('and of a small one that is blown up to the ceiling', 100, 50, 800, 600);
whole('and of one that only just fits', 846, 526, 862, 542);

/* AND WHAT A LAYOUT THAT CANNOT BE READ WHOLE DOES INSTEAD. 1726 x 448 is the twelve node
   board laid out FLAT, which is the shape `elk.aspectRatio` exists to stop producing: it
   cannot be read at both axes (0.49), so the desk fits the width, the floor takes it to
   0.6, and the stage is panned. The answer to this case is the LAYOUT, not the scale. */
const flat = B.fittedView(1726, 448, 862, 542, true);
check('a flat twelve node layout is drawn readably rather than wholly', near(flat.scale, 0.6));
check('which means it is pannable, and says so', flat.tx + 1726 * flat.scale > 862);

/* AND THE FALLBACK IS THE WIDTH, NOT THE FLOOR. The real grouped board, wrapped: both axes
   would be 0.592, a hair under the floor, and the WIDTH is 0.673. Taking the floor would
   throw away that eight percent and clip the same amount off the right; fitting the width
   keeps every label and pans down instead. */
const tall = B.fittedView(1256, 889, 862, 542, true);
check('under the floor the desk fits the WIDTH rather than settling for the floor',
      near(tall.scale, (862 - 16) / 1256));
check('so nothing is cut off the side', tall.tx + 1256 * tall.scale <= 862 + 1e-6);
check('and what overflows is the axis a stage can be panned down', tall.ty + 889 * tall.scale > 542);

/* READABLE BEFORE COMPLETE, on the desk. Under 0.6 a 15px label is 9px, and Harbor's ten
   node chain was being shown at 0.4: six pixel labels, and the last node clipped anyway.
   Below the floor the desk stops fitting BOTH axes and fits the WIDTH, which is what the
   phone has always done, and the stage is panned down the rest. */
check('the desk never fits below the readable floor', B.fittedView(2861, 104, 862, 542, true).scale >= 0.6);
const chain = B.fittedView(2861, 104, 862, 542, true);
check('and what it fits instead is the width, not both axes', near(chain.scale, 0.6));
check('a board that fits both axes above the floor still fits both',
      near(B.fittedView(632, 700, 862, 542, true).scale, (542 - 16) / 700));

/* WHICH OF TWO LAYOUTS IS DRAWN. A layout that can be read WHOLE beats one that cannot,
   however much bigger the second is drawn: the grouped board folded RIGHT came out 1256 x
   889, which reads at 0.673 with its bottom off the stage, and laid out DOWN it is 1206 x
   761, whole, at 0.691. Between two that both fail, the bigger one wins. */
const rightWrapped = B.layoutScore(1256, 889, 862, 542, true);
const downwards = B.layoutScore(1206, 761, 862, 542, true);
check('a layout that fits whole and readably beats one that does not', downwards > rightWrapped);
check('and it says so by a mile, not by a hair', downwards > 1000 && rightWrapped < 1000);
/* Between two that cannot be read whole, `choose` (ui.boardlayout.js) compares how much of
   each is on the stage (`visibleShare`), not this score: round 2 of lane K. */
check('a flat chain shows a share of itself that says it is cut',
      B.visibleShare(2861, 104, 862, 542, true) < 0.5 && B.visibleShare(632, 700, 862, 542, true) === 1);

/* NEVER BLOWN UP BECAUSE IT OVERFLOWS: a tall narrow drawing that cannot be read whole is
   drawn at its natural size at most, not at the 2.5 its width alone would allow. */
check('a tall narrow drawing is not zoomed past its natural size', near(B.fittedView(276, 1092, 1138, 528, true).scale, 1));
check('but one whose width fit is under 1 still fits the width (W4)', near(B.fittedView(1256, 889, 862, 542, true).scale, (862 - 16) / 1256));
check('fitBoth ignores the readable floor and answers for the whole board',
      near(B.fitBoth(1206, 761, 862, 542), (542 - 16) / 761));

/* The raw ratio, before any clamp: the number that decides what is actually drawn. */
check('the desk asks for both axes', near(B.fitScale(1000, 500, 800, 600, true), (600 - 16) / 500 > (800 - 16) / 1000 ? (800 - 16) / 1000 : (600 - 16) / 500));
check('the phone asks for the width alone', near(B.fitScale(1000, 2000, 858, 600, false), (858 - 16) / 1000));
check('a desk graph that cannot be read at both axes asks for the width',
      near(B.fitScale(2861, 104, 862, 542, true), (862 - 16) / 2861));

/* THE STAGE'S SIZE IS WHAT A HAND-SET ZOOM IS RELATIVE TO. Keeping it across a resize, a
   view switch or the phone's drawer opening leaves him looking at the wrong part of a
   diagram that is no longer the size it was fitted against. */
const mine = B.fittedView(1000, 500, 800, 600, true);
mine.user = true;
mine.scale = 1.5;
const again = B.fittedView(1000, 500, 800, 600, true);
check('his zoom survives a redraw at the same size',
      B.viewFor(mine, again, 800, 600, false).scale === 1.5);
check('and it is dropped when the stage changed size',
      B.viewFor(mine, again, 640, 600, false).user === false);
check('a fresh board is always fitted, whatever he did to the last one',
      B.viewFor(mine, again, 800, 600, true).user === false);
check('a view he never touched is refitted anyway',
      B.viewFor(B.fittedView(1000, 500, 800, 600, true), again, 800, 600, false).user === false);
check('the kept view carries the size it is relative to',
      B.viewFor(mine, again, 800, 600, false).forW === 800);

/* THE WALK PANS TO ITS STEP'S NODE, and only when it has to. An axis the whole diagram
   already fits on cannot have a node off the edge, so moving it there throws the rest of
   the graph off the OTHER side, which is what the walk did the moment the fit could show
   the whole board. One axis at a time, and only the one that is out of view. */
const view0 = { tx: 8, ty: 100, scale: 0.5 };
const fits = { width: 1600, height: 800 };        // 800 x 400 drawn, inside a 900 x 600 wrap
check('a node in view moves nothing',
      B.panFor(view0, { x: 400, y: 200 }, fits, 900, 600) === null);
check('and a node off the bottom of an axis that FITS still moves nothing',
      B.panFor(view0, { x: 400, y: 780 }, fits, 900, 600) === null);
const overflowing = { width: 4000, height: 800 };  // 2000 wide drawn, in a 900 wrap: x does not fit
const panned = B.panFor(view0, { x: 3800, y: 200 }, overflowing, 900, 600);
check('a node off the edge of an axis that does NOT fit is centred on that axis',
      panned && near(panned.tx, 900 / 2 - 3800 * 0.5));
check('and the axis that fits is left exactly where it was', near(panned.ty, 100));
const view = { scale: 3, fitted: 3, tx: -40, ty: 25, user: false };   // 6 is inside the band
const world = { x: (100 - view.tx) / view.scale, y: (50 - view.ty) / view.scale };
B.zoomAbout(view, 100, 50, 2);
check('the scale doubled', near(view.scale, 6));
check('the point under the cursor stayed under it (x)', near(world.x * view.scale + view.tx, 100));
check('the point under the cursor stayed under it (y)', near(world.y * view.scale + view.ty, 50));
check('zooming records that he set it by hand', view.user === true);
const same = { scale: 1, fitted: 1, tx: 10, ty: 20, user: false };
B.zoomAbout(same, 0, 0, 1);
check('a factor of one changes nothing', near(same.tx, 10) && near(same.ty, 20) && near(same.scale, 1));

process.stdout.write(JSON.stringify(fails.length ? { ok: false, failed: fails } : { ok: true }));
