/* Where finished work goes, the first run's step 7 (c-678), loaded before `ui.start.js`,
 * which reads it as `K.landsScreen(report, step, parts)`.
 *
 * FOUR CHOICES per space, each saying what happens next (c-758; three until then, c-729), as
 * one radio group (`K.startChoice`). The first teammate to set Shipyard up could not tell
 * what the page was for, and the way to add a connection someone shared was not on it at all.
 *
 * 1. Use a connection Shipyard ships: the connections in the code's own folder, each with
 *    what it still needs in one quiet line and Turn on for the space.
 * 2. Add a connection someone shared with you: under "Shared with you", the connections that
 *    are a clone of their own in the install's folder (`own_repo` on the row), each marked
 *    as found there (`folder`, `packsetup.pack_row`), then the one command to copy with the
 *    install's real folder filled in, Copy, and Look again. These are the Setup view's own
 *    (`K.setupParts.sharedPack`, in this page's word): Shipyard never clones for the user and
 *    never handles a repo's address or credentials. Anything else that folder holds is
 *    listed after, under the plain heading "Found in this install", never as shared (r1.F7).
 * 3. Have Bosun draft one for another provider: the box, the tap that files the card
 *    (`setup.pack.draft`), and the check that follows that card. A draft in progress and a
 *    draft that landed and is not turned on say exactly that, and where work goes meanwhile
 *    (this computer, or the connection the space is on, r1.F1); the landed connection's row,
 *    with its Turn on, is drawn here for the space it was drafted for, and the box comes back
 *    once no draft is open (r1.F4).
 * 4. Keep work on this computer, and push when you say (keel/landpush.py): what happens, the
 *    space's two switches (the Settings form's own fields) and the push check, run on a tap.
 *
 * PICKING IS SEPARATE FROM TURNING ON (c-758). A choice opens its section and writes nothing:
 * the button inside acts (Turn on, Turn off, Have Bosun draft a connection, Keep work on this
 * computer), and the line under the choices states what is true now ("Work for <space> now
 * goes through <connection>."). Until c-758 picking the first option with one connection
 * listed turned it on at once, and picking the last one asked to turn a connection off.
 *
 * What is IN USE is the config's (a space on a connection, else this computer). What is OPEN
 * is the option tapped (`picked`), else the one in use, else the draft while one is open or
 * has landed for this space, else the shared one while a cloned connection waits or a folder
 * of the install's own has a problem (`packs_error_install`, r1.F13), else this computer. A connection that is on is drawn in full: its
 * checks with their fixes, each once (a capability row a failing check holds up is that
 * check, so it is not drawn again), Turn off, and under one that can bring review requests
 * (c-730) the one question about them. Every problem line the step shows ends in a control
 * the step has: each place that can show one has Look again. A line about the install's
 * folder is drawn in the shared section; a connection that does not load, wherever it lies,
 * is drawn under the choices with a neutral label (r1.F13). The lines are read in this
 * page's word (`connections_error`; the Setup view reads `packs_error`, r1.F7).
 *
 * What each space has (its remote, its copied repos with their hosts) is `start.lands` on the
 * Setup report. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el;
  var asked = {};       /* space -> { state: 'checking' | 'done', rows: [...] } */
  var provider = {};    /* space -> what the user is typing for the draft */
  var reviewsToo = {};  /* space -> the draft's answer: should it bring review requests (c-730) */
  var picked = {};      /* space -> the choice the user opened: shipped, shared, draft or local */
  var GITHUB = 'github.com';
  /* the draft's example, as the box's placeholder (the owner's call): a host no pack names */
  /* the owner's word (c-758): the box asks what the connection must be able to do on the
     host, never how the team works, which is How work ships' question */
  var ASK = 'Which code host, and what should Shipyard do there?';
  /* no host's own noun is spelled here (`make drift`): the host is not known yet, so the
     page says "change" and asks what the host calls it */
  var DOES = 'What it can do there: open each card\'s change for review, watch its checks, and bring review comments ' +
    'back to the card. Say which of these you want, what your host calls them, and how you sign in to it.';
  var EXAMPLE = 'For example: GitLab. Open each card\'s change for review into the branch it started from, watch its pipeline, ' +
    'and bring review comments back to the card. Sign-in is through the glab tool, already signed in.';
  var TITLES = { shipped: 'Use a connection Shipyard ships', shared: 'Add a connection someone shared with you',
    draft: 'Have Bosun draft one for another provider', local: 'Keep work on this computer, and push when you say' };
  var PICK = 'Pick one to see what it takes. Nothing changes until you press a button inside it.';
  var DONE = 'This step is done when a connection is turned on and everything it needs is ready, or when you keep work on this computer.';
  /* r1.F2: while a draft stands the step is not done by keeping work here (`firstrunsteps.draft_waiting`), and Skip is the way on */
  var DONE_DRAFT = 'A connection draft stands, so this step is not done yet: it is done when that connection is turned on and everything it needs is ready. ' +
    'To keep work on this computer meanwhile, press Skip below.';

  var STYLE = [
    '.lands{display:flex;flex-direction:column;gap:16px}',
    /* four choices read as two rows of two on the desk, one column on a phone */
    '.lands .start-choice{grid-template-columns:repeat(2,minmax(0,1fr))}',
    '@media (max-width:899px){.lands .start-choice{grid-template-columns:minmax(0,1fr)}}',
    '.lands-opt{border:1px solid var(--accent);background:var(--s1);padding:12px;display:flex;flex-direction:column;gap:8px;font-size:13px;line-height:1.5;min-width:0}',
    '.lands-opt h3{margin:0;font-size:15px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}',
    '.lands-opt p{margin:0}',
    /* a problem line carries a folder's whole path: it wraps on a phone, and reads as the thing to fix */
    '.lands-opt .empty.crit{overflow-wrap:anywhere;text-align:left;font-size:13px;line-height:1.5;padding:8px 12px;border-left:3px solid var(--warn);background:var(--warn-soft);color:var(--ink)}',
    '.lands-btns{display:flex;gap:8px;flex-wrap:wrap}.lands-btns .btn{min-height:44px}',
    '.lands-read{font-size:13px;line-height:1.5}',
    '.lands-quiet{font-size:12px;line-height:1.5;color:var(--ink-2)}',
    '.lands-now{font-size:13px;line-height:1.5;padding:8px 12px;border-left:3px solid var(--good);background:var(--good-soft)}',
    '.lands-found{display:flex;flex-direction:column;gap:4px}',
    '.lands-mark{font-family:var(--mono);font-size:11px;color:var(--accent-ink);overflow-wrap:anywhere}',
    '.lands-ask{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--ink-2)}',
    '.lands-ask textarea{width:100%;min-height:88px;font-size:13px}',
    '.lands-reviews{display:flex;flex-direction:column;gap:4px;border-top:1px solid var(--hair);padding-top:12px;margin-top:4px}',
    '.lands-q{font-weight:600}',
    '.lands-tick{display:flex;gap:8px;align-items:flex-start;font-size:13px;line-height:1.5}',
    '.lands-tick input{margin-top:3px;flex:none}'
  ].join('\n');
  function styleOnce() {
    if (document.getElementById('startlands-style')) return;
    var node = document.createElement('style');
    node.id = 'startlands-style';
    node.textContent = STYLE;
    document.head.appendChild(node);
  }
  function redraw() { K.renderBody(); }

  function ask(space) {
    asked[space] = { state: 'checking', rows: [] };
    redraw();
    K.act({ verb: 'land.push.check', space: space }, function () { return ''; }).then(function (r) {
      if (r && r.checks) asked[space] = { state: 'done', rows: r.checks };
      else asked[space] = { state: 'done', rows: [{ key: space, ok: false, why: K.refused('land.push.check') || 'the check did not run' }] };
      redraw();
    });
  }

  /* "This computer can push to origin": waiting until asked, then one line per repo */
  function canPush(space, own) {
    var name = 'This computer can push to ' + own.remote, found = asked[space];
    var again = el('div', { class: 'lands-btns' }, el('button', { class: 'btn', onclick: function () { ask(space); } },
      found && found.state === 'done' ? 'Check again' : 'Check'));
    if (!found) return [K.check({ key: 'can-push-' + space, state: 'waiting', name: name }), again];
    if (found.state === 'checking') return K.check({ key: 'can-push-' + space, state: 'checking', name: name });
    return [found.rows.map(function (row) {
      var github = row.host === GITHUB;
      return row.ok ? K.check({ key: 'can-push-' + space + '-' + row.key, state: 'ready', name: name, says: row.why })
        : K.check({ key: 'can-push-' + space + '-' + row.key, state: 'needs', name: name, what: row.why,
          fix: github ? 'The fix is the first two checks of the GitHub connection: GitHub\'s command line tool (gh), and your GitHub sign-in.' : null });
    }), again];
  }

  /* ---------- what the report says of a space ---------- */

  function packsOf(report) { return report.packs || []; }
  function onOf(report, space) { return (report.spaces[space] || {}).pack || null; }
  function rowOf(report, name) { return packsOf(report).filter(function (p) { return p.name === name; })[0] || null; }
  function draftOf(report) { return ((report.builder || {}).connection) || {}; }
  /* c-734 point 5: the connection a landed draft added, while it is offered. r2.F4: only in
     the space the draft was for (`connection.space`, recorded on the card); a draft that
     names none is drawn under the draft choice nowhere */
  function draftedPack(report, space) {
    var c = draftOf(report);
    return c.done && c.pack && c.space === space && rowOf(report, c.pack) ? c.pack : null;
  }
  /* which choice a connection is listed under for this space: the draft's own, else by where
     it was found (the install's folder, or the code's) */
  function kindOf(report, space, p) {
    return draftedPack(report, space) === p.name ? 'draft' : p.folder ? 'shared' : 'shipped';
  }
  /* r1.F7: "someone shared with you" is a connection that is a clone of its own in the
     install's folder (`own_repo`); anything else found there (one Bosun drafted for another
     space, the user's own import) is listed in the same section under a plain heading */
  function isClone(p) { return !!p.own_repo; }
  /* the problem lines in this page's word, and whether they are about the install's folder (r1.F13) */
  function problems(report) { return report.connections_error !== undefined ? report.connections_error : report.packs_error; }
  function installProblem(report) { return !!problems(report) && !!report.packs_error_install; }
  function listed(report, space, kind) {
    return packsOf(report).filter(function (p) { return kindOf(report, space, p) === kind; });
  }
  /* a connection that is on and no longer listed (it does not load) keeps the first choice */
  function inUse(report, space) {
    var on = onOf(report, space), row = on ? rowOf(report, on) : null;
    return !on ? 'local' : row ? kindOf(report, space, row) : 'shipped';
  }
  /* a cloned connection nobody has turned on, or a folder there with a problem: the shared
     choice opens by itself, so what was just cloned is on the page */
  function sharedWaits(report, space) {
    return installProblem(report) || listed(report, space, 'shared').some(function (p) { return isClone(p) && !(p.spaces || []).length; });
  }
  function draftOpen(report, space) {
    var open = draftOf(report).open;
    return open && (!open.space || open.space === space) ? open : null;
  }
  /* a draft the step waits on: open, or landed and not on, for a space on no connection */
  function draftStands(report, space) {
    return !onOf(report, space) && !!(draftOpen(report, space) || draftedPack(report, space));
  }
  function openOf(report, space) {
    if (picked[space]) return picked[space];
    if (onOf(report, space)) return inUse(report, space);
    return draftOpen(report, space) || draftedPack(report, space) ? 'draft' : sharedWaits(report, space) ? 'shared' : 'local';
  }

  /* ---------- a connection's rows ---------- */

  /* the space's readiness row for a capability: a row that says the space cannot use it at
     all (`declared` false, keel/readiness.py) is not something it needs, and one a failing
     check holds up (`needs`) is that check, drawn once in the connection's own row (c-758) */
  function shown(space, cap) {
    var rows = (((K.App.data || {}).readiness || {}).spaces || {})[space] || {};
    return !rows[cap] || (rows[cap].declared !== false && !(rows[cap].needs || []).length);
  }
  /* c-730: one plain question, off by default, under a connection that can bring review
     requests (it declares `reviews`): the space's own `review_scan`, and once it is ticked the
     space's auto review and review model, in the Settings form's own fields */
  function reviewsAsk(report, space, on) {
    var p = rowOf(report, on);
    if (!p || (p.capabilities || []).indexOf('reviews') < 0 || !K.settingsForm) return null;
    var wanted = K.settingShown && K.settingShown(space, 'space.review_scan') === true;
    return el('div', { class: 'lands-reviews', 'data-key': 'lands-reviews-' + space },
      el('p', { class: 'lands-q', 'data-key': 'lands-reviews-ask', text: K.say(space, 'Also bring me {changes} that wait on my review?') }),
      el('p', { class: 'lands-read', text: K.say(space, 'Off unless you turn it on. Each one becomes a review card: a house reviews the {change}, ' +
        'and you choose what is posted. One from a fork waits for your tap, even with auto review on, and its code is read, never run.') }),
      K.settingsForm({ space: space, keys: wanted ? ['space.review_scan', 'space.review_auto', 'space.review_model'] : ['space.review_scan'] }));
  }
  function lookAgain() {
    return el('div', { class: 'lands-btns' }, el('button', { class: 'btn', 'data-key': 'lands-again', onclick: function () { K.setupParts.again(); } }, 'Look again'));
  }
  /* the connection that is on, in full: its row (checks, fixes, Turn off), what else the space
     has through it, the review question, and Look again for the fixes that end in it */
  function onRows(report, space, parts) {
    var on = onOf(report, space), p = rowOf(report, on);
    var rows = [['tracker', 'Tracker'], ['codehost', 'Code host'], ['reviews', 'Review scanning'], ['ci', 'CI builds']]
      .filter(function (pair) { return shown(space, pair[0]); });
    return [p ? K.setupParts.packRow(p, space) : null, p ? noHost(p) : null,
      parts.rowLines ? parts.rowLines(space, rows) : null, reviewsAsk(report, space, on), lookAgain()];
  }
  /* a connection that is not on for this space: where it was found, what it still needs in one
     quiet line, and its Turn on, which is left out while the space is on another */
  function offRow(report, space, p) {
    var locked = !!onOf(report, space);
    return el('div', { class: 'lands-found', 'data-key': 'lands-row-' + p.name },
      p.folder ? el('span', { class: 'lands-mark', 'data-key': 'lands-found-' + p.name, text: 'Found in ' + p.folder }) : null,
      K.setupParts.packRow(p, space, { quiet: true, locked: locked }), noHost(p));
  }
  /* r1.F7: a row with no code host still lists, and says so on the row (`capabilities` is the
     pack's own claim; a row that carries none is not judged) */
  function noHost(p) {
    return Array.isArray(p.capabilities) && p.capabilities.indexOf('codehost') < 0
      ? el('span', { class: 'lands-quiet', 'data-key': 'lands-nohost-' + p.name, text: p.name + ' has no code host: it cannot open work for review.' }) : null;
  }
  /* r1.F13: a problem that is not about the install's folder (a connection that does not
     load, wherever it is; a misnamed folder somewhere else) is drawn under the choices, with
     a neutral label and Look again. The label says none is listed only when none is: a
     misnamed folder leaves every other connection listed (keel/packsetup.py `listing`) */
  function problemBlock(report, space) {
    if (!problems(report) || installProblem(report)) return null;
    return el('div', { class: 'lands-opt', 'data-key': 'lands-problem-' + space },
      el('p', { class: 'lands-q', text: packsOf(report).length ? 'A folder Shipyard reads connections from needs a look:'
        : 'A connection does not load, so none is listed:' }),
      K.setupParts.packProblems(report, problems(report)), lookAgain());
  }
  /* said in a section the space cannot act in until its connection is off */
  function lockedLine(report, space) {
    var on = onOf(report, space);
    if (!on) return null;
    /* r2.F1: one connection that does not load empties the list, so the one in use has no row
       and no Turn off: the line names the control that is drawn, the Keep work button
       (`setup.pack.off` goes through then, tests/test_packdraft.py) */
    if (!rowOf(report, on)) return el('p', { class: 'lands-quiet', 'data-key': 'lands-locked', text: space + ' is on ' + on + ' now, and ' + on +
      ' is not listed' + (problems(report) ? ' because a connection does not load' : '') + '. To use another, press Keep work for ' + space +
      ' on this computer under "' + TITLES.local + '", or fix the connection and press Look again.' });
    return el('p', { class: 'lands-quiet', 'data-key': 'lands-locked', text: space + ' is on ' + on + ' now. To use another, turn ' +
      on + ' off first, under "' + TITLES[inUse(report, space)] + '".' });
  }

  /* ---------- the four sections, drawn for the open one only ---------- */

  function shipped(report, space, parts) {
    var mine = inUse(report, space) === 'shipped', rows = listed(report, space, 'shipped');
    return el('div', { class: 'lands-opt', 'data-key': 'lands-shipped-' + space },
      el('h3', { text: mine ? onOf(report, space) + ' is on for ' + space : 'Connections Shipyard ships' }),
      mine ? onRows(report, space, parts) : [
        el('p', { 'data-key': 'lands-shipped-said', text: K.say(space, 'Each one opens your work as a {change} on its code host, as you, and follows its review there. ' +
          'Turn one on for ' + space + '. You can turn it off again.') }),
        lockedLine(report, space),
        rows.length ? rows.map(function (p) { return offRow(report, space, p); })
          : problems(report) ? null : el('p', { class: 'lands-quiet', text: 'None is listed on this install.' }),
        lookAgain()]);
  }
  function shared(report, space, parts) {
    var mine = inUse(report, space) === 'shared', on = onOf(report, space);
    var rows = listed(report, space, 'shared').filter(function (p) { return !(mine && p.name === on); });
    var clones = rows.filter(isClone), others = rows.filter(function (p) { return !isClone(p); });
    var first = on ? ' (to use one, turn ' + on + ' off first)' : '';
    return el('div', { class: 'lands-opt', 'data-key': 'lands-shared-' + space },
      el('h3', { text: mine ? on + ' is on for ' + space : 'A connection someone shared with you' }),
      mine ? onRows(report, space, parts) : [
        el('p', { 'data-key': 'lands-shared-said', text: 'A team keeps its connection in a repo of its own. You copy it into this install with one command, ' +
          'then turn it on here. Shipyard never asks for its address or your sign-in: the command is yours to run.' }),
        lockedLine(report, space)],
      installProblem(report) ? K.setupParts.packProblems(report, problems(report)) : null,
      /* a row here has no Turn on while the space is on a connection, and its heading says why */
      clones.length ? el('p', { class: 'lands-q', 'data-key': 'lands-clones', text: 'Shared with you' + first }) : null,
      clones.map(function (p) { return offRow(report, space, p); }),
      K.setupParts.sharedPack(report, { found: mine || clones.length > 0, noun: 'connection' }),
      others.length ? el('p', { class: 'lands-q', 'data-key': 'lands-others', text: 'Found in this install' + first }) : null,
      others.map(function (p) { return offRow(report, space, p); }));
  }

  /* The draft (c-678): the user says which provider, and one tap files the card on which Bosun
     drafts a connection (`setup.pack.draft`, keel/onboarding.py). The check under it follows
     that card: `builder.connection` on the Setup report, `{open, done, pack, space}`. */
  var STAGES = { inbox: 'Waiting for Bosun to start', assigned: 'Waiting for Bosun to start', planning: 'Bosun is writing its plan',
    building: 'Bosun is building it', review: 'Ready for you to approve', shipping: 'Landing' };
  /* c-734 point 9: what a draft is, said before the tap and kept while it runs. The figures
     are a stated estimate, never a promise, and the page says so. */
  /* r2.F4: Skip and "this step stays open" are said only to a space on no connection, the one
     the step waits for (`firstrunsteps.draft_waiting`) */
  function expect(on) {
    return 'Drafting a connection is a real build. Bosun writes a plan first, for you to approve, then builds the whole ' +
      'connection with its tests. That can take around 40 minutes and add a few thousand lines: an estimate, not a promise. ' +
      (on ? 'You can carry on with the other steps meanwhile. '
        : 'You can carry on with the other steps meanwhile: press Skip below, and this step stays open until the connection is on. ') +
      'The check below shows where it is, and the card shows on Now when it needs you.';
  }
  /* c-734: the gate that waits on the user is said first, then whether Bosun has heard of the
     user's last tap (`pausewake.told`, keel/packdraft.py `connection_cards`) */
  var GATES = { plan: 'Waiting for you to approve its plan', outcome: 'Ready for you to approve' };
  function whereItIs(open) {
    var at = GATES[open.gate] || (open.waiting ? 'Waiting for you' : STAGES[open.stage] || open.stage);
    return at + ' (' + open.card + '). ' + (open.told ? 'Bosun has been told.' : 'Bosun is told as soon as it is free.');
  }
  /* c-758: honest states. In progress says it is not finished; landed says whether the
     connection is on, and where its Turn on is when it is not drawn here. One draft slot is
     install-wide, so a space the draft is not for sees it too, and is told whose it is (r2.F4) */
  var DRAFT = 'Draft of the connection';
  function draftCheck(report, space) {
    var c = draftOf(report);
    if (c.open) return openCheck(report, space, c.open);
    if (c.done) return landedCheck(report, space, c);
    return K.check({ key: 'connection-draft', state: 'waiting', name: DRAFT });
  }
  /* r1.F1: where work goes meanwhile is the space's own connection when it is on one */
  function openCheck(report, space, open) {
    var on = onOf(report, space), theirs = open.space && open.space !== space ? open.space : null;
    var goes = on ? 'work for ' + space + ' goes through ' + on + '.'
      : theirs ? 'work for ' + space + ' stays on this computer.' : 'work stays on this computer.';
    return [K.check({ key: 'connection-draft', state: 'checking', name: DRAFT,
      says: 'Not finished yet' + (theirs ? ', and it is for ' + theirs : '') + '. ' + whereItIs(open) +
        (theirs ? ' Until it has landed and is turned on, ' : ' Until it has landed and you turn it on, ') + goes }),
      el('div', { class: 'lands-btns' }, el('button', { class: 'btn sm', onclick: function () { K.go('cards', open.card); } }, 'Open ' + open.card))];
  }
  function landedCheck(report, space, c) {
    var mine = draftedPack(report, space), on = onOf(report, space);
    if (mine && on === mine) return K.check({ key: 'connection-draft', state: 'ready', name: DRAFT,
      says: c.done + ' landed, and ' + mine + ' is on for ' + space + '.' });
    /* landed for a space that is on another connection: no Turn on is drawn (the server would
       refuse it), so the check says where work goes and the line under it where the Turn off is */
    if (mine && on) return K.check({ key: 'connection-draft', state: 'waiting', name: DRAFT,
      says: c.done + ' landed: the connection ' + mine + ' is here, and it is not turned on. Work for ' + space + ' goes through ' + on + '.' });
    if (mine) return K.check({ key: 'connection-draft', state: 'needs', name: DRAFT,
      what: c.done + ' landed: the connection ' + mine + ' is here, and it is not turned on yet. Work for ' + space + ' still stays on this computer.',
      fix: 'Press Turn on for ' + space + ' just below.' });
    /* r1.F3: landed and not on here is never ready, and the shared choice is named only when
       the connection is really listed there (it is in the install's folder and it loads).
       r2.F4: it says whose draft it was, and promises a Turn on only where this space's row has one */
    var there = c.pack ? rowOf(report, c.pack) : null;
    if (there && there.folder) return K.check({ key: 'connection-draft', state: 'waiting', name: DRAFT,
      says: c.done + ' landed' + (c.space && c.space !== space ? ' for ' + c.space : '') + '. The connection ' + c.pack +
        ' is listed under "' + TITLES.shared + '"' + (on ? '.' : ', with its Turn on for ' + space + '.') });
    return [K.check({ key: 'connection-draft', state: 'waiting', name: DRAFT,
      says: c.done + ' landed, and no connection from it is listed on this install. Open the card to see what it added, or press Look again.' }),
      el('div', { class: 'lands-btns' }, el('button', { class: 'btn sm', onclick: function () { K.go('cards', c.done); } }, 'Open ' + c.done),
        el('button', { class: 'btn sm', onclick: function () { K.setupParts.again(); } }, 'Look again'))];
  }
  /* `again` (r1.F4): one has landed already, so the form is worded as drafting another */
  function draftForm(space, again) {
    var why = K.refused('setup.pack.draft');
    return [
      again ? el('p', { class: 'lands-q', 'data-key': 'lands-c-again', text: 'Draft another connection' }) : null,
      again ? el('p', { class: 'lands-read', text: 'If the one that landed is for the wrong code host, or is not right, Bosun can draft another. ' +
        'It is a new card and a new build, and the one that landed stays until you remove it.' }) : null,
      el('label', { class: 'lands-ask' }, el('span', { text: ASK }),
        el('span', { 'data-key': 'lands-c-does', text: DOES }),
        el('textarea', { 'data-fk': 'lands-provider-' + space, rows: 3, value: provider[space] || '', placeholder: EXAMPLE,
          'aria-label': ASK,
          oninput: function (ev) { provider[space] = ev.target.value; } })),
      el('label', { class: 'lands-tick', 'data-key': 'lands-c-reviews' },
        el('input', { type: 'checkbox', checked: !!reviewsToo[space], 'aria-label': K.say(space, 'Should it also bring you {changes} that wait on your review?'),
          onchange: function (ev) { reviewsToo[space] = !!ev.target.checked; redraw(); } }),
        el('span', { text: K.say(space, 'Should it also bring you {changes} that wait on your review? Bosun then builds that too, and it starts off until you turn it on.') })),
      why ? el('div', { class: 'empty crit', 'data-key': 'lands-c-refused', text: why }) : null,
      el('div', { class: 'lands-btns' }, el('button', { class: 'btn', onclick: function () {
        K.setupParts.change({ verb: 'setup.pack.draft', space: space, words: provider[space] || '', reviews: !!reviewsToo[space] }, 'filed for Bosun')
          .then(function (r) { if (r) { delete provider[space]; delete reviewsToo[space]; } });
      } }, again ? 'Have Bosun draft another connection' : 'Have Bosun draft a connection'))];
  }
  function draft(report, space, parts) {
    var c = draftOf(report), mine = draftedPack(report, space), on = onOf(report, space);
    var row = mine ? rowOf(report, mine) : null;
    return el('div', { class: 'lands-opt', 'data-key': 'lands-draft-' + space },
      el('h3', { text: mine && on === mine ? mine + ' is on for ' + space : 'A connection Bosun drafts for you' }),
      el('p', { 'data-key': 'lands-c-said', text: 'For a code host Shipyard ships no connection for. Bosun writes the connection as a card: ' +
        'you read its plan and approve the result, and nothing changes until you turn the connection on. ' +
        /* fix check, residue A: said from the space's state, as the check under it is */
        (on && on !== mine ? 'Until then, work for ' + space + ' keeps going through ' + on + '.'
          : 'Until then, work stays on this computer, which works with any git host.') }),
      mine ? null : el('p', { class: 'lands-read', 'data-key': 'lands-c-expect', text: expect(on) }),
      c.open || c.done ? null : draftForm(space),
      draftCheck(report, space),
      row && on && on !== mine ? lockedLine(report, space) : null,
      !row ? null : on === mine ? onRows(report, space, parts) : [offRow(report, space, row), lookAgain()],
      /* r1.F4: the form comes back once no draft is open, under what the landed one left */
      c.done && !c.open ? draftForm(space, true) : null);
  }
  function local(report, space, own) {
    var branch = ((own.repos[0] || {}).branch) || 'main', on = onOf(report, space);
    return el('div', { class: 'lands-opt', 'data-key': 'lands-local-' + space },
      el('h3', { text: 'Work kept on this computer' }),
      el('p', { 'data-key': 'lands-b-said', text: 'Work is merged into ' + branch + ' in Shipyard\'s copy on this computer. Shipyard fetches from your repo\'s home address ' +
        'before it starts a card, so it builds on what your team has. After a landing you get a Push button. ' +
        'Nothing leaves this computer without your tap.' }),
      on ? [el('p', { 'data-key': 'lands-local-off', text: space + ' is on ' + on + ' now. Keeping work on this computer turns ' + on +
        ' off for ' + space + '. The space and its repos stay, and you can turn the connection on again.' }),
        el('div', { class: 'lands-btns' }, el('button', { class: 'btn', 'data-key': 'lands-keep-local', onclick: function () {
          K.setupParts.change({ verb: 'setup.pack.off', space: space });
        } }, 'Keep work for ' + space + ' on this computer'))]
        : [K.settingsForm ? K.settingsForm({ space: space, keys: ['space.fetch_before_work', 'space.offer_push'] }) : null,
          own.repos.length ? canPush(space, own) : null]);
  }

  /* ---------- the choice ---------- */

  /* the choice the repo's host points at: the shipped ones, when one is for github.com */
  function matches(report, own) {
    return own.repos.some(function (r) { return r.host === GITHUB; }) && !!rowOf(report, 'github') && !rowOf(report, 'github').folder;
  }
  function readLine(own) {
    var first = own.repos.filter(function (r) { return r.host; })[0];
    return first ? el('div', { class: 'lands-read', 'data-key': 'lands-read', text: 'Shipyard read ' + first.key + '\'s address: it lives on ' +
      first.host + '. Pick how its work should arrive there.' }) : null;
  }
  function names(rows) { return rows.map(function (p) { return p.name; }).join(', '); }
  /* each choice: what happens next in one line, and one quiet line of what is there now */
  function options(report, space, own) {
    var use = inUse(report, space), c = draftOf(report), open = draftOpen(report, space), mine = draftedPack(report, space);
    var ships = listed(report, space, 'shipped'), found = listed(report, space, 'shared');
    var clones = found.filter(isClone), others = found.filter(function (p) { return !isClone(p); });
    var there = [clones.length ? 'Shared with you: ' + names(clones) : null, others.length ? 'Found in this install: ' + names(others) : null]
      .filter(Boolean).join('. ');
    var all = [];
    if (ships.length || problems(report) || use === 'shipped') all.push({ id: 'shipped',
      said: K.say(space, (matches(report, own) ? 'Matches your repo. ' : '') + 'Shipyard opens each {change} on your code host, as you. Next: turn one on and see what it needs.'),
      note: ships.length ? 'Shipped: ' + names(ships) : null });
    all.push({ id: 'shared', said: 'Your team has its own. Next: copy one command, run it, then turn the connection on here.',
      note: installProblem(report) ? 'A folder in this install needs a look' : there || null });
    all.push({ id: 'draft', said: 'For a code host Shipyard does not ship yet. Bosun writes a connection as a card: code you read, then turn on. ' +
        'Next: tell Bosun which host, approve its plan, then turn on what it builds.',
      note: open ? 'In progress (' + open.card + '), not finished' : mine && use !== 'draft' ? 'Drafted (' + c.done + '), not turned on yet' : null });
    all.push({ id: 'local', said: 'Needs nothing set up. Work is merged here, and nothing leaves this computer without your Push.' });
    return all.map(function (o) {
      o.title = TITLES[o.id];
      o.tag = use === o.id ? 'in use' : 'open';
      o.badge = use === o.id ? 'in use' : null;
      return o;
    });
  }
  /* what is true now, whichever choice is open (c-758) */
  function nowLine(report, space) {
    var on = onOf(report, space);
    return el('div', { class: 'lands-now', role: 'status', 'data-key': 'lands-now-' + space, text: on
      ? 'Work for ' + space + ' now goes through ' + on + '.'
      : 'Work for ' + space + ' now stays on this computer, and you push when you say.' });
  }
  function choice(report, space, own) {
    return K.startChoice({ key: 'lands-how-' + space, label: 'Where finished work goes for ' + space, chosen: openOf(report, space),
      options: options(report, space, own), pick: function (id) { picked[space] = id; redraw(); } });
  }
  var SECTIONS = { shipped: shipped, shared: shared, draft: draft };

  K.landsScreen = function (report, step, parts) {
    styleOnce();
    var lands = (report.start || {}).lands || {};
    var every = Object.keys(report.spaces || {});
    /* the spaces with a repo of the user's, or on a connection; every space while there is none */
    var used = every.filter(function (n) {
      return report.spaces[n].pack || (report.spaces[n].repos || []).some(function (r) { return !K.ownRepo(r.key); });
    });
    var all = used.length ? used : every;
    return el('div', { class: 'lands', 'data-key': 'lands' }, all.map(function (space) {
      var own = lands[space] || { remote: 'origin', repos: [] };
      var open = openOf(report, space);
      return parts.sub('lands-' + space, all.length > 1 ? space : null, [readLine(own),
        el('div', { class: 'lands-quiet', 'data-key': 'lands-pick-' + space, text: PICK }),
        choice(report, space, own), problemBlock(report, space), nowLine(report, space),
        SECTIONS[open] ? SECTIONS[open](report, space, parts) : local(report, space, own)]);
    }), el('div', { class: 'lands-quiet', 'data-key': 'lands-done-means', text: all.some(function (space) { return draftStands(report, space); }) ? DONE_DRAFT : DONE }));
  };
})(window.Keel);
