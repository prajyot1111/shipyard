/* r-55 (c-723): a prepared fix that waits on the owner, on the comments page and in the
 * card's pane, drawn by the real modules under the DOM stand-in (as comments-page.js does).
 *
 * Usage: node ship-prepared.js <path to app/> <payload.json>
 * The payload is the comments route's answer for a card whose c11 is prepared.
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const fs = require('fs');
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const PAYLOAD = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const MODULES = ['ui.core.js', 'ui.boardlayout.js', 'ui.board.js', 'ui.planlook.js', 'ui.plandiagram.js', 'ui.plancode.js',
                 'ui.planfinding.js', 'ui.receipt.js', 'ui.planblocks.js', 'ui.plan.js', 'ui.ci.js', 'ui.shipping.js', 'ui.shipsendback.js',
                 'ui.comments.js'];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }
let answered = false;
function json(body) { return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(JSON.parse(JSON.stringify(body))) }); }
function fetch(url) {
  if (String(url).indexOf('/api/comments/') === 0) {
    const body = JSON.parse(JSON.stringify(PAYLOAD));
    if (answered) body.card.derived.ship_prepared = [];
    return json(body);
  }
  return json({ ok: true, result: {} });
}

const id = PAYLOAD.card.id;
globalThis.location = { pathname: '/comments/' + id, search: '' };
const K = deck.load(APP, MODULES, { desk: true, fetch: fetch });
K.render = K.renderBody = function () {};
K.App.data = deck.state([]);
K.App.space = 'personal';
K.readPlanRoute();
const tick = () => new Promise((resolve) => setImmediate(resolve));
const keyed = (view, re) => deck.all(view, (n) => n.getAttribute && re.test(n.getAttribute('data-key') || ''));
const textOf = (view, re) => (keyed(view, re)[0] || { textContent: '' }).textContent;

(async function () {
  K.viewPlan();
  await tick(); await tick();
  let view = deck.wrap(K.viewPlan(), K);
  const row = textOf(view, /^row-c11$/);
  check('the row says prepared and that it waits on the owner: ' + row,
        row.indexOf('Prepared, waits on you') >= 0 && row.indexOf('waits on your answer') >= 0);
  check('the row carries the house\'s question as its why', row.indexOf('Move the card\'s branch to it?') >= 0);
  check('the summary counts it: ' + view.textContent, view.textContent.indexOf('1 prepared for your answer') >= 0);

  /* the card as a deck read carries it: in needs you, with the question */
  const card = Object.assign({}, PAYLOAD.card, { derived: Object.assign({}, PAYLOAD.card.derived, { needs_you: true }) });
  check('needs you names it: ' + K.needWord(card), K.needWord(card) === 'waits on you');
  check('its line is the house\'s question: ' + K.needLine(card),
        K.needLine(card).indexOf('waits on your answer (c11)') >= 0 && K.needLine(card).indexOf('Move the card') >= 0);
  const put = {};
  K.putNeed = K.putNeed || function () {};      /* the Cards module's, not loaded on this page */
  K.shipping.gateItems(card, function (key, node) { put[key] = node; });
  check('the pane leads with the question: ' + Object.keys(put).join(), !!put['ship-prepared']);
  check('Ship\'s confirm says it still waits', K.shipping.shipConfirm(card, PAYLOAD.shipping).indexOf('waiting on your answer') >= 0);

  /* Answer is Send back with the item's handle leading his words */
  const answer = keyed(view, /^answer-c11$/);
  check('the row has its Answer', answer.length === 1);
  answer[0].onclick({ stopPropagation() {} });
  check('Answer opens Send back', K.App.sheet && K.App.sheet.kind === 'ship-sendback');
  check('with the handle leading: ' + JSON.stringify(K.draft(id, 'ship-sendback')), K.draft(id, 'ship-sendback') === 'c11: ');
  /* c-723 review r2.F6: a second Answer adds its own line; one already named adds nothing */
  K.setDraft(id, 'ship-sendback', 'c11: yes, move it');
  K.shipping.answerButton(PAYLOAD.card, 'c12').onclick({ stopPropagation() {} });
  check('a second Answer adds a line for its item: ' + JSON.stringify(K.draft(id, 'ship-sendback')),
        K.draft(id, 'ship-sendback') === 'c11: yes, move it\nc12: ');
  K.setDraft(id, 'ship-sendback', 'C11: yes');
  answer[0].onclick({ stopPropagation() {} });
  check('an item the draft already names is not added again: ' + JSON.stringify(K.draft(id, 'ship-sendback')),
        K.draft(id, 'ship-sendback') === 'C11: yes');
  K.clearDraft(id, 'ship-sendback');
  K.App.sheet = null;

  /* once he answered, the row says so and offers no second Answer */
  answered = true;
  await K.loadComments(id);
  await tick(); await tick();
  view = deck.wrap(K.viewPlan(), K);
  check('answered, the row says the house records it again: ' + textOf(view, /^row-c11$/),
        textOf(view, /^row-c11$/).indexOf('You answered with a send-back') >= 0 && keyed(view, /^answer-c11$/).length === 0);

  process.stdout.write(JSON.stringify(fails.length ? { fails: fails } : { ok: true }));
})().catch((e) => { process.stdout.write(JSON.stringify({ fails: fails.concat(['threw: ' + e.stack]) })); });
