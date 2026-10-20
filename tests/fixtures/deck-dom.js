/* A DOM stand-in the deck's page modules can be loaded into under node.
 *
 * `deck-morph.js` carries its own copy for the morph alone. This one is for running the
 * RENDERERS (the card pane, Attention, More, the header): it loads the page's modules in
 * their real order against a window whose width the caller picks, so a phone rendering
 * and a desk rendering can both be asked for and their trees read back.
 *
 * Usage (from another fixture): const deck = require('./deck-dom.js');
 *   const K = deck.load(appDir, ['ui.core.js', 'ui.cards.js'], { desk: false });
 */
'use strict';
const fs = require('fs');
const path = require('path');

function Node(type) { this.nodeType = type; this.childNodes = []; this.parentNode = null; }
Node.prototype.insertBefore = function (child, ref) {
  if (child.parentNode) child.parentNode.removeChild(child);
  let at = ref ? this.childNodes.indexOf(ref) : -1;
  if (at < 0) at = this.childNodes.length;
  this.childNodes.splice(at, 0, child);
  child.parentNode = this;
  return child;
};
Node.prototype.appendChild = function (child) { return this.insertBefore(child, null); };
Node.prototype.removeChild = function (child) {
  const at = this.childNodes.indexOf(child);
  if (at >= 0) this.childNodes.splice(at, 1);
  child.parentNode = null;
  return child;
};

function Text(value) { Node.call(this, 3); this.nodeValue = String(value); }
Text.prototype = Object.create(Node.prototype);
Object.defineProperty(Text.prototype, 'textContent', { get: function () { return this.nodeValue; } });

function Element(tag) {
  Node.call(this, 1);
  this.nodeName = String(tag).toUpperCase();
  this.tagName = this.nodeName;
  this.attrs = {};
  this.style = {};
}
Element.prototype = Object.create(Node.prototype);
Element.prototype.getAttribute = function (name) { return name in this.attrs ? this.attrs[name] : null; };
Element.prototype.setAttribute = function (name, value) { this.attrs[name] = String(value); };
Element.prototype.removeAttribute = function (name) { delete this.attrs[name]; };
Element.prototype.hasAttribute = function (name) { return name in this.attrs; };
Element.prototype.addEventListener = function () {};
/* `[name="value"]` only, which is all the menu asks (V2-1) */
Element.prototype.querySelectorAll = function (selector) {
  const m = /^\[([\w-]+)="([^"]*)"\]$/.exec(selector);
  return m ? all(this, (n) => n !== this && n.getAttribute(m[1]) === m[2]) : [];
};
Element.prototype.focus = function () { focused.node = this; };
const focused = { node: null };
Object.defineProperty(Element.prototype, 'attributes', {
  get: function () { return Object.keys(this.attrs).map((name) => ({ name, value: this.attrs[name] })); }
});
Object.defineProperty(Element.prototype, 'className', {
  get: function () { return this.attrs['class'] || ''; },
  set: function (value) { this.attrs['class'] = String(value); }
});
Object.defineProperty(Element.prototype, 'textContent', {
  get: function () { return this.childNodes.map((n) => n.textContent).join(''); },
  set: function (value) {
    this.childNodes.slice().forEach((n) => this.removeChild(n));
    this.appendChild(new Text(value));
  }
});

/* ---------- reading a built tree back ---------- */
function classes(node) { return node.nodeType === 1 ? node.className.split(/\s+/).filter(Boolean) : []; }
function hasClass(node, name) { return classes(node).indexOf(name) >= 0; }
/* every element under `node` (itself included) that `pick` accepts, in document order */
function all(node, pick) {
  const out = [];
  (function walk(n) {
    if (n.nodeType !== 1) return;
    if (pick(n)) out.push(n);
    n.childNodes.forEach(walk);
  })(node);
  return out;
}
function byClass(node, name) { return all(node, (n) => hasClass(n, name)); }
function buttons(node) { return all(node, (n) => n.tagName === 'BUTTON'); }
/* A menu entry (V2-1) carries its name and, under it, the line saying what it does: its
   label is the name alone, as its `aria-labelledby` says. */
function labelOf(b) {
  const name = all(b, (n) => hasClass(n, 'mname'))[0];
  return (name || b).textContent.trim();
}
function labels(node) { return buttons(node).map(labelOf); }
/* a list of what a renderer returned (a node, an array, nulls) as one element */
function wrap(children, K) {
  const host = new Element('div');
  K.add(host, children);
  return host;
}

function load(appDir, modules, opts) {
  opts = opts || {};
  const byId = {};
  const doc = {
    get activeElement() { return focused.node; },
    visibilityState: 'hidden',
    createElement: (tag) => new Element(tag),
    createElementNS: (ns, tag) => new Element(tag),
    createDocumentFragment: () => new Element("fragment"),
    createTextNode: (value) => new Text(value),
    /* kept by kind, so a check can send a key (`_on.keydown`) */
    _on: {},
    addEventListener(kind, fn) { (doc._on[kind] = doc._on[kind] || []).push(fn); },
    getElementById: (id) => byId[id] || (byId[id] = new Element('div')),
    querySelector: () => null,
    querySelectorAll: () => [],
    documentElement: { style: { setProperty() {} }, setAttribute() {} },
    head: new Element('head')
  };
  /* The views are the manifest's, as the served page has them (app/views.json, c-634):
     `opts.views` stands in for a page that has none (the plan page, the Console). */
  const manifest = path.join(appDir, 'views.json');
  const win = {
    Keel: {}, innerHeight: 844,
    KEEL_VIEWS: opts.views !== undefined ? opts.views
      : fs.existsSync(manifest) ? JSON.parse(fs.readFileSync(manifest, 'utf8')) : undefined,
    /* a page's popstate listeners are kept, so `history.back()` can walk back through them */
    _pop: [],
    addEventListener(kind, fn) { if (kind === 'popstate') win._pop.push(fn); },
    matchMedia: () => ({ matches: !!opts.desk }),
    /* a caller that set its own `location` (the plan route reads its path) keeps it */
    location: globalThis.location || { search: '', pathname: '/' },
    URLSearchParams: function () { this.get = () => null; },
    confirm: () => true
  };
  /* `opts.storage` is a real one ({getItem, setItem, removeItem}) for a page that must
     remember something; the default remembers nothing. */
  const store = opts.storage || { getItem: () => null, setItem() {}, removeItem() {} };
  /* History moves the stand-in location, so what a page writes to the URL can be read back
     (`K._pushed` counts the entries it pushed). */
  const moveTo = (url) => {
    const at = String(url).indexOf('?');
    win.location.pathname = at < 0 ? String(url) : String(url).slice(0, at);
    win.location.search = at < 0 ? '' : String(url).slice(at);
  };
  const stack = [];
  const here = () => win.location.pathname + (win.location.search || '');
  /* `opts.history(win, moveTo)` is a caller's own history (one with states, Forward and
     `go`, as tests/fixtures/settings-leave.js needs); the default walks back only. */
  const history = opts.history ? opts.history(win, (url) => moveTo(url)) : {
    pushState(a, b, url) { stack.push(here()); moveTo(url); win.Keel._pushed = (win.Keel._pushed || 0) + 1; },
    replaceState(a, b, url) { moveTo(url); },
    /* synchronous here, where a browser's is not: the entry before, then every popstate listener */
    back() { if (stack.length) { moveTo(stack.pop()); win._pop.forEach((fn) => fn({})); } }
  };
  modules.forEach((name) => {
    const source = fs.readFileSync(path.join(appDir, name), 'utf8');
    new Function('window', 'document', 'setInterval', 'setTimeout', 'clearTimeout',
                 'requestAnimationFrame', 'fetch', 'history', 'localStorage', 'sessionStorage',
                 'EventSource', 'location', source)(
      /* setTimeout is a stub that never fires, unless a page gives itself `_setTimeout`,
         which is then handed what the page scheduled */
      win, doc, () => 0, (fn, ms) => (win.Keel && win.Keel._setTimeout ? win.Keel._setTimeout(fn, ms) : 0), () => 0, () => 0, opts.fetch || (() => Promise.resolve({ json: () => ({}) })),
      history, store, store, opts.EventSource, win.location);
  });
  const K = win.Keel;
  K._win = win;
  K._doc = doc;
  return K;
}

/* A card as the state document carries one, with every key the renderers read. */
function card(id, extra) {
  const base = {
    id, space: 'personal', title: id + ' title', brief: '', autonomy: 'attended', repo: 'keel',
    model: 'opus', stage: 'inbox', blocked_reason: null, session_id: null, plan_ref: null,
    output_ref: null, parent: null, after: null, topic: null, options: {},
    created_at: '2026-09-20T10:00:00+00:00', updated_at: '2026-09-23T10:00:00+00:00',
    derived: { plan_gate: false, outcome_gate: false, needs_you: false, kind: 'house',
               startable: false, parent_stage: null, tracking: false, tracking_tally: '',
               follow_ups: [], archived: false, backlog: false, backlog_override: null,
               backlog_since: null, relays: [], voice_hold: null, notice: false,
               gate_since: null },
    last_event: null, last_said: null, links: {}, house: null, children: [], idle: null
  };
  const out = Object.assign(base, extra || {});
  out.derived = Object.assign(base.derived, (extra || {}).derived || {});
  return out;
}

/* The state document around a list of cards. */
/* What `/api/state`'s space entries carry as `terms` (keel/terms.py, c-630): the core's
   defaults for personal, the work pack's words for work. The deck keeps no copy of them. */
const NEUTRAL = { ticket: 'ticket', tickets: 'tickets', ticket_ref: null, change: 'pull request', changes: 'pull requests',
                  change_short: 'PR', changes_short: 'PRs', tracker_name: 'the tracker', codehost_name: 'the code host' };
const TERMS = { personal: NEUTRAL, work: Object.assign({}, NEUTRAL, { ticket: 'story', tickets: 'stories', ticket_ref: 'st-<n>' }) };

function state(cards, extra) {
  return Object.assign({
    now: '2026-09-24T10:00:00+00:00', cards, needs_you: cards.filter((c) => c.derived.needs_you).map((c) => c.id),
    running: [], backlog: [], houses: [], waiting: {},
    drain: { host: 'mac', at: '2026-09-24T09:59:40+00:00', age_seconds: 20, text: 'drain: idle', alive: true },
    usage: { available: false, windows: [] }, segments: [],
    spaces: { personal: { adapter: null, repos: ['keel'], options: [], verbs: { card: [] }, topics: [], counts: {}, terms: TERMS.personal },
              work: { adapter: null, repos: [], options: [], verbs: { card: [] }, topics: [], counts: {}, terms: TERMS.work } },
    providers: {}, config: { houses_max: 3, drain_paused: false },
    health: { level: 'green', reasons: [], services: [] }
  }, extra || {});
}

module.exports = { Element, Text, load, card, state, TERMS, all, byClass, buttons, labels, labelOf, hasClass, classes, wrap };
