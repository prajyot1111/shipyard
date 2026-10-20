/* The deck's service worker: the SHELL only, network-first.
 *
 * `/api/*`, `/segments/*` and the lavish proxy are never touched: the page polls live
 * state and a cached answer would be a wrong one. The shell files are cached only as the
 * offline fallback; a deploy shows on the very next load. Activate deletes every other cache
 * with this prefix.
 *
 * The deck's own scripts are not listed here (c-634): the server fills the `var DECK` line
 * from app/views.json (keel/deckviews.py), with a hash of that manifest, so the cache name
 * changes by itself whenever a view or a script is added. Bump the `v` below only when a
 * file in the hand-kept list changes.
 *
 * Network first costs little now (c-540): the door sends each file with an ETag and
 * `no-cache`, so the browser's own cache answers the fetch below with a 304 and no body.
 * Bosun's Console registers this worker too, and its shell and files are in the list. */
var DECK = { scripts: [], hash: '' };
var CACHE = 'keel-deck-shell-v43-' + DECK.hash;
var SHELL = ['/', '/ui.css', '/ui.find.css'].concat(DECK.scripts, [
             '/ui.plandiagram.js', '/ui.plancode.js', '/ui.planfinding.js', '/ui.planblocks.js', '/ui.plan.js', '/ui.plan.css', '/ui.planpage.js', '/ui.planlook.js', '/ui.ci.js', '/ui.comments.js',
             '/vendor/elk.bundled.js', '/manifest.json',
             '/icons/keel-glyph.svg', '/icons/keel-tile.svg', '/icons/keel-32.png', '/icons/keel-180.png', '/icons/voice-glyph.svg',
             '/console', '/console/queue', '/console/shipped', '/console/journal', '/ui.console.js', '/ui.console.asks.js', '/ui.console.css', '/console.webmanifest',
             '/icons/bosun.ico', '/icons/bosun-180.png', '/icons/bosun-192.png', '/icons/bosun-glyph.svg']);

self.addEventListener('install', function (ev) {
  self.skipWaiting();
  ev.waitUntil(caches.open(CACHE).then(function (c) {
    return Promise.all(SHELL.map(function (u) { return c.add(u).catch(function () {}); }));
  }));
});

self.addEventListener('activate', function (ev) {
  ev.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k.indexOf('keel-deck-shell-') === 0 && k !== CACHE; })
      .map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener('fetch', function (ev) {
  var req = ev.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin !== location.origin) return;
  var path = url.pathname === '/index.html' ? '/' : url.pathname;
  if (SHELL.indexOf(path) < 0) return;
  ev.respondWith(fetch(req).then(function (res) {
    var copy = res.clone();
    caches.open(CACHE).then(function (c) { c.put(path, copy); }).catch(function () {});
    return res;
  }).catch(function () {
    return caches.match(path).then(function (hit) { return hit || Response.error(); });
  }));
});
