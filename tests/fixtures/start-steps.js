/* The first run's screens, one block per screen (c-678, the first-run design of c-668), under
 * node against the deck's DOM stand-in. The frame they sit in (the list, Next, the header
 * line, the stuck line) is tests/fixtures/start-deck.js; the page and the state both use are
 * tests/fixtures/start-page.js.
 *
 * Each block draws its pages, waits one turn for the Setup report each page asked for, then
 * checks them and calls `done`. The blocks run one after another and the result is printed
 * by the last one, so no check is ever left scheduled after it.
 *
 * Usage: node start-steps.js <path to app/>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const APP = process.argv[2];
const { deck, check, fails, ready, not, firstrun, REPORT, page, body, named, keyedAll, keyed, stuckOf, text,
        placeOf, ATTACH } = require('./start-page.js')(APP);

/* a page on one step, its report and its state */
const at = (step, fr, report, opts) => { const K = page(fr || firstrun(null, true), 'start', report, opts); K.App.step = step; return K; };
const withStart = (more) => Object.assign({}, REPORT, { start: Object.assign({}, REPORT.start, more) });
const stepOf = (fr, id) => fr.steps[placeOf(id)];
const codes = (node) => (node ? deck.all(node, (n) => n.tagName === 'CODE').map(text) : []);
const tags = (node, tag) => (node ? deck.all(node, (n) => n.tagName === tag) : []);
const press = (button) => { if (button) button._on.onclick({ stopPropagation() {}, preventDefault() {} }); return !!button; };
const has = (node, name) => !!node && deck.hasClass(node, name);
const labels = (node) => (node ? deck.labels(node) : []);
/* a row's state, or null for a row that was not drawn */
const st = (node) => (node ? node.getAttribute('data-state') : null);
const sent = (K, verb) => K._acted.filter((a) => a.verb === verb);

/* Sign in to Claude: the four lines with the one command, the live status in its four
   states, and the one probe the page asks for when the sign-in file appears */
function signin(done) {
  const CMD = 'CLAUDE_CONFIG_DIR=/i/claude /usr/bin/claude auth login';
  const login = (state, why) => withStart({ login: { space: 'personal', state: state, why: why || '', config_dir: '/i/claude',
                                                     fix: 'run claude', command: CMD } });
  const seen = (fr, yes) => { Object.assign(stepOf(fr, 'login'), { seen: yes, stamp: yes ? 1700000000 : null }); return fr; };
  const none = { login: not('the install\'s Claude login is not checked yet', 'login') };
  const waiting = at('login', seen(firstrun(null, false), false), login(null), none);
  const appeared = at('login', seen(firstrun(null, false), true), login(null), none);
  const good = at('login', seen(firstrun(null, true), true), login('good'));
  const unsure = at('login', seen(firstrun(null, true), true), login('unknown', 'no answer in 45s'),
    { login: Object.assign(ready('could not be checked'), { sure: false }) });
  const refused = at('login', seen(firstrun(null, false), true), login('expired', 'Not logged in'),
    { login: not('the install\'s Claude login does not work', 'login') });
  /* outside the first run: the banner on Now and a red Claude row of the Logins list */
  const now = page(firstrun('2026-10-03T10:00:00+00:00', true, true), 'now');
  now.App.data.spaces.personal.login = { state: 'expired', why: 'Login expired', at: '2026-10-03T10:03:00+00:00', fix: 'run claude',
                                         never_logged_in: false, signin: CMD, stamp: 1700000000 };
  now.App.data.health = { level: 'red', reasons: [], services: [], logins: [
    { id: 'claude:personal', kind: 'claude', label: 'Claude personal', host: 'mac', state: 'expired', why: 'Login expired',
      where: '/i/claude', fix: CMD, spaces: ['personal'], stamp: 1700000000 },
    { id: 'claude:talker', kind: 'claude', label: 'Claude talker and voice', host: 'mac', state: 'expired', why: 'Login expired',
      where: '/i/talker', fix: 'CLAUDE_CONFIG_DIR=/i/talker claude auth login', spaces: [], stamp: null },
    { id: 'drive', kind: 'drive', label: 'Drive (the backup store)', host: 'mac', state: 'expired', where: '/r', fix: 'rclone config reconnect x:' }] };
  /* this page's probe answers when the check says so, so the row can be read while it runs */
  let answer = null;
  appeared.act = (sent) => { appeared._acted.push(sent); return new Promise((resolve) => { answer = resolve; }); };
  [waiting, appeared, good, unsure, refused].forEach(body);
  setImmediate(function () {
    let b = body(waiting);
    const lines = keyed(b, 'signin-lines');
    check('signin: four lines, in a list', tags(lines, 'LI').length === 4);
    check('signin: the first line says how to open a terminal', text(lines).indexOf('Open a terminal. (On macOS: press Command and Space, type Terminal, press Return.)') >= 0);
    check('signin: the one command, as the server gave it, with Copy', codes(lines).indexOf(CMD) >= 0 && !!named(lines, 'Copy'));
    check('signin: the last line asks for nothing', text(lines).indexOf('Come back to this page. You do not need to press anything.') >= 0);
    let row = keyed(b, 'signin-status');
    check('signin: the status row is named', text(row).indexOf('Claude sign-in for this install') >= 0);
    check('signin: no sign-in yet is waiting', !!row && row.getAttribute('data-state') === 'waiting' && text(row).indexOf('Waiting for you to sign in.') >= 0);
    check('signin: waiting asks for no probe', waiting._acted.length === 0);
    check('signin: common problems, folded', text(keyed(b, 'signin-problems')).indexOf('command not found: claude') >= 0 &&
      text(keyed(b, 'signin-problems')).indexOf('I signed in but this page still waits.') >= 0);
    check('signin: the line about what is next', text(keyed(b, 'signin-next')) === 'Next you meet your builder. It needs this sign-in to run.');
    check('signin: the old note about a new setup is gone from this step', !keyed(b, 'new-setup'));
    press(named(b, 'Check again'));
    check('signin: Check again asks for the probe', JSON.stringify(waiting._acted) === JSON.stringify([{ verb: 'firstrun.login.check' }]));

    /* the file appeared: the page asks for the one probe, and says so while it runs */
    row = keyed(body(appeared), 'signin-status');
    check('signin: a sign-in that was seen is probed once, by the page', sent(appeared, 'firstrun.login.check').length === 1);
    check('signin: while the probe runs the row says checking', !!row && row.getAttribute('data-state') === 'checking' &&
      text(row).indexOf('Sign-in seen. Making sure it works.') >= 0);
    body(appeared);
    check('signin: a redraw does not ask again', sent(appeared, 'firstrun.login.check').length === 1);

    row = keyed(body(good), 'signin-status');
    check('signin: a login that works is ready', !!row && row.getAttribute('data-state') === 'ready' && text(row).indexOf('Signed in. Shipyard can run sessions.') >= 0);
    check('signin: and nothing is asked', good._acted.length === 0);

    b = body(unsure);
    row = keyed(b, 'stuck-signin-status');
    check('signin: a probe that could not tell says so, with its reason', !!row &&
      text(keyed(row, 'stuck-what')).indexOf('Shipyard could not reach Claude to check (no answer in 45s). Check your connection, then press Check again.') >= 0);
    check('signin: it does not block, so it is the quiet form', !!row && has(row, 'quiet') && text(row).indexOf('needs you') < 0);
    check('signin: its fix is Check again', !!row && !!named(keyed(row, 'stuck-fix'), 'Check again'));
    check('signin: and the page does not probe by itself after a probe that could not tell', unsure._acted.length === 0);

    /* the banner: the same block, folded under Sign in again, with the space's own command */
    b = body(now);
    let fold = keyed(keyed(b, 'login-banner'), 'signin-again-banner-personal');
    check('banner: Sign in again, and the block is folded until it is pressed', !!named(fold, 'Sign in again') && !keyed(fold, 'signin-lines'));
    check('banner: the old bare command is gone', codes(keyed(b, 'login-banner')).indexOf('run claude') < 0);
    press(named(fold, 'Sign in again'));
    fold = keyed(keyed(body(now), 'login-banner'), 'signin-again-banner-personal');
    check('banner: pressed, it is the four lines with the command and Copy', tags(keyed(fold, 'signin-lines'), 'LI').length === 4 &&
      codes(fold).indexOf(CMD) >= 0 && !!named(fold, 'Copy'));
    check('banner: with the live status row', !!keyed(fold, 'signin-status'));
    check('banner: opened on a sign-in file it has not asked about, it probes that space once',
      JSON.stringify(sent(now, 'firstrun.login.check')) === JSON.stringify([{ verb: 'firstrun.login.check', space: 'personal' }]));
    /* the Logins list: a red Claude row draws the block; any other red row keeps its one-liner */
    const list = keyed(b, 'logins-panel');
    const mine = keyed(list, 'mac:claude:personal'), talker = keyed(list, 'mac:claude:talker'), drive = keyed(list, 'mac:drive');
    check('logins: a red Claude row offers Sign in again', !!named(mine, 'Sign in again') && !keyed(mine, 'signin-lines'));
    press(named(mine, 'Sign in again'));
    const opened = keyed(keyed(body(now), 'logins-panel'), 'mac:claude:personal');
    check('logins: pressed, the row draws the same four lines and its command', tags(keyed(opened, 'signin-lines'), 'LI').length === 4 &&
      codes(opened).indexOf(CMD) >= 0);
    const offered = !!named(talker, 'Sign in again');
    press(named(talker, 'Sign in again'));
    const folder = keyed(keyed(body(now), 'logins-panel'), 'mac:claude:talker');
    check('logins: a Claude folder no space runs under has the block and no Check again of its own: ' + JSON.stringify(labels(folder)),
      offered && tags(keyed(folder, 'signin-lines'), 'LI').length === 4 && !named(folder, 'Check again') &&
      text(folder).indexOf('Shipyard checks this sign-in by itself') >= 0);
    check('logins: any other red row keeps its one-liner with Copy', codes(drive).indexOf('rclone config reconnect x:') >= 0 &&
      !!named(drive, 'Copy') && !named(drive, 'Sign in again'));
    if (answer) answer({ ok: true });
    setImmediate(function () {
      /* the probe answered "not signed in": waiting again, and not asked a second time */
      row = keyed(body(appeared), 'signin-status');
      check('signin: after the probe the row is waiting again', !!row && row.getAttribute('data-state') === 'waiting');
      check('signin: a probe that said no is not repeated by a redraw', sent(appeared, 'firstrun.login.check').length === 1);
      body(refused);
      check('signin: an expired login with its file there is probed once on the page', sent(refused, 'firstrun.login.check').length === 1);
      /* a sign-in made after a probe that said no: the file changed, so it is asked about once more */
      stepOf(appeared.App.data.firstrun, 'login').stamp = 1700000600;
      body(appeared); body(appeared);
      check('signin: a sign-in file that changed is probed once more', sent(appeared, 'firstrun.login.check').length === 2);
      done();
    });
  });
}

/* Choose your builder: two option cards, neither preselected, a pick that writes the mode,
   and a pick the server refused; then Meet Bosun: the form chosen, the three checks, how
   to open Bosun's session, and the hello check */
function builders(done) {
  const withBosun = (bosun, builder) => Object.assign(withStart({ bosun: bosun }), { builder: builder || null });
  const BOSUN = { on: true, form: 'guide', workspace: true, refusal: null, missing: [] };
  const step = (id, more) => { const fr = firstrun(null, true); Object.assign(stepOf(fr, id), { done: false }, more); return fr; };
  const none = at('choose-builder', step('choose-builder', { choice: null, skip: false }));
  const full = at('choose-builder', step('choose-builder', { choice: 'full', done: true, skip: false }));
  const refused = at('choose-builder', step('choose-builder', { choice: null, skip: false }));
  refused.act = (sent) => { refused._acted.push(sent); return Promise.resolve(null); };
  refused.refused = () => 'another setup change is running: wait for it to finish';
  const up = { state: 'idle', up: true, attach: ATTACH };
  const down = at('builder', step('builder', { running: false, hello: false }), withBosun(BOSUN), { state: { console: { state: 'never', up: false, attach: ATTACH } } });
  const waitingHello = at('builder', step('builder', { running: true, hello: false }), withBosun(BOSUN), { state: { console: up } });
  const met = at('builder', step('builder', { running: true, hello: true, done: true }),
    withBosun(Object.assign({}, BOSUN, { form: 'full' }), { mode: 'in-app', label: 'Builder, bypass', repos: ['packs'], importing: null }),
    { state: { console: up } });
  const unseen = at('builder', step('builder', { running: true, hello: false, hidden: true, done: true, sure: false }),
    withBosun(BOSUN), { state: { console: up } });
  const broken = at('builder', step('builder', { running: false, hello: false }),
    withBosun({ on: true, form: 'guide', workspace: false, missing: ['packs'],
                refusal: 'the builder has no clone of packs under /i/builder, and none could be made' }),
    { state: { console: { state: 'never', up: false, attach: ATTACH } }, builder: false });
  const failing = at('builder', step('builder', { running: false, hello: false }), withBosun(BOSUN), { state: { console: { state: 'never', up: false, attach: ATTACH } } });
  failing.act = (sent) => { failing._acted.push(sent); return Promise.resolve(null); };
  failing.refused = () => 'claude --bg printed no session id';
  [none, full, refused, down, waitingHello, met, unseen, broken, failing].forEach(body);
  setImmediate(function () {
    let b = body(none);
    const cards = keyed(b, 'builder-forms');
    const opts = cards ? deck.all(cards, (n) => n.getAttribute('role') === 'radio') : [];
    check('builder: two option cards, Full then Guide', opts.length === 2 && text(opts[0]).indexOf('Full builder') === 0 && text(opts[1]).indexOf('Guide builder') === 0);
    check('builder: neither is preselected', opts.every((o) => o.getAttribute('aria-checked') === 'false') && !named(b, 'Chosen'));
    check('builder: each says what you gain, do by hand, what it builds and what to know',
      opts.every((o) => ['What you gain', 'What you do by hand', 'What it can build', 'What to know'].every((l) => text(o).indexOf(l) >= 0)));
    check('builder: Full says it in one line, and that nothing reviews its commands', text(opts[0]).indexOf('It can fix things for you.') >= 0 &&
      text(opts[0]).indexOf('Nothing reviews its commands.') >= 0);
    check('builder: Guide says it in one line, and that it installs nothing', text(opts[1]).indexOf('It explains, you do.') >= 0 &&
      text(opts[1]).indexOf('It will not install software or change settings on this computer') >= 0);
    check('builder: the line for someone who is not sure', text(keyed(b, 'builder-unsure')) === 'Not sure? Start with Guide. You can switch in Settings.');
    check('builder: What is a builder, folded', text(keyed(b, 'builder-what')).indexOf('It is your builder') >= 0);
    check('builder: no Skip, and Continue waits for a pick', !named(b, 'Skip') && !!named(b, 'Continue') && named(b, 'Continue').hasAttribute('disabled') &&
      text(keyed(b, 'start-hint')) === 'Pick a builder to continue.');
    press(named(b, 'Choose guide builder'));
    check('builder: a pick is one save, builder mode on and the form\'s mode: ' + JSON.stringify(none._acted),
      JSON.stringify(none._acted) === JSON.stringify([{ verb: 'setup.settings.save', changes: [
        { table: 'keel', key: 'bosun_builder', value: true }, { table: 'builder', key: 'mode', value: 'auto' }] }]));
    b = body(full);
    const chosen = keyed(b, 'builder-full');
    check('builder: the chosen form is marked, and Continue is on', !!chosen && chosen.getAttribute('aria-checked') === 'true' &&
      !!named(chosen, 'Chosen') && !named(b, 'Continue').hasAttribute('disabled'));
    press(named(body(full), 'Choose guide builder'));
    check('builder: switching sends the other mode', full._acted.length === 1 && full._acted[0].changes[1].value === 'auto');
    press(named(body(refused), 'Choose full builder'));

    /* Meet Bosun */
    b = body(down);
    check('bosun: the line for the form chosen, with Change', text(keyed(b, 'bosun-form')).indexOf(
      'You chose the guide builder. Bosun explains and points. Where a fix needs a command, it gives it to you to run.') >= 0 &&
      !!named(keyed(b, 'bosun-form'), 'Change'));
    press(named(keyed(b, 'bosun-form'), 'Change'));
    check('bosun: Change goes back to Choose your builder', down.App.step === 'choose-builder');
    down.App.step = 'builder';
    b = body(down);
    check('bosun: the builder is switched on, in the form\'s words', text(keyed(b, 'bosun-on')).indexOf('Builder is switched on') >= 0 &&
      text(keyed(b, 'bosun-on')).indexOf('On, guide builder') >= 0);
    check('bosun: its workspace is ready', st(keyed(b, 'bosun-workspace')) === 'ready' &&
      text(keyed(b, 'bosun-workspace')).indexOf('Its own copy of this install\'s add-ons is in place') >= 0);
    let row = keyed(b, 'stuck-bosun-running');
    check('bosun: not running needs you, with Start Bosun', !!row && text(row).indexOf('Not started.') >= 0 && !!named(row, 'Start Bosun'));
    check('bosun: that row has no "or ask Bosun" part: Bosun is the thing that is down', !!row && !keyed(row, 'stuck-bosun'));
    const open = keyed(b, 'bosun-open');
    check('bosun: how to open its session: the command with Copy', text(open).indexOf('Open Bosun\'s session') >= 0 &&
      text(open).indexOf('In a terminal, run this:') >= 0 && codes(open).indexOf(ATTACH) >= 0 && !!named(open, 'Copy'));
    check('bosun: or the Claude app, and what to do there', text(open).indexOf('Or open Bosun in the Claude app: it is the session named Bosun.') >= 0 &&
      text(open).indexOf('Say hello there. Then come back to this page.') >= 0);
    let hello = keyed(b, 'bosun-hello');
    check('bosun: hello waits for Bosun to start', !!hello && hello.getAttribute('data-state') === 'waiting' && text(hello).indexOf('Start Bosun first') >= 0);
    check('bosun: Next waits for it', named(b, 'Next').hasAttribute('disabled') && !!named(b, 'Skip'));
    press(named(row, 'Start Bosun'));
    check('bosun: Start Bosun is the console\'s own start tap', JSON.stringify(sent(down, 'console.start')) === JSON.stringify([{ verb: 'console.start' }]));
    check('bosun: while it starts the row says so', text(keyed(body(down), 'bosun-running')).indexOf('Starting (a few seconds)') >= 0);

    b = body(waitingHello);
    check('bosun: running, the row is ready', st(keyed(b, 'bosun-running')) === 'ready' &&
      text(keyed(b, 'bosun-running')).indexOf('Running, idle') >= 0 && !named(b, 'Start Bosun'));
    hello = keyed(b, 'bosun-hello');
    check('bosun: hello waits for the first message, and says how it will know', text(hello).indexOf('Waiting for your first message') >= 0 &&
      text(hello).indexOf('This row turns green when Bosun\'s session has a message from you.') >= 0);
    hello = keyed(body(unseen), 'bosun-hello');
    check('bosun: a session Shipyard cannot see into is said so, and no hello is asked for again: ' + text(hello),
      text(hello).indexOf('Shipyard cannot see into Bosun\'s session from here, so this row cannot turn green. Go on when you have said hello.') >= 0 &&
      text(hello).indexOf('Waiting for your first message') < 0);
    b = body(met);
    check('bosun: hello ready', st(keyed(b, 'bosun-hello')) === 'ready' &&
      text(keyed(b, 'bosun-hello')).indexOf('Bosun\'s session has your first message.') >= 0);
    check('bosun: the full builder\'s line', text(keyed(b, 'bosun-form')).indexOf(
      'You chose the full builder. Where a fix needs a command, Bosun can run it for you if you ask it in its session.') >= 0);
    check('bosun: Next is on once Bosun runs and has the message', !named(b, 'Next').hasAttribute('disabled'));
    const bring = keyed(b, 'bosun-import');
    check('bosun: the import is a quiet link, with the button inside it', !!bring &&
      text(tags(bring, 'SUMMARY')[0]) === 'Bring over my own Claude instructions and skills' && !!named(bring, 'Import my Claude setup'));
    check('bosun: the old note about a new setup is gone', !keyed(b, 'new-setup') && !keyed(body(none), 'new-setup'));

    b = body(broken);
    row = keyed(b, 'stuck-bosun-running');
    check('bosun: a missing workspace is said in the design\'s sentence', !!row &&
      text(keyed(row, 'stuck-what')).indexOf('Bosun could not start: its own copy of this install\'s add-ons is missing.') >= 0);
    check('bosun: with Start again and Copy details', !!named(row, 'Start again') && !!named(row, 'Copy details'));
    check('bosun: and that there is no session to ask yet', text(row).indexOf('Bosun is down, so there is no session to ask yet.') >= 0 && !keyed(row, 'stuck-bosun'));
    check('bosun: no header line while Bosun cannot run', !keyed(b, 'bosun-line'));
    press(named(keyed(body(failing), 'stuck-bosun-running'), 'Start Bosun'));
    setImmediate(function () {
      const said = keyed(body(refused), 'builder-not-saved');
      check('builder: a pick that was not saved says so, with Try again', text(said).indexOf('Your choice was not saved.') >= 0 &&
        text(said).indexOf('Another setup change is still running. Try again in a moment.') >= 0 && !!named(said, 'Try again'));
      press(named(said, 'Try again'));
      check('builder: Try again sends the same pick', refused._acted.length === 2 && refused._acted[1].changes[1].value === 'bypass');
      row = keyed(body(failing), 'stuck-bosun-running');
      check('bosun: a start that was refused says why, in the server\'s words', !!row &&
        text(keyed(row, 'stuck-what')).indexOf('Bosun could not start: claude --bg printed no session id.') >= 0 && !!named(row, 'Start again'));
      done();
    });
  });
}

/* Add your repos: the space named once, a panel per repo, Add another repo always there,
   adds sent one at a time, and a copy that failed drawn by its kind */
function repos(done) {
  const repo = (key, more) => Object.assign({ key: key, path: '/i/spaces/work/' + key + '/repo', ok: true, cloned: true,
    origin: 'https://github.com/maya-okafor/' + key, branch: 'main', tier: null, proposal: null }, more);
  const personal = { pack: null, tier: null, writable: true, proposal: null,
    repos: [{ key: 'packs', path: '/i/packs', ok: true, cloned: false, origin: null, branch: 'main', tier: null, proposal: null },
            { key: 'memory', path: '/i/memory', ok: true, cloned: false, origin: null, branch: 'main', tier: null, proposal: null }] };
  const withWork = (list) => Object.assign({}, REPORT, { spaces: { personal: personal,
    work: { pack: null, tier: null, writable: true, proposal: null, repos: list } } });
  const fresh = at('repos', null, Object.assign({}, REPORT, { spaces: { personal: personal } }));
  const two = at('repos', null, withWork([repo('api'), repo('web', { origin: null })]));
  /* each page answers its adds when the check says so */
  const answers = [];
  [fresh, two].forEach(function (K) {
    K.act = (sent) => { K._acted.push(sent); return new Promise((resolve) => { answers.push({ K: K, sent: sent, resolve: resolve }); }); };
  });
  const refuse = (K, verb, detail, error) => { K.refusal = () => ({ error: error || 'git clone failed', detail: detail }); };
  const type = (b, label, value) => {
    const input = deck.all(b, (n) => n.tagName === 'INPUT' && n.getAttribute('aria-label') === label)[0];
    if (input) input._on.oninput({ target: { value: value } });
    return input;
  };
  const field = (b, label) => deck.all(b, (n) => n.tagName === 'INPUT' && n.getAttribute('aria-label') === label)[0];
  [fresh, two].forEach(body);
  setImmediate(function () {
    let b = body(fresh);
    const space = field(b, 'Space name');
    check('repos: the space is named work, and may be renamed', !!space && space.value === 'work' && !space.hasAttribute('disabled'));
    check('repos: the install\'s own packs and memory repos are not the user\'s', text(keyed(b, 'repo-count')) === 'Your repos (0)' &&
      text(keyed(b, 'repo-list')).indexOf('No repos yet. Add the first one above.') >= 0);
    check('repos: with none, the form reads Add a repo', text(tags(keyed(b, 'repo-add'), 'H3')[0]) === 'Add a repo' &&
      text(keyed(b, 'repo-add')).indexOf('The URL you would give to git clone, or the path of a folder on this computer.') >= 0);
    /* c-729: the choice is at the top, a copy chosen, and the form follows it */
    const how = keyed(b, 'repo-how');
    check('repos: the choice at the top, Copy a repo chosen', !!how && how.getAttribute('role') === 'radiogroup' &&
      keyed(how, 'repo-how-copy').getAttribute('aria-checked') === 'true' &&
      keyed(how, 'repo-how-folder').getAttribute('aria-checked') === 'false' && !keyed(b, 'repo-attach'));
    type(b, 'Repo address or folder', 'https://github.com/maya-okafor/api.git');
    check('repos: the short name is filled from the address', field(body(fresh), 'Short name').value === 'api');
    press(named(body(fresh), 'Add repo'));
    type(body(fresh), 'Repo address or folder', 'git@github.com:maya-okafor/web.git');
    press(named(body(fresh), 'Add repo'));
    b = body(fresh);
    check('repos: an add is one verb with the space, the address and the name: ' + JSON.stringify(fresh._acted),
      JSON.stringify(fresh._acted) === JSON.stringify([{ verb: 'setup.repo.add', space: 'work', url: 'https://github.com/maya-okafor/api.git', key: 'api' }]));
    check('repos: the fields clear after an add', field(b, 'Repo address or folder').value === '' && field(b, 'Short name').value === '');
    check('repos: the space name is fixed once a repo is on its way', field(b, 'Space name').hasAttribute('disabled') &&
      text(keyed(b, 'repo-space')).indexOf('Fixed once the first repo is in.') >= 0);
    check('repos: two panels, and the form reads Add another repo', text(keyed(b, 'repo-count')) === 'Your repos (2)' &&
      text(tags(keyed(b, 'repo-add'), 'H3')[0]) === 'Add another repo');
    const first = keyed(b, 'adding-1'), second = keyed(b, 'adding-2');
    check('repos: the first is copying, with its three checks', st(first) === 'copying' &&
      text(first).indexOf('Copying, large repos take a minute') >= 0 && text(first).indexOf('Has a home address') >= 0 &&
      text(first).indexOf('Main branch') >= 0);
    check('repos: the second waits its turn, and is not sent yet', text(second).indexOf('Waiting for the copy before it') >= 0 &&
      fresh._acted.length === 1);

    /* an install with two repos in: a ready one in one line, and one that has no home address */
    b = body(two);
    check('repos: a space that is there is the space, and its name is not asked', field(b, 'Space name').value === 'work' &&
      field(b, 'Space name').hasAttribute('disabled'));
    const api = keyed(b, 'repo-work/api'), web = keyed(b, 'repo-work/web');
    check('repos: a ready repo is one line, with its address and Remove', st(api) === 'ready' &&
      text(api).indexOf('Copied. It has a home address, and the main branch is out.') >= 0 &&
      text(api).indexOf('https://github.com/maya-okafor/api') >= 0 && !!named(api, 'Remove'));
    check('repos: a copy with no home address needs you, and says so in the check', st(web) === 'needs' &&
      !!keyed(web, 'stuck-home-web') && text(keyed(web, 'copied-web')).indexOf('Done') >= 0);
    keyed(b, 'repo-how-folder')._on.onclick({});
    b = body(two);
    const fold = keyed(b, 'repo-attach');
    check('repos: Use a folder in place, chosen at the top, with what it costs', !!fold &&
      text(tags(fold, 'H3')[0]) === 'Use a folder you already have' && text(fold).indexOf('A copy is safer.') >= 0 &&
      !!named(fold, 'Attach') && !keyed(b, 'repo-add') &&
      keyed(b, 'repo-how-folder').getAttribute('aria-checked') === 'true');
    keyed(b, 'repo-how-copy')._on.onclick({});
    b = body(two);
    two._win.confirm = () => true;
    press(named(api, 'Remove'));
    check('repos: Remove is Setup\'s own verb', JSON.stringify(two._acted) === JSON.stringify([{ verb: 'setup.repo.remove', space: 'work', key: 'api' }]));

    /* the first copy lands: it leaves the page's list, and the next is sent once the report is back */
    answers[0].resolve({ ok: true });
    setImmediate(function () {
      b = body(fresh);
      /* c-729: it stays as copied until a report lists it, so the row never drops out and comes back */
      check('repos: a copy that landed stays, copied, until the report lists it', !!keyed(b, 'adding-1') &&
        text(keyed(b, 'copied-1')).indexOf('Done') >= 0);
      const listed = withWork([repo('api')]);
      listed.spaces.work.repos[0].key = 'api';
      const kept = fresh.setupParts.report;
      fresh.setupParts.report = () => listed;
      check('repos: and leaves the page\'s own list once one does', !keyed(body(fresh), 'adding-1'));
      fresh.setupParts.report = kept;
      b = body(fresh);
      check('repos: then the next add is sent', fresh._acted.length === 2 && fresh._acted[1].url === 'git@github.com:maya-okafor/web.git');
      refuse(fresh, 'setup.repo.add', { kind: 'ssh', sentence: 'This address uses SSH, and this computer has no SSH key that host accepts.',
        git: 'git@github.com: Permission denied (publickey).', https: 'https://github.com/maya-okafor/web.git' });
      answers.filter((a) => a.K === fresh)[1].resolve(null);
      setImmediate(function () {
        b = body(fresh);
        const failed = keyed(b, 'adding-2');
        const row = keyed(failed, 'stuck-copied-2');
        check('repos: a copy that failed needs you, in the sentence for its kind', st(failed) === 'needs' &&
          text(keyed(row, 'stuck-what')).indexOf('This address uses SSH, and this computer has no SSH key that host accepts.') >= 0);
        check('repos: git\'s own line is shown as it came', text(keyed(row, 'repo-git')) === 'git@github.com: Permission denied (publickey).');
        check('repos: and it ends with Bosun\'s session', !!keyed(row, 'stuck-bosun'));
        press(named(row, 'Use the https address'));
        b = body(fresh);
        check('repos: Use the https address sends the same repo by https, in one tap', fresh._acted.length === 3 &&
          fresh._acted[2].url === 'https://github.com/maya-okafor/web.git' && fresh._acted[2].key === 'web');
        refuse(fresh, 'setup.repo.add', { kind: 'nosuch', sentence: 'There is no repo at that address. Check the spelling, or open it in your browser to make sure it exists.',
          git: 'fatal: repository not found' });
        answers.filter((a) => a.K === fresh)[2].resolve(null);
        setImmediate(function () {
          b = body(fresh);
          const gone = keyed(keyed(b, 'adding-2'), 'stuck-copied-2');
          check('repos: no such repo offers Edit the address, and no retry', !!named(gone, 'Edit the address') && !named(gone, 'Try the copy again'));
          press(named(gone, 'Edit the address'));
          b = body(fresh);
          check('repos: Edit the address puts it back in the form and drops the panel', !keyed(b, 'adding-2') &&
            field(b, 'Repo address or folder').value === 'https://github.com/maya-okafor/web.git' && field(b, 'Short name').value === 'web');
          press(named(b, 'Add repo'));
          body(fresh);
          refuse(fresh, 'setup.repo.add', { kind: 'host', sentence: 'git.example.org did not let this computer read that repo.',
            git: 'fatal: Authentication failed', needs: 'git.example.org needs a key or a saved password for git. Set one up, then try again.' });
          answers.filter((a) => a.K === fresh)[3].resolve(null);
          setImmediate(function () {
            const host = keyed(keyed(body(fresh), 'adding-3'), 'stuck-copied-3');
            check('repos: another host says what it needs, with Try the copy again', text(host).indexOf('git.example.org needs a key or a saved password for git.') >= 0 &&
              !!named(host, 'Try the copy again'));
            done();
          });
        });
      });
    });
  });
}

/* How Keel remembers: four layers top to bottom, each with where it lives, who writes it and
   who may change it; the workspace file dashed with one repo; nothing to press but Next */
function memory(done) {
  const MEM = { layout: '/i/spaces', rules: '/code/etc/house-contract.md', bosun: '/code/bosun/memory',
                spaces: [{ name: 'work', tier: '/i/spaces/work/CLAUDE.md', repos: [{ key: 'api', tier: '/i/spaces/work/api/CLAUDE.md' },
                                                                                    { key: 'web', tier: '/i/spaces/work/web/CLAUDE.md' }] }] };
  const two = at('memory', null, withStart({ memory: MEM }));
  const one = at('memory', null, withStart({ memory: Object.assign({}, MEM, { spaces: [{ name: 'work', tier: '/i/spaces/work/CLAUDE.md',
    repos: [{ key: 'api', tier: '/i/spaces/work/api/CLAUDE.md' }] }] }) }));
  const none = at('memory', null, withStart({ memory: Object.assign({}, MEM, { spaces: [] }) }));
  [two, one, none].forEach(body);
  setImmediate(function () {
    let b = body(two);
    const layers = keyedAll(b, 'memory-layer');
    const heads = layers.map((l) => text((tags(l, 'H3')[0] || { childNodes: [] }).childNodes[0]));
    check('memory: four layers, top to bottom: ' + JSON.stringify(heads), JSON.stringify(heads) ===
      JSON.stringify(['Workspace CLAUDE.md', 'Each repo\'s CLAUDE.md', 'Rules', 'Bosun\'s own memory']));
    check('memory: "then" between them', keyedAll(b, 'memory-then').length === 3);
    check('memory: each says where it lives, who writes it and who may change it', layers.every((l) =>
      ['Where it lives', 'Who writes it', 'Who may change it'].every((w) => text(l).indexOf(w) >= 0)));
    check('memory: the workspace file\'s meaning and its real path', text(layers[0]).indexOf('What is true across your repos: how they fit together, shared conventions, which repo owns what.') >= 0 &&
      text(layers[0]).indexOf('/i/spaces/work/CLAUDE.md') >= 0 && !has(layers[0], 'off'));
    check('memory: each repo\'s file, by its real path', text(layers[1]).indexOf('/i/spaces/work/api/CLAUDE.md') >= 0 &&
      text(layers[1]).indexOf('/i/spaces/work/web/CLAUDE.md') >= 0);
    check('memory: the team\'s own file is left alone and not read', text(layers[1]).indexOf(
      'The CLAUDE.md your team keeps inside the repo is not changed, and Shipyard\'s sessions do not read it: Bosun reads it once and carries over what is worth keeping.') >= 0);
    check('memory: the rules, and where they are', text(layers[2]).indexOf('enforced, not just read') >= 0 &&
      text(layers[2]).indexOf('/code/etc/house-contract.md') >= 0 && text(layers[2]).indexOf('A session cannot change them.') >= 0);
    check('memory: Bosun\'s memory, where the code keeps it', text(layers[3]).indexOf('/code/bosun/memory') >= 0 &&
      text(layers[3]).indexOf('Bosun proposes changes as cards, and you approve them.') >= 0);
    const under = keyed(b, 'memory-under');
    check('memory: the lines under the picture, which say who reads what', text(under).indexOf('Every card\'s session reads the first three; Bosun reads its own memory.') >= 0 &&
      text(under).indexOf('Every session Shipyard starts') < 0 &&
      text(under).indexOf('nothing is written without you seeing it first.') >= 0 &&
      text(tags(under, 'STRONG')[0]) === 'Bosun writes the first draft of each with you in the next step.');
    check('memory: no button but the way on, and no Skip: ' + JSON.stringify(labels(keyed(b, 'screen-memory'))),
      JSON.stringify(labels(keyed(b, 'screen-memory'))) === JSON.stringify(['Back', 'Next', 'Finish']) &&
      !named(b, 'Next').hasAttribute('disabled'));
    check('memory: drawing it sent nothing', two._acted.length === 0);
    const single = keyedAll(body(one), 'memory-layer')[0];
    check('memory: with one repo the workspace layer is dashed, and says when it applies', has(single, 'off') &&
      text(single).indexOf('only with more than one repo') >= 0);
    const empty = keyedAll(body(none), 'memory-layer');
    check('memory: with no repo yet it says where the files will be', text(empty[1]).indexOf('/i/spaces/<space>/<repo>/CLAUDE.md') >= 0);
    done();
  });
}

/* Set up your repos with Bosun: the hand-over, what Bosun will ask, and what came back: a
   row per file with its state, the draft read as text, Adopt, and Skip for now */
function drafts(done) {
  let workspace = null;
  const TEXT = '# api: how to work in this repo\n\n## Prepare and test\n- Prepare a fresh copy: `npm ci`\n- Run the tests: `npm test`\n';
  const CMDS = { prepare: { value: 'npm ci', line: 4 }, test: { value: 'npm test', line: 5 }, lands: { value: 'main', line: 8 }, run: null };
  const full = (key, state, more) => Object.assign({ aim: 'work/' + key, label: key + '/CLAUDE.md', path: '/i/spaces/work/' + key + '/CLAUDE.md',
    state: state, card: state === 'adopted' ? null : 'c-' + key, text: state === 'ready' || state === 'adopted' ? TEXT : null,
    commands: state === 'ready' || state === 'adopted' ? CMDS : null }, more);
  const light = (row) => ({ aim: row.aim, label: row.label, path: row.path, state: row.state, card: row.card, space: 'work',
    stamp: row.text ? 1700000000 : null, lines: row.lines || null });
  const withRows = (rows) => Object.assign(withStart({ bosun: { on: true, form: 'guide', workspace: true, refusal: null, missing: [] } }),
    { spaces: { personal: REPORT.spaces.personal, work: { pack: null, tier: null, writable: true, proposal: null, repos: [], drafts: rows } } });
  const up = { state: { console: { state: 'idle', up: true, attach: ATTACH } } };
  const open = (rows, opts, done_) => {
    const fr = firstrun(null, true);
    Object.assign(stepOf(fr, 'rules'), { done: !!done_, drafts: rows.map(light) });
    return at('rules', fr, withRows(rows), opts || up);
  };
  const mixed = open([full('api', 'ready'), full('web', 'drafting'), full('docs', 'idle'), full('old', 'idle', { card: null })]);
  const adopted = open([full('api', 'adopted'), full('web', 'adopted')], up, true);
  const down = open([full('api', 'adopted'), full('web', 'drafting'), full('docs', 'idle')],
    { state: { console: { state: 'stopped', up: false, attach: ATTACH } } });
  const stood = open([full('api', 'adopted', { lines: 'changed' }), full('web', 'adopted', { lines: 'never' }),
                      full('docs', 'adopted', { lines: 'run' })], up, true);
  [mixed, adopted, down, stood].forEach(body);
  setImmediate(function () {
    let b = body(mixed);
    const hand = keyed(b, 'drafts-hand');
    check('drafts: 1. Hand over to Bosun, with the command and Copy', text(tags(hand, 'H3')[0]) === '1. Hand over to Bosun' &&
      text(hand).indexOf('Open Bosun\'s session and tell it to start. In a terminal, run this:') >= 0 && codes(hand).indexOf(ATTACH) >= 0);
    check('drafts: a first thing to say, with Copy', text(hand).indexOf('Or open Bosun in the Claude app. If you want a first thing to say, say this:') >= 0 &&
      codes(hand).indexOf('Set up my repos.') >= 0 && labels(hand).filter((l) => l === 'Copy').length === 2);
    check('drafts: the line for the guide builder', text(hand).indexOf('Guide builder: Bosun explains and asks. Where a command has to run, it gives it to you.') >= 0);
    const ask = keyed(b, 'drafts-ask');
    check('drafts: 2. What Bosun will ask about, three things (c-734: never where work lands)', text(tags(ask, 'H3')[0]) === '2. What Bosun will ask about' &&
      text(ask).indexOf('This is a conversation, not a form. So you know what is coming:') >= 0 && tags(ask, 'LI').length === 3 &&
      text(ask).indexOf('Until this is written, sessions run tests only.') >= 0);
    const back = keyed(b, 'drafts-back');
    check('drafts: 3. What came back, and what the list is', text(tags(back, 'H3')[0]) === '3. What came back' &&
      text(back).indexOf('This list updates while Bosun works. Read each draft, then Adopt it. Adopt writes the file.') >= 0);
    const rows = keyedAll(back, 'draft-row');
    check('drafts: a row per file, in order, with its path', JSON.stringify(rows.map((r) => text(keyed(r, 'draft-label')))) ===
      JSON.stringify(['api/CLAUDE.md', 'web/CLAUDE.md', 'docs/CLAUDE.md', 'old/CLAUDE.md']) && text(rows[0]).indexOf('/i/spaces/work/api/CLAUDE.md') >= 0);
    check('drafts: each row says its state', JSON.stringify(rows.map((r) => text(keyed(r, 'draft-pill')))) ===
      JSON.stringify(['ready for you', 'Bosun is drafting', 'not started', 'not started']));
    const ready = rows[0];
    check('drafts: a ready row shows the commands and the line each came from', text(keyed(ready, 'draft-commands')).indexOf('npm ci') >= 0 &&
      text(keyed(ready, 'draft-commands')).indexOf('(line 4 of the file)') >= 0 && text(keyed(ready, 'draft-commands')).indexOf('(line 5)') >= 0);
    /* c-734: a lands line still in a file is said to move nothing */
    check('drafts: a lands line is said to move nothing', codes(keyed(ready, 'draft-lands')).indexOf('main') >= 0 &&
      text(keyed(ready, 'draft-lands')).indexOf('(line 8: not read. Shipyard moves nothing for it.') >= 0);
    check('drafts: with Read the draft and Adopt, and the text folded', !!named(ready, 'Read the draft') && !!named(ready, 'Adopt') && !keyed(ready, 'draft-text'));
    check('drafts: a row Bosun is drafting has no button', labels(rows[1]).length === 0);
    check('drafts: a row with no card offers to open one', !!named(rows[3], 'Open a draft for Bosun') && !named(rows[2], 'Open a draft for Bosun'));
    press(named(rows[3], 'Open a draft for Bosun'));
    check('drafts: which is the user\'s tap', JSON.stringify(mixed._acted) === JSON.stringify([{ verb: 'setup.tier.draft', space: 'work', key: 'old' }]));
    press(named(ready, 'Read the draft'));
    let opened = keyedAll(keyed(body(mixed), 'drafts-back'), 'draft-row')[0];
    check('drafts: opened, the draft is read as text under its path', text(keyed(opened, 'draft-text')).indexOf('Draft of /i/spaces/work/api/CLAUDE.md') >= 0 &&
      text(tags(keyed(opened, 'draft-text'), 'PRE')[0]) === TEXT);
    check('drafts: with Adopt, Tell Bosun what to change and Close', JSON.stringify(labels(keyed(opened, 'draft-text'))) ===
      JSON.stringify(['Adopt', 'Tell Bosun what to change', 'Close']));
    press(named(opened, 'Tell Bosun what to change'));
    opened = keyedAll(keyed(body(mixed), 'drafts-back'), 'draft-row')[0];
    check('drafts: Tell Bosun what to change only says where to say it', text(keyed(opened, 'draft-tell')).indexOf(
      'Tell Bosun in its session what to change. This draft updates when Bosun has changed it. Nothing is written until you press Adopt.') >= 0 &&
      codes(keyed(opened, 'draft-tell')).indexOf(ATTACH) >= 0 && mixed._acted.length === 1);
    press(named(keyed(opened, 'draft-text'), 'Adopt'));
    check('drafts: Adopt is the tier\'s own adopt, for that card', JSON.stringify(mixed._acted[1]) === JSON.stringify({ verb: 'setup.tier.adopt', card: 'c-api' }));
    press(named(keyedAll(keyed(body(mixed), 'drafts-back'), 'draft-row')[0], 'Close'));
    check('drafts: Close folds it again', !keyed(keyedAll(keyed(body(mixed), 'drafts-back'), 'draft-row')[0], 'draft-text'));
    const skip = keyed(b, 'drafts-skip');
    check('drafts: Skip for now says what is lost', text(skip).indexOf('Sessions will work in these repos with no guidance and will run tests only if they can find them.') >= 0 &&
      text(skip).indexOf('Next turns on when every repo\'s CLAUDE.md is adopted.') >= 0);
    press(named(skip, 'Skip for now'));
    check('drafts: and skips the step', JSON.stringify(mixed._acted[2]) === JSON.stringify({ verb: 'firstrun.skip', step: 'rules' }));
    check('drafts: Next waits for the files', named(b, 'Next').hasAttribute('disabled'));
    check('drafts: Bosun running, nothing at the top needs you', !keyed(b, 'stuck-drafts-bosun'));

    b = body(adopted);
    const done_ = keyedAll(keyed(b, 'drafts-back'), 'draft-row')[0];
    check('drafts: an adopted row keeps its commands, with Read the file', text(keyed(done_, 'draft-pill')) === 'adopted' &&
      !!keyed(done_, 'draft-commands') && !!named(done_, 'Read the file') && !named(done_, 'Adopt'));
    press(named(done_, 'Read the file'));
    check('drafts: read, it says where it was written', text(keyed(keyedAll(keyed(body(adopted), 'drafts-back'), 'draft-row')[0], 'draft-text')).indexOf(
      'Written to /i/spaces/work/api/CLAUDE.md') >= 0);
    check('drafts: every repo adopted, Next is on', !named(body(adopted), 'Next').hasAttribute('disabled'));
    /* whether an adopted file's lines run (the record of what the user adopted or saved) */
    const lines = (row) => keyed(row, 'draft-lines');
    check('drafts: a file whose lines run says nothing more', !lines(done_));
    const three = keyedAll(keyed(body(stood), 'drafts-back'), 'draft-row');
    check('drafts: a file changed since it was adopted says its lines do not run: ' + text(lines(three[0])),
      text(lines(three[0])) === 'This file changed since it was adopted or saved, so Shipyard runs none of its lines and will not land this repo\'s cards. Read the file, then press Keep this text.' &&
      text(keyed(three[0], 'draft-pill')) === 'changed since');
    check('drafts: a file never adopted or saved says how to turn its lines on: ' + text(lines(three[1])),
      text(lines(three[1])) === 'This file has not been adopted or saved yet, so Shipyard runs none of its lines. Read the file, then press Keep this text to turn them on.' &&
      text(keyed(three[1], 'draft-pill')) === 'not saved yet');
    check('drafts: beside one whose lines run', !lines(three[2]) && text(keyed(three[2], 'draft-pill')) === 'adopted');
    /* review r2.F12: the row can be left from here. The text is read first, then kept */
    check('drafts: Keep this text is not offered before the file is read', !named(three[0], 'Keep this text') && !!named(three[0], 'Read the file'));
    press(named(three[0], 'Read the file'));
    press(named(keyedAll(keyed(body(stood), 'drafts-back'), 'draft-row')[2], 'Read the file'));
    const read = keyedAll(keyed(body(stood), 'drafts-back'), 'draft-row');
    check('drafts: read, the file\'s text is shown with Keep this text', text(keyed(read[0], 'draft-text')).indexOf('Run the tests: `npm test`') >= 0 &&
      !!named(keyed(read[0], 'draft-text'), 'Keep this text'));
    check('drafts: a file whose lines run has nothing to keep: ' + JSON.stringify(labels(read[2])), !!keyed(read[2], 'draft-text') && !named(read[2], 'Keep this text'));
    const acts = stood._acted.length;
    press(named(read[0], 'Keep this text'));
    const kept = sent(stood, 'setup.tier.save')[0];
    check('drafts: Keep this text saves the text that was read, as the user\'s own Save: ' + JSON.stringify(kept), stood._acted.length === acts + 1 &&
      !!kept && kept.space === 'work' && kept.key === 'api' && kept.text === TEXT);

    b = body(down);
    const top = keyed(b, 'stuck-drafts-bosun');
    check('drafts: Bosun not running is said at the top, with why', text(keyed(top, 'stuck-what')).indexOf(
      'Bosun is not running, so nothing is being drafted. Bosun reads your repos and drafts these files with you in its session.') >= 0);
    check('drafts: its fix is Start Bosun, and it has no "or ask Bosun" part', !!named(top, 'Start Bosun') && !keyed(top, 'stuck-bosun'));
    check('drafts: every row not yet adopted says Bosun is not running', JSON.stringify(keyedAll(keyed(b, 'drafts-back'), 'draft-pill').map(text)) ===
      JSON.stringify(['adopted', 'Bosun is not running', 'Bosun is not running']));
    press(named(top, 'Start Bosun'));
    check('drafts: Start Bosun is the same tap as on Meet Bosun', JSON.stringify(sent(down, 'console.start')) === JSON.stringify([{ verb: 'console.start' }]));

    /* the workspace file, with more than one repo: a row like the others, with no commands */
    const WS = { aim: 'work', label: 'CLAUDE.md (workspace)', path: '/i/spaces/work/CLAUDE.md', state: 'ready', card: 'c-ws',
                 text: '# work: how the repos fit together\n', commands: null };
    const both = open([full('api', 'adopted'), full('web', 'adopted'), WS], up, true);
    body(both);
    workspace = both;
    /* the list follows Bosun: the state says web is ready now, so the report is read again */
    const before = mixed._fetched.filter((u) => u === '/api/setup').length;
    stepOf(mixed.App.data.firstrun, 'rules').drafts[1] = Object.assign(light(full('web', 'ready')), { stamp: 1700000300 });
    mixed._report = withRows([full('api', 'ready'), full('web', 'ready'), full('docs', 'idle'), full('old', 'idle', { card: null })]);
    check('drafts: a row\'s state is the live one before the report is back', text(keyedAll(keyed(body(mixed), 'drafts-back'), 'draft-pill')[1]) === 'ready for you');
    body(mixed);
    check('drafts: and the report is asked for once more, once', mixed._fetched.filter((u) => u === '/api/setup').length === before + 1);
    setImmediate(function () {
      const ws = keyedAll(keyed(body(workspace), 'drafts-back'), 'draft-row')[2];
      check('workspace: the space\'s own file is the last row, by its name and path', text(keyed(ws, 'draft-label')) === 'CLAUDE.md (workspace)' &&
        text(ws).indexOf('/i/spaces/work/CLAUDE.md') >= 0);
      check('workspace: it has no commands, and is read and adopted like any other', !keyed(ws, 'draft-commands') &&
        !!named(ws, 'Read the draft') && !!named(ws, 'Adopt'));
      press(named(ws, 'Adopt'));
      check('workspace: Adopt is the same verb, for its card', JSON.stringify(workspace._acted) === JSON.stringify([{ verb: 'setup.tier.adopt', card: 'c-ws' }]));
      check('workspace: it does not hold Next', !named(body(workspace), 'Next').hasAttribute('disabled'));
      const web = keyedAll(keyed(body(mixed), 'drafts-back'), 'draft-row')[1];
      check('drafts: then the row has its draft to read', !!named(web, 'Read the draft') && !!keyed(web, 'draft-commands'));
      done();
    });
  });
}

/* A card whose landing runs no tests says so at its outcome gate, before the tap */
function untested(done) {
  const SAID = 'api\'s CLAUDE.md has no Run the tests line, so Approve lands this without running any tests.';
  const card = (repo) => deck.card('c-7', { space: 'personal', repo: repo, stage: 'review', derived: { outcome_gate: true, needs_you: true } });
  const K = page(firstrun('2026-10-03T10:00:00+00:00', true, true), 'cards');
  K.App.data.spaces.personal.untested = { api: SAID };
  const said = (repo) => { const host = deck.wrap(K.gateEvidence(card(repo)), K); return keyed(host, 'lands-untested'); };
  /* a pre-run that was not run (the repo's file changed) is not called red (fix check r2.D4) */
  const word = (pretest) => K.pretestWord(deck.card('c-7', { space: 'personal', repo: 'api', stage: 'review', options: { pretest: pretest } }));
  check('untested: a pre-run that was not run is not called red: ' + word({ result: 'not run', said: 'x' }),
    word({ result: 'not run', said: 'x' }) === 'not pre-run' && word({ result: 'red' }) === 'merged tree red' && word({ result: 'green' }) === 'merged tree green');
  check('untested: the outcome gate says a landing runs no tests, and why', text(said('api')) === SAID);
  check('untested: a repo with a test command says nothing', !said('web'));
  /* review r2.F3: a repo whose file changed since it was adopted will be refused, said first */
  const WONT = 'api\'s CLAUDE.md changed since it was adopted or saved, so Approve will not land this. Adopt or save the file again (Setup, the api repo\'s file).';
  K.App.data.spaces.personal.untested = {};
  K.App.data.spaces.personal.unlandable = { api: WONT };
  const host = deck.wrap(K.gateEvidence(card('api')), K);
  check('untested: a repo whose file changed says Approve will not land it', text(keyed(host, 'lands-refused')) === WONT);
  check('untested: and it is labelled so, not as landing untested', text(keyed(host, 'refused-label')) === 'will not land' && !keyed(host, 'lands-untested'));
  done();
}

/* Where finished work goes: keeping work on this computer for a space on no connection (the
   sentence, the check that runs on a tap), the choice the repo's host points at, and a space
   that is on a connection. The four choices themselves are tests/fixtures/start-connection.js. */
function lands(done) {
  const B = 'Work is merged into main in Shipyard\'s copy on this computer. Shipyard fetches from your repo\'s home address before it starts a card, ' +
    'so it builds on what your team has. After a landing you get a Push button. Nothing leaves this computer without your tap.';
  const own = (host) => ({ personal: { remote: 'origin', fetch: true, push: true, repos: [{ key: 'api', host: host, branch: 'main' }] } });
  const pack = (name, spaces) => ({ name: name, description: 'a pack', spaces: spaces || [], rules: [], checks: [] });
  const plain = at('integrations', null, withStart({ lands: own('gitlab.example') }));
  const github = at('integrations', null, Object.assign(withStart({ lands: own('github.com') }), { packs: [Object.assign(pack('github'), { checks: [{ name: 'GitHub sign-in', ok: false, why: 'not signed in', for: ['codehost'] }] })] }));
  const other = at('integrations', null, Object.assign(withStart({ lands: own('github.com') }), { packs: [pack('forge')] }));
  const none = at('integrations', null, withStart({ lands: { personal: { remote: 'origin', fetch: true, push: true, repos: [] } } }));
  const packed = at('integrations', null, Object.assign(withStart({ lands: {} }), { packs: [pack('forge', ['personal'])],
    spaces: { personal: { pack: 'forge', tier: null, writable: true, proposal: null, repos: [] } } }));
  const answers = [];
  plain.act = (body) => { plain._acted.push(body); return new Promise((resolve) => { answers.push(resolve); }); };
  [plain, github, other, none, packed].forEach(body);
  setImmediate(function () {
    let b = body(plain);
    check('lands: it says what Keel read from the address', text(keyed(b, 'lands-read')) ===
      'Shipyard read api\'s address: it lives on gitlab.example. Pick how its work should arrive there.');
    const optB = keyed(b, 'lands-local-personal');
    /* c-729: one visible choice, each option its own control, the one in use open */
    const how = keyed(b, 'lands-how-personal');
    const opt = (node, id) => keyed(node, 'lands-how-personal-' + id);
    check('lands: one choice, this computer open and in use, by its name', !!how && how.getAttribute('role') === 'radiogroup' &&
      opt(how, 'local').getAttribute('aria-checked') === 'true' &&
      text(opt(how, 'local')).indexOf('Keep work on this computer, and push when you say') === 0 && text(opt(how, 'local')).indexOf('in use') >= 0);
    check('lands: it says what happens: ' + text(keyed(optB, 'lands-b-said')), text(keyed(optB, 'lands-b-said')) === B);
    check('lands: with no connection shipped, that choice is left out, and nothing claims to match the repo', !opt(how, 'shipped') &&
      !keyed(b, 'lands-shipped-personal') && text(how).indexOf('Matches your repo.') < 0);
    check('lands: the draft is a control of its own, and its section is not drawn until opened', opt(how, 'draft').getAttribute('aria-checked') === 'false' &&
      !keyed(b, 'lands-draft-personal'));
    const can = () => keyed(body(plain), 'can-push-personal');
    check('lands: the push check waits for a tap', st(can()) === 'waiting' && text(can()).indexOf('This computer can push to origin') >= 0 &&
      plain._acted.length === 0);
    press(named(body(plain), 'Check'));
    check('lands: Check asks the server once, for that space', sent(plain, 'land.push.check').length === 1 &&
      sent(plain, 'land.push.check')[0].space === 'personal' && st(can()) === 'checking');
    answers[0]({ checks: [{ key: 'api', ok: true, host: 'gitlab.example', why: 'api can push main to origin' }] });
    setImmediate(function () {
      const ok = keyed(body(plain), 'can-push-personal-api');
      check('lands: a repo that can push is ready, in the server\'s words', st(ok) === 'ready' && text(ok).indexOf('api can push main to origin') >= 0);
      press(named(body(plain), 'Check again'));
      answers[1]({ checks: [{ key: 'api', ok: false, host: 'github.com', why: 'git could not reach origin to push api: denied' }] });
      setImmediate(function () {
        const bad = keyed(body(plain), 'stuck-can-push-personal-api');
        check('lands: one that cannot is a stuck line with what git said', !!bad &&
          text(keyed(bad, 'stuck-what')).indexOf('git could not reach origin to push api: denied.') >= 0);
        check('lands: for github.com its fix points at the GitHub connection\'s checks', text(keyed(bad, 'stuck-fix')).indexOf(
          'The fix is the first two checks of the GitHub connection') >= 0);
        check('lands: and it can be asked again', !!named(body(plain), 'Check again'));

        b = body(github);
        const gh = keyed(b, 'lands-how-personal');
        check('lands: a github.com repo with the GitHub connection shipped matches the shipped choice, in the space\'s words',
          text(opt(gh, 'shipped')).indexOf('Use a connection Shipyard ships') === 0 && text(opt(gh, 'shipped')).indexOf('Matches your repo. Shipyard opens each pull request') >= 0 &&
          text(opt(gh, 'local')).indexOf('Matches your repo.') < 0);
        check('lands: the unopened choice says what ships in one quiet line, never a needs-you block',
          text(opt(gh, 'shipped')).indexOf('Shipped: github') >= 0 && !keyed(b, 'stuck-check-GitHub sign-in') && !keyed(b, 'lands-shipped-personal'));
        opt(gh, 'shipped')._on.onclick({});
        b = body(github);
        /* c-758: picking only opens; until then it turned the one listed connection on at once */
        check('lands: opening the choice writes nothing: ' + JSON.stringify(github._acted), github._acted.length === 0 &&
          !!keyed(b, 'lands-shipped-personal') && text(keyed(b, 'lands-now-personal')) === 'Work for personal now stays on this computer, and you push when you say.');
        check('lands: a connection that is not on says what it needs in one quiet line: ' + text(keyed(keyed(b, 'pack-github'), 'pack-needs')),
          text(keyed(keyed(b, 'pack-github'), 'pack-needs')) === 'needs: GitHub sign-in' && !keyed(b, 'stuck-check-GitHub sign-in'));
        press(named(keyed(b, 'pack-github'), 'Turn on for personal'));
        check('lands: Turn on inside it turns the connection on for that space: ' + JSON.stringify(github._acted),
          JSON.stringify(github._acted) === JSON.stringify([{ verb: 'setup.pack.on', pack: 'github', space: 'personal' }]));
        b = body(other);
        check('lands: with another connection only, nothing claims to match', text(keyed(b, 'lands-how-personal')).indexOf('Matches your repo.') < 0 &&
          text(keyed(b, 'lands-how-personal-shipped')).indexOf('Shipped: forge') >= 0);
        b = body(none);
        check('lands: with no repo copied there is nothing read and no check', !keyed(b, 'lands-read') && !keyed(b, 'can-push-personal') &&
          !!keyed(b, 'lands-local-personal'));
        b = body(packed);
        const on = keyed(b, 'lands-how-personal');
        check('lands: a space on a connection has its choice open and in use, the connection with Turn off, and the others still offered',
          keyed(on, 'lands-how-personal-shipped').getAttribute('aria-checked') === 'true' && !!named(keyed(b, 'lands-shipped-personal'), 'Turn off for personal') &&
          !keyed(b, 'lands-local-personal') && keyed(on, 'lands-how-personal-local').getAttribute('aria-checked') === 'false' &&
          text(keyed(b, 'lands-now-personal')) === 'Work for personal now goes through forge.');
        keyed(on, 'lands-how-personal-local')._on.onclick({});
        b = body(packed);
        check('lands: opening this computer on it writes nothing, and says what its button will do: ' + text(keyed(b, 'lands-local-off')),
          packed._acted.length === 0 && text(keyed(b, 'lands-local-off')).indexOf('Keeping work on this computer turns forge off for personal.') >= 0);
        press(named(keyed(b, 'lands-local-personal'), 'Keep work for personal on this computer'));
        check('lands: its one button turns the connection off: ' + JSON.stringify(packed._acted),
          JSON.stringify(packed._acted) === JSON.stringify([{ verb: 'setup.pack.off', space: 'personal' }]));
        done();
      });
    });
  });
}

/* c-730: under the chosen connection, when it can bring review requests, one plain question,
   off by default; ticked, it offers the space's auto review and review model; it saves as
   every setting does. A connection that cannot, or keeping work on this computer, asks nothing. */
function reviewAsks(done) {
  const S = (key, kind, label, dflt) => ({ id: 'space.' + key, table: 'space', key: key, scope: 'space', kind: kind,
    label: label, help: label + '.', group: 'Review', 'default': dflt, choices: [] });
  const SETTINGS = { install: '/i', groups: ['Review'], helps: {},
    schema: [S('review_scan', 'bool', 'Bring me review requests', true), S('review_auto', 'bool', 'Auto review', false),
             S('review_model', 'model', 'Review model', null)],
    values: { install: {}, spaces: { personal: { 'space.review_scan': { value: false, source: 'pack', 'default': false } } } } };
  const pack = (name, caps) => ({ name: name, description: 'a pack', spaces: ['personal'], rules: [], checks: [], capabilities: caps });
  const make = (caps) => {
    const K = at('integrations', null, Object.assign(withStart({ lands: {} }), { packs: [pack('github', caps)],
      spaces: { personal: { pack: 'github', tier: null, writable: true, proposal: null, repos: [] } } }), { ready: true });
    K._answers['/api/settings'] = SETTINGS;
    K.App.data.readiness.spaces.personal.reviews = { ready: false, why: 'review scanning is off for personal', step: 'integrations', declared: false };
    K.App.data.readiness.spaces.personal.tracker = { ready: false, why: 'the github connection has no tracker', step: 'integrations', declared: false };
    return K;
  };
  const able = make(['codehost', 'reviews']), unable = make(['codehost']);
  [able, unable].forEach(body);
  setImmediate(function () {
    setImmediate(function () {
      let b = body(able);
      const ask = keyed(b, 'lands-reviews-personal');
      const box = () => (keyedAll(body(able), 'lands-reviews-personal')[0] ? deck.all(keyed(body(able), 'lands-reviews-personal'), (n) => n.getAttribute('data-fk') === 'personal|space.review_scan')[0] : null);
      const fields = (node) => !node ? [] : deck.all(node, (n) => n.getAttribute && /^personal\|space\./.test(n.getAttribute('data-fk') || '')).map((n) => n.getAttribute('data-fk'));
      check('asks: under the connection that is on, the question in plain words', !!keyed(keyed(b, 'lands-shipped-personal'), 'lands-reviews-personal') &&
        text(keyed(ask, 'lands-reviews-ask')) === 'Also bring me pull requests that wait on my review?');
      check('asks: it says a pull request from a fork waits for your tap (r1.F1)',
        text(ask).indexOf('One from a fork waits for your tap, even with auto review on, and its code is read, never run.') >= 0);
      check('asks: off by default, and nothing else is asked yet: ' + JSON.stringify(fields(ask)), !!box() && !box().checked &&
        JSON.stringify(fields(ask)) === JSON.stringify(['personal|space.review_scan']));
      const field = keyed(ask, 'set-personal|space.review_scan');
      check('asks: off is the pack\'s default for the space, said so, with nothing to reset: ' + text(field),
        text(field).indexOf('from the pack') >= 0 && text(field).indexOf('default on') < 0 && !named(field, 'Reset'));
      check('asks: a capability the space does not use is not drawn as something it needs',
        !keyed(b, 'stuck-row-personal-reviews') && !keyed(b, 'stuck-row-personal-tracker') && text(keyed(b, 'lands-shipped-personal')).indexOf('has no tracker') < 0);
      if (box()) box()._on.onchange({ target: { checked: true } });
      b = body(able);
      check('asks: ticked, it offers the space\'s auto review and review model: ' + JSON.stringify(fields(keyed(b, 'lands-reviews-personal'))),
        JSON.stringify(fields(keyed(b, 'lands-reviews-personal'))) === JSON.stringify(['personal|space.review_scan', 'personal|space.review_auto', 'personal|space.review_model']));
      press(!keyed(b, 'lands-reviews-personal') ? null : deck.buttons(keyed(b, 'lands-reviews-personal')).filter((n) => /^Save/.test(deck.labelOf(n)))[0]);
      const saved = sent(able, 'setup.settings.save')[0];
      check('asks: it saves as every setting does: ' + JSON.stringify(saved), !!saved &&
        JSON.stringify(saved.changes) === JSON.stringify([{ table: 'space', key: 'review_scan', value: true, space: 'personal' }]));
      check('asks: a connection that cannot bring review requests asks nothing', !keyed(body(unable), 'lands-reviews-personal'));
      done();
    });
  });
}

/* The Push after a landing, on the card: the sentence and the one button, the refused push
   with its fix, and nothing once the remote has it */
function pushes(done) {
  const BEHIND = 'origin has commits this computer has not seen, so the push was refused.';
  const card = deck.card('c-9', { space: 'personal', repo: 'api', stage: 'done' });
  const make = (push) => {
    const K = page(firstrun('2026-10-03T10:00:00+00:00', true, true), 'cards');
    K.App.detail = { card: card, push: push }; K.App.detailFor = 'c-9';
    K.loadDetail = () => {};
    return K;
  };
  const offer = { repo: 'api', branch: 'main', remote: 'origin', pushed: false, said: 'Merged into main on this computer.' };
  const K = make(offer), gone = make(Object.assign({}, offer, { pushed: true, said: 'Pushed: origin has it.' })), none = make(null);
  let answer = null;
  K.act = (body) => { K._acted.push(body); return Promise.resolve(answer); };
  const block = (on) => deck.wrap(on.pushBlock(card), on);
  let b = block(K);
  check('push: the card says where its work is', text(keyed(b, 'push-said')) === 'Merged into main on this computer.');
  check('push: and carries the one button: ' + JSON.stringify(labels(b)), JSON.stringify(labels(b)) === JSON.stringify(['Push main to origin']));
  check('push: nothing is sent until the tap', K._acted.length === 0);
  check('push: a card with no push offered draws nothing', !none.pushBlock(card));
  check('push: once the remote has it there is no button', text(keyed(block(gone), 'push-said')) === 'Pushed: origin has it.' &&
    labels(block(gone)).length === 0);
  K.refusal = () => ({ error: BEHIND, detail: { kind: 'behind' } });
  press(named(b, 'Push main to origin'));
  setImmediate(function () {
    check('push: the tap sends land.push for that card, without fetch', K._acted.length === 1 && K._acted[0].verb === 'land.push' &&
      K._acted[0].id === 'c-9' && !K._acted[0].fetch);
    b = block(K);
    const line = keyed(b, 'stuck-push');
    check('push: a refused push is a stuck line in the server\'s words', !!line && text(keyed(line, 'stuck-what')).indexOf(BEHIND) >= 0);
    check('push: its fix is Fetch and try again: ' + JSON.stringify(labels(keyed(line, 'stuck-fix'))),
      JSON.stringify(labels(keyed(line, 'stuck-fix'))) === JSON.stringify(['Fetch and try again']));
    answer = { push: 'testing', note: 'fetching origin\'s commits and testing them with yours; the card says when it is pushed' };
    press(named(b, 'Fetch and try again'));
    setImmediate(function () {
      check('push: which sends the same verb with fetch', K._acted.length === 2 && K._acted[1].fetch === true && K._acted[1].id === 'c-9');
      check('push: a tap that was taken clears the refusal', !keyed(block(K), 'stuck-push'));
      /* the worker runs: the card's detail says testing, and the page says so with no button */
      const SAME = 'origin\'s commits and this computer\'s change the same lines of api, so Shipyard did not merge them and nothing was pushed. A card on api can merge them: file one that says so.';
      const during = make(Object.assign({}, offer, { testing: true, refused: null }));
      b = block(during);
      const row = keyed(b, 'push-testing');
      check('push: while the worker runs the card says testing: ' + text(row), st(row) === 'checking' &&
        text(row).indexOf('Bringing in origin\'s commits and testing them with yours. This page follows it.') >= 0);
      check('push: and offers no button meanwhile', labels(b).length === 0);
      /* the worker answered on the card: a refusal that a retry would only repeat has no retry */
      [['conflict', SAME], ['tests', 'the tests failed with origin\'s commits merged in (`npm test`), so nothing was merged or pushed: 2 failed']].forEach(function (pair) {
        const stopped = block(make(Object.assign({}, offer, { testing: false, refused: { error: pair[1], kind: pair[0], fetch: true } })));
        const said = keyed(stopped, 'stuck-push');
        check('push: a ' + pair[0] + ' refusal is said in the server\'s words, kept on the card', !!said && text(keyed(said, 'stuck-what')).indexOf(pair[1].slice(0, 40)) >= 0);
        check('push: and has no Fetch and try again, which would only repeat it: ' + JSON.stringify(labels(stopped)), !named(stopped, 'Fetch and try again') && !named(stopped, 'Try again') && !named(stopped, 'Push main to origin'));
      });
      const died = make(Object.assign({}, offer, { testing: false, refused: { error: 'The push stopped before it finished, and nothing says why. Try again.', kind: 'failed', fetch: true } }));
      died.act = (body) => { died._acted.push(body); return Promise.resolve(null); };
      b = block(died);
      check('push: a worker that died is a refusal with Try again', JSON.stringify(labels(keyed(b, 'stuck-fix'))) === JSON.stringify(['Try again']));
      press(named(b, 'Try again'));
      check('push: which starts the worker again', died._acted.length === 1 && died._acted[0].fetch === true);
      K.refusal = () => ({ error: 'git could not push main to origin: denied', detail: { kind: 'failed' } });
      answer = null;
      press(named(block(K), 'Push main to origin'));
      setImmediate(function () {
        const failed = keyed(block(K), 'stuck-push');
        check('push: any other refusal says what git said, with Try again', !!failed && text(failed).indexOf('denied') >= 0 &&
          JSON.stringify(labels(keyed(failed, 'stuck-fix'))) === JSON.stringify(['Try again']));
        done();
      });
    });
  });
}

/* How work ships: the usual path as a picture with the moves that are yours marked, Bosun's
   draft beside it to Adopt, the adopted state, the line to Bosun's session, and the plan
   question */
function ships(done) {
  const local = { name: 'Local merge', description: 'Your approval merges the card.', source: 'keel', proposal: null, landing: {},
    handling: { shipping: false },
    branches: [{ id: 'card', label: 'card branch', kind: 'card' }, { id: 'base', label: '{base}', kind: 'base' }],
    moves: [{ id: 'land', label: 'Approve outcome', from: 'card', to: 'base', by: 'keel', step: 'land', stages: ['review'] }] };
  const theirs = { name: 'Staging first', description: 'You and Bosun agreed that work goes to a staging branch first, and a release moves it to main.',
    source: 'space', branches: local.branches.concat([{ id: 'live', label: 'the live site', kind: 'environment' }]),
    moves: local.moves.concat([{ id: 'release', label: 'Release', from: 'base', to: 'live', by: 'colleague', stages: [] }]) };
  /* Shipyard's general flow as the state carries it for a space on GitHub (etc/flows/general.toml, worded) */
  const hosted = Object.assign({}, local, { name: 'General', description: 'A draft, your approval publishes it, you or a teammate merge it.',
    moves: [{ id: 'draft', label: 'Draft pull request', from: 'card', to: 'base', by: 'house', step: 'pr', stages: ['building'] },
            { id: 'publish', label: 'Approve outcome', from: 'card', to: 'base', by: 'keel', step: 'publish', stages: ['review'] },
            { id: 'ship', label: 'Ship', from: 'card', to: 'base', by: 'keel', step: 'ship', stages: ['shipping'] },
            { id: 'merge', label: 'Review and merge', from: 'card', to: 'base', by: 'colleague', stages: ['shipping'],
              about: 'You or a teammate review and merge the pull request on GitHub. Shipyard never merges it. The card is done once it is merged.' }] });
  const lands = { personal: { remote: 'origin', fetch: true, push: true, repos: [{ key: 'api', host: 'gitlab.example', branch: 'main' }] } };
  const row = (more) => Object.assign({ pack: null, tier: null, writable: true, proposal: null, repos: [{ key: 'api' }] }, more || {});
  /* c-732: the step's questions (keel/bases.py ASKS) and each space's answer to the first */
  const ASKS = [{ id: 'starts', ask: 'Where does work start?', where: 'page', example: 'main, and staging' },
    { id: 'lands', ask: 'Which branch does finished work go back into?', where: 'bosun', example: 'back where it started' },
    { id: 'approves', ask: 'Who says it is good?', where: 'bosun', example: 'I approve it here' },
    { id: 'after', ask: 'What happens after that?', where: 'bosun', example: 'staging is merged into main every Friday' },
    { id: 'live', ask: 'When do people see it live?', where: 'bosun', example: 'when main is deployed' }];
  const make = (flow, space, plans, start, bases) => {
    const fr = firstrun(null, true);
    stepOf(fr, 'defaults').plans = { personal: plans === undefined ? false : plans };
    stepOf(fr, 'defaults').asks = ASKS;
    stepOf(fr, 'defaults').bases = { personal: bases || { bases: [], suggested: 'main', pack: false } };
    const K = at('defaults', fr, Object.assign(withStart(start || { lands: lands }), { spaces: { personal: row(space) } }),
      { state: { console: { attach: ATTACH, up: true } } });
    K.App.data.spaces.personal.flow = flow;
    return K;
  };
  /* each arrow as `from>what(who)>to`, a `*` on the ones that are the user's */
  const path = (node) => (node ? deck.all(node, (n) => n.nodeType === 1 && n.getAttribute('data-key') === 'fp-move').map((row) => {
    const what = deck.byClass(row, 'fp-what')[0], who = deck.byClass(row, 'fp-who')[0];
    return row.getAttribute('data-from') + '>' + text(what) + '(' + text(who) + ')>' + row.getAttribute('data-to') +
      (row.getAttribute('data-yours') === 'yes' ? '*' : '');
  }) : []);
  const proposal = { card: 'c-9', stage: 'review', waiting: false, draft: true };
  const plain = make(local);
  const two = make(local, null, false, undefined, { bases: ['main', 'staging'], suggested: 'main', pack: false });
  const packed = make(local, { pack: 'ours' }, false, { lands: {} }, { bases: ['release', 'trunk'], suggested: 'trunk', pack: true, listed: true });
  /* r2.F5: a pack whose own base field is a text box lists nothing */
  const fielded = make(local, { pack: 'ours' }, false, { lands: {} }, { bases: ['main'], suggested: 'main', pack: true, listed: false });
  const github = make(hosted, { pack: 'github' }, false, { lands: {} });
  /* c-732 r1.F4, F5: a repo whose cards land on an integration branch offers no bases */
  const integrated = make(local, null, false, undefined, { bases: [], suggested: 'next', pack: false, integration: 'next' });
  const drafting = make(Object.assign({}, local, { proposal: { card: 'c-9', stage: 'building', waiting: false, draft: true } }),
    { flow_draft: { card: 'c-9', stage: 'building', draft: true, flow: null, error: null } });
  const waiting = make(Object.assign({}, local, { proposal: proposal }),
    { flow_draft: { card: 'c-9', stage: 'review', draft: true, flow: theirs, error: null } });
  const broken = make(Object.assign({}, local, { proposal: proposal }),
    { flow_draft: { card: 'c-9', stage: 'review', draft: true, flow: null, error: 'move release: no branch nowhere' } });
  const adopted = make(Object.assign({}, theirs, { proposal: null, adopted: true }), null, true);
  /* review r2.F13: a flow of its own that no draft of Bosun's made (written in Settings) */
  const ownFlow = make(Object.assign({}, theirs, { proposal: null, adopted: false }), null, true);
  /* review r2.F14: a proposal at review whose draft the report does not carry */
  const unread = make(Object.assign({}, local, { proposal: proposal }), { flow_draft: null });
  /* the page's own timer, recorded from its first draw: what it scheduled is what is fired
     below, so a page that arms no timer fails (fix check r2.D6) */
  const timers = [];
  unread._setTimeout = (fn, ms) => { timers.push({ fn: fn, ms: ms }); return timers.length; };
  [plain, two, packed, fielded, integrated, github, drafting, waiting, broken, adopted, ownFlow, unread].forEach(body);
  setImmediate(function () {
    let b = body(plain);
    /* c-732: the first question, answered on the page, the repo's default branch filled in */
    const q1 = keyed(b, 'ships-bases-personal');
    check('ships: question 1, on the page, with its example', text(tags(q1, 'H3')[0]) === '1.Where does work start?' &&
      text(q1).indexOf('For example: "main, and staging"') >= 0);
    check('ships: r1.F3: what its Save does is said', text(q1).indexOf('Save applies at once, to new cards only.') >= 0);
    check('ships: the repo\'s default branch is filled in, and said to be: ' + text(keyed(q1, 'ships-bases-said')),
      deck.all(q1, (n) => n.getAttribute && n.getAttribute('data-key') === 'ships-base').map(text).join() === 'main×' &&
      text(keyed(q1, 'ships-bases-said')) === 'main is your repo\'s default branch, filled in for you. Press Save to keep it.');
    const field = deck.all(q1, (n) => n.getAttribute && n.getAttribute('data-fk') === 'ships-add-personal')[0];
    field._on.oninput({ target: { value: 'staging' } });
    press(named(q1, 'Add'));
    press(named(keyed(body(plain), 'ships-bases-personal'), 'Save'));
    const bases = sent(plain, 'setup.settings.save')[0];
    check('ships: Add, then Save, keeps the space\'s bases: ' + JSON.stringify(bases), !!bases &&
      JSON.stringify(bases.changes) === JSON.stringify([{ table: 'space', space: 'personal', key: 'bases', value: ['main', 'staging'] }]));
    plain._acted.length = 0;
    /* the rest, in Bosun's session, and why */
    const tell = keyed(b, 'ships-tell');
    check('ships: the rest is answered with Bosun, is optional, and the page says where', text(tags(tell, 'H3')[0]) === 'Only if your team works differently' &&
      text(tell).indexOf('This part is optional.') >= 0 &&
      text(tell).indexOf('You answer them in Bosun\'s session, not on this page') >= 0 &&
      text(tell).indexOf('asks back anything it cannot place rather than guess') >= 0);
    check('ships: questions 2 to 5, each with its example',
      deck.all(tell, (n) => n.getAttribute && n.getAttribute('data-key') === 'ships-ask').map((n) => text(tags(n, 'STRONG')[0])).join('|') ===
        '2.Which branch does finished work go back into?|3.Who says it is good?|4.What happens after that?|5.When do people see it live?' &&
      text(tell).indexOf('For example: "staging is merged into main every Friday"') >= 0);
    check('ships: with the command to Bosun\'s session and Copy', codes(tell).indexOf(ATTACH) >= 0 && !!named(tell, 'Copy'));
    check('ships: no box to describe a flow in, and no Propose', !tags(b, 'TEXTAREA').length && !named(b, 'Propose'));
    /* the drawing: places, labelled arrows, yours marked, one sentence */
    check('ships: the usual path, place to place, yours marked: ' + JSON.stringify(path(keyed(b, 'ships-now'))),
      JSON.stringify(path(keyed(b, 'ships-now'))) === JSON.stringify(['your card\'s branch>Approve(you)>main*', 'main>Push(you)>origin*']));
    check('ships: and one sentence under it: ' + text(keyed(b, 'ships-now-said')), text(keyed(b, 'ships-now-said')) ===
      'In words: Work starts on main. You press Approve, and Shipyard merges it into main on this computer. You press Push when your team should see it on origin.');
    check('ships: only the arrows marked you are buttons', text(keyed(b, 'ships-only')) ===
      'Only the arrows marked you are buttons on a card. The rest is a picture of what happens.');
    /* every part is reachable from the drawing */
    const places = deck.all(keyed(b, 'ships-now'), (n) => n.getAttribute && n.getAttribute('data-key') === 'fp-place');
    press(places[1]);
    let part = keyed(body(plain), 'fp-part');
    check('ships: a base, tapped, says where to change it: ' + text(part), text(part).indexOf('main is a branch work starts from') === 0 &&
      !!named(part, 'Change where work starts') && text(part).indexOf('Nothing changes until you press Adopt.') >= 0);
    const arrow = deck.all(keyed(body(plain), 'ships-now'), (n) => deck.hasClass(n, 'fp-arrow'))[0];
    press(arrow);
    part = keyed(body(plain), 'fp-part');
    check('ships: your arrow, tapped, says it is a button and how to change it, with the command: ' + text(part),
      text(part).indexOf('This is yours: a button on the card.') === 0 && text(part).indexOf('tell Bosun in its session') >= 0 &&
      codes(part).indexOf(ATTACH) >= 0);
    press(deck.all(keyed(body(plain), 'ships-now'), (n) => deck.hasClass(n, 'fp-arrow'))[0]);
    check('ships: tapped again, it closes', !keyed(body(plain), 'fp-part'));
    press(named(body(plain), 'Keep how it works now'));
    /* c-729: and records the step as seen, so the list shows it done */
    check('ships: Keep how it works now goes on to the next step, the step seen on the way: ' + JSON.stringify(plain._acted), plain.App.step === 'browser' &&
      JSON.stringify(plain._acted) === JSON.stringify([{ verb: 'firstrun.seen', step: 'defaults' }]));
    plain.App.step = 'defaults';
    plain.App.data.firstrun.steps.filter((s) => s.id === 'defaults')[0].seen = '2026-10-09T12:00:00+05:30';
    const kept = keyed(body(plain), 'ships-keep');
    check('ships: once seen, it says Kept, pressed', text(kept) === 'Kept' && kept.getAttribute('aria-pressed') === 'true');
    plain.App.data.firstrun.steps.filter((s) => s.id === 'defaults')[0].seen = undefined;
    press(named(body(plain), 'Start this with Bosun'));
    check('ships: the draft card is filed by the tap, for that space', sent(plain, 'setup.flow.draft').length === 1 &&
      sent(plain, 'setup.flow.draft')[0].space === 'personal');
    const q = keyed(body(plain), 'ships-plans-personal');
    /* c-729: in Shipyard's words, for the named space, a default, and the one in force marked */
    const opt = (node, id) => keyed(node, 'ships-plans-personal-how-' + id);
    check('ships: the plan question says what it sets, with the answer in force selected', text(tags(q, 'H3')[0]) === 'New cards in personal start as:' &&
      opt(q, 'autonomous').getAttribute('aria-checked') === 'true' && text(opt(q, 'autonomous')).indexOf('selected') >= 0 &&
      opt(q, 'attended').getAttribute('aria-checked') === 'false' && text(opt(q, 'attended')).indexOf('It stops at its plan for you.') >= 0 &&
      text(q).indexOf('You can change it on any card.') >= 0);
    opt(q, 'attended')._on.onclick({});
    const saved = sent(plain, 'setup.settings.save')[0];
    check('ships: Yes saves the space\'s autonomy as attended: ' + JSON.stringify(saved), !!saved &&
      JSON.stringify(saved.changes) === JSON.stringify([{ table: 'space', space: 'personal', key: 'autonomy', value: 'attended' }]));

    /* c-732: two bases are two places, as the user named them */
    b = body(two);
    check('ships: two bases, each a place by name: ' + JSON.stringify(path(keyed(b, 'ships-now'))),
      JSON.stringify(path(keyed(b, 'ships-now'))) === JSON.stringify(['your card\'s branch>Approve(you)>main*',
        'your card\'s branch>Approve(you)>staging*', 'main>Push(you)>origin*', 'staging>Push(you)>origin*']));
    check('ships: and the sentence says both: ' + text(keyed(b, 'ships-now-said')), text(keyed(b, 'ships-now-said')) ===
      'In words: Work starts on main or staging. You press Approve, and Shipyard merges it into the branch it started from (main or staging) on this computer. You press Push when your team should see it on origin.');
    /* the coordinator's bar: one diagram, each place once, drawn by the board's own drawing */
    const gitea = { name: 'Main or staging', description: 'Work starts on main or staging. Staging is merged into main every week.',
      source: 'space', branches: [{ id: 'card', label: 'card branch', kind: 'card' }, { id: 'main', label: 'main', kind: 'base' },
        { id: 'staging', label: 'staging', kind: 'base' }],
      moves: [{ id: 'm', label: 'Approve outcome', from: 'card', to: 'main', by: 'keel', step: 'land', bases: ['main'] },
        { id: 's', label: 'Approve outcome', from: 'card', to: 'staging', by: 'keel', step: 'land', bases: ['staging'] },
        { id: 'w', label: 'Weekly merge', from: 'staging', to: 'main', by: 'colleague', about: 'Every week, a teammate merges staging into main.' }] };
    const drawn = two.flowLinesOf(gitea, { bases: ['main', 'staging'], push: 'origin' });
    check('ships: each place once, as a box: ' + JSON.stringify(drawn.filter((l) => l.indexOf('node ') === 0)),
      JSON.stringify(drawn.filter((l) => l.indexOf('node ') === 0)) === JSON.stringify(['node p0 git-branch "your card\'s branch" "one card\'s own work"',
        'node p1 git-branch "main" "work starts here"', 'node p2 git-branch "staging" "work starts here"', 'node p3 cloud "origin" "your team\'s copy"']));
    check('ships: each arrow once, labelled with the move and who makes it: ' + JSON.stringify(drawn.filter((l) => l.indexOf('edge ') === 0)),
      JSON.stringify(drawn.filter((l) => l.indexOf('edge ') === 0)) === JSON.stringify(['edge p0 -> p1 "Approve, you"', 'edge p0 -> p2 "Approve, you"',
        'edge p2 -> p1 "Weekly merge, a teammate"', 'edge p1 -> p3 "Push, you"', 'edge p2 -> p3 "Push, you"']));
    const host = keyed(b, 'ships-now-graph');
    check('ships: the drawing is a picture the page leaves alone, named in words', !!host && host.getAttribute('role') === 'img' &&
      host.getAttribute('data-morph') === 'skip' && host.getAttribute('aria-label').indexOf('your card\'s branch to main (Approve, you)') >= 0);
    check('ships: the saved list is said', text(keyed(b, 'ships-bases-said')) === 'Saved. Every new card offers main, staging.');
    b = body(packed);
    check('ships: a pack that lists its own bases is shown, not edited: ' + text(keyed(b, 'ships-bases-pack')),
      text(keyed(b, 'ships-bases-pack')) === 'Your connection lists these, and every new card offers them: release, trunk.' &&
      !named(keyed(b, 'ships-bases-personal'), 'Save'));

    b = body(fielded);
    check('ships: r2.F5: a pack with a field of its own says so: ' + text(keyed(b, 'ships-bases-pack')),
      text(keyed(b, 'ships-bases-pack')) === 'Your connection has a Base branch field of its own on every new card, so you name the branch there.');
    b = body(integrated);
    check('ships: an integration branch is said, not offered: ' + text(keyed(b, 'ships-bases-integration')),
      text(keyed(b, 'ships-bases-integration')).indexOf('Every card here starts from next and goes back into it.') === 0 &&
      !named(keyed(b, 'ships-bases-personal'), 'Save') && JSON.stringify(path(keyed(b, 'ships-now'))) ===
      JSON.stringify(['your card\'s branch>Approve(you)>next*', 'next>Push(you)>origin*']));
    b = body(github);
    check('ships: with GitHub, the pull request path: ' + JSON.stringify(path(keyed(b, 'ships-now'))),
      JSON.stringify(path(keyed(b, 'ships-now'))) === JSON.stringify(['your card\'s branch>Draft pull request(the session)>main',
        'your card\'s branch>Approve(you)>main*', 'your card\'s branch>Ship(you)>main*',
        'your card\'s branch>Review and merge(you or a teammate)>main']));
    /* c-758: the drawing agrees with the connection's own words: Ship is your button, and you may be the one who merges */
    check('ships: and its sentence: ' + text(keyed(b, 'ships-now-said')), text(keyed(b, 'ships-now-said')) ===
      'In words: Work starts on main. The session opens a draft pull request to main. You press Approve, and Shipyard marks the pull request ready. ' +
      'You press Ship to send the fixes made after review. You or a teammate review and merge the pull request on GitHub. Shipyard never merges it. ' +
      'The card is done once it is merged.');

    b = body(drafting);
    check('ships: while Bosun drafts, the usual path stands and the card is named', !!keyed(b, 'ships-now') &&
      text(keyed(b, 'ships-drafting')) === 'Bosun is drafting (c-9).' && !named(b, 'Adopt Bosun\'s draft') && !named(b, 'Start this with Bosun'));

    b = body(waiting);
    const panel = keyed(b, 'ships-draft-personal');
    check('ships: a draft at review is said', text(tags(panel, 'H3')[0]) === 'Bosun has a draft: check it against what you said');
    check('ships: with what the user told Bosun: ' + text(keyed(panel, 'ships-agreed')), text(keyed(panel, 'ships-agreed')) ===
      'You and Bosun agreed that work goes to a staging branch first, and a release moves it to main.' && text(panel).indexOf('What you told Bosun') >= 0);
    check('ships: the two drawings, labelled, each with its sentence', text(panel).indexOf('How it works now') >= 0 && text(panel).indexOf('Bosun\'s draft') >= 0 &&
      path(keyed(panel, 'ships-now')).length === 2 &&
      JSON.stringify(path(keyed(panel, 'ships-theirs'))) === JSON.stringify(['your card\'s branch>Approve(you)>main*',
        'main>Release(a teammate)>the live site', 'main>Push(you)>origin*']) &&
      text(keyed(panel, 'ships-theirs-said')) === 'In words: Work starts on main. You press Approve, and Shipyard merges it into main on this computer. A teammate: Release. You press Push when your team should see it on origin.');
    const btns = labels(panel);
    check('ships: the buttons say what they do: ' + JSON.stringify(btns.slice(-2)), JSON.stringify(btns.slice(-2)) === JSON.stringify(['Adopt Bosun\'s draft', 'Keep how it works now']));
    press(named(panel, 'Adopt Bosun\'s draft'));
    check('ships: Adopt is the flow proposal\'s own adopt, for its card', sent(waiting, 'setup.flow.adopt').length === 1 &&
      sent(waiting, 'setup.flow.adopt')[0].card === 'c-9');

    b = body(broken);
    check('ships: a draft that does not check is not drawn, and says why', !keyed(b, 'ships-draft-personal') &&
      text(keyed(b, 'ships-draft-error')).indexOf('move release: no branch nowhere') >= 0 && !named(b, 'Adopt Bosun\'s draft'));

    b = body(adopted);
    check('ships: adopted, in the design\'s words', text(keyed(b, 'ships-adopted')) === 'Adopted. Bosun\'s draft is how this space ships now.' &&
      text(keyed(b, 'ships-now-personal')).indexOf('Tell Bosun in its session if you want to change it again.') >= 0);
    check('ships: with the new picture', path(keyed(b, 'ships-now')).indexOf('main>Release(a teammate)>the live site') >= 0);
    b = body(ownFlow);
    check('ships: a flow of its own that no draft made is not called Bosun\'s draft: ' + text(keyed(b, 'ships-own')),
      text(keyed(b, 'ships-own')) === 'This space ships by its own flow.' && !keyed(b, 'ships-adopted') &&
      path(keyed(b, 'ships-now')).indexOf('main>Release(a teammate)>the live site') >= 0);
    b = body(unread);
    check('ships: a draft at review that has not come is being read', text(keyed(b, 'ships-drafting')) === 'Reading Bosun\'s draft...');
    body(unread);
    check('ships: the page sets one timer to ask again, three seconds on: ' + JSON.stringify(timers.map((t) => t.ms)),
      JSON.stringify(timers.map((t) => t.ms)) === JSON.stringify([3000]));
    const reads = unread._fetched.filter((u) => u === '/api/setup').length;
    if (timers.length) timers.shift().fn();
    check('ships: and the report is asked for again when its timer fires', unread._fetched.filter((u) => u === '/api/setup').length === reads + 1 &&
      text(keyed(body(unread), 'ships-drafting')) === 'Reading Bosun\'s draft...' && timers.length === 1);
    for (let n = 0; n < 4 && timers.length; n += 1) { timers.shift().fn(); body(unread); }
    check('ships: five tries, each from the timer the page set, and no sixth: ' + timers.length, timers.length === 0);
    b = body(unread);
    check('ships: after five tries it says the draft could not be read, and where to read it: ' + text(keyed(b, 'ships-draft-unread')),
      text(keyed(b, 'ships-draft-unread')).indexOf('Bosun\'s draft could not be read.') === 0 && !keyed(b, 'ships-drafting') && !!named(b, 'Open c-9'));
    b = body(adopted);
    check('ships: the plan answer in force there is Attended', keyed(b, 'ships-plans-personal-how-attended').getAttribute('aria-checked') === 'true');

    /* the report is read again when the proposal's stage moved */
    const before = drafting._fetched.filter((u) => u === '/api/setup').length;
    drafting.App.data.spaces.personal.flow = Object.assign({}, local, { proposal: proposal });
    body(drafting);
    check('ships: the report is read again when the draft\'s stage moved', drafting._fetched.filter((u) => u === '/api/setup').length === before + 1);
    done();
  });
}

/* A browser for sessions: Node's check, and the install in its four states */
function browsers(done) {
  const NODE = { ok: true, said: 'v22.3.0' };
  const make = (install, node) => {
    const fr = firstrun(null, true);
    Object.assign(stepOf(fr, 'browser'), { done: install.state === 'ready', install: install, node: node || NODE });
    return at('browser', fr);
  };
  const waiting = make({ state: 'waiting', percent: 0, of_mb: null, said: '' });
  const noNode = make({ state: 'waiting', percent: 0, of_mb: null, said: '' },
    { ok: false, said: 'Node.js v18.19.1 is installed, and Shipyard\'s browser needs 20 or newer.',
      fix: 'Install Node.js 20 or newer (nodejs.org, or on Linux your package manager).', command: 'brew install node' });
  /* c-757: the downloader's own count, and no number where it gave none */
  const loading = make({ state: 'downloading', percent: 50, received_mb: 75, of_mb: 151, part: 'Chromium',
    said: 'Downloading Chromium: 50% of 151.2 MiB' });
  const getting = make({ state: 'downloading', percent: null, received_mb: 0, of_mb: null, part: null,
    said: 'Getting the installer. The download starts in a moment.' });
  const ready = make({ state: 'ready', percent: 100, of_mb: null, said: 'Shipyard\'s browser is installed.' });
  const failed = make({ state: 'failed', percent: 50, received_mb: 75, of_mb: 151,
    said: 'The download stopped: network error. Chromium had reached 50% of 151.2 MiB.' });
  [waiting, noNode, loading, getting, ready, failed].forEach(body);
  setImmediate(function () {
    let b = body(waiting);
    check('browser: Node is ready, with its version', st(keyed(b, 'browser-node')) === 'ready' &&
      text(keyed(b, 'browser-node')).indexOf('Node.js 20 or newer') >= 0 && text(keyed(b, 'browser-node')).indexOf('v22.3.0') >= 0);
    check('browser: the install waits for the tap', st(keyed(b, 'browser-install')) === 'waiting' &&
      text(keyed(b, 'browser-install')).indexOf('Shipyard\'s browser is installed') >= 0 && waiting._acted.length === 0);
    check('browser: the step is optional, so the frame offers Skip', !!named(b, 'Skip'));
    press(named(b, 'Install'));
    check('browser: Install sends the one verb', sent(waiting, 'firstrun.browser.install').length === 1);

    b = body(noNode);
    const node = keyed(b, 'stuck-browser-node');
    check('browser: an old Node is a stuck line with what is installed', !!node &&
      text(keyed(node, 'stuck-what')).indexOf('Node.js v18.19.1 is installed, and Shipyard\'s browser needs 20 or newer.') >= 0);
    check('browser: and its fix, with the command to copy', text(keyed(node, 'stuck-fix')).indexOf('Install Node.js 20 or newer') >= 0 &&
      codes(node).indexOf('brew install node') >= 0);
    check('browser: Install is off until Node is ready', named(b, 'Install').hasAttribute('disabled'));

    b = body(loading);
    check('browser: while it downloads, the row is checking and says how far', st(keyed(b, 'browser-install')) === 'checking' &&
      text(keyed(b, 'browser-install')).indexOf('Downloading Chromium: 50% of 151.2 MiB') >= 0 && !named(b, 'Install'));
    const far = keyed(b, 'browser-progress');
    const fill = far ? deck.all(far, (n) => deck.hasClass(n, 'brw-fill'))[0] : null;
    check('browser: with a bar at what has arrived, and the megabytes', !!fill && fill.getAttribute('style') === 'width:50%' &&
      text(keyed(far, 'browser-far')) === '75 of 151 MiB');
    b = body(getting);
    check('browser: with no size known it says what is known and draws no bar', st(keyed(b, 'browser-install')) === 'checking' &&
      text(keyed(b, 'browser-install')).indexOf('Getting the installer. The download starts in a moment.') >= 0 && !keyed(b, 'browser-progress'));

    b = body(ready);
    check('browser: installed is ready, with no button', st(keyed(b, 'browser-install')) === 'ready' && !named(b, 'Install') && !named(b, 'Try again'));

    b = body(failed);
    const stopped = keyed(b, 'stuck-browser-install');
    check('browser: a download that stopped says what happened and how much arrived', !!stopped &&
      text(keyed(stopped, 'stuck-what')).indexOf('The download stopped: network error. Chromium had reached 50% of 151.2 MiB.') >= 0);
    check('browser: its fix is Try again: ' + JSON.stringify(labels(keyed(stopped, 'stuck-fix'))),
      JSON.stringify(labels(keyed(stopped, 'stuck-fix'))) === JSON.stringify(['Try again']));
    check('browser: with Bosun\'s session as the third part', keyedAll(stopped, 'stuck-bosun').length === 1);
    press(named(stopped, 'Try again'));
    check('browser: Try again is the same verb', sent(failed, 'firstrun.browser.install').length === 1);
    done();
  });
}

/* Back up: the folder and the one verb, the refusal with its fix, the three checks once it
   is on, each in the state the server observed (c-757), and the passphrase, shown once */
function backups(done) {
  const INSIDE = 'That folder is inside the install, so the backup would copy itself.';
  const make = (backup, more) => {
    const fr = firstrun(null, true);
    Object.assign(stepOf(fr, 'backup'), { done: !!backup.on, backup: backup }, more || {});
    return at('backup', fr);
  };
  const field = (b) => deck.all(b, (n) => n.tagName === 'INPUT' && n.getAttribute('data-fk') === 'backup-folder')[0];
  const GPG = { name: 'gpg', label: 'gpg, for backup', ok: true, said: 'gpg (GnuPG) 2.4.7 (/opt/homebrew/bin/gpg)', required: false };
  const NO_GPG = { name: 'gpg', label: 'gpg, for backup', ok: false, said: 'not installed', required: false,
                   what: 'The gpg program is not installed on this computer. Shipyard encrypts every backup copy with it. It is needed only for Back up: the install and everything else work without it.',
                   fix: 'Install gpg (on Linux, your package manager\'s gnupg), then press Check again.', command: 'brew install gnupg' };
  const REFUSED = 'Backup needs gpg, and this computer has none where the backup looks. The Check this computer step has its row, with how to install it.';
  const off = make({ on: false, suggested: '/srv/keel-backup', gpg: GPG, same_disk: true });
  const noGpg = make({ on: false, suggested: '/srv/keel-backup', gpg: NO_GPG, same_disk: true });
  /* a page whose kept reading still says gpg is there, and whose tap the server refused */
  const refusedGpg = make({ on: false, suggested: '/srv/keel-backup', gpg: GPG, same_disk: false });
  refusedGpg.refusal = () => ({ error: REFUSED, detail: { kind: 'gpg', step: 'prerequisites' } });
  /* the rows as keel/backupstatus.py reads them */
  const LOG = '/srv/.keel-backup/logs/backup.out';
  const GO = 'The first copy is being written now, in the background. You can go on to the next step.';
  const WAITING = { state: 'waiting', at: null, fix: '', next: '2026-10-18T04:30:00+05:30',
                    said: 'First proof on Sunday 18 October, once there is a copy to prove.' };
  const ON = { on: true, store: 'file:/Volumes/disk/keel', folder: '/Volumes/disk/keel', writable: true, same_disk: false, gpg: GPG,
               first: null, copy: { state: 'writing', at: null, said: GO, fix: '' }, proof: WAITING,
               key: '/srv/.keel-backup/backup.key', log: LOG };
  const PENDING = { done: true, sure: false, word: 'copy pending',
                    why: 'backup is on, into /Volumes/disk/keel. The first copy is being written in the background' };
  const fresh = make(ON, PENDING);
  const WRITTEN = { state: 'written', at: '2026-09-24T09:00:00+00:00', said: '', fix: '' };
  const settled = make(Object.assign({}, ON, { first: WRITTEN.at, copy: WRITTEN,
    proof: { state: 'proved', at: '2026-09-21T04:30:00+00:00', said: 'The next one is due Sunday 25 October.', fix: '' } }),
    { why: 'backup is on, and the first copy is written, into /Volumes/disk/keel' });
  const lost = make(Object.assign({}, ON, { writable: false }));
  /* r1.F3, r1.F4: a copy exists and something is wrong after it: done, not confirmed, with its own word */
  const HOURLY = 'The next hourly run tries again. The run\'s log is ' + LOG + '.';
  const later = make(Object.assign({}, ON, { first: WRITTEN.at, copy: { state: 'failed', at: WRITTEN.at, said: 'could not list the store. Check the disk.', fix: HOURLY } }),
    { done: true, sure: false, word: 'last run failed', why: 'backup is on and has a copy, but the last run stopped: could not list the store' });
  body(later);
  const sameDisk = make(Object.assign({}, ON, { folder: '/srv/keel-backup', same_disk: true, copy: WRITTEN }));
  /* no run, no lock, no success, no error: a copy still to come, then one that never started */
  const SOON = 'No copy is being written right now. Shipyard starts one by itself within a few minutes. You can go on to the next step.';
  const NEVER = 'No copy has been written since backup was turned on 25 minutes ago, and none is being written now.';
  const FIX = 'Shipyard starts one by itself while this computer is awake, and files a notice on the board if none succeeds. The run\'s log is ' + LOG + '.';
  const young = make(Object.assign({}, ON, { copy: { state: 'none', late: false, at: null, said: SOON, fix: FIX } }), PENDING);
  const late = make(Object.assign({}, ON, { copy: { state: 'none', late: true, at: null, said: NEVER, fix: FIX } }),
    { done: false, why: 'backup is on, but no copy has been written and none is being written' });
  /* a run that died, with the reason the tool left; and the proof in its other states */
  const DIED = 'gpg did not run (it is not installed, or not on this run\'s PATH), and every copy is encrypted with it. Install it (on a Mac: brew install gnupg). The next run then writes the copy.';
  const AGAIN = 'Shipyard starts another within a minute or two while this computer is awake, then again about every ten minutes, up to three an hour. The run\'s log is ' + LOG + '.';
  const died = make(Object.assign({}, ON, { gpg: NO_GPG, copy: { state: 'failed', at: null, said: DIED, fix: AGAIN } }),
    { done: false, why: 'backup is on, but the last run wrote no copy: ' + DIED });
  const unproven = make(Object.assign({}, ON, { copy: WRITTEN, proof: { state: 'failed', at: null,
    said: 'The last restore proof failed: keel unreadable at 2026-10-17T23:01:00Z',
    fix: 'It runs again by itself on Sunday 25 October. Its log is /srv/.keel-backup/logs/verify.out.' } }));
  const missed = make(Object.assign({}, ON, { copy: WRITTEN, proof: { state: 'missed', at: null,
    said: 'The restore proof due Sunday 18 October did not run.',
    fix: 'It runs again by itself on Sunday 25 October. Its log is /srv/.keel-backup/logs/verify.out.' } }));
  let answer = null;
  off.act = (body) => { off._acted.push(body); return Promise.resolve(answer); };
  [off, noGpg, refusedGpg, fresh, settled, lost, sameDisk, young, late, died, unproven, missed].forEach(body);
  setImmediate(function () {
    let b = body(off);
    check('backup: the folder is filled with the suggested one', field(b).value === '/srv/keel-backup');
    check('backup: one button, and nothing sent before it', !!named(b, 'Turn on backup') && off._acted.length === 0);
    off.refusal = () => ({ error: INSIDE, detail: { kind: 'inside', suggested: '/srv/keel-backup' } });
    field(b)._on.oninput({ target: { value: '/i/state/copies' } });
    press(named(b, 'Turn on backup'));
    setImmediate(function () {
      check('backup: the tap sends the one verb with the folder typed', sent(off, 'firstrun.backup.on').length === 1 &&
        sent(off, 'firstrun.backup.on')[0].folder === '/i/state/copies');
      b = body(off);
      const line = keyed(b, 'stuck-backup-refused');
      check('backup: a folder inside the install is refused in the design\'s words', !!line && text(keyed(line, 'stuck-what')).indexOf(INSIDE) >= 0);
      check('backup: its fix is Use the suggested folder', JSON.stringify(labels(keyed(line, 'stuck-fix'))) === JSON.stringify(['Use the suggested folder']));
      press(named(line, 'Use the suggested folder'));
      b = body(off);
      check('backup: which puts the suggested folder back and clears the line', field(b).value === '/srv/keel-backup' &&
        !keyed(b, 'stuck-backup-refused'));
      /* turned on: the answer carries the passphrase, once */
      answer = { folder: '/srv/keel-backup', passphrase: 'correct-horse', key: '/srv/.keel-backup/backup.key', kept_key: false };
      press(named(b, 'Turn on backup'));
      setImmediate(function () {
        stepOf(off.App.data.firstrun, 'backup').backup = ON;
        b = body(off);
        const key = keyed(b, 'backup-passphrase');
        check('backup: the passphrase is shown, with Copy', text(tags(key, 'H3')[0]) === 'Your recovery passphrase' &&
          codes(key).indexOf('correct-horse') >= 0 && !!named(key, 'Copy'));
        check('backup: with the tick, in the design\'s words', text(key).indexOf('I saved it somewhere that is not this computer.') >= 0);
        check('backup: while it is shown, its panel names the key file, once', text(key).indexOf('/srv/.keel-backup/backup.key') >= 0 && !keyed(b, 'backup-keyfile'));
        const tick = keyed(key, 'backup-saved');
        tick._on.onchange({ target: { checked: true } });
        b = body(off);
        check('backup: ticking it takes the passphrase off the page', !keyed(b, 'backup-passphrase') && text(b).indexOf('correct-horse') < 0);
        /* review r2.F6: after the tick, and on a page that never had the answer, the key file is named */
        const KEYFILE = 'The recovery passphrase is kept on this computer in /srv/.keel-backup/backup.key. Without it a copy cannot be read, so keep it somewhere that is not this computer too.';
        check('backup: after the tick the panel says where the key file is', text(keyed(b, 'backup-keyfile')) === KEYFILE);
        check('backup: and so does a fresh page, which was never given the passphrase', text(keyed(body(fresh), 'backup-keyfile')) === KEYFILE);
        /* c-757: nothing is writing it, so the row does not spin: a copy still to come, then one that never started */
        b = body(young);
        check('backup: with no run, the first copy is waiting, not being written', st(keyed(b, 'backup-first')) === 'waiting' &&
          text(keyed(b, 'backup-first')).indexOf(SOON) >= 0 && !!keyed(b, 'backup-go'));
        b = body(late);
        const none = keyed(b, 'stuck-backup-first');
        check('backup: a copy that never started is a stuck line that says so', !!none && text(keyed(none, 'stuck-what')).indexOf(NEVER) >= 0);
        check('backup: with the log\'s path, and no word that you can go on', text(none).indexOf(LOG) >= 0 && !keyed(b, 'backup-go'));
        check('backup: its sentence is the step\'s, as a warning', text(keyed(b, 'why')) === 'Backup is on, but no copy has been written and none is being written.' &&
          !has(keyed(b, 'why'), 'done'));

        /* on, first copy pending: no Done above a spinner, the way on said and Next ready */
        b = body(fresh);
        check('backup: on, the folder can be written', st(keyed(b, 'backup-folder')) === 'ready' && text(keyed(b, 'backup-folder')).indexOf('Folder can be written') >= 0);
        check('backup: the first copy is being written, and the row says you can go on', st(keyed(b, 'backup-first')) === 'checking' &&
          text(keyed(b, 'backup-first')).indexOf('First copy written') >= 0 && text(keyed(b, 'backup-first')).indexOf(GO) >= 0);
        check('backup: pending is not said as Done: ' + text(keyed(b, 'why')),
          text(keyed(b, 'why')) === 'Backup is on, into /Volumes/disk/keel. The first copy is being written in the background.' && !has(keyed(b, 'why'), 'done'));
        check('backup: the screen says the copy is written in the background and to press Next',
          text(keyed(b, 'backup-go')) === 'Backup is on. The first copy is written in the background, so you can go on: press Next. This page shows the copy once it is written.');
        check('backup: and Next is the way on', !!named(b, 'Next') && !named(b, 'Next').hasAttribute('disabled') && has(named(b, 'Next'), 'primary'));
        check('backup: the proof row names the real day', st(keyed(b, 'backup-proof')) === 'waiting' &&
          text(keyed(b, 'backup-proof')).indexOf('First proof on Sunday 18 October, once there is a copy to prove.') >= 0);
        check('backup: no passphrase on a page that did not turn it on', !keyed(b, 'backup-passphrase') && !named(b, 'Turn on backup'));
        check('backup: the words say what happens now', text(keyed(b, 'backup-where')) === 'An encrypted copy of the board is written to /Volumes/disk/keel about every hour, when something on the board has changed. If a copy is overdue, Shipyard starts one itself. Copies are kept hourly for a day and daily for thirty days. If none succeeds, a notice appears on the board.');
        check('backup: a folder on another disk gets no same-disk line', !keyed(b, 'backup-disk'));
        /* the step list says the same two states */
        fresh.App.step = 'browser';
        check('backup: in the step list, pending is said as copy pending', text(keyed(body(fresh), 'go-backup')).indexOf('copy pending') >= 0);
        settled.App.step = 'browser';
        check('backup: and written is done', text(keyed(body(settled), 'go-backup')).indexOf('done') >= 0 &&
          text(keyed(body(settled), 'go-backup')).indexOf('pending') < 0);
        fresh.App.step = 'backup'; settled.App.step = 'backup';
        b = body(settled);
        check('backup: once written and proven, both are ready', st(keyed(b, 'backup-first')) === 'ready' && st(keyed(b, 'backup-proof')) === 'ready');
        check('backup: each says when, in words', /Written .+ ago/.test(text(keyed(b, 'backup-first'))) &&
          /Proved .+ ago\. The next one is due Sunday 25 October\./.test(text(keyed(b, 'backup-proof'))));
        check('backup: written is Done, with no word about waiting', text(keyed(b, 'why')) === 'Done: backup is on, and the first copy is written, into /Volumes/disk/keel' && !keyed(b, 'backup-go'));
        check('backup: a proof that passed says when the next is due', text(keyed(b, 'backup-proof')).indexOf('The next one is due Sunday 25 October.') >= 0);
        b = body(sameDisk);
        check('backup: a folder on the install\'s own disk says what that protects against', text(keyed(b, 'backup-disk')) ===
          'That folder is on the same disk as this install. Unless that folder is synced somewhere else, a copy there does not survive losing the disk or the computer.');

        /* a run that died: the tool's own reason, and the way to the gpg row when that is why */
        b = body(died);
        const dead = keyed(b, 'stuck-backup-first');
        check('backup: a run that died shows the reason the tool left', !!dead && text(keyed(dead, 'stuck-what')).indexOf(DIED) >= 0);
        check('backup: its fix says it is tried again, and leads to the gpg row', text(keyed(dead, 'stuck-fix')).indexOf(AGAIN) >= 0 &&
          JSON.stringify(labels(keyed(dead, 'stuck-fix'))) === JSON.stringify(['Open Check this computer']));
        press(named(dead, 'Open Check this computer'));
        check('backup: which opens Check this computer', died.App.step === 'prerequisites');
        /* the proof, failed and missed */
        b = body(unproven);
        let proof = keyed(b, 'stuck-backup-proof');
        check('backup: a proof that failed is a stuck line with its reason', !!proof &&
          text(keyed(proof, 'stuck-what')).indexOf('The last restore proof failed: keel unreadable at 2026-10-17T23:01:00Z') >= 0 &&
          text(keyed(proof, 'stuck-fix')).indexOf('It runs again by itself on Sunday 25 October.') >= 0);
        proof = keyed(body(missed), 'stuck-backup-proof');
        check('backup: a proof that did not run is said as that', !!proof &&
          text(keyed(proof, 'stuck-what')).indexOf('The restore proof due Sunday 18 October did not run.') >= 0);

        /* gpg: said before the tap, and after a tap the server refused, each with the way to its row */
        b = body(noGpg);
        let gpg = keyed(b, 'stuck-backup-gpg');
        check('backup: with no gpg the step says so before the tap', !!gpg && text(keyed(gpg, 'stuck-what')).indexOf('The gpg program is not installed on this computer.') >= 0);
        check('backup: and points at its row on Check this computer', JSON.stringify(labels(keyed(gpg, 'stuck-fix'))) === JSON.stringify(['Open Check this computer']));
        check('backup: the suggested folder is on the install\'s disk, and the step says what that means',
          text(keyed(b, 'backup-disk')) === 'The suggested folder is on the same disk as this install. Unless that folder is synced somewhere else, a copy there does not survive losing the disk or the computer.');
        b = body(refusedGpg);
        gpg = keyed(b, 'stuck-backup-gpg');
        check('backup: a turn-on refused for gpg says the server\'s words, once', !!gpg && text(keyed(gpg, 'stuck-what')).indexOf(REFUSED) >= 0 &&
          !keyed(b, 'stuck-backup-refused'));
        press(named(gpg, 'Open Check this computer'));
        check('backup: and its button opens that step', refusedGpg.App.step === 'prerequisites');
        b = body(later);
        const after = keyed(b, 'stuck-backup-first');
        check('backup: a run that failed after a copy says when the copy was written and what stopped', !!after &&
          /The newest copy was written .+ ago\. The run after it stopped: could not list the store\./.test(text(keyed(after, 'stuck-what'))) &&
          text(keyed(after, 'stuck-fix')).indexOf('The next hourly run tries again.') >= 0);
        check('backup: the step stays done, is not said as Done, and Next is on: ' + text(keyed(b, 'why')),
          text(keyed(b, 'why')) === 'Backup is on and has a copy, but the last run stopped: could not list the store.' &&
          !has(keyed(b, 'why'), 'done') && !named(b, 'Next').hasAttribute('disabled') && !named(b, 'Skip'));
        later.App.step = 'browser';
        check('backup: the step list says last run failed', text(keyed(body(later), 'go-backup')).indexOf('last run failed') >= 0);
        later.App.step = 'set-up';
        b = body(later);
        check('backup: the last screen lists it under What was set, with that sentence, never under What was skipped',
          text(keyed(keyed(b, 'setup-set'), 'set-backup')).indexOf('Backup is on and has a copy, but the last run stopped: could not list the store.') >= 0 &&
          !keyed(b, 'skipped-backup'));
        fresh.App.step = 'set-up';
        b = body(fresh);
        check('backup: a copy still to come is under What was set too', !!keyed(keyed(b, 'setup-set'), 'set-backup') && !keyed(b, 'skipped-backup'));
        died.App.step = 'set-up';
        b = body(died);
        check('backup: a first run that failed is under What was skipped, with Set it up', !!keyed(keyed(b, 'setup-skipped'), 'skipped-backup') &&
          !keyed(b, 'set-backup'));
        fresh.App.step = 'backup'; died.App.step = 'backup';
        b = body(lost);
        check('backup: a folder that went away is a stuck line', !!keyed(b, 'stuck-backup-folder') &&
          text(keyed(b, 'stuck-backup-folder')).indexOf('/Volumes/disk/keel is not there or cannot be written') >= 0);
        done();
      });
    });
  });
}

/* Your first card: the form and the card Bosun suggested, then the card's path past review
   to landed, with its two answers at a gate, the refused landing and the Push */
function firstCards(done) {
  const SUGGEST = { space: 'work', repo: 'api', file: 'api/CLAUDE.md', title: 'Add a setup section to the README',
                    saw: 'the README has no setup section' };
  const make = (card, more, cardMore, plans) => {
    const fr = firstrun(null, true);
    Object.assign(stepOf(fr, 'first-card'), { done: false }, more || {});
    stepOf(fr, 'defaults').plans = { work: !!plans };
    const cards = card ? [deck.card(card.id, Object.assign({ space: 'work', repo: 'api', title: 'Fix a typo' }, cardMore || {}))] : [];
    if (card) stepOf(fr, 'first-card').card = card;
    const K = at('first-card', fr, null, { cards: cards });
    K.App.data.spaces.work.repos = ['api', 'web'];
    K.App.data.spaces.personal.repos = ['packs', 'memory'];
    return K;
  };
  const field = (b, key) => deck.all(b, (n) => n.nodeType === 1 && n.getAttribute('data-fk') === key)[0];
  const places = (b) => keyedAll(b, 'first-place').map((n) => n.getAttribute('data-place') + ':' + n.getAttribute('data-at'));
  const nowAt = (b) => (places(b).filter((p) => /:now$/.test(p))[0] || '').split(':')[0];
  const card = (stage, extra) => Object.assign({ id: 'c-5', title: 'Fix a typo', stage: stage, space: 'work', blocked: null }, extra || {});
  const empty = make(null);
  const offered = make(null, { suggestion: SUGGEST });
  const waiting = make(card('assigned'), null, { stage: 'assigned' });
  const planGate = make(card('planning'), null, { stage: 'planning', derived: { plan_gate: true, needs_you: true } }, true);
  const building = make(card('building'), null, { stage: 'building' });
  const ready = make(card('review'), null, { stage: 'review', derived: { outcome_gate: true, needs_you: true } });
  const landing = make(card('review'), null, { stage: 'review', derived: { outcome_gate: true, landing: true } });
  const WHY = 'outcome not merged: tests failed on the merged tree (`npm test` exited 1); nothing was merged; failed: 2';
  const refused = make(card('review', { blocked: WHY }), null, { stage: 'review', blocked_reason: WHY, derived: { outcome_gate: true, needs_you: true } });
  /* the Push comes with the card's own detail, which the screen asks for once it has landed
     (the state no longer carries it on every build) */
  const local = make(card('done'), { done: true }, { stage: 'done' });
  const asked = [];
  local.loadDetail = (id) => { asked.push(id); };
  /* review r2.F4: two repos and a list nobody touched; and a chosen repo that went away */
  const untouched = make(null);
  const went = make(null);
  [empty, offered, waiting, planGate, building, ready, landing, refused, local, untouched, went].forEach(body);
  setImmediate(function () {
    let b = body(empty);
    const form = keyed(b, 'first-form');
    check('first card: the form asks what to do, more about it and the repo', ['What to do', 'More about it', 'Repo'].every((w) => text(form).indexOf(w) >= 0));
    check('first card: the repos that are in, and not the install\'s own packs', JSON.stringify(tags(form, 'OPTION').map(text)) === JSON.stringify(['api', 'web']));
    check('first card: no suggestion where Bosun left none', !keyed(b, 'first-suggestion'));
    field(b, 'first-title')._on.oninput({ target: { value: 'Fix a typo' } });
    field(b, 'first-repo')._on.onchange({ target: { value: 'work/web' } });
    press(named(b, 'File and start'));
    const made = sent(empty, 'create')[0];
    /* c-729: the user's words go as words; the server makes the short title */
    check('first card: File and start files it in the repo\'s space and starts it: ' + JSON.stringify(made), !!made && made.space === 'work' &&
      made.repo === 'web' && made.words === 'Fix a typo' && !made.title && made.start === true);

    b = body(untouched);
    check('first card: with two repos the first is the one chosen, as the list shows it',
      tags(b, 'OPTION').map((n) => !!n.selected).join() === 'true,false');
    field(b, 'first-title')._on.oninput({ target: { value: 'Fix a typo' } });
    press(named(b, 'File and start'));
    const plainly = sent(untouched, 'create')[0];
    check('first card: File and start with the list untouched files it in the repo that is shown: ' + JSON.stringify(plainly),
      !!plainly && plainly.space === 'work' && plainly.repo === 'api');
    b = body(went);
    field(b, 'first-title')._on.oninput({ target: { value: 'Fix a typo' } });
    field(b, 'first-repo')._on.onchange({ target: { value: 'work/web' } });
    went.App.data.spaces.work.repos = ['api'];
    b = body(went);
    press(named(b, 'File and start'));
    const after = sent(went, 'create')[0];
    check('first card: a chosen repo that is gone gives way to the first that is in: ' + JSON.stringify(after),
      !!after && after.space === 'work' && after.repo === 'api');

    b = body(offered);
    const idea = keyed(b, 'first-suggestion');
    check('first card: the card Bosun suggested, in the design\'s words: ' + text(keyed(idea, 'first-suggested')), text(tags(idea, 'H3')[0]) === 'A first card you could use' &&
      text(keyed(idea, 'first-suggested')) === 'While drafting api/CLAUDE.md, Bosun saw that the README has no setup section. Want that as your first card?');
    press(named(idea, 'Use this'));
    b = body(offered);
    check('first card: Use this fills the form and sends nothing', field(b, 'first-title').value === 'Add a setup section to the README' &&
      offered._acted.length === 0);

    check('first card: a filed card waits for a session: ' + JSON.stringify(places(body(waiting))), nowAt(body(waiting)) === 'waiting' &&
      places(body(waiting)).length === 7);
    b = body(planGate);
    check('first card: a space that shows plans has the plan on the path, and the card is there', nowAt(b) === 'plan' && places(b).length === 8);
    check('first card: with Approve and Send back for the plan', !!named(b, 'Approve') && !!named(b, 'Send back'));
    press(named(b, 'Approve'));
    check('first card: Approve there answers the plan gate', sent(planGate, 'approve')[0].gate === 'plan' && sent(planGate, 'approve')[0].id === 'c-5');
    check('first card: building', nowAt(body(building)) === 'building' && !named(body(building), 'Approve'));

    b = body(ready);
    check('first card: at review it is ready for you, past checking its own work', nowAt(b) === 'ready' &&
      places(b).indexOf('checking:past') >= 0);
    check('first card: with the card\'s two answers', !!named(b, 'Approve') && !!named(b, 'Send back'));
    press(named(b, 'Send back'));
    b = body(ready);
    field(b, 'first-back')._on.oninput({ target: { value: 'the heading is wrong' } });
    press(named(b, 'Send it back'));
    const back = sent(ready, 'sendback')[0];
    check('first card: Send back sends the words as the reason: ' + JSON.stringify(back), !!back && back.id === 'c-5' && back.reason === 'the heading is wrong');
    press(named(body(ready), 'Approve'));
    check('first card: Approve answers the outcome gate', sent(ready, 'approve')[0].gate === 'outcome');

    b = body(landing);
    check('first card: an approved card is landing, with no answer to give', nowAt(b) === 'landing' && !named(b, 'Approve'));
    b = body(refused);
    const line = keyed(b, 'stuck-first-landing');
    check('first card: a refused landing is a stuck line in the server\'s words', nowAt(b) === 'landing' && !!line && text(keyed(line, 'stuck-what')).indexOf('nothing was merged') >= 0);
    press(named(line, 'Send back with the failures'));
    check('first card: its fix sends those words back', sent(refused, 'sendback').length === 1 && sent(refused, 'sendback')[0].reason === WHY);

    b = body(local);
    check('first card: a landed card asks for its own detail, once: ' + JSON.stringify(asked), JSON.stringify(asked) === JSON.stringify(['c-5']) &&
      !keyed(b, 'push-said'));
    local.App.detail = { card: local.App.data.cards[0], push: { repo: 'api', branch: 'main', remote: 'origin', pushed: false,
      said: 'Merged into main on this computer.', testing: false, refused: null } };
    local.App.detailFor = 'c-5';
    b = body(local);
    check('first card: landed on this computer says so, with the Push: ' + JSON.stringify(labels(keyed(b, 'first-path'))), nowAt(b) === 'landed' &&
      text(keyed(b, 'push-said')) === 'Merged into main on this computer.' && !!named(b, 'Push main to origin'));
    press(named(b, 'Push main to origin'));
    check('first card: the Push is the card\'s own', sent(local, 'land.push').length === 1 && sent(local, 'land.push')[0].id === 'c-5');
    /* review r2.F14: another card's detail took its place, so it is asked for again, once */
    local.App.detail = { card: { id: 'c-9' } };
    local.App.detailFor = 'c-9';
    body(local);
    body(local);
    check('first card: when another card\'s detail took its place it asks again, once: ' + JSON.stringify(asked),
      JSON.stringify(asked) === JSON.stringify(['c-5', 'c-5']));
    done();
  });
}

/* You are set up: where to go when something does not work, what was set and what was
   skipped, the phone and voice folded under More to set up later, and the two ways on */
function setUps(done) {
  const fr = firstrun(null, true);
  fr.steps.forEach((s) => { if (s.done !== null) { s.done = true; s.why = 'why ' + s.id; } });
  Object.assign(stepOf(fr, 'backup'), { done: false, why: 'no backup is set up: the board lives only in this install' });
  Object.assign(stepOf(fr, 'browser'), { done: false, skipped: '2026-10-03T10:00:00+00:00', why: 'Shipyard\'s browser is not installed' });
  stepOf(fr, 'first-card').card = { id: 'c-5', title: 'Fix a typo', stage: 'done', space: 'work' };
  const CMDS = { prepare: { value: 'npm ci', line: 4 }, test: { value: 'npm test', line: 5 }, lands: { value: 'main', line: 8 } };
  const drafts = [{ aim: 'work/api', label: 'api/CLAUDE.md', state: 'adopted', lines: 'run', commands: CMDS },
                  { aim: 'work/web', label: 'web/CLAUDE.md', state: 'adopted', lines: 'changed', commands: CMDS },
                  { aim: 'work/docs', label: 'docs/CLAUDE.md', state: 'adopted', lines: 'never', commands: CMDS },
                  { aim: 'work', label: 'workspace CLAUDE.md', state: 'idle', commands: null }];
  const report = Object.assign({}, REPORT, { spaces: {
    personal: { pack: null, tier: null, writable: true, proposal: null, repos: [{ key: 'packs' }, { key: 'memory' }], drafts: [] },
    work: { pack: null, tier: null, writable: true, proposal: null, repos: [{ key: 'api' }, { key: 'web' }], drafts: drafts } } });
  const K = at('set-up', fr, report, { state: { console: { attach: ATTACH, up: true } } });
  const bare = at('set-up', firstrun(null, true));
  [K, bare].forEach(body);
  setImmediate(function () {
    let b = body(K);
    check('set up: where things stand: ' + text(keyed(b, 'setup-lead')), text(keyed(b, 'setup-lead')) ===
      'Shipyard is running, api, web are connected, and your first card landed.');
    const help = keyed(b, 'setup-help');
    check('set up: when something does not work, Bosun\'s session, with the command and Copy', text(tags(help, 'H3')[0]) === 'When something does not work' &&
      text(help).indexOf('Bosun\'s session is where to go. Open it in a terminal with this command, or open Bosun in the Claude app (the session named Bosun).') >= 0 &&
      codes(help).indexOf(ATTACH) >= 0 && !!named(help, 'Copy'));
    check('set up: and when to go there', text(help).indexOf('Every red line in Shipyard says what happened, what to do, and how to ask Bosun in its session.') >= 0);
    const set = keyed(b, 'setup-set');
    check('set up: what was set, each step that reads done in its own sentence, with Change', text(tags(set, 'H3')[0]) === 'What was set' &&
      !!keyed(set, 'set-login') && text(keyed(set, 'set-login')).indexOf('Why login.') >= 0 && !!named(keyed(set, 'set-login'), 'Change'));
    const repo = keyed(set, 'set-repo-work/api');
    check('set up: each adopted repo file\'s prepare, test and lands-on: ' + text(repo), !!repo && text(repo).indexOf('api/CLAUDE.md') >= 0 &&
      JSON.stringify(codes(repo)) === JSON.stringify(['npm ci', 'npm test', 'main']));
    check('set up: a file that is not adopted is not listed as set', !keyed(set, 'set-repo-work'));
    /* review r2.F13: lines Keel will not run are not listed as set */
    const web = keyed(set, 'set-repo-work/web'), docs = keyed(set, 'set-repo-work/docs');
    check('set up: a file changed since it was adopted lists no line and says they are not on: ' + text(web), !!web && codes(web).length === 0 &&
      text(web).indexOf('Its lines are not on: the file changed since it was adopted or saved.') >= 0);
    check('set up: a file never adopted or saved says the same of itself: ' + text(docs), !!docs && codes(docs).length === 0 &&
      text(docs).indexOf('Its lines are not on yet: the file has not been adopted or saved.') >= 0);
    check('set up: a step with nothing to check is in neither list', !keyed(b, 'set-memory') && !keyed(b, 'skipped-memory') && !keyed(b, 'set-set-up'));
    press(named(keyed(set, 'set-login'), 'Change'));
    check('set up: Change opens that step', K.App.step === 'login');
    K.App.step = 'set-up';
    b = body(K);
    const skipped = keyed(b, 'setup-skipped');
    check('set up: what was skipped, with Set it up', text(tags(skipped, 'H3')[0]) === 'What was skipped' &&
      !!keyed(skipped, 'skipped-backup') && !!keyed(skipped, 'skipped-browser') && !keyed(skipped, 'skipped-login') &&
      text(keyed(skipped, 'skipped-backup')).indexOf('No backup is set up: the board lives only in this install.') >= 0);
    press(named(keyed(skipped, 'skipped-backup'), 'Set it up'));
    check('set up: Set it up opens that step', K.App.step === 'backup');
    K.App.step = 'set-up';
    b = body(K);
    const later = keyed(b, 'setup-later');
    check('set up: the phone and voice are under More to set up later', text(tags(later, 'SUMMARY')[0]) === 'More to set up later' &&
      codes(later).indexOf('tailscale serve --bg 8890') >= 0 && !!keyed(later, 'later-voice'));
    const ways = keyed(b, 'setup-ways');
    check('set up: the two ways on', !!named(ways, 'Open the board') && text(keyed(ways, 'open-bosun')) === 'Open Bosun' &&
      keyed(ways, 'open-bosun').getAttribute('href') === '/console');
    check('set up: no Skip on the last screen, and Finish is the frame\'s', !named(b, 'Skip') && !!named(b, 'Finish'));
    press(named(ways, 'Open the board'));
    setImmediate(function () {
      check('set up: Open the board finishes the first run and goes to the board', sent(K, 'firstrun.finish').length === 1 && K.App.view === 'cards');
      b = body(bare);
      check('set up: with no repo and no card the line says only what is true', text(keyed(b, 'setup-lead')) === 'Shipyard is running.');
      done();
    });
  });
}

/* Connect GitHub from a failed private copy: the GitHub connection's own requirement rows,
   drawn inline on Add your repos with each fix, Check again and Try the copy again */
function connects(done) {
  const SAID = 'GitHub did not let this computer read maya-okafor/web. Private repos need this computer to be signed in to GitHub.';
  const need = (name, ok, more) => Object.assign({ name: name, kind: 'command', ok: ok, why: 'why ' + name, for: ['codehost'] }, more || {});
  const github = (signedIn) => ({ name: 'github', description: 'GitHub through gh', spaces: [], rules: [], demo_only: false, checks: [
    need('gh', true), need('GitHub sign-in', signedIn, { fix: 'Run gh auth login in a terminal. Choose GitHub.com, then HTTPS, then sign in with your browser. Then check again.',
      command: 'gh auth login', done_when: '`gh auth status` names your account on github.com.' }),
    need('GitHub address', true), need('GitHub access', true)] });
  const fail = (K) => {
    const answers = [];
    K.act = (sent) => { K._acted.push(sent); return new Promise((resolve) => { answers.push(resolve); }); };
    K.refusal = () => ({ error: 'git clone failed', detail: { kind: 'private', sentence: SAID, git: 'fatal: could not read Username', slug: 'maya-okafor/web' } });
    const b = body(K);
    const input = deck.all(b, (n) => n.tagName === 'INPUT' && n.getAttribute('aria-label') === 'Repo address or folder')[0];
    input._on.oninput({ target: { value: 'https://github.com/maya-okafor/web.git' } });
    press(named(body(K), 'Add repo'));
    return answers;
  };
  const withPack = at('repos', null, Object.assign({}, REPORT, { packs: [github(false)] }), { state: { console: { attach: ATTACH, up: true } }, ready: true });
  const noPack = at('repos', null, null);
  [withPack, noPack].forEach(body);
  setImmediate(function () {
    const first = fail(withPack), bare = fail(noPack);
    first[0](null); bare[0](null);
    setImmediate(function () {
      let b = body(withPack);
      let row = keyed(keyed(b, 'adding-1'), 'stuck-copied-1');
      check('connect: a private copy that failed says so in the design\'s words', text(keyed(row, 'stuck-what')).indexOf(SAID) >= 0);
      check('connect: its fix is Connect GitHub, and nothing is open yet', !!named(row, 'Connect GitHub') && !keyed(b, 'connect-1'));
      press(named(row, 'Connect GitHub'));
      b = body(withPack);
      const panel = keyed(b, 'connect-1');
      check('connect: the connection\'s checks open right there, one row each: ' + JSON.stringify(keyedAll(panel, 'connect-check').map((n) => n.getAttribute('data-name'))),
        JSON.stringify(keyedAll(panel, 'connect-check').map((n) => n.getAttribute('data-name'))) ===
        JSON.stringify(['gh', 'GitHub sign-in', 'GitHub address', 'GitHub access']));
      const signIn = keyed(panel, 'stuck-gh-GitHub sign-in');
      check('connect: a check that fails is the stuck line with the pack\'s own fix and its command', !!signIn &&
        text(keyed(signIn, 'fix-said')).indexOf('Run gh auth login in a terminal.') === 0 && codes(signIn).indexOf('gh auth login') >= 0 &&
        !!named(signIn, 'Copy'));
      check('connect: a check that passes is a ready row', st(keyed(panel, 'gh-gh')) === 'ready');
      check('connect: opening it sent nothing, and turned nothing on', withPack._acted.length === 1 && !named(panel, 'Turn on'));
      check('connect: Check again and Try the copy again are there', !!named(panel, 'Check again') && !!named(panel, 'Try the copy again'));
      const before = withPack._fetched.filter((u) => u === '/api/setup').length;
      press(named(panel, 'Check again'));
      check('connect: Check again reads the report again', withPack._fetched.filter((u) => u === '/api/setup').length === before + 1);
      withPack._report = Object.assign({}, REPORT, { packs: [github(true)] });
      press(named(keyed(body(withPack), 'connect-1'), 'Check again'));
      setImmediate(function () {
        b = body(withPack);
        check('connect: once signed in every row is ready', keyedAll(keyed(b, 'connect-1'), 'connect-check').every((n) => n.getAttribute('data-state') === 'ready'));
        press(named(keyed(b, 'connect-1'), 'Try the copy again'));
        check('connect: Try the copy again sends the same add: ' + JSON.stringify(withPack._acted.map((a) => a.url)), withPack._acted.length === 2 &&
          withPack._acted[1].verb === 'setup.repo.add' && withPack._acted[1].url === 'https://github.com/maya-okafor/web.git');
        row = keyed(keyed(body(noPack), 'adding-1'), 'stuck-copied-1');
        check('connect: with no GitHub connection offered there is no Connect GitHub, only the copy again', !named(row, 'Connect GitHub') &&
          !!named(row, 'Try the copy again'));
        done();
      });
    });
  });
}

/* Another provider: the draft choice, its box and its one tap, and the check that follows the card */
function providers(done) {
  const C = 'For a code host Shipyard ships no connection for. Bosun writes the connection as a card: you read its plan and approve the result, ' +
    'and nothing changes until you turn the connection on. Until then, work stays on this computer, which works with any git host.';
  const lands = { personal: { remote: 'origin', fetch: true, push: true, repos: [{ key: 'api', host: 'git.example.org', branch: 'main' }] } };
  const make = (connection) => at('integrations', null, Object.assign(withStart({ lands: lands }),
    { builder: { mode: 'in-app', label: 'Builder', repos: ['packs'], importing: null, connection: connection } }));
  const none = make({ open: null, done: null });
  const open = make({ open: { card: 'c-12', stage: 'planning', waiting: false }, done: null });
  const landed = make({ open: null, done: 'c-12' });
  [none, open, landed].forEach(body);
  setImmediate(function () {
    let b = body(none);
    /* c-729: the draft is one of the choices, opened by its own control; this computer stays in use */
    const how = keyed(b, 'lands-how-personal-draft');
    check('provider: the draft choice, by its name', !!how && text(how).indexOf('Have Bosun draft one for another provider') === 0 &&
      !keyed(b, 'lands-draft-personal'));
    how._on.onclick({});
    b = body(none);
    const opt = keyed(b, 'lands-draft-personal');
    check('provider: opened, its section is drawn, and this computer still says it is in use', !!opt &&
      text(keyed(opt, 'lands-c-said')) === C && keyed(b, 'lands-how-personal-draft').getAttribute('aria-checked') === 'true' &&
      text(keyed(b, 'lands-how-personal-local')).indexOf('in use') >= 0 && !keyed(b, 'lands-local-personal'));
    const box = tags(opt, 'TEXTAREA')[0];
    check('provider: a box that asks which code host and what Shipyard should do there', !!box &&
      box.getAttribute('aria-label') === 'Which code host, and what should Shipyard do there?');
    /* c-729: an example of what to write, as the box's placeholder, never its text */
    check('provider: its example is the placeholder, with the host, what to do there and the sign-in',
      /^For example: GitLab\. /.test(box.getAttribute('placeholder') || '') && box.getAttribute('placeholder').indexOf('Open each card\'s change for review') >= 0 &&
      box.getAttribute('placeholder').indexOf('approves') < 0 &&
      box.getAttribute('placeholder').indexOf('Sign-in') >= 0 && !box.value);
    check('provider: the draft check waits', st(keyed(opt, 'connection-draft')) === 'waiting' &&
      text(keyed(opt, 'connection-draft')).indexOf('Draft of the connection') >= 0 && none._acted.length === 0);
    box._on.oninput({ target: { value: 'Gitea, a teammate merges' } });
    /* c-730: whether the drafted connection should also bring review requests, unticked */
    const reviews = () => deck.all(keyed(body(none), 'lands-draft-personal'), (n) => n.getAttribute && n.getAttribute('data-key') === 'lands-c-reviews')[0];
    const tick = () => (reviews() ? deck.all(reviews(), (n) => n.tagName === 'INPUT')[0] : null);
    check('provider: it asks whether the connection should bring review requests too, unticked',
      text(reviews()).indexOf('Should it also bring you pull requests that wait on your review?') >= 0 && !!tick() && !tick().checked);
    if (tick()) tick()._on.onchange({ target: { checked: true } });
    press(named(keyed(body(none), 'lands-draft-personal'), 'Have Bosun draft a connection'));
    check('provider: the tap files the card with the space, the words and the answer: ' + JSON.stringify(none._acted),
      JSON.stringify(none._acted) === JSON.stringify([{ verb: 'setup.pack.draft', space: 'personal', words: 'Gitea, a teammate merges', reviews: true }]));
    b = body(open);
    const going = keyed(b, 'lands-draft-personal');
    check('provider: while the card is open its choice is open by itself, and the check says where it is, with the card', st(keyed(going, 'connection-draft')) === 'checking' &&
      text(keyed(going, 'connection-draft')).indexOf('Bosun is writing its plan (c-12).') >= 0 && !!named(going, 'Open c-12'));
    check('provider: and there is no second box or tap', !tags(going, 'TEXTAREA').length && !named(going, 'Have Bosun draft a connection'));
    keyed(body(landed), 'lands-how-personal-draft')._on.onclick({});
    b = body(landed);
    /* c-758 r1.F3: a landing whose connection is not listed anywhere never reads as ready, and
       points at no row: it offers the card and Look again */
    check('provider: a draft that landed with nothing listed says so, and is not ready: ' + text(keyed(b, 'connection-draft')),
      st(keyed(b, 'connection-draft')) === 'waiting' && text(keyed(b, 'connection-draft')).indexOf(
        'c-12 landed, and no connection from it is listed on this install. Open the card to see what it added, or press Look again.') >= 0 &&
      text(keyed(b, 'lands-draft-personal')).indexOf('someone shared with you') < 0 &&
      !!named(keyed(b, 'lands-draft-personal'), 'Open c-12') && !!named(keyed(b, 'lands-draft-personal'), 'Look again'));
    done();
  });
}

/* c-734 point 3: after an action the page stays on its step, and a resume never passes a step
   the user has not been through (Adopt on step 6 jumped to step 9 on the second stranger run:
   the screen was the resumed one, and steps 7 and 8 have nothing to check) */
function stays(done) {
  const reached = () => {
    const fr = firstrun(null, true, true);
    ['memory'].forEach((id) => Object.assign(stepOf(fr, id), { done: true, seen: '2026-10-10T06:00:00+00:00' }));
    ['rules', 'browser', 'backup', 'first-card'].forEach((id) => { stepOf(fr, id).done = false; });
    stepOf(fr, 'integrations').done = null;     /* no pack: B, the default, stands and nothing is checked */
    return fr;
  };
  const K = page(reached(), 'start');
  K.App.step = null;
  const screen = (k) => { const s = deck.all(body(k), (n) => /^screen-/.test(n.getAttribute && n.getAttribute('data-key') || ''))[0]; return s ? s.getAttribute('data-key') : null; };
  setImmediate(function () {
    check('stays: the resumed screen is the first open step', screen(K) === 'screen-rules');
    stepOf(K.App.data.firstrun, 'rules').done = true;           /* Adopt landed: the step is done */
    check('stays: after the action the page is still on that step: ' + screen(K), screen(K) === 'screen-rules');
    const fresh = page((() => { const fr = reached(); stepOf(fr, 'rules').done = true; return fr; })(), 'start');
    fresh.App.step = null;
    check('stays: a resume stops at a step with nothing to check that the user has not been through: ' + screen(fresh),
      screen(fresh) === 'screen-integrations');
    done();
  });
}

/* c-734 point 4: a setup card moved from elsewhere (`firstrun.watch` moved) reads the Setup
   report again, on Start and on Setup, with no reload */
function follows(done) {
  const K = page(Object.assign(firstrun(null, true), { watch: 'a1' }), 'start');
  K.App.step = 'integrations';
  const reads = () => K._fetched.filter((u) => u === '/api/setup').length;
  body(K);
  setImmediate(function () {
    const first = reads();
    body(K);
    check('follows: the same stamp reads nothing again', reads() === first);
    K.App.data.firstrun.watch = 'b2';
    body(K);
    setImmediate(function () {
      check('follows: a new stamp reads the report again: ' + first + ' then ' + reads(), reads() === first + 1);
      K.App.view = 'setup';
      K.App.data.firstrun.watch = 'c3';
      body(K);
      setImmediate(function () {
        check('follows: on Setup too', reads() === first + 2);
        done();
      });
    });
  });
}

/* c-734 point 5: a drafted connection that landed is offered under the draft choice, open by
   itself, its own row the one tap to turn it on; point 9: the draft says before the tap what
   it is, and the check says where it stands, the gate that waits on the user, and that Bosun
   has been told */
function drafted(done) {
  const lands = { personal: { remote: 'origin', fetch: true, push: true, repos: [{ key: 'api', host: 'git.example.org', branch: 'main' }] } };
  const pack = (name, spaces, folder) => ({ name: name, description: 'a pack', spaces: spaces || [], rules: [], checks: [], folder: folder || null });
  const make = (connection) => at('integrations', null, Object.assign(withStart({ lands: lands }),
    { packs: [pack('github'), pack('forge', [], '/i/packs/forge')],
      builder: { mode: 'in-app', label: 'Builder', repos: ['packs'], importing: null, connection: connection } }));
  const landed = make({ open: null, done: 'c-12', pack: 'forge', space: 'personal' });
  /* r2.F4: drafted for another space, or before the space was recorded: not opened here */
  const elsewhere = make({ open: null, done: 'c-12', pack: 'forge', space: 'team' });
  const unknown = make({ open: null, done: 'c-12', pack: 'forge', space: null });
  const none = make({ open: null, done: null, pack: null });
  const asked = make({ open: { card: 'c-12', stage: 'planning', waiting: false, gate: 'plan', told: true }, done: null, pack: null });
  const queued = make({ open: { card: 'c-12', stage: 'assigned', waiting: false, gate: null, told: false }, done: null, pack: null });
  [landed, elsewhere, unknown, none, asked, queued].forEach(body);
  setImmediate(function () {
    let b = body(landed);
    const a = keyed(b, 'lands-how-personal-draft');
    check('drafted: the landed connection\'s choice is open by itself, and says it is not turned on: ' + text(a), !!a && a.getAttribute('aria-checked') === 'true' &&
      text(a).indexOf('Drafted (c-12), not turned on yet') >= 0);
    const setup = keyed(b, 'lands-draft-personal');
    check('drafted: its row is there with the one tap to turn it on, and the shipped ones are under their own choice (r2.F4)',
      !!setup && !!keyed(setup, 'pack-forge') && !keyed(setup, 'pack-github') && !!named(setup, 'Turn on for personal') &&
      text(keyed(b, 'lands-how-personal-shipped')).indexOf('Shipped: github') >= 0);
    [['for another space', elsewhere], ['for no recorded space', unknown]].forEach(function (pair) {
      const how = keyed(body(pair[1]), 'lands-how-personal');
      check('drafted: a connection drafted ' + pair[0] + ' is not opened here, and is listed as found in the install (r2.F4)',
        keyed(how, 'lands-how-personal-local').getAttribute('aria-checked') === 'true' &&
        keyed(how, 'lands-how-personal-draft').getAttribute('aria-checked') === 'false' &&
        text(keyed(how, 'lands-how-personal-draft')).indexOf('Drafted') < 0 &&
        text(keyed(how, 'lands-how-personal-shared')).indexOf('Found in this install: forge') >= 0);
    });
    keyed(body(none), 'lands-how-personal-draft')._on.onclick({});
    const c = keyed(body(none), 'lands-draft-personal');
    const said = text(keyed(c, 'lands-c-expect'));
    check('drafted: before the tap, the draft says it is a real build, a plan first, an estimate: ' + said,
      /real build/.test(said) && /plan first/.test(said) && /around 40 minutes/.test(said) && /a few thousand lines/.test(said) &&
      /an estimate, not a promise/.test(said) && /carry on with the other steps/.test(said));
    const going = text(keyed(body(asked), 'connection-draft'));
    check('drafted: while it runs the check says the plan waits for you, and that Bosun has been told: ' + going,
      /Waiting for you to approve its plan \(c-12\)/.test(going) && /Bosun has been told/.test(going));
    const waits = text(keyed(body(queued), 'connection-draft'));
    check('drafted: a card Bosun has not heard of yet says so: ' + waits, /Bosun is told as soon as it is free/.test(waits));
    done();
  });
}

/* c-734 point 6: the Setup page's Packs panel. A pack on for no space says what it needs in one
   quiet line, never a "needs you" block; a pack offers Turn on only for the spaces it is not on */
function packsPanel(done) {
  const failing = [{ name: 'GitHub sign-in', ok: false, why: 'not signed in', for: ['codehost'] }];
  const report = Object.assign({}, REPORT, {
    spaces: { personal: REPORT.spaces.personal, work: { pack: 'forge', tier: null, writable: true, proposal: null, repos: [] } },
    packs: [{ name: 'github', description: 'GitHub', spaces: [], rules: [], checks: failing },
            { name: 'forge', description: 'a forge', spaces: ['work'], rules: [], checks: failing }] });
  const K = page(firstrun('2026-10-03T10:00:00+00:00', true, true), 'setup', report);
  body(K);
  setImmediate(function () {
    const b = body(K);
    const gh = keyed(b, 'pack-github'), forge = keyed(b, 'pack-forge');
    check('packs: a pack on for no space has no needs-you block', !!gh && stuckOf(gh).length === 0);
    check('packs: its unmet requirements are one quiet line: ' + text(keyed(gh, 'pack-needs')), text(keyed(gh, 'pack-needs')) === 'needs: GitHub sign-in');
    check('packs: a pack on for a space keeps its stuck line', !!forge && stuckOf(forge).length === 1);
    const forgeLabels = labels(forge);
    check('packs: on for its space, it offers Turn off there and Turn on only where it is not: ' + JSON.stringify(forgeLabels),
      forgeLabels.indexOf('Turn on') < 0 && forgeLabels.indexOf('Turn off for work') >= 0 && forgeLabels.indexOf('Turn on for work') < 0 &&
      forgeLabels.indexOf('Turn on for personal') >= 0);
    check('packs: a pack on for no space offers Turn on for each space with no pack, and a new one: ' + JSON.stringify(labels(gh)),
      labels(gh).indexOf('Turn on for personal') >= 0 && labels(gh).indexOf('Turn on for work') < 0 && labels(gh).indexOf('Turn on for a new space') >= 0);
    done();
  });
}

const BLOCKS = [signin, builders, repos, memory, drafts, untested, lands, reviewAsks, pushes, ships, browsers, backups, firstCards, setUps, connects, providers,
  stays, follows, drafted, packsPanel];
(function run(i) {
  if (i >= BLOCKS.length) { process.stdout.write(JSON.stringify(fails.length ? { fails } : { ok: true })); return; }
  BLOCKS[i](function () { run(i + 1); });
})(0);
