/* THE FULL-SCREEN BOARD (C6, 2026-09-23).
 *
 * A diagram of twelve nodes is drawn into whatever the deck leaves it: the rail, the header,
 * the board header, the ask row and, on the phone, the dock. This gives it the whole screen.
 * A toggle in the board header (and `f` on the desk) hides the deck's header, rail, dock and
 * the board list; the board's own items (notes, steps, tables, files), the view switch and
 * the walk controls move to a slim side rail on the desk that collapses to icons, and to a
 * BOTTOM SHEET over the diagram on the phone, never a drawer (P2, I8).
 *
 * TWO MECHANISMS, ONE MODE. The desk asks the Fullscreen API for the page. An iPhone has no
 * element fullscreen, so there, and anywhere the API refuses, the same mode is a FOCUS mode:
 * all the chrome hidden, the stage 100dvh, the sheet above `env(safe-area-inset-bottom)`.
 * Either way `body.board-full` is what the CSS keys on, and leaving is the same tap.
 *
 * ENTERING OR LEAVING CHOOSES THE LAYOUT AGAIN (round 3 of lane K, 2026-09-24, K-12).
 * Full screen exists to make the board BIGGER: keeping the shape the page or the walk drew
 * left b-009 as a 0.60 strip across an empty 1440 x 900 screen, where laid out afresh it is
 * a clean column at 0.79. So `enter` and `leave` forget this board's kept shapes
 * (`forgetShapes`) before the stage is drawn again (`refit`); every OTHER change of the
 * stage's size (the rail folding, a resize, the node column) keeps the shape, within its
 * slack (K-9), because only the toggle is him asking for a bigger board.
 */
(function (K) {
  'use strict';

  function inner() { return K.boardInner || null; }

  function refit() {
    requestAnimationFrame(function () {
      Array.prototype.forEach.call(document.querySelectorAll('.kind-graph'), function (host) {
        host._view = null;
        host._drawn = -1;
        host._shape = '';
      });
      K.renderBody();
    });
  }

  function forgetShapes() {
    var B = K.boardState, id = B && B.open && B.open.id;
    if (!id || !B.layouts) return;
    Object.keys(B.layouts).forEach(function (key) {
      if (key.indexOf(id + ':') === 0) delete B.layouts[key];
    });
  }

  function apiFullscreen() {
    var root = document.documentElement;
    return K.isDesk() && root && typeof root.requestFullscreen === 'function' && document.fullscreenEnabled !== false;
  }

  function enter() {
    var B = K.boardState;
    B.full = true;
    forgetShapes();
    B.rail = B.rail === undefined ? K.isDesk() : B.rail;   // the phone's sheet starts folded: the diagram is what he asked for
    document.body.classList.add('board-full');
    if (apiFullscreen()) {
      B.fullApi = true;
      document.documentElement.requestFullscreen().catch(function () { B.fullApi = false; });
    } else {
      B.fullApi = false;            // focus mode: the chrome is hidden and nothing else is asked
    }
    refit();
  }

  function leave() {
    var B = K.boardState;
    B.full = false;
    forgetShapes();
    document.body.classList.remove('board-full');
    if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(function () {});
    B.fullApi = false;
    refit();
  }

  function toggle() { if (K.boardState.full) leave(); else enter(); }

  /* THE MODE CAN NEVER OUTLIVE THE BOARD (review F2). `board-full` hides the rail, the
     header and the dock, so a mode left on after Back, a move to another board or the
     error page is a deck with no navigation at all. The class is derived from the state on
     every render pass (`ui.js` calls this before it paints), and any state that is not
     "this board, open, on the board route" leaves. */
  function valid() {
    var B = K.boardState;
    return !!(B && B.open && !B.error && K.App && K.App.view === 'board' &&
              K.App.board && B.open.id === K.App.board);
  }
  function sync() {
    var B = K.boardState;
    if (!B) return;
    if (B.full && !valid()) { leave(); return; }
    if (B.full) document.body.classList.add('board-full');
    else document.body.classList.remove('board-full');
  }
  window.addEventListener('popstate', sync);

  /* Esc on the desk leaves the browser's fullscreen without asking the page, so the page
     follows it rather than leaving the chrome hidden around a window that is not full. */
  document.addEventListener('fullscreenchange', function () {
    var B = K.boardState;
    if (!B) return;
    if (!document.fullscreenElement && B.full && B.fullApi) leave();
    else refit();
  });

  /* `f` on the desk, on an open board, when he is not typing. */
  document.addEventListener('keydown', function (ev) {
    if (ev.key !== 'f' && ev.key !== 'F') return;
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    var t = ev.target, tag = t && t.tagName ? t.tagName.toLowerCase() : '';
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || (t && t.isContentEditable)) return;
    if (!K.App || K.App.view !== 'board' || !K.App.board || !K.boardState || !K.boardState.open) return;
    ev.preventDefault();
    toggle();
  });

  function button() {
    var on = !!(K.boardState && K.boardState.full);
    return K.el('button', { class: 'bnav fullbtn', 'data-key': 'full',
      title: on ? 'leave full screen (f)' : 'full screen (f)',
      'aria-label': on ? 'leave full screen' : 'give the diagram the whole screen',
      'aria-pressed': on ? 'true' : 'false', onclick: toggle }, on ? '✕' : '⛶');
  }

  /* ---------- the layout ---------- */
  function railToggle(B, open) {
    return K.el('button', { class: 'bnav', 'data-key': 'railtoggle',
      'aria-label': open ? 'fold the side rail to icons' : 'open the side rail',
      onclick: function () { B.rail = !open; refit(); } },
      K.isDesk() ? (open ? '›' : '‹') : (open ? '▾' : '▴'));
  }

  function iconViews(I) {
    var now_ = I.viewOf();
    return K.el('div', { class: 'bfull-icons' }, I.VIEWS.map(function (name) {
      return K.el('button', { class: 'bnav' + (now_ === name ? ' on' : ''), 'data-key': 'v' + name,
        title: name, 'aria-label': 'see this board as a ' + name,
        onclick: function () { I.setView(name); refit(); } }, name.charAt(0).toUpperCase());
    }));
  }

  /* Stepping is a render, not a refit: the stage keeps its layout and its zoom, the lit
     node is panned into view, and the step's words are the stage's callout (Z1). */
  function walkControls(I, model) {
    var B = K.boardState, steps = I.stepsOf(model);
    if (!steps.length) return K.el('div', { class: 'empty t11 ink3', text: 'no steps on this board' });
    var at = Math.max(0, Math.min(B.step, steps.length - 1));
    return K.el('div', { class: 'bfull-walk', 'data-key': 'walk' },
      K.el('div', { class: 'bwalk-head' },
        K.el('button', { class: 'bnav', 'aria-label': 'the step before this one', disabled: at <= 0 ? true : null,
          onclick: function () { B.step = at - 1; K.renderBody(); } }, '‹'),
        K.el('span', { class: 'bcount mono t11 ink2', text: (at + 1) + ' of ' + steps.length }),
        K.el('button', { class: 'bnav', 'aria-label': 'the next step', disabled: at >= steps.length - 1 ? true : null,
          onclick: function () { B.step = at + 1; K.renderBody(); } }, '›')));
  }

  function items(I, model) {
    var B = K.boardState;
    var node = B.node ? I.nodeBy(model, B.node) : null;
    return K.el('div', { class: 'bfull-items', 'data-key': 'items' },
      K.el('div', { class: 'label ellip', text: node ? node.label : 'On the board' }),
      I.attachmentList(model, node ? node.id : I.BOARD_TARGET,
        node ? 'nothing hangs on this node yet' : 'tap a node to see what hangs on it'));
  }

  function side(I, model, view) {
    var B = K.boardState, open = B.rail !== false, desk = K.isDesk();
    var record = B.open.record || {};
    var cls = desk ? 'bfull-rail' : 'bfull-sheet';
    if (!open && desk) {
      return K.el('aside', { class: cls + ' shut', 'data-key': 'side' },
        railToggle(B, false), button(), iconViews(I));
    }
    return K.el('aside', { class: cls + (open ? '' : ' shut'), 'data-key': 'side' },
      K.el('div', { class: 'bfull-head' },
        railToggle(B, open),
        K.el('span', { class: 't ellip', title: record.title, text: record.title || 'Untitled board' }),
        button()),
      open ? K.el('div', { class: 'bfull-body' },
        I.viewSwitch(),
        view === 'walk' ? walkControls(I, model) : null,
        view !== 'outline' ? items(I, model) : null) : null);
  }

  function stage(I, model, view) {
    var B = K.boardState;
    if (view === 'outline') return K.el('div', { class: 'bfull-stage bfull-outline' }, I.outlineView(model));
    var focus = B.node, walk = null;
    if (view === 'walk') {
      var steps = I.stepsOf(model), at = Math.max(0, Math.min(B.step, steps.length - 1)), item = steps[at];
      focus = item && item.at !== I.BOARD_TARGET ? item.at : null;
      /* THE CALLOUT SHOWS HERE TOO (Z1): full screen is where a plan's embedded board opens,
         and the caption bar carries the steppers, because the phone's sheet starts folded. */
      walk = item ? I.walkSpec(model, steps, at, true) : null;
    }
    return K.el('div', { class: 'bfull-stage bframe bstage', 'data-key': 'bstage' },
      I.stageHost(model, false, focus, walk));
  }

  function view(model, viewName) {
    var I = inner();
    return K.el('section', { class: 'bfull', 'data-view': viewName, 'data-key': 'bfull' },
      stage(I, model, viewName), side(I, model, viewName));
  }

  K.boardFull = { view: view, toggle: toggle, enter: enter, leave: leave, button: button, sync: sync };
})(window.Keel);
