/* The plan page's boot (P2-5): a plan or an outcome as a page of its own.
 *
 * `/plan/<c-id>` and `/outcome/<c-id>` are served from `app/plan.html`, which loads the
 * deck's core (the element builder, the morph, the POST with its cookie renewal, the sheet
 * and the toast), the board's drawing, and the plan's own renderers, and NOT the deck's
 * boot (`ui.js`): there is no rail, no header, no dock, no card list and no `/api/state`
 * load to wait for. The document is the page, and the page scrolls.
 *
 * The one live channel is the deck's own: `/api/events?plan=<id>` says `card <id>` when a
 * mark lands and `plan <id>` when the house rewrites the file, and the page reloads its
 * one answer (`K.loadPlan`). With the stream shut (a reconnect, a hidden tab) nothing
 * polls; showing the tab again reloads once and reopens it.
 */
(function (K) {
  'use strict';

  var App = K.App;

  function renderBody() {
    K.paint('body', K.viewPlan());
    if (App.sheet) K.renderSheet();
  }
  /* A verb's answer (`K.act`) reloads the deck's state and then calls `K.render`; here that
     is the page itself, and the state it read is not what this page draws. */
  K.render = renderBody;
  K.renderBody = renderBody;
  /* the deck's chrome does not exist on this page; the calls that reach for it are no-ops */
  K.renderRail = K.renderHeader = K.renderControls = K.renderDock = function () {};
  K.markStrips = K.markStrips || function () {};

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') { K.openStream(); K.loadPlan(true); }
    else K.closeStream();
  });
  window.addEventListener('resize', function () {
    clearTimeout(App.resizeTimer);
    App.resizeTimer = setTimeout(renderBody, 140);
  });
  window.addEventListener('popstate', function () { K.readPlanRoute(); renderBody(); });

  K.readPlanRoute();
  renderBody();
  K.openStream();
})(window.Keel);
