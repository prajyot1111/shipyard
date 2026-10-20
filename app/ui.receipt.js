/* The receipt a gate leaves once it is answered (c-537).
 *
 * After Approve on the plan page nothing said what happened, and the button came back once
 * the command went through. The server decides whether a gate was answered and what follows
 * (`keel/receipt.py`: who answered and when, from the card's events; what is happening now,
 * from the card's own state) and sends it as `receipt` on `/api/plan/<id>` and
 * `/api/card/<id>`. This draws it, the same way on the plan page's send panel and in the card
 * Inspector (the deck's and the Console's), so the two can never say different things.
 *
 * It decides nothing: whether Approve is offered again (a refused landing) is the server's
 * `answerable`, read by the plan page. The page redraws it on every card event, which is how
 * "landing" becomes "landed" in front of him with no tap.
 */
(function (K) {
  'use strict';

  var el = K.el;
  var TONES = { accent: 1, good: 1, warn: 1, crit: 1 };

  /* `r` is the server's receipt; `opts.links` adds the plan and outcome pages it names (the
     Inspector's, where those pages are elsewhere), and `opts.card` is the card's id. */
  function receipt(r, opts) {
    if (!r) return null;
    opts = opts || {};
    var tone = TONES[r.tone] ? ' tone-' + r.tone : '';
    var docHref = function (doc) { return '/' + doc + '/' + opts.card; };
    return el('section', { class: 'receipt', 'data-key': 'receipt', role: 'status', 'aria-live': 'polite' },
      el('div', { class: 'receipt-said' },
        el('span', { class: 'receipt-mark' + (r.mode === 'approve' ? ' ok' : ''), 'aria-hidden': 'true',
          text: r.mode === 'approve' ? '✓' : '↩' }),
        el('span', { class: 'label', text: r.gate === 'plan' ? 'Plan' : 'Outcome' }),
        el('strong', { text: r.said }),
        el('span', { class: 'ink2', title: r.at, text: 'at ' + when(r.at) })),
      el('div', { class: 'receipt-now' + tone },
        el('span', { class: 'dot', 'aria-hidden': 'true' }),
        el('span', { class: 'receipt-now-text', text: r.now }),
        r.log ? el('a', { class: 'receipt-log mono', href: r.log, target: '_blank', rel: 'noopener' }, 'log') : null),
      r.link && opts.card && !opts.links ? el('a', { class: 'receipt-link', href: docHref(r.link) },
        (r.link === 'outcome' ? 'Open the outcome' : 'Open the plan') + ' ›') : null,
      opts.links && opts.card ? el('div', { class: 'receipt-docs' },
        opts.links.map(function (doc) {
          return el('a', { class: 'btn sm', href: docHref(doc), 'data-key': 'receipt-' + doc },
            doc === 'plan' ? 'Plan' : 'Outcome');
        })) : null);
  }

  /* the clock for today's answer, the day too for an older one */
  function when(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return '';
    var today = new Date().toDateString() === d.toDateString();
    return K.clock(iso) + (today ? '' : ' on ' + d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }));
  }

  K.receipt = receipt;
})(window.Keel);
