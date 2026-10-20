/* The stuck line (c-677, from the first-run design of c-668): the ONE component for a
 * requirement that needs you, and the line that says where Bosun's session is.
 *
 * `K.stuck({key, name, what, fix, quiet})` draws up to three parts:
 * 1. what happened: `what`, the reason the report already carries (a readiness row's `why`,
 *    a check's `said` or `why`), in its own words: only a closing full stop is added, and
 *    its case is never changed, since it may begin with a tool's own name ("gh", "wt-repo");
 * 2. the fix: `fix`, when the report has one. A string is prose whose `code` is drawn as
 *    code; a node (a button, a command box) is drawn as it is. With no fix the part is left
 *    out: nothing here invents one;
 * 3. "or ask Bosun in its session:" with the attach command and Copy, whenever Bosun's
 *    session can run (`K.bosunSession`), on every step and in Setup. `ask: false` leaves it
 *    out, for the one row where Bosun is the thing that is down.
 * `quiet` is the form for a requirement that does not block (a machine check that is not
 * required, a login that could not be checked): the same parts, with a muted mark and no
 * "needs you". `how` adds "How this page knows", for a row that turns green by itself.
 *
 * `K.check({key, state, name, says, how, what, fix, quiet})` is one check row in the four
 * states the first-run design gives every check (c-678): `waiting` (grey), `checking` (a
 * spinner), `ready` (a tick and what was found), and `needs`, which is the stuck line above
 * (`what`, else `says`, is what happened). The first-run screens and the sign-in block
 * (app/ui.signin.js) draw their rows with it.
 *
 * `K.fixOf(needs)` is the fix a requirement brings with it (c-688), for `fix`: a pack's
 * `[[requires]]` entry may say `fix` (the sentence), `command` (one line to copy, drawn with
 * Copy) and `done_when` (how you know it worked), which `packs.checks` returns on the check
 * and readiness on the row a failing check holds up (`needs`). It takes one check or a
 * list, names each when there are several, and is null when none says a fix. An entry's
 * `action` (a line a button would run) is carried in the report and not drawn: no verb runs
 * one yet.
 *
 * `K.bosunSession()` is `{attach}` when Bosun's session can run, else null: nothing points at
 * a session that cannot answer. One rule, from readiness's install rows (keel/readiness.py):
 * `builder` is ready (builder mode on, and Start would not refuse), `login` is ready (a
 * login that could not be checked counts as ready, since a probe that timed out must not
 * hide a live Bosun; an expired or missing login draws nothing), and `prerequisites` is
 * ready (no required machine check fails, Claude Code among them; a failing check that
 * does not block changes nothing). The command
 * is the state's own (`console.attach`, or `bosun.attach` while no session exists,
 * keel/deckstate.py): this install's `<home>/bin/keel console attach`, which joins Bosun's
 * session from a terminal here and starts it first when it is down.
 * `K.bosunLine()` is the first run's header line, "Stuck? Open Bosun's session", or null.
 *
 * Setup's pack checks (app/ui.setup.js) and every first-run step (app/ui.start.js) draw a
 * failing requirement with it, so they cannot say it two ways. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el;

  var STYLE = [
    '.stuck{border:1px solid var(--warn);background:var(--s1);display:flex;flex-direction:column;min-width:0}',
    '.stuck.quiet{border-color:var(--hair-hi)}.stuck.quiet .stuck-mark{color:var(--ink-3)}',
    '.stuck-head{display:flex;align-items:center;gap:8px;padding:8px 12px;border-bottom:1px solid var(--hair);font-size:13px;font-weight:600}',
    '.stuck-mark{font-family:var(--mono);color:var(--warn);flex:0 0 16px;text-align:center}',
    '.stuck-name{flex:1;min-width:0;overflow-wrap:anywhere}',
    '.stuck-pill{font-family:var(--mono);font-size:10px;font-weight:400;color:var(--warn);border:1px solid var(--warn);border-radius:var(--pill);padding:2px 8px;white-space:nowrap}',
    '.stuck-part{display:grid;grid-template-columns:132px minmax(0,1fr);gap:4px 12px;padding:8px 12px;font-size:13px;line-height:1.5;align-items:start}',
    '.stuck-part .label{padding-top:2px}',
    '.stuck-part .said{min-width:0;overflow-wrap:anywhere}',
    '.stuck-part code{font-family:var(--mono);font-size:12px}',
    '.stuck-how{display:flex;flex-direction:column;gap:6px;min-width:0}.stuck-how+.stuck-how{margin-top:12px}',
    '.stuck-then{font-size:12px;color:var(--ink-2)}',
    '.stuck-bosun{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:8px 12px;font-size:12px;color:var(--ink-2)}',
    '.stuck-bosun .lfix{flex:1 1 240px;align-items:center}',
    '.chk{display:grid;grid-template-columns:16px minmax(0,1fr) auto;gap:2px 8px;align-items:center;font-size:13px;padding:8px 0;border-top:1px solid var(--hair);min-width:0}',
    '.chk:first-child{border-top:0}',
    /* a row that waits is a row, not the deck's waiting banner, whose class has the same name (ui.css) */
    '.chk.waiting{padding:8px 0;border-left:0;border-bottom:0;color:inherit}',
    '.chk-mark{font-family:var(--mono);font-size:11px;text-align:center;color:var(--ink-3);display:flex;justify-content:center}',
    '.chk.ready .chk-mark{color:var(--good)}',
    '.chk .spin{width:12px;height:12px}',
    '.chk-name{min-width:0;overflow-wrap:anywhere}.chk.waiting .chk-name{color:var(--ink-2)}',
    '.chk-pill{font-family:var(--mono);font-size:10px;color:var(--ink-3);border:1px solid var(--hair-hi);border-radius:var(--pill);padding:2px 8px;white-space:nowrap}',
    '.chk.ready .chk-pill{color:var(--good);border-color:var(--good)}.chk.checking .chk-pill{color:var(--accent-ink);border-color:var(--accent)}',
    '.chk-says,.chk-how{grid-column:2 / -1;font-size:12px;color:var(--ink-2);overflow-wrap:anywhere}.chk-how{color:var(--ink-3)}',
    '.bosun-line{display:flex;align-items:center;gap:8px 12px;flex-wrap:wrap;padding:8px 12px;margin-bottom:12px;border:1px solid var(--hair);background:var(--s1);font-size:13px}',
    '.bosun-line strong{font-weight:600}',
    '.bosun-line .lfix{flex:1 1 240px;align-items:center}',
    '@media (max-width:899px){.stuck-part{grid-template-columns:minmax(0,1fr)}.stuck-part .label{padding-top:0}}'
  ].join('\n');

  function styleOnce() {
    if (document.getElementById('stuck-style')) return;
    var node = document.createElement('style');
    node.id = 'stuck-style';
    node.textContent = STYLE;
    document.head.appendChild(node);
  }

  /* `code` and **bold** in a line of plain text, as nodes: never as HTML */
  function words(text) {
    var out = [], rest = String(text || ''), m;
    var pattern = /(`[^`]+`|\*\*[^*]+\*\*)/;
    while ((m = pattern.exec(rest))) {
      if (m.index) out.push(rest.slice(0, m.index));
      var bit = m[0];
      out.push(bit.charAt(0) === '`' ? el('code', { text: bit.slice(1, -1) }) : el('strong', { text: bit.slice(2, -2) }));
      rest = rest.slice(m.index + bit.length);
    }
    if (rest) out.push(rest);
    return out;
  }
  function sentence(text) {
    var t = String(text || '').trim();
    return t ? t.charAt(0).toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? '' : '.') : '';
  }

  /* `what` as it came, closed with a full stop when it has none */
  function closed(text) {
    var t = String(text || '').trim();
    return t && !/[.!?]$/.test(t) ? t + '.' : t;
  }

  function bosunSession() {
    var d = K.App.data || {};
    var rows = (d.readiness || {}).install || {};
    var entry = d.console || d.bosun;
    var runs = ['builder', 'login', 'prerequisites'].every(function (name) {
      return rows[name] && rows[name].ready;
    });
    return runs && entry && entry.attach ? { attach: entry.attach } : null;
  }
  function command(text) {
    return el('div', { class: 'lfix' }, el('code', { class: 'fix', text: text }), K.copyButton(text));
  }
  function askBosun() {
    var session = bosunSession();
    return session ? el('div', { class: 'stuck-bosun', 'data-key': 'stuck-bosun' },
      el('span', { text: 'or ask Bosun in its session:' }), command(session.attach)) : null;
  }
  function part(key, label, body) {
    return el('div', { class: 'stuck-part', 'data-key': key }, el('span', { class: 'label', text: label }),
      el('div', { class: 'said' }, body));
  }

  function fixOf(needs) {
    var list = (Array.isArray(needs) ? needs : [needs]).filter(function (c) { return c && c.fix; });
    if (!list.length) return null;
    return list.map(function (c) {
      return el('div', { class: 'stuck-how', 'data-key': 'fix-' + c.name },
        el('div', { 'data-key': 'fix-said' }, list.length > 1 ? el('strong', { text: c.name + ': ' }) : null, words(c.fix)),
        c.command ? command(c.command) : null,
        c.done_when ? el('div', { class: 'stuck-then', 'data-key': 'fix-then' }, words(c.done_when)) : null);
    });
  }

  function stuck(o) {
    styleOnce();
    return el('div', { class: 'stuck' + (o.quiet ? ' quiet' : ''), role: 'status', 'data-key': 'stuck-' + o.key },
      el('div', { class: 'stuck-head' }, el('span', { class: 'stuck-mark', text: o.quiet ? '\u2717' : '!' }),
        el('span', { class: 'stuck-name', text: o.name }),
        o.quiet ? null : el('span', { class: 'stuck-pill', text: 'needs you' })),
      part('stuck-what', 'What happened', words(closed(o.what))),
      o.fix ? part('stuck-fix', 'The fix', typeof o.fix === 'string' ? words(o.fix) : o.fix) : null,
      o.how ? part('stuck-knows', 'How this page knows', o.how) : null,
      o.ask === false ? null : askBosun());
  }

  var MARKS = { waiting: '-', ready: '\u2713' };
  function check(o) {
    if (o.state === 'needs') return stuck({ key: o.key, name: o.name, what: o.what || o.says, fix: o.fix, quiet: o.quiet, how: o.how, ask: o.ask });
    styleOnce();
    return el('div', { class: 'chk ' + o.state, 'data-key': o.key, 'data-state': o.state },
      el('span', { class: 'chk-mark' }, o.state === 'checking' ? el('span', { class: 'spin', 'aria-hidden': 'true' }) : MARKS[o.state] || '-'),
      el('span', { class: 'chk-name', text: o.name }),
      el('span', { class: 'chk-pill', text: o.state }),
      o.says ? el('span', { class: 'chk-says', text: o.says }) : null,
      o.how ? el('span', { class: 'chk-how', text: o.how }) : null);
  }

  function bosunLine() {
    var session = bosunSession();
    if (!session) return null;
    styleOnce();
    return el('div', { class: 'bosun-line', 'data-key': 'bosun-line' },
      el('strong', { text: 'Stuck? Open Bosun\'s session' }), command(session.attach));
  }

  K.stuck = stuck; K.check = check; K.command = command; K.fixOf = fixOf; K.bosunSession = bosunSession; K.bosunLine = bosunLine;
  K.words = words; K.asSentence = sentence;
})(window.Keel);
