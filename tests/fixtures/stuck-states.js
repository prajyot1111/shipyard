/* The stuck states outside setup (c-678, app/ui.stuckcard.js), under node against the deck's
 * DOM stand-in: a blocked card read into what happened and its fix, the
 * services, an unknown config key, and the sign-in that ran out. Each is the stuck line of
 * the setup pages, so the checks read its three parts.
 *
 * Every page is drawn before the result is printed, and each tap's follow-up is waited for
 * in turn, so no check is left scheduled after it.
 *
 * Usage: node stuck-states.js <path to app/>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const APP = process.argv[2];
const { deck, check, fails, firstrun, page, body, named, keyedAll, keyed, text, ATTACH } = require('./start-page.js')(APP);

const press = (button) => { if (button) button._on.onclick({ stopPropagation() {}, preventDefault() {} }); return !!button; };
const labels = (node) => (node ? deck.labels(node) : []);
const codes = (node) => (node ? deck.all(node, (n) => n.tagName === 'CODE').map(text) : []);
const sent = (K, verb) => K._acted.filter((a) => a.verb === verb);
const done = firstrun('2026-10-03T10:00:00+00:00', true, true);
const up = { state: { console: { attach: ATTACH, up: true } }, ready: true };
const evidence = (K, card) => deck.wrap(K.gateEvidence(card), K);

function cards(next) {
  const TESTS = 'outcome not merged: tests failed on the merged tree (`npm test` exited 1); nothing was merged; failed: a, b';
  const make = (stuck, more) => {
    const card = deck.card('c-9', Object.assign({ space: 'personal', repo: 'api', stage: 'review', blocked_reason: (stuck && stuck.said) || 'blocked',
      stuck: stuck, derived: { outcome_gate: true, needs_you: true } }, more || {}));
    const K = page(done, 'cards', null, Object.assign({ cards: [card] }, up));
    K.act = (sentBody) => { K._acted.push(sentBody); return Promise.resolve({ ok: true, note: 'done' }); };
    return [K, card];
  };
  const model = make({ kind: 'no-model', what: 'No session started for c-9: this card names no model, and Shipyard never guesses one.',
    said: 'no model on c-9', fix: { label: 'Use opus (this space\'s default) and start', body: { verb: 'stuck.model', id: 'c-9' }, then: 'house.retry' } },
    { stage: 'assigned', derived: { needs_you: true } });
  const start = make({ kind: 'start-failed', what: 'No session started for c-9: claude --bg printed no session id.', said: 'house failed to start: x',
    fix: { label: 'Try again', body: { verb: 'house.retry', id: 'c-9' } } }, { stage: 'assigned', derived: { needs_you: true } });
  const tests = make({ kind: 'land-tests', what: 'The merged result failed `npm test`: 2 failed. Nothing landed.', said: TESTS,
    fix: { label: 'Send back with the failures', body: { verb: 'sendback', id: 'c-9', reason: TESTS } } });
  const dirty = make({ kind: 'land-dirty', said: 'outcome not merged: /i/spaces/work/api/repo has uncommitted changes on main',
    what: 'The folder Shipyard lands into has changes that were never committed: README.md, package.json. Shipyard will not merge over them.',
    fix: { label: 'Set them aside and land', body: { verb: 'land.aside', id: 'c-9' }, then: 'land',
      expect: 'outcome not merged: /i/spaces/work/api/repo has uncommitted changes on main' } });
  const own = make({ kind: 'land-dirty', what: 'The folder Shipyard lands into has changes that were never committed: README.md. Shipyard will not merge over them.',
    said: 'This is your own folder, so Shipyard does not move what is in it. Set the changes aside, approve again, then bring them back:',
    commands: ['git -C /code/api stash push', 'git -C /code/api stash pop'] });
  const ident = make({ kind: 'land-identity', said: 'outcome not merged: empty ident',
    what: 'The merge did not go through: git does not know your name and email, which every merge records.',
    fix: { label: 'Set your name and email', step: 'prerequisites' } });
  const other = make({ kind: 'land-other', said: 'outcome not merged: fatal: bad revision', what: 'The merge did not go through: fatal: bad revision.' });
  const plain = make(null, { stuck: null, blocked_reason: 'Which heading did you mean?', derived: { needs_you: true } });

  let line = keyed(evidence(model[0], model[1]), 'stuck-card-c-9');
  check('card: no model is a stuck line, what happened in the design\'s words', !!line &&
    text(keyed(line, 'stuck-what')).indexOf('No session started for c-9: this card names no model, and Shipyard never guesses one.') >= 0);
  check('card: its fix names the space\'s default: ' + JSON.stringify(labels(keyed(line, 'stuck-fix'))),
    JSON.stringify(labels(keyed(line, 'stuck-fix'))) === JSON.stringify(['Use opus (this space\'s default) and start']));
  check('card: with Bosun\'s session as the third part', keyedAll(line, 'stuck-bosun').length === 1 && text(line).indexOf(ATTACH) >= 0);
  check('card: the block\'s own words are still under it', text(evidence(model[0], model[1])).indexOf('no model on c-9') >= 0);
  press(named(line, 'Use opus (this space\'s default) and start'));
  setImmediate(function () {
    check('card: the tap sets the model, then starts it afresh: ' + JSON.stringify(model[0]._acted.map((a) => a.verb)),
      JSON.stringify(model[0]._acted.map((a) => a.verb)) === JSON.stringify(['stuck.model', 'house.retry']) && model[0]._acted[1].id === 'c-9');
    line = keyed(evidence(start[0], start[1]), 'stuck-card-c-9');
    check('card: a start that failed says why, with Try again', text(keyed(line, 'stuck-what')).indexOf('claude --bg printed no session id.') >= 0 &&
      JSON.stringify(labels(keyed(line, 'stuck-fix'))) === JSON.stringify(['Try again']));
    press(named(line, 'Try again'));
    check('card: Try again is the card\'s own fresh start', sent(start[0], 'house.retry').length === 1);

    line = keyed(evidence(tests[0], tests[1]), 'stuck-card-c-9');
    check('card: red tests on the merged result, in the design\'s words', text(keyed(line, 'stuck-what')).indexOf('The merged result failed npm test: 2 failed. Nothing landed.') >= 0);
    press(named(line, 'Send back with the failures'));
    check('card: Send back with the failures sends the refusal as the reason', sent(tests[0], 'sendback').length === 1 &&
      sent(tests[0], 'sendback')[0].reason === TESTS);

    line = keyed(evidence(dirty[0], dirty[1]), 'stuck-card-c-9');
    check('card: changes never committed in Keel\'s copy name the files', text(keyed(line, 'stuck-what')).indexOf('README.md, package.json. Shipyard will not merge over them.') >= 0);
    press(named(line, 'Set them aside and land'));
    setImmediate(function () {
      check('card: Set them aside and land stashes, lifts that block, then approves again: ' + JSON.stringify(dirty[0]._acted),
        JSON.stringify(dirty[0]._acted) === JSON.stringify([{ verb: 'land.aside', id: 'c-9' },
          { verb: 'unblock', id: 'c-9', expect: 'outcome not merged: /i/spaces/work/api/repo has uncommitted changes on main' },
          { verb: 'approve', id: 'c-9', gate: 'outcome' }]));
      line = keyed(evidence(own[0], own[1]), 'stuck-card-c-9');
      check('card: a folder of the user\'s own gets the two commands to copy, and no button: ' + JSON.stringify(codes(keyed(line, 'stuck-fix'))),
        JSON.stringify(codes(keyed(line, 'stuck-fix'))) === JSON.stringify(['git -C /code/api stash push', 'git -C /code/api stash pop']) &&
        labels(keyed(line, 'stuck-fix')).every((l) => l === 'Copy') && text(keyed(line, 'stuck-fix')).indexOf('This is your own folder') >= 0);
      line = keyed(evidence(ident[0], ident[1]), 'stuck-card-c-9');
      press(named(line, 'Set your name and email'));
      check('card: git\'s name and email opens Check this computer', ident[0].App.step === 'prerequisites' && ident[0].App.view === 'start');
      line = keyed(evidence(other[0], other[1]), 'stuck-card-c-9');
      check('card: anything else git said has no fix part', !!line && !keyedAll(line, 'stuck-fix').length &&
        text(keyed(line, 'stuck-what')).indexOf('The merge did not go through: fatal: bad revision.') >= 0);
      check('card: a block Keel does not read draws no stuck line', !keyed(evidence(plain[0], plain[1]), 'stuck-card-c-9') &&
        text(evidence(plain[0], plain[1])).indexOf('Which heading did you mean?') >= 0);
      /* review r2.F16: a fix the server refused (the act resolves nothing) is not followed */
      const failing = make({ kind: 'land-lock', said: 'outcome not merged: index.lock',
        what: 'The merge did not go through: a git lock file was left behind in the folder Shipyard lands into.',
        fix: { label: 'Remove the stale lock and land', body: { verb: 'land.unlock', id: 'c-9' }, then: 'land',
          expect: 'outcome not merged: index.lock' } });
      failing[0].act = (sentBody) => { failing[0]._acted.push(sentBody); return Promise.resolve(null); };
      const working = make(failing[1].stuck);
      const halted = make(failing[1].stuck);
      halted[0].act = (sentBody) => { halted[0]._acted.push(sentBody); return Promise.resolve(sentBody.verb === 'unblock' ? null : { ok: true }); };
      press(named(keyed(evidence(halted[0], halted[1]), 'stuck-card-c-9'), 'Remove the stale lock and land'));
      /* The server does not refuse an unblock whose `expect` no longer matches: it answers
         with the card as it is, still blocked, on something else. That is not a lifted block. */
      const OTHER = { id: 'c-9', stage: 'review', blocked_reason: 'Which heading did you mean?' };
      const SAID = 'c-9 is blocked on something else now, so it was not approved. Read the block on the card.';
      const elsewhere = (stuck) => {
        const found = make(stuck);
        found[0]._said = [];
        found[0].toast = (words) => { found[0]._said.push(words); };
        found[0].act = (sentBody) => { found[0]._acted.push(sentBody); return Promise.resolve(sentBody.verb === 'unblock' ? OTHER : { ok: true }); };
        return found;
      };
      const still = elsewhere(failing[1].stuck);
      press(named(keyed(evidence(still[0], still[1]), 'stuck-card-c-9'), 'Remove the stale lock and land'));
      press(named(keyed(evidence(failing[0], failing[1]), 'stuck-card-c-9'), 'Remove the stale lock and land'));
      press(named(keyed(evidence(working[0], working[1]), 'stuck-card-c-9'), 'Remove the stale lock and land'));
      /* fix check r2.D4: a landing refused for the repo's file, in its two forms */
      const FILE = 'outcome not merged: api\'s CLAUDE.md changed since it was adopted or saved, and Shipyard takes this repo\'s test command from that file, so nothing was landed.';
      const WHAT = 'Nothing landed: api\'s CLAUDE.md changed since it was adopted or saved, and Shipyard takes this repo\'s test command from that file.';
      const standing = make({ kind: 'land-file', said: FILE, what: WHAT, fix: { label: 'Open the file to save it', step: 'rules' } });
      const saved = make({ kind: 'land-file', said: FILE, what: WHAT,
        fix: { label: 'Unblock and land', body: { verb: 'unblock', id: 'c-9', expect: FILE }, then: 'approve' } });
      line = keyed(evidence(standing[0], standing[1]), 'stuck-card-c-9');
      check('card: a landing refused for the repo\'s file says so: ' + text(keyed(line, 'stuck-what')), text(keyed(line, 'stuck-what')).indexOf(WHAT) >= 0);
      check('card: while the file stands changed the one fix opens it: ' + JSON.stringify(labels(keyed(line, 'stuck-fix'))),
        JSON.stringify(labels(keyed(line, 'stuck-fix'))) === JSON.stringify(['Open the file to save it']));
      press(named(line, 'Open the file to save it'));
      check('card: which opens Set up your repos with Bosun and sends nothing', standing[0].App.step === 'rules' && standing[0].App.view === 'start' &&
        standing[0]._acted.length === 0);
      line = keyed(evidence(saved[0], saved[1]), 'stuck-card-c-9');
      check('card: once the file is saved the one fix is Unblock and land: ' + JSON.stringify(labels(keyed(line, 'stuck-fix'))),
        JSON.stringify(labels(keyed(line, 'stuck-fix'))) === JSON.stringify(['Unblock and land']));
      press(named(line, 'Unblock and land'));
      const otherFile = elsewhere(saved[1].stuck);
      press(named(keyed(evidence(otherFile[0], otherFile[1]), 'stuck-card-c-9'), 'Unblock and land'));
      setImmediate(function () {
        check('card: an unblock that left the card blocked on something else is followed by no Approve: ' + JSON.stringify(still[0]._acted.map((a) => a.verb)),
          JSON.stringify(still[0]._acted.map((a) => a.verb)) === JSON.stringify(['land.unlock', 'unblock']));
        check('card: and the page says the card is blocked on something else: ' + JSON.stringify(still[0]._said),
          JSON.stringify(still[0]._said) === JSON.stringify([SAID]));
        check('card: the same for Unblock and land, whose own verb is the unblock: ' + JSON.stringify(otherFile[0]._acted.map((a) => a.verb)),
          JSON.stringify(otherFile[0]._acted.map((a) => a.verb)) === JSON.stringify(['unblock']) &&
          JSON.stringify(otherFile[0]._said) === JSON.stringify([SAID]));
        check('card: Unblock and land unblocks that block, then approves: ' + JSON.stringify(saved[0]._acted),
          JSON.stringify(saved[0]._acted) === JSON.stringify([{ verb: 'unblock', id: 'c-9', expect: FILE }, { verb: 'approve', id: 'c-9', gate: 'outcome' }]));
        check('card: a refused fix sends its one verb and no Approve: ' + JSON.stringify(failing[0]._acted.map((a) => a.verb)),
          JSON.stringify(failing[0]._acted.map((a) => a.verb)) === JSON.stringify(['land.unlock']));
        check('card: the lock fix that worked lands the card, as its label says: ' + JSON.stringify(working[0]._acted.map((a) => a.verb)),
          JSON.stringify(working[0]._acted.map((a) => a.verb)) === JSON.stringify(['land.unlock', 'unblock', 'approve']) &&
          working[0]._acted[1].expect === 'outcome not merged: index.lock');
        /* an unblock the server refused outright (the act resolves nothing, and has said why) */
        check('card: an unblock the server refused is followed by no Approve: ' + JSON.stringify(halted[0]._acted.map((a) => a.verb)),
          JSON.stringify(halted[0]._acted.map((a) => a.verb)) === JSON.stringify(['land.unlock', 'unblock']));
        next();
      });
    });
  });
}

function rest(next) {
  /* the services */
  const down = page(done, 'now', null, Object.assign({}, up, { state: Object.assign({}, up.state,
    { drain: { host: 'mac', at: '2026-09-24T09:00:00+00:00', age_seconds: 3600, text: 'drain: idle', alive: false } }) }));
  let line = keyed(body(down), 'stuck-services');
  let b;
  check('services: a drain that stopped is said in the design\'s words', !!line &&
    text(keyed(line, 'stuck-what')).indexOf('The part of Shipyard that starts sessions and lands work has stopped.') >= 0);
  press(named(line, 'Restart it'));
  check('services: Restart it sends the one verb', sent(down, 'services.restart').length === 1);
  check('services: nothing is said while the drain runs', !keyed(body(page(done, 'now', null, up)), 'stuck-services'));
  const paused = page(done, 'now', null, Object.assign({}, up, { state: Object.assign({}, up.state,
    { drain: { host: 'mac', alive: false, text: 'x' }, config: { houses_max: 3, drain_paused: true, warnings: [] } }) }));
  check('services: a drain that is paused on purpose is not stuck', !keyed(body(paused), 'stuck-services'));

  /* an unknown key */
  const WHAT = 'config.toml has a setting Shipyard does not know: `[keel] huose_max`. It was ignored and the default is in use.';
  const unknown = [{ table: 'keel', key: 'huose_max', near: 'houses_max', what: WHAT, line: '[keel] huose_max is not a key; did you mean houses_max?' },
                   { table: 'spaces.work', key: 'zzz', near: null, line: '[spaces.work] zzz is not a key',
                     what: 'config.toml has a setting Shipyard does not know: `[spaces.work] zzz`. It was ignored and the default is in use.' }];
  const cfg = page(done, 'now', null, Object.assign({}, up, { state: Object.assign({}, up.state, { config: { houses_max: 3, drain_paused: false,
    warnings: unknown.map((u) => u.line).concat(['[keel] poll_seconds = "soon" is not a number; the default (30) is used']), unknown: unknown } }) }));
  b = body(cfg);
  line = keyed(b, 'stuck-config-keel-huose_max');
  check('config: an unknown key is said in the design\'s words, the key as code', !!line && codes(keyed(line, 'stuck-what')).indexOf('[keel] huose_max') >= 0 &&
    text(keyed(line, 'stuck-what')).indexOf('It was ignored and the default is in use.') >= 0);
  check('config: Rename to the near name, or Remove this line: ' + JSON.stringify(labels(keyed(line, 'stuck-fix'))),
    JSON.stringify(labels(keyed(line, 'stuck-fix'))) === JSON.stringify(['Rename to houses_max', 'Remove this line']));
  press(named(line, 'Rename to houses_max'));
  check('config: Rename sends the table, the key and the name', JSON.stringify(sent(cfg, 'setup.config.rename')[0]) ===
    JSON.stringify({ verb: 'setup.config.rename', table: 'keel', key: 'huose_max', to: 'houses_max' }));
  const far = keyed(b, 'stuck-config-spaces.work-zzz');
  check('config: with no near name there is only Remove this line', JSON.stringify(labels(keyed(far, 'stuck-fix'))) === JSON.stringify(['Remove this line']));
  press(named(far, 'Remove this line'));
  check('config: Remove sends the table and the key', JSON.stringify(sent(cfg, 'setup.config.remove')[0]) ===
    JSON.stringify({ verb: 'setup.config.remove', table: 'spaces.work', key: 'zzz' }));
  const panel = keyed(b, 'config-warnings');
  check('config: the panel keeps the warnings that are not unknown keys', !!panel && text(panel).indexOf('poll_seconds') >= 0 &&
    text(panel).indexOf('huose_max') < 0 && text(panel).indexOf('The config has 1 problem') >= 0);

  /* the sign-in that ran out */
  const out = page(done, 'now', null, Object.assign({}, up));
  out.App.data.spaces.personal.login = { state: 'expired', why: 'Login expired', never_logged_in: false, fix: 'run claude',
    signin: 'CLAUDE_CONFIG_DIR=/i/claude claude auth login', stamp: null };
  out.App.data.spaces.work.login = { state: 'expired', why: 'Login expired', never_logged_in: false, fix: 'run claude',
    signin: 'CLAUDE_CONFIG_DIR=/w/claude claude auth login', stamp: null };
  b = body(out);
  const mine = keyed(b, 'login-personal');
  check('sign-in: with another sign-in beside it, the sentence names the space: ' + text(mine).slice(0, 120), text(mine).indexOf(
    'Shipyard\'s Claude sign-in ran out, so no session of the personal space can run. They pick up where they stopped once you sign in') === 0);
  const sole = page(done, 'now', null, Object.assign({}, up));
  sole.App.data.spaces.personal.login = { state: 'expired', why: 'Login expired', never_logged_in: false, fix: 'run claude',
    signin: 'CLAUDE_CONFIG_DIR=/i/claude claude auth login', stamp: null, only: true };
  check('sign-in: the one sign-in of the install, in the design\'s words', text(keyed(body(sole), 'login-personal')).indexOf(
    'Shipyard\'s Claude sign-in ran out, so no session can run. They pick up where they stopped once you sign in') === 0);
  const third = keyed(mine, 'paused-bosun');
  check('sign-in: the third part says Bosun is paused until you sign in, with the command', !!third &&
    text(third).indexOf('or ask Bosun in its session (it is paused until you sign in):') >= 0 && codes(third).indexOf(ATTACH) >= 0);
  const theirs = keyed(b, 'login-work');
  check('sign-in: another space\'s login keeps its own words and has no such part', text(theirs).indexOf('The work login expired, so its houses cannot run') === 0 &&
    !keyed(theirs, 'paused-bosun'));
  next();
}

cards(function () { rest(function () { process.stdout.write(JSON.stringify(fails.length ? { fails } : { ok: true })); }); });
