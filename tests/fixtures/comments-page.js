/* The review comments page on the real plan shell (c-643): the plan modules, the shipping
 * pane's script and app/ui.comments.js loaded whole under the DOM stand-in, fetch answered
 * by URL and every action body recorded.
 *
 * Usage: node comments-page.js <path to app/> <payload.json>
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

const fetched = [], acted = [];
let refuse = false, stage = null, failWhole = false, shippedAt = null, working = false;
/* c-660: his Ship's answer, and the page's data as the board holds it once the Ship is recorded */
const SHIP_LINE = 'shipped: pushed api f8e7cb9c34, posted 1 reply (c11)', SHIPPED_AT = '2026-10-06T10:00:00+05:30';
const ANYWAY_LINE = 'shipped: pushed api 0a1b2c3d4e, posted 0 replies', ANYWAY_AT = '2026-10-06T10:20:00+05:30';
function shipped(payload, at) {
  const body = JSON.parse(JSON.stringify(payload));
  Object.assign(body.card.options.shipping, { shipped_at: at || SHIPPED_AT, local: { ahead: 0 } });
  Object.assign(body.shipping.summary, { to_post: 0, shipped_at: at || SHIPPED_AT });
  return body;
}
/* the house in its turn with two more commits, after the first Ship: Ship anyway is his way */
function inTurn(payload) {
  const body = shipped(payload);
  body.card.options.shipping.local = { ahead: 2 };
  body.card.house = { working: true };
  return body;
}
function json(body) { return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(JSON.parse(JSON.stringify(body))) }); }
function fetch(url, opts) {
  url = String(url);
  fetched.push(url);
  if (url === '/api/action') {
    const sent = JSON.parse(opts.body);
    acted.push(sent);
    if (sent.verb === 'ship' && sent.anyway) return json({ ok: true, result: { card: shipped(PAYLOAD, ANYWAY_AT).card, note: ANYWAY_LINE } });
    if (sent.verb === 'ship') return json({ ok: true, result: { card: shipped(PAYLOAD).card, note: SHIP_LINE } });
    return json(refuse ? { ok: false, error: 'the reply to c11 is already posted' } : { ok: true, result: {} });
  }
  if (url.indexOf('/api/comments/') === 0) {
    if (failWhole && url.indexOf('again=1') < 0) return Promise.reject(new Error('the deck did not answer'));
    const body = working ? inTurn(PAYLOAD) : shippedAt ? shipped(PAYLOAD, shippedAt) : JSON.parse(JSON.stringify(PAYLOAD));
    if (stage) body.card.stage = stage;
    if (url.indexOf('again=1') >= 0) body.docs = null;      /* as the route answers a re-read */
    return json(body);
  }
  return json({});
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

(async function () {
  K.viewPlan();
  check('the first draw reads the comments once', fetched.filter((u) => u.indexOf('/api/comments/') === 0).length === 1);
  await tick(); await tick();
  let view = deck.wrap(K.viewPlan(), K);
  const text = view.textContent;

  /* each round, newest first */
  const rounds = keyed(view, /^round-/).map((n) => n.getAttribute('data-key'));
  check('each round is a section, newest first: ' + rounds.join(), rounds.join() === 'round-2,round-1');
  check('a round says when it was told', text.indexOf('Round 2, told') >= 0);
  /* the reviewer, the house, the reply */
  check('the reviewer and where', text.indexOf('Ana on a.py:4') >= 0);
  check('the reviewer\'s words', text.indexOf('Why 40?') >= 0 && text.indexOf('Use a dict') >= 0);
  check('the verdict as a chip', text.indexOf('Not valid') >= 0 && text.indexOf('Valid') >= 0);
  check('the house\'s summary and reasoning', text.indexOf('why the cap') >= 0 && text.indexOf('the host pages at 40') >= 0);
  check('a commit and its folded diff', keyed(view, /^diff-abc1234def$/).length === 1 && text.indexOf('+x = {}') >= 0);
  check('a commit says its subject', text.indexOf('change abc1234def Use a dict for the lookups') >= 0);
  /* a posted reply says so, and has no Post, Edit or Drop */
  check('a posted reply says posted', keyed(view, /^row-c13$/).length === 1 && keyed(view, /^row-c13$/)[0].textContent.indexOf('posted') >= 0);
  check('a posted reply has no choices', keyed(view, /^pick-c13-/).length === 0);
  /* c-600: the choices wait while an answer on the card is on its way (moved from the pane) */
  K.App.pending['mark·' + id] = { subject: id };
  let busy = keyed(deck.wrap(K.viewPlan(), K), /^pick-c11-/);
  check('choices wait while an answer is on its way', busy.length === 3 && busy.every((b) => b.getAttribute('disabled') !== null));
  delete K.App.pending['mark·' + id];
  busy = keyed(deck.wrap(K.viewPlan(), K), /^pick-c11-/);
  check('choices are open once nothing is on its way', busy.length === 3 && busy.every((b) => b.getAttribute('disabled') === null));
  check('the drafted reply', text.indexOf('Reply: It is the page size.') >= 0);
  check('the summary line', text.indexOf('3 review items: 3 judged, 1 reply to post, 1 posted; the house made 1 commit.') >= 0);
  /* c-655: each kind's automatic handling is said here as on the pane, with its tap */
  const autos = keyed(view, /^auto-words-(comments|checks)$/).map((n) => n.textContent);
  check('the page says each kind is off and what waits: ' + autos.join(' | '), autos.length === 2
        && autos[0] === '3 comments waiting. Automatic handling of review comments is off: hand them to the house, or turn it on to have each new comment handled as it arrives.'
        && autos[1] === 'Automatic handling of failing checks is off: each failing check waits here until you hand it to the house.');
  check('the page never says review goes to the house as it arrives', text.indexOf('go to the house as they arrive') < 0);
  /* the hand-over's label says the count and the kind, and never the verb's name */
  const label = K.shipping.handLabel;
  check('label: 3 comments', label({ comments: 3, checks: 0 }) === 'Hand 3 comments to the house');
  check('label: 1 comment', label({ comments: 1, checks: 0 }) === 'Hand 1 comment to the house');
  check('label: 1 check', label({ comments: 0, checks: 1 }) === 'Hand the failing check to the house');
  check('label: both', label({ comments: 3, checks: 1 }) === 'Hand 3 comments and the failing check to the house');
  check('label: nothing', label({ comments: 0, checks: 0 }) === null);
  /* Ship at the top and the foot, as the pane's */
  /* c-653: the button is named for what it sends (here, the one kept reply) */
  check('Ship at the top and the foot', keyed(view, /^ship-(top|foot)$/).length === 2
        && keyed(view, /^ship-(top|foot)$/).every((n) => deck.labels(n).length === 1 && /1 reply/.test(deck.labels(n)[0])));
  /* the header switches to the card's other pages */
  const hrefs = deck.all(view, (n) => n.tagName === 'A').map((n) => n.getAttribute('href') || '');
  check('the header links the plan and the outcome', hrefs.indexOf('/plan/' + id) >= 0 && hrefs.indexOf('/outcome/' + id) >= 0);
  check('the header does not link comments to itself', hrefs.indexOf('/comments/' + id) < 0);

  /* Post, Edit and Drop send the pane's own mark, and the page reads itself again with no
     stream (r1.F1): the read follows the answer, not a board event */
  const reads = () => fetched.filter((u) => u.indexOf('/api/comments/') === 0);
  const readsBefore = reads().length;
  keyed(view, /^pick-c11-drop$/)[0].onclick();
  await tick(); await tick(); await tick();
  check('a mark that landed reads the page again', reads().length === readsBefore + 1);
  check('a re-read keeps the header\'s pages', reads()[reads().length - 1].indexOf('again=1') >= 0
        && deck.all(deck.wrap(K.viewPlan(), K), (n) => n.tagName === 'A' && n.getAttribute('href') === '/plan/' + id).length === 1);
  const drop = acted[0] || {};
  check('Drop sends the pane\'s mark: ' + JSON.stringify(drop), drop.verb === 'mark' && drop.id === id && drop.data
        && drop.data.doc === 'shipping' && drop.data.block === 'replies' && drop.data.row === 'c11' && drop.data.choice === 'drop');
  view = deck.wrap(K.viewPlan(), K);
  keyed(view, /^pick-c11-post$/)[0].onclick();
  await tick(); await tick();
  check('Post sends post', (acted[1] || {}).data && acted[1].data.choice === 'post');
  view = deck.wrap(K.viewPlan(), K);
  keyed(view, /^pick-c11-edit$/)[0].onclick();
  view = deck.wrap(K.viewPlan(), K);
  check('Edit opens the field with the drafted words', keyed(view, /^edit-c11$/).length === 1);

  /* c-655: Turn on is a set of the card's own option, and the page reads itself again */
  const readsAuto = reads().length;
  deck.all(deck.wrap(K.viewPlan(), K), (n) => n.tagName === 'BUTTON' && n.textContent === 'Turn on')[0].onclick({ stopPropagation() {} });
  await tick(); await tick(); await tick();
  const turned = acted[acted.length - 1] || {};
  check('Turn on sets the card\'s option: ' + JSON.stringify(turned), turned.verb === 'set' && turned.id === id
        && turned.fields && turned.fields['options.ship_auto_comments'] === true);
  check('a switch that landed reads the page again', reads().length === readsAuto + 1);

  /* c-660: a Ship that went. Its answer is on the page where the button was, while what the
     page holds is still from before it; the next read draws what waits now */
  const top = () => keyed(deck.wrap(K.viewPlan(), K), /^ship-top$/)[0];
  check('before the tap, Ship is offered', deck.labels(top()).length === 1);
  deck.buttons(top())[0].onclick({ stopPropagation() {} });
  check('a Ship on its way cannot be tapped again', deck.buttons(top()).every((b) => b.getAttribute('disabled') !== null));
  await tick(); await tick(); await tick();
  check('Ship sends ship: ' + JSON.stringify(acted[acted.length - 1]), (acted[acted.length - 1] || {}).verb === 'ship');
  check('after the answer the button is gone and the Ship\'s own line is there: ' + top().textContent,
        deck.labels(top()).length === 0 && top().textContent.indexOf(SHIP_LINE) >= 0);
  shippedAt = SHIPPED_AT;
  await K.loadComments(id);
  await tick(); await tick();
  check('the next read draws what waits now, never the old label: ' + top().textContent,
        deck.labels(top()).length === 0 && top().textContent.indexOf(SHIP_LINE) < 0 && /Nothing to send/.test(top().textContent));

  /* r1.F6: Ship anyway from the line, and its answer drawn where the line's button was */
  working = true;
  await K.loadComments(id);
  await tick(); await tick();
  const anyway = () => keyed(deck.wrap(K.viewPlan(), K), /^ship-anyway$/);
  check('a house in its turn offers Ship anyway, at the top and the foot', anyway().length === 2 && deck.labels(top()).join() === 'Ship anyway');
  anyway()[0].onclick();
  check('Ship anyway on its way cannot be tapped again', anyway().every((b) => b.getAttribute('disabled') !== null));
  await tick(); await tick(); await tick();
  check('Ship anyway sends ship with anyway: ' + JSON.stringify(acted[acted.length - 1]), (acted[acted.length - 1] || {}).anyway === true);
  check('its answer is drawn where the line was: ' + top().textContent, anyway().length === 0 && top().textContent.indexOf(ANYWAY_LINE) >= 0);
  working = false;
  shippedAt = ANYWAY_AT;
  await K.loadComments(id);
  await tick(); await tick();
  check('and the next read says what waits now: ' + top().textContent, top().textContent.indexOf(ANYWAY_LINE) < 0 && /Nothing to send/.test(top().textContent));

  /* a refused mark leaves the row and reads nothing */
  refuse = true;
  const readsRefused = reads().length;
  keyed(deck.wrap(K.viewPlan(), K), /^pick-c11-drop$/)[0].onclick();
  await tick(); await tick(); await tick();
  check('a refused mark reads nothing again', reads().length === readsRefused);
  check('a refused mark leaves the row', keyed(deck.wrap(K.viewPlan(), K), /^pick-c11-/).length === 3);
  refuse = false;

  /* c-663: his own send-back. One told and answered is a row marked his beside a reviewer's,
     with nothing to post; one not told yet waits in his words; and Send back opens a box
     whose words are required and are what is sent */
  PAYLOAD.rounds[0].rows.push({ handle: 'his-1', his: true, item: { kind: 'his', handle: 'his-1', text: 'Rename CAP to PAGE_SIZE.', batch: 2 },
    verdict: { verdict: 'valid', why: 'renamed in three files', summary: '', reply: 'Done, and the docstring says why.', commits: [] },
    choice: null, edited: '', words: '', posted: false, text: 'Rename CAP to PAGE_SIZE.', whole: true });
  PAYLOAD.card.derived.ship_sendback = [{ handle: 'his-2', text: 'And drop the dead import.', at: SHIPPED_AT }];
  await K.loadComments(id);
  await tick(); await tick();
  view = deck.wrap(K.viewPlan(), K);
  const mine = (keyed(view, /^row-his-1$/)[0] || { textContent: '' }).textContent;
  check('his row is marked his, with his words and the answer to him: ' + mine, mine.indexOf('yours') >= 0
        && mine.indexOf('nothing is posted') >= 0 && mine.indexOf('Rename CAP to PAGE_SIZE.') >= 0
        && mine.indexOf('The house\'s answer to you: Done, and the docstring says why.') >= 0);
  check('his row has no Post, Edit or Drop', keyed(view, /^pick-his-1-/).length === 0);
  /* an item of his the house was told and has not judged says so, in words */
  const unjudged = deck.wrap(K.shipping.row(PAYLOAD.card, { handle: 'his-3', his: true, verdict: null, choice: null, edited: '', words: '',
    posted: false, text: 'Use a dict.', whole: true, item: { kind: 'his', handle: 'his-3', text: 'Use a dict.', batch: 2 } }), K).textContent;
  check('his row with no verdict says told, not judged yet: ' + unjudged, unjudged.indexOf('told, not judged yet') >= 0
        && unjudged.indexOf('Use a dict.') >= 0);
  check('a reviewer\'s row beside it keeps its choices', keyed(view, /^pick-c11-/).length === 3);
  const waits = (keyed(view, /^sentback-his-2$/)[0] || { textContent: '' }).textContent;
  check('what he sent and is not told yet waits in his words: ' + waits,
        waits.indexOf('And drop the dead import.') >= 0 && waits.indexOf('waiting') >= 0);
  check('the summary counts his beside the review, never as a reply to post',
        view.textContent.indexOf('1 send-back of yours: 1 answered') >= 0);
  check('the hand-over names a send-back left unjudged', label({ comments: 1, checks: 0, his: 1 }) === 'Hand 1 comment and your send-back to the house');
  const opener = keyed(view, /^ship-sendback$/);
  check('Send back is on the page once', opener.length === 1);
  opener[0].onclick({ stopPropagation() {} });
  check('Send back opens its box', K.App.sheet && K.App.sheet.kind === 'ship-sendback');
  const box = () => deck.wrap(K.shipSendbackSheet(K.App.sheet), K);
  const sendIt = () => deck.buttons(box()).filter((b) => deck.labelOf(b) === 'Send back')[0].onclick();
  check('the box says what will happen', /next item/.test(box().textContent) && /Nothing is posted/.test(box().textContent));
  const sentBefore = acted.length;
  sendIt();
  await tick(); await tick();
  check('a send back with no words sends nothing', acted.length === sentBefore && K.App.sheet !== null);
  K.setDraft(id, 'ship-sendback', 'Use a dict here too.');
  sendIt();
  await tick(); await tick(); await tick();
  const sentBack = acted[acted.length - 1] || {};
  check('Send back sends his words: ' + JSON.stringify(sentBack), sentBack.verb === 'ship.sendback' && sentBack.id === id
        && sentBack.words === 'Use a dict here too.');
  check('the box closes and its draft is cleared once the send landed', K.App.sheet === null && K.draft(id, 'ship-sendback') === '');

  /* review pass 1: an ask the drain is not telling says why, never that it is on its way;
     and Send back is drawn only where a tell can follow */
  const redrawn = async () => { await K.loadComments(id); await tick(); await tick(); return deck.wrap(K.viewPlan(), K); };
  PAYLOAD.card.derived.ship_sendback[0].held = 'the card is blocked, so nothing is told to its house';
  view = await redrawn();
  const heldLine = (keyed(view, /^sentback-his-2$/)[0] || { textContent: '' }).textContent;
  check('a held send-back says why and promises no tell: ' + heldLine, heldLine.indexOf('the card is blocked') >= 0
        && heldLine.indexOf('told it as its next item') < 0 && heldLine.indexOf('And drop the dead import.') >= 0);
  PAYLOAD.card.derived.ship_sendback[0].held = 'you stopped its house, so it is told with your Resume';
  const stoppedLine = (keyed(await redrawn(), /^sentback-his-2$/)[0] || { textContent: '' }).textContent;
  check('one held by his own Stop says it goes with his Resume: ' + stoppedLine, stoppedLine.indexOf('your Resume') >= 0
        && stoppedLine.indexOf('held') >= 0 && stoppedLine.indexOf('told it as its next item') < 0);
  PAYLOAD.card.derived.ship_sendback[0].held = null;
  PAYLOAD.card.blocked_reason = 'waiting on the pager';
  check('a blocked card has no Send back', keyed(await redrawn(), /^ship-sendback$/).length === 0);
  PAYLOAD.card.blocked_reason = null;
  PAYLOAD.card.derived.archived = true;
  check('an archived card has no Send back', keyed(await redrawn(), /^ship-sendback$/).length === 0);
  PAYLOAD.card.derived.archived = false;
  PAYLOAD.card.options.shipping.state = 'declined';
  check('a declined card has no Send back', keyed(await redrawn(), /^ship-sendback$/).length === 0);
  delete PAYLOAD.card.options.shipping.state;
  check('and it is back once a tell can follow', keyed(await redrawn(), /^ship-sendback$/).length === 1);

  /* a card that left shipping: read only; its stage moved, so its pages are read whole again */
  stage = 'done';
  const readsStage = reads().length;
  await K.loadComments(id);
  await tick(); await tick(); await tick();
  check('a moved stage reads the header\'s pages again', reads().length === readsStage + 2
        && reads()[reads().length - 1].indexOf('again=1') < 0);
  view = deck.wrap(K.viewPlan(), K);
  check('a closed review has no choices', keyed(view, /^pick-/).length === 0);
  check('a closed review says so', keyed(view, /^cm-closed$/).length === 1);
  check('a closed review counts nothing to post', view.textContent.indexOf('to post') < 0);
  check('a closed review has no Ship', deck.labels(view).indexOf('Ship') < 0);
  check('a closed review has no automatic-handling lines', keyed(view, /^ship-auto$/).length === 0);
  check('a closed review has no Send back and nothing waiting', keyed(view, /^(ship-sendback|ship-sentback)$/).length === 0);

  /* a board event reads the comments again (the plan shell's reload), unlike CI */
  const before = fetched.filter((u) => u.indexOf('/api/comments/') === 0).length;
  await K.loadPlan(true);
  await tick();
  check('a board event reads the comments again', fetched.filter((u) => u.indexOf('/api/comments/') === 0).length === before + 1);
  /* a whole read that fails is owed to the next read, not lost (fix check): the stage
     moves, the re-read sees it, the whole read it starts fails, and the next read is whole */
  failWhole = true;
  stage = 'shipping-moved';
  await K.loadComments(id);
  await tick(); await tick(); await tick();
  failWhole = false;
  await K.loadComments(id);
  await tick();
  check('a failed whole read is owed to the next', reads()[reads().length - 1].indexOf('again=1') < 0);
  stage = null;

  process.stdout.write(JSON.stringify(fails.length ? { fails: fails } : { ok: true }));
})().catch((e) => { process.stdout.write(JSON.stringify({ fails: fails.concat(['threw: ' + e.stack]) })); });
