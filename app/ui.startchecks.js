/* The Check this computer screen of the first run (c-679), split from `ui.start.js` at its
 * review. Loaded after `ui.setup.js` and before `ui.start.js`, which reads it as
 * `K.checkScreen(report, step, parts)` and hands it its own row and section helpers (`parts`:
 * `checkRow`, `sub`), so a check is drawn the way every other step draws one.
 *
 * - Each check of the machine (`start.prerequisites` on `/api/setup`, keel/prereqs.py) is a
 *   row named by its `label`. One that fails says the three parts it carries, the sentences
 *   the installer prints: what happened (`what`), the fix (`fix`, and its `command` with
 *   Copy, drawn by `K.fixOf`, the one renderer of a fix and its command, c-688), and whether it is required (the quiet form, "does not block", for one that is not).
 * - git's name and email (`git identity`) is the one check whose fix the page does itself:
 *   two fields and Save, which sends `firstrun.identity.save`. A field starts from what git
 *   has (`values`) and one git already has cannot be typed over: the server writes only what
 *   is missing (`prereqs.save_identity`), and the page says the same. What is typed is kept
 *   across redraws until it is saved. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el;
  var IDENTITY = 'git identity';
  var draft = {};

  function has(c, field) { return (c.values || {})[field] || ''; }
  function typed(c, field) { return String(has(c, field) || (draft[field] !== undefined ? draft[field] : '')).trim(); }
  function field(c, name, label, type) {
    var set = has(c, name);
    return el('label', { class: 'start-field' }, el('span', { class: 'label', text: label }),
      el('input', { type: type, 'data-fk': 'start-git-' + name, value: set || (draft[name] !== undefined ? draft[name] : ''),
        'aria-label': label, autocomplete: 'off', disabled: set ? true : null,
        title: set ? 'git already has this, so it is kept' : null,
        oninput: function (ev) { draft[name] = ev.target.value; } }));
  }
  function save(c) {
    var name = typed(c, 'name'), email = typed(c, 'email');
    if (!name || !email) { K.toast('git needs both your name and your email', true); return; }
    K.setupParts.change({ verb: 'firstrun.identity.save', name: name, email: email }, 'saved')
      .then(function (r) { if (r) draft = {}; });
  }
  function identityForm(c) {
    return el('div', { class: 'start-form', 'data-key': 'identity-form' },
      field(c, 'name', 'Name', 'text'), field(c, 'email', 'Email', 'email'),
      el('div', { class: 'start-chips' },
        el('button', { class: 'btn primary', onclick: function () { save(c); } }, 'Save'),
        el('span', { class: 'start-hint', text: 'Writes git\'s global setting.' })));
  }

  function row(c, parts) {
    /* the form, unless git's settings could not be read: no fields over a value that may be there */
    var mine = c.name === IDENTITY && !(c.unread || []).length;
    return parts.checkRow('check-' + c.name, c.ok, (c.label || c.name) + (c.required ? '' : ' (does not block)'),
      c.ok ? c.said : c.what || c.said, c.ok ? null : mine ? identityForm(c) : K.fixOf(c), !c.required);
  }

  K.checkScreen = function (report, step, parts) {
    var checks = ((report.start || {}).prerequisites || []).map(function (c) { return row(c, parts); });
    return [parts.sub('checks', 'This computer', checks.length ? checks : el('div', { class: 'empty', text: 'reading the checks...' })),
      el('div', { class: 'start-chips' }, el('button', { class: 'btn', onclick: function () { K.setupParts.again(); } }, 'Check again')),
      el('div', { class: 'start-about', 'data-key': 'checks-note',
        text: 'Your builder joins two steps from now. Until then each row carries its own fix.' })];
  };
})(window.Keel);
