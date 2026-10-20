/* A reopened event stream reads the state (c-729), under node.
 *
 * A stream starts at what its deck holds now, so a page whose stream came back after the
 * deck restarted held the old deck's state until the next write: the setup step's Done and
 * Next stayed stale until a reload. The first open of a page says nothing (the page has
 * just read the state); every open after it, the browser's own reconnect included, reads
 * the state once.
 *
 * Usage: node deck-reopen.js <path to app/>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const deck = require('./deck-dom.js');
const APP = process.argv[2];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

const made = [];
function FakeSource(path) { this.path = path; this.readyState = 0; made.push(this); }
FakeSource.prototype.close = function () { this.readyState = 2; };
const asked = [];
const K = deck.load(APP, ['ui.core.js'], { desk: true, EventSource: FakeSource,
  fetch: (url) => { asked.push(url); return new Promise(() => {}); } });
K._doc.visibilityState = 'visible';
K.App.view = 'now';
const states = () => asked.filter((url) => String(url).indexOf('/api/state') === 0).length;

K.openStream();
check('one stream is opened', made.length === 1);
made[0].readyState = 1;
made[0].onopen();
check('the first open reads nothing: ' + states(), states() === 0);
made[0].onopen();
check('the browser\'s own reconnect reads the state once: ' + states(), states() === 1);
K.closeStream();
K.openStream();
made[1].readyState = 1;
made[1].onopen();
check('a stream opened again reads the state: ' + states(), states() === 2);
process.stdout.write(JSON.stringify(fails.length ? { fails } : { ok: true }));
