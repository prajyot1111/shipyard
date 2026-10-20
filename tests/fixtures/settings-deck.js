/* The Settings view under node (c-633): app/ui.settings.js run whole against a stand-in for
 * the few things it touches (K.el builds plain nodes, K.act records what Save posts), fed the
 * report tests/test_settings_deck.py wrote. It prints what the test checks: every field's
 * label and the help shown under it (c-640: always shown, no tooltip), the one batch a
 * Save sends, and what the page does about WHICH space a setting is for and about a change
 * that is not saved yet (c-661, `spacesOut`). */
'use strict';
var fs = require('fs');
var path = require('path');

var app = process.argv[2], reportFile = process.argv[3], flowFile = process.argv[4];
var report = JSON.parse(fs.readFileSync(reportFile, 'utf8'));

function node(tag, attrs, children) { return { tag: tag, attrs: attrs || {}, children: children }; }
function flat(list, out) {
  list.forEach(function (c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) flat(c, out); else out.push(c);
  });
  return out;
}
var acted = [];
var asked = [], answers = [], unload = null, redraws = 0;   /* `answers`: what the next confirms say (none left: no) */
global.window = { Keel: {}, addEventListener: function (name, fn) { if (name === 'beforeunload') unload = fn; } };
global.confirm = window.confirm = function (words) { asked.push(words); return answers.length ? answers.shift() : false; };
global.document = { getElementById: function () { return null; }, createElement: function () { return {}; },
                    head: { appendChild: function () {} } };
global.fetch = function () { return Promise.resolve({ json: function () { return Promise.resolve(report); } }); };
global.setTimeout = function () { return 0; };
var K = window.Keel;
K.el = function (tag, attrs) { return node(tag, attrs, flat(Array.prototype.slice.call(arguments, 2), [])); };
K.App = { view: 'settings', space: Object.keys(report.values.spaces).pop(), data: { config: { warnings: ['[keel] houses_max = \'3\' is not a whole number'] }, spaces: {} } };
if (flowFile) K.App.data.spaces.personal = { flow: JSON.parse(fs.readFileSync(flowFile, 'utf8')) };
K.renderBody = function () { redraws += 1; };
K.go = function () {};
K.palette = function (space) { return space === 'work' ? 'work' : 'personal'; };
/* c-667: an Adopt's answer is said through `K.sentence`, as the card's own Adopt says it */
var adoptSaid = [];
K.sentence = function (body, r) { return { text: r.note, err: r.stage !== 'done', id: body.id }; };
K.act = function (body, done) {
  acted.push(body);
  if (done && /\.adopt$/.test(body.verb)) adoptSaid.push(done({ where: '/f.toml', stage: 'review', note: 'adopted, but not moved' }));
  return Promise.resolve({ saved: [] });
};
K.viewMore = function () { return [node('section', {}, []), node('section', {}, [])]; };
K.say = function (space, words) { return words.replace('{change}', 'change'); };
K.stepHref = function (step, space) { return '?view=start&step=' + step + '&space=' + space; };
global.Keel = K;

/* Setup first, as the deck loads them (app/views.json): the Flow panel's Propose wording is
   Setup's `K.proposing` (c-664) */
eval(fs.readFileSync(path.join(app, 'ui.setup.js'), 'utf8'));
eval(fs.readFileSync(path.join(app, 'ui.settings.js'), 'utf8'));

function walk(n, seen) {
  if (Array.isArray(n)) { n.forEach(function (c) { walk(c, seen); }); return seen; }
  if (!n || typeof n !== 'object') return seen;
  seen.push(n);
  (n.children || []).forEach(function (c) { walk(c, seen); });
  return seen;
}
function classed(nodes, name) {
  return nodes.filter(function (n) { return (' ' + (n.attrs['class'] || '') + ' ').indexOf(' ' + name + ' ') >= 0; });
}
function text(n) { return typeof n === 'string' ? n : (n.attrs.text || (n.children || []).map(text).join('')); }

K.viewSettings();                       /* the first draw asks for the report */
setImmediate(function () {
  var nodes = walk(K.viewSettings(), []);
  var labels = classed(nodes, 'set-label').map(function (n) {
    var help = classed(n.children.filter(function (c) { return c && typeof c === 'object'; }), 'set-help')[0];
    return { label: text(walk(n, []).filter(function (c) { return c.tag === 'label'; })[0]), title: help ? text(help) : null };
  });
  var infos = classed(nodes, 'set-help').length;
  var flow = flowFile ? flowOut() : null;     /* before the edits, so Save posts only its own */
  var spaces = spacesOut();                   /* and it leaves nothing pending behind it */
  var typing = typingOut(), stepper = stepperOut();
  acted.length = 0;
  /* two edits: a switch turned on and a number typed */
  var inputs = nodes.filter(function (n) { return n.attrs['data-fk']; });
  var paused = inputs.filter(function (n) { return n.attrs['data-fk'] === 'install|keel.drain_paused'; })[0];
  paused.attrs.onchange({ target: { checked: true } });
  var houses = inputs.filter(function (n) { return n.attrs['data-fk'] === 'install|keel.houses_max'; })[0];
  houses.attrs.onchange({ target: { value: '5' } });
  var drawn = walk(K.viewSettings(), []);
  var changed = classed(drawn, 'set-field').filter(function (n) { return /changed/.test(n.attrs['class']); }).length;
  var save = drawn.filter(function (n) { return n.tag === 'button' && /^Save /.test(text(n)); })[0];
  var what = text(classed(drawn, 'what')[0]);
  /* the seam S4 embeds: only the Drain group's fields, with a Save of its own */
  var embedded = walk(K.settingsForm({ groups: ['Drain'] }), []);
  var form = classed(embedded, 'set-field').length;
  var formSave = embedded.some(function (n) { return n.tag === 'button' && /^Save 2 changes to this install$/.test(text(n)); });
  save.attrs.onclick();
  setImmediate(function () {
    var now = walk(K.configWarnings(), []);
    var more = K.viewMore();
    process.stdout.write(JSON.stringify({
      labels: labels, infos: infos, changed: changed, saveText: text(save), acted: acted,
      nowWarnings: classed(now, 'row').length,
      moreHasSettings: walk(more, []).some(function (n) { return n.attrs['data-key'] === 'settings-entry'; }),
      form: form, formSave: formSave, flow: flow, spaces: spaces, what: what, typing: typing, stepper: stepper
    }));
  });
});

/* c-640: the personal space's Flow panel, its board lines, and Propose posting his words */
function flowOut() {
  var drawn = walk(K.viewSettings(), []);
  var panel = drawn.filter(function (n) { return n.attrs['data-key'] === 'set-flow-personal'; })[0];
  var inside = walk(panel, []);
  function keyed(key) {
    var found = inside.filter(function (n) { return n.attrs['data-key'] === key; })[0];
    return found ? text(found) : null;
  }
  var proposal = K.App.data.spaces.personal.flow.proposal;
  var box = inside.filter(function (n) { return n.tag === 'textarea'; })[0];
  /* an open proposal takes the box's place: its card, its state, and Adopt once it is ready */
  if (box) box.attrs.oninput({ target: { value: 'dev review on my word' } });
  var tap = walk(K.viewSettings(), []).filter(function (n) {
    return n.tag === 'button' && text(n) === (box ? 'Propose' : 'Adopt');
  })[0];
  if (tap) tap.attrs.onclick();
  var link = inside.filter(function (n) { return n.tag === 'a' && proposal && text(n) === proposal.card; })[0];
  return {
    lines: K.flowLines(K.App.data.spaces.personal.flow),
    moves: classed(inside, 'flow-move').map(function (n) { return n.attrs['data-key']; }),
    who: classed(inside, 'who').map(text),
    graph: classed(inside, 'flow-graph').length,
    nav: drawn.some(function (n) { return n.tag === 'a' && text(n) === 'Flow · personal'; }),
    /* c-664: what a flow is, how review at shipping is handled, and what Propose says */
    honest: keyed('flow-honest-personal'), handling: keyed('flow-handling-personal'),
    before: keyed('proposing-before'), after: proposal ? keyed('proposing-' + proposal.card) : null,
    link: link ? link.attrs.href : null, example: box ? box.attrs.placeholder : null,
    about: keyed('flow-about-personal'), held: keyed('flow-held-personal'),
    setup: (inside.filter(function (n) { return n.attrs['data-key'] === 'flow-setup-personal'; })[0] || { attrs: {} }).attrs.href || null,
    proposed: acted.slice(), adoptSaid: adoptSaid.slice()
  };
}

/* c-661: the deck is in the LAST space of the config, so "its section comes first" is not
   the config's order by luck. One switch is turned in each space, then turned back. */
function spacesOut() {
  var names = Object.keys(report.values.spaces), here = K.App.space;
  function within(n, test) { return walk(n, []).some(test); }
  function rows(drawn) { return classed(drawn, 'set-field'); }
  function ownerOf(row) { return row.attrs['data-key'].slice(4).split('|')[0]; }
  function switchOf(drawn, space) {
    return drawn.filter(function (n) { return n.attrs.type === 'checkbox' && String(n.attrs['data-fk']).indexOf(space + '|') === 0; })[0];
  }
  function turn(space) {
    var box = switchOf(walk(K.viewSettings(), []), space);
    box.attrs.onchange({ target: { checked: !box.attrs.checked } });
    return box.attrs['data-fk'];
  }
  var first = walk(K.viewSettings(), []);
  var out = {
    here: here,
    order: first.filter(function (n) { return n.tag === 'section' && /^set-(space|install|voice)/.test(n.attrs.id || ''); })
      .map(function (n) { return n.attrs.id; }),
    unnamed: rows(first).filter(function (row) {
      var owner = ownerOf(row);
      return owner !== 'install' && !within(row, function (n) { return n.attrs['data-space'] === owner; });
    }).length,
    installNamed: rows(first).filter(function (row) {
      return ownerOf(row) === 'install' && within(row, function (n) { return n.attrs['data-space']; });
    }).length,
    barBefore: classed(first, 'set-save').length,
    leaveClean: K.beforeLeave('settings', 'cards'), askedClean: asked.length
  };
  var turned = names.map(function (name) { return turn(name); });
  var drawn = walk(K.viewSettings(), []);
  out.turned = turned.map(function (key) { return 'set-' + key; }).sort();
  out.unsaved = rows(drawn).filter(function (row) {
    return within(row, function (n) { return (' ' + (n.attrs['class'] || '') + ' ').indexOf(' set-unsaved ') >= 0; });
  }).map(function (row) { return row.attrs['data-key']; }).sort();
  out.saveText = text(drawn.filter(function (n) { return n.tag === 'button' && /^Save /.test(text(n)); })[0] || '');
  out.what = text(classed(drawn, 'what')[0] || '');
  /* the bar sticks within its parent, so where it hangs is what lets it travel (review F1) */
  var column = classed(drawn, 'set-main')[0].children.filter(function (c) { return c && typeof c === 'object'; });
  out.barLastInColumn = / bar$/.test(column[column.length - 1].attrs['class'] || '');
  out.leavePending = K.beforeLeave('settings', 'cards');
  out.askedPending = asked.length;
  var ev = { stopped: false, preventDefault: function () { this.stopped = true; } };
  if (unload) unload(ev);
  out.unloadAsks = ev.stopped;
  names.forEach(function (name) { turn(name); });
  var after = walk(K.viewSettings(), []);
  out.unsavedAfter = classed(after, 'set-unsaved').length;
  out.leaveAfter = K.beforeLeave('settings', 'cards');
  return out;
}

/* What is on the page now: the rows marked unsaved, the Save bar, and whether an unload asks. */
function pendingNow() {
  var drawn = walk(K.viewSettings(), []);
  var ev = { stopped: false, preventDefault: function () { this.stopped = true; } };
  if (unload) unload(ev);
  return { unsaved: classed(drawn, 'set-unsaved').length, bar: classed(drawn, 'bar').length, unload: ev.stopped };
}
function fieldOf(drawn, key) { return drawn.filter(function (n) { return n.attrs['data-fk'] === key; })[0]; }

/* c-661 review: a number typed (no blur) marks its row at the first keystroke and redraws
   only when the key joins or leaves the pending set; typed back to what is stored it is no
   change; and a yes to the leave question empties the pending set. */
function typingOut() {
  var out = {}, key = 'install|keel.houses_max';
  var box = fieldOf(walk(K.viewSettings(), []), key), was = box.attrs.value;
  redraws = 0;
  box.attrs.oninput({ target: { value: was + '1' } });
  out.afterFirstKey = [redraws, pendingNow()];
  box.attrs.oninput({ target: { value: was + '12' } });
  out.afterSecondKey = redraws;
  box.attrs.oninput({ target: { value: was } });
  out.typedBack = [redraws, pendingNow()];
  box.attrs.oninput({ target: { value: was + '1' } });
  var before = asked.length;
  answers.push(true);
  out.leaveYes = K.beforeLeave('settings', 'cards');
  out.askedYes = asked.length - before;
  out.afterYes = pendingNow();
  return out;
}

/* c-661 review, F5: the stepper's asked choice (`choose`). Untouched it says "choose one";
   another engine and then the default again keeps the default as his answer. */
function stepperOut() {
  var key = 'install|voice.engine_default';
  var s = report.schema.filter(function (x) { return x.id === 'voice.engine_default'; })[0];
  var other = s.choices.filter(function (c) { return c !== s['default']; })[0];
  function form() { return walk(K.settingsForm({ keys: [s.id], choose: true }), []); }
  function state() {
    var drawn = form(), options = walk(fieldOf(drawn, key), []).filter(function (n) { return n.tag === 'option'; });
    return { chooseOne: options.some(function (o) { return o.attrs.value === ''; }),
             selected: options.filter(function (o) { return o.attrs.selected; }).map(function (o) { return o.attrs.value; }),
             save: text(drawn.filter(function (n) { return n.tag === 'button' && /Save|Nothing/.test(text(n)); })[0]) };
  }
  var out = { untouched: state() };
  fieldOf(form(), key).attrs.onchange({ target: { value: other } });
  out.other = state();
  fieldOf(form(), key).attrs.onchange({ target: { value: s['default'] } });
  out.backToDefault = state();
  out['default'] = s['default'];
  var discard = form().filter(function (n) { return n.tag === 'button' && text(n) === 'Discard'; })[0];
  if (discard) discard.attrs.onclick();
  return out;
}
