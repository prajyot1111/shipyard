/* The CI page under node (c-642): app/ui.ci.js run whole against a stand-in for the few
 * things it touches (K.el builds plain nodes, fetch answers the payload the test wrote,
 * K.docTabs records what the header asks for), and read back. */
'use strict';
var fs = require('fs');
var path = require('path');

var app = process.argv[2], dataFile = process.argv[3];
var payload = JSON.parse(fs.readFileSync(dataFile, 'utf8'));

function node(tag, attrs, children) { return { tag: tag, attrs: attrs || {}, children: children }; }
function flat(list, out) {
  list.forEach(function (c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) flat(c, out); else out.push(c);
  });
  return out;
}
var fetched = [], linked = null;
global.window = { Keel: {} };
global.document = { getElementById: function () { return null; }, createElement: function () { return {}; },
                    head: { appendChild: function () {} }, title: '' };
global.fetch = function (url) {
  fetched.push(url);
  return Promise.resolve({ ok: true, json: function () { return Promise.resolve(payload); } });
};
var K = window.Keel;
K.el = function (tag, attrs) { return node(tag, attrs, flat(Array.prototype.slice.call(arguments, 2), [])); };
K.renderBody = function () {};
K.cardTerms = {};
K.say = function (space, template) {
  var t = K.cardTerms[space] || {};
  return String(template).replace(/\{([A-Za-z_]+)\}/g, function (all, key) { return t[key] || all; });
};
K.ago = function () { return 'a while ago'; };
K.docTabs = function (card, docs, current) { linked = { card: card.id, docs: docs, current: current }; return []; };
global.Keel = K;

eval(fs.readFileSync(path.join(app, 'ui.ci.js'), 'utf8'));

function walk(n, seen) {
  if (Array.isArray(n)) { n.forEach(function (c) { walk(c, seen); }); return seen; }
  if (!n || typeof n !== 'object') return seen;
  seen.push(n);
  (n.children || []).forEach(function (c) { walk(c, seen); });
  return seen;
}
function classed(nodes, name) {
  return nodes.filter(function (n) { return (' ' + (n.attrs['class'] || '') + ' ').indexOf(' ' + name + ' ') >= 0; });
}
function text(n) { return typeof n === 'string' ? n : (n.attrs.text || (n.children || []).map(text).join('')); }

K.viewCi('c-001');                      /* the first draw asks for the data */
setImmediate(function () {
  var nodes = walk(K.viewCi('c-001'), []);
  var builds = nodes.filter(function (n) { return /^build-/.test(n.attrs['data-key'] || ''); });
  var checks = nodes.filter(function (n) { return /^check-/.test(n.attrs['data-key'] || ''); });
  var log = nodes.filter(function (n) { return n.tag === 'pre'; })[0];
  var refresh = nodes.filter(function (n) { return n.attrs['data-key'] === 'ci-refresh'; })[0];
  refresh.attrs.onclick();
  setImmediate(function () {
    process.stdout.write(JSON.stringify({
      fetched: fetched.slice(0, 1), refreshed: fetched.length === 2, links: linked,
      checks: checks.length,
      builds: builds.map(function (n) { return n.attrs['data-key']; }),
      stages: classed(nodes, 'ci-stage').map(function (n) { return [text(n), n.attrs['class']]; }),
      log: log ? text(log) : null,
      why: classed(nodes, 'ci-why').map(text).join(' | '),
      headings: nodes.filter(function (n) { return n.tag === 'h2'; }).map(text)
    }));
  });
});
