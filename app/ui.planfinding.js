/* A review finding as ONE card (lane FC, FC-2): what he decides about one finding, in one
 * place.
 *
 * Lane RC drew a review's findings as a batch of rows, their comments as copy blocks further
 * down and their code in a Snippets section at the end: three places for one decision. A
 * `finding` block (keel/planfinding.py) is drawn here as one card:
 *
 *   the head   severity, the member pull request on a feature card, `path:line` linking to
 *              the pull request it is posted on, and the claim;
 *   the code   the lines around it, read from the worktree by the server when the page was
 *              asked for (keel/planexcerpt.py), never written by the house, with the
 *              finding's own lines marked by a bar, coloured (app/ui.plancode.js);
 *   the why    the evidence, the verifier's word (a disputed one with both sides), the
 *              suggestion;
 *   the comment in a field he can rewrite: "Keep these words" is the row's edit mark (RC-3),
 *              and Approve posts his words at the line in place of the draft;
 *   the choice post, edit or drop, the house's recommendation picked until he moves it.
 *
 * On the desk the card has two columns, the code (and why) left and the comment and choice
 * right. On the phone it is one column, the code in a frame of its own that scrolls
 * sideways, and a low finding starts folded to its head.
 */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';
  var el = K.el;
  var CHOICES = ['post', 'edit', 'drop'];
  var VERIFIER = { kept: 'kept by the verifier', unverified: 'not verified', disputed: 'disputed' };

  function spans(list) { return K.planBlocks.spans(list); }

  function head(b, open, desk) {
    var P = K.plan, href = P.prOf(b.member);
    var at = b.path ? b.path + ':' + b.start + (b.end && b.end !== b.start ? '-' + b.end : '') : '';
    return el('div', { class: 'pf-head' },
      el('div', { class: 'pf-line' },
        el('span', { class: 'chip pf-sev sev-' + (b.severity || 'none'), text: b.severity || '?' }),
        b.member ? el('span', { class: 'chip pf-member mono', text: b.member }) : null,
        at ? (href ? el('a', { class: 'pf-at mono', href: href, target: '_blank', rel: 'noopener',
                               title: K.say(P.space(), 'open the {change} this is posted on') }, at)
                   : el('span', { class: 'pf-at mono', text: at })) : null,
        el('span', { class: 'spacer' }),
        desk ? null : el('button', { class: 'btn sm ghost pf-toggle', 'aria-expanded': open ? 'true' : 'false',
          'aria-label': (open ? 'fold ' : 'open ') + b.id, onclick: function (ev) { ev.stopPropagation(); P.toggleFinding(b); } },
          open ? 'Fold' : 'Open')),
      el('div', { class: 'pf-claim' }, spans(b.claim)));
  }

  function codeFrame(b) {
    var c = b.code || {};
    if (!c.lines) {
      return el('div', { class: 'pcode pf-code none' },
        el('div', { class: 'pcode-why', text: c.why ? 'The code is not drawn: ' + c.why : 'The code is read from the worktree when the page opens.' }));
    }
    var lang = c.lang || K.planCode.langOf(b.path);
    return el('div', { class: 'pcode pf-code' },
      el('div', { class: 'pcode-head' },
        el('span', { class: 'mono t11 pcode-path', text: b.path + ':' + c.first + '-' + (c.first + c.lines.length - 1) }),
        el('span', { class: 'spacer' }),
        el('span', { class: 'mono t11 ink2', text: lang || 'text' })),
      el('pre', { class: 'pcode-pre' }, el('code', {}, K.planCode.lines(c.lines, lang, { first: c.first, start: c.start, end: c.end }))));
  }

  function why(b) {
    var sides = b.verifier === 'disputed';
    return el('div', { class: 'pf-why' },
      b.evidence && b.evidence.length ? el('p', {}, el('span', { class: 'k', text: 'Evidence ' }), spans(b.evidence)) : null,
      el('p', { class: 'pf-verdict v-' + (b.verifier || 'none') },
        el('span', { class: 'k', text: 'Verifier ' }), VERIFIER[b.verifier] || String(b.verifier || '')),
      sides && b['for'] ? el('p', { class: 'pf-side' }, el('span', { class: 'k', text: 'For ' }), spans(b['for'])) : null,
      sides && b.against ? el('p', { class: 'pf-side' }, el('span', { class: 'k', text: 'Against ' }), spans(b.against)) : null,
      b.suggestion && b.suggestion.length ? el('p', {}, el('span', { class: 'k', text: 'Suggestion ' }), spans(b.suggestion)) : null);
  }

  function status(pick, kept) {
    if (pick === 'drop') return 'Dropped: nothing is posted for this finding';
    if (pick === 'edit') return kept ? 'Approve posts your words' : 'Nothing kept yet: Approve refuses an edit with no words';
    return 'Approve posts these words at the line';
  }

  function comment(b, pick) {
    var P = K.plan, row = { id: b.id, rec: b.rec }, kept = P.editOf(b.id, b.id);
    return el('div', { class: 'pf-comment' + (pick === 'drop' ? ' dropped' : '') },
      el('label', { class: 'label', 'for': 'fc-' + b.id, text: 'Comment to post' }),
      el('textarea', { id: 'fc-' + b.id, 'data-fk': 'fc-' + b.id, rows: 5, 'aria-label': 'the comment for ' + b.id,
        value: P.shownEdit(b, row), disabled: P.canAnswer() ? null : true,
        oninput: function (ev) { P.typeWords(b, row, ev.target.value); } }),
      el('div', { class: 'row-actions' },
        el('span', { class: 't11 ink2 pf-status', text: status(pick, kept) }),
        el('span', { class: 'spacer' }),
        el('button', { class: 'btn sm primary', disabled: P.canAnswer() ? null : true,
          onclick: function (ev) { ev.stopPropagation(); P.keepWords(b, row); } }, 'Keep these words')));
  }

  function choice(b, pick) {
    var P = K.plan, row = { id: b.id, rec: b.rec };
    return el('div', { class: 'pf-choice' },
      el('div', { class: 'pb-choices', role: 'radiogroup', 'aria-label': 'what to do with ' + b.id }, CHOICES.map(function (c) {
        var on = pick === c;
        return el('button', { class: 'pb-choice' + (on ? ' on' : '') + (c === b.rec ? ' rec' : ''), role: 'radio',
          'aria-checked': on ? 'true' : 'false', 'data-key': c, disabled: P.canAnswer() ? null : true,
          title: c === b.rec ? 'recommended' : null,
          onclick: function (ev) { ev.stopPropagation(); P.answerRow(b, row, c); } }, c);
      })),
      b.because && b.because.length ? el('p', { class: 't11 ink2 pf-because' },
        el('span', { class: 'k', text: 'Why ' + b.rec + ': ' }), spans(b.because)) : null);
  }

  function card(b) {
    var P = K.plan, desk = K.isDesk(), open = P.findingOpen(b);
    var pick = P.rowsOf(b.id)[b.id] || b.rec;
    var cls = 'pfinding sev-' + (b.severity || 'none') + (desk ? ' pf-cols' : '') + (open ? '' : ' folded')
      + (pick !== b.rec ? ' changed' : '');
    if (!open) {
      return el('div', { class: cls, 'data-fid': b.id }, head(b, false, desk),
        el('div', { class: 't11 ink2 pf-folded', text: 'Folded: ' + pick + (pick === b.rec ? ', as recommended' : ', your choice') }));
    }
    var body = desk
      ? el('div', { class: 'pf-body' },
          el('div', { class: 'pf-left' }, codeFrame(b), why(b)),
          el('div', { class: 'pf-right' }, comment(b, pick), choice(b, pick)))
      : el('div', { class: 'pf-body' }, codeFrame(b),
          el('details', { class: 'pf-whyfold' }, el('summary', { text: 'Why it holds' }), why(b)),
          comment(b, pick), choice(b, pick));
    return el('div', { class: cls, 'data-fid': b.id }, head(b, true, desk), body);
  }

  K.planFinding = { card: card };
})(window.Keel);
