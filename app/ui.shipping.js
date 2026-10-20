/* The shipping phase on the deck (c-600).
 *
 * A work card whose outcome he approved sits at `shipping` until its pull request merges,
 * and its build house lives on: the drain tells it each batch of review comments and failed
 * checks in its own session, and it records ONE VERDICT per item (keel/shipreplies.py). The
 * review comments page (`/comments/<id>`, app/ui.comments.js, c-643) shows that standing
 * batch by round, one row per item: the comment, the verdict, the reasoning, the diff of the
 * commits that answer it and/or the reply's words, and his Post, Edit or Drop for the reply
 * (a `mark` on doc `shipping`, block `replies`). The pane says one line of it and opens the
 * page. His one action is Ship, on both: push the house's commits, mark a draft ready, post
 * the kept replies once. The row and Ship are drawn here for both (`K.shipping.row`,
 * `K.shipping.bar`), so a control is never written twice.
 *
 * SHIP SAYS WHAT IT SENDS, AND IS DRAWN ONLY WHERE THE SEND CAN SUCCEED (c-653). One label
 * for several actions read as nothing, and it was offered on cards where it could only
 * fail. So the button is named from what is waiting, in the space's words ("Push 2 commits
 * and post 3 replies", "Post 1 reply", "Mark the pull request ready for review"), and it
 * stays ONE tap that sends everything he accepted, the push first. Where a send cannot go,
 * the card says why in one line where the button would be (`shipState`): the worktree has
 * diverged from its pull request's branch (the sentence is the backend's own, drawn as
 * given, and under it the command that brings the worktree in line by hand, one chain in a
 * block he can copy, keel/shipstep.py: Keel moves no branch for him);
 * the house is still in its turn (Ship anyway stays reachable from the line); nothing is
 * waiting. A worktree only BEHIND that branch has nothing to push, so Ship still sends what
 * waits, with the line and the commands beside it. The backend is
 * still the judge (keel/shipcheck.py refuses and holds with the same reasons): the deck
 * only stops offering a tap it knows will be refused.
 *
 * Every control at shipping is justified (docs/atlas/40-deck.md, "Controls by phase"): Ship,
 * the ways into the house's own session on the row itself as at every other stage
 * (Open in Claude app, Resume and open in app, Drop in; Talk, the sheet, where voice is
 * installed), Open output, Open story, View context, Stop session while the house works,
 * Archive; and (c-655) the hand-over of the review that waits, with the branch brought up to
 * its base beside it; and (c-663) Send back, his own notes for the house. A blocked shipping
 * card has Unblock only and the ways in: a Retry there would restart a shipped card from scratch.
 *
 * SEND BACK AT SHIPPING (c-663) is app/ui.shipsendback.js: its button, its box and what he
 * sent that still waits. Here its row in the standing batch is marked as his (`row.his`):
 * the house's verdict and its answer to him, with no Post, Edit or Drop, since nothing of it
 * ever goes to the code host.
 */
(function (K) {
  'use strict';
  var el = K.el, App = K.App;
  var VERDICT_WORDS = { valid: ['Valid', 'good'], 'not-valid': ['Not valid', 'warn'], deferred: ['Valid, deferred', 'plain'],
    prepared: ['Prepared, waits on you', 'warn'] };      /* r-55 (c-723) */
  var CHOICE_WORDS = [['post', 'Post'], ['edit', 'Edit'], ['drop', 'Drop']];

  function shippingOf(c) { return (c.options && c.options.shipping) || {}; }
  function detailOf(c) {
    return App.detailFor === c.id && App.detail ? App.detail.shipping || null : null;
  }
  function declined(c) { return shippingOf(c).state === 'declined'; }
  /* told items whose words his Ship has not posted yet (the card row's own count); the
     rebase item is never posted (c-651), so it is not one */
  function openTold(c) {
    var s = shippingOf(c), posted = s.posted || {};
    return (s.told || []).filter(function (i) { return i.kind !== 'rebase' && i.kind !== 'his' && !posted[i.handle]; }).length;
  }
  /* Is Ship offered: something is waiting AND the send can go (`shipState`, c-653) */
  function shippable(c, given) { return !!shipState(c, given).send; }
  function plural(n, word) { return n + ' ' + (n === 1 ? word : word.replace(/y$/, 'ie') + 's'); }

  /* ---------- what his Ship would send, and whether it can (c-653) ---------- */
  /* What is waiting: commits a fast-forward push would send, a draft to mark ready, kept
     replies not posted (`posts` is null until the rows have loaded), items the house has not
     judged yet, and how the worktree stands against its pull request's branch
     (`options.shipping.local`, keel/shipping.py `step_facts`). */
  function waiting(c, given) {
    var s = shippingOf(c), l = s.local || {}, f = s.facts || {}, d = given || detailOf(c);
    return { commits: l.ahead || 0, draft: !!f.draft, posts: d ? d.summary.to_post : null,
      judging: d ? d.summary.judging : 0, behind: l.behind || 0, diverged: l.diverged || null,
      said: l.said || null, hand: l.by_hand || [], conflicts: !!l.conflicts, restack: !!l.restack };
  }
  /* each thing the one tap does, in the order it does them: the push always goes first */
  function sendWords(c, w) {
    var posts = w.posts === null ? (openTold(c) && (w.commits || w.draft) ? 'post the replies you kept' : null)
      : w.posts ? 'post ' + plural(w.posts, 'reply') : null;
    return [w.commits ? 'push ' + plural(w.commits, 'commit') : null,
      w.draft ? K.say(c.space, 'mark the {change} ready') : null, posts].filter(Boolean);
  }
  function joined(parts) {
    return parts.length < 2 ? parts.join('') : parts.slice(0, -1).join(', ') + ' and ' + parts[parts.length - 1];
  }
  function shipLabel(c, given) {
    var w = waiting(c, given), parts = sendWords(c, w);
    if (parts.length === 1 && w.draft) return K.say(c.space, 'Mark the {change} ready for review');
    var said = joined(parts);
    return said.charAt(0).toUpperCase() + said.slice(1);
  }
  /* The sentence for a worktree its pull request's branch has left behind is the BACKEND'S,
     drawn as given (`options.shipping.local.said`, keel/shipstep.py `said`): the
     card's note and the terminal's refusal are the same string, so the three cannot drift. */
  function astrayWhy(c, w) {
    return w.said || K.say(c.space, 'The branch is out of step with the {change}\'s branch.');
  }
  /* The command that brings each worktree in line by hand, as he pastes it: ONE chain per
     worktree, joined with && by the backend so a paste stops at the first step that fails
     (`local.by_hand`, keel/shipstep.py `chain`); the same text the terminal's refusal carries */
  function handCommands(w) {
    return w.hand.map(function (h) { return h.command; }).filter(Boolean).join('\n');
  }
  function nothingWhy(c, w) {
    if (w.judging) return 'Nothing to send yet: the house was told ' + plural(w.judging, 'item') + ' it has not judged.';
    return K.say(c.space, 'Nothing to send: no commit the {change} lacks and no reply to post.');
  }
  /* {send, why, anyway, commands}: whether Ship is drawn, the one line said where it would
     be, and what the line carries. Empty for a declined or blocked card (each says its own). */
  function shipState(c, given) {
    if (declined(c) || c.blocked_reason) return {};
    /* c-660: a Ship that just went is said where the button was, never offered again */
    var went = sentLine(c, given);
    if (went) return { why: went };
    var w = waiting(c, given), busy = K.houseBusy(c);
    /* diverged: the push cannot succeed, and the push goes before any reply */
    if (w.diverged) return { why: astrayWhy(c, w), commands: handCommands(w) };
    var st = sendState(c, w, busy);
    if (!w.behind && !w.restack) return st;
    /* behind only, or a stacked card's parent squash-merged (c-718): said with its commands,
       and what else waits still goes */
    st.why = [astrayWhy(c, w), st.why].filter(Boolean).join(' ');
    st.commands = handCommands(w);
    return st;
  }
  function sendState(c, w, busy) {
    var round = shippingOf(c).round;
    if (!sendWords(c, w).length) return w.posts === null ? {} : { why: nothingWhy(c, w) };
    if (busy) {
      return { anyway: true, why: 'The house is still in its turn' + (round ? ' on batch ' + round : '') +
        ', so what it is doing is not on the branch yet: Ship waits for it.' };
    }
    return { send: true, why: w.conflicts ? K.say(c.space, 'After this send the {change} will still conflict with its base.') : null };
  }
  /* What Ship will do, and what he should know first: said in its confirm */
  /* `given`: the standing batch where the caller has it (the comments page), else the pane's */
  function shipConfirm(c, given) {
    var s = shippingOf(c), l = s.local || {}, f = s.facts || {}, d = given || detailOf(c);
    var posts = d ? d.summary.to_post : null;
    var doing = [l.ahead ? 'push ' + plural(l.ahead, 'commit') + ' first' : 'push nothing new',
      f.draft ? K.say(c.space, 'mark the {change} ready') : null,
      posts === null ? 'post the replies you kept' : 'post ' + plural(posts, 'reply')].filter(Boolean);
    var warn = [];
    if (l.unchecked) warn.push('The commits are not checked: no review stamp covers them (the house runs keel check).');
    if (l.conflicts) warn.push('The branch conflicts with its base.');
    if (f.behind) warn.push('The branch is ' + f.behind + ' behind its base.');
    if (d && d.summary.judging) warn.push(plural(d.summary.judging, 'item') + ' still being judged.');
    if (K.preparedOf(c).length) warn.push(plural(K.preparedOf(c).length, 'item') + ' still waiting on your answer: its prepared fix is not on the branch.');
    return 'Ship ' + c.id + '? It will ' + doing.join(', ') + '.' + (warn.length ? '\n\n' + warn.join('\n') : '');
  }
  /* A SHIP THAT WENT IS SAID, NOT OFFERED AGAIN (c-660). The answer arrives before the state
     that holds it: for that moment the page still held "23 commits ahead", drew "Push 23
     commits" again, and his second tap was refused. So the Ship's own line (the card's
     record of it, `r.note`) is kept with the stamp the board gave that Ship
     (`shipping.shipped_at`) and drawn where the button was until BOTH the card and the
     standing batch on the page are that Ship's or newer. Then the state says what waits.
     THE LINE NEVER OUTLIVES WHAT IT DESCRIBES (c-660 review): its entry is dropped the
     moment the page holds that Ship's state, after `SENT_MS` whatever the page holds (as
     the bridge word ends, app/ui.core.js), and when the card's record is no longer the one
     the Ship answered on (`since` or `round` moved: a record begun afresh carries no
     `shipped_at`, and the old line stood in for the button until a reload). */
  var sent = {}, SENT_MS = 30000;
  function instant(stamp) { return stamp ? Date.parse(stamp) || 0 : 0; }
  function landed(c, r) {
    var s = (r && r.card && r.card.options && r.card.options.shipping) || {};
    if (!s.shipped_at) return;
    sent[c.id] = { note: r.note || 'shipped', at: instant(s.shipped_at), since: s.since, round: s.round, drawn: Date.now() };
    /* drawn now: the pressed button would else say "Shipping…" until the state's own redraw */
    K.renderBody();
  }
  function sentLine(c, given) {
    var s = sent[c.id], d = given || detailOf(c), now = shippingOf(c);
    if (!s) return null;
    var fresh = instant(now.shipped_at) >= s.at && (!d || instant(d.summary.shipped_at) >= s.at);
    var over = Date.now() - s.drawn > SENT_MS || now.since !== s.since || now.round !== s.round;
    if (fresh || over) { delete sent[c.id]; return null; }
    return s.note;
  }
  /* The worktree NOW, on the house's machine, is what Ship checks (keel/shipcheck.py): a
     house in a turn or commits no receipt covers HOLD it, and the answer says why. Only his
     explicit "Ship anyway" sends it as it is. */
  function shipDone(c) {
    return function (r) {
      if (r && r.held) {
        setTimeout(function () { shipAnyway(c, r.held); }, 0);
        return '';
      }
      landed(c, r);
      return (r && r.note) || 'shipped';
    };
  }
  function shipAnyway(c, why) {
    if (!window.confirm(why + '\n\nShip ' + c.id + ' anyway, as it is now?')) return null;
    var done = shipDone(c);
    return K.act({ verb: 'ship', id: c.id, anyway: true }, function (r) { var said = done(r); acted(); return said; });
  }
  function shipButton(c, given) {
    var done = shipDone(c);
    return K.actionBtn(shipLabel(c, given), { verb: 'ship', id: c.id }, { cls: 'primary shipsend', confirm: shipConfirm(c, given),
      done: function (r) { var said = done(r); acted(); return said; } });
  }
  /* The line where Ship would be; a held Ship stays one tap away from it (`anyway`), and
     the by-hand commands sit under it in the deck's copy block (as a login's fix does) */
  function whyLine(c, st, given) {
    return el('div', { class: 'needs-line shipwhy', role: 'status' }, el('span', { text: st.why }),
      st.anyway ? el('button', { class: 'btn sm', 'data-key': 'ship-anyway', disabled: K.pendingOn(c.id) ? true : null,
        onclick: function () { shipAnyway(c, shipConfirm(c, given)); } }, 'Ship anyway') : null,
      st.commands ? el('div', { class: 'lfix', 'data-key': 'ship-by-hand' },
        el('code', { class: 'fix', text: st.commands }), K.copyButton(st.commands)) : null);
  }
  /* Ship as the comments page draws it: the line, the button, whichever apply */
  function bar(c, given) {
    var st = shipState(c, given);
    return [st.why ? whyLine(c, st, given) : null, st.send ? shipButton(c, given) : null];
  }
  /* A mark or a Ship that landed: the page that drew it reads its own data again. `K.act`
     reloads the deck's state, which the comments page does not draw (c-643 r1.F1). */
  function acted() { if (K.shipping.onActed) K.shipping.onActed(); }

  /* ---------- Talk: every way into the house's own session, in one sheet ---------- */
  function voiceHere() {
    var h = K.health ? K.health() : null;
    var v = ((h && h.services) || []).filter(function (s) { return s.name === 'voice'; })[0];
    return !!(v && v.level !== 'off');
  }
  function talkButton(c) {
    return el('button', { class: 'btn', onclick: function () { App.sheet = { kind: 'talk', id: c.id }; K.renderSheet(); } }, 'Talk');
  }
  function talkSheet(s) {
    var c = K.byId(s.id);
    if (!c) return el('div', { class: 'sheet' });
    var close = function () { App.sheet = null; K.renderSheet(); };
    var listed = !!K.houseOf(c), ways = [];
    if (listed && c.options.app_link) {
      ways.push(el('button', { class: 'btn wide primary', 'data-key': 'talk-app', onclick: function () { close(); K.openLink(c.options.app_link); } },
        'Open in Claude app'));
      ways.push(el('p', { class: 't11 ink2', text: 'Its own session over Remote Control: what you type is its next turn.' }));
    } else if (K.appResumable(c)) {
      ways.push(K.resumeAppBtn(c, 'Resume and open in app', 'wide primary'));
      ways.push(el('p', { class: 't11 ink2', text: 'The house is not running: it comes back with no turn, and opens in the app.' }));
    }
    if (!K.inTerminal(c)) {
      ways.push(K.actionBtn('Drop in', { verb: 'dropin', id: c.id },
        { cls: 'wide', done: function (r) { K.showCommand(c.id, r.command, r.said); return ''; } }));
      ways.push(el('p', { class: 't11 ink2', text: 'The command for a terminal at your desk, on the same session.' }));
    }
    if (voiceHere()) {
      ways.push(el('button', { class: 'btn wide', 'data-key': 'talk-voice', onclick: function () { close(); K.openLink(K.voiceHref() + '?connect=' + encodeURIComponent(c.id)); } }, 'Talk by voice'));
    }
    return el('div', { class: 'sheet', 'data-key': 'sheet-talk' },
      el('div', { class: 'sheet-head' }, el('button', { onclick: close }, '‹ close'),
        el('span', { class: 'spacer' }), el('span', { class: 'mono t11 ink2', text: c.id + ' · talk' })),
      el('div', { class: 'sheet-body' }, el('div', { class: 'title', text: c.title }),
        ways.length ? ways : el('p', { class: 'ink2', text: 'This card has no house to talk to.' })));
  }

  /* ---------- the actions at shipping ---------- */
  function gateItems(c, put) {
    if (c.blocked_reason) {
      put('unblock', K.actionBtn('Unblock only', { verb: 'unblock', id: c.id }, { cls: 'primary' }));
      return;
    }
    /* c-631: Ship stays, and the backend decides; the line says what it will refuse with */
    K.putNeed(c, put, 'need-codehost', 'codehost');
    /* r-55 (c-723): the house's question first, since the card waits on his answer to it */
    var asked = K.shipping.preparedLines ? K.shipping.preparedLines(c) : null;
    if (asked) put('ship-prepared', asked);
    /* c-653: Ship named for what it sends, only where it can go; else why, where it would be */
    var st = shipState(c);
    if (st.why) put('ship-why', whyLine(c, st));
    if (st.send) put('ship', shipButton(c));
    handItems(c, put);         /* c-655: the waiting review, handed to the house */
    /* c-663: his own notes for the house (app/ui.shipsendback.js), where a tell can follow */
    if (K.shipping.sendBackOffered && K.shipping.sendBackOffered(c)) put('ship-sendback', K.shipping.sendBackButton(c));
  }
  /* The ways into the house's own session, on the row itself as at every other stage
     (c-653: Open in Claude app and Drop in were only inside the Talk sheet, and he could not
     find the way into a running house). Talk, the sheet, stays where voice is installed. */
  function waysIn(c, put, btn) {
    if (!c.session_id) return;
    if (K.inTerminal(c)) put('in-terminal', el('span', { class: 'pill accent' }, 'in a terminal'));
    else if (c.options.app_link && K.houseOf(c)) put('open-app', btn('Open in Claude app', function () { K.openLink(c.options.app_link); }));
    /* a house in its turn with no link on record (c-135): the same button, and the tap reads
       the link from its log without waking or stopping anything (`house.open_app`) */
    else if (K.houseBusy(c)) put('open-app', K.resumeAppBtn(c, 'Open in Claude app'));
    else if (K.appResumable(c)) put('resume-app', K.resumeAppBtn(c, 'Resume and open in app'));
    if (!K.inTerminal(c)) {
      put('dropin', K.actionBtn('Drop in', { verb: 'dropin', id: c.id },
        { done: function (r) { K.showCommand(c.id, r.command, r.said); return ''; } }));
    }
    if (voiceHere()) put('talk', talkButton(c));
  }
  function cardItems(c, put, btn) {
    waysIn(c, put, btn);
    var output = K.outputLink(c), prs = K.pullsOf(c);
    if (prs.length > 1) put('open-output', btn('Open output', function () { App.sheet = { kind: 'prs', id: c.id }; K.renderSheet(); }));
    else if (output) put('open-output', btn('Open output', function () { K.openLink(output); }));
    if (c.links.story) put('story', btn(K.say(c.space, 'Open {ticket}'), function () { K.openLink(c.links.story); }));
    /* the code host's line is on the row unless the card is blocked (`gateItems`) */
    else K.putNeed(c, put, 'need-tracker', c.options && c.options.tracker_ref ? 'tracker' : null, c.blocked_reason ? null : 'codehost');
    if (c.links.context) put('context', btn('View context', function () { K.openPlan(K.contextLink(c)); }));
    /* c-643, c-644: the review comments page, a page of the card's viewer (Pages) */
    if ((shippingOf(c).told || []).length) put('open-comments', btn('Open comments', function () { K.openPlan('/comments/' + c.id); }));
    if (K.putCi) K.putCi(c, put);      /* c-642: its builds, at shipping too */
    /* the flow's moves he makes at shipping (c-641's merge to dev review and early merge to
       master both run here), in the groups the flow names (c-644); they were never drawn at
       shipping before */
    (K.flowMoves ? K.flowMoves(c) : []).forEach(function (m) {
      put('flow-' + m.id, K.actionBtn(m.label, { verb: 'flow.move', id: c.id, move: m.id },
        { done: function (r) { return (r && r.note) || m.label + ': the house was told'; } }));
    });
    if (K.houseBusy(c) && !K.inTerminal(c)) {
      put('stop', K.actionBtn('Stop session', { verb: 'house.stop', id: c.id },
        { cls: 'crit', confirm: 'Stop the session on ' + c.id + '? It is answering review now. Nothing else ends a live session.' }));
    }
    /* c-607: a house left idle between batches holds its memory; the next batch brings it back */
    if (K.closeableIdle && K.closeableIdle(c)) put('close-idle', K.closeIdleBtn(c));
    put('archive', K.actionBtn(c.derived.archived ? 'Unarchive' : 'Archive',
      { verb: 'set', id: c.id, fields: { 'options.archived': !c.derived.archived } }));
  }

  /* ---------- automatic handling, and the hand-over (c-655) ----------
   * Two switches per card, each its space's setting with the card's own option over it
   * (keel/shipauto.py): whether a new review comment, and a failing check, goes to the house
   * by itself. The pane says each in words, on or off, with what waits and the tap that
   * turns it. The hand-over is `ship.handover` (`kb ship <id> reoffer` as him): its label
   * says what it gives the house, and it is drawn only when there is something to give. */
  var AUTO = [
    { kind: 'comments', key: 'ship_auto_comments', what: 'review comments', each: 'each new comment' },
    { kind: 'checks', key: 'ship_auto_checks', what: 'failing checks', each: 'each failing check' }
  ];
  function handOf(c) { return (c.derived && c.derived.ship_handover) || null; }
  function autoOf(c) { return (c.derived && c.derived.ship_auto) || null; }
  function countOf(kind, n) {
    if (kind === 'comments') return plural(n, 'comment');
    return n === 1 ? 'the failing check' : n + ' failing checks';
  }
  function capital(text) { return text.charAt(0).toUpperCase() + text.slice(1); }
  /* one switch in words: what waits, whether it is on, and what either choice does */
  function autoWords(a, on, n, asked) {
    var count = capital(countOf(a.kind, n)), it = n === 1 ? 'it' : 'them';
    /* handed over already: what waits is on its way, so nothing urges the tap again */
    if (asked && n) {
      return count + ' handed over: the house is told on the drain\'s next pass. Automatic handling of ' +
        a.what + ' is ' + (on ? 'on.' : 'off.');
    }
    if (on) {
      return 'Automatic handling of ' + a.what + ' is on: ' + a.each + ' goes to the house as it arrives.' +
        (n ? ' ' + count + (n === 1 ? ' still waits' : ' still wait') + ' for your hand-over.' : '');
    }
    if (!n) return 'Automatic handling of ' + a.what + ' is off: ' + a.each + ' waits here until you hand it to the house.';
    return count + (a.kind === 'checks' && n === 1 ? ' is waiting. ' : ' waiting. ') + 'Automatic handling of ' + a.what +
      ' is off: hand ' + it + ' to the house, or turn it on to have ' + a.each + ' handled as it arrives.';
  }
  function autoSet(c, a, value, label) {
    var fields = {};
    fields['options.' + a.key] = value;
    return K.actionBtn(label, { verb: 'set', id: c.id, fields: fields },
      { cls: 'sm', name: label + ': automatic handling of ' + a.what + ' on ' + c.id, done: function () { acted(); return ''; } });
  }
  function autoRow(c, a, mine, n, asked) {
    return el('div', { class: 'shipauto' + (mine.on ? ' on' : ''), 'data-key': 'auto-' + a.kind },
      el('p', { class: 't13', 'data-key': 'auto-words-' + a.kind, text: autoWords(a, mine.on, n, asked) +
        (mine.by === 'card' ? ' Set on this card.' : '') }),
      el('div', { class: 'row-actions' }, autoSet(c, a, !mine.on, mine.on ? 'Turn off' : 'Turn on'),
        mine.by === 'card' ? autoSet(c, a, null, 'Use the space\'s setting') : null));
  }
  function autoLines(c) {
    var auto = autoOf(c), h = handOf(c) || {};
    /* only at shipping: the comments page of a card that left it keeps its last read */
    if (!auto || declined(c) || c.stage !== 'shipping') return null;
    var rows = AUTO.map(function (a) { return autoRow(c, a, auto[a.kind] || {}, h[a.kind] || 0, !!h.asked); });
    /* asked with items counted: the rows above say it; asked for the base alone: said here */
    var said = h.asked ? (h.comments || h.checks ? null : ['hand-asked', 'Handed over: the house is told on the drain\'s next pass.'])
      : h.busy ? ['hand-busy', 'The house is on batch ' + h.busy + ' now: what it leaves unjudged can be handed over once its turn ends.'] : null;
    if (said) rows.push(el('p', { class: 't11 ink2', 'data-key': said[0], text: said[1] }));
    return el('div', { class: 'shipautos', 'data-key': 'ship-auto' }, rows);
  }
  /* "Hand 3 comments and the failing check to the house", or null with nothing to hand */
  function handLabel(h) {
    var parts = AUTO.filter(function (a) { return h[a.kind]; }).map(function (a) { return countOf(a.kind, h[a.kind]); });
    /* c-663: a send-back of his own the house was told and never judged */
    if (h.his) parts.push(h.his === 1 ? 'your send-back' : 'your ' + h.his + ' send-backs');
    return parts.length ? 'Hand ' + parts.join(' and ') + ' to the house' : null;
  }
  function handItems(c, put) {
    var h = handOf(c);
    if (!h || h.asked || declined(c)) return;
    var label = handLabel(h), done = function (r) { acted(); return (r && r.note) || 'handed over'; };
    /* the row has ONE leading button: Ship, else this (c-653) */
    var st = shipState(c), astray = shippingOf(c).local || {};
    /* on a card whose branch is out of step the house is handed the review all the same,
       and told that its branch is out of step: said before he taps */
    var warned = astray.behind ? K.say(c.space, 'This card\'s branch is out of step with its {change}\'s branch. ' +
      'The house is handed the review all the same and is told so: it judges and commits, and what it ' +
      'commits cannot be pushed until the worktree is in line again.') : null;
    if (label) put('hand-over', K.actionBtn(label, { verb: 'ship.handover', id: c.id }, { cls: st.send ? '' : 'primary', done: done, confirm: warned }));
    /* not while the worktree is behind or has diverged from its pull request's branch
       (c-653): a merge of the base on top of that history is one more thing to untangle,
       and the backend refuses the ask (`Board.reoffer`); the worktree in line first */
    if (h.base && !astray.behind) {
      put('hand-base', K.actionBtn('Bring the branch up to its base', { verb: 'ship.handover', id: c.id, rebase: true },
        { done: done, confirm: label ? 'Bring ' + c.id + '\'s branch up to its base? Its house merges the base in, and this will also ' +
          label.charAt(0).toLowerCase() + label.slice(1) + '.' : null }));
    }
  }

  /* ---------- the standing batch ---------- */
  function mark(c, handle, choice, other) {
    var data = { what: 'answer', doc: 'shipping', block: 'replies', row: handle, choice: choice };
    if (other) data.other = other;
    return K.act({ verb: 'mark', id: c.id, data: data }, function () { acted(); return ''; });
  }
  var editing = {};
  function where(c, item) {
    if (item.kind === 'ci') return (item.name || 'a check') + ' failed';
    if (item.kind === 'review') return item.author + ' asked for changes';
    if (item.kind === 'his') return 'your own send-back: it stays here, nothing is posted';
    if (item.kind === 'rebase') return 'bring the branch up to ' + (item.base || 'its base') + ' by merging it in';
    var at = item.path ? item.path + (item.line ? ':' + item.line : '') : 'the ' + K.term(c.space, 'change');
    return item.author + ' on ' + at;
  }
  function verdictChip(row) {
    if (!row.verdict) return el('span', { class: 'chip', text: 'judging…' });
    var w = VERDICT_WORDS[row.verdict.verdict] || [row.verdict.verdict, 'plain'];
    return el('span', { class: 'chip ' + w[1], text: w[0] + (row.verdict.severity ? ' · ' + row.verdict.severity : '') });
  }
  /* the diff is `git show --format='%h %s'`, so its first line is the sha and the subject */
  function subjectOf(one) {
    var first = String(one.diff || '').split('\n')[0];
    var m = /^[0-9a-f]{7,40} (.+)$/.exec(first);
    return m ? ' ' + m[1] : '';
  }
  function commitsOf(row) {
    return ((row.verdict && row.verdict.commits) || []).map(function (one) {
      return el('details', { class: 'shipdiff', 'data-key': 'diff-' + one.sha },
        el('summary', { class: 'mono t11', text: 'change ' + String(one.sha).slice(0, 10) + subjectOf(one) }),
        el('pre', { class: 'pcode-pre', text: one.diff || '(no diff recorded)' }));
    });
  }
  function choiceRow(c, row) {
    if (row.posted) return el('span', { class: 'chip good', text: 'posted' });
    return el('div', { class: 'pseg', role: 'group', 'aria-label': 'what to do with the reply to ' + row.handle },
      CHOICE_WORDS.map(function (cw) {
        var on = row.choice === cw[0];
        return el('button', { class: on ? 'on' : '', 'aria-pressed': on ? 'true' : 'false',
          'data-key': 'pick-' + row.handle + '-' + cw[0], disabled: K.pendingOn(c.id) ? true : null,
          onclick: function () {
            if (cw[0] === 'edit') { editing[c.id + ':' + row.handle] = row.edited || row.verdict.reply || ''; K.renderBody(); return; }
            delete editing[c.id + ':' + row.handle];
            mark(c, row.handle, cw[0]);
          } }, cw[1]);
      }));
  }
  function editField(c, row) {
    var key = c.id + ':' + row.handle;
    return el('div', { class: 'pd-otherfield', 'data-key': 'edit-' + row.handle },
      el('textarea', { rows: 4, 'aria-label': 'your words for ' + row.handle, value: editing[key],
        oninput: function (ev) { editing[key] = ev.target.value; } }),
      el('div', { class: 'row-actions' },
        el('button', { class: 'btn sm', onclick: function () { delete editing[key]; K.renderBody(); } }, 'Cancel'),
        el('button', { class: 'btn sm primary', disabled: K.pendingOn(c.id) ? true : null, onclick: function () {
          var text = (editing[key] || '').trim();
          if (!text) { K.toast('type the words to post, or pick Drop', true); return; }
          /* the field closes only once the mark has landed: a tap while another answer on
             this card is still on its way is not lost with his words (c-600 sandbox run) */
          mark(c, row.handle, 'edit', text).then(function (r) {
            if (r !== null) { delete editing[key]; K.renderBody(); }
          });
        } }, 'Keep these words')));
  }
  function replyOf(c, row) {
    /* c-663: on his own item the reply is the house's answer to HIM, shown and never sent */
    if (row.his) {
      return row.verdict && row.verdict.reply ? el('div', { class: 'reading shipreply', 'data-key': 'reply-' + row.handle,
        text: 'The house\'s answer to you: ' + row.verdict.reply }) : null;
    }
    if (editing[c.id + ':' + row.handle] !== undefined) return editField(c, row);
    var words = row.choice === 'edit' ? row.edited : (row.verdict && row.verdict.reply) || '';
    if (!words) return null;
    return el('div', { class: 'reading shipreply' + (row.choice === 'drop' ? ' dropped' : ''), 'data-key': 'reply-' + row.handle,
      text: (row.choice === 'edit' ? 'Your words: ' : 'Reply: ') + words });
  }
  /* One item: who said what, the house's verdict, its reasoning and commits, the reply and his
     choice. The comments page passes the whole text (`row.text`, read from the card's
     `comments/`) and says when only the cut one could be read. */
  function rowNode(c, row, closed) {
    var v = row.verdict || {}, item = row.item || {};
    /* his own words are never cut (c-663): no file holds the rest of them */
    var text = row.text !== undefined ? row.text : String(item.text || '').slice(0, row.his ? undefined : 600);
    return el('div', { class: 'shiprow' + (row.his ? ' his' : ''), 'data-key': 'row-' + row.handle },
      el('div', { class: 'row-chips' }, el('span', { class: 'mono t11', text: row.handle }),
        row.his ? el('span', { class: 'chip accent', text: 'yours' }) : null, verdictChip(row),
        el('span', { class: 't11 ink2', text: where(c, item) })),
      text ? el('div', { class: 'reading quote', text: text }) : null,
      row.whole === false ? el('div', { class: 't11 ink2', 'data-key': 'cut-' + row.handle,
        text: row.cut === 'edited' ? 'Cut: the comment was edited on the ' + K.term(c.space, 'change') + ' since the house was told it; the next round brings its new words.'
          : 'Cut: the whole text is kept on the machine that watches the ' + K.term(c.space, 'change') + '.' }) : null,
      /* c-663: his own item told and with no verdict yet says so in words; that is all it does */
      row.his && !row.verdict ? el('div', { class: 't11 ink2', 'data-key': 'his-unjudged-' + row.handle,
        text: 'Your send-back was told, not judged yet: the house has recorded no verdict on it.' }) : null,
      v.summary ? el('div', { class: 'shipsum', text: v.summary }) : null,
      v.why ? el('div', { class: 't11 ink2', text: 'Why: ' + v.why }) : null,
      /* after the why, which holds the house's question (r-55, c-723) */
      preparedLine(c, row),
      commitsOf(row), replyOf(c, row),
      /* `closed`: the card left shipping, so no Ship will post a reply (c-643 r1.F4) */
      !row.his && row.verdict && (v.reply || row.edited) && (!closed || row.posted) ? choiceRow(c, row) : null);
  }
  /* r-55 (c-723): a prepared fix says it waits on him, and whether he has answered */
  function preparedLine(c, row) {
    if (!row.verdict || row.verdict.verdict !== 'prepared') return null;
    var open = K.preparedOf(c).some(function (w) { return w.handle === row.handle; });
    return el('div', { class: 'needs-line', role: 'status', 'data-key': 'prepared-row-' + row.handle },
      el('span', { text: open ? 'The house prepared this and waits on your answer, which goes to it as a send-back.'
        : 'You answered with a send-back: the house records this item again once it has done what you said.' }),
      open && K.shipping.answerButton && K.shipping.sendBackOffered(c) ? K.shipping.answerButton(c, row.handle) : null);
  }
  function waitingLine(c) {
    var s = shippingOf(c), n = (s.pending || []).length;
    if (!n) return null;
    return el('p', { class: 't11 ink2', 'data-key': 'waiting', text: plural(n, 'item') + ' waiting: they go to the house after 5 quiet minutes (30 at most).' });
  }
  /* "4 review items: 3 judged, 2 replies to post": the pane's line and the page's summary */
  function countLine(all, closed) {
    /* c-663: his own send-backs are no reviewer's, so they are counted beside the review */
    var mine = all.filter(function (r) { return r.his; }), rows = all.filter(function (r) { return !r.his; });
    var judged = rows.filter(function (r) { return r.verdict; }).length;
    var waits = rows.filter(function (r) { return r.verdict && r.verdict.verdict === 'prepared'; }).length;
    var toPost = closed ? 0 : rows.filter(function (r) { return r.words && !r.posted; }).length;
    var posted = rows.filter(function (r) { return r.posted; }).length;
    var review = plural(rows.length, 'review item') + ': ' + judged + ' judged' + (waits ? ', ' + waits + ' prepared for your answer' : '') +
      (toPost ? ', ' + plural(toPost, 'reply') + ' to post' : '') + (posted ? ', ' + posted + ' posted' : '');
    if (!mine.length) return review;
    var yours = plural(mine.length, 'send-back') + ' of yours: ' + mine.filter(function (r) { return r.verdict; }).length + ' answered';
    return rows.length ? review + '; ' + yours : yours;
  }
  /* The pane's part of the standing batch (c-643): one line, and the page that holds the rows. */
  function section(c) {
    if (K.stageOf(c) !== 'shipping') return null;
    var d = detailOf(c), parts = [el('div', { class: 'label', 'data-key': 'replies-label', text: 'review replies' })];
    if (declined(c)) parts.push(el('div', { class: 'blockbox', 'data-key': 'declined', text: K.say(c.space, 'The {change} was declined: nothing ships from this card. Archive puts it away.') }));
    parts.push(waitingLine(c));
    if (K.shipping.sentBackLines) parts.push(K.shipping.sentBackLines(c));    /* c-663: what he sent back, waiting */
    parts.push(autoLines(c));    /* c-655: each kind's automatic handling, said on or off */
    if (!d) parts.push(el('p', { class: 't11 ink2', text: 'loading…' }));
    else if (!d.rows.length) parts.push(el('p', { class: 't11 ink2', 'data-key': 'no-rows', text: 'The house has been told no review yet.' }));
    /* the rows are on the review comments page; Open comments is among the card's Pages (c-644) */
    else parts.push(el('p', { class: 'shipline', 'data-key': 'ship-line', text: countLine(d.rows) + '. Open comments has each one.' }));
    return el('div', { class: 'psec shipsec', 'data-key': 'shipping-sec' }, parts);
  }

  K.shipping = { gateItems: gateItems, cardItems: cardItems, section: section, shippable: shippable, shipDone: shipDone,
                 shipConfirm: shipConfirm, openTold: openTold, row: rowNode, shipButton: shipButton,
                 shipState: shipState, shipLabel: shipLabel, bar: bar,
                 countLine: countLine, waitingLine: waitingLine, declined: declined };
  K.shipping.handItems = handItems; K.shipping.handLabel = handLabel; K.shipping.autoLines = autoLines;   /* c-655 */
  K.shipping.acted = acted;     /* c-663: app/ui.shipsendback.js tells the page its send landed */
  K.talkSheet = talkSheet;
})(window.Keel);
