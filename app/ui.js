/* The deck's boot: which view the body draws, the render pass, and the live channel.
 *
 * The page is one state document, and every write goes through /api/action. The modules
 * are app/views.json's `scripts` (c-634): ui.core (state, helpers, the morph, routing,
 * chrome) first, each view's own file, and this one last, which starts them.
 *
 * Three rules, and between them the page stops looking like it reloads.
 *
 * 1. The render pass MORPHS (`K.morph`, ui.core.js). The tree is built fresh every pass
 *    and only what differs is written into the live one, so the live node never leaves
 *    the document and the scroll offsets, the caret, the selection, a transition part way
 *    through and the board's own pan and zoom survive by construction.
 * 2. NOTHING RENDERS WHEN NOTHING CHANGED. The state document carries a `rev`; the page
 *    holds its ETag and a 304 ends the pass before `render` is reached.
 * 3. The page is TOLD what changed rather than asking. One `EventSource` on `/api/events`
 *    while the tab is visible (`ui.core.js`), and the five second poll is what runs only
 *    while that stream is not open.
 *
 * The modal and the sheet draw themselves and are morphed too, so a half-filled form and
 * a half-typed gate answer survive anything that repaints. */
(function (K) {
  'use strict';

  var App = K.App;

  /* The body is its view's `render`, from the manifest's row (app/views.json, c-634): one
     lookup, so a new view is a row and a script and never an edit here. A route no row
     names draws Now. */
  function bodyContent() {
    var v = K.viewOf(App.view);
    return v && K[v.render] ? K[v.render](v.arg) : K.viewNow();
  }

  /* A click that lands on the page's own background, with no card row, tile or control
     under it, closes the open card or the open provider row: the third way out, beside
     the ✕ and Escape. */
  function outsideCloses(ev) {
    if ((!App.card && !App.row) || !K.isDesk()) return;
    var t = ev.target;
    if (!t || !t.closest) return;
    if (t.closest('.split-pane, .drawer, .modal, .sheet, .toast')) return;
    if (t.closest('tr.card, .row, .tile, .slice, .compact, button, a, input, select, textarea, label')) return;
    K.closeDetail();
  }

  /* A page whose `needs` (its VIEWS entry, c-631) are unmet opens with the panel saying
     what is missing and where to set it up. Only from the entry, and never over an open
     card. */
  function needsPanel() {
    var v = K.viewOf(App.view);
    return v && v.needs && v.needs.length && !App.card ? K.needs(v.needs) : null;
  }
  function renderBody() {
    /* the full-screen board's class follows the route before anything is painted (F2) */
    if (K.boardFull) K.boardFull.sync();
    var panel = needsPanel(), content = bodyContent();
    K.paint('body', panel ? [panel].concat(content) : content);
    /* `enterRoute` moves the page only on the pass that enters a route, never on a poll. */
    K.enterRoute();
    K.markStrips();
    /* the row a setup action runs on stays marked through every repaint (app/ui.setup.js) */
    if (K.markWorking) K.markWorking();
    K.followScope();
  }

  function render() {
    if (!App.data) return;
    K.renderRail(); K.renderHeader(); K.renderControls(); K.renderDock();
    renderBody();
    document.title = (K.needsYou().length ? '(' + K.needsYou().length + ') ' : '') + 'Shipyard';
  }
  K.render = render; K.renderBody = renderBody;

  /* THE FALLBACK, not the channel. It fires only while the event stream is shut: a
     reconnect in progress, a browser with no EventSource, a door that does not answer the
     route. With the stream open this costs nothing at all. */
  function poll() {
    clearInterval(App.timer);
    App.timer = setInterval(function () {
      if (document.visibilityState !== 'visible' || K.streamOpen()) return;
      K.load();
    }, K.POLL_MS);
  }
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') { K.openStream(); K.load(); K.loadHealth(); }
    else K.closeStream();
  });
  window.addEventListener('resize', function () { clearTimeout(App.resizeTimer); App.resizeTimer = setTimeout(render, 140); });
  document.getElementById('body').addEventListener('click', outsideCloses);

  K.readRoute();
  if (App.card) K.loadDetail(App.card, true);
  K.load().then(function () { poll(); K.openStream(); K.watchHealth(); });
})(window.Keel);
