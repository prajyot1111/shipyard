/* Which layout the desk draws (K1 to K3, 2026-09-24), checked against the REAL vendored ELK.
 *
 * b-009 ("Event Replay: where the example runs in code", three groups) read cleanly top to
 * bottom in the walk's compact graph and, in full screen, came out folded into rows with an
 * edge between the groups routed round the whole drawing. `layoutBest` scored a layout only
 * on whether it fit, and a wide stage let the folded one fit. This runs the page's own
 * `layoutBest` (ui.board.js, with ui.boardlayout.js beside it) on `board-b009.txt`, a
 * hand-written board of the same shape, and on W1's long single chain.
 *
 * Under node there is no canvas, so text is measured by `textWidth`'s linear estimate; the
 * sizes differ a little from a browser's, the shapes do not.
 *
 * Usage: node board-layout.js <path to the app directory> <path to board-b009.txt>
 * Output: {"ok": true, ...numbers}, or a JSON object naming the checks that failed.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const app = path.resolve(process.argv[2]);
const ELK = require(path.join(app, 'vendor', 'elk.bundled.js'));
/* TEXT IS MEASURED AS CHROME MEASURES IT. `board-text-widths.json` holds canvas
   `measureText` widths taken in Chrome for every string these layouts ask about, keyed by
   font and text, so the layout here is the deck's to the pixel (b-009 laid out RIGHT is
   1874px wide in both). A string missing from it falls back to the linear estimate and is
   listed in `seen.unmeasured`; `board-text-measure.js` says how to measure new ones. */
const WIDTHS = JSON.parse(fs.readFileSync(path.join(__dirname, 'board-text-widths.json'), 'utf8'));
const asked = {}, unmeasured = new Set();
function measureContext() {
  const ctx = { font: '' };
  ctx.measureText = text => {
    const key = ctx.font + '|' + text;
    asked[key] = true;
    if (key in WIDTHS) return { width: WIDTHS[key] };
    unmeasured.add(key);
    return { width: text.length * parseFloat(ctx.font) * 0.55 };
  };
  return ctx;
}
const win = { Keel: {}, addEventListener() {}, matchMedia: () => ({ matches: true }) };
const doc = {
  visibilityState: 'hidden',
  createElement: () => ({ getContext: () => measureContext() }),
  createElementNS: () => ({ setAttribute() {}, appendChild() {} }),
  addEventListener() {}, getElementById: () => null, querySelector: () => null
};
for (const name of ['ui.boardlayout.js', 'ui.board.js']) {
  const file = path.join(app, name);
  if (!fs.existsSync(file)) continue;
  new Function('window', 'document', 'setInterval', 'requestAnimationFrame', 'fetch', 'history',
               fs.readFileSync(file, 'utf8'))(
    win, doc, () => 0, () => 0, () => Promise.resolve(), { pushState() {}, replaceState() {} });
}

const B = win.Keel.board, L = win.Keel.boardLayout;
const fails = [], seen = {};
function check(name, ok) { if (!ok) fails.push(name); }
function done() {
  if (process.env.KEEL_RECORD_TEXT) fs.writeFileSync(process.env.KEEL_RECORD_TEXT, JSON.stringify(Object.keys(asked)));
  if (unmeasured.size) seen.unmeasured = [...unmeasured];
  process.stdout.write(JSON.stringify(fails.length ? { ok: false, failed: fails, seen } : { ok: true, seen }));
}
if (!B || typeof B.layoutBest !== 'function' || !L) {
  fails.push('ui.board.js exports no layoutBest, or ui.boardlayout.js is missing');
  done();
  process.exit(0);
}

const engine = new ELK();
const b009 = B.foldInto(B.newModel(), fs.readFileSync(process.argv[3], 'utf8').split('\n'));
const chain = B.foldInto(B.newModel(), ['board "How drawing on the board works"']
  .concat([0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map(i => 'node d' + i + ' box "drawing step ' + i + '"'))
  .concat([0, 1, 2, 3, 4, 5, 6, 7, 8].map(i => 'edge d' + i + ' -> d' + (i + 1) + ' "then ' + i + '"')));

/* The stages, in CSS pixels, as MEASURED on the deck (the graph wrap's clientWidth and
   clientHeight, playwright-core, Chrome): per window, the full-screen stage with the rail
   open, the diagram on the page, and the walk's compact graph. W1 is the stage the chain
   was first measured in. */
const SCREENS = {
  '1280x800': { full: [960, 800], page: [978, 428], compact: [1034, 374] },
  '1440x900': { full: [1120, 900], page: [1138, 528], compact: [1194, 474] },
  '1920x1080': { full: [1600, 1080], page: [1618, 708], compact: [1674, 654] }
};
const W1 = [862, 542], FULL = SCREENS['1440x900'].full, FOLDED_RAIL = [1384, 900];

function direction(laid) { return (laid.layoutOptions || {})['elk.direction']; }
function folded(laid) { return !!(laid.layoutOptions || {})['elk.layered.wrapping.strategy']; }
function shape(best) { return direction(best.laid) + (folded(best.laid) ? ':folded' : ''); }
/* Every edge label box against every group title box, in the drawing's own coordinates. */
function titleHits(laid) {
  const titles = [], labels = [], lines = [];
  (function walk(node, ox, oy) {
    (node.children || []).forEach(c => {
      const x = ox + (c.x || 0), y = oy + (c.y || 0);
      if (c.id.indexOf('g_') === 0) {
        const t = B.groupTitleBox((c.labels || [])[0] ? c.labels[0].text : '');
        titles.push({ id: c.id, x: x + t.x, y: y + t.y, width: t.width, height: t.height });
      }
      walk(c, x, y);
    });
    (node.edges || []).forEach(e => {
      (e.labels || []).forEach(l =>
        labels.push({ id: e.id, x: ox + l.x, y: oy + l.y, width: l.width, height: l.height }));
      (e.sections || []).forEach(sec => {
        const pts = [sec.startPoint].concat(sec.bendPoints || [], [sec.endPoint]);
        for (let i = 1; i < pts.length; i++) {
          const a = pts[i - 1], b = pts[i];
          lines.push({ id: e.id + ' line', x: ox + Math.min(a.x, b.x) - 0.75, y: oy + Math.min(a.y, b.y) - 0.75,
                       width: Math.abs(a.x - b.x) + 1.5, height: Math.abs(a.y - b.y) + 1.5 });
        }
      });
    });
  })(laid, 0, 0);
  const meet = (a, b) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
  const out = { labels: [], lines: [] };
  labels.forEach(l => titles.forEach(t => { if (meet(l, t)) out.labels.push(l.id + ' on ' + t.id); }));
  lines.forEach(l => titles.forEach(t => { if (meet(l, t)) out.lines.push(l.id + ' on ' + t.id); }));
  return out;
}
const lay = (model, [w, h], kept) => B.layoutBest(engine, model, true, w, h, kept);

(async () => {
  check('b-009 has three groups', b009.groups.length === 3 && b009.nodes.length === 11);
  seen.b009 = {};
  for (const name of Object.keys(SCREENS)) {
    const at = SCREENS[name], got = {};
    for (const place of ['full', 'page', 'compact']) got[place] = await lay(b009, at[place]);
    const cost = L.readability(got.full.laid);
    seen.b009[name] = { full: shape(got.full), page: shape(got.page), compact: shape(got.compact), outside: cost.outside };
    /* K1: the bug itself. No full-screen stage gets an edge sent round the outside, and
       what it draws can be read whole. */
    check(name + ': b-009 full screen has no edge routed around the outside', cost.outside === 0);
    check(name + ': and it can be read whole at the floor', got.full.fit >= 1000);
    /* K2: several groups are never folded. */
    check(name + ': b-009 is not folded anywhere',
          !folded(got.full.laid) && !folded(got.page.laid) && !folded(got.compact.laid));
  }
  /* FULL SCREEN CHOOSES AGAIN (round 3, reversing K-4). Full screen exists to make the
     board bigger, so entering it lays the board out afresh for the new stage (the page
     forgets the kept shape on the toggle: board-full.js checks that half). Among the layouts
     readable whole at the floor the cheapest wins and then the one drawn bigger: b-009 at
     1440 and 1280 is the large clean DOWN column, not a 0.60 strip kept from the walk. */
  const at1440 = SCREENS['1440x900'];
  const page1440 = await lay(b009, at1440.page);
  const walk1440 = await lay(b009, at1440.compact);
  seen.b009.rightWidth = Math.round(walk1440.laid.width);
  for (const name of ['1440x900', '1280x800']) {
    const full = await lay(b009, SCREENS[name].full);
    const view = B.fittedView(full.laid.width, full.laid.height, SCREENS[name].full[0], SCREENS[name].full[1], true);
    seen.b009['full' + name] = { shape: shape(full), scale: view.scale };
    check(name + ' full screen: b-009 is the DOWN column', shape(full) === 'DOWN');
    if (name === '1440x900') check('1440 x 900 full screen: drawn at 0.75 or more', view.scale >= 0.75);
  }
  const tie = L.choose([{ name: 'small', fit: 1000.6, cost: 2, scale: 0.6 }, { name: 'big', fit: 1000.9, cost: 2.2, scale: 0.9 }]);
  check('between two readable layouts costing about the same, the one drawn bigger wins', tie.name === 'big');

  /* KEPT WITH SLACK EVERYWHERE ELSE (K-9): the rail folding in full screen is a change of
     the stage's size on the same board, and keeps what full screen chose. */
  const full1440 = await lay(b009, at1440.full);
  const railKept = await lay(b009, FOLDED_RAIL, full1440.choice);
  const railFresh = await lay(b009, FOLDED_RAIL);
  seen.b009.rail = { kept: shape(railKept), fresh: shape(railFresh) };
  check('folding the rail keeps the shape full screen chose', railKept.choice === full1440.choice);
  const walkKept = await lay(b009, [at1440.compact[0] - 40, at1440.compact[1]], walk1440.choice);
  check('a slightly narrower walk keeps its shape inside the slack', walkKept.choice === walk1440.choice);

  /* NOTHING UNDER THE EDGE (round 3). Every layout the fit draws WHOLE has every node box
     inside the visible stage, at every measured size and place, and a kept one inside the
     slack is drawn whole below the floor rather than cut at it (the Events DB box was cut
     about 20px at the rail). The measured stages are the graph wraps, which already stop
     at the rail. */
  function outsideNodes(best, [w, h]) {
    const v = B.fittedView(best.laid.width, best.laid.height, w, h, true), out = [];
    /* The whole drawing (the group boxes, their padding, every edge) as well as each node:
       in the round 2 shot the node stopped at 1113 but its group ran on to 1132, under the
       rail at 1120. */
    if (v.tx < 0 || v.ty < 0 || v.tx + best.laid.width * v.scale > w + 0.01 ||
        v.ty + best.laid.height * v.scale > h + 0.01) out.push('the drawing');
    (function walk(node, ox, oy) {
      (node.children || []).forEach(c => {
        const x = ox + (c.x || 0), y = oy + (c.y || 0);
        if (c.id.indexOf('n_') === 0) {
          const l = v.tx + x * v.scale, t = v.ty + y * v.scale;
          const r = l + c.width * v.scale, btm = t + c.height * v.scale;
          if (l < 0 || t < 0 || r > w + 0.01 || btm > h + 0.01) out.push(c.id);
        }
        walk(c, x, y);
      });
    })(best.laid, 0, 0);
    return out;
  }
  const whole = (best, [w, h]) => B.fitBoth(best.laid.width, best.laid.height, w, h) >= 0.6 * 0.95;
  for (const name of Object.keys(SCREENS)) {
    for (const place of ['full', 'page', 'compact']) {
      const at = SCREENS[name][place], got = await lay(b009, at);
      if (!whole(got, at)) { (seen.pannable = seen.pannable || []).push(name + ' ' + place); continue; }
      const cut = outsideNodes(got, at);
      check(name + ' ' + place + ': every node and group is inside the visible stage', cut.length === 0);
    }
  }
  check('1440 x 900 page: the RIGHT row a pixel under the floor is drawn whole',
        outsideNodes(page1440, at1440.page).length === 0);
  const keptRight = await lay(b009, at1440.full, walk1440.choice);
  check('a kept layout inside the slack is drawn whole, not cut at the floor',
        keptRight.choice === walk1440.choice && outsideNodes(keptRight, at1440.full).length === 0);

  /* THE FALLBACK (round 2, reversing W3's second clause). On the 1138 x 528 page stage
     neither layout of b-009 reads whole. The DOWN column used to win because its WIDTH fit
     was bigger, and was drawn at the 2.5 ceiling showing a fifth of itself. Now the one that
     shows the most of itself at its drawn scale wins, and a drawing that overflows is never
     blown up past its natural size to fill the other axis. */
  const pageView = B.fittedView(page1440.laid.width, page1440.laid.height, at1440.page[0], at1440.page[1], true);
  const shown = B.visibleShare(page1440.laid.width, page1440.laid.height, at1440.page[0], at1440.page[1], true);
  seen.b009.page1440 = { shape: shape(page1440), scale: pageView.scale, shown };
  check('1440 x 900 page: b-009 draws RIGHT', shape(page1440) === 'RIGHT');
  check('1440 x 900 page: near the floor', pageView.scale <= 0.65);
  check('1440 x 900 page: showing nearly all of itself', shown >= 0.95);
  const down = { laid: await engine.layout(B.buildGraph(b009, 'DOWN', 0).root) };
  const downView = B.fittedView(down.laid.width, down.laid.height, at1440.page[0], at1440.page[1], true);
  seen.b009.page1440.downScale = downView.scale;
  check('a DOWN column that overflows is not blown past its natural size', downView.scale <= 1);
  check('and RIGHT shows more of itself than DOWN does',
        shown > B.visibleShare(down.laid.width, down.laid.height, at1440.page[0], at1440.page[1], true));

  /* THE GROUP TITLE IS CLEAR (round 2): no edge label box sits on a group's title, in any
     place on any screen; the group's top padding comes from the title's height. An edge's
     own LINE can still enter a DOWN group through its title (ELK brings it in at the top
     wherever it likes, and b-009's CLOUD EVENTS SERVICE title spans its group), so the
     titles are drawn above the edges on a plate (`drawGroups`), and the crossings are
     recorded in `seen.titleLines` rather than asserted away. */
  for (const name of Object.keys(SCREENS)) {
    for (const place of ['full', 'page', 'compact']) {
      const got = await lay(b009, SCREENS[name][place]);
      const hits = titleHits(got.laid);
      if (hits.lines.length) (seen.titleLines = seen.titleLines || []).push(name + ' ' + place + ': ' + hits.lines.join(', '));
      check(name + ' ' + place + ': no edge label sits on a group title', hits.labels.length === 0);
    }
  }
  check('the group padding clears the title', B.GROUP_PAD_TOP >= B.groupTitleBox('web').y + B.groupTitleBox('web').height + 8);

  /* K2: W1's chain still folds. */
  check('the fold is for a simple chain', L.shouldFold(chain) === true && L.shouldFold(b009) === false);
  const w1 = await lay(chain, W1);
  seen.chain = { page: shape(w1), width: w1.laid.width, height: w1.laid.height };
  check("W1's single wide chain still folds into rows on the page",
        shape(w1) === 'RIGHT:folded' && w1.laid.height > 2 * 64);
  check('and the fold can be read whole', w1.fit >= 1000);

  /* K3: the shape kept across full screen. What the page drew is kept at the full-screen
     stage while it can still be read there, and chosen again when it cannot. */
  const kept = await lay(chain, FULL, w1.choice);
  check('entering full screen keeps the folded chain it had',
        shape(kept) === 'RIGHT:folded' && kept.laid.width === w1.laid.width && kept.laid.height === w1.laid.height);
  const tiny = await lay(chain, [420, 300], w1.choice);
  check('a kept layout that cannot be read at the new size is chosen again',
        B.layoutScore(tiny.laid.width, tiny.laid.height, 420, 300, true) >=
        B.layoutScore(w1.laid.width, w1.laid.height, 420, 300, true) && tiny.choice !== w1.choice);
  const phone = await B.layoutBest(engine, b009, false, 358, 600);
  check('the phone still lays out DOWN', shape(phone) === 'DOWN');
  done();
})().catch(err => { fails.push('threw: ' + err); done(); });
