/* A work research card's outcome page (c-719 r1.F9): the send panel drawn from the payload
 * the route answered, on the real plan shell, so the card's kind is read where the page reads
 * it. Its approve says Done and confirms "Mark <id> done?", never "This publishes it".
 *
 * Usage: node research-send.js <path to app/> <outcome payload.json>
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
const id = PAYLOAD.card.id;
function fetch() {
  return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ ok: true, result: {} }) });
}

globalThis.location = { pathname: '/outcome/' + id, search: '' };
const K = deck.load(APP, MODULES, { desk: true, fetch: fetch });
K.render = K.renderBody = function () {};
K.App.data = deck.state([]);
K.readPlanRoute();
K.planState.data = PAYLOAD;
const view = deck.wrap(K.viewPlan(), K);
const send = deck.buttons(view).filter((b) => /^(Done|Approve outcome)$/.test(deck.labelOf(b)))[0];
check('the payload\'s gate is open: ' + PAYLOAD.gate + ' ' + PAYLOAD.answerable, PAYLOAD.gate === 'outcome' && PAYLOAD.answerable !== false);
check('the approve says Done: ' + (send ? deck.labelOf(send) : 'none'), !!send && deck.labelOf(send) === 'Done');
let asked = null;
K._win.confirm = function (text) { asked = text; return false; };
if (send) send.onclick({ stopPropagation() {}, preventDefault() {}, currentTarget: send });
check('it confirms Mark done, not a publish: ' + asked, asked === 'Mark ' + id + ' done?');
check('no publish words anywhere', view.textContent.indexOf('publishes') < 0);
process.stdout.write(JSON.stringify(fails.length ? { fails: fails } : { ok: true }));
