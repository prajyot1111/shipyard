/* Two screens of the first run about the builder (c-678, the first-run design's steps 0 and
 * 3), loaded before `ui.start.js`, which reads them as `K.builderChoice(report, step, parts)`
 * and `K.meetBosun(report, step, parts)` and hands them its section helper (`parts.sub`).
 *
 * CHOOSE YOUR BUILDER. Two option cards, Full and Guide, and neither is preselected: the
 * step's `choice` on the state (keel/firstrun.py) is `full`, `guide` or null, read from the
 * config, where Full is `[builder] mode = "bypass"` and Guide is `"auto"`. A pick sends ONE
 * `setup.settings.save` with builder mode on and that mode, so the choice has the writer
 * every setting has; the save records Full as Claude Code's acceptance of bypass mode in the
 * install's Claude folder, and Guide takes it out (`builder.record_bypass`, c-729). A pick the server refused says so in a panel with Try again, in the
 * server's own words (`K.refused`, app/ui.core.js).
 *
 * MEET BOSUN. One line saying which form was chosen, with Change; three checks (the builder
 * is switched on, its workspace is there, it is running, with Start Bosun, the existing
 * `console.start` tap); how to open its session (the attach command with Copy, and the
 * Claude app); and the check that the user has said hello there, which the step's `hello`
 * carries (keel/bosunhello.py reads it from the session's transcript, never a terminal).
 * The page starts no conversation and draws none: Bosun is reached in its own session.
 * The row for a Bosun that is not running has no "or ask Bosun" part, since Bosun is the
 * thing that is down. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el, App = K.App;
  var failed = null;       /* {form, error}: the pick the server refused */
  var starting = false;    /* a Start Bosun tap is running */
  var startFailed = null;  /* the last Start's refusal, in the server's words */

  var STYLE = [
    '.bopts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}',
    '.bopt{border:1px solid var(--hair-hi);background:var(--s1);padding:12px;display:flex;flex-direction:column;gap:6px;font-size:13px;line-height:1.5;min-width:0}',
    '.bopt.on{border-color:var(--accent);box-shadow:inset 3px 0 0 var(--accent)}',
    '.bopt-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:15px;font-weight:600}',
    '.bopt-one{color:var(--ink-2)}',
    '.bopt .label{margin-top:6px}',
    '.bopt p{margin:0}',
    '.bopt .btn{align-self:flex-start;margin-top:8px}',
    '.bopt-chosen{font-family:var(--mono);font-size:10px;font-weight:400;color:var(--accent-ink);border:1px solid var(--accent);border-radius:var(--pill);padding:2px 8px}',
    '.bosun-failed{border:1px solid var(--crit);background:var(--crit-soft);padding:10px 12px;font-size:13px;line-height:1.5;display:flex;flex-direction:column;gap:8px}',
    '.bosun-open{border:1px solid var(--accent);background:var(--accent-soft);padding:12px;display:flex;flex-direction:column;gap:8px;font-size:13px;line-height:1.5}',
    '.bosun-open h3{margin:0;font-size:15px}.bosun-open p{margin:0}',
    '.bosun-open .lfix{align-items:center}',
    '.bosun-form{font-size:13px;line-height:1.5;display:flex;gap:8px;flex-wrap:wrap;align-items:baseline}',
    '.linkbtn{background:none;border:0;padding:0;color:var(--accent-ink);text-decoration:underline;text-underline-offset:2px;cursor:pointer;font:inherit;font-size:13px}',
    '@media (max-width:899px){.bopts{grid-template-columns:minmax(0,1fr)}.bopt .btn,.bosun-open .btn{min-height:44px}.linkbtn{min-height:44px}}'
  ].join('\n');

  function styleOnce() {
    if (document.getElementById('startbosun-style')) return;
    var node = document.createElement('style');
    node.id = 'startbosun-style';
    node.textContent = STYLE;
    document.head.appendChild(node);
  }

  /* ---------- Choose your builder ---------- */

  /* the two forms, in the design's words: in one line, what you gain, what you do by hand,
     what it can build, what to know */
  var FORMS = [
    { id: 'full', mode: 'bypass', name: 'Full builder', one: 'It can fix things for you.',
      gain: 'When a step needs a command or something breaks, it can do the fix: install a missing tool, repair a setting, restart a service. It does not stop to ask before it acts, and it approves its own plans, so its work moves without waiting for you.',
      hand: 'Signing in (to Claude, to GitHub) is always you. Buttons on these pages are always you: it cannot press Approve for you.',
      build: 'Additions to this install (for example a connection to a code host Shipyard does not ship). Anything that would go live at once still waits for your Approve.',
      know: 'It runs as you and can reach what you can reach on this computer. Nothing reviews its commands. Two guards stay on: it never edits the code Shipyard runs or your repos\' own folders (it works in its own copies), and it is kept away from your key and password files and from pushing to main. Those rules stop accidents; they are not a locked door. Choosing it also answers Claude Code\'s own warning about this mode for you, so your builder starts without asking; choosing Guide takes that answer back.' },
    { id: 'guide', mode: 'auto', name: 'Guide builder', one: 'It explains, you do.',
      gain: 'It explains each step, points at the button to press, and reads errors with you. Claude\'s own safety check reviews everything it does and skips what it does not allow.',
      hand: 'The same, plus every fix that needs a command: it gives you the exact command, why, and how you will know it worked. You run it.',
      build: 'The same additions, and you approve both its plan and its result.',
      know: 'It will not install software or change settings on this computer, so a broken step can take you a few more minutes.' }
  ];
  var BUILDER = 'Shipyard runs Claude sessions on cards: one card is one piece of work. One session is different. It is your builder: ' +
    'it stays with this install, guides you through setup, answers when you are stuck, and can build additions to Shipyard itself.';
  var BUSY = /another setup change is running/;

  function pick(form) {
    failed = null;
    K.setupParts.change({ verb: 'setup.settings.save', changes: [
      { table: 'keel', key: 'bosun_builder', value: true }, { table: 'builder', key: 'mode', value: form.mode }] },
      form.name + ' chosen').then(function (r) {
      if (!r) { failed = { form: form, error: K.refused ? K.refused('setup.settings.save') : '' }; if (K.renderBody) K.renderBody(); }
    });
  }
  function option(form, chosen) {
    var on = chosen === form.id;
    function row(label, text) { return [el('span', { class: 'label', text: label }), el('p', { text: text })]; }
    return el('div', { class: 'bopt' + (on ? ' on' : ''), 'data-key': 'builder-' + form.id, role: 'radio', 'aria-checked': on ? 'true' : 'false' },
      el('div', { class: 'bopt-head' }, el('span', { text: form.name }), on ? el('span', { class: 'bopt-chosen', text: 'chosen' }) : null),
      el('p', { class: 'bopt-one', text: form.one }),
      row('What you gain', form.gain), row('What you do by hand', form.hand),
      row('What it can build', form.build), row('What to know', form.know),
      el('button', { class: 'btn' + (on ? ' primary' : ''), onclick: function () { pick(form); } },
        on ? 'Chosen' : 'Choose ' + form.name.toLowerCase()));
  }
  function notSaved() {
    if (!failed) return null;
    return el('div', { class: 'bosun-failed', role: 'alert', 'data-key': 'builder-not-saved' },
      el('strong', { text: 'Your choice was not saved.' }),
      el('div', { text: BUSY.test(failed.error || '') || !failed.error ? 'Another setup change is still running. Try again in a moment.'
        : K.asSentence(failed.error) }),
      el('div', null, el('button', { class: 'btn', onclick: function () { pick(failed.form); } }, 'Try again')));
  }

  K.builderChoice = function (report, step) {
    styleOnce();
    return [notSaved(),
      el('div', { class: 'bopts', role: 'radiogroup', 'aria-label': 'Builder form', 'data-key': 'builder-forms' },
        FORMS.map(function (form) { return option(form, step.choice || null); })),
      el('div', { class: 'start-about', 'data-key': 'builder-unsure', text: 'Not sure? Start with Guide. You can switch in Settings.' }),
      el('details', { class: 'start-more', 'data-key': 'builder-what' },
        el('summary', { text: 'What is a builder?' }),
        el('p', { text: BUILDER }),
        el('p', { text: 'Example of help in the full builder: a tool is missing, and it installs it. Example in the guide builder: ' +
          'the same tool is missing, and it gives you the command and tells you how you will know it worked.' }))];
  };

  /* ---------- Meet Bosun ---------- */

  var CHOSE = { full: 'You chose the full builder. Where a fix needs a command, Bosun can run it for you if you ask it in its session.',
    guide: 'You chose the guide builder. Bosun explains and points. Where a fix needs a command, it gives it to you to run.' };

  function session() { return (App.data && (App.data.console || App.data.bosun)) || {}; }
  function start() {
    starting = true; startFailed = null;
    if (K.renderBody) K.renderBody();
    K.act({ verb: 'console.start' }).then(function (r) {
      starting = false;
      if (!r) startFailed = (K.refused ? K.refused('console.start') : '') || 'the start was refused';
      if (K.renderBody) K.renderBody();
    });
  }
  function startButton(label, primary) {
    return el('button', { class: 'btn' + (primary ? ' primary' : ''), 'data-key': 'bosun-start', disabled: starting ? true : null,
      onclick: start }, starting ? 'Starting (a few seconds)' : label);
  }
  /* the same tap for any screen that needs Bosun running (Set up your repos with Bosun) */
  K.bosunStart = function (label) { return startButton(label || 'Start Bosun', true); };
  /* "Bosun is running": ready once the harness lists its session; else what to press. A
     workspace that is missing is the one failure the design names in its own sentence. */
  function runningRow(b, up, state) {
    var name = 'Bosun is running', how = 'This row turns green when Bosun is running.';
    if (up) return K.check({ key: 'bosun-running', state: 'ready', name: name, says: 'Running, ' + (state === 'working' ? 'working' : 'idle') });
    if (starting) return K.check({ key: 'bosun-running', state: 'checking', name: name, says: 'Starting (a few seconds)' });
    var why = startFailed || (!b.workspace && b.refusal) || '';
    if (!why) return K.check({ key: 'bosun-running', state: 'needs', name: name, ask: false, how: how,
      what: 'Not started. Bosun has to be running before you can talk to it.', fix: startButton('Start Bosun', true) });
    var said = (b.missing || []).length ? 'Bosun could not start: its own copy of this install\'s add-ons is missing.'
      : 'Bosun could not start: ' + why;
    return K.check({ key: 'bosun-running', state: 'needs', name: name, ask: false, how: how, what: said,
      fix: [el('div', { class: 'signin-row' }, startButton('Start again', true), K.copyButton(why, 'Copy details')),
        el('div', { class: 'stuck-then', text: 'Bosun is down, so there is no session to ask yet. Copy details is for help elsewhere. You can also Skip this step.' })] });
  }
  function openPanel(attach) {
    return el('div', { class: 'bosun-open', 'data-key': 'bosun-open' },
      el('h3', { text: 'Open Bosun\'s session' }),
      el('p', { text: 'In a terminal, run this:' }),
      attach ? K.command(attach) : null,
      el('p', { text: 'Or open Bosun in the Claude app: it is the session named Bosun.' }),
      el('p', { text: 'Say hello there. Then come back to this page.' }));
  }
  function helloRow(up, hello, hidden) {
    var name = 'You said hello in Bosun\'s session';
    if (hello) return K.check({ key: 'bosun-hello', state: 'ready', name: name, says: 'Bosun\'s session has your first message.' });
    /* a Bosun whose session Keel cannot read: said so, and no hello is asked for again */
    if (up && hidden) return K.check({ key: 'bosun-hello', state: 'waiting', name: name,
      says: 'Shipyard cannot see into Bosun\'s session from here, so this row cannot turn green. Go on when you have said hello.' });
    return K.check({ key: 'bosun-hello', state: 'waiting', name: name, says: up ? 'Waiting for your first message' : 'Start Bosun first',
      how: 'This row turns green when Bosun\'s session has a message from you.' });
  }
  function importLink(report) {
    var b = report.builder;
    if (!b || b.mode !== 'in-app') return null;
    return el('details', { class: 'start-more', 'data-key': 'bosun-import', open: b.importing ? true : null },
      el('summary', { text: 'Bring over my own Claude instructions and skills' }),
      K.setupParts.importPanel(b));
  }

  /* WATCHING FOR THE HELLO (c-729). A message in Bosun's session writes nothing on the board,
     so nothing told the page: it showed "Waiting for your first message" until some other
     write or a reload. While the page shows the step, Bosun is up and no hello is seen, the
     page asks `GET /api/hello`, and reads the state once the answer is yes, which then
     carries the hello. It is a read (r1.F6): no setup lock, so a setup tap at the same
     moment goes through, and the deck moves only when the answer changed (r1.F7). Since a
     no moves nothing, nothing redraws the page after one: the watch sets its own next ask
     (r2.F1), one timer at a time (`watching` holds from the timer through the answer),
     every three seconds for the first minute, then every ten. A failed read is a no. */
  var watching = false, asked = 0;
  function helloWait() { return asked < 20 ? 3000 : 10000; }
  function waiting() {
    var f = (K.App.data || {}).firstrun, step = f && (f.steps || []).filter(function (x) { return x.id === 'builder'; })[0];
    var shown = K.startStep ? K.startStep() : 'builder';
    return K.App.view === 'start' && shown === 'builder' && !!step && !step.hello && !step.hidden && !!session().up;
  }
  function watchHello() {
    if (watching) return;
    watching = true;
    setTimeout(function () {
      if (!waiting()) { watching = false; return; }
      asked += 1;
      function again() { watching = false; watchHello(); }
      fetch('/api/hello', { cache: 'no-store' }).then(function (r) { return r.json(); })
        .then(function (d) {
          if (d && d.hello) { watching = false; return K.load(); }
          again();
          return null;
        }, again);
    }, helloWait());
  }

  K.meetBosun = function (report, step, parts) {
    styleOnce();
    var b = (report.start || {}).bosun || {}, s = session();
    var up = !!s.up, form = b.form;
    if (up && !step.hello && !step.hidden) watchHello();
    return [
      el('div', { class: 'bosun-form', 'data-key': 'bosun-form' },
        el('span', { text: CHOSE[form] || 'No builder form is chosen yet.' }),
        el('button', { class: 'linkbtn', onclick: function () { K.openStep('choose-builder'); } }, form ? 'Change' : 'Choose your builder')),
      parts.sub('bosun-checks', null, [
        K.check({ key: 'bosun-on', state: b.on ? 'ready' : 'needs', name: 'Builder is switched on',
          says: 'On, ' + (form === 'full' ? 'full builder' : form === 'guide' ? 'guide builder' : 'no form chosen yet'),
          what: 'The builder is switched off.', ask: false,
          fix: el('button', { class: 'btn', onclick: function () { K.openStep('choose-builder'); } }, 'Choose your builder') }),
        K.check({ key: 'bosun-workspace', state: b.workspace ? 'ready' : b.on ? 'needs' : 'waiting', name: 'Bosun\'s workspace is ready',
          says: b.workspace ? 'Its own copy of this install\'s add-ons is in place' : '', ask: false,
          what: (b.missing || []).length ? 'Bosun\'s own copy of this install\'s add-ons is missing.' : b.refusal,
          fix: 'Start Bosun makes the copy when it can. If it cannot, the row below says why.' }),
        runningRow(b, up, s.state)]),
      openPanel(s.attach),
      parts.sub('bosun-said', null, helloRow(up, !!step.hello, !!step.hidden)),
      importLink(report)];
  };
})(window.Keel);
