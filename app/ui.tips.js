/* One hover line for every action the deck draws for a card (U2, 2026-09-24), and the one
 * group each action belongs to (V2-1, below the lines).
 *
 * He could not tell Drop in from Resume house on an exited house, and nothing on the deck
 * said what any action does or does NOT do. Each line says both, in one sentence or two,
 * and they all live in ONE table keyed by the action's data-key (the key the phone picks
 * its primaries by), so wording is edited here and nowhere else. `tests/test_card_tips.py`
 * fails on a drawn key with no line, and on a line nothing draws.
 *
 * - A line is a string, or a function of the card for the few whose truth depends on it
 *   (Send back at the plan gate or the outcome gate, Archive or Unarchive, Drop in).
 * - DROP IN SAYS WHAT IT WILL DO before he taps: attach to a running house, resume an
 *   exited one, or open a fresh one, in `keel/dropin.py`'s own sentences (`SAID`, which a
 *   test holds equal to these). When the deck cannot tell (a house on another machine not
 *   asked yet, a card whose listing this deck does not carry) it says all three.
 * - An ADAPTER verb's line is the verb's own `help` from the space's verbs table, so its
 *   vocabulary stays in its pack (`packs/<name>/`); `verb` here is only the fallback.
 * - It is a `title`, never an aria label, which would replace the visible name for a
 *   screen reader. The phone has no hover, so its More actions sheet and every menu show
 *   the same line under each action's name (V2-1).
 */
(function (K) {
  'use strict';

  var el = K.el;

  /* keel/dropin.py SAID, word for word */
  var DROPIN_SAID = {
    attach: 'Joins the running house: the same session, what you type lands in its ' +
      'conversation. Ctrl+Z drops back to your shell and the house keeps running: ' +
      'it does not close it.',
    resume: 'The house has exited: this resumes its conversation in its own directory. ' +
      'Shipyard will not resume it in the background while you are in it. ' +
      'End it with /exit (or Ctrl+D) when done: Ctrl+Z only suspends it and keeps it open.',
    'new': 'No session on this card yet: this opens a fresh one in the house\'s directory. ' +
      'End it with /exit (or Ctrl+D) when done: Ctrl+Z only suspends it and keeps it open.',
    record: 'The card is done and its conversation is gone: this opens a fresh session in ' +
      'the card\'s record, told to read its plan and context first. ' +
      'End it with /exit (or Ctrl+D) when done: Ctrl+Z only suspends it and keeps it open.'
  };
  var DROPIN_LEAD = 'Drop in: a command to paste in your terminal. ';
  /* his terminal already has the conversation: the server hands out no command then */
  var DROPIN_OPEN = 'Drop in: this conversation is already open in your terminal; carry on ' +
    'there. Nothing new is started.';
  /* when this deck cannot tell which of the three it will be */
  var DROPIN_ANY = 'Drop in: a command to paste in your terminal. Joins a running house, ' +
    'continues an exited one, or opens a fresh one.';

  var TIPS = {
    /* the gate row */
    'approve-plan': 'Approve plan: the house starts building from this plan, in the same ' +
      'conversation. Nothing is published until you approve the outcome.',
    'approve-note': 'Approve with a note: the same approve, with your words handed to the ' +
      'house as it starts building.',
    'answer-ask': 'Answer Bosun: its question about this card, on the Bosun page, in its Now section. ' +
      'Bosun is told your answer and does only what the option you pick says.',
    'sendback': function (c) {
      if (K.gateOf(c) === 'plan') {
        return 'Send back: the house revises its plan with your reason, in the same conversation. ' +
          'Nothing is built yet.';
      }
      /* lane X: a tracking card has no house of its own to take the reason */
      return K.tracking(c)
        ? 'Send back: the card goes back to tracking its slices, with your reason as a note. ' +
          'No house is resumed; file or reopen a slice for the work.'
        : K.research && K.research(c)
          /* c-592: research and the like */
          ? 'Send back with a note: the house takes your note and works on, in the same ' +
            'conversation; the card goes back to building.'
        : 'Send back: the card goes back to building with your reason, in the same ' +
          'conversation. Nothing is published.';
    },
    'sendback-stay': 'Send back and stay: the house talks the plan through with you on its ' +
      'surface and keeps its slot. The plan is not approved.',
    /* lane X: on a tracking card the tap closes the ticket, and nothing lands or publishes */
    'approve-outcome': function (c) {
      /* c-667: a tier or flow proposal: this tap is the one that writes its draft */
      if (K.proposalOf && K.proposalOf(c)) {
        return 'Adopt: writes this card\'s draft into ' + K.proposalOf(c) + ', then the card is done and ' +
          'its finished house is stopped. Nothing changes until this tap (or Adopt beside the ' +
          'proposal in Setup or Settings, which is the same one).';
      }
      /* c-592: research, a plan, an errand: nothing to publish or land */
      if (K.research && K.research(c) && !K.tracking(c)) {
        return 'Done: you have read the result, and the card is done; its finished house is stopped. ' +
          'Nothing is published.';
      }
      return K.tracking(c)
        ? 'Approve outcome: closes the {ticket}: every slice is done and already landed. ' +
          'Nothing is merged or published.'
        : c.derived.review
          /* lane RC: a review card's Approve posts on a colleague's pull request */
          ? 'Approve: posts the findings you kept inline at their lines (an edit posts your ' +
            'words), then one summary and your verdict, on the {change}; the card is done.'
        : c.space === 'work' || (c.options && c.options.pr)
          /* c-600: a work card goes to shipping and keeps its house */
          ? 'Approve outcome: marks the {change} ready and moves the card to shipping; ' +
            'its house stays, and answers the reviewers there until you Ship.'
          : 'Approve outcome: publishes or lands the work and moves the card to done; its ' +
            'finished house is stopped.';
    },
    'answer': 'Answer and resume: the house continues its conversation with your words as ' +
      'its next turn, in the background. You are not in it; use Drop in to type into it.',
    'resume': 'Resume house: the house continues its conversation on its own, in the ' +
      'background. You are not in it; use Drop in to type into it.',
    'retry': 'Retry: starts a fresh house from scratch. The current conversation is dropped.',
    /* c-600: a shipping card's two controls of its own */
    'ship': 'Ship: one tap sends everything you accepted, in this order: pushes the house\'s commits, ' +
      'marks the {change} ready if it is a draft, and posts the replies you kept, once. The button ' +
      'says which of those are waiting. The card stays at shipping until it merges.',
    /* c-653 */
    'ship-why': 'Why nothing is sent from here now, or what to know before a send: the reason the ' +
      'backend would refuse or hold a Ship with.',
    /* r-55 (c-723) */
    'ship-prepared': 'The house prepared a fix that needs your yes (it replaces commits already pushed, ' +
      'or it is otherwise your call). Answer sends your words back to it as its next item.',
    /* c-655: the review that waits on a shipping card, handed to its house by his tap */
    'hand-over': 'Hand to the house: the review that waits here (comments, a review asking for changes, ' +
      'a failing check) is told to this card\'s house on the drain\'s next pass. It judges each one, and ' +
      'is closed when that turn ends. Nothing is posted until you Ship.',
    'hand-base': 'Bring the branch up to its base: the house merges the base into its branch, never a ' +
      'rebase or a force push, with whatever review waits. Nothing is pushed until you Ship.',
    /* c-663 */
    'ship-sendback': 'Send back: your own notes for this card\'s house. It is told them as its next item ' +
      'once it is free and does them, or says plainly why not. The card stays at shipping and ' +
      'nothing is posted; any commits go out with your next Ship.',
    'unblock': 'Unblock only: clears the block. Nothing starts until the drain picks the card up.',
    'dismiss': 'Dismiss: puts this notice away. The segment files it again if the condition ' +
      'is still true.',
    'end-discussion': 'End discussion: closes the plan discussion so the house\'s turn ends. ' +
      'The session is not stopped and the plan is not approved.',
    'regate': 'Back to your gate: every slice is done and you sent this card back. This brings it to ' +
      'review, and the drain closes it on its next pass, with a rollup of the slices as its outcome.',
    'split': 'Split: cuts this card into slices that run as cards of their own. This card ' +
      'then only tracks them.',
    'edit': 'Edit: changes the card\'s fields in the dialog. Nothing is sent to the house.',
    /* 2026-09-24: a review card's Edit, with only the two fields a review has */
    'review-settings': 'Review settings: the model this review runs on, and an optional focus note for the reviewer.',
    /* the card menu */
    'on-voice': 'On voice: voice is talking to this house, so nothing else resumes or stops ' +
      'it until the conversation ends.',
    'in-terminal': 'In a terminal: you dropped into this house, so Shipyard does not resume it ' +
      'until that session ends (or the hold runs out if you never opened it).',
    'open-app': 'Open in Claude app: the same session over Remote Control. What you type ' +
      'there lands in the house\'s conversation.',
    /* c-600: at shipping, Talk is one sheet with every way into the house's own session */
    'talk': 'Talk: every way into this card\'s house in one sheet, voice among them: what you say ' +
      'goes into its own session.',
    'talk-voice': 'Talk to this house: opens voice connected to it. What you say goes into its ' +
      'conversation, and the house is held while you talk.',
    'story': 'Open {ticket}: the card\'s {ticket} in {tracker_name}. Nothing changes here.',
    /* lane RC */
    'open-pr': 'Open {change_short}: the {change} this card reviews, on {codehost_name}. Nothing is posted.',
    'rereview': 'Re-review: new commits came after your review, so a new round starts on this card in a ' +
      'fresh session, told what you posted and dropped. Nothing is posted until you approve it.',
    /* lane GRP: a held review card's one way out of the wait for its story's other side */
    'review-now': 'Review now anyway: ends the wait for the other side\'s {change}, so this one is ' +
      'reviewed alone; it is never held again. Tap Review next to start it. Nothing is posted.',
    'design-doc': 'Open design doc: the card\'s design document. Nothing changes here.',
    'open-plan': 'Open plan: the house\'s plan, to read. Nothing is approved.',
    'open-output': function (c) {
      return c && K.pullsOf && K.pullsOf(c).length > 1
        ? 'Open output: the card has a {change} in each of its repos; pick one to open. Nothing is approved.'
        : 'Open output: what the house produced, to read. Nothing is approved.';
    },
    'context': 'View context: the card\'s context file, to read.',
    'worker': function (c) {
      return c && c.derived && c.derived.worker === 'bosun'
        ? 'Give to a house: a house builds it instead of Bosun, and its gates are yours. Only before anything starts.'
        : 'Give to Bosun: Bosun builds it instead of a house. Only before anything starts.';
    },
    'open-comments': 'Open comments: each round of review the house was told, what it did with each comment, and your replies.',
    /* c-642 */
    'open-ci': 'CI: the checks on its {changes} and the builds that carry its work, with a failed step\'s last lines.',
    /* c-592 */
    'open-result': 'Open result: what the house wrote, on its own page. Nothing is approved.',
    'open-named': 'The output the card names beside its result (a file it wrote, or its findings board), opened where it is read. Nothing is approved.',
    'open-outcome': 'Open outcome: the outcome on its own page, where you read it, note it and answer it. Nothing is approved.',
    'open-bosun': 'Open the Bosun page: Bosun builds this card; its queue, batch and asks are there.',
    'resume-house': 'Resume house: the house continues its conversation on its own, in the ' +
      'background. You are not in it; use Drop in to type into it.',
    'rotate': 'Rotate session: the house writes a checkpoint, then a NEW session carries on ' +
      'from it. The old conversation is not continued.',
    'resume-app': 'Resume and open in app: brings the house back idle, with no turn, and opens ' +
      'it in the Claude app so you can type to it.',
    'dropin': function (c) {
      if (inTerminal(c)) return DROPIN_OPEN;
      var said = dropinSaid(c);
      return said ? DROPIN_LEAD + said : DROPIN_ANY;
    },
    'verb': 'Carried out by this space\'s adapter.',
    'flow': 'A move of this space\'s flow: the card\'s house is told what to do, and says on the card what it did.',
    'logs': 'Logs: the house\'s recent terminal output, to read. Nothing is sent to it.',
    'stop': 'Stop session: ends the running session now. Its conversation is kept; Resume ' +
      'house or Drop in continues it.',
    'close-idle': 'Close idle house: ends this idle house to free its memory. Its next review ' +
      'batch, your answer at a gate, or Resume house brings it back in about 5 to 15 s, with ' +
      'its conversation. Offered only while the harness lists it idle.',
    'stop-twin': 'Stop stale session: ends the OTHER live session named for this card, left by ' +
      'a double start. The card\'s own session is not touched.',
    'assign': function (c) {
      /* lane RC: on a review card this tap IS "Review" */
      return c.derived.review
        ? 'Review: starts the review of this {change}; the drain starts it in the review pool. ' +
          'Nothing is posted until you approve its outcome.'
        : 'Assign: queues the card for the drain, which starts a house when a slot is free.';
    },
    'assign-tree': 'Assign tree: queues this card\'s unassigned slices. You see how many ' +
      'start and how many wait before you confirm.',
    'next-front': 'Move to front: the drain starts this card before the others waiting.',
    'next-filing': 'Back in filing order: drops the place you gave it; it waits in the order ' +
      'it was filed.',
    'backlog-active': 'Move to active: takes the card out of the backlog, back under Attention.',
    'backlog-send': 'Send to backlog: parks the card out of Attention. Its house and its gate ' +
      'are left as they are.',
    'backlog-auto': 'Back to auto: the date decides again (a card at its outcome gate longer ' +
      'than the backlog days goes to the backlog).',
    'archive': function (c) {
      /* lane RC, 2026-09-24: on a review card this tap is Dismiss review, and the fetcher
         brings the same card back on new activity (keel/reviewcards.py `revive`) */
      if (c.derived.review) {
        return c.derived.archived
          ? 'Restore review: puts this review back on the Reviews list.'
          : 'Dismiss review: hides this review. It is not filed again unless the {change} gets new activity.';
      }
      return c.derived.archived
        ? 'Unarchive: puts the card back in the lists.'
        : 'Archive: hides the card from the lists. Its house is not stopped.';
    },
    /* the phone's overflow */
    'more': 'More actions: every other action for this card.'
  };

  /* The state Drop in will act on, or null when this deck cannot tell. */
  function dropinSaid(c) {
    /* c-787: a done card resumes its conversation or opens one on its record; which, only
       the server's probe can tell */
    if (K.stageOf(c) === 'done') return null;
    if (!c.session_id) return DROPIN_SAID['new'];
    if (K.houseOf(c)) return DROPIN_SAID.attach;
    var listedHere = K.stageOf(c) === 'planning' || K.stageOf(c) === 'building' || !!c.blocked_reason;
    return listedHere ? DROPIN_SAID.resume : null;
  }

  /* An adapter verb's line: its own `help`, under its own label. */
  function verbTip(key) {
    var name = key.slice('verb-'.length);
    var v = ((K.spaceInfo().verbs || {}).card || []).filter(function (x) { return x.verb === name; })[0];
    return v && v.help ? v.label + ': ' + v.help + '.' : TIPS.verb;
  }

  /* THE BOARD'S OWN ACTIONS (lane BD), in a table of their own: TIPS above is every action a
     CARD draws, and `tests/test_card_tips.py` holds that table to the card's drawing. These
     are drawn by `app/ui.boarddelete.js`, and `tests/test_boarddelete_ui.py` holds them to
     it the same way, both directions. */
  var BOARD_TIPS = {
    'board-delete': 'Delete board: it goes to the trash and leaves every list, search and ' +
      'card pane. Include deleted on the board list restores it for 30 days; then it is purged.',
    'board-delete-stack': 'Delete all these boards: each goes to the trash, restorable from ' +
      'Include deleted on the board list for 30 days. Nothing else about the card changes.',
    'board-restore': 'Restore: the board comes back to the list where it stood, with ' +
      'everything on it. It does not become the live board over a newer one.'
  };
  function boardTip(key) { return BOARD_TIPS[key] || null; }

  /* A flow move's line: its own `about`, under its own label (c-640). */
  function flowTip(key, c) {
    var id = key.slice('flow-'.length);
    var spaces = (K.App.data || {}).spaces || {};
    var flow = ((spaces[c && c.space ? c.space : K.App.space] || {}).flow) || { moves: [] };
    var m = flow.moves.filter(function (x) { return x.id === id; })[0];
    return m && m.about ? m.label + ': ' + m.about : TIPS.flow;
  }

  /* A line's {ticket} and {change} are the card's space's words, or the deck's space's
     where no card is given (c-630) */
  function tip(key, c) {
    if (key.indexOf('verb-') === 0) return verbTip(key);
    if (key.indexOf('flow-') === 0) return flowTip(key, c);
    var line = TIPS[key];
    line = typeof line === 'function' ? line(c) : (line || null);
    return line && K.say(c && c.space ? c.space : K.App.space, line);
  }
  function tipped(node, key, c) {
    var line = tip(key, c);
    if (line) node.setAttribute('title', line);
    return node;
  }

  /* A card he dropped into (U3): its session is listed as running in a terminal, or it is
     held the way the server holds it (`views.dropin_holding`: seen, or not yet run out). */
  function inTerminal(c) {
    var h = K.houseOf(c);
    if (h && h.kind === 'interactive') return true;
    var held = c.options && c.options.dropin_hold;
    if (!held || typeof held !== 'object') return false;
    if (held.seen) return true;
    var until = Date.parse(held.until || '');
    return isNaN(until) || until > Date.now();
  }

  /* ---------- the groups (V2-1, 2026-09-24) ----------
   * "If we have hundreds of options it becomes hard to find the item." Every action a card
   * draws belongs to EXACTLY ONE group, here and nowhere else (`tests/test_card_groups.py`
   * holds it), and the desk draws one control per group: its most likely action for the
   * card's state as the button, and a caret that opens the rest, each with the line above
   * under its name. A group with one live action is a plain button; one with none is not
   * drawn. The order inside a group IS the preference: the first action the card has is
   * the one on the button, which is how the gate's primary (Approve plan, Approve outcome,
   * Answer and resume, a bare Resume house on a card with no session, Dismiss, Assign) is
   * always a group's button and never inside a menu. Pages' and Links' order follows the
   * stage. `verb` stands for every adapter verb, in the order the space lists them.
   *
   * c-644: Read was two things, the card's own pages (which open its viewer, where each
   * switches to the others) and links that leave the card; a split button named for its
   * first action made View context look as if it were the plan's. They are Pages and Links
   * now. And the flow's moves he makes are drawn in the groups the flow names (`group` on
   * each move, `flowGroupsOf`), not one Flow group: `flow` below is where they go. */
  var GROUPS = [
    { key: 'decide', name: 'Decide',
      keys: ['approve-plan', 'approve-outcome', 'approve-note', 'sendback', 'sendback-stay', 'answer-ask', 'regate', 'ship', 'ship-sendback'] },
    { key: 'continue', name: 'Continue',
      keys: ['answer', 'resume', 'rereview', 'review-now', 'resume-house', 'resume-app', 'retry', 'rotate', 'unblock',
             'hand-over', 'hand-base'] },
    { key: 'talk', name: 'Talk to it', keys: ['open-app', 'dropin', 'talk', 'talk-voice'] },
    { key: 'pages', name: 'Pages', keys: ['open-outcome', 'open-plan', 'context', 'open-comments', 'open-ci'] },
    { key: 'links', name: 'Links', keys: ['open-result', 'open-named', 'open-bosun', 'open-output', 'open-pr', 'story', 'design-doc', 'logs'] },
    /* c-640: the moves of the space's flow he makes (`flow-<move>`), drawn in the groups the
       flow names (c-644); a move that names none is drawn under Flow */
    { key: 'flow', name: 'Flow', keys: ['flow'] },
    { key: 'card', name: 'Card',
      keys: ['dismiss', 'assign', 'assign-tree', 'review-settings', 'edit', 'split', 'end-discussion', 'close-idle', 'stop', 'stop-twin', 'verb',
             'next-front', 'next-filing', 'backlog-active', 'backlog-send', 'backlog-auto', 'worker', 'archive'] }
  ];
  /* a fact about the card rather than an action: drawn before the groups, in none of them */
  /* `ship-why` (c-653): the line where Ship would be, saying why there is none */
  /* `need-codehost`, `need-tracker` (c-631): what the card's space has not set up. They were
     in no group and not here, so no row drew them (c-662). The order here is the row's:
     the lines, each a row wide, then the pills. */
  /* `ship-prepared` (r-55, c-723): the house's question on a fix it prepared, with Answer */
  var STATUS = ['need-codehost', 'need-tracker', 'ship-prepared', 'ship-why', 'on-voice', 'in-terminal'];

  /* Pages lead with what the stage is about: a result or an outcome to judge, the plan
     while it is being planned, the context while it is built, the comments at shipping. */
  var PAGES = ['open-outcome', 'open-plan', 'context', 'open-comments', 'open-ci'];
  function pagesOrder(c) {
    var s = K.stageOf(c);
    var lead = c.derived.review ? ['open-plan', 'context']
      : s === 'shipping' ? ['open-comments', 'context', 'open-ci']
      : s === 'review' || s === 'done' ? ['context', 'open-ci', 'open-comments']
      : s === 'planning' || s === 'inbox' || s === 'assigned' || K.tracking(c) ? ['open-plan', 'context']
      : ['context', 'open-plan', 'open-ci'];
    lead = ['open-outcome'].concat(lead);
    return lead.concat(PAGES.filter(function (k) { return lead.indexOf(k) < 0; }));
  }
  /* Links lead with the output once there is one: a review card's page (where the Ask is)
     at the gate, else the pull request it reviews; Bosun's page for a card Bosun builds. */
  function linksOrder(c) {
    var s = K.stageOf(c), rest = ['story', 'design-doc', 'logs'];
    if (c.derived.review) {
      return (c.derived.review === 'gate' ? ['open-output', 'open-pr'] : ['open-pr', 'open-output']).concat(['open-result', 'open-named', 'open-bosun'], rest);
    }
    /* a research card's result to judge leads, as it is the gate's primary (c-592) */
    /* c-719 r2.F1: a research card's named output follows its result */
    var out = s === 'review' || s === 'shipping' || s === 'done' ? ['open-result', 'open-named', 'open-bosun', 'open-output', 'open-pr'] : ['open-result', 'open-named', 'open-bosun', 'open-pr', 'open-output'];
    return out.concat(rest);
  }
  function tableKey(key) {
    return key.indexOf('verb-') === 0 ? 'verb' : key.indexOf('flow-') === 0 ? 'flow' : key;
  }
  /* The flow's own groups for a card (c-644): one per `group` its moves name, in the order
     the flow first names them, kept per space so a group is the same object on every draw
     (its menu's id is made from it). A move named into "Decide" joins the card's Decide. */
  var FLOW_GROUPS = {};
  function flowOf(c) {
    var spaces = (K.App.data || {}).spaces || {};
    return ((spaces[c.space] || {}).flow || {}).moves || [];
  }
  function slug(name) { return String(name).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'flow'; }
  function flowGroupsOf(c) {
    var seen = FLOW_GROUPS[c.space] || (FLOW_GROUPS[c.space] = {});
    var out = [];
    flowOf(c).forEach(function (m) {
      if (m.by !== 'you') return;
      var name = m.group || 'Flow';
      if (slug(name) === 'decide') return;
      var key = 'flow-' + slug(name);
      var g = seen[key] || (seen[key] = { key: key, name: name, keys: [], flow: true });
      g.name = name;          /* the same object, its name as the flow says it now (r1.F8) */
      if (out.indexOf(g) < 0) out.push(g);
    });
    return out;
  }
  /* The card's groups: the table, with Flow replaced by the flow's own */
  function groupsOf(c) {
    var out = [];
    GROUPS.forEach(function (g) {
      if (g.key === 'flow') out = out.concat(c ? flowGroupsOf(c) : [g]);
      else out.push(g);
    });
    return out;
  }
  function groupOf(key, c) {
    var k = tableKey(key);
    if (k === 'flow' && c) {
      var id = key.slice('flow-'.length);
      var move = flowOf(c).filter(function (m) { return m.id === id; })[0];
      var name = (move && move.group) || 'Flow';
      if (slug(name) === 'decide') return GROUPS[0];
      return flowGroupsOf(c).filter(function (g) { return g.key === 'flow-' + slug(name); })[0] || GROUPS.filter(function (g) { return g.key === 'flow'; })[0];
    }
    return GROUPS.filter(function (g) { return g.keys.indexOf(k) >= 0; })[0] || null;
  }
  /* A review card's Card group leads with what a review is answered by (2026-09-24):
     Review, then Review settings, then Dismiss review, before the queue and the backlog. */
  var REVIEW_CARD_LEAD = ['dismiss', 'assign', 'review-settings', 'archive'];
  function cardOrder(g, c) {
    if (!c.derived.review) return g.keys;
    return REVIEW_CARD_LEAD.concat(g.keys.filter(function (k) { return REVIEW_CARD_LEAD.indexOf(k) < 0; }));
  }
  function orderOf(g, c) {
    return g.key === 'pages' ? pagesOrder(c) : g.key === 'links' ? linksOrder(c) : g.key === 'card' ? cardOrder(g, c)
      : g.flow ? flowOf(c).map(function (m) { return 'flow-' + m.id; }) : g.keys;
  }
  function keyOf(node) { return node.getAttribute('data-key') || ''; }

  /* The card's keyed nodes, in groups: [{group, nodes}] in the table's order, each group's
     nodes in its preference order (the first is its button), empty groups left out. */
  function grouped(c, nodes) {
    return groupsOf(c).map(function (g) {
      var order = orderOf(g, c);
      var mine = nodes.filter(function (n) { return groupOf(keyOf(n), c) === g; });
      /* a flow group orders by the move's own id; the rest by their table key */
      var at = function (n) {
        var i = order.indexOf(g.flow ? keyOf(n) : tableKey(keyOf(n)));
        return i < 0 ? order.length : i;      /* a flow move in Decide sorts after the gate's own (r1.F3) */
      };
      mine.sort(function (a, b) { return at(a) - at(b); });
      return { group: g, nodes: mine };
    }).filter(function (x) { return x.nodes.length; });
  }
  function statusOf(nodes) {
    return nodes.filter(function (n) { return STATUS.indexOf(keyOf(n)) >= 0; })
      .sort(function (a, b) { return STATUS.indexOf(keyOf(a)) - STATUS.indexOf(keyOf(b)); });
  }

  /* The line under an entry's name: the hover line without the name it starts with, which
     the entry already shows in bold right above it. */
  function lineUnder(key, c) {
    var line = tip(key, c) || '';
    var cut = /^[^.:]{1,40}: /.exec(line);
    if (cut) line = line.slice(cut[0].length);
    return line.charAt(0).toUpperCase() + line.slice(1);
  }
  function menuId(c, where, g) { return 'menu-' + where + '-' + c.id + '-' + g.key; }
  /* {alone, rest}: the critical actions that would lead a group, and the group without them */
  function critLead(nodes) {
    var rest = nodes.slice(), alone = [];
    while (rest.length > 1 && /\bcrit\b/.test(rest[0].className || '')) alone.push(rest.shift());
    return { alone: alone, rest: rest };
  }

  /* One row of group controls: the status pills, then a split button per group with more
     than one live action and a plain button per group with one. `where` names the surface
     (`pane`, `tile`), so the same card's menu on two surfaces is two menus. */
  function groupRow(c, nodes, where) {
    var out = statusOf(nodes), live = grouped(c, nodes);
    live.forEach(function (x) {
      /* A CRITICAL ACTION IS NEVER THE LEAD OF A SPLIT GROUP (c-653). Stop session led the
         Card group at shipping, and the caret that shares its border was drawn over the
         stop's red edge, so the two read as one cut control. It stands alone, with the
         row's own gap, and the rest of its group is that group's own control. */
      var parts = critLead(x.nodes);
      parts.alone.forEach(function (n) { out.push(n); });
      x = { group: x.group, nodes: parts.rest };
      if (!x.nodes.length) return;
      if (x.nodes.length === 1) { out.push(x.nodes[0]); return; }
      /* the group's name on its caret (c-644 r2.F1): "Open plan | Pages ▾", so View context
         under the caret never reads as the plan's; the Now tile is too tight for it */
      out.push(K.splitButton({ id: menuId(c, where, x.group), key: x.group.key, name: x.group.name, named: where !== 'tile',
        main: x.nodes[0], rest: x.nodes.slice(1),
        line: function (n) { return lineUnder(keyOf(n), c); },
        sheet: function () { K.App.sheet = { kind: 'menu', id: c.id, where: where, group: x.group.key }; K.renderSheet(); } }));
    });
    return out;
  }

  /* The phone's More actions, and a phone menu: every action UNDER ITS GROUP'S HEADING, each
     with its line under its name, so the phone reads what the desk hovers. */
  function groupedList(c, nodes, where) {
    return el('div', { class: 'glist', 'data-key': 'glist' }, grouped(c, nodes).map(function (x) {
      return el('section', { class: 'gsec', 'data-key': 'gs-' + x.group.key },
        el('h4', { class: 'label ghead', text: x.group.name }),
        x.nodes.map(function (n) { return K.menuEntry(n, lineUnder(keyOf(n), c), where + '-' + c.id, null); }));
    }));
  }

  /* Where a surface's actions come from, so a phone menu sheet can draw them again: the
     render pass rebuilds everything, and the sheet is drawn outside it. */
  var SOURCES = {};
  function menuSheet(s) {
    var c = K.byId(s.id), source = SOURCES[s.where];
    if (!c || !source) return el('div', { class: 'sheet' });
    var x = grouped(c, source(c)).filter(function (y) { return y.group.key === s.group; })[0];
    var close = function () { K.App.sheet = null; K.renderSheet(); };
    return el('div', { class: 'sheet', 'data-key': 'sheet-menu' },
      el('div', { class: 'sheet-head' }, el('button', { onclick: close }, '‹ close'),
        el('span', { class: 'spacer' }), el('span', { class: 'mono t11 ink2', text: c.id + ' · ' + (x ? x.group.name : '') })),
      el('div', { class: 'sheet-body' }, el('div', { class: 'title', text: c.title }),
        x ? groupedList(c, critLead(x.nodes).rest.slice(1).map(function (n) { return closingSheet(n); }), 'sheet') : null));
  }
  function closingSheet(node) {
    var fn = node.onclick;
    var wrapped = function (ev) { K.App.sheet = null; K.renderSheet(); return fn ? fn.call(this, ev) : undefined; };
    node.onclick = wrapped;
    (node._on || (node._on = {})).onclick = wrapped;
    return node;
  }

  /* ---------- Resume and open in app (V2-2) ----------
   * The server wakes the house with no turn and answers with its link (`house.open_app`,
   * keel/openapp.py). A tab opened after a network answer is a popup the browser blocks,
   * so the tab is opened ON THE TAP, empty, and pointed at the link when it arrives; with
   * no link it is closed again and the answer says why. */
  function appResumable(c) {
    return !!c.session_id && !K.houseBusy(c) && !c.derived.voice_hold && !inTerminal(c)
      && !(K.houseOf(c) && c.options.app_link);
  }
  function openedIn(tab, r) {
    if (r && r.link) {
      if (tab) { tab.opener = null; tab.location.href = r.link; return 'the house is up, opened in the Claude app'; }
      K.openLink(r.link);
      return 'the house is up; Open in Claude app has its link';
    }
    if (tab) tab.close();
    return { text: (r && r.note) || 'the house is awake, but it has no app link yet', err: true };
  }
  function resumeAppBtn(c, label, cls) {
    var body = { verb: 'house.open_app', id: c.id };
    return K.faceBtn(label, body, cls || '', function (ev) {
      if (ev && ev.stopPropagation) ev.stopPropagation();
      var tab = null;
      try { tab = window.open('', '_blank'); } catch (e) { tab = null; }
      K.act(body, function (r) { return openedIn(tab, r); }, ev && ev.currentTarget)
        .then(function (r) { if (!r && tab) tab.close(); });
    });
  }

  K.GROUPS = GROUPS; K.groupOf = groupOf; K.grouped = grouped; K.groupRow = groupRow; K.groupsOf = groupsOf;
  K.groupedList = groupedList; K.menuSheet = menuSheet; K.lineUnder = lineUnder;
  K.actionSources = SOURCES; K.appResumable = appResumable; K.resumeAppBtn = resumeAppBtn;

  K.BOARD_TIPS = BOARD_TIPS; K.boardTip = boardTip;
  K.TIPS = TIPS; K.tip = tip; K.tipped = tipped; K.inTerminal = inTerminal;
})(window.Keel);
