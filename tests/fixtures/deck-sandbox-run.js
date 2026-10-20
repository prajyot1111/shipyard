/* What the sandbox end-to-end run of 2026-09-30 found on the deck (c-604), rendered under
 * node and read back.
 *
 * Usage: node deck-sandbox-run.js <path to app/>
 * Output: {"fails": [names]}; `tests/test_deck_sandbox_run.py` expects it empty.
 */
'use strict';
const deck = require('./deck-dom.js');

const APP = process.argv[2];
const MODULES = ['ui.core.js', 'ui.findcore.js', 'ui.findpages.js', 'ui.find.js', 'ui.tips.js', 'ui.modal.js',
                 'ui.cards.js', 'ui.shipping.js', 'ui.shipsendback.js', 'ui.tree.js', 'ui.reviews.js', 'ui.views.js', 'ui.atlas.js', 'ui.board.js'];
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

function page(cards, opts, extra) {
  const K = deck.load(APP, MODULES, opts || {});
  K.App.data = deck.state(cards, extra);
  K.App.space = 'personal';
  K.render = K.renderBody = function () {};
  return K;
}
function keysOf(K, c) {
  return deck.wrap(K.gateActions(c).concat(K.cardItems(c)), K).childNodes
    .map((n) => n.getAttribute && n.getAttribute('data-key')).filter(Boolean);
}
const SESSION = 'aaaaaaaa-1111-4000-8000-000000000001';
const LIVE = { bg_id: 'aaaaaaaa', status: 'idle', kind: 'background', session_id: SESSION, recorded: true, working: false };
const VOICE_OFF = { health: { level: 'green', reasons: [], services: [{ name: 'voice', state: 'not installed here', level: 'off', at: null }] } };
const VOICE_ON = { health: { level: 'green', reasons: [], services: [{ name: 'voice', state: 'running', level: 'green', at: null }] } };

/* ---------- 5: the create form's repo chips ---------- */
function spaces(repo) {
  return { spaces: { personal: { adapter: 'sandbox', repos: repo.options, verbs: { card: [] }, topics: [], counts: {},
    options: [Object.assign({ key: 'repo', label: 'Repo', type: 'multiselect', stored: 'card' }, repo)] },
    work: { adapter: null, repos: [], options: [], verbs: { card: [] }, topics: [], counts: {} } } };
}
function chipsOn(K) {
  let painted = null;
  K.paint = function (slot, node) { if (slot === 'modal') painted = node; };
  K.openModal(null);
  return deck.byClass(deck.wrap(painted, K), 'chip').filter((b) => deck.hasClass(b, 'on')).map((b) => b.textContent);
}
check('5: two repos and a sheet default: no chip is preselected',
      chipsOn(page([], {}, spaces({ options: ['api', 'web'], default: ['api'] }))).length === 0);
check('5: exactly one repo, which the sheet names: it is preselected',
      chipsOn(page([], {}, spaces({ options: ['api'], default: ['api'] }))).join() === 'api');
check('5: a sheet that defaults to none stays none',
      chipsOn(page([], {}, spaces({ options: ['keel'], default: [] }))).length === 0);

/* ---------- c-732: Base branch, a select of the space's bases, empty unless picked ---------- */
function baseForm(row) {
  const K = page([], {}, { spaces: { personal: { adapter: null, repos: ['shop'], verbs: { card: [] }, topics: [], counts: {},
    options: [{ key: 'repo', label: 'Repo', type: 'multiselect', stored: 'card', options: ['shop'], default: ['shop'] }, row] },
    work: { adapter: null, repos: [], options: [], verbs: { card: [] }, topics: [], counts: {} } } });
  const form = { K: K, painted: null, sent: null };
  K.paint = function (slot, node) { if (slot === 'modal') form.painted = node; };
  K.act = function (body) { form.sent = body; return Promise.resolve({}); };
  K.openModal(null);
  form.field = () => deck.all(deck.wrap(form.painted, K), (n) => n.getAttribute('data-fk') === 'f:base')[0];
  form.create = () => {
    K.App.modal.values.title = 'a hotfix';
    const button = deck.buttons(deck.wrap(form.painted, K)).filter((b) => deck.labelOf(b) === 'Create, file to inbox')[0];
    if (button) button._on.onclick({ currentTarget: button, stopPropagation() {}, preventDefault() {} });
  };
  return form;
}
const SPACE_ROW = { key: 'base', label: 'Base branch', type: 'select', stored: 'options', options: ['', 'main', 'staging'],
  default: '', blank: 'the repo\'s usual branch', typed: true, when: 'repo != none' };
(function () {
  /* r1.F5, F7: nothing picked is no base, so the card follows the repo's own rule */
  const plain = baseForm(SPACE_ROW);
  const sel = plain.field();
  const opts = sel ? deck.all(sel, (n) => n.tagName === 'OPTION') : [];
  check('c-732: Base branch is a select of the bases, with nothing picked: ' + opts.map((o) => o.textContent).join('|'),
        !!sel && sel.tagName === 'SELECT' && opts.map((o) => o.textContent).join('|') ===
        'the repo\'s usual branch|main|staging|Another branch...' && opts[0].selected === true);
  plain.create();
  check('c-732: a card that picks none names no base: ' + JSON.stringify(plain.sent), !!plain.sent && !('base' in plain.sent.options));
  const typed = baseForm(SPACE_ROW);
  const pick = typed.field(), other = pick ? deck.all(pick, (n) => n.tagName === 'OPTION')[3] : null;
  if (pick && other) pick._on.onchange({ target: { value: other.value } });
  const box = typed.field();
  check('c-732: Another branch... turns it into a box to type in', !!box && box.tagName === 'INPUT');
  if (box && box.tagName === 'INPUT') box._on.oninput({ target: { value: 'release-7' } });
  typed.create();
  check('c-732: the typed branch is the card\'s base: ' + JSON.stringify(typed.sent), !!typed.sent && typed.sent.options.base === 'release-7');
  /* r2.F4: in a space where some repos land on an integration branch, the row is for the others */
  const mixed = baseForm(Object.assign({}, SPACE_ROW, { repos: ['shop'] }));
  mixed.K.App.modal.values.repo = ['keelish'];
  mixed.K.renderModal();
  const onKeelish = !!mixed.field();
  mixed.K.App.modal.values.repo = ['shop'];
  mixed.K.renderModal();
  check('c-732 r2.F4: Base branch only for a card on a repo that takes one', !onKeelish && !!mixed.field());
  /* r1.F2: a pack's own `custom` select is drawn as it always was: its list, nothing to type */
  const pack = baseForm({ key: 'base', label: 'Base branch', type: 'select', stored: 'options', options: ['release', 'trunk'],
    default: 'release', custom: true });
  const packOpts = pack.field() ? deck.all(pack.field(), (n) => n.tagName === 'OPTION').map((o) => o.textContent) : [];
  check('c-732 r1.F2: a pack\'s custom select offers only its list: ' + packOpts.join('|'), packOpts.join('|') === 'release|trunk');
})();

/* ---------- 5: closing the dialog with a field focused (the removeChild error) ----------
   A browser fires a focused field's blur INSIDE its removal, and refuses to remove a node
   that is no longer a child. The stand-in does both here. */
(function () {
  const K = page([]);
  const host = K._doc.getElementById('modal');
  const realRemove = Object.getPrototypeOf(Object.getPrototypeOf(host)).removeChild;
  const focusedIn = (node) => { for (let n = K._doc.activeElement; n; n = n.parentNode) if (n === node) return true; return false; };
  /* `focus` with no element is how the stand-in forgets what has focus */
  deck.Element.prototype.blur = function () {
    if (K._doc.activeElement !== this) return;
    deck.Element.prototype.focus.call(null);
    if (this.onblur) this.onblur({ target: this });
  };
  let blurredIn = false;
  deck.Element.prototype.removeChild = function (child) {
    if (this.childNodes.indexOf(child) < 0) throw new Error("Failed to execute 'removeChild' on 'Node'");
    if (focusedIn(child)) {
      const field = K._doc.activeElement;
      blurredIn = true;
      if (field.onblur) field.onblur({ target: field });
    }
    return realRemove.call(this, child);
  };
  const fieldOf = () => deck.all(host, (n) => n.getAttribute('data-fk') === 'f:title')[0];
  K.openModal(null);
  const title = fieldOf();
  check('5: the create dialog opens with its title field', !!title);
  if (title) title.focus();
  let error = null;
  try { K.closeModal(); } catch (e) { error = e; }
  check('5: closing with the title focused raises nothing (' + (error && error.message) + ')', !error);
  check('5: the dialog is gone', host.childNodes.length === 0);
  check('5: the field was blurred before the dialog went, not inside its removal', !blurredIn);
})();

/* ---------- 6: a done card says approved once ---------- */
(function () {
  const done = deck.card('c-20', { stage: 'done', plan_ref: 'p.md', output_ref: 'o' });
  const K = page([done]);
  const words = K.wordsOf(done).map((n) => n.textContent);
  check('6: a done card does not read "approved approved" (' + words.join(' ') + ')',
        words.filter((w) => w === 'approved').length === 1);
})();

/* ---------- 7: the header's Voice link only where voice is installed ---------- */
(function () {
  const voiceLink = (extra) => {
    const K = page([], { desk: true }, extra);
    K.renderHeader();
    return deck.byClass(K._doc.getElementById('header'), 'voicebtn').length;
  };
  check('7: no Voice link where voice is not installed', voiceLink(VOICE_OFF) === 0);
  check('7: the Voice link where it is', voiceLink(VOICE_ON) === 1);
})();

/* ---------- 7: no Resume house at an open plan gate ---------- */
(function () {
  const gate = deck.card('c-21', { stage: 'planning', session_id: SESSION, house: LIVE, plan_ref: 'p.md',
                                   derived: { plan_gate: true, needs_you: true } });
  const building = deck.card('c-22', { stage: 'building', session_id: SESSION, house: LIVE });
  const K = page([gate, building], { desk: true }, VOICE_ON);
  const atGate = keysOf(K, gate), built = keysOf(K, building);
  check('7: no Resume house at an open plan gate', atGate.indexOf('resume-house') < 0);
  check('7: the gate is answered there', atGate.indexOf('approve-plan') >= 0 && atGate.indexOf('sendback') >= 0);
  check('7: an idle building house keeps Resume house', built.indexOf('resume-house') >= 0);
  /* ---------- 7: talk is two keys ---------- */
  check('7: Talk to this house is `talk-voice`', built.indexOf('talk-voice') >= 0 && built.indexOf('talk') < 0);
  const ship = deck.card('c-23', { stage: 'shipping', space: 'personal', repo: 'keel', session_id: SESSION, house: LIVE,
                                   options: { shipping: { facts: {}, local: {} } } });
  const Ks = page([ship], { desk: true }, VOICE_ON);
  const shipKeys = keysOf(Ks, ship);
  check('7: the shipping Talk sheet is `talk`', shipKeys.indexOf('talk') >= 0 && shipKeys.indexOf('talk-voice') < 0);
})();

process.stdout.write(JSON.stringify({ fails: fails }));
