/* What the first-run fixtures share (tests/fixtures/start-deck.js and start-steps.js): the
 * deck's modules in their real order, a state with `firstrun` and a Setup report, and the
 * few readers every check uses. One place, so a step that is added is added once.
 *
 * Usage: const start = require('./start-page.js'); const S = start(appDir);
 */
'use strict';
const deck = require('./deck-dom.js');

module.exports = function (APP) {
  const MODULES = ['ui.core.js', 'ui.findcore.js', 'ui.findpages.js', 'ui.find.js', 'ui.tips.js', 'ui.modal.js',
                   'ui.shipping.js', 'ui.shipsendback.js', 'ui.landpush.js', 'ui.cards.js', 'ui.tree.js', 'ui.reviews.js', 'ui.views.js', 'ui.stuck.js', 'ui.stuckcard.js', 'ui.signin.js', 'ui.setup.js',
                   'ui.settings.js', 'ui.startchecks.js', 'ui.startbosun.js', 'ui.startrepos.js', 'ui.startmemory.js', 'ui.startdrafts.js', 'ui.startlands.js', 'ui.flowpicture.js', 'ui.startships.js', 'ui.startbrowser.js', 'ui.startbackup.js', 'ui.startcard.js', 'ui.startdone.js', 'ui.start.js', 'ui.js'];
  const fails = [];
  function check(name, ok) { if (!ok) fails.push(name); }
  const ready = (why) => ({ ready: true, why: why, step: null });
  const not = (why, step) => ({ ready: false, why: why, step: step });
  function readiness(builder, all, login, machine) {
    const space = all ? { repos: ready('1 repo: api'), tracker: ready('t'), codehost: ready('c'), reviews: ready('r'), rules: ready('written') }
      : { repos: not('no repo is cloned for personal yet', 'repos'), tracker: not('x', 'integrations'),
          codehost: not('x', 'integrations'), reviews: not('x', 'integrations'), rules: not('y', 'rules') };
    return { install: { prerequisites: machine || ready('ok'), login: login || ready('ok'), voice: ready('ok'),
                        builder: builder === false ? not('the builder is off', 'builder') : ready('Builder, auto mode'),
                        segments: ready('1'), phone: all ? ready('the phone reaches the deck') : not('tailscale is not installed', 'phone') },
             spaces: { personal: space, work: space } };
  }
  /* the approved order (c-677), as keel/firstrun.py reports it: id, title, required, optional */
  const IDS = [['choose-builder', 'Choose your builder'], ['prerequisites', 'Check this computer', true],
               ['login', 'Sign in to Claude', true], ['builder', 'Meet Bosun'], ['repos', 'Add your repos'],
               ['memory', 'How Shipyard remembers'], ['rules', 'Set up your repos with Bosun'], ['integrations', 'Where finished work goes'],
               ['defaults', 'How work ships'], ['browser', 'A browser for sessions', false, true], ['backup', 'Back up'], ['first-card', 'Your first card'], ['set-up', 'You are set up']];
  const REQUIRED = ['prerequisites', 'login'];
  const NOTHING = ['memory', 'defaults', 'set-up'];
  const NO_SKIP = ['choose-builder', 'memory', 'set-up'];     /* steps with no Skip that Finish does not wait for */        /* steps with nothing to check: done is null, and they are not counted */
  const BOSUN_AT = IDS.findIndex((s) => s[0] === 'builder');
  const ATTACH = '/i/bin/keel console attach';
  function firstrun(finished, prereqsDone, allDone) {
    return { install: true, finished: finished, reason: null, redirect: !finished || !prereqsDone,
             steps: IDS.map((s, i) => ({ id: s[0], title: s[1], about: 'about ' + s[0], required: !!s[2], optional: !!s[3],
                                         skip: !s[2] && NO_SKIP.indexOf(s[0]) < 0, bosun: i >= BOSUN_AT,
                                         done: NOTHING.indexOf(s[0]) >= 0 ? null : REQUIRED.indexOf(s[0]) >= 0 ? prereqsDone : !!allDone,
                                         skipped: null, why: 'why ' + s[0] })) };
  }
  const REPORT = { install: '/i', config: '/i/config.toml', fresh: true, builder: null,
                   spaces: { personal: { pack: null, tier: null, writable: true, proposal: null, repos: [] } },
                   packs: [], packs_error: null, packs_folder: '/i/packs',
                   start: { prerequisites: [{ name: 'git', ok: true, said: '2.4', fix: '', required: true }],
                            login: { space: 'personal', state: 'good', config_dir: '/i/claude', fix: 'run claude' },
                            phone: { port: 8890, command: 'tailscale serve --bg 8890' }, pack_steps: {} } };

  /* `opts.state` is more of the state document (a console entry, cards, health) */
  function page(fr, view, report, opts) {
    opts = opts || {};
    const acted = [], fetched = [];
    /* `K._report` may be swapped by a check, to stand for a report that moved on the server;
       while `K._hold` is a list, a read of the report waits there until the check lets it land */
    const answer = () => ({ json: () => K._report || report || REPORT });
    const others = {};
    const K = deck.load(APP, MODULES, { desk: opts.desk !== false, fetch: (url) => { fetched.push(url);
      /* `K._answers[url]`: what another read answers, for a check that sets one */
      if (url in others) return Promise.resolve({ json: () => others[url] });
      if (url !== '/api/setup') return new Promise(() => {});
      return K._hold ? new Promise((done) => K._hold.push(() => done(answer()))) : Promise.resolve(answer()); } });
    K._fetched = fetched;
    K._answers = others;
    /* no console session yet: the state carries the attach line on `bosun` (keel/deckstate.py) */
    K.App.data = deck.state(opts.cards || [], Object.assign({ readiness: readiness(opts.builder, opts.ready, opts.login, opts.machine),
                                                             firstrun: fr, console: null, bosun: { attach: ATTACH } }, opts.state || {}));
    K.App.space = 'personal';
    K.App.view = view || 'now';
    K.App.card = null;
    K.act = (body) => { acted.push(body); return Promise.resolve({ ok: true }); };
    K._acted = acted;
    return K;
  }
  const body = (K) => { K.renderBody(); return K._doc.getElementById('body'); };
  /* a missing node has no button: the check that asked is the one that is named, never a crash */
  const named = (node, label) => (node ? deck.buttons(node).filter((b) => deck.labelOf(b) === label)[0] : undefined);
  const keyedAll = (node, key) => (node ? deck.all(node, (n) => n.nodeType === 1 && n.getAttribute('data-key') === key) : []);
  const keyed = (node, key) => keyedAll(node, key)[0];
  const stuckOf = (node) => deck.byClass(node, 'stuck');
  const countOf = (node) => (keyedAll(node, 'start-count')[0] || {}).textContent;
  const text = (node) => (node ? node.textContent : '');
  /* a step's place in the list, and the last place: the counter reads "N of M" */
  const placeOf = (id) => IDS.findIndex((s) => s[0] === id);
  return { deck, MODULES, fails, check, ready, not, readiness, IDS, REQUIRED, ATTACH, firstrun, REPORT, page, body, named,
           keyedAll, keyed, stuckOf, countOf, text, placeOf, LAST: IDS.length - 1, COUNTED: IDS.length - NOTHING.length };
};
