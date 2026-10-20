/* Choosing a connection, and the page that follows from it (c-758), under node against the
 * deck's DOM stand-in: Where finished work goes as four choices, in each state a new user
 * meets it, How work ships opening with what was chosen, and a connection's own step after
 * them. The page and the state are tests/fixtures/start-page.js, as for start-steps.js.
 *
 * Each block draws its pages, waits one turn for the Setup report each page asked for, then
 * checks them and calls `done`.
 *
 * Usage: node start-connection.js <path to app/>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const APP = process.argv[2];
const { deck, check, fails, firstrun, REPORT, page, body, named, keyedAll, keyed, stuckOf, text,
        placeOf, ATTACH } = require('./start-page.js')(APP);

const at = (step, fr, report, opts) => { const K = page(fr || firstrun(null, true), 'start', report, opts); K.App.step = step; return K; };
const withStart = (more) => Object.assign({}, REPORT, { start: Object.assign({}, REPORT.start, more) });
const stepOf = (fr, id) => fr.steps[placeOf(id)];
const codes = (node) => (node ? deck.all(node, (n) => n.tagName === 'CODE').map(text) : []);
const tags = (node, tag) => (node ? deck.all(node, (n) => n.tagName === tag) : []);
const press = (button) => { if (button) button._on.onclick({ stopPropagation() {}, preventDefault() {} }); return !!button; };
const st = (node) => (node ? node.getAttribute('data-state') : null);
const how = (K, id) => keyed(body(K), 'lands-how-work' + (id ? '-' + id : ''));
const open = (K) => ['shipped', 'shared', 'draft', 'local'].filter((id) => how(K, id) && how(K, id).getAttribute('aria-checked') === 'true').join();

const LANDS = { work: { remote: 'origin', fetch: true, push: true, repos: [{ key: 'api', host: 'git.example.org', branch: 'main' }] } };
const FOLDER = '/i/packs';
const need = (name, ok) => ({ name: name, kind: 'command', ok: ok, why: 'why ' + name, for: ['codehost'],
  fix: 'Run forge login in a terminal. Then look again.', command: 'forge login' });
const pack = (name, more) => Object.assign({ name: name, description: name + ' in its own words: you merge there.', spaces: [], rules: [], checks: [],
  capabilities: ['codehost'], folder: null, own_repo: null }, more || {});
const SHIPPED = [pack('gitea', { checks: [need('Gitea sign-in', false)] }), pack('github')];
const TEAM = pack('team', { folder: FOLDER + '/team', own_repo: { key: 'pack-team', built: false }, checks: [need('TeamForge sign-in', false)] });
const builder = (connection) => ({ mode: 'in-app', label: 'Builder', repos: ['packs'], importing: null,
  connection: Object.assign({ open: null, done: null, pack: null, space: null }, connection || {}) });
const space = (on) => ({ pack: on || null, tier: null, writable: true, proposal: null, repos: [{ key: 'api' }] });
/* a report for the work space: `packs`, the connection it is on, the draft, a problem line
   (`error`, in the first run's word; `install`: it is about a folder of the install's own) */
const report = (o) => Object.assign(withStart({ lands: o.on ? {} : LANDS }), { packs: o.packs || SHIPPED,
  packs_error: o.error ? o.error.replace('holds the connection', 'holds the pack') : null, connections_error: o.error || null,
  packs_error_install: o.install === undefined ? !!o.error : o.install,
  packs_folder: FOLDER, builder: builder(o.connection), spaces: { personal: REPORT.spaces.personal, work: space(o.on) } });
const lands = (o) => at('integrations', null, report(o || {}));

/* 1. Four choices, each saying what happens next; picking one writes nothing */
function choices(done) {
  const fresh = lands();
  body(fresh);
  setImmediate(function () {
    const b = body(fresh), group = how(fresh);
    const titles = ['shipped', 'shared', 'draft', 'local'].map((id) => text(deck.byClass(how(fresh, id), 'start-opt-title')[0]));
    check('choices: four, by what you do: ' + JSON.stringify(titles), JSON.stringify(titles) === JSON.stringify([
      'Use a connection Shipyard ships', 'Add a connection someone shared with you', 'Have Bosun draft one for another provider',
      'Keep work on this computer, and push when you say']) && group.getAttribute('role') === 'radiogroup');
    check('choices: each says what happens next', ['shipped', 'shared', 'draft'].every((id) => /Next: /.test(text(how(fresh, id)))) &&
      /Needs nothing set up\./.test(text(how(fresh, 'local'))));
    check('choices: the page says a pick only opens: ' + text(keyed(b, 'lands-pick-work')),
      text(keyed(b, 'lands-pick-work')) === 'Pick one to see what it takes. Nothing changes until you press a button inside it.');
    check('choices: a fresh install opens on this computer, which is in use: ' + open(fresh), open(fresh) === 'local' &&
      text(how(fresh, 'local')).indexOf('in use') >= 0 && text(how(fresh, 'shipped')).indexOf('Shipped: gitea, github') >= 0);
    check('choices: a line states what is true now: ' + text(keyed(b, 'lands-now-work')),
      text(keyed(b, 'lands-now-work')) === 'Work for work now stays on this computer, and you push when you say.');
    check('choices: what done means is said on the step: ' + text(keyed(b, 'lands-done-means')), text(keyed(b, 'lands-done-means')) ===
      'This step is done when a connection is turned on and everything it needs is ready, or when you keep work on this computer.');
    ['shipped', 'shared', 'draft', 'local'].forEach(function (id) {
      how(fresh, id)._on.onclick({});
      check('choices: picking ' + id + ' opens its section and writes nothing: ' + JSON.stringify(fresh._acted),
        open(fresh) === id && !!keyed(body(fresh), 'lands-' + id + '-work') && fresh._acted.length === 0 &&
        text(keyed(body(fresh), 'lands-now-work')).indexOf('stays on this computer') >= 0);
    });
    how(fresh, 'shipped')._on.onclick({});
    const section = keyed(body(fresh), 'lands-shipped-work');
    check('choices: the shipped ones are listed, each with its Turn on and what it needs in one quiet line', !!keyed(section, 'pack-gitea') &&
      !!keyed(section, 'pack-github') && text(keyed(keyed(section, 'pack-gitea'), 'pack-needs')) === 'needs: Gitea sign-in' && !stuckOf(section).length);
    check('choices: and the section has Look again, for a fix that ends in it', !!named(section, 'Look again'));
    press(named(keyed(section, 'pack-github'), 'Turn on for work'));
    check('choices: the one button inside acts: ' + JSON.stringify(fresh._acted),
      JSON.stringify(fresh._acted) === JSON.stringify([{ verb: 'setup.pack.on', pack: 'github', space: 'work' }]));
    done();
  });
}

/* 2. The shared one is on the step: found first and marked, the command, Copy, Look again */
function shared(done) {
  const none = lands(), cloned = lands({ packs: SHIPPED.concat([TEAM]) });
  const MISNAMED = 'The folder /i/packs/team-connection holds the connection team: rename it to /i/packs/team, then Look again.';
  const misnamed = lands({ error: MISNAMED });
  /* r1.F13: a connection that does not load is not a problem of the install's folder */
  const BROKEN = 'github/pack.toml: `version` must be a non-empty string';
  const broken = lands({ packs: [], error: BROKEN, install: false });
  /* r1.F7: found in the install's folder and no clone of its own (the user's own import), with no code host */
  const MINE = pack('mine', { folder: FOLDER + '/mine', capabilities: [] });
  const imported = lands({ packs: SHIPPED.concat([MINE, TEAM]) }), alone = lands({ packs: SHIPPED.concat([MINE]) });
  /* fix check D1: a misnamed folder outside the install's folder: the others still list */
  const OUTSIDE = 'The folder /src/packs/team-connection holds the connection team: rename it to /src/packs/team, then Look again.';
  const outside = lands({ error: OUTSIDE, install: false });
  /* r2.F1: the space is on a connection, and none is listed because one does not load */
  const lost = lands({ on: 'github', packs: [], error: BROKEN, install: false });
  [none, cloned, misnamed, broken, imported, alone, outside, lost].forEach(body);
  setImmediate(function () {
    how(none, 'shared')._on.onclick({});
    let section = keyed(body(none), 'lands-shared-work');
    const line = keyed(section, 'pack-shared');
    check('shared: the command is on the step, with the install\'s real folder: ' + JSON.stringify(codes(line)),
      JSON.stringify(codes(line)) === JSON.stringify(['git clone <its address> /i/packs/<name>']) && !!named(line, 'Copy') && !!named(line, 'Look again'));
    check('shared: it says the command is yours to run', text(section).indexOf('Shipyard never asks for its address or your sign-in') >= 0 &&
      text(line).indexOf('Shipyard does not run it for you.') >= 0);
    const reads = none._fetched.filter((u) => u === '/api/setup').length;
    press(named(line, 'Look again'));
    check('shared: Look again reads the report again and writes nothing', none._fetched.filter((u) => u === '/api/setup').length === reads + 1 && none._acted.length === 0);

    check('shared: a connection cloned and not turned on opens its choice by itself: ' + open(cloned), open(cloned) === 'shared' &&
      text(how(cloned, 'shared')).indexOf('Shared with you: team') >= 0);
    section = keyed(body(cloned), 'lands-shared-work');
    const mark = keyed(section, 'lands-found-team');
    check('shared: it is listed first, marked as found in the install\'s folder: ' + text(mark), text(mark) === 'Found in /i/packs/team' &&
      text(section).indexOf('Found in /i/packs/team') < text(section).indexOf('git clone'));
    check('shared: not on, it says what it needs in one quiet line and has its Turn on', text(keyed(section, 'pack-needs')) === 'needs: TeamForge sign-in' &&
      !stuckOf(section).length && text(keyed(body(cloned), 'lands-now-work')).indexOf('stays on this computer') >= 0);
    check('shared: the command then says it adds another', text(keyed(section, 'pack-shared-said')).indexOf('To add another, run this in a terminal') === 0);
    press(named(keyed(section, 'pack-team'), 'Turn on for work'));
    check('shared: Turn on is the one write: ' + JSON.stringify(cloned._acted),
      JSON.stringify(cloned._acted) === JSON.stringify([{ verb: 'setup.pack.on', pack: 'team', space: 'work' }]));

    /* a misnamed folder: its line ends in Look again, which the section it is drawn in has */
    check('misnamed: the shared choice opens by itself and says a folder needs a look: ' + open(misnamed), open(misnamed) === 'shared' &&
      text(how(misnamed, 'shared')).indexOf('A folder in this install needs a look') >= 0);
    section = keyed(body(misnamed), 'lands-shared-work');
    check('misnamed: the problem line is in the section, in the server\'s words', keyedAll(section, 'packs-problem').map(text).join() === MISNAMED);
    check('misnamed: and the control it points at is there', /then Look again\.$/.test(MISNAMED) && !!named(section, 'Look again'));
    check('misnamed: it is drawn once, in the section of the folder it is about', keyedAll(body(misnamed), 'packs-problem').length === 1 && !keyed(body(misnamed), 'lands-problem-work'));

    /* r1.F13 */
    check('broken: a connection that does not load opens nothing by itself, and the shared choice is not blamed: ' + open(broken), open(broken) === 'local' &&
      text(how(broken, 'shared')).indexOf('needs a look') < 0);
    const block = keyed(body(broken), 'lands-problem-work');
    check('broken: its line is under the choices, with a neutral label and Look again: ' + text(block), !!block &&
      text(block).indexOf('A connection does not load, so none is listed:') === 0 && keyedAll(block, 'packs-problem').map(text).join() === BROKEN && !!named(block, 'Look again'));
    const far = keyed(body(outside), 'lands-problem-work');
    check('outside: a folder problem with connections still listed never says none is listed: ' + text(far), !!far &&
      text(far).indexOf('A folder Shipyard reads connections from needs a look:') === 0 && text(far).indexOf('none is listed') < 0 &&
      keyedAll(far, 'packs-problem').map(text).join() === OUTSIDE && !!named(far, 'Look again'));
    how(outside, 'shipped')._on.onclick({});
    check('outside: and the shipped ones are listed', !!keyed(keyed(body(outside), 'lands-shipped-work'), 'pack-github'));
    how(lost, 'shared')._on.onclick({});
    const stuck = keyed(body(lost), 'lands-shared-work');
    check('lost: with the connection in use not listed, the line names a control the step has: ' + text(keyed(stuck, 'lands-locked')),
      text(keyed(stuck, 'lands-locked')) === 'work is on github now, and github is not listed because a connection does not load. ' +
        'To use another, press Keep work for work on this computer under "Keep work on this computer, and push when you say", ' +
        'or fix the connection and press Look again.' && text(stuck).indexOf('turn github off first') < 0);
    how(lost, 'local')._on.onclick({});
    check('lost: and that button is there', !!named(keyed(body(lost), 'lands-local-work'), 'Keep work for work on this computer'));
    how(broken, 'shared')._on.onclick({});
    check('broken: and it is not drawn a second time in a section', keyedAll(body(broken), 'packs-problem').length === 1);

    /* r1.F7 */
    check('found: one that is no clone of its own does not open the shared choice, and is not called shared: ' + text(how(alone, 'shared')), open(alone) === 'local' &&
      text(how(alone, 'shared')).indexOf('Found in this install: mine') >= 0 && text(how(alone, 'shared')).indexOf('Shared with you') < 0);
    check('found: beside a clone, each is named for what it is: ' + text(how(imported, 'shared')),
      text(how(imported, 'shared')).indexOf('Shared with you: team. Found in this install: mine') >= 0);
    section = keyed(body(imported), 'lands-shared-work');
    const order = ['lands-clones', 'pack-team', 'pack-shared', 'lands-others', 'pack-mine'].map((key) => text(section).indexOf(text(keyed(section, key))));
    check('found: the shared ones first under their heading, then the command, then the rest under a plain heading: ' + JSON.stringify(order),
      text(keyed(section, 'lands-clones')) === 'Shared with you' && text(keyed(section, 'lands-others')) === 'Found in this install' &&
      order.every((at, i) => at >= 0 && (i === 0 || at > order[i - 1])));
    check('found: a row with no code host says so, and still lists with its Turn on: ' + text(keyed(section, 'lands-nohost-mine')),
      text(keyed(section, 'lands-nohost-mine')) === 'mine has no code host: it cannot open work for review.' && !keyed(section, 'lands-nohost-team') &&
      !!named(keyed(section, 'pack-mine'), 'Turn on for work'));
    check('found: the command on this step says connection', text(keyed(section, 'pack-shared-said')).indexOf('the connection\'s name') >= 0 &&
      text(keyed(section, 'pack-shared-said')).indexOf('pack') < 0);
    done();
  });
}

/* 3. A connection that is on, with a failing check: each check once, and a way to look again */
function turnedOn(done) {
  const on = lands({ on: 'team', packs: SHIPPED.concat([Object.assign({}, TEAM, { spaces: ['work'] })]) });
  const undeclared = (what) => ({ ready: false, why: 'the team connection has no ' + what, step: 'integrations', declared: false });
  on.App.data.readiness.spaces.work = Object.assign({}, on.App.data.readiness.spaces.work, {
    tracker: undeclared('tracker'), reviews: undeclared('review scanning'),
    codehost: { ready: false, why: 'TeamForge sign-in is not set up: why TeamForge sign-in', step: 'integrations', declared: true, needs: [need('TeamForge sign-in', false)] } });
  const beside = lands({ on: 'team', packs: SHIPPED.concat([Object.assign({}, TEAM, { spaces: ['work'] }), pack('forge', { folder: FOLDER + '/forge' })]) });
  [on, beside].forEach(body);
  setImmediate(function () {
    const b = body(on), section = keyed(b, 'lands-shared-work');
    check('on: its choice is open and in use, and the line says where work goes: ' + text(keyed(b, 'lands-now-work')), open(on) === 'shared' &&
      text(how(on, 'shared')).indexOf('in use') >= 0 && text(keyed(b, 'lands-now-work')) === 'Work for work now goes through team.');
    check('on: the failing check is drawn once, with its fix: ' + stuckOf(section).map((n) => n.getAttribute('data-key')),
      stuckOf(section).length === 1 && !!keyed(section, 'stuck-check-TeamForge sign-in') && codes(section).indexOf('forge login') >= 0);
    check('on: its fix says look again, and the section has that control', text(section).indexOf('Then look again.') >= 0 && !!named(section, 'Look again'));
    check('on: Turn off is inside it', !!named(section, 'Turn off for work'));
    check('on: another one found there has no Turn on, and its heading says why: ' + text(keyed(keyed(body(beside), 'lands-shared-work'), 'lands-others')),
      text(keyed(keyed(body(beside), 'lands-shared-work'), 'lands-others')) === 'Found in this install (to use one, turn team off first)' &&
      !named(keyed(keyed(body(beside), 'lands-shared-work'), 'pack-forge'), 'Turn on for work'));
    how(on, 'shipped')._on.onclick({});
    const other = keyed(body(on), 'lands-shipped-work');
    check('on: another choice says to turn this one off first, and offers no Turn on: ' + text(keyed(other, 'lands-locked')),
      text(keyed(other, 'lands-locked')) === 'work is on team now. To use another, turn team off first, under "Add a connection someone shared with you".' &&
      !named(other, 'Turn on for work') && on._acted.length === 0);
    how(on, 'local')._on.onclick({});
    check('on: this computer, opened, writes nothing until its button', on._acted.length === 0 && !!named(keyed(body(on), 'lands-local-work'), 'Keep work for work on this computer'));
    done();
  });
}

/* 4. Honest states: a draft in progress, and one that landed and is not turned on */
function drafts(done) {
  const going = lands({ connection: { open: { card: 'c-12', stage: 'building', waiting: false, gate: null, told: true, space: 'work' } } });
  const FORGE = pack('forge', { folder: FOLDER + '/forge' });
  const landed = lands({ packs: SHIPPED.concat([FORGE]), connection: { done: 'c-12', pack: 'forge', space: 'work' } });
  const turned = lands({ on: 'forge', packs: SHIPPED.concat([Object.assign({}, FORGE, { spaces: ['work'] })]), connection: { done: 'c-12', pack: 'forge', space: 'work' } });
  const GITHUB_ON = [SHIPPED[0], pack('github', { spaces: ['work'] })];
  const elsewhere = lands({ on: 'github', packs: GITHUB_ON.concat([FORGE]), connection: { done: 'c-12', pack: 'forge', space: 'work' } });
  const busy = lands({ on: 'github', packs: GITHUB_ON, connection: { open: { card: 'c-12', stage: 'building', waiting: false, gate: null, told: true, space: 'work' } } });
  const another = lands({ packs: SHIPPED.concat([FORGE]), connection: { done: 'c-12', pack: 'forge', space: 'team' } });
  const fresh = lands();
  /* r2.F4: two spaces, and the draft is for the other one */
  const OPEN_TEAM = { open: { card: 'c-12', stage: 'building', waiting: false, gate: null, told: true, space: 'team' } };
  const two = (o) => { const r = report(o); r.spaces = Object.assign({}, r.spaces, { team: space() }); return at('integrations', null, r); };
  const theirs = two({ connection: OPEN_TEAM }), theirsOn = two({ on: 'github', packs: GITHUB_ON, connection: OPEN_TEAM });
  const landedTheirs = two({ on: 'github', packs: GITHUB_ON.concat([FORGE]), connection: { done: 'c-12', pack: 'forge', space: 'team' } });
  [going, landed, turned, elsewhere, busy, another, fresh, theirs, theirsOn, landedTheirs].forEach(body);
  setImmediate(function () {
    /* the owner's word: the form asks what the connection must do, not how the team works */
    how(fresh, 'draft')._on.onclick({});
    const form = keyed(body(fresh), 'lands-draft-work'), ASK = 'Which code host, and what should Shipyard do there?';
    check('draft: the box asks which code host and what Shipyard should do there: ' + (tags(form, 'TEXTAREA')[0] || { getAttribute() {} }).getAttribute('aria-label'),
      tags(form, 'TEXTAREA')[0].getAttribute('aria-label') === ASK && text(form).indexOf(ASK) >= 0 && text(form).indexOf('how does your team review') < 0);
    check('draft: with what it can be asked to do: ' + text(keyed(form, 'lands-c-does')),
      text(keyed(form, 'lands-c-does')) === 'What it can do there: open each card\'s change for review, watch its checks, and bring review comments ' +
        'back to the card. Say which of these you want, what your host calls them, and how you sign in to it.');
    check('draft: its choice says what Bosun does here: ' + text(how(fresh, 'draft')),
      text(how(fresh, 'draft')).indexOf('Bosun writes a connection as a card: code you read, then turn on.') >= 0);
    let b = body(going);
    check('draft: in progress, its choice is open and says it is not finished: ' + text(how(going, 'draft')), open(going) === 'draft' &&
      text(how(going, 'draft')).indexOf('In progress (c-12), not finished') >= 0 && text(how(going, 'local')).indexOf('in use') >= 0);
    const row = keyed(b, 'connection-draft');
    check('draft: the check says not finished, where it is, and that work stays here meanwhile: ' + text(row), st(row) === 'checking' &&
      text(row).indexOf('Not finished yet. Bosun is building it (c-12). Bosun has been told. Until it has landed and you turn it on, work stays on this computer.') >= 0);
    /* r1.F2: keeping work on this computer does not finish the step while a draft stands; Skip does */
    const MEANS = 'A connection draft stands, so this step is not done yet: it is done when that connection is turned on and everything it needs is ready. ' +
      'To keep work on this computer meanwhile, press Skip below.';
    check('draft: what done means says a draft stands, and that Skip keeps work here: ' + text(keyed(b, 'lands-done-means')),
      text(keyed(b, 'lands-done-means')) === MEANS && text(keyed(body(landed), 'lands-done-means')) === MEANS &&
      text(keyed(body(turned), 'lands-done-means')).indexOf('or when you keep work on this computer.') >= 0 &&
      text(keyed(body(elsewhere), 'lands-done-means')).indexOf('or when you keep work on this computer.') >= 0);
    check('draft: and the line under the choices still says this computer', text(keyed(b, 'lands-now-work')).indexOf('stays on this computer') >= 0);

    b = body(landed);
    const stuck = keyed(b, 'stuck-connection-draft') || keyed(b, 'connection-draft');
    check('landed: not turned on, it does not read as done: ' + text(stuck), open(landed) === 'draft' && st(keyed(b, 'connection-draft')) !== 'ready' &&
      text(stuck).indexOf('c-12 landed: the connection forge is here, and it is not turned on yet. Work for work still stays on this computer.') >= 0);
    check('landed: its Turn on is right there, where the check points', text(stuck).indexOf('Press Turn on for work just below.') >= 0 &&
      !!named(keyed(keyed(b, 'lands-draft-work'), 'pack-forge'), 'Turn on for work'));
    /* r1.F4: once a draft has landed the form is back, worded as drafting another */
    const again = keyed(b, 'lands-draft-work');
    check('landed: the form is offered again, as drafting another', text(keyed(again, 'lands-c-again')) === 'Draft another connection' &&
      tags(again, 'TEXTAREA').length === 1 && !!named(again, 'Have Bosun draft another connection') && !named(again, 'Have Bosun draft a connection'));
    press(named(again, 'Have Bosun draft another connection'));
    check('landed: and its tap files a draft for the space: ' + JSON.stringify(landed._acted), landed._acted.length === 1 &&
      landed._acted[0].verb === 'setup.pack.draft' && landed._acted[0].space === 'work');
    check('in progress: no form while a draft is open', !tags(keyed(body(going), 'lands-draft-work'), 'TEXTAREA').length);
    check('landed: the line under the choices still says this computer', text(keyed(b, 'lands-now-work')).indexOf('stays on this computer') >= 0);

    b = body(turned);
    check('landed and on: now it reads as done: ' + text(keyed(b, 'connection-draft')), st(keyed(b, 'connection-draft')) === 'ready' &&
      text(keyed(b, 'connection-draft')).indexOf('c-12 landed, and forge is on for work.') >= 0 &&
      text(keyed(b, 'lands-now-work')) === 'Work for work now goes through forge.');

    /* r1.F1: the draft landed for a space that is on another connection, and one still being
       drafted for it: neither says work stays on this computer, nor points at a Turn on */
    how(elsewhere, 'draft')._on.onclick({});
    b = body(elsewhere);
    const section = keyed(b, 'lands-draft-work'), said = text(keyed(b, 'connection-draft'));
    check('landed, on another: the check says which connection work is on, not this computer: ' + said, st(keyed(b, 'connection-draft')) === 'waiting' &&
      said.indexOf('c-12 landed: the connection forge is here, and it is not turned on. Work for work goes through github.') >= 0 &&
      text(section).indexOf('stays on this computer.') < 0 && text(section).indexOf('Press Turn on') < 0);
    check('landed, on another: the section says where the Turn off is, and offers no Turn on: ' + text(keyed(section, 'lands-locked')),
      text(keyed(section, 'lands-locked')) === 'work is on github now. To use another, turn github off first, under "Use a connection Shipyard ships".' &&
      !named(section, 'Turn on for work') && !!keyed(section, 'pack-forge'));
    /* r1.F3: landed for another space: listed in the install's folder, so the check says where, and waits */
    how(another, 'draft')._on.onclick({});
    const other = keyed(body(another), 'connection-draft');
    check('landed for another space: not ready, it says whose, and names the choice its row is really under: ' + text(other), st(other) === 'waiting' &&
      text(other).indexOf('c-12 landed for team. The connection forge is listed under "Add a connection someone shared with you", with its Turn on for work.') >= 0 &&
      text(other).indexOf('does nothing until') < 0);
    /* r2.F4: the other space's draft, seen from this one */
    how(theirs, 'draft')._on.onclick({});
    const sectionOf = (K, name) => keyed(body(K), 'lands-draft-' + name);
    check('two spaces, a draft open for the other: this space\'s check says whose it is and where this space\'s work goes: ' + text(keyed(sectionOf(theirs, 'work'), 'connection-draft')),
      text(keyed(sectionOf(theirs, 'work'), 'connection-draft')).indexOf('Not finished yet, and it is for team. Bosun is building it (c-12). Bosun has been told. ' +
        'Until it has landed and is turned on, work for work stays on this computer.') >= 0);
    check('two spaces: the space it is for reads as before: ' + text(keyed(sectionOf(theirs, 'team'), 'connection-draft')),
      text(keyed(sectionOf(theirs, 'team'), 'connection-draft')).indexOf('Not finished yet. Bosun is building it (c-12). Bosun has been told. ' +
        'Until it has landed and you turn it on, work stays on this computer.') >= 0);
    check('two spaces: a space on no connection is told the step stays open, and Skip',
      text(keyed(sectionOf(theirs, 'work'), 'lands-c-expect')).indexOf('press Skip below, and this step stays open until the connection is on') >= 0);
    how(theirsOn, 'draft')._on.onclick({});
    check('two spaces: a space on a connection is not told the step stays open: ' + text(keyed(sectionOf(theirsOn, 'work'), 'lands-c-expect')),
      text(keyed(sectionOf(theirsOn, 'work'), 'lands-c-expect')).indexOf('You can carry on with the other steps meanwhile.') >= 0 &&
      text(keyed(sectionOf(theirsOn, 'work'), 'lands-c-expect')).indexOf('Skip') < 0 &&
      text(keyed(sectionOf(theirsOn, 'work'), 'lands-c-expect')).indexOf('stays open') < 0 &&
      text(keyed(sectionOf(theirsOn, 'work'), 'connection-draft')).indexOf('Not finished yet, and it is for team.') >= 0 &&
      text(keyed(sectionOf(theirsOn, 'work'), 'connection-draft')).indexOf('Until it has landed and is turned on, work for work goes through github.') >= 0);
    how(landedTheirs, 'draft')._on.onclick({});
    check('two spaces, landed for the other, this one on a connection: no Turn on is promised: ' + text(keyed(sectionOf(landedTheirs, 'work'), 'connection-draft')),
      text(keyed(sectionOf(landedTheirs, 'work'), 'connection-draft')).indexOf('c-12 landed for team. The connection forge is listed under "Add a connection someone shared with you".') >= 0 &&
      text(keyed(sectionOf(landedTheirs, 'work'), 'connection-draft')).indexOf('with its Turn on') < 0);
    how(another, 'shared')._on.onclick({});
    check('landed for another space: and the row is there, with its Turn on', !!named(keyed(keyed(body(another), 'lands-shared-work'), 'pack-forge'), 'Turn on for work'));
    how(busy, 'draft')._on.onclick({});
    const during = text(keyed(body(busy), 'connection-draft'));
    /* residue A: the whole section, its opening paragraph included, never says this computer */
    const whole = keyed(body(busy), 'lands-draft-work');
    check('in progress, on another: no sentence of the section says work stays on this computer: ' + text(keyed(whole, 'lands-c-said')),
      text(whole).indexOf('this computer') < 0 &&
      text(keyed(whole, 'lands-c-said')).indexOf('Until then, work for work keeps going through github.') >= 0);
    check('in progress, on another: it says work stays on that connection meanwhile: ' + during,
      during.indexOf('Until it has landed and you turn it on, work for work goes through github.') >= 0 && during.indexOf('this computer') < 0);
    done();
  });
}

/* 5. How work ships opens with what was chosen; a connection with no code host says why
      nothing is drawn; the drawing's words are the connection's */
function ships(done) {
  const branches = [{ id: 'card', label: 'card branch', kind: 'card' }, { id: 'base', label: '{base}', kind: 'base' }];
  const local = { name: 'Local merge', description: 'Your approval merges the card.', source: 'keel', proposal: null, landing: {}, held: null,
    handling: { shipping: false }, branches: branches,
    moves: [{ id: 'land', label: 'Approve outcome', from: 'card', to: 'base', by: 'keel', step: 'land', stages: ['review'] }] };
  const HELD = 'A repo card cannot be approved in this space until a code host is set up (the team connection has no code host).';
  const held = Object.assign({}, local, { description: 'Shipyard draws no flow for this space yet.', moves: [], held: HELD, held_codehost: true });
  /* r1.F8: held for another reason: an older adapter that has a code host and no ship verb */
  const NO_SHIP = 'A card can be approved and published in this space, but Shipyard cannot watch it at shipping: the old adapter has no ship verb. So Shipyard draws no flow for it.';
  const unwatched = Object.assign({}, held, { held: NO_SHIP, held_codehost: false });
  const make = (flow, o, seen) => {
    const fr = firstrun(null, true);
    if (seen) stepOf(fr, 'integrations').seen = '2026-10-12T10:00:00+00:00';
    Object.assign(stepOf(fr, 'defaults'), { plans: { work: false }, asks: [{ id: 'starts', ask: 'Where does work start?', where: 'page', example: 'main' },
      { id: 'lands', ask: 'Which branch does finished work go back into?', where: 'bosun', example: 'back where it started' }],
      bases: { work: { bases: [], suggested: 'main', pack: false } } });
    const K = at('defaults', fr, report(o), { state: { console: { attach: ATTACH, up: true } } });
    K.App.data.spaces.work = Object.assign({}, K.App.data.spaces.personal, { flow: flow });
    return K;
  };
  const kept = make(local, {}, true), untouched = make(local, {});
  const older = make(unwatched, { on: 'team', packs: SHIPPED.concat([Object.assign({}, TEAM, { spaces: ['work'] })]) });
  const chosen = make(local, { on: 'github', packs: [pack('gitea'), pack('github', { spaces: ['work'] })] });
  const empty = make(held, { on: 'team', packs: SHIPPED.concat([Object.assign({}, TEAM, { spaces: ['work'], capabilities: [] })]) });
  const drafting = make(local, { connection: { open: { card: 'c-12', stage: 'building', waiting: false, space: 'work' } } });
  /* fix check D7: a space that ships by its own flow, with a new draft of Bosun's open and not at review */
  const ownDraft = make(Object.assign({}, local, { source: 'space', proposal: { card: 'c-9', stage: 'building' } }),
    { on: 'github', packs: [pack('gitea'), pack('github', { spaces: ['work'] })] });
  const ownLocal = make(Object.assign({}, local, { source: 'space', proposal: null }), {}, true);
  [kept, untouched, chosen, empty, drafting, older, ownDraft, ownLocal].forEach(body);
  setImmediate(function () {
    let b = body(kept);
    const first = (node) => deck.all(keyed(node, 'ships'), (n) => n.nodeType === 1 && /^ships-(chose|bases|tell)/.test(n.getAttribute('data-key') || ''))[0];
    check('ships: it opens with what was chosen, before any question: ' + text(keyed(b, 'ships-chose-said')), first(b).getAttribute('data-key') === 'ships-chose-work' &&
      text(keyed(b, 'ships-chose-said')) === 'You chose to keep work for work on this computer, so this page starts from that');
    press(named(keyed(b, 'ships-chose-work'), 'Change it on Where finished work goes'));
    check('ships: and the way back to change it goes to that step', kept.App.step === 'integrations');
    /* r1.F8: nothing was chosen (the step was skipped or never opened), so the page does not say you chose */
    b = body(untouched);
    check('ships: with the choice step not seen it says where work stays, not that you chose: ' + text(keyed(b, 'ships-chose-said')),
      text(keyed(b, 'ships-chose-said')) === 'Work for work stays on this computer, so this page starts from that' &&
      !!named(keyed(b, 'ships-chose-work'), 'Choose on Where finished work goes'));

    b = body(chosen);
    check('ships: a connection is named: ' + text(keyed(b, 'ships-chose-said')), text(keyed(b, 'ships-chose-said')) === 'You chose github for work, so this page starts from it');
    check('ships: with what it does in its own words, read from its row: ' + text(keyed(b, 'ships-chose-words')),
      text(keyed(b, 'ships-chose-words')) === 'github in its own words: you merge there.');
    check('ships: question 2 no longer repeats the step before\'s headline', text(keyed(b, 'ships-tell')).indexOf('Where does finished work go?') < 0 &&
      text(keyed(b, 'ships-tell')).indexOf('Which branch does finished work go back into?') >= 0);

    /* the owner's word: what is already set comes right after question 1, as the normal way on;
       the Bosun questions are below it, and say they are optional */
    const order = (node) => deck.all(keyed(node, 'ships'), (n) => n.nodeType === 1 &&
      /^ships-(chose-work|bases-work|now-work|tell|plans-work)$/.test(n.getAttribute('data-key') || '')).map((n) => n.getAttribute('data-key')).join();
    check('ships: the drawing follows question 1, and the Bosun questions come after it: ' + order(b),
      order(b) === 'ships-chose-work,ships-bases-work,ships-now-work,ships-tell,ships-plans-work');
    let now = keyed(b, 'ships-now-work');
    check('ships: with a connection on, the drawing is headed as already set: ' + text(tags(now, 'H3')[0]),
      text(tags(now, 'H3')[0]) === 'This is how github ships work for work, and it is already set');
    check('ships: and it says keeping it is all most people do, with the button there: ' + text(keyed(now, 'ships-set-said')),
      text(keyed(now, 'ships-set-said')) === 'Keeping it is all most people do: press Keep how it works now and go on.' &&
      !!named(now, 'Keep how it works now'));
    const tell = keyed(b, 'ships-tell');
    check('ships: the Bosun questions are headed as optional: ' + text(tags(tell, 'H3')[0]),
      text(tags(tell, 'H3')[0]) === 'Only if your team works differently');
    check('ships: and one sentence says what that is: ' + text(keyed(tell, 'ships-optional')),
      text(keyed(tell, 'ships-optional')) === 'This part is optional. If the drawing above is not how your team ships, tell Bosun how it does: ' +
        'a short conversation, in which Bosun asks the questions below and turns your answers into a new drawing. ' +
        'Nothing changes until you press Adopt, and no code is written.' &&
      !!named(tell, 'Start this with Bosun') && codes(tell).indexOf(ATTACH) >= 0);
    check('ships: the opening says what is yours to answer and that the rest is optional: ' + text(keyed(b, 'ships-chose-work')),
      text(keyed(b, 'ships-chose-work')).indexOf('The drawing below shows that path, and it is already set. You answer question 1 here; changing the rest is optional.') >= 0 &&
      text(keyed(b, 'ships-chose-work')).indexOf('The questions are about the rest') < 0);
    now = keyed(body(untouched), 'ships-now-work');
    check('ships: with work kept on this computer, the drawing is headed as that: ' + text(tags(now, 'H3')[0]),
      text(tags(now, 'H3')[0]) === 'Work for work is merged on this computer and pushed when you say, and that is already set' &&
      order(body(untouched)) === 'ships-chose-work,ships-bases-work,ships-now-work,ships-tell,ships-plans-work');

    /* the general flow draws four arrows between two places: on a phone the list starts open */
    const hosted = Object.assign({}, local, { moves: ['pr', 'publish', 'ship'].map((step) => ({ id: step, label: step, from: 'card', to: 'base',
      by: step === 'pr' ? 'house' : 'keel', step: step, stages: [] })).concat([{ id: 'merge', label: 'Review and merge', from: 'card', to: 'base', by: 'colleague', stages: [] }]) });
    const wide = deck.wrap(chosen.flowPicture(hosted, { key: 'w', space: 'work', bases: ['main'] }), chosen);
    check('drawing: on the desk the list stays folded', !keyed(wide, 'w-list').open);
    chosen.isDesk = () => false;
    const narrow = deck.wrap(chosen.flowPicture(hosted, { key: 'n', space: 'work', bases: ['main'] }), chosen);
    check('drawing: on a phone, four arrows between two places open the list', keyed(narrow, 'n-list').open === true &&
      keyed(deck.wrap(chosen.flowPicture(local, { key: 'l', space: 'work', bases: ['main'] }), chosen), 'l-list').open !== true);
    check('drawing: Ship is your button, and the merge may be yours: ' + chosen.flowLinesOf(hosted, { bases: ['main'] }).filter((l) => /^edge/.test(l)).join(' | '),
      chosen.flowLinesOf(hosted, { bases: ['main'] }).filter((l) => /^edge/.test(l)).join(' | ').indexOf('"ship, you"') >= 0 &&
      chosen.flowLinesOf(hosted, { bases: ['main'] }).join(' | ').indexOf('"Review and merge, you or a teammate"') >= 0);
    chosen.isDesk = () => true;

    now = keyed(body(ownDraft), 'ships-now-work');
    check('own flow, a draft open: the drawing is headed as the flow it draws, not as the connection\'s: ' + text(tags(now, 'H3')[0]),
      text(tags(now, 'H3')[0]) === 'This is how work ships work now: your own flow' && text(now).indexOf('already set') < 0 &&
      !keyed(now, 'ships-set-said') && !!named(now, 'Keep how it works now'));
    /* the green panel too is worded from what is drawn */
    check('own flow, a connection on: the opening says the drawing is the space\'s own flow: ' + text(keyed(body(ownDraft), 'ships-chose-work')),
      text(keyed(body(ownDraft), 'ships-chose-work')).indexOf('The drawing below is work\'s own flow, adopted in place of github\'s usual path. ' +
        'You answer question 1 here; changing the rest is optional.') >= 0 &&
      text(keyed(body(ownDraft), 'ships-chose-work')).indexOf('shows that path') < 0 && text(keyed(body(ownDraft), 'ships-chose-work')).indexOf('already set') < 0);
    check('own flow, work kept here: the opening says the same of the usual path: ' + text(keyed(body(ownLocal), 'ships-chose-work')),
      text(keyed(body(ownLocal), 'ships-chose-work')).indexOf('The drawing below is work\'s own flow, adopted in place of the usual path. ') >= 0 &&
      text(keyed(body(ownLocal), 'ships-chose-work')).indexOf('shows that path') < 0);

    b = body(empty);
    /* fix check D8: nothing is drawn, so the optional part names no drawing above */
    check('held: the optional part does not speak of a drawing above: ' + text(keyed(keyed(b, 'ships-tell'), 'ships-optional')),
      text(keyed(keyed(b, 'ships-tell'), 'ships-optional')) === 'This part is optional. Nothing is drawn for work yet. To have your team\'s way drawn, tell Bosun how it ships: ' +
        'a short conversation, in which Bosun asks the questions below and turns your answers into a drawing. ' +
        'Nothing changes until you press Adopt, and no code is written.');
    check('held: the opening does not promise a drawing', text(keyed(b, 'ships-chose-work')).indexOf('Nothing is drawn for it below yet') >= 0 &&
      text(keyed(b, 'ships-chose-work')).indexOf('The drawing below shows') < 0);
    check('held: a connection with no code host says why nothing is drawn, in the server\'s sentence: ' + text(keyed(b, 'ships-held')),
      text(keyed(b, 'ships-held')) === HELD && !keyed(b, 'ships-now-graph'));
    check('held: the advice to choose a connection with a code host is for that reason', !!keyed(b, 'ships-held-advice'));
    press(named(keyed(b, 'ships-now-work'), 'Back to Where finished work goes'));
    check('held: with the way back to choose another', empty.App.step === 'integrations');
    b = body(older);
    check('held for another reason: the server\'s own sentence, and no advice that does not fit: ' + text(keyed(b, 'ships-held')),
      text(keyed(b, 'ships-held')) === NO_SHIP && !keyed(b, 'ships-held-advice') && text(keyed(b, 'ships-now-work')).indexOf('has a code host') < 0);

    b = body(drafting);
    check('ships: a draft in progress is said, and the page still shows this computer: ' + text(keyed(b, 'ships-chose-draft')),
      text(keyed(b, 'ships-chose-draft')) === 'Bosun is drafting a connection for work (c-12). It is not finished, so this page still shows work kept on this computer.');
    done();
  });
}

/* 6. A connection's own step does not draw the checks a second time */
function ownStep(done) {
  const checks = [need('gh', true), need('GitHub sign-in', false)];
  const make = (list, after) => {
    const fr = firstrun(null, true);
    fr.steps.splice(placeOf(after || 'integrations') + 1, 0, { id: 'github:connect', title: 'Connect GitHub', about: 'From the github connection, for work.',
      required: false, optional: false, skip: true, bosun: true, done: false, skipped: null, why: 'why', after: after || 'integrations' });
    const r = report({ on: 'github', packs: [pack('github', { spaces: ['work'], checks: list })] });
    r.start = Object.assign({}, r.start, { pack_steps: { 'github:connect': { pack: 'github', text: 'Two checks, each with its fix:\n\n1. **gh is installed.** Install it,\n   then look.\n2. **You are signed in.**', requires: ['gh', 'GitHub sign-in'] } } });
    return at('github:connect', fr, r);
  };
  const failing = make(checks), passing = make([need('gh', true), need('GitHub sign-in', true)]);
  /* r1.F5: a step that follows another core step has not had its checks shown on the screen before it */
  const early = make(checks, 'repos');
  [failing, passing, early].forEach(body);
  setImmediate(function () {
    let b = body(failing);
    check('own step: the checks are said in one line, not drawn again: ' + text(keyed(b, 'named-summary')), !stuckOf(b).length && !keyed(b, 'named-gh') &&
      text(keyed(b, 'named-summary')) === '1 of 2 checks still needs you: GitHub sign-in. Each one is on Where finished work goes, with its fix.');
    const lines = tags(deck.byClass(b, 'start-text')[0], 'P').map(text);
    check('own step: a numbered line of its text is a line of its own: ' + JSON.stringify(lines), JSON.stringify(lines) ===
      JSON.stringify(['Two checks, each with its fix:', '1. gh is installed. Install it, then look.', '2. You are signed in.']));
    press(named(b, 'See the checks'));
    check('own step: See the checks goes back to them', failing.App.step === 'integrations');
    b = body(passing);
    check('own step: all passing is one line too: ' + text(keyed(b, 'named-summary')),
      text(keyed(b, 'named-summary')) === 'All 2 of its checks pass. They are on Where finished work goes.' && !!named(b, 'Look again'));
    b = body(early);
    const stuck = keyed(b, 'stuck-named-GitHub sign-in');
    check('own step, after another step: its checks are drawn with their fixes, and nothing points back: ' + stuckOf(b).map((n) => n.getAttribute('data-key')),
      !keyed(b, 'named-summary') && !named(b, 'See the checks') && !!keyed(b, 'named-gh') && !!stuck && codes(stuck).indexOf('forge login') >= 0 &&
      text(keyed(b, 'screen-github:connect')).indexOf('Where finished work goes') < 0 && !!named(b, 'Look again'));
    done();
  });
}

const BLOCKS = [choices, shared, turnedOn, drafts, ships, ownStep];
(function run(i) {
  if (i >= BLOCKS.length) { process.stdout.write(JSON.stringify(fails.length ? { fails } : { ok: true })); return; }
  BLOCKS[i](function () { run(i + 1); });
})(0);
