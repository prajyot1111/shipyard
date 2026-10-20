/* The deck's DOM morph, checked outside a browser.
 *
 * `K.morph` is the one piece of the render pass that decides whether the page changes or
 * reloads, and it is pure structure: given a live tree and a freshly built one it must
 * change only what differs. That is testable without a browser, so it is tested, against
 * a DOM stand-in small enough to read in one sitting (below): nodes, attributes, children,
 * insertBefore and removeChild, which is the whole of what the morph touches.
 *
 * Usage: node deck-morph.js <path to ui.core.js>
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const fs = require('fs');

/* ---------- the DOM stand-in ---------- */
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

function Element(tag) {
  Node.call(this, 1);
  this.nodeName = String(tag).toUpperCase();
  this.tagName = this.nodeName;
  this.attrs = {};
}
Element.prototype = Object.create(Node.prototype);
Element.prototype.getAttribute = function (name) {
  return name in this.attrs ? this.attrs[name] : null;
};
Element.prototype.setAttribute = function (name, value) { this.attrs[name] = String(value); };
Element.prototype.removeAttribute = function (name) { delete this.attrs[name]; };
Element.prototype.hasAttribute = function (name) { return name in this.attrs; };
Object.defineProperty(Element.prototype, 'attributes', {
  get: function () {
    return Object.keys(this.attrs).map((name) => ({ name: name, value: this.attrs[name] }));
  }
});
Object.defineProperty(Element.prototype, 'className', {
  get: function () { return this.attrs['class'] || ''; },
  set: function (value) { this.attrs['class'] = String(value); }
});
Object.defineProperty(Element.prototype, 'textContent', {
  get: function () { return this.childNodes.map((n) => (n.nodeType === 3 ? n.nodeValue : n.textContent)).join(''); },
  set: function (value) {
    this.childNodes.slice().forEach((n) => this.removeChild(n));
    this.appendChild(new Text(value));
  }
});

const doc = {
  activeElement: null,
  visibilityState: 'hidden',
  createElement: (tag) => new Element(tag),
  createTextNode: (value) => new Text(value),
  addEventListener() {}, getElementById: () => null, querySelector: () => null,
  querySelectorAll: () => [], documentElement: { style: { setProperty() {} }, setAttribute() {} },
  head: new Element('head')
};
const win = {
  Keel: {}, addEventListener() {}, matchMedia: () => ({ matches: true }),
  location: { search: '', pathname: '/' }, URLSearchParams: function () { this.get = () => null; }
};

/* ---------- the module under test ---------- */
const source = fs.readFileSync(process.argv[2], 'utf8');
new Function('window', 'document', 'setInterval', 'setTimeout', 'clearTimeout',
             'requestAnimationFrame', 'fetch', 'history', 'localStorage', 'sessionStorage', source)(
  win, doc, () => 0, () => 0, () => 0, () => 0, () => Promise.resolve(),
  { pushState() {}, replaceState() {} },
  { getItem: () => null, setItem() {}, removeItem() {} },
  { getItem: () => null, setItem() {}, removeItem() {} });

const K = win.Keel;
const el = K.el;
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }

/* A host with `next`'s children morphed into it, and the host itself. */
function host(children) {
  const node = new Element('div');
  K.add(node, children);
  return node;
}
function into(live, children) {
  const next = new Element('div');
  K.add(next, children);
  K.morph(live, next);
  return live;
}
function kids(node) { return node.childNodes; }

/* ---------- 1. a text change is a text change and nothing else ---------- */
(function () {
  const live = host(el('p', { text: 'before' }));
  const was = kids(live)[0];
  const wasText = was.childNodes[0];
  into(live, el('p', { text: 'after' }));
  check('a text change keeps the element', kids(live)[0] === was);
  check('a text change keeps the text node', was.childNodes[0] === wasText);
  check('a text change writes the new text', was.textContent === 'after');
})();

/* ---------- 2. attributes are added and removed, never rewritten wholesale ---------- */
(function () {
  const live = host(el('div', { class: 'row', title: 'gone' }));
  const was = kids(live)[0];
  into(live, el('div', { class: 'row on', 'data-x': '1' }));
  check('an attribute is updated', was.getAttribute('class') === 'row on');
  check('an attribute is added', was.getAttribute('data-x') === '1');
  check('an attribute the new tree dropped is removed', was.getAttribute('title') === null);
  check('the node itself is kept through an attribute change', kids(live)[0] === was);
})();

/* ---------- 3. a keyed reorder moves the same nodes ---------- */
(function () {
  const rows = ['a', 'b', 'c'].map((id) => el('tr', { 'data-key': id, text: id }));
  const live = host(rows);
  const before = kids(live).slice();
  into(live, ['c', 'a', 'b'].map((id) => el('tr', { 'data-key': id, text: id })));
  const after = kids(live);
  check('a keyed reorder keeps every node', after[0] === before[2] && after[1] === before[0] && after[2] === before[1]);
  check('a keyed reorder leaves the count alone', after.length === 3);
})();

/* ---------- 4. a keyed row that is gone is removed, a new one is inserted ---------- */
(function () {
  const live = host(['a', 'b', 'c'].map((id) => el('li', { 'data-key': id })));
  const kept = kids(live)[2];
  into(live, ['d', 'c'].map((id) => el('li', { 'data-key': id })));
  check('a removed key is gone', kids(live).length === 2);
  check('a surviving key is the same node', kids(live)[1] === kept);
  check('a new key is a new node', kids(live)[0].getAttribute('data-key') === 'd');
})();

/* ---------- 5. an unkeyed insert matches the rest by position ---------- */
(function () {
  const live = host([el('span', { text: 'one' }), el('span', { text: 'two' })]);
  const first = kids(live)[0], second = kids(live)[1];
  into(live, [el('span', { text: 'one' }), el('span', { text: 'one and a half' }), el('span', { text: 'two' })]);
  check('an unkeyed insert keeps the first node', kids(live)[0] === first);
  check('an unkeyed insert reuses the second slot in place', kids(live)[1] === second);
  check('an unkeyed insert grows the list', kids(live).length === 3);
  check('an unkeyed insert says the new text', kids(live).map((n) => n.textContent).join('|') === 'one|one and a half|two');
})();

/* ---------- 6. a different tag in the same slot is a new node ---------- */
(function () {
  const live = host(el('span', { text: 'x' }));
  const was = kids(live)[0];
  into(live, el('div', { text: 'x' }));
  check('a tag change replaces the node', kids(live)[0] !== was && kids(live)[0].nodeName === 'DIV');
  check('a tag change leaves nothing behind', kids(live).length === 1);
})();

/* ---------- 7. a skip subtree belongs to whoever drew it, not to the pass ----------
 * The render pass builds the skip node EMPTY (the board's `.bframe-body` is `el('div',
 * {class: 'bframe-body empty', 'data-morph': 'skip'})` and nothing else), so "morph it
 * anyway" would mean deleting what its owner drew into it. There is no condition on this
 * and no hash: the node, its attributes and everything under it are the owner's. Only the
 * handlers are carried, because those are the pass's and a stale closure is a live bug. */
(function () {
  let said = '';
  const live = host(el('div', { class: 'bframe-body empty', 'data-morph': 'skip',
                                onclick: function () { said = 'first'; } },
                              el('svg', { class: 'drawn' })));
  const body = kids(live)[0];
  body.className = 'bframe-body kind-graph';          // what `mount` did to it
  body.setAttribute('data-panned', 'yes');            // what his finger did to it
  into(live, el('div', { class: 'bframe-body empty', 'data-morph': 'skip',
                         onclick: function () { said = 'second'; } }));
  check('a skip keeps its children', body.childNodes.length === 1);
  check('a skip keeps the class its owner set', body.getAttribute('class') === 'bframe-body kind-graph');
  check('a skip keeps what the page set on it by hand', body.getAttribute('data-panned') === 'yes');
  check('a skip is still the same node', kids(live)[0] === body);
  body.onclick();
  check('a skip still takes the new pass handler', said === 'second');
})();

/* ---------- 8. handlers are carried onto the kept node ---------- */
(function () {
  let said = '';
  const live = host(el('button', { 'data-key': 'b', onclick: function () { said = 'first'; } }));
  const was = kids(live)[0];
  was.onclick();
  check('the first pass wired its own handler', said === 'first');
  into(live, el('button', { 'data-key': 'b', onclick: function () { said = 'second'; } }));
  check('the kept node is the same node', kids(live)[0] === was);
  was.onclick();
  check('the kept node runs the new pass handler', said === 'second');
  into(live, el('button', { 'data-key': 'b' }));
  check('a handler the new pass dropped is cleared', was.onclick === null);
})();

/* ---------- 9. a field he is typing in is his ---------- */
(function () {
  const live = host(el('input', { 'data-key': 'q', value: 'ab' }));
  const field = kids(live)[0];
  check('the field starts with the value it was built with', field.value === 'ab');
  doc.activeElement = field;
  field.value = 'abc';                                   // what he typed
  into(live, el('input', { 'data-key': 'q', value: 'ab' }));
  check('a focused field keeps what he typed', field.value === 'abc');
  doc.activeElement = null;
  into(live, el('input', { 'data-key': 'q', value: 'zz' }));
  check('a field he is not in takes the new value', field.value === 'zz');
})();

/* ---------- 10. a child list emptied is emptied ---------- */
(function () {
  const live = host([el('p', {}), el('p', {})]);
  into(live, null);
  check('an empty pass empties the host', kids(live).length === 0);
})();

/* ---------- 11. an unkeyed mismatch spends its slot rather than sliding the rest ----------
 * The shipping case is `app/ui.atlas.js`: a panel head whose FIRST child is a `<button>`
 * on the phone with a page open and a `<span>` everywhere else, followed by two unkeyed
 * spans that never change. Matching unkeyed children strictly by ordinal is what keeps the
 * spacer and the title on their own nodes when that first child flips tag. Sliding the
 * cursor onto the next fresh sibling instead would hand the spacer the title's node and
 * every sibling after it would be off by one for the rest of the list. */
(function () {
  const live = host([el('span', { class: 'label', text: 'head' }),
                     el('span', { class: 'spacer' }),
                     el('span', { class: 'mono', text: 'title' })]);
  const [head, spacer, title] = kids(live);
  spacer.__mark = 'the spacer';
  title.__mark = 'the title';
  into(live, [el('button', { class: 'btn sm', text: 'back' }),
              el('span', { class: 'spacer' }),
              el('span', { class: 'mono', text: 'another title' })]);
  const now = kids(live);
  check('the mismatched slot is a new node of the new tag',
        now[0] !== head && now[0].nodeName === 'BUTTON');
  check('the old node in that slot is gone', !document_contains(live, head));
  check('the sibling after it is still its own node', now[1] === spacer && now[1].__mark === 'the spacer');
  check('and so is the one after that', now[2] === title && now[2].__mark === 'the title');
  check('the list did not grow or shrink', now.length === 3);
  check('the survivors say the new text', now.map((n) => n.textContent).join('|') === 'back||another title');

  /* The same list back again: the button becomes a span and the two hold their nodes. */
  into(live, [el('span', { class: 'label', text: 'head' }),
              el('span', { class: 'spacer' }),
              el('span', { class: 'mono', text: 'title' })]);
  const back = kids(live);
  check('flipping the tag back keeps the siblings again',
        back[1] === spacer && back[2] === title && back.length === 3);
})();

function document_contains(root, node) {
  return root.childNodes.indexOf(node) >= 0;
}

process.stdout.write(JSON.stringify(fails.length ? { ok: false, failed: fails } : { ok: true }));
