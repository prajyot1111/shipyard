/* The stuck states outside setup (c-678, keel/stuckcards.py): each is the stuck line of the
 * setup pages (`K.stuck`, app/ui.stuck.js), so what happened, the fix on the page and
 * Bosun's session read the same everywhere.
 *
 * - `K.stuckCard(card)`: a blocked card whose block Keel can read (`card.stuck` on the
 *   state): a session that will not start (no model named, a start that failed) and a
 *   landing that was refused (red tests, changes never committed, a stale lock, git's name
 *   and email, anything else git said). The fix is a button that sends the reading's own
 *   verb, and then the one that follows it (a fresh start, or Approve again); or a step to
 *   open; or, for a folder that is the user's own, the commands to copy.
 * - `K.servicesStuck()`: the drain has stopped on an install, with Restart it
 *   (`services.restart`).
 * - `K.unknownKeys()`: a key in config.toml Keel does not know (`config.unknown` on the
 *   state), with Remove this line and, where Keel knows a near name, Rename to it.
 *
 * Every button is the user's tap. A card's fix sends its own verb and, where that only
 * clears the way and the server took it, what follows (`follow`), which its label says
 * ("and start", "and land"): a fresh start, or, for a landing, the unblock of that block
 * and then Approve. A step the server refused is followed by nothing. The
 * other buttons each send one verb of the page. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el, App = K.App;
  var NAMES = { 'no-model': 'Starting a session', 'start-failed': 'Starting a session' };

  function styleOnce() {
    if (document.getElementById('stuckcard-style')) return;
    var node = document.createElement('style');
    node.id = 'stuckcard-style';
    /* a fix's label says what follows it ("Remove the stale lock and land"), so it may wrap
       in the card pane's narrow column instead of pressing against the button's edges */
    node.textContent = '.stk-btns{display:flex;gap:8px;flex-wrap:wrap}' +
      '.stk-btns .btn{min-height:44px;height:auto;white-space:normal;text-align:left;padding-top:6px;padding-bottom:6px}' +
      '.stk-cmds{display:flex;flex-direction:column;gap:6px;min-width:0}';
    document.head.appendChild(node);
  }
  function pendingOf(body) { return K.isPending(K.pendKey(body)); }
  function button(label, body, then, cls) {
    var mine = pendingOf(body);
    return el('button', { class: 'btn' + (cls ? ' ' + cls : '') + (mine ? ' pending' : ''), disabled: mine ? true : null,
      onclick: function (ev) {
        if (ev && ev.stopPropagation) ev.stopPropagation();
        K.act(body, function (r) { return (r && r.note) || ''; }).then(function (r) { if (r && then) then(r); });
      } }, label);
  }
  /* what follows a fix that only clears the way: the card's fresh start, or Approve again.
     `land` is both steps a refused landing needs after the fix's own verb (keel/stuckcards.py
     `lands`): the deck's unblock of that one block (`expect`), then Approve. A bare Approve
     is refused on a blocked card where landings are queued.

     APPROVE IS SENT ONLY WHEN THE BLOCK WAS LIFTED, which the page reads off the card the
     unblock answers with: the server does not refuse an unblock whose `expect` no longer
     matches, it answers with the card as it is (`Board.unblock`). A card that comes back
     still blocked is blocked on something else, and with the queue off an Approve would
     land it over that block. So nothing is sent and the page says so. */
  var ELSEWHERE = ' is blocked on something else now, so it was not approved. Read the block on the card.';
  function follow(c, f) {
    function approve() { K.act({ verb: 'approve', id: c.id, gate: 'outcome' }); }
    function ifLifted(r) {
      if (!r) return;            /* refused outright: the act has said why */
      if (r.blocked_reason) { K.toast(c.id + ELSEWHERE, true); return; }
      approve();
    }
    if (f.then === 'house.retry') return function () { K.act({ verb: 'house.retry', id: c.id }); };
    if (f.then === 'approve') return f.body && f.body.verb === 'unblock' ? ifLifted : approve;
    if (f.then === 'land') return function () {
      K.act({ verb: 'unblock', id: c.id, expect: f.expect }).then(ifLifted);
    };
    return null;
  }
  function fixOf(c, s) {
    var f = s.fix;
    if (f && f.body) return el('div', { class: 'stk-btns' }, button(f.label, f.body, follow(c, f), 'primary'));
    if (f && f.step) return el('div', { class: 'stk-btns' }, el('button', { class: 'btn primary',
      onclick: function () { if (K.openStep) K.openStep(f.step); } }, f.label));
    if (s.commands && s.commands.length) return el('div', { class: 'stk-cmds' },
      el('span', { text: s.said || '' }), s.commands.map(function (cmd) { return K.command(cmd); }));
    return null;
  }

  K.stuckCard = function (c) {
    var s = c.stuck;
    if (!s) return null;
    styleOnce();
    return K.stuck({ key: 'card-' + c.id, name: NAMES[s.kind] || 'Landing', what: s.what, fix: fixOf(c, s) });
  };

  K.servicesStuck = function () {
    var d = App.data || {}, drain = d.drain || {};
    if (!(d.firstrun || {}).install || drain.alive !== false || (d.config || {}).drain_paused) return null;
    styleOnce();
    return K.stuck({ key: 'services', name: 'Shipyard\'s services',
      what: 'The part of Shipyard that starts sessions and lands work has stopped.',
      fix: el('div', { class: 'stk-btns' }, button('Restart it', { verb: 'services.restart' }, function () { if (K.load) K.load(); }, 'primary')) });
  };

  K.unknownKeys = function () {
    var list = ((App.data || {}).config || {}).unknown || [];
    if (!list.length) return null;
    styleOnce();
    return list.map(function (u) {
      return K.stuck({ key: 'config-' + u.table + '-' + u.key, name: 'config.toml', what: u.what, quiet: true,
        fix: el('div', { class: 'stk-btns' },
          u.near ? button('Rename to ' + u.near, { verb: 'setup.config.rename', table: u.table, key: u.key, to: u.near }, null, 'primary') : null,
          button('Remove this line', { verb: 'setup.config.remove', table: u.table, key: u.key }, null, u.near ? '' : 'primary')) });
    });
  };
})(window.Keel);
