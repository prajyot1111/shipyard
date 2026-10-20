/* DELETING A BOARD (lane BD, 2026-09-24): "I need an option to delete boards too."
 *
 * Three places ask for it and one confirm answers all three (BD-3):
 * - the board page's header menu (Delete board),
 * - a small menu on every row of the Saved list, rows inside an open stack included,
 * - a stack's own menu (Delete all N boards), with its own confirm.
 * And Include deleted, in the board list's Filter, adds the trash with Restore on every row.
 *
 * THE CONFIRM NAMES WHERE THE BOARD IS USED (BD-2). Before it is drawn with a button, the page
 * asks `GET /api/boards/uses?ids=...` (`keel/boarduses.py`) which open and recent plans and
 * outcomes embed it, and says so: "b-006 is embedded in c-272's outcome." with "Delete
 * anyway". Everything goes to a trash he restores from for 30 days, and the confirm says that
 * too, so a delete is never a surprise and never final on a tap.
 *
 * Every menu item and button carries its line from `K.boardTip` (ui.tips.js), as a `title`
 * on the desk and printed under the item's name, because the phone has no hover. The
 * sentences the confirm says are `lines`, pure and exported, so they are tested outside a
 * browser (`tests/fixtures/board-delete.js`).
 */
(function (K) {
  'use strict';

  var el = K.el;
  var D = null;                 // the open confirm
  var M = { open: null };       // which menu is open, by its key
  var T = { rows: null, loading: false };   // the trash, for Include deleted

  /* ---------- the words (pure) ---------- */
  function joined(names) {
    if (names.length < 2) return names[0] || '';
    return names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1];
  }
  function docName(use) { return use.card + '\'s ' + use.doc; }
  function whose(row) {
    var source = row.source || {};
    return source.kind === 'card' ? source.card + '\'s' : 'Harbor\'s';
  }
  function embedded(rows, uses) {
    return rows.filter(function (r) { return ((uses || {})[r.id] || []).length; });
  }
  /* What the confirm says, one sentence per fact: where each board is embedded, and which
     board was live. */
  function lines(rows, uses) {
    var out = [];
    embedded(rows, uses).forEach(function (r) {
      out.push(r.id + ' is embedded in ' + joined(uses[r.id].map(docName)) + '.');
    });
    if (uses && !out.length) {
      out.push(rows.length > 1 ? 'No open or recent plan or outcome embeds these boards.'
                               : 'No open or recent plan or outcome embeds it.');
    }
    rows.filter(function (r) { return r.live && !r.closed; }).forEach(function (r) {
      out.push(r.id + ' is ' + whose(r) + ' live board: the next push continues another or starts a new one.');
    });
    return out;
  }
  function heading(rows, label) {
    if (rows.length === 1) return 'Delete ' + rows[0].id + '?';
    return 'Delete all ' + rows.length + ' boards' + (label ? ' of ' + label : '') + '?';
  }
  function button(rows, uses) {
    var all = rows.length > 1 ? 'Delete all ' + rows.length : 'Delete';
    return embedded(rows, uses).length ? all + ' anyway' : all;
  }
  function said(rows) {
    return (rows.length === 1 ? rows[0].id + ' is' : rows.length + ' boards are') +
      ' in the trash: Include deleted on the board list restores it for 30 days';
  }

  /* ---------- the confirm ---------- */
  function ask(rows, opts) {
    opts = opts || {};
    var ids = rows.map(function (r) { return r.id; });
    D = { rows: rows, ids: ids, label: opts.label || '', uses: null,
          failed: false, focused: false };
    M.open = null;
    render();
    fetch('/api/boards/uses?ids=' + encodeURIComponent(ids.join(',')), { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!D || D.ids !== ids) return;
        D.uses = d.uses || {};
        render();
      })
      .catch(function () { if (D && D.ids === ids) { D.failed = true; render(); } });
  }
  function close() { D = null; render(); }

  function doDelete(ev) {
    var mine = D;
    K.act({ verb: 'board.delete', ids: mine.ids }, function () {
      close();
      if (K.boardAfterDelete) K.boardAfterDelete(mine.ids);
      T.rows = null;
      return said(mine.rows);
    }, ev.currentTarget);
  }

  function body() {
    var out = [el('ul', { class: 'bconfirm-list' }, D.rows.slice(0, 8).map(function (r) {
      return el('li', { 'data-key': r.id },
        el('span', { class: 'mono t11 ink3', text: r.id + ' ' }),
        el('span', { text: r.title || 'Untitled board' }));
    }), D.rows.length > 8 ? el('li', { class: 'ink3', text: 'and ' + (D.rows.length - 8) + ' more' }) : null)];
    if (D.failed) out.push(el('p', { class: 'bconfirm-warn', text: 'The deck could not say which documents embed it.' }));
    else if (!D.uses) out.push(el('p', { class: 'ink3', text: 'Looking for plans and outcomes that embed it...' }));
    else {
      lines(D.rows, D.uses).forEach(function (line, i) {
        var warn = i < embedded(D.rows, D.uses).length;
        out.push(el('p', { class: warn ? 'bconfirm-warn' : '', text: line }));
      });
    }
    out.push(el('p', { class: 'ink2', text: 'It goes to the trash: Include deleted on the board ' +
      'list shows it with Restore for 30 days, then it is purged.' }));
    return out;
  }

  function render() {
    if (!D) { K.paint('modal', null); return; }
    var ready = !!D.uses || D.failed;
    var card = el('div', { class: 'modal-card bconfirm', role: 'dialog', 'aria-modal': 'true',
      'aria-labelledby': 'bconfirm-title', 'data-key': 'bconfirm-' + D.ids.join('-'),
      onclick: function (ev) { ev.stopPropagation(); } },
      el('div', { class: 'modal-head' },
        el('h3', { class: 'title', id: 'bconfirm-title', text: heading(D.rows, D.label) })),
      el('div', { class: 'modal-body' }, body()),
      el('div', { class: 'modal-foot' },
        el('button', { class: 'btn', 'data-key': 'cancel', onclick: close }, 'Cancel'),
        el('span', { class: 'spacer' }),
        ready ? tip(K.faceBtn(button(D.rows, D.uses), { verb: 'board.delete', ids: D.ids }, 'crit',
                              doDelete), D.rows.length > 1 ? 'board-delete-stack' : 'board-delete')
              : null));
    K.paint('modal', el('div', { class: 'modal bconfirm-scrim', onclick: close }, card));
    if (!D.focused) {
      D.focused = true;
      var cancel = document.querySelector('.bconfirm [data-key="cancel"]');
      if (cancel) cancel.focus();
    }
  }

  function tip(node, key) {
    var line = K.boardTip ? K.boardTip(key) : '';
    if (line && node && node.setAttribute) node.setAttribute('title', line);
    return node;
  }

  /* ---------- the menus ---------- */
  /* One small button, 44px on the phone, that opens a short list of actions under it. The
     list is drawn by the page's own render pass, so it is closed by a tap anywhere else and
     by Escape (below). */
  function menu(key, name, items) {
    var open = M.open === key;
    return el('div', { class: 'bmenu-wrap' + (open ? ' open' : ''), 'data-key': 'menu-' + key },
      el('button', { class: 'bmenu-btn', type: 'button', 'data-key': 'menu-button',
        'aria-haspopup': 'menu', 'aria-expanded': open ? 'true' : 'false',
        'aria-label': 'actions for ' + name,
        onclick: function (ev) { ev.stopPropagation(); M.open = open ? null : key; K.renderBody(); } },
        '⋯'),
      open ? el('div', { class: 'bmenu', role: 'menu' }, items.map(function (item) {
        return tip(el('button', { class: 'bmenu-item' + (item.crit ? ' crit' : ''), role: 'menuitem',
          type: 'button', 'data-key': item.key,
          onclick: function (ev) { ev.stopPropagation(); M.open = null; K.renderBody(); item.run(); } },
          el('span', { class: 'bmenu-name', text: item.label }),
          el('span', { class: 'bmenu-line', text: K.boardTip ? K.boardTip(item.key) : '' })), item.key);
      })) : null);
  }

  function deleteItem(rows, label, key) {
    return { key: key, crit: true, label: rows.length > 1 ? 'Delete all ' + rows.length + ' boards' : 'Delete board',
             run: function () { ask(rows, { label: label }); } };
  }
  /* The board page's header: the open board's own menu. */
  function boardMenu(record) {
    return menu('board-' + record.id, record.id, [deleteItem([record], '', 'board-delete')]);
  }
  /* One row of the Saved list. */
  function rowMenu(row) {
    return menu('row-' + row.id, row.id, [deleteItem([row], '', 'board-delete')]);
  }
  /* A stack's header: every board in the group, with its own confirm. */
  function stackMenu(stack) {
    var label = stack.card || stack.title;
    return menu('stack-' + stack.key, label, [deleteItem(stack.rows, label, 'board-delete-stack')]);
  }

  document.addEventListener('click', function () {
    if (M.open) { M.open = null; K.renderBody(); }
  });
  document.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Escape') return;
    if (D) { close(); return; }
    if (M.open) { M.open = null; K.renderBody(); }
  });

  /* ---------- the trash, behind Include deleted ----------
   * The trash is read once, when the board list first needs it (Include deleted is on, or
   * the Filter panel is open and wants its count), and its rows join the list's own through
   * the find bar: they are filtered by the same facets and ADDED under a Deleted heading,
   * never swapped in for the list. */
  function loadTrash() {
    if (T.rows || T.loading) return;
    T.loading = true;
    fetch('/api/boards?deleted=1', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) { T.loading = false; T.rows = d.rows || []; K.renderBody(); })
      .catch(function () { T.loading = false; T.rows = []; K.renderBody(); });
  }
  /* The trash's rows, each marked deleted, or [] while it is being read. */
  function trashRows(wanted) {
    if (wanted) loadTrash();
    return (T.rows || []).map(function (r) { return r.deleted ? r : Object.assign({}, r, { deleted: {} }); });
  }
  function restoreBtn(row) {
    return tip(K.actionBtn('Restore', { verb: 'board.restore', id: row.id }, {
      cls: 'brestore', done: function () {
        T.rows = null;
        if (K.boardAfterRestore) K.boardAfterRestore(row.id);
        return row.id + ' is back on the board list';
      } }), 'board-restore');
  }
  function trashRow(api, r) {
    var gone = r.deleted || {};
    return el('div', { class: 'bsaved-row btrash-row', 'data-key': r.id },
      el('div', { class: 'bsaved-item btrash-item' },
        el('div', { class: 'bsaved-head' },
          el('span', { class: 't ellip', text: r.title || 'Untitled board' }),
          api.chip(r, (r.card || {}).space)),
        el('div', { class: 'sub ink2', text: 'deleted by ' + (gone.by || 'someone') + ' ' + K.ago(gone.at) +
          (r.purge_at ? ', purged ' + String(r.purge_at).slice(0, 10) : '') }),
        el('div', { class: 'bsaved-chips' },
          el('span', { class: 'bchip', text: r.nodes + (r.nodes === 1 ? ' node' : ' nodes') }),
          el('span', { class: 'bchip', text: r.id }))),
      restoreBtn(r));
  }
  /* The Deleted section under the list: the trash rows the find bar kept, most recently
     deleted first, each with Restore. */
  function trashSection(api, rows) {
    var list = (rows || []).slice().sort(function (a, b) {
      return String((b.deleted || {}).at || '').localeCompare(String((a.deleted || {}).at || ''));
    });
    return el('section', { class: 'bsaved-section', 'data-key': 'Deleted' },
      el('h3', { class: 'label', text: 'Deleted' }),
      el('p', { class: 'ink2 t13', text: 'Restorable for 30 days, then the drain purges them.' }),
      !T.rows ? el('div', { class: 'empty', text: 'reading the trash...' })
        : list.length ? list.map(function (r) { return trashRow(api, r); })
          : el('div', { class: 'empty', text: 'nothing deleted matches' }));
  }

  /* ---------- a board that was deleted, opened by its link ---------- */
  function goneView(id, gone, onRestore) {
    var d = gone || {};
    return [el('div', { class: 'empty', text: id + ' was deleted by ' + (d.by || 'someone') + ' ' +
                 K.ago(d.at) + '. It is in the trash until ' + String(d.purge_at || '').slice(0, 10) + '.' }),
            el('div', { class: 'bgone-actions' },
              tip(K.actionBtn('Restore', { verb: 'board.restore', id: id }, {
                cls: 'brestore', done: function () { T.rows = null; onRestore(); return id + ' is back'; } }),
                'board-restore'))];
  }

  K.boardDelete = { lines: lines, heading: heading, button: button, ask: ask, boardMenu: boardMenu,
                    rowMenu: rowMenu, stackMenu: stackMenu, trashRows: trashRows, trashSection: trashSection, goneView: goneView,
                    forgetTrash: function () { T.rows = null; } };
})(window.Keel);
