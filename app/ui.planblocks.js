/* The plan page's blocks: one renderer per kind of the closed set.
 *
 * Every block arrives from the server already typed (keel/planformat.py), and every string
 * in it is a SPAN, never markup: this file builds each node with `K.el` and `textContent`,
 * the way the board does, so nothing a house wrote can run in the origin the approve verbs
 * live in. The page owns the look: the deck's tokens, its four sizes and two weights.
 *
 * The answerable blocks (a decision, a batch, the open questions, a review finding) read and write their
 * answers through `P` (app/ui.plan.js), which holds the round: the page shows his pick where
 * he made one and the recommendation where he did not, and says which it is.
 */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';
  var el = K.el;

  /* ---------- inline spans ---------- */
  function spans(list) {
    return (list || []).map(function (s) {
      if (s.t === 'text') return document.createTextNode(s.v);
      if (s.t === 'code') return el('code', { text: s.v });
      if (s.t === 'strong') return el('strong', {}, spans(s.c));
      if (s.t === 'em') return el('em', {}, spans(s.c));
      if (s.t === 'link') return link(s);
      if (s.t === 'ref') return ref(s);
      return document.createTextNode(s.v || '');
    });
  }
  function link(s) {
    if (!s.href) return el('span', { class: 'unserved', title: s.why || 'not served', text: s.v });
    return el('a', { href: s.href, target: /^https?:/.test(s.href) ? '_blank' : null, rel: 'noopener' }, s.v);
  }
  function ref(s) {
    if (s.kind === 'card') {
      return el('a', { class: 'pref card', href: '/?view=cards&card=' + s.v,
        onclick: function (ev) { ev.preventDefault(); K.go(K.cardRoute(K.byId(s.v)), s.v); } }, s.v);
    }
    var broken = s.kind === 'path' && K.plan && K.plan.brokenRef(s.v);
    return el('span', { class: 'pref ' + s.kind + (s.code ? ' mono' : '') + (broken ? ' broken' : ''),
      title: broken || null, text: s.v });
  }
  function para(list, cls) { return el('p', { class: cls || null }, spans(list)); }
  function words(list) { return (list || []).map(function (s) { return s.v || words(s.c); }).join(''); }

  /* ---------- the plain blocks ---------- */
  function heading(b) {
    if (b.level === 2) return el('h2', { class: 'ph2' + (b.name ? ' named n-' + b.name : '') }, spans(b.text));
    return el('h3', { class: 'ph3' }, spans(b.text));
  }
  function list(b) {
    return el(b.ordered ? 'ol' : 'ul', { class: 'plist' + (b.ordered ? ' ordered' : '') },
      b.items.map(function (item, i) {
        return el('li', { 'data-key': 'i' + i },
          item.lead ? el('strong', { class: 'lead' }, spans(item.lead), ' ') : null, spans(item.text),
          item.children ? el('ul', { class: 'plist sub' }, item.children.map(function (c, j) {
            return el('li', { 'data-key': 'c' + j }, c.lead ? el('strong', { class: 'lead' }, spans(c.lead), ' ') : null, spans(c.text));
          })) : null);
      }));
  }
  function checklist(b) {
    return el('ul', { class: 'pcheck' }, b.items.map(function (item, i) {
      return el('li', { class: item.done ? 'done' : '', 'data-key': 'i' + i },
        el('span', { class: 'box', 'aria-hidden': 'true', text: item.done ? '✓' : '' }),
        el('span', { class: 'sr', text: item.done ? 'done: ' : 'to do: ' }), spans(item.text));
    }));
  }
  function table(b) {
    return el('div', { class: 'ptablewrap', tabindex: '0' },
      el('table', { class: 'ptable' },
        el('thead', {}, el('tr', {}, b.head.map(function (h) { return el('th', {}, spans(h)); }))),
        el('tbody', {}, b.rows.map(function (row, i) {
          return el('tr', { 'data-key': 'r' + i }, row.map(function (cell) {
            return el('td', {}, cell.chip ? el('span', { class: 'chip tone-' + cell.chip, text: cell.chip }) : null,
              cell.chip ? ' ' : null, spans(cell.text));
          }));
        }))));
  }
  var TONE_WORD = { info: 'Note', warn: 'Careful', error: 'Broken', success: 'Landed', settled: 'Settled' };
  function callout(b) {
    return el('div', { class: 'pcallout tone-' + b.tone, role: b.tone === 'error' ? 'alert' : null },
      el('div', { class: 'pc-head' }, el('span', { class: 'pc-tone', text: TONE_WORD[b.tone] || 'Note' }),
        b.title && b.title.length ? el('span', { class: 'pc-title' }, spans(b.title)) : null),
      (b.body || []).map(function (p) { return para(p); }));
  }
  function quote(b) { return el('blockquote', { class: 'pquote' }, (b.body || []).map(function (p) { return para(p); })); }

  /* Code, diffs and copy blocks are app/ui.plancode.js's: it colours them (lane FC, FC-3). */
  function code(b) { return K.planCode.code(b); }
  function copyBlock(b) { return K.planCode.copyBlock(b); }
  function images(b) {
    return el('div', { class: 'pimages' + (b.items.length > 1 ? ' gallery' : '') }, b.items.map(function (item, i) {
      return el('figure', { class: 'pfig frame-' + item.frame, 'data-key': 'f' + i },
        item.src ? el('a', { href: item.src, target: '_blank', rel: 'noopener' },
          el('img', { src: item.src, alt: words(item.caption), loading: 'lazy', decoding: 'async' }))
          : el('div', { class: 'unserved pfig-missing', title: item.why || '', text: item.path }),
        item.caption && item.caption.length ? el('figcaption', {}, spans(item.caption)) : null);
    }));
  }
  function stats(b) {
    return el('div', { class: 'pstats' }, b.tiles.map(function (t, i) {
      return el('div', { class: 'pstat' + (t.tone ? ' tone-' + t.tone : ''), 'data-key': 's' + i },
        el('div', { class: 'label', text: t.label }), el('div', { class: 'pstat-v', text: t.value }),
        t.sub ? el('div', { class: 't11 ink2', text: t.sub }) : null);
    }));
  }
  var STEP_WORD = { todo: 'to do', doing: 'doing', done: 'done', blocked: 'blocked' };
  function steps(b) {
    return el('ol', { class: 'psteps' }, b.items.map(function (item, i) {
      return el('li', { class: 'st-' + item.state, 'data-key': 'i' + i },
        el('span', { class: 'n mono', text: String(i + 1) }),
        el('div', { class: 'pst-body' },
          el('div', { class: 'pst-title' }, spans(item.title),
            el('span', { class: 'chip st st-' + item.state, text: STEP_WORD[item.state] })),
          item.body ? el('div', { class: 'ink2' }, spans(item.body)) : null));
    }));
  }
  function compare(b) {
    var imageRow = function (row, i) {
      return el('div', { class: 'pcmp-row img', 'data-key': 'r' + i },
        ['left', 'right'].map(function (side) {
          var src = row[side + '_src'];
          return el('div', { class: 'pcmp-cell' }, el('div', { class: 'label', text: b[side] }),
            src ? el('img', { src: src, alt: b[side], loading: 'lazy' }) : el('span', { class: 'unserved', text: row[side] }));
        }));
    };
    return el('div', { class: 'pcompare' },
      b.title && b.title.length ? el('div', { class: 'pcmp-title' }, spans(b.title)) : null,
      el('div', { class: 'pcmp-head' }, el('span', {}), el('span', { class: 'label', text: b.left }), el('span', { class: 'label', text: b.right })),
      b.rows.map(function (row, i) {
        if (row.image) return imageRow(row, i);
        return el('div', { class: 'pcmp-row', 'data-key': 'r' + i },
          el('div', { class: 'pcmp-aspect' }, spans(row.aspect)),
          el('div', { class: 'pcmp-cell left' }, el('span', { class: 'label side', text: b.left }), cellText(row.left)),
          el('div', { class: 'pcmp-cell right' }, el('span', { class: 'label side', text: b.right }), cellText(row.right)));
      }));
  }
  /* A cell's words are ONE inline run (P2-4): the cell is a flex row for its side label,
     and spans laid straight into it became flex items side by side, so a cell of words,
     code and words was three columns and the next column's text ran over it. */
  function cellText(list) { return el('span', { class: 'pcmp-text' }, spans(list)); }
  function options(b) {
    return el('div', { class: 'poptions' }, b.options.map(function (o) {
      var rec = o.id === b.rec;
      return el('div', { class: 'popt' + (rec ? ' rec' : ''), 'data-key': o.id },
        el('div', { class: 'popt-head' }, el('span', { class: 'mono t11 ink2', text: o.id }),
          el('span', { class: 'popt-label' }, spans(o.label)), rec ? el('span', { class: 'chip tone-accent', text: 'recommended' }) : null),
        o.summary ? el('div', {}, spans(o.summary)) : null,
        el('ul', { class: 'pprocon' },
          (o.pros || []).map(function (p, i) { return el('li', { class: 'pro', 'data-key': 'p' + i }, spans(p)); }),
          (o.cons || []).map(function (p, i) { return el('li', { class: 'con', 'data-key': 'c' + i }, spans(p)); })));
    }), b.decision ? el('div', { class: 't11 ink2', text: 'answered in decision ' + b.decision }) : null);
  }
  /* A diagram's frame: its title, a Full screen button (a tap on the drawing does the same),
     the drawing, and a line that appears when the drawing is wider than the column. */
  function diagramHead(title, extra) {
    return el('div', { class: 'pdia-title' }, title ? el('span', { class: 'pdia-name' }, title) : el('span', { class: 'pdia-name' }),
      el('span', { class: 'spacer' }), extra || null);
  }
  function fullButton(opts, lines) {
    return el('button', { class: 'btn sm pdia-full', 'aria-label': 'open this diagram full screen',
      onclick: function (ev) { ev.stopPropagation(); if (K.planDiagram) K.planDiagram.full(opts, lines); } }, 'Full screen');
  }
  /* THE BOARD'S DRAWING IS FETCHED WHEN A DIAGRAM NEEDS IT (P4-7). The plan page's shell
     loads the core and the plan's renderers only, so a plan's words are on screen before
     the board's code (ui.board.js and its three companions, about 43 KB compressed) has
     been fetched, and a plan with no diagram never fetches it. The first diagram asks for
     the four in order and draws an empty frame of the same key meanwhile; once they have
     run the page renders again and the frame is drawn into (it is `data-morph="skip"`, so
     the render keeps the node and the drawing owns what is inside). ELK, bigger still,
     is fetched by the board's own code when the first graph is laid out, as before. */
  var DRAWING = ['/ui.boardlayout.js', '/ui.board.js', '/ui.planlook.js', '/ui.plandiagram.js'];
  var drawing = null;
  function needDrawing() {
    if (K.planDiagram || drawing) return;
    drawing = DRAWING.reduce(function (chain, src) {
      return chain.then(function () {
        return new Promise(function (resolve, reject) {
          var tag = document.createElement('script');
          tag.src = src;
          tag.onload = resolve;
          tag.onerror = function () { reject(new Error(src)); };
          document.head.appendChild(tag);
        });
      });
    }, Promise.resolve()).then(function () { if (K.renderBody) K.renderBody(); })
      .catch(function () { drawing = null; });
  }
  function diagramHost(key, lines, opts) {
    if (K.planDiagram) return K.planDiagram.host(key, lines, opts);
    needDrawing();
    return el('div', { class: 'pdiagram', 'data-key': key, 'data-morph': 'skip', 'aria-busy': 'true' });
  }
  function wideCue() {
    return el('div', { class: 't11 ink2 pdia-cue', text: 'Wider than the page: scroll it sideways, or open it full screen.' });
  }
  function diagram(b) {
    var title = b.title && b.title.length ? spans(b.title) : null;
    if (!b.ops || !b.ops.length) return el('div', { class: 'pdia' }, diagramHead(title), el('div', { class: 'empty', text: 'this diagram draws nothing' }));
    var opts = { title: words(b.title), icons: b.source !== 'mermaid' };
    return el('div', { class: 'pdia' }, diagramHead(title, fullButton(opts, b.ops)),
      diagramHost(b.id, b.ops, opts), wideCue(),
      el('div', { class: 't10 ink3 mono pdia-src', text: b.source === 'mermaid' ? b.kind + ', drawn by the board' : 'board lines' }));
  }
  /* AN EMBEDDED BOARD KEEPS ITS WALK (P2-2). A board is one model with attachments hanging
     on its nodes (B1): the steps, notes, tables and files are what make it more than a
     picture, and the embed used to draw only the picture. They are here, under the
     diagram, as the board's own outline (the same renderer as the board page's Outline
     view), folded behind a line that counts them; Open board and a tap on the drawing still
     go to the board itself, whose full screen view walks it step by step. */
  function boardWalk(b) {
    var D = K.boardDraw;
    if (!D || !D.outlineView || !b.ops || !b.ops.length) return null;
    var model = D.foldInto(D.newModel(), b.ops);
    var items = model.attachments || [], counts = {};
    if (!items.length) return null;
    items.forEach(function (a) { counts[a.kind] = (counts[a.kind] || 0) + 1; });
    var said = ['step', 'note', 'table', 'code', 'file'].filter(function (k) { return counts[k]; }).map(function (k) {
      return counts[k] + ' ' + k + (counts[k] === 1 ? '' : 's');
    }).join(', ');
    return el('details', { class: 'pwalk', 'data-key': 'walk' },
      el('summary', {}, el('span', { text: 'What hangs on this board' }), el('span', { class: 't11 ink2', text: said })),
      counts.step && b.ref ? walkLink(b.ref, counts.step, b.upto) : null,
      el('div', { class: 'pwalk-body' }, D.outlineView(model)));
  }
  /* THE WALK IS READ ON THE BOARD'S FULL SCREEN (Z1, lane Z): each step as a callout from
     its lit node. Open board stays the diagram's one button (R3-1); this is a plain link in
     the folded list, where the steps are counted, to the same full screen in its walk. */
  /* c-604 review: an approved plan's embed is the board AS APPROVED (`upto`, its line count
     then), and so is every link out of it, so a redraw at the built head never changes it */
  function pinned(upto) { return upto ? '&upto=' + upto : ''; }
  function walkLink(ref, count, upto) {
    return el('a', { class: 'pwalk-go', href: '/board/' + ref + '?view=walk&full=1' + pinned(upto),
      'aria-label': 'walk board ' + ref + ' full screen, one step at a time' },
      'Walk the ' + count + (count === 1 ? ' step' : ' steps') + ', full screen');
  }
  /* ONE BUTTON PER DIAGRAM (R3-1). An embedded board had Full screen and Open b-NNN, and
     both went to the board: the same place twice. It has one, Open board, to the board's
     own full screen view with its walk, where a tap on the drawing goes too. */
  function openBoard(ref, upto) {
    return el('a', { class: 'btn sm pdia-full', href: '/board/' + ref + '?full=1' + pinned(upto),
      'aria-label': 'open board ' + ref + ' full screen' }, 'Open board');
  }
  /* an outcome's board redrawn since the plan: the picture he approved, to compare with */
  function asPlanned(b) {
    return b.planned_upto ? el('a', { class: 'pwalk-go', 'data-key': 'as-planned',
      href: '/board/' + b.ref + '?full=1&upto=' + b.planned_upto }, 'As approved in the plan') : null;
  }
  /* A BOARD HE DELETED is a small placeholder, not an error (lane BD, BD-2): who deleted it,
     until when it can come back, and Restore, which is his and this page is his. */
  function deletedEmbed(b) {
    var d = b.deleted || {};
    var restore = el('button', { class: 'btn sm pdia-restore', type: 'button', 'data-key': 'restore',
      title: 'Restore: the board comes back to the list where it stood, with everything on it.',
      onclick: function (ev) {
        var btn = ev.currentTarget;
        btn.disabled = true;
        K.post('/api/action', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ verb: 'board.restore', id: b.ref }) })
          .then(function (r) { return r.json(); })
          .then(function (r) {
            if (!r.ok) { btn.disabled = false; if (K.toast) K.toast(r.error || 'refused', true); return; }
            if (K.loadPlan) K.loadPlan(); else location.reload();
          })
          .catch(function () { btn.disabled = false; });
      } }, 'Restore');
    return el('div', { class: 'pdia pdia-deleted', 'data-key': 'deleted-' + b.ref },
      el('div', { class: 'pdia-gone' },
        el('span', { class: 'mono t11 ink3', text: b.ref }),
        el('span', { text: 'Board deleted' + (d.title ? ': ' + d.title : '') }),
        el('span', { class: 't11 ink2', text: 'by ' + (d.by || 'someone') +
          (d.purge_at ? ', in the trash until ' + String(d.purge_at).slice(0, 10) : '') })),
      restore);
  }
  function boardEmbed(b) {
    if (b.deleted) return deletedEmbed(b);
    if (b.missing) return el('div', { class: 'pdia' }, el('div', { class: 'unserved', text: b.ref + ': ' + b.missing }));
    var opts = { board: b.ref, title: b.board_title || b.ref, upto: b.upto || 0 };
    var title = b.title && b.title.length ? spans(b.title) : [document.createTextNode(b.board_title || b.ref)];
    /* c-602: an outcome's board last drawn before his plan approval is the plan's drawing,
       carried over unchanged; its head says so rather than passing it off as the build's. */
    if (b.carried) title = title.concat([el('span', { class: 'chip pdia-carried', text: b.carried })]);
    return el('div', { class: 'pdia' + (b.carried ? ' carried' : '') }, diagramHead(title, openBoard(b.ref, b.upto)),
      diagramHost(b.id, b.ops || [], opts), wideCue(), asPlanned(b), boardWalk(b));
  }
  function details(b) {
    return el('details', { class: 'pdetails' }, el('summary', {}, spans(b.summary)),
      el('div', { class: 'pdetails-body' }, (b.blocks || []).map(function (inner) { return K.planBlocks.block(inner); })));
  }

  /* ---------- the answerable blocks ---------- */
  function decision(b) {
    var P = K.plan, pick = P.answerOf(b), open = P.otherOpen(b.id);
    var changed = pick.mine && (pick.option !== b.rec || pick.other);
    return el('fieldset', { class: 'pdecision' + (changed ? ' changed' : '') },
      el('legend', { class: 'pd-q' }, el('span', { class: 'mono t11 ink2 pd-id', text: b.id }), spans(b.q)),
      b.why && b.why.length ? el('p', { class: 'ink2 pd-why' }, spans(b.why)) : null,
      b.after ? el('p', { class: 't11 ink2' }, 'Depends on ', el('a', { href: '#b-' + b.after, class: 'mono' }, b.after)) : null,
      el('div', { class: 'pd-opts', role: 'radiogroup', 'aria-label': words(b.q) }, b.options.map(function (o) {
        var on = pick.option === o.id && !open, rec = o.id === b.rec;
        return el('button', { class: 'pd-opt' + (on ? ' on' : '') + (rec ? ' rec' : ''), role: 'radio', 'data-key': o.id,
          'aria-checked': on ? 'true' : 'false', disabled: P.canAnswer() ? null : true,
          onclick: function (ev) { ev.stopPropagation(); P.answer(b, o.id); } },
          el('span', { class: 'pd-dot', 'aria-hidden': 'true' }),
          el('span', { class: 'pd-body' },
            el('span', { class: 'pd-label' }, spans(o.label), rec ? el('span', { class: 'chip tone-accent', text: 'recommended' }) : null),
            o.body ? el('span', { class: 'pd-text ink2' }, spans(o.body)) : null,
            o.gets ? el('span', { class: 'pd-gets' }, el('span', { class: 'k', text: 'Gets' }), spans(o.gets)) : null,
            o.cost ? el('span', { class: 'pd-cost' }, el('span', { class: 'k', text: 'Costs' }), spans(o.cost)) : null));
      }),
      b.other !== false ? el('button', { class: 'pd-opt other' + (open ? ' on' : ''), 'data-key': '__other', role: 'radio',
        'aria-checked': open ? 'true' : 'false', disabled: P.canAnswer() ? null : true,
        onclick: function (ev) { ev.stopPropagation(); P.openOther(b.id); } },
        el('span', { class: 'pd-dot', 'aria-hidden': 'true' }), el('span', { class: 'pd-body' }, el('span', { class: 'pd-label', text: 'Something else' }))) : null),
      open ? P.otherField(b) : null,
      b.because && b.because.length ? el('p', { class: 'pd-because' }, el('span', { class: 'k', text: 'Why ' + b.rec + ': ' }), spans(b.because)) : null,
      el('div', { class: 'pd-state t11' + (changed ? ' mine' : ''), text: changed ? 'Your answer, not the recommendation'
        : pick.mine ? 'You confirmed the recommendation' : 'The recommendation stands unless you pick another' }));
  }
  function batch(b) {
    var P = K.plan, picks = P.rowsOf(b.id), changed = 0;
    var rows = b.rows.map(function (row) {
      var pick = picks[row.id] || row.rec;
      if (pick !== row.rec) changed++;
      return el('div', { class: 'pb-row' + (pick !== row.rec ? ' changed' : ''), 'data-key': row.id },
        el('div', { class: 'pb-text' }, el('span', { class: 'mono t11 ink2', text: row.id + ' ' }), spans(row.text),
          row.why ? el('span', { class: 'ink2 t11' }, ' · ', spans(row.why)) : null),
        el('div', { class: 'pb-choices', role: 'radiogroup', 'aria-label': row.id }, b.choices.map(function (c) {
          var on = pick === c;
          return el('button', { class: 'pb-choice' + (on ? ' on' : '') + (c === row.rec ? ' rec' : ''), role: 'radio',
            'aria-checked': on ? 'true' : 'false', 'data-key': c, disabled: P.canAnswer() ? null : true,
            title: c === row.rec ? 'recommended' : null,
            onclick: function (ev) { ev.stopPropagation(); P.answerRow(b, row, c); } }, c);
        })),
        /* RC-3: a row at edit carries his words, in a field opened with the house's draft */
        pick === 'edit' && P.editField ? P.editField(b, row) : null);
    });
    return el('div', { class: 'pbatch' },
      el('div', { class: 'pb-head' }, el('span', { class: 'pd-q' }, el('span', { class: 'mono t11 ink2 pd-id', text: b.id + ' ' }), spans(b.q)),
        el('span', { class: 'spacer' }),
        el('span', { class: 't11 ink2', text: b.rows.length + ' rows' + (changed ? ', ' + changed + ' changed' : ', all recommended') })),
      changed ? el('button', { class: 'btn sm', disabled: P.canAnswer() ? null : true,
        onclick: function (ev) { ev.stopPropagation(); P.resetRows(b); } }, 'Back to every recommendation') : null,
      el('div', { class: 'pb-rows' }, rows));
  }
  function questions(b) {
    var P = K.plan;
    if (!b.items.length) return el('p', { class: 'ink2' }, b.none ? spans(b.none) : 'None.');
    return el('ol', { class: 'pquestions' }, b.items.map(function (item, i) {
      var said = P.replyOf(b.id, i), writing = P.replyOpen(b.id, i);
      return el('li', { class: 'pq' + (said ? ' answered' : ''), 'data-key': 'q' + i },
        el('div', { class: 'pq-q' }, spans(item.q)),
        item.rec ? el('div', { class: 'pq-rec' }, el('span', { class: 'k', text: 'Recommended: ' }), spans(item.rec)) : null,
        said && !writing ? el('div', { class: 'pq-said' }, el('span', { class: 'k', text: 'You: ' }), said) : null,
        writing ? P.replyField(b, i) : el('button', { class: 'btn sm', disabled: P.canAnswer() ? null : true,
          onclick: function (ev) { ev.stopPropagation(); P.openReply(b.id, i); } }, said ? 'Change your answer' : 'Answer differently'));
    }));
  }

  var RENDER = { heading: heading, paragraph: function (b) { return para(b.text); }, list: list,
                 checklist: checklist, table: table, callout: callout, quote: quote, code: code, diff: code,
                 copy: copyBlock, images: images, stats: stats, steps: steps, compare: compare,
                 options: options, diagram: diagram, board: boardEmbed, details: details,
                 decision: decision, batch: batch, questions: questions,
                 /* one review finding, whole: app/ui.planfinding.js (lane FC, FC-2) */
                 finding: function (b) { return K.planFinding.card(b); } };
  var ANSWERABLE = { decision: 1, batch: 1, questions: 1, finding: 1 };

  /* One block in its frame: the frame is what a note pins to, through the note button
     every block carries or through words selected inside it. */
  function block(b) {
    var render = RENDER[b.type];
    var body = render ? render(b) : el('div', { class: 'unserved', text: 'a block of kind ' + b.type + ' this page does not draw' });
    if (b.type === 'heading' && b.level === 2) return el('div', { class: 'pblock pb-h', 'data-key': b.id, 'data-bid': b.id, id: 'b-' + b.id }, body);
    var P = K.plan, notes = P ? P.notesOn(b.id) : [];
    return el('div', { class: 'pblock t-' + b.type + (P && P.selected() === b.id ? ' sel' : '') + (ANSWERABLE[b.type] ? ' answerable' : ''),
      'data-key': b.id, 'data-bid': b.id, id: 'b-' + b.id },
      P ? P.noteButton(b) : null,
      body,
      P && P.findingsOn(b.id).length ? el('ul', { class: 'pfindings' }, P.findingsOn(b.id).map(function (f, i) {
        return el('li', { 'data-key': 'f' + i, class: 'lvl-' + f.level }, el('span', { class: 'mono', text: f.rule + ' ' }), f.text);
      })) : null,
      notes.length ? el('div', { class: 'pnotes-on' }, notes.map(function (n) { return P.noteChip(n); })) : null,
      P && P.asksOn(b.id).length ? el('div', { class: 'pnotes-on' }, P.asksOn(b.id).map(function (a) { return P.askChip(a); })) : null);
  }

  K.planBlocks = { block: block, spans: spans, words: words, ANSWERABLE: ANSWERABLE };
})(window.Keel);
