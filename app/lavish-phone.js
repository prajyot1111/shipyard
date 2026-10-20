/* The deck's phone layer for a lavish page: the bar that opens the conversation.
 *
 * The CSS beside this file does the layout; this does the four things CSS cannot say.
 *
 * 1. It draws the bar: "Conversation", the queued prompt count when there is one, and a
 *    chevron. Tapping it opens the panel as a sheet over the plan, tapping it or the plan
 *    again closes it, and closed is the state on every load.
 * 2. It watches lavish's presence banner. While lavish says the agent is not listening the
 *    bar says "Not listening" in one line and the sheet swaps the message box for the one
 *    sentence that actually resumes the house.
 * 3. It counts the queued prompts, which is the number the bar has to carry when the
 *    conversation is folded away.
 * 4. It leaves the desk alone: above 860px, lavish's own phone breakpoint, the bar and the
 *    scrim are display:none and the body attributes decide nothing.
 *
 * IT RENAMES NOTHING OF LAVISH'S and adds no listener to anything of lavish's. It reads
 * lavish's elements, it appends two of its own, and it sets two data attributes on the
 * body. Annotation is untouched: the scrim exists only while the sheet is open, and it
 * covers the plan rather than lavish's top bar, so the Annotate switch is always reachable
 * and element annotation with the sheet closed is exactly what it was. */
(function () {
  'use strict';

  var PHONE = '(max-width: 860px)';
  var LABEL = 'Conversation';
  var AWAY = 'Not listening';
  var RESUME = 'Send back from the deck to resume the house.';
  var CHEVRON = '<svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true" focusable="false">'
    + '<path d="M1 6.5L5 2.5L9 6.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';

  function start() {
    var body = document.body;
    if (!body || body.className.indexOf('lavish') < 0) return;

    var panel = document.querySelector('.panel');
    var composer = panel && panel.querySelector('.composer');
    var banner = document.getElementById('presenceBanner');
    var pills = document.getElementById('annotationPills');
    /* A lavish that is not this shape is left alone, the way the injection itself is: the
       plan gate is the last place to be clever about a page that has moved on. */
    if (!panel || !composer || !banner || !pills) return;
    if (document.querySelector('.keel-convbar')) return;   // injected twice: once is enough

    var bar = document.createElement('button');
    bar.type = 'button';
    bar.className = 'keel-convbar';
    var label = document.createElement('span');
    label.className = 'keel-convbar-label';
    var count = document.createElement('span');
    count.className = 'keel-convbar-count';
    count.hidden = true;
    var chevron = document.createElement('span');
    chevron.className = 'keel-convbar-chev';
    chevron.innerHTML = CHEVRON;
    bar.appendChild(label);
    bar.appendChild(count);
    bar.appendChild(chevron);

    var scrim = document.createElement('div');
    scrim.className = 'keel-scrim';

    /* Beside lavish's own banner rather than at a place in the composer: `#annotationPills`
       sits inside the composer in lavish 0.1.36 and inside `.panel-scroll` in 0.1.48, and a
       layer that guesses at an order is a layer that throws on the next release. */
    var resume = document.createElement('p');
    resume.className = 'keel-resume';
    resume.textContent = RESUME;
    banner.insertAdjacentElement('afterend', resume);

    body.appendChild(scrim);
    body.appendChild(bar);

    function open() { return body.getAttribute('data-keel-panel') === 'open'; }
    function setOpen(next) {
      body.setAttribute('data-keel-panel', next ? 'open' : 'closed');
      bar.setAttribute('aria-expanded', next ? 'true' : 'false');
    }
    /* `hidden` on lavish's banner is lavish saying the agent IS listening. */
    function listening() { return banner.hidden !== false; }
    function queued() { return pills.querySelectorAll('.pill-wrap').length; }

    function paint() {
      var away = !listening(), n = queued();
      label.textContent = away ? AWAY : LABEL;
      bar.setAttribute('data-keel-away', away ? 'yes' : 'no');
      /* Not listening is said in ONE line: a count beside it would be a second fact on a
         bar that is 44px tall and is reporting that nothing is reading the queue. */
      count.hidden = away || !n;
      count.textContent = String(n);
      bar.setAttribute('aria-label', (away ? AWAY : LABEL) + (!away && n ? ', ' + n + ' queued' : ''));
      body.setAttribute('data-keel-listening', away ? 'no' : 'yes');
    }

    bar.addEventListener('click', function () { setOpen(!open()); });
    scrim.addEventListener('click', function () { setOpen(false); });

    /* lavish repaints the pills and flips the banner from its own poll, so the bar follows
       the DOM rather than guessing at the poll's cadence */
    new MutationObserver(paint).observe(banner, { attributes: true, attributeFilter: ['hidden'] });
    new MutationObserver(paint).observe(pills, { childList: true });

    /* Closed on every load. A conversation left open is not the thing he opened the plan
       to look at, and the bar is one tap away. */
    setOpen(false);
    paint();

    var phone = window.matchMedia(PHONE);
    var leave = function () { if (!phone.matches) setOpen(false); };
    if (phone.addEventListener) phone.addEventListener('change', leave);
    else if (phone.addListener) phone.addListener(leave);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
