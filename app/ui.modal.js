/* The card modal: the new-card form, the same form editing a card's options, and the
 * Split dialog that cuts one card into slices.
 *
 * Every field comes from the space's `options` schema in the state document (the
 * adapter's options.json, already in the order the retired dashboard's modal had, with
 * its `when` and `default_if` rules), plus the fields every card has: title, brief and
 * topic first, then the two that place it under a big card, parent and after. The page
 * names nothing itself: labels, choices, help and even the story format come from the
 * schema, so an adapter change moves the form without a code change.
 *
 * A New project field is a card field like any other: the page sends the name it was
 * given and `kb create` decides what it means (the repo, the option placement reads, and
 * the attended default a first card on an empty repository gets).
 *
 * Create sends `create` (Enter files to inbox, Create and start also stages assigned);
 * edit sends `set`, with card fields as fields and the rest as `options.<key>`; Split
 * sends `split` with one `{title, brief, after, repo}` per slice, the shape `actions.split_argv`
 * folds back into `--slice "title|brief|after-title|repo=key"`.
 * On the phone the dialog is a full-screen sheet; the CSS decides that, not this file. */
(function (K) {
  'use strict';

  var el = K.el, add = K.add, App = K.App;

  /* ---------- the schema ---------- */
  function spaceOf(name) { return (K.App.data && K.App.data.spaces[name]) || { options: [], repos: [] }; }

  /* A card that may be this one's parent: unarchived, in this space, and neither the card
     itself nor one of its own slices (a card cannot be its own big card). */
  function parentChoices(space, id) {
    return K.cards().filter(function (c) {
      return c.space === space && !c.derived.archived && c.id !== id && c.parent !== id;
    }).map(function (c) { return { value: c.id, label: c.id + ' · ' + c.title }; });
  }
  /* The siblings a slice can be told to wait for: the parent's other children. */
  function afterChoices(parentId, id) {
    var p = parentId ? K.byId(parentId) : null;
    if (!p) return [];
    return (p.children || []).filter(function (kid) { return kid !== id; }).map(function (kid) {
      var k = K.byId(kid);
      return { value: kid, label: kid + (k ? ' · ' + k.title : '') };
    });
  }
  function schema(space, id) {
    return [
      { key: 'title', label: 'Title', type: 'text', stored: 'card', placeholder: 'what needs doing' },
      { key: 'topic', label: 'Topic', type: 'text', stored: 'card', placeholder: 'a word to group by' },
      { key: 'brief', label: 'Brief', type: 'textarea', stored: 'card', wide: true,
        placeholder: 'the detail the house starts from' }
    ].concat(personalRows(space, spaceOf(space).options || [])).concat([
      { key: 'parent', label: 'Parent', type: 'cardref', stored: 'card',
        choices: function () { return parentChoices(space, id); },
        help: 'the big card this one is a slice of' },
      { key: 'after', label: 'After', type: 'cardref', stored: 'card', when: 'parent != none',
        choices: function (v) { return afterChoices(v.parent, id); },
        help: 'the sibling slice this one waits for; it cannot start until that one is at review or done' }
    ]);
  }
  /* A personal card (c-592) is either code, which Bosun builds (a repo), or research, a
     plan or an errand, which a house does (none). Plan style decides nothing while plans
     are pages (`[keel] plan_pages`, on by default), and the model is the house's, so a card
     with a repo, which has no house, does not ask for one. Driven by Bosun is gone: a
     personal card is Bosun's by its repo, never by a switch. */
  function personalRows(space, rows) {
    if (space !== 'personal') return rows;
    var pages = !!(App.data && App.data.config && App.data.config.plan_pages);
    return rows.filter(function (f) { return !(pages && f.key === 'plan_style'); }).map(function (f) {
      return f.key === 'model' && !f.when ? Object.assign({}, f, { when: 'repo == none' }) : f;
    }).concat(workerRows());
  }

  /* WHO WORKS IT (c-645), said before the card exists. In builder mode a personal card on a
     repo Bosun builds is his by default, and the form says so with a choice of a house; on
     any other card it says "a house", one line, so where a card goes is never a surprise.
     A new card only: a card's worker moves on its pane (Give to a house, Give to Bosun),
     before anything starts. The board checks the same rule (`views.bosun_eligible`). */
  function builder() { return (App.data && App.data.config && App.data.config.builder) || { on: false }; }
  function firstRepo(v) {
    var r = Array.isArray(v.repo) ? v.repo[0] : String(v.repo || '').split(',')[0];
    /* a new project becomes the card's repo (`kb create --new-project`), so it counts (r1.F6) */
    return String(r || v.new_project || '').trim();
  }
  function eligible(v) {
    var b = builder(), repo = firstRepo(v);
    return !!(b.on && repo && (b.builds === null || (b.builds || []).indexOf(repo) >= 0));
  }
  function workerWords(worker, v) {
    if (worker === 'house') return 'A house builds it; its plan and outcome are yours to approve.';
    /* the repo's own landing branch (c-665), or no branch named where it has none */
    var on = K.landsOn(App.modal.space || App.space, firstRepo(v || {}));
    return builder().lands
      ? 'Bosun builds it and lands it' + (on ? ' on ' + on : '') + ' itself; the deploy stays yours.'
      : 'Bosun builds it' + (on ? ' on ' + on : '') + '; you approve its plan and outcome.';
  }
  function workerRows() {
    if (!builder().on) return [];
    return [
      { key: 'worker', label: 'Worker', type: 'select', stored: 'options', options: ['bosun', 'house'], default: 'bosun',
        shown: function (v) { return App.modal && App.modal.mode !== 'edit' && eligible(v); },
        help: function (v) { return workerWords(v.worker || 'bosun', v); } },
      { key: 'worker_fact', label: 'Worker', type: 'fact',
        shown: function (v) { return App.modal && App.modal.mode !== 'edit' && !eligible(v); },
        fact: function (v) {
          return firstRepo(v) ? 'A house: Bosun builds only the repos on [builder] repos. ' + workerWords('house')
            : 'A house: no repo, so research, a plan or an errand. ' + workerWords('house');
        } }
    ];
  }
  K.workerWords = workerWords;
  function storyField(space) {
    return schema(space).filter(function (f) { return f.type === 'story'; })[0] || null;
  }

  /* `when` and `default_if`: `key == value` / `key != value` clauses joined by ` and `. */
  function clause(text, values) {
    var m = /^\s*([a-z_]+)\s*(==|!=)\s*(.+?)\s*$/.exec(text);
    if (!m) return true;
    var raw = m[3].trim().toLowerCase(), actual = values[m[1]], same;
    if (raw === 'none' || raw === 'null' || raw === '""') {
      /* an empty multiselect is nothing chosen, which is what `repo == none` asks about */
      var none = actual === null || actual === undefined || actual === '' || actual === 'none'
        || actual === false || (Array.isArray(actual) && !actual.length);
      return m[2] === '==' ? none : !none;
    }
    var expected = raw === 'true' ? true : raw === 'false' ? false : raw;
    same = actual !== null && actual !== undefined && String(actual).toLowerCase() === String(expected).toLowerCase();
    return m[2] === '==' ? same : !same;
  }
  function evaluate(cond, values) {
    if (!cond || !cond.trim()) return true;
    return cond.split(' and ').every(function (part) { return clause(part, values); });
  }
  function equality(cond) {
    /* the first `key == value` clause of a condition, for the inference below */
    var parts = (cond || '').split(' and ');
    for (var i = 0; i < parts.length; i++) {
      var m = /^\s*([a-z_]+)\s*==\s*(.+?)\s*$/.exec(parts[i]);
      if (m) return { key: m[1], value: m[2] };
    }
    return null;
  }
  /* c-604: a multiselect (the repo chips) starts with NOTHING chosen unless it has exactly
     one choice and the sheet's default names one: a preselected `api` chip, one of two, filed
     cards in a repo he never picked. His tap is the only other way a chip turns on. A sheet
     that defaults to none (the personal space's: none is research or an errand) stays none. */
  function defaultOf(e) {
    if (e.type === 'multiselect') {
      var one = (e.options || []).length === 1 && Array.isArray(e.default) && e.default.length;
      return one ? [e.options[0]] : [];
    }
    return Array.isArray(e.default) ? e.default.slice() : e.default;
  }
  function defaultsFor(fields) {
    var v = {};
    fields.forEach(function (e) { if ('default' in e || e.type === 'multiselect') v[e.key] = defaultOf(e); });
    fields.forEach(function (e) { if ('default_if' in e) v[e.key] = evaluate(e.default_if, v); });
    return v;
  }

  /* ---------- a card's own values, for the edit form ---------- */
  function valuesOfCard(card) {
    var v = {};
    schema(card.space, card.id).forEach(function (f) {
      if (f.stored === 'options') { if (f.key in (card.options || {})) v[f.key] = card.options[f.key]; return; }
      var raw = card[f.key];
      if (raw === null || raw === undefined) return;
      v[f.key] = f.type === 'multiselect' ? String(raw).split(',').filter(Boolean) : raw;
    });
    return v;
  }

  /* ---------- the live value set ---------- */
  function values() {
    var m = App.modal, fields = schema(m.space, m.id), v = defaultsFor(fields);
    Object.keys(m.base || {}).forEach(function (k) { v[k] = m.base[k]; });
    Object.keys(m.inferred || {}).forEach(function (k) { if (!(k in m.values)) v[k] = m.inferred[k]; });
    Object.keys(m.values).forEach(function (k) { v[k] = m.values[k]; });
    /* a `default_if` the human has not overridden follows the fields it depends on */
    fields.forEach(function (e) {
      if ('default_if' in e && !(e.key in m.values) && !(e.key in (m.inferred || {})) && !(e.key in (m.base || {}))) {
        v[e.key] = evaluate(e.default_if, v);
      }
    });
    return v;
  }
  /* c-732 r2.F4: a row that names `repos` (Base branch in a space where some repos land on an
     integration branch) is shown only for a card whose repos are all among them */
  function onRepos(f, v) {
    if (!f.repos) return true;
    var chosen = Array.isArray(v.repo) ? v.repo : String(v.repo || '').split(',').filter(Boolean);
    return chosen.length > 0 && chosen.every(function (r) { return f.repos.indexOf(r) >= 0; });
  }
  function visibleFields(v) {
    return schema(App.modal.space, App.modal.id).filter(function (f) {
      return evaluate(f.when, v) && (!f.shown || f.shown(v)) && onRepos(f, v);
    });
  }

  /* ---------- the story reference ----------
   * The schema says the shape it wants (`normalise`, e.g. a prefix and a number), so a
   * bare id, the prefixed id and a full tracker link all land in that shape without this
   * file knowing which tracker it is. */
  function normaliseRef(pattern, raw) {
    var text = String(raw || '').trim();
    if (!pattern || !text) return text;
    var m = /^(.*)<n>(.*)$/.exec(pattern);
    if (!m) return text;
    var prefix = m[1], suffix = m[2];
    var after = prefix ? new RegExp(prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(\\d+)', 'i').exec(text) : null;
    var digits = after ? after[1] : null;
    if (!digits) {
      var runs = text.match(/\d+/g) || [];
      runs.sort(function (a, b) { return b.length - a.length; });
      digits = runs[0] || null;
    }
    return digits ? prefix + digits + suffix : text;
  }
  K.normaliseRef = normaliseRef;

  /* ---------- inference from the title ----------
   * What the old one-line composer did, kept: a story reference, a repo, "plan it first"
   * and a leading verb fill fields the human has not set. The words come from the schema
   * (a select's own choices, a multiselect's own repos), never from this file, and the
   * title itself is left exactly as typed: a form that rewrites what you are typing is
   * worse than one that guesses beside it. */
  var LEADING = [[/^\s*(fix|bug)\b/i, 'bug'], [/^\s*(research|understand|investigate|explore)\b/i, 'research'],
                 [/^\s*(chore|rename|clean|tidy|upgrade|bump)\b/i, 'chore'], [/^\s*(add|build|ship|implement)\b/i, 'feature']];

  function selectHolding(fields, word) {
    return fields.filter(function (f) {
      return f.type === 'select' && (f.options || []).some(function (o) { return String(o).toLowerCase() === word; });
    })[0] || null;
  }
  function infer() {
    var m = App.modal, text = String(m.values.title || m.inferred.title || ''), fields = schema(m.space, m.id), inf = {};
    var story = storyField(m.space);
    if (story) {
      var prefix = (/^(.*)<n>/.exec(story.normalise || '') || [])[1] || '';
      var re = prefix ? new RegExp('\\b' + prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '?(\\d{3,})\\b', 'i') : null;
      var hit = re ? re.exec(text) : null;
      if (hit) {
        inf[story.key] = normaliseRef(story.normalise, hit[0]);
        inf.topic = inf[story.key];
        var need = equality(story.when);     // the mode that makes the story field appear
        if (need) inf[need.key] = need.value;
      }
    }
    fields.forEach(function (f) {
      if (f.type !== 'multiselect') return;
      var found = (f.options || []).filter(function (o) {
        return new RegExp('\\b' + String(o).replace(/-/g, '[- ]?') + '\\b', 'i').test(text);
      });
      if (found.length) inf[f.key] = found;
    });
    /* a new project's first card decides what the project is, so it is planned with him
       unless he says otherwise; the same rule `kb create --new-project` applies */
    if (/\bplan (it )?first\b|\battended\b/i.test(text) || String(m.values.new_project || '').trim()) {
      var attended = selectHolding(fields, 'attended');
      if (attended) inf[attended.key] = 'attended';
    }
    for (var i = 0; i < LEADING.length; i++) {
      if (!LEADING[i][0].test(text)) continue;
      var kind = selectHolding(fields, LEADING[i][1]);
      if (kind) { inf[kind.key] = LEADING[i][1]; break; }
    }
    if (!inf.topic && text) {
      var words = text.replace(/^\[[^\]]*\]\s*/, '').split(/\s+/)
        .filter(function (w) { return /^[a-z0-9-]+$/i.test(w); }).slice(0, 2);
      if (words.length) inf.topic = words.join(' ').toLowerCase().replace(/[:,.]$/, '');
    }
    delete inf.title;
    App.modal.inferred = inf;
  }

  /* ---------- opening and closing ---------- */
  function openModal(card) {
    /* c-540 (review F1): a scoped state clips a long brief, and a form based on the clip
       would write the clip back over the whole brief. Its base is the card's detail. */
    if (card && card.brief_clipped) {
      var d = App.detailFor === card.id ? App.detail : null;
      if (!(d && d.card)) {
        return fetch('/api/card/' + encodeURIComponent(card.id), { cache: 'no-store' })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (got) {
            if (got && got.card) openModal(Object.assign({}, card, { brief: got.card.brief, brief_clipped: false }));
            else K.toast('the whole brief could not be read, so Edit did not open; try again', true);
          }).catch(function () { K.toast('the whole brief could not be read, so Edit did not open; try again', true); });
      }
      card = Object.assign({}, card, { brief: d.card.brief, brief_clipped: false });
    }
    App.modal = card
      ? { mode: 'edit', id: card.id, space: card.space, base: valuesOfCard(card), values: {}, inferred: {} }
      : { mode: 'create', id: null, space: App.space, base: {}, values: {}, inferred: {} };
    renderModal();
    var first = document.querySelector('.modal [data-fk="f:title"]');
    if (first) first.focus();
  }
  /* c-604: a focused field is BLURRED before the dialog goes. Removing it focused fires its
     blur inside the removal, its blur redrew the dialog, and that redraw removed the same
     node again: "Failed to execute 'removeChild'" on every Create pressed with Enter. */
  function closeModal() {
    var host = document.getElementById('modal'), focused = document.activeElement;
    for (var n = focused; n && host; n = n.parentNode) {
      if (n === host) { if (focused.blur) focused.blur(); break; }
    }
    App.modal = null;
    renderModal();
  }
  function redrawOnBlur() { if (App.modal) renderModal(); }

  /* ---------- Split: the big card ----------
   * `kb split <id> --slice "title|brief[|after-title]"` cuts one card into children and
   * turns it into a tracking card. The dialog is that verb and nothing more: a list of
   * slices, each with a title, a brief and an optional sibling to wait for. The board
   * resolves `after` by TITLE against the slices already created in the same call, so the
   * picker only ever offers the slices ABOVE this one, which is also what keeps the order
   * a chain rather than a knot. A `|` in a title or a brief would split the argument in
   * two, so it is refused here rather than mangled there. A slice's `repo` is null while it
   * takes every repo the card names, else the ones left chosen (c-771). */
  var SLICE = { title: '', brief: '', after: '', repo: null };
  function openSplit(card) {
    App.modal = { mode: 'split', id: card.id, space: card.space, title: card.title,
      repos: String(card.repo || '').split(',').map(function (r) { return r.trim(); }).filter(Boolean),
      slices: [Object.assign({}, SLICE), Object.assign({}, SLICE)], values: {}, base: {}, inferred: {} };
    renderModal();
    var first = document.querySelector('.modal [data-fk="s:0:title"]');
    if (first) first.focus();
  }
  function sliceField(index, key, placeholder) {
    var s = App.modal.slices[index];
    return el('input', { type: 'text', 'data-fk': 's:' + index + ':' + key, value: s[key], placeholder: placeholder,
      oninput: function (ev) { s[key] = ev.target.value; },
      onblur: redrawOnBlur });
  }
  function afterPicker(index) {
    var s = App.modal.slices[index];
    var earlier = App.modal.slices.slice(0, index).filter(function (o) { return o.title.trim(); });
    if (!earlier.length) return el('span', { class: 'fhelp', text: 'starts on its own' });
    return el('select', { 'data-fk': 's:' + index + ':after', onchange: function (ev) { s.after = ev.target.value; renderModal(); } },
      [el('option', { value: '', text: 'starts on its own', selected: s.after ? null : true })].concat(earlier.map(function (o) {
        return el('option', { value: o.title, text: 'after ' + o.title, selected: o.title === s.after ? true : null });
      })));
  }
  /* c-718: in a space whose pack stacks, a slice that waits for another is STACKED on it
     (cut from its branch, its change aimed there, starting once that branch is pushed) or
     INDEPENDENT (cut from the base, starting at once). Stacked is offered first: a slice is
     made to wait because it needs the other's work. The answer rides on the slice
     (`|stack=`), so it has it from the start. */
  function stackPicker(index) {
    var s = App.modal.slices[index];
    if (!s.after || !spaceOf(App.modal.space).stacks) return null;
    var value = s.stack || 'stacked';
    return el('select', { 'data-fk': 's:' + index + ':stack', 'aria-label': 'stacked or independent',
      onchange: function (ev) { s.stack = ev.target.value; } },
      [['stacked', 'stacked on it'], ['independent', 'independent']].map(function (o) {
        return el('option', { value: o[0], text: o[1], selected: o[0] === value ? true : null });
      }));
  }
  /* c-771: a card that names several repos offers them per slice, all chosen to start with,
     so a slice that needs fewer says so here and is never held for a worktree in a repo it
     does not touch. The last one cannot be taken off: a slice of a repo card is a repo card.
     The choice rides on the slice (`|repo=`); a slice left with all of them sends none and
     inherits, as before. */
  function repoPicker(index) {
    var m = App.modal, s = m.slices[index];
    if (m.repos.length < 2) return null;
    var cur = s.repo ? s.repo.slice() : m.repos.slice();
    return el('div', { class: 'chips', 'aria-label': 'the repos this slice works in' }, m.repos.map(function (o) {
      return el('button', { type: 'button', class: 'chip' + (cur.indexOf(o) >= 0 ? ' on' : ''),
        'data-fk': 's:' + index + ':repo:' + o, onclick: function () {
          var i = cur.indexOf(o);
          if (i >= 0 && cur.length === 1) return;
          if (i >= 0) cur.splice(i, 1); else cur.push(o);
          s.repo = cur.length === m.repos.length ? null : cur.slice();
          renderModal();
        } }, o);
    }));
  }
  function sliceRow(index) {
    var m = App.modal;
    return el('div', { class: 'splitrow' },
      el('span', { class: 'n mono t11 ink2', text: String(index + 1) }),
      sliceField(index, 'title', 'what this slice is'),
      sliceField(index, 'brief', 'the detail its house starts from'),
      afterPicker(index),
      stackPicker(index),
      repoPicker(index),
      el('button', { class: 'iconbtn', title: 'drop this slice', 'aria-label': 'drop this slice',
        onclick: function () {
          var gone = m.slices.splice(index, 1)[0];
          m.slices.forEach(function (o) { if (o.after === gone.title) o.after = ''; });
          if (!m.slices.length) m.slices.push(Object.assign({}, SLICE));
          renderModal();
        } }, '✕'));
  }
  function splitBody() {
    var m = App.modal, filled = m.slices.filter(function (s) { return s.title.trim(); });
    return [
      el('div', { class: 'ink2', text: 'Cutting ' + m.id + ', "' + m.title + '", into slices. Each slice becomes a '
        + 'child card at assigned, carrying this card\'s space, repo, model, autonomy and topic'
        + (m.repos.length > 1 ? ' (a slice that needs fewer of its repos keeps only those chosen on its row). ' : '. ') + m.id
        + ' becomes a tracking card: its stage follows its slices and it has no gate of its own.' }),
      el('div', { class: 'splitrows' }, m.slices.map(function (s, i) { return sliceRow(i); })),
      el('div', { class: 'actions' },
        el('button', { class: 'btn', onclick: function () { m.slices.push(Object.assign({}, SLICE)); renderModal(); } }, 'Add a slice'),
        el('span', { class: 'fhelp', text: filled.length + ' slice' + (filled.length === 1 ? '' : 's') + ' so far' }))
    ];
  }
  function submitSplit(ev) {
    var m = App.modal, slices = [], bad = null;
    m.slices.forEach(function (s) {
      var title = s.title.trim(), brief = s.brief.trim();
      if (!title) return;
      if (title.indexOf('|') >= 0 || brief.indexOf('|') >= 0) { bad = title; return; }
      var piece = { title: title, brief: brief };
      if (s.after) piece.after = s.after;
      if (s.after && spaceOf(m.space).stacks) piece.stack = s.stack || 'stacked';
      if (s.repo && s.repo.length < m.repos.length) {
        piece.repo = m.repos.filter(function (r) { return s.repo.indexOf(r) >= 0; });
      }
      slices.push(piece);
    });
    if (bad) { K.toast('a slice cannot carry a | in its title or brief: ' + bad, true); return; }
    if (!slices.length) { K.toast('a split needs at least one slice with a title', true); return; }
    var titles = slices.map(function (s) { return s.title; });
    if (titles.some(function (t, i) { return titles.indexOf(t) !== i; })) {
      K.toast('two slices share a title, so `after` could not tell them apart', true); return;
    }
    /* the dialog stays up until the answer lands: its Split button is where the wait is
       shown, and a refusal leaves the slices still typed */
    K.act({ verb: 'split', id: m.id, slices: slices }, function () { closeModal(); },
      ev && ev.currentTarget);
  }
  K.openModal = openModal; K.closeModal = closeModal; K.openSplit = openSplit;

  /* ---------- the controls ---------- */
  function setValue(key, value, rerender) {
    App.modal.values[key] = value;
    if (rerender) renderModal();
  }
  function control(f, v) {
    var value = v[f.key];
    /* a fact the form says, not a value it sends (c-645's "Worker: a house") */
    if (f.type === 'fact') return el('span', { class: 'ffact', 'data-fk': 'f:' + f.key, text: f.fact(v) });
    if (f.type === 'select') {
      var opts = (f.options || []).slice();
      if ((f.custom || f.typed) && value && opts.indexOf(value) < 0) opts.push(value);
      /* c-732: a `typed` select (the space's Base branch, `bases.row`) takes a value its list
         does not name: "Another branch..." turns it into a box to type in, and "Pick from the
         list" turns it back. A pack's `custom` select is drawn as it always was (r1.F2). */
      if (f.typed && (App.modal.typing || {})[f.key]) return customBox(f, value);
      return el('select', { 'data-fk': 'f:' + f.key, onchange: function (ev) {
        if (ev.target.value === OTHER) { typing(f.key, true); setValue(f.key, '', true); return; }
        setValue(f.key, ev.target.value, true);
      } },
        opts.map(function (o) {
          return el('option', { value: o, text: o === '' ? (f.blank || '(default)') : o, selected: String(o) === String(value === undefined || value === null ? '' : value) ? true : null });
        }).concat(f.typed ? [el('option', { value: OTHER, text: f.key === 'base' ? 'Another branch...' : 'Another...' })] : []));
    }
    /* a card picker: the ids are the board's, so the option's label carries the title and
       the value stays the bare id the verb takes */
    if (f.type === 'cardref') {
      var picks = (f.choices ? f.choices(v) : []) || [];
      return el('select', { 'data-fk': 'f:' + f.key, onchange: function (ev) { setValue(f.key, ev.target.value, true); } },
        [el('option', { value: '', text: '(none)', selected: value ? null : true })].concat(picks.map(function (p) {
          return el('option', { value: p.value, text: p.label, selected: String(p.value) === String(value) ? true : null });
        })));
    }
    if (f.type === 'multiselect') {
      var cur = Array.isArray(value) ? value.slice() : (value ? String(value).split(',') : []);
      return el('div', { class: 'chips' }, (f.options || []).map(function (o) {
        return el('button', { type: 'button', class: 'chip' + (cur.indexOf(o) >= 0 ? ' on' : ''), onclick: function () {
          var i = cur.indexOf(o);
          if (i >= 0) cur.splice(i, 1); else cur.push(o);
          setValue(f.key, cur.slice(), true);
        } }, o);
      }));
    }
    if (f.type === 'textarea') {
      return el('textarea', { 'data-fk': 'f:' + f.key, value: value || '', placeholder: f.placeholder || '',
        oninput: function (ev) { App.modal.values[f.key] = ev.target.value; } });
    }
    if (f.type === 'story') {
      return el('input', { type: 'text', 'data-fk': 'f:' + f.key, value: value || '', placeholder: f.placeholder || '',
        oninput: function (ev) { App.modal.values[f.key] = ev.target.value; },
        onblur: function (ev) { if (App.modal) setValue(f.key, normaliseRef(f.normalise, ev.target.value), true); } });
    }
    return el('input', { type: 'text', 'data-fk': 'f:' + f.key, value: value || '', placeholder: f.placeholder || '',
      oninput: function (ev) {
        App.modal.values[f.key] = ev.target.value;
        if (f.key === 'title' || f.key === 'new_project') infer();
      },
      onblur: redrawOnBlur });
  }
  var OTHER = '\u0000other';
  function typing(key, on) { App.modal.typing = App.modal.typing || {}; App.modal.typing[key] = on; }
  function customBox(f, value) {
    return el('span', { class: 'fcustom' },
      el('input', { type: 'text', 'data-fk': 'f:' + f.key, value: value || '', placeholder: f.key === 'base' ? 'a branch name' : '',
        'aria-label': f.label, oninput: function (ev) { App.modal.values[f.key] = ev.target.value; } }),
      el('button', { type: 'button', class: 'btn sm', onclick: function () {
        typing(f.key, false);
        setValue(f.key, (f.options || [])[0] || '', true);
      } }, 'Pick from the list'));
  }
  function checkbox(f, v) {
    var on = v[f.key] === true;
    return el('label', { class: 'check' + (on ? ' on' : ''), title: f.help || '' },
      el('input', { type: 'checkbox', 'data-fk': 'f:' + f.key, checked: on ? true : null,
        onchange: function (ev) { setValue(f.key, ev.target.checked, true); } }),
      el('span', { text: f.label }));
  }
  /* c-631: a field that depends on something not set up says so under itself, in the
     panel's own words, and stays usable: a card with no repo is a real errand, and a
     ticket ref can be typed before the tracker is turned on. An empty repo list draws the
     line in place of its empty chip row. */
  function fieldNeeds(f) {
    var space = App.modal ? App.modal.space : App.space;
    if (f.type === 'multiselect' && f.key === 'repo' && !(f.options || []).length) return K.needs('repos', space, { line: true });
    if (f.type === 'story') return K.needs('tracker', space, { line: true });
    return null;
  }
  function field(f, v) {
    if (f.type === 'checkbox') return checkbox(f, v);
    var need = fieldNeeds(f), bare = f.type === 'multiselect' && !(f.options || []).length;
    return el('label', { class: 'field' + (f.wide || f.type === 'textarea' || f.type === 'multiselect' ? ' wide' : '') },
      el('span', { class: 'flabel', text: f.label }),
      need && bare ? null : control(f, v),
      need,
      f.help ? el('span', { class: 'fhelp', text: typeof f.help === 'function' ? f.help(v) : f.help }) : null);
  }

  /* The fields keep the schema's order (the retired modal's order); a run of checkboxes
     becomes one row of toggles where that run sits, so the form reads as it used to. */
  function formRows(fields, v) {
    var rows = [], run = null;
    fields.forEach(function (f) {
      if (f.type === 'checkbox') {
        if (!run) { run = el('div', { class: 'checks' }); rows.push(run); }
        add(run, checkbox(f, v));
        return;
      }
      run = null;
      rows.push(field(f, v));
    });
    return rows;
  }

  /* ---------- the bodies the page sends ---------- */
  function commaJoin(value) { return Array.isArray(value) ? value.join(',') : value; }
  function createBody(v, fields, start) {
    var body = { verb: 'create', space: App.modal.space, start: !!start, options: {} };
    fields.forEach(function (f) {
      var value = f.emit ? f.emit(v[f.key]) : v[f.key];
      if (value === undefined || value === null || value === '') return;
      if (Array.isArray(value) && !value.length) return;
      if (f.stored === 'card') body[f.key] = value; else body.options[f.key] = value;
    });
    return body;
  }
  function setBody(v, fields) {
    /* `kb set` takes one `field=value` per change; a list is a comma string there, not JSON */
    var fieldsOut = {};
    fields.forEach(function (f) {
      var value = v[f.key], was = (App.modal.base || {})[f.key];
      if (Array.isArray(value) && Array.isArray(was) && value.join(',') === was.join(',')) return;
      if (!Array.isArray(value) && value === was) return;
      if (value === undefined) return;
      if (f.stored === 'card') fieldsOut[f.key] = value === '' ? null : commaJoin(value);
      else fieldsOut['options.' + f.key] = Array.isArray(value) ? value.join(',') : value;
    });
    return { verb: 'set', id: App.modal.id, fields: fieldsOut };
  }
  function submit(start, from) {
    var v = values(), fields = visibleFields(v);
    if (App.modal.mode === 'edit') {
      var body = setBody(v, fields);
      if (!Object.keys(body.fields).length) { closeModal(); return; }
      K.act(body, function () { closeModal(); }, from);
      return;
    }
    if (!v.title) { K.toast('a card needs a title', true); return; }
    K.act(createBody(v, fields, start), function () { closeModal(); }, from);
  }

  /* ---------- the dialog ---------- */
  /* MORPHED, not rebuilt. `repaint` redraws the dialog the moment something goes in
     flight, and the form is a dozen fields he may be part way through; the morph is what
     leaves the caret and the half-typed value exactly where they were. */
  function renderModal() {
    if (!App.modal) { K.paint('modal', null); return; }
    var m = App.modal, split = m.mode === 'split';
    var v = split ? {} : values(), fields = split ? [] : visibleFields(v);
    var card = el('div', { class: 'modal-card', role: 'dialog', 'aria-modal': 'true',
      'data-key': 'modal-' + m.mode + '-' + (m.id || 'new'),
      onclick: function (ev) { ev.stopPropagation(); },
      onkeydown: function (ev) {
        if (ev.key === 'Enter' && !ev.shiftKey && ev.target.tagName !== 'TEXTAREA' && ev.target.tagName !== 'BUTTON') {
          ev.preventDefault();
          if (split) submitSplit(ev); else submit(false, ev.currentTarget);
        }
      } },
      el('div', { class: 'modal-head' },
        el('h3', { class: 'title', text: split ? 'Split ' + m.id : m.mode === 'edit' ? 'Edit ' + m.id : 'New card' }),
        el('span', { class: 'spacer' }),
        el('span', { class: 'mono t11 ink2', text: m.space }),
        el('button', { class: 'iconbtn', title: 'close', 'aria-label': 'close', onclick: closeModal }, '✕')),
      el('div', { class: 'modal-body' }, split ? splitBody() : el('div', { class: 'form' }, formRows(fields, v))),
      el('div', { class: 'modal-foot' },
        el('button', { class: 'btn', onclick: closeModal }, 'Cancel'),
        el('span', { class: 'spacer' }),
        split
          ? K.faceBtn('Split into slices', { verb: 'split', id: m.id }, 'primary', submitSplit)
          : m.mode === 'edit'
            ? K.faceBtn('Save', { verb: 'set', id: m.id }, 'primary',
                function (ev) { submit(false, ev.currentTarget); })
            : [K.faceBtn('Create, file to inbox', { verb: 'create' }, '',
                 function (ev) { submit(false, ev.currentTarget); }),
               K.faceBtn('Create and start', { verb: 'create' }, 'primary',
                 function (ev) { submit(true, ev.currentTarget); })]));
    K.paint('modal', el('div', { class: 'modal', onclick: closeModal }, card));
  }
  K.renderModal = renderModal;
})(window.Keel);
