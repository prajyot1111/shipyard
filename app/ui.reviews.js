/* The Reviews route, and PRs beside it.
 *
 * Reviews is the list of REVIEW CARDS (lane RC): a pull request that needs his review is a
 * card (keel/reviewcards.py files it), and the list is those cards and nothing else. The
 * old scanner's rows and its row verbs (Lavish review, Terminal review, Launch review and
 * the lane moves) are not drawn: a card's own actions are (Review is the move to assigned,
 * the outcome page is where the findings are read and posted). A tap opens the card's own
 * pane, the Cards inspector's, beside the list on the desk and as a route on the phone, so
 * its grouped actions and their lines are the ones every card has.
 *
 * Found through the deck's one find bar (lane FIND; app/ui.find.js, the `reviews` table in
 * app/ui.findpages.js), newest raised first by default, reading the facts every review card
 * carries: where it stands (`derived.review`), the highest severity he posted
 * (`derived.review_severity`), and the pull request's author, when it was raised and its
 * latest activity (`options.review_pr`). Include backlog adds the quiet ones, Include
 * closed the ones whose pull request merged or was declined, Include dismissed the ones he
 * put away. The View button offers List or Kanban on the desk (below, "the kanban").
 *
 * The fetcher's two settings sit behind a small gear at the title: auto review (a new
 * review card goes straight to assigned) and the review model (the model a new review card
 * carries), both the adapter's `reviews` provider's facts, set through its route verbs.
 *
 * PRs is the same provider board it has always been, with the same pane: the tile says
 * the pull request, the pane carries its verbs. */
(function (K) {
  'use strict';

  var el = K.el, add = K.add, App = K.App;

  /* ---------- sending a verb ----------
   * One answer handler for every verb, because the adapter answers in one of four ways:
   * a command for the desk (a sheet, the way Drop in hands one over), a surface on this
   * origin (a new tab), a card it made, or a sentence. */
  function reply(result, label) {
    if (!result) return '';
    /* the sheet and the new tab ARE the answer, so neither says it again in the toast */
    if (result.command) { K.showCommand(result.cwd || 'review', result.command); return ''; }
    if (result.surface) K.openLink(result.surface);
    return result.message || (result.output ? K.firstLine(result.output) : (label || 'done'));
  }
  function routeBody(verb, value) {
    return { verb: 'adapter', space: App.space, route: 'reviews', action: verb,
             args: value ? { value: value } : {} };
  }
  function routeVerb(verb, value, label, from) {
    K.act(routeBody(verb, value), function (r) { return reply(r, label); }, from);
  }

  /* ---------- the settings the fetcher reads (lane RC) ---------- */
  function segmented(label, values, current, verb) {
    return el('div', { class: 'filters' },
      el('span', { class: 'lbl10', text: label }),
      el('div', { class: 'toggle' }, values.map(function (value) {
        var body = routeBody(verb, value), busy = K.isPending(K.pendKey(body));
        return el('button', { class: (value === current ? 'on' : '') + (busy ? ' pending' : ''), 'data-key': verb + ':' + value,
          disabled: busy || K.pendingOn('reviews') ? true : null, title: label + ' ' + value,
          onclick: function (ev) { routeVerb(verb, value, label + ' ' + value, ev.currentTarget); } }, value);
      })));
  }
  /* Drawn from the provider's facts only: no toggle without the flag, no model choice
     without the list the adapter names (then the model it uses, sonnet unless set). */
  function settingsControls(s) {
    return [
      typeof s.auto_review === 'boolean'
        ? segmented('auto review', ['on', 'off'], s.auto_review ? 'on' : 'off', 'set_auto_review') : null,
      (s.models || []).length ? segmented('review model', s.models, s.review_model || 'sonnet', 'set_review_model')
        : el('span', { class: 'pill', text: 'review model ' + (s.review_model || 'sonnet') })
    ].filter(Boolean);
  }
  function settingsOf() { var r = K.providers('reviews'); return (r && r.settings) || null; }
  /* The two settings behind a small gear at the Reviews title, on the desk and the phone
     alike: they are set once in a while, and the list is what he came for. */
  function gear(s) {
    var open = !!App.reviewGear;
    return el('button', { class: 'btn sm ghost rv-gear' + (open ? ' on' : ''), 'data-key': 'review-gear',
      'aria-expanded': open ? 'true' : 'false', title: 'Review settings: auto review and the review model',
      onclick: function () { App.reviewGear = !open; K.renderBody(); } }, '⚙ settings');
  }
  /* His Scan now (2026-09-25): the review fetcher on the machine that holds the space looks
     on its next drain pass, instead of waiting out its 15-minute cadence. Drawn only when
     the adapter offers the verb; its tip says when it last looked, or that a scan is asked. */
  function scanNow(s) {
    if (!(s.verbs || []).some(function (v) { return v.verb === 'scan_now'; })) return null;
    var body = routeBody('scan_now'), busy = K.isPending(K.pendKey(body)) || !!s.scan_asked;
    var said = s.scan_asked ? 'scan asked, the next pass looks'
      : (s.last_scan ? 'last scanned ' + (K.ago(s.last_scan) === 'just now' ? 'just now' : K.ago(s.last_scan) + ' ago') : 'not scanned yet');
    return el('button', { class: 'btn sm ghost rv-scan' + (busy ? ' pending' : ''), 'data-key': 'review-scan',
      disabled: busy ? true : null, title: K.say(App.space, 'Scan now: look for {changes} that need your review now, ') +
        'not at the next 15-minute scan (' + said + ')',
      onclick: function (ev) { routeVerb('scan_now', null, 'Scan now', ev.currentTarget); } },
      s.scan_asked ? 'Scanning' : 'Scan now');
  }
  function gearMenu(s) {
    return App.reviewGear ? el('div', { class: 'panel-head rv-gear-menu', 'data-key': 'review-settings' }, settingsControls(s)) : null;
  }

  /* ---------- the review cards (lane RC) ---------- */
  /* ---------- lane GRP: a feature card's members ----------
   * One story's pull requests reviewed as one card (`options.review_members`): each member
   * is a chip saying its repo and number that opens its own pull request. The row is itself
   * a button, so a chip is a span with the link role, and its tap does not select the row. */
  function reviewMembers(c) {
    return ((c.options && c.options.review_members) || []).map(function (m) {
      return el('span', { class: 'spill member', role: 'link', tabindex: '0', 'data-key': 'member-' + m.label,
        title: 'Open ' + m.label + (m.author ? ', by ' + m.author : '') + ' on the code host',
        onclick: function (ev) { ev.stopPropagation(); K.openLink(m.url); } }, m.repo + ' #' + m.pr);
    });
  }
  function prOf(c) { return (c.options && c.options.review_pr) || {}; }
  function raisedAt(c) { return prOf(c).created || c.created_at; }
  /* Every review card of the space, dismissed (archived) ones included: the find bar hides
     those until Include dismissed, as it hides the backlog until Include backlog. */
  function allReviewCards() {
    return ((App.data && App.data.cards) || []).filter(function (c) {
      return c.derived && c.derived.review && (!App.space || c.space === App.space);
    });
  }
  function reviewCards() { return allReviewCards().filter(function (c) { return !c.derived.archived; }); }
  function reviewRow(c) {
    var pr = prOf(c), st = c.derived.review, loud = st === 'gate' || st === 'new' || st === 'waiting';
    /* the row says its column, in the board's word, and what that means on hover */
    var lane = K.findPages.reviews.lanes.filter(function (l) { return l.key === K.findPages.reviews.laneOf(c); })[0];
    var sub = [K.reviewWaitLine(c) || null, pr.author ? 'by ' + pr.author : null, c.options && c.options.pr ? K.say(c.space, '{change_short} #') + c.options.pr : null,
               'raised ' + K.ago(raisedAt(c)) + ' ago'].filter(Boolean).join(' · ');
    var members = reviewMembers(c);
    return el('button', { class: 'row' + (st === 'gate' ? ' k-outcome' : '') + (App.card === c.id ? ' sel' : ''),
      'data-key': c.id, onclick: function () { K.select(c.id); } },
      el('div', { class: 'row-head' },
        el('span', { class: 'id', text: c.id }),
        el('span', { class: 't ellip', title: c.title, text: c.title }),
        el('span', { class: 'age', text: K.ago(c.updated_at) })),
      el('div', { class: 'row-chips' },
        el('span', { class: 'spill' + (loud ? ' gate' : ''), title: lane ? K.say(c.space, lane.said) : null, text: lane ? lane.label : st }),
        badges(c), members.length ? members : (c.repo ? el('span', { class: 'spill', text: c.repo }) : null)),
      el('div', { class: 'sub ellip', title: sub, text: sub }));
  }
  /* A review card in the backlog (its pull request quiet past the space's days, or his
     override) is out of the way here as it is in Cards and Attention: counted in the title,
     and listed with the find bar's Include backlog (or the Backlog view). */
  function backlogged() { return reviewCards().filter(function (c) { return c.derived.backlog; }); }
  function reviewsHeading(all) {
    var waiting = all.filter(function (c) { return c.derived.review === 'waiting'; }).length;
    var gate = all.filter(function (c) { return c.derived.review === 'gate'; }).length;
    var parked = backlogged().length;
    return 'Reviews · ' + all.length + (waiting ? ', ' + waiting + ' waiting for Review' : '')
      + (gate ? ', ' + gate + ' at your gate' : '') + (parked ? ', ' + parked + ' in the backlog' : '');
  }
  /* ---------- the kanban (2026-09-24) ----------
   * The List or Kanban choice is the find bar's View button (the `reviews` table's layout
   * mode), remembered and in the URL like Cards' layout, and desk only: the phone stays a
   * list. The columns are the OLD REVIEW BOARD's, in its order and under its names
   * (`lanes` and `laneOf` in the `reviews` table, which the State facet reads too, so the
   * filter and the columns agree): Detected, Assigned, Inbox, Held, Posted, and Dismissed
   * while Include dismissed is on. Held is always drawn, backlog cards in it whether or not
   * Include backlog is on (the list keeps them out until it is): it is where the quiet ones
   * live and its count tells him. A posted card with new commits stays in Posted with a
   * badge. The columns are the FOUND list cut by column, in its order, so every filter and
   * the sort apply within them. A tile is not dragged: a review moves by its own actions
   * (Review, Approve, Re-review), which the pane carries. */
  function spec() { return K.findPages.reviews; }
  function lanesOn() {
    var inc = K.find.state('reviews').inc;
    return spec().lanes.filter(function (l) { return l.key !== 'dismissed' || inc.indexOf('dismissed') >= 0; });
  }
  /* the kanban's own find: the bar's state with the backlog always in, since Held is */
  function kanbanFound(items) {
    var st = JSON.parse(JSON.stringify(K.find.state('reviews')));
    if (st.inc.indexOf('backlog') < 0) st.inc.push('backlog');
    return K.findCore.run(items, st, spec(), K.find.ctx());
  }
  function badges(c) {
    var sev = c.derived.review_severity;
    return [c.derived.review === 'new' ? el('span', { class: 'spill gate', text: 'new commits' }) : null,
      c.derived.review === 'closed' ? el('span', { class: 'spill', text: 'closed' }) : null,
      sev ? el('span', { class: 'spill' + (/critical|high/.test(sev) ? ' crit' : ''), text: sev }) : null];
  }
  function reviewTile(c) {
    var pr = prOf(c);
    var said = [pr.author, c.options && c.options.pr ? '#' + c.options.pr : null].filter(Boolean).join(' · ');
    return el('div', { class: 'tile' + (c.derived.review === 'gate' ? ' need' : '') + (App.card === c.id ? ' sel' : '')
      + (K.pendingOn(c.id) ? ' pending' : ''), 'data-key': c.id, onclick: function () { K.select(c.id); } },
      el('div', { class: 'h' }, el('span', { class: 'id', text: c.id }), el('span', { class: 'spacer' })),
      el('div', { class: 't', text: c.title }),
      el('div', { class: 'row-chips' }, badges(c), reviewMembers(c)),
      K.reviewWaitLine(c) ? el('div', { class: 'm ellip', text: K.reviewWaitLine(c) }) : null,
      el('div', { class: 'm' }, el('span', { class: 'ellip', title: said, text: said }),
        el('span', { text: 'raised ' + K.ago(raisedAt(c)) })));
  }
  function reviewKanban(items) {
    return el('div', { class: 'board', 'data-key': 'reviews-board' }, lanesOn().map(function (l) {
      var mine = items.filter(function (c) { return spec().laneOf(c) === l.key; });
      return el('section', { class: 'lane', 'data-key': l.key },
        el('div', { class: 'lane-head', title: K.say(App.space, l.said) }, el('span', { class: 'lbl10', text: l.label }),
          el('span', { class: 'n', text: String(mine.length) })),
        el('div', { class: 'lane-said t11 ink2', text: K.say(App.space, l.said) }),
        el('div', { class: 'stack' }, mine.length ? mine.map(reviewTile) : el('div', { class: 'empty', text: 'none' })));
    }));
  }

  function viewReviews() {
    var all = reviewCards().filter(function (c) { return !c.derived.backlog; });
    var board = K.isDesk() && K.find.mode('reviews', 'layout') === 'kanban';
    var found = board ? kanbanFound(allReviewCards()) : K.find.run('reviews', allReviewCards());
    var sel = App.card ? K.byId(App.card) : null, s = settingsOf();
    if (sel && !K.isDesk()) return K.phoneDetail(sel, 'reviews');
    var empty = allReviewCards().length ? 'no review matches' : K.say(App.space, 'no {change} needs your review');
    /* c-631: while review scanning or the code host is not set up, the page's panel says so,
       and an empty list is not followed by a false "nothing to review" */
    if (K.unmet(K.viewOf('reviews').needs).length) empty = null;
    var rows = board ? reviewKanban(found.items)
      : el('div', { class: 'split-table', 'data-key': 'reviews-list' },
        found.items.length ? found.items.map(reviewRow) : empty ? el('div', { class: 'empty', text: empty }) : null);
    return el('section', { class: 'panel grow' },
      el('div', { class: 'panel-head' },
        el('span', { class: 'label', text: reviewsHeading(all) }),
        el('span', { class: 'spacer' }),
        s ? scanNow(s) : null,
        s ? gear(s) : null),
      s ? gearMenu(s) : null,
      el('div', { class: 'panel-body' }, K.find.bar('reviews', found),
        withPane(rows, sel && K.isDesk() ? K.detailPane(sel) : null)));
  }
  /* What the rail and Now count: the review cards waiting on him (his Review tap, his gate,
     new commits since his review). */
  function reviewCount() {
    return reviewCards().filter(function (c) {
      if (c.derived.backlog) return false;
      return c.derived.review === 'waiting' || c.derived.review === 'gate' || c.derived.review === 'new';
    }).length;
  }

  /* ---------- Review settings (2026-09-24) ----------
   * A review card takes its fields from its pull request, so it has no Edit: its Card group
   * has Review settings instead (drawn by app/ui.cards.js while nothing is reviewing), a
   * sheet with exactly two fields. Model: Sonnet or Opus, starting from the card's own (the
   * fetcher's review model when it was filed). Focus: optional words kept on the card
   * (`options.review_focus`), which the reviewer is handed with the diff
   * (keel/review/brief.py `write_focus`). One `set` writes both; an empty focus clears it. */
  var REVIEW_MODELS = [['sonnet', 'Sonnet'], ['opus', 'Opus']];
  function openReviewSettings(c) {
    App.sheet = { kind: 'review-settings', id: c.id, model: c.model || 'sonnet',
                  focus: (c.options && c.options.review_focus) || '' };
    K.renderSheet();
  }
  function settingsBody(s) {
    return { verb: 'set', id: s.id,
             fields: { model: s.model, 'options.review_focus': String(s.focus || '').trim() || null } };
  }
  function closeSettings() { App.sheet = null; K.renderSheet(); }
  function modelChoice(s) {
    return el('div', { class: 'toggle rs-model', role: 'radiogroup', 'aria-label': 'Model' }, REVIEW_MODELS.map(function (m) {
      return el('button', { class: s.model === m[0] ? 'on' : '', 'data-key': 'rs-model-' + m[0], role: 'radio',
        'aria-checked': s.model === m[0] ? 'true' : 'false', onclick: function () { s.model = m[0]; K.renderSheet(); } }, m[1]);
    }));
  }
  function reviewSettingsSheet(s) {
    var c = K.byId(s.id);
    if (!c) return el('div', { class: 'sheet' });
    var save = K.faceBtn('Save', settingsBody(s), 'primary', function () {
      K.act(settingsBody(App.sheet), function () { closeSettings(); return 'review settings saved'; });
    });
    save.setAttribute('data-key', 'rs-save');
    return el('div', { class: 'sheet', 'data-key': 'sheet-review-settings' },
      el('div', { class: 'sheet-head' }, el('button', { onclick: closeSettings }, '‹ close'),
        el('span', { class: 'spacer' }), el('span', { class: 'mono t11 ink2', text: c.id + ' · review settings' })),
      el('div', { class: 'sheet-body' },
        el('div', { class: 'title', text: c.title }),
        el('div', { class: 'saybox' }, el('span', { class: 'label', text: 'Model' }), modelChoice(s),
          el('span', { class: 'fhelp', text: 'The model this review runs on.' })),
        el('div', { class: 'saybox' }, el('span', { class: 'label', text: 'Focus' }),
          el('textarea', { 'data-fk': 'review-focus', rows: '4', value: s.focus,
            placeholder: 'optional: where the reviewer should look hardest',
            oninput: function (ev) { s.focus = ev.target.value; } }),
          el('span', { class: 'fhelp', text: 'Handed to the reviewer with the diff. It says where to look hardest; it does not narrow the review.' }))),
      el('div', { class: 'sheet-foot' }, el('button', { class: 'btn', onclick: closeSettings }, 'Cancel'), save));
  }
  K.openReviewSettings = openReviewSettings; K.reviewSettingsSheet = reviewSettingsSheet;
  /* The list and its detail pane side by side on the desk. */
  function withPane(content, pane) {
    return el('div', { class: 'split' }, content,
      pane ? el('div', { class: 'split-pane drawer', 'data-key': 'row-detail' }, pane) : null);
  }


  function viewRoute(route) {
    /* Reviews is the one route left (the PRs page retired with PR watch, lane RETIRE). */
    return viewReviews();
  }

  K.viewRoute = viewRoute; K.reviewCount = reviewCount; K.reviewMembers = reviewMembers;
})(window.Keel);
