/* The rest of the routes: Now, Attention, Segments and More.
 *
 * The adapter's route, Reviews, is `ui.reviews.js`. */
(function (K) {
  'use strict';

  var el = K.el, add = K.add, App = K.App;

  /* ---------- Now ---------- */
  function usageTile(w) {
    var level = w.used >= 85 ? 'crit' : w.used >= 65 ? 'warn' : '';
    /* the level is the tile's class, not only the meter's: a grey 75% beside a red 94%
       said the window was fine when it is two thirds gone */
    return el('div', { class: 'stat' + (level ? ' ' + level : ''), 'data-key': w.key },
      el('div', { class: 'n', text: w.used + '%' }),
      el('div', { class: 'l', text: K.isDesk() ? w.label : w.label.replace(' usage', '') }),
      el('div', { class: 'meter' }, el('i', { class: level, style: 'width:' + Math.max(2, w.used) + '%' })),
      el('div', { class: 's', text: w.span + ', resets ' + K.until(w.resets_at) }));
  }
  /* "2 at a gate, 1 blocked, 1 notice": only the kinds there are, so a deck with no
     notice does not spend the line saying so. */
  function needTally(t) {
    return [[t.gate, 'at a gate'], [t.blocked, 'blocked'], [t.notice, t.notice === 1 ? 'notice' : 'notices'],
      [t.ask, 'asked by Bosun'], [t.waits, 'waiting on your answer']]
      .filter(function (p) { return p[0]; }).map(function (p) { return p[0] + ' ' + p[1]; }).join(', ');
  }
  function statTiles() {
    var u = App.data.usage, need = K.needsYou(), run = K.running();
    var tally = { gate: 0, blocked: 0, notice: 0, ask: 0, waits: 0 };
    need.forEach(function (c) { var k = K.needKind(c); tally[k === 'plan' || k === 'outcome' ? 'gate' : k] += 1; });
    var tiles = u.windows.map(usageTile);
    if (!u.available) {
      tiles.push(el('div', { class: 'stat', 'data-key': 'usage' }, el('div', { class: 'n', text: '?' }), el('div', { class: 'l', text: 'Usage' }),
        el('div', { class: 's', text: 'no usage file' })));
    }
    tiles.push(el('div', { class: 'stat' + (need.length ? ' flag' : ''), 'data-key': 'attention' }, el('div', { class: 'n', text: String(need.length) }),
      el('div', { class: 'l', text: 'Attention' }),
      el('div', { class: 's', text: need.length ? needTally(tally) : 'nothing waiting' })));
    tiles.push(el('div', { class: 'stat', 'data-key': 'houses' }, el('div', { class: 'n', text: String(run.length) }), el('div', { class: 'l', text: 'Houses running' }),
      el('div', { class: 's', text: run.length ? run.map(function (c) { return c.id; }).join(', ')
        : 'of ' + App.data.config.houses_max + (App.data.config.drain_paused ? ', drain paused' : '') })));
    return el('div', { class: 'stats' }, tiles);
  }
  /* Every button here that sends a verb goes through `K.actionBtn`, so a Now tile says
     the same waiting as the inspector: the pressed button carries the progress verb and
     the tile's other buttons go quiet until the answer lands. */
  function houseActionNodes(c) {
    var blocked = !!c.blocked_reason;
    /* The same names and the same hover lines as the card's own row (U1, U2); a session
       in his terminal gets neither Logs nor Stop, which take a background id (U3) */
    var house = c.house && c.house.recorded !== false && !K.inTerminal(c);
    /* c-601: the tile asks the card pane's one table (`K.shownIn`, CONTROL_PHASES) too */
    function keyed(key, node) {
      if (!node || !K.shownIn(key, c)) return null;
      node.setAttribute('data-key', key);
      return node;
    }
    /* c-600: a blocked shipping card is never resumed or retried from here (a Retry would
       restart a shipped card from scratch): its way on is Unblock, and Talk on the card */
    if (blocked && K.stageOf(c) === 'shipping') {
      return [keyed('unblock', K.actionBtn('Unblock only', { verb: 'unblock', id: c.id }, { cls: 'sm', title: K.tip('unblock', c) }))];
    }
    return (blocked ? [
      K.inTerminal(c) || !c.session_id ? null : keyed('resume', K.actionBtn('Resume house', { verb: 'house.resume', id: c.id },
        { cls: 'sm', title: K.tip('resume', c) })),
      /* V2-2: back with no turn, and straight into the Claude app */
      K.appResumable(c) ? keyed('resume-app', K.tipped(K.resumeAppBtn(c, 'Resume and open in app', 'sm'), 'resume-app', c)) : null,
      keyed('retry', K.actionBtn('Retry', { verb: 'house.retry', id: c.id },
        { cls: 'sm', confirm: 'Start a fresh house on ' + c.id + '?', title: K.tip('retry', c) }))
    ] : [
      house && c.options.app_link ? keyed('open-app', el('button', { class: 'btn sm', title: K.tip('open-app', c),
        onclick: function () { K.openLink(c.options.app_link); } }, 'Open in app')) : null,
      house ? keyed('logs', el('button', { class: 'btn sm', title: K.tip('logs', c),
        onclick: function (ev) { K.showLogs(c.id, ev.currentTarget); } }, 'Logs')) : null,
      /* c-607: an idle house's quieter way out, back at its next batch or his tap */
      house && K.closeableIdle && K.closeableIdle(c) ? keyed('close-idle', K.closeIdleBtn(c, 'sm')) : null,
      house ? keyed('stop', K.actionBtn('Stop', { verb: 'house.stop', id: c.id },
        { cls: 'sm crit', confirm: 'Stop the session on ' + c.id + '? Nothing else ends a live session.',
          title: K.tip('stop', c) })) : null,
      K.talking(c) ? keyed('end-discussion', K.actionBtn('End discussion', { verb: 'end_discussion', id: c.id },
        { cls: 'sm', title: K.tip('end-discussion', c) })) : null
    ]).filter(Boolean);
  }
  /* V2-1: a tile with more than two actions draws them in the card's groups (ui.tips.js),
     so it stays one short row; two or fewer are plain buttons. */
  var TILE_PLAIN = 2;
  function houseActions(c) {
    var nodes = houseActionNodes(c);
    return el('div', { class: 'house-actions rowbody' },
      nodes.length > TILE_PLAIN ? K.groupRow(c, nodes, 'tile') : nodes);
  }
  K.actionSources.tile = houseActionNodes; K.houseActions = houseActions;
  /* c-606: a blocked tile says why it is blocked and what the house last said as two
     labelled lines: joined with a space they read as one sentence. A strip whose second
     line is already the last words (not a prompt or a working detail) says them once. */
  function blockedSaid(c, strip) {
    var said = c.last_said && !(strip && K.stripSaysLast && K.stripSaysLast(c));
    return [el('div', { class: 'house-log sub', 'data-key': 'reason' },
        el('span', { class: 'ink3', text: 'why: ' }), K.firstLine(c.blocked_reason)),
      strip, said ? el('div', { class: 'house-log sub', 'data-key': 'said' },
        el('span', { class: 'ink3', text: 'last said: ' }), K.firstLine(c.last_said)) : null];
  }
  /* A tile that is bridging says no word for busy or idle: the house word above it is
     already saying that the house is coming back, and "idle" beside it was the lie. */
  function houseAge(c) {
    var started = c.house && c.house.started_at ? new Date(c.house.started_at).toISOString() : c.updated_at;
    if (K.bridgeWord(c)) return K.ago(started);
    /* A house that went quiet mid-turn is idle since it went quiet, not since its session
       started: the tile used to say "idle 3h" about a house that worked for most of it. */
    if (c.idle) return 'idle ' + K.ago(c.idle.since);
    /* c-607: an idle house's age is since its turn ended, as its strip and Now's Idle houses say */
    var idleS = !K.houseBusy(c) && K.idleSeconds ? K.idleSeconds(c) : null;
    if (idleS !== null && idleS !== undefined && K.liveShort) return 'idle ' + K.liveShort(idleS);
    return (K.houseBusy(c) ? 'busy ' : 'idle ') + K.ago(started);
  }
  /* c-606: the house word under the title says blocked, so the head says only how long it
     has been blocked, from the same fact Attention dates it by (derived.gate_since; a note
     moves updated_at). A relay in flight takes the house word, so then the head says it. */
  function tileAge(c) {
    if (!c.blocked_reason || K.bridgeWord(c)) return el('span', { class: 'age', text: houseAge(c) });
    var age = K.ago(c.derived.gate_since || c.updated_at);
    var relay = (c.derived.relays || [])[0];
    return el('span', { class: 'age', title: 'how long it has been blocked', text: relay ? 'blocked ' + age : age });
  }
  function houseTile(c) {
    var blocked = !!c.blocked_reason;
    return el('div', { class: 'house' + (blocked ? ' blocked' : K.houseBusy(c) ? ' run' : ' quiet'), 'data-key': c.id },
      el('div', { class: 'house-head' },
        el('span', { class: 'id', text: c.id }),
        el('button', { class: 't ellip', title: c.title, onclick: function () { K.go(K.cardRoute(c), c.id); } }, c.title),
        tileAge(c)),
      K.wordsRow(c, true),
      stripOrSaid(c),
      houseActions(c));
  }
  /* The live strip (c-599, app/ui.live.js) carries what the house said as its second line,
     so the tile draws one or the other; a blocked card leads with its reason. */
  function stripOrSaid(c) {
    var strip = K.liveStrip ? K.liveStrip(c, true) : null;
    if (c.blocked_reason) return blockedSaid(c, strip);
    return strip || el('div', { class: 'house-log sub', text: c.last_said || (c.house ? c.house.status : '') || 'nothing said yet' });
  }

  /* A big card whose slices are running is ONE tile, with the running slices under it:
     three houses cutting one card apart are one piece of work, and Now said they were
     three unrelated rows. The tile's head is the parent (its derived stage and the slice
     tally); each line under it is a running slice with its own words and its own buttons. */
  function trackTile(parent, slices) {
    return el('div', { class: 'house big', 'data-key': parent.id },
      el('div', { class: 'house-head' },
        el('span', { class: 'id', text: parent.id }),
        el('button', { class: 't ellip', title: parent.title, onclick: function () { K.go('cards', parent.id); } }, parent.title)),
      el('div', { class: 'swords' }, K.word(K.trackWord(parent), 'slices')),
      el('div', { class: 'slicelines' }, slices.map(function (c) {
        return el('div', { class: 'sliceline' + (c.blocked_reason ? ' blocked' : ''), 'data-key': c.id },
          el('div', { class: 'house-head' },
            el('span', { class: 'id', text: c.id }),
            el('button', { class: 't ellip', title: c.title, onclick: function () { K.go(K.cardRoute(c), c.id); } }, c.title),
            tileAge(c)),
          K.wordsRow(c, true),
          stripOrSaid(c),
          houseActions(c));
      })));
  }

  /* The Now strip in the order the houses came, with the slices of one big card collected
     onto that card's tile (the parent keeps the place of its first running slice). */
  function nowTiles() {
    var groups = [], byParent = {};
    K.houses().forEach(function (c) {
      var p = c.parent ? K.byId(c.parent) : null;
      if (!p) { groups.push({ parent: null, card: c }); return; }
      if (!byParent[p.id]) { byParent[p.id] = { parent: p, slices: [] }; groups.push(byParent[p.id]); }
      byParent[p.id].slices.push(c);
    });
    return groups.map(function (g) { return g.parent ? trackTile(g.parent, g.slices) : houseTile(g.card); });
  }
  function glanceRows() {
    var u = App.data.usage, need = K.needsYou(), run = K.running();
    var rows = [];
    if (u.available) {
      rows.push(['limits', u.windows.map(function (w) {
        return w.label.replace(' usage', '').toLowerCase() + ' ' + w.used + '% used, resets ' + K.until(w.resets_at);
      }).join(' · ')]);
    }
    rows.push(['attention', need.length ? need.map(function (c) {
      return c.id + ' ' + K.needWord(c);
    }).join(', ') : 'nothing waiting']);
    rows.push(['houses', run.length ? run.length + ' running: ' + run.map(function (c) { return c.id; }).join(', ')
      : 'none running' + (App.data.config.drain_paused ? ' (drain paused)' : '')]);
    rows.push(['backlog', (K.spaceInfo().counts || {}).backlog
      ? K.spaceInfo().counts.backlog + ' cards sat at their outcome gate; the Cards chip shows them' : 'nothing has backlogged']);
    /* lane RC: the review cards waiting on him (his Review tap, his gate, new commits); on
       every space, since Reviews explains itself where it is not set up (c-631), but only
       while some space can file review cards at all (c-730) */
    if (K.declaredSomewhere(K.viewOf('reviews').needs)) {
      rows.push(['reviews', K.unmet(K.viewOf('reviews').needs).length ? 'not set up'
        : (K.reviewCount ? K.reviewCount() : 0) + ' waiting on you']);
    }
    var segs = App.data.segments;
    if (segs.length) {
      rows.push(['segments', segs.map(function (s) { var t = (s.summary.tiles || [])[0]; return s.name + (t ? ' ' + t.value + ' ' + t.label : s.fetched === false ? ' not fetched yet' : ''); }).join(' · ')]);
    }
    return el('dl', { class: 'kv' }, rows.map(function (r2) { return el('div', { class: 'kv-row', 'data-key': r2[0] }, el('dt', { text: r2[0] }), el('dd', { text: r2[1] })); }));
  }
  /* ---------- the services block (F4) ----------
   * One row per service Keel runs on, from `health.services` (keel/health.py): the name,
   * the service's own word for its state in its level's colour, and how long ago the
   * instant it names was (its last start, its last pass, its last good run), aged here
   * on the page's clock. A service this machine does not run says so, at level `off`. */
  function servicesBlock(h) {
    var rows = (h && h.services) || [];
    return el('div', { class: 'services', 'data-key': 'services' }, rows.length ? rows.map(function (s) {
      return el('div', { class: 'svc ' + s.level, 'data-key': s.name },
        el('span', { class: 'hdot', 'aria-hidden': 'true' }),
        el('span', { class: 'svc-name', text: s.name }),
        el('span', { class: 'svc-state', text: s.state }),
        el('span', { class: 'age', text: s.at ? K.ago(s.at) : '' }));
    }) : el('div', { class: 'empty', text: 'no reading yet' }));
  }
  function reasonsBlock(h) {
    var reasons = (h && h.reasons) || [];
    if (!reasons.length) return el('div', { class: 'ink2', 'data-key': 'reasons', text: 'nothing is wrong' });
    return el('ul', { class: 'reasons', 'data-key': 'reasons' }, reasons.map(function (r) {
      return el('li', { 'data-key': r, text: r });
    }));
  }
  function healthSheet() {
    var h = K.health() || { level: 'unknown', reasons: [], services: [] };
    return el('div', { class: 'sheet', 'data-key': 'sheet-health' },
      el('div', { class: 'sheet-head' },
        el('button', { onclick: function () { App.sheet = null; K.renderSheet(); } }, '‹ close'),
        el('span', { class: 'spacer' }),
        el('span', { class: 'mono t11 ink2', text: 'services' })),
      el('div', { class: 'sheet-body' },
        el('div', { class: 'title', text: 'Shipyard is ' + h.level }),
        reasonsBlock(h),
        servicesBlock(h),
        el('div', { class: 'sheet-sub', 'data-key': 'logins-head' }, K.loginsLabel()),
        K.loginsBlock()));
  }
  K.healthSheet = healthSheet;

  /* ---------- a space whose login expired (lane Q) ----------
   * `spaces.<name>.login` is the drain's kept probe answer (keel/login.py). An expired one
   * means no house of that space can run and its quiet houses are blocked for it, so Now
   * and Attention open with one line per such space, whichever space the switch shows: it
   * is the one fault the Attention rows alone would misread as N separate blocks. A dir
   * that never held a login (`never_logged_in`, c-560) is said so, not called expired. The
   * fix is the guided sign-in (c-678, app/ui.signin.js), folded under Sign in again: the
   * four lines with the space's own command (`login.signin`), and the live status, which
   * probes that space when a sign-in appears. */
  function installLogin(name, spaces) { return name === 'personal' || (!spaces.personal && Object.keys(spaces)[0] === name); }
  /* The third part while the sign-in is out (c-678): Bosun's session cannot answer until
     it is back, and the line says so (`K.bosunSession` draws none then, since nothing runs). */
  function pausedBosun() {
    var entry = App.data.console || App.data.bosun;
    if (!entry || !entry.attach) return null;
    return el('div', { class: 'stuck-bosun', 'data-key': 'paused-bosun' },
      el('span', { text: 'or ask Bosun in its session (it is paused until you sign in):' }), K.command(entry.attach));
  }
  function loginBanner() {
    var spaces = App.data.spaces || {};
    var gone = Object.keys(spaces).filter(function (name) {
      var l = spaces[name].login;
      return l && l.state === 'expired';
    });
    if (!gone.length) return null;
    return el('div', { class: 'logins', 'data-key': 'login-banner' }, gone.map(function (name) {
      var l = spaces[name].login;
      var mine = installLogin(name, spaces);
      /* c-678: the install's own sign-in, in the first-run design's words; where another
         space signs in elsewhere (`login.only` false) only this space's sessions stopped */
      var said = mine && !l.never_logged_in ? 'Shipyard\'s Claude sign-in ran out, so no session ' + (l.only ? '' : 'of the ' + name + ' space ') + 'can run'
        : (l.never_logged_in ? 'The ' + name + ' space is not logged in' : 'The ' + name + ' login expired') + ', so its houses cannot run';
      var after = (mine && !l.never_logged_in ? 'They pick up where they stopped once you sign in' : 'They resume on their own once it works') +
        (l.at ? ' (probed ' + K.ago(l.at) + ')' : '') + '.';
      if (!K.signIn || !l.signin) return el('div', { class: 'waiting login', role: 'alert', 'data-key': 'login-' + name },
        el('span', { text: said + ': ' }), el('code', { class: 'fix', text: l.fix }), el('span', { text: '. ' + after }));
      return el('div', { class: 'waiting login', role: 'alert', 'data-key': 'login-' + name },
        el('span', { text: said + '. ' + after }),
        K.signIn.again({ key: 'banner-' + name, command: l.signin, space: name, watch: true,
          name: mine ? null : 'Claude sign-in for the ' + name + ' space',
          login: { state: l.state, why: l.why, stamp: l.stamp || null } }),
        mine ? pausedBosun() : null);
    }));
  }
  K.loginBanner = loginBanner;

  /* The install's own rows Now owns (c-631): what Keel needs to run, voice, the builder. */
  var NOW_NEEDS = ['prerequisites', 'voice', 'builder'];
  function viewNow() {
    var tiles = nowTiles();
    return [
      loginBanner(),
      K.needs(NOW_NEEDS, App.space, { title: 'Not set up' }),
      /* c-678: the drain stopped on an install, with Restart it (app/ui.stuckcard.js) */
      K.servicesStuck ? K.servicesStuck() : null,
      /* c-633: what the config loader did not take, with the way to Settings */
      K.configWarnings ? K.configWarnings() : null,
      statTiles(),
      el('section', { class: 'panel' }, el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'Now' })),
        el('div', { class: 'panel-body' }, tiles.length ? el('div', { class: 'strip' }, tiles)
          : el('div', { class: 'empty', text: 'no house is running in this space' }))),
      /* c-607: the live houses doing nothing, what they hold, and his way to close them */
      K.idlePanel ? K.idlePanel() : null,
      el('section', { class: 'panel', 'data-key': 'services-panel' },
        el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'Services' })),
        el('div', { class: 'panel-body' }, servicesBlock(K.health()))),
      el('section', { class: 'panel', 'data-key': 'logins-panel' },
        el('div', { class: 'panel-head' }, K.loginsLabel()),
        el('div', { class: 'panel-body' }, K.loginsBlock())),
      el('section', { class: 'panel' }, el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'At a glance' })),
        el('div', { class: 'panel-body' }, glanceRows()))
    ].filter(Boolean);
  }

  /* ---------- Attention ---------- */
  /* The age is how long he has been waited on: `derived.gate_since`, the event that opened
     the gate, the block or the notice (F5). It was `updated_at`, which a note, a set or a
     voice-hold release moves, so a gate two days open could read "2m". */
  function attentionRow(c) {
    var g = K.needKind(c);
    return el('button', { class: 'row k-' + (g || 'notice') + (App.card === c.id ? ' sel' : '') + (c.blocked_reason ? ' blocked' : ''),
      'data-key': c.id, onclick: function () { K.select(c.id); } },
      el('div', { class: 'row-head' }, el('span', { class: 'id', text: c.id }), K.keelChip(c), el('span', { class: 't ellip', text: c.title }),
        K.talkingPill(c), el('span', { class: 'age', text: K.ago(c.derived.gate_since || c.updated_at) })),
      el('div', { class: 'sub', text: K.needLine(c) }),
      el('div', { class: 'row-chips' }, K.pill(K.needWord(c), g === 'blocked' || g === 'notice' ? g : 'gate'),
        K.word(K.roundWord(c), 'round'), K.word(K.contractWord(c), 'contract')));
  }
  function attentionPane(c) {
    return el('div', { class: 'split-pane', 'data-key': 'attention-pane' },
      el('div', { class: 'drawer-head' },
        el('div', { class: 'drawer-title' }, el('h3', { class: 'title', text: c.title }), K.talkingPill(c),
          el('button', { class: 'iconbtn close', title: 'close the card', 'aria-label': 'close the card', onclick: K.closeDetail }, '✕')),
        el('div', { class: 'mono t11 ink2', text: c.id + (c.options.tracker_ref ? ' · ' + c.options.tracker_ref : '') + (c.topic ? ' · ' + c.topic : '') })),
      el('div', { class: 'actionbar' }, K.gateActions(c)),
      K.planBlock(c),
      K.gateEvidence(c),
      el('div', { class: 'actions' }, el('button', { class: 'btn sm', onclick: function () { K.go(K.cardRoute(c), c.id); } }, 'Open the card')));
  }
  function viewAttention() {
    var list = K.needsYou(), sel = App.card ? K.byId(App.card) : null;
    if (sel && sel.space !== App.space) sel = null;
    if (!K.isDesk() && sel) return K.phoneDetail(sel, 'attention');
    return [loginBanner(), el('section', { class: 'panel grow' },
      el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'Attention, ' + (list.length ? list.length + ' waiting on a tap' : 'nothing waiting') })),
      el('div', { class: 'panel-body' }, el('div', { class: 'split' },
        el('div', { class: 'split-list', 'data-key': 'attention-list' },
          list.length ? list.map(attentionRow) : el('div', { class: 'empty', text: 'no gate is open, nothing is blocked and no notice is open' })),
        K.isDesk() ? (sel && sel.derived.needs_you ? attentionPane(sel)
          : el('div', { class: 'split-pane center' }, el('span', { class: 'empty', text: list.length ? 'select an item' : 'all clear' }))) : null)))].filter(Boolean);
  }

  /* ---------- Segments ----------
   * The dashboard's segment card, on the deck's own summary documents. Over there each
   * card frames an iframe of the segment's own card.html; here the segment publishes
   * `summary.tiles`, so the deck draws the tiles itself. The chrome is the same either
   * way: a coloured dot, the name as a mono kicker in the segment's own accent, the
   * numbers as a hairline grid, and the segment's own words underneath. */

  /* THE CURATED ACCENTS, the same six the dashboard's providers.py carries, so the two
     surfaces agree on which colour a segment is. A segment nobody has curated rotates
     through the same six rather than falling back to grey (which reads as broken beside
     five coloured cards) or to a fresh hue (which breaks the "chosen to sit together"
     premise on the very next segment created). The rotation is a plain FNV-1a over the
     name rather than the md5 used server side: the only property either needs is that
     the same name always lands on the same colour. */
  var SEG_ACCENTS = {
    'cloud-spend': { ink: '#79D8A8', base: '#51B885' },
    oci:           { ink: '#79D8D3', base: '#51B8B3' },
    daybook:       { ink: '#81AADA', base: '#5181B8' },
    fathom:        { ink: '#9D90DF', base: '#6251B8' },
    voice:         { ink: '#C888DD', base: '#9E51B8' },
    instamart:     { ink: '#DA81B9', base: '#B85192' }
  };
  var SEG_ORDER = Object.keys(SEG_ACCENTS);
  function segAccent(name) {
    if (SEG_ACCENTS[name]) return SEG_ACCENTS[name];
    var h = 2166136261;
    for (var i = 0; i < name.length; i++) { h ^= name.charCodeAt(i); h = (h * 16777619) >>> 0; }
    return SEG_ACCENTS[SEG_ORDER[h % SEG_ORDER.length]];
  }
  function segmentTile(s) {
    var tiles = s.summary.tiles || [], a = segAccent(s.name);
    var notes = (s.summary.notes || []).slice(0, 2);
    return el('div', { class: 'seg', 'data-key': s.name, style: '--seg-ink:' + a.ink + ';--seg-base:' + a.base },
      el('div', { class: 'seg-head' },
        el('span', { class: 'seg-dot' }),
        el('span', { class: 'seg-name', title: s.name, text: s.name }),
        el('span', { class: 'seg-age', text: s.generated_at ? K.ago(s.generated_at) : '' }),
        s.has_app ? el('a', { class: 'seg-open', href: s.app_url, target: '_blank', rel: 'noopener', text: 'open \u2192' })
          : el('span', { class: 'seg-none', text: 'no app' })),
      /* installed and never fetched (c-742): the state's own words, never an absent card */
      tiles.length ? el('div', { class: 'stiles' }, tiles.map(function (t, i) {
        return el('div', { class: 'stile' + (i === 0 ? ' hero' : ''), 'data-key': t.label },
          el('div', { class: 'stile-l', title: t.label, text: t.label }),
          el('div', { class: 'stile-v', text: String(t.value) }));
      })) : s.fetched === false ? el('div', { class: 'empty', 'data-key': 'not-fetched', text: s.fetch_said || 'not fetched yet' })
        : el('div', { class: 'empty', text: 'no tiles' }),
      notes.length ? el('div', { class: 'seg-foot' }, notes.map(function (n) {
        return el('div', { class: 'seg-note', text: n });
      })) : null);
  }
  function viewSegments() {
    return el('section', { class: 'panel' },
      el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'Segments \u00b7 ' + App.data.segments.length })),
      el('div', { class: 'panel-body' }, App.data.segments.length ? el('div', { class: 'tiles' }, App.data.segments.map(segmentTile))
        : K.unmet(K.viewOf('segments').needs).length ? null : el('div', { class: 'empty', text: 'no segment has a summary' })));
  }

  /* ---------- More ---------- */
  /* More lists every view that declares needs and is not in the phone dock (c-631): Reviews
     while some space can file review cards (c-730), Segments until one is installed. One not
     set up says so on its row. */
  function viewMore() {
    var items = [], dock = K.dockKeys();
    K.VIEWS.filter(function (v) { return v.needs && v.needs.length && dock.indexOf(v.key) < 0 && K.listedView(v); }).forEach(function (v) {
      var n = K.counts()[v.key], off = K.unmet(v.needs).length > 0;
      items.push(el('button', { class: 'row', 'data-key': v.key, onclick: function () { K.go(v.key); } },
        el('div', { class: 'row-head' }, el('span', { class: 't', text: v.name }),
          off ? el('span', { class: 'spill', text: 'not set up' }) : n ? el('span', { class: 'badge', text: String(n) }) : null)));
    });
    /* No panel when nothing is listed: "this space has no extra routes" was the first thing
       More said on personal, above the Board (F3). */
    return [
      items.length ? el('section', { class: 'panel', 'data-key': 'routes' },
        el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'More' })),
        el('div', { class: 'panel-body' }, items)) : null,
      el('section', { class: 'panel' }, el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'Drain' })),
        el('div', { class: 'panel-body' },
          el('div', { class: 'mono t11 ink2', text: K.drainLine() + ' · ' + App.data.drain.text })))
    ];
  }

  K.viewNow = viewNow; K.viewAttention = viewAttention; K.viewSegments = viewSegments;
  K.viewMore = viewMore;
})(window.Keel);
