/* Set up your repos with Bosun, the first run's step 6 (c-678), loaded before `ui.start.js`,
 * which reads it as `K.draftsScreen(report, step, parts)`.
 *
 * The page has three parts and draws no conversation:
 * 1. Hand over to Bosun: how to open its session (the attach command with Copy, the Claude
 *    app) and a first thing to say, "Set up my repos.".
 * 2. What Bosun will ask about, so the user knows what is coming. It is not a form.
 * 3. What came back: one row per CLAUDE.md Bosun drafts (keel/tierdrafts.py), with its
 *    state: not started, Bosun is drafting, ready for you, adopted. A ready row shows the
 *    lines Keel reads from the draft (prepare, test, and a lands line said to move nothing, each with the line of the
 *    file it came from), Read the draft, which opens the text, and Adopt, which is
 *    `setup.tier.adopt` for the draft's card: the user's tap, and the only thing that
 *    writes the file. Tell Bosun what to change says where to say it and sends nothing.
 *    An adopted file whose lines do not run (it changed since it was adopted or saved, or
 *    never was) says so, and once its text has been read here it has Keep this text, which
 *    is the Setup page's own Save (`setup.tier.save`) of exactly the text that was shown.
 *
 * THE LIST FOLLOWS BOSUN. The rows' states come from the step on the state document
 * (`step.drafts`, read on every poll); their text and commands from the Setup report
 * (`spaces.<name>.drafts`), which is read again, once, whenever the states or a draft's
 * stamp moved.
 *
 * While Bosun is not running a check at the top says so with Start Bosun (the same tap as
 * on Meet Bosun, `K.bosunStart`), and every row not yet ready or adopted says so too. Skip
 * for now says what is lost and skips the step. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el, App = K.App;
  var opened = {};        /* aim -> its text is open */
  var telling = {};       /* aim -> the note about telling Bosun is shown */
  var seen = null;        /* the states and stamps the report was last asked for */

  var STYLE = [
    '.dr-panel{border:1px solid var(--hair-hi);background:var(--s1);padding:12px;display:flex;flex-direction:column;gap:8px;font-size:13px;line-height:1.5;min-width:0}',
    '.dr-panel.flag{border-color:var(--accent)}',
    '.dr-panel h3,.dr-back h3{margin:0;font-size:15px}.dr-panel p{margin:0}.dr-panel ul{margin:0;padding-left:20px}',
    '.dr-panel .lfix{align-items:center}',
    '.dr-back{display:flex;flex-direction:column;gap:8px}',
    '.dr-row{border:1px solid var(--hair-hi);background:var(--s1);padding:12px;display:flex;flex-direction:column;gap:8px;min-width:0}',
    '.dr-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}',
    '.dr-label{font-family:var(--mono);font-size:13px;font-weight:600}',
    '.dr-pill{font-family:var(--mono);font-size:10px;border:1px solid var(--hair-hi);border-radius:var(--pill);padding:2px 8px;color:var(--ink-3);display:inline-flex;align-items:center;gap:6px}',
    '.dr-pill.ready{color:var(--warn);border-color:var(--warn)}.dr-pill.adopted{color:var(--good);border-color:var(--good)}',
    '.dr-pill.drafting{color:var(--accent-ink);border-color:var(--accent)}.dr-pill.off{color:var(--warn);border-color:var(--warn)}',
    '.dr-pill .spin{width:10px;height:10px}',
    '.dr-path{font-family:var(--mono);font-size:11px;color:var(--ink-3);overflow-wrap:anywhere}',
    '.dr-cmds{display:grid;grid-template-columns:72px minmax(0,1fr);gap:4px 12px;margin:0;align-items:baseline;font-size:13px}',
    '.dr-cmds dt,.dr-cmds dd{margin:0}.dr-cmds dd{overflow-wrap:anywhere}.dr-cmds code{font-family:var(--mono);font-size:12px}',
    '.dr-line{font-size:11px;color:var(--ink-3)}',
    '.dr-btns{display:flex;gap:8px;flex-wrap:wrap;align-items:center}',
    '.dr-text{display:flex;flex-direction:column;gap:8px;min-width:0}',
    /* the file's path: as it is written (a label is upper case, and a path is not), and wrapped */
    '.dr-text>.label{text-transform:none;overflow-wrap:anywhere}',
    '.dr-text pre{margin:0;max-height:380px;overflow:auto;font-family:var(--mono);font-size:12px;line-height:1.5;padding:10px;background:var(--canvas);border:1px solid var(--hair);white-space:pre-wrap;overflow-wrap:anywhere}',
    '.dr-tell{border:1px solid var(--hair);padding:8px 10px;font-size:12px;color:var(--ink-2);display:flex;flex-direction:column;gap:6px}',
    '@media (max-width:899px){.dr-cmds{grid-template-columns:minmax(0,1fr)}.dr-row .btn,.dr-panel .btn{min-height:44px}}'
  ].join('\n');

  function styleOnce() {
    if (document.getElementById('startdrafts-style')) return;
    var node = document.createElement('style');
    node.id = 'startdrafts-style';
    node.textContent = STYLE;
    document.head.appendChild(node);
  }

  function session() { return (App.data && (App.data.console || App.data.bosun)) || {}; }
  function redraw() { if (K.renderBody) K.renderBody(); }

  /* ---------- the rows: live states from the step, text from the report ---------- */

  function fullRows(report) {
    var out = {};
    Object.keys(report.spaces || {}).forEach(function (name) {
      (report.spaces[name].drafts || []).forEach(function (r) { out[r.aim] = Object.assign({ space: name }, r); });
    });
    return out;
  }
  /* the step's rows where the state has them, each with what the report knows of it */
  function rowsOf(report, step) {
    var full = fullRows(report);
    var live = step.drafts || Object.keys(full).map(function (aim) { return full[aim]; });
    return live.map(function (l) {
      var f = full[l.aim] || {};
      var same = f.state === l.state;
      return Object.assign({}, l, { text: same ? f.text || null : null, commands: same ? f.commands || null : null });
    });
  }
  /* read the report again when the live rows moved: once for each way they stand */
  function follow(report, step) {
    if (!step.drafts) return;
    var full = fullRows(report);
    var sig = step.drafts.map(function (l) { return l.aim + ':' + l.state + ':' + (l.stamp || ''); }).join('|');
    var stale = step.drafts.some(function (l) { return (full[l.aim] || {}).state !== l.state; });
    if (sig !== seen && (seen !== null || stale) && K.loadSetup) K.loadSetup(0);
    seen = sig;
  }

  /* ---------- one row ---------- */

  var PILLS = { idle: 'not started', drafting: 'Bosun is drafting', ready: 'ready for you', adopted: 'adopted' };
  /* An adopted file whose lines do not run (keel/tierrecord.py): changed since it was
     adopted or saved, or never adopted or saved at all (a file from before, or by hand). */
  var UNHELD = {
    changed: ['changed since', 'This file changed since it was adopted or saved, so Shipyard runs none of its lines and will not land this repo\'s cards. Read the file, then press Keep this text.'],
    never: ['not saved yet', 'This file has not been adopted or saved yet, so Shipyard runs none of its lines. Read the file, then press Keep this text to turn them on.']
  };
  /* the user's own Save of the text this row is showing: read first, so it is offered only
     under the open text (review r2.F12) */
  function keepText(r) {
    var at = r.aim.split('/'), body = { verb: 'setup.tier.save', space: r.space || at[0], text: r.text };
    if (at[1]) body.key = at[1];
    var mine = K.isPending && K.isPending(K.pendKey(body));
    return el('button', { class: 'btn primary' + (mine ? ' pending' : ''), disabled: mine ? true : null, onclick: function () {
      K.setupParts.change(body, r.label + ' saved: its lines are on');
    } }, 'Keep this text');
  }
  function unheld(r) { return r.state === 'adopted' ? UNHELD[r.lines] || null : null; }
  function pill(r, up) {
    if (!up && (r.state === 'idle' || r.state === 'drafting'))
      return el('span', { class: 'dr-pill off', 'data-key': 'draft-pill', text: 'Bosun is not running' });
    if (unheld(r)) return el('span', { class: 'dr-pill ready', 'data-key': 'draft-pill', text: unheld(r)[0] });
    return el('span', { class: 'dr-pill ' + r.state, 'data-key': 'draft-pill' },
      r.state === 'drafting' ? el('span', { class: 'spin', 'aria-hidden': 'true' }) : null, PILLS[r.state] || r.state);
  }
  function commands(r) {
    var c = r.commands;
    if (!c) return null;
    function one(label, found, first) {
      return [el('dt', { class: 'label', text: label }),
        el('dd', null, found ? [el('code', { text: found.value }), ' ',
          el('span', { class: 'dr-line', text: '(line ' + found.line + (first ? ' of the file)' : ')') })]
          : el('span', { class: 'dr-line', text: 'not said in the file' }))];
    }
    /* c-734: the lands line is retired; a file that still names one is told it moves nothing */
    return el('dl', { class: 'dr-cmds', 'data-key': 'draft-commands' },
      one('Prepare', c.prepare, true), one('Test', c.test),
      c.lands ? [el('dt', { class: 'label', text: 'Lands on' }),
        el('dd', { 'data-key': 'draft-lands' }, el('code', { text: c.lands.value }), ' ',
          el('span', { class: 'dr-line', text: '(line ' + c.lands.line + ': not read. Shipyard moves nothing for it. A card lands on its own base, ' +
            'else on the branch your repo\'s remote names as its default. Add a base on How work ships.)' }))] : null);
  }
  function adopt(r) {
    return el('button', { class: 'btn primary', onclick: function () {
      K.setupParts.change({ verb: 'setup.tier.adopt', card: r.card }, r.label + ' adopted');
    } }, 'Adopt');
  }
  function tellNote(r) {
    if (!telling[r.aim]) return null;
    var attach = session().attach;
    return el('div', { class: 'dr-tell', 'data-key': 'draft-tell' },
      el('span', { text: 'Tell Bosun in its session what to change. This draft updates when Bosun has changed it. Nothing is written until you press Adopt.' }),
      attach ? K.command(attach) : null);
  }
  function textOf(r) {
    var ready = r.state === 'ready';
    return el('div', { class: 'dr-text', 'data-key': 'draft-text' },
      el('span', { class: 'label', text: (ready ? 'Draft of ' : 'Written to ') + r.path }),
      el('pre', { tabindex: '0', text: r.text || '' }),
      el('div', { class: 'dr-btns' },
        ready ? adopt(r) : null,
        unheld(r) && r.text ? keepText(r) : null,
        ready ? el('button', { class: 'btn', onclick: function () { telling[r.aim] = !telling[r.aim]; redraw(); } }, 'Tell Bosun what to change') : null,
        el('button', { class: 'btn', onclick: function () { delete opened[r.aim]; delete telling[r.aim]; redraw(); } }, 'Close')),
      ready ? tellNote(r) : null);
  }
  function row(r, up) {
    var has = (r.state === 'ready' || r.state === 'adopted') && r.text !== null && r.text !== undefined;
    var open = has && opened[r.aim];
    var key = r.aim.split('/')[1] || null;
    return el('div', { class: 'dr-row', 'data-key': 'draft-row', 'data-aim': r.aim },
      el('div', { class: 'dr-head' }, el('span', { class: 'dr-label', 'data-key': 'draft-label', text: r.label }), pill(r, up)),
      el('div', { class: 'dr-path', text: r.path }),
      unheld(r) ? el('div', { class: 'dr-line', 'data-key': 'draft-lines', text: unheld(r)[1] }) : null,
      has ? commands(r) : null,
      has && !open ? el('div', { class: 'dr-btns' },
        el('button', { class: 'btn', onclick: function () { opened[r.aim] = true; redraw(); } }, r.state === 'ready' ? 'Read the draft' : 'Read the file'),
        r.state === 'ready' ? adopt(r) : null) : null,
      r.state === 'idle' && !r.card && up ? el('div', { class: 'dr-btns' }, el('button', { class: 'btn sm', onclick: function () {
        var body = { verb: 'setup.tier.draft', space: r.space || r.aim.split('/')[0] };
        if (key) body.key = key;
        K.setupParts.change(body, 'a draft is open for Bosun');
      } }, 'Open a draft for Bosun')) : null,
      open ? textOf(r) : null);
  }

  /* ---------- the three parts ---------- */

  var FORM = { full: 'Full builder: Bosun can also run the prepare and test commands in a copy to prove they work.',
    guide: 'Guide builder: Bosun explains and asks. Where a command has to run, it gives it to you.' };
  function handOver(report) {
    var attach = session().attach, form = ((report.start || {}).bosun || {}).form;
    return el('div', { class: 'dr-panel flag', 'data-key': 'drafts-hand' },
      el('h3', { text: '1. Hand over to Bosun' }),
      el('p', { text: 'Open Bosun\'s session and tell it to start. In a terminal, run this:' }),
      attach ? K.command(attach) : null,
      el('p', { text: 'Or open Bosun in the Claude app. If you want a first thing to say, say this:' }),
      K.command('Set up my repos.'),
      FORM[form] ? el('p', { class: 'dr-line', text: FORM[form] }) : null);
  }
  function willAsk() {
    return el('div', { class: 'dr-panel', 'data-key': 'drafts-ask' },
      el('h3', { text: '2. What Bosun will ask about' }),
      el('p', { text: 'This is a conversation, not a form. So you know what is coming:' }),
      el('ul', null,
        el('li', { text: 'How to prepare a fresh copy of the repo (the install step), and how to run the tests.' }),
        el('li', { text: 'Whether sessions may run the app, and how to run it without touching your own running copy. Until this is written, sessions run tests only.' }),
        el('li', { text: 'Conventions it could not infer from the code.' })));
  }
  function notRunning() {
    return K.check({ key: 'drafts-bosun', state: 'needs', name: 'Bosun is running', ask: false,
      what: 'Bosun is not running, so nothing is being drafted. Bosun reads your repos and drafts these files with you in its session.',
      fix: K.bosunStart ? K.bosunStart('Start Bosun') : null, how: 'This row turns green when Bosun is running.' });
  }
  function skipPanel(step) {
    return el('div', { class: 'dr-panel', 'data-key': 'drafts-skip' },
      el('p', null, el('strong', { text: 'Skip for now: ' }), 'Sessions will work in these repos with no guidance and will run tests only if they can find them.'),
      el('div', { class: 'dr-btns' },
        step.skipped || step.done ? null : el('button', { class: 'btn', onclick: function () {
          K.setupParts.change({ verb: 'firstrun.skip', step: step.id });
        } }, 'Skip for now'),
        el('span', { class: 'dr-line', text: 'Next turns on when every repo\'s CLAUDE.md is adopted.' })));
  }

  K.draftsScreen = function (report, step) {
    styleOnce();
    follow(report, step);
    var up = !!session().up, rows = rowsOf(report, step);
    return [
      up ? null : notRunning(),
      handOver(report), willAsk(),
      el('div', { class: 'dr-back', 'data-key': 'drafts-back' },
        el('h3', { text: '3. What came back' }),
        el('div', { class: 'start-about', text: 'This list updates while Bosun works. Read each draft, then Adopt it. Adopt writes the file.' }),
        rows.length ? rows.map(function (r) { return row(r, up); })
          : el('div', { class: 'empty', text: 'No repo is added yet. Add one on Add your repos, and its CLAUDE.md is listed here.' })),
      skipPanel(step)];
  };
})(window.Keel);
