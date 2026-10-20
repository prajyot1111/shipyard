/* The delete confirm's words (lane BD), checked outside a browser.
 *
 * Usage: node board-delete.js <path to ui.boarddelete.js>
 * Output: {"ok": true}, or a JSON object naming the checks that failed.
 */
'use strict';
const fs = require('fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
const doc = { addEventListener() {}, querySelector() { return null; } };
const win = { Keel: { el() { return {}; } } };
new Function('window', 'document', source)(win, doc);
const D = win.Keel.boardDelete;
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

const one = [{ id: 'b-006', title: 'The flow', source: { kind: 'card', card: 'c-272' }, live: false }];
const uses = { 'b-006': [{ card: 'c-272', doc: 'outcome', title: 'x' }] };
check('the brief\'s own sentence', D.lines(one, uses, 0)[0] === 'b-006 is embedded in c-272\'s outcome.');
check('embedded asks to delete anyway', D.button(one, uses) === 'Delete anyway');
check('a single board is named in the heading', D.heading(one, '') === 'Delete b-006?');
check('nothing embeds it says so', D.lines(one, { 'b-006': [] }, 0)[0] === 'No open or recent plan or outcome embeds it.');
check('not embedded is a plain Delete', D.button(one, { 'b-006': [] }) === 'Delete');
const two = [{ id: 'b-1', source: { kind: 'card', card: 'c-1' }, live: true, closed: null },
             { id: 'b-2', source: { kind: 'card', card: 'c-1' }, live: false }];
const twoUses = { 'b-1': [], 'b-2': [{ card: 'c-1', doc: 'plan' }, { card: 'c-9', doc: 'outcome' }] };
const said = D.lines(two, twoUses);
check('a stack names every embedding document', said[0] === 'b-2 is embedded in c-1\'s plan and c-9\'s outcome.');
check('the live board is said', said.some(l => /^b-1 is c-1's live board/.test(l)));
check('a stack heading counts and names', D.heading(two, 'c-1') === 'Delete all 2 boards of c-1?');
check('a stack button counts', D.button(two, twoUses) === 'Delete all 2 anyway');
check('Harbor\'s board is said as Harbor\'s',
      D.lines([{ id: 'b-3', source: { kind: 'talker' }, live: true }], {}).some(l => /Harbor's live board/.test(l)));
process.stdout.write(JSON.stringify(fails.length ? { ok: false, fails } : { ok: true }));
