/* The first-run stepper (c-632): the `start` route, `&step=<id>` naming its screen, one step per screen.
 *
 * The steps and whether each is done come from the state (`firstrun` on `/api/state`,
 * keel/firstrun.py), never from a guess here: done is read from readiness each time, and
 * only a skip and Finish are stored. What a screen draws beyond that (the prerequisites'
 * fixes, the login, the phone's command, a pack step's text) is on `/api/setup`, and the
 * forms and rows are Setup's own (`K.setupParts`, app/ui.setup.js), so Setup and Start
 * never draw one thing two ways. The How work ships and voice choices
 * are S5's settings form (`K.settingsForm`, app/ui.settings.js), so a setting has one writer.
 * A screen may be its own file, loaded before this one and read here (`own`): Check this
 * computer (ui.startchecks.js), the sign-in (ui.signin.js), Choose your builder and
 * Meet Bosun (ui.startbosun.js), Add your repos (ui.startrepos.js), How Keel remembers
 * (ui.startmemory.js), Set up your repos with Bosun (ui.startdrafts.js), Where finished
 * work goes (ui.startlands.js), How work ships (ui.startships.js), A browser for sessions
 * (ui.startbrowser.js), Back up (ui.startbackup.js), Your first card (ui.startcard.js) and
 * You are set up (ui.startdone.js).
 *
 * - The steps are in the approved order (c-677, keel/firstrun.py `STEPS`), and a step's
 *   screen is its entry in `K.startPanels`: a step that is added is an entry there, an entry
 *   in `STEPS` and one in `STATE`. Only a pack's own step (`<pack>:<id>`) has none.
 * - One screen: the step's headline (its title where it has none) and what it is for, its
 *   done or skipped mark, why, its panel, then Back, Skip, Next and Finish. Next is the step's own state: on once it is
 *   done, skipped, or has nothing to check. The exception is an install whose first run is
 *   finished: there Next is off only on a required step that is not done, as before c-677,
 *   and no hint is drawn. Finish is on once the required steps are. On the desk the steps
 *   are listed on the left, each with its place, its state (done, here, skipped, or not
 *   checked for a step that is done and not confirmed, `sure: false`) and whether it is
 *   required or optional; on the phone a strip with the counter and one mark per step,
 *   with the list under Steps.
 * - From Meet Bosun on (`step.bosun`) the screen is headed by the line to Bosun's session
 *   (`K.bosunLine`). A requirement that needs you ends with it on every step (`K.stuck`,
 *   app/ui.stuck.js). Neither is drawn while that session cannot run.
 * - It resumes at `?step=`, else at the first step neither done nor skipped (one with nothing
 *   to check counts until it is seen, c-734), and keeps that step through an action; an install
 *   nobody has acted on yet (`firstrun.untouched`) opens on the first step.
 * - A deck loaded with no `?view=` opens here while `firstrun.redirect` is true (until
 *   Finish, and whenever the prerequisites stop being met), replacing the history entry so
 *   Back does not loop. It took this over from Setup's once-per-tab `openOnFresh`.
 * - `K.openStep(id, space)` is the one way to a step: the needs panels (c-631) call it
 *   through `K.stepHref`'s link. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el, App = K.App;
  /* the boot's own address named a route: the redirect never overrides one he asked for */
  var asked = (function () {
    var q = new URLSearchParams(location.search);
    return !!(q.get('view') || q.get('card') || /^\/board/.test(location.pathname || ''));
  })();
  var redirected = false;

  var STYLE = [
    /* wide enough for a step's own state word beside its title ("last run failed", c-757 r1.F3) */
    '.start{display:grid;grid-template-columns:252px minmax(0,1fr);gap:16px;align-items:start}',
    '.start-steps{display:flex;flex-direction:column;gap:2px;padding:8px}',
    '.start-step{display:flex;align-items:center;gap:8px;padding:8px;color:var(--ink-2);text-align:left;width:100%;background:none;border:0;border-bottom:1px solid var(--hair);cursor:pointer;font-size:13px;min-height:44px}',
    '.start-num{font-family:var(--mono);font-size:11px;color:var(--ink-3);flex:0 0 20px}',
    '.start-name{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px}',
    '.start-kind{font-size:11px;color:var(--ink-3)}',
    '.start-state{font-family:var(--mono);font-size:11px;color:var(--ink-3);flex:0 0 auto}',
    '.start-state.done{color:var(--good)}.start-step.on .start-state{color:var(--ink)}',
    '.start-hint{font-size:12px;color:var(--ink-2)}',
    '.start-strip{display:flex;gap:4px}',
    '.start-seg{flex:1;height:4px;background:var(--s3)}',
    '.start-seg.done{background:var(--good)}.start-seg.here{background:var(--accent)}',
    '.start-phone summary .start-now{flex:1;min-width:0;font-family:var(--sans);font-size:13px;font-weight:600;text-transform:none;letter-spacing:0;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.start-step:hover{background:var(--s2);color:var(--ink)}',
    '.start-step.on{background:var(--s2);color:var(--ink);font-weight:600;box-shadow:inset 2px 0 0 var(--accent)}',
    '.start-mark{font-family:var(--mono);font-size:11px;width:16px;flex:0 0 16px;text-align:center}',
    '.start-mark.done{color:var(--good)}.start-mark.skipped{color:var(--ink-3)}.start-mark.need{color:var(--warn)}',
    '.start-screen .panel-body{display:flex;flex-direction:column;gap:12px}',
    '.start-title{font-size:18px;font-weight:600;margin:0}',
    '.start-about{color:var(--ink-2);font-size:13px;line-height:1.5}',
    /* a step's sentence may carry a path (the backup's folder), which wraps at phone width */
    '.start-why{font-size:13px;line-height:1.5;padding:8px 10px;border-left:3px solid var(--warn);background:var(--warn-soft);overflow-wrap:anywhere;min-width:0}',
    '.start-why.done{border-left-color:var(--good);background:var(--good-soft)}',
    '.start-why.skipped{border-left-color:var(--hair-hi);background:var(--s2)}',
    '.start-note{font-size:13px;line-height:1.5;padding:10px 12px;border:1px solid var(--accent);background:var(--accent-soft)}',
    '.start-buttons{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:var(--pad);border-top:1px solid var(--hair)}',
    '.start-buttons .spacer{flex:1}',
    '.start-phone{display:flex;flex-direction:column;gap:8px;margin-bottom:12px}',
    '.start-phone summary{font-family:var(--mono);font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-2);cursor:pointer;min-height:44px;display:flex;align-items:center;gap:12px}',
    '.start-check{display:grid;grid-template-columns:16px minmax(0,1fr);gap:2px 8px;font-size:13px;padding:6px 0;border-top:1px solid var(--hair)}',
    '.start-check:first-child{border-top:0}',
    '.start-check .fix,.start-check .said{grid-column:2;font-size:12px;color:var(--ink-2);overflow-wrap:anywhere}',
    '.start-cmd{font-family:var(--mono);font-size:12px;padding:8px 10px;background:var(--canvas);border:1px solid var(--hair);overflow-wrap:anywhere;user-select:all}',
    '.start-sub{display:flex;flex-direction:column;gap:8px;padding-top:4px}',
    '.start-sub + .start-sub{border-top:1px solid var(--hair);padding-top:12px}',
    '.start-chips{display:flex;gap:6px;flex-wrap:wrap}',
    '.start-chips .btn.on{background:var(--accent-soft);border-color:var(--accent);color:var(--accent-ink)}',
    '.start-text p{margin:0 0 8px;font-size:13px;line-height:1.55}',
    '.start-text code,.start-note code,.start-about code{font-family:var(--mono);font-size:12px}',
    '.start-field{display:flex;flex-direction:column;gap:4px;max-width:420px}',
    '.start-more{border:1px solid var(--hair);background:var(--s1);padding:0 12px;font-size:13px;line-height:1.5}',
    '.start-more summary{cursor:pointer;min-height:44px;display:flex;align-items:center;color:var(--accent-ink)}',
    '.start-more p{margin:0 0 12px}',
    /* one visible choice (c-729, `K.startChoice`): each option a control of its own, the chosen one marked */
    '.start-choice{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px}',
    '.start-opt{display:flex;flex-direction:column;align-items:flex-start;gap:4px;text-align:left;border:1px solid var(--hair-hi);background:var(--s1);color:var(--ink);padding:10px 12px;cursor:pointer;font:inherit;font-size:13px;line-height:1.45;min-height:44px;min-width:0}',
    '.start-opt:hover{border-color:var(--ink-3)}',
    '.start-opt.on{border-color:var(--accent);background:var(--accent-soft);box-shadow:inset 3px 0 0 var(--accent)}',
    '.start-opt-head{display:flex;align-items:flex-start;gap:8px;width:100%;font-weight:600;min-width:0}',
    '.start-opt-title{flex:1 1 auto;min-width:0;overflow-wrap:anywhere}',
    '.start-opt-tag,.start-opt-dot{flex:0 0 auto}.start-opt-dot{margin-top:2px}',
    '.start-opt-dot{width:14px;height:14px;flex:0 0 14px;border-radius:50%;border:2px solid var(--ink-3)}',
    '.start-opt.on .start-opt-dot{border-color:var(--accent);background:radial-gradient(var(--accent) 0 3px,transparent 4px)}',
    '.start-opt-tag{margin-left:auto;font-family:var(--mono);font-size:10px;font-weight:400;color:var(--accent-ink);border:1px solid var(--accent);border-radius:var(--pill);padding:1px 8px;white-space:nowrap}',
    '.start-opt-tag.quiet{color:var(--ink-3);border-color:var(--hair-hi)}',
    '.start-opt-said{color:var(--ink-2);font-size:12px;overflow-wrap:anywhere}',
    '.start-opt-needs{color:var(--ink-3);font-size:12px;font-family:var(--mono)}',
    '@media (max-width:899px){.start{display:block}',
    '.start-buttons .btn,.start-sub .btn{min-height:44px}.start-buttons .spacer{display:none}',
    '.start-buttons .btn{flex:1 1 40%}}'
  ].join('\n');

  function styleOnce() {
    if (document.getElementById('start-style')) return;
    var node = document.createElement('style');
    node.id = 'start-style';
    node.textContent = STYLE;
    document.head.appendChild(node);
  }

  /* ONE VISIBLE CHOICE (c-729): a radio group whose every option is a control of its own,
     the chosen one marked "selected" (or `tag`), so switching back is as plain as switching
     away. `o.options`: [{id, title, said, needs, note, tag, badge}]; `needs` is an unchosen option's
     requirements as one quiet line, never a "needs you" block; `note` (c-758) is one quiet line
     of what is there now, chosen or not; `badge` is said on an
     unchosen option (what is in use while another is open). `o.pick(id)` is the tap. */
  function startChoice(o) {
    styleOnce();
    return el('div', { class: 'start-choice', role: 'radiogroup', 'aria-label': o.label, 'data-key': o.key },
      o.options.map(function (opt) {
        var on = opt.id === o.chosen;
        return el('button', { class: 'start-opt' + (on ? ' on' : ''), role: 'radio', 'aria-checked': on ? 'true' : 'false',
          'data-key': o.key + '-' + opt.id, onclick: function () { if (!on) o.pick(opt.id); } },
          el('span', { class: 'start-opt-head' }, el('span', { class: 'start-opt-dot', 'aria-hidden': 'true' }),
            el('span', { class: 'start-opt-title', text: opt.title }), on ? el('span', { class: 'start-opt-tag', text: opt.tag || 'selected' })
              : opt.badge ? el('span', { class: 'start-opt-tag quiet', text: opt.badge }) : null),
          opt.said ? el('span', { class: 'start-opt-said', text: opt.said }) : null,
          opt.note ? el('span', { class: 'start-opt-needs', text: opt.note }) : null,
          !on && opt.needs ? el('span', { class: 'start-opt-needs', text: 'needs: ' + opt.needs }) : null);
      }));
  }
  K.startChoice = startChoice;

  /* ---------- the steps, from the state ---------- */

  function firstrun() { return (App.data && App.data.firstrun) || null; }
  function steps() { return (firstrun() || {}).steps || []; }
  function counted() { return steps().filter(function (s) { return s.done !== null; }); }
  /* a step to resume at (c-734): not done and not skipped, a step with nothing to check
     included until the user has been through it (it then reads done, `firstrun.seen`), so a
     resume never passes a step the user has not seen */
  function open(s) { return s.done !== true && !s.skipped; }
  /* `?step=`; else, on an install nobody has acted on yet (`firstrun.untouched`), the first
     step, which reads done there (builder mode ships on) and would be passed unseen; else
     the first step neither done nor skipped, else the last */
  function current() {
    var list = steps();
    if (!list.length) return null;
    var asked = list.filter(function (s) { return s.id === App.step; })[0];
    return asked || (firstrun().untouched ? list[0] : null) || list.filter(open)[0] || list[list.length - 1];
  }
  /* the step on screen now, by id (the hello watch stops once it is not Meet Bosun, r2.F1) */
  K.startStep = function () { var c = current(); return c ? c.id : null; };
  function requiredDone() { return steps().every(function (s) { return !s.required || s.done; }); }
  function readyRow(cap, space) { return K.readyRow ? K.readyRow(cap, space) : null; }

  function openStep(id, space) {
    if (space && space !== App.space && K.spaceNames().indexOf(space) >= 0) K.setSpace(space);
    App.step = id || null;
    K.go('start');
  }
  K.openStep = openStep;
  /* the step on screen, kept by the page (c-734); the address is left as it is, so a deck
     opened with no `?step=` still resumes afresh */
  function pin(id) { App.step = id; }
  /* On to the next step (Next, Keep this). A step with nothing to check (`done` null) is
     recorded as seen on the way (`firstrun.seen`, c-729), so the list shows it done once the
     user has been through it; quietly, since going on is the whole of what was asked. */
  function goPast(step, next) {
    if (step.done === null && !step.skipped && step.id.indexOf(':') < 0) {
      K.act({ verb: 'firstrun.seen', step: step.id }, function () { return ''; });
    }
    openStep(next.id);
  }

  /* A deck loaded on no route of its own opens here while the stepper says so: once, on the
     first state, and replacing the entry so Back does not come straight back. */
  K.stateLanded = function () {
    if (redirected || !App.data) return;
    redirected = true;
    var f = firstrun();
    if (asked || !f || !f.redirect || App.view === 'start') return;
    App.step = null;
    K.go('start', null, true);
  };

  /* ---------- small pieces ---------- */

  /* A step's state in a word, as the list and the strip say it: the one on screen is here,
     else done or skipped, else nothing (it is open, or has nothing to check). */
  function unsure(s) { return !!s.done && s.sure === false; }
  /* a step that is done and not confirmed says why in a word of its own where it has one
     (`word`: Back up's "copy pending", c-757), else "not checked" */
  function stateOf(s, here) {
    return s.id === here.id ? 'here' : unsure(s) ? s.word || 'not checked' : s.done ? 'done' : s.skipped ? 'skipped' : '';
  }
  /* the strip's mark: the state's colour, and none for a step that is not confirmed */
  function segOf(s, here) { var w = stateOf(s, here); return unsure(s) && w !== 'here' ? '' : w; }
  /* "N of M": the step's place, counted from 0 as the list numbers them */
  function countWords(list, here) { return list.indexOf(here) + ' of ' + (list.length - 1); }
  function stepButtons(list, here) {
    return list.map(function (s, i) {
      var state = stateOf(s, here);
      return el('button', { class: 'start-step' + (s.id === here.id ? ' on' : ''), 'data-key': 'go-' + s.id,
        'aria-current': s.id === here.id ? 'step' : null, onclick: function () { openStep(s.id); } },
        el('span', { class: 'start-num', text: String(i) }),
        el('span', { class: 'start-name' }, el('span', { text: s.title }),
          el('span', { class: 'start-kind', text: s.required ? 'required' : s.optional ? 'optional' : '' })),
        el('span', { class: 'start-state' + (state === 'done' ? ' done' : ''), text: state }));
    });
  }
  function deskList(list, here) {
    return el('section', { class: 'panel', 'data-key': 'start-list' },
      el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'Setup steps' }), el('span', { class: 'spacer' }),
        el('span', { class: 'mono t11 ink3', 'data-key': 'start-count', text: countWords(list, here) })),
      el('div', { class: 'start-steps' }, stepButtons(list, here)));
  }
  function phoneTop(list, here) {
    return el('div', { class: 'start-phone', 'data-key': 'start-phone' },
      el('details', { class: 'panel', 'data-key': 'start-sheet' },
        el('summary', { class: 'panel-head' }, el('span', { 'data-key': 'start-count', text: countWords(list, here) }),
          el('span', { class: 'start-now', text: here.title }), el('span', { text: 'Steps' })),
        el('div', { class: 'start-steps' }, stepButtons(list, here))),
      el('div', { class: 'start-strip', role: 'img', 'aria-label': 'step ' + countWords(list, here) },
        list.map(function (s) { return el('span', { class: 'start-seg ' + segOf(s, here), 'data-key': 'seg-' + s.id }); })));
  }
  function progressWords() {
    var list = counted();
    /* a step that is done and not confirmed (`sure: false`) is not counted as done */
    return list.filter(function (s) { return s.done && !unsure(s); }).length + ' of ' + list.length + ' done';
  }
  var words = K.words, sentence = K.asSentence;
  /* a numbered line starts a paragraph of its own (c-758): a connection's four checks read
     as four lines, not one run-on sentence */
  function paragraphs(text) {
    return el('div', { class: 'start-text' }, String(text || '').split(/\n\s*\n|\n(?=\s*\d+\.\s)/).map(function (p, i) {
      return p.trim() ? el('p', { 'data-key': 'p' + i }, words(p.replace(/\s*\n\s*/g, ' ').trim())) : null;
    }));
  }
  function sub(key, title, body) {
    return el('div', { class: 'start-sub', 'data-key': key }, title ? el('div', { class: 'label', text: title }) : null, body);
  }
  /* A requirement that needs you: the stuck line (app/ui.stuck.js). Its third part, Bosun's
     session, is drawn on every step, the ones before Meet Bosun too, while that session can
     run (`K.bosunSession`: the builder, login and prerequisites rows all ready; a login
     that could not be checked is ready, an expired or missing one is not). */
  function stuck(o) { return K.stuck(o); }
  /* One check: a quiet row when it passes, the stuck line when it does not (`quiet`: its
     form for a check that does not block). */
  function checkRow(key, ok, name, said, fix, quiet) {
    if (!ok) return stuck({ key: key, name: name, what: said, fix: fix, quiet: quiet });
    return el('div', { class: 'start-check', 'data-key': key },
      el('span', { class: 'start-mark done', text: '✓' }), el('span', { text: name }), el('span', { class: 'said', text: said }));
  }
  /* The readiness rows `pairs` ([cap, label]) of a space, or of the install: a ready row is
     a quiet line; the rows that fail for ONE reason are one stuck line naming them all, so
     a space with no pack says so once and not once per capability. A row a pack's failing
     check holds up brings that check's own fix (`needs`, keel/readiness.py; `K.fixOf`, c-688). */
  function rowLines(space, pairs) {
    var out = [], groups = {};
    pairs.forEach(function (pair) {
      var r = readyRow(pair[0], space);
      if (!r) return;
      if (r.ready) { out.push(checkRow('row-' + (space || 'install') + '-' + pair[0], true, pair[1], r.why)); return; }
      if (!groups[r.why]) out.push(groups[r.why] = { caps: [], labels: [], why: r.why, needs: r.needs });
      groups[r.why].caps.push(pair[0]); groups[r.why].labels.push(pair[1]);
    });
    return out.map(function (g) {
      return g.caps ? stuck({ key: 'row-' + (space || 'install') + '-' + g.caps.join('-'), name: g.labels.join(', '), what: g.why, fix: K.fixOf(g.needs) }) : g;
    });
  }
  function rowLine(cap, space, label) { return rowLines(space, [[cap, label]]); }
  function spacesOf(report) {
    /* the asked space first, so a needs panel's Set it up lands on its own space */
    var names = Object.keys((report && report.spaces) || {});
    return names.sort(function (a, b) { return (a === App.space ? -1 : 0) - (b === App.space ? -1 : 0); });
  }

  /* a screen that is its own file (app/views.json loads it before this one), or the line
     that says the file is missing */
  function own(draw, file, report, step) {
    var list = steps(), next = list[list.indexOf(step) + 1];
    /* `next`: the way on, for a screen whose own button goes there (Keep this) */
    return draw ? draw(report, step, { checkRow: checkRow, sub: sub, rowLine: rowLine, rowLines: rowLines,
      next: next ? function () { goPast(step, next); } : null,
      /* what the last screens read of the whole run: the steps, the way to one, whether
         Finish would go through, and whether each space shows its plans (How work ships) */
      steps: steps, open: openStep, canFinish: requiredDone, finished: function () { return !!firstrun().finished; },
      plans: function () { return (list.filter(function (s) { return s.id === 'defaults'; })[0] || {}).plans || {}; } })
      : el('div', { class: 'empty crit', text: 'This step\'s screen is not loaded (' + file + ').' });
  }

  /* ---------- each step's panel ---------- */

  /* Choose your builder (c-678): the two forms as option cards, neither preselected
     (app/ui.startbosun.js). Until then it was the two builder settings in a form. */
  function chooseBuilder(report, step) { return own(K.builderChoice, 'ui.startbosun.js', report, step); }

  /* Check this computer: its screen is its own file (app/ui.startchecks.js, loaded before
     this one), drawn with this file's row and section helpers. */
  function prerequisites(report, step) { return own(K.checkScreen, 'ui.startchecks.js', report, step); }

  /* Sign in to Claude: the guided sign-in (c-678, app/ui.signin.js), the same block the
     sign-in banner and the Logins list draw. Its state is readiness's `login` row, the one
     the step's own state is read from, so the list and the screen cannot disagree: ready is
     signed in, ready and not confirmed (`sure: false`) is a probe that could not tell, and
     anything else waits for the sign-in. `step.stamp` is when the sign-in file in the
     install's Claude folder last changed, read on every state: the block asks for the one
     probe when a sign-in appears. */
  function loginStep(report, step) {
    var lg = (report.start || {}).login || {}, row = readyRow('login');
    if (!K.signIn) return el('div', { class: 'empty crit', text: 'The sign-in screen is not loaded (ui.signin.js).' });
    if (!row) return el('div', { class: 'empty', text: 'reading the sign-in...' });
    var state = row.ready ? (row.sure === false ? 'unknown' : 'good') : null;
    return [
      K.signIn.block({ key: 'install', command: lg.command, watch: true,
        login: { state: state, why: state === 'unknown' ? lg.why : '', stamp: step.stamp || null } }),
      el('details', { class: 'start-more', 'data-key': 'signin-problems' },
        el('summary', { text: 'Common problems' }),
        el('p', null, el('strong', { text: 'The terminal says command not found: claude. ' }), 'Go Back to Check this computer.'),
        el('p', null, el('strong', { text: 'I signed in but this page still waits. ' }), 'Press Check again.')),
      el('div', { class: 'start-about', 'data-key': 'signin-next', text: 'Next you meet your builder. It needs this sign-in to run.' })];
  }

  /* Add your repos (c-678): the space named once, a panel per repo, Add another repo always
     there, and a failed copy sorted into its kind (app/ui.startrepos.js). Until then it was
     an Add space form and Setup's Clone and Attach forms per space. */
  function repos(report, step) { return own(K.reposScreen, 'ui.startrepos.js', report, step); }
  /* How Keel remembers (c-678): the read-only picture of the four layers (app/ui.startmemory.js). */
  function memory(report, step) { return own(K.memoryScreen, 'ui.startmemory.js', report, step); }

  /* Set up your repos with Bosun (c-678): the hand-over, what Bosun will ask, and what came
     back to read and Adopt (app/ui.startdrafts.js). Until then it was the space tier in a
     box with Propose; those are Setup's still. A pack's own rules are named under it, since
     its sessions already read them (decision `pack-rules`: list). */
  function rules(report, step) {
    var packRules = (report.packs || []).filter(function (p) { return (p.spaces || []).length && (p.rules || []).length; });
    return [own(K.draftsScreen, 'ui.startdrafts.js', report, step),
      packRules.map(function (p) {
        return el('div', { class: 'start-about', 'data-key': 'pack-rules-' + p.name },
          'The ' + p.name + ' pack\'s rules are already read by its sessions, so nothing is copied: ',
          p.rules.map(function (r, i) { return [i ? ', ' : '', el('code', { text: r })]; }), '.');
      })];
  }

  /* Where finished work goes (c-678): per space, a connection to its code host or the merge
     on this computer with a Push (app/ui.startlands.js). Until then it was the capability
     rows of every space and the pack list. */
  function integrations(report, step) { return own(K.landsScreen, 'ui.startlands.js', report, step); }

  /* A connection's own step (c-632): its text, then its checks. Where the step follows Where
     finished work goes (`step.after`, the default, c-758 r1.F5), that step has just shown each
     check with its fix, so they are not drawn a second time: ONE line says how many pass and
     names the ones that do not, and See the checks goes back to them, by the step's name. A
     step that follows any other core step draws its checks with their fixes, as before: the
     user has not seen them yet, or not on the screen before this one. */
  function packStep(report, step) {
    var own = ((report.start || {}).pack_steps || {})[step.id];
    if (!own) return el('div', { class: 'empty', text: 'reading the step...' });
    var pack = (report.packs || []).filter(function (p) { return p.name === own.pack; })[0] || { checks: [] };
    var named = pack.checks.filter(function (c) { return own.requires.indexOf(c.name) >= 0; });
    var again = el('button', { class: 'btn', onclick: function () { K.setupParts.again(); } }, 'Look again');
    if (step.after !== 'integrations') return [paragraphs(own.text),
      named.length ? sub('named', 'Checks', named.map(function (c) {
        return checkRow('named-' + c.name, c.ok, c.name, c.ok ? c.why : K.setupParts.notSetUp(c), K.fixOf(c));
      })) : null,
      el('div', { class: 'start-chips' }, again)];
    var failing = named.filter(function (c) { return !c.ok; }).map(function (c) { return c.name; });
    var n = named.length, said = !failing.length
      ? (n === 1 ? 'Its one check passes.' : 'All ' + n + ' of its checks pass.') + ' They are on Where finished work goes.'
      : failing.length + ' of ' + n + (n === 1 ? ' check' : ' checks') + ' still ' + (failing.length === 1 ? 'needs' : 'need') + ' you: ' + failing.join(', ') +
        '. Each one is on Where finished work goes, with its fix.';
    return [paragraphs(own.text),
      n ? el('div', { class: 'start-why' + (failing.length ? '' : ' done'), 'data-key': 'named-summary', text: said }) : null,
      el('div', { class: 'start-chips' },
        n ? el('button', { class: 'btn', 'data-key': 'named-back', onclick: function () { openStep('integrations'); } }, 'See the checks') : null, again)];
  }

  /* How work ships (c-678): the path a finished card takes, Bosun's draft beside it to
     Adopt, and the plan question (app/ui.startships.js). Until then it was four settings
     in a form and a line pointing at the Flow panel in Settings. */
  function defaults(report, step) { return own(K.shipsScreen, 'ui.startships.js', report, step); }

  /* A browser for sessions (c-678): Node, and the one download with its progress
     (app/ui.startbrowser.js). */
  function browserStep(report, step) { return own(K.browserScreen, 'ui.startbrowser.js', report, step); }

  /* Back up (c-678): the folder and Turn on backup, then its checks and the passphrase,
     shown once (app/ui.startbackup.js). */
  function backupStep(report, step) { return own(K.backupScreen, 'ui.startbackup.js', report, step); }

  /* Meet Bosun (c-678): the form chosen, the three checks, how to open Bosun's session and
     the hello check (app/ui.startbosun.js). */
  function builderStep(report, step) { return own(K.meetBosun, 'ui.startbosun.js', report, step); }

  /* Your first card (c-678): the form, the card Bosun suggested, and the card's path past
     review to landed (app/ui.startcard.js). */
  function firstCard(report, step) { return own(K.firstCardScreen, 'ui.startcard.js', report, step); }

  /* You are set up (c-678): where to go when something does not work, what was set, what
     was skipped, and the phone and voice under More to set up later (app/ui.startdone.js). */
  function setUp(report, step) { return own(K.setUpScreen, 'ui.startdone.js', report, step); }

  /* A step's screen, by its id (keel/firstrun.py `STEPS`): `function (report, step)`. A
     step that is added puts its entry here, from this file or its own. A step with none is
     a pack's (`<pack>:<id>`), drawn from its text and its checks. */
  K.startPanels = {
    'choose-builder': chooseBuilder, prerequisites: prerequisites, login: loginStep, builder: builderStep,
    repos: repos, memory: memory, rules: rules, integrations: integrations, defaults: defaults, browser: browserStep, backup: backupStep,
    'first-card': firstCard, 'set-up': setUp
  };
  /* a core step always has its screen; one that lost it says so, since the pack screen
     would read "reading the step..." for good */
  function panelOf(step, report) {
    var panel = K.startPanels[step.id] || (step.id.indexOf(':') >= 0 ? packStep : null);
    return panel ? panel(report, step)
      : el('div', { class: 'empty crit', text: 'The step ' + step.id + ' has no screen in this deck (K.startPanels).' });
  }

  /* ---------- the screen ---------- */

  function act(body, word) { return K.setupParts.change(body, word); }

  function buttons(step, list) {
    var at = list.indexOf(step), next = list[at + 1], back = list[at - 1];
    var canFinish = requiredDone(), last = !next;
    /* Next is the step's own state: done, skipped, or nothing to check (`done` is null).
       An install whose first run is finished keeps the Next it had before c-677, off only
       on a required step that is not done, and is told nothing about finishing or skipping. */
    var finished = !!firstrun().finished;
    var go = finished ? !(step.required && !step.done) : step.done !== false || !!step.skipped;
    /* a step with no Skip that is not required (`skip: false`, Choose your builder) */
    var noSkip = step.required || step.skip === false;
    var hint = step.id === 'choose-builder' ? 'Pick a builder to continue.'
      : noSkip ? 'Finish this step to go on.' : 'Finish this step to go on, or Skip.';
    return el('div', { class: 'start-buttons', 'data-key': 'start-buttons' },
      back ? el('button', { class: 'btn', onclick: function () { openStep(back.id); } }, 'Back') : null,
      noSkip ? null : step.skipped
        ? el('button', { class: 'btn', onclick: function () { act({ verb: 'firstrun.unskip', step: step.id }); } }, 'Unskip')
        : step.done ? null : el('button', { class: 'btn', onclick: function () {
          act({ verb: 'firstrun.skip', step: step.id }).then(function (r) { if (r && next) openStep(next.id); });
        } }, 'Skip'),
      next && !go && !finished ? el('span', { class: 'start-hint', 'data-key': 'start-hint', text: hint }) : null,
      el('span', { class: 'spacer' }),
      /* the first screen's way on reads Continue, as the design writes it */
      next ? el('button', { class: 'btn' + (go ? ' primary' : ''), disabled: go ? null : true,
        onclick: function () { goPast(step, next); } }, at === 0 ? 'Continue' : 'Next') : null,
      firstrun().finished ? el('button', { class: 'btn sm', title: 'Open the deck on Start again until you finish',
        onclick: function () { act({ verb: 'firstrun.reopen' }); } }, 'Finished · reopen')
        : el('button', { class: 'btn' + (last && canFinish ? ' primary' : ''), disabled: canFinish ? null : true,
          title: canFinish ? null : 'Finish waits for the required steps',
          onclick: function () { act({ verb: 'firstrun.finish' }).then(function (r) { if (r) K.go('now'); }); } }, 'Finish'));
  }

  function screen(step, list, report) {
    var at = list.indexOf(step);
    /* done and not confirmed (`sure: false`): its sentence alone, with no Done and no done colour */
    var mark = unsure(step) ? 'skipped' : step.done ? 'done' : step.skipped || step.done === null ? 'skipped' : '';
    var said = unsure(step) ? sentence(step.why) : step.done ? 'Done: ' + step.why
      : step.skipped ? 'Skipped. ' + sentence(step.why) + ' The page that needs it says so, and this step stays here.'
        : sentence(step.why);
    return el('section', { class: 'panel start-screen', 'data-key': 'screen-' + step.id },
      el('div', { class: 'panel-head' },
        el('span', { class: 'label', text: 'Step ' + at }),
        step.required ? el('span', { class: 'badge need', text: 'required' }) : null,
        step.optional ? el('span', { class: 'badge', text: 'optional' }) : null),
      el('div', { class: 'panel-body' },
        el('h2', { class: 'start-title', text: step.headline || step.title }),
        el('div', { class: 'start-about', text: step.about }),
        el('div', { class: 'start-why' + (mark ? ' ' + mark : ''), role: 'status', 'data-key': 'why', text: said }),
        report ? panelOf(step, report) : el('div', { class: 'empty', text: K.setupParts.failed() ? 'Setup could not be read: ' + K.setupParts.failed() : 'reading the setup...' })),
      buttons(step, list));
  }

  function viewStart() {
    styleOnce();
    if (K.setupParts) K.setupParts.want();
    var f = firstrun();
    if (!f) return el('div', { class: 'empty', text: 'This deck\'s server has no first run yet.' });
    if (!f.install) return el('div', { class: 'empty', 'data-key': 'not-install',
      text: 'This deck reads a config that is not an install\'s: the first run sets up an install made by shipyard init.' });
    var list = steps(), step = current();
    if (!step) return el('div', { class: 'empty', text: 'no steps' });
    /* c-734: the step resumed at is pinned, so the state after an action on it (Adopt marking
       it done) keeps the page there instead of resuming again further on */
    if (!App.step) pin(step.id);
    var report = K.setupParts ? K.setupParts.report() : null;
    return [step.bosun ? K.bosunLine() : null,
      el('div', { class: 'start', 'data-key': 'start' },
        K.isDesk() ? deskList(list, step) : phoneTop(list, step),
        screen(step, list, report))];
  }
  K.viewStart = viewStart;

  /* More lists Start always: on the phone it is the way back to it after Finish. */
  var baseMore = K.viewMore;
  K.viewMore = function () {
    var out = baseMore ? baseMore() : [];
    if (!Array.isArray(out)) out = [out];
    var f = firstrun();
    if (!f || !f.install) return out;
    out.splice(1, 0, el('section', { class: 'panel', 'data-key': 'start-entry' },
      el('div', { class: 'panel-body' },
        el('button', { class: 'row', onclick: function () { openStep(null); } },
          el('div', { class: 'row-head' }, el('span', { class: 't', text: 'Start' }),
            el('span', { class: 'spacer' }),
            el('span', { class: 'mono t11 ink3', text: f.finished ? 'the first run, ' + progressWords() : progressWords() }))))));
    return out;
  };
})(window.Keel);
