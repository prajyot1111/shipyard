/* The Bosun page (c-519, reshaped by c-591): `/console`, four sections, one visible at a time.
 *
 * `app/console.html` loads the deck's core (the element builder, the morph, the POST with
 * its cookie renewal, the toast, the state load and its stream) and this file, and NOT the
 * deck's boot or its Inspector: a card opens in the deck's own Inspector, on the deck
 * (`cardHref`). The shell is the deck's (a rail on the desk, a bottom tab bar on the phone),
 * and each section is a route of it:
 *
 *   /console          NOW: the session (status, context meter, Open in Claude app, Start,
 *                     Restart, Stop, the attach command), the batch in hand, and what needs
 *                     him: his plan gates on Bosun's attended cards, Bosun's open asks, and
 *                     held discussions (Bosun's blocked cards).
 *   /console/queue    Bosun's cards by state (waiting on him, doing, will do) and the intake
 *                     (the open and taken requests, each with Copy for chat).
 *   /console/shipped  what is on next and not live (the open deploy ask) with Deploy, the
 *                     last deploy's result, and what went live lately.
 *   /console/journal  cards done lately, the recurring gaps, and the session's feed.
 *
 * The page's cards are the ones Bosun builds (`derived.bosun`, `K.stateScope = 'bosun'`):
 * the console space, driving and strikes are retired (c-593). On every
 * stream tick it loads the state again (`ui.core.js`), since Bosun's status can arrive with
 * a push that writes nothing on the board.
 */
(function (K) {
  'use strict';

  var App = K.App, el = K.el;
  K.stateScope = 'bosun';
  /* The asks and the card links are `ui.console.asks.js`'s, loaded first. */
  var A = K.bosunAsks;
  var cardHref = A.cardHref, cardLink = A.cardLink, answerBody = A.answerBody, isDeploy = A.isDeploy,
    whoOf = A.whoOf, askCard = A.askCard, closedRow = A.closedRow;
  var SECTIONS = [
    { key: 'now', name: 'Now', icon: '◆' },
    { key: 'queue', name: 'Queue', icon: '▤' },
    { key: 'shipped', name: 'Shipped', icon: '▲' },
    { key: 'journal', name: 'Journal', icon: '≡' }
  ];
  /* The old tabs' names, so a link from before c-591 still lands somewhere that holds it. */
  var OLD_TABS = { needs: 'now', requests: 'queue', board: 'queue', journal: 'journal' };
  var DOING = ['planning', 'building', 'review', 'shipping'];
  var WILL = ['inbox', 'assigned'];

  App.view = 'console';

  /* A link from before c-591 that names a card (`?card=`) goes to the deck's Inspector: the
     page no longer draws one. */
  (function oldCardLink() {
    var id = new URLSearchParams(location.search).get('card');
    if (id && /^c-\d+$/.test(id) && location.replace) location.replace(cardHref(id));
  })();
  App.tab = sectionFromUrl();

  function sectionFromUrl() {
    var m = /^\/console\/([a-z]+)\/?$/.exec(location.pathname || '');
    if (m && SECTIONS.some(function (s) { return s.key === m[1]; })) return m[1];
    return OLD_TABS[new URLSearchParams(location.search).get('tab')] || 'now';
  }
  function pathOf(key) { return key === 'now' ? '/console' : '/console/' + key; }
  function go(key) {
    if (key === App.tab) return;
    App.tab = key;
    history.pushState(null, '', pathOf(key));
    render();
    if (window.scrollTo) window.scrollTo(0, 0);
  }
  window.addEventListener('popstate', function () { App.tab = sectionFromUrl(); render(); });

  /* Bosun's session with the board's half (`console`), or the board's half alone (`bosun`)
     when there is no console session: Shipped, the asks and the Journal never need one. */
  function bosun() {
    var d = App.data || {};
    return d.console || (d.bosun ? Object.assign({ state: 'away', context: {} }, d.bosun) : null);
  }
  function counts() { return (bosun() && bosun().counts) || {}; }
  /* Bosun's cards: the scope sends only those, and the flag is read again so a card the page
     holds for another reason is never counted as his. */
  function bosunCards() {
    return ((App.data && App.data.cards) || []).filter(function (c) {
      return c.derived.bosun && !c.derived.archived && !c.outside;
    });
  }

  /* ---------- the words the session says ---------- */
  function modelWord(b) {
    var m = String((b && b.model) || '');
    return m.replace(/^claude-/, '').replace(/-(\d+)-(\d+)$/, '-$1.$2');
  }
  function windowWord(n) {
    if (!n) return '';
    return n >= 1000000 ? (n / 1000000) + 'M' : Math.round(n / 1000) + 'K';
  }
  function statusWord(b) {
    var word = K.bosunWord(b);
    if (word === 'never') return 'never started';
    if (word === 'stuck') return 'stuck: listed with no process';
    if (word === 'voice') return 'on voice: back to Harbor or a tap ends it';
    return word;
  }
  function statusChip(b, phone) {
    var word = K.bosunWord(b);
    /* one machine never names itself (c-634, c-622) */
    var said = phone && word === 'voice' ? 'on voice' : statusWord(b);
    return el('span', { class: 'cstatus', role: 'status' },
      el('span', { class: 'dot b-' + word, 'aria-hidden': 'true' }), el('span', { text: said }));
  }
  /* The meter: context used against the window, with the compaction mark above it. */
  function meter(b) {
    var c = (b && b.context) || {};
    var pct = c.percent == null ? null : Math.max(0, Math.min(100, c.percent));
    var at = c.compact_at || 70;
    var said = pct == null ? 'context used: not known yet' : 'context used: ' + pct + '%, compacts at ' + at + '%';
    return el('div', { class: 'cmeter', role: 'img', 'aria-label': said },
      el('div', { class: 'cmeter-track' },
        el('span', { class: 'cmeter-mark', style: 'left:' + at + '%' },
          el('span', { class: 'cmeter-label', text: 'compacts at ' + at + '%' })),
        el('span', { class: 'cmeter-fill' + (pct != null && pct >= at ? ' over' : ''), style: 'width:' + (pct || 0) + '%' })),
      el('span', { class: 'cmeter-pct', text: pct == null ? '-' : pct + '%' }));
  }
  function said(r) { return r && r.note ? r.note : 'done'; }
  function appLink(b) {
    var link = b && b.up && b.app_link;
    return link
      ? el('a', { class: 'btn primary copen', href: link, target: '_blank', rel: 'noopener' },
        'Open in Claude app ', el('span', { 'aria-hidden': 'true', text: '↗' }))
      : el('button', { class: 'btn primary copen', disabled: true,
        title: 'Bosun is not running, so there is no app link' }, 'Open in Claude app');
  }
  function taps(b) {
    var up = b && b.up;
    var first = up
      ? K.actionBtn('Restart', { verb: 'console.restart' }, { cls: 'cbtn', done: said,
        title: 'stop it and start a fresh session from its memory',
        confirm: 'Restart Bosun? Its conversation ends and a fresh one starts from its memory.' })
      : K.actionBtn('Start', { verb: 'console.start' }, { cls: 'cbtn', done: said,
        title: b && b.state === 'stuck' ? 'its session is listed with no process: bring it back (resumed if it can be stopped, else fresh)'
          : b && b.session_id ? 'resume its last conversation' : 'start it for the first time' });
    var stop = up
      ? K.actionBtn('Stop', { verb: 'console.stop' }, { cls: 'cbtn stop', done: said,
        title: 'stop it; Start picks the conversation up again' })
      : el('button', { class: 'btn cbtn stop', disabled: true, title: 'Bosun is not running' }, 'Stop');
    return [first, stop];
  }
  function facts(b) {
    return [modelWord(b), windowWord(b.context && b.context.window),
      b.up_since ? 'up ' + K.ago(b.up_since) : '',
      b.last_turn ? 'last turn ' + K.ago(b.last_turn) : ''].filter(Boolean).join(' · ');
  }
  /* Which builder it is: the builder in auto mode or in bypass ([builder] mode), or the
     box's superuser. Nothing when builder mode is off. */
  function modeLine(b) {
    var m = b && b.builder;
    if (!m) return null;
    return el('div', { class: 'cmode t11' },
      el('span', { class: 'pill' + (m.label !== 'Builder, auto mode' ? ' warn' : ''), text: m.label }),
      m.repos ? el('span', { class: 'ink3', text: ' · builds ' + m.repos.join(', ') }) : null);
  }
  /* The attach line is the state's (`console.attach`, keel/deckstate.py): this install's own
     `bin/keel console attach`, run in a terminal here (c-634). */
  function sessionPanel(b) {
    var attach = b.attach || 'bin/keel console attach';
    return el('section', { class: 'panel csession', 'aria-label': 'Bosun\'s session' },
      el('div', { class: 'panel-body' },
        el('div', { class: 'csession-top' }, statusChip(b), el('span', { class: 'mono t11 ink2 cfact', text: facts(b) })),
        modeLine(b),
        meter(b),
        el('div', { class: 'ctaps' }, appLink(b), taps(b)),
        el('div', { class: 'lfix cattach' }, el('code', { class: 'fix', text: attach }), K.copyButton(attach)),
        el('div', { class: 't11 ink3', text: 'Run this in a terminal to join the same session.' })));
  }

  /* ---------- the shell: the rail, the header, the bar ---------- */
  function needsOf(b) {
    var cards = bosunCards();
    var plans = cards.filter(function (c) { return c.derived.plan_gate; });
    var asks = ((b && b.asks) || []).filter(function (a) { return a.state === 'open' && !isDeploy(a); });
    /* a held card Bosun has asked about shows once, as the ask */
    var asked = asks.map(function (a) { return a.card; });
    var held = cards.filter(function (c) {
      return c.blocked_reason && !c.derived.plan_gate && asked.indexOf(c.id) < 0;
    });
    return { plans: plans, held: held, asks: asks, n: plans.length + held.length + asks.length };
  }
  function pendingDeploy(b) { return (b && b.shipped && b.shipped.pending) || null; }
  function countOf(key, b) {
    if (key === 'now') return needsOf(b).n;
    if (key === 'queue') return counts().requests || 0;
    if (key === 'shipped') { var p = pendingDeploy(b); return p ? Math.max(1, p.cards.length) : 0; }
    return 0;
  }
  /* Now and Shipped count what waits on him (red); Queue counts the open requests (grey). */
  function needy(key) { return key === 'now' || key === 'shipped'; }
  function railOf(b) {
    return [
      el('div', { class: 'rail-brand' }, el('span', { class: 'bmark', 'aria-hidden': 'true' }), el('span', { text: 'Bosun' })),
      el('div', { class: 'rail-nav' }, SECTIONS.map(function (s) {
        var n = countOf(s.key, b), on = App.tab === s.key;
        return el('button', { class: 'rail-item' + (on ? ' on' : ''), 'aria-current': on ? 'page' : null,
          onclick: function () { go(s.key); } },
          el('span', { class: 'name', text: s.name }),
          n ? el('span', { class: 'badge' + (needy(s.key) ? ' need' : ''), text: String(n) }) : null);
      })),
      el('a', { class: 'rail-item cdeck', href: '/' }, el('span', { class: 'name', text: '‹ Back to the deck' })),
      el('div', { class: 'rail-foot', text: App.data.drain ? K.drainLine() : '' })
    ];
  }
  function dockOf(b) {
    return SECTIONS.map(function (s) {
      var n = countOf(s.key, b), on = App.tab === s.key;
      return el('button', { class: 'dock-item' + (on ? ' on' : ''),
        'aria-label': s.name + (n ? ', ' + n + (needy(s.key) ? ' need you' : ' open') : ''),
        'aria-current': on ? 'page' : null, onclick: function () { go(s.key); } },
        el('span', { class: 'ic', 'aria-hidden': 'true' }, s.icon,
          n ? el('span', { class: 'dock-badge' + (needy(s.key) ? '' : ' grey'), text: String(n) }) : null),
        el('span', { class: 'name', 'aria-hidden': 'true', text: s.name }));
    });
  }
  function headerOf(b, desk) {
    var s = SECTIONS.filter(function (x) { return x.key === App.tab; })[0];
    if (desk) {
      return [el('h1', { text: s.name }), el('span', { class: 'spacer' }), statusChip(b)];
    }
    return [
      el('a', { class: 'iconbtn cback', href: '/', 'aria-label': 'back to the deck', title: 'back to the deck' }, '‹'),
      el('span', { class: 'bmark', 'aria-hidden': 'true' }),
      el('h1', { text: 'Bosun' }), el('span', { class: 'hint', text: s.name }),
      el('span', { class: 'spacer' }), statusChip(b, true)
    ];
  }

  /* ---------- small parts ---------- */
  function lead(label, line) {
    return el('div', { class: 'clead' }, el('div', { class: 'label', text: label }),
      line ? el('div', { class: 'ink2 t13', text: line }) : null);
  }
  function empty(text) { return el('div', { class: 'cempty', text: text }); }
  function firstLine(text) { return String(text || '').split('\n')[0]; }
  /* A card of Bosun's as one row: its id, its title, a pill for where it stands, and what
     the row is for underneath. The whole row opens the card in the deck's Inspector. */
  function cardRow(c, pill, line, cls) {
    return el('a', { class: 'crow' + (cls ? ' ' + cls : ''), href: cardHref(c.id), 'data-key': c.id },
      el('div', { class: 'crow-head' },
        el('span', { class: 'mono t11 ink2', text: c.id }),
        el('span', { class: 'crow-title', text: c.title }),
        pill ? el('span', { class: 'pill cpill' + (cls === 'need' ? ' need' : ''), text: pill }) : null),
      line ? el('div', { class: 't11 ink2 crow-line', text: line }) : null);
  }
  function batchOf(c) { return (c.options || {}).bosun || {}; }

  /* ---------- NOW ---------- */
  /* The batch in hand: Bosun's cards it is building, grouped by the batch `options.bosun`
     names, each with its branch (bosun/memory/builder.md). */
  function batchPanel() {
    /* at a plan gate or held, a card is waiting on him, not in hand */
    var doing = bosunCards().filter(function (c) {
      return DOING.indexOf(K.stageOf(c)) >= 0 && !c.derived.plan_gate && !c.blocked_reason;
    });
    var batches = {}, order = [];
    doing.forEach(function (c) {
      var name = batchOf(c).batch || '';
      if (!(name in batches)) { batches[name] = []; order.push(name); }
      batches[name].push(c);
    });
    return el('section', { class: 'panel', 'data-key': 'batch' },
      el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'The batch in hand' }),
        el('span', { class: 'ink2 t11', text: doing.length ? doing.length + (doing.length === 1 ? ' card' : ' cards') : '' })),
      el('div', { class: 'panel-body' }, doing.length ? order.map(function (name) {
        return el('div', { class: 'cbatch' },
          el('div', { class: 'mono t11 ink2', text: name ? 'batch ' + name : 'no batch named yet' }),
          batches[name].map(function (c) {
            return cardRow(c, K.stageOf(c), batchOf(c).branch || 'no branch yet');
          }));
      }) : empty('Nothing in hand. Bosun takes its next batch from the Queue.')));
  }
  function needsPanel(b) {
    var needs = needsOf(b);
    var rows = [];
    needs.plans.forEach(function (c) { rows.push(cardRow(c, 'plan gate', 'waiting for your plan approval', 'need')); });
    needs.asks.forEach(function (a) { rows.push(askCard(a)); });
    needs.held.forEach(function (c) {
      rows.push(cardRow(c, 'held', firstLine(c.blocked_reason), 'need'));
    });
    return [lead('Needs you', needs.n ? needs.n + ' waiting · your plan gates, Bosun\'s asks, and what it holds to discuss'
        : 'answer by tap, voice, or in the chat; every answer is recorded'),
      needs.n ? rows : empty('Nothing needs you. A plan gate on an attended card, a question from Bosun, or a card it holds to discuss arrives here.')];
  }
  function answeredFold(b) {
    var closed = ((b && b.asks) || []).filter(function (a) { return a.state !== 'open'; });
    return closed.length ? el('details', { class: 'cfolded' },
      el('summary', { class: 't13 ink2', text: 'Answered in the last day (' + closed.length + '); older ones are in the Journal' }),
      closed.map(closedRow)) : null;
  }
  /* The Logins list (c-558), the same rows the deck's health sheet draws. */
  function loginsPanel() {
    return el('section', { class: 'panel clogins', 'data-key': 'logins-panel' },
      el('div', { class: 'panel-head' }, K.loginsLabel()),
      el('div', { class: 'panel-body' }, K.loginsBlock()));
  }
  function nowSection(b) {
    return el('div', { class: 'cgrid' },
      el('div', { class: 'cmain' }, needsPanel(b), answeredFold(b), loginsPanel()),
      /* on the phone this column comes first: the session, then the batch, then what needs him */
      el('div', { class: 'cside' }, sessionPanel(b), batchPanel()));
  }

  /* ---------- QUEUE ---------- */
  function queueGroup(label, line, cards, rowOf) {
    return el('section', { class: 'panel', 'data-key': 'q-' + label },
      el('div', { class: 'panel-head' }, el('span', { class: 'label', text: label }),
        el('span', { class: 'badge', text: String(cards.length) }), el('span', { class: 'ink2 t11', text: line })),
      el('div', { class: 'panel-body' }, cards.length ? cards.map(rowOf) : el('div', { class: 'ink3 mono t11', text: 'none' })));
  }
  function waitingLine(c) {
    if (c.derived.plan_gate) return 'your plan gate';
    if (c.derived.ask) return 'Bosun asks: ' + c.derived.ask.question;
    if (c.blocked_reason) return (/^held\b/i.test(c.blocked_reason) ? '' : 'held: ') + firstLine(c.blocked_reason);
    if (c.derived.outcome_gate) return 'your outcome gate';
    return 'needs you';
  }
  function doingLine(c) {
    var o = batchOf(c);
    return [o.batch ? 'batch ' + o.batch : '', o.branch || ''].filter(Boolean).join(' · ') || 'no batch named yet';
  }
  function copyBtn(text) {
    var btn = el('button', { class: 'btn ccopy', title: 'put "' + text + '" on the clipboard, to paste to Bosun', onclick: function () {
      var done = function () { btn.textContent = 'Copied'; setTimeout(function () { btn.textContent = 'Copy for chat'; }, 1400); };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, function () { K.toast('copy it by hand: ' + text); });
      else K.toast('copy it by hand: ' + text);
    } }, 'Copy for chat');
    return btn;
  }
  function requestRow(r) {
    var seen = r.key && r.seen > 1 ? el('span', { class: 'mono t11 ink3', text: 'seen ' + r.seen + ' times' }) : null;
    return el('article', { class: 'creq' + (r.state === 'taken' ? ' taken' : ''), 'data-key': r.id },
      el('div', { class: 'creq-head' },
        el('span', { class: 'pill cstate' + (r.state === 'taken' ? ' on' : ''), text: r.state }),
        el('span', { class: 'mono t11 ink2', text: r.id }), r.card ? cardLink(r.card) : null,
        el('span', { class: 'mono t11 ink3', text: 'from ' + whoOf(r.actor) }), seen,
        el('span', { class: 'spacer' }),
        el('span', { class: 'mono t11 ink3', text: K.ago(r.created_at) })),
      el('div', { class: 'creq-what', text: r.what }),
      r.detail ? el('details', { class: 'creq-detail' }, el('summary', { class: 't11 ink2', text: 'detail' }),
        el('pre', { class: 'mono t11', text: r.detail })) : null,
      r.state === 'open' ? el('div', { class: 'creq-foot' }, copyBtn('take ' + r.id),
        el('span', { class: 't11 ink3', text: 'Bosun acts on it once you say take ' + r.id }))
        : el('div', { class: 'creq-foot t11 ink2', text: 'Taken by ' + whoOf(r.taken_by) + '; it ends fixed, filed, declined or escalated' }));
  }
  function intake(b) {
    var rows = (b && b.requests) || [];
    var n = counts().requests || 0, taken = rows.length - n;
    return [lead('Intake', n + ' open' + (taken ? ', ' + taken + ' taken' : '') + ' · requests not yet cards; Bosun acts on one only when you say take it'),
      rows.length ? rows.map(requestRow)
        : empty('No open requests. A house, the drain or Harbor files one when Shipyard gets in its own way.')];
  }
  function queueSection(b) {
    var cards = bosunCards();
    var waiting = cards.filter(function (c) { return c.derived.needs_you && K.stageOf(c) !== 'done'; });
    var doing = cards.filter(function (c) { return !c.derived.needs_you && DOING.indexOf(K.stageOf(c)) >= 0; });
    var will = cards.filter(function (c) { return !c.derived.needs_you && WILL.indexOf(K.stageOf(c)) >= 0; });
    return el('div', { class: 'cgrid' },
      el('div', { class: 'cmain' },
        lead('Bosun\'s cards', 'the personal cards with a repo: Bosun builds them, the drain never starts a house on one'),
        queueGroup('Waiting on you', 'plan gates, asks, held', waiting, function (c) { return cardRow(c, K.stageOf(c), waitingLine(c), 'need'); }),
        queueGroup('Doing', 'with its batch and branch', doing, function (c) { return cardRow(c, K.stageOf(c), doingLine(c)); }),
        queueGroup('Will do', 'assigned, in the order Bosun takes them', will, function (c) { return cardRow(c, K.stageOf(c), null); })),
      el('div', { class: 'cmain' }, intake(b)));
  }

  /* ---------- SHIPPED ---------- */
  function shippedCard(id) {
    var c = K.byId(id);
    return c ? cardRow(c, null, null) : el('a', { class: 'crow', href: cardHref(id), 'data-key': id },
      el('div', { class: 'crow-head' }, el('span', { class: 'mono t11 ink2', text: id })));
  }
  function deployButton(b, p) {
    var ask = ((b && b.asks) || []).filter(function (a) { return a.id === p.ask; })[0];
    var yes = ask && ask.options && ask.options[0];
    return el('button', { class: 'btn primary cdeploy', 'data-key': 'deploy-' + p.ask, onclick: function (ev) {
      var msg = 'Deploy ' + (p.target || 'the landing branch') + ' at ' + String(p.sha || '').slice(0, 8) + ' to ' + (p.trunk || 'the trunk') + '?' +
        (yes && yes.does ? '\n\nShipyard does: ' + yes.does : '');
      if (!window.confirm(msg)) return;
      /* review F3: 'now' only when a drain heard the kick (`kick` in kb's payload) */
      K.act(answerBody({ id: p.ask }, { choice: 'A' }), function (r) {
        var heard = r && r.kick === 'kicked';
        return 'answered ' + p.ask + (heard ? '; the deploy starts now' : '; waiting for the drain to start it') +
          ', and ' + (p.trunk || 'the trunk') + ' moves only if the suite is green';
      }, ev.currentTarget);
    } }, 'Deploy');
  }
  /* c-636: each phase a deploy passes, as the ask's own record says it (deployask.steps_of).
   * 'starting' is his Yes that no worker has taken yet: true from the instant he taps, and
   * 'waiting for the drain' once that has lasted two drain polls; 'started' is a worker's.
   * A deploy of Keel itself whose deck was not seen on the new code says so (deck false). */
  var PHASE_WORD = { starting: 'starting', start: 'started', merge: 'building', suite: 'testing',
    live: 'going live', deploying: 'deploying', deployed: 'deployed', running: 'live everywhere',
    refused: 'not deployed' };
  function phaseWord(s) {
    if (s.waiting) return 'waiting for the drain';
    if (s.move === 'deployed' && s.deck === false) return 'deployed, deck not restarted';
    return PHASE_WORD[s.phase] || PHASE_WORD[s.move] || s.phase || s.move;
  }
  function deploySteps(steps) {
    if (!steps || steps.length < 2) return null;
    return el('div', { class: 'cship-steps' }, steps.map(function (s) {
      return el('div', { class: 'cship-step' },
        el('span', { class: 'mono t11 ink3', text: s.at ? K.clock(s.at) : '' }),
        el('span', { class: 'mono t11 ink2', text: phaseWord(s) }),
        el('span', { class: 't11 ink2 cship-text', text: s.text || '' }));
    }));
  }
  function lastDeploy(last) {
    if (!last) return empty('No deploy yet on this board.');
    var r = last.result || {};
    var tone = r.move === 'refused' ? ' crit' :
      (r.move === 'deploying' || r.move === 'starting' || r.deck === false) ? ' warn' : ' good';
    return el('div', { class: 'cship-last' },
      el('div', { class: 'creq-head' },
        el('span', { class: 'pill cresult' + tone, text: phaseWord(r) }),
        el('span', { class: 'mono t11 ink2', text: String(r.sha || last.sha || '').slice(0, 8) }),
        el('span', { class: 'mono t11 ink3', text: last.ask }), el('span', { class: 'spacer' }),
        r.at ? el('span', { class: 'mono t11 ink3', text: K.clock(r.at) + ' · ' + K.ago(r.at) }) : null),
      r.text ? el('div', { class: 't13 ink2 cship-text', text: r.text }) : null,
      deploySteps(r.steps));
  }
  function shippedSection(b) {
    var s = (b && b.shipped) || {}, p = s.pending;
    /* The two branch names are the deploy ask's own (`deployask.brief_of`: `target`, the
       landing branch, and `trunk`), read off the open ask, else the last deploy, else one
       that went live; with none to read, the page says it without a name (c-665). */
    var named = [p, s.last].concat(s.live || []).filter(function (d) { return d && d.target; })[0] || {};
    var target = named.target || 'the landing branch', trunk = named.trunk || 'the trunk';
    var pending = el('section', { class: 'panel' + (p ? ' cship-open' : ''), 'data-key': 'ship-pending' },
      el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'On ' + target + ', not live' }),
        p ? el('span', { class: 'mono t11 ink2', text: (p.target ? p.target + ' at ' : 'at ') + String(p.sha || '').slice(0, 8) }) : null),
      el('div', { class: 'panel-body' }, p ? [
        p.cards.length ? p.cards.map(shippedCard) : el('div', { class: 't13 ink2', text: 'No card merges: only commits of your own.' }),
        el('div', { class: 'cship-go' }, deployButton(b, p),
          el('span', { class: 't11 ink2', text: trunk + ' moves only on this Yes; the suite runs first unless a landing already ran this tree green' }))
      ] : empty('Nothing waiting: ' + target + ' is at ' + trunk + ', or the drain has not asked yet.')));
    return el('div', { class: 'cgrid' },
      el('div', { class: 'cmain' }, lead('Shipped', 'what Bosun landed on ' + target + ', and what went live'), pending,
        el('section', { class: 'panel', 'data-key': 'ship-last' },
          el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'The last deploy' })),
          el('div', { class: 'panel-body' }, lastDeploy(s.last)))),
      el('div', { class: 'cmain' },
        el('section', { class: 'panel', 'data-key': 'ship-live' },
          el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'Recently live' })),
          el('div', { class: 'panel-body' }, (s.live || []).length ? s.live.map(function (d) {
            return el('div', { class: 'cbatch' },
              el('div', { class: 'mono t11 ink2', text: String(d.sha || '').slice(0, 8) + (d.result && d.result.at ? ' · ' + K.ago(d.result.at) : '') }),
              d.cards.length ? d.cards.map(shippedCard) : el('div', { class: 't11 ink3', text: 'no card merges' }));
          }) : empty('Nothing has gone live lately.')))));
  }

  /* ---------- JOURNAL (c-524) ---------- */
  function journalRows(b) {
    var taps = ((b && b.history) || []).map(function (r) {
      return { at: r.at, what: r.what, by: r.by, session: r.session };
    });
    var moves = ((b && b.journal) || []).map(function (e) {
      if (/^a-/.test(e.card)) return { at: e.at, what: e.card + ' ' + (e.text || e.move), by: whoOf(e.actor) };
      var what = e.card + ' ' + (e.move || 'moved') + (e.move === 'taken' ? '' : ': ' + (e.text || ''));
      return { at: e.at, what: what, by: whoOf(e.actor), gap: e.gap };
    });
    return taps.concat(moves).sort(function (x, y) { return Date.parse(y.at) - Date.parse(x.at); });
  }
  /* Cards done lately, by space: the two he works in (the console space is c-593's to remove). */
  var THROUGH = [['personal', 'Personal'], ['work', 'Work']];
  function throughTiles(t) {
    if (!t || !t.done) return null;
    return el('div', { class: 'cthrough' }, THROUGH.filter(function (s) { return s[0] in t.done; }).map(function (s) {
      return el('div', { class: 'stat' },
        el('span', { class: 'n', text: String(t.done[s[0]]) }),
        el('span', { class: 'l', text: s[1] }),
        el('span', { class: 's mono', text: 'done' }));
    }));
  }
  var HOWS = ['fixed', 'filed', 'declined', 'escalated'];
  function gapRow(g) {
    var hows = HOWS.filter(function (h) { return (g.hows || {})[h]; }).map(function (h) { return g.hows[h] + ' ' + h; });
    return el('div', { class: 'cgaprow' },
      el('span', { class: 'pill cgap mono t11', text: g.gap }),
      g.recurring ? el('span', { class: 'pill warn mono t11', text: 'recurring' }) : null,
      el('span', { class: 'cgapn t13', text: g.count + (g.count === 1 ? ' request' : ' requests') }),
      el('span', { class: 'ink2 t11 cgaphow', text: hows.join(', ') + (g.last ? ' · last ' + K.ago(g.last) : '') }),
      el('span', { class: 'mono t11 ink3', text: (g.requests || []).join(' ') }));
  }
  function gapsPanel(gaps) {
    if (!gaps || !gaps.length) return null;
    var again = gaps.filter(function (g) { return g.recurring; });
    var once = gaps.filter(function (g) { return !g.recurring; });
    return el('div', { class: 'panel' },
      el('div', { class: 'panel-head' }, el('span', { class: 'label', text: 'Recurring gaps' }),
        el('span', { class: 'ink2 t11', text: again.length ? 'the gaps Shipyard keeps hitting, most requests first' : 'none twice yet' })),
      el('div', { class: 'panel-body' }, again.map(gapRow),
        once.length ? el('details', { class: 'cfolded' },
          el('summary', { class: 't13 ink2', text: 'Seen once (' + once.length + ')' }), once.map(gapRow)) : null));
  }
  function journalSection(b) {
    var rows = journalRows(b), t = b && b.throughput;
    return el('div', { class: 'cmain' },
      lead('Journal', 'Bosun\'s session, its requests and its asks, newest first; each request\'s ending carries its gap tag.'),
      t ? el('div', { class: 'label', text: 'Done in the last ' + t.days + ' days' }) : null,
      throughTiles(t),
      gapsPanel(b && b.gaps),
      rows.length ? el('div', { class: 'panel' }, el('div', { class: 'panel-body' }, rows.map(function (r) {
        return el('div', { class: 'cjournal' },
          el('span', { class: 'mono t11 ink2 cjat', text: K.clock(r.at) + ' · ' + K.ago(r.at) }),
          el('span', { class: 'cjwhat', text: r.what }),
          r.gap ? el('span', { class: 'pill cgap mono t11', text: r.gap }) : null,
          el('span', { class: 'mono t11 ink3', text: 'by ' + r.by }),
          r.session ? el('span', { class: 'mono t11 ink3', text: String(r.session).slice(0, 8) }) : null);
      }))) : empty('Nothing yet: Bosun has not been started, and no request has been filed.'));
  }
  function sectionBody(b) {
    if (App.tab === 'queue') return queueSection(b);
    if (App.tab === 'shipped') return shippedSection(b);
    if (App.tab === 'journal') return journalSection(b);
    return nowSection(b);
  }

  var scrolled = false;
  function render() {
    if (!App.data) return;
    var b = bosun() || { state: 'away', context: {} };
    var desk = K.isDesk();
    if (desk) K.paint('rail', railOf(b));
    K.paint('header', headerOf(b, desk));
    K.paint('body', [el('div', { class: 'cbody', 'data-section': App.tab }, sectionBody(b))]);
    if (!desk) K.paint('dock', dockOf(b));
    if (App.sheet) K.renderSheet();
    var n = needsOf(b).n;
    var s = SECTIONS.filter(function (x) { return x.key === App.tab; })[0];
    document.title = (n ? '(' + n + ') ' : '') + 'Bosun' + (App.tab === 'now' ? '' : ' · ' + s.name);
    K.followScope();
    /* An "Answer Bosun" link (`/console#a-N`) lands on the ask once it is drawn. */
    if (!scrolled && location.hash && document.getElementById) {
      scrolled = true;
      var at = document.getElementById(location.hash.slice(1));
      if (at && at.scrollIntoView) at.scrollIntoView({ block: 'start' });
    }
  }
  K.render = render; K.renderBody = render;
  /* the deck's chrome is drawn here by this page; the calls that reach for the deck's own are no-ops */
  K.renderRail = K.renderHeader = K.renderControls = K.renderDock = function () {};
  K.markStrips = K.markStrips || function () {};

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') { K.openStream(); K.load(); }
    else K.closeStream();
  });
  window.addEventListener('resize', function () { clearTimeout(App.resizeTimer); App.resizeTimer = setTimeout(render, 140); });
  /* The fallback while the stream is shut, as the deck's own (`ui.js`). */
  function poll() {
    clearInterval(App.timer);
    App.timer = setInterval(function () {
      if (document.visibilityState !== 'visible' || K.streamOpen()) return;
      K.load();
    }, K.POLL_MS);
  }
  K.load().then(function () { poll(); K.openStream(); });
})(window.Keel);
