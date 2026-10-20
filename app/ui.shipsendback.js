/* Keel deck: Send back at shipping (c-663, keel/shipsendback.py, docs/atlas/40-deck.md).
 *
 * A shipping card only goes on to done, so what he wants changed there is told to its house
 * as one more item of the batch, of a kind of its own (`his`). This module is the action's
 * three drawn parts, for the card pane and the comments page alike (both load it after
 * app/ui.shipping.js, which draws the told item's row):
 *
 * - THE BUTTON (`K.shipping.sendBackButton`), offered where a tell can follow
 *   (`sendBackOffered`): a card at shipping that is not blocked, declined or archived.
 * - THE BOX (`K.shipSendbackSheet`): a sheet, as the outcome gate's Send back is
 *   (app/ui.cards.js says why a sheet): his words survive a redraw, and the field and its
 *   button stay on screen over a phone's keyboard. His words are required, the draft is kept
 *   per card (`K.draft`) and only a send the server accepted clears it, and the help says
 *   what will happen: told as the house's next item, the card stays, nothing is posted.
 * - WHAT WAITS (`K.shipping.sentBackLines`, from `derived.ship_sendback`): what he sent and
 *   the house has not been told yet, in his words. One the drain is not telling now says
 *   why, in the backend's own sentence (`held`, keel/shipsendback.py: the pull request
 *   declined, the card archived or blocked, the house stopped by him, the drain paused, or
 *   a batch he re-offered still open), never that it is on its way.
 */
(function (K) {
  'use strict';
  var el = K.el, App = K.App;

  var SENDBACK = 'ship-sendback';
  var SENDBACK_HELP = 'The house is told this as its next item once it is free, and judges it like ' +
    'any other: it does it, or says plainly why not. The card stays at shipping. Nothing is posted: ' +
    'its answer is shown to you here, and any commits go out with your next Ship.';
  function sendBackButton(c) {
    return el('button', { class: 'btn', 'data-key': SENDBACK, disabled: K.pendingOn(c.id) ? true : null,
      onclick: function (ev) { if (ev && ev.stopPropagation) ev.stopPropagation(); openSendBack(c); } }, 'Send back');
  }
  function openSendBack(c) {
    App.sheet = { kind: SENDBACK, id: c.id, title: c.title || '' };
    K.renderSheet();
    var field = document.querySelector('.sheet [data-fk="say"]');
    if (field && field.focus) field.focus();
  }
  function closeSendBack() { App.sheet = null; K.renderSheet(); }
  function sendBackBody(s) { return { verb: 'ship.sendback', id: s.id, words: K.draft(s.id, SENDBACK).trim() }; }
  function submitSendBack() {
    var s = App.sheet;
    if (!s || s.kind !== SENDBACK) return null;
    var body = sendBackBody(s);
    if (!body.words) { K.toast('a send back needs your words: what you want changed', true); return null; }
    /* the sheet stays up while the send is on its way; a refusal leaves his words in it */
    return K.act(body, function (r) { K.clearDraft(s.id, SENDBACK); closeSendBack(); if (K.shipping.acted) K.shipping.acted(); return (r && r.note) || 'sent back'; });
  }
  function sendBackSheet(s) {
    return el('div', { class: 'sheet', 'data-key': 'sheet-' + SENDBACK },
      el('div', { class: 'sheet-head' }, el('button', { onclick: closeSendBack }, '‹ close'),
        el('span', { class: 'spacer' }), el('span', { class: 'mono t11 ink2', text: s.id + ' · send back at shipping' })),
      el('div', { class: 'sheet-body' }, s.title ? el('div', { class: 'title', text: s.title }) : null,
        el('div', { class: 'saybox' },
          el('span', { class: 'label', text: 'What you want changed' }),
          el('textarea', { 'data-fk': 'say', rows: '4', value: K.draft(s.id, SENDBACK),
            placeholder: 'what is wrong, and what you want instead',
            'aria-label': 'what you want changed on ' + s.id, readonly: K.pendingOn(s.id) ? true : null,
            oninput: function (ev) { K.setDraft(s.id, SENDBACK, ev.target.value); },
            onkeydown: function (ev) {
              if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); submitSendBack(); }
            } }),
          el('span', { class: 'fhelp', 'data-key': 'sendback-help', text: SENDBACK_HELP }))),
      el('div', { class: 'sheet-foot' }, el('button', { class: 'btn', onclick: closeSendBack }, 'Cancel'),
        K.faceBtn('Send back', sendBackBody(s), 'primary', submitSendBack)));
  }
  /* where a send-back can be told: at shipping, not blocked, not declined, not archived */
  function sendBackOffered(c) {
    return c.stage === 'shipping' && !c.blocked_reason && !K.shipping.declined(c) && !(c.derived && c.derived.archived);
  }
  /* what he sent that the house has not been told yet, in his words; held, it says why */
  function sentBackLines(c) {
    var waits = (c.derived && c.derived.ship_sendback) || [];
    if (!waits.length || c.stage !== 'shipping') return null;
    return el('div', { class: 'shipsent', 'data-key': 'ship-sentback' }, waits.map(function (w) {
      return el('div', { class: 'shiprow his', 'data-key': 'sentback-' + w.handle },
        el('div', { class: 'row-chips' }, el('span', { class: 'mono t11', text: w.handle }),
          el('span', { class: 'chip accent', text: 'yours' }),
          el('span', { class: 'chip' + (w.held ? ' warn' : ''), text: w.held ? 'held' : 'waiting' }),
          el('span', { class: 't11 ink2', 'data-key': 'sentback-says-' + w.handle, text: w.held
            ? 'your send-back is not on its way: ' + w.held + '. Nothing is posted'
            : 'your send-back: the house is told it as its next item once it is free; nothing is posted' })),
        el('div', { class: 'reading quote', text: w.text }));
    }));
  }

  /* r-55 (c-723): ANSWER THE HOUSE'S QUESTION. A `prepared` verdict is a fix the house made
     ready and that waits on his yes; the answer is a send-back, so the house is told it as
     its next item like any other. The box opens with the item's handle leading his words
     (kept if he had started some), so the house knows which question it answers. */
  /* does a line of the words start with this handle and a colon, in any case
     (keel/shipsendback.py `answers` reads them the same way) */
  function names(words, handle) {
    var bare = handle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp('^\\s*' + bare + '\\s*:', 'im').test(words || '');
  }
  function answerButton(c, handle) {
    return el('button', { class: 'btn sm', 'data-key': 'answer-' + handle, disabled: K.pendingOn(c.id) ? true : null,
      onclick: function (ev) {
        if (ev && ev.stopPropagation) ev.stopPropagation();
        var said = K.draft(c.id, SENDBACK);
        /* c-723 review r2.F6: a second Answer adds its own line, so one send-back answers both */
        if (!names(said, handle)) K.setDraft(c.id, SENDBACK, (said.trim() ? said.replace(/\s+$/, '') + '\n' : '') + handle + ': ');
        openSendBack(c);
      } }, 'Answer');
  }
  /* what waits on him at shipping, each with the house's question and its Answer */
  function preparedLines(c) {
    var waits = K.preparedOf(c);
    if (!waits.length || !sendBackOffered(c)) return null;
    return el('div', { class: 'shipsent', 'data-key': 'ship-prepared' }, waits.map(function (w) {
      return el('div', { class: 'needs-line', role: 'status', 'data-key': 'prepared-' + w.handle },
        el('span', { text: 'The house prepared a fix for ' + w.handle + ' and waits on your answer: ' + w.why }),
        answerButton(c, w.handle));
    }));
  }

  K.shipping.answerButton = answerButton; K.shipping.preparedLines = preparedLines;
  K.shipping.sendBackButton = sendBackButton; K.shipping.sendBackOffered = sendBackOffered;
  K.shipping.sentBackLines = sentBackLines; K.shipSendbackSheet = sendBackSheet;
})(window.Keel);
