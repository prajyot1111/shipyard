/* Bosun's asks on the Bosun page (c-521, `keel/asks.py`), split from `ui.console.js` (c-591
 * review): an ask as a card with its options as buttons, an answered one folded to a line,
 * and the link a card id makes, which opens the card in the deck's Inspector. Loaded by
 * `app/console.html` after `ui.core.js` and before `ui.console.js`, which reads it as
 * `K.bosunAsks`.
 */
(function (K) {
  'use strict';

  var App = K.App, el = K.el;

  /* A card opens in the deck's Inspector, where every card does. */
  function cardHref(id) {
    var c = K.byId && App.data ? K.byId(id) : null;
    return '/?view=cards&card=' + encodeURIComponent(id) + (c ? '&space=' + encodeURIComponent(c.space) : '');
  }
  function cardLink(id) { return el('a', { class: 'mono t11', text: id, href: cardHref(id) }); }

  /* ---------- Bosun's asks (c-521, `keel/asks.py`) ----------
     An ask's options are the buttons: a tap asks one confirm, then answers it. "Something
     else" sends his own words instead, which closes it as redirected. */
  var CHANNEL = { tap: 'tap', voice: 'voice', chat: 'chat' };
  function answerBody(a, extra) {
    var body = { verb: 'console', sub: 'answer', target: a.id };
    Object.keys(extra).forEach(function (k) { body[k] = extra[k]; });
    return body;
  }
  /* A deploy ask (c-526, `keel/deployask.py`) is the drain's, not Bosun's, and lives on
     Shipped: its Yes is carried out by Keel on the box's next pass. */
  function isDeploy(a) { return !!(a.options && a.options[0] && a.options[0].deploy); }
  /* A login ask (c-558, `keel/loginask.py`) is the drain's too: a red row on the Logins list. */
  function loginOf(a) { return (a.options && a.options[0] && a.options[0].login) || null; }
  function isKeels(a) { return isDeploy(a) || !!loginOf(a); }
  function answeredSay(a) {
    return function () {
      return 'answered ' + a.id + (isDeploy(a) ? '; Shipyard deploys on its next pass if the suite is green'
        : loginOf(a) ? '; it closes itself once the login answers'
        : '; Bosun is told on its next pass');
    };
  }
  function loginFix(a) {
    var l = loginOf(a);
    if (!l || !l.fix || a.state !== 'open') return null;
    return el('div', { class: 'lfix' }, el('code', { class: 'fix', text: l.fix }), K.copyButton(l.fix));
  }
  /* Where the card an option files builds, said before he taps (c-550, `asks.where`). */
  function filesWhere(f) {
    if (!('repo' in f)) return 'repo from its card';
    if (!f.repo) return 'as an errand, no repo';
    return 'in ' + f.repo + (f.repo_from && f.repo_from !== 'stated' ? ' (from ' + f.repo_from + ')' : '');
  }
  function filesWhereMarked(f) {
    return filesWhere(f) + (f.kind ? ', marked ' + f.kind : '') + (f.autonomy ? ', ' + f.autonomy : '');
  }
  function optionRow(a, o) {
    var files = o.files ? el('div', { class: 't11 ink2',
      text: 'files a personal card ' + filesWhereMarked(o.files) + ': ' + o.files.title }) : null;
    var chosen = a.state !== 'open' && a.answer === o.letter;
    var inner = [
      el('div', { class: 'copt-head' }, el('span', { class: 'mono t11 ink3', text: o.letter }),
        el('span', { class: 'copt-label', text: o.label }),
        o.letter === 'A' ? el('span', { class: 'pill crec', text: 'recommended' }) : null,
        chosen ? el('span', { class: 'mono t11 cchosen', text: 'chosen' }) : null),
      el('div', { class: 'mono t11 ink2 copt-does', text: o.does }), files];
    if (a.state !== 'open') return el('div', { class: 'copt done' + (chosen ? ' chosen' : '') }, inner);
    return el('button', { class: 'copt', 'data-key': a.id + '-' + o.letter, onclick: function (ev) {
      var ask = 'Answer ' + a.id + ' with ' + o.letter + ', ' + o.label + '?\n\n' +
        (isKeels(a) ? 'Shipyard does: ' : 'Bosun does: ') + o.does;
      if (!window.confirm(ask)) return;
      K.act(answerBody(a, { choice: o.letter }), answeredSay(a), ev.currentTarget);
    } }, inner);
  }
  function redirectBox(a) {
    var input = el('textarea', { class: 'cwords', rows: '2', placeholder: 'Your own words: none of the options is done, and Bosun is told what you wrote' });
    return el('details', { class: 'cother' }, el('summary', { class: 't13 ink2', text: 'Something else' }),
      input, el('button', { class: 'btn cbtn', onclick: function (ev) {
        var words = input.value.trim();
        if (!words) { K.toast('write what you want instead', true); return; }
        if (!window.confirm('Redirect ' + a.id + '? None of its options is done; Bosun gets your words.')) return;
        K.act(answerBody(a, { words: words }), answeredSay(a), ev.currentTarget);
      } }, 'Send instead'));
  }
  /* Who filed or answered it, in the page's words (`requests.SOURCES` says the same). */
  var WHO = { house: 'a house', drain: 'the drain', doctor: 'doctor', voice: 'Harbor', human: 'you',
    bosun: 'Bosun', cli: 'a terminal', hook: 'a hook' };
  function whoOf(actor) { return WHO[actor] || actor; }
  function whoAnswered(a) {
    var by = a.answered_by === 'human' || a.answered_by === 'voice' ? 'you' : whoOf(a.answered_by);
    return by + ', ' + (CHANNEL[a.channel] || a.channel) + ', ' + K.clock(a.answered_at);
  }
  function closedLine(a) {
    if (a.state === 'withdrawn') return el('span', { class: 'pill cclosed', text: 'withdrawn by ' + (isKeels(a) ? 'Shipyard' : 'Bosun') + ': ' + (a.words || '') });
    var head = a.state === 'redirected' ? 'redirected by ' + whoAnswered(a) : 'answered by ' + whoAnswered(a) + ': ' + a.answer;
    return el('span', { class: 'pill cclosed good', text: head });
  }
  function askCard(a) {
    return el('article', { class: 'cask open', id: a.id, 'data-key': a.id },
      el('div', { class: 'creq-head' },
        el('span', { class: 'pill ckind', text: a.kind }), el('span', { class: 'mono t11 ink2', text: a.id }),
        a.card ? cardLink(a.card) : null, el('span', { class: 'spacer' }),
        el('span', { class: 'mono t11 ink3', text: K.ago(a.created_at) })),
      el('div', { class: 'creq-what', text: a.question }),
      el('div', { class: 't13 ink2', text: 'Why: ' + a.why }),
      loginFix(a),
      el('div', { class: 'copts' }, a.options.map(function (o) { return optionRow(a, o); })),
      isKeels(a) ? null : redirectBox(a));
  }
  /* An answered ask, folded to one line; the whole record stays in the Journal. */
  function closedRow(a) {
    return el('div', { class: 'cfold', 'data-key': a.id },
      el('span', { class: 'mono t11 ink3', text: a.id }), closedLine(a),
      el('span', { class: 't13 cfold-q', text: a.question }),
      el('span', { class: 'mono t11 ink3', text: K.clock(a.answered_at || a.updated_at) }));
  }

  K.bosunAsks = { cardHref: cardHref, cardLink: cardLink, answerBody: answerBody, isDeploy: isDeploy,
    whoOf: whoOf, askCard: askCard, closedRow: closedRow };
})(window.Keel);
