/* The card tree on the deck: a big card's outline, a slice's place in it, the Assign tree
 * sheet, and the queue's order.
 *
 * NOTHING HERE WORKS THE TREE OUT. The steps, what each slice still waits for, `next` and
 * `unblocks` are `derived.tree` (keel/tree.py), and the queue is the state document's
 * `queue`: the same computation `kb tree` and `kb queue` print and the drain follows, so
 * the deck and the voice cannot tell him two orders. What this module adds is the shape:
 *
 * - THE TREE FIRST on a big card. The outline sits under the head, above every button, so
 *   the phone's first screen is the tree (it used to be a flat list below six buttons, the
 *   plan and the brief). Slices by step; done slices fold into one line he can open;
 *   follow-ups listed apart, never as slices.
 * - A SLICE KNOWS ITS PLACE: its step, what it waits for (each with its own words), and
 *   what it unblocks.
 * - ASSIGN TREE asks the board for a dry run first and shows the counts in a sheet, so he
 *   sees how many start now and how many wait before he confirms.
 * - ASSIGNED IS THE QUEUE: the Cards list numbers assigned cards in the drain's order. */
(function (K) {
  'use strict';

  var el = K.el, App = K.App;

  function treeOf(c) { return c && c.derived ? c.derived.tree : null; }
  /* A card these rows name and the state does not hold: a done one comes behind the first
     draw (c-549), so until the done part lands it is loading, not elsewhere. */
  function missing() { return K.doneHeld() ? 'not in this space' : 'loading'; }
  function slices(tree) {
    var out = [];
    (tree ? tree.steps : []).forEach(function (g) { g.cards.forEach(function (n) { out.push(n); }); });
    return out;
  }

  /* ---------- one slice row ---------- */
  function nextPill() { return K.pill('next', 'next'); }
  function unblocks(n) {
    return n.unblocks ? el('span', { class: 'unb', text: 'unblocks ' + n.unblocks }) : null;
  }
  function waits(n) {
    return n.waiting_for.length ? el('span', { class: 'sw wait', text: 'waits for ' + n.waiting_for.join(', ') }) : null;
  }
  /* The card's own words (the three the rest of the deck says) when it has any; an inbox
     slice has none, so it says that it is not assigned. */
  function stateWords(n, card) {
    var words = card ? K.wordsOf(card) : [];
    if (n.stage === 'inbox') return [el('span', { class: 'sw plain', text: 'not assigned' })];
    /* a slice the three words have nothing to say about (no house listed yet) still says
       where it is, so a row never stands there wordless */
    if (!words.length && !n.next && !n.waiting_for.length) words = [el('span', { class: 'sw plain', text: n.stage })];
    return words;
  }
  function sliceRow(n) {
    var card = K.byId(n.id);
    return el('button', { class: 'treeslice' + (card && card.derived.needs_you ? ' need' : '')
        + (n.blocked ? ' blocked' : ''), 'data-key': n.id, onclick: function () { K.select(n.id); } },
      el('span', { class: 'r1' }, el('span', { class: 'id', text: n.id }), el('span', { class: 'name', text: n.title })),
      el('span', { class: 'r2' }, stateWords(n, card), n.next ? nextPill() : null, waits(n), unblocks(n)));
  }

  /* ---------- the outline of a big card ---------- */
  /* Done slices fold into one line per step; review stays shown, since it is a gate. The
     fold is his to open, and it is kept across the poll's redraw like a clipped brief. */
  function stepRows(c, g) {
    var done = g.cards.filter(function (n) { return n.stage === 'done'; });
    var rest = g.cards.filter(function (n) { return n.stage !== 'done'; });
    var key = 'tree-done:' + c.id + ':' + g.step, open = K.keepFlag(key);
    var rows = [];
    if (done.length && !open) {
      rows.push(el('button', { class: 'treedone', 'data-key': key,
        onclick: function () { K.keepFlag(key, true); K.renderBody(); } },
        el('span', { text: done.length + ' done · ' + done.map(function (n) { return n.id; }).join(', ') }),
        el('span', { class: 'chev', text: '›' })));
    } else {
      done.forEach(function (n) { rows.push(sliceRow(n)); });
    }
    rest.forEach(function (n) { rows.push(sliceRow(n)); });
    return rows;
  }
  function stepLabel(g, first) {
    var can = g.cards.some(function (n) { return n.next; });
    return 'Step ' + g.step + (first && can ? ' · can start' : '');
  }
  function followUps(tree) {
    if (!tree.follow_ups.length) return null;
    return [el('div', { class: 'treestep', 'data-key': 'follow-label', text: 'Follow-ups · ' + tree.follow_ups.length }),
      el('div', { class: 'treerows', 'data-key': 'follow' }, tree.follow_ups.map(function (id) {
        var k = K.byId(id);
        return el('button', { class: 'treeslice treefollow', 'data-key': id, onclick: function () { K.select(id); } },
          el('span', { class: 'r1' }, el('span', { class: 'id', text: id }),
            el('span', { class: 'name', text: k ? k.title : missing() })));
      }))];
  }
  function assignButton(c, tree) {
    if (!tree.unassigned) return null;
    return K.actionBtn('Assign tree (' + tree.unassigned + ')', { verb: 'assign', id: c.id, dry_run: true },
      { cls: 'primary', done: function (r) { openAssign(c, r); return ''; } });
  }
  /* The Assign tree button for a card, or null (no tree, nothing left to assign). `bare`
     leaves it out of the tree's head: the phone pane puts it in its action row instead. */
  function assignTreeButton(c) { var tree = treeOf(c); return tree ? assignButton(c, tree) : null; }
  function treeSection(c, bare) {
    var tree = treeOf(c);
    if (!tree) return null;
    var n = slices(tree).length;
    return el('div', { class: 'tree', 'data-key': 'tree' },
      el('div', { class: 'treehead' },
        el('span', { class: 'label', text: 'Tree · ' + n + (n === 1 ? ' slice' : ' slices') }),
        el('span', { class: 'spacer' }), bare ? null : assignButton(c, tree)),
      tree.steps.map(function (g, i) {
        return [el('div', { class: 'treestep', 'data-key': 'step-' + g.step, text: stepLabel(g, i === 0) }),
          el('div', { class: 'treerows', 'data-key': 'rows-' + g.step }, stepRows(c, g))];
      }),
      followUps(tree));
  }

  /* ---------- a slice's place ---------- */
  function nodeIn(tree, id) {
    return slices(tree).filter(function (n) { return n.id === id; })[0] || null;
  }
  function waitRow(id, node) {
    var card = K.byId(id);
    return el('button', { class: 'waitrow', 'data-key': 'wait-' + id, onclick: function () { K.select(id); } },
      el('span', { class: 'id', text: id }),
      el('span', { class: 'name', text: card ? card.title : missing() }),
      card ? K.wordsOf(card) : null,
      node && node.next ? nextPill() : null);
  }
  function placeSection(c) {
    var parent = c.parent ? K.byId(c.parent) : null, tree = treeOf(parent);
    var node = tree ? nodeIn(tree, c.id) : null;
    if (!node) return null;
    var below = slices(tree).filter(function (n) { return n.after.indexOf(c.id) >= 0; });
    return el('div', { class: 'intree', 'data-key': 'intree' },
      el('span', { class: 'label', text: 'In its tree' }),
      el('div', { class: 'ink2', text: 'Step ' + node.step + ' of ' + tree.steps.length
        + (node.next ? ' · could start now' : '') }),
      node.after.length ? [el('span', { class: 'label', text: 'Waits for' }),
        node.after.map(function (id) { return waitRow(id, nodeIn(tree, id)); })] : null,
      node.unblocks ? el('div', { class: 'ink2', text: 'Unblocks ' + node.unblocks
        + (below.length ? ': ' + below.map(function (n) { return n.id; }).join(', ') : '') }) : null);
  }

  /* ---------- Assign tree: the counts, then his confirm ---------- */
  function openAssign(c, preview) { App.sheet = { kind: 'assign', id: c.id, preview: preview }; K.renderSheet(); }
  function closeAssign() { App.sheet = null; K.renderSheet(); }
  function count(n, label, sub, cls) {
    return el('div', { class: 'tcount ' + cls }, el('span', { class: 'n', text: n + ' ' + label }),
      sub ? el('span', { class: 'l', text: sub }) : null);
  }
  function assignSheet(s) {
    var c = K.byId(s.id), p = s.preview || {};
    if (!c) return el('div', { class: 'sheet' });
    var total = (p.assigned || []).length, waiting = p.wait || [];
    return el('div', { class: 'sheet', 'data-key': 'sheet-assign' },
      el('div', { class: 'sheet-head' }, el('span', { text: 'Assign the tree of ' + c.id }),
        el('span', { class: 'spacer' }), el('button', { onclick: closeAssign }, '✕')),
      el('div', { class: 'sheet-body' },
        el('div', { class: 'title', text: c.title }),
        el('div', { class: 'ink2', text: total + (total === 1 ? ' slice' : ' slices') + ' not assigned yet.' }),
        el('div', { class: 'tcounts' },
          count((p.start_now || []).length, 'start now', (p.start_now || []).join(', '), 'good'),
          count(waiting.length, 'wait', waiting.map(function (w) {
            return w.id + (w.waiting_for.length ? ' for ' + w.waiting_for.join(', ') : ' (blocked)');
          }).join('; '), 'warn'),
          (p.plan_gate || []).length ? count(p.plan_gate.length, 'stop at their plan gate first',
            'attended: you approve each plan', 'acc') : null),
        el('div', { class: 'ink2', text: 'The drain follows the tree from here, in queue order. '
          + 'Slices filed later are not included.' })),
      el('div', { class: 'sheet-foot' },
        el('button', { class: 'btn', onclick: closeAssign }, 'Cancel'),
        K.actionBtn('Assign ' + total, { verb: 'assign', id: c.id, ids: p.assigned || [] },
          { cls: 'primary', done: function (r) { closeAssign(); return r && r.assigned
            ? r.assigned.length + ' assigned: ' + r.start_now.length + ' start now, ' + r.wait.length + ' wait' : ''; } })));
  }

  /* ---------- the queue ---------- */
  /* His "put this first": a slice moves to the front of its tree, anything else (a whole
     tree included) to the front of the queue. Offered on a card the queue can place. */
  function nextActions(c) {
    var tracking = K.tracking(c), stage = K.stageOf(c);
    if (c.derived.archived || (!tracking && c.stage !== 'assigned') || (tracking && stage === 'done')) return [];
    var out = [K.actionBtn(c.parent ? 'Move to front of tree' : 'Move to front of queue', { verb: 'next', id: c.id })];
    if (c.rank !== null && c.rank !== undefined) {
      out.push(K.actionBtn('Back in filing order', { verb: 'next', id: c.id, clear: true }));
    }
    return out;
  }
  /* A card's place in the drain's queue, 1-based, or 0 when it is not queued. */
  function queuePos(c) { return ((App.data && App.data.queue) || []).indexOf(c.id) + 1; }
  function inQueueOrder(list) {
    return list.slice().sort(function (a, b) {
      var pa = queuePos(a) || 1e9, pb = queuePos(b) || 1e9;
      return pa - pb;
    });
  }

  K.treeSection = treeSection; K.placeSection = placeSection; K.assignSheet = assignSheet;
  K.assignTreeButton = assignTreeButton;
  K.nextActions = nextActions; K.queuePos = queuePos; K.inQueueOrder = inQueueOrder;
})(window.Keel);
