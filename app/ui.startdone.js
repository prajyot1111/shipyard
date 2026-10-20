/* You are set up, the first run's last screen (c-678), loaded before `ui.start.js`, which
 * reads it as `K.setUpScreen(report, step, parts)`.
 *
 * One line of where things stand (Keel is running, which repos are connected, whether the
 * first card landed), then:
 *
 * - When something does not work: Bosun's session is where to go, with the command and
 *   Copy, and when to go there.
 * - What was set: every step that reads done, in the step's own sentence, with Change, which
 *   opens that step; and each repo's prepare, test and lands-on as its adopted CLAUDE.md
 *   says them (`spaces.<name>.drafts` on the Setup report).
 * - What was skipped: every step that is not done, with Set it up.
 * - More to set up later: the phone and voice, which were a step of their own until this
 *   screen existed. They are folded, since nothing else depends on them.
 * - Open the board, which finishes the first run where it can be finished, and Open Bosun,
 *   which is Bosun's own page on the deck (`/console`), not a panel on this one.
 *
 * Nothing here is stored: each line is the step's state as the page already has it. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el, App = K.App;
  var LAST = 'set-up';

  var STYLE = [
    '.su{display:flex;flex-direction:column;gap:16px}',
    '.su-lead{font-size:15px;line-height:1.5}',
    '.su-panel{border:1px solid var(--hair-hi);background:var(--s1);padding:12px;display:flex;flex-direction:column;gap:8px;font-size:13px;line-height:1.5;min-width:0}',
    '.su-panel.flag{border-color:var(--accent)}',
    '.su-panel h3{margin:0;font-size:15px}.su-panel p{margin:0}',
    '.su-row{display:grid;grid-template-columns:minmax(0,180px) minmax(0,1fr) auto;gap:4px 12px;align-items:center;padding:8px 0;border-top:1px solid var(--hair);font-size:13px}',
    '.su-row:first-of-type{border-top:0}',
    '.su-row .t{font-weight:600}.su-row .said{color:var(--ink-2);overflow-wrap:anywhere;min-width:0}',
    '.su-row .btn{min-height:44px}',
    '.su-row code{font-family:var(--mono);font-size:12px}',
    '.su-btns{display:flex;gap:8px;flex-wrap:wrap}.su-btns .btn{min-height:44px}',
    '.su-later summary{cursor:pointer;min-height:44px;display:flex;align-items:center;font-weight:600}',
    /* a flex summary loses the browser's own fold mark, so the fold says it is one */
    '.su-later summary::before{content:"+";font-family:var(--mono);margin-right:8px;color:var(--ink-2)}',
    '.su-later[open] summary::before{content:"-"}',
    '.su-later[open] summary{margin-bottom:8px}',
    '@media (max-width:899px){.su-row{grid-template-columns:minmax(0,1fr) auto}.su-row .said{grid-column:1 / -1;grid-row:2}}'
  ].join('\n');
  function styleOnce() {
    if (document.getElementById('startdone-style')) return;
    var node = document.createElement('style');
    node.id = 'startdone-style';
    node.textContent = STYLE;
    document.head.appendChild(node);
  }
  function session() { return (App.data && (App.data.console || App.data.bosun)) || {}; }
  function sentence(text) {
    var t = String(text || '').trim();
    return t ? t.charAt(0).toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? '' : '.') : '';
  }

  /* the user's repos, by name: the install's own repos (K.OWN_REPOS) are not among them */
  function repoNames(report) {
    var out = [];
    Object.keys(report.spaces || {}).forEach(function (name) {
      (report.spaces[name].repos || []).forEach(function (r) { if (!K.ownRepo(r.key)) out.push(r.key); });
    });
    return out;
  }
  function lead(report, list) {
    var repos = repoNames(report);
    var first = list.filter(function (s) { return s.id === 'first-card'; })[0] || {};
    var landed = first.card && first.card.stage === 'done';
    var bits = ['Shipyard is running'];
    if (repos.length) bits.push(repos.join(', ') + (repos.length > 1 ? ' are' : ' is') + ' connected');
    if (landed) bits.push('your first card landed');
    var said = bits.length > 2 ? bits.slice(0, -1).join(', ') + ', and ' + bits[bits.length - 1] : bits.join(', and ');
    return el('div', { class: 'su-lead', 'data-key': 'setup-lead', text: said + '.' });
  }

  function help() {
    var attach = session().attach;
    return el('div', { class: 'su-panel flag', 'data-key': 'setup-help' },
      el('h3', { text: 'When something does not work' }),
      el('p', { text: 'Bosun\'s session is where to go. Open it in a terminal with this command, or open Bosun in the Claude app (the session named Bosun).' }),
      attach ? K.command(attach) : null,
      el('p', { text: 'Go to Bosun when a check is red and its fix did not work, when a card is blocked and you cannot tell why, when a landing fails, ' +
        'or when you want Shipyard to do something it does not do yet. Every red line in Shipyard says what happened, what to do, and how to ask Bosun in its session.' }));
  }

  function row(key, title, said, label, go) {
    return el('div', { class: 'su-row', 'data-key': key },
      el('span', { class: 't', text: title }), el('span', { class: 'said' }, said),
      el('button', { class: 'btn sm', onclick: go }, label));
  }
  /* each adopted repo file's three lines, as the file says them, where Keel runs them
     (`lines` is `run`, keel/tierrecord.py). A file whose lines are not on lists none: they
     were not set (review r2.F13). */
  var NOT_ON = { changed: 'Its lines are not on: the file changed since it was adopted or saved.',
    never: 'Its lines are not on yet: the file has not been adopted or saved.' };
  function commands(report, open) {
    var out = [];
    Object.keys(report.spaces || {}).forEach(function (name) {
      (report.spaces[name].drafts || []).forEach(function (r) {
        var c = r.commands;
        if (r.state !== 'adopted' || !c || r.aim.indexOf('/') < 0) return;
        function one(label, found) { return found ? [label + ' ', el('code', { text: found.value }), '. '] : null; }
        if (NOT_ON[r.lines]) out.push(row('set-repo-' + r.aim, r.label, NOT_ON[r.lines], 'Turn them on', function () { open('rules'); }));
        else if (r.lines === 'run') out.push(row('set-repo-' + r.aim, r.label, [one('Prepare', c.prepare), one('Test', c.test), one('Lands on', c.lands)],
          'Change', function () { open('rules'); }));
      });
    });
    return out;
  }
  function wasSet(report, list, open) {
    var done = list.filter(function (s) { return s.id !== LAST && s.done === true; });
    if (!done.length) return null;
    return el('div', { class: 'su-panel', 'data-key': 'setup-set' }, el('h3', { text: 'What was set' }),
      done.map(function (s) {
        var rows = [row('set-' + s.id, s.title, sentence(s.why), 'Change', function () { open(s.id); })];
        return s.id === 'rules' ? rows.concat(commands(report, open)) : rows;
      }));
  }
  function wasSkipped(list, open) {
    var open_ = list.filter(function (s) { return s.id !== LAST && s.done === false; });
    if (!open_.length) return null;
    return el('div', { class: 'su-panel', 'data-key': 'setup-skipped' }, el('h3', { text: 'What was skipped' }),
      open_.map(function (s) { return row('skipped-' + s.id, s.title, sentence(s.why), 'Set it up', function () { open(s.id); }); }));
  }

  /* the phone and voice: the old step's content, folded */
  function later(report, parts) {
    var cmd = ((report.start || {}).phone || {}).command || 'tailscale serve --bg <port>';
    return el('details', { class: 'su-panel su-later', 'data-key': 'setup-later' },
      el('summary', { text: 'More to set up later' }),
      parts.sub('later-phone', 'The phone', [parts.rowLine('phone', undefined, 'Tailscale serve'),
        el('div', { class: 'start-about', text: 'The phone reaches the deck over your tailnet. Run this once, in a terminal on this machine. Shipyard only reads whether it is set; it never changes your network.' }),
        K.command(cmd)]),
      parts.sub('later-voice', 'Voice', [parts.rowLine('voice', undefined, 'Voice'),
        el('div', { class: 'start-about', text: 'Talk to a session from the Voice page. Two voices can read answers back: Google TTS (Google\'s cloud voices; needs a Google Cloud text-to-speech key on this machine, and each sentence is a small charge), and kokoro (runs on this machine, free and offline; `keel voice install` sets it up, several hundred MB). Neither is picked for you.' }),
        K.settingsForm ? K.settingsForm({ keys: ['voice.engine_default'], choose: true }) : null,
        el('div', { class: 'su-btns' }, el('a', { class: 'btn', href: K.voiceHref ? K.voiceHref() : '#' }, 'Open Voice and hold to talk'))]));
  }

  function ways(parts) {
    return el('div', { class: 'su-btns', 'data-key': 'setup-ways' },
      el('button', { class: 'btn primary', onclick: function () {
        var go = function () { K.go('cards'); };
        if (parts.finished() || !parts.canFinish()) { go(); return; }
        K.act({ verb: 'firstrun.finish' }).then(go);
      } }, 'Open the board'),
      el('a', { class: 'btn', href: '/console', 'data-key': 'open-bosun' }, 'Open Bosun'));
  }

  K.setUpScreen = function (report, step, parts) {
    styleOnce();
    var list = parts.steps();
    return el('div', { class: 'su', 'data-key': 'set-up' },
      lead(report, list), help(), wasSet(report, list, parts.open), wasSkipped(list, parts.open),
      later(report, parts), ways(parts));
  };
})(window.Keel);
