/* A browser for sessions, the first run's step 9 (c-678), loaded before `ui.start.js`,
 * which reads it as `K.browserScreen(report, step, parts)`.
 *
 * Two checks, each in the shared check row (`K.check`, app/ui.stuck.js):
 * 1. "Node.js 20 or newer" (`step.node`, keel/browserinstall.py): ready with the version,
 *    or the stuck line with what is installed and how to get a newer one.
 * 2. "Shipyard's browser is installed" (`step.install`): waiting with Install; checking
 *    while it downloads, with the server's sentence ("Downloading Chromium: 40% of 151.2
 *    MiB") and, where the size is known, a bar of what has arrived (c-757: `percent` is the
 *    downloader's own count, and None while no size is known, when the row says what is
 *    known and draws no bar); ready; or, when the download stopped, the stuck line with
 *    what the installer said and how far it was, and Try again.
 *
 * Install and Try again are one verb (`firstrun.browser.install`), which starts the download
 * on the server, detached from the deck. The page never waits on it: the step comes with
 * the state on every poll, and while a download runs the page asks for the state again
 * every few seconds so the bar moves. The step is optional; Skip is the frame's. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el;
  var POLL_MS = 3000;
  var armed = false;
  var NAME = 'Shipyard\'s browser is installed';

  function styleOnce() {
    if (document.getElementById('startbrowser-style')) return;
    var node = document.createElement('style');
    node.id = 'startbrowser-style';
    node.textContent = '.brw{display:flex;flex-direction:column;gap:8px}.brw-btns{display:flex;gap:8px;flex-wrap:wrap}.brw-btns .btn{min-height:44px}' +
      '.brw-load{display:flex;flex-direction:column;gap:6px;padding:0 0 4px 24px;font-size:12px;color:var(--ink-2)}' +
      '.brw-bar{height:6px;background:var(--s3);overflow:hidden}.brw-fill{height:100%;background:var(--accent);transition:width .4s linear}';
    document.head.appendChild(node);
  }

  /* while it downloads, the state is asked for again so the bar moves; one timer */
  function follow(downloading) {
    if (!downloading || armed) return;
    armed = true;
    setTimeout(function () { armed = false; if (K.load) K.load(); }, POLL_MS);
  }

  function install(label) {
    var body = { verb: 'firstrun.browser.install' }, mine = K.isPending(K.pendKey(body));
    return el('div', { class: 'brw-btns' }, el('button', { class: 'btn primary' + (mine ? ' pending' : ''), disabled: mine ? true : null,
      onclick: function () { K.act(body, function (r) { return (r && r.note) || 'downloading Shipyard\'s browser'; }); } }, label));
  }

  function nodeRow(node) {
    if (node.ok) return K.check({ key: 'browser-node', state: 'ready', name: 'Node.js 20 or newer', says: node.said });
    return K.check({ key: 'browser-node', state: 'needs', name: 'Node.js 20 or newer', what: node.said,
      fix: [el('div', { text: node.fix || '' }), node.command ? K.command(node.command) : null] });
  }

  /* what has arrived of what there is: drawn only where the downloader said a size */
  function bar(found) {
    if (found.percent === null || found.percent === undefined) return null;
    var percent = Math.max(0, Math.min(100, found.percent));
    return el('div', { class: 'brw-load', 'data-key': 'browser-progress' },
      el('div', { class: 'brw-bar', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(percent),
        'aria-label': 'Download progress' }, el('div', { class: 'brw-fill', style: 'width:' + percent + '%' })),
      el('div', { 'data-key': 'browser-far', text: found.received_mb + ' of ' + found.of_mb + ' MiB' }));
  }

  function browserRow(found, node) {
    if (found.state === 'ready') return K.check({ key: 'browser-install', state: 'ready', name: NAME });
    if (found.state === 'downloading') return [K.check({ key: 'browser-install', state: 'checking', name: NAME, says: found.said }), bar(found)];
    if (found.state === 'failed') return K.check({ key: 'browser-install', state: 'needs', name: NAME, what: found.said,
      fix: install('Try again') });
    return [K.check({ key: 'browser-install', state: 'waiting', name: NAME }),
      node.ok ? install('Install') : el('div', { class: 'brw-btns' },
        el('button', { class: 'btn', disabled: true }, 'Install'),
        el('span', { class: 'start-hint', text: 'Install turns on when Node.js is ready.' }))];
  }

  K.browserScreen = function (report, step) {
    styleOnce();
    var node = step.node || { ok: false, said: 'Node.js could not be checked.' };
    var found = step.install || { state: 'waiting' };
    follow(found.state === 'downloading');
    return el('div', { class: 'brw', 'data-key': 'browser' }, nodeRow(node), browserRow(found, node));
  };
})(window.Keel);
