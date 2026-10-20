/* Leaving a view that has something unsaved (c-661): the one question, and the way back
 * onto the entry he was on when Back or Forward is refused.
 *
 * THE QUESTION. A view that may refuse a move sets `K.beforeLeave(from, to)` (Settings does,
 * app/ui.settings.js: it asks him, and false keeps him there). `K.leave.may` is its one
 * caller. app/ui.core.js asks it in `go` before it moves anything, and hands every popstate
 * to `K.leave.popped` before it reads the route, so a refused move has no side effects.
 *
 * THE WAY BACK. By the time popstate fires the browser is already on the other entry, and
 * the History API says neither which way he went nor how far. So every entry this page
 * makes carries a stamp that only grows along the history: `history.pushState` and
 * `history.replaceState` are wrapped here, once, for every caller (`go`, a selected row, the
 * find bar, the Atlas, a board), and the entry the page loaded on is stamped as this file
 * loads. A push gets a new stamp; a replace keeps the one its entry has. Each render pass
 * notes the URL and the stamp of the entry it drew (`K.leave.note`, from `enterRoute`).
 *
 * A refusal compares the stamp of the entry he landed on with the noted one, which says the
 * direction, and walks back with `history.go`, a step at a time, until the stamp matches.
 * That leaves no second copy of the entry and keeps what lay ahead of it, after a Back or a
 * Forward of any length, across entries that have no stamp.
 *
 * WHAT IS LEFT. An entry has no stamp only when this page did not make it through those two
 * calls: a `#fragment` link, or an entry from a deck loaded before this file existed. When
 * he LANDS on one, or was ON one when he moved, the direction cannot be known, so the entry
 * he was on is pushed again with the search string it had. After a Back that drops the old entry and everything ahead
 * of it. After a Forward it adds a second copy of the entry and drops what lay ahead of the
 * one he landed on. The same push is the answer when a walk passes the stamp it is looking
 * for without meeting it. A walk whose popstate never comes is forgotten after WALK_MS, so
 * it cannot swallow a later Back.
 *
 * Loaded by the deck's page only (app/views.json). A page without it (the plan page, the
 * Console) has no guard and its history is untouched. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var WALK_MS = 2000;
  var entry = { url: null, k: null };   /* the entry the last render pass drew */
  var lastK = 0;
  var returning = null;                 /* a walk back in flight: { k, url, step, at } */

  function stampOf() { var s = history.state; return s && typeof s.k === 'number' ? s.k : null; }
  function fresh() { lastK = Math.max(Date.now(), lastK + 1); return lastK; }
  /* The deck's page passes only null or a plain object as a state, and the key `k` in it is
     this module's: a state of another shape would be reshaped here, and a caller's own `k`
     overwritten. */
  function stamped(state, k) { return Object.assign({}, state, { k: k }); }

  var push = history.pushState, replace = history.replaceState;
  history.pushState = function (state, title, url) { return push.call(history, stamped(state, fresh()), title, url); };
  history.replaceState = function (state, title, url) {
    var k = stampOf();
    return replace.call(history, stamped(state, k === null ? fresh() : k), title, url);
  };
  /* the entry the page loaded on */
  if (stampOf() === null) history.replaceState(history.state, '', location.pathname + location.search + (location.hash || ''));

  function walk() {
    if (returning && Date.now() - returning.at > WALK_MS) returning = null;
    return returning;
  }
  /* Not while a walk is in flight: the address bar is on an entry he is not staying on. */
  function note() { if (!walk()) entry = { url: location.pathname + location.search, k: stampOf() }; }
  function may(from, to) { return from === to || !K.beforeLeave || K.beforeLeave(from, to); }

  function pushAgain(url) { returning = null; history.pushState(null, '', url); note(); }
  function stayOn() {
    var dest = stampOf();
    /* no stamp on the entry he landed on, or on the one he was on (or the same one twice):
       there is no direction to walk in */
    if (dest === null || entry.k === null || dest === entry.k) { pushAgain(entry.url); return; }
    returning = { k: entry.k, url: entry.url, step: dest < entry.k ? 1 : -1, at: Date.now() };
    history.go(returning.step);
  }
  /* A popstate of the walk: true while it is the walk's own, which draws nothing. */
  function walking() {
    var r = walk(), k = stampOf();
    if (!r) return false;
    if (k === r.k) { returning = null; note(); return true; }
    if (k !== null && (r.step > 0 ? k > r.k : k < r.k)) { pushAgain(r.url); return true; }
    history.go(r.step);
    return true;
  }
  /* Every popstate, before the route is read: true when it is not the deck's to draw. */
  function popped(from) {
    if (walking()) return true;
    if (may(from, K.routeView())) return false;
    stayOn();
    return true;
  }

  K.leave = { may: may, note: note, popped: popped };
})(window.Keel);
