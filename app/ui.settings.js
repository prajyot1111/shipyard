/* The Settings route (c-633): how Keel behaves, changed here rather than in config.toml.
 *
 * `/api/settings` (keel/settings.py) is the whole of what it draws: the schema (each
 * setting's table, scope, kind, default, label, help, group, choices, range and unit) and
 * every value with where it came from (config, pack, default, or gear for the Reviews gear's
 * live override). Nothing about a setting is written here: a new setting in the schema
 * appears with its label and its tooltip without deck code.
 *
 * Every field shows its help under its label, always (c-640: no tooltip to find, and the
 * phone has no hover). Reset puts a key back to its default (the key is taken out of the
 * file). Each space also has its FLOW (c-640, below): drawn as a board, with the moves
 * listed, changed by proposing it in words and adopting the proposal.
 *
 * WHICH SPACE, AND WHAT IS NOT SAVED (c-661, 2026-10-06: he ticked two switches and left
 * without Save, then saved them onto the other space, whose identical rows came first).
 * The page opens at the space the deck is in: that space's panels are the first sections.
 * A space's row carries the space's chip in the row itself, in the space's own colour. A
 * row whose value differs from what is stored says `unsaved`, and one turned back is not a
 * change. While anything is pending the Save bar is stuck to the bottom of the view and
 * names what it writes and where, and leaving the route or the page asks first
 * (`K.beforeLeave`, asked by app/ui.leave.js for `go`, Back and Forward, and `beforeunload`).
 *
 * Save sends ONE `setup.settings.save` with every change; the server checks them all before
 * it writes any, writes them in one edit, and the deck reads them in place (c-729,
 * keel/deckreload.py); a change it cannot read so (voice) re-execs it, and the page asks
 * again with retries while it is away, as Setup does. The form is never blanked meanwhile. A config that is not an
 * install's is shown read-only.
 *
 * THE SEAM S4 EMBEDS (c-632, the stepper's How work ships step): `K.settingsForm(opts)`, with
 *   opts.groups   the group names to draw (default: every group of the scope)
 *   opts.keys     setting ids (`space.autonomy`, `voice.engine_default`) to draw only those
 *   opts.choose   true: a choice still at its default shows "choose one", not the default,
 *                 so the stepper asks rather than preselects (the voice engine)
 *   opts.space    a space's name for its settings; absent for the install's
 *   opts.onSaved  called with the save's result after its own Save
 *   opts.save     false leaves out its own Save (the Settings view has one for every panel)
 * It returns one element. It loads `/api/settings` itself the first time and redraws the
 * page body when the answer arrives. `K.saveSettings(filter, onSaved)` saves the pending
 * changes, all of them or the ones `filter(change)` keeps. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el;
  var report = null, loading = false, failed = null;
  var edits = {};      /* fieldKey -> the value typed (null: back to the default), kept across redraws */
  var RETRY_MS = 1500;
  var SOURCE_WORDS = { pack: 'from the pack', gear: 'set by the Reviews gear', 'default': 'default' };

  /* THE LAYOUT (c-640, his word: the labels sat far left and the controls far right, so it
     was hard to tell which was which). A field is a label column and a control column side
     by side in a measure of at most 760px, the help always shown under its label (no hover,
     no tap), and the control next to it, left aligned; on the desk a sticky list of the
     sections sits beside them. Settings pages that read well (GitHub's, Linear's, macOS's)
     keep the pair within one glance and the explanation in the label's column. */
  var STYLE = [
    '.set-page{display:grid;grid-template-columns:184px minmax(0,760px);gap:28px;align-items:start}',
    '.set-nav{position:sticky;top:12px;display:flex;flex-direction:column;gap:2px;padding-top:4px}',
    '.set-nav a{padding:6px 10px;border-radius:8px;color:var(--ink-2);text-decoration:none;font-size:13px;line-height:1.3}',
    '.set-nav a:hover,.set-nav a:focus-visible{background:var(--s2);color:var(--ink)}',
    '.set-main{min-width:0;display:flex;flex-direction:column;gap:16px}',
    '.set-group-title{font-family:var(--mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);margin:14px 0 2px}',
    '.set-group:first-child .set-group-title{margin-top:0}',
    '.set-field{display:grid;grid-template-columns:minmax(180px,280px) minmax(0,1fr);gap:4px 24px;align-items:start;padding:12px 0;border-top:1px solid var(--hair)}',
    '.set-group > .set-field:first-child,.set-group-title + .set-field{border-top:0}',
    '.set-label{display:flex;flex-direction:column;gap:3px;min-width:0}',
    '.set-label .t{font-weight:600;color:var(--ink);font-size:13px}',
    '.set-name{display:flex;align-items:center;gap:4px 8px;flex-wrap:wrap}',
    /* your edit, not yet written: the accent filled, so it is not one more outlined chip */
    '.set-unsaved{display:inline-flex;align-items:center;height:20px;padding:0 8px;border-radius:var(--pill);background:var(--accent);color:var(--on-accent);font-family:var(--mono);font-size:10px;font-weight:600;flex:0 0 auto}',
    '.set-field.changed .set-label .t::before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--accent);margin-right:6px;vertical-align:middle}',
    '.set-help{color:var(--ink-3);font-size:12px;line-height:1.45}',
    '.set-control{display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-height:32px}',
    '.set-control input[type=number]{width:104px}',
    '.set-control input[type=text]{width:min(100%,320px)}',
    '.set-control select{max-width:320px}',
    '.set-src{grid-column:2;font-family:var(--mono);font-size:10px;color:var(--ink-3)}',
    /* Reset is quiet: a value the config sets explicitly is most of them on an install */
    '.set-reset{border:0;background:none;color:var(--ink-3);font-size:12px;padding:4px 6px;cursor:pointer;text-decoration:underline;text-underline-offset:3px}',
    '.set-reset:hover,.set-reset:focus-visible{color:var(--ink)}',
    '.set-save{display:flex;gap:8px;align-items:center;flex-wrap:wrap}',
    /* The view's own Save, drawn only while something is pending: the LAST CHILD OF
       `.set-main`, so the whole column is the room it sticks within (as a grid item of
       `.set-page` its own row was, and it never left the end of the page). It sticks to the
       bottom of the scroller's content box: `.body`'s bottom padding, which on the phone is
       the dock's height and the inset (app/ui.css), is what keeps it above the fixed dock. */
    '.set-save.bar{position:sticky;bottom:0;z-index:5;padding:8px 12px;background:var(--s3);border:1px solid var(--accent);border-radius:var(--r)}',
    '.set-save .what{flex:1 1 200px;min-width:0}',
    '.set-warn .row{border-left:3px solid var(--warn)}',
    '.flow-graph{height:240px;border:1px solid var(--hair);border-radius:var(--r);background:var(--s1);overflow:hidden}',
    '.flow-moves{display:flex;flex-direction:column;gap:6px;margin-top:12px}',
    '.flow-move{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 12px;padding:8px 10px;border:1px solid var(--hair);border-radius:var(--r)}',
    '.flow-move .who{font-family:var(--mono);font-size:10px;padding:2px 6px;border-radius:var(--pill);background:var(--s2);color:var(--ink-2);align-self:start}',
    '.flow-move .who.him{background:var(--accent-soft);color:var(--accent-ink)}',
    '.flow-move .path{grid-column:1 / -1;font-family:var(--mono);font-size:11px;color:var(--ink-3)}',
    '.flow-change{display:flex;flex-direction:column;gap:8px;margin-top:14px}',
    '.flow-change textarea{min-height:88px;width:100%;resize:vertical}',
    '@media (max-width:899px){.set-page{grid-template-columns:1fr}.set-nav{display:none}',
    '.set-field{grid-template-columns:1fr}.set-src{grid-column:1}',
    '.set-control input,.set-control select,.set-save .btn,.flow-change .btn{min-height:44px}.set-control input[type=text],.set-control select{width:100%;max-width:none}}'
  ].join('\n');

  function styleOnce() {
    if (document.getElementById('settings-style')) return;
    var node = document.createElement('style');
    node.id = 'settings-style';
    node.textContent = STYLE;
    document.head.appendChild(node);
  }

  function load(retries) {
    if (loading) return;
    loading = true;
    fetch('/api/settings', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (d) {
      loading = false; failed = null; report = d; redraw();
    }).catch(function (e) {
      loading = false;
      /* right after a save the deck is re-executing: ask again shortly */
      if (retries > 0) { setTimeout(function () { load(retries - 1); }, RETRY_MS); return; }
      failed = e.message; redraw();
    });
  }
  K.loadSettings = load;
  function redraw() { if (K.App.data && K.renderBody) K.renderBody(); }

  /* ---------- one field ---------- */

  function fieldKey(space, s) { return (space || 'install') + '|' + s.id; }
  function stored(space, s) {
    var values = space ? ((report.values.spaces || {})[space] || {}) : report.values.install;
    return values[s.id] || { value: s['default'], source: 'default' };
  }
  function edited(key) { return Object.prototype.hasOwnProperty.call(edits, key); }
  /* the default this field goes back to: the space's pack's value where its `[space]` sets
     one (c-730, `default` on the value row), else Shipyard's */
  function dfltOf(space, s) {
    var now = stored(space, s);
    return Object.prototype.hasOwnProperty.call(now, 'default') ? now['default'] : s['default'];
  }
  /* what the field shows: his edit, else the value in force; a reset shows the default */
  function shown(space, s) {
    var key = fieldKey(space, s);
    if (!edited(key)) return stored(space, s).value;
    return edits[key] === null ? dfltOf(space, s) : edits[key];
  }
  /* An edit back to what is stored is no change (c-661): nothing to save, nothing to ask
     about. `keep` is the stepper's asked choice (`opts.choose`, a choice whose stored value
     is the default), where picking the default IS his answer. */
  function set(s, space, value, again, keep) {
    var key = fieldKey(space, s), was = edited(key);
    if (!keep && same(value, stored(space, s).value)) delete edits[key]; else edits[key] = value;
    /* A keystroke redraws only when it moves the key into or out of the pending set, so the
       mark and the Save bar are there at the first character, not at blur. The field he is
       typing in keeps its text and caret: the morph leaves a focused input's value alone. */
    if (again || was !== edited(key)) redraw();
  }
  function same(a, b) { return JSON.stringify(a === undefined ? null : a) === JSON.stringify(b === undefined ? null : b); }

  function words(v) {
    if (v === true) return 'on';
    if (v === false) return 'off';
    if (v === null || v === undefined || v === '') return 'unset';
    return Array.isArray(v) ? v.join(', ') : String(v);
  }

  function numberOf(s, text) {
    if (text === '') return s['default'] === null ? null : text;
    var n = Number(text);
    return isFinite(n) ? n : text;          /* the server says what is wrong with the rest */
  }

  function modelOptions(s, value) {
    var names = (s.choices || []).concat(report.models || []);
    if (value && names.indexOf(value) < 0) names.push(value);
    var out = s['default'] === null ? [el('option', { value: '', text: 'unset (the default below this)', selected: !value })] : [];
    return out.concat(names.map(function (n) { return el('option', { value: n, text: n, selected: n === value }); }));
  }

  function control(s, space, value, readOnly, choose, keep) {
    var key = fieldKey(space, s);
    function put(v, again) { set(s, space, v, again, keep); }
    var off = readOnly || null;
    var label = s.label;
    if (s.kind === 'bool') {
      return el('input', { type: 'checkbox', role: 'switch', 'aria-label': label, 'data-fk': key, checked: !!value,
        disabled: off, onchange: function (ev) { put(!!ev.target.checked, true); } });
    }
    if (s.kind === 'int' || s.kind === 'float') {
      return [el('input', { type: 'number', 'aria-label': label, 'data-fk': key, disabled: off,
          value: value === null || value === undefined ? '' : String(value),
          min: s.low === null ? null : String(s.low), max: s.high === null ? null : String(s.high),
          step: s.kind === 'int' ? '1' : 'any', placeholder: s['default'] === null ? 'unset' : null,
          oninput: function (ev) { put(numberOf(s, ev.target.value)); },
          onchange: function (ev) { put(numberOf(s, ev.target.value), true); } }),
        s.unit ? el('span', { class: 'mono t11 ink3', text: s.unit }) : null];
    }
    if (s.kind === 'choice' || s.kind === 'model') {
      var options = s.kind === 'model' ? modelOptions(s, value)
        : (choose ? [el('option', { value: '', text: 'choose one', selected: true, disabled: true })] : [])
          .concat(s.choices.map(function (c) { return el('option', { value: c, text: c, selected: !choose && c === value }); }));
      return el('select', { 'aria-label': label, 'data-fk': key, disabled: off,
        onchange: function (ev) { put(ev.target.value === '' ? null : ev.target.value, true); } }, options);
    }
    if (s.kind === 'list') {
      return el('input', { type: 'text', 'aria-label': label, 'data-fk': key, disabled: off,
        value: (value || []).join(', '), placeholder: 'comma separated',
        oninput: function (ev) { put(listOf(ev.target.value)); },
        onchange: function (ev) { put(listOf(ev.target.value), true); } });
    }
    return el('input', { type: 'text', 'aria-label': label, 'data-fk': key, disabled: off,
      value: value === null || value === undefined ? '' : String(value), placeholder: s['default'] === null ? 'unset' : null,
      oninput: function (ev) { put(textOf(s, ev.target.value)); },
      onchange: function (ev) { put(textOf(s, ev.target.value), true); } });
  }
  function listOf(text) { return text.split(',').map(function (w) { return w.trim(); }).filter(Boolean); }
  function textOf(s, text) { return text === '' && s['default'] === null ? null : text; }

  function sourceLine(s, now, key, dflt) {
    if (edited(key)) return edits[key] === null ? 'goes back to the default (' + words(dflt) + ') on Save' : null;
    var word = SOURCE_WORDS[now.source];
    if (!word) return null;
    /* a pack's value is the space's default, so it names no other (c-730) */
    return now.source === 'default' ? 'default' : now.source === 'pack' ? word : word + ' (default ' + words(dflt) + ')';
  }

  /* a space's own words for a help that names a ticket or a change (c-630), else the schema's */
  function helpOf(s, space) { return (space && ((report.helps || {})[space] || {})[s.id]) || s.help; }

  function field(s, space, readOnly, ask) {
    var key = fieldKey(space, s);
    var help = helpOf(s, space);
    var now = stored(space, s), dflt = dfltOf(space, s);
    var changed = edited(key), atDefault = now.source === 'default' || now.source === 'pack';
    var resettable = !readOnly && (changed ? edits[key] !== null : !atDefault);
    var source = sourceLine(s, now, key, dflt);
    /* asked, not preselected: "choose one" only while it is still the default and untouched.
       Once he has answered, the answer is kept even when it is the default, so going back
       to the default does not drop it and put "choose one" back (c-661 review, F5). */
    var asked = !!ask && s.kind === 'choice' && now.source === 'default';
    var choose = asked && !changed;
    return el('div', { class: 'set-field' + (changed ? ' changed' : ''), 'data-key': 'set-' + key },
      el('div', { class: 'set-label' },
        el('div', { class: 'set-name' },
          el('label', { class: 't', text: s.label }),
          space ? spaceChip(space) : null,
          changed ? el('span', { class: 'set-unsaved', text: 'unsaved' }) : null),
        help ? el('div', { class: 'set-help', text: help }) : null),
      el('div', { class: 'set-control' },
        control(s, space, shown(space, s), readOnly, choose, asked),
        resettable ? el('button', { class: 'set-reset', type: 'button', title: 'Back to the default: ' + words(dflt),
          onclick: function () { if (atDefault) delete edits[key]; else edits[key] = null; redraw(); } }, 'Reset') : null),
      source ? el('div', { class: 'set-src', text: source }) : null);
  }

  /* The space a row is for, said in the row (c-661): the board's chip in the space's own
     colour (`.bchip.space-*`, app/ui.css), whichever space the deck is in. */
  function spaceChip(space) {
    return el('span', { class: 'bchip space-' + (K.palette ? K.palette(space) : space), 'data-space': space,
      title: 'a setting of the ' + space + ' space', text: space });
  }

  /* ---------- the form, and its Save ---------- */

  function settingsOf(space, groups, keys) {
    var scope = space ? 'space' : 'install';
    return report.schema.filter(function (s) {
      return s.scope === scope && (!groups || groups.indexOf(s.group) >= 0) && (!keys || keys.indexOf(s.id) >= 0);
    });
  }

  function pending(filter) {
    return Object.keys(edits).map(function (key) {
      var at = key.indexOf('|'), owner = key.slice(0, at), id = key.slice(at + 1);
      var s = report.schema.filter(function (x) { return x.id === id; })[0];
      var change = { table: s.table, key: s.key, value: edits[key], field: key, label: s.label };
      if (owner !== 'install') change.space = owner;
      return change;
    }).filter(function (c) { return !filter || filter(c); });
  }

  /* One batch, then the deck reads it (in place, or by a re-exec): the report is asked for again. */
  function save(filter, onSaved) {
    var changes = pending(filter);
    if (!changes.length) return Promise.resolve(null);
    var body = { verb: 'setup.settings.save', changes: changes.map(function (c) {
      var out = { table: c.table, key: c.key, value: c.value };
      if (c.space) out.space = c.space;
      return out;
    }) };
    return K.act(body, function () { return 'saved; the deck is reading the new config'; }).then(function (result) {
      if (!result) return null;
      changes.forEach(function (c) { delete edits[c.field]; });
      /* c-729: the form keeps showing what it had until the new report lands, and the state
         is read after it; a save the deck read in place is asked for at once */
      if (result.restarting) setTimeout(function () { load(8); }, RETRY_MS);
      else load(0);
      if (K.load) K.load();
      if (onSaved) onSaved(result);
      return result;
    });
  }
  K.saveSettings = save;

  function listed(names) {
    return names.length < 2 ? names.join('') : names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1];
  }
  /* where the changes go: "work", "this install and work", in the order they were made */
  function whereOf(changes) {
    var names = [];
    changes.forEach(function (c) {
      var name = c.space || 'this install';
      if (names.indexOf(name) < 0) names.push(name);
    });
    return listed(names);
  }
  /* which settings, each with its space: the first three by name, the rest counted */
  function whatOf(changes) {
    var names = changes.slice(0, 3).map(function (c) { return c.label + (c.space ? ' (' + c.space + ')' : ''); });
    return names.join(', ') + (changes.length > 3 ? ' and ' + (changes.length - 3) + ' more' : '');
  }
  function countOf(changes) { return changes.length + (changes.length === 1 ? ' change' : ' changes') + ' to ' + whereOf(changes); }

  /* `stuck` is the Settings view's one bar (c-661): absent until something is pending, then
     stuck to the bottom of the view. An embedded form's own bar is always drawn, in place. */
  function saveBar(filter, onSaved, readOnly, stuck) {
    if (readOnly) return null;
    var changes = pending(filter), n = changes.length;
    if (stuck && !n) return null;
    return el('div', { class: 'set-save' + (stuck ? ' bar' : ''), 'data-key': 'set-save' },
      el('button', { class: 'btn primary', disabled: n ? null : true, onclick: function () { save(filter, onSaved); } },
        n ? 'Save ' + countOf(changes) : 'Nothing to save'),
      n ? el('button', { class: 'btn sm', onclick: function () { discard(filter); redraw(); } }, 'Discard') : null,
      el('span', { class: 'mono t11 ink3 what', text: (n ? whatOf(changes) + ' · ' : '') + 'a save takes effect at once (a voice change restarts the deck)' }));
  }
  function discard(filter) { pending(filter).forEach(function (c) { delete edits[c.field]; }); }

  /* Leaving with changes pending asks first (c-661). `go`, Back and Forward ask this
     through app/ui.leave.js, with the view being left and the one asked for: false keeps
     him here. A yes drops the changes, so they are not waiting, unsaved and unseen, when
     he comes back. */
  K.beforeLeave = function (from) {
    if (from !== 'settings') return true;
    var changes = report ? pending() : [];
    if (changes.length && !window.confirm('Settings has ' + countOf(changes) + ' not saved: ' + whatOf(changes) +
        '.\n\nLeave and drop ' + (changes.length === 1 ? 'it' : 'them') + '?')) return false;
    if (changes.length) discard();
    opened = null;
    return true;
  };
  /* a reload, a closed tab, or a link to a page outside the deck's shell: the browser's own ask */
  if (window.addEventListener) window.addEventListener('beforeunload', function (ev) {
    if (!Object.keys(edits).length) return;
    ev.preventDefault();
    ev.returnValue = '';
  });

  function settingsForm(opts) {
    opts = opts || {};
    styleOnce();
    if (!report && !loading && !failed) load(0);
    if (failed) return el('div', { class: 'empty', text: 'Settings could not be read: ' + failed });
    if (!report) return el('div', { class: 'empty', text: 'reading the settings...' });
    var readOnly = !report.install;
    var list = settingsOf(opts.space, opts.groups, opts.keys);
    var groups = report.groups.filter(function (g) { return list.some(function (s) { return s.group === g; }); });
    var mine = function (c) { return (c.space || null) === (opts.space || null) && list.some(function (s) { return s.table === c.table && s.key === c.key; }); };
    return el('div', { class: 'set-form', 'data-key': 'set-form-' + (opts.space || 'install') + '-' + groups.join('/') + (opts.keys ? '-' + opts.keys.join('/') : '') },
      groups.map(function (g) {
        return el('div', { class: 'set-group', 'data-key': 'group-' + g },
          groups.length > 1 ? el('div', { class: 'set-group-title', text: g }) : null,
          list.filter(function (s) { return s.group === g; }).map(function (s) { return field(s, opts.space, readOnly, opts.choose); }));
      }),
      opts.save === false ? null : saveBar(mine, opts.onSaved, readOnly));
  }
  K.settingsForm = settingsForm;
  /* c-730: what a space's field shows now (its unsaved edit, else the value in force), so a
     form that offers more once a switch is on can follow the switch before Save; null while
     the settings are not read yet */
  K.settingShown = function (space, id) {
    var s = report ? report.schema.filter(function (x) { return x.id === id; })[0] : null;
    return s ? shown(space, s) : null;
  };

  /* ---------- the route ---------- */

  function panel(key, title, body) {
    return el('section', { class: 'panel', 'data-key': key, id: key },
      el('div', { class: 'panel-head' }, el('span', { class: 'label', text: title })),
      el('div', { class: 'panel-body' }, body));
  }

  /* ---------- a space's flow (c-640, keel/flows.py, Atlas 64) ---------- */

  var flowWords = {};   /* space -> your words for a proposal, kept across redraws */
  var WHO = { house: 'the house', you: 'you', colleague: 'a teammate', keel: 'Shipyard' };
  /* c-758 r1.F6: the same words as the first run's drawing (app/ui.flowpicture.js). Approve
     and Ship are the card's own buttons, so those steps are yours; a step made on the code
     host is a teammate's in a flow a team wrote, and "you or a teammate" in Shipyard's own
     general flow, which cannot know, as the shipped connections say of the merge. */
  var CARD_BUTTONS = { land: true, publish: true, ship: true };
  function cardButton(m) { return m.by === 'keel' && !!CARD_BUTTONS[m.step]; }
  function whoOf(m, flow) {
    if (cardButton(m)) return 'you';
    return m.by === 'colleague' && (flow || {}).source === 'keel' ? 'you or a teammate' : WHO[m.by] || m.by;
  }
  /* c-664: what a flow is and is not, said where the flow is read */
  var ONLY_YOURS = 'Only the moves you make are buttons that act. Every other move is a picture of what the space\'s pack and Shipyard already do: changing it in the flow changes this drawing, not what happens.';
  var NO_BUTTON = ' This flow has no move of your own, so it adds no button to a card: Approve and Ship are the card\'s own buttons, and they stay where they are.';

  function flowOf(name) {
    var spaces = ((K.App.data || {}).spaces || {});
    return (spaces[name] || {}).flow || null;
  }

  /* A label as a person reads it (c-664): `{base}` and `{branch}` are filled per card, so
     the drawing says which, never the braces. */
  function flowLabel(label) {
    return String(label).replace(/\{base\}/g, 'the card\'s base').replace(/\{branch\}/g, '(the card\'s branch)');
  }
  K.flowLabel = flowLabel;

  K.flowLines = flowLines;     /* for the node fixture */
  function flowLines(flow) {
    var icon = { card: 'git-branch', base: 'git-branch', integration: 'git-branch', environment: 'cloud', trunk: 'server' };
    var lines = ['board "' + flow.name.replace(/"/g, "'") + '"'];
    flow.branches.forEach(function (b) {
      lines.push('node ' + b.id + ' ' + (icon[b.kind] || 'box') + ' "' + flowLabel(b.label).replace(/"/g, "'") + '" "' + b.kind + '"');
    });
    /* one edge per move: each label within the board's 240 characters (flows.LABEL_MAX) */
    flow.moves.forEach(function (m) {
      lines.push('edge ' + m.from + ' -> ' + m.to + ' "' + (m.label + ' · ' + whoOf(m, flow)).replace(/"/g, "'") + '"');
    });
    flow.moves.filter(function (m) { return m.by === 'you'; }).forEach(function (m) { lines.push('mark ' + m.to + ' accent'); });
    return lines;
  }

  /* The graph host: built EMPTY by the render pass and drawn after it (the plan diagram's
     way), drawn again only when the flow or the width changed. */
  function flowGraph(name, flow) {
    var key = 'flow-graph-' + name, lines = flowLines(flow);
    var node = el('div', { class: 'flow-graph', 'data-key': key, 'data-morph': 'skip', role: 'img',
      'aria-label': 'the ' + name + ' flow: ' + flow.branches.map(function (b) { return flowLabel(b.label); }).join(', ') });
    setTimeout(function () {
      var live = document.querySelector('.flow-graph[data-key="' + key + '"]');
      if (!live || !K.boardDraw) return;
      var sig = lines.join('\n') + '@' + (live.clientWidth || 0);
      if (live._sig === sig) return;
      live._sig = sig;
      K.boardDraw.drawGraph(live, K.boardDraw.foldInto(K.boardDraw.newModel(), lines), true);
    }, 0);
    return node;
  }

  function flowMove(m, flow) {
    var when = m.stages && m.stages.length ? ' · at ' + m.stages.join(', ') : '';
    var yours = m.by === 'you';
    return el('div', { class: 'flow-move', 'data-key': 'flow-move-' + m.id },
      el('span', { class: 't', text: m.label }),
      el('span', { class: 'who' + (yours ? ' him' : ''), text: whoOf(m, flow) +
        (yours ? ' · a button' : cardButton(m) ? ' · the card\'s own button' : ' · drawn only') }),
      el('span', { class: 'path', text: m.from + ' → ' + m.to + when + (yours && m.group ? ' · in ' + m.group : '') }),
      m.about ? el('span', { class: 'set-help', style: 'grid-column:1 / -1', text: m.about }) : null);
  }

  /* How the space handles review at shipping (c-664): no flow says it, the space's two
     settings do (`flow.handling`, keel/flows.py), so their state is said here with the way
     to them. Where no card reaches shipping, a setting that is on is said to do nothing. */
  function flowHandling(name, flow) {
    var h = flow.handling;
    if (!h) return null;
    /* a held space: its cases differ (one of them does reach shipping, unwatched), so the
       note says only what is true of them all and leaves the rest to the held line */
    if (flow.held) return el('div', { class: 'set-help', 'data-key': 'flow-handling-' + name,
      text: 'Not in the flow: Shipyard draws no flow here, so it says nothing of shipping; see the line above.' });
    var kept = 'kept on the card until you hand them to its house', sent = 'handed to its house as they arrive';
    var on = [h.comments ? 'Handle review comments automatically' : null, h.checks ? 'Handle failing checks automatically' : null]
      .filter(function (one) { return one; });
    var words = h.shipping
      ? 'Not in the flow: while a card waits at shipping, review comments are ' + (h.comments ? sent : kept) +
        ', and failing checks are ' + (h.checks ? sent : kept) + '. Two settings of this space decide that: '
      : 'Not in the flow: no card of this space reaches shipping (it has no code host), so there is no review to hand over.' +
        (on.length ? ' ' + on.join(' and ') + (on.length > 1 ? ' are' : ' is') + ' turned on here and ' +
          (on.length > 1 ? 'do' : 'does') + ' nothing in this space: ' : ' The two settings for it do nothing here: ');
    return el('div', { class: 'set-help', 'data-key': 'flow-handling-' + name }, words,
      el('a', { href: '#set-space-' + name, text: 'Space · ' + name + ', Tests and shipping', onclick: function (ev) {
        var target = document.getElementById('set-space-' + name);
        if (!target) return;
        ev.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      } }), '.');
  }

  var SOURCE = { space: "this space's own", pack: "its pack's", keel: "Shipyard's" };

  /* The Propose box says what the tap starts and that nothing changes until Adopt, and an
     open proposal says where it went and how it stands (`K.proposing`, app/ui.setup.js:
     one wording for this, the tier proposal and the import, c-664). */
  function flowChange(name, flow) {
    var proposal = flow.proposal, P = K.proposing;
    if (proposal) return el('div', { class: 'flow-change', 'data-key': 'flow-change-' + name },
      P.after(proposal, 'a new ' + name + ' flow', el('button', { class: 'btn primary sm',
        onclick: function () { K.act({ verb: 'setup.flow.adopt', card: proposal.card }, function (r) { return r && r.where ? K.sentence({ verb: 'approve', gate: 'outcome', id: proposal.card }, r) : 'the ' + name + ' flow is the proposal now'; }); } }, 'Adopt')));
    var example = 'We branch from main and open a {change} for each piece of work. A teammate reviews and merges it. Sometimes I merge a branch into our shared test branch first, to try it live...';
    return el('div', { class: 'flow-change', 'data-key': 'flow-change-' + name },
      el('label', { class: 't', for: 'flow-words-' + name, text: 'Describe how your team ships' }),
      el('div', { class: 'set-help', text: 'The branches, where work goes after it is built, and who moves it. A move you want to make yourself (a merge to a test branch, say) becomes a button on the card; the rest is drawn.' }),
      el('textarea', { id: 'flow-words-' + name, 'data-key': 'flow-words-' + name, value: flowWords[name] || '',
        placeholder: K.say ? K.say(name, example) : example,
        oninput: function (ev) { flowWords[name] = ev.target.value; } }),
      P.before(),
      el('div', { class: 'set-save' },
        el('button', { class: 'btn primary', onclick: function () {
          K.act({ verb: 'setup.flow.propose', space: name, words: flowWords[name] || '' },
            function (r) { flowWords[name] = ''; return (r && r.card) + ' is filed to draft the ' + name + ' flow: its card is linked here now'; });
        } }, 'Propose'),
        flow.source === 'space' ? el('button', { class: 'btn sm', onclick: function () {
          K.act({ verb: 'setup.flow.reset', space: name }, function (r) { return (r && r.note) || 'reset'; });
        } }, "Use the pack's or Shipyard's flow") : null));
  }

  function flowPanel(name, readOnly) {
    var flow = flowOf(name);
    if (!flow) return null;
    var yours = flow.moves.some(function (m) { return m.by === 'you'; });
    return el('section', { class: 'panel', 'data-key': 'set-flow-' + name, id: 'set-flow-' + name },
      el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'Flow · ' + name }), el('span', { class: 'spacer' }), spaceChip(name)),
      el('div', { class: 'panel-body' },
        el('div', { class: 'sub', 'data-key': 'flow-about-' + name, text: flow.name + ', ' + SOURCE[flow.source] + ' flow. ' + flow.description }),
        /* c-664: why Keel draws no flow for a held space (`flow.held`, keel/flows.py: a
           whole sentence, true of its own case, printed as it is). A line of its own,
           whatever the flow's source, with the first run's step for it */
        flow.held ? el('div', { class: 'sub', 'data-key': 'flow-held-' + name }, flow.held,
          K.stepHref ? [' ', el('a', { href: K.stepHref('integrations', name), 'data-key': 'flow-setup-' + name, text: 'Set it up',
            onclick: function (ev) { if (K.openStep) { ev.preventDefault(); K.openStep('integrations', name); } } })] : null) : null,
        el('div', { class: 'set-help', 'data-key': 'flow-honest-' + name, text: ONLY_YOURS + (yours ? '' : NO_BUTTON) }),
        flowGraph(name, flow),
        el('div', { class: 'flow-moves' }, flow.moves.map(function (m) { return flowMove(m, flow); })),
        flowHandling(name, flow),
        readOnly ? null : flowChange(name, flow)));
  }

  /* The space the page was last opened at: an arrival, or a switch of space, opens at the
     top, where that space's sections are, not where a past visit had scrolled to. */
  var opened = null;
  function openAt(here) {
    if (opened === here) return;
    opened = here;
    if (K.writeScroll && K.scrollKey) K.writeScroll(K.scrollKey(), 0);
  }

  /* what the page holds, said at its top: the deck's header names one space, the page has all */
  function holds(here, others) {
    var rest = ['this install'].concat(others);
    return (here ? 'The deck is in ' + here + ', so its settings come first, then those of ' + listed(rest) + '.'
        : 'These are the settings of ' + listed(rest) + '.') +
      ' A setting of one space carries that space\'s name.';
  }

  function viewSettings() {
    styleOnce();
    var names = report ? Object.keys(report.values.spaces || {}) : [];
    var here = names.indexOf(K.App.space) >= 0 ? K.App.space : null;
    openAt(K.App.space || '');
    if (!report) return settingsForm();
    var readOnly = !report.install;
    var out = [], nav = [];
    function add(id, title, node) {
      if (!node) return;
      if (!node.id) node.id = id;
      out.push(node);
      nav.push(el('a', { href: '#' + node.id, text: title, onclick: function (ev) {
        ev.preventDefault();
        var target = document.getElementById(node.id);
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      } }));
    }
    if (readOnly) out.push(el('div', { class: 'empty', 'data-key': 'not-install',
      text: 'This deck reads ' + report.config + ', which is not an install\'s config.toml: Settings shows it and changes nothing.' }));
    if ((report.warnings || []).length) out.push(warningPanel(report.warnings, false));
    var others = names.filter(function (name) { return name !== here; });
    out.push(el('div', { class: 'sub', 'data-key': 'set-holds', text: holds(here, others) }));
    function space(name) {
      add('set-space-' + name, 'Space · ' + name, panel('set-space-' + name, 'Space · ' + name, settingsForm({ space: name, save: false })));
      add('set-flow-' + name, 'Flow · ' + name, flowPanel(name, readOnly));
    }
    /* the deck's space first (c-661), then the install's own, then every other space */
    if (here) space(here);
    var install = report.groups.filter(function (g) { return g !== 'Voice'; });
    add('set-install', 'This install', panel('set-install', 'This install', settingsForm({ groups: install, save: false })));
    others.forEach(space);
    add('set-voice', 'Voice', panel('set-voice', 'Voice', settingsForm({ groups: ['Voice'], save: false })));
    return el('div', { class: 'set-page', 'data-key': 'set-page' },
      el('nav', { class: 'set-nav', 'aria-label': 'Settings sections' }, nav),
      el('div', { class: 'set-main' }, out, saveBar(null, null, readOnly, true)));
  }
  K.viewSettings = viewSettings;
  /* beside the deck's header, which names the one space the deck is in */
  K.headerHint = function (view) { return view === 'settings' ? 'Settings · every space' : null; };

  /* ---------- the warnings, on Now and here ---------- */

  function warningPanel(lines, link) {
    return el('section', { class: 'panel set-warn', 'data-key': 'config-warnings' },
      el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'The config has ' + lines.length +
        (lines.length === 1 ? ' problem' : ' problems') }), el('span', { class: 'spacer' }),
        link ? el('button', { class: 'btn sm', onclick: function () { K.go('settings'); } }, 'Open Settings') : null),
      el('div', { class: 'panel-body' }, lines.map(function (line, i) {
        return el('div', { class: 'row', 'data-key': 'warn-' + i }, el('div', { class: 'sub mono t11', text: line }));
      }),
      el('div', { class: 'sub', text: 'Each one was left out and its default used, so Shipyard runs; fix it here or in the file.' })));
  }
  /* Now draws this (ui.views.js): the loader's warnings, from the state document. */
  K.configWarnings = function () {
    var config = (K.App.data && K.App.data.config) || {};
    /* c-678: a key Keel does not know is a stuck line with its fix (app/ui.stuckcard.js);
       the panel keeps the rest (a value a setting may not take, a flow that did not load) */
    var known = (config.unknown || []).map(function (u) { return u.line; });
    var lines = (config.warnings || []).filter(function (line) { return !K.unknownKeys || known.indexOf(line) < 0; });
    if (!lines.length && !known.length) return null;
    styleOnce();
    return [K.unknownKeys ? K.unknownKeys() : null, lines.length ? warningPanel(lines, true) : null];
  };

  /* The phone reaches Settings under More, beside Setup. */
  var baseMore = K.viewMore;
  K.viewMore = function () {
    var out = baseMore ? baseMore() : [];
    if (!Array.isArray(out)) out = [out];
    out.splice(2, 0, el('section', { class: 'panel', 'data-key': 'settings-entry' },
      el('div', { class: 'panel-body' },
        el('button', { class: 'row', onclick: function () { K.go('settings'); } },
          el('div', { class: 'row-head' }, el('span', { class: 't', text: 'Settings' }),
            el('span', { class: 'spacer' }),
            el('span', { class: 'mono t11 ink3', text: 'how Shipyard behaves' }))))));
    return out;
  };
})(window.Keel);
