/* How Keel remembers, the first run's step 5 (c-678), loaded before `ui.start.js`, which
 * reads it as `K.memoryScreen(report, step, parts)`.
 *
 * A read-only page: one picture of the four layers every session reads, top to bottom, with
 * "then" between them, and for each what it is for, where it lives, who writes it and who
 * may change it. Nothing on it is a decision, so it has no button and sends nothing; the
 * step has no Skip and its Next is always on (keel/firstrun.py: nothing to check).
 *
 * The paths are the install's real ones (`start.memory` on `/api/setup`): each space's file
 * and each cloned repo's (keel/repolayout.py), Keel's house contract, and Bosun's memory,
 * which lives with the code Keel runs. The workspace layer is drawn dashed while no space
 * has more than one repo, since it applies only then. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el;

  var STYLE = [
    '.mem{display:flex;flex-direction:column;gap:8px}',
    '.mem-layer{display:grid;grid-template-columns:24px minmax(0,1fr);gap:12px;border:1px solid var(--hair-hi);background:var(--s1);padding:12px;font-size:13px;line-height:1.5}',
    '.mem-layer.off{border-style:dashed}.mem-layer.off h3,.mem-layer.off .mem-num{color:var(--ink-3)}',
    '.mem-num{font-family:var(--mono);font-size:15px;font-weight:600;color:var(--accent-ink)}',
    '.mem-layer h3{margin:0 0 4px;font-size:15px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}',
    '.mem-tag{font-family:var(--mono);font-size:10px;font-weight:400;color:var(--ink-3);border:1px solid var(--hair-hi);border-radius:var(--pill);padding:2px 8px}',
    '.mem-layer p{margin:0}',
    '.mem-facts{display:grid;grid-template-columns:120px minmax(0,1fr);gap:4px 12px;margin:8px 0 0;align-items:baseline}',
    '.mem-facts dt,.mem-facts dd{margin:0}.mem-facts dd{overflow-wrap:anywhere}',
    '.mem-path{font-family:var(--mono);font-size:12px;display:block}',
    '.mem-then{text-align:center;font-family:var(--mono);font-size:11px;color:var(--ink-3)}',
    '.mem-under{border:1px solid var(--accent);background:var(--accent-soft);padding:12px;font-size:13px;line-height:1.5;display:flex;flex-direction:column;gap:8px}',
    '.mem-under p{margin:0}',
    '@media (max-width:899px){.mem-facts{grid-template-columns:minmax(0,1fr)}.mem-facts dd{margin-bottom:8px}.mem-layer{grid-template-columns:20px minmax(0,1fr);gap:8px}}'
  ].join('\n');

  function styleOnce() {
    if (document.getElementById('startmemory-style')) return;
    var node = document.createElement('style');
    node.id = 'startmemory-style';
    node.textContent = STYLE;
    document.head.appendChild(node);
  }

  var YOU = 'You. Bosun can only propose a change, and you press Adopt.';
  function paths(list) { return list.map(function (p) { return el('span', { class: 'mem-path', text: p }); }); }
  /* one layer: its number, its name, what it is for, then the three facts */
  function layer(n, title, tag, meaning, where, writes, changes, off) {
    return el('div', { class: 'mem-layer' + (off ? ' off' : ''), 'data-key': 'memory-layer' },
      el('span', { class: 'mem-num', text: String(n) }),
      el('div', null,
        el('h3', null, el('span', { text: title }), tag ? el('span', { class: 'mem-tag', text: tag }) : null),
        el('p', { text: meaning }),
        el('dl', { class: 'mem-facts' },
          el('dt', { class: 'label', text: 'Where it lives' }), el('dd', null, where),
          el('dt', { class: 'label', text: 'Who writes it' }), el('dd', { text: writes }),
          el('dt', { class: 'label', text: 'Who may change it' }), el('dd', { text: changes }))));
  }
  function then() { return el('div', { class: 'mem-then', 'data-key': 'memory-then', text: 'then' }); }

  K.memoryScreen = function (report) {
    styleOnce();
    var m = (report.start || {}).memory || { spaces: [] };
    var spaces = m.spaces || [];
    var several = spaces.some(function (s) { return s.repos.length > 1; });
    var repos = [];
    spaces.forEach(function (s) { s.repos.forEach(function (r) { repos.push(r.tier); }); });
    var layout = m.layout || '<install>/spaces';
    return [
      el('div', { class: 'mem', 'data-key': 'memory' },
        layer(1, 'Workspace CLAUDE.md', 'only with more than one repo',
          'What is true across your repos: how they fit together, shared conventions, which repo owns what.',
          paths(spaces.length ? spaces.map(function (s) { return s.tier; }) : [layout + '/<space>/CLAUDE.md']),
          'Bosun drafts it with you in the next step.', YOU, !several),
        then(),
        layer(2, 'Each repo\'s CLAUDE.md', null,
          'What a session must know to work in that repo: how to prepare a worktree, how to run the tests, what never to touch, the conventions of that code.',
          paths(repos.length ? repos : [layout + '/<space>/<repo>/CLAUDE.md']),
          'Bosun drafts it with you in the next step. The CLAUDE.md your team keeps inside the repo is not changed, and Shipyard\'s sessions do not read it: Bosun reads it once and carries over what is worth keeping.',
          YOU),
        then(),
        layer(3, 'Rules', null,
          'Short rules a session cannot break, for every repo or for one. They add to the files above and are enforced, not just read.',
          [el('span', { text: 'Shipyard\'s own folder, and the rules a connection to a code host adds:' }), paths(m.rules ? [m.rules] : [])],
          'Shipyard, and the connections you turn on.', 'You, in Setup. A session cannot change them.'),
        then(),
        layer(4, 'Bosun\'s own memory', null,
          'What Bosun has learned about this install: how it was set up, what went wrong, what it knows how to fix.',
          paths(m.bosun ? [m.bosun] : []), 'Bosun.',
          'You can read and edit it. Bosun proposes changes as cards, and you approve them.')),
      el('div', { class: 'mem-under', 'data-key': 'memory-under' },
        el('p', { text: 'Every card\'s session reads the first three; Bosun reads its own memory. They are plain files in your repos and your install. ' +
          'Nothing here is hidden, and nothing is written without you seeing it first.' }),
        el('p', null, el('strong', { text: 'Bosun writes the first draft of each with you in the next step.' })))];
  };
})(window.Keel);
