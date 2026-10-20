/* The Push after a landing (c-678, keel/landpush.py), on the card: `K.pushBlock(card)`.
 *
 * A space with no pack lands a card by a merge in Keel's copy of the repo, on this computer.
 * Such a card, once done, says "Merged into main on this computer." and carries one button,
 * "Push main to origin". The push is the page's verb (`land.push`): nothing leaves this
 * computer without the tap, and it is never forced. What the card knows comes with its
 * detail (`push` on `/api/card/<id>`): the branch, the remote, and whether the remote has
 * the landing already, read from git each time.
 *
 * A push the remote refused because it has commits this computer has not seen is a stuck
 * line with its fix, Fetch and try again: the same verb with `fetch`. That one does not run
 * in the tap: the server marks the card and starts a worker that fetches, merges the
 * remote's commits in on a tested tree, and pushes (keel/landpush.py). While it runs the
 * detail says `testing` and the block says so with no button; when it ends the detail says
 * pushed, or carries the refusal (`refused`: `{error, kind, fetch}`), which is therefore
 * still there after a reload.
 *
 * A refusal a retry would only repeat has no retry: the remote's commits and this
 * computer's change the same lines (the sentence says a card can merge them), or the tests
 * failed with them merged in. Any other refusal says what git said, with Try again. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el;
  var refused = {};      /* card id -> the last refusal of its push: {error, detail} */

  var STYLE = [
    '.push-sec{display:flex;flex-direction:column;gap:8px}',
    '.push-said{font-size:13px}',
    '.push-btns{display:flex;gap:8px;flex-wrap:wrap}',
    '.push-btns .btn{min-height:44px}'
  ].join('\n');
  function styleOnce() {
    if (document.getElementById('landpush-style')) return;
    var node = document.createElement('style');
    node.id = 'landpush-style';
    node.textContent = STYLE;
    document.head.appendChild(node);
  }

  function send(c, fetch) {
    var body = { verb: 'land.push', id: c.id };
    if (fetch) body.fetch = true;
    return K.act(body, function (r) { return r && r.note; }).then(function (r) {
      if (r) delete refused[c.id];
      else refused[c.id] = K.refusal('land.push') || { error: 'the push was refused', detail: null, fetch: !!fetch };
      /* the pane's offer comes with the card's detail; the first run's with the state,
         which `act` has just read again */
      if (K.loadDetail && K.App.detailFor === c.id) K.loadDetail(c.id, true);
      return r;
    });
  }
  function button(c, label, fetch, cls) {
    var key = K.pendKey({ verb: 'land.push', id: c.id }), mine = K.isPending(key);
    return el('button', { class: 'btn' + (cls ? ' ' + cls : '') + (mine ? ' pending' : ''), 'data-pend': key,
      disabled: mine ? true : null, onclick: function (ev) { ev.stopPropagation(); send(c, fetch); } }, mine ? 'Pushing…' : label);
  }

  /* the sentence and the button (or the refusal with its fix) for an offer `p` of card `c`:
     the pane's block below, and the first run's Landed (app/ui.startcard.js) */
  K.pushLine = function (c, p) {
    styleOnce();
    var label = 'Push ' + p.branch + ' to ' + p.remote;
    var said = el('div', { class: 'push-said', 'data-key': 'push-said', text: p.said });
    if (p.pushed) return [said];
    /* the worker is bringing the remote's commits in: said, and nothing to press */
    if (p.testing) return [said, K.check({ key: 'push-testing', state: 'checking', name: label,
      says: 'Bringing in ' + p.remote + '\'s commits and testing them with yours. This page follows it.' })];
    /* the refusal the card keeps, else the one this page was just given */
    var kept = p.refused, mine = refused[c.id];
    var why = kept ? { error: kept.error, kind: kept.kind, fetch: !!kept.fetch }
      : mine ? { error: mine.error, kind: mine.detail ? mine.detail.kind : null, fetch: !!mine.fetch } : null;
    if (!why) return [said, el('div', { class: 'push-btns' }, button(c, label, false, 'primary'))];
    var fix = why.kind === 'behind' ? button(c, 'Fetch and try again', true, 'primary')
      : why.kind === 'conflict' || why.kind === 'tests' ? null
        : button(c, 'Try again', why.fetch, 'primary');
    return [said, K.stuck({ key: 'push', name: label, what: why.error, fix: fix ? el('div', { class: 'push-btns' }, fix) : null })];
  };

  K.pushBlock = function (c) {
    var d = K.App.detailFor === c.id ? K.App.detail : null, p = d && d.push;
    if (!p) return null;
    return el('div', { class: 'psec push-sec', 'data-key': 'push-sec' },
      el('div', { class: 'label', text: 'landing' }), K.pushLine(c, p));
  };
})(window.Keel);
