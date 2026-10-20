/* EVERY PAGE'S FIND TABLE (lane FIND, 2026-09-24), in one place so the pages cannot drift:
 * the same words for the same idea ("Include done", "Include archived", "Include deleted"),
 * the same shape for every facet. A page's table is everything the find bar needs to know
 * about it; the engine (app/ui.findcore.js) and the bar (app/ui.find.js) do the rest.
 *
 * A table: {page, noun: [one, many], placeholder,
 *   facets:  [{key, label, values(items) -> [{value, label}], match(item, value, ctx), search?}]
 *   include: [{key, label, group?}]  the switches for what the page hides by default;
 *            `hidden(item, ctx)` names the switch that shows an item (or null), or a list
 *            of them when it takes several
 *   text(item) -> the words the search looks in (or `textMatch(item, words)`)
 *   sorts:   [{key, label, cmp(a, b, ctx)}], the default first
 *   views:   the built-in presets, [{key, label, state: {f, inc, sort}}]
 *   modes:   [{key, label, options(state, ctx) -> [{key, label}], fallback(ctx)}]}
 *
 * `ctx` is {desk, space, now}: what the page is drawn for.
 */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  function opts(pairs) { return pairs.map(function (p) { return { value: p[0], label: p[1] }; }); }
  function distinct(list, pick) { return K.findCore.distinct(list, pick); }
  function time(iso) { var t = new Date(iso || 0).getTime(); return isNaN(t) ? 0 : t; }
  function newer(field) { return function (a, b) { return time(b[field]) - time(a[field]); }; }

  /* ---------- Cards ---------- */
  var STAGE_VALUES = opts([['inbox', 'Inbox'], ['assigned', 'Assigned'], ['planning', 'Planning'],
                           ['building', 'Building'], ['review', 'Review'], ['shipping', 'Shipping']]);
  var STAGE_ORDER = ['inbox', 'assigned', 'planning', 'building', 'review', 'shipping', 'done'];
  function stageOf(c) { return K.stageOf ? K.stageOf(c) : c.stage; }
  function repos(c) { return String(c.repo || '').split(',').map(function (r) { return r.trim(); }).filter(Boolean); }
  /* One kind per card, the loudest first: a tracking card works at nothing itself, a
     research card ships nothing, an errand has no repo. A review card is never on Cards
     (2026-09-24; Reviews is its list), so it is no kind here. */
  function kindOf(c) {
    var o = c.options || {}, d = c.derived || {};
    if (d.tracking || (c.children && c.children.length)) return 'tracking';
    if (o.kind === 'research') return 'research';
    if (d.kind === 'errand' || !c.repo) return 'errand';
    return 'house';
  }
  function queuePos(c) { return K.queuePos ? K.queuePos(c) : 0; }
  function byQueue(a, b) {
    var pa = queuePos(a) || 1e9, pb = queuePos(b) || 1e9;
    return pa - pb;
  }
  function spaceList(key) { return (K.spaceInfo ? K.spaceInfo()[key] : null) || []; }
  function withKnown(found, known) {
    var have = found.map(function (v) { return v.value; });
    known.forEach(function (k) { if (have.indexOf(k) < 0) found.push({ value: k, label: k }); });
    return found.sort(function (a, b) { return a.label.localeCompare(b.label); });
  }

  var cards = {
    page: 'cards', noun: ['card', 'cards'],
    placeholder: 'Search cards, or type stage:review repo:keel',
    facets: [
      { key: 'stage', label: 'Stage', values: function () { return STAGE_VALUES; },
        match: function (c, v) { return stageOf(c) === v; } },
      { key: 'needs', label: 'Needs', values: function () { return opts([['me', 'Needs me'], ['blocked', 'Blocked']]); },
        match: function (c, v) { return v === 'me' ? !!(c.derived && c.derived.needs_you) : !!c.blocked_reason; } },
      { key: 'repo', label: 'Repo', values: function (list) { return withKnown(distinct(list, repos), spaceList('repos')); },
        match: function (c, v) { return repos(c).indexOf(v) >= 0; } },
      { key: 'topic', label: 'Topic', values: function (list) {
          return withKnown(distinct(list, function (c) { return c.topic; }), spaceList('topics'));
        }, match: function (c, v) { return c.topic === v; } },
      { key: 'kind', label: 'Kind', values: function () {
          return opts([['house', 'House'], ['errand', 'Errand'], ['research', 'Research'], ['tracking', 'Tracking']]);
        }, match: function (c, v) { return kindOf(c) === v; } }
    ],
    include: [{ key: 'done', label: 'Include done' }, { key: 'backlog', label: 'Include backlog' },
              { key: 'archived', label: 'Include archived' }],
    /* archived first: an archived card is history whatever its stage, and it comes back
       with Include archived alone */
    hidden: function (c) {
      if (c.derived && c.derived.archived) return 'archived';
      /* c-592: a Keel card he filed stays on his board, done, until it is live */
      if (stageOf(c) === 'done' && !(c.derived && c.derived.keel_card && c.derived.keel_card.shown)) return 'done';
      if (c.derived && c.derived.backlog) return 'backlog';
      return null;
    },
    text: function (c) {
      var o = c.options || {};
      return [c.id, c.title, c.topic, c.repo, o.branch, o.tracker_ref, o.pr ? '#' + o.pr : '',
              String(c.brief || '').slice(0, 400)].join(' ');
    },
    sorts: [
      { key: 'queue', label: 'Queue order', cmp: byQueue },
      { key: 'updated', label: 'Recently updated', cmp: newer('updated_at') },
      { key: 'newest', label: 'Newest created', cmp: newer('created_at') },
      { key: 'oldest', label: 'Oldest created', cmp: function (a, b) { return time(a.created_at) - time(b.created_at); } },
      { key: 'stage', label: 'Stage', cmp: function (a, b) {
          return STAGE_ORDER.indexOf(stageOf(a)) - STAGE_ORDER.indexOf(stageOf(b)) || byQueue(a, b);
        } }
    ],
    views: [
      { key: 'needs', label: 'Needs me', state: { f: { needs: ['me'] } } },
      { key: 'flight', label: 'In flight', state: { f: { stage: ['assigned', 'planning', 'building'] } } },
      { key: 'shipping', label: 'Shipping', state: { f: { stage: ['shipping'] } } },
      /* a backlogged card sits at its outcome gate, so the backlog is the review stage with
         the backlog switch on, oldest first */
      { key: 'backlog', label: 'Backlog', state: { f: { stage: ['review'] }, inc: ['backlog'], sort: 'oldest' } }
    ],
    modes: [
      { key: 'layout', label: 'Layout', options: function (st, ctx) {
          return ctx.desk ? [{ key: 'table', label: 'Table' }, { key: 'kanban', label: 'Kanban' }] : [{ key: 'list', label: 'List' }];
        }, fallback: function (ctx) { return ctx.desk ? 'table' : 'list'; } },
      /* kanban IS a grouping by stage, so it offers none: a choice that would do nothing
         there is not drawn rather than drawn and ignored */
      { key: 'group', label: 'Group by', options: function (st, ctx) {
          if (K.findCore.modeOf(st, cards, ctx, 'layout') === 'kanban') return [];
          return [{ key: 'none', label: 'None' }, { key: 'stage', label: 'Stage' }, { key: 'topic', label: 'Topic' },
                  { key: 'parent', label: 'Parent' }, { key: 'repo', label: 'Repo' }];
        }, fallback: function (ctx) { return ctx.desk ? 'none' : 'stage'; } }
    ],
    kindOf: kindOf
  };

  /* ---------- the board list (Saved) ---------- */
  var DAY = 86400000;
  /* A review card's board (lane FC, FC-4) is its own source: it describes a colleague's code */
  function sourceOf(r) {
    if ((r.source || {}).kind !== 'card') return 'harbor';
    return (r.card || {}).review ? 'review' : 'house';
  }
  function cardOf(r) { return (r.source || {}).card || ''; }
  function age(r, ctx) { return (ctx && ctx.now ? ctx.now : Date.now()) - time(r.updated); }
  function startOfDay(ctx) {
    var d = new Date(ctx && ctx.now ? ctx.now : Date.now());
    d.setHours(0, 0, 0, 0);
    return d.getTime();
  }
  var UPDATED = {
    today: function (r, ctx) { return time(r.updated) >= startOfDay(ctx); },
    week: function (r, ctx) { return age(r, ctx) <= 7 * DAY; },
    month: function (r, ctx) { return age(r, ctx) <= 30 * DAY; }
  };
  var boards = {
    page: 'boards', noun: ['board', 'boards'],
    placeholder: 'Search boards, or type source:house',
    facets: [
      { key: 'source', label: 'Source', values: function () { return opts([['house', 'House'], ['harbor', 'Harbor'], ['review', 'Review']]); },
        match: function (r, v) { return sourceOf(r) === v; } },
      /* many values, so the panel gives this facet a search of its own */
      { key: 'card', label: 'Card', search: true, values: function (list) {
          var seen = {}, out = [];
          list.forEach(function (r) {
            var id = cardOf(r);
            if (!id || seen[id]) return;
            seen[id] = true;
            out.push({ value: id, label: id + ((r.card || {}).title ? ' ' + r.card.title : '') });
          });
          return out.sort(function (a, b) { return a.value.localeCompare(b.value, undefined, { numeric: true }); });
        }, match: function (r, v) { return cardOf(r) === v; } },
      { key: 'state', label: 'State', values: function () { return opts([['live', 'Live'], ['closed', 'Closed']]); },
        match: function (r, v) { return v === 'live' ? !!(r.live && !r.closed) : !!r.closed; } },
      { key: 'updated', label: 'Updated', values: function () {
          return opts([['today', 'Today'], ['week', 'This week'], ['month', 'This month']]);
        }, match: function (r, v, ctx) { return !!UPDATED[v] && UPDATED[v](r, ctx); } }
    ],
    /* The GLOBAL space switch applies here too: a house board of the other space is hidden
       until All spaces is on. Harbor's boards belong to no card and so to no space, and are
       listed in both. */
    /* REVIEW BOARDS ARE OFF THE LIST until he asks for them (lane FC, FC-4): a review card's
       board draws a colleague's change, not his own work. Its outcome's embed, Open board and
       a direct link still open it; only the list, its search, its counts and its stacks
       leave it out. */
    /* A FINISHED CARD'S BOARDS ARE OFF THE LIST too (c-562): a card at done or archived
       (`card.done`, keel/boardlist.py) is history, and Include done ADDS its boards under a
       Done heading. Done is a SECOND reason beside the others, so a done board of the other
       space needs All spaces and Include done both; Harbor's boards have no card and are
       never done. */
    include: [{ key: 'deleted', label: 'Include deleted' }, { key: 'done', label: 'Include done' },
              { key: 'review', label: 'Include review boards' },
              { key: 'allspaces', label: 'All spaces', group: 'Space' }],
    hidden: function (r, ctx) {
      if (r.deleted) return 'deleted';
      var card = r.card || {}, why = [];
      if (card.review) why.push('review');
      else if (card.space && ctx && ctx.space && card.space !== ctx.space) why.push('allspaces');
      if (card.done) why.push('done');
      return why.length > 1 ? why : why[0] || null;
    },
    /* The words go to the server (`GET /api/boards?q=`, which reads every board whole), so a
       listed row has already matched; only the trash is searched here. */
    textMatch: function (r, words) {
      if (!r.deleted) return true;
      var hay = [r.id, r.title, cardOf(r), (r.card || {}).title].join(' ').toLowerCase();
      return words.split(/\s+/).every(function (w) { return hay.indexOf(w) >= 0; });
    },
    sorts: [
      { key: 'activity', label: 'Latest activity', cmp: newer('updated') },
      { key: 'newest', label: 'Newest created', cmp: newer('created') },
      { key: 'title', label: 'Title', cmp: function (a, b) { return String(a.title || '').localeCompare(String(b.title || '')); } }
    ],
    views: [
      { key: 'week', label: 'Mine this week', state: { f: { updated: ['week'] } } },
      { key: 'houses', label: 'From houses', state: { f: { source: ['house'] } } },
      { key: 'harbor', label: 'From Harbor', state: { f: { source: ['harbor'] } } },
      { key: 'review', label: 'Review boards', state: { f: { source: ['review'] }, inc: ['review'] } }
    ],
    modes: []
  };

  /* ---------- Reviews: the review cards (lane RC) ---------- */
  function prOf(c) { return (c.options && c.options.review_pr) || {}; }
  function raised(c) { return prOf(c).created || c.created_at; }
  function activity(c) { return prOf(c).activity || prOf(c).updated || c.updated_at; }
  function since(ctx, days) { return (ctx && ctx.now ? ctx.now : Date.now()) - days * DAY; }
  var RAISED = {
    today: function (c, ctx) { return time(raised(c)) >= startOfDay(ctx); },
    week: function (c, ctx) { return time(raised(c)) >= since(ctx, 7); },
    older: function (c, ctx) { return time(raised(c)) < since(ctx, 7); }
  };
  /* THE OLD REVIEW BOARD'S SIX COLUMNS (2026-09-24), in its order and under its names: the
     State facet and the Reviews kanban read this one table, so the filter and the columns
     agree. `said` is what each means, drawn under the column's name. */
  var REVIEW_LANES = [
    { key: 'detected', label: 'Detected', said: 'Waiting for your Review tap.' },
    { key: 'assigned', label: 'Assigned', said: 'Queued for the review pool, or being reviewed.' },
    { key: 'inbox', label: 'Inbox', said: 'Reviewed: the findings wait at your gate for Approve to post them.' },
    { key: 'held', label: 'Held', said: 'Waiting up to 48 hours for its other side, quiet past the backlog days, or held by you.' },
    { key: 'posted', label: 'Posted', said: 'Your review is on the {change}; new commits say so here.' },
    { key: 'dismissed', label: 'Dismissed', said: 'Put away by you; back on new activity.' }
  ];
  var LANE_OF_STATE = { waiting: 'detected', reviewing: 'assigned', gate: 'inbox', posted: 'posted', 'new': 'posted' };
  /* One column per review card: dismissed (archived) first, then held (the derived backlog,
     the old Hold), then its state; a closed one (its pull request merged or was declined)
     sits where it stopped, posted when he had posted, else detected. */
  function laneOf(c) {
    var d = c.derived || {};
    if (d.archived) return 'dismissed';
    if (d.backlog || d.review === 'held') return 'held';
    if (d.review === 'closed') return (c.options || {}).review_posted ? 'posted' : 'detected';
    return LANE_OF_STATE[d.review] || null;
  }
  function byStamp(pick, newest) {
    return function (a, b) { var d = time(pick(b)) - time(pick(a)); return newest ? d : -d; };
  }
  var reviews = {
    page: 'reviews', noun: ['review', 'reviews'],
    placeholder: 'Search reviews, or type state:inbox author:',
    facets: [
      { key: 'state', label: 'State', values: function () {
          return REVIEW_LANES.map(function (l) { return { value: l.key, label: l.label }; });
        }, match: function (c, v) { return laneOf(c) === v; } },
      /* a posted card with new commits stays Posted; this is how to find those */
      { key: 'commits', label: 'New commits', values: function () { return opts([['new', 'Since your review']]); },
        match: function (c) { return (c.derived || {}).review === 'new'; } },
      { key: 'author', label: 'Author', values: function (list) { return distinct(list, function (c) { return prOf(c).author; }); },
        match: function (c, v) { return prOf(c).author === v; } },
      { key: 'repo', label: 'Repo', values: function (list) { return distinct(list, repos); },
        match: function (c, v) { return repos(c).indexOf(v) >= 0; } },
      { key: 'severity', label: 'Highest finding', values: function () {
          return opts([['critical', 'Critical'], ['high', 'High'], ['medium', 'Medium'], ['low', 'Low']]);
        }, match: function (c, v) { return String((c.derived || {}).review_severity || '').toLowerCase() === v; } },
      { key: 'raised', label: 'Raised', values: function () {
          return opts([['today', 'Today'], ['week', 'This week'], ['older', 'Older']]);
        }, match: function (c, v, ctx) { return !!RAISED[v] && RAISED[v](c, ctx); } }
    ],
    /* dismissed first: Dismiss review archives a review card, whatever else it is; then a
       closed one (its pull request merged or was declined, `derived.review` closed), which
       is history; a quiet one waiting for his Review sits in the derived backlog
       (views.review_backlog). Each is out until its Include switch is on. */
    include: [{ key: 'backlog', label: 'Include backlog' }, { key: 'closed', label: 'Include closed' },
              { key: 'dismissed', label: 'Include dismissed' }],
    hidden: function (c) {
      if (c.derived && c.derived.archived) return 'dismissed';
      if (c.derived && c.derived.review === 'closed') return 'closed';
      if (c.derived && c.derived.backlog) return 'backlog';
      return null;
    },
    text: function (c) {
      var o = c.options || {};
      /* a feature card is found by any member's label (lane GRP) */
      var members = (o.review_members || []).map(function (m) { return m.label + ' #' + m.pr; }).join(' ');
      return [c.id, c.title, c.repo, prOf(c).author, o.pr ? '#' + o.pr : '', o.branch, members].join(' ');
    },
    sorts: [
      { key: 'raised', label: 'Newest raised', cmp: byStamp(raised, true) },
      { key: 'oldest', label: 'Oldest raised', cmp: byStamp(raised, false) },
      { key: 'activity', label: 'Latest activity', cmp: byStamp(activity, true) }
    ],
    views: [
      { key: 'waiting', label: 'Waiting for me', state: { f: { state: ['detected'] } } },
      { key: 'gate', label: 'At my gate', state: { f: { state: ['inbox'] } } },
      { key: 'new', label: 'New commits', state: { f: { commits: ['new'] } } },
      /* the quiet ones (the old Hold): their pull request still, oldest first */
      { key: 'held', label: 'Held', state: { f: { state: ['held'] }, inc: ['backlog'], sort: 'oldest' } }
    ],
    /* List or Kanban on the desk, remembered and in the URL like Cards' layout; the phone
       stays a list, as Cards' kanban is desk only (app/ui.reviews.js draws the lanes) */
    modes: [
      { key: 'layout', label: 'Layout', options: function (st, ctx) {
          return ctx.desk ? [{ key: 'list', label: 'List' }, { key: 'kanban', label: 'Kanban' }] : [{ key: 'list', label: 'List' }];
        }, fallback: function () { return 'list'; } }
    ],
    lanes: REVIEW_LANES,
    laneOf: laneOf
  };

  K.findPages = { cards: cards, boards: boards, reviews: reviews };
})(window.Keel);
