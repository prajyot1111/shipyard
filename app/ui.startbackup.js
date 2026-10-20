/* Back up, the first run's step 10 (c-678, c-757), loaded before `ui.start.js`, which reads
 * it as `K.backupScreen(report, step, parts)`.
 *
 * Off: one field, the folder (the suggested one filled in), and Turn on backup, which is the
 * one verb `firstrun.backup.on` (keel/backupsetup.py): the folder named as the store, the
 * keys made, the two jobs loaded and the first copy started. A refusal stays on the page as
 * a stuck line in the server's words; for a folder inside the install its fix is Use the
 * suggested folder, and for a computer with no gpg it is Open Check this computer, where
 * gpg's row has its install command. That gpg line is drawn before the tap too, whenever the
 * state says gpg is missing (`step.backup.gpg`).
 *
 * On (`step.backup`, read with every state, keel/backupstatus.py): what is observed, never
 * assumed. Folder can be written; First copy written, in the state the server read (`copy`:
 * written with when, writing, failed with the tool's own reason, or none); Restore proof
 * (`proof`: proved with when, failed with the reason, missed, or waiting), each with the
 * real day the next one is due. While the first copy is still to come the screen says it is
 * written in the background and that you can go on, and the page asks for the state again
 * every few seconds so the row turns by itself.
 *
 * The words under the heading say what happens now: a copy about every hour when something
 * changed, an overdue one started by Shipyard itself, what is kept and for how long, a
 * notice on the board when none succeeds, and, for a folder on the install's own disk,
 * that a copy there does not survive losing the disk unless the folder is synced somewhere
 * else (`same_disk`, which proves a shared device and nothing about syncing).
 *
 * THE PASSPHRASE IS SHOWN ONCE. The verb's answer carries it only when that call made it,
 * and this page holds it in memory, never in storage: it is shown with Copy and one tick,
 * "I saved it somewhere that is not this computer.", and ticking it drops it from the page.
 * A reload drops it too, so whenever no passphrase is showing the panel says where on this
 * computer the key file is, from the state's own `key` (review r2.F6): after the tick, on a
 * reload, and where the tap's answer never reached the page. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el;
  var VERB = 'firstrun.backup.on';
  var typed = null;          /* the folder as the user is typing it; null: the suggested one */
  var shown = null;          /* { passphrase, key }: the answer of the tap, until the tick */
  var kept = null;           /* the key this computer already had: where it is */
  var hushed = false;        /* the last refusal was answered with the suggested folder */
  var POLL_MS = 4000;        /* while the first copy is still to come, the state is asked for again */
  var armed = false;
  var CHECKS = 'prerequisites';

  var STYLE = [
    '.bkp{display:flex;flex-direction:column;gap:12px}',
    '.bkp-form{display:flex;gap:8px;flex-wrap:wrap;align-items:end}',
    '.bkp-form label{display:flex;flex-direction:column;gap:4px;flex:1 1 320px;min-width:0;font-size:12px;color:var(--ink-2)}',
    '.bkp-form input{min-height:44px;font-family:var(--mono);font-size:13px;min-width:0}',
    '.bkp-form .btn{min-height:44px}',
    '.bkp-key{border:1px solid var(--accent);background:var(--accent-soft);padding:12px;display:flex;flex-direction:column;gap:8px;font-size:13px;line-height:1.5;min-width:0}',
    '.bkp-key h3{margin:0;font-size:15px}.bkp-key p{margin:0}',
    '.bkp-key label{display:flex;gap:8px;align-items:center;min-height:44px}',
    '.bkp-key .fix{overflow-wrap:anywhere}',
    '.bkp-line{font-size:12px;line-height:1.5;color:var(--ink-2);overflow-wrap:anywhere}',
    '.bkp-go{font-size:13px;line-height:1.5;padding:10px 12px;border:1px solid var(--accent);background:var(--accent-soft)}',
    '.bkp-fix{margin-top:8px}.bkp-fix .btn{min-height:44px}'
  ].join('\n');
  function styleOnce() {
    if (document.getElementById('startbackup-style')) return;
    var node = document.createElement('style');
    node.id = 'startbackup-style';
    node.textContent = STYLE;
    document.head.appendChild(node);
  }
  function redraw() { K.renderBody(); }

  function turnOn(folder) {
    hushed = false;
    K.setupParts.change({ verb: VERB, folder: folder }, 'backup is on').then(function (r) {
      if (!r) return;
      typed = null;
      if (r.passphrase) shown = { passphrase: r.passphrase, key: r.key };
      else if (r.kept_key) kept = r.key;
      redraw();
    });
  }

  /* one timer: while a copy is still to come the row is read again without a reload */
  function follow(pending) {
    if (!pending || armed) return;
    armed = true;
    setTimeout(function () { armed = false; if (K.load) K.load(); }, POLL_MS);
  }
  function openChecks() {
    return el('button', { class: 'btn primary', onclick: function () { K.openStep(CHECKS); } }, 'Open Check this computer');
  }

  function refusedLine(suggested) {
    var why = hushed ? null : K.refusal(VERB);
    if (!why) return null;
    var kind = (why.detail || {}).kind;
    if (kind === 'gpg') return null;        /* the gpg line below says it, with its way to the row */
    return K.stuck({ key: 'backup-refused', name: 'Turn on backup', what: why.error,
      fix: kind === 'inside' ? el('button', { class: 'btn primary', onclick: function () {
        typed = (why.detail.suggested || suggested); hushed = true; redraw();
      } }, 'Use the suggested folder') : null });
  }

  /* gpg is missing: said before the tap from the state, and after a refused one */
  function gpgLine(found) {
    var why = K.refusal(VERB), refused = why && (why.detail || {}).kind === 'gpg';
    var check = found.gpg || {};
    if (check.ok !== false && !refused) return null;
    return K.stuck({ key: 'backup-gpg', name: 'gpg, for backup',
      what: check.ok === false ? check.what : why.error,
      fix: [el('div', { text: 'Its row on the Check this computer step has the command that installs it. Then come back here and turn backup on.' }),
        el('div', { class: 'bkp-fix' }, openChecks())] });
  }

  /* what a shared device proves, and no more (r1.F7): the folder may itself be a synced one */
  var SAME_DISK = ' is on the same disk as this install. Unless that folder is synced somewhere else, a copy there does not survive losing the disk or the computer.';
  function diskLine(found, folder) {
    return found.same_disk ? el('div', { class: 'bkp-line', 'data-key': 'backup-disk', text: folder + SAME_DISK }) : null;
  }

  function off(found) {
    var folder = typed === null ? found.suggested || '' : typed;
    var pending = K.isPending(K.pendKey({ verb: VERB }));
    return [
      el('div', { class: 'bkp-form', 'data-key': 'backup-form' },
        el('label', null, el('span', { text: 'Folder' }),
          el('input', { type: 'text', 'data-fk': 'backup-folder', value: folder, 'aria-label': 'Folder', spellcheck: 'false',
            oninput: function (ev) { typed = ev.target.value; } })),
        el('button', { class: 'btn primary' + (pending ? ' pending' : ''), disabled: pending ? true : null,
          onclick: function () { turnOn(typed === null ? found.suggested || '' : typed); } }, 'Turn on backup')),
      folder === (found.suggested || '') ? diskLine(found, 'The suggested folder') : null,
      gpgLine(found), refusedLine(found.suggested)];
  }

  function passphrase(found) {
    if (shown) return el('div', { class: 'bkp-key', 'data-key': 'backup-passphrase' },
      el('h3', { text: 'Your recovery passphrase' }),
      K.command(shown.passphrase),
      el('p', { class: 'bkp-line', text: 'It is shown here once. Without it a copy cannot be read. On this computer it is kept in ' + shown.key + '.' }),
      el('label', null, el('input', { type: 'checkbox', 'data-key': 'backup-saved', onchange: function (ev) {
        if (ev.target.checked) { shown = null; redraw(); }
      } }), el('span', { text: 'I saved it somewhere that is not this computer.' })));
    if (kept) return el('div', { class: 'bkp-line', 'data-key': 'backup-kept',
      text: 'This computer already had a recovery passphrase, from a backup set up before, so none was made and none is shown. It is kept in ' + kept + '.' });
    if (found.key) return el('div', { class: 'bkp-line', 'data-key': 'backup-keyfile',
      text: 'The recovery passphrase is kept on this computer in ' + found.key + '. Without it a copy cannot be read, so keep it somewhere that is not this computer too.' });
    return null;
  }

  var ago = function (at) { return K.ago ? K.ago(at) : at; };
  var FIRST = 'First copy written', PROOF = 'Restore proof';

  /* the first copy, in the state the server read (`copy`, keel/backupstatus.py) */
  function firstCopy(found) {
    var copy = found.copy || { state: 'none', said: '' };
    if (copy.state === 'written') return K.check({ key: 'backup-first', state: 'ready', name: FIRST, says: 'Written ' + ago(copy.at) + ' ago' });
    if (copy.state === 'writing') return K.check({ key: 'backup-first', state: 'checking', name: FIRST, says: copy.said });
    if (copy.state === 'none' && !copy.late) return K.check({ key: 'backup-first', state: 'waiting', name: FIRST, says: copy.said });
    var newest = copy.state === 'failed' && copy.at ? 'The newest copy was written ' + ago(copy.at) + ' ago. The run after it stopped: ' : '';
    return K.check({ key: 'backup-first', state: 'needs', name: FIRST, what: newest + copy.said,
      fix: (found.gpg || {}).ok === false ? [el('div', { text: 'This computer has no gpg where the backup looks. ' + copy.fix }), el('div', { class: 'bkp-fix' }, openChecks())] : copy.fix });
  }

  /* the restore proof, in the state the server read (`proof`), with the day the next is due */
  function proofRow(found) {
    var proof = found.proof || { state: 'waiting', said: '' };
    if (proof.state === 'proved') return K.check({ key: 'backup-proof', state: 'ready', name: PROOF, says: 'Proved ' + ago(proof.at) + ' ago. ' + proof.said });
    if (proof.state === 'waiting') return K.check({ key: 'backup-proof', state: 'waiting', name: PROOF, says: proof.said });
    return K.check({ key: 'backup-proof', state: 'needs', name: PROOF, quiet: proof.state === 'missed',
      what: proof.said + (proof.at ? ' The last one that passed was ' + ago(proof.at) + ' ago.' : ''), fix: proof.fix });
  }

  var HOW = ' about every hour, when something on the board has changed. If a copy is overdue, Shipyard starts one itself. Copies are kept hourly for a day and daily for thirty days. If none succeeds, a notice appears on the board.';
  function pending(found) {
    var state = (found.copy || {}).state;
    return state === 'writing' || (state === 'none' && !found.copy.late);
  }

  function on(found) {
    var folder = found.folder || found.store;
    follow(pending(found));
    return [
      el('div', { class: 'bkp-line', 'data-key': 'backup-where', text: 'An encrypted copy of the board is written to ' + folder + HOW }),
      diskLine(found, 'That folder'),
      pending(found) ? el('div', { class: 'bkp-go', role: 'status', 'data-key': 'backup-go',
        text: 'Backup is on. The first copy is written in the background, so you can go on: press Next. This page shows the copy once it is written.' }) : null,
      found.writable === false
        ? K.check({ key: 'backup-folder', state: 'needs', name: 'Folder can be written',
          what: folder + ' is not there or cannot be written, so no copy is being made.',
          fix: 'Put the folder back (a disk that is not connected, a synced folder that is signed out), and this row turns green.' })
        : K.check({ key: 'backup-folder', state: 'ready', name: 'Folder can be written', says: folder }),
      firstCopy(found), proofRow(found),
      passphrase(found)];
  }

  K.backupScreen = function (report, step) {
    styleOnce();
    var found = step.backup || { on: false, suggested: '' };
    return el('div', { class: 'bkp', 'data-key': 'backup' }, found.on ? on(found) : off(found));
  };
})(window.Keel);
