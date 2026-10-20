/* Cards: the list, the kanban, and the card detail (the inspector).
 *
 * The list honours the Work | Personal switch in every layout and is found through the
 * page's find bar (app/ui.find.js, the table in app/ui.findpages.js): the search with typed
 * filters, the facets, Include done, backlog and archived, the sort, and the View menu's
 * layout and grouping (none, stage, topic, parent, repo). The detail opens beside the list
 * on the desk and as a route on the phone; it can always be closed (the ✕, Escape, or a
 * click outside it), and closing walks history back to the list.
 *
 * A card's live state is said in THREE WORDS (house, plan, outcome), one function each,
 * below. They are the single place those rules live: the table, the kanban tile, the
 * phone list, the inspector's head, the slice list and Now all read the same three
 * functions, so the page cannot say two different things about one card.
 *
 * The inspector puts every action in ONE sticky row under the title, in groups (Decide,
 * Continue, Talk to it, Pages, Links, the flow's own, Card; the table is ui.tips.js, c-644),
 * each a split button whose caret, named for its group, opens the rest with a line under
 * every name; then the evidence, the details,
 * the house notes and the events. A button that cannot act is not drawn at all. A card that is not done and has
 * no children can be Split into slices; a tracking card lists its slices instead of a gate,
 * and a slice links back to the card it was cut from. */
(function (K) {
  'use strict';

  var el = K.el, add = K.add, App = K.App, STAGES = K.STAGES;

  /* ---------- finding (app/ui.find.js) ----------
   * The list is the space's cards run through the page's find table (`K.findPages.cards`):
   * the search (typed filters included), the facets, the Include switches and the sort.
   * Done, backlog and archived cards are out of the list until their Include switch is on,
   * which ADDS them to it; nothing on this page swaps one list for another any more.
   * A review card is never here, in any layout, count or facet (2026-09-24): Reviews is its
   * one list, and Attention carries it only at his gate, as it does any card. */
  /* c-592: a Keel card his board does not show (`derived.keel_card.shown`: one Bosun filed
     that does not need him, or one gone live) lives on the Bosun page; a link to it still
     opens it here, since the pane reads the whole board. One he filed that went live comes
     back with Include done, as a done card of his. */
  function onHisBoard(c) {
    var k = keelOf(c);
    return !k || k.shown !== false || (k.filed_by !== 'bosun' && K.stageOf(c) === 'done' && showsDone());
  }
  function spaceCards() {
    return K.cards().filter(function (c) { return K.inSpace(c) && !K.isReview(c) && onHisBoard(c); }).slice().reverse();
  }
  function findCards() { return K.find.run('cards', spaceCards()); }
  function showsDone() { return K.find.state('cards').inc.indexOf('done') >= 0; }
  /* sorted by the drain's queue, a queued card says its place in it */
  /* a Keel card is Bosun's queue, not the drain's (c-592), so it carries no place in this one */
  function queueNumber(c) { return K.find.state('cards').sort === 'queue' && !keelOf(c) ? K.queuePos(c) : 0; }

  /* ---------- the three words ----------
   * What the six stage dots and the house dot never said: where the card actually is.
   * Each function answers one question in one or two words and carries the colour that
   * word means (the palette's rule: `acc` waits on you or is live here, `warn` runs
   * elsewhere or has gone quiet, `crit` is broken, `good` has landed, `plain` is a fact
   * that is neither). Everything is derived from the state document the page already has.
   *
   * A question with NOTHING TO ANSWER returns null rather than the word "none", and
   * `word` and `wordsOf` drop it. An inbox card has no house, no plan and no outcome, so
   * under its title it used to print `none none none`: three words saying only that the
   * card had not started, on every row, tile, Now line and pane. Nothing is nothing now,
   * one answer left is that answer on its own, and a card with none of the three draws no
   * words line at all. */
  function daysSince(iso) {
    var base = App.data && App.data.now ? new Date(App.data.now).getTime() : Date.now();
    return Math.max(0, Math.round((base - new Date(iso).getTime()) / 86400000));
  }
  function tracking(c) { return !!(c.children && c.children.length); }

  /* house: is anything of yours running on this card, and is it yours to answer?
     blocked first (it is the loudest fact), then a discussion (you are in it), then the
     agents row: busy is working, a listed but quiet row is idle, no row at all is silence. */
  function houseWord(c) {
    /* While a gate answer, a Resume or a Retry is bridging, that is the truest thing the
       house column can say: the board still reads idle (or blocked) for a poll or two. */
    var bridging = K.bridgeWord(c);
    if (bridging) return { text: bridging, cls: 'acc bridge' };
    /* A tap on this deck for a house on another machine, waiting for that machine's drain. */
    var relay = (c.derived.relays || [])[0];
    if (relay) return { text: relay.what + ' asked of ' + relay.to, cls: 'warn' };
    if (c.blocked_reason) return { text: 'blocked', cls: 'crit' };
    /* c-605: he stopped it, and the drain leaves it down until his Resume (derived.held_by_stop) */
    if (c.derived.held_by_stop && !c.house) return { text: 'stopped by you: waiting for your Resume', cls: 'warn tally' };
    /* c-607: he closed it while it was idle; its next batch or his tap brings it back */
    if (c.derived.closed_idle && !K.houseOf(c)) return { text: K.closedSaid ? K.closedSaid(c) : 'closed while idle', cls: 'plain tally' };
    /* Nothing awake can start or carry this card (keel/where.py): its drain is away, or this
       install lacks its repo. The pane's facts carry the whole line. */
    var waits = waitingOf(c);
    if (waits) return { text: waits.indexOf('Cannot start') === 0 ? 'cannot start' : waits.split(':')[0].toLowerCase(), cls: 'warn' };
    /* the card does not say which branch moved (`options.merging` is `true`), so none is named (c-665) */
    if (c.options && c.options.merging) return { text: 'merging its target', cls: 'warn' };
    if (rotatingOf(c)) return { text: 'rotating', cls: 'acc' };
    if (K.talking(c)) return { text: 'talking', cls: 'acc' };
    /* c-599: the harness asked him something (a Notification that is not the idle prompt,
       from this turn, with nothing written after it): said the moment the hook lands, not
       when the drain blocks the card */
    if (K.prompting && K.prompting(c)) return { text: 'waiting on a prompt', cls: 'acc' };
    /* Out of its turn, but a background job of its own is still running (keel/housejobs.py):
       it is waiting on that job, not working. The harness lists such a session as busy, so
       this comes before the busy word: c-526 read "working" for thirty minutes behind a wait
       loop that could never end. */
    if (c.house && c.jobs && c.jobs.length) return { text: 'idle · job running', cls: 'warn tally' };
    if (K.houseBusy(c)) return { text: 'working', cls: 'acc' };
    /* A house the account's limit stopped mid-turn: listed, idle, its turn ended with no
       Stop. The card still reads `building`, so a bare "idle" looked like a pause in the
       work while three of them held the whole pool doing nothing (2026-09-20). Say how long,
       and when the drain puts it back, from the drain's own answer (keel/drain.py).
       `tally` because this is two facts rather than a word: nowrap clipped it to
       "idle 30m · blocking in 5" in the table's house column (measured, not guessed). */
    if (c.idle) return { text: idleWord(c.idle), cls: 'warn tally' };
    if (c.house) return { text: 'idle', cls: 'warn' };
    return null;
  }
  function rotateOn() { return !!(App.data && App.data.config && App.data.config.rotate); }
  function rotatingOf(c) { return !!(c.options && c.options.rotate && c.options.rotate.state === 'checkpointing'); }
  function idleWord(idle) {
    return 'idle ' + K.ago(idle.since) + ' · '
      + (idle.blocking ? 'blocking ' : 'resume ') + K.until(idle.next_at);
  }

  function waitingOf(c) { return ((App.data && App.data.waiting) || {})[c.id] || null; }

  /* The newest `approve` event for the plan gate, when this card's events are loaded (the
     inspector asks for them); the list document carries only the last event, so everywhere
     else the stage is the answer, which is what moving past planning means. */
  function planApproved(c) {
    var d = App.detailFor === c.id ? App.detail : null;
    if (!d) return false;
    return d.events.some(function (e) { return e.kind === 'approve' && e.data && e.data.gate === 'plan'; });
  }
  function planWord(c) {
    if (!c.plan_ref) return null;
    if (c.derived.plan_gate) return { text: 'gate open', cls: 'acc' };
    if (planApproved(c)) return { text: 'approved', cls: 'good' };
    if (STAGES.indexOf(K.stageOf(c)) > STAGES.indexOf('planning')) return { text: 'approved', cls: 'good' };
    return { text: 'written', cls: 'plain' };
  }

  /* outcome: what came out, and whether it is still yours to answer. A backlogged card is
     at its outcome gate too, so it says how long it has sat there instead of "gate open",
     which is the whole of what the date rule decided on. */
  /* The landing queue (keel/landing.py): a `land` relay pending, a worker testing the
     merged tree, or its refusal. The relay itself is the house column's "land asked of". */
  function landingOf(c) {
    return (c.options && c.options.landing) || null;
  }
  /* `derived.landing` (keel/views.py, c-535) is the board's own answer, which also takes the
     card out of needs-you; the rest is for a card read from an older board. */
  function landingPending(c) {
    if (c.derived.landing) return true;
    var l = landingOf(c);
    return (c.derived.relays || []).some(function (r) { return r.what === 'land'; })
      || !!(l && l.state === 'testing' && K.stageOf(c) === 'review');
  }
  function pretestWord(c) {
    var p = c.options && c.options.pretest;
    if (!p || !p.result) return null;
    /* not run: the repo's file changed, so Keel could not know what to test (keel/merging.py).
       It is not a red tree, and the gate says why under "will not land" */
    if (p.result === 'not run') return 'not pre-run';
    return p.result === 'green' ? 'merged tree green' : p.result === 'conflict' ? 'conflicts with ' + (p.target || 'its target') : 'merged tree red';
  }
  /* lane SHIP: the pull request is ready and watched until it merges. The chip says what
     the watcher last saw on it (`options.shipping.facts`, keel/shipwatch.py). */
  function shippingOf(c) { return (c.options && c.options.shipping) || null; }
  function shipWord(c) {
    /* SH-10: a card with a pull request in each of its repos says how many are ready and
       how many merged (`facts.prs`); one pull request is 'PR ready', as it always was. */
    var s = shippingOf(c) || {}, f = s.facts || {}, prs = f.prs || [];
    var merged = prs.filter(function (p) { return p.state === 'merged'; }).length;
    var ready = prs.length > 1 ? (prs.length - merged) + K.say(c.space, ' {changes_short} ready') + (merged ? ' \u00b7 ' + merged + ' merged' : '') : K.say(c.space, '{change_short} ready');
    /* c-600: a declined or still-draft pull request says so first; what the house has
       answered and not shipped yet (`told` not `posted`) and the commits the pull request
       lacks (`local.ahead`) are what his Ship would send */
    if (s.state === 'declined') ready = K.say(c.space, '{change_short} declined');
    else if (f.draft) ready = K.say(c.space, '{change_short} draft');
    var parts = [ready, count(f.comments || 0, 'comment')];
    var open = K.shipping ? K.shipping.openTold(c) : 0, ahead = (s.local || {}).ahead || 0;
    if (f.waiting) parts.push(f.waiting + ' waiting');
    /* c-655: what his hand-over would give the house, the number its button says
       (`derived.ship_handover`); nothing once he has asked and the drain has it */
    var h = (c.derived && c.derived.ship_handover) || {};
    var unhanded = h.asked ? 0 : (h.comments || 0) + (h.checks || 0);
    if (unhanded) parts.push(unhanded + ' not handed over');
    if (open) parts.push(open + ' open');
    if (ahead) parts.push(count(ahead, 'commit') + ' to ship');
    /* c-653: a worktree that has diverged from its pull request's branch sends nothing */
    var astray = (s.local || {}).behind ? ((s.local || {}).diverged ? 'branch diverged' : 'branch behind') : null;
    if (astray) parts.push(astray);
    if (f.ci === 'failed') parts.push('checks failed');
    if (f.behind) parts.push(f.behind + ' behind');
    return { text: parts.join(' · '), cls: (f.waiting || unhanded || open || astray || f.ci === 'failed' ? 'warn' : 'acc') + ' tally' };
  }
  /* lane RC: a review card says where its review stands (`derived.review`, keel/views.py) */
  var REVIEW_WORDS = { waiting: ['waiting for your Review', 'plain'], reviewing: null, gate: null,
                       posted: ['review posted', 'good'], 'new': ['new commits since your review', 'warn'],
                       closed: ['{change} closed', 'plain'] };
  /* lane GRP: a held review card's wait for its story's other side (`derived.review_wait`,
     keel/views.py), in the one line the row, the pane and the kanban all say */
  function reviewWaitLine(c) {
    var w = c.derived && c.derived.review_wait;
    return w ? 'waiting for the ' + w.sibling_repo + K.say(c.space, ' {change_short} (') + w.story + ' has a branch there), ' + w.hours_left + 'h left' : '';
  }
  function reviewWord(c) {
    /* FC-10: the wait is a sentence, so it wraps (`tally`) rather than being clipped at the
       pane head's edge; `word` puts the whole of it in the title as well */
    if (c.derived.review === 'held') return { text: reviewWaitLine(c) || 'held', cls: 'warn tally' };
    var w = REVIEW_WORDS[c.derived.review];
    if (!w) return null;
    var verdict = c.options && c.options.review_posted && c.options.review_posted.verdict;
    var word = K.say(c.space, w[0]);
    var text = c.derived.review === 'posted' && verdict ? word + ' \u00b7 ' + ({ changes: 'changes requested', approve: 'approved', comment: 'comments only' }[verdict] || verdict) : word;
    return { text: text, cls: w[1] };
  }
  function outcomeWord(c) {
    if (c.derived.review && reviewWord(c)) return reviewWord(c);
    if (research(c)) return researchWord(c);
    if (K.stageOf(c) === 'shipping') return shipWord(c);
    if (K.stageOf(c) === 'done') return { text: 'approved', cls: 'good' };
    var l = landingOf(c);
    if (landingPending(c) && K.stageOf(c) === 'review' && !c.blocked_reason)
      return { text: l && l.state === 'testing' ? 'landing \u00b7 testing on ' + l.host : 'landing', cls: 'acc' };
    if (l && l.state === 'refused' && K.stageOf(c) === 'review') return { text: 'not landed', cls: 'crit' };
    if (c.derived.outcome_gate && pretestWord(c)) return { text: 'gate open · ' + pretestWord(c), cls: c.options.pretest.result === 'green' ? 'acc' : 'warn' };
    if (c.derived.backlog) return { text: 'backlog ' + daysSince(c.derived.backlog_since) + ' d', cls: 'warn' };
    if (c.derived.outcome_gate) return { text: 'gate open', cls: 'acc' };
    if (c.output_ref) return { text: c.options.pr ? K.say(c.space, 'draft {change_short} #') + c.options.pr : 'output', cls: 'plain' };
    return null;
  }

  /* research and the like (c-592): its result is ready for him, or done; no pull request,
     landing, review round or merged-tree test applies to it */
  function researchWord(c) {
    if (K.stageOf(c) === 'done') return { text: 'done', cls: 'good' };
    if (c.derived.backlog) return { text: 'backlog ' + daysSince(c.derived.backlog_since) + ' d', cls: 'warn' };
    if (c.derived.outcome_gate) return { text: 'result ready', cls: 'acc' };
    return c.output_ref ? { text: 'result', cls: 'plain' } : null;
  }

  /* A tracking card has no gate and no work of its own, so it says that it IS a tracking
     card and how its slices stand, instead of the three words. It used to lead with the
     stage it borrows from its children, which on c-277 read `building` beside a house that
     was idle, holding a pool slot for nothing (2026-09-20).
     The counts are `derived.tracking_tally`, the board's own words (`keel/views.py`), so
     this and `kb list` cannot say it differently. `plain` rather than `warn` because a
     parent whose slices are building has not gone quiet, it is simply not the one working. */
  function trackWord(c) {
    var stage = K.stageOf(c);
    var cls = stage === 'done' ? 'good' : stage === 'review' ? 'acc' : 'plain';
    return { text: 'tracking · ' + (c.derived.tracking_tally || 'no slices'),
             cls: cls + ' tally' };
  }

  /* the cards a card is still waiting for (the board's own `derived.waiting_for`: every
     card its `after` names that is not at review or done), or null when it may start */
  function waitsFor(c) {
    var left = c.derived.waiting_for || [];
    return left.length ? 'waits for ' + left.join(', ') : null;
  }

  /* null in, null out: a question with no answer draws nothing, and every caller of `word`
     already stands beside a `: null` of its own, so the gap simply closes. */
  function word(w, name) {
    if (!w) return null;
    return el('span', { class: 'sw ' + w.cls, title: name + ': ' + w.text, text: w.text });
  }
  /* A plan or an outcome in the format, at its gate (P4-5): what it asks and where his round
     stands, from the same parse and lint the page uses (`plan_doc`, keel/planfacts.py). A
     reply waiting is the loud one: the house has answered something he asked. */
  function count(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }
  function roundWord(c) {
    var d = c.plan_doc;
    if (!d) return null;
    var parts = [];
    if (d.decisions) parts.push(count(d.decisions, 'decision') + (d.changed ? ', ' + d.changed + ' changed' : ''));
    if (d.questions) parts.push(count(d.questions, 'question'));
    if (d.notes) parts.push(count(d.notes, 'note'));
    if (d.replies) parts.push(count(d.replies, 'reply', 'replies') + ' waiting');
    if (d.asks_open) parts.push(count(d.asks_open, 'ask') + ' open');
    return parts.length ? { text: parts.join(' · '), cls: (d.replies ? 'acc' : 'plain') + ' tally' } : null;
  }
  function contractWord(c) {
    var d = c.plan_doc;
    if (!d) return null;
    return d.ok ? { text: 'contract holds', cls: 'good' } : { text: count(d.breaks, 'break'), cls: 'crit' };
  }
  function wordsOf(c) {
    if (keelOf(c)) return keelWords(c);
    if (tracking(c)) return [word(trackWord(c), 'slices')];
    /* research says its plan only while it waits on him, so "approved" never reads as the result's */
    if (research(c)) return [word(houseWord(c), 'house'), c.derived.plan_gate ? word(planWord(c), 'plan') : null,
      word(outcomeWord(c), 'outcome'), word(roundWord(c), 'round'), word(contractWord(c), 'contract')].filter(Boolean);
    /* c-604: a done card's plan and outcome are both `approved`, and the line read
       "approved approved"; the outcome's answer covers the plan's, so it is said once */
    var plan = planWord(c), outcome = outcomeWord(c);
    if (plan && outcome && plan.text === outcome.text) plan = null;
    return [word(houseWord(c), 'house'), word(plan, 'plan'),
      word(outcome, 'outcome'), word(roundWord(c), 'round'),
      word(contractWord(c), 'contract')].filter(Boolean);
  }
  /* No words and nothing waited on means no row: an empty `.swords` is a 12px gap under
     the title that says nothing, which is what "none none none" was in the first place. */
  function wordsRow(c, extra) {
    var words = wordsOf(c), wait = extra ? waitsFor(c) : null;
    if (!words.length && !wait) return null;
    return el('div', { class: 'swords' }, words,
      wait ? el('span', { class: 'sw wait', text: wait }) : null);
  }
  K.houseWord = houseWord; K.planWord = planWord; K.outcomeWord = outcomeWord; K.reviewWaitLine = reviewWaitLine;
  K.trackWord = trackWord; K.tracking = tracking; K.roundWord = roundWord; K.contractWord = contractWord;
  K.waitsFor = waitsFor; K.word = word; K.wordsOf = wordsOf; K.wordsRow = wordsRow;

  /* ---------- the table ---------- */
  var COLUMNS = [
    { key: 'id', head: 'Id', cell: function (c) { return el('td', { class: 'id', text: c.id }); } },
    /* sorted by queue order, each queued title says its place */
    { key: 'title', head: 'Title', cell: function (c) {
      var n = queueNumber(c);
      return el('td', { class: 't', title: c.title }, n ? el('span', { class: 'qn', text: String(n) }) : null,
        keelChip(c), c.title);
    } },
    /* the three words, and for a tracking card one cell across all three: a big card has
       no house, plan or outcome of its own, its slices carry them */
    { key: 'house', head: 'House', cell: function (c) {
      if (tracking(c) && !keelOf(c)) return el('td', { class: 'swcell', colspan: '3' }, word(trackWord(c), 'slices'));
      /* a Keel card has no house of its own: Bosun's state across the three (c-592) */
      if (keelOf(c)) return el('td', { class: 'swcell', colspan: '3' }, keelWords(c));
      /* why nothing is running is part of the house's answer, so the sibling a slice is
         still waiting for is said here rather than beside its outcome */
      return el('td', { class: 'swcell' }, word(houseWord(c), 'house'),
        waitsFor(c) ? el('span', { class: 'sw wait', text: waitsFor(c) }) : null);
    } },
    { key: 'plan', head: 'Plan', cell: function (c) {
      return tracking(c) || keelOf(c) ? null : el('td', { class: 'swcell' }, word(planWord(c), 'plan'));
    } },
    { key: 'outcome', head: 'Outcome', cell: function (c) {
      return tracking(c) || keelOf(c) ? null : el('td', { class: 'swcell' }, word(outcomeWord(c), 'outcome'));
    } },
    { key: 'auto', head: 'Auto', wide: true, cell: function (c) { return el('td', { text: c.autonomy }); } },
    { key: 'repo', head: 'Repo', wide: true, cell: function (c) { return el('td', { text: c.repo || 'errand' }); } },
    { key: 'topic', head: 'Topic', wide: true, roomy: true, cell: function (c) { return el('td', { text: c.topic || '' }); } },
    { key: 'last', head: 'Last event', wide: true, roomy: true, cell: function (c) { return el('td', { class: 'last', title: K.lastLine(c), text: K.lastLine(c) }); } },
    { key: 'age', head: 'Age', cell: function (c) { return el('td', { class: 'age', text: K.ago(c.updated_at) }); } }
  ];
  /* beside the detail pane the table keeps the id, the title, the three words and the age:
     the columns it gives up (autonomy, repo, topic, last event) are all in the pane */
  /* and under ROOMY wide it gives up topic and last event even with no pane (c-553): the
     other columns' widths sum past what a 1280 window leaves, and the title, which takes
     only what is left, was squeezed to one letter */
  var ROOMY = '(min-width: 1400px)';
  function columns(compact) {
    var narrow = !window.matchMedia(ROOMY).matches;
    return COLUMNS.filter(function (col) { return !(compact && col.wide) && !(narrow && col.roomy); });
  }
  /* `data-key` is the card's own id, so a row that moved when the list re-sorted is the
     SAME NODE in its new place: what it was holding (the row he had hovered, a transition
     part way through, the selection) moves with it. */
  function cardRow(c, cols, depth) {
    return el('tr', { class: 'card' + (c.derived.needs_you && !c.blocked_reason ? ' need' : '')
      + (c.blocked_reason ? ' blocked' : '') + (App.card === c.id ? ' sel' : '')
      + (depth ? ' kin' : '') + (tracking(c) ? ' bigcard' : ''),
      'data-key': c.id, onclick: function () { K.select(c.id); } },
      cols.map(function (col) { return col.cell(c); }));
  }
  /* Group by (the View menu): a heading per stage, topic or repo with its count, the
     slices under their big card for parent, or one flat list. */
  function lastIs(word) { return function (a, b) { return a === word ? 1 : b === word ? -1 : a.localeCompare(b); }; }
  var GROUPS = {
    stage: { of: function (c) { return K.stageOf(c); }, order: function (a, b) { return STAGES.indexOf(a) - STAGES.indexOf(b); } },
    topic: { of: function (c) { return c.topic || 'no topic'; }, order: lastIs('no topic') },
    repo: { of: function (c) { return c.repo || 'errand'; }, order: lastIs('errand') }
  };
  function groupsOf(list, group) {
    var g = GROUPS[group];
    if (!g) return [{ name: null, items: group === 'parent' ? byParent(list) : list.map(flat) }];
    var seen = {}, order = [];
    list.forEach(function (c) {
      var key = g.of(c);
      if (!seen[key]) { seen[key] = []; order.push(key); }
      seen[key].push(c);
    });
    order.sort(g.order);
    return order.map(function (k) { return { name: k, items: seen[k].map(flat) }; });
  }
  /* ---------- group by parent ----------
   * A tracking card is one block: the card itself, then the slices that survived the
   * filters, indented under it. A slice whose parent is filtered out stands on its own
   * rather than disappearing, and the order the list came in is otherwise kept. */
  function flat(c) { return { card: c, depth: 0 }; }
  /* a big card's slices in its tree's order (by step, then queue order within a step),
     and in filing order for a card the board has not given a tree */
  function childOrder(c) {
    var tree = c.derived && c.derived.tree;
    if (!tree) return c.children || [];
    var out = [];
    tree.steps.forEach(function (g) { g.cards.forEach(function (n) { out.push(n.id); }); });
    (c.children || []).forEach(function (id) { if (out.indexOf(id) < 0) out.push(id); });
    return out;
  }
  function byParent(list) {
    var index = {}, seen = {}, out = [];
    list.forEach(function (c) { index[c.id] = c; });
    list.forEach(function (c) {
      if (seen[c.id] || (c.parent && index[c.parent])) return;
      out.push({ card: c, depth: 0 });
      seen[c.id] = true;
      childOrder(c).forEach(function (id) {
        if (index[id] && !seen[id]) { out.push({ card: index[id], depth: 1 }); seen[id] = true; }
      });
    });
    list.forEach(function (c) { if (!seen[c.id]) { out.push({ card: c, depth: 0 }); seen[c.id] = true; } });
    return out;
  }
  /* An empty list says which kind of empty it is (c-631): a space with no card yet, or a
     filter that hid them. Review cards are Reviews' and do not count. */
  function spaceEmpty() {
    var n = (K.spaceInfo().counts || {}).cards;
    if (typeof n === 'number') return n === 0;
    return !K.cards().some(function (c) { return K.inSpace(c) && !K.isReview(c) && K.liveCard(c); });
  }
  function emptyLine() { return spaceEmpty() ? 'no card in this space yet' : 'no card matches'; }
  function cardsTable(list, compact, group) {
    var cols = columns(compact), rows = [];
    groupsOf(list, group).forEach(function (g) {
      if (g.name) rows.push(el('tr', { class: 'group', 'data-key': 'group:' + g.name }, el('td', { colspan: String(cols.length), text: g.name + ' · ' + g.items.length })));
      g.items.forEach(function (item) { rows.push(cardRow(item.card, cols, item.depth)); });
    });
    return el('div', { class: 'table-wrap' }, el('table', { class: 'cards' },
      el('colgroup', {}, cols.map(function (col) { return el('col', { class: 'c-' + col.key, 'data-key': col.key }); })),
      el('thead', {}, el('tr', {}, cols.map(function (col) { return el('th', { 'data-key': col.key, text: col.head }); }))),
      el('tbody', {}, rows.length ? rows : el('tr', {}, el('td', { colspan: String(cols.length), class: 'empty', text: emptyLine() })))));
  }

  /* ---------- the kanban ---------- */
  /* `from` is the tile that was dragged: a drop has no button to press, so the tile it
     came from is what breathes while the move is in flight. */
  function dropOn(c, stage, from) {
    if (K.stageOf(c) === stage) return;
    if (c.derived.plan_gate && stage === 'building') { K.approveGate(c, 'plan', from); return; }
    if (c.stage === 'review' && (stage === 'done' || stage === 'shipping')) {
      /* c-551: an Approve that could not publish is not offered by a drop either */
      if (c.unpublished) { alert(c.unpublished); return; }
      if (confirm(K.proposalOf(c) ? K.adoptConfirm(c) : 'Approve the outcome of ' + c.id + '?')) K.approveGate(c, 'outcome', from);
      return;
    }
    K.act({ verb: 'stage', id: c.id, stage: stage }, null, from);
  }
  function kanbanTile(c) {
    var t = el('div', { class: 'tile' + (c.derived.needs_you && !c.blocked_reason ? ' need' : '')
      + (K.houseBusy(c) ? ' run' : '') + (App.card === c.id ? ' sel' : '') + (c.blocked_reason ? ' blocked' : '')
      + (K.pendingOn(c.id) ? ' pending' : ''),
      draggable: 'true', 'data-key': c.id, onclick: function () { K.select(c.id); } },
      el('div', { class: 'h' }, el('span', { class: 'id', text: c.id }), keelChip(c), el('span', { class: 'spacer' }),
        c.parent ? el('span', { class: 'kin', text: '↳ ' + c.parent }) : null),
      el('div', { class: 't', text: c.title }),
      wordsRow(c, true),
      el('div', { class: 'm' }, el('span', { text: c.autonomy }), c.repo ? el('span', { text: c.repo }) : null));
    t.addEventListener('dragstart', function (ev) {
      ev.dataTransfer.setData('text/plain', c.id); ev.dataTransfer.effectAllowed = 'move';
      App.dragTile = t;
    });
    return t;
  }
  function kanban(list) {
    return el('div', { class: 'board' }, STAGES.map(function (s) {
      var lane = el('section', { class: 'lane', 'data-key': s });
      var items = list.filter(function (c) { return K.stageOf(c) === s; });
      var hidden = s === 'done' && !showsDone(), loading = s === 'done' && !hidden && !K.doneHeld();
      add(lane, el('div', { class: 'lane-head' }, el('span', { class: 'lbl10', text: s }),
        el('span', { class: 'n', text: hidden ? 'hidden' : loading ? 'loading' : String(items.length) })));
      var stack = el('div', { class: 'stack' },
        hidden ? el('div', { class: 'empty' },
          el('button', { class: 'btn sm', onclick: function () { K.find.include('cards', 'done'); } }, 'Include done'))
          : loading ? el('div', { class: 'empty', 'data-key': 'loading-done', text: 'Loading done cards' })
          : items.map(kanbanTile));
      stack.addEventListener('dragover', function (ev) { ev.preventDefault(); lane.classList.add('over'); });
      stack.addEventListener('dragleave', function () { lane.classList.remove('over'); });
      stack.addEventListener('drop', function (ev) {
        ev.preventDefault(); lane.classList.remove('over');
        var c = K.byId(ev.dataTransfer.getData('text/plain')), tile = App.dragTile;
        App.dragTile = null;
        if (c) dropOn(c, s, tile);
      });
      add(lane, stack);
      return lane;
    }));
  }

  /* ---------- the phone list ----------
   * One list, grouped by stage with a count on each heading unless he picks another
   * grouping in the View menu: the lane strip that showed one stage at a time is gone, and
   * the inbox, where triage starts, is still the first heading (F3). No kanban here. */
  function phoneRow(item) {
    var c = item.card, n = queueNumber(c);
    return el('button', { class: 'compact stack' + (item.depth ? ' kin' : ''), 'data-key': c.id, onclick: function () { K.select(c.id); } },
      el('span', { class: 'crow' }, n ? el('span', { class: 'qn', text: String(n) }) : null,
        el('span', { class: 'id', text: c.id }), el('span', { class: 't', text: c.title })),
      /* c-592: on the phone the Keel label leads the words line, so the title keeps the row */
      keelOf(c) ? el('div', { class: 'swords' }, keelChip(c), keelWords(c)) : wordsRow(c, true), n && c.derived.startable ? K.pill('next', 'next') : null);
  }
  function phoneCards(list, group) {
    var out = [];
    groupsOf(list, group).forEach(function (g) {
      if (g.name) {
        out.push(el('div', { class: 'fgroup-head', 'data-key': 'g:' + g.name },
          el('span', { text: g.name }), el('span', { class: 'n', text: String(g.items.length) })));
      }
      g.items.forEach(function (item) { out.push(phoneRow(item)); });
    });
    return out.length ? out : [el('div', { class: 'empty', 'data-key': 'none', text: emptyLine() })];
  }

  /* ---------- the view ---------- */
  function viewCards() {
    var found = findCards(), list = found.items, sel = App.card ? K.byId(App.card) : null;
    var layout = K.find.mode('cards', 'layout'), group = K.find.mode('cards', 'group');
    if (sel && sel.space !== App.space) sel = null;
    if (!K.isDesk() && sel) return K.phoneDetail(sel, 'cards');
    /* Include done on before the done part has landed (c-549): the count says it is not
       whole yet, and one line says why, rather than a list that looks complete */
    var loading = showsDone() && !K.doneHeld();
    var head = el('div', { class: 'panel-head' }, el('span', { class: 'label',
      text: 'Cards · ' + list.length + (loading ? ' · loading done' : '') }));
    var bar = K.find.bar('cards', found);
    if (loading && layout !== 'kanban') bar = [bar, el('div', { class: 'empty', 'data-key': 'loading-done', text: 'Loading done cards' })];
    if (!K.isDesk()) return el('section', { class: 'panel grow' }, head, el('div', { class: 'panel-body' }, bar, phoneCards(list, group)));
    var content = layout === 'kanban' ? kanban(list) : el('div', { class: 'split', 'data-key': 'split' },
      el('div', { class: 'split-table', 'data-key': 'cards-list' }, cardsTable(list, !!sel, group)),
      sel ? el('div', { class: 'split-pane drawer', 'data-key': 'detail' }, K.detailPane(sel)) : null);
    return el('section', { class: 'panel grow' }, head,
      el('div', { class: 'panel-body' }, bar, layout === 'kanban' && sel
        ? el('div', { class: 'split', 'data-key': 'split' }, content, el('div', { class: 'split-pane drawer', 'data-key': 'detail' }, K.detailPane(sel)))
        : content));
  }

  /* ---------- the gate answers ---------- */
  /* The sentence each of these says is `act`'s, one table for every caller, so the drop
     on a lane and the button in the gate row cannot answer differently. */
  function approveGate(c, gate, from) { K.act({ verb: 'approve', id: c.id, gate: gate }, null, from); }

  /* ---------- where he types ----------
   * ONE FIELD for every answer a gate takes: a send back's reason, a discussion's topic,
   * and what he wants to say with an Approve (his answers to the plan's open questions
   * above all). It replaces the one-line input that used to sit in the card, where Enter
   * submitted and he could not see what he had typed.
   *
   * It is a SHEET rather than a field grown in place, for three reasons.
   * - The keyboard covers roughly the bottom 40% of the screen, and a field near the
   *   bottom of a long card pane goes under it, taking its button with it. A sheet is
   *   pinned to the viewport and lifts off the keyboard (`--kbd`, set in ui.core.js), so
   *   the field and the button that sends it are both on screen.
   * - The five second poll rebuilds the body and never touches the sheet, so what he
   *   typed, the caret and the open field survive a refresh by construction rather than by
   *   a rule the next edit has to remember.
   * - The deck already opens the create form, the logs and the drop-in command this way. A
   *   field grown inside the card would be a fourth idiom for the same job.
   *
   * A plain Approve is untouched and still ONE TAP. This is the quiet control beside it,
   * and its field may be left empty, which is that plain approve again. */
  var SAY = {
    approve: { verb: 'Approve plan', body: { verb: 'approve', gate: 'plan' }, need: false,
               label: 'What you want to say',
               placeholder: 'anything the build should carry',
               help: "Your answers to the plan's open questions, or anything else the house "
                     + 'should build with. Leave it empty and it is a plain approve.' },
    sendback: { verb: 'Send back', body: { verb: 'sendback' }, need: true,
                label: 'Why it is going back',
                placeholder: 'what is wrong, and what you want instead',
                help: 'The house takes this and revises. A send back needs a reason.' },
    stay: { verb: 'Send back and stay', body: { verb: 'sendback', stay: true }, need: true,
            label: 'What to talk about',
            placeholder: 'what you want to work through',
            help: 'The house holds its slot and talks it through on the plan surface.' },
    /* F1: a blocked house that stopped to ask him something gets his answer WITH the
       resume. Resume alone sends "continue from where you stopped", which answers nothing. */
    answer: { verb: 'Answer and resume', body: { verb: 'house.resume' }, need: true,
              label: 'Your answer',
              placeholder: 'what the house needs to carry on',
              help: 'The house is resumed with your words, and they are noted on the card as yours.' }
  };
  var SAY_LINES = 4, SAY_SHARE = 0.4;

  function openSay(c, mode) {
    App.sheet = { kind: 'say', id: c.id, gate: K.gateOf(c), mode: mode };
    K.renderSheet();
    var field = document.querySelector('.sheet [data-fk="say"]');
    if (!field) return;
    field.focus();
    try { field.setSelectionRange(field.value.length, field.value.length); } catch (e) { /* no caret */ }
  }
  function closeSay() { App.sheet = null; K.renderSheet(); }

  /* The field grows with what is in it, up to 40% of the VISIBLE viewport (the window
     minus the keyboard), and scrolls inside itself past that, so a long answer never
     pushes the button off the screen. `height:auto` first, because `scrollHeight` is the
     content's height only when the box is not already holding it; the four line floor is
     the CSS `min-height`, which wins over anything smaller set here. */
  function growDraft() {
    var node = document.querySelector('.sheet [data-fk="say"]');
    if (!node) return;
    node.style.height = 'auto';
    node.style.height = Math.min(node.scrollHeight, Math.round(K.viewHeight() * SAY_SHARE)) + 'px';
  }

  /* The plan's own "Open questions" section, so he is not answering them from memory. It
     is there only when the deck is already carrying the plan text (a markdown plan,
     through `/api/card/<id>`); it is cut from one heading to the next, the way
     `deckstate.section` cuts context.md, and shown as the plain text it is. Nothing here
     parses markdown. */
  function openQuestions(c) {
    var d = App.detailFor === c.id ? App.detail : null;
    var found = /^#{1,6}[ \t]*open questions[^\n]*\n([\s\S]*)/im.exec((d && d.plan_text) || '');
    if (!found) return '';
    /* A plan is wrapped at a column for the terminal. Shown raw on a phone every wrapped
       line breaks twice, so a line that only continues the one before it is joined to it;
       a blank line, a list item and a numbered item still start a new line. */
    return found[1].split(/^#{1,6}[ \t]/m)[0].trim()
      .replace(/(?<!\n)\n(?![ \t]*\n)(?![ \t]*(?:[-*+]|\d+[.)])[ \t])[ \t]*/g, ' ');
  }

  /* What a blocked house last said, which is usually the question it stopped on: its
     block reason, and its last output when that says more than the reason already does. */
  function houseAsked(c) {
    var reason = String(c.blocked_reason || ''), said = String(c.last_said || '');
    return said && reason.indexOf(said) < 0 ? (reason ? reason + '\n\n' : '') + said : reason;
  }

  function sayBody(s) {
    var shape = SAY[s.mode], text = K.draft(s.id, s.gate).trim();
    var body = Object.assign({ id: s.id }, shape.body);
    if (s.mode === 'approve' || s.mode === 'answer') { if (text) body.said = text; } else { body.reason = text; }
    return body;
  }
  function submitSay() {
    var s = App.sheet;
    if (!s || s.kind !== 'say') return;
    if (SAY[s.mode].need && !K.draft(s.id, s.gate).trim()) {
      K.toast(s.mode === 'answer' ? 'an answer needs words; Resume house sends none' : 'a send back needs a reason', true);
      return;
    }
    /* The sheet stays up while the send is in flight: its button is where the wait is
       shown, and a refusal leaves everything he typed exactly where it was. */
    K.act(sayBody(s), function () { K.clearDraft(s.id, s.gate); closeSay(); });
  }

  function sayField(s) {
    var node = el('textarea', { 'data-fk': 'say', rows: String(SAY_LINES),
      value: K.draft(s.id, s.gate), placeholder: SAY[s.mode].placeholder,
      readonly: K.pendingOn(s.id) ? true : null,
      oninput: function (ev) { K.setDraft(s.id, s.gate, ev.target.value); growDraft(); },
      /* ENTER IS A NEW LINE. The button is what sends, and on a desk keyboard Cmd or
         Ctrl with Enter does too. */
      onkeydown: function (ev) {
        if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); submitSay(); }
      } });
    /* the first grow needs the node laid out, which it is not until this pass ends */
    setTimeout(growDraft, 0);
    return node;
  }

  /* The questions, clipped to a preview with one Show all: the same shape `readingBlock`
     gives a long brief on the phone, so a long section cannot push the field off the
     screen and nothing is cut flat by an edge. Open is the sheet's own state, because the
     DOM is what a rebuild throws away. */
  function questionsBlock(s, text, label) {
    var long = text.length > PREVIEW_CHARS, open = long ? !!s.questionsOpen : true;
    return [el('span', { class: 'label', text: label || 'Open questions' }),
      el('div', { class: 'sayq' + (open ? '' : ' clip'), text: text }),
      long ? el('button', { class: 'btn sm showall',
        onclick: function () { s.questionsOpen = !open; K.renderSheet(); } },
        open ? 'Show less' : 'Show all') : null];
  }

  function saySheet(s) {
    var c = K.byId(s.id);
    if (!c) return el('div', { class: 'sheet' });      // the card left the space under him
    var shape = SAY[s.mode], questions = s.mode === 'approve' ? openQuestions(c) : '';
    var asked = s.mode === 'answer' ? houseAsked(c) : '';
    return el('div', { class: 'sheet' },
      el('div', { class: 'sheet-head' },
        el('button', { onclick: closeSay }, '‹ close'),
        el('span', { class: 'spacer' }),
        el('span', { class: 'mono t11 ink2', text: c.id + ' · ' + (s.gate === 'blocked' ? 'blocked' : (s.gate || 'gate') + ' gate') })),
      el('div', { class: 'sheet-body' },
        el('div', { class: 'title', text: c.title }),
        questions ? questionsBlock(s, questions) : null,
        asked ? questionsBlock(s, asked, 'What the house said') : null,
        el('div', { class: 'saybox' },
          el('span', { class: 'label', text: shape.label }),
          sayField(s),
          el('span', { class: 'fhelp', text: shape.help }))),
      el('div', { class: 'sheet-foot' },
        el('button', { class: 'btn', onclick: closeSay }, 'Cancel'),
        K.faceBtn(shape.verb, sayBody(s), 'primary', submitSay)));
  }
  K.approveGate = approveGate; K.openSay = openSay; K.saySheet = saySheet;
  K.growDraft = growDraft; K.openQuestions = openQuestions;

  /* ---------- the inspector ---------- */
  /* A button that does something on the page rather than sending a verb (it opens the
     reason line, the dialog, a sheet, a tab). `subject` is the card it belongs to: given
     one, it goes quiet with the rest of its row while an action on that card is in
     flight, so the gate row cannot be worked while it is answering. */
  function btn(label, fn, cls, subject, title) {
    return el('button', { class: 'btn' + (cls ? ' ' + cls : ''), title: title || null,
      disabled: subject && K.pendingOn(subject) ? true : null, onclick: fn }, label);
  }

  /* Every action carries a KEY (`data-key`, which the morph matches by too), so the phone
     can pick its primaries by name rather than by position (`PHONE_PRIMARY`, below), and
     its hover line is looked up by the same key (`K.tipped`, app/ui.tips.js). */
  function keyed(key, node) { node.setAttribute('data-key', key); return node; }

  /* ---------- which control each phase shows (c-601): THE ONE TABLE ----------
     Every control the card pane may draw, keyed as `put` keys it, and the phases (the card's
     stage, `K.stageOf`) it may be drawn in. `put` asks `shownIn` before anything else, so the
     conditions written beside each control (a session, a live house, a link) only narrow
     this further; a key missing here is never drawn. The Atlas gives every row its reason
     (docs/atlas/40-deck.md, "Controls by phase") and tests/test_deck_phases.py pins the two
     together. The shipping column is card c-600's (after-gate): Ship is its one door out, and a done card whose house is still listed keeps Stop (and Logs).
     The pane's shipping phase draws its own set (ui.shipping.js), but the shipping column is
     still asked: by the Now tile (`houseActionNodes`: Open in app, Logs, Stop, and Resume,
     Resume and open in app, Retry for a blocked house) and by a Keel card, which skips the
     shipping branch (c-604 review). */
  var ALL = ['inbox', 'assigned', 'planning', 'building', 'review', 'shipping', 'done'];
  var NOT_DONE = ['inbox', 'assigned', 'planning', 'building', 'review', 'shipping'];
  var HOUSED = ['planning', 'building', 'review', 'shipping'];
  var CONTROL_PHASES = {
    'answer-ask': ALL, 'unblock': ALL, 'dismiss': ALL, 'end-discussion': ALL, 'edit': ALL,
    'open-bosun': ALL, 'on-voice': ALL, 'in-terminal': ALL, 'story': ALL, 'open-pr': ALL,
    'design-doc': ALL, 'open-plan': ALL, 'open-output': ALL, 'open-named': ALL, 'context': ALL, 'verb': ALL,
    /* c-640: a flow's moves he makes; each says its own stages, so the row allows them all */
    'flow': ALL,
    'review-settings': ALL, 'backlog-active': ALL, 'backlog-send': ['review'],
    'backlog-auto': ALL, 'archive': ALL,
    'approve-plan': ['planning'], 'approve-note': ['planning'], 'sendback-stay': ['planning'],
    'sendback': ['planning', 'review'], 'open-result': ['review'], 'open-outcome': ['review'],
    'open-ci': ['building', 'review', 'shipping', 'done'],
    'open-comments': ['shipping', 'done'],      /* c-643, c-644: a page of the card's viewer, app/ui.shipping.js; at done, read only */
    'worker': ['inbox', 'assigned'],      /* c-645: Give to a house, Give to Bosun */
    'approve-outcome': ['review'],
    'answer': HOUSED, 'resume': HOUSED, 'retry': NOT_DONE,
    /* a tracking card reads at its children's stage (`parent_stage`), which is review once
       every slice is done, and that is exactly when Back to your gate is wanted */
    'regate': ['inbox', 'assigned', 'planning', 'building', 'review'],
    'split': ['inbox', 'assigned', 'planning', 'building', 'shipping'],
    /* c-604: two controls, two keys: `talk-voice` is Talk to this house (voice, connected to
       it), `talk` is the shipping phase's Talk sheet (every way into its session) */
    'open-app': HOUSED, 'talk-voice': ['planning', 'building', 'review'], 'talk': ['shipping'],
    'resume-house': HOUSED, 'resume-app': HOUSED,
    'rotate': HOUSED, 'logs': ALL, 'stop': HOUSED.concat(['done']), 'stop-twin': ALL,
    /* c-607: an idle house he closes to free its memory, only where something brings it back
       by itself (his gate answer at review, the next batch at shipping); elsewhere it is Stop's */
    'close-idle': ['review', 'shipping'], 'dropin': ALL,      /* c-787: a done card too */
    'rereview': ['done'], 'review-now': ['inbox', 'assigned'], 'ship': ['shipping'],
    'assign': ['inbox'], 'assign-tree': NOT_DONE, 'next-front': NOT_DONE, 'next-filing': NOT_DONE,
    /* c-631: the line saying what is not set up, where its control would be: a card's ticket
       with no tracker to open it in, and Ship with no code host to send it to */
    'need-tracker': ALL, 'need-codehost': ['shipping'],
    /* c-653: why there is no Ship, where it would be */
    'ship-why': ['shipping'],
    /* c-655: the review that waits on a shipping card, handed to its house (ui.shipping.js) */
    'hand-over': ['shipping'], 'hand-base': ['shipping'],
    /* c-663: his own notes for the house of a shipping card (ui.shipsendback.js) */
    'ship-sendback': ['shipping'],
    /* r-55 (c-723): the house's question on a prepared fix, with its Answer (ui.shipsendback.js) */
    'ship-prepared': ['shipping']
  };
  /* The moves of the card's space flow he makes at the card's stage (c-640, keel/flows.py
     `offered`), only on a card with a house to carry them out. */
  function flowMoves(c) {
    var spaces = (K.App.data || {}).spaces || {};
    var flow = (spaces[c.space] || {}).flow;
    if (!flow || !c.session_id) return [];
    /* the card's OWN stage, as the server checks (`flows.offered`), not a parent's */
    var stage = c.stage;
    /* c-732: the base the server says applies (`base`, `merging.card_base`): on a repo with
       an integration branch none does, whatever options.base holds */
    var base = String(c.base !== undefined ? c.base : (c.options || {}).base || '');
    /* and a move that names `bases` only on a card based on one (c-641, `flows.based`) */
    return flow.moves.filter(function (m) {
      return m.by === 'you' && (m.stages || []).indexOf(stage) >= 0 &&
        (!(m.bases || []).length || m.bases.indexOf(base) >= 0);
    });
  }
  K.flowMoves = flowMoves;
  /* c-642: the card's CI page, where its space's pack reads builds (`ci` ready) and the card
     has a repo, from the build on */
  var CI_STAGES = ['building', 'review', 'shipping', 'done'];
  function putCi(c, put) {
    var row = K.readyRow ? K.readyRow('ci', c.space) : null;
    if (!c.repo || !row || !row.ready || CI_STAGES.indexOf(c.stage) < 0) return;
    put('open-ci', btn('CI', function () { K.openPlan('/ci/' + c.id); }));
  }
  K.putCi = putCi;
  /* an adapter's verbs are one row: each carries its own `when` (`verb-<name>`) */
  function phaseKey(key) {
    return key.indexOf('verb-') === 0 ? 'verb' : key.indexOf('flow-') === 0 ? 'flow' : key;
  }
  function shownIn(key, c) {
    var phases = CONTROL_PHASES[phaseKey(key)];
    return !!phases && phases.indexOf(K.stageOf(c)) >= 0;
  }
  K.CONTROL_PHASES = CONTROL_PHASES; K.shownIn = shownIn;
  /* `cap`'s one-line panel under `key`, while the card's space has it unmet (c-631). `said`
     names a cap whose line the row already carries: the same reason is said once (c-662). */
  function putNeed(c, put, key, cap, said) {
    var line = cap ? K.needs(cap, c.space, { line: true }) : null;
    if (line && said && sameWhy(c.space, cap, said)) return;
    if (line) put(key, line);
  }
  function sameWhy(space, cap, other) {
    var a = K.unmet(cap, space)[0], b = K.unmet(other, space)[0];
    return !!a && !!b && a.row.why === b.row.why;
  }
  K.putNeed = putNeed;

  function gateActions(c) {
    var g = K.gateOf(c), out = [], held = K.inTerminal(c);
    function put(key, node) { if (shownIn(key, c)) out.push(K.tipped(keyed(key, node), key, c)); }
    /* c-521: Bosun's open ask about this card is answered where every ask is, on /console (Now) */
    if (c.derived.ask) put('answer-ask', btn('Answer Bosun (' + c.derived.ask.id + ')', function () {
      window.location.href = '/console#' + c.derived.ask.id;
    }, g ? '' : 'primary', c.id));
    /* c-600: the shipping phase draws its own controls, each one justified (ui.shipping.js) */
    if (K.stageOf(c) === 'shipping' && !keelOf(c) && K.shipping) { K.shipping.gateItems(c, put); return out; }
    if (g === 'plan') {
      put('approve-plan', K.actionBtn('Approve plan', { verb: 'approve', id: c.id, gate: 'plan' }, { cls: 'primary' }));
      /* the quiet one beside it: nothing is required in front of a plain approve, and this
         is the only way words of his reach a house whose plan is a markdown page */
      put('approve-note', btn('Approve with a note', function () { openSay(c, 'approve'); }, '', c.id));
      put('sendback', btn('Send back', function () { openSay(c, 'sendback'); }, '', c.id));
      /* a discussion runs on the plan's own surface, so it is offered only when there is one */
      if (K.onSurface(c)) put('sendback-stay', btn('Send back and stay', function () { openSay(c, 'stay'); }, '', c.id));
    } else if (g === 'outcome' && research(c)) {
      /* c-592: research, a plan, an errand: he reads the result on its own page, then says
         Done (the outcome approve, which publishes nothing here) or sends it back with a
         note (the same send back, which returns it to building with his words) */
      if (resultLink(c)) put('open-result', btn('Open result', function () { K.openPlan(resultLink(c)); }, 'primary'));
      /* c-719: a named output file beside the outcome is offered by its own name, never
         hidden behind Open result; it opens in the viewer (`links.output`, keel/cardfiles.py) */
      putNamed(c, put);
      /* c-667: a proposal's tap writes its draft, so it is Adopt and says into what */
      put('approve-outcome', K.actionBtn(K.proposalOf(c) ? 'Adopt' : 'Done', { verb: 'approve', id: c.id, gate: 'outcome' },
        { cls: resultLink(c) ? '' : 'primary', confirm: K.proposalOf(c) ? K.adoptConfirm(c) : 'Mark ' + c.id + ' done?' }));
      put('sendback', btn('Send back with a note', function () { openSay(c, 'sendback'); }, '', c.id));
      if (c.blocked_reason) put('unblock', K.actionBtn('Unblock only', { verb: 'unblock', id: c.id }));
    } else if (g === 'blocked' && keelOf(c)) {
      /* a Keel card has no house to resume or retry: Bosun holds it, and his answer goes to
         Bosun, on the Bosun page (c-592) */
      put('unblock', K.actionBtn('Unblock only', { verb: 'unblock', id: c.id }));
    } else if (g === 'outcome') {
      /* while it is landing, a second tap would only be refused (one landing per card) */
      /* lane RC: a review card's Approve is the one that posts (2026-09-24: "Approve") */
      /* c-551: one his Approve could not publish says what is missing (gateEvidence) and
         offers Send back in its place, never a button that is refused every time */
      /* c-605: the outcome's own page, where he reads it, notes it and answers it, one tap
         from the pane rather than More then View context; it leads, as Open result does */
      var page = outcomePage(c);
      if (page) put('open-outcome', btn('Open outcome', function () { K.openPlan(page); }, 'primary'));
      if (!landingPending(c) && !c.unpublished) put('approve-outcome', K.actionBtn(K.proposalOf(c) ? 'Adopt' : c.derived.review ? 'Approve' : 'Approve outcome', { verb: 'approve', id: c.id, gate: 'outcome' },
        /* c-667: a proposal first, slices or none, as its label and its tip */
        { cls: page ? '' : 'primary', confirm: K.proposalOf(c) ? K.adoptConfirm(c)
          : tracking(c) ? 'Close ' + c.id + '? Every slice is done and already landed. Nothing is published.'
          /* lane RC: a review card's Approve posts on a colleague's pull request */
          : c.derived.review ? K.say(c.space, 'Post this review on the {change}? The findings you kept go inline at their lines, then one summary and your verdict.')
          : 'Approve the outcome of ' + c.id + '? This publishes it.' }));
      /* c-605 review: one primary; where Open outcome leads, Send back stays secondary */
      put('sendback', btn('Send back', function () { openSay(c, 'sendback'); }, c.unpublished && !page ? 'primary' : '', c.id));
      /* r-26: a landing's refusal blocks the card and leaves it at this gate (gateOf), so
         the blocked row's way out is drawn here too; c-575 sat with no Unblock. Resume
         house stays in the card's menu, which draws it for a gate that is not `blocked`. */
      if (c.blocked_reason) put('unblock', K.actionBtn('Unblock only', { verb: 'unblock', id: c.id }));
    } else if (g === 'blocked') {
      /* his words WITH the resume (F1); a card with no session has nothing to resume, and
         one he is in at a terminal is not resumed behind him (U3: the server refuses it) */
      if (c.session_id && !held) put('answer', btn('Answer and resume', function () { openSay(c, 'answer'); }, 'primary', c.id));
      /* U1: the same verb as the menu's, so the same name; the menu leaves its own out here */
      /* c-601: a card that never started has no house to resume; Retry is what starts it */
      if (!held && c.session_id) put('resume', K.actionBtn('Resume house', { verb: 'house.resume', id: c.id }));
      put('retry', K.actionBtn('Retry', { verb: 'house.retry', id: c.id },
        { cls: c.session_id ? '' : 'primary', confirm: 'Start a fresh house on ' + c.id + '?' }));
      /* "Unblock" read as a resume; it starts nothing, and the name says so */
      put('unblock', K.actionBtn('Unblock only', { verb: 'unblock', id: c.id }));
    } else if (c.derived.regate) {
      /* r-19 (c-540): he sent this tracking card back with every slice done. It shows at
         review, since its slices are, but the drain waits for a slice to change before it
         closes it, and with all done none will. His tap brings it to review, and the drain
         closes it from there (c-649). */
      put('regate', K.actionBtn('Back to your gate', { verb: 'stage', id: c.id, stage: 'review',
        note: 'brought back to your gate from the deck: every slice is done' }, { cls: 'primary' }));
    } else if (c.derived.notice && !c.derived.archived) {
      /* A segment's notice closes when the segment stages it done; his answer to one is
         to put it away, and the segment files it again if the condition is still true. */
      put('dismiss', K.actionBtn('Dismiss', { verb: 'set', id: c.id, fields: { 'options.archived': true } }, { cls: 'primary' }));
    }
    if (K.talking(c)) put('end-discussion', K.actionBtn('End discussion', { verb: 'end_discussion', id: c.id }));
    /* The big card: any card that is not finished and has not been cut yet can be cut
       into slices. A card with children is already a tracking card, and `kb split` would
       refuse a second cut, so the button is absent rather than refused. A review card is
       never cut: it reviews one pull request (2026-09-24). */
    if (!tracking(c) && K.stageOf(c) !== 'done' && !c.derived.review) {
      put('split', btn('Split', function () { K.openSplit(c); }, '', c.id));
    }
    /* A review card takes its fields from its pull request: no Edit, and Review settings
       (in cardItems) holds the two it has (2026-09-24). */
    if (!c.derived.review) put('edit', btn('Edit', function () { K.openModal(c); }, '', c.id));
    return out;
  }

  /* The voice page, opened pinned to this card: the gateway reads `?connect=` on load and
     takes the hold, so the first thing he says goes to this house (V6). */
  function voiceUrl(c) { return K.voiceHref() + '?connect=' + encodeURIComponent(c.id); }

  /* Only a button that can act is drawn: a link the card does not have, a stop with no
     live house and a resume with no session are not greyed out, they are absent. */
  function cardItems(c) {
    var out = [], plan = K.planLink(c), output = K.outputLink(c), verbs = (K.spaceInfo().verbs || {}).card || [];
    var held = K.inTerminal(c), live = houseActs(c) && !keelOf(c);
    function put(key, node) { if (shownIn(key, c)) out.push(K.tipped(keyed(key, node), key, c)); }
    /* c-592: a Keel card is Bosun's, so its way in is the Bosun page, never a house */
    if (keelOf(c)) put('open-bosun', el('a', { class: 'btn', href: bosunPage(c) }, 'Open the Bosun page'));
    /* c-600: a shipping card's house answers review in its own session; the phase draws
       only the controls it justifies (ui.shipping.js) */
    if (K.stageOf(c) === 'shipping' && !keelOf(c) && K.shipping) { K.shipping.cardItems(c, put, btn); return out; }
    /* A held house has been STOPPED on purpose, by voice, so its app link cannot open: the
       pill says why, where the link would have been, and it goes when the hold does. */
    if (c.derived.voice_hold) put('on-voice', el('span', { class: 'pill accent' }, 'on voice'));
    /* U3: he dropped into it from a terminal, so nothing here resumes it behind him */
    if (held) put('in-terminal', el('span', { class: 'pill accent' }, 'in a terminal'));
    else if (live && c.options.app_link && K.houseOf(c)) put('open-app', btn('Open in Claude app', function () { K.openLink(c.options.app_link); }));
    /* "Talk to this house" opens voice already connected (V6); the turn itself is
       `house.converse`, which the gateway and the phone Harbor run through `keel converse`. */
    /* c-601: only where voice is installed on this machine; elsewhere the link opens nothing */
    if (live && c.session_id && K.voiceHere()) put('talk-voice', btn('Talk to this house', function () { K.openLink(voiceUrl(c)); }));
    if (c.links.story) put('story', btn(K.say(c.space, 'Open {ticket}'), function () { K.openLink(c.links.story); }));
    else putNeed(c, put, 'need-tracker', c.options && c.options.tracker_ref ? 'tracker' : null);
    /* lane RC: a review card's pull request is the colleague's, and a link is all it needs */
    if (c.derived.review && c.links.pr) put('open-pr', btn(K.say(c.space, 'Open {change_short}'), function () { K.openLink(c.links.pr); }));
    if (c.links.design_doc) put('design-doc', btn('Open design doc', function () { K.openLink(c.links.design_doc); }));
    if (plan) put('open-plan', btn(plan.label, function () { K.openPlan(plan.url); }));
    putCi(c, put);
    /* c-565: a cross-repo card has a pull request in each repo (`links.prs`), so Open output
       opens a sheet with one link per repo; one pull request opens as it always did */
    /* c-592: research's output is its result, on its own page; the gate row draws it there */
    if (research(c)) {
      if (resultLink(c) && K.gateOf(c) !== 'outcome') put('open-output', btn('Open result', function () { K.openPlan(resultLink(c)); }));
      if (K.gateOf(c) !== 'outcome') putNamed(c, put);
    }
    else if (pullsOf(c).length > 1) put('open-output', btn('Open output', function () { App.sheet = { kind: 'prs', id: c.id }; K.renderSheet(); }));
    else if (output) put('open-output', btn('Open output', function () { K.openLink(output); }));
    if (c.links.context) put('context', btn('View context', function () { K.openPlan(K.contextLink(c)); }));
    /* c-644 r2.F8: a done card whose house answered review keeps its comments page, read only */
    if (K.stageOf(c) === 'done' && (((c.options || {}).shipping || {}).told || []).length) {
      put('open-comments', btn('Open comments', function () { K.openPlan('/comments/' + c.id); }));
    }
    /* Hidden while the house is WORKING (N10): a resume of a busy session would copy it and
       stop the original, and the server refuses it anyway (E1). An idle one may be resumed.
       Hidden too while he is in it at a terminal (U3), and on a blocked card, whose gate
       row already draws the same verb under the same name (U1). c-604: not at an open plan
       gate either, where his answer is the gate's (Approve or Send back), and a bare resume
       would only have the house carry on without it. */
    if (live && c.session_id && !K.houseBusy(c) && !c.derived.voice_hold && !K.inTerminal(c) && K.gateOf(c) !== 'blocked' && K.gateOf(c) !== 'plan') put('resume-house', K.actionBtn('Resume house', { verb: 'house.resume', id: c.id }));
    /* V2-2: the same house back with NO turn, and opened in the Claude app. Absent where Open
       in Claude app already does it (a listed house whose link the card has), and wherever
       a resume would be refused (ui.tips.js `appResumable`). */
    if (live && K.appResumable(c)) put('resume-app', K.resumeAppBtn(c, 'Resume and open in app'));
    /* R6: his rotation, on demand. Same rule as Resume (the checkpoint turn is a resume),
       and absent while one is already under way. */
    if (live && rotateOn() && c.session_id && !K.houseBusy(c) && !c.derived.voice_hold && !held && !rotatingOf(c)) {
      put('rotate', K.actionBtn('Rotate session', { verb: 'house.rotate', id: c.id },
        { confirm: 'Rotate ' + c.id + ' into a fresh session? It writes a checkpoint first, then a new session carries on from it.' }));
    }
    /* lane RC: new commits on a pull request he reviewed; a new round on the same card */
    if (c.derived.review === 'new' && !c.blocked_reason) {
      put('rereview', K.actionBtn('Re-review', { verb: 'rereview', id: c.id }, { cls: 'primary' }));
    }
    /* lane GRP: a held review card waits for its story's other side; this ends the wait at once */
    if (c.derived.review === 'held') {
      put('review-now', K.actionBtn('Review now anyway', { verb: 'set', id: c.id,
        fields: { 'options.review_wait': null, 'options.review_alone': true } }, { cls: 'primary' }));
    }
    /* the command sheet IS the answer, so the toast says nothing on top of it */
    if (live) put('dropin', K.actionBtn('Drop in', { verb: 'dropin', id: c.id },
      { done: function (r) { K.showCommand(c.id, r.command, r.said); return ''; } }));
    verbs.forEach(function (v) {
      if (v.when && !K.valueAt(c, v.when)) return;
      put('verb-' + v.verb, K.actionBtn(v.label, { verb: 'adapter', space: c.space, route: 'card', action: v.verb, key: c.id },
        { done: function (r) { return r && r.output ? K.firstLine(r.output) : v.label + ' done'; } }));
    });
    flowMoves(c).forEach(function (m) {
      put('flow-' + m.id, K.actionBtn(m.label, { verb: 'flow.move', id: c.id, move: m.id },
        { done: function (r) { return (r && r.note) || m.label + ': the house was told'; } }));
    });
    /* both take a background session's id: a session in his terminal has none (U3). c-601:
       only the card's OWN session, listed live; a row the listing matched by name alone (an
       orphan of an earlier start) is not the session Stop and Logs act on. */
    if (K.houseOf(c) && K.houseOf(c).recorded !== false && !K.inTerminal(c)) {
      /* a read that opens a sheet: it is not the gate row, so it stays live */
      put('logs', btn('Logs', function (ev) { K.showLogs(c.id, ev.currentTarget); }));
      put('stop', K.actionBtn('Stop session', { verb: 'house.stop', id: c.id },
        { cls: 'crit', confirm: 'Stop the session on ' + c.id + '? Nothing else ends a live session.' }));
      /* c-607: only while the harness lists it idle; the server checks again at the tap */
      if (K.closeableIdle && K.closeableIdle(c)) put('close-idle', K.closeIdleBtn(c));
    } else if (c.lingering && K.stageOf(c) === 'done') {
      /* c-601 review: a done card whose own session the harness still lists: its log is the
         post-mortem, read only */
      put('logs', btn('Logs', function (ev) { K.showLogs(c.id, ev.currentTarget); }));
    }
    /* c-601 review: two live sessions named for the card (a double start's stale one), which
       a message by name cannot reach (`tellhouse.refuse_twins`): his tap stops the stale
       one, never the card's own */
    twinsOf(c).forEach(function (id) {
      put('stop-twin', K.actionBtn('Stop stale session ' + id, { verb: 'house.stop', id: c.id, twin: id },
        { cls: 'crit', confirm: 'Stop ' + id + ', the stale session also named ' + c.id + '? The card keeps its own.' }));
    });
    /* a tracking card is never startable, so assigning it would only move a stage nothing
       reads: its slices are the ones that run */
    if (c.stage === 'inbox' && !tracking(c) && !(c.derived.review && c.derived.notice) && c.derived.review !== 'held') {
      /* lane RC: a review card's Assign is his "Review" tap: it is what starts the review */
      put('assign', K.actionBtn(c.derived.review ? 'Review' : 'Assign', { verb: 'stage', id: c.id, stage: 'assigned' }, { cls: 'primary' }));
    }
    if (reviewSettable(c)) put('review-settings', btn('Review settings', function () { K.openReviewSettings(c); }, '', c.id));
    /* keyed by what they do, not by place, so each carries its own line */
    K.nextActions(c).forEach(function (b, i) { put(NEXT_KEYS[i], b); });
    backlogActions(c).forEach(function (b) { put(b.getAttribute('data-key'), b); });
    putWorker(c, put);      /* c-645 */
    /* lane RC: on a review card Archive is Dismiss review (2026-09-24), and a closed one's
       notice already draws its Dismiss in the gate row, so it is not drawn twice */
    if (!(c.derived.review && c.derived.notice && !c.derived.archived)) {
      put('archive', K.actionBtn(archiveLabel(c), { verb: 'set', id: c.id, fields: { 'options.archived': !c.derived.archived } }));
    }
    return out;
  }
  function twinsOf(c) { var h = K.houseOf(c); return (h && h.twins) || []; }
  function archiveLabel(c) {
    if (c.derived.review) return c.derived.archived ? 'Restore review' : 'Dismiss review';
    return c.derived.archived ? 'Unarchive' : 'Archive';
  }
  /* A review card's house is his to talk to only WHILE it reviews (2026-09-24): in the inbox
     there is none yet, at the gate the page (and its Ask) is where he answers it, and after
     posting Re-review is the way back in. Any other card: always. */
  function houseActs(c) { return !c.derived.review || c.derived.review === 'reviewing'; }
  /* Review settings (the model, his focus; the sheet is app/ui.reviews.js) while nothing is
     reviewing: in the inbox, at assigned before its house starts, and after posting, where
     they apply to the next Re-review. Never while it reviews or at the gate. */
  function reviewSettable(c) {
    var r = c.derived.review;
    if (!r || c.derived.archived) return false;
    if (r === 'waiting' || r === 'posted' || r === 'new') return true;
    return r === 'reviewing' && c.stage === 'assigned' && !c.session_id && !K.houseOf(c);
  }
  /* `K.nextActions` (app/ui.tree.js) draws Move to front first and Back in filing order
     second, always in that order */
  var NEXT_KEYS = ['next-front', 'next-filing'];
  /* THE DESK'S ONE ROW (V2-1): every action of the gate row and of the card, in their five
     groups (`GROUPS`, ui.tips.js), sticky under the title. It used to be the gate row there
     and a grid of about fourteen more buttons under the tree. */
  function deskActions(c) { return K.groupRow(c, gateActions(c).concat(cardItems(c)), 'pane'); }

  /* ---------- the phone's action row: three for the card's state, the rest behind one ----------
   * On the phone the pane led with about twelve buttons (six gate and card verbs, then six
   * full-width link rows) before a line of the card: c-302 at its plan gate showed its plan
   * at y 770 of 844. The phone now shows the CONTENT first (the plan, the gate's evidence,
   * the brief), then at most THREE actions picked for the card's state, and one More
   * actions that opens every other action in a sheet. The desk keeps its whole row and its
   * grid: it has the room, and nothing there comes before the content.
   *
   * The table is keyed by state and names actions by key, in the order they are shown; an
   * action the card does not have is simply skipped, so a state can never show more than
   * three and never shows a button that cannot act. */
  var PHONE_PRIMARY = {
    /* Open plan first: a plan he cannot reach in one tap is not one to approve */
    plan: ['open-plan', 'approve-plan', 'sendback'],
    /* c-605: the outcome's page first where it has one; three at most are drawn */
    outcome: ['open-outcome', 'approve-outcome', 'sendback', 'open-output'],
    /* c-592: research and the like: read the result, then Done or Send back with a note */
    result: ['open-result', 'approve-outcome', 'sendback'],
    blocked: ['answer', 'resume', 'retry'],
    /* c-592: a Keel card Bosun holds has no house: Unblock, and the Bosun page */
    held: ['open-bosun', 'unblock', 'edit'],
    /* c-592: a Keel card Bosun builds, and nothing waiting on him */
    keel: ['open-bosun', 'assign', 'open-plan'],
    notice: ['dismiss', 'edit'],
    /* c-521: an open ask of Bosun's, and nothing else waiting */
    ask: ['answer-ask', 'open-plan', 'open-output'],
    /* lane GRP: a held review card's Review now anyway leads; any other has none */
    inbox: ['review-now', 'assign', 'edit', 'archive'],
    /* a big card: its tree is the content above, and assigning it is the act */
    tracking: ['assign-tree', 'open-plan', 'edit'],
    /* r-19 (c-540): a tracking card he sent back with every slice done */
    regate: ['regate', 'open-plan', 'edit'],
    house: ['open-app', 'talk-voice', 'logs'],
    /* c-600: the house answers the reviewers in its session; Ship is his one act */
    /* c-653: the line where Ship would be, Ship; c-655: the hand-over beside them;
       then the way into the house */
    /* r-55 (c-723): the house's question leads, a line with its Answer, taking no place */
    shipping: ['ship-prepared', 'ship-why', 'ship', 'hand-over', 'open-app', 'resume-app', 'dropin', 'open-output'],
    'shipping-blocked': ['unblock', 'open-app', 'resume-app', 'dropin', 'open-output'],
    /* lane RC: new commits on a pull request he reviewed */
    rereview: ['rereview', 'open-pr', 'review-settings'],
    /* lane RC, 2026-09-24: a review waiting for his Review tap, and one he has posted */
    'review-waiting': ['assign', 'open-pr', 'review-settings'],
    reviewed: ['open-pr', 'review-settings', 'open-output'],
    other: ['open-plan', 'open-output', 'resume-house']
  };
  var PHONE_MAX = 3;
  /* what the card's space has not set up (c-631) leads the row in every state: a line, so
     it takes none of the three places (c-662: no state named them, and More drew none) */
  var PHONE_NEEDS = ['need-codehost', 'need-tracker'];
  function phoneState(c) {
    if (K.stageOf(c) === 'shipping' && !keelOf(c)) return c.blocked_reason ? 'shipping-blocked' : 'shipping';
    var k = K.needKind(c);
    /* a dismissed notice is history: it reads as the card it is, not as a notice */
    if (k === 'notice' && c.derived.archived) k = null;
    if (k === 'outcome' && research(c)) return 'result';
    if (k === 'blocked' && keelOf(c)) return 'held';
    if (k) return k;
    if (keelOf(c)) return 'keel';
    if (c.derived.review === 'new') return 'rereview';
    if (c.derived.review && c.stage === 'inbox') return 'review-waiting';
    if (c.derived.review && c.stage === 'done') return 'reviewed';
    if (c.stage === 'inbox' && !tracking(c)) return 'inbox';
    if (c.derived.regate) return 'regate';
    if (tracking(c)) return 'tracking';
    if (K.stageOf(c) === 'shipping') return 'shipping';
    if (c.derived.review === 'new') return 'rereview';
    return K.houseOf(c) ? 'house' : 'other';
  }
  /* {primary, rest}: the state's picks in the table's order, then every other action in
     the order the desk draws them */
  function phoneSplit(c) {
    var tree = K.assignTreeButton ? K.assignTreeButton(c) : null;
    var all = gateActions(c).concat(tree && shownIn('assign-tree', c) ? [K.tipped(keyed('assign-tree', tree), 'assign-tree', c)] : [], cardItems(c)), byKey = {};
    all.forEach(function (n) { byKey[n.getAttribute('data-key')] = n; });
    /* three ACTIONS at most: a line that is a fact about the card (c-653, why there is no
       Ship) is drawn with them and takes none of the three places */
    var taken = 0;
    var primary = PHONE_NEEDS.concat(PHONE_PRIMARY[phoneState(c)]).map(function (k) { return byKey[k]; })
      .filter(Boolean).filter(function (n) { return n.tagName !== 'BUTTON' && n.tagName !== 'A' ? true : taken++ < PHONE_MAX; });
    return { primary: primary, rest: all.filter(function (n) { return primary.indexOf(n) < 0; }) };
  }
  function phoneActions(c) {
    var split = phoneSplit(c);
    return split.primary.concat(split.rest.length ? [K.tipped(keyed('more', btn('More actions', function () {
      App.sheet = { kind: 'actions', id: c.id }; K.renderSheet();
    }, 'more')), 'more', c)] : []);
  }
  /* The overflow, as a sheet. A tap on anything in it closes the sheet first, so a verb's
     answer lands on the pane (its toast, the header's pulse) and a control that opens its
     own sheet or the dialog is not drawn under this one. */
  function closingFirst(node) {
    var fn = node.onclick;
    if (!fn) return node;
    var wrapped = function (ev) {
      if (App.sheet && App.sheet.kind === 'actions') { App.sheet = null; K.renderSheet(); }
      return fn.call(this, ev);
    };
    node.onclick = wrapped;
    if (node._on) node._on.onclick = wrapped;
    return node;
  }
  function actionsSheet(s) {
    var c = K.byId(s.id);
    if (!c) return el('div', { class: 'sheet' });
    return el('div', { class: 'sheet', 'data-key': 'sheet-actions' },
      el('div', { class: 'sheet-head' },
        el('button', { onclick: function () { App.sheet = null; K.renderSheet(); } }, '‹ close'),
        el('span', { class: 'spacer' }),
        el('span', { class: 'mono t11 ink2', text: c.id + ' · more actions' })),
      el('div', { class: 'sheet-body' },
        el('div', { class: 'title', text: c.title }),
        /* under the desk's group headings, each with its line under its name (V2-1) */
        K.groupedList(c, phoneSplit(c).rest.map(closingFirst), 'more')));
  }
  K.actionsSheet = actionsSheet;

  /* c-565: the card's pull requests, one per repo, as the adapter linked them */
  function pullsOf(c) { return (c.links && c.links.prs) || []; }
  /* Open output on a cross-repo card: one link per pull request, each opened in a new tab */
  function prsSheet(s) {
    var c = K.byId(s.id);
    if (!c) return el('div', { class: 'sheet' });
    var close = function () { App.sheet = null; K.renderSheet(); };
    return el('div', { class: 'sheet', 'data-key': 'sheet-prs' },
      el('div', { class: 'sheet-head' },
        el('button', { onclick: close }, '\u2039 close'),
        el('span', { class: 'spacer' }),
        el('span', { class: 'mono t11 ink2', text: c.id + ' \u00b7 ' + K.term(c.space, 'changes') })),
      el('div', { class: 'sheet-body' },
        el('div', { class: 'title', text: c.title }),
        pullsOf(c).map(function (p) {
          return el('a', { class: 'btn wide', 'data-key': 'pr-' + p.repo, href: p.url, target: '_blank',
            rel: 'noopener', onclick: close }, p.repo + ' #' + p.pr);
        })));
  }
  K.prsSheet = prsSheet; K.pullsOf = pullsOf;

  /* The deck cannot run the board's backlog verb, so the override rides on the card as a
     plain field: `options.backlog` is `backlog`, `active`, or null for the date rule. */
  function backlogBody(c, value) { return { verb: 'set', id: c.id, fields: { 'options.backlog': value } }; }
  function backlogActions(c) {
    var out = [], override = c.derived.backlog_override;
    if (c.derived.backlog) out.push(keyed('backlog-active', K.actionBtn('Move to active', backlogBody(c, 'active'))));
    else if (c.derived.outcome_gate) out.push(keyed('backlog-send', K.actionBtn('Send to backlog', backlogBody(c, 'backlog'))));
    if (override) out.push(keyed('backlog-auto', K.actionBtn('Back to auto', backlogBody(c, null))));
    return out;
  }

  /* ---------- a block long enough to need a decision ----------
   * On the DESK a long block is a 320px window with a scrollbar of its own. It keeps the
   * offset he left it at because the morph keeps the NODE: the block is keyed, so a pass
   * that changes the text around it writes the text and nothing else.
   *
   * On the PHONE the page is the scroller, and a scroller inside it is the annoyance the
   * audit recorded (`<install>/history/docs/deck-mobile-audit.md`, recommendation 3). The block is clipped
   * to a preview instead, with one Show all that expands it into the page's own scroll.
   * Expanded is the one thing here the morph cannot keep, because no part of the built
   * tree says it: it lives in the pane's flag map (`K.keepFlag`, ui.core.js). */
  var PREVIEW_CHARS = 400;
  function readingBlock(key, text, cls) {
    var body = String(text || ''), open = K.keepFlag(key), desk = K.isDesk();
    var reading = el('div', { class: 'reading' + (cls ? ' ' + cls : ''), 'data-key': key, text: body });
    if (desk || body.length <= PREVIEW_CHARS) return reading;
    if (!open) reading.className += ' clip';
    return el('div', { class: 'psec', 'data-key': key }, reading,
      el('button', { class: 'btn sm showall', onclick: function () { K.keepFlag(key, !open); K.renderBody(); } },
        open ? 'Show less' : 'Show all'));
  }
  /* A section that is a list of nodes rather than one: the wrapper carries the pane's own
     column gap, so wrapping it to key it does not close the gaps inside it. */
  function section(key, build) {
    return el('div', { class: 'psec', 'data-key': key }, build());
  }

  /* The evidence under the gate that is open. The PLAN gate has none of its own: the plan
     block above it says what the deck knows about the plan, and Open plan opens the plan
     itself, full screen. It used to be an iframe of the live lavish session, which the poll
     reloaded every five seconds and which put lavish's whole chrome (a bar, an annotate
     switch, a conversation panel) inside a box a few hundred pixels tall. */
  function gateEvidence(c) {
    K.keepPane('card:' + c.id);
    var g = K.gateOf(c), d = K.App.detailFor === c.id ? K.App.detail : null, parts = [];
    /* c-678: a block Keel can read is said as a stuck line, what happened and its fix,
       above the block's own words (app/ui.stuckcard.js, keel/stuckcards.py) */
    if (c.stuck && K.stuckCard) parts.push(K.stuckCard(c));
    if (g === 'outcome' && tracking(c)) {
      /* lane X: a tracking card has no output or PR body of its own; its evidence is that
         every slice is done, and the tree above lists them */
      parts.push(el('div', { class: 'label', 'data-key': 'slices-label', text: 'slices' }));
      parts.push(readingBlock('slices', (c.derived.tracking_tally || 'every slice done') +
        K.say(c.space, '. Each landed or was published on its own; approving closes the {ticket}.')));
    } else if (g === 'outcome' && c.options && c.options.review_key) {
      /* FC-8: a review card posts comments on someone else's pull request; it has no PR body
         of its own, so its evidence is where the findings are */
      parts.push(el('div', { class: 'label', 'data-key': 'review-label', text: 'review' }));
      parts.push(readingBlock('review', 'The findings wait on the outcome page: Approve posts the ones you keep at ' +
        'their lines, the summary and the verdict.'));
    } else if (g === 'outcome' && research(c)) {
      /* c-592: the result is the evidence, read on its own page (Open result); here, where
         it is and what the house said it stands on, never a PR body */
      var link = resultLink(c), file = namedOutput(c);
      file = file && file !== link ? file : null;
      parts.push(el('div', { class: 'row-chips', 'data-key': 'output' }, el('span', { class: 'label', text: 'result' }),
        link ? el('a', { href: link, target: '_blank', rel: 'noopener',
          text: link.indexOf('/outcome/') === 0 ? 'its own page' : String(c.output_ref || link).split('/').pop() })
          : el('span', { class: 'ink2', text: c.output_ref || 'none' }),
        /* c-719: and the file its output names, by name, when that is not the result itself */
        file ? el('a', { href: file, target: '_blank', rel: 'noopener', 'data-key': 'named', text: namedWord(file).slice(5) }) : null));
      parts.push(el('div', { class: 'label', 'data-key': 'result-said-label', text: 'what it says' }));
      parts.push(readingBlock('result-said', d ? (d.stands || d.findings || c.last_said || d.pr_body || d.away || 'the house left no summary') : 'loading\u2026'));
    } else if (g === 'outcome') {
      if (c.unpublished) {
        parts.push(el('div', { class: 'label', 'data-key': 'unpublished-label', text: 'not publishable' }));
        parts.push(el('div', { class: 'blockbox', 'data-key': 'unpublished', text: c.unpublished }));
      }
      /* c-678: a repo with no test command lands with no test run, and the card says so
         before the tap (`spaces.<name>.untested`, keel/repocommands.py) */
      var lands = (K.App.data.spaces || {})[c.space] || {};
      var first = String(c.repo || '').split(',')[0].trim();
      /* review r2.F3: a repo whose file changed since it was adopted or saved will not land
         at all (`spaces.<name>.unlandable`), and that is said instead */
      var wont = (lands.unlandable || {})[first];
      var why = wont ? '' : (lands.untested || {})[first];
      if (wont) {
        parts.push(el('div', { class: 'label', 'data-key': 'refused-label', text: 'will not land' }));
        parts.push(el('div', { class: 'blockbox', 'data-key': 'lands-refused', text: wont }));
      }
      if (why) {
        parts.push(el('div', { class: 'label', 'data-key': 'untested-label', text: 'lands untested' }));
        parts.push(el('div', { class: 'blockbox', 'data-key': 'lands-untested', text: why }));
      }
      parts.push(el('div', { class: 'row-chips', 'data-key': 'output' }, el('span', { class: 'label', text: 'output' }),
        c.links.output ? el('a', { href: c.links.output, target: '_blank', rel: 'noopener', text: c.output_ref })
          : el('span', { class: 'ink2', text: c.output_ref || 'none' })));
      parts.push(el('div', { class: 'label', 'data-key': 'pr-body-label', text: 'PR body' }));
      parts.push(readingBlock('pr-body', d ? (d.pr_body || d.stands || c.last_said || d.away || 'context.md has no PR body yet') : 'loading…'));
    } else if (!g && c.derived.notice && !c.derived.archived) {
      parts.push(el('div', { class: 'label', 'data-key': 'notice-label', text: 'notice' }));
      parts.push(readingBlock('notice', K.fullBrief(c) || c.title));
    } else if (g === 'blocked') {
      parts.push(el('div', { class: 'label', 'data-key': 'blocked-label', text: 'blocked' }));
      parts.push(el('div', { class: 'blockbox', 'data-key': 'blocked', text: c.blocked_reason }));
      if (c.last_said && c.blocked_reason.indexOf(c.last_said) < 0) {
        parts.push(el('div', { class: 'label', 'data-key': 'last-said-label', text: 'last output' }));
        parts.push(readingBlock('last-said', c.last_said, 'mono'));
      }
    }
    return parts;
  }

  /* The chip beside `stage`. A tracking card's stage is its children's, so the chip said
     `building` in the warn face a working house wears; it says what the card is instead,
     and the words line above the grid carries the slice counts. */
  function stagePill(c) {
    if (tracking(c)) return K.pill('tracking', 'tracking');
    return K.pill(K.stageOf(c), K.stageOf(c));
  }
  /* What the session row says: the listed house's status, else that it is not listed. */
  function sessionWord(c) {
    var h = K.houseOf(c);
    return h ? h.status || '' : 'not listed';
  }
  /* Option keys the facts grid does not list raw: each is drawn elsewhere or is the
     board's own bookkeeping. `provenance` (lane B, keel/cardspec.py) is a per-field map
     that would read as one row of JSON; its visible form is a chip that comes later. */
  var HIDDEN_OPTIONS = ['archived', 'backlog', 'discussion', 'record_nudged', 'branch', 'worktree',
    'pr', 'segment', 'asks', 'add_dirs', 'tools', 'drop', 'provenance', 'dropin_hold', 'prs', 'worktrees',
    /* a review card's own bookkeeping (lanes RC and GRP): what posting recorded as it went,
       the members' checkouts, and the ledgers carried in; its facts are drawn below */
    'review_posting', 'review_worktrees', 'review_carried', 'review_ledger',
    /* retired in c-593: an old card may still carry them, and nothing reads them */
    'driver', 'grant',
    /* c-592: Bosun's batch and branch are drawn in its view of the card */
    'bosun'];
  /* FC-9: NO RAW JSON in the facts grid, for any card kind. A review card's options are
     drawn as the facts they are; any other object is flattened to its plain values, or left
     out when it has none. */
  function shortHead(head) {
    return String(head || '').split(',').map(function (part) {
      var at = part.lastIndexOf('@');
      return at >= 0 ? part.slice(0, at + 1) + part.slice(at + 1, at + 9) : part.slice(0, 8);
    }).join(', ');
  }
  var READABLE = {
    review_pr: function (v, c) {
      var out = [];
      if (v.author) out.push(['author', String(v.author)]);
      if (v.url) out.push([K.term(c.space, 'change'), el('a', { href: v.url, target: '_blank', rel: 'noopener', text: v.title || v.url })]);
      if (v.created) out.push(['raised', K.ago(v.created) + ' ago']);
      if (v.head) out.push(['head', shortHead(v.head)]);
      return out;
    },
    review_focus: function (v) { return [['focus', typeof v === 'object' ? String(v.text || '') : String(v)]]; },
    review_members: function (v) { return [['members', (v || []).map(function (m) { return m.label || m.repo + '#' + m.pr; }).join(', ')]]; },
    review_heads: function (v) { return [['heads', Object.keys(v || {}).map(function (k) { return k + ' ' + shortHead(v[k]); }).join(', ')]]; },
    review_posted: function (v) {
      return [['posted', [v.verdict, v.round ? 'round ' + v.round : '', v.head ? 'at ' + shortHead(v.head) : '',
                          v.at ? K.ago(v.at) + ' ago' : ''].filter(Boolean).join(' \u00b7 ')]];
    },
    review_new: function (v) { return [['new commits', v && v.head ? 'at ' + shortHead(v.head) : 'yes']]; },
    review_wait: function (v, c) { return [['held', reviewWaitLine(c) || 'waiting for its other side']]; }
  };
  function flatFact(v) {
    if (Array.isArray(v)) {
      if (v.every(function (x) { return x === null || typeof x !== 'object'; })) return v.join(', ');
      var labels = v.map(function (x) { return x && typeof x === 'object' ? x.label || '' : String(x); }).filter(Boolean);
      return labels.length === v.length ? labels.join(', ') : v.length + (v.length === 1 ? ' entry' : ' entries');
    }
    return Object.keys(v).map(function (k) {
      var x = v[k];
      if (x === null || x === undefined || x === '') return '';
      if (Array.isArray(x)) return x.every(function (y) { return typeof y !== 'object'; }) ? k + ' ' + x.join(', ') : '';
      return typeof x === 'object' ? '' : k + ' ' + x;
    }).filter(Boolean).join(' \u00b7 ');
  }
  function optionFacts(c, k, v) {
    if (READABLE[k]) return v === null || v === undefined ? [] : READABLE[k](v, c);
    if (v === null || v === undefined) return [];
    if (typeof v !== 'object') return [[k, typeof v === 'boolean' ? (v ? 'yes' : 'no') : String(v)]];
    var said = flatFact(v);
    return said ? [[k, said]] : [];
  }
  /* WHO WORKS IT (c-645): Bosun or a house, and who approves, in one line */
  function workerLine(c) {
    var bosun = c.derived && c.derived.worker === 'bosun';
    var lands = !!((K.App.data || {}).config || {}).builder && ((K.App.data.config.builder || {}).lands);
    var on = K.landsOn(c.space, c.repo);       /* the card's own landing branch, or none named */
    return bosun ? (lands ? 'Bosun: approves and lands it' + (on ? ' on ' + on : '') + '; the deploy is yours' : 'Bosun: you approve its plan and outcome')
      : 'a house: you approve its gates';
  }
  K.workerLine = workerLine;
  /* His move of a card between workers, before anything starts on it (the board checks the
     same: inbox or assigned, no session, Bosun only where he may build) */
  var WORKER_STAGES = ['inbox', 'assigned'];
  function putWorker(c, put) {
    if (!c.derived || !c.derived.worker_eligible || c.session_id || WORKER_STAGES.indexOf(c.stage) < 0) return;
    if (c.derived.tracking) return;      /* each slice has its own worker (r1.F8) */
    if ((c.options || {}).claim) return;      /* a drain is starting it (r2.F2) */
    var toHouse = c.derived.worker === 'bosun';
    put('worker', K.actionBtn(toHouse ? 'Give to a house' : 'Give to Bosun',
      { verb: 'set', id: c.id, fields: { 'options.worker': toHouse ? 'house' : 'bosun' } },
      { done: function () { return toHouse ? c.id + ' is a house\'s now' : c.id + ' is Bosun\'s now'; } }));
  }
  K.putWorker = putWorker;
  function facts(c) {
    var rows = [['stage', stagePill(c)], ['worker', workerLine(c)], ['autonomy', c.autonomy], ['repo', c.repo || 'errand'],
                ['topic', c.topic || ''], ['model', c.model || 'default']];
    if (c.blocked_reason) rows.push(['blocked', K.firstLine(c.blocked_reason)]);
    if (waitingOf(c)) rows.push(['waiting', waitingOf(c)]);
    /* how long it has sat at its outcome gate is the whole of what the date rule decides
       on, so the line that says a card has backlogged says the number too */
    if (c.derived.backlog_since) rows.push(['at ' + K.stageOf(c), K.ago(c.derived.backlog_since) + ' at the gate']);
    if (c.derived.backlog) rows.push(['backlog', c.derived.backlog_override ? 'held by you' : 'by date']);
    if (c.derived.backlog_override) rows.push(['backlog set to', c.derived.backlog_override]);
    if (K.talking(c)) rows.push(['discussion', 'open on the plan surface']);
    if (c.parent) rows.push(['parent', c.parent]);
    if (c.after) rows.push(['after', c.after]);
    K.spaceInfo().options.forEach(function (o) {
      if (o.stored !== 'options' || !(o.key in c.options)) return;
      var v = c.options[o.key];
      rows.push([o.label.toLowerCase(), typeof v === 'boolean' ? (v ? 'yes' : 'no') : String(v)]);
    });
    Object.keys(c.options).forEach(function (k) {
      if (HIDDEN_OPTIONS.indexOf(k) >= 0) return;
      if (K.spaceInfo().options.some(function (o) { return o.key === k; })) return;
      optionFacts(c, k, c.options[k]).forEach(function (r) { rows.push(r); });
    });
    if (c.options.branch) rows.push(['branch', c.options.branch]);
    /* SH-10: a card's pull request per repo, one row, rather than a line of JSON */
    var prs = c.options.prs || {};
    if (Object.keys(prs).length) rows.push([K.term(c.space, 'changes'), Object.keys(prs).map(function (r) { return r + ' #' + (prs[r] || {}).pr; }).join(', ')]);
    if (c.session_id) rows.push(['session', c.session_id.slice(0, 8) + ' · ' + sessionWord(c)]);
    rows.push(['created', K.ago(c.created_at) + ' ago']);
    /* one row is two nodes, so both carry the row's own key: the grid is a flat child
       list and a row that appears or goes would otherwise shift every pair after it */
    return el('dl', { class: 'kv-grid' }, rows.map(function (r) {
      return [el('dt', { 'data-key': 'k:' + r[0], text: r[0] }), el('dd', { 'data-key': 'v:' + r[0] }, r[1])];
    }));
  }

  /* the quick topic line the old board had, beside the dialog's own Topic field: the
     grouping is changed often enough that it should not need the form */
  function topicEditor(c) {
    return el('div', { class: 'actions', 'data-key': 'topic' }, el('span', { class: 'label', text: 'topic' }),
      el('input', { type: 'text', 'data-fk': 'topic', placeholder: 'a word to group by', value: c.topic || '',
        onkeydown: function (ev) {
          if (ev.key !== 'Enter') return;
          var value = ev.target.value;
          K.act({ verb: 'set', id: c.id, fields: { topic: value || null } },
            function () { return value ? 'topic is ' + value : 'topic cleared'; }, ev.currentTarget);
        } }));
  }

  function notes(c) {
    var d = K.App.detailFor === c.id ? K.App.detail : null;
    var rows = d ? d.events.filter(function (e) { return e.kind === 'note'; }).slice(-8).reverse() : [];
    return [
      el('span', { class: 'label', 'data-key': 'notes-label', text: 'House notes' }),
      el('div', { class: 'notes', 'data-key': 'notes-rows' }, rows.length ? rows.map(function (e) {
        return el('div', { class: 'note-row', 'data-key': e.at + '\u00b7' + e.actor },
          el('span', { class: 'at', text: K.clock(e.at) }),
          el('span', { class: 'who', text: e.actor }), el('span', { class: 'x', text: e.text || '' }));
      }) : el('div', { class: 'empty', text: d ? 'no note on this card yet' : 'loading…' })),
      el('div', { class: 'actions', 'data-key': 'note-field' }, el('input', { type: 'text', 'data-fk': 'note', placeholder: 'add a note, Enter to save',
        onkeydown: function (ev) {
          if (ev.key !== 'Enter' || !ev.target.value) return;
          K.act({ verb: 'note', id: c.id, text: ev.target.value }, null, ev.currentTarget);
        } }))
    ];
  }

  /* A slice says what it is a slice of, and opens it: the way back up from a child card
     to the big card it was cut from. */
  function parentLine(c) {
    if (!c.parent) return null;
    var p = K.byId(c.parent), wait = waitsFor(c);
    return el('div', { class: 'actions sliceof', 'data-key': 'sliceof' },
      el('button', { class: 'btn sm', onclick: function () { K.select(c.parent); } }, 'slice of ' + c.parent),
      p ? el('span', { class: 'ink2 ellip', text: p.title }) : null,
      wait ? el('span', { class: 'sw wait', text: wait }) : null);
  }

  function timeline(c) {
    var d = K.App.detailFor === c.id ? K.App.detail : null;
    if (!d) return el('div', { class: 'empty', text: 'loading events…' });
    var events = App.allEvents ? d.events : d.events.slice(-12);
    return [el('div', { class: 'row-chips', 'data-key': 'events-head' }, el('span', { class: 'label', text: 'Events · ' + d.events.length }), el('span', { class: 'spacer' }),
      d.events.length > 12 ? el('button', { class: 'btn sm', onclick: function () { App.allEvents = !App.allEvents; K.renderBody(); } }, App.allEvents ? 'last 12' : 'all') : null),
    el('div', { class: 'timeline', 'data-key': 'timeline' }, events.slice().reverse().map(function (e) {
      var text = e.text || '';
      if (e.kind === 'stage' && e.data) text = e.data.from + ' → ' + e.data.to + (text ? ': ' + text : '');
      if (e.kind === 'hook' && e.data) text = (e.data.hook || 'hook') + (e.data.stop_blocked ? ' (nudged)' : '') + (e.data.payload && e.data.payload.last_assistant_message ? ': ' + K.firstLine(e.data.payload.last_assistant_message) : '');
      if (e.kind === 'set' && e.data) text = Object.keys(e.data).map(function (k) { return k + '=' + JSON.stringify(e.data[k]); }).join(' ');
      if (e.kind === 'approve' && e.data) text = e.data.gate + ' gate' + (e.data.published && e.data.published.published !== 'nothing' ? ', published' : '') + (e.text ? ': ' + e.text : '');
      return el('div', { class: 'tl', 'data-key': e.at + '\u00b7' + e.kind + '\u00b7' + e.actor },
        el('span', { class: 'at', text: K.clock(e.at) }), el('span', { class: 'k k-' + e.kind, text: e.kind }),
        el('span', { class: 'x', title: e.actor + ' ' + e.at, text: text }));
    }))];
  }

  function headLine(c) {
    var bits = [c.id];
    if (c.options.tracker_ref) bits.push(c.options.tracker_ref);
    if (c.topic) bits.push(c.topic);
    if (c.derived.archived) bits.push('archived');
    return bits.join(' · ');
  }
  /* ---------- the plan, said rather than framed ----------
   * What the deck knows about the plan, in one block: its title, where it stands, and when
   * it was last touched. The number of decisions the plan is waiting on is NOT here: that
   * count lives inside lavish's own session, the deck does not carry it, and fetching it
   * would be the deck reading another tool's state to print a number on a poll.
   *
   * The title is the plan document's own first heading when the deck is carrying the text
   * (a markdown plan, through `/api/card/<id>`), and the card's title when it is not (an
   * html surface, which the deck links rather than reads). */
  function planTitle(c, d) {
    var head = /^#\s+(.+)$/m.exec((d && d.plan_text) || '');
    return head ? head[1].trim() : c.title;
  }
  function planEvent(e) {
    if (e.kind === 'approve' && e.data && e.data.gate === 'plan') return true;
    return e.kind === 'set' && e.data && 'plan_ref' in e.data;
  }
  /* The file's own mtime when the deck could stat it, and the newest event that moved the
     plan when it could not (an http plan_ref has no mtime to read). */
  function planTouched(c, d) {
    if (d && d.plan_at) return 'last touched ' + K.ago(d.plan_at) + ' ago';
    var events = d ? d.events.filter(planEvent) : [];
    if (events.length) return 'last touched ' + K.ago(events[events.length - 1].at) + ' ago';
    return 'when it was last touched is not recorded';
  }
  function planBlock(c) {
    if (!c.plan_ref) return null;
    var d = K.App.detailFor === c.id ? K.App.detail : null, plan = K.planLink(c);
    return el('div', { class: 'planblock', 'data-key': 'plan' },
      el('div', { class: 'row-chips' }, el('span', { class: 'label', text: 'plan' }),
        word(planWord(c), 'plan'),
        plan && plan.live ? K.pill('live', 'talk') : null),
      el('div', { class: 't', text: planTitle(c, d) }),
      el('div', { class: 'mono t11 ink2', text: planTouched(c, d) }));
  }

  /* EVERY BOARD THIS CARD HAS, SAID ON THE CARD (2026-09-21). A board sits at one of two
     levels: a house's, which is this card's, or Harbor's, which belongs to no card. The
     Board route says so with a chip; this is the same fact on the card's own pane.

     A CARD HAS AS MANY BOARDS AS IT HAS PICTURES. "a user flow diagram and then a database
     schema diagram both belong to the same story but are different, and the node cap would
     hamper cramming them into one." So this lists all of them, newest first, with the live
     one marked (it is the one the next push lands on); it used to show the newest and a
     count, which was the shape of a card having ONE board and some history. */
  function boardRow(c, b) {
    return el('button', { class: 'boardrow' + (b.live && !b.closed ? ' live' : ''),
      'data-key': b.id, onclick: function () { K.goBoard(b.id, null, false); } },
      el('div', { class: 'row-chips' },
        el('span', { class: 'bchip space-' + c.space, text: b.id }),
        b.live && !b.closed ? K.pill('live', 'talk') : null,
        b.closed ? el('span', { class: 'bchip', text: 'closed' }) : null,
        el('span', { class: 'spacer' }),
        el('span', { class: 'mono t11 ink3',
          text: b.nodes + ' nodes \u00b7 ' + b.attachments + ' attached' })),
      el('div', { class: 't ellip', text: b.title || 'Untitled board' }));
  }

  function boardBlock(c) {
    var d = K.App.detailFor === c.id ? K.App.detail : null;
    var b = d && d.board;
    if (!b) return null;
    var rows = b.boards || [b];
    return el('div', { class: 'planblock boardblock', 'data-key': 'board' },
      el('div', { class: 'row-chips' }, el('span', { class: 'label', text: 'boards' }),
        el('span', { class: 'spacer' }),
        el('span', { class: 'mono t11 ink3',
          text: rows.length + (rows.length === 1 ? ' board' : ' boards') })),
      el('div', { class: 'boardrows' }, rows.map(function (row) { return boardRow(c, row); })));
  }

  /* THE CARD'S FILES (c-719): every markdown file its house wrote beyond the plan and the
     record (`deckstate.detail`'s `files`, keel/cardfiles.py), each opening in the viewer's
     rich renderer, the way the plan and the outcome do. */
  function filesBlock(c) {
    var d = K.App.detailFor === c.id ? K.App.detail : null;
    var files = (d && d.files) || [];
    if (!files.length) return null;
    return el('div', { class: 'planblock filesblock', 'data-key': 'files' },
      el('div', { class: 'row-chips' }, el('span', { class: 'label', text: 'files' }),
        el('span', { class: 'spacer' }),
        el('a', { class: 'mono t11', href: '/files/' + c.id, target: '_blank', rel: 'noopener',
          text: files.length + (files.length === 1 ? ' file' : ' files') })),
      el('div', { class: 'filerows' }, files.map(function (f) {
        return el('button', { class: 'boardrow', 'data-key': 'f:' + f.name, onclick: function () { K.openPlan(f.url); } },
          el('div', { class: 'ellip mono', text: f.name }));
      })));
  }

  /* The frame (the head with its close, the sticky action row, the sections under it) is
     `K.paneFrame`, shared with the Reviews pane; what goes in it is this card's own.
     EVERY SECTION IS KEYED, so a section that appears or goes (a plan block on a card
     that just got a plan, the slice list) moves nothing around it: the morph matches the
     rest by key rather than by position, and each one is the same node, holding the same
     scroll, from one pass to the next. */
  /* ---------- a Keel card: Bosun builds it (c-592, keel/bosuncards.py) ----------
     A personal card with a repo is Bosun's to build (`derived.bosun`), never a house's, so it
     wears the Keel / Bosun label wherever it is listed and says Bosun's state
     (`derived.keel_card.state`) in place of the house, plan and outcome words. Its pane is
     Bosun's view of it: the state, the batch and branch, the sha it landed as, and the way
     to the Bosun page. What replaced the driving switches, the grant, Bosun's note and the
     May / May not panel (c-522), none of which a card Bosun builds reads. */
  function keelOf(c) { return c.derived && c.derived.bosun ? c.derived.keel_card || {} : null; }
  function keelChip(c) {
    return keelOf(c) ? el('span', { class: 'kchip', title: 'a Keel card: Bosun builds it' },
      el('span', { class: 'bmark', 'aria-hidden': 'true' }), 'Keel \u00b7 Bosun') : null;
  }
  /* `next` is the STATE's name (keel/bosuncards.py: landed, not yet live); its word names the
     card's own landing branch (`K.landsOn`, c-665), or none where it is not known */
  var KEEL_STATES = { plan: ['plan waiting for you', 'acc'], queued: ['queued', 'plain'],
                      building: ['building', 'acc'], next: ['landed, not live', 'good'], live: ['live', 'good'] };
  function keelWord(c) {
    var k = keelOf(c), s = k && KEEL_STATES[k.state], on = k && k.state === 'next' && K.landsOn(c.space, c.repo);
    return s ? { text: on ? 'on ' + on : s[0], cls: s[1] } : null;
  }
  /* what a Keel card says where another says its three words: a hold and Bosun's ask first,
     since those are his, then where Bosun has it */
  function keelWords(c) {
    return [c.blocked_reason ? word({ text: 'held', cls: 'crit' }, 'bosun') : null,
      c.derived.ask ? word({ text: 'Bosun asks', cls: 'acc' }, 'bosun') : null,
      word(keelWord(c), 'bosun')].filter(Boolean);
  }
  /* Where Bosun said it landed when it moved the card to done ("landed on <branch> as
     <sha>"), from the card's own notes once its events are loaded: the note's own words. */
  function landedAs(c) {
    var d = K.App.detailFor === c.id ? K.App.detail : null, said = null;
    (d ? d.events : []).forEach(function (e) {
      var m = e.kind === 'stage' || e.kind === 'note' ? /landed on (\S+) as ([0-9a-f]{7,40})/.exec(e.text || '') : null;
      if (m) said = 'on ' + m[1] + ' as ' + m[2].slice(0, 8);
    });
    return said;
  }
  /* Where on the Bosun page this card is: Now when it waits on him, else Queue. */
  function bosunPage(c) { return c.derived.needs_you ? '/console' : '/console/queue'; }
  function keelSection(c) {
    var k = keelOf(c);
    if (!k) return null;
    var batch = (c.options || {}).bosun || {}, landed = landedAs(c), rows = [];
    if (batch.batch || batch.branch) rows.push(['batch', [batch.batch, batch.branch].filter(Boolean).join(' \u00b7 ')]);
    if (landed) rows.push(['landed', landed]);
    rows.push(['filed by', k.filed_by === 'bosun' ? 'Bosun' : 'you']);
    /* the state is the head's words line, and Open the Bosun page is in the action row */
    return el('div', { class: 'keelview', 'data-key': 'keel' },
      el('div', { class: 'row-chips' }, keelChip(c), el('span', { class: 'ink2 t11', text: 'Bosun builds this card' })),
      el('dl', { class: 'kv-grid' }, rows.map(function (r) {
        return [el('dt', { 'data-key': 'k:' + r[0], text: r[0] }), el('dd', { 'data-key': 'v:' + r[0], text: r[1] })];
      })));
  }
  /* A personal card with no repo is research, a plan, an errand or a capture: a house does
     it and writes what it found, so no code pipeline applies (no review round, risk,
     landing, worktree or pull request) and its outcome gate is the user's read of the result.
     c-719: so is a research card on either side, known by its kind (`options.kind`, the
     work pack's and a personal card's `--file-kind`), whose approve publishes nothing: a
     work research card is never "PR body" or "This publishes it". */
  function research(c) {
    if (tracking(c) || c.derived.review || c.derived.notice) return false;
    return (c.space === 'personal' && !c.repo) || (c.options || {}).kind === 'research';
  }
  function outcomePage(c) {
    return c.links && c.links.formats && c.links.formats.outcome ? '/outcome/' + c.id : null;
  }
  /* c-719: the result is the outcome's own page where it has one, else the output. A named
     output that is a markdown file in the card's folder is a page of the viewer
     (`links.output` is `/file/<id>/<name>`, keel/cardfiles.py), offered beside the result
     by its own name (`namedOutput`), so a report the house named is one tap away. r1.F6:
     so is any other output the card declared (a work research card stages with its findings
     board's link), named for what it is. */
  function resultLink(c) {
    if (c.links && c.links.formats && c.links.formats.outcome) return '/outcome/' + c.id;
    return K.outputLink(c);
  }
  function namedOutput(c) {
    var o = c.links && c.links.output;
    return o && o !== resultLink(c) ? o : null;
  }
  /* the named output, beside Open result, under its own key at every phase (r1.F6) */
  function putNamed(c, put) {
    var o = namedOutput(c);
    if (!o) return;
    var inViewer = o.indexOf('/file/' + c.id + '/') === 0;
    put('open-named', btn(namedWord(o), function () { if (inViewer) K.openPlan(o); else K.openLink(o); }));
  }
  function fileName(url) {
    var name = String(url).split('/').pop();
    try { return decodeURIComponent(name); } catch (e) { return name; }
  }
  function namedWord(url) {
    if (/\/board\/b-\d+/.test(url)) return 'Open findings board';
    return url.indexOf('/file/') >= 0 ? 'Open ' + fileName(url) : 'Open output';
  }
  K.keelChip = keelChip; K.keelWord = keelWord; K.research = research; K.dropOn = dropOn;

  /* THE RECEIPT of the card's last gate answer (c-537, `keel/receipt.py`, drawn by
     app/ui.receipt.js exactly as the plan page draws it): who answered, when, and what is
     happening now, with the plan and the outcome it can open. It comes with the card's
     events (`/api/card/<id>`), so it is there once they are. */
  function receiptBlock(c) {
    var d = K.App.detailFor === c.id ? K.App.detail : null;
    if (!d || !d.receipt || !K.receipt) return null;
    var docs = [];
    if (c.plan_ref) docs.push('plan');
    if (['review', 'shipping', 'done'].indexOf(c.stage) >= 0) docs.push('outcome');
    return el('div', { class: 'psec', 'data-key': 'receipt-sec' }, K.receipt(d.receipt, { card: c.id, links: docs }));
  }

  /* c-678: a card that landed by a merge on this computer, in a space with no pack: where
     its work is, and the Push that sends it (app/ui.landpush.js) */
  function pushBlock(c) { return K.pushBlock ? K.pushBlock(c) : null; }

  function detailPane(c) {
    K.keepPane('card:' + c.id);
    var desk = K.isDesk();
    /* the content the phone puts before its three actions, and the desk after its grid */
    /* a notice's evidence IS its brief, so the brief is not drawn a second time under it */
    var briefShown = c.derived.notice && !c.derived.archived && !K.gateOf(c);
    var content = [planBlock(c), gateEvidence(c), K.shipping ? K.shipping.section(c) : null,
      c.brief && !briefShown ? readingBlock('brief', K.fullBrief(c)) : null];
    /* On the phone the tree and a slice's place in it are content too, and lead it (c-302:
       the first screen of a big card is its tree); Assign tree moves from the tree's head
       into the action row, where the card's state decides whether it is a primary. */
    if (!desk) content = [K.treeSection(c, true), K.placeSection(c), receiptBlock(c), pushBlock(c)].concat(content);
    /* Bosun's view of a Keel card (c-592): what it IS, so it leads the content on the phone
       and sits under the title on the desk */
    var keel = keelSection(c);
    if (!desk) content = [keel].concat(content);
    return K.paneFrame({
      title: c.title,
      identity: headLine(c),
      /* the same three words the row showed, so the card he opened says the state he
         opened it for without reading the facts grid */
      words: [wordsRow(c, false), K.liveStrip ? K.liveStrip(c, true) : null],
      lead: desk ? [parentLine(c), keel] : parentLine(c),
      content: desk ? null : content,
      actions: desk ? deskActions(c) : phoneActions(c),
      actionClass: desk ? '' : 'phone',
      closeTitle: 'close the card',
      /* a big card's tree, and a slice's place in its tree, come FIRST: on the phone
         they are the first screen, above every button (keel/tree.py, ui.tree.js) */
      sections: [
        desk ? K.treeSection(c) : null,
        desk ? K.placeSection(c) : null,
        desk ? receiptBlock(c) : null,
        desk ? pushBlock(c) : null,
        desk ? content[0] : null,
        boardBlock(c),
        filesBlock(c),
        desk ? content.slice(1) : null,
        section('facts', function () { return facts(c); }),
        topicEditor(c),
        section('notes', function () { return notes(c); }),
        section('events', function () { return timeline(c); })
      ]
    });
  }
  function phoneDetail(c, backTo) {
    return K.phonePane({ attention: 'Attention', reviews: 'Reviews' }[backTo] || 'Cards', detailPane(c));
  }

  K.viewCards = viewCards; K.detailPane = detailPane; K.phoneDetail = phoneDetail;
  K.pretestWord = pretestWord;
  K.gateEvidence = gateEvidence; K.gateActions = gateActions; K.cardItems = cardItems;
  K.planBlock = planBlock; K.boardBlock = boardBlock;
  K.readingBlock = readingBlock;
  K.findCards = findCards;
})(window.Keel);
