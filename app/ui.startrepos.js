/* Add your repos, the first run's step 4 (c-678), loaded before `ui.start.js`, which reads
 * it as `K.reposScreen(report, step, parts)`.
 *
 * - ONE SPACE FOR THE USER'S CODE. The space the repos go in is named at the top, `work`
 *   unless the user types another, and it is fixed once the first repo is in (decision
 *   `space`: personal keeps the builder's own cards). Where the install already has a space
 *   beside personal, that one is the space and its name is not asked.
 * - SEVERAL REPOS. Every repo is a panel of its own with its state (ready, copying, needs
 *   you), its address and Remove; Add another repo is always there, and its fields clear
 *   after each add so the next address can go in. Adds are sent one at a time, in the order
 *   they were made (the server runs one setup change at a time and restarts after each), so
 *   a second address typed while the first copies waits its turn in the list.
 * - CONNECT GITHUB. A private copy GitHub refused has Connect GitHub where the GitHub
 *   connection is offered: its requirement rows open in the panel, each with the fix its
 *   pack wrote, then Check again and Try the copy again.
 * - A COPY THAT FAILED stays in the list as a panel that needs you: the server's sentence
 *   for its kind (keel/cloneerrors.py), git's own line as it came, and the kind's fix: the
 *   https address in one tap for an SSH address with no key, Edit the address where there
 *   is no such repo, Try the copy again for the rest. A failed copy left nothing behind on
 *   the server, so the panel is this page's alone and a reload drops it.
 * - THE CHOICE AT THE TOP (c-729): Copy a repo (its URL, or the path of a folder on this
 *   computer, which the address field says it takes; `~` is read as the home folder) or Use a
 *   folder in place, Setup's Attach with what it costs. One is chosen at a time
 *   (`K.startChoice`), and only its form is drawn.
 *
 * The verb is `setup.repo.add` {space, url, key}: the space made when it is not there, the
 * repo copied into the install's layout (keel/onboarding.py). */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el, App = K.App;
  var named = { space: 'work' };      /* the space name typed, until the first repo is in */
  var form = { url: '', key: '', typed: false };
  var queue = [];                     /* adds this page made: {n, space, url, key, state, failure} */
  var count = 0;

  var STYLE = [
    '.repo-card{border:1px solid var(--hair-hi);background:var(--s1);padding:12px;display:flex;flex-direction:column;gap:8px;min-width:0}',
    '.repo-card.needs{border-color:var(--warn)}',
    '.repo-connect{display:flex;flex-direction:column;gap:8px;border-top:1px solid var(--hair);padding-top:8px;min-width:0}',
    '.repo-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}',
    '.repo-name{font-family:var(--mono);font-size:13px;font-weight:600}',
    '.repo-pill{font-family:var(--mono);font-size:10px;border:1px solid var(--hair-hi);border-radius:var(--pill);padding:2px 8px;color:var(--ink-3)}',
    '.repo-pill.ready{color:var(--good);border-color:var(--good)}.repo-pill.copying{color:var(--accent-ink);border-color:var(--accent)}',
    '.repo-pill.needs{color:var(--warn);border-color:var(--warn)}',
    '.repo-addr{font-family:var(--mono);font-size:11px;color:var(--ink-3);overflow-wrap:anywhere}',
    '.repo-said{font-size:12px;color:var(--ink-2)}',
    '.repo-git{font-family:var(--mono);font-size:12px;padding:8px 10px;background:var(--canvas);border:1px solid var(--hair);overflow-wrap:anywhere;white-space:pre-wrap;margin:0}',
    '.repo-add{border:1px solid var(--accent);background:var(--s1);padding:12px;display:flex;flex-direction:column;gap:10px}',
    '.repo-add h3,.repo-list h3{margin:0;font-size:15px}',
    '.repo-list{display:flex;flex-direction:column;gap:8px}',
    '.repo-field{display:flex;flex-direction:column;gap:4px}',
    '.repo-field input{width:100%}',
    '.repo-hint{font-size:11px;color:var(--ink-2)}',
    '.repo-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}',
    '@media (max-width:899px){.repo-card .btn,.repo-add .btn,.repo-add input,.repo-field input{min-height:44px}}'
  ].join('\n');

  function styleOnce() {
    if (document.getElementById('startrepos-style')) return;
    var node = document.createElement('style');
    node.id = 'startrepos-style';
    node.textContent = STYLE;
    document.head.appendChild(node);
  }

  /* the key an address suggests, as the server would fill it (cloneerrors.short_name) */
  function shortName(url) {
    var last = String(url || '').trim().replace(/\/+$/, '').split(/[\/:]/).pop() || '';
    var name = last.replace(/\.git$/i, '').toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^[-_]+|[-_]+$/g, '').slice(0, 32);
    return !name || /^[a-z]/.test(name) ? name : ('r' + name).slice(0, 32);
  }
  /* the install's own repos (K.OWN_REPOS): not cloned by Setup, and at <install>/<key> */
  function ownRepo(r) {
    return K.ownRepo(r.key) && !r.cloned && String(r.path || '').replace(/\/+$/, '').split('/').pop() === r.key;
  }
  function mine(report, name) { return report.spaces[name].repos.filter(function (r) { return !ownRepo(r); }); }
  /* The space the user's repos go in: the install's space beside personal where it has one
     (the one the address shows first), else the name typed, which Add makes. */
  function target(report) {
    var names = Object.keys(report.spaces).filter(function (n) { return n !== 'personal' && report.spaces[n].writable; });
    var at = names.indexOf(App.space) >= 0 ? App.space : names[0];
    if (at) return { name: at, made: true, fixed: mine(report, at).length > 0 || queue.some(function (q) { return q.space === at; }) };
    return { name: (named.space || '').trim(), made: false, fixed: queue.length > 0 };
  }

  /* ---------- the adds this page made ---------- */

  function failureOf(sent) {
    var found = (K.refusal && K.refusal('setup.repo.add')) || {};
    var d = found.detail || {};
    return { kind: d.kind || 'refused', sentence: d.sentence || K.asSentence(found.error || 'the copy was refused'),
      git: d.git || '', https: d.https || null, needs: d.needs || null, url: sent.url };
  }
  /* one at a time, and only once the report is back: after each add the deck reads its config
     again, and the next is sent to what it read */
  function pump(report) {
    if (!report || queue.some(function (q) { return q.state === 'copying'; })) return;
    var next = queue.filter(function (q) { return q.state === 'queued'; })[0];
    if (!next) return;
    next.state = 'copying';
    var body = { verb: 'setup.repo.add', space: next.space, url: next.url };
    if (next.key) body.key = next.key;
    K.setupParts.change(body, (next.key || 'the repo') + ' copied', 'adding-' + next.n).then(function (r) {
      /* c-729: a copy that went through stays on the list as copied until the report that
         lists it lands, so the row never drops out and comes back */
      if (r) next.state = 'landed';
      else { next.state = 'failed'; next.failure = failureOf(next); }
      if (K.renderBody) K.renderBody();
    });
  }
  function add(space, url, key) {
    count += 1;
    queue.push({ n: count, space: space, url: url, key: key, state: 'queued', failure: null });
    if (K.renderBody) K.renderBody();
  }
  function drop(q) { queue.splice(queue.indexOf(q), 1); if (K.renderBody) K.renderBody(); }
  function again(q, url) { q.url = url || q.url; q.state = 'queued'; q.failure = null; if (K.renderBody) K.renderBody(); }

  /* ---------- one repo, one panel ---------- */

  function pill(state) { return el('span', { class: 'repo-pill ' + state, text: state === 'needs' ? 'needs you' : state }); }
  function card(key, name, state, address, button, body) {
    return el('div', { class: 'repo-card' + (state === 'needs' ? ' needs' : ''), 'data-key': key, 'data-state': state },
      el('div', { class: 'repo-head' }, el('span', { class: 'repo-name', text: name }), pill(state), el('span', { class: 'spacer' }), button),
      el('div', { class: 'repo-addr', text: address }), body);
  }
  function removeButton(space, r) {
    return el('button', { class: 'btn sm', onclick: function () {
      if (window.confirm('Take ' + r.key + ' off ' + space + '? Only the config entry goes: its folder stays where it is.'))
        K.setupParts.change({ verb: 'setup.repo.remove', space: space, key: r.key });
    } }, 'Remove');
  }
  /* a repo the install lists: ready in one line, or the check that does not hold */
  function listed(space, r) {
    var key = 'repo-' + space + '/' + r.key, address = r.origin || r.path;
    if (!r.ok) return card(key, r.key, 'needs', address, removeButton(space, r),
      K.check({ key: 'copied-' + r.key, state: 'needs', name: 'Copied', what: 'The folder this repo was copied into is gone: ' + r.path + '.',
        fix: 'Remove it here, then add its address again.' }));
    if (!r.cloned) return card(key, r.key, 'ready', r.path, removeButton(space, r),
      el('div', { class: 'repo-said', text: 'A folder you already have, used where it is.' + (r.branch ? ' The ' + r.branch + ' branch is out.' : '') }));
    if (r.origin && r.branch) return card(key, r.key, 'ready', address, removeButton(space, r),
      el('div', { class: 'repo-said', text: 'Copied. It has a home address, and the ' + r.branch + ' branch is out.' }));
    return card(key, r.key, 'needs', address, removeButton(space, r), [
      K.check({ key: 'copied-' + r.key, state: 'ready', name: 'Copied', says: 'Done' }),
      K.check({ key: 'home-' + r.key, state: r.origin ? 'ready' : 'needs', name: 'Has a home address', says: r.origin || '',
        how: r.origin ? 'The remote Shipyard will fetch from and push to.' : null,
        what: 'This copy has no home address, so Shipyard cannot fetch what your team has or push to it.',
        fix: 'Remove it here, then add it again by its address.' }),
      K.check({ key: 'main-' + r.key, state: r.branch ? 'ready' : 'needs', name: 'Main branch', says: r.branch || '',
        how: r.branch ? 'The branch the copy has out.' : null,
        what: 'This copy has no branch out, so there is nothing for finished work to land on.',
        fix: 'Ask Bosun in its session to look at this copy.' })]);
  }
  /* Connect GitHub (c-678): a private copy that GitHub refused opens the GitHub connection's
     own requirement rows right here, as the Where finished work goes step draws them (the
     pack's checks on the Setup report, each with the fix the pack wrote, `K.fixOf`): a row
     per check, Check again, which reads the report again, and Try the copy again. Opening
     it turns nothing on: signing this computer in is what the copy needed. */
  var GITHUB = 'github';
  var connecting = {};      /* the adds whose Connect GitHub is open, by their number */
  var shown = null;         /* the Setup report this screen was last drawn from */
  function githubPack() {
    return ((shown || {}).packs || []).filter(function (p) { return p.name === GITHUB; })[0] || null;
  }
  function connectPanel(q, pack) {
    return el('div', { class: 'repo-connect', 'data-key': 'connect-' + q.n },
      pack.checks.map(function (c) {
        return el('div', { 'data-key': 'connect-check', 'data-name': c.name, 'data-state': c.ok ? 'ready' : 'needs' },
          c.ok ? K.check({ key: 'gh-' + c.name, state: 'ready', name: c.name })
            : K.check({ key: 'gh-' + c.name, state: 'needs', name: c.name, what: K.setupParts.notSetUp(c), fix: K.fixOf(c), ask: false }));
      }),
      el('div', { class: 'repo-row' },
        el('button', { class: 'btn', onclick: function () { K.setupParts.again(); } }, 'Check again'),
        el('button', { class: 'btn primary', onclick: function () { delete connecting[q.n]; again(q); } }, 'Try the copy again')));
  }
  var FIXES = {
    private: function (q) {
      if (!githubPack() || connecting[q.n]) return null;
      return el('button', { class: 'btn primary', onclick: function () { connecting[q.n] = true; K.renderBody(); } }, 'Connect GitHub');
    },
    ssh: function (q) {
      return q.failure.https ? el('button', { class: 'btn primary', onclick: function () { again(q, q.failure.https); } }, 'Use the https address') : null;
    },
    /* a host this computer has never met over SSH: the same one-tap way round it */
    hostkey: function (q) { return FIXES.ssh(q); },
    nosuch: function (q) {
      return el('button', { class: 'btn', onclick: function () { form.url = q.url; form.key = q.key || ''; form.typed = !!q.key; drop(q); } }, 'Edit the address');
    }
  };
  function fixOf(q) {
    var special = (FIXES[q.failure.kind] || function () { return null; })(q);
    var pack = q.failure.kind === 'private' && connecting[q.n] ? githubPack() : null;
    var said = [q.failure.git ? el('pre', { class: 'repo-git', 'data-key': 'repo-git', text: q.failure.git }) : null,
      q.failure.needs ? el('div', { class: 'repo-said', text: q.failure.needs }) : null];
    if (pack) return said.concat([connectPanel(q, pack)]);
    return [said,
      el('div', { class: 'repo-row' }, special,
        q.failure.kind === 'nosuch' ? null : el('button', { class: 'btn' + (special ? '' : ' primary'), onclick: function () { again(q); } },
          q.failure.kind === 'ssh' || q.failure.kind === 'hostkey' ? 'Try this address again' : 'Try the copy again'))];
  }
  /* an add this page made: waiting its turn, copying, or failed */
  function adding(q) {
    var key = 'adding-' + q.n, name = q.key || shortName(q.url) || 'new repo';
    var forget = el('button', { class: 'btn sm', onclick: function () { drop(q); } }, 'Remove');
    if (q.state === 'failed') return card(key, name, 'needs', q.url, forget, [
      K.check({ key: 'copied-' + q.n, state: 'needs', name: 'Copied', what: q.failure.sentence, fix: fixOf(q),
        how: 'The copy runs again when you press the button, and the three checks turn green by themselves.' }),
      K.check({ key: 'home-' + q.n, state: 'waiting', name: 'Has a home address' }),
      K.check({ key: 'main-' + q.n, state: 'waiting', name: 'Main branch' })]);
    var copying = q.state === 'copying', landed = q.state === 'landed';
    return card(key, name, 'copying', q.url, copying || landed ? null : forget, [
      K.check({ key: 'copied-' + q.n, state: landed ? 'ready' : copying ? 'checking' : 'waiting', name: 'Copied',
        says: landed ? 'Done' : copying ? 'Copying, large repos take a minute' : 'Waiting for the copy before it' }),
      K.check({ key: 'home-' + q.n, state: 'waiting', name: 'Has a home address' }),
      K.check({ key: 'main-' + q.n, state: 'waiting', name: 'Main branch' })]);
  }

  /* ---------- the form ---------- */

  function spaceField(t) {
    return el('label', { class: 'repo-field', 'data-key': 'repo-space' }, el('span', { class: 'label', text: 'Space name' }),
      el('input', { type: 'text', 'data-fk': 'start-space', value: t.name, 'aria-label': 'Space name', disabled: t.made || t.fixed ? true : null,
        autocomplete: 'off', oninput: function (ev) { named.space = ev.target.value; } }),
      t.fixed ? el('span', { class: 'repo-hint', text: 'Fixed once the first repo is in.' }) : null);
  }
  function send(t) {
    var url = form.url.trim(), key = (form.key || '').trim() || shortName(url);
    if (!url) { K.toast('a repo needs its address', true); return; }
    if (!t.name) { K.toast('the space needs a name', true); return; }
    add(t.name, url, key);
    form = { url: '', key: '', typed: false };
  }
  function addForm(t, any) {
    return el('div', { class: 'repo-add', 'data-key': 'repo-add' },
      el('h3', { text: any ? 'Add another repo' : 'Add a repo' }),
      el('label', { class: 'repo-field' }, el('span', { class: 'label', text: 'Repo address or folder' }),
        el('input', { type: 'text', 'data-fk': 'start-repo-url', value: form.url, 'aria-label': 'Repo address or folder', autocomplete: 'off',
          inputmode: 'url', placeholder: 'https://github.com/you/project or ~/code/project',
          oninput: function (ev) { form.url = ev.target.value; if (!form.typed) { form.key = shortName(form.url); if (K.renderBody) K.renderBody(); } } }),
        el('span', { class: 'repo-hint', text: 'The URL you would give to git clone, or the path of a folder on this computer. Either way Shipyard copies it.' })),
      el('label', { class: 'repo-field' }, el('span', { class: 'label', text: 'Short name' }),
        el('input', { type: 'text', 'data-fk': 'start-repo-key', value: form.key, 'aria-label': 'Short name', autocomplete: 'off',
          placeholder: 'filled from the address', oninput: function (ev) { form.key = ev.target.value; form.typed = !!ev.target.value; } })),
      el('div', { class: 'repo-row' }, el('button', { class: 'btn primary', onclick: function () { send(t); } }, 'Add repo')));
  }
  /* Attach makes the space too when it is not there yet, as Add does */
  function attach(report, t) {
    if (!t.name) return null;
    return el('div', { class: 'repo-add', 'data-key': 'repo-attach' },
      el('h3', { text: 'Use a folder you already have' }),
      el('p', { class: 'repo-said', text: 'Shipyard will work in that folder and merge finished work into its main branch. If you also work there, a landing is refused ' +
        'while you have uncommitted changes. A copy is safer.' }),
      K.setupParts.attachForm(t.name));
  }
  /* THE CHOICE AT THE TOP (c-729): a copy (from an address or a folder's path) or the folder
     itself, in place; the stranger run found "Use a folder" folded under the form */
  var how = 'copy';
  function choice() {
    return K.startChoice ? K.startChoice({ key: 'repo-how', label: 'How to add a repo', chosen: how,
      pick: function (id) { how = id; if (K.renderBody) K.renderBody(); },
      options: [{ id: 'copy', title: 'Copy a repo', said: 'From its URL, or from a folder on this computer. Shipyard works in its own copy, so your folder is never touched.' },
                { id: 'folder', title: 'Use a folder in place', said: 'Shipyard works in a folder you already have, and merges finished work into it.' }] }) : null;
  }

  K.reposScreen = function (report) {
    styleOnce();
    shown = report;
    var t = target(report);
    pump(report);
    var rows = [], keys = {};
    Object.keys(report.spaces).forEach(function (name) {
      mine(report, name).forEach(function (r) { keys[name + '/' + r.key] = true; rows.push(listed(name, r)); });
    });
    /* a copy that landed leaves the page's list once the report lists it */
    queue = queue.filter(function (q) { return q.state !== 'landed' || !keys[q.space + '/' + q.key]; });
    queue.forEach(function (q) { rows.push(adding(q)); });
    return [
      spaceField(t),
      choice(),
      how === 'folder' ? attach(report, t) : addForm(t, rows.length > 0),
      el('div', { class: 'repo-list', 'data-key': 'repo-list' },
        el('h3', { 'data-key': 'repo-count', text: 'Your repos (' + rows.length + ')' }),
        rows.length ? rows : el('div', { class: 'start-about', text: 'No repos yet. Add the first one above.' }))];
  };
})(window.Keel);
