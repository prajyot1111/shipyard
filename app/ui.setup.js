/* The Setup route (c-618): a fresh install clones its repos, writes their tiers and turns a
 * pack on here, not by editing config.toml by hand.
 *
 * `/api/setup` (keel/onboarding.py) is the whole of what it draws: per space its tier (a
 * textarea), its repos (Remove, which takes off the config entry and leaves the folder; for
 * a repo the install cloned, its tier, Propose from the repo and Adopt), a Clone form (key
 * and URL), an Attach form (key and the path of a checkout you already have, c-632), and
 * every pack with its tool checks: a check that passes is a badge, one that fails is the
 * stuck line (c-677, app/ui.stuck.js): what happened, the fix its pack wrote for it (the
 * sentence, the command with Copy, how you know it worked: c-688, `K.fixOf`), and
 * Bosun's session while it can run (`K.bosunSession`: the builder, login and prerequisites
 * rows all ready). It is fetched when a page that draws it is opened, after each change
 * and on Look again, never on the deck's poll: it runs the packs' checks. A change to the
 * config (a clone, an attach, a remove, a space or a pack: `onboarding.CONFIG_VERBS`) is read
 * by the deck in place (`reloaded`, keel/deckreload.py, c-729), or, where it cannot be, re-execs
 * the deck (`restarting`) and the page asks again until the new process answers (`boot`); a
 * tier is a file, and needs neither. Through all of it the page keeps what it shows and marks
 * the row acted on as working (c-729), then swaps in the new report and the new state.
 *
 * The first-run stepper (app/ui.start.js, c-632) draws its screens from these same parts,
 * exported as `K.setupParts`; it took over the fresh install's redirect. The phone reaches
 * Setup under More; the desk's rail lists it. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el;
  var report = null, loading = false, failed = null;
  var draft = {};      /* space -> {key, url}: the clone form, kept across redraws */
  var attached = {};   /* space -> {key, path}: the attach form, the same way */
  var RETRY_MS = 1500;
  /* a deck waits for quiet before it re-execs (`serve.restart_when_quiet`): a minute of asking */
  var RESTART_TRIES = 40;

  var STYLE = [
    '.setup-form{display:flex;gap:8px;flex-wrap:wrap;align-items:center}',
    '.setup-form input{flex:1 1 140px;min-width:0}',
    '.setup-form input.k{flex:0 1 120px}',
    '.setup-checks{display:flex;flex-wrap:wrap;gap:6px}',
    '.setup-tier{display:flex;flex-direction:column;gap:6px}',
    '.setup-tier textarea{width:100%;min-height:120px;font-family:var(--mono);font-size:11px;line-height:1.5}',
    '.setup-needs{display:flex;flex-direction:column;gap:8px}',
    /* the row a setup action runs on (c-729): kept on the page, dimmed, and said */
    '.setup-working{position:relative;opacity:.6;pointer-events:none;transition:opacity .2s}',
    '.setup-working::after{content:"working";position:absolute;top:6px;right:6px;font-family:var(--mono);font-size:10px;color:var(--accent-ink);border:1px solid var(--accent);background:var(--s1);border-radius:var(--pill);padding:2px 8px}',
    /* a pack's name, its badge, Turn on and a Turn off per space: they wrap on a phone */
    '.pack-head{flex-wrap:wrap}.pack-head .t{flex:1 1 96px;overflow-wrap:anywhere}',
    '@media (max-width:899px){.setup-form input,.setup-form input.k,.setup-form .btn{min-height:44px;flex:1 1 100%}}'
  ].join('\n');

  function styleOnce() {
    if (document.getElementById('setup-style')) return;
    var node = document.createElement('style');
    node.id = 'setup-style';
    node.textContent = STYLE;
    document.head.appendChild(node);
  }

  /* `then` runs once it has landed: Look again asks for the state after it, since the
     report drops the deck's kept readings (keel/onboarding.py) and the state reads them again.
     `after` (c-729): a deck that is restarting answers with the old process's `boot` until it
     has gone, so a report from that process is not the new one, and is asked for again.
     A call while a read is on its way (r1.F3) is never dropped: that read may predate what
     the caller changed, so the call is kept and made once it lands, every kept `then` with it. */
  var next = null;
  function load(retries, then, after) {
    if (loading) {
      next = next || { retries: 0, thens: [], after: null };
      next.retries = Math.max(next.retries, retries || 0);
      next.after = after || next.after;
      if (then) next.thens.push(then);
      return;
    }
    loading = true;
    fetch('/api/setup', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (d) {
      loading = false;
      if (after && d.boot === after && retries > 0) { setTimeout(function () { load(retries - 1, then, after); }, RETRY_MS); return; }
      failed = null; report = d;
      if (queued()) return;
      redraw();
      if (then) then();
    }).catch(function (e) {
      loading = false;
      /* right after a change the deck is re-executing: ask again shortly */
      if (retries > 0) { setTimeout(function () { load(retries - 1, then, after); }, RETRY_MS); return; }
      /* a page that already shows the setup keeps showing it; only a first read says it failed */
      if (!report) failed = e.message;
      if (queued()) return;
      if (then) then(); else redraw();
    });
    /* the read that was asked for meanwhile goes now, and carries this one's `then` too */
    function queued() {
      if (!next) return false;
      var kept = next;
      next = null;
      if (then) kept.thens.unshift(then);
      load(kept.retries, kept.thens.length ? function () { kept.thens.forEach(function (fn) { fn(); }); } : null, kept.after);
      return true;
    }
  }
  K.loadSetup = load;
  /* THE PAGE FOLLOWS THE BOARD (c-734). The report is read on the page's own actions and on
     Look again, never on the poll; a setup card that moved from elsewhere (a draft staged,
     approved or landed by Bosun, the drain or another tab) moves `firstrun.watch` on the state
     (keel/firstrun.py `watch`), and the page that draws the report reads it again, once. */
  var watched = null;
  function follow() {
    var stamp = ((K.App.data || {}).firstrun || {}).watch;
    if (stamp === undefined || stamp === null) return;
    if (watched !== null && stamp !== watched && report) load(0);
    watched = stamp;
  }
  /* the boot's look may answer before the state document has: nothing is drawn till then */
  function redraw() { if (K.App.data && K.renderBody) K.renderBody(); }

  /* THE PAGE NEVER BLANKS (c-729). Through an action, and through any restart of the deck it
     causes, the page keeps what it shows: the row the user acted on is marked as working
     (`working`, drawn by `K.markWorking` after each paint), and the new report and the new
     state are swapped in together when they arrive. The row is the nearest element with a
     `data-key` around what was clicked, read off the page's last click. */
  var working = null, clicked = null;
  if (document.addEventListener) document.addEventListener('click', function (ev) { clicked = { node: ev.target, at: Date.now() }; }, true);
  function rowOf() {
    for (var n = clicked && Date.now() - clicked.at < 2000 ? clicked.node : null; n && n.nodeType === 1; n = n.parentNode) {
      if (n.getAttribute('data-key')) return n.getAttribute('data-key');
    }
    return null;
  }
  function settle() { working = null; redraw(); }
  /* after the report, the step's verdict: Done, the list's marks and Next are the state's */
  function landed() { return K.load().then(settle, settle); }
  var MARK = /(^|\s)setup-working(?=\s|$)/;
  /* the first element of the body with the working row's key carries the mark; any other loses it */
  K.markWorking = function () {
    var key = working && working.key, found = false;
    (function walk(n) {
      if (!n || n.nodeType !== 1) return;
      var cls = typeof n.className === 'string' ? n.className : null;
      var mine = !found && !!key && cls !== null && n.getAttribute('data-key') === key;
      if (mine) found = true;
      if (cls !== null && mine && !MARK.test(cls)) { n.className = (cls + ' setup-working').trim(); n.setAttribute('aria-busy', 'true'); }
      else if (cls !== null && !mine && MARK.test(cls)) { n.className = cls.replace(/(^|\s)setup-working(?=\s|$)/g, '').trim(); n.removeAttribute('aria-busy'); }
      for (var i = 0; i < n.childNodes.length; i++) walk(n.childNodes[i]);
    })(document.getElementById ? document.getElementById('body') : null);
  };

  /* A config change the deck cannot read in place re-execs it (the server says so with
     `restarting`), so the report is asked for until the new process answers; one it read
     in place (`reloaded`), and a tier change, are asked for at once. `row` names the row to
     mark when it is not the one clicked in: Add repo marks the repo it queued, never its form,
     which stays free for the next address while a copy runs (r1.F4). */
  function change(body, word, row) {
    var before = report && report.boot;
    working = { key: row || rowOf(), verb: body.verb };
    redraw();
    /* an Adopt's answer is said as the card's own Adopt says it (c-667, `K.sentence`) */
    return K.act(body, function (r) { return r && r.where ? K.sentence({ verb: 'approve', gate: 'outcome', id: body.card }, r) : (r && r.note) || word || 'saved'; })
      .then(function (result) {
        if (!result) { settle(); return result; }
        if (result.restarting) setTimeout(function () { load(RESTART_TRIES, landed, before || null); }, RETRY_MS);
        else load(0, landed);
        return result;
      });
  }

  /* A tier's text as he is typing it, kept across redraws until it is saved. */
  var tiers = {};
  function tierBox(id, label, text, save) {
    var value = tiers[id] !== undefined ? tiers[id] : (text || '');
    return el('div', { class: 'setup-tier', 'data-key': 'tier-' + id },
      el('div', { class: 'label', text: label }),
      el('textarea', { 'data-fk': 'tier-' + id, rows: 8, value: value, 'aria-label': label,
        oninput: function (ev) { tiers[id] = ev.target.value; } }),
      el('div', { class: 'setup-form' },
        el('button', { class: 'btn sm', onclick: function () {
          save(value).then(function (ok) { if (ok) delete tiers[id]; });
        } }, 'Save')));
  }

  /* WHAT A PROPOSE DOES, SAID IN ONE PLACE (c-664). A new user may think they say it once and
     leave, so every Propose says, before the tap, what starts and that nothing changes until
     they take the draft; after it, where it went (the card, as a link, and its state in
     words); and that it is a conversation. The flow proposal (app/ui.settings.js), the tier
     proposal and the import below, and the first run (app/ui.start.js) all draw these, so
     they cannot say different things. Each sentence is what the code does:
     - `flowcards.propose` and `tiercards.propose` file a card of its own, autonomous and
       assigned, which the drain starts a house on when a slot is free (until then there is
       no session, and the card says it waits for one); the house stages review with a file,
       which is written only when it is adopted: by Adopt here, or by the card's own
       outcome button, which reads Adopt too and is the same function
       (`onboarding.adopt_proposal`, c-667; `K.proposalOf`, app/ui.core.js);
     - Send back at that gate takes the card back to building and resumes the same session
       with the reason (`actions.act_sendback`), so there can be any number of rounds;
     - Drop in is the card's way into that session (`keel/dropin.py`, app/ui.tips.js).
     The import is Bosun's (`onboarding.import_setup`: a card the in-app builder takes, landed
     by Approve outcome), so it has its own first sentence and promises no more than that. */
  var HOUSE = { starts: 'Propose files a card of its own, and a Claude session (a house) starts on it when one is free: it reads what you wrote and writes a draft. Nothing changes until you Adopt it: the Adopt button beside the proposal or the one on its card, either one puts the draft in.',
    waits: 'waiting for a session to start',
    queued: 'Nothing changes until you Adopt its draft (the Adopt button here or the one on its card). You can open the card now, and type into its session once it has started.',
    talk: 'It is a conversation, not one message: open its card and use Drop in to type into that session, and when the draft is ready Adopt it or Send back with what to change, as many rounds as you like.',
    working: 'Nothing changes until you Adopt its draft (the Adopt button here or the one on its card). Open the card to follow it, and use Drop in there to type into its session.',
    ready: 'Adopt it, here or with Adopt on its card (the same tap); or open the card and Send back with what to change: the same session revises the draft, as many rounds as you like.' };
  var BOSUN = { waits: 'waiting for Bosun, which you start on the Bosun page',
    queued: 'Nothing changes until you Approve outcome on its card. You can open the card now; Bosun takes it once it is started.',
    starts: 'Import files a card of its own for Bosun, your in-app builder: one Claude session, which you start on the Bosun page. It writes a draft (the pack mine, on a branch). Nothing changes until you Approve outcome on that card.',
    talk: 'It is not one message either: Bosun asks you on the Bosun page when it needs an answer, and the draft waits on its card for you.',
    working: 'Nothing changes until you Approve outcome on its card. Bosun takes it once it is started, on the Bosun page.',
    ready: 'Open the card to read the draft, then Approve outcome there to land it.' };
  var STATES = { planning: 'working', building: 'working', review: 'draft ready' };
  var proposing = {
    /* before the tap, beside the button */
    before: function (bosun) {
      var words = bosun ? BOSUN : HOUSE;
      return el('div', { class: 'sub proposing', 'data-key': 'proposing-before' }, words.starts + ' ' + words.talk);
    },
    /* one line of it, for a step that only mentions a Propose */
    line: HOUSE.starts,
    /* an assigned card has no session yet, so it says what it waits for, not "starting" */
    state: function (p, bosun) {
      if (p.waiting) return 'waiting for you (it asked something: open the card to answer it)';
      return p.stage === 'assigned' ? (bosun ? BOSUN : HOUSE).waits : (STATES[p.stage] || p.stage);
    },
    /* after it: `p` is the open proposal ({card, stage, waiting}), `what` what it drafts,
       and `adopt` the Adopt button where the draft is taken here */
    after: function (p, what, adopt, bosun) {
      var words = bosun ? BOSUN : HOUSE;
      return el('div', { class: 'sub proposing', 'data-key': 'proposing-' + p.card },
        el('a', { href: '/?card=' + p.card, text: p.card }),
        (p.stage === 'assigned' ? ' will draft ' : ' is drafting ') + what + ': ' + proposing.state(p, bosun) + '. ',
        p.stage === 'review' ? words.ready : p.stage === 'assigned' ? words.queued : words.working,
        p.stage === 'review' && adopt ? ' ' : null, p.stage === 'review' ? adopt : null);
    }
  };
  K.proposing = proposing;

  /* Propose is an audit (keel/tiercards.py): the user's own words first, carried into the card's
     brief verbatim; empty is allowed. An open proposal shows its card, and Adopt at review.
     A draft Bosun has started reads as any open proposal does. */
  var likes = {};
  function proposalBits(id, p, aim, label) {
    /* a draft card Bosun has not started (c-678, keel/tiercards.py `open_draft`): said, and
       Propose stays, since it takes that card's place */
    var unstarted = p && p.draft && p.stage === 'inbox';
    if (p && !unstarted) return el('div', { class: 'setup-tier', 'data-key': 'proposal-' + id },
      proposing.after(p, 'the ' + label + ' tier', el('button', { class: 'btn sm primary', onclick: function () {
        change({ verb: 'setup.tier.adopt', card: p.card }, 'the proposal is now the ' + label + ' tier');
      } }, 'Adopt')));
    return el('div', { class: 'setup-tier', 'data-key': 'propose-' + id },
      unstarted ? el('div', { class: 'sub proposing', 'data-key': 'draft-open-' + id },
        el('a', { href: '/?card=' + p.card, text: p.card }),
        ' is open for Bosun to draft the ' + label + ' tier with you: tell Bosun in its session. Propose below files a card of its own in its place.') : null,
      el('textarea', { 'data-fk': 'likes-' + id, rows: 2, value: likes[id] || '',
        placeholder: 'What do you like? (style, testing, review, anything)', 'aria-label': 'What do you like?',
        oninput: function (ev) { likes[id] = ev.target.value; } }),
      proposing.before(),
      el('div', { class: 'setup-form' }, el('button', { class: 'btn sm', onclick: function () {
        change(Object.assign({ verb: 'setup.tier.propose', likes: likes[id] || '' }, aim),
          'filed: a house will audit ' + label + ' and draft its tier; its card is linked here now').then(function (ok) { if (ok) delete likes[id]; });
      } }, 'Propose from the ' + (aim.key ? 'repo' : 'space\'s repos'))));
  }

  function repoRow(space, r) {
    return el('div', { class: 'row', 'data-key': space + '/' + r.key },
      el('div', { class: 'row-head' }, el('span', { class: 't', text: r.key }),
        r.ok ? null : el('span', { class: 'badge need', text: 'missing' }),
        r.cloned ? null : el('span', { class: 'badge', text: 'existing checkout' }),
        el('button', { class: 'btn sm crit', onclick: function () {
          if (window.confirm('Take ' + r.key + ' off ' + space + '? Only the config entry goes: its folder stays where it is.'))
            change({ verb: 'setup.repo.remove', space: space, key: r.key });
        } }, 'Remove')),
      el('div', { class: 'sub mono t11', text: r.path }),
      r.cloned ? proposalBits(space + '/' + r.key, r.proposal, { space: space, key: r.key }, r.key) : null,
      r.cloned ? tierBox(space + '/' + r.key, 'Repo tier · ' + r.key + '/CLAUDE.md', r.tier, function (text) {
        return change({ verb: 'setup.tier.save', space: space, key: r.key, text: text }, r.key + ' tier saved');
      }) : null);
  }

  function cloneForm(space) {
    var d = draft[space] = draft[space] || { key: '', url: '' };
    function field(name, cls, hint) {
      return el('input', { type: 'text', class: cls, 'data-fk': 'setup-' + space + '-' + name, placeholder: hint,
        value: d[name], 'aria-label': hint, oninput: function (ev) { d[name] = ev.target.value; } });
    }
    return el('div', { class: 'setup-form', 'data-key': space + '/form' },
      field('key', 'k', 'key, e.g. api'), field('url', 'p', 'git URL to clone'),
      el('button', { class: 'btn primary', onclick: function () {
        change({ verb: 'setup.repo.clone', space: space, key: d.key.trim(), url: d.url.trim() }, d.key.trim() + ' cloned')
          .then(function (ok) { if (ok) draft[space] = { key: '', url: '' }; });
      } }, 'Clone'));
  }

  /* An existing checkout listed where it is (c-632), as `shipyard import` lists them: no
     clone, and outside the layout the tiers do not load there. */
  function attachForm(space) {
    var d = attached[space] = attached[space] || { key: '', path: '' };
    function field(name, cls, hint) {
      return el('input', { type: 'text', class: cls, 'data-fk': 'attach-' + space + '-' + name, placeholder: hint,
        value: d[name], 'aria-label': hint, oninput: function (ev) { d[name] = ev.target.value; } });
    }
    return el('div', { class: 'setup-form', 'data-key': space + '/attach' },
      field('key', 'k', 'key, e.g. api'), field('path', 'p', 'path of a checkout you have'),
      el('button', { class: 'btn', onclick: function () {
        change({ verb: 'setup.repo.attach', space: space, key: d.key.trim(), path: d.path.trim() }, d.key.trim() + ' listed')
          .then(function (ok) { if (ok) attached[space] = { key: '', path: '' }; });
      } }, 'Attach'));
  }

  function spacePanel(name, s) {
    return el('section', { class: 'panel', 'data-key': 'space-' + name },
      el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'Repos · ' + name }),
        el('span', { class: 'spacer' }), s.pack ? el('span', { class: 'mono t11 ink3', text: 'pack ' + s.pack }) : null),
      el('div', { class: 'panel-body' },
        s.writable ? tierBox(name, 'Space tier · rules for every repo of ' + name, s.tier, function (text) {
          return change({ verb: 'setup.tier.save', space: name, text: text }, name + ' tier saved');
        }) : null,
        s.writable && s.repos.some(function (r) { return r.cloned; })
          ? proposalBits(name, s.proposal, { space: name }, 'the ' + name + ' space') : null,
        s.repos.length ? s.repos.map(function (r) { return repoRow(name, r); })
          : el('div', { class: 'empty', text: 'no repos yet: clone one, and a card in ' + name + ' can name it' }),
        s.writable ? cloneForm(name) : null,
        s.writable ? attachForm(name) : null));
  }

  /* A pack's checks: the ones that pass as badges, each one that fails as the stuck line.
     A check's `why` is why the pack needs it, so what happened is said as readiness says it
     (keel/readiness.py): "<name> is not set up: <why>". The fix is the check's own, where
     its pack wrote one (`K.fixOf`, c-688); a check with none has the reason alone. */
  function notSetUp(c) { return c.name + ' is not set up: ' + c.why; }
  function checks(list) {
    if (!list.length) return el('span', { class: 'mono t11 ink3', text: 'needs no tools' });
    var passing = list.filter(function (c) { return c.ok; }), failing = list.filter(function (c) { return !c.ok; });
    return el('div', { class: 'setup-needs' },
      passing.length ? el('div', { class: 'setup-checks' }, passing.map(function (c) {
        return el('span', { class: 'badge', title: c.why, text: '✓ ' + c.name });
      })) : null,
      failing.map(function (c) { return K.stuck({ key: 'check-' + c.name, name: c.name, what: notSetUp(c), fix: K.fixOf(c) }); }));
  }

  /* Turn off, one button per space the pack is on (c-688, `packsetup.pack_off`): the pack
     and what Turn on wrote for it go and the space stays, so it is asked once and said
     plainly. A demo-only pack leaves this list on an install once no space is on it
     (`packsetup.offered`), so the confirm for its last space says that and does not promise
     Turn on; while another space is still on it the row stays, and the words are the
     ordinary ones. The server
     refuses while the space has open cards, and its words are the toast. */
  function turnOff(p, name) {
    var last = p.spaces.length === 1 && p.spaces[0] === name;
    var after = p.demo_only && last && report && report.install ? 'It is for demos only, so it will no longer be listed here.' : 'Turn on puts it back.';
    return el('button', { class: 'btn sm', 'data-key': 'off-' + name, onclick: function () {
      /* c-758: no noun, so the Setup view (a pack) and the first run (a connection) say it alike */
      if (window.confirm('Turn ' + p.name + ' off for ' + name + '? The space, its repos and its own settings stay; ' + p.name + ' and the settings it brought come off. ' + after))
        change({ verb: 'setup.pack.off', space: name });
    } }, 'Turn off for ' + name);
  }

  /* Turn on asks for a space here. Given `space` (the stepper's Where finished work goes step), it turns
     the pack on for that one: a plain space is adopted, a new name is a new space (c-632). */
  /* c-734: Turn on is offered only for a space the pack is not on, by name: the given space
     (the stepper's), else each space with no pack, and a new space by name. A pack on for its
     only space showed both Turn on and Turn off for it, which read as if it were off. */
  function turnOn(p, name) {
    return el('button', { class: 'btn sm', 'data-key': 'on-' + name, onclick: function () {
      change({ verb: 'setup.pack.on', pack: p.name, space: name });
    } }, 'Turn on for ' + name);
  }
  function turnOnNew(p) {
    return el('button', { class: 'btn sm', 'data-key': 'on-new', onclick: function () {
      var name = window.prompt('Turn ' + p.name + ' on for a new space: its name (lower case, e.g. work):', '');
      if (name && name.trim()) change({ verb: 'setup.pack.on', pack: p.name, space: name.trim() });
    } }, 'Turn on for a new space');
  }
  function onButtons(p, space, locked) {
    if (space) return p.spaces.indexOf(space) < 0 && !locked ? turnOn(p, space) : null;
    var free = Object.keys((report && report.spaces) || {}).filter(function (name) { return !report.spaces[name].pack; });
    return [free.map(function (name) { return turnOn(p, name); }), turnOnNew(p)];
  }
  /* c-734: on the Setup page a pack on for no space says what it still needs in one quiet line,
     as a connection that is not on does on Where finished work goes (c-729), never a needs-you block */
  function quietChecks(list) {
    var missing = list.filter(function (c) { return !c.ok; }).map(function (c) { return c.name; });
    var passing = list.filter(function (c) { return c.ok; });
    return el('div', { class: 'setup-needs' },
      passing.length ? el('div', { class: 'setup-checks' }, passing.map(function (c) {
        return el('span', { class: 'badge', title: c.why, text: '✓ ' + c.name });
      })) : null,
      missing.length ? el('div', { class: 'mono t11 ink3', 'data-key': 'pack-needs', text: 'needs: ' + missing.join(', ') }) : null);
  }
  /* `opts` (c-758, Where finished work goes): `quiet`, a row that is not on for `space` says
     what it needs in the one quiet line too; `locked`, no Turn on (the space is on another) */
  function packRow(p, space, opts) {
    opts = opts || {};
    var off = space ? p.spaces.indexOf(space) < 0 : !p.spaces.length;
    var quiet = (opts.quiet || !space) && off && (p.checks || []).length;
    return el('div', { class: 'row', 'data-key': 'pack-' + p.name },
      el('div', { class: 'row-head pack-head' }, el('span', { class: 't', text: p.name }),
        p.spaces.length ? el('span', { class: 'badge', text: 'on: ' + p.spaces.join(', ') }) : null,
        onButtons(p, space, opts.locked),
        p.spaces.map(function (name) { return turnOff(p, name); })),
      el('div', { class: 'sub', text: p.description }),
      quiet ? quietChecks(p.checks) : checks(p.checks || []),
      space ? null : ownRepo(p));
  }
  /* A pack that is its own clone in the packs folder (c-740 r1.F1): once Bosun builds it, the
     repo its cards name; until then one tap that lists it (`setup.pack.build`), on an install
     whose builder is Bosun. A change to it then lands in the pack's own repo. */
  function ownRepo(p) {
    var own = p.own_repo;
    if (!own) return null;
    if (own.built) return el('div', { class: 'mono t11 ink3', 'data-key': 'pack-own-repo',
      text: 'It has a repo of its own. Bosun builds it there, as the repo ' + own.key + '.' });
    if (!(report && report.builder && report.builder.mode === 'in-app')) return null;
    return el('div', { class: 'setup-form', 'data-key': 'pack-own-repo' },
      el('span', { class: 'sub', text: 'It has a repo of its own. Bosun does not build it yet.' }),
      el('button', { class: 'btn sm', onclick: function () {
        change({ verb: 'setup.pack.build', pack: p.name }, 'Bosun builds ' + p.name + ' in its own repo now');
      } }, 'Let Bosun build this pack'));
  }

  /* Import my Claude setup (c-619): a card for the in-app builder, which reads ~/.claude and
     writes it as packs/mine/ on its branch; Approve outcome lands it. */
  function importPanel(m) {
    var sb = m.sandbox || {};
    return el('section', { class: 'panel', 'data-key': 'import' },
      el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'Your own Claude' })),
      el('div', { class: 'panel-body' },
        el('div', { class: 'sub', text: 'Bosun reads your ~/.claude (CLAUDE.md, skills, agents, commands; never its ' +
          'settings or credentials) and writes them as the pack mine. Settings, hooks and MCP servers are not imported: carry them over by hand.' }),
        sb.ok === false ? el('div', { class: 'empty crit', text: 'The sandbox cannot run here: ' + sb.fix }) : null,
        /* c-664: what the tap starts, and once it is filed, where it went and how it stands */
        m.importing ? proposing.after(m.importing, 'the pack mine', null, true) : [proposing.before(true),
          el('div', { class: 'setup-form' }, el('button', { class: 'btn sm', onclick: function () {
            change({ verb: 'setup.import' }, 'filed: Bosun imports your Claude setup');
          } }, 'Import my Claude setup'))]));
  }

  /* Look again: the report and the state read again, what is shown kept meanwhile (c-729) */
  function again() { working = { key: rowOf(), verb: 'again' }; redraw(); load(0, landed); }

  function viewSetup() {
    styleOnce();
    if (!report && !loading && !failed) load(0);
    follow();
    if (failed) return el('div', { class: 'empty', text: 'Setup could not be read: ' + failed });
    if (!report) return el('div', { class: 'empty', text: 'reading the setup...' });
    var out = [];
    if (!report.install) out.push(el('div', { class: 'empty', 'data-key': 'not-install',
      text: 'This deck reads ' + report.config + ', which is not an install\'s config.toml: Setup shows it and changes nothing.' }));
    Object.keys(report.spaces).forEach(function (name) { out.push(spacePanel(name, report.spaces[name])); });
    if (report.install && report.builder && report.builder.mode === 'in-app') out.push(importPanel(report.builder));
    out.push(el('section', { class: 'panel', 'data-key': 'packs' },
      el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'Packs' }), el('span', { class: 'spacer' }),
        el('button', { class: 'btn sm', onclick: again }, 'Look again')),
      el('div', { class: 'panel-body' },
        packProblems(report),
        /* no space is given here, so Turn on asks for one (`map` would pass the index) */
        /* a pack that does not load empties the list: the error above says which, so "no packs" is not said too */
        report.packs.length ? report.packs.map(function (p) { return packRow(p); })
          : report.packs_error ? null : el('div', { class: 'empty', text: 'no packs found' }),
        sharedPack(report))));
    return out;
  }

  /* What is wrong in the packs folder, a line each (c-740): a pack that does not load, or a
     folder that is not called what its pack is, beside the packs that still list. */
  /* `said` (c-758 r1.F7): the same lines in another page's word (the first run's
     `connections_error`); the Setup view draws its own, `packs_error` */
  function packProblems(r, said) {
    return String((said === undefined ? r.packs_error : said) || '').split('\n').filter(Boolean).map(function (line) {
      return el('div', { class: 'empty crit', 'data-key': 'packs-problem', text: line });
    });
  }

  /* The one line for a connection someone shared (c-740): a clone of its own in the install's
     packs folder, which is filled in; the address and the name are the reader's to put in.
     The Setup view and Where finished work goes both draw this (c-758), with Copy on the
     command and Look again beside it; `opts.found`: one is there already, so it says "another";
     `opts.noun` (r1.F7): the page's one word for it, pack here and connection on the first run. */
  function sharedPack(r, opts) {
    if (!r.install || !r.packs_folder) return null;   /* the folder comes quoted as a shell reads it (r1.F8) */
    var more = opts && opts.found, noun = (opts && opts.noun) || 'pack';
    return el('div', { class: 'row pack-shared', 'data-key': 'pack-shared' },
      el('div', { class: 'sub', 'data-key': 'pack-shared-said', text: (more ? 'To add another, run' : 'Run') + ' this in a terminal, ' +
        'with the address your teammate gave you and the ' + noun + '\'s name. It goes in a folder of its own here, named for the ' + noun + ':' }),
      K.command('git clone <its address> ' + r.packs_folder + '/<name>'),
      el('div', { class: 'setup-form' },
        el('span', { class: 'sub', text: 'Shipyard does not run it for you. When it has finished:' }),
        el('button', { class: 'btn sm', 'data-key': 'pack-shared-again', onclick: again }, 'Look again')));
  }
  K.viewSetup = viewSetup;

  /* The phone reaches Setup under More, as it does the Atlas. */
  var baseMore = K.viewMore;
  K.viewMore = function () {
    var out = baseMore ? baseMore() : [];
    if (!Array.isArray(out)) out = [out];
    out.splice(1, 0, el('section', { class: 'panel', 'data-key': 'setup-entry' },
      el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'This install' })),
      el('div', { class: 'panel-body' },
        el('button', { class: 'row', onclick: function () { K.go('setup'); } },
          el('div', { class: 'row-head' }, el('span', { class: 't', text: 'Setup' }),
            el('span', { class: 'spacer' }),
            el('span', { class: 'mono t11 ink3', text: 'repos and packs' }))))));
    return out;
  };

  /* What the stepper (app/ui.start.js) builds its screens from: the same report and the
     same rows and forms, so Setup and Start can never draw one thing two ways. */
  K.setupParts = {
    report: function () { return report; }, failed: function () { return failed; },
    want: function () { styleOnce(); if (!report && !loading && !failed) load(0); follow(); },
    again: again,
    change: change, tierBox: tierBox, proposalBits: proposalBits, repoRow: repoRow, cloneForm: cloneForm,
    attachForm: attachForm, packRow: packRow, packProblems: packProblems, sharedPack: sharedPack, checks: checks, notSetUp: notSetUp, importPanel: importPanel
  };
})(window.Keel);
