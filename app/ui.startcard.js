/* Your first card, the first run's step 11 (c-678), loaded before `ui.start.js`, which
 * reads it as `K.firstCardScreen(report, step, parts)`.
 *
 * Before a card is filed: the form (What to do, More about it, Repo, a choice of the repos
 * that are in, and File and start, which is `create` with `start`). The repo chosen is always
 * one of the list: the first, until another is picked, and again when the picked one is no
 * longer in, so what the list shows is what is sent. Above the form, when Bosun
 * left one while drafting a file that is now adopted (`step.suggestion`, keel/tierdrafts.py),
 * "A first card you could use" with Use this, which fills the form and sends nothing.
 *
 * Once a card is filed: its path, past review to landed. Each place is read from the card as
 * the state carries it: Waiting for a session, Planning, Your plan to approve (only where
 * the space shows plans, or the card is there now), Building, Checking its own work, Ready
 * for you, Landing, Landed. At a gate the step has the card's own two answers, Approve and
 * Send back (`approve` and `sendback`, the card pane's verbs, so nothing here is a second
 * way to answer). A landing that was refused is the stuck line in the server's words, with
 * Send back with the failures, which sends those words back as the reason. Landed shows the
 * link to what was opened, or, for a merge on this computer, the sentence and the Push
 * (`K.pushLine`, app/ui.landpush.js). The Push comes with the card's own detail (`push` on
 * `/api/card/<id>`), which this screen asks for once the card has landed: the state does not
 * read git for it on every build. The page holds one card's detail at a time, so when another
 * card's took its place this screen asks for its own again, once for each time that happens. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el, App = K.App;
  var draft = { title: '', brief: '', repo: '' };
  var back = {};        /* card id -> the reason being typed for Send back; undefined: closed */

  var STYLE = [
    '.fc{display:flex;flex-direction:column;gap:12px}',
    '.fc-panel{border:1px solid var(--hair-hi);background:var(--s1);padding:12px;display:flex;flex-direction:column;gap:8px;font-size:13px;line-height:1.5;min-width:0}',
    '.fc-panel.flag{border-color:var(--accent);background:var(--accent-soft)}',
    '.fc-panel h3{margin:0;font-size:15px}.fc-panel p{margin:0}',
    '.fc-form{display:flex;flex-direction:column;gap:8px}',
    '.fc-form label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--ink-2)}',
    '.fc-form input,.fc-form textarea,.fc-form select{width:100%;min-height:44px;font-size:13px}',
    '.fc-btns{display:flex;gap:8px;flex-wrap:wrap}.fc-btns .btn{min-height:44px}',
    '.fc-path{display:flex;flex-direction:column;gap:0;margin:0;padding:0;list-style:none}',
    '.fc-path li{display:grid;grid-template-columns:16px minmax(0,1fr);gap:4px 8px;padding:8px 0;border-top:1px solid var(--hair);font-size:13px;color:var(--ink-3)}',
    '.fc-path li:first-child{border-top:0}',
    '.fc-path li.past{color:var(--ink-2)}.fc-path li.past .fc-mark{color:var(--good)}',
    '.fc-path li.now{color:var(--ink);font-weight:600}.fc-path li.now .fc-mark{color:var(--accent-ink)}',
    '.fc-mark{font-family:var(--mono);font-size:11px;text-align:center}',
    '.fc-more{grid-column:2;font-weight:400;display:flex;flex-direction:column;gap:8px;min-width:0}',
    '.fc-more textarea{width:100%;min-height:88px;font-size:13px}'
  ].join('\n');
  function styleOnce() {
    if (document.getElementById('startcard-style')) return;
    var node = document.createElement('style');
    node.id = 'startcard-style';
    node.textContent = STYLE;
    document.head.appendChild(node);
  }
  function redraw() { K.renderBody(); }

  /* ---------- the form ---------- */

  /* every repo that is in, as `space/key`; the install's own repos (K.OWN_REPOS) are not the user's */
  function repos() {
    var out = [], spaces = (App.data || {}).spaces || {};
    Object.keys(spaces).forEach(function (name) {
      (spaces[name].repos || []).forEach(function (key) { if (!K.ownRepo(key)) out.push(name + '/' + key); });
    });
    return out;
  }
  function suggested(s) {
    return el('div', { class: 'fc-panel flag', 'data-key': 'first-suggestion' },
      el('h3', { text: 'A first card you could use' }),
      el('p', { 'data-key': 'first-suggested', text: 'While drafting ' + s.file + ', Bosun ' +
        (s.saw ? 'saw that ' + s.saw + '.' : 'noted one: ' + s.title + '.') + ' Want that as your first card?' }),
      el('div', { class: 'fc-btns' }, el('button', { class: 'btn', onclick: function () {
        draft = { title: s.title, brief: s.saw ? 'Bosun saw that ' + s.saw + '.' : '', repo: s.space + '/' + s.repo };
        redraw();
      } }, 'Use this')));
  }
  function form() {
    var list = repos();
    /* review r2.F4: with none chosen the browser showed the first and the card was filed with
       no repo, in whatever space the deck had open */
    if (list.indexOf(draft.repo) < 0) draft.repo = list[0] || '';
    return el('div', { class: 'fc-form', 'data-key': 'first-form' },
      el('label', null, el('span', { text: 'What to do' }),
        el('input', { type: 'text', 'data-fk': 'first-title', value: draft.title, 'aria-label': 'What to do',
          oninput: function (ev) { draft.title = ev.target.value; } })),
      el('label', null, el('span', { text: 'More about it' }),
        el('textarea', { 'data-fk': 'first-brief', rows: 3, value: draft.brief, 'aria-label': 'More about it',
          oninput: function (ev) { draft.brief = ev.target.value; } })),
      list.length ? el('label', null, el('span', { text: 'Repo' }),
        el('select', { 'data-fk': 'first-repo', 'aria-label': 'Repo', onchange: function (ev) { draft.repo = ev.target.value; } },
          list.map(function (r) { return el('option', { value: r, text: r.split('/')[1], selected: r === draft.repo }); }))) : null,
      el('div', { class: 'fc-btns' }, el('button', { class: 'btn primary', onclick: function () {
        var title = draft.title.trim(), at = (draft.repo || '').split('/');
        if (!title) { K.toast('Say what to do first.', true); return; }
        /* c-729: what the user wrote is sent as their words: the card gets a short title, and the
           words are its brief (keel/cardtitle.py) */
        K.act({ verb: 'create', space: at[1] ? at[0] : App.space, words: title, brief: draft.brief.trim(), repo: at[1] || null, start: true })
          .then(function (r) { if (r) draft = { title: '', brief: '', repo: '' }; });
      } }, 'File and start')));
  }

  /* ---------- the path ---------- */

  function live(card) {
    var found = ((App.data || {}).cards || []).filter(function (c) { return c.id === card.id; })[0];
    return found || { id: card.id, title: card.title, stage: card.stage, space: card.space, derived: {}, links: {} };
  }
  /* where the card is: the key of its place on the path */
  function placeOf(c, blocked) {
    var d = c.derived || {};
    if (c.stage === 'done') return 'landed';
    if (c.stage === 'shipping' || d.landing) return 'landing';
    if (c.stage === 'review') return blocked ? 'landing' : 'ready';
    if (c.stage === 'building') return 'building';
    if (c.stage === 'planning') return d.plan_gate ? 'plan' : 'planning';
    return 'waiting';
  }
  function answers(c, gate) {
    var typing = back[c.id] !== undefined;
    return [el('div', { class: 'fc-btns' },
      el('button', { class: 'btn primary', onclick: function () { K.act({ verb: 'approve', id: c.id, gate: gate }); } }, 'Approve'),
      el('button', { class: 'btn', onclick: function () { if (typing) delete back[c.id]; else back[c.id] = ''; redraw(); } }, 'Send back'),
      el('button', { class: 'btn', onclick: function () { K.go('cards', c.id); } }, 'Open ' + c.id)),
      typing ? [el('textarea', { 'data-fk': 'first-back', value: back[c.id], 'aria-label': 'What to change',
        oninput: function (ev) { back[c.id] = ev.target.value; } }),
        el('div', { class: 'fc-btns' }, el('button', { class: 'btn', onclick: function () {
          var reason = (back[c.id] || '').trim();
          if (!reason) { K.toast('Say what to change first.', true); return; }
          K.act({ verb: 'sendback', id: c.id, reason: reason }).then(function (r) { if (r) { delete back[c.id]; redraw(); } });
        } }, 'Send it back'))] : null];
  }
  function refusedLanding(c, why) {
    return K.stuck({ key: 'first-landing', name: 'Landing', what: (c.stuck && c.stuck.what) || why,
      fix: el('div', { class: 'fc-btns' }, el('button', { class: 'btn primary', onclick: function () {
        K.act({ verb: 'sendback', id: c.id, reason: why });
      } }, 'Send back with the failures')) });
  }
  var asked = {};      /* card id -> whose detail the page held when this card's was asked for */
  function landed(c, step) {
    var d = K.App.detailFor === c.id ? K.App.detail : null, links = c.links || {};
    var held = 'held:' + (K.App.detailFor || '');
    if (!d && asked[c.id] !== held && K.loadDetail) { asked[c.id] = held; K.loadDetail(c.id, true); }
    var push = d && d.push;
    var href = links.pr || links.output;
    if (push) return K.pushLine ? K.pushLine(c, push) : null;
    return href ? el('a', { href: href, target: '_blank', rel: 'noopener', text: links.pr ? K.say(c.space, 'Open the {change}') : c.output_ref || href }) : null;
  }
  function path(c, step, plans) {
    var blocked = (step.card || {}).blocked;
    var at = placeOf(c, blocked);
    var places = [['waiting', 'Waiting for a session'], ['planning', 'Planning'], ['plan', 'Your plan to approve'],
      ['building', 'Building'], ['checking', 'Checking its own work'], ['ready', 'Ready for you'],
      ['landing', 'Landing'], ['landed', 'Landed']]
      .filter(function (p) { return p[0] !== 'plan' || plans || at === 'plan'; });
    var here = places.map(function (p) { return p[0]; }).indexOf(at);
    return el('ol', { class: 'fc-path', 'data-key': 'first-path' }, places.map(function (p, i) {
      var cls = i < here ? 'past' : i === here ? 'now' : '';
      var more = i !== here ? null
        : p[0] === 'plan' ? answers(c, 'plan')
          : p[0] === 'ready' ? answers(c, 'outcome')
            : p[0] === 'landing' && blocked ? refusedLanding(c, blocked)
              : p[0] === 'landed' ? landed(c, step) : null;
      return el('li', { class: cls, 'data-key': 'first-place', 'data-place': p[0], 'data-at': cls || 'ahead' },
        el('span', { class: 'fc-mark', text: i < here ? '✓' : i === here ? '●' : '·' }),
        el('span', { text: p[1] }),
        more ? el('div', { class: 'fc-more' }, more) : null);
    }));
  }

  K.firstCardScreen = function (report, step, parts) {
    styleOnce();
    if (!step.card) return el('div', { class: 'fc', 'data-key': 'first-card' },
      step.suggestion ? suggested(step.suggestion) : null, form());
    var c = live(step.card);
    var plans = ((parts.plans && parts.plans()) || {})[c.space];
    return el('div', { class: 'fc', 'data-key': 'first-card' },
      el('div', { class: 'fc-panel', 'data-key': 'first-following' },
        el('h3', { text: c.id + ': ' + c.title }),
        path(c, step, plans),
        placeOf(c, (step.card || {}).blocked) === 'ready' || placeOf(c) === 'plan' ? null
          : el('div', { class: 'fc-btns' }, el('button', { class: 'btn sm', onclick: function () { K.go('cards', c.id); } }, 'Open ' + c.id))));
  };
})(window.Keel);
