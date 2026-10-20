/* The guided Claude sign-in (c-678, the first-run design's step 2): ONE block, drawn on the
 * Sign in to Claude step (app/ui.start.js), in the sign-in banner (app/ui.views.js) and on a
 * red Claude row of the Logins list (app/ui.core.js), so the three cannot say it three ways.
 *
 * `K.signIn.block({key, command, login, space, watch})` is the four lines and the live
 * status row:
 * 1. open a terminal; 2. paste `command` (with Copy) and press Return; 3. the browser opens,
 *    or the terminal prints a link; 4. come back, with nothing to press.
 * `command` is the server's (`login.signin_command`, keel/login.py): `claude auth login`
 * under the space's own Claude folder. Nothing here types into a terminal, and there is no
 * field for a token or a password.
 *
 * `login` is `{state, why, stamp}`: the kept answer of the last probe (`good`, `expired`,
 * `unknown`, or none yet), and when the sign-in file in that folder last changed (null
 * while there is none; `login.signin_stamp`). The status row
 * (`K.signIn.status`) has the design's four states:
 * - waiting: "Waiting for you to sign in.";
 * - checking: "Sign-in seen. Making sure it works.", while the one probe runs;
 * - ready: "Signed in. Keel can run sessions.";
 * - could not tell: Keel could not reach Claude to check. It is the stuck line in its quiet
 *   form, since a login that could not be checked does not block (keel/readiness.py).
 *
 * WATCH THE FILE, THEN ONE PROBE. With `watch`, the block asks for the probe itself when it
 * is drawn with a sign-in file it has not asked about and no good answer: once per stamp
 * for that key, so a redraw or a probe that says "not signed in" never asks again, and a
 * sign-in made after that (the file changes) is asked about once more. A probe that could
 * not tell is not repeated by the page. Check again asks whenever it is pressed. Both send `firstrun.login.check` (keel/firstrun.py), with `space`
 * where the block is a space's (the banner, a Logins row); the step's names none.
 *
 * `K.signIn.again({key, ...})` is the block folded under a Sign in again button, for the
 * banner and the Logins row. `check: false` is a folder no verb of the page probes (a
 * Logins row no space runs under): no Check again, and the row says Keel's own upkeep
 * checks it. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el;
  var busy = {};       /* key -> a probe this page asked for is running */
  var asked = {};      /* key -> the stamp of the sign-in file the watch last asked about */
  var open = {};       /* key -> the folded block is open */

  var STYLE = [
    '.signin{display:flex;flex-direction:column;gap:8px;min-width:0}',
    '.signin ol{margin:0;padding-left:20px;display:flex;flex-direction:column;gap:8px;font-size:13px;line-height:1.5}',
    '.signin li .lfix{margin-top:4px;align-items:center}',
    '.signin-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}',
    '.signin-fold{display:flex;flex-direction:column;gap:8px;margin-top:8px;color:var(--ink)}',
    '@media (max-width:899px){.signin .btn{min-height:44px}}'
  ].join('\n');

  function styleOnce() {
    if (document.getElementById('signin-style')) return;
    var node = document.createElement('style');
    node.id = 'signin-style';
    node.textContent = STYLE;
    document.head.appendChild(node);
  }

  var SAYS = {
    waiting: ['Waiting for you to sign in.', 'The page looks every few seconds for the sign-in file in this install\'s folder.'],
    checking: ['Sign-in seen. Making sure it works.', 'One one-word call to Claude, made once the file appears, or on Check again.'],
    ready: ['Signed in. Shipyard can run sessions.', 'The call answered.']
  };
  /* a folder the page cannot probe (`check: false`) is checked by Keel's own upkeep */
  var UPKEEP = 'Shipyard checks this sign-in by itself, about every ten minutes while it does not work.';
  function status(login, key, own) {
    var l = login || {};
    var state = l.state === 'good' ? 'ready' : busy[key] ? 'checking' : l.state === 'unknown' ? 'needs' : 'waiting';
    if (state === 'waiting' && own === false) return { state: state, says: SAYS[state][0], how: UPKEEP };
    if (state !== 'needs') return { state: state, says: SAYS[state][0], how: SAYS[state][1] };
    return { state: 'needs', says: 'Shipyard could not reach Claude to check' + (l.why ? ' (' + l.why + ')' : '') +
      '. Check your connection, then press Check again.',
      how: 'The call timed out or failed for another reason. The row checks again on Check again.' };
  }

  function send(o) {
    var body = { verb: 'firstrun.login.check' };
    if (o.space) body.space = o.space;
    busy[o.key] = true;
    var sent = K.setupParts ? K.setupParts.change(body, 'checked') : K.act(body, function () { return 'checked'; });
    return sent.then(function (r) { delete busy[o.key]; if (K.renderBody) K.renderBody(); return r; });
  }
  /* the file is there and nothing says the sign-in works: ask once for that file, and not
     again until it changes */
  function watch(o) {
    var l = o.login || {};
    if (!l.stamp) { delete asked[o.key]; return; }
    if (l.state === 'good' || l.state === 'unknown' || asked[o.key] === l.stamp || busy[o.key]) return;
    asked[o.key] = l.stamp;
    send(o);
  }

  function checkAgain(o) {
    return el('button', { class: 'btn', 'data-key': 'signin-check', onclick: function () { send(o); } }, 'Check again');
  }
  function block(o) {
    styleOnce();
    if (o.watch) watch(o);
    var s = status(o.login, o.key, o.check);
    return el('div', { class: 'signin', 'data-key': 'signin-' + o.key },
      el('ol', { 'data-key': 'signin-lines' },
        el('li', { text: 'Open a terminal. (On macOS: press Command and Space, type Terminal, press Return.)' }),
        el('li', null, 'Paste this and press Return:', o.command ? K.command(o.command) : null),
        el('li', { text: 'Your browser opens. Sign in and approve. If no browser opens, the terminal prints a link: ' +
          'open it, then paste the code it gives you back into the terminal.' }),
        el('li', { text: 'Come back to this page. You do not need to press anything.' })),
      K.check({ key: 'signin-status', state: s.state, name: o.name || 'Claude sign-in for this install', says: s.says,
        how: s.how, quiet: true, fix: s.state === 'needs' && o.check !== false ? checkAgain(o) : null }),
      s.state === 'needs' || o.check === false ? null : el('div', { class: 'signin-row' }, checkAgain(o)));
  }

  function again(o) {
    styleOnce();
    var shown = !!open[o.key];
    return el('div', { class: 'signin-fold', 'data-key': 'signin-again-' + o.key },
      el('div', { class: 'signin-row' }, el('button', { class: 'btn sm' + (shown ? '' : ' primary'), 'aria-expanded': shown ? 'true' : 'false',
        onclick: function (ev) { if (ev && ev.stopPropagation) ev.stopPropagation(); open[o.key] = !shown; if (K.renderBody) K.renderBody(); if (K.App.sheet && K.renderSheet) K.renderSheet(); } },
        shown ? 'Close' : 'Sign in again')),
      shown ? block(o) : null);
  }

  K.signIn = { block: block, again: again, status: status };
})(window.Keel);
