/* The deck's core: state, helpers, the morph, the live channel, routing and the chrome.
 *
 * Every module hangs off `window.Keel`. The load order is app/views.json's `scripts`
 * (c-634): this file first, ui.js (the boot) last, and a name is only ever read at call
 * time, so a later module may be referenced from an earlier one.
 *
 * `K.morph` (below) is what the rest of the page rests on: a renderer builds a fresh tree
 * and the morph writes only the difference into the live one, so nothing the DOM was
 * holding for the reader is thrown away. The patches that used to put back what a rebuild
 * ate are gone with it: the scroll map over every inner scroller, the focus mark and
 * restore, and the node cache the pane kept per section. What is left of the scroll
 * memory is one number per route, read back only on the pass that enters a route.
 * `openStream` is the other half: one EventSource on `/api/events` says what changed, and
 * the five second poll in `ui.js` is only the fallback for while that is shut.
 *
 * Routes are `?view=<name>` (now, attention, cards, segments, reviews, atlas, setup, settings, start, more) with
 * `&step=<id>` for the first-run stepper's screen (c-632), `&card=<id>` for a selected card and `&key=<row key>` for a selected provider row: the
 * detail pane beside the list on the desk, a full-screen route on the phone. `?space=`
 * and `?d=` pin the palette and the density. The PRs page is gone (lane RETIRE): an old
 * link to its route, or a remembered one, lands on Cards with the find bar's Shipping view.
 * Selecting a card pushes history, so Back closes it and lands on the list again.
 * Nothing here knows an employer's vocabulary: the adapter's options.json, its providers
 * and its `act verbs` supply the labels. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  /* `shipping` (lane SHIP): a work card whose pull request is ready, until it merges */
  var STAGES = ['inbox', 'assigned', 'planning', 'building', 'review', 'shipping', 'done'];
  /* THE VIEWS ARE THE MANIFEST'S (c-634): app/views.json, which the server writes into the
     page as `window.KEEL_VIEWS` (keel/deckviews.py). A page that is not the deck (the plan
     page, the Console) has none, and an empty list. Each row says how its body is drawn
     (`K[render](arg)`, app/ui.js) and:
     - `needs`, the readiness rows it depends on (c-631, keel/readiness.py): the one gating
       in the deck, and it never hides a view. An unmet one draws a panel saying what is
       missing and where to set it up (`K.needs`).
     - `dock`: true puts it in the phone dock; `when-ready` keeps it out until its needs are
       met, and it is under More until then.
     - `rail: 'until-finished'` keeps the first-run stepper on the desk's rail until Finish
       (c-632); More lists it always.
     - `nav: false` keeps a row off the rail: More, which is a dock item only.
     `ROWS` is every row, `VIEWS` the ones the rail lists, `DOCK` the dock's keys in order. */
  var ROWS = ((window.KEEL_VIEWS || {}).views || []).slice();
  var VIEWS = ROWS.filter(function (v) { return v.nav !== false; });
  /* Lane RETIRE (RT-1): the retired PRs page's route, and the Cards view that replaced it. A
     work pull request Keel's house built is a card in `shipping`. */
  var RETIRED_PRS = 'prs', SHIPPING_VIEW = 'shipping';
  var DOCK = ROWS.filter(function (v) { return v.dock; }).map(function (v) { return v.key; });
  var POLL_MS = 5000;

  var App = {
    data: null, detail: null, detailFor: null,
    view: 'now', space: '', density: 'work', card: null, row: null,
    /* the first-run stepper's screen (`?step=`, app/ui.start.js) */
    step: null,
    /* the Board route's own place in the URL: the board id, from the PATH, and which of
       its three views, from the query (see `boardPath`) */
    board: null, boardView: null,
    /* each page's find state (search, filters, sort, view), kept by app/ui.find.js */
    find: {},
    modal: null, sheet: null, timer: null, allEvents: false,
    /* the one split-button menu that is open (V2-1): {id}, or null */
    menu: null,
    pushedDetail: false, dragRow: null, dragTile: null,
    /* what is in flight, and what the page is covering for until the board catches up */
    pending: {}, bridge: {},
    /* what he has typed at a gate and not sent yet, one draft per card and gate */
    drafts: {}
  };

  K.STAGES = STAGES; K.VIEWS = VIEWS; K.DOCK = DOCK; K.ROWS = ROWS; K.App = App;
  /* the install's own repos (keel/builder.py OWN_REPOS, c-722 r1.F1): its packs and its
     memory, built on cards like any repo but never one of the user's */
  K.OWN_REPOS = ['packs', 'memory'];
  K.ownRepo = function (key) { return K.OWN_REPOS.indexOf(key) >= 0; };

  /* ---------- small helpers ---------- */
  /* A handler goes on as a PROPERTY (`node.onclick`), never through addEventListener, so
     `morph` below can lift the new pass's closure onto a node it kept: a listener added
     with addEventListener cannot be read back off a node, and a kept node still carrying
     last pass's closure would act on last pass's card. `_on` is the same set by name, so
     the morph can also clear a handler the new pass no longer has.
     A form value goes on as a property too and is recorded in `_props`, because the morph
     has to tell "the new tree says this field reads abc" from "the new tree says nothing
     about it", and an attribute cannot say the second. */
  var PROPS = { value: 1, checked: 1, selected: 1, open: 1 };
  function el(tag, attrs) {
    var node = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === 'text') node.textContent = v;
      else if (k === 'html') node.innerHTML = v;
      else if (k === 'class') node.className = v;
      else if (k.indexOf('on') === 0 && typeof v === 'function') {
        node[k] = v;
        (node._on || (node._on = {}))[k] = v;
      } else if (PROPS[k]) {
        node[k] = k === 'value' ? v : true;
        (node._props || (node._props = {}))[k] = k === 'value' ? v : true;
      } else node.setAttribute(k, v === true ? '' : v);
    });
    for (var i = 2; i < arguments.length; i++) add(node, arguments[i]);
    return node;
  }
  function add(node, child) {
    if (child === null || child === undefined || child === false) return;
    if (Array.isArray(child)) { child.forEach(function (c) { add(node, c); }); return; }
    node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  }

  /* ---------- the morph: the page changes rather than reloads ----------
   * `K.el` builds a FRESH tree every pass, which is the cheap thing to write. `morph` is
   * what makes drawing it cheap too: it walks the new tree against the LIVE one and changes
   * only what differs, so the live node never leaves the document. Everything the DOM was
   * holding for the reader then survives by construction rather than by a patch per kind:
   * the scroll offset of the page and of every inner scroller, the caret and the selection
   * in a field, a CSS transition part way through, an SVG's pan and zoom transform, ELK's
   * layout, an open <details>. The page used to rebuild `#body` whole every five seconds,
   * which is the whole of what "it looks like it reloaded" was.
   *
   * The rules, all of them:
   * - A child is matched by `data-key` when it has one and by POSITION AND TAG when it does
   *   not. A keyed row that moved is the same node in its new place; a row that went is
   *   removed and one that arrived is inserted, and nothing between them is touched.
   * - Handlers are carried from the new node onto the kept one on every pass, because a
   *   closure captures the card it was built from (see `el` above).
   * - `value`, `checked`, `selected` and `open` are written only when the new tree names
   *   them AND the element is not the one he is typing in. What is half typed is his.
   * - A subtree marked `data-morph="skip"` is left whole, node and children alike, and
   *   only its handlers are carried. The board's frame body is drawn by ELK and panned
   *   with a finger; neither belongs to the render pass, which builds that node empty, so
   *   the pass does not get to touch it and its owner keeps it current.
   *
   * A listener attached IMPERATIVELY (a tile's dragstart, a strip's own scroll) stays on
   * the live node and is never re-attached, so whatever such a closure captures has to be
   * stable for the node's key: the kanban tile is keyed by its card id and its drag reads
   * that id, the lane is keyed by its stage.
   */
  function keyOf(node) {
    return node.nodeType === 1 ? node.getAttribute('data-key') : null;
  }
  function sameKind(a, b) {
    if (a.nodeType !== b.nodeType) return false;
    return a.nodeType !== 1 || a.nodeName === b.nodeName;
  }
  function carry(live, next) {
    var was = live._on, now_ = next._on, name;
    if (was) for (name in was) { if (!now_ || !(name in now_)) live[name] = null; }
    if (now_) for (name in now_) live[name] = now_[name];
    live._on = now_ || null;
  }
  function syncAttrs(live, next) {
    var attrs = next.attributes, i, name;
    for (i = 0; i < attrs.length; i++) {
      if (live.getAttribute(attrs[i].name) !== attrs[i].value) live.setAttribute(attrs[i].name, attrs[i].value);
    }
    attrs = live.attributes;
    for (i = attrs.length - 1; i >= 0; i--) {
      name = attrs[i].name;
      if (!next.hasAttribute(name)) live.removeAttribute(name);
    }
  }
  function syncProps(live, next) {
    var props = next._props, name;
    live._props = props || null;
    if (!props || live === document.activeElement) return;
    for (name in props) { if (live[name] !== props[name]) live[name] = props[name]; }
  }
  /* True when this subtree is not the render pass's to touch, AT ALL: the node's own
     attributes as well as its children. There is no condition on it, because the renderer
     builds a skip node EMPTY (the board's `.bframe-body` is a class and this attribute and
     nothing else), so a pass that decided to morph it after all would delete what its
     owner drew and then leave it blank. Whoever draws into a skip subtree owns keeping it
     current; `mount` in ui.board.js does, off the frame's own version. */
  function skipped(live, next) {
    return next.getAttribute('data-morph') === 'skip';
  }
  function morphNode(live, next) {
    if (live.nodeType !== 1) {
      if (live.nodeValue !== next.nodeValue) live.nodeValue = next.nodeValue;
      return;
    }
    carry(live, next);
    if (skipped(live, next)) return;
    syncAttrs(live, next);
    syncProps(live, next);
    morphChildren(live, next);
  }
  /* The children of `next` reconciled into `live`. The lists are snapshotted first,
     because the placing loop below moves nodes between them. */
  function morphChildren(live, next) {
    var old = Array.prototype.slice.call(live.childNodes);
    var fresh = Array.prototype.slice.call(next.childNodes);
    var byKey = {}, used = [], pick = [], cursor = 0, i, key, at;
    for (i = 0; i < old.length; i++) {
      key = keyOf(old[i]);
      if (key) byKey[key] = i;
    }
    for (i = 0; i < fresh.length; i++) {
      key = keyOf(fresh[i]);
      if (key) {
        at = byKey[key];
        if (at !== undefined && !used[at] && sameKind(old[at], fresh[i])) { pick[i] = at; used[at] = true; }
        continue;                              // a keyed child with no match is a new one
      }
      /* An unkeyed child takes the next unkeyed old node BY ORDINAL, and SPENDS that slot
         whether or not it could use it. A mismatched tag leaves the old node unused (the
         loop at the end removes it) and moves on, so the siblings after it line up with
         the siblings after it. Leaving the cursor where it was instead would hand the next
         fresh child the node this one rejected, and every sibling for the rest of the list
         would be one node out: the `panel-head` in ui.atlas.js, whose first child is a
         button on the phone and a span elsewhere, would give the spacer the title's node.
         A genuine INSERT in the middle of an unkeyed list rebuilds the tail under this
         rule, which is exactly what `data-key` is for and what every list that reorders
         already carries. */
      while (cursor < old.length && (used[cursor] || keyOf(old[cursor]))) cursor++;
      if (cursor < old.length) {
        if (sameKind(old[cursor], fresh[i])) { pick[i] = cursor; used[cursor] = true; }
        cursor++;
      }
    }
    var here = live.firstChild;
    for (i = 0; i < fresh.length; i++) {
      var node = pick[i] === undefined ? fresh[i] : old[pick[i]];
      if (pick[i] !== undefined) morphNode(node, fresh[i]);
      if (node === here) { here = here.nextSibling; continue; }
      live.insertBefore(node, here);
    }
    for (i = 0; i < old.length; i++) {
      if (!used[i] && old[i].parentNode === live) live.removeChild(old[i]);
    }
  }
  /* THE ONE ENTRY POINT. `next` is a throwaway container whose CHILDREN are morphed into
     `live`; `live` itself keeps its own id and class, which come from index.html. */
  function morph(live, next) {
    if (live && next) morphChildren(live, next);
    return live;
  }
  /* Draw `children` into the element with that id, in place. */
  function paint(id, children) {
    var live = document.getElementById(id);
    if (!live) return null;
    var next = document.createElement(live.tagName);
    add(next, children);
    morph(live, next);
    return live;
  }
  K.morph = morph; K.paint = paint;

  function now() { return App.data && App.data.now ? new Date(App.data.now).getTime() : Date.now(); }
  function ago(iso) {
    if (!iso) return '';
    var d = (now() - new Date(iso).getTime()) / 1000;
    if (d < 45) return 'just now';
    if (d < 3600) return Math.round(d / 60) + 'm';
    if (d < 86400) return Math.round(d / 3600) + 'h';
    return Math.round(d / 86400) + 'd';
  }
  function until(iso) {
    if (!iso) return '';
    var d = (new Date(iso).getTime() - now()) / 1000;
    if (d <= 0) return 'now';
    if (d < 3600) return 'in ' + Math.round(d / 60) + 'm';
    if (d < 86400) return 'in ' + Math.floor(d / 3600) + 'h' + Math.round((d % 3600) / 60) + 'm';
    return 'in ' + Math.round(d / 86400) + 'd';
  }
  function secs(n) {
    if (n === null || n === undefined) return 'never';
    if (n < 60) return n + 's ago';
    if (n < 3600) return Math.round(n / 60) + 'm ago';
    if (n < 86400) return Math.round(n / 3600) + 'h ago';
    return Math.round(n / 86400) + 'd ago';
  }
  function clock(iso) {
    if (!iso) return '';
    var d = new Date(iso), h = d.getHours(), m = d.getMinutes();
    return (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m;
  }
  function firstLine(text) { return (text || '').split('\n')[0]; }
  function isDesk() { return window.matchMedia('(min-width: 900px)').matches; }
  function store(k, v) { try { localStorage.setItem('keel.' + k, v); } catch (e) { /* private window */ } }
  function stored(k) { try { return localStorage.getItem('keel.' + k); } catch (e) { return null; } }
  /* What the reader can actually see: the visual viewport where there is one, which is the
     window minus whatever the on-screen keyboard is covering. */
  function viewHeight() {
    var v = window.visualViewport;
    return Math.round((v && v.height) || window.innerHeight || 0);
  }
  K.el = el; K.add = add; K.ago = ago; K.until = until; K.secs = secs;
  K.clock = clock; K.firstLine = firstLine; K.isDesk = isDesk; K.store = store; K.stored = stored;
  K.viewHeight = viewHeight;

  /* ---------- the keyboard takes the bottom of the screen ----------
   * The LAYOUT viewport does not shrink when the on-screen keyboard opens, so a sheet
   * pinned to it puts its foot, which is where the submit button lives, under the keys:
   * the keyboard is roughly the bottom 40% of an 844px phone. `--kbd` is how much of the
   * window the keyboard covers, read off `visualViewport` whenever it moves, and `.sheet`
   * lifts its bottom edge by exactly that. It stays 0 wherever there is no visual
   * viewport, which is every desk browser, so nothing moves there. */
  function markKeyboard() {
    var v = window.visualViewport;
    var covered = v ? Math.max(0, Math.round(window.innerHeight - v.height - v.offsetTop)) : 0;
    document.documentElement.style.setProperty('--kbd', covered + 'px');
    if (K.growDraft) K.growDraft();
    /* the sheet just got shorter under a field he is typing in, so put it back on screen */
    var node = document.activeElement;
    if (covered && node && node.getAttribute && node.getAttribute('data-fk') === 'say') {
      node.scrollIntoView({ block: 'center' });
    }
  }
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', markKeyboard);
    window.visualViewport.addEventListener('scroll', markKeyboard);
  }
  K.markKeyboard = markKeyboard;

  /* ---------- the draft he is typing, kept off the DOM ----------
   * What he types at a gate is page state, not DOM state, for the same reason `keepFlag`
   * is: anything that re-renders throws the DOM away, and losing half a typed answer under
   * him is the defect commit c71e260 exists for. One draft per CARD and GATE, so opening
   * Send back after Approve with a note finds the same half-written answer rather than a
   * second one, and it is mirrored into sessionStorage so a reload, or the app being
   * backgrounded and killed, still comes back to it. A submit that was accepted is the
   * only thing that clears it. */
  function draftKey(id, gate) { return String(id) + '·' + String(gate || ''); }
  function draft(id, gate) {
    var key = draftKey(id, gate);
    if (!(key in App.drafts)) {
      var kept = null;
      try { kept = sessionStorage.getItem('keel.draft.' + key); } catch (e) { /* private window */ }
      App.drafts[key] = kept || '';
    }
    return App.drafts[key];
  }
  function setDraft(id, gate, text) {
    var key = draftKey(id, gate);
    App.drafts[key] = String(text || '');
    try {
      if (App.drafts[key]) sessionStorage.setItem('keel.draft.' + key, App.drafts[key]);
      else sessionStorage.removeItem('keel.draft.' + key);
    } catch (e) { /* private window */ }
  }
  function clearDraft(id, gate) { setDraft(id, gate, ''); }
  K.draft = draft; K.setDraft = setDraft; K.clearDraft = clearDraft;

  /* ---------- data ---------- */
  function cards() { return App.data ? App.data.cards : []; }
  function byId(id) { return cards().filter(function (c) { return c.id === id; })[0] || null; }
  function inSpace(c) { return c.space === App.space; }
  function liveCard(c) { return !c.derived.archived; }
  /* A review card (lane RC) is listed on Reviews and nowhere else (2026-09-24): Cards never
     shows one, and a link to one opens it there. */
  function isReview(c) { return !!(c && c.options && c.options.review_key); }
  function cardRoute(c) { return isReview(c) ? 'reviews' : 'cards'; }
  function spaceInfo() { return (App.data && App.data.spaces[App.space]) || { options: [], verbs: { card: [] }, repos: [], topics: [], counts: {} }; }
  /* The branch a card of this space and repo LANDS on, by name, when its repo has a landing
     branch (`flow.landing`, keel/flows.py drawn: `{repo: branch}`, c-665); '' when it lands
     on the checkout's own branch, or the name is not known here. No branch name is spelt in
     the deck's copy: a line that names one reads it here, and says it without a name on ''. */
  function landsOn(space, repo) {
    var info = App.data && App.data.spaces && App.data.spaces[space];
    var lands = (info && info.flow && info.flow.landing) || {};
    return lands[String(Array.isArray(repo) ? repo[0] || '' : repo || '').split(',')[0].trim()] || '';
  }
  /* What a space calls a ticket and a change (c-630): its pack's [terms] over the core's
     defaults, resolved by keel/terms.py and carried on the space entry, or on the plan
     page's card (which sets K.cardTerms). There is no copy of the defaults here: a space
     with no terms reads the key itself, so a missed one shows rather than guesses. */
  var cardTerms = {};
  function termsOf(space) {
    var info = App.data && App.data.spaces && App.data.spaces[space];
    return (info && info.terms) || cardTerms[space] || null;
  }
  function term(space, key) {
    var lower = key.charAt(0).toLowerCase() + key.slice(1), t = termsOf(space) || {};
    var word = t[lower] == null ? lower : String(t[lower]);
    return lower === key ? word : word.charAt(0).toUpperCase() + word.slice(1);
  }
  /* `template` with each {key} filled from the space's terms; {Key} capitalises. */
  function sayTerms(space, template) {
    return String(template).replace(/\{([A-Za-z_]+)\}/g, function (all, key) { return term(space, key); });
  }
  function providers(route) { var p = App.data && App.data.providers[App.space]; return p && p[route] ? p[route] : null; }
  function needsYou() { return cards().filter(inSpace).filter(function (c) { return c.derived.needs_you; }); }
  function houses() { return cards().filter(inSpace).filter(function (c) { return App.data.houses.indexOf(c.id) >= 0; }); }
  function running() { return cards().filter(inSpace).filter(function (c) { return App.data.running.indexOf(c.id) >= 0; }); }
  function stageOf(c) { return c.derived.parent_stage || c.stage; }
  function gateOf(c) {
    /* A block that says "outcome not merged" is the merge refusing, not the house: the
       card is still at its outcome gate and the next Approve is the answer to it. */
    if (c.blocked_reason && !(c.derived.outcome_gate && /^outcome not merged/.test(c.blocked_reason))) return 'blocked';
    if (c.derived.plan_gate) return 'plan';
    if (c.derived.outcome_gate) return 'outcome';
    return null;
  }
  /* Why a card is in needs-you: its gate, or `notice` for a segment's open notice (Q8,
     F6). A notice is not a gate (there is nothing to approve), so `gateOf` never says it;
     every place that names what a needs-you item IS reads this instead. */
  function needKind(c) {
    return gateOf(c) || (c.derived.notice && !c.derived.archived ? 'notice' : null) || (c.derived.ask && c.derived.needs_you ? 'ask' : null) ||
      (preparedOf(c).length && c.derived.needs_you ? 'waits' : null);
  }
  /* r-55 (c-723): a shipping card's items whose fix the house prepared and that wait on
     his answer (`derived.ship_prepared`, keel/shipreplies.py), oldest first */
  function preparedOf(c) { return (c.derived && c.derived.ship_prepared) || []; }
  /* The words a needs-you item goes by, in one place: "blocked", "notice", "plan gate". */
  function needWord(c) {
    var k = needKind(c);
    if (k === 'ask') return 'Bosun asks';
    if (k === 'waits') return 'waits on you';
    return k === 'blocked' || k === 'notice' ? k : k ? k + ' gate' : '';
  }
  /* A house on the OTHER machine is not in this deck's listing, so `c.house` is null for it;
     the card pane asks that machine's door when it is opened (E3, decision N8) and the
     answer rides on the detail document, never on the board. */
  function houseOf(c) {
    /* the live strip's row when the stream said it after the document did (c-599) */
    var streamed = K.stripHouse ? K.stripHouse(c) : undefined;
    if (streamed !== undefined) return streamed;
    if (c.house) return c.house;
    var d = App.detailFor === c.id ? App.detail : null;
    return d && d.house ? d.house : null;
  }
  /* `working` is the server's one rule (keel/housejobs.py `working`, r-26): a listed
     process in a turn. A house pushed by an older machine has no flag, so status answers. */
  function houseBusy(c) {
    var h = houseOf(c);
    if (!h) return false;
    return h.working !== undefined ? !!h.working : h.status === 'busy';
  }
  function talking(c) { return c.options && c.options.discussion === true; }
  /* a plan on an html surface is the one a discussion can run on (the server refuses the rest) */
  function onSurface(c) { return /\.html?($|[?#])/i.test(String(c.plan_ref || '')); }
  K.cards = cards; K.byId = byId; K.inSpace = inSpace; K.liveCard = liveCard;
  K.isReview = isReview; K.cardRoute = cardRoute;
  K.spaceInfo = spaceInfo; K.providers = providers; K.landsOn = landsOn;
  K.term = term; K.say = sayTerms; K.cardTerms = cardTerms;
  /* c-667: a card that proposes a tier or a flow (`options.tier_proposal`,
     `options.flow_proposal`). Its outcome gate's tap is Adopt, the one Setup draws too
     (`onboarding.adopt_proposal`): it writes the draft, so the button, its confirm and its
     tip say Adopt and name what the draft is written into, on the card, on a kanban drop
     and on the outcome page. */
  function proposalOf(c) {
    var o = (c && c.options) || {};
    if (o.flow_proposal) return 'the flow of the ' + o.flow_proposal + ' space';
    if (!o.tier_proposal) return null;
    var aim = String(o.tier_proposal).split('/');
    return 'the tier (the rules) of the ' + (aim[1] ? aim[1] + ' repo in the ' : '') + aim[0] + ' space';
  }
  function adoptConfirm(c) { return 'Adopt ' + c.id + '? This writes its draft into ' + proposalOf(c) + '.'; }
  K.proposalOf = proposalOf; K.adoptConfirm = adoptConfirm;
  K.needsYou = needsYou; K.houses = houses; K.running = running; K.stageOf = stageOf;
  K.gateOf = gateOf; K.needKind = needKind; K.preparedOf = preparedOf; K.needWord = needWord; K.houseOf = houseOf; K.houseBusy = houseBusy; K.talking = talking; K.onSurface = onSurface;

  /* ---------- fetching and acting ----------
   * NOTHING RENDERS WHEN NOTHING CHANGED. Both documents carry a revision: the state's is
   * the server's own (`deckstate.Deck.rev`, bumped by every write and by a coarse clock),
   * a card's is its `updated_at` and how many events it has. The page keeps the ETag it
   * was given and sends it back, and a 304 ends the fetch before anything is drawn. The
   * morph already makes a needless render cheap and invisible; this makes it free. */
  var stateTag = null, detailTags = {};
  function conditional(tag) {
    var headers = { 'Cache-Control': 'no-store' };
    if (tag) headers['If-None-Match'] = tag;
    return { cache: 'no-store', headers: headers };
  }
  /* WHAT THIS PAGE ASKS FOR (c-540). A bare `/api/state` is the whole board, 2 MB, for the
     machine readers; a page asks for its scope instead: the deck for its live cards, the
     Bosun page (`K.stateScope = 'bosun'`, app/ui.console.js) for its own. Either way each
     brief is clipped (`brief_clipped`) and the pane reads the whole one from its detail.
     Archived cards come only while something here shows them: Include archived on Cards or
     Include dismissed on Reviews. The card the page has open rides as `card=` whenever the
     scope would not hold it (an archived card he was linked to, a personal card the Console
     opens from an ask), and the server holds it whatever the scope (review F2). */
  K.stateScope = K.stateScope || 'deck';
  function includes(page, key) {
    var st = App.find && App.find[page];
    return !!(st && st.inc && st.inc.indexOf(key) >= 0);
  }
  function wantsArchived() { return includes('cards', 'archived') || includes('reviews', 'dismissed'); }
  /* The first-run steps (c-678 review): only the Start view draws them, so only it asks. A
     finished install's state reads none of them for any other view (keel/firstrun.py). */
  function wantsSteps() { return App.view === 'start'; }
  /* the open card, when this page's scope would not hold it on its own */
  function askedCard() {
    /* not before the first state: a card it holds anyway would be a second document */
    if (!App.card || !App.data) return null;
    var open = byId(App.card);
    /* a done card is not missing until the done part has landed (c-549) */
    if (!open && !doneHeld()) return null;
    return !open || open.outside ? App.card : null;
  }
  function stateUrl() {
    var card = askedCard();
    return '/api/state?scope=' + encodeURIComponent(K.stateScope) + (wantsArchived() ? '&archived=1' : '') +
      (card ? '&card=' + encodeURIComponent(card) : '') + (wantsSteps() ? '&steps=1' : '');
  }
  /* A render that finds the page wanting archived cards its state lacks, holding ones it no
     longer shows, or missing the card it has open, asks again, once for each; a door too
     old to know scopes says `all` and is left. */
  var following = false;
  function scopeMoved(held) {
    if (!!held.archived !== wantsArchived()) return true;
    /* a state that holds the steps is kept when Start is left; one that lacks them is not */
    if (wantsSteps() && held.steps === false) return true;
    var card = askedCard();
    return !!card && held.card !== card;
  }
  function followScope() {
    var held = App.data && App.data.scope;
    if (!held || held.name === 'all' || following || !scopeMoved(held)) return;
    following = true;
    load().then(function () { following = false; });
  }
  /* The brief as the pane shows it: the whole one from the card's detail once it is here. */
  function fullBrief(c) {
    if (!c.brief_clipped) return c.brief || '';
    var d = App.detailFor === c.id ? App.detail : null;
    return d && d.card ? (d.card.brief || '') : (c.brief || '') + '…';
  }
  K.followScope = followScope; K.fullBrief = fullBrief;
  /* LIVE CARDS FIRST, DONE CARDS BEHIND THE DRAW (c-549). Done cards were 225 of the deck's
     294 and two thirds of its bytes, and no first screen needs them. So the first load asks
     for `part=live` (every card not done, plus every top-level list, the whole board's as
     ever), draws, and only then asks for `part=done` and merges it in, the live copy winning
     on an id in both. After that every refresh asks for BOTH parts at once and draws once,
     so a card moving to done is not dropped by one part landing before the other (the two
     are separate requests, so a write between them shows at the next refresh); the done
     part is tagged on its own cards, so while none of them moved it is a 304. `App.live` is the live part as
     it came; `App.data` is always the merge the views read, and `scope.done` says whether
     the done cards are in it (`K.doneHeld`). A door too old to know parts answers the
     whole scope to `part=live`, and then nothing else is asked. */
  var doneTag = null, doneCards = null;
  function askPart(part, tag) {
    return fetch(stateUrl() + '&part=' + part, conditional(tag)).then(function (r) {
      if (r.status === 304) return null;
      /* an error body is never a part: it would be an empty Done lane marked as held */
      if (!r.ok) throw new Error('the state answered ' + r.status);
      var got = r.headers.get('ETag');
      return r.json().then(function (d) { return { d: d, tag: got }; });
    });
  }
  function whole() { return !App.live || !App.live.scope || App.live.scope.part !== 'live'; }
  function merged() {
    var live = App.live;
    if (whole()) return live;
    var have = {}, d = {};
    live.cards.forEach(function (c) { have[c.id] = true; });
    Object.keys(live).forEach(function (k) { d[k] = live[k]; });
    d.cards = live.cards.concat((doneCards || []).filter(function (c) { return !have[c.id]; }));
    d.scope = Object.assign({}, live.scope, { done: doneCards !== null });
    return d;
  }
  function tookLive(got) {
    if (!got) return false;
    stateTag = got.tag;
    App.live = got.d;
    /* a whole state carries the verdict as it stands now, so it replaces a fetched one */
    App.health = null;
    return true;
  }
  function tookDone(got) {
    if (!got) return false;
    doneTag = got.tag;
    doneCards = got.d.cards || [];
    return true;
  }
  function show(detail) {
    App.data = merged();
    settleSpace();
    /* the first-run stepper's boot redirect (app/ui.start.js) reads the first state here */
    if (K.stateLanded) K.stateLanded();
    App.stripGot = Date.now();    /* when the document's live strip facts arrived (ui.live.js) */
    if (detail && App.card) loadDetail(App.card, true);
    K.render();
  }
  function failed(e) { toast('the deck cannot reach the server: ' + e.message, true); }
  /* A done part that did not come is asked for again, on a backoff, until one has: with the
     stream open nothing else would ask on a quiet board, and the views would say "Loading
     done cards" for good. Once one has landed, a refresh that fails keeps it. */
  var DONE_RETRY = [1000, 2000, 5000, 15000], doneTries = 0, doneRetrying = false;
  K.later = function (fn, ms) { setTimeout(fn, ms); };
  function retryDone() {
    if (doneCards !== null || doneRetrying) return;
    doneRetrying = true;
    K.later(function () { doneRetrying = false; loadDone(); }, DONE_RETRY[Math.min(doneTries++, DONE_RETRY.length - 1)]);
  }
  function loadDone() {
    return askPart('done', doneTag).then(function (got) { doneTries = 0; if (tookDone(got)) show(false); })
      .catch(retryDone);
  }
  /* After the next paint: a frame, then a task. A background tab runs no frames, so the
     timer is the floor under it rather than a done part that never comes. */
  K.afterDraw = function (fn) {
    var ran = false;
    function go() { if (!ran) { ran = true; fn(); } }
    requestAnimationFrame(function () { setTimeout(go, 0); });
    setTimeout(go, 250);
  };
  function load() {
    var live = askPart('live', stateTag);
    if (!App.live) {
      return live.then(function (got) {
        if (!tookLive(got)) return;
        show(true);
        /* the draw is on the screen before the done cards are even asked for */
        if (!whole()) K.afterDraw(loadDone);
      }).catch(failed);
    }
    /* a done part that fails never holds the live one back */
    var done = whole() ? Promise.resolve(null) : askPart('done', doneTag).catch(function () { retryDone(); return null; });
    return Promise.all([live, done]).then(function (both) {
      var moved = tookLive(both[0]);
      if (tookDone(both[1])) moved = true;
      if (moved) show(!!both[0]);
    }).catch(failed);
  }
  /* Are the done cards in the page's state: true for a whole document, and for a live part
     once its done part has been merged in. A view that shows done cards reads this, so it
     says it is loading them rather than drawing an empty lane or a wrong count. */
  function doneHeld() {
    var held = App.data && App.data.scope;
    return !held || held.part !== 'live' || !!held.done;
  }
  K.doneHeld = doneHeld;
  /* ---------- the health verdict, asked for on its own ----------
   * `health` (keel/health.py) rides on the state document but does NOT move its revision
   * (A-8), so a page holding a current state is answered 304 and would never see a new
   * verdict that way. Once a minute, while the tab is visible, the page asks
   * `/api/health`, which is never a 304, and the newer of the two answers is the one drawn
   * (F4). */
  var HEALTH_MS = 60000;
  function health() { return App.health || (App.data && App.data.health) || null; }
  function loadHealth() {
    if (document.visibilityState !== 'visible') return Promise.resolve(null);
    return fetch('/api/health', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.level) return;
        App.health = d;
        K.renderHeader();
        if (App.sheet && App.sheet.kind === 'health') K.renderSheet();
        if (App.view === 'now') K.renderBody();
      }).catch(function () { /* the dot keeps the last verdict it had */ });
  }
  function watchHealth() { clearInterval(App.healthTimer); App.healthTimer = setInterval(loadHealth, HEALTH_MS); }
  K.health = health; K.loadHealth = loadHealth; K.watchHealth = watchHealth;

  /* ---------- the Logins list (c-558, keel/logins.py) ----------
   * `health.logins`: one row per credential Keel depends on, each machine's own plus the
   * rows the other machine pushed, with its state, when it was last checked, and the
   * one-liner that logs it back in. The deck's health sheet and Now, and the Console, draw
   * the same block. A red row carries its one-liner with a Copy button: the command is
   * copied, never typed into anything (a red Claude row carries the guided sign-in, c-678).
   * Red first, then a login about to end, then the rest. */
  var LOGIN_RED = { expired: 1, missing: 1 };
  function loginLevel(r) {
    if (LOGIN_RED[r.state]) return 'red';
    if (r.ending || r.state === 'unknown') return 'amber';
    return 'green';
  }
  function loginRows() {
    var h = health();
    var rows = ((h && h.logins) || []).slice();
    var rank = { red: 0, amber: 1, green: 2 };
    rows.sort(function (a, b) { return rank[loginLevel(a)] - rank[loginLevel(b)]; });
    return rows;
  }
  function loginCount() {
    return loginRows().filter(function (r) { return !!LOGIN_RED[r.state]; }).length;
  }
  function copyButton(text, label) {
    label = label || 'Copy';
    var btn = el('button', { class: 'btn sm lcopy', title: 'put the command on the clipboard', onclick: function (ev) {
      ev.stopPropagation();
      var done = function () { btn.textContent = 'Copied'; setTimeout(function () { btn.textContent = label; }, 1400); };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, function () { K.toast('copy it by hand: ' + text); });
      else K.toast('copy it by hand: ' + text);
    } }, label);
    return btn;
  }
  function loginState(r) {
    if (r.state === 'good') return r.ending && r.expires ? 'ends ' + r.expires.slice(0, 10) : 'good';
    return r.state + (r.why ? ': ' + r.why : '');
  }
  /* A red Claude row's fix is the guided sign-in (c-678, app/ui.signin.js), folded under Sign
     in again: the four lines, the row's own command and the live status. Its Check again and
     its watch probe the first space that runs under the folder (`r.spaces`); a folder no
     space runs under (the talker's) has neither, since no verb of the page probes it. A
     page without that file (the Console) keeps the one-liner. */
  function loginFix(r) {
    if (!LOGIN_RED[r.state] || !r.fix) return null;
    if (r.kind !== 'claude' || !K.signIn) return el('div', { class: 'lfix' }, el('code', { class: 'fix', text: r.fix }), copyButton(r.fix));
    var space = (r.spaces || [])[0] || null;
    return K.signIn.again({ key: 'row-' + r.id, command: r.fix, space: space, check: !!space, watch: !!space, name: r.label,
      login: { state: r.state, why: r.why, stamp: r.stamp || null } });
  }
  function loginRow(r) {
    var level = loginLevel(r);
    var fix = loginFix(r);
    return el('div', { class: 'lg ' + level, 'data-key': (r.host || '') + ':' + r.id },
      el('div', { class: 'lg-head' },
        el('span', { class: 'hdot', 'aria-hidden': 'true' }),
        el('span', { class: 'lg-label', text: r.label }),
        el('span', { class: 'spacer' }),
        el('span', { class: 'age', text: r.at ? 'checked ' + ago(r.at) : 'not checked' })),
      el('div', { class: 'lg-state', text: loginState(r) + (r.stale ? ' (its machine has stopped pushing)' : '') }),
      el('div', { class: 'lg-where mono t11 ink3', text: r.where || '' }),
      fix);
  }
  function loginsBlock() {
    var rows = loginRows();
    return el('div', { class: 'logins-list', 'data-key': 'logins' }, rows.length ? rows.map(loginRow)
      : el('div', { class: 'empty', text: 'no reading yet' }));
  }
  /* The label a Logins section opens with: the word, and a count of red rows when any. */
  function loginsLabel() {
    var n = loginCount();
    return [el('span', { class: 'label', text: 'Logins' }),
      n ? el('span', { class: 'badge need', 'data-key': 'logins-badge', text: String(n) }) : null];
  }
  K.loginsBlock = loginsBlock; K.loginsLabel = loginsLabel; K.loginCount = loginCount;
  K.copyButton = copyButton;

  function loadDetail(id, quiet) {
    /* The tag is only good while the pane is still showing that card: a 304 says "what
       you hold for this id is current", which is worth nothing if what is held is another
       card's. */
    var tag = App.detailFor === id ? detailTags[id] : null;
    return fetch('/api/card/' + id, conditional(tag)).then(function (r) {
      if (r.status === 304) return null;
      detailTags[id] = r.headers.get('ETag');
      return r.json();
    }).then(function (d) {
      if (d && d.card) { App.detail = d; App.detailFor = id; if (!quiet) K.render(); else K.renderBody(); }
    }).catch(function () {});
  }

  /* ---------- the live channel: the page is TOLD what changed ----------
   * One `EventSource` on `/api/events` while the tab is visible, and one only. The server
   * names what moved (`state <rev>`, `card <id> <rev>`, `board <b-id> <cursor>`, and a
   * `ping` so a quiet channel stays warm), and the page fetches ONLY what it is holding:
   * a card event for a card nobody has open is a line read and dropped.
   *
   * The five second poll is the FALLBACK, not the channel (`ui.js`). It runs while this
   * is shut, which is a reconnect in flight or a browser without EventSource.
   *
   * The board rides on the same stream, which is what closes the gap the board's own poll
   * left: a frame pushed while a house is speaking used to appear up to five seconds
   * later. `?board=` names the one board that is open, because the server has to know
   * which file to watch for a push made in another process. */
  var stream = null, streamTimer = null, streamTries = 0, streamFor = null, opened = false;
  var STREAM_BACKOFF = [1000, 2000, 5000, 15000];

  function streamOpen() { return !!stream && stream.readyState === 1; }
  function streamPath() {
    if (App.view === 'plan' && K.planState && K.planState.id) {
      return '/api/events?plan=' + encodeURIComponent(K.planState.id);
    }
    return '/api/events' + (App.view === 'board' && App.board
      ? '?board=' + encodeURIComponent(App.board) : '');
  }
  function closeStream() {
    clearTimeout(streamTimer);
    streamTimer = null;
    if (stream) { stream.close(); stream = null; }
    streamFor = null;
  }
  function openStream() {
    if (typeof EventSource !== 'function' || document.visibilityState !== 'visible') return;
    var path = streamPath();
    if (stream && streamFor === path) return;
    closeStream();
    streamFor = path;
    try { stream = new EventSource(path); } catch (e) { stream = null; return; }
    /* A REOPEN READS THE STATE (c-729). A stream starts at what its deck holds now, which is
       what a page that has just loaded holds; a page that held a stream before may hold an
       older deck's state (a restart, a sleep), and nothing would say `state` until the
       next write, so the step's Done and Next stayed stale until a reload. */
    var reopened = opened;
    opened = true;
    stream.onopen = function () {
      streamTries = 0;
      if (reopened) load();
      reopened = true;
    };
    stream.onmessage = function (ev) { heard(String(ev.data || '')); };
    stream.onerror = function () {
      /* EventSource reconnects on its own only while it is CONNECTING; a closed one is
         ours to reopen, and the poll is covering the page until it is back. */
      if (!stream || stream.readyState !== 2) return;
      closeStream();
      var wait = STREAM_BACKOFF[Math.min(streamTries, STREAM_BACKOFF.length - 1)];
      streamTries++;
      streamTimer = setTimeout(openStream, wait);
    };
  }
  function heard(line) {
    var bits = line.split(' ');
    /* c-599: what a house is doing now, the facts themselves: patched in, nothing fetched */
    if (bits[0] === 'live') { if (K.heardLive) K.heardLive(line); return; }
    /* the plan page (a page of its own, P2-5) draws one card's document and nothing of
       the deck's state, so only its own card and its own file move it */
    if (App.view === 'plan' && bits[0] !== 'card' && bits[0] !== 'plan') return;
    if (bits[0] === 'state') { load(); return; }
    /* A TICK IS NOT A FETCH. It says fifteen seconds passed and nothing else did, so the
       ages on screen are stale by fifteen seconds and the DOCUMENT is not. The page used
       to be told `state` for this and answered it with a whole `/api/state`, four times a
       minute, on a deck nobody was touching. `render` walks what we already hold, and the
       morph writes only the few age strings that moved. */
    /* ...except on the Console (c-519): Bosun's status arrives with the Mac's push, which
       writes nothing on the board, so its one page asks for the state on each tick. */
    if (bits[0] === 'tick' && App.view === 'console') { load(); return; }
    if (bits[0] === 'tick') { K.render(); return; }
    /* the plan page follows its own card (his marks from another screen) and its file (a
       house rewriting the plan moves no board event, so the stream names the file) */
    if ((bits[0] === 'card' || bits[0] === 'plan') && App.view === 'plan' && K.planState
        && K.planState.id === bits[1]) { K.loadPlan(true); return; }
    if (bits[0] === 'card') { if (App.card === bits[1]) loadDetail(App.card, true); return; }
    if (bits[0] === 'board' && K.loadBoard) {
      var open = K.boardState && K.boardState.open;
      if (App.view === 'board' && open && open.id === bits[1]) K.loadBoard(bits[1], open.cursor);
    }
  }
  K.streamOpen = streamOpen; K.openStream = openStream; K.closeStream = closeStream;

  /* ---------- the pressed button is the indicator ----------
   * A gate action takes five to fifteen seconds on the server (the resume starts a
   * session, waits for the harness to list it, polls for the app link, stops the session
   * it superseded). The page used to say nothing at all for those seconds and nothing on
   * success either, so a tap looked like nothing happening. Three things say it now, and
   * they all live in `act`: the button that was pressed, one sentence when the answer
   * comes back, and a bridge word until the state document catches up.
   *
   * The pending set is keyed by the VERB and the CARD (an adapter verb by its route, its
   * action and the row key), never by a DOM node, so the five second poll can rebuild the
   * body mid-flight and every renderer that draws an action button repaints it still
   * pending. The key is cleared when the response arrives, success or error. */
  var PROGRESS = {
    approve: 'Approving…', sendback: 'Sending back…', end_discussion: 'Ending…',
    split: 'Splitting…', create: 'Creating…', set: 'Saving…', note: 'Saving…',
    stage: 'Moving…', block: 'Blocking…', unblock: 'Unblocking…',
    'house.resume': 'Starting…', 'house.retry': 'Starting…', 'house.stop': 'Stopping…', 'house.close_idle': 'Closing…', restart: 'Restarting…',
    'house.logs': 'Reading…', 'house.open_app': 'Waking…', ship: 'Shipping…', mark: 'Saving…',
    assign: 'Assigning…', next: 'Moving…', 'plan.send': 'Sending…', 'ship.handover': 'Handing over…',
    'ship.sendback': 'Sending back…'
  };
  function verbOf(body) {
    return body.verb === 'adapter' ? 'adapter.' + (body.route || '') + '.' + (body.action || '') : body.verb;
  }
  /* What the action acts on: a card, a provider row, or the route itself. Every button
     that shares a subject goes quiet while one of them is in flight, which is what stops a
     second tap firing an action the first tap is already running. */
  function subjectOf(body) {
    return String(body.id || body.key || (body.verb === 'adapter' ? body.route : '') || body.verb || '');
  }
  function pendKey(body) { return verbOf(body) + '\u00b7' + subjectOf(body); }
  function pendWord(body) {
    if (body.verb === 'adapter') return PROGRESS['adapter:' + body.action] || 'Working…';
    return PROGRESS[body.verb] || 'Working…';
  }
  function isPending(key) { return !!App.pending[key]; }
  function pendingOn(subject) {
    if (!subject) return false;
    return Object.keys(App.pending).some(function (k) { return App.pending[k].subject === subject; });
  }
  function anyPending() { return Object.keys(App.pending).length > 0; }
  /* The instant half: the node that was pressed says so before anything re-renders, which
     is also what covers a surface the render pass does not rebuild (an open sheet) and a
     node that is not a button at all (the tile being dragged). */
  function markPressed(node, key) {
    var p = App.pending[key];
    if (!p || !node || !node.tagName) return;
    node.classList.add('pending');
    if (node.tagName === 'BUTTON') { node.textContent = p.label; node.disabled = true; }
    if (!node.parentNode || !node.parentNode.querySelectorAll) return;
    Array.prototype.forEach.call(node.parentNode.querySelectorAll('button'), function (b) {
      if (b !== node) b.disabled = true;
    });
  }
  /* Everything the pending set is drawn into, in one call: the header's pill, the body,
     the dialog and whichever sheet is open. */
  function repaint() {
    K.renderHeader();
    K.renderBody();
    if (App.modal) K.renderModal();
    if (App.sheet) K.renderSheet();
  }
  /* THE ONE WRAPPER every action button goes through. `opts` carries the button's class,
     the confirm() it keeps, and a `done` that may open a sheet or a tab and may return the
     sentence to say (or '' when the answer is already on screen). */
  function actionBtn(label, body, opts) {
    opts = opts || {};
    var key = pendKey(body), mine = isPending(key);
    return el('button', {
      class: 'btn' + (opts.cls ? ' ' + opts.cls : '') + (mine ? ' pending' : ''),
      'data-pend': key, title: opts.title || null,
      /* a button whose label is a glyph says its name here, or it has none */
      'aria-label': opts.name || null,
      disabled: mine || pendingOn(subjectOf(body)) ? true : null,
      onclick: function (ev) {
        ev.stopPropagation();
        if (opts.confirm && !window.confirm(opts.confirm)) return;
        act(body, opts.done, ev.currentTarget);
      }
    }, mine ? App.pending[key].label : label);
  }
  /* The same face on a button that cannot hand `act` its body at draw time: the dialog's
     Create and Split validate first, and the send back reads its reason line. It wears the
     pending face of the action it is going to send, and runs its own handler. */
  function faceBtn(label, body, cls, onclick) {
    var key = pendKey(body), mine = isPending(key);
    return el('button', {
      class: 'btn' + (cls ? ' ' + cls : '') + (mine ? ' pending' : ''), 'data-pend': key,
      disabled: mine || pendingOn(subjectOf(body)) ? true : null, onclick: onclick
    }, mine ? App.pending[key].label : label);
  }

  /* ---------- one sentence from the result ----------
   * Every verb answers in its own shape (`docs/layout.md` and keel/actions.py), so the
   * page says what came back rather than "done": the gate verbs say whether the house was
   * resumed, a split names the cards it cut, an adapter verb says its own first line. A
   * caller's `done` may return a sentence of its own, or '' when the answer is already on
   * screen (a sheet, a new tab). */
  function sentence(body, r) {
    var v = body.verb;
    if (v === 'restart') return 'restarting the deck, this page reloads in a moment';
    /* c-734: a gate tap on a card Bosun builds resumes no house; Bosun is told (`r.told`) */
    if ((v === 'approve' || v === 'sendback') && r && r.told && !r.merge_conflict) return { text: r.note, err: false };
    if (v === 'approve') {
      /* the branch that moved is the refusal's own (`actions.merge_conflict`, c-665) */
      /* a card Bosun builds resumes no house (`r.bosun`, c-647) */
      if (r && r.merge_conflict) return { text: (r.target ? String(r.target).split(',').join(' and ') : 'its target branch') +
        (r.bosun ? ' moved: waiting for Bosun to merge it into its branch, approve again when it is back at review'
          : ' moved: the house is merging it into its branch, approve again when it is back at review'), err: false };
      /* c-667: a proposal's Approve is Adopt, and its answer says what happened: adopted
         into where, already adopted, or adopted but the card was not moved (an error: the
         draft is in and the card still waits at review) */
      if (body.gate !== 'plan' && r && r.where) return { text: r.note || 'adopted into ' + r.where, err: r.stage !== 'done' };
      if (body.gate !== 'plan') return body.id + ' approved';
      if (r && r.relayed) return r.note;
      if (r && !r.resumed) return { text: r.note || 'approved, but no house session was resumed', err: true };
      return 'plan approved, house resumed';
    }
    if (v === 'sendback') {
      if (r && r.relayed) return r.note;
      if (r && !r.resumed) return { text: r.note || 'sent back, but no house session was resumed', err: true };
      return body.stay ? 'sent back and staying, house resumed' : 'sent back, house resumed';
    }
    if (v === 'end_discussion') return (r && r.message) || 'the discussion is ending';
    if (v === 'ship') return (r && r.note) || 'shipped';
    /* A house on another machine: the tap became a relay its drain carries next pass. */
    if (r && r.relayed && /^house\./.test(v)) return r.note;
    if (v === 'house.resume') return body.said ? 'answer sent, house resumed' : 'house resumed';
    if (v === 'house.retry') return 'fresh house started';
    if (v === 'house.stop') return 'the session is stopped';
    /* c-607: one card's, or Close all idle's count (and how many the server refused) */
    if (v === 'house.close_idle') return { text: (r && r.note) || 'closed while idle', err: !!(r && r.refused && Object.keys(r.refused).length) };
    if (v === 'split') {
      var made = (r || []).map(function (c) { return c.id; });
      return made.length ? body.id + ' split into ' + made.join(', ') : body.id + ' split';
    }
    if (v === 'create') return ((r && r.id) || 'the card') + (body.start ? ' filed and started' : ' filed to inbox');
    if (v === 'stage') return body.id + ' moved to ' + body.stage;
    if (v === 'set') return body.id + ' updated';
    if (v === 'next') return body.clear ? body.id + ' back in filing order' : body.id + ' moved to the front';
    if (v === 'note') return 'noted on ' + body.id;
    if (v === 'unblock') return body.id + ' unblocked';
    if (v === 'adapter') return (r && r.message) || (r && r.output ? firstLine(r.output) : 'done');
    return 'done';
  }
  function say(said) {
    if (!said) return;
    if (typeof said === 'string') { toast(said); return; }
    toast(said.text, !!said.err);
  }

  /* ---------- the bridge, from the answer to the state catching up ----------
   * A gate answer, a Resume and a Retry all return as soon as the harness LISTS the new
   * session, which is before it is busy, so the state document polled next still says
   * idle and the card looks untouched. Until it catches up the card's house word says
   * what is happening instead, on the card head, the row and the Now tile. It ends on the
   * first state that shows the house busy or a session that is not the one the bridge
   * opened on, and it times out after thirty seconds so a house that never started does
   * not claim to be starting forever. The state is fetched once three seconds in rather
   * than waiting out the poll. */
  var BRIDGE_MS = 30000, BRIDGE_SETTLE_MS = 3000;
  var BRIDGE_WORDS = { approve: 'resuming the house…', sendback: 'resuming the house…',
                       'house.resume': 'resuming the house…', 'house.retry': 'starting the house…' };
  function bridgeAfter(body, result) {
    var word = BRIDGE_WORDS[body.verb];
    if (!word || !body.id) return false;
    if (body.verb === 'approve' && body.gate !== 'plan') return false;   // only the plan gate resumes
    if (result && 'resumed' in result && !result.resumed) return false;  // nothing started, so nothing to wait for
    if (result && result.relayed) return false;   // another machine starts it; the relay word says so
    App.bridge[body.id] = { word: word, at: Date.now(), session: null };
    setTimeout(function () { if (App.bridge[body.id]) load(); }, BRIDGE_SETTLE_MS);
    return true;
  }
  /* The session the bridge is waiting to see replaced, read from the state the action's
     own reload brought back rather than the stale one it was fired from. */
  function bridgeOpened(id) {
    var b = App.bridge[id], card = byId(id);
    if (b) b.session = (card && card.session_id) || '';
  }
  function bridgeWord(c) {
    var b = App.bridge[c.id];
    if (!b) return null;
    var over = Date.now() - b.at > BRIDGE_MS || houseBusy(c)
      || (b.session !== null && c.session_id && c.session_id !== b.session);
    if (over) { delete App.bridge[c.id]; return null; }
    return b.word;
  }

  /* THE PAGE'S ONE POST (c-451). Every POST that acts as him needs the cookie the deck set
     on this page's GET of the shell, which the browser sends by itself (fetch's default
     credentials are same-origin, and nothing here may pass `omit`). A deck that restarted
     since the page loaded holds a new key and refuses the old one with `renew`: the shell
     is fetched once, past every cache, which sets the new cookie, and the same POST goes
     again. Once, never a loop, and only on `renew`: any other refusal is the answer. */
  function post(url, init) {
    return fetch(url, init).then(function (r) {
      if (r.status !== 403) return r;
      return r.clone().json().then(function (d) {
        if (!d || !d.renew) return r;
        return fetch('/', { cache: 'no-store' }).then(function () { return fetch(url, init); });
      }, function () { return r; });
    });
  }
  K.post = post;

  function act(body, done, from) {
    var key = pendKey(body);
    if (isPending(key)) return Promise.resolve(null);
    App.pending[key] = { label: pendWord(body), subject: subjectOf(body), at: Date.now() };
    markPressed(from, key);
    repaint();
    /* c-601: once the server has answered ok, a failure is the PAGE's (a redraw), never
       "did not reach the server": a Create that landed said it had not. */
    var landed = null;
    return post('/api/action', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        delete App.pending[key];
        if (!d.ok) { refusals[body.verb] = { error: d.error || 'refused', detail: d.detail || null }; toast(d.error || 'refused', true); repaint(); return null; }
        delete refusals[body.verb];
        landed = d;
        /* the reload below repaints the page but not an open sheet, which is where a
           verb pressed in a sheet was pressed */
        if (App.sheet) K.renderSheet();
        var said = done ? done(d.result) : undefined;
        say(typeof said === 'string' || (said && said.text) ? said : sentence(body, d.result));
        var bridging = bridgeAfter(body, d.result);
        return load().then(function () {
          if (bridging) bridgeOpened(body.id);
          return d.result;
        });
      })
      .catch(function (e) {
        delete App.pending[key];
        if (landed) {
          toast(sentence(body, landed.result) + '; the page did not redraw (' + e.message + '), so reload to see it');
          try { repaint(); } catch (_) { /* the redraw is what failed; the toast stands */ }
          return landed.result;
        }
        toast('the action did not reach the server: ' + e.message, true);
        repaint();
        return null;
      });
  }
  /* The last refusal of a verb, in the server's words, until that verb next goes through
     (c-678): `act` answers null for a refusal and says it in a toast, which is gone in
     seconds, so a screen that must keep saying it (a pick that was not saved, a start that
     failed, a copy git refused) reads it here. `detail` is what the server sent beside
     the sentence, where a verb sends any. */
  var refusals = {};
  K.refused = function (verb) { return (refusals[verb] || {}).error || ''; };
  K.refusal = function (verb) { return refusals[verb] || null; };
  var toastTimer = null;
  /* c-605: the toast is found, or made again when something took it off the page (the
     sandbox run's script removed every `.toast`, and the next answer threw "Cannot set
     properties of null" from here, inside the answer's own promise) */
  function toastNode() {
    var t = document.getElementById('toast');
    if (t) return t;
    t = el('div', { class: 'toast', id: 'toast', role: 'status', 'aria-live': 'polite' });
    document.body.appendChild(t);
    return t;
  }
  function toast(text, isError) {
    var t = toastNode();
    t.textContent = text;
    t.className = 'toast on' + (isError ? ' err' : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.className = 'toast'; }, isError ? 8000 : 3500);
  }
  K.load = load; K.loadDetail = loadDetail; K.act = act; K.toast = toast; K.sentence = sentence;
  K.actionBtn = actionBtn; K.faceBtn = faceBtn; K.isPending = isPending; K.pendKey = pendKey;
  K.pendingOn = pendingOn; K.anyPending = anyPending; K.bridgeWord = bridgeWord;

  /* ---------- the page's own scroll, ACROSS A NAVIGATION ONLY ----------
   * The morph covers everything a re-render used to eat: the page's scroll, every inner
   * scroller's, the caret. It cannot cover the two cases where the DOM is genuinely gone
   * or genuinely different: a real reload, and a Back or Forward into a route whose body
   * the morph has just replaced. So one number per route survives in sessionStorage, and
   * it is READ BACK ONLY WHEN THE ROUTE KEY CHANGES. A poll never touches it, which is
   * what the five second jump back to the top used to be.
   * The per-scroller half of this (one offset per inner scroller, applied after every
   * pass) is gone: an inner scroller is the same node from one pass to the next now. */
  var lastKey = null, saveTimer = null;

  /* A selected provider row is as much a route as a selected card, so it gets its own
     entry under the same key. */
  function scrollKey() { return 'keel.scroll.' + App.view + '|' + (App.card || App.row || '') + '|' + App.space; }
  function readScroll(key) {
    try { return parseInt(sessionStorage.getItem(key) || '0', 10) || 0; } catch (e) { return 0; }
  }
  function writeScroll(key, top) {
    try { sessionStorage.setItem(key, String(top)); } catch (e) { /* private window */ }
  }
  function rememberScroll() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      var body = document.getElementById('body');
      if (lastKey && body) writeScroll(lastKey, body.scrollTop);
    }, 120);
  }
  /* scroll does not bubble, so the listener captures. */
  document.addEventListener('scroll', rememberScroll, true);
  /* Called once per pass: it moves the page only on the pass that ENTERS a route. */
  function enterRoute() {
    if (K.leave) K.leave.note();
    var key = scrollKey();
    if (key === lastKey) return false;
    lastKey = key;
    var body = document.getElementById('body');
    if (body) body.scrollTop = readScroll(key);
    return true;
  }
  K.scrollKey = scrollKey; K.readScroll = readScroll; K.writeScroll = writeScroll;
  K.enterRoute = enterRoute;
  K.scrollState = function () { return lastKey; };

  /* ---------- routing ----------
   * Every route is `?view=<name>` but ONE. The Board is `/board` and `/board/<b-id>`,
   * because a board is the one thing on the deck he sends himself a link to. `?view=` on
   * that path means something else there: WHICH OF THE THREE VIEWS of that one board
   * (diagram, outline, walk), which is a way of looking rather than another thing to open.
   * `keel/serve.py` answers both shapes with the page, so this is the only place that has
   * to know. A `/board/<b-id>/<n>` from the frames era still opens its board: the number
   * is matched and dropped.
   *
   * Everything else therefore writes an ABSOLUTE `/?view=...`: a relative `?view=cards`
   * from `/board/b-004` would leave the board's path in front of it. */
  var BOARD_PATH = /^\/board(?:\/(b-\d+)(?:\/(\d+))?)?\/?$/;
  function boardPath() {
    var m = BOARD_PATH.exec(location.pathname);
    return m ? { id: m[1] || null } : null;
  }
  K.boardPath = boardPath;

  /* The view the address names, as written; `K.routeView` is the one it opens, read without
     touching the route (app/ui.leave.js asks it about a Back before the route is read). */
  function namedView() {
    return boardPath() ? 'board' : (new URLSearchParams(location.search).get('view') || stored('view') || 'now');
  }
  K.routeView = function () { var view = namedView(); return view === RETIRED_PRS ? 'cards' : view; };

  function readRoute() {
    var q = new URLSearchParams(location.search);
    var onBoard = boardPath();
    App.board = onBoard ? onBoard.id : null;
    App.boardView = onBoard && onBoard.id ? q.get('view') : null;
    App.view = namedView();
    var retired = App.view === RETIRED_PRS;
    if (retired) App.view = 'cards';
    /* the space asked for or last used; checked against the config's spaces once the state
       arrives (`settleSpace`, c-629), since a fresh install may not have the one stored */
    App.space = q.get('space') || stored('space') || '';
    App.density = q.get('d') || 'work';
    App.card = q.get('card') || null;
    App.row = q.get('key') || null;
    App.step = q.get('step') || null;
    if (['glance', 'work', 'deep'].indexOf(App.density) < 0) App.density = 'work';
    /* the page's find state comes off the URL when the URL carries it (app/ui.find.js) */
    if (K.find) K.find.fromRoute(App.view);
    if (retired) landOnShipping(q);
    applyChrome();
  }
  /* An old PRs link: Cards with the Shipping view, said in the URL and remembered, so Back
     and a reload both show what the link now means. */
  function landOnShipping(q) {
    if (K.find) K.find.preset('cards', SHIPPING_VIEW);
    store('view', 'cards');
    q.set('view', 'cards');
    if (K.find) K.find.params('cards').forEach(function (pair) { q.set(pair[0], pair[1]); });
    history.replaceState(null, '', location.pathname + '?' + q.toString());
  }
  /* The two palettes the deck has: a space named work wears work's, every other its own
     calmer one (c-629: the spaces are the config's, not a fixed pair). */
  function palette(space) { return space === 'work' ? 'work' : 'personal'; }
  function applyChrome() {
    document.documentElement.setAttribute('data-mode', palette(App.space));
    document.documentElement.setAttribute('data-density', App.density);
    var tc = document.querySelector('meta[name="theme-color"]');
    if (tc) tc.setAttribute('content', palette(App.space) === 'work' ? '#101418' : '#161412');
  }
  /* The spaces the config has, in its order. */
  function spaceNames() { return App.data && App.data.spaces ? Object.keys(App.data.spaces) : []; }
  /* A space the config does not have (a stored one, or none yet) becomes its first. */
  function settleSpace() {
    var names = spaceNames();
    if (!names.length || names.indexOf(App.space) >= 0) return;
    App.space = names[0]; store('space', App.space); applyChrome();
  }
  function spaceLabel(space) { return space ? space.charAt(0).toUpperCase() + space.slice(1) : ''; }
  function nextSpace() {
    var names = spaceNames();
    return names[(names.indexOf(App.space) + 1) % names.length];
  }
  function go(view, card, replace) {
    /* a view with something unsaved may refuse the move (c-661, app/ui.leave.js) */
    if (K.leave && !K.leave.may(App.view, view)) return;
    if (lastKey) writeScroll(lastKey, document.getElementById('body').scrollTop);
    /* whatever was open in the find bar belongs to the route being left */
    if (K.find && view !== App.view) K.find.leave();
    App.view = view;
    App.card = card || null;
    App.row = null;
    App.board = null;
    App.boardView = null;
    /* a gate's field belongs to the card he left, so it closes with the route; the draft
       in it does not, and is still there when he opens that gate again */
    if (App.sheet && (App.sheet.kind === 'say' || App.sheet.kind === 'actions')) { App.sheet = null; K.renderSheet(); }
    if (!card) { App.detail = null; App.detailFor = null; }
    store('view', view);
    var q = new URLSearchParams();
    q.set('view', view);
    if (App.card) q.set('card', App.card);
    /* a stepper screen is a route of its own, and the space it is shown for rides with it */
    if (view === 'start' && App.step) { q.set('step', App.step); if (App.space) q.set('space', App.space); }
    /* a page with a find bar carries its state in the URL, so a link says what it shows
       and Back walks it (app/ui.find.js) */
    var found = new URLSearchParams();
    (K.find ? K.find.params(view) : []).forEach(function (pair) { q.set(pair[0], pair[1]); found.set(pair[0], pair[1]); });
    /* absolute, so a move off `/board/<id>` does not keep the board's path in front; the
       board route is its path, so only the find state rides in its query */
    var url = view === 'board' ? '/board' + (found.toString() ? '?' + found.toString() : '') : '/?' + q.toString();
    if (replace) history.replaceState(null, '', url); else history.pushState(null, '', url);
    if (App.card) loadDetail(App.card);
    /* the stream names the board it is watching, so leaving one re-opens it */
    openStream();
    K.render();
  }
  /* Selecting pushes, so Back is the way out of a card and lands on the list again. */
  function select(id) { App.pushedDetail = true; go(App.view, id, false); }
  /* A provider row is selected exactly the way a card is, by a key in the URL: the pane
     opens beside the list on the desk and as a route on the phone, and the ✕, Escape, a
     click on the page behind and Back all close it again. */
  function selectRow(key) {
    if (lastKey) writeScroll(lastKey, document.getElementById('body').scrollTop);
    App.pushedDetail = true;
    App.row = key;
    /* the rest of the query survives, so a pinned palette, density or layout is still
       pinned once a row is open */
    var q = new URLSearchParams(location.search);
    q.set('view', App.view);
    q.set('key', key);
    q.delete('card');
    history.pushState(null, '', '/?' + q.toString());
    K.render();
  }
  function closeDetail() {
    if (!App.card && !App.row) return;
    if (App.pushedDetail) { App.pushedDetail = false; history.back(); return; }
    go(App.view, null, false);
  }
  function setSpace(space) {
    App.space = space; store('space', space); applyChrome();
    if (App.modal && App.modal.mode === 'create') K.closeModal();
    if (App.card && byId(App.card) && byId(App.card).space !== space) App.card = null;
    /* a provider row belongs to the space it was listed in, so the pane closes with it */
    App.row = null;
    K.render();
  }
  window.addEventListener('popstate', function () {
    /* the Console is a page of its own (c-519): the deck's route would make it a deck view
       and paint it in a space's palette, so its history is its own (ui.console.js) */
    if (App.view === 'console') return;
    /* asked before anything moves: a refused Back or Forward, and the walk back onto the
       entry he was on, are not the deck's to draw (app/ui.leave.js) */
    if (K.leave && K.leave.popped(App.view)) return;
    App.pushedDetail = false;
    readRoute();
    if (App.card) loadDetail(App.card, true);
    openStream();
    K.render();
  });
  K.readRoute = readRoute; K.go = go; K.select = select; K.selectRow = selectRow; K.closeDetail = closeDetail;
  K.setSpace = setSpace; K.palette = palette; K.spaceNames = spaceNames;

  /* Escape closes what is open, innermost first. */
  document.addEventListener('keydown', function (ev) {
    if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'k') { ev.preventDefault(); if (K.openModal) K.openModal(); return; }
    if (ev.key !== 'Escape') return;
    if (App.menu) { closeMenu(true); return; }
    if (App.modal) { K.closeModal(); return; }
    if (App.sheet) { App.sheet = null; K.renderSheet(); return; }
    if (App.card || App.row) closeDetail();
  });

  /* ---------- a split button and its menu (V2-1) ----------
   * A card can offer about twenty actions, and one flat row of them was hard to search. So
   * the card's actions come in groups (the table is `GROUPS` in ui.tips.js), and a
   * group with more than one live action is a SPLIT BUTTON: its most likely action for the
   * card's state as the button, and a caret that opens the rest. This is only the widget;
   * which action leads and what each one says are the table's.
   *
   * It is a real menu: the caret is a button with `aria-haspopup="menu"` and
   * `aria-expanded`, the menu has `role="menu"` and its entries `role="menuitem"`, the
   * arrow keys, Home and End move between them, Escape closes it and puts focus back on the
   * caret, Tab and a click anywhere else close it. Which menu is open is page state
   * (`App.menu`), so a redraw draws it open again and the morph keeps the focused entry.
   * EVERY ENTRY SAYS WHAT IT DOES under its name (lane U's line), because the phone has no
   * hover; on the phone the caret opens the same entries as a sheet, since a menu inside a
   * strip that scrolls sideways is clipped by it. */
  function menuIsOpen(id) { return !!(App.menu && App.menu.id === id); }
  function menuEntries(node) {
    return node ? Array.prototype.slice.call(node.querySelectorAll('[role="menuitem"]')) : [];
  }
  function focusEntry(id, last) {
    var entries = menuEntries(document.querySelector('[data-menu="' + id + '"]'));
    var entry = last ? entries[entries.length - 1] : entries[0];
    if (entry) entry.focus();
  }
  function openMenu(id, last) {
    App.menu = { id: id, shift: 0 };
    K.renderBody();
    fitMenu(id);
    focusEntry(id, last);
  }
  /* The menu drops from the group's left edge and is slid left just far enough to stay
     inside the box that clips it (the card pane scrolls, so it clips), and never past that
     box's left edge. Measured once, when it opens, and kept in `App.menu` so a redraw puts
     it in the same place; a guess from the group's place in the row cannot, since the row
     wraps. */
  function clipBox(node) {
    for (var p = node.parentElement; p && p !== document.body; p = p.parentElement) {
      if (/(auto|scroll|hidden)/.test(getComputedStyle(p).overflowX)) return p.getBoundingClientRect();
    }
    return { left: 0, right: window.innerWidth };
  }
  var MENU_MARGIN = 4;
  function fitMenu(id) {
    var menu = document.querySelector('[data-menu="' + id + '"]');
    if (!menu || !menu.getBoundingClientRect) return;
    var box = menu.getBoundingClientRect(), clip = clipBox(menu), shift = 0;
    if (box.right > clip.right - MENU_MARGIN) shift = clip.right - MENU_MARGIN - box.right;
    if (box.left + shift < clip.left + MENU_MARGIN) shift = clip.left + MENU_MARGIN - box.left;
    if (!shift) return;
    App.menu.shift = Math.round(shift);
    K.renderBody();
  }
  function closeMenu(refocus) {
    var id = App.menu && App.menu.id;
    if (!id) return;
    App.menu = null;
    K.renderBody();
    var caret = refocus ? document.querySelector('[data-caret="' + id + '"]') : null;
    if (caret) caret.focus();
  }
  var MENU_MOVES = { ArrowDown: 1, ArrowUp: -1 };
  function menuKeys(ev) {
    var entries = menuEntries(ev.currentTarget), n = entries.length;
    var at = entries.indexOf(document.activeElement), to = null;
    if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); closeMenu(true); return; }
    if (ev.key === 'Tab') { closeMenu(false); return; }
    if (MENU_MOVES[ev.key]) to = (at + MENU_MOVES[ev.key] + n) % n;
    else if (ev.key === 'Home') to = 0;
    else if (ev.key === 'End') to = n - 1;
    if (to === null || !n) return;
    ev.preventDefault();
    entries[to].focus();
  }
  function caretKeys(id) {
    return function (ev) {
      if (ev.key !== 'ArrowDown' && ev.key !== 'ArrowUp') return;
      ev.preventDefault();
      openMenu(id, ev.key === 'ArrowUp');
    };
  }
  /* An entry closes the menu before it acts, and hands focus back to the caret, so a verb's
     answer lands on the pane and a sheet or the dialog it opens is not drawn under it. */
  function closingMenu(node, fn) {
    var wrapped = function (ev) { closeMenu(true); return fn ? fn.call(this, ev) : undefined; };
    node.onclick = wrapped;
    (node._on || (node._on = {})).onclick = wrapped;
    return node;
  }
  /* An action button as an entry: its name, and under it the line that says what it does.
     The name alone is its accessible name; the line describes it. */
  function menuEntry(node, line, id, role) {
    var key = node.getAttribute('data-key') || 'x', base = id + '-' + key;
    var name = el('span', { class: 'mname', id: base + '-n' });
    Array.prototype.slice.call(node.childNodes).forEach(function (child) { name.appendChild(child); });
    add(node, [name, line ? el('span', { class: 'mdesc', id: base + '-d', text: line }) : null]);
    /* the gate's primary is a group's button, never an entry; an entry is never the accent */
    node.className = node.className.replace(/\bprimary\b/, '').replace(/\s+/g, ' ').trim() + ' mitem';
    node.setAttribute('aria-labelledby', base + '-n');
    if (line) node.setAttribute('aria-describedby', base + '-d');
    if (role) { node.setAttribute('role', role); node.setAttribute('tabindex', '-1'); }
    return node;
  }
  /* o: {id, key, name, main, rest: [nodes], line(node) -> text, sheet(): a phone's menu sheet} */
  function splitButton(o) {
    var open = menuIsOpen(o.id), primary = /\bprimary\b/.test(o.main.className);
    var names = o.rest.map(function (n) { return n.textContent; }).join(', ');
    var caret = el('button', { class: 'btn caret' + (primary ? ' primary' : ''), 'data-key': 'caret',
      'data-caret': o.id, 'aria-haspopup': 'menu', 'aria-expanded': open ? 'true' : 'false',
      'aria-controls': open ? o.id : null, 'aria-label': 'More in ' + o.name, title: o.name + ': ' + names,
      onclick: function (ev) {
        ev.stopPropagation();
        if (!isDesk() && o.sheet) { o.sheet(); return; }
        if (open) closeMenu(true); else openMenu(o.id, false);
      },
      onkeydown: caretKeys(o.id) }, o.named ? el('span', { class: 'cname', text: o.name }) : null, '▾');
    o.main.className += ' amain';
    var menu = open ? el('div', { class: 'amenu', id: o.id,
      style: App.menu.shift ? 'left:' + App.menu.shift + 'px' : null, 'data-menu': o.id,
      'data-key': 'menu', role: 'menu', 'aria-label': o.name, onkeydown: menuKeys },
      el('div', { class: 'mhead', role: 'presentation', text: o.name }),
      o.rest.map(function (n) { return closingMenu(menuEntry(n, o.line(n), o.id, 'menuitem'), n.onclick); })) : null;
    return el('div', { class: 'agroup' + (open ? ' open' : ''), 'data-key': 'g-' + o.key,
      'data-menu-host': o.id, role: 'group', 'aria-label': o.name }, o.main, caret, menu);
  }
  /* A click anywhere outside the open menu's own group closes it. */
  document.addEventListener('click', function (ev) {
    if (!App.menu) return;
    var t = ev.target;
    if (t && t.closest && t.closest('[data-menu-host="' + App.menu.id + '"]')) return;
    closeMenu(false);
  });
  K.splitButton = splitButton; K.menuEntry = menuEntry; K.openMenu = openMenu;
  K.closeMenu = closeMenu; K.menuKeys = menuKeys; K.caretKeys = caretKeys; K.closingMenu = closingMenu;

  /* ---------- rail, header, controls, dock ---------- */
  function viewOf(key) { return ROWS.filter(function (v) { return v.key === key; })[0] || null; }
  /* Every view, always (c-631): a view whose needs are unmet explains itself on its page.
     The stepper leaves the rail once Finish is pressed (c-632), and stays under More. */
  function finished() { var f = App.data && App.data.firstrun; return !f || !f.install || !!f.finished; }
  /* c-730: whether some space can use every capability in `caps` at all: a readiness row
     that says `declared` false (no pack, a pack without it, review scanning turned off) does
     not count; one held up only by a failing check does. No readiness (an older server) is yes. */
  function declaredSomewhere(caps) {
    var spaces = App.data && App.data.readiness && App.data.readiness.spaces;
    if (!spaces) return true;
    return Object.keys(spaces).some(function (name) {
      return [].concat(caps || []).every(function (cap) { var row = spaces[name][cap]; return !row || row.declared !== false; });
    });
  }
  /* a `when-declared` view (Reviews) is listed only while some space can fill it, or while
     it is the page open */
  function listed(v) { return v.rail !== 'when-declared' || declaredSomewhere(v.needs) || App.view === v.key; }
  function visibleViews() {
    return VIEWS.filter(function (v) { return (v.rail !== 'until-finished' || !finished() || App.view === v.key) && listed(v); });
  }
  /* The phone dock: `K.DOCK`, less a `when-ready` view whose needs are not met yet. */
  function dockKeys() {
    return DOCK.filter(function (key) {
      var v = viewOf(key);
      return !v || ((v.dock !== 'when-ready' || !unmet(v.needs || [], App.space).length) && listed(v));
    });
  }
  function counts() {
    var need = needsYou().length;
    /* lane RC: Reviews counts the review cards waiting on him, not the old scanner's rows */
    return { attention: need, reviews: K.reviewCount ? K.reviewCount() : 0 };
  }
  function drainLine() {
    /* one machine never names itself (c-634, c-622) */
    var d = App.data.drain;
    return !d.at ? 'drain: no log yet' : 'drain: polled ' + secs(d.age_seconds);
  }
  /* ---------- what a page needs (c-631) ----------
   * One component for every page that depends on something being set up. It reads S1's
   * readiness rows (`readiness` on `/api/state`, keel/readiness.py): `{ready, why, step}`
   * per space for repos, tracker, codehost and reviews, and for the install for
   * prerequisites, voice, builder and segments. A state with no `readiness` (an older deck
   * server) reads as ready, so nothing flashes. The sentences are the rows' own, which the
   * backend refuses a verb with (`readiness.refusal`), so the deck and `kb` agree. */
  function readyRow(cap, space) {
    var r = App.data && App.data.readiness;
    if (!r) return null;
    var mine = (r.spaces || {})[space === undefined ? App.space : space] || {};
    return mine[cap] || (r.install || {})[cap] || null;
  }
  /* The unmet rows of `caps` (a name or a list), each as {cap, row}. */
  function unmet(caps, space) {
    return [].concat(caps || []).map(function (cap) { return { cap: cap, row: readyRow(cap, space) }; })
      .filter(function (u) { return u.row && !u.row.ready; });
  }
  /* What each capability unlocks, said once under the missing ones. Through `K.say`, so a
     space's own words read here (c-630). */
  var UNLOCKS = {
    repos: 'A repo lets a card build code in a worktree of its own.',
    tracker: "A tracker lets a card carry its {ticket} and open it from here.",
    codehost: 'A code host lets Approve open a {change} and Ship send it.',
    reviews: 'Review scanning lists the {changes} that need your review here.',
    segments: 'A segment adds its summary tiles here, and its tab to the phone dock.',
    prerequisites: 'Houses run once everything Shipyard needs is installed.',
    voice: 'Voice lets you talk to a house from the phone.',
    builder: 'The builder lets Bosun build changes to this install.'
  };
  /* The one function that turns a first-run step id into a URL: that step's screen in the
     stepper (c-632), for `space`. The link's tap goes through `K.openStep` (app/ui.start.js),
     so the page moves without a reload; the href is for a new tab. Nothing else builds it. */
  function stepHref(step, space) {
    return '?view=start&step=' + encodeURIComponent(step) + (space ? '&space=' + encodeURIComponent(space) : '');
  }
  function stepTap(step, space) {
    return function (ev) {
      if (!K.openStep || (ev && (ev.metaKey || ev.ctrlKey))) return;
      if (ev && ev.preventDefault) ev.preventDefault();
      K.openStep(step, space);
    };
  }
  function asSentence(text) {
    var t = String(text || '').trim();
    if (!t) return '';
    return t.charAt(0).toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? '' : '.');
  }
  function setUpLink(step, space) {
    return step ? el('a', { class: 'btn needs-go', href: stepHref(step, space), 'data-key': 'needs-go',
      onclick: stepTap(step, space) }, 'Set it up') : null;
  }
  /* A row no first-run step sets up, where Bosun is the way (c-729, the owner's call: no
     voice step): the sentence, Bosun's page, and its session's command with Copy, as the
     first run's "Stuck? Open Bosun's session" line gives it. Its session is offered only
     where it can run (`K.bosunSession`, app/ui.stuck.js), or as the state names it where
     that file is not loaded. */
  var ASK_BOSUN = { voice: 'Ask Bosun how to set up voice on this computer.' };
  function askBosun(cap) {
    var d = App.data || {}, entry = d.console || d.bosun;
    var session = K.bosunSession ? K.bosunSession() : (entry && entry.attach ? { attach: entry.attach } : null);
    return el('div', { class: 'needs-ask', 'data-key': 'needs-ask' },
      el('div', { text: ASK_BOSUN[cap] + (session ? ' Open its page, or its session in a terminal:' : ' Open its page:') }),
      el('a', { class: 'btn needs-go', href: '/console', 'data-key': 'needs-bosun' }, 'Open Bosun'),
      session ? el('div', { class: 'lfix' }, el('code', { class: 'fix', text: session.attach }), copyButton(session.attach)) : null);
  }
  /* The panel for `caps` on `space`, or null when all of them are ready. `opts.line` draws
     the one-line form a form field or a card pane carries. `opts.title` heads the panel. */
  function needs(caps, space, opts) {
    opts = opts || {};
    space = space === undefined || space === null ? App.space : space;
    var missing = unmet(caps, space);
    if (!missing.length) return null;
    var whys = [], step = null, ask = null;
    missing.forEach(function (u) {
      var said = asSentence(u.row.why);
      if (whys.indexOf(said) < 0) whys.push(said);
      if (!step && u.row.step) step = u.row.step;
      if (!ask && !u.row.step && ASK_BOSUN[u.cap]) ask = u.cap;
    });
    var key = 'needs-' + missing.map(function (u) { return u.cap; }).join('-');
    if (opts.line) {
      return el('div', { class: 'needs-line', role: 'status', 'data-key': key },
        el('span', { text: whys.join(' ') }), step ? ' ' : null,
        step ? el('a', { href: stepHref(step, space), text: 'Set it up', onclick: stepTap(step, space) }) : null);
    }
    return el('div', { class: 'waiting needs', role: 'status', 'data-key': key },
      el('div', { class: 'needs-head', text: opts.title || 'Not set up yet' }),
      whys.map(function (w) { return el('div', { class: 'needs-why', 'data-key': w, text: w }); }),
      missing.map(function (u) {
        return UNLOCKS[u.cap] ? el('div', { class: 'needs-unlocks', 'data-key': 'unlocks-' + u.cap, text: sayTerms(space, UNLOCKS[u.cap]) }) : null;
      }),
      step ? setUpLink(step, space) : ask ? askBosun(ask) : null);
  }
  K.readyRow = readyRow; K.unmet = unmet; K.needs = needs; K.stepHref = stepHref; K.UNLOCKS = UNLOCKS;

  /* The header's own indicator: while anything is in flight the pill breathes, so on the
     phone, where the sheet that carried the button may have closed, something visible is
     still moving. */
  /* The pill's DOT is Keel's health verdict (F4, review round 1): green, amber or red, from
     `health` (keel/health.py), which already counts a drain with no pass as its own reason,
     so the dot and the word cannot contradict each other. The pill keeps its drain word, and
     a tap on it opens the services sheet with the reasons. One control, not a second dot in
     a box beside it: two red dots said one thing twice and squeezed the space name to
     "Pers...". Without a verdict yet, the dot says the drain's liveness as it always did. */
  /* On the PHONE the pill is its dot alone, in a 44px box (c-519, his pick): Bosun's entry
     made the header's fourth icon, and the dot already carries the verdict. The word is
     still in its accessible name, and the tap still opens the sheet with the reasons. */
  function drainPill() {
    var d = App.data.drain, busy = anyPending(), h = health(), desk = isDesk();
    var word = desk ? drainLine() : (d.alive ? 'drain up' : 'drain ' + secs(d.age_seconds));
    var said = h ? 'Shipyard is ' + h.level + (h.reasons && h.reasons.length ? ': ' + h.reasons.join('; ') : '') + '. ' + word
      : word;
    return el('button', { class: 'pill' + (desk ? '' : ' dotonly') + (h ? ' h-' + h.level : d.alive ? '' : ' stale') + (busy ? ' busy' : ''),
      title: busy ? 'an action is in flight' : said, 'aria-label': said,
      onclick: function () { App.sheet = { kind: 'health' }; K.renderSheet(); } },
      el('span', { class: 'dot', 'aria-hidden': 'true' }), desk ? el('span', { class: 'pill-word', text: word }) : null);
  }
  /* Bosun's word for its session: what the harness says (working, idle), or why it says
     nothing (stopped, never started; away when this config has no session at all). */
  /* 'voice' while Harbor's voice holds Bosun's session (c-523): the board says so. */
  function bosunWord(b) {
    if (b && b.voice) return 'voice';
    return b ? (b.state || 'away') : 'away';
  }
  /* Bosun's entry, left of the drain pill (c-519, the canvas's "Deck header"): on the desk a
     pill with its mark, its name, the session's dot, the red count (asks that need him) and
     the grey one (open requests); on the phone a 44px icon with the red count. The counts
     are the open asks (c-521) and the open requests (c-520). A link, not a verb: the
     Console is a page of its own. */
  function bosunEntry() {
    var b = App.data && App.data.console;
    if (!b) return null;
    var word = bosunWord(b), counts = b.counts || {};
    var asks = counts.asks || 0, requests = counts.requests || 0;
    var said = 'Bosun, ' + (word === 'voice' ? 'on voice' : word) + (asks ? ', ' + asks + ' need you' : '') + (requests ? ', ' + requests + ' open requests' : '');
    if (isDesk()) {
      return el('a', { class: 'pill bosun', href: '/console', title: said, 'aria-label': said },
        el('span', { class: 'bmark', 'aria-hidden': 'true' }),
        el('span', { class: 'bname', 'aria-hidden': 'true', text: 'Bosun' }),
        el('span', { class: 'dot b-' + word, 'aria-hidden': 'true' }),
        asks ? el('span', { class: 'bcount need', 'aria-hidden': 'true', text: String(asks) }) : null,
        requests ? el('span', { class: 'bcount', 'aria-hidden': 'true', text: String(requests) }) : null);
    }
    return el('a', { class: 'iconbtn bosunbtn', href: '/console', title: said, 'aria-label': said },
      el('span', { class: 'bmark', 'aria-hidden': 'true' }),
      asks ? el('span', { class: 'bbadge', 'aria-hidden': 'true', text: String(asks) }) : null);
  }
  /* The checkout moved past the commit this serve loaded (a merge landed): the running
     code is stale, and only a restart fixes that. The verb execs serve in place; the page
     reloads itself once the new process answers.

     On the PHONE it is the fourth icon in the header, not a twenty character pill: worded, it
     is 166px in a 390px row that already carries the drain pill and three 44px icons, and the
     header's title and view name were squeezed to nothing and painted past the edge. Same
     verb, same wait, same sentence; one control per job, chosen by breakpoint, which is the
     rule the ⇄ and + icons already follow. */
  function codePill() {
    var cfg = App.data.config || {};
    if (!cfg.code_moved) return null;
    var why = 'the code is at ' + String(cfg.code_head || '').slice(0, 7) + ', this deck loaded ' + String(cfg.serve_head || '').slice(0, 7);
    var reload = function () { setTimeout(function () { location.reload(); }, 2500); };
    if (isDesk()) {
      return actionBtn('code moved · restart', { verb: 'restart' },
        { cls: 'pill moved', title: why, done: reload });
    }
    return actionBtn('↻', { verb: 'restart' },
      { cls: 'iconbtn moved', name: 'code moved, restart the deck',
        title: 'code moved, restart the deck: ' + why, done: reload });
  }
  function renderRail() {
    var c = counts();
    paint('rail', [
      el('div', { class: 'rail-brand' }, el('span', { class: 'mark' }), el('span', { text: 'Shipyard' })),
      el('div', { class: 'rail-nav' }, visibleViews().map(function (v) {
        var n = c[v.key];
        return el('button', { class: 'rail-item' + (App.view === v.key ? ' on' : ''), onclick: function () { go(v.key); } },
          el('span', { class: 'name', text: v.name }),
          n ? el('span', { class: 'badge' + (v.key === 'attention' ? ' need' : ''), text: String(n) }) : null);
      })),
      el('div', { class: 'rail-foot', text: drainLine() })
    ]);
  }
  /* The way into the voice app from the deck, on the desk and the phone (c-518): its bare
     mark in the button's ink (ui.css), and a plain link, so the app opens in this window and
     its back link returns. */
  /* Voice's own address when it has one (`[voice] app_url`, the `harbor` name), so the
     installed Voice app is what opens; else the path under the deck. */
  function voiceHref() { return ((App.data && App.data.config) || {}).voice_url || '/segments/voice/app/'; }
  K.voiceHref = voiceHref;
  /* c-601: voice runs on this machine. The services block says `off` ("not installed here")
     when it does not; an unread block (no health yet) is not taken as an absence. */
  function voiceHere() {
    var rows = ((App.data && App.data.health) || {}).services || [];
    var voice = rows.filter(function (r) { return r.name === 'voice'; })[0];
    return !voice || voice.level !== 'off';
  }
  K.voiceHere = voiceHere;
  /* c-604: absent where voice is not installed here, where the link opened nothing */
  function voiceButton() {
    if (!voiceHere()) return null;
    return el('a', { class: 'iconbtn voicebtn', href: voiceHref(), title: 'Voice', 'aria-label': 'open Voice' },
      el('span', { class: 'glyph', 'aria-hidden': 'true' }));
  }
  function renderHeader() {
    var v = viewOf(App.view);
    paint('header', [
      el('span', { class: 'mark' }),
      el('h1', { text: spaceLabel(App.space) }),
      el('span', { class: 'hint', text: (K.headerHint && K.headerHint(App.view)) || (v ? v.name : (App.view === 'plan' ? 'Plan' : '')) }),
      el('span', { class: 'spacer' }),
      bosunEntry(),
      drainPill(),
      codePill(),
      voiceButton(),
      /* phone only: the desk has New card and the worded switch in the controls row */
      spaceNames().length > 1 ? el('button', { class: 'iconbtn phone-only', title: 'switch space', 'aria-label': 'switch space', onclick: function () { setSpace(nextSpace()); } }, '⇄') : null,
      el('button', { class: 'iconbtn phone-only', title: 'new card', 'aria-label': 'new card', onclick: function () { K.openModal(); } }, '+')
    ]);
  }
  function renderControls() {
    paint('controls', [
      spaceNames().length < 2 ? null : el('div', { class: 'switch' }, spaceNames().map(function (s) {
        return el('button', { class: App.space === s ? 'on' : '', onclick: function () { setSpace(s); } }, el('span', { class: 'dot' }), s);
      })),
      el('span', { class: 'spacer' }),
      el('button', { class: 'btn primary', onclick: function () { K.openModal(); } }, 'New card',
        el('span', { class: 'key', text: '⌘K' }))
    ]);
  }
  /* The tab's accessible name is said once, in words. Left to the DOM it is the glyph, the
     count and the label run together ("⋯41More"), which is what a screen reader reads out,
     so the two decorative spans are hidden and the name carries the count as a sentence. */
  function renderDock() {
    var c = counts();
    paint('dock', dockKeys().map(function (key) {
      var v = viewOf(key) || { name: key, icon: '' };
      var n = key === 'attention' ? c.attention : key === 'more' ? c.reviews : 0;
      return el('button', { class: 'dock-item' + (App.view === key ? ' on' : ''),
        'aria-label': v.name + (n ? ', ' + n + ' waiting' : ''),
        'aria-current': App.view === key ? 'page' : null,
        onclick: function () { go(key); } },
        el('span', { class: 'ic', 'aria-hidden': 'true' }, v.icon, n ? el('span', { class: 'dock-badge', text: String(n) }) : null),
        el('span', { class: 'name', 'aria-hidden': 'true', text: v.name }));
    }));
  }

  /* ---------- a chip strip says which way it holds more ----------
   * A strip cut flat by the box's edge reads as broken rather than as scrollable, and no
   * CSS can ask where the reader left it. One attribute, set after every render and on the
   * strip's own scroll, and `ui.css` fades the edge it names.
   *
   * The listener is attached once per node, and whether it has been is a PROPERTY rather
   * than an attribute: the morph prunes an attribute the new tree does not carry, so a
   * `data-edged` marker would be wiped on the next pass and a second listener bound to the
   * same live node. */
  function markStrip(n) {
    var more = n.scrollWidth - n.clientWidth;
    if (more < 3) { n.setAttribute('data-edge', 'none'); return; }
    var start = n.scrollLeft > 2, end = n.scrollLeft < more - 2;
    n.setAttribute('data-edge', start && end ? 'both' : start ? 'start' : 'end');
  }
  function markStrips() {
    Array.prototype.forEach.call(document.querySelectorAll('.lanechips, .find-tokens'), function (n) {
      markStrip(n);
      if (n._edged) return;
      n._edged = true;
      n.addEventListener('scroll', function () { markStrip(n); });
    });
  }
  K.counts = counts; K.drainLine = drainLine;
  K.viewOf = viewOf; K.visibleViews = visibleViews; K.dockKeys = dockKeys; K.listedView = listed;
  K.declaredSomewhere = declaredSomewhere;
  K.drainPill = drainPill; K.bosunWord = bosunWord;
  K.renderRail = renderRail; K.renderHeader = renderHeader;
  K.renderControls = renderControls; K.renderDock = renderDock;
  K.markStrip = markStrip; K.markStrips = markStrips;

  /* ---------- shared pieces ---------- */
  function track(c) {
    var idx = STAGES.indexOf(stageOf(c)), busy = houseBusy(c);
    return el('span', { class: 'track' + (c.blocked_reason ? ' blocked' : ''), title: stageOf(c) }, STAGES.map(function (s, i) {
      return el('i', { class: i < idx ? 'done' : i === idx ? ('cur' + (busy ? ' pulse' : '')) : '' });
    }));
  }
  function stageDot(c) {
    var cls = c.blocked_reason ? 'exited' : houseBusy(c) ? 'busy' : 'idle';
    return el('span', { class: 'dot ' + cls, title: c.house ? (c.house.status || 'idle') : 'no house' });
  }
  function pill(text, cls) { return el('span', { class: 'spill ' + (cls || ''), text: text }); }
  function talkingPill(c) { return talking(c) ? pill('talking', 'talk') : null; }
  function needLine(c) {
    var g = gateOf(c);
    if (g === 'blocked') return 'blocked: ' + firstLine(c.blocked_reason);
    if (g === 'plan') return 'plan ready' + (c.children.length ? ', ' + c.children.length + ' slices' : '') + ', waiting on your tap';
    if (g === 'outcome') return 'outcome ready: ' + (c.output_ref || 'no output ref');
    if (c.derived.notice) return 'notice: ' + (firstLine(c.brief || '') || c.title);
    /* c-521: Bosun's open ask about this card, answered in the Bosun page's Now section */
    if (c.derived.ask) return 'Bosun asks (' + c.derived.ask.id + '): ' + c.derived.ask.question;
    /* r-55 (c-723): the house's question, in its own words */
    var waits = preparedOf(c);
    if (waits.length) return 'the house waits on your answer (' + waits[0].handle + '): ' + firstLine(waits[0].why);
    return c.last_event ? c.last_event.kind + (c.last_event.text ? ': ' + firstLine(c.last_event.text) : '') : '';
  }
  function lastLine(c) {
    var e = c.last_event;
    if (!e) return '';
    if (e.kind === 'stage') return 'stage: ' + firstLine(e.text || '');
    if (e.kind === 'hook') return c.last_said ? firstLine(c.last_said) : 'hook';
    return e.kind + (e.text ? ': ' + firstLine(e.text) : '');
  }
  function openLink(url) { if (url) window.open(url, '_blank', 'noopener'); }
  /* The plan opens FULL SCREEN, never in a box inside the pane. On the desk that is a tab
     beside the deck; on the phone it is a top level navigation in the surface he is
     already holding, so lavish gets the whole viewport and Back is the way out of it. */
  function openPlan(url) {
    if (!url) return;
    /* a markdown plan is a page of its own (`/plan/<c-id>`, app/plan.html, P2-5), opened
       beside the deck in a new tab on the desk and the phone alike */
    if (/^\/(plan|outcome|context|files?|ci|comments)\/c-\d+/.test(url) || isDesk()) { openLink(url); return; }
    location.href = url;
  }
  function sameOrigin(url) {
    if (!url) return null;
    var m = /^https?:\/\/(127\.0\.0\.1|localhost):(\d+)(\/.*)?$/.exec(url);
    if (m && App.data && String(App.data.config.lavish_port) === m[2]) return m[3] || '/';
    return url;
  }
  /* The plan the deck opens: the live surface he can annotate when lavish still has a
     session for it, the minted token otherwise. Null when there is neither. */
  function planLink(c) {
    if (c.links.plan_live) return { url: c.links.plan_live, label: 'Open plan (live)', live: true };
    /* A plan in the plan format opens on its own page (app/plan.html). Only one: a lavish
       page or a markdown file without frontmatter keeps opening the way it always did
       (P4-2), and the server is what says which is which (`links.formats`, keel/planfacts.py). */
    if (formatOf(c, 'plan')) return { url: '/plan/' + c.id, label: 'Open plan', live: false, native: true };
    if (c.links.plan) return { url: c.links.plan, label: 'Open plan', live: false };
    var direct = sameOrigin(c.plan_ref);
    return direct && /^https?:|^\//.test(direct) ? { url: direct, label: 'Open plan', live: false } : null;
  }
  function outputLink(c) { return c.links.pr || c.links.output || null; }
  /* The card's record (context.md), always a page of the card's viewer (c-644): the
     outcome page when it is in the plan format, else the context page, which draws it as
     plain markdown on the same shell so every page switches to the others. */
  function contextLink(c) {
    if (!c.links.context) return null;
    return formatOf(c, 'outcome') ? '/outcome/' + c.id : '/context/' + c.id;
  }
  function formatOf(c, doc) { return !!(c.links && c.links.formats && c.links.formats[doc]); }
  function valueAt(c, path) {
    return path.split('.').reduce(function (o, k) { return o && o[k] !== undefined ? o[k] : null; }, c);
  }
  /* ---------- what a pane remembers that the DOM never held ----------
   * The node cache that used to live here is gone: a section that has not changed is the
   * same node after the morph by construction, so holding one per key and hashing its
   * input was work to avoid work that is no longer done.
   *
   * What stays is `keepFlag`, and it stays because the morph CANNOT cover it. Whether a
   * long block is expanded is page state, not DOM state: nothing in the tree the renderer
   * builds says it, so a rebuild recomputes `.clip` from whatever the page remembers, and
   * if the page remembers nothing the block folds shut under him. The map belongs to ONE
   * pane, which `keepPane` names, so a key can never hand one card's flag to another. */
  var keptFor = null, keptFlags = {};
  function keepPane(name) {
    if (keptFor === name) return;
    keptFor = name; keptFlags = {};
  }
  /* Read with one argument, written with two. */
  function keepFlag(key, value) {
    if (value !== undefined) keptFlags[key] = !!value;
    return !!keptFlags[key];
  }
  K.keepPane = keepPane; K.keepFlag = keepFlag;

  /* ---------- the detail pane's frame ----------
   * One shape for every pane the deck opens beside a list: the title with the close
   * control, the identity line under it, the words that say where the thing stands, then
   * whatever rides above the actions, then the sticky action row, then the sections. The
   * Cards inspector and the Reviews pane are both drawn through this, so the two cannot
   * drift apart, and the close control is the same one Escape and Back reach.
   * `o` is {title, identity, words, lead, actions, sections, closeTitle}. */
  function paneFrame(o) {
    var closeTitle = o.closeTitle || 'close';
    return [
      el('div', { class: 'drawer-head' },
        el('div', { class: 'drawer-title' },
          el('h3', { class: 'title', text: o.title }),
          el('button', { class: 'iconbtn close', title: closeTitle, 'aria-label': closeTitle, onclick: closeDetail }, '✕')),
        o.identity ? el('div', { class: 'mono t11 ink2', text: o.identity }) : null,
        o.words || null),
      o.lead || null,
      /* what the pane is ABOUT, before its buttons: the phone card pane passes its plan,
         evidence and brief here (F2); every other pane leads with its action row */
      o.content || null,
      el('div', { class: 'actionbar' + (o.actionClass ? ' ' + o.actionClass : ''), 'data-key': 'actionbar' }, o.actions || []),
      o.sections || []
    ];
  }
  /* The same pane as a phone route: a back control above it, and the pane in a panel. */
  function phonePane(backLabel, content) {
    return [
      el('button', { class: 'back', onclick: closeDetail }, '‹ ', backLabel),
      el('div', { class: 'panel' }, el('div', { class: 'panel-body' }, content))
    ];
  }
  K.paneFrame = paneFrame; K.phonePane = phonePane;
  K.track = track; K.stageDot = stageDot; K.pill = pill; K.talkingPill = talkingPill;
  K.needLine = needLine; K.lastLine = lastLine; K.openLink = openLink; K.sameOrigin = sameOrigin;
  K.planLink = planLink; K.outputLink = outputLink; K.contextLink = contextLink; K.openPlan = openPlan; K.valueAt = valueAt;

  /* ---------- sheets: logs and the drop-in command ---------- */
  /* The sheet IS the answer, so these two say nothing in the toast on top of it. */
  function showLogs(id, from) {
    act({ verb: 'house.logs', id: id, lines: 200 }, function (r) {
      App.sheet = { kind: 'logs', id: id, text: r.logs }; K.renderSheet(); return '';
    }, from);
  }
  function showCommand(id, command, said) { App.sheet = { kind: 'command', id: id, text: command, said: said || '' }; K.renderSheet(); }
  /* The sheet is MORPHED like the body is. It is rebuilt whenever something goes in flight
     (`repaint`), and the gate's answer field is in it, so the caret and what he has typed
     live or die by this being a morph rather than an empty-and-add. */
  function sheetContent(s) {
    /* the gate answer sheet is the Cards module's own, drawn from the card and the draft */
    if (s.kind === 'say' && K.saySheet) return K.saySheet(s);
    /* the phone pane's More actions: every action its row did not show (ui.cards.js) */
    if (s.kind === 'actions' && K.actionsSheet) return K.actionsSheet(s);
    /* Open output on a card with a pull request per repo (c-565, ui.cards.js) */
    if (s.kind === 'prs' && K.prsSheet) return K.prsSheet(s);
    /* Talk on a shipping card: every way into its house's own session (c-600, ui.shipping.js) */
    if (s.kind === 'talk' && K.talkSheet) return K.talkSheet(s);
    /* Send back on a shipping card: his own notes for its house (c-663, ui.shipsendback.js) */
    if (s.kind === 'ship-sendback' && K.shipSendbackSheet) return K.shipSendbackSheet(s);
    /* a split button's menu on the phone (V2-1, ui.tips.js) */
    if (s.kind === 'menu' && K.menuSheet) return K.menuSheet(s);
    /* the drain pill's services sheet (ui.views.js) */
    if (s.kind === 'health' && K.healthSheet) return K.healthSheet(s);
    /* Assign tree's counts before he confirms: the tree module's own (ui.tree.js) */
    if (s.kind === 'assign' && K.assignSheet) return K.assignSheet(s);
    /* a review card's two settings, the model and his focus (ui.reviews.js) */
    if (s.kind === 'review-settings' && K.reviewSettingsSheet) return K.reviewSettingsSheet(s);
    /* a note pinned to a block or to the words he selected on a plan (ui.plan.js) */
    if (s.kind === 'plannote' && K.planNoteSheet) return K.planNoteSheet(s);
    var closeBtn = el('button', { onclick: function () { App.sheet = null; renderSheet(); } }, '‹ close');
    return el('div', { class: 'sheet' + (s.kind === 'logs' ? ' wide' : ''), 'data-key': 'sheet-' + s.kind },
      el('div', { class: 'sheet-head' }, closeBtn, el('span', { class: 'spacer' }), el('span', { class: 'mono t11 ink2', text: s.id + ' · ' + s.kind })),
      el('div', { class: 'sheet-body' }, s.kind === 'command'
        ? [el('div', { class: 'ink2', text: 'A server cannot open an interactive session. Run this at the desk:' }), el('code', { class: 'cmd', text: s.text }),
           s.said ? el('div', { class: 'ink2', text: s.said }) : null]
        : el('pre', { class: 'logs', text: s.text || '(no output)' })));
  }
  function renderSheet() {
    var s = App.sheet;
    paint('sheet', s ? sheetContent(s) : null);
  }
  K.showLogs = showLogs; K.showCommand = showCommand; K.renderSheet = renderSheet;
  K.POLL_MS = POLL_MS;
})(window.Keel);
