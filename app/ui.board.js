/* The Board route: the blackboard a house draws on, rendered live.
 *
 * A BOARD IS ONE MODEL SEEN THREE WAYS. One diagram (groups, nodes, edges, marks) with
 * attachments hanging off its nodes and off the board itself, shown as a **diagram**, as an
 * **outline** (the whole thing as a readable document) or as a **walk** (the steps, one at a
 * time, each highlighting its node). There are no frames: a second picture is a second
 * board (`board new`). His words, 2026-09-21: "one view that can be viewed in different
 * ways, like diagrammatic and list, but not multiple frames".
 *
 * `keel/boards.py` decides what may be written; this file decides where it goes on the
 * screen. The two parse the SAME grammar (`docs/atlas/45-board.md`), and
 * `tests/test_boards.py` runs both over one fixture of good and bad lines, so an op added
 * to one side alone fails `make test` rather than his phone.
 *
 * Nothing here trusts a string from a board. Every node is built with `createElement` and
 * `textContent`, and the only HTML this module ever writes is the stylesheet's, which is
 * in `app/ui.css` with the rest of the deck's. A house may have read a hostile page; its
 * output must never run in the origin the approve verbs live in.
 *
 * The route is a PATH: `/board` and `/board/<b-id>`, with `?view=diagram|outline|walk` on
 * the second, because a board is a thing he sends himself a link to and the view he sends
 * is part of what he means. `keel/serve.py` answers both with the page and
 * `app/ui.core.js` reads the path.
 *
 * LIVE is one fetch: `GET /api/board/<id>?since=<line>`, told by the event stream and
 * polled only while the stream is shut, and what comes back is appended. The cursor is a
 * line count over `ops.log`, so neither end holds the other's model.
 *
 * The diagram is laid out by ELK (`app/vendor/elk.bundled.js`), in the browser, layered,
 * RIGHT on the desk and DOWN on the phone. Pan and zoom are ONE transform on one group,
 * never a viewBox rewritten per event, and they go through pointer events so the mouse and
 * the finger are one code path.
 */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  /* ---------- the vocabulary, which is the server's too ----------
   * tests/test_boards.py reads these five arrays out of this file and compares them name
   * by name with `keel/boards.py`. They are written as plain literals for that reason. */
  var OPS = ['board', 'group', 'node', 'edge', 'mark', 'note', 'step', 'table', 'cols',
             'row', 'code', 'lang', 'line', 'path'];
  var ATTACH_KINDS = ['note', 'step', 'table', 'code', 'file'];
  var MARKS = ['accent', 'good', 'warn', 'crit'];
  var ARROWS = ['->', '<->', '--'];
  var ICON_NAMES = ['laptop', 'server', 'cloud', 'database', 'phone', 'mic', 'speaker',
                    'globe', 'network', 'lock', 'key', 'file', 'folder', 'git-branch',
                    'bot', 'user', 'clock', 'list', 'cpu', 'hard-drive', 'shield', 'box',
                    'terminal', 'zap'];
  var ARROW_KIND = { '->': 'to', '<->': 'both', '--': 'none' };
  var FALLBACK_ICON = 'box';
  var BOARD_TARGET = 'board';
  /* The two explicit forms of `board`. A bare title is the TOPIC, and a topic that is not
     this board's topic starts another board: that decision is the SERVER'S (`plan_push`),
     because it is about which board a line lands on and only the store knows what is live.
     This half only has to read the line. */
  var BOARD_MODES = ['new', 'rename'];
  var VIEWS = ['diagram', 'outline', 'walk'];
  var MAX_TEXT = 240, MAX_NAME = 48, MAX_LINE = 800, MAX_CELLS = 6;
  var SVGNS = 'http://www.w3.org/2000/svg';
  var FENCE = '```';

  /* ---------- the parser ----------
   * `null` for a blank, a comment or a stray fence mark, an op object, or `{bad: reason}`.
   * The reason is never shown to him here: the server already recorded it in `skipped.log`
   * when it refused the line, and a line that reached `ops.log` was accepted. This half
   * exists so the deck reads the record the same way the server wrote it. */
  var TOKEN = /"([^"]*)"|(\S+)/g;
  var NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/;
  /* eslint-disable no-control-regex */
  var CONTROL = /[\x00-\x08\x0b-\x1f\x7f]/;
  /* The two ops that went with the frames. Answered by name, exactly as the server answers
     them, so the deck and the store agree that these lines are refused rather than unknown. */
  var RETIRED = { frame: 1, text: 1 };

  function bad(reason) { return { bad: reason }; }

  function tokenize(line) {
    if ((line.match(/"/g) || []).length % 2) return null;
    var out = [], m;
    TOKEN.lastIndex = 0;
    while ((m = TOKEN.exec(line))) {
      out.push(m[1] !== undefined ? { v: m[1], q: true } : { v: m[2], q: false });
    }
    return out;
  }
  function okText(value) { return value.length <= MAX_TEXT && !CONTROL.test(value); }
  function okName(value) { return value.length <= MAX_NAME && NAME_RE.test(value); }

  function cellsOf(rest) {
    var parts = rest.split('|').map(function (s) { return s.trim(); })
      .filter(function (s) { return s.length; });
    if (!parts.length || parts.length > MAX_CELLS) return null;
    return parts.every(okText) ? parts : null;
  }

  /* Where an attachment hangs: the word `board`, or a node id, never quoted. `board` wins
     over a node that happens to be called `board`, which is the server's rule too. */
  function whereOf(token) {
    if (!token || token.q) return null;
    if (token.v === BOARD_TARGET) return BOARD_TARGET;
    return okName(token.v) ? token.v : null;
  }

  function parseNode(t) {
    if (t.length < 4 || t[1].q || t[2].q || !t[3].q) return bad('node wants: node <id> <icon> "label" [in <group>] ["sub label"]');
    if (!okName(t[1].v) || !okText(t[3].v)) return bad('the node id or its label is not a legal one');
    var op = { op: 'node', id: t[1].v, icon: ICON_NAMES.indexOf(t[2].v) >= 0 ? t[2].v : FALLBACK_ICON,
               label: t[3].v, group: null, sub: null };
    var rest = t.slice(4);
    if (rest.length && !rest[0].q && rest[0].v === 'in') {
      if (rest.length < 2 || rest[1].q || !okName(rest[1].v)) return bad('`in` wants the name of a group declared on this board');
      op.group = rest[1].v;
      rest = rest.slice(2);
    }
    if (rest.length) {
      if (rest.length !== 1 || !rest[0].q || !okText(rest[0].v)) return bad('the only thing after a node label or its group is a quoted "sub label"');
      op.sub = rest[0].v;
    }
    return op;
  }

  function parseEdge(t) {
    if ((t.length !== 4 && t.length !== 5) || t[1].q || t[2].q || t[3].q || ARROWS.indexOf(t[2].v) < 0) {
      return bad('edge wants: edge <a> -> <b> ["label"], with -> or <-> or --');
    }
    if (!okName(t[1].v) || !okName(t[3].v)) return bad('an edge names two node ids');
    var op = { op: 'edge', a: t[1].v, b: t[3].v, arrow: ARROW_KIND[t[2].v], label: null };
    if (t.length === 5) {
      if (!t[4].q || !okText(t[4].v)) return bad('an edge label is quoted');
      op.label = t[4].v;
    }
    return op;
  }

  function parsePath(t) {
    if (t.length !== 7 || !t[2].q || t[3].q || t[3].v !== 'size' || !t[4].q ||
        t[5].q || t[5].v !== 'from' || t[6].q) {
      return bad('path wants: path <node|board> "<path>" size "<size>" from <who>');
    }
    var at = whereOf(t[1]);
    if (!at || !okText(t[2].v) || !okText(t[4].v) || !okName(t[6].v)) return bad('the place, the path, the size or the source is not a legal one');
    return { op: 'path', at: at, path: t[2].v, size: t[4].v, from: t[6].v };
  }

  function parseAttached(op, t, field) {
    if (t.length !== 3 || !t[2].q || !okText(t[2].v)) return bad(op + ' wants: ' + op + ' <node|board> "<text>"');
    var at = whereOf(t[1]);
    if (!at) return bad(op + ' hangs on an unquoted <node|board>');
    var out = { op: op, at: at };
    out[field] = t[2].v;
    return out;
  }

  function parseBoard(t) {
    if (t.length === 2 && t[1].q && okText(t[1].v)) return { op: 'board', mode: 'topic', title: t[1].v };
    if (t.length === 3 && !t[1].q && BOARD_MODES.indexOf(t[1].v) >= 0 && t[2].q && okText(t[2].v)) {
      return { op: 'board', mode: t[1].v, title: t[2].v };
    }
    return bad('board wants: board "<title>", or board new|rename "<title>"');
  }

  function parseLine(raw) {
    if (raw === null || raw === undefined) return null;
    if (String(raw).length > MAX_LINE) return bad('the line is too long');
    var text = String(raw).trim();
    if (!text || text.charAt(0) === '#' || text.slice(0, 3) === FENCE) return null;
    var head = text.split(/\s+/)[0];
    if (RETIRED[head]) return bad(head + ' went with the frames');
    if (head === 'cols' || head === 'row') {
      var cells = cellsOf(text.slice(head.length));
      if (!cells) return bad(head + ' wants cells separated by |');
      return head === 'cols' ? { op: 'cols', cols: cells } : { op: 'row', cells: cells };
    }
    var t = tokenize(text);
    if (!t) return bad('it has an unclosed quote');
    if (!t.length) return null;
    if (head === 'board') return parseBoard(t);
    if (head === 'group') {
      if (t.length !== 3 || t[1].q || !t[2].q || !okName(t[1].v) || !okText(t[2].v)) return bad('group wants: group <id> "<label>"');
      return { op: 'group', id: t[1].v, label: t[2].v };
    }
    if (head === 'node') return parseNode(t);
    if (head === 'edge') return parseEdge(t);
    if (head === 'mark') {
      if (t.length !== 3 || t[1].q || t[2].q || MARKS.indexOf(t[2].v) < 0 || !okName(t[1].v)) {
        return bad('mark wants: mark <node> ' + MARKS.join('|'));
      }
      return { op: 'mark', id: t[1].v, status: t[2].v };
    }
    if (head === 'note') return parseAttached('note', t, 'text');
    if (head === 'step') return parseAttached('step', t, 'text');
    if (head === 'table') return parseAttached('table', t, 'title');
    if (head === 'code') return parseAttached('code', t, 'title');
    if (head === 'line') {
      if (t.length !== 2 || !t[1].q || !okText(t[1].v)) return bad('line wants one quoted string');
      return { op: 'line', text: t[1].v };
    }
    if (head === 'lang') {
      if (t.length !== 2 || t[1].q || !okName(t[1].v)) return bad('lang wants one unquoted language name');
      return { op: 'lang', lang: t[1].v };
    }
    if (head === 'path') return parsePath(t);
    return bad('that is not an op');
  }

  /* ---------- the model ----------
   * ONE per board. Permissive on purpose: the caps (twelve nodes, the string lengths) and
   * the rules about where an attachment may hang are the SERVER'S, because a cap the
   * server does not hold is a cap an agent can talk its way past, and a line that reached
   * `ops.log` has already passed them. What this half does is fold what it is given and
   * ignore what does not fit, so a record written by a newer server still draws.
   *
   * `version` is the one number the drawing watches: a graph is laid out again when it
   * moves and left alone when it does not, which is what keeps a push from disturbing a
   * diagram he has zoomed into. */
  function newModel() {
    return { title: '', groups: [], nodes: [], edges: [], attachments: [], version: 0 };
  }
  function nodeBy(model, id) {
    for (var i = 0; i < model.nodes.length; i++) if (model.nodes[i].id === id) return model.nodes[i];
    return null;
  }
  function lastOf(model, kind) {
    for (var i = model.attachments.length - 1; i >= 0; i--) {
      if (model.attachments[i].kind === kind) return model.attachments[i];
    }
    return null;
  }
  function attach(model, kind, at, rest) {
    var item = { n: model.attachments.length + 1, kind: kind, at: at };
    Object.keys(rest || {}).forEach(function (k) { item[k] = rest[k]; });
    model.attachments.push(item);
    return item;
  }
  /* An attachment on a node nobody declared is dropped rather than moved to the board: the
     server refused that line, so a deck that drew it would be showing what the record does
     not say. */
  function placeOf(model, op) {
    if (op.at === BOARD_TARGET) return BOARD_TARGET;
    return nodeBy(model, op.at) ? op.at : null;
  }

  function applyOp(model, op) {
    var at, i, was, node, table, code;
    if (op.op === 'board') { model.title = op.title; model.version++; return; }
    if (op.op === 'group') {
      for (i = 0; i < model.groups.length; i++) {
        if (model.groups[i].id === op.id) { model.groups[i].label = op.label; model.version++; return; }
      }
      model.groups.push({ id: op.id, label: op.label });
    } else if (op.op === 'node') {
      was = nodeBy(model, op.id);
      if (was) { was.icon = op.icon; was.label = op.label; was.group = op.group; was.sub = op.sub; }
      else model.nodes.push({ id: op.id, icon: op.icon, label: op.label, group: op.group, sub: op.sub, mark: null });
    } else if (op.op === 'edge') {
      if (!nodeBy(model, op.a) || !nodeBy(model, op.b)) return;
      model.edges.push({ a: op.a, b: op.b, arrow: op.arrow, label: op.label });
    } else if (op.op === 'mark') {
      node = nodeBy(model, op.id);
      if (node) node.mark = op.status;
    } else if (op.op === 'note' || op.op === 'step') {
      at = placeOf(model, op);
      if (at === null) return;
      attach(model, op.op, at, { text: op.text });
    } else if (op.op === 'table') {
      at = placeOf(model, op);
      if (at === null) return;
      attach(model, 'table', at, { title: op.title, cols: [], rows: [] });
    } else if (op.op === 'code') {
      at = placeOf(model, op);
      if (at === null) return;
      attach(model, 'code', at, { title: op.title, lang: '', lines: [] });
    } else if (op.op === 'path') {
      at = placeOf(model, op);
      if (at === null) return;
      attach(model, 'file', at, { path: op.path, size: op.size, from: op.from });
    } else if (op.op === 'cols' || op.op === 'row') {
      table = lastOf(model, 'table');
      if (!table) return;
      if (op.op === 'cols') table.cols = op.cols;
      else if (table.cols.length) table.rows.push(op.cells);
      else return;
    } else if (op.op === 'lang' || op.op === 'line') {
      code = lastOf(model, 'code');
      if (!code) return;
      if (op.op === 'lang') code.lang = op.lang;
      else code.lines.push(op.text);
    }
    model.version++;
  }

  /* Fold lines onto a model, in place, so a live append costs only the new lines.
     A `board new` line is the SERVER'S business: it started another board, whose ops are in
     that board's own log, so there is nothing for this side to do with it but take the
     title of the board it opened when that board is the one being read. */
  /* A REDRAW (`keel board push --board`, c-604) opens with this marker, and the model starts
     afresh there, in place, as `build` in keel/boards.py does: the board shows the redrawn
     picture alone. In place, so a page folding lines since its cursor redraws too. */
  var REDRAW_MARK = '# redraw ';
  function resetModel(model) {
    model.title = ''; model.groups = []; model.nodes = []; model.edges = []; model.attachments = [];
    model.version++;
  }
  function foldInto(model, lines) {
    (lines || []).forEach(function (raw) {
      if (String(raw).indexOf(REDRAW_MARK) === 0) { resetModel(model); return; }
      var op = parseLine(raw);
      if (op && !op.bad) applyOp(model, op);
    });
    return model;
  }

  function attachmentsOn(model, at) {
    return model.attachments.filter(function (a) { return a.at === at; });
  }
  function stepsOf(model) {
    return model.attachments.filter(function (a) { return a.kind === 'step'; });
  }

  /* ---------- the icons ----------
   * Twenty four stroke primitives, drawn small enough to read at 24px. An unknown name
   * became `box` back in the parser, so nothing here has to guess. */
  var ICONS = {
    laptop: [['rect', 4, 4, 16, 10, 1], ['path', 'M2 18 L4 14 L20 14 L22 18 Z'], ['line', 2, 18, 22, 18]],
    server: [['rect', 4, 3, 16, 7, 1], ['rect', 4, 14, 16, 7, 1], ['fcircle', 7.5, 6.5, 0.9], ['fcircle', 7.5, 17.5, 0.9]],
    cloud: [['path', 'M7 18c-2.2 0-4-1.8-4-4c0-2 1.5-3.7 3.4-4c0.4-2.8 2.8-5 5.6-5c2.9 0 5.3 2.1 5.7 4.9c1.9 0.3 3.3 1.9 3.3 3.8c0 2.4-2 4.3-4.4 4.3H7z']],
    database: [['ellipse', 12, 5, 8, 3], ['line', 4, 5, 4, 17], ['line', 20, 5, 20, 17],
               ['path', 'M4 11a8 3 0 0 0 16 0'], ['path', 'M4 17a8 3 0 0 0 16 0']],
    phone: [['rect', 7, 2, 10, 20, 2], ['line', 10.5, 18, 13.5, 18]],
    mic: [['rect', 9, 2, 6, 11, 3], ['path', 'M5 10v1a7 7 0 0 0 14 0v-1'], ['line', 12, 18, 12, 22], ['line', 9, 22, 15, 22]],
    speaker: [['path', 'M4 9h4l5-4v14l-5-4H4z'], ['path', 'M16 9a4 4 0 0 1 0 6'], ['path', 'M19 6.5a8 8 0 0 1 0 11']],
    globe: [['circle', 12, 12, 9], ['line', 3, 12, 21, 12], ['path', 'M12 3c3.2 3 3.2 15 0 18'], ['path', 'M12 3c-3.2 3-3.2 15 0 18']],
    network: [['circle', 12, 4.5, 2], ['circle', 4.5, 20, 2], ['circle', 19.5, 20, 2],
              ['line', 12, 6.5, 5.5, 18], ['line', 12, 6.5, 18.5, 18]],
    lock: [['rect', 5, 11, 14, 10, 1], ['path', 'M8 11V7a4 4 0 0 1 8 0v4'], ['fcircle', 12, 15.5, 1.2]],
    key: [['circle', 8, 16, 4], ['line', 11, 13, 21, 3], ['line', 17, 7, 19, 9], ['line', 19, 5, 21, 7]],
    file: [['path', 'M6 2h9l5 5v15H6z'], ['path', 'M15 2v5h5'], ['line', 8.5, 13, 15.5, 13], ['line', 8.5, 16.5, 15.5, 16.5]],
    folder: [['path', 'M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z']],
    'git-branch': [['circle', 6, 5, 2], ['circle', 6, 19, 2], ['circle', 18, 15, 2],
                   ['line', 6, 7, 6, 17], ['path', 'M6 12a5 5 0 0 0 5 5h3']],
    bot: [['rect', 5, 8, 14, 11, 2], ['fcircle', 9, 13.3, 1.3], ['fcircle', 15, 13.3, 1.3],
          ['line', 12, 8, 12, 4], ['circle', 12, 3, 1.2], ['line', 3, 13, 5, 13], ['line', 19, 13, 21, 13]],
    user: [['circle', 12, 8, 4], ['path', 'M4 20c0-4.5 3.5-7 8-7s8 2.5 8 7']],
    clock: [['circle', 12, 12, 9], ['line', 12, 12, 12, 7], ['line', 12, 12, 16, 14]],
    list: [['line', 5, 6, 19, 6], ['line', 5, 12, 19, 12], ['line', 5, 18, 19, 18]],
    cpu: [['rect', 7, 7, 10, 10, 0], ['rect', 10, 10, 4, 4, 0], ['line', 9, 3, 9, 7], ['line', 15, 3, 15, 7],
          ['line', 9, 17, 9, 21], ['line', 15, 17, 15, 21], ['line', 3, 9, 7, 9], ['line', 3, 15, 7, 15],
          ['line', 17, 9, 21, 9], ['line', 17, 15, 21, 15]],
    'hard-drive': [['rect', 3, 10, 18, 8, 1], ['line', 3, 14, 21, 14], ['fcircle', 7, 17, 1], ['line', 12, 17, 16, 17]],
    shield: [['path', 'M12 2l8 3v6c0 5-3.5 8.5-8 11c-4.5-2.5-8-6-8-11V5z'], ['path', 'M9 12l2 2l4-4']],
    box: [['path', 'M3 7l9-4l9 4v10l-9 4l-9-4z'], ['line', 3, 7, 12, 11], ['line', 21, 7, 12, 11], ['line', 12, 11, 12, 21]],
    terminal: [['rect', 3, 4, 18, 16, 2], ['polyline', '7,9 11,12 7,15'], ['line', 13, 15, 17, 15]],
    zap: [['fpath', 'M13 2L4 14h6l-1 8l9-12h-6z']]
  };

  function svgEl(tag, attrs) {
    var node = document.createElementNS(SVGNS, tag);
    if (attrs) Object.keys(attrs).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    return node;
  }
  function iconShapes(name) {
    return (ICONS[name] || ICONS.box).map(function (s) {
      var kind = s[0];
      if (kind === 'rect') return svgEl('rect', { x: s[1], y: s[2], width: s[3], height: s[4], rx: s[5] || 0 });
      if (kind === 'circle') return svgEl('circle', { cx: s[1], cy: s[2], r: s[3] });
      if (kind === 'fcircle') return svgEl('circle', { cx: s[1], cy: s[2], r: s[3], fill: 'currentColor', stroke: 'none' });
      if (kind === 'ellipse') return svgEl('ellipse', { cx: s[1], cy: s[2], rx: s[3], ry: s[4] });
      if (kind === 'line') return svgEl('line', { x1: s[1], y1: s[2], x2: s[3], y2: s[4] });
      if (kind === 'polyline') return svgEl('polyline', { points: s[1] });
      if (kind === 'fpath') return svgEl('path', { d: s[1], fill: 'currentColor' });
      return svgEl('path', { d: s[1] });
    });
  }

  /* ---------- measuring, so ELK reserves room for real text ----------
   * One offscreen canvas, made on first use rather than at load: this module is also
   * loaded by the test harness under node, where there is no canvas to make. */
  var MONO = 'ui-monospace, "SF Mono", Menlo, monospace';
  var SANS = '-apple-system, BlinkMacSystemFont, Inter, system-ui, sans-serif';
  var measureCtx = null;
  function textWidth(text, size, family) {
    if (measureCtx === null) {
      try { measureCtx = document.createElement('canvas').getContext('2d'); } catch (e) { measureCtx = false; }
    }
    if (!measureCtx) return String(text).length * size * 0.55;
    measureCtx.font = size + 'px ' + family;
    return measureCtx.measureText(String(text)).width;
  }

  /* ---------- cutting a label to the box it is drawn in ----------
   * A node is sized to its own text and then CLAMPED at NODE_MAX_W, so a label past that
   * width used to be painted straight across the diagram: a house that wrote
   * `state/cards/c-001/board-files` got a path lying over its neighbours. The box cannot
   * simply grow instead, because one long label would then set the width of every node
   * beside it.
   *
   * A PATH IS CUT IN THE MIDDLE and everything else at the END, which is one judgement in
   * two directions: the part that says WHICH THING THIS IS is the tail of a path and the
   * head of a sentence. A prefix cut leaves every file in one directory looking identical,
   * which is the worst possible answer on a board about files.
   *
   * Nothing is lost: the full text goes on the node's `<title>`, so hovering says it and a
   * screen reader reads it. */
  var ELLIPSIS = '…';

  function cutAt(text, keep, path) {
    if (keep <= 0) return ELLIPSIS;
    if (!path) return text.slice(0, keep) + ELLIPSIS;
    var tail = Math.ceil(keep / 2);
    return text.slice(0, keep - tail) + ELLIPSIS + text.slice(text.length - tail);
  }

  /* The longest cut of `text` that measures no wider than `room`. A binary search over the
     MEASUREMENT rather than a characters-per-pixel estimate, because the label font is
     proportional and there is no such number for it. */
  function fitText(text, room, size, family) {
    text = String(text === null || text === undefined ? '' : text);
    if (!text || textWidth(text, size, family) <= room) return text;
    if (room <= 0) return ELLIPSIS;
    var path = text.indexOf('/') >= 0;
    var low = 0, high = text.length - 1;
    while (low < high) {
      var mid = Math.ceil((low + high) / 2);
      if (textWidth(cutAt(text, mid, path), size, family) <= room) low = mid; else high = mid - 1;
    }
    return cutAt(text, low, path);
  }

  var NODE_MIN_W = 96, NODE_MAX_W = 184, ICON_TOP = 10, LABEL_Y = 50, SUB_Y = 66;
  /* What the drawing keeps clear inside the box. `nodeSize` sizes a box with 32 of padding;
     the cut leaves 12 a side, so a label that only just forced the clamp is not cut for the
     sake of a pixel, and one that is cut still sits well inside its border. */
  var NODE_PAD = 24;
  /* A card is sized to its own label, never a fixed width: "His phone" and
     "~/.claude/CLAUDE.md" cannot share one box without clipping the long one or wasting
     the short one's room, and a fixed width is what let two labels run into each other. */
  function nodeSize(n) {
    var w = Math.max(textWidth(n.label, 15, SANS), n.sub ? textWidth(n.sub, 13, MONO) : 0) + 32;
    w = Math.max(NODE_MIN_W, Math.min(NODE_MAX_W, Math.ceil(w / 4) * 4));
    return { width: w, height: n.sub ? 80 : 64 };
  }
  /* A group's title, in the group's own space: drawn at (GROUP_TITLE_X, GROUP_TITLE_Y) as
     an 11px baseline in `drawGroups`, uppercase with .06em of letter spacing (app/ui.css). */
  var GROUP_TITLE_X = 12, GROUP_TITLE_Y = 20, GROUP_TITLE_SIZE = 11;
  /* The top padding ELK gives a group: the title's baseline, its descent, and 8px of air,
     so nothing ELK places inside the group (a node, an edge label) reaches the title. */
  var GROUP_PAD_TOP = GROUP_TITLE_Y + 4 + 8;
  function groupTitleBox(label) {
    var upper = String(label).toUpperCase();
    return { x: GROUP_TITLE_X, y: GROUP_TITLE_Y - GROUP_TITLE_SIZE,
             width: Math.ceil(textWidth(upper, GROUP_TITLE_SIZE, MONO) + upper.length * 0.66),
             height: GROUP_TITLE_SIZE + 4 };
  }
  function groupSize(label) {
    var upper = String(label).toUpperCase();
    return { width: Math.ceil(textWidth(upper, 11, MONO) + upper.length * 0.66) + 40, height: 48 };
  }
  function edgeLabelSize(label) {
    return { width: Math.ceil(textWidth(label, 13, MONO)) + 16, height: 24 };
  }
  /* A LOOK another page passes on the model (`model.look`): the plan page's, in
     app/ui.planlook.js, sizes and paints nodes and edge labels its own way (P2-1). A model
     with no look, which is every board on this page, never asks, so nothing here changes. */
  function lookOf(model) {
    return model && model.look && K.boardLooks ? K.boardLooks[model.look] || null : null;
  }

  /* ---------- the ELK graph ---------- */
  /* NODES AND GROUPS ARE KEYED APART, the way ELK's ids are ('n_' and 'g_'). One map keyed by
     the bare ids sent a node `lint` in a group `lint` to itself as its own parent, and `chain`
     never ended: the page hung and drew nothing (c-602). A push now refuses the clash, and a
     board already stored that way still lays out; `chain` also stops at a key it has seen. */
  function parentMap(model) {
    var map = {};
    model.nodes.forEach(function (n) {
      if (n.group && model.groups.some(function (g) { return g.id === n.group; })) map['n_' + n.id] = 'g_' + n.group;
    });
    return map;
  }
  function chain(key, parentOf) {
    var out = [], seen = {}, cur = key;
    while (cur !== undefined && cur !== null && !seen[cur]) { seen[cur] = true; out.push(cur); cur = parentOf[cur]; }
    return out;
  }
  /* The group id both nodes sit in, or null (the root). */
  function commonAncestor(a, b, parentOf) {
    var seen = {};
    chain('n_' + a, parentOf).forEach(function (x) { seen[x] = true; });
    var other = chain('n_' + b, parentOf);
    for (var i = 0; i < other.length; i++) if (seen[other[i]]) return other[i].indexOf('g_') === 0 ? other[i].slice(2) : null;
    return null;
  }

  /* HOW A CHAIN IS FOLDED. ELK lays a chain of ten nodes out as a chain of ten nodes, 2861
     pixels of it, and no amount of scaling makes that readable in an 862 pixel stage. Given
     the stage's own aspect ratio and `MULTI_EDGE` wrapping it folds the same chain into
     rows instead: 632 x 700 for the ten node case, which fits at 0.75 rather than 0.4.
     Measured against the vendored elkjs 0.9.3, with the DEFAULT cutting strategy (`MANUAL`
     refuses to wrap at all, and `ARD` is a different trade for a gain of a few percent).
     `aspect` of 0 is the phone, which is laid out DOWN and scrolls. */
  function wrapOptions(aspect) {
    if (!(aspect > 0)) return {};
    return { 'elk.aspectRatio': String(aspect),
             'elk.layered.wrapping.strategy': 'MULTI_EDGE',
             'elk.layered.wrapping.additionalEdgeSpacing': '24' };
  }

  function buildGraph(model, direction, aspect) {
    var groups = {}, meta = {};
    model.groups.forEach(function (g) {
      var size = groupSize(g.label);
      groups[g.id] = {
        id: 'g_' + g.id, labels: [{ text: g.label, width: size.width, height: 14 }],
        layoutOptions: {
          'elk.padding': '[top=' + GROUP_PAD_TOP + ',left=16,bottom=12,right=16]',
          'elk.nodeSize.constraints': 'MINIMUM_SIZE',
          'elk.nodeSize.minimum': '(' + size.width + ', ' + size.height + ')'
        },
        children: [], edges: []
      };
    });
    var root = {
      id: 'root',
      layoutOptions: {
        'elk.algorithm': 'layered', 'elk.direction': direction,
        'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
        'elk.spacing.nodeNode': 20, 'elk.layered.spacing.nodeNodeBetweenLayers': 16,
        'elk.spacing.edgeNode': 12, 'elk.layered.spacing.edgeNodeBetweenLayers': 12,
        'elk.spacing.edgeLabel': 4, 'elk.edgeLabels.placement': 'CENTER',
        'elk.layered.edgeLabels.sideSelection': 'SMART',
        'elk.padding': '[top=12,left=16,bottom=12,right=16]'
      },
      children: [], edges: []
    };
    /* c-732: a narrow drawing (a flow on a phone) carries each arrow's words on the arrow,
       not beside it, so the words do not widen the drawing */
    if (model.inlineLabels) root.layoutOptions['elk.edgeLabels.inline'] = true;
    Object.keys(wrapOptions(aspect)).forEach(function (k) {
      root.layoutOptions[k] = wrapOptions(aspect)[k];
    });
    model.groups.forEach(function (g) { root.children.push(groups[g.id]); });
    var look = lookOf(model);
    model.nodes.forEach(function (n) {
      var size = look ? look.nodeSize(model, n) : nodeSize(n);
      var node = { id: 'n_' + n.id, width: size.width, height: size.height };
      if (n.group && groups[n.group]) groups[n.group].children.push(node);
      else root.children.push(node);
    });
    var parentOf = parentMap(model);
    model.edges.filter(function (e) { return nodeBy(model, e.a) && nodeBy(model, e.b); })
      .forEach(function (e, i) {
        var lca = commonAncestor(e.a, e.b, parentOf);
        var into = (lca && groups[lca]) ? groups[lca] : root;
        var id = 'e_' + i;
        var edge = { id: id, sources: ['n_' + e.a], targets: ['n_' + e.b] };
        if (e.label) {
          var size = look ? look.edgeLabelSize(e.label) : edgeLabelSize(e.label);
          edge.labels = [{ text: e.label, width: size.width, height: size.height }];
        }
        into.edges.push(edge);
        meta[id] = e;
      });
    return { root: root, meta: meta };
  }

  function absolute(node, x, y, out) {
    var ax = x + (node.x || 0), ay = y + (node.y || 0);
    out[node.id] = { x: ax, y: ay, width: node.width || 0, height: node.height || 0 };
    (node.children || []).forEach(function (c) { absolute(c, ax, ay, out); });
  }
  /* An edge declared inside a group is positioned in THAT group's own local space, like
     its child nodes are, so it carries the group's absolute offset with it. */
  function edgesAbsolute(node, ax, ay, out) {
    (node.edges || []).forEach(function (e) { out.push({ edge: e, x: ax, y: ay }); });
    (node.children || []).forEach(function (c) { edgesAbsolute(c, ax + (c.x || 0), ay + (c.y || 0), out); });
  }
  function pathOf(section, ox, oy) {
    var points = [section.startPoint].concat(section.bendPoints || [], [section.endPoint]);
    return points.map(function (p, i) {
      return (i ? 'L' : 'M') + (p.x + ox).toFixed(1) + ' ' + (p.y + oy).toFixed(1);
    }).join(' ');
  }

  /* ---------- pan and zoom ----------
   * ONE transform on ONE group, `translate(tx,ty) scale(k)`, never a viewBox rewritten per
   * event: the browser composites a transform and re-rasterises a viewBox, which is the
   * difference between a smooth pinch and a slideshow. Pointer events throughout, so the
   * mouse, the trackpad and two fingers are one code path with one capture.
   *
   * The band is relative to the FITTED scale rather than absolute, because what "too
   * small to read" means depends on how big the graph was to begin with. */
  var ZOOM_MIN = 0.25, ZOOM_MAX = 4, WHEEL_RATE = 0.0015, PINCH_RATE = 0.01, TAP_SLOP = 6;

  function clampScale(next, fitted) {
    if (!(fitted > 0)) return next;
    return Math.min(Math.max(next, fitted * ZOOM_MIN), fitted * ZOOM_MAX);
  }
  /* Exported for tests/test_boards.py, which runs it under node: the clamp is the one
     piece of this that is arithmetic rather than layout, so it is the one piece a test
     can hold honestly. */
  K.boardClamp = clampScale;

  /* READABLE BEFORE COMPLETE. A fit that clips is not a fit, and a fit nobody can read is
     not one either. The first answer to a twelve node board was to shrink it, and Harbor's
     ten node chain (2861 x 104, a flat left-to-right line) then came out at 0.4: six pixel
     labels, AND its last node still off the edge. Shrinking is the wrong answer for a wide
     chain. Two things fix it: the LAYOUT is folded to the stage's shape (`buildGraph`,
     `elk.aspectRatio` with `MULTI_EDGE` wrapping), and the fit below stops at a scale a
     label survives.

     0.6 IS THE FLOOR AND THE THRESHOLD AT ONCE. Above it the desk fits BOTH axes, which is
     what "the whole board" means. Below it the desk stops trying to show everything and
     fits the WIDTH instead, letting the stage be panned down the rest, which is what the
     phone has always done and is the better trade: a 15px label is 9px at 0.6 and 6px at
     0.4. Either way, reading the WORDS is what the outline view is for.

     The phone keeps 0.75: it fits the width alone and never showed everything anyway, so
     there is nothing to win by shrinking it. The zoom band is a quarter to four times the
     fitted scale on both, so he can always go closer. */
  var DESK_READABLE = 0.6, PHONE_FIT_MIN = 0.75, FIT_MAX = 2.5;

  /* NEVER BLOWN UP BECAUSE IT OVERFLOWS (round 2 of lane K, 2026-09-24). Below the floor the
     desk fits the width, and a tall narrow drawing's width fit is huge: b-009 laid out DOWN
     on the 1138 x 528 page stage came out at the 2.5 ceiling showing a fifth of itself.
     Enlarging a drawing that already cannot be shown whole only hides more of it, so the
     width fallback stops at the drawing's natural size. */
  var DESK_FALLBACK_MAX = 1;

  /* THE SLACK A KEPT LAYOUT GETS (K3, round 2): it is kept while it reads whole at 0.95 of
     the floor. At 1440 x 900 with the rail open b-009's RIGHT layout (1874px) misses the
     1120px full-screen stage by one pixel, and a kept shape that flips over a pixel is not
     kept. It is drawn at the floor, panned by the 20px it overflows. */
  var DESK_KEEP_SLACK = 0.95;

  /* The ratio the fit WANTS, before any clamp: the desk asks for both axes and falls back
     to the width when both cannot be read; the phone always asks for the width. It is also
     what decides whether a second layout is worth running (`layoutBest`). */
  function fitScale(width, height, innerW, innerH, desk) {
    if (!desk) return Math.max(40, innerW - 16) / width;
    var both = fitBoth(width, height, innerW, innerH);
    return both >= DESK_READABLE ? both : Math.min(DESK_FALLBACK_MAX, Math.max(40, innerW - 16) / width);
  }

  /* The scale at which the WHOLE board is on the stage, whatever that costs in legibility.
     It is what decides whether a layout is worth laying out again (`layoutBest`), because
     the point of a second try is to get the whole board readable: `fitScale` above hides
     that question, since it answers with the width fallback the moment both axes fail. */
  function fitBoth(width, height, innerW, innerH) {
    return Math.min(Math.max(40, innerW - 16) / width, Math.max(40, innerH - 16) / height);
  }

  /* WHICH OF TWO LAYOUTS IS BETTER. One that can be read WHOLE beats one that cannot,
     however much bigger the second is drawn; between two that cannot, the bigger wins. */
  function layoutScore(width, height, innerW, innerH, desk) {
    var both = fitBoth(width, height, innerW, innerH);
    if (both >= DESK_READABLE) return 1000 + both;
    return fitScale(width, height, innerW, innerH, desk);
  }

  /* THE FLOOR THE FIT MAY GO DOWN TO. The phone's is 0.75. The desk's is 0.6, except for a
     drawing that reads whole within the slack (at 0.95 of the floor or better) and whose
     width alone is under the floor: that one is drawn WHOLE a hair under the floor rather
     than lifted to it and cut. A kept layout lives in that band (K-9), and so does b-009's
     RIGHT row on the 1440 x 900 page; lifted to 0.6 its group ran under the rail at 1120.
     A drawing whose width fits above the floor still fits the width (W4). */
  function deskFloor(width, height, innerW, innerH, desk) {
    if (!desk) return PHONE_FIT_MIN;
    var both = fitBoth(width, height, innerW, innerH);
    var byWidth = Math.max(40, innerW - 16) / width;
    return both >= DESK_READABLE * DESK_KEEP_SLACK && byWidth < DESK_READABLE ? both : DESK_READABLE;
  }

  /* HOW MUCH OF A DRAWING IS ON THE STAGE at the scale it is drawn at, from 0 to 1: the
     share of each axis that fits, multiplied. */
  function visibleShare(width, height, innerW, innerH, desk) {
    var scale = fittedView(width, height, innerW, innerH, desk).scale;
    return Math.min(1, Math.max(40, innerW - 16) / (width * scale)) *
           Math.min(1, Math.max(40, innerH - 16) / (height * scale));
  }

  function fittedView(width, height, innerW, innerH, desk) {
    /* Fitted INSIDE an 8px margin, not against the bare edge: fitting to the full width
       and then nudging the content 8px in leaves it 8px past the other side, which the
       "there is more this way" fade below then reports on a graph that is entirely
       visible. The margin is in the fit, so the two agree, and `Fit` is this same function
       so the button lands exactly where the board opened. */
    var scale = Math.max(deskFloor(width, height, innerW, innerH, desk),
                         Math.min(FIT_MAX, fitScale(width, height, innerW, innerH, desk) || 1));
    return { scale: scale, fitted: scale, user: false, forW: innerW, forH: innerH,
             tx: Math.max(8, (innerW - width * scale) / 2),
             ty: Math.max(8, (innerH - height * scale) / 2) };
  }

  /* WHICH VIEW A REDRAW USES: the one he set by hand, or a fresh fit.
     A HAND-SET ZOOM IS RELATIVE TO THE STAGE IT WAS SET IN, and it was kept across any
     redraw at all. So opening the phone's drawer (which halves the stage), switching views
     and resizing all left him looking at a transform computed for a stage that is no longer
     there: the part he had leaned into slid off the edge. It survives a redraw at the SAME
     size, which is the case it exists for (a node arriving while he is looking at one), and
     a stage that changed size is refitted. */
  function viewFor(was, fit, innerW, innerH, fresh) {
    if (!was || !was.user || fresh || was.forW !== innerW || was.forH !== innerH) return fit;
    return { scale: was.scale, tx: was.tx, ty: was.ty, fitted: fit.fitted, user: true,
             forW: innerW, forH: innerH };
  }
  function applyView(stage, view) {
    stage.setAttribute('transform', 'translate(' + view.tx.toFixed(2) + ',' + view.ty.toFixed(2) +
      ') scale(' + view.scale.toFixed(4) + ')');
    markMore(stage);
    /* the walk's callout is placed from the screen, so it follows every pan and zoom */
    if (K.boardCallout) K.boardCallout.follow(stage);
  }
  /* WHICH WAY THE DIAGRAM CONTINUES. A graph cut flat by the stage's edge reads as broken
     rather than as pannable, and no CSS can ask where the reader has dragged it to. One
     attribute, set on every transform, and `app/ui.css` fades that edge, which is the same
     answer the deck's chip strips already give (`K.markStrips`). The fitted scale has a
     floor, so a wide graph legitimately starts wider than its stage: the floor keeps a
     15px label readable and this says there is more of it. */
  function markMore(stage) {
    var svg = stage.ownerSVGElement, wrap = svg && svg.parentNode;
    if (!wrap || !svg._view || !svg._content) return;
    var v = svg._view, size = svg._content;
    var right = v.tx + size.width * v.scale > wrap.clientWidth + 2;
    var down = v.ty + size.height * v.scale > wrap.clientHeight + 2;
    wrap.setAttribute('data-more', right && down ? 'xy' : right ? 'x' : down ? 'y' : 'none');
  }
  function zoomAbout(view, px, py, factor) {
    var next = clampScale(view.scale * factor, view.fitted);
    var ratio = next / view.scale;
    view.tx = px - ratio * (px - view.tx);
    view.ty = py - ratio * (py - view.ty);
    view.scale = next;
    view.user = true;
  }

  /* One set of listeners per <svg>, attached once. They read `svg._view` every time, so a
     graph re-laid-out under them keeps working without rebinding anything. */
  function wireGestures(svg) {
    if (svg._wired) return;
    svg._wired = true;
    var points = {}, count = 0, last = null, pinch = null, moved = 0, lastTap = 0;

    function local(ev) {
      var box = svg.getBoundingClientRect();
      return { x: ev.clientX - box.left, y: ev.clientY - box.top };
    }
    function redraw() { if (svg._stage && svg._view) applyView(svg._stage, svg._view); }

    svg.addEventListener('wheel', function (ev) {
      if (!svg._view) return;
      ev.preventDefault();
      var at = local(ev);
      /* A trackpad pinch arrives as a wheel with ctrlKey set, and it is a finer gesture
         than a wheel notch, so it gets its own rate. */
      var rate = ev.ctrlKey ? PINCH_RATE : WHEEL_RATE;
      zoomAbout(svg._view, at.x, at.y, Math.exp(-ev.deltaY * rate));
      redraw();
    }, { passive: false });

    svg.addEventListener('pointerdown', function (ev) {
      if (!svg._view) return;
      points[ev.pointerId] = local(ev);
      count = Object.keys(points).length;
      moved = 0;
      if (count === 1) { last = points[ev.pointerId]; pinch = null; }
      else if (count === 2) {
        var two = Object.keys(points).map(function (id) { return points[id]; });
        pinch = { distance: Math.hypot(two[0].x - two[1].x, two[0].y - two[1].y),
                  mid: { x: (two[0].x + two[1].x) / 2, y: (two[0].y + two[1].y) / 2 } };
      }
      try { svg.setPointerCapture(ev.pointerId); } catch (e) { /* a synthetic event has no capture */ }
    });

    svg.addEventListener('pointermove', function (ev) {
      if (!svg._view || !(ev.pointerId in points)) return;
      var at = local(ev);
      points[ev.pointerId] = at;
      var ids = Object.keys(points);
      if (ids.length >= 2 && pinch) {
        var two = ids.map(function (id) { return points[id]; });
        var distance = Math.hypot(two[0].x - two[1].x, two[0].y - two[1].y);
        var mid = { x: (two[0].x + two[1].x) / 2, y: (two[0].y + two[1].y) / 2 };
        if (pinch.distance > 0) zoomAbout(svg._view, mid.x, mid.y, distance / pinch.distance);
        svg._view.tx += mid.x - pinch.mid.x;
        svg._view.ty += mid.y - pinch.mid.y;
        pinch = { distance: distance, mid: mid };
        moved += 99;
        redraw();
        return;
      }
      if (!last) return;
      var dx = at.x - last.x, dy = at.y - last.y;
      moved += Math.abs(dx) + Math.abs(dy);
      svg._view.tx += dx;
      svg._view.ty += dy;
      svg._view.user = true;
      last = at;
      redraw();
    });

    function release(ev) {
      if (!(ev.pointerId in points)) return;
      delete points[ev.pointerId];
      count = Object.keys(points).length;
      if (count < 2) pinch = null;
      last = count === 1 ? points[Object.keys(points)[0]] : null;
      try { svg.releasePointerCapture(ev.pointerId); } catch (e) { /* already gone */ }
      if (moved > TAP_SLOP) return;
      /* A tap that did not drag is a tap: on a node it opens that node, on empty canvas
         twice in a row it is the phone's double-click, which fits the view again. */
      var node = ev.target && ev.target.closest ? ev.target.closest('.gnode') : null;
      if (node) { openNode(node.getAttribute('data-nid')); return; }
      var at = Date.now();
      if (at - lastTap < 320 && svg._fit) svg._fit();
      lastTap = at;
    }
    svg.addEventListener('pointerup', release);
    svg.addEventListener('pointercancel', release);
    svg.addEventListener('dblclick', function (ev) {
      if (ev.target && ev.target.closest && ev.target.closest('.gnode')) return;
      if (svg._fit) svg._fit();
    });
  }

  /* ---------- drawing the diagram ----------
   * The bookkeeping lives on the HOST element rather than on the model, because one model
   * is drawn in two places (the diagram's stage and the walk's compact graph) and each of
   * them has its own layout, its own transform and its own idea of what it has drawn. */
  var elk = null;
  /* ELK is a deferred script, so it may not have run yet the first time a graph is drawn.
     A miss is NOT cached: caching it would leave the route permanently unable to lay a
     graph out because of the order two files happened to load in on one page load. */
  /* ELK IS FETCHED WHEN A GRAPH FIRST NEEDS IT (lane P). It is 1.6 MB, and as a deferred
     script in the shell it held DOMContentLoaded on every cold load of every route, which on
     a shaped phone link was the whole of a plan's first paint. The callers already retry
     while it is missing, so asking for it here is all the loading there is. */
  var elkAsked = false;
  function askForElk() {
    if (elkAsked || typeof document === 'undefined' || !document.createElement) return;
    elkAsked = true;
    var tag = document.createElement('script');
    tag.src = '/vendor/elk.bundled.js';
    tag.async = true;
    (document.head || document.documentElement).appendChild(tag);
  }
  function layoutEngine() {
    if (elk) return elk;
    if (typeof ELK !== 'function') { askForElk(); return null; }  // eslint-disable-line no-undef
    elk = new ELK();                                             // eslint-disable-line no-undef
    return elk;
  }

  function graphParts(host) {
    var wrap = host.querySelector('.graphwrap'), svg, stage;
    if (!wrap) {
      wrap = K.el('div', { class: 'graphwrap' });
      svg = svgEl('svg', { class: 'graph' });
      svg.appendChild(arrowDefs());
      stage = svgEl('g', { class: 'gstage' });
      svg.appendChild(stage);
      wrap.appendChild(svg);
      host.appendChild(wrap);
    } else { svg = wrap.querySelector('svg'); stage = svg.querySelector('.gstage'); }
    return { wrap: wrap, svg: svg, stage: stage };
  }

  /* FIT IS THE GATE, READABILITY IS THE CHOICE (K1, 2026-09-24). On the desk BOTH layouts
     are laid out, RIGHT and DOWN (two ELK runs on at most twelve nodes is milliseconds), and
     among the ones that can be read whole at the floor the one with the lowest readability
     cost is drawn (`app/ui.boardlayout.js`: crossings, bends, edge length, and above all an
     edge routed round the outside). When neither can, the one that shows the most of itself
     at the scale it is drawn at wins (round 2, reversing W3's "the bigger drawn wins"). The fit used to be the whole score and DOWN was tried only when the folded RIGHT
     did not fit, so a wide full-screen stage let b-009's three groups fold into rows with
     an edge looped round the whole drawing. RIGHT is FOLDED only for a simple chain (K2,
     `shouldFold`). The phone lays out DOWN and scrolls, as it always has.

     A KEPT CHOICE (K-5, K-9) is laid out alone and drawn while it reads whole at 0.95 of the
     floor, so the board does not change shape when the rail folds or the window is resized;
     past that the choice is made again. The full-screen toggle forgets the kept choice
     (K-12, `forgetShapes` in ui.boardfull.js), because full screen is for a bigger board. */
  function candidatesFor(model, desk, innerW, innerH) {
    if (!desk) return [{ direction: 'DOWN', aspect: 0, desk: false }];
    return [{ direction: 'RIGHT', aspect: K.boardLayout.shouldFold(model) ? innerW / innerH : 0, desk: true },
            { direction: 'DOWN', aspect: 0, desk: true }];
  }
  function laidOut(engine, model, choice, innerW, innerH) {
    var built = buildGraph(model, choice.direction, choice.aspect);
    return engine.layout(built.root).then(function (laid) {
      return { laid: laid, meta: built.meta, choice: choice,
               fit: layoutScore(laid.width || 200, laid.height || 120, innerW, innerH, choice.desk),
               shown: visibleShare(laid.width || 200, laid.height || 120, innerW, innerH, choice.desk),
               scale: fittedView(laid.width || 200, laid.height || 120, innerW, innerH, choice.desk).scale,
               cost: K.boardLayout.readability(laid).cost };
    });
  }
  /* ONE layout of one shape, with its readability cost: what the plan page's own chooser
     (`K.planLook.chooseForColumn`) weighs, since a column he scrolls is not a stage. */
  function layoutOnce(engine, model, direction, aspect) {
    var built = buildGraph(model, direction, aspect);
    return engine.layout(built.root).then(function (laid) {
      return { laid: laid, meta: built.meta, choice: { direction: direction, aspect: aspect },
               cost: K.boardLayout.readability(laid).cost };
    });
  }
  function chooseLayout(engine, model, desk, innerW, innerH) {
    return Promise.all(candidatesFor(model, desk, innerW, innerH).map(function (choice) {
      return laidOut(engine, model, choice, innerW, innerH).catch(function () { return null; });
    })).then(function (list) {
      list = list.filter(Boolean);
      if (!list.length) throw new Error('no layout');
      return K.boardLayout.choose(list);
    });
  }
  function layoutBest(engine, model, desk, innerW, innerH, kept) {
    if (!kept || kept.desk !== desk) return chooseLayout(engine, model, desk, innerW, innerH);
    return laidOut(engine, model, kept, innerW, innerH).then(function (got) {
      var both = fitBoth(got.laid.width || 200, got.laid.height || 120, innerW, innerH);
      return both >= DESK_READABLE * DESK_KEEP_SLACK ? got : chooseLayout(engine, model, desk, innerW, innerH);
    });
  }

  function drawGraph(host, model, fresh) {
    var parts = graphParts(host), svg = parts.svg, stage = parts.stage, wrap = parts.wrap;
    if (!host._still) wireGestures(svg);     /* c-732: a drawing on a page (How work ships) is still, so the page scrolls over it */
    if (!model.nodes.length) return;
    var engine = layoutEngine();
    if (!engine) {
      /* Try again once the vendored bundle has run. It re-enters the DRAWING rather than
         the render pass: the host does not need rebuilding to lay a graph out. */
      host._drawn = -1;
      setTimeout(function () { if (host.parentNode) drawGraph(host, model, fresh); }, 200);
      return;
    }
    /* COMPACT IS SHORTER, NOT NARROWER. The walk's graph has the same width as the
       stage's and a third of its height, so it lays out the same way (RIGHT on the desk,
       DOWN on the phone): turning it DOWN on a 1440px desk would waste every pixel of the
       width and push the lit node off the bottom. */
    var desk = K.isDesk();
    var innerW0 = Math.max(80, wrap.clientWidth), innerH0 = Math.max(80, wrap.clientHeight);
    var seq = host._seq = (host._seq || 0) + 1;
    /* a still drawing reads one way, unfolded: left to right on the desk, top to bottom on a phone */
    var laying = host._still ? layoutOnce(engine, model, desk ? 'RIGHT' : 'DOWN', 0)
      : layoutBest(engine, model, desk, innerW0, innerH0, host._kept);
    laying.then(function (best) {
      if (seq !== host._seq) return;         // a newer op superseded this layout
      var laid = best.laid, built = best;
      if (host._keep) host._keep(best.choice);
      var box = {}, edges = [];
      absolute(laid, 0, 0, box);
      edgesAbsolute(laid, 0, 0, edges);
      var width = laid.width || 200, height = laid.height || 120;
      var innerW = Math.max(80, wrap.clientWidth), innerH = Math.max(80, wrap.clientHeight);
      if (host._still) innerH = stillHeight(host, width, height, innerW);
      svg.setAttribute('width', innerW);
      svg.setAttribute('height', innerH);
      svg.setAttribute('viewBox', '0 0 ' + innerW + ' ' + innerH);

      /* THE FITTED VIEW IS RECOMPUTED, the one he set by hand is kept. A board opened, or
         a stage that changed size, starts fitted; a diagram he has zoomed into keeps that
         zoom while ops append to it, so the thing he leaned in to look at does not jump
         away under him when the next node lands. That IS following the latest node: with
         no zoom of his own the fit grows to hold it, and with one his view is his. */
      host._view = host._still ? stillView(width, height, innerW)
        : viewFor(host._view, fittedView(width, height, innerW, innerH, desk), innerW, innerH, fresh);
      svg._view = host._view;
      svg._stage = stage;
      svg._content = { width: width, height: height };
      svg._fit = function () {
        host._view = fittedView(width, height, Math.max(80, wrap.clientWidth),
                                Math.max(80, wrap.clientHeight), K.isDesk());
        svg._view = host._view;
        applyView(stage, host._view);
        markFitted(host);
      };
      applyView(stage, host._view);
      markFitted(host);

      drawGroups(stage, model, box);
      drawEdges(stage, model, host, edges, built.meta);
      drawNodes(stage, model, host, box);
      raiseTitles(stage);
      focusNodes(host);
    }).catch(function () { wrap.classList.add('noelk'); });
  }

  /* A STILL DRAWING (c-732, How work ships) cannot be panned, so it is shown whole: its width
     fits the page (never above its natural size) and the host takes the height that gives,
     so no part of it is ever off an edge. */
  function stillHeight(host, width, height, innerW) {
    var scale = Math.min(1, Math.max(40, innerW - 16) / width);
    var tall = Math.ceil(height * scale + 16);
    host.style.height = tall + 'px';
    return tall;
  }
  function stillView(width, height, innerW) {
    var scale = Math.min(1, Math.max(40, innerW - 16) / width);
    return { scale: scale, fitted: scale, user: false, forW: innerW, forH: Math.ceil(height * scale + 16),
             tx: Math.max(8, (innerW - width * scale) / 2), ty: 8 };
  }

  function markFitted(host) {
    var head = host.parentNode && host.parentNode.querySelector('.fitbtn');
    if (head) head.classList.toggle('on', !!(host._view && !host._view.user));
  }

  function arrowDefs() {
    var defs = svgEl('defs');
    ['fwd', 'bwd'].forEach(function (kind) {
      var marker = svgEl('marker', { id: 'board-arrow-' + kind, viewBox: '0 0 10 10',
        refX: kind === 'fwd' ? 9 : 1, refY: 5, markerWidth: 7, markerHeight: 7,
        orient: kind === 'fwd' ? 'auto' : 'auto-start-reverse' });
      marker.appendChild(svgEl('path', { d: 'M0 0 L10 5 L0 10 z', fill: 'var(--ink-3)' }));
      defs.appendChild(marker);
    });
    return defs;
  }

  function esc(value) { return String(value).replace(/(["\\])/g, '\\$1'); }

  /* A GROUP'S TITLE IS DRAWN ABOVE THE EDGES, on a plate of the stage's own colour. ELK
     brings an edge into a group laid out DOWN through its top, wherever along it it likes,
     and a title that spans the group has nowhere to stand aside: b-009's `replay` edge ran
     straight through CLOUD EVENTS SERVICE. The box stays under everything; the title goes in
     one layer at the end of the stage (`raiseTitles`), so a line passes behind the words
     rather than across them. Edge LABELS never reach a title: the group's top padding is
     taken from the title's own height (`GROUP_PAD_TOP`). */
  function drawGroups(stage, model, box) {
    var titles = titleLayer(stage);
    model.groups.forEach(function (g) {
      var at = box['g_' + g.id];
      if (!at) return;
      var node = stage.querySelector('[data-gid="' + esc(g.id) + '"]');
      if (!node) {
        node = svgEl('g', { class: 'ggroup', 'data-gid': g.id });
        node.appendChild(svgEl('rect', { class: 'gbox' }));
        stage.insertBefore(node, stage.firstChild);
      }
      node.setAttribute('transform', 'translate(' + at.x + ',' + at.y + ')');
      var rect = node.querySelector('rect');
      rect.setAttribute('width', at.width);
      rect.setAttribute('height', at.height);
      drawTitle(titles, g, at);
    });
  }
  function titleLayer(stage) {
    var layer = stage.querySelector('.gtitles');
    if (!layer) { layer = svgEl('g', { class: 'gtitles' }); stage.appendChild(layer); }
    return layer;
  }
  function drawTitle(layer, g, at) {
    var title = layer.querySelector('[data-tid="' + esc(g.id) + '"]');
    if (!title) {
      title = svgEl('g', { class: 'gtitle', 'data-tid': g.id });
      title.appendChild(svgEl('rect', { class: 'gtitlebg' }));
      title.appendChild(svgEl('text', { class: 'glabel', x: GROUP_TITLE_X, y: GROUP_TITLE_Y }));
      layer.appendChild(title);
    }
    var at0 = groupTitleBox(g.label), plate = title.querySelector('rect');
    title.querySelector('text').textContent = g.label;
    title.setAttribute('transform', 'translate(' + at.x + ',' + at.y + ')');
    plate.setAttribute('x', at0.x - 4);
    plate.setAttribute('y', at0.y - 2);
    plate.setAttribute('width', at0.width + 8);
    plate.setAttribute('height', at0.height + 4);
  }
  /* Edges and nodes are appended as they arrive, so the title layer is moved back to the
     end of the stage after every drawing. */
  function raiseTitles(stage) {
    var layer = stage.querySelector('.gtitles');
    if (layer) stage.appendChild(layer);
  }

  function drawEdges(stage, model, host, edges, meta) {
    var seen = {};
    host._seenEdges = host._seenEdges || {};
    edges.forEach(function (item) {
      var section = (item.edge.sections || [])[0];
      if (!section) return;
      var key = item.edge.id;
      seen[key] = true;
      var fresh = !host._seenEdges[key];
      var node = stage.querySelector('[data-eid="' + esc(key) + '"]');
      if (!node) {
        node = svgEl('g', { class: 'gedge', 'data-eid': key });
        node.appendChild(svgEl('path', {}));
        stage.appendChild(node);
      }
      var line = node.querySelector('path');
      line.setAttribute('d', pathOf(section, item.x, item.y));
      var arrow = (meta[key] || {}).arrow;
      if (arrow === 'none') line.removeAttribute('marker-end');
      else line.setAttribute('marker-end', 'url(#board-arrow-fwd)');
      if (arrow === 'both') line.setAttribute('marker-start', 'url(#board-arrow-bwd)');
      else line.removeAttribute('marker-start');
      var old = node.querySelector('.elabel-wrap');
      if (old) old.remove();
      var label = (item.edge.labels || [])[0];
      if (label) {
        var group = svgEl('g', { class: 'elabel-wrap' });
        group.appendChild(svgEl('rect', { class: 'elabel', x: label.x + item.x, y: label.y + item.y,
          width: label.width, height: label.height, rx: 4 }));
        var text = svgEl('text', { class: 'elabel', 'text-anchor': 'middle',
          x: label.x + item.x + label.width / 2, y: label.y + item.y + label.height / 2 + 4.5 });
        if (lookOf(model)) lookOf(model).paintEdgeLabel(text, label, label.x + item.x, label.y + item.y);
        else text.textContent = label.text;
        group.appendChild(text);
        node.appendChild(group);
      }
      if (fresh) enter(node);
    });
    host._seenEdges = seen;
  }

  /* The 200ms entrance: a node that has just arrived fades and settles in, so what changed
     is visible without him having to compare the board with the one in his memory. */
  function enter(node) {
    node.classList.add('enter');
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { node.classList.remove('enter'); });
    });
  }

  /* A node carries a small count of what hangs on it, so the diagram says where the detail
     is without showing it: tapping that node is how he opens it. */
  function drawBadge(node, count, width) {
    var badge = node.querySelector('.gbadge');
    if (!count) { if (badge) badge.remove(); return; }
    if (!badge) {
      badge = svgEl('g', { class: 'gbadge' });
      badge.appendChild(svgEl('circle', { r: 9 }));
      badge.appendChild(svgEl('text', { 'text-anchor': 'middle', y: 3.5 }));
      node.appendChild(badge);
    }
    badge.setAttribute('transform', 'translate(' + (width - 10) + ',10)');
    badge.querySelector('text').textContent = String(count);
  }

  function drawNodes(stage, model, host, box) {
    var seen = {};
    host._seenNodes = host._seenNodes || {};
    model.nodes.forEach(function (n) {
      var at = box['n_' + n.id];
      if (!at) return;
      seen[n.id] = true;
      var fresh = !host._seenNodes[n.id];
      var node = stage.querySelector('[data-nid="' + esc(n.id) + '"]');
      if (!node) {
        node = svgEl('g', { class: 'gnode', 'data-nid': n.id });
        /* FIRST CHILD, and a real `<title>`: it is the SVG tooltip and the group's
           accessible name, and it carries whatever the cut below took off. */
        node.appendChild(svgEl('title'));
        node.appendChild(svgEl('rect', { class: 'card' }));
        node.appendChild(svgEl('g', { class: 'gicon' }));
        node.appendChild(svgEl('text', { class: 'lbl', 'text-anchor': 'middle' }));
        node.appendChild(svgEl('text', { class: 'sub', 'text-anchor': 'middle' }));
        stage.appendChild(node);
      }
      node.querySelector('title').textContent = n.sub ? n.label + '\n' + n.sub : n.label;
      MARKS.forEach(function (mark) { node.classList.toggle('mark-' + mark, n.mark === mark); });
      var rect = node.querySelector('rect.card');
      rect.setAttribute('width', at.width);
      rect.setAttribute('height', at.height);
      if (lookOf(model)) {
        lookOf(model).paintNode(model, node, n, at);
        drawBadge(node, attachmentsOn(model, n.id).length, at.width);
        node.setAttribute('transform', 'translate(' + at.x + ',' + at.y + ')');
        if (fresh) enter(node);
        return;
      }
      var icon = node.querySelector('.gicon');
      while (icon.firstChild) icon.removeChild(icon.firstChild);
      /* Presentation attributes are inherited only from a real ancestor, so they go on
         the wrapper the shapes are appended to; set on a throwaway <svg> they would be
         left behind and every icon would render as a solid black blob. */
      icon.setAttribute('fill', 'none');
      icon.setAttribute('stroke', 'currentColor');
      icon.setAttribute('stroke-width', '1.75');
      icon.setAttribute('stroke-linecap', 'round');
      icon.setAttribute('stroke-linejoin', 'round');
      icon.setAttribute('transform', 'translate(' + (at.width / 2 - 12) + ',' + ICON_TOP + ')');
      iconShapes(n.icon).forEach(function (shape) { icon.appendChild(shape); });
      var room = at.width - NODE_PAD;
      var label = node.querySelector('text.lbl');
      label.setAttribute('x', at.width / 2);
      label.setAttribute('y', LABEL_Y);
      label.textContent = fitText(n.label, room, 15, SANS);
      var sub = node.querySelector('text.sub');
      if (n.sub) {
        sub.setAttribute('x', at.width / 2);
        sub.setAttribute('y', SUB_Y);
        sub.textContent = fitText(n.sub, room, 13, MONO);
        sub.removeAttribute('hidden');
      } else { sub.textContent = ''; sub.setAttribute('hidden', ''); }
      drawBadge(node, attachmentsOn(model, n.id).length, at.width);
      node.setAttribute('transform', 'translate(' + at.x + ',' + at.y + ')');
      if (fresh) enter(node);
    });
    host._seenNodes = seen;
  }

  /* WHICH NODE IS LIT, without a layout. The selected node in the diagram and the walk's
     current step's node are the same class on the same element, and changing either is a
     class toggle rather than a reason to lay the graph out again. */
  function focusNodes(host) {
    var want = host._focus || null;
    var lit = null;
    Array.prototype.forEach.call(host.querySelectorAll('.gnode'), function (node) {
      var on = node.getAttribute('data-nid') === want;
      node.classList.toggle('on', on);
      if (on) lit = node;
    });
    if (lit && (host._compact || host._walk)) bringIntoView(host, lit);
    if (K.boardCallout) K.boardCallout.show(host);
  }

  /* THE WALK MOVES THE DIAGRAM; THE DIAGRAM DOES NOT MOVE ITSELF. Stepping through a walk
     (the compact graph, or full screen's stage while it walks)
     is asking to be shown that node, so a node that is off the edge is panned to the
     middle, at the scale that is already set. In the diagram a tap is a tap on something he
     is already looking at, and panning under his finger is the one thing it must not do,
     which is why this is gated on the compact graph alone.

     ONE AXIS AT A TIME, AND ONLY ONE THAT DOES NOT FIT. An axis the whole diagram already
     fits on cannot have a node off the edge, and centring on it throws the rest of the
     graph off the other side: the walk did exactly that the moment the fit was allowed to
     show a whole board, sliding the left hand half of it out of the stage to centre a node
     that was already visible. Arithmetic, so `tests/fixtures/board-zoom.js` runs it. */
  function panFor(view, at, size, w, h) {
    var out = { tx: view.tx, ty: view.ty }, moved = false;
    if (size.width * view.scale > w) {
      var x = view.tx + at.x * view.scale;
      if (x < w / 8 || x > w * 7 / 8) { out.tx = w / 2 - at.x * view.scale; moved = true; }
    }
    if (size.height * view.scale > h) {
      var y = view.ty + at.y * view.scale;
      if (y < h / 8 || y > h * 7 / 8) { out.ty = h / 2 - at.y * view.scale; moved = true; }
    }
    return moved ? out : null;
  }

  /* The node's own transform is its position in STAGE coordinates, which is the space the
     view's transform maps to the screen, so the centre of its box is a read rather than a
     measurement. */
  function bringIntoView(host, node) {
    var svg = host.querySelector('svg'), wrap = host.querySelector('.graphwrap');
    var view = host._view;
    if (!svg || !wrap || !view || !svg._content) return;
    var t = /translate\(([-\d.]+),([-\d.]+)\)/.exec(node.getAttribute('transform') || '');
    var box = node.querySelector('rect.card');
    if (!t || !box) return;
    var at = { x: parseFloat(t[1]) + (parseFloat(box.getAttribute('width')) || 0) / 2,
               y: parseFloat(t[2]) + (parseFloat(box.getAttribute('height')) || 0) / 2 };
    var to = panFor(view, at, svg._content, wrap.clientWidth, wrap.clientHeight);
    if (!to) return;
    view.tx = to.tx;
    view.ty = to.ty;
    applyView(svg.querySelector('.gstage'), view);
  }

  /* ---------- an attachment, drawn ----------
   * The same five renderers serve the node panel, the phone drawer and the outline, so a
   * table looks like a table wherever he meets it. Every one of them builds DOM nodes with
   * `K.el` and `textContent`; there is no path by which a board's text becomes markup. */

  /* `note` renders a markdown SUBSET and nothing else: **bold**, `code`, and a line break. */
  function inline(text) {
    var frag = document.createDocumentFragment();
    var re = /\*\*(.+?)\*\*|`([^`]+?)`|\\n|\n/g, last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      if (m[0] === '\n' || m[0] === '\\n') frag.appendChild(document.createElement('br'));
      else if (m[1] !== undefined) frag.appendChild(K.el('strong', { text: m[1] }));
      else frag.appendChild(K.el('code', { text: m[2] }));
      last = re.lastIndex;
    }
    if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
    return frag;
  }

  function noteNode(item) {
    var para = K.el('p');
    para.appendChild(inline(item.text));
    return K.el('div', { class: 'bnote', 'data-key': 'a' + item.n }, para);
  }
  function stepNode(item, number) {
    return K.el('div', { class: 'bstep', 'data-key': 'a' + item.n },
      K.el('span', { class: 'n mono t11 ink2', text: number + '.' }),
      K.el('span', { class: 't', text: item.text }));
  }
  function tableNode(item) {
    return K.el('div', { class: 'battach', 'data-key': 'a' + item.n },
      K.el('div', { class: 'battach-head label ellip', text: item.title }),
      K.el('div', { class: 'btablewrap' },
        K.el('table', {},
          K.el('thead', {}, item.cols.length
            ? K.el('tr', {}, item.cols.map(function (c) { return K.el('th', { text: c }); }))
            : null),
          K.el('tbody', {}, item.rows.map(function (row, i) {
            return K.el('tr', { 'data-key': 'r' + i }, row.map(function (cell) {
              return K.el('td', { text: cell });
            }));
          })))));
  }
  function codeNode(item) {
    return K.el('div', { class: 'battach', 'data-key': 'a' + item.n },
      K.el('div', { class: 'battach-head label ellip', text: item.title }),
      K.el('div', { class: 'bcode' },
        K.el('div', { class: 'bcodehead mono t11 ink2', text: item.lang || ' ' }),
        K.el('pre', { class: 'bcodepre' }, K.el('code', {}, item.lines.map(function (line, i) {
          return K.el('div', { class: 'cl', 'data-key': 'l' + i, text: line });
        })))));
  }
  /* A file attachment is a real file (K6, K7). The server keeps a COPY under the board's own
     directory and hands its artifact token out beside the board's lines, keyed by the path
     the op named; a row with no entry is one whose bytes never travelled, and it is drawn
     as metadata rather than as a download that would fail. */
  function servedFile(item) {
    var files = B.open && B.open.record ? B.open.record.files : null;
    var entry = files ? files[item.path] : null;
    return entry && entry.url ? entry : null;
  }
  function fileNode(item) {
    var served = servedFile(item);
    var name = (served && served.name) || String(item.path).split('/').pop();
    var said = (served ? served.size : item.size) + ' \u00b7 from ' + item.from;
    return K.el('div', { class: 'bfile', 'data-key': 'a' + item.n },
      K.el('div', { class: 'bficon' }, iconNode('file')),
      K.el('div', { class: 'bfinfo' },
        K.el('div', { class: 'bfname ellip', title: item.path, text: name }),
        K.el('div', { class: 'mono t11 ink2', text: said })),
      served
        ? K.el('a', { class: 'btn sm bfget', href: served.url, download: name, rel: 'noopener' }, 'Download')
        : K.el('div', { class: 'mono t10 ink3', text: 'on the board only' }));
  }
  function iconNode(name) {
    var svg = svgEl('svg', { viewBox: '0 0 24 24', width: 24, height: 24, fill: 'none',
      stroke: 'currentColor', 'stroke-width': 1.6, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
    iconShapes(name).forEach(function (shape) { svg.appendChild(shape); });
    return svg;
  }

  /* One attachment, whichever kind it is. `steps` carries the number this step has ACROSS
     the board, which is the order they were pushed in and the order the walk takes them. */
  function attachmentNode(item, steps) {
    if (item.kind === 'note') return noteNode(item);
    if (item.kind === 'step') return stepNode(item, steps.indexOf(item) + 1);
    if (item.kind === 'table') return tableNode(item);
    if (item.kind === 'code') return codeNode(item);
    return fileNode(item);
  }
  function attachmentList(model, at, extra) {
    var steps = stepsOf(model);
    var items = attachmentsOn(model, at);
    if (!items.length) {
      return K.el('div', { class: 'empty t11 ink3', text: extra || 'nothing hangs on this yet' });
    }
    return K.el('div', { class: 'battachments' }, items.map(function (item) {
      return attachmentNode(item, steps);
    }));
  }

  /* ---------- the route's own state ---------- */
  var B = {
    list: null,          /* the index, fetched once per open of the route */
    listing: false,
    open: null,          /* {id, record, model, cursor} */
    wanted: null,        /* the id a fetch is in flight for */
    tab: 'live',         /* live | saved */
    node: null,          /* the node whose attachments are open, in the diagram */
    panel: null,         /* the desk's side column: true, false, or null for "decide" */
    step: 0,             /* where the walk is */
    error: null,
    /* the ask box under the stage: what he has typed, which node it is about, the turn in
       flight and the answer to it. It is page state rather than DOM state for the reason
       every draft on the deck is (`K.draft`): the render pass rebuilds the body, and losing
       a half-typed question under him is the defect that rule exists for. */
    ask: { text: '', about: null, turn: null, busy: false, reply: null, open: false }
  };
  K.boardState = B;

  /* WHICH VIEW, and it is remembered per board. The URL wins, because a link he sent
     himself says what to open; what he last chose on THIS board is next, because a board
     that reads as a document should still read as a document when he comes back to it; and
     the diagram is the default on the desk and the phone alike. */
  function viewOf() {
    var asked = K.App.boardView;
    if (VIEWS.indexOf(asked) >= 0) return asked;
    var was = K.App.board ? K.stored('boardview-' + K.App.board) : null;
    return VIEWS.indexOf(was) >= 0 ? was : 'diagram';
  }

  /* ---------- the ask box (K11) and the attach control (K7) ----------
   * `POST /api/board/<id>/ask` answers with a TURN ID, not an answer: a turn into a house
   * is a whole `claude` and takes tens of seconds, which is longer than a request should
   * be held open. So the page polls `GET /api/board/<id>/ask/<turn>` until it is done,
   * while whatever the house pushes on the way arrives through the live channel above,
   * on its own cadence. A second Send is refused here AND on the server: one board, one
   * question, the same rule the voice conversation keeps. */
  var ASK_POLL_MS = 1500;
  var UPLOAD_TYPES = { pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg',
                       jpeg: 'image/jpeg' };
  var UPLOAD_MAX = 10 * 1024 * 1024;      /* the server's cap, checked here for a clearer no */

  function resetAsk() {
    B.ask.text = '';
    B.ask.about = null;
    B.ask.turn = null;
    B.ask.busy = false;
    B.ask.reply = null;
    B.ask.open = false;
  }

  function askPrefix() { return B.ask.about ? 'About "' + B.ask.about + '": ' : ''; }
  function askValue() { return askPrefix() + B.ask.text; }

  function askField() { return document.querySelector('[data-fk="board-ask"]'); }

  /* TAPPING A NODE IS TWO THINGS AT ONCE (K12). It opens that node's attachments, in the
     panel on the desk and the drawer on the phone, and it names the subject in the ask box
     in his own words rather than as an id he never saw. The label is read off the MODEL, so
     it is the text the house wrote and not whatever the renderer did with it.

     The render pass is safe to run: the graph sits in a `data-morph="skip"` subtree and its
     own drawing returns early when the version has not moved, so nothing is laid out again
     under his finger. */
  function openNode(id) {
    var model = B.open ? B.open.model : null;
    var found = model ? nodeBy(model, id) : null;
    B.node = B.node === id ? null : id;
    B.ask.about = B.node && found ? found.label : null;
    if (B.node) B.panel = true;
    K.renderBody();
    if (!B.node || !K.isDesk()) return;
    var field = askField();
    if (!field) return;
    field.value = askValue();
    field.setSelectionRange(field.value.length, field.value.length);
  }

  function askTyped(value) {
    var prefix = askPrefix();
    if (prefix && value.indexOf(prefix) === 0) { B.ask.text = value.slice(prefix.length); return; }
    /* he edited the prefix away, so the question is no longer about that node */
    B.ask.about = null;
    B.ask.text = value;
  }

  function sendAsk() {
    var said = askValue().trim();
    if (!said || B.ask.busy || !K.App.board) return;
    var id = K.App.board;
    B.ask.busy = true;
    B.ask.reply = null;
    K.renderBody();
    K.post('/api/board/' + encodeURIComponent(id) + '/ask',
           { method: 'POST', headers: { 'Content-Type': 'application/json' },
             body: JSON.stringify({ text: said }) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { askDone({ err: true, text: d.error || 'that was refused' }); return; }
        /* THE QUESTION IS SENT, so the box is empty and the node it was about is no longer
           the subject: the next question starts clean. */
        B.ask.turn = d.turn;
        B.ask.text = '';
        B.ask.about = null;
        K.renderBody();
        pollAsk(id, d.turn);
      })
      .catch(function (e) { askDone({ err: true, text: 'that did not reach the deck: ' + e.message }); });
  }

  function pollAsk(id, turn) {
    setTimeout(function () {
      if (B.ask.turn !== turn) return;            // he sent another one, or left the board
      fetch('/api/board/' + encodeURIComponent(id) + '/ask/' + encodeURIComponent(turn),
            { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (B.ask.turn !== turn) return;
          if (!d.ok) { askDone({ err: true, text: d.error || 'that turn is gone' }); return; }
          if (d.state !== 'done') { pollAsk(id, turn); return; }
          /* `ok` is the poll's, `answered` is the TURN's: a house saying "I have no session
             yet" answered him, and the reply says so quietly rather than as a failure. */
          askDone({ refused: !d.answered, text: d.say || 'it said nothing' });
        })
        .catch(function () { pollAsk(id, turn); });   // a poll that missed is not an answer
    }, ASK_POLL_MS);
  }

  function askDone(reply) {
    B.ask.busy = false;
    B.ask.turn = null;
    B.ask.reply = reply;
    K.renderBody();
  }

  function askReply() {
    var reply = B.ask.reply;
    if (!reply) return null;
    return K.el('div', { class: 'bask-reply' + (reply.err || reply.refused ? ' bad' : '') },
      K.el('div', { class: 'bask-said', text: reply.text }),
      K.el('button', { class: 'bnav bask-shut', 'aria-label': 'dismiss this answer',
        onclick: function () { B.ask.reply = null; K.renderBody(); } }, '✕'));
  }

  /* One 56px row under the stage. On the phone the field collapses behind Ask, beside the
     paperclip, because a 390px row cannot hold a field, a Send and a clip at 44px each. */
  function askRow() {
    var open = K.isDesk() || B.ask.open;
    return K.el('div', { class: 'bask' },
      K.el('div', { class: 'bask-row' },
        open ? K.el('input', { class: 'bask-in', type: 'text', 'data-fk': 'board-ask',
          value: askValue(), disabled: B.ask.busy ? true : null,
          placeholder: 'Ask this board’s house to draw or explain something',
          oninput: function (ev) { askTyped(ev.target.value); },
          onkeydown: function (ev) { if (ev.key === 'Enter') { ev.preventDefault(); sendAsk(); } } }) : null,
        open ? K.el('button', { class: 'btn primary bask-send', disabled: B.ask.busy ? true : null,
          onclick: sendAsk },
          B.ask.busy ? K.el('span', { class: 'spin', 'aria-label': 'asking' }) : 'Send') : null,
        !open ? K.el('button', { class: 'btn bask-open',
          onclick: function () { B.ask.open = true; K.renderBody(); } }, 'Ask') : null,
        clipControl()),
      askReply());
  }

  /* THE SEGMENTS' ATTACH CONTROL, pointed at this board: the same three types, the same
     10MB cap and the same one-file-per-request shape the segment apps have used since the
     old dashboard. The checks here are for a clearer no; the ones that matter are the
     server's (`keel/boardfiles.py`). */
  function clipControl() {
    return K.el('label', { class: 'btn bask-clip', title: 'put a file on this board',
      'aria-label': 'put a file on this board' },
      K.el('span', { 'aria-hidden': 'true' }, '📎'),
      K.el('input', { type: 'file', hidden: true, multiple: true,
        accept: 'application/pdf,image/png,image/jpeg',
        onchange: function (ev) { uploadFiles(ev.target.files); ev.target.value = ''; } }));
  }

  function typeOf(file) {
    var ext = String(file.name || '').split('.').pop().toLowerCase();
    return UPLOAD_TYPES[ext] || (file.type === 'application/pdf' || /^image\/(png|jpeg)$/.test(file.type)
      ? file.type : '');
  }

  function uploadFiles(files) {
    var list = Array.prototype.slice.call(files || []);
    if (!list.length || !K.App.board) return;
    var id = K.App.board;
    /* One at a time: a phone on a weak connection sending four at once is how a batch half
       fails, and each one settles visibly on its own. */
    list.reduce(function (chain, file) {
      return chain.then(function () { return uploadOne(id, file); });
    }, Promise.resolve()).then(function () {
      if (B.open && B.open.id === id) loadBoard(id, B.open.cursor);
    });
  }

  function uploadOne(id, file) {
    var kind = typeOf(file);
    if (!kind) { K.toast(file.name + ' is not a PDF, a PNG or a JPEG', true); return Promise.resolve(); }
    if (file.size > UPLOAD_MAX) { K.toast(file.name + ' is bigger than the 10MB limit', true); return Promise.resolve(); }
    return K.post('/api/board/' + encodeURIComponent(id) + '/inbox?name=' + encodeURIComponent(file.name),
                  { method: 'POST', headers: { 'Content-Type': kind }, body: file })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { K.toast(d.error || 'that file was refused', true); return; }
        K.toast(d.duplicate ? file.name + ' was already on this board'
          : file.name + ' is on the board, and the house is told');
      })
      .catch(function (e) { K.toast('that file did not reach the deck: ' + e.message, true); });
  }

  /* The list is `GET /api/boards` (C5): every board with its card's title and story, which
     is what grouping by card needs; `board.list` stays the verb's. */
  function loadList(force) {
    if ((B.list && !force) || B.listing) return;
    B.listing = true;
    fetch('/api/boards', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) { B.listing = false; B.list = d.rows || []; K.renderBody(); })
      .catch(function () { B.listing = false; B.list = B.list || []; K.renderBody(); });
  }

  function fullAsked(id) {
    if (B.fullDone === id || typeof location === 'undefined') return false;
    var asked = new URLSearchParams(location.search).get('full') === '1';
    if (asked) B.fullDone = id;
    return asked;
  }
  /* `?upto=<n>` (c-604 review): the board as it stood at its first n lines, which is how an
     approved plan links it: the picture he approved, never the redraw since. It does not
     follow the live channel. */
  function uptoAsked() {
    if (typeof location === 'undefined') return 0;
    var n = parseInt(new URLSearchParams(location.search).get('upto') || '0', 10);
    return n > 0 ? n : 0;
  }
  function loadBoard(id, since) {
    if (B.wanted === id && since) return;
    if (since && B.open && B.open.id === id && B.open.pinned) return;
    /* a board that answered with an error is not asked again on every render pass; a move
       to another board, a Restore or a reload asks afresh */
    if (!since && B.error && B.errorFor === id) return;
    var cursor = since || 0;
    if (!cursor) B.wanted = id;
    fetch('/api/board/' + encodeURIComponent(id) + '?since=' + cursor, { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error || !d.id) {
          B.wanted = null;
          B.error = d.error || 'that board is not there';
          B.errorFor = id;
          /* DELETED, not missing (lane BD): the page offers him Restore */
          B.gone = d.deleted || null;
          K.renderBody();
          return;
        }
        B.error = null;
        B.gone = null;
        if (!cursor || !B.open || B.open.id !== id) {
          /* another board is another conversation: the half-typed question, the node it was
             about, the answer on screen and where the walk had got to all belonged to the
             one he left */
          if (!B.open || B.open.id !== id) { resetAsk(); B.node = null; B.step = 0; }
          var upto = uptoAsked();
          B.open = { id: id, record: d, model: foldInto(newModel(), upto ? d.lines.slice(0, upto) : d.lines),
                     cursor: d.next, pinned: upto };
          /* A SEARCH HIT OPENS ITS BOARD WITH THAT NODE LIT (C5): the node is opened as a
             tap would open it, once the model that holds it has arrived. */
          if (B.lit && B.lit.board === id && nodeBy(B.open.model, B.lit.node)) {
            B.node = B.lit.node;
            B.panel = true;
          }
          B.lit = null;
          B.wanted = null;
          /* `?full=1` OPENS IT FULL SCREEN, once: what a tap on a board embedded in a plan
             asks for (P2-1). With no gesture behind it the desk's Fullscreen API refuses,
             so it is the focus mode, which is the same layout. */
          if (fullAsked(id) && K.boardFull && !B.full) K.boardFull.enter();
        } else {
          foldInto(B.open.model, d.lines);
          B.open.record = d;
          B.open.cursor = d.next;
        }
        K.renderBody();
      })
      .catch(function () { B.wanted = null; });
  }

  /* THE LIVE CHANNEL IS THE EVENT STREAM (`/api/events`, ui.core.js): the server names
     the board and the line it has reached, and `K.loadBoard` is called with the cursor
     this page holds. A node pushed while a house is speaking lands as it is written
     rather than up to five seconds later, which is what this poll used to cost.
     The poll below is what remains: a FALLBACK, on the same terms as the deck's own, for
     while the stream is shut. */
  function tick() {
    if (document.visibilityState !== 'visible' || K.streamOpen()) return;
    if (K.App.view !== 'board' || !K.App.board || !B.open) return;
    if (B.open.record && B.open.record.closed) return;   // a closed board never grows
    loadBoard(B.open.id, B.open.cursor);
  }
  setInterval(tick, K.POLL_MS);
  K.loadBoard = loadBoard;

  /* ---------- routing ---------- */
  function goBoard(id, view, replace) {
    var path = '/board' + (id ? '/' + id : '') + (id && view && view !== 'diagram' ? '?view=' + view : '');
    if (replace) history.replaceState(null, '', path); else history.pushState(null, '', path);
    K.App.view = 'board';
    K.App.board = id || null;
    K.App.boardView = id ? (view || null) : null;
    K.store('view', 'board');
    /* the stream watches ONE board, named in its own URL, so a move between boards
       re-opens it (ui.core.js `openStream`) */
    K.openStream();
    K.renderBody();
    K.renderRail();
    K.renderDock();
  }
  K.goBoard = goBoard;

  function setView(name) {
    if (K.App.board) K.store('boardview-' + K.App.board, name);
    goBoard(K.App.board, name, true);
  }

  /* ---------- the chrome ---------- */
  /* WHOSE BOARD THIS IS, said the same way everywhere it is said. A card's board wears its
     own space's colour, which is what tells two boards from two spaces apart in one list;
     Harbor's says Harbor. The level is never implied by where the board is shown. */
  function sourceChip(record) {
    var source = record.source || {};
    if (source.kind === 'card') {
      var card = K.byId(source.card);
      var space = card ? card.space : K.App.space;
      return K.el('span', { class: 'bchip space-' + space, title: 'a house drew this, on ' + source.card,
        text: source.card });
    }
    return K.el('span', { class: 'bchip', title: 'Harbor drew this: it belongs to no card',
      text: 'Harbor' });
  }

  function viewSwitch() {
    var now_ = viewOf();
    return K.el('div', { class: 'bswitch bviews' }, VIEWS.map(function (name) {
      return K.el('button', { class: now_ === name ? 'on' : '', 'data-key': name,
        'aria-label': 'see this board as a ' + name,
        onclick: function () { setView(name); } }, name);
    }));
  }

  function metaRow(record) {
    var live = record.live && !record.closed;
    return K.el('div', { class: 'board-meta' },
      K.el('h2', { class: 'title ellip', title: record.title, text: record.title || 'Untitled board' }),
      sourceChip(record),
      live ? K.el('span', { class: 'livedot', title: 'this board is live' }) : null,
      K.el('span', { class: 'mono t11 ink3',
        text: record.nodes + (record.nodes === 1 ? ' node' : ' nodes') }),
      K.el('span', { class: 'spacer' }),
      viewSwitch(),
      tabSwitch(),
      K.boardFull ? K.boardFull.button() : null,
      K.boardDelete ? K.boardDelete.boardMenu(record) : null);
  }

  /* AFTER A DELETE (lane BD): the list is read again, and a board that was open and is now
     in the trash hands the page back to Saved, since there is nothing left to draw. */
  K.boardAfterDelete = function (ids) {
    loadList(true);
    if (B.open && ids.indexOf(B.open.id) >= 0) {
      B.open = null;
      if (K.App.board && ids.indexOf(K.App.board) >= 0) { B.tab = 'saved'; goBoard(null, null, true); }
    }
  };
  K.boardAfterRestore = function (id) {
    loadList(true);
    if (B.errorFor === id) { B.error = null; B.errorFor = null; B.gone = null; loadBoard(id, 0); }
  };

  /* With no board open the route IS the saved list, so the tab says Saved rather than a
     Live it is not showing. */
  function tabSwitch() {
    var shown = K.App.board ? B.tab : 'saved';
    return K.el('div', { class: 'bswitch' }, ['live', 'saved'].map(function (name) {
      return K.el('button', { class: shown === name ? 'on' : '', 'data-key': name,
        'aria-pressed': shown === name ? 'true' : 'false',
        onclick: function () { B.tab = name; if (name === 'saved') loadList(true); K.renderBody(); } },
        name === 'live' ? 'Live' : 'Saved');
    }));
  }

  /* ---------- the diagram view ----------
   * THE STAGE IS NOT THE RENDER PASS'S. `drawGraph` builds it (an ELK layout, an entrance
   * animation, a badge) and his finger pans and zooms it, so it is marked
   * `data-morph="skip"` and the morph leaves it whole, unconditionally: the pass builds
   * that node EMPTY, so a pass that touched it would delete the diagram and leave nothing
   * in its place. Keeping it current is the drawing's own job, off the model's `version`.
   * The head around it is ordinary and morphs like anything else. */

  /* THE SHAPE A BOARD WAS DRAWN IN IS KEPT (K-5). The layout chosen for this board, at this
     version, in this view (the diagram or the walk) is remembered on the page state rather
     than on the host, because full screen builds a NEW host. A redraw of the same board at a
     new size (the rail, the node column, a resize) lays that same choice out and only refits
     the zoom; `layoutBest` chooses again when it cannot be read whole there within the slack,
     or when an op has changed the board. Entering or leaving full screen forgets it first
     (K-12). */
  function keepShape(host, model) {
    var key = B.open.id + ':' + viewOf();
    var kept = (B.layouts || {})[key];
    host._kept = kept && kept.version === model.version ? kept.choice : null;
    host._keep = function (choice) {
      B.layouts = B.layouts || {};
      B.layouts[key] = { version: model.version, choice: choice };
    };
  }

  /* `walk` is the lit step for the walk's callout (app/ui.boardcallout.js), or null. */
  function stageHost(model, compact, focus, walk) {
    var host = K.el('div', { class: 'bframe-body kind-graph' + (compact ? ' compact' : ''),
      'data-morph': 'skip' });
    var key = compact ? '.walkgraph .bframe-body' : '.bstage .bframe-body';
    setTimeout(function () {
      var live = document.querySelector(key);
      if (!live) return;
      live._compact = compact;
      live._focus = focus || null;
      live._walk = walk || null;
      focusNodes(live);
      /* THE SHAPE OF THE STAGE, not just its width. An ELK layout writes the svg's own
         `height` attribute from the wrap it measured, so the wrap cannot shrink under it:
         when the phone's drawer opens and the stage is asked to give up half its height,
         the old attribute holds it at the size it had and the diagram is left as a sliver
         behind the drawer. So a change of SHAPE is a reason to lay out again, exactly as a
         change of width is. */
      var shape = (K.isDesk() ? 'desk' : 'phone') + (B.node ? ':open' : ':shut') +
        (B.full ? ':full:' + window.innerWidth + 'x' + window.innerHeight : '');
      if (live._drawn === model.version && live._shape === shape) return;
      live._drawn = model.version;
      live._shape = shape;
      keepShape(live, model);
      drawGraph(live, model, live._for !== B.open.id);
      live._for = B.open.id;
    }, 0);
    return host;
  }

  function diagramView(model) {
    var node = B.node ? nodeBy(model, B.node) : null;
    var desk = K.isDesk();
    /* `open` is the phone's shape when a node's drawer is up: the diagram gives way to it
       and becomes a thumbnail, because what he asked for by tapping is the content. */
    return K.el('div', { class: 'bdiagram' + (node && !desk ? ' open' : '') },
      K.el('div', { class: 'bframe bstage', 'data-key': 'bstage' },
        K.el('div', { class: 'bframe-head' },
          K.el('span', { class: 'label ellip', text: 'Diagram' }),
          K.el('span', { class: 'spacer' }),
          K.el('span', { class: 'mono t11 ink3',
            text: model.nodes.length + ' nodes \u00b7 ' + model.attachments.length + ' attached' }),
          K.el('button', { class: 'bnav fitbtn', title: 'fit the diagram to the stage',
            'aria-label': 'fit the diagram to the stage',
            onclick: function (ev) {
              var svg = ev.currentTarget.closest('.bframe').querySelector('.graph');
              if (svg && svg._fit) svg._fit();
            } }, 'Fit')),
        stageHost(model, false, B.node)),
      node ? nodePanel(model, node, desk) : (desk ? boardPanel(model) : null));
  }

  /* The node's own attachments: a 320px column on the desk, a drawer over the bottom of
     the phone. Same content, same builders, two shapes. */
  function nodePanel(model, node, desk) {
    if (desk && !B.panel) {
      return K.el('aside', { class: 'bpanel shut', 'data-key': 'bpanel' },
        K.el('button', { class: 'bnav', 'aria-label': 'show this node',
          onclick: function () { B.panel = true; K.renderBody(); } }, '\u2039'));
    }
    return K.el('aside', { class: 'bpanel' + (desk ? '' : ' drawer'), 'data-key': 'bpanel' },
      K.el('div', { class: 'bpanel-head' },
        K.el('span', { class: 'label ellip', title: node.label, text: node.label }),
        K.el('span', { class: 'spacer' }),
        desk ? K.el('button', { class: 'bnav', 'aria-label': 'hide this node',
          onclick: function () { B.panel = false; K.renderBody(); } }, '\u203a') : null,
        K.el('button', { class: 'bnav', 'aria-label': 'close this node',
          onclick: function () { B.node = null; B.ask.about = null; K.renderBody(); } }, '✕')),
      node.sub ? K.el('div', { class: 'bpanel-sub mono t11 ink2', text: node.sub }) : null,
      K.el('div', { class: 'bpanel-body' },
        attachmentList(model, node.id, 'nothing hangs on this node yet')));
  }

  /* With no node open the desk's column shows what hangs on the BOARD, which is where a
     house puts the thing that is about the whole picture.

     AND IT IS SHUT WHEN THERE IS NOTHING IN IT. A board with no board-level attachments and
     no node open had 320px of column saying "tap a node to see what hangs on it", taken off
     the stage of a diagram that needed every pixel. It opens by itself when there IS
     something to read, and on a tap; `B.panel` is his own answer once he has given one, and
     `null` until then. */
  function boardPanelOpen(model) {
    if (B.panel !== null) return B.panel;
    return attachmentsOn(model, BOARD_TARGET).length > 0;
  }

  function boardPanel(model) {
    if (!boardPanelOpen(model)) {
      return K.el('aside', { class: 'bpanel shut', 'data-key': 'bpanel' },
        K.el('button', { class: 'bnav', 'aria-label': 'show the board\u2019s own notes',
          onclick: function () { B.panel = true; K.renderBody(); } }, '\u2039'));
    }
    return K.el('aside', { class: 'bpanel', 'data-key': 'bpanel' },
      K.el('div', { class: 'bpanel-head' },
        K.el('span', { class: 'label', text: 'On the board' }),
        K.el('span', { class: 'spacer' }),
        K.el('button', { class: 'bnav', 'aria-label': 'hide this column',
          onclick: function () { B.panel = false; K.renderBody(); } }, '\u203a')),
      K.el('div', { class: 'bpanel-body' },
        attachmentList(model, BOARD_TARGET, 'tap a node to see what hangs on it')));
  }

  /* ---------- the outline view ----------
   * The whole board as a document: what hangs on the board first, then each group as a
   * heading with its nodes under it, then anything not in a group. This is what replaced
   * "All frames", and it is the view that answers "just let me read the thing". */
  function outlineNode(model, node, steps) {
    var items = attachmentsOn(model, node.id);
    return K.el('section', { class: 'bo-node', 'data-key': 'n' + node.id },
      K.el('div', { class: 'bo-node-head' },
        K.el('span', { class: 'bo-icon' }, iconNode(node.icon)),
        K.el('div', { class: 'bo-names' },
          K.el('h4', { class: 't', text: node.label }),
          node.sub ? K.el('div', { class: 'mono t11 ink2', text: node.sub }) : null),
        node.mark ? K.el('span', { class: 'bchip mark-' + node.mark, text: node.mark }) : null),
      items.length
        ? K.el('div', { class: 'battachments' }, items.map(function (item) {
            return attachmentNode(item, steps);
          }))
        : null);
  }

  function outlineView(model) {
    var steps = stepsOf(model);
    var grouped = {};
    model.nodes.forEach(function (n) {
      var key = n.group && model.groups.some(function (g) { return g.id === n.group; }) ? n.group : '';
      (grouped[key] = grouped[key] || []).push(n);
    });
    var sections = model.groups.filter(function (g) { return (grouped[g.id] || []).length; })
      .map(function (g) {
        return K.el('section', { class: 'bo-group', 'data-key': 'g' + g.id },
          K.el('h3', { class: 'label', text: g.label }),
          grouped[g.id].map(function (n) { return outlineNode(model, n, steps); }));
      });
    var loose = grouped[''] || [];
    if (loose.length) {
      sections.push(K.el('section', { class: 'bo-group', 'data-key': 'g-loose' },
        model.groups.length ? K.el('h3', { class: 'label', text: 'On its own' }) : null,
        loose.map(function (n) { return outlineNode(model, n, steps); })));
    }
    var onBoard = attachmentsOn(model, BOARD_TARGET);
    return K.el('div', { class: 'boutline' },
      onBoard.length
        ? K.el('section', { class: 'bo-board', 'data-key': 'g-board' },
            K.el('div', { class: 'battachments' }, onBoard.map(function (item) {
              return attachmentNode(item, steps);
            })))
        : null,
      sections.length ? sections : K.el('div', { class: 'empty', text: 'nothing drawn yet' }));
  }

  /* ---------- the walk view ----------
   * The steps in push order, one at a time, over a compact diagram with that step's node
   * lit. THE STEP IS READ WHERE IT HAPPENS (Z1, lane Z): on the desk its words are a callout
   * flowing out of the lit node (`app/ui.boardcallout.js`), and the row under the diagram
   * keeps only the steppers and the node's name. On the phone the diagram is on top and the
   * words are a caption bar under it, beside the steppers his thumb is already on. */
  function walkSpec(model, steps, at, nav) {
    var item = steps[at];
    var node = item.at === BOARD_TARGET ? null : nodeBy(model, item.at);
    return { text: item.text, n: at + 1, of: steps.length, label: node ? node.label : '', nav: !!nav };
  }

  function walkCaption(item, at, count) {
    return K.el('div', { class: 'wcall-caption inflow', 'data-key': 'caption', role: 'note' },
      K.el('div', { class: 'wcall-words' },
        K.el('div', { class: 'wcall-n', text: 'Step ' + (at + 1) + ' of ' + count }),
        K.el('div', { class: 'wcall-text', text: item.text })));
  }

  function walkView(model) {
    var steps = stepsOf(model);
    if (!steps.length) {
      return K.el('div', { class: 'bwalk' },
        K.el('div', { class: 'empty', text: 'this board has no steps on it; the outline reads it whole' }));
    }
    var at = Math.max(0, Math.min(B.step, steps.length - 1));
    B.step = at;
    var item = steps[at], desk = K.isDesk();
    var node = item.at === BOARD_TARGET ? null : nodeBy(model, item.at);
    return K.el('div', { class: 'bwalk' },
      K.el('div', { class: 'bframe walkgraph', 'data-key': 'walkgraph' },
        stageHost(model, true, node ? node.id : null, desk ? walkSpec(model, steps, at, false) : null)),
      K.el('div', { class: 'bwalk-step', 'data-key': 'walkstep' },
        K.el('div', { class: 'bwalk-head' },
          K.el('button', { class: 'bnav', 'aria-label': 'the step before this one',
            disabled: at <= 0 ? true : null,
            onclick: function () { B.step = at - 1; K.renderBody(); } }, '\u2039'),
          K.el('span', { class: 'bcount mono t11 ink2', text: (at + 1) + ' of ' + steps.length }),
          K.el('button', { class: 'bnav', 'aria-label': 'the next step',
            disabled: at >= steps.length - 1 ? true : null,
            onclick: function () { B.step = at + 1; K.renderBody(); } }, '\u203a'),
          K.el('span', { class: 'spacer' }),
          node ? K.el('button', { class: 'bchip on', 'data-key': 'at',
            onclick: function () { openNode(node.id); setView('diagram'); }, }, node.label)
            : K.el('span', { class: 'bchip', text: 'on the board' }),
          desk ? K.el('span', { class: 'mono t11 ink3 bwalk-keys', text: '\u2190 \u2192 to step, Esc to leave' }) : null),
        desk ? null : walkCaption(item, at, steps.length)));
  }

  /* ---------- Saved: the list, grouped by card and by topic (app/ui.boardlist.js) ----------
   * His words: "boards can be at house level and global level and it should clearly show
   * that". The level is still the first split (Houses, Harbor); inside it a house's boards
   * are grouped by card and Harbor's by topic, and the card in context leads. */
  function cardInContext() {
    if (K.App.card) return K.App.card;
    var source = B.open && B.open.record ? (B.open.record.source || {}) : {};
    return source.kind === 'card' ? source.card : null;
  }

  var listApi = {
    state: B,
    load: function () { loadList(); },
    context: cardInContext,
    chip: function (record, space) {
      var chip = sourceChip(record);
      if (space) chip.className = 'bchip space-' + space;
      return chip;
    },
    open: function (id, node) {
      B.tab = 'live';
      B.lit = node ? { board: id, node: node } : null;
      if (node && B.open && B.open.id === id) { B.node = node; B.panel = true; B.lit = null; }
      goBoard(id, node ? 'diagram' : null, false);
    }
  };

  function savedList() {
    if (!K.boardList) return K.el('div', { class: 'empty', text: 'the board list did not load' });
    return K.boardList.view(listApi);
  }

  /* ---------- the view ---------- */
  function viewBoard() {
    var id = K.App.board;
    if (id && (!B.open || B.open.id !== id)) loadBoard(id, 0);
    if (!id || B.tab === 'saved') {
      /* not `grow`: the list's panel grows with its rows (c-562), see `.blist-panel` */
      return K.el('section', { class: 'panel blist-panel' },
        K.el('div', { class: 'panel-head' },
          K.el('span', { class: 'label', text: 'Board' }),
          K.el('span', { class: 'spacer' }), tabSwitch()),
        K.el('div', { class: 'panel-body' }, savedList()));
    }
    if (B.error) {
      return K.el('section', { class: 'panel grow' },
        K.el('div', { class: 'panel-head' }, K.el('span', { class: 'label', text: 'Board' })),
        K.el('div', { class: 'panel-body' },
          B.gone && K.boardDelete
            ? K.boardDelete.goneView(id, B.gone, function () { K.boardAfterRestore(id); })
            : K.el('div', { class: 'empty', text: B.error }),
          K.el('button', { class: 'btn sm', onclick: function () { B.error = null; B.errorFor = null; B.gone = null; goBoard(null, null, false); } }, 'Saved boards')));
    }
    if (!B.open || B.open.id !== id) {
      return K.el('section', { class: 'panel grow' },
        K.el('div', { class: 'panel-head' }, K.el('span', { class: 'label', text: 'Board' })),
        K.el('div', { class: 'panel-body' }, K.el('div', { class: 'empty', text: 'reading ' + id + '...' })));
    }
    var model = B.open.model, view = viewOf();
    if (B.full && K.boardFull) return K.boardFull.view(model, view);
    var body = view === 'outline' ? outlineView(model)
      : view === 'walk' ? walkView(model) : diagramView(model);
    return K.el('section', { class: 'panel grow boardroute', 'data-view': view },
      K.el('div', { class: 'panel-head' },
        !K.isDesk() ? K.el('button', { class: 'btn sm', onclick: function () { goBoard(null, null, false); } }, '\u2039 boards')
          : K.el('span', { class: 'label', text: 'Board' }),
        K.el('span', { class: 'spacer' }),
        B.open.pinned ? K.el('span', { class: 'chip', 'data-key': 'pinned', text: 'as approved in the plan' }) : null,
        K.el('span', { class: 'mono t11 ink3', text: B.open.id })),
      K.el('div', { class: 'panel-body board-body' },
        metaRow(B.open.record),
        K.el('div', { class: 'board-cols' }, body),
        askRow()));
  }
  K.viewBoard = viewBoard;

  /* What the full-screen layout (app/ui.boardfull.js) builds with: the same stage, the same
     attachment renderers and the same view switch, so full screen is a different ARRANGEMENT
     of the one board rather than a second rendering of it. */
  K.boardInner = { stageHost: stageHost, viewSwitch: viewSwitch, attachmentList: attachmentList,
                   walkSpec: walkSpec,
                   outlineView: outlineView, nodeBy: nodeBy, stepsOf: stepsOf, viewOf: viewOf,
                   setView: setView, VIEWS: VIEWS, BOARD_TARGET: BOARD_TARGET };

  /* A resize changes what fits, so a mounted graph is forgotten and drawn again at the new
     size: in the shape it already had while that can still be read whole there (K3,
     `keepShape`), and chosen afresh when it cannot or when the desk became the phone. */
  window.addEventListener('resize', function () {
    Array.prototype.forEach.call(document.querySelectorAll('.kind-graph'), function (host) {
      host._view = null;
      host._drawn = -1;
      host._shape = '';
    });
  });

  /* The phone reaches the Board under More, the way it reaches the Atlas: the dock holds
     five items and the Board is the sixth thing. On the desk it is a rail item, which
     `app/ui.core.js` lists. */
  var baseMore = K.viewMore;
  K.viewMore = function () {
    var out = baseMore ? baseMore() : [];
    if (!Array.isArray(out)) out = [out];
    out.splice(0, 0, K.el('section', { class: 'panel' },
      K.el('div', { class: 'panel-head' }, K.el('span', { class: 'label', text: 'The board' })),
      K.el('div', { class: 'panel-body' },
        K.el('button', { class: 'row', onclick: function () { goBoard(null, null, false); } },
          K.el('div', { class: 'row-head' }, K.el('span', { class: 't', text: 'Board' }),
            K.el('span', { class: 'spacer' }),
            K.el('span', { class: 'mono t11 ink3', text: 'what a house drew for you' }))))));
    return out;
  };

  /* The drawing, without the route: what the plan page (app/ui.plandiagram.js) draws a
     diagram in a plan with, so a mermaid block or a board embedded in a plan is laid out and
     drawn by exactly this code, in exactly this theme, and never by a second renderer. */
  K.boardDraw = { newModel: newModel, foldInto: foldInto, svgEl: svgEl, arrowDefs: arrowDefs,
                  layoutEngine: layoutEngine, chooseLayout: chooseLayout, layoutOnce: layoutOnce,
                  absolute: absolute, edgesAbsolute: edgesAbsolute, drawGroups: drawGroups,
                  drawEdges: drawEdges, drawNodes: drawNodes, raiseTitles: raiseTitles,
                  attachmentList: attachmentList, iconShapes: iconShapes, outlineView: outlineView,
                  stepsOf: stepsOf, attachmentsOn: attachmentsOn, drawGraph: drawGraph };

  /* What the test harness reads. Everything above is the deck's; this is the seam the
     grammar tests come in through, and it costs one object. */
  K.board = { parseLine: parseLine, applyOp: applyOp, newModel: newModel, foldInto: foldInto,
              clampScale: clampScale, fittedView: fittedView, fitScale: fitScale,
              fitBoth: fitBoth, layoutScore: layoutScore, layoutBest: layoutBest, buildGraph: buildGraph,
              visibleShare: visibleShare, groupTitleBox: groupTitleBox, GROUP_PAD_TOP: GROUP_PAD_TOP,
              viewFor: viewFor, panFor: panFor, wrapOptions: wrapOptions,
              zoomAbout: zoomAbout,
              fitText: fitText, textWidth: textWidth,
              OPS: OPS, ATTACH_KINDS: ATTACH_KINDS, MARKS: MARKS, ARROWS: ARROWS,
              BOARD_MODES: BOARD_MODES,
              ICON_NAMES: ICON_NAMES, VIEWS: VIEWS };
})(window.Keel);
