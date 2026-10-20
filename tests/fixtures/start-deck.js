/* The first-run stepper (c-632) under node, against the deck's DOM stand-in: the page modules,
 * Setup, Settings, Start and the boot (ui.js, with a state fetch that never answers), fed a
 * state with `firstrun` and a Setup report. Every check that did not hold is named.
 *
 * Usage: node start-deck.js <path to app/>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const APP = process.argv[2];
/* the page, the state and the readers, shared with start-steps.js (start-page.js) */
const { deck, check, fails, ready, not, IDS, ATTACH, firstrun, REPORT, page, body, named, keyedAll, stuckOf, countOf,
        placeOf, LAST, COUNTED } = require('./start-page.js')(APP);
/* "N of M" for a step, by its id: a step that is added moves no check here */
const place = (id) => placeOf(id) + ' of ' + LAST;
/* the screen of Check this computer is its own file, listed where the deck's scripts are */
const SCRIPTS = JSON.parse(require('fs').readFileSync(require('path').join(APP, 'views.json'), 'utf8')).scripts;
check('split: ui.startchecks.js is loaded before ui.start.js', SCRIPTS.indexOf('ui.startchecks.js') >= 0 &&
  SCRIPTS.indexOf('ui.startchecks.js') < SCRIPTS.indexOf('ui.start.js'));

/* a fresh install with no ?view= lands on Start; a finished one stays on Now */
(function () {
  const K = page(firstrun(null, true));
  K.stateLanded();
  check('boot: a fresh install opens Start', K.App.view === 'start');
  check('boot: replacing the entry, not pushing one', !K._pushed);
  check('boot: the address says start', K._win.location.search === '?view=start');
  const done = page(firstrun('2026-10-03T10:00:00+00:00', true));
  done.stateLanded();
  check('boot: a finished install stays on Now', done.App.view === 'now');
  const blocked = page(firstrun('2026-10-03T10:00:00+00:00', false));
  blocked.stateLanded();
  check('boot: missing prerequisites open Start even after Finish', blocked.App.view === 'start');
})();

/* after the Setup report has landed */
setImmediate(function () {
  /* the screen: Next stays off on prerequisites until it is done */
  (function () {
    const K = page(firstrun(null, false), 'start');
    K.App.step = 'prerequisites';
    let b = body(K);
    check('screen: one step, its title', b.textContent.indexOf('Check this computer') >= 0);
    check('screen: the counter is the step\'s place, N of M', countOf(b) === '1 of ' + LAST);
    const next = named(b, 'Next');
    check('screen: Next is off on prerequisites while not done', !!next && next.hasAttribute('disabled'));
    check('screen: no Skip on a required step', !named(b, 'Skip'));
    const finish = named(b, 'Finish');
    check('screen: Finish is off while prerequisites miss', !!finish && finish.hasAttribute('disabled'));
    K.App.data.firstrun = firstrun(null, true);
    b = body(K);
    check('screen: Next is on once done', !named(b, 'Next').hasAttribute('disabled'));
    check('screen: Finish is on once done', !named(b, 'Finish').hasAttribute('disabled'));
  })();

  /* Skip sends firstrun.skip for the step on screen */
  (function () {
    const K = page(firstrun(null, true), 'start');
    K.App.step = 'repos';
    const skip = named(body(K), 'Skip');
    check('skip: a Skip on Repos', !!skip);
    if (skip) skip._on.onclick({});
    check('skip: sends firstrun.skip', JSON.stringify(K._acted[0]) === JSON.stringify({ verb: 'firstrun.skip', step: 'repos' }));
  })();

  /* it resumes at the first step neither done nor skipped */
  (function () {
    const fr = firstrun(null, true);
    fr.steps[0].skipped = '2026-10-03T10:00:00+00:00';
    const K = page(fr, 'start');
    check('resume: past a skipped step and the done ones, to Meet Bosun', countOf(body(K)) === '3 of ' + LAST);
  })();

  /* K.openStep routes to the step for a space */
  (function () {
    const K = page(firstrun(null, true));
    K.openStep('repos', 'work');
    check('openStep: the view is start', K.App.view === 'start');
    check('openStep: the address', K._win.location.search === '?view=start&step=repos&space=work');
    check('openStep: the space follows', K.App.space === 'work');
  })();

  /* the rail: Start until Finish; More lists it always */
  (function () {
    const K = page(firstrun(null, true));
    K.renderRail();
    check('rail: Start while not finished', K._doc.getElementById('rail').textContent.indexOf('Start') >= 0);
    const done = page(firstrun('2026-10-03T10:00:00+00:00', true));
    done.renderRail();
    check('rail: no Start after Finish', done._doc.getElementById('rail').textContent.indexOf('Start') < 0);
    const more = deck.wrap(done.viewMore(), done);
    check('more: Start is listed after Finish', deck.all(more, (n) => n.getAttribute('data-key') === 'start-entry').length === 1);
    const fr = firstrun('2026-10-03T10:00:00+00:00', true);
    const entry = (K) => deck.all(deck.wrap(K.viewMore(), K), (n) => n.getAttribute('data-key') === 'start-entry')[0].textContent;
    check('more: the done count: ' + entry(page(fr)), entry(page(fr)).indexOf('2 of ' + COUNTED + ' done') >= 0);
    fr.steps[2].sure = false;
    check('more: a login that could not be checked is not counted as done: ' + entry(page(fr)), entry(page(fr)).indexOf('1 of ' + COUNTED + ' done') >= 0);
  })();

  /* a needs panel's Set it up opens the step through K.openStep */
  (function () {
    const K = page(firstrun(null, true), 'cards');
    const b = body(K);
    const link = deck.all(b, (n) => n.tagName === 'A' && n.getAttribute('href') === '?view=start&step=repos&space=personal')[0];
    check('needs: the panel links the step', !!link);
    if (link) link._on.onclick({ preventDefault() {} });
    check('needs: the tap opens the step', K.App.view === 'start' && K.App.step === 'repos');
  })();

  frame();
  proposing(function () {
    drafts(function () { process.stdout.write(JSON.stringify(fails.length ? { fails } : { ok: true })); });
  });
});

/* c-679: what is typed into git's name and email is kept after a Save that was refused and
   cleared after one that went through. Three turns (the report, the Save's answer, the
   redraw), so it is its own step before the result is printed, never a check left
   scheduled after it. */
function drafts(done) {
  const IDENT = { name: 'git identity', label: 'Your name and email for git', ok: false, said: 'user.email not set',
                  what: 'Git on this computer has no email set.', fix: 'x', command: '', required: true, page: true,
                  values: { name: 'Maya', email: '' } };
  const report = Object.assign({}, REPORT, { start: Object.assign({}, REPORT.start, { prerequisites: [IDENT] }) });
  const open = (answer) => {
    const K = page(firstrun(null, false), 'start', report, { machine: not('x', 'prerequisites') });
    K.App.step = 'prerequisites';
    K.act = (sent) => { K._acted.push(sent); return Promise.resolve(answer); };
    body(K);
    return K;
  };
  const email = (K) => deck.all(body(K), (n) => n.tagName === 'INPUT' && n.getAttribute('aria-label') === 'Email')[0];
  const refused = open(null), saved = open({ ok: true });
  /* an identity nobody could read: its sentence and Check again, and no fields over a value that may be there */
  const UNREAD = Object.assign({}, IDENT, { said: 'could not be checked', what: 'Git\'s settings could not be read just now.',
    fix: 'Check again.', page: false, unread: ['name'], values: { name: '', email: '' } });
  const unread = page(firstrun(null, false), 'start', Object.assign({}, REPORT, { start: Object.assign({}, REPORT.start, { prerequisites: [UNREAD] }) }),
    { machine: not('x', 'prerequisites') });
  unread.App.step = 'prerequisites';
  body(unread);
  setImmediate(function () {
    const row = keyedAll(body(unread), 'stuck-check-git identity')[0];
    check('unread: the row says its own fix and offers no fields', !!row && row.textContent.indexOf('Check again.') >= 0 &&
      !deck.all(row, (n) => n.tagName === 'INPUT').length && !named(row, 'Save'));
    [refused, saved].forEach(function (K) {
      const input = email(K);
      if (input) input._on.oninput({ target: { value: 'maya@example.com' } });
      const save = named(body(K), 'Save');
      if (save) save._on.onclick({});
    });
    setImmediate(function () {
      check('draft: both Saves were sent', refused._acted.length === 1 && saved._acted.length === 1);
      check('draft: kept after a Save that was refused', !!email(refused) && email(refused).value === 'maya@example.com');
      check('draft: cleared after a Save that went through', !!email(saved) && email(saved).value === '');
      done();
    });
  });
}

/* c-677: the frame every step sits in. The list in the approved order with each step's state,
   Next from the step's own state, the line to Bosun's session from Meet Bosun on, the three
   parts of a requirement that needs you, and a finished install that is asked nothing. */
function frame() {
  const at = (step, fr, report, opts) => { const K = page(fr || firstrun(null, true), 'start', report, opts); K.App.step = step; return K; };
  const text = (node) => (node ? node.textContent : '');

  /* the list: the order, and done, here, required, optional, skipped */
  (function () {
    const fr = firstrun(null, true);
    fr.steps[4].skipped = '2026-10-03T10:00:00+00:00';
    const b = body(at('builder', fr));
    const rows = deck.byClass(b, 'start-step');
    check('list: every step, in the approved order', JSON.stringify(rows.map((r) => r.getAttribute('data-key'))) ===
      JSON.stringify(IDS.map((s) => 'go-' + s[0])));
    check('list: each row has its place and its title', text(rows[0]).indexOf('0') === 0 && text(rows[3]).indexOf('Meet Bosun') >= 0);
    const word = (i) => text(deck.byClass(rows[i], 'start-state')[0]);
    const sub = (i) => text(deck.byClass(rows[i], 'start-kind')[0]);
    check('list: a done step says done', word(1) === 'done' && word(2) === 'done');
    check('list: the step on screen says here', word(3) === 'here' && rows[3].getAttribute('aria-current') === 'step');
    check('list: a skipped step says skipped', word(4) === 'skipped');
    check('list: a required step says required', sub(1) === 'required' && sub(2) === 'required' && sub(3) === '');
    check('list: an optional step says optional', sub(placeOf('browser')) === 'optional');
    check('list: an open step has no word', word(placeOf('rules')) === '');
  })();

  /* the phone: the counter and the title on a strip, the list under Steps */
  (function () {
    const b = body(at('builder', null, null, { desk: false }));
    const strip = keyedAll(b, 'start-phone')[0];
    check('phone: a strip with the counter and the step', !!strip && text(strip).indexOf('3 of ' + LAST) >= 0 && text(strip).indexOf('Meet Bosun') >= 0);
    check('phone: one mark per step on the strip', !!strip && deck.byClass(strip, 'start-seg').length === IDS.length);
    check('phone: the list is under Steps', !!strip && deck.byClass(strip, 'start-step').length === IDS.length);
  })();

  /* Next is the step's own state: done, skipped, or nothing to check */
  (function () {
    const fr = firstrun(null, true);
    let b = body(at('repos', fr));
    check('next: off on a step that is neither done nor skipped', named(b, 'Next').hasAttribute('disabled'));
    check('next: the foot says how to go on', text(keyedAll(b, 'start-hint')[0]) === 'Finish this step to go on, or Skip.');
    check('next: Skip is offered there', !!named(b, 'Skip'));
    fr.steps[4].skipped = '2026-10-03T10:00:00+00:00';
    b = body(at('repos', fr));
    check('next: on once the step is skipped', !named(b, 'Next').hasAttribute('disabled') && !keyedAll(b, 'start-hint').length);
    b = body(at('defaults', fr));
    check('next: on where there is nothing to check', !named(b, 'Next').hasAttribute('disabled'));
    b = body(at('login', firstrun(null, false)));
    check('next: a required step names no Skip', text(keyedAll(b, 'start-hint')[0]) === 'Finish this step to go on.' && !named(b, 'Skip'));
    check('next: Back is there', !!named(b, 'Back'));
  })();

  /* the header line: from Meet Bosun on, and only while Bosun's session can run (the
     builder, login and prerequisites rows all ready; the cases are further down) */
  (function () {
    const line = (K) => keyedAll(body(K), 'bosun-line')[0];
    check('header: none before Meet Bosun', !line(at('choose-builder')) && !line(at('prerequisites')) && !line(at('login')));
    const on = line(at('builder'));
    check('header: on Meet Bosun, the words', !!on && text(on).indexOf('Stuck? Open Bosun\'s session') >= 0);
    check('header: this install\'s own command, with Copy', !!on && text(on).indexOf(ATTACH) >= 0 && !!named(on, 'Copy'));
    check('header: on every later step', !!line(at('repos')) && !!line(at('first-card')) && !!line(at('set-up')));
    check('header: none while no builder is set up', !line(at('builder', null, null, { builder: false })) &&
      !line(at('repos', null, null, { builder: false })));
  })();

  /* a requirement that needs you: what happened, the fix where the report has one, and Bosun */
  (function () {
    const failing = Object.assign({}, REPORT, { start: Object.assign({}, REPORT.start, {
      prerequisites: [{ name: 'git', ok: true, said: '2.4', fix: '', required: true },
                      { name: 'claude', ok: false, said: 'not on PATH', fix: 'install Claude Code (`npm install -g x`)', required: true }] }) });
    /* Bosun's session cannot run while a required check fails, so its part is not offered */
    const MISSING = { machine: not('claude: not on PATH', 'prerequisites') };
    let K = at('prerequisites', firstrun(null, false), failing, MISSING);
    body(K);
    setImmediate(function () {
      const b = body(K);
      const rows = stuckOf(b);
      check('stuck: one line for the one failing check', rows.length === 1 && rows[0].getAttribute('data-key') === 'stuck-check-claude');
      check('stuck: what happened', text(keyedAll(rows[0], 'stuck-what')[0]) === 'What happenednot on PATH.');
      const fix = keyedAll(rows[0], 'stuck-fix')[0];
      check('stuck: the fix the report carries, its command as code', !!fix && text(fix).indexOf('install Claude Code') >= 0 &&
        deck.all(fix, (n) => n.tagName === 'CODE' && text(n) === 'npm install -g x').length === 1);
      check('stuck: no Bosun part while a required check fails', !!rows[0] && !keyedAll(rows[0], 'stuck-bosun').length);
      check('stuck: a passing check is one quiet row', keyedAll(b, 'check-git').length === 1 && !deck.hasClass(keyedAll(b, 'check-git')[0], 'stuck'));
    });

    const pack = { name: 'forge', description: 'a pack', spaces: [], rules: [],
                   checks: [{ name: 'git', ok: true, why: 'found', for: [] },
                            { name: 'token', ok: false, why: 'FORGE_TOKEN is not set', for: ['codehost'] }] };
    const withPack = Object.assign({}, REPORT, { packs: [pack] });
    /* a space that is on the pack: its capability rows are drawn on Where finished work goes */
    const onPack = Object.assign({}, withPack, { packs: [Object.assign({}, pack, { spaces: ['personal'] })],
      spaces: { personal: { pack: 'forge', tier: null, writable: true, proposal: null, repos: [] } } });
    /* c-729: a connection's checks are drawn in full where it is the chosen option (the space
       is on it); unchosen, they are one quiet line (tests/fixtures/start-steps.js) */
    const draws = [at('integrations', null, onPack), at('integrations', null, onPack, { builder: false }),
                   page(firstrun('2026-10-03T10:00:00+00:00', true, true), 'setup', onPack), at('integrations', null, onPack),
                   at('integrations', null, withPack)];
    draws.forEach(body);
    setImmediate(function () {
      const row = (K) => keyedAll(body(K), 'stuck-check-token')[0];
      const on = row(draws[0]);
      check('stuck: a pack\'s failing check is a line, not a badge with a hover title', !!on &&
        !deck.all(body(draws[0]), (n) => n.nodeType === 1 && n.getAttribute('title') === 'FORGE_TOKEN is not set').length);
      check('stuck: its reason, said as readiness says it', !!on &&
        text(keyedAll(on, 'stuck-what')[0]).indexOf('token is not set up: FORGE_TOKEN is not set.') >= 0);
      check('stuck: no fix is invented where the report has none', !!on && !keyedAll(on, 'stuck-fix').length);
      const ask = on && keyedAll(on, 'stuck-bosun')[0];
      check('stuck: or ask Bosun in its session, with the command and Copy', !!ask && text(ask).indexOf('or ask Bosun in its session') >= 0 &&
        text(ask).indexOf(ATTACH) >= 0 && !!named(ask, 'Copy'));
      const off = row(draws[1]);
      check('stuck: no Bosun part while no builder is set up', !!off && !keyedAll(off, 'stuck-bosun').length);
      const setup = row(draws[2]);
      check('stuck: the Setup view draws the same line', !!setup && keyedAll(setup, 'stuck-bosun').length === 1);
      check('stuck: a pack\'s passing check stays a badge', deck.all(body(draws[2]), (n) => deck.hasClass(n, 'badge') && text(n) === '\u2713 git').length === 1);
      /* the readiness rows of a step: one line per reason, naming what it holds up */
      const caps = keyedAll(body(draws[3]), 'stuck-row-personal-tracker-codehost-reviews')[0];
      check('stuck: a space with no pack is asked for none of them', !keyedAll(body(draws[4]), 'stuck-row-personal-tracker-codehost-reviews').length);
      check('stuck: rows that fail for one reason are one line', !!caps && text(caps).indexOf('Tracker, Code host, Review scanning') >= 0 &&
        keyedAll(caps, 'stuck-bosun').length === 1);
    });
  })();

  /* c-688: a pack's requirement carries its own fix, drawn in the same stuck line: the
     sentence, the one line to copy with Copy, and how you know it worked; and a pack that is
     on for a space can be turned off there. Every page is drawn before the one turn that
     checks them all, so no check runs after the result is printed. */
  (function () {
    const need = { name: 'gh', ok: false, why: 'pull requests are opened with it', for: ['codehost'],
                   fix: 'Install it with `brew`.', command: 'brew install gh', done_when: 'This check passes on Look again.' };
    const pack = { name: 'forge', description: 'a pack', spaces: ['personal'], rules: [], demo_only: false,
                   checks: [need, { name: 'token', ok: false, why: 'unset', for: [] }] };
    const withPack = Object.assign({}, REPORT, { packs: [pack],
      spaces: { personal: { pack: 'forge', tier: null, writable: true, proposal: null, repos: [] } } });
    const done = firstrun('2026-10-03T10:00:00+00:00', true, true);
    const setup = page(done, 'setup', withPack);
    const step = at('integrations', null, withPack);
    step.App.data.readiness.spaces.personal.codehost = { ready: false, step: 'integrations',
      why: 'gh is not set up: pull requests are opened with it', needs: [need] };
    const plain = page(done, 'setup', Object.assign({}, REPORT, { packs: [Object.assign({}, pack, { spaces: [] })] }));
    /* r1.F3: a demo-only pack leaves the list on an install once no space is on it */
    const demo = page(done, 'setup', Object.assign({}, withPack, { packs: [Object.assign({}, pack, { demo_only: true })] }));
    const demoTwo = page(done, 'setup', Object.assign({}, withPack,
      { packs: [Object.assign({}, pack, { demo_only: true, spaces: ['personal', 'work'] })] }));
    /* r1.F9: an `action` is carried and never drawn */
    const acting = page(done, 'setup', Object.assign({}, withPack,
      { packs: [Object.assign({}, pack, { checks: [Object.assign({ action: 'gh auth setup-git' }, need)] })] }));
    /* r1.F9: a readiness row two failing checks hold up */
    const other = { name: 'token', ok: false, why: 'unset', for: ['codehost'], fix: 'Make a token.', command: 'forge login' };
    const two = at('integrations', null, Object.assign({}, withPack, { packs: [Object.assign({}, pack, { checks: [need, other] })] }));
    two.App.data.readiness.spaces.personal.codehost = { ready: false, step: 'integrations',
      why: 'gh is not set up: x; token is not set up: unset', needs: [need, other] };
    /* r1.F5: a pack that does not load */
    const WHY = 'forge/pack.toml: the forge pack\'s [[requires]] \'gh\': fix must be one line of text';
    const broken = page(done, 'setup', Object.assign({}, REPORT, { packs: [], packs_error: WHY }));
    /* c-740: a folder under the wrong name is a problem line, and the packs that load still list */
    const MISNAMED = 'The folder /i/packs/shared-pack holds the pack shared: rename it to /i/packs/shared, then Look again.';
    const beside = page(done, 'setup', Object.assign({}, REPORT, { packs: [pack], packs_error: MISNAMED + '\n' + WHY }));
    const elsewhere = page(done, 'setup', Object.assign({}, REPORT, { install: null, packs_folder: null, packs: [pack] }));
    /* r1.F8: the folder comes quoted as a shell reads it */
    const spaced = page(done, 'setup', Object.assign({}, REPORT, { install: '/my i', packs_folder: "'/my i/packs'", packs: [pack] }));
    /* c-740 r1.F1: a pack with a repo of its own, before and after Bosun builds it there */
    const inApp = { mode: 'in-app', label: 'Builder, auto mode', repos: ['packs'], importing: null };
    const ownRepo = (built) => page(done, 'setup', Object.assign({}, REPORT, { builder: inApp,
      packs: [Object.assign({}, pack, { spaces: [], own_repo: { key: 'pack-forge', built: built } })] }));
    const unbuilt = ownRepo(false), built = ownRepo(true);
    const noBuilder = page(done, 'setup', Object.assign({}, REPORT,
      { packs: [Object.assign({}, pack, { spaces: [], own_repo: { key: 'pack-forge', built: false } })] }));
    [setup, step, plain, demo, demoTwo, acting, two, broken, beside, elsewhere, spaced, unbuilt, built, noBuilder].forEach(body);
    setImmediate(function () {
      const fixIn = (node) => keyedAll(node, 'stuck-fix')[0];
      const drawn = (fix) => !!fix && text(keyedAll(fix, 'fix-said')[0]) === 'Install it with brew.' &&
        deck.all(fix, (n) => n.tagName === 'CODE' && text(n) === 'brew install gh').length === 1 &&
        !!named(fix, 'Copy') && text(keyedAll(fix, 'fix-then')[0]) === 'This check passes on Look again.';
      const row = keyedAll(body(setup), 'stuck-check-gh')[0];
      check('pack fix: Setup draws the sentence, the command with Copy and how you know', drawn(fixIn(row)));
      check('pack fix: still the one stuck line, with Bosun\'s session after it', !!row && deck.hasClass(row, 'stuck') &&
        keyedAll(row, 'stuck-bosun').length === 1);
      check('pack fix: a requirement with none still has no fix part', !fixIn(keyedAll(body(setup), 'stuck-check-token')[0]));
      const cap = keyedAll(body(step), 'stuck-row-personal-codehost')[0];
      /* c-758: the row a failing check holds up is that check, so the step draws the fix once */
      check('pack fix: the readiness row it holds up is not drawn a second time on the step', !cap);
      check('pack fix: the first run\'s pack row draws it too', drawn(fixIn(keyedAll(body(step), 'stuck-check-gh')[0])));
      /* c-758: two failing checks that hold one row up are each drawn once, as the checks they
         are, each with its own fix (r1.F11), and the row they hold up is not drawn again */
      const fixOf = (name) => fixIn(keyedAll(body(two), 'stuck-check-' + name)[0]);
      const saids = ['gh', 'token'].map((name) => text(keyedAll(fixOf(name), 'fix-said')[0]));
      check('pack fix: two failing checks on one row are drawn once each, and the row is not: ' + stuckOf(body(two)).map((n) => n.getAttribute('data-key')),
        keyedAll(body(two), 'stuck-check-gh').length === 1 && keyedAll(body(two), 'stuck-check-token').length === 1 &&
        !keyedAll(body(two), 'stuck-row-personal-codehost').length);
      check('pack fix: each of the two checks carries its own fix and command: ' + JSON.stringify(saids),
        saids[0] === 'Install it with brew.' && saids[1] === 'Make a token.' &&
        deck.all(fixOf('gh'), (n) => n.tagName === 'CODE' && text(n) === 'brew install gh').length === 1 &&
        deck.all(fixOf('token'), (n) => n.tagName === 'CODE' && text(n) === 'forge login').length === 1 &&
        deck.all(fixOf('gh'), (n) => n.tagName === 'CODE' && text(n) === 'forge login').length === 0);
      const line = keyedAll(body(acting), 'stuck-check-gh')[0];
      check('action: a check that carries one draws no button but Copy: ' + JSON.stringify(line && deck.labels(line)),
        !!line && deck.labels(line).length > 0 && deck.labels(line).every((l) => l === 'Copy') &&
        text(line).indexOf('setup-git') < 0);

      const off = named(body(setup), 'Turn off for personal');
      check('turn off: a pack that is on for a space has the button', !!off);
      /* r1.F9: the confirm guards a mistaken tap: No sends nothing, and its words are these */
      let asked = null;
      setup._win.confirm = function (said) { asked = said; return false; };
      if (off) off._on.onclick({});
      check('turn off: a No at the confirm sends nothing', setup._acted.length === 0);
      check('turn off: the confirm says what stays, and that Turn on puts it back: ' + asked,
        asked === 'Turn forge off for personal? The space, its repos and its own settings stay; forge and the settings it brought come off. Turn on puts it back.');
      setup._win.confirm = function () { return true; };
      if (off) off._on.onclick({});
      check('turn off: it sends setup.pack.off for that space: ' + JSON.stringify(setup._acted),
        setup._acted.length === 1 && setup._acted[0].verb === 'setup.pack.off' && setup._acted[0].space === 'personal');
      check('turn off: none for a pack no space is on', !deck.labels(body(plain)).some((l) => /^Turn off/.test(l)));
      let said = null;
      demo._win.confirm = function (words) { said = words; return false; };
      const demoOff = named(body(demo), 'Turn off for personal');
      if (demoOff) demoOff._on.onclick({});
      check('turn off: a demo-only pack\'s confirm says it will no longer be listed: ' + said,
        /It is for demos only, so it will no longer be listed here\.$/.test(said || '') && !/puts it back/.test(said || ''));
      /* fix check 2: while another space is still on it the row stays, so the ordinary words */
      let shared = null;
      demoTwo._win.confirm = function (words) { shared = words; return false; };
      const sharedOff = named(body(demoTwo), 'Turn off for personal');
      if (sharedOff) sharedOff._on.onclick({});
      check('turn off: a demo-only pack another space is still on keeps the ordinary words: ' + shared,
        /Turn on puts it back\.$/.test(shared || '') && !/no longer be listed/.test(shared || ''));

      const panel = keyedAll(body(broken), 'packs')[0];
      check('packs error: the page says which pack does not load and why', text(panel).indexOf(WHY) >= 0);
      check('packs error: and does not also say there are none', text(panel).indexOf('no packs found') < 0);

      /* c-740: the one line for a pack someone shared, with the install's own folder in it */
      const sharedLine = keyedAll(body(plain), 'pack-shared')[0];
      const cloneLine = 'git clone <its address> /i/packs/<name>';
      check('shared pack: the Packs panel says where one goes and the line that puts it there',
        !!sharedLine && text(sharedLine).indexOf('the pack\'s name. It goes in a folder of its own here, named for the pack:') >= 0 &&
        deck.all(sharedLine, (n) => n.tagName === 'CODE' && text(n) === cloneLine).length === 1 && !!named(sharedLine, 'Copy') &&
        !!named(sharedLine, 'Look again') && text(sharedLine).indexOf('Shipyard does not run it for you.') >= 0);
      check('shared pack: the line is inside the Packs panel', keyedAll(keyedAll(body(plain), 'packs')[0] || body(plain), 'pack-shared').length === 1);
      check('shared pack: a config that is no install has no folder to name, so no line', !keyedAll(body(elsewhere), 'pack-shared').length);
      const quoted = "git clone <its address> '/my i/packs'/<name>";
      check('shared pack: a folder with a space in it is in the line as a shell reads it',
        deck.all(keyedAll(body(spaced), 'pack-shared')[0], (n) => n.tagName === 'CODE' && text(n) === quoted).length === 1);
      const problems = keyedAll(body(beside), 'packs-problem').map(text);
      check('packs problem: each problem is a line of its own: ' + JSON.stringify(problems),
        problems.length === 2 && problems[0] === MISNAMED && problems[1] === WHY);
      check('packs problem: the packs that load still list beside it', keyedAll(body(beside), 'pack-' + pack.name).length === 1);

      /* c-740 r1.F1: the tap that lists a cloned pack for Bosun */
      const tap = named(body(unbuilt), 'Let Bosun build this pack');
      if (tap) tap._on.onclick({});
      check('own repo: a cloned pack Bosun does not build yet has the one tap, which sends setup.pack.build: ' +
        JSON.stringify(unbuilt._acted), !!tap && unbuilt._acted.length === 1 &&
        unbuilt._acted[0].verb === 'setup.pack.build' && unbuilt._acted[0].pack === 'forge');
      const builtSaid = keyedAll(body(built), 'pack-own-repo').map(text)[0] || '';
      check('own repo: once built it says the repo, with no tap: ' + builtSaid,
        builtSaid.indexOf('pack-forge') >= 0 && !named(body(built), 'Let Bosun build this pack'));
      check('own repo: with no builder on the install there is no tap', !named(body(noBuilder), 'Let Bosun build this pack'));
      check('own repo: a pack with no repo of its own says nothing of it', !keyedAll(body(plain), 'pack-own-repo').length);
    });
  })();

  /* review F1, F8: an install whose first run is finished keeps the Next it had, off only on
     a required step that is not done; paging through its open steps sends and writes nothing */
  (function () {
    const fr = firstrun('2026-10-03T10:00:00+00:00', true, false);
    const K = at('rules', fr);
    let b = body(K);
    check('finished, open steps: Next is on', !!named(b, 'Next') && !named(b, 'Next').hasAttribute('disabled'));
    check('finished, open steps: no hint to finish or skip', !keyedAll(b, 'start-hint').length);
    named(b, 'Next')._on.onclick({});
    check('finished, open steps: Next goes on', K.App.step === 'integrations');
    b = body(K);
    check('finished, open steps: Next is on there too', !named(b, 'Next').hasAttribute('disabled'));
    named(b, 'Back')._on.onclick({});
    check('finished, open steps: Back comes back', K.App.step === 'rules');
    ['first-card', 'choose-builder'].forEach(function (id) {
      K.App.step = id;
      const next = named(body(K), id === 'choose-builder' ? 'Continue' : 'Next');
      check('finished, open steps: Next is on at ' + id, !!next && !next.hasAttribute('disabled'));
    });
    K.App.step = 'set-up';
    check('finished, open steps: the last step has no Next', !named(body(K), 'Next'));
    check('finished, open steps: paging sent nothing', K._acted.length === 0);
    const blocked = firstrun('2026-10-03T10:00:00+00:00', false, false);
    check('finished: Next is still off on a required step that is not done', named(body(at('login', blocked)), 'Next').hasAttribute('disabled'));
  })();

  /* review F2: an install nobody has acted on opens on Choose your builder, though it reads done */
  (function () {
    const fr = firstrun(null, true);
    fr.steps[0].done = true; fr.steps[3].done = true;
    fr.untouched = true;
    const K = page(fr);
    K.stateLanded();
    check('fresh: the boot opens Start', K.App.view === 'start');
    check('fresh: on Choose your builder, the first step', countOf(body(K)) === '0 of ' + LAST);
    named(body(K), 'Continue')._on.onclick({});
    check('fresh: Continue goes on from it', K.App.step === 'prerequisites');
    fr.untouched = false;
    const later = page(fr);
    later.stateLanded();
    check('fresh: once a step is taken it resumes at the first open step', countOf(body(later)) === '4 of ' + LAST);
  })();

  /* review F3: the sign-in step's frame follows the readiness row, so the list and the
     screen agree. The screen itself (the four lines, the status in its four states) is
     tests/fixtures/start-steps.js. */
  (function () {
    const UNKNOWN = 'the install\'s Claude login could not be checked last time (exit 2: x); houses try it as they run';
    const unknown = Object.assign(ready(UNKNOWN), { sure: false });
    const fr = firstrun(null, true);
    Object.assign(fr.steps[2], { why: UNKNOWN, sure: false });
    const stamped = Object.assign({}, REPORT, { start: Object.assign({}, REPORT.start, {
      login: { space: 'personal', state: 'unknown', why: 'exit 2: x', at: '2026-10-03T10:03:00+00:00', config_dir: '/i/claude',
               fix: 'run claude', command: 'claude auth login' } }) });
    const draws = [at('login', fr, stamped, { login: unknown })];
    draws.forEach(body);
    setImmediate(function () {
      const b = body(draws[0]);
      /* r2.F1, r2.F3: done for Next and Finish, and nowhere said as done */
      const row = keyedAll(b, 'stuck-signin-status')[0];
      check('login: a login that could not be checked is the quiet line', !!row && deck.hasClass(row, 'quiet') && text(row).indexOf('needs you') < 0);
      check('login: and it does not say it works', !!row && text(row).indexOf('could not reach Claude') >= 0 && text(row).indexOf('works') < 0);
      check('login: Bosun\'s part stays for a login that could not be checked', !!row && keyedAll(row, 'stuck-bosun').length === 1);
      const why = keyedAll(b, 'why')[0];
      check('login: the why line has no Done and no done colour: ' + text(why), text(why).indexOf('Done') < 0 &&
        !deck.hasClass(why, 'done') && text(why).indexOf('could not be checked') >= 0);
      const word = deck.byClass(deck.byClass(body(Object.assign(draws[0], { App: Object.assign(draws[0].App, { step: 'builder' }) })), 'start-step')[2], 'start-state')[0];
      check('login: the list says not checked, not done: ' + text(word), text(word) === 'not checked' && !deck.hasClass(word, 'done'));
      draws[0].App.step = 'login';
      check('login: Next and Finish are on all the same', !named(body(draws[0]), 'Next').hasAttribute('disabled') &&
        !named(body(draws[0]), 'Finish').hasAttribute('disabled'));
    });
  })();

  /* Bosun's session is offered only while it can run: the builder row ready, the login row
     ready (a login that could not be checked counts, since a probe that timed out must not
     hide a live Bosun; an expired or missing one does not), and no required machine check
     failing. One rule, on every step. */
  (function () {
    const soft = Object.assign({}, REPORT, { start: Object.assign({}, REPORT.start, {
      prerequisites: [{ name: 'node', ok: false, said: 'not on PATH', fix: 'install Node.js 20 or newer', required: false }] }) });
    const unsure = Object.assign(ready('could not be checked'), { sure: false });
    const cases = [['a failing optional check on a signed-in install', {}, true],
                   ['no builder set up', { builder: false }, false],
                   ['an expired login', { login: not('does not work', 'login') }, false],
                   ['a login that could not be checked', { login: unsure }, true],
                   ['a required check failing', { machine: not('claude: not on PATH', 'prerequisites') }, false]];
    const draws = cases.map((c) => at('prerequisites', null, soft, c[1]));
    /* a later step that draws a readiness row that fails: Where finished work goes, for a
       space that is on a pack */
    const packed = Object.assign({}, REPORT, { packs: [{ name: 'forge', description: 'a pack', spaces: ['personal'], rules: [], checks: [] }],
      spaces: { personal: { pack: 'forge', tier: null, writable: true, proposal: null, repos: [] } } });
    const later = cases.map((c) => at('integrations', null, packed, c[1]));
    draws.concat(later).forEach(body);
    setImmediate(function () {
      cases.forEach(function (c, i) {
        const row = keyedAll(body(draws[i]), 'stuck-check-node')[0];
        check('bosun: before Meet Bosun, ' + c[0] + (c[2] ? ' draws' : ' draws no') + ' Bosun part',
          !!row && keyedAll(row, 'stuck-bosun').length === (c[2] ? 1 : 0));
        const b = body(later[i]), after = stuckOf(b)[0];
        check('bosun: after it, ' + c[0] + (c[2] ? ' draws' : ' draws no') + ' Bosun part and header line',
          !!after && keyedAll(after, 'stuck-bosun').length === (c[2] ? 1 : 0) && keyedAll(b, 'bosun-line').length === (c[2] ? 1 : 0));
      });
    });
  })();

  /* review F4: a failing check that does not block is said quietly */
  (function () {
    const soft = Object.assign({}, REPORT, { start: Object.assign({}, REPORT.start, {
      prerequisites: [{ name: 'node', ok: false, said: 'not on PATH', fix: 'install Node.js 20 or newer', required: false }] }) });
    const K = at('prerequisites', null, soft);
    body(K);
    setImmediate(function () {
      const row = keyedAll(body(K), 'stuck-check-node')[0];
      check('quiet: a failing check that does not block is not "needs you"', !!row && deck.hasClass(row, 'quiet') &&
        !deck.byClass(row, 'stuck-pill').length && text(row).indexOf('needs you') < 0);
      check('quiet: it still says what happened and the fix', !!row && keyedAll(row, 'stuck-what').length === 1 &&
        text(keyedAll(row, 'stuck-fix')[0]).indexOf('install Node.js') >= 0);
    });
  })();

  /* c-679, Check this computer: a miss says the three parts the check carries (what
     happened, the fix with its command to copy), and git's name and email are two fields
     and Save */
  (function () {
    const IDENT = { name: 'git identity', label: 'Your name and email for git', ok: false, said: 'user.email not set',
                    what: 'Git on this computer has no email set. When work lands, git records who merged it.',
                    fix: 'Type them into the two fields on the setup page.', command: '', page: true,
                    required: true, values: { name: 'Maya', email: '' } };
    const OLD = { name: 'claude --bg (background sessions)', label: 'Claude Code can run sessions in the background', ok: false,
                  said: 'missing from --help', what: 'Claude Code on this computer is too old to run sessions in the background. Shipyard starts every session that way.',
                  fix: 'Update Claude Code.', command: 'claude update', required: true };
    const withChecks = (list) => Object.assign({}, REPORT, { start: Object.assign({}, REPORT.start, { prerequisites: list }) });
    const MISSING = { machine: not('git identity: user.email not set', 'prerequisites') };
    const K = at('prerequisites', firstrun(null, false), withChecks([IDENT, OLD]), MISSING);
    const set = at('prerequisites', null, withChecks([Object.assign({}, IDENT, { ok: true, said: 'Maya <maya@example.com>', what: '', fix: '', command: '' })]));
    [K, set].forEach(body);
    setImmediate(function () {
      let b = body(K);
      const old = keyedAll(b, 'stuck-check-' + OLD.name)[0];
      check('check: a miss is named by its label', !!old && text(deck.byClass(old, 'stuck-name')[0]) === OLD.label);
      check('check: what happened is the check\'s own sentences', !!old && text(keyedAll(old, 'stuck-what')[0]) === 'What happened' + OLD.what);
      const fix = old && keyedAll(old, 'stuck-fix')[0];
      check('check: the fix, then its command with Copy', !!fix && text(fix).indexOf('Update Claude Code.') >= 0 &&
        deck.all(fix, (n) => n.tagName === 'CODE' && text(n) === 'claude update').length === 1 && !!named(fix, 'Copy'));
      const row = keyedAll(b, 'stuck-check-git identity')[0];
      const inputs = row ? deck.all(row, (n) => n.tagName === 'INPUT') : [];
      check('identity: unset, the row needs you and says why', !!row && text(keyedAll(row, 'stuck-what')[0]) === 'What happened' + IDENT.what);
      check('identity: its fix is two fields, starting from what git has', inputs.length === 2 &&
        inputs[0].getAttribute('aria-label') === 'Name' && inputs[0].value === 'Maya' &&
        inputs[1].getAttribute('aria-label') === 'Email' && !inputs[1].value);
      check('identity: a field whose value is already set cannot be typed over, and the missing one can',
        inputs.length === 2 && inputs[0].hasAttribute('disabled') && !inputs[1].hasAttribute('disabled'));
      check('identity: the fix is the form alone, not the sentence that points at this page',
        !!row && text(row).indexOf('Type them into') < 0);
      check('identity: it says where Save writes', !!row && text(row).indexOf('Writes git\'s global setting.') >= 0);
      check('identity: the fields are the fix, so no command is drawn', !!row && !named(row, 'Copy'));
      const save = row && named(row, 'Save');
      if (save) save._on.onclick({});
      check('identity: Save with a field empty sends nothing', !!save && K._acted.length === 0);
      if (inputs[1]) inputs[1]._on.oninput({ target: { value: ' maya@example.com ' } });
      if (save) save._on.onclick({});
      check('identity: Save sends the two fields', JSON.stringify(K._acted[0]) ===
        JSON.stringify({ verb: 'firstrun.identity.save', name: 'Maya', email: 'maya@example.com' }));
      check('page: the line under the checks', text(keyedAll(b, 'checks-note')[0]) ===
        'Your builder joins two steps from now. Until then each row carries its own fix.');
      b = body(set);
      const good = keyedAll(b, 'check-git identity')[0];
      check('identity: set, the row is a passing check', !!good && !stuckOf(b).length &&
        text(good).indexOf('Your name and email for git') >= 0 && text(good).indexOf('Maya <maya@example.com>') >= 0 &&
        !deck.all(good, (n) => n.tagName === 'INPUT').length);
    });
  })();

  /* the Setup view's Turn on asks which space: it is not given the pack's place in the list */
  (function () {
    const pack = (name) => ({ name: name, description: 'a pack', spaces: [], rules: [], checks: [] });
    const K = page(firstrun('2026-10-03T10:00:00+00:00', true, true), 'setup', Object.assign({}, REPORT, { packs: [pack('one'), pack('two')] }));
    body(K);
    setImmediate(function () {
      const labels = deck.labels(body(K));
      /* c-734: Turn on names the space (each with no pack) or a new one, never the list's index */
      const ons = labels.filter((l) => /^Turn on/.test(l));
      check('setup: every pack\'s Turn on names a space or a new one: ' + JSON.stringify(ons),
        JSON.stringify(ons) === JSON.stringify(['Turn on for personal', 'Turn on for a new space', 'Turn on for personal', 'Turn on for a new space']));
    });
  })();

  /* r2.F7: every core step has its screen; only a pack's own id falls back to the pack screen */
  (function () {
    const K = at('repos');
    check('panels: every core step has an entry in K.startPanels', IDS.every((s) => typeof K.startPanels[s[0]] === 'function'));
    const fr = firstrun(null, true);
    fr.steps.splice(5, 0, { id: 'lost', title: 'A step with no screen', about: 'a', required: false, optional: false, bosun: true,
                            done: false, skipped: null, why: 'w' });
    const lost = at('lost', fr);
    body(lost);
    setImmediate(function () {
      const b = body(lost);
      check('panels: a core step with no screen says so, not "reading the step..." for good',
        text(b).indexOf('reading the step') < 0 && text(b).indexOf('has no screen') >= 0);
    });
  })();

  /* an install that is already set up: every step done, nothing asked, nothing sent */
  (function () {
    const K = at(null, firstrun('2026-10-03T10:00:00+00:00', true, true), null, { ready: true });
    body(K);
    setImmediate(function () {
      const b = body(K);
      const words = deck.byClass(b, 'start-state').map(text);
      /* it opens on the last screen, which has nothing to check and says here */
      check('finished: every step that can be checked says done, and the last screen here', words.filter((w) => w === 'done').length === COUNTED && words.filter((w) => w === 'here').length === 1);
      check('finished: nothing needs you', !stuckOf(b).length);
      check('finished: no Skip, and Finish is the way back only', !named(b, 'Skip') && !named(b, 'Finish') && !!named(b, 'Finished \u00b7 reopen'));
      check('finished: drawing it sent nothing', K._acted.length === 0);
    });
  })();
}

/* c-664: what a Propose says before the tap and after it (K.proposing, app/ui.setup.js), on
   the places that have one: the tier proposal (Setup), the import (Meet Bosun), and the
   one line about flows (How work ships). Each page reads its own Setup report, so the checks run a turn
   after the first draw asked for it. */
function proposing(done) {
  const repo = { key: 'api', path: '/i/spaces/personal/api/repo', ok: true, cloned: true, tier: null, proposal: null };
  const withRepo = (proposal, builder) => Object.assign({}, REPORT, { builder: builder || null,
    spaces: { personal: { pack: null, tier: null, writable: true, proposal: proposal, repos: [repo] } } });
  const at = (step, report) => { const K = page(firstrun(null, true), 'start', report); K.App.step = step; body(K); return K; };
  const keyed = (node, key) => deck.all(node, (n) => n.getAttribute('data-key') === key)[0];
  /* the tier's Propose is Setup's since c-678: the first run's step is Bosun's drafts */
  const setup = (report) => { const K = page(firstrun('2026-10-03T10:00:00+00:00', true, true), 'setup', report); body(K); return K; };
  const before = setup(withRepo(null));
  const queued = setup(withRepo({ card: 'c-9', stage: 'assigned', waiting: false }));
  const open = setup(withRepo({ card: 'c-9', stage: 'building', waiting: false }));
  const asked = setup(withRepo({ card: 'c-9', stage: 'building', waiting: true }));
  const ready = setup(withRepo({ card: 'c-9', stage: 'review', waiting: false }));
  /* c-678: a draft card Bosun has not started does not take Propose away */
  const drafted = setup(withRepo({ card: 'c-9', stage: 'inbox', waiting: false, draft: true }));
  const bosun = { mode: 'in-app', label: 'Builder, auto mode', repos: ['packs'], importing: null };
  const toImport = at('builder', withRepo(null, bosun));
  const importing = at('builder', withRepo(null, Object.assign({}, bosun, { importing: { card: 'c-12', stage: 'assigned', waiting: false } })));
  setImmediate(function () {
    /* c-667: the tier's Adopt says the adoption's own answer (K.sentence), an error when
       the card was not moved */
    let adoptSaid = null;
    ready.act = (sent, word) => { adoptSaid = word({ where: '/t/CLAUDE.md', stage: 'review', note: 'adopted, but c-9 was not moved to done: held' }); return Promise.resolve(null); };
    const adopt = named(body(ready), 'Adopt');
    if (adopt) adopt.onclick({ stopPropagation: function () {} });
    check('propose: Adopt says the adoption\'s answer, as an error when the card was not moved: ' + JSON.stringify(adoptSaid),
      !!adoptSaid && adoptSaid.err === true && /was not moved to done/.test(adoptSaid.text));
    const waits = keyed(body(drafted), 'draft-open-personal');
    check('propose: a draft card nobody has started is said, with its card: ' + (waits && waits.textContent),
      !!waits && /c-9 is open for Bosun to draft/.test(waits.textContent) && deck.all(waits, (n) => n.tagName === 'A')[0].getAttribute('href') === '/?card=c-9');
    check('propose: and Propose is still there', !!named(body(drafted), 'Propose from the space\'s repos'));
    let b = body(before);
    const said = keyed(b, 'proposing-before');
    check('propose: before the tap, what starts and that nothing changes until Adopt',
      !!said && /house/.test(said.textContent) && /draft/.test(said.textContent) && /Nothing changes until you Adopt/.test(said.textContent));
    check('propose: before the tap, that it is a conversation, with the way in and Send back',
      !!said && /Drop in/.test(said.textContent) && /Send back/.test(said.textContent));
    check('propose: the button is still there', !!named(b, 'Propose from the space\'s repos'));
    const queuedSaid = keyed(body(queued), 'proposing-c-9');
    check('propose: a card no session has started on says it waits for one, not that it drafts',
      !!queuedSaid && /will draft/.test(queuedSaid.textContent) && /waiting for a session to start/.test(queuedSaid.textContent) &&
      !/is drafting/.test(queuedSaid.textContent));
    check('propose: a card with no session yet does not say to Drop in now', !!queuedSaid && !/use Drop in there/.test(queuedSaid.textContent) &&
      /once it has started/.test(queuedSaid.textContent));
    const tap = named(body(before), 'Propose from the space\'s repos');
    let toast = null;
    before.act = (bodyOf, word) => { toast = typeof word === 'function' ? word({ card: 'c-9' }) : word; return Promise.resolve({ ok: true }); };
    if (tap) tap._on.onclick({});
    check('propose: the tier toast says the card is filed, not that a house is auditing', !!toast && /filed/.test(toast) && !/is auditing/.test(toast));
    b = body(open);
    let after = keyed(b, 'proposing-c-9');
    const link = after && deck.all(after, (n) => n.tagName === 'A')[0];
    check('propose: after the tap, the card is a link to it', !!link && link.getAttribute('href') === '/?card=c-9');
    check('propose: after the tap, its state in words', !!after && /working/.test(after.textContent));
    check('propose: no Adopt before the draft is ready', !named(b, 'Adopt'));
    after = keyed(body(asked), 'proposing-c-9');
    check('propose: a house that asked is waiting for you', !!after && /waiting for you/.test(after.textContent));
    b = body(ready);
    after = keyed(b, 'proposing-c-9');
    check('propose: a staged draft is ready, with Adopt and Send back', !!after && /draft ready/.test(after.textContent) &&
      /Send back/.test(after.textContent) && !!named(b, 'Adopt'));
    b = body(toImport);
    const bosunSaid = keyed(b, 'proposing-before');
    check('import: before the tap, it is Bosun\'s card and nothing changes until Approve outcome',
      !!bosunSaid && /Bosun/.test(bosunSaid.textContent) && /Approve outcome/.test(bosunSaid.textContent) && !/Adopt/.test(bosunSaid.textContent));
    check('import: the button', !!named(b, 'Import my Claude setup'));
    b = body(importing);
    after = keyed(b, 'proposing-c-12');
    check('import: a card Bosun has not taken does not say it is being worked', !!after && !/Drop in/.test(after.textContent));
    check('import: after the tap, its card and its state, and no second import', !!after && /will draft/.test(after.textContent) && /waiting for Bosun/.test(after.textContent) &&
      deck.all(after, (n) => n.tagName === 'A')[0].getAttribute('href') === '/?card=c-12' && !named(b, 'Import my Claude setup'));
    done();
  });
}
