/* A space's flow as someone who has never seen Shipyard reads it (c-732), loaded before
 * `ui.startships.js`, which draws it as `K.flowPicture(flow, opts)`.
 *
 * ONE DIAGRAM, EACH PLACE ONCE. Branches are places, boxes with their name and a few words on
 * what each is; each move is an arrow between two of them, labelled with what happens and who
 * does it ("Approve, you", "Ship, you", "Review and merge, you or a teammate"); a place a move
 * of yours reaches is marked. THE WORDS AGREE WITH THE CONNECTION'S OWN (c-758): Ship is a
 * button on the card, so it is yours. A step someone makes on the code host (`colleague`) is
 * "a teammate" in a flow a team wrote, which knows who; in Shipyard's own general flow, which
 * cannot know, it is "you or a teammate", as the shipped connections say of the merge. It is drawn by the deck's own diagram drawing (`K.boardDraw.drawGraph`, the ELK
 * layout of app/vendor/elk.bundled.js that boards and the Settings Flow panel use): left to
 * right in the order work moves on the desk, top to bottom on a phone. Drawn still
 * (`host._still`): no pan or zoom, so the page scrolls over it.
 *
 * A flow's `{base}` is drawn as each of the space's bases by name (`opts.bases`, the answer to
 * "Where does work start?"), so "main or staging" is two places; a branch the flow names by
 * its own label is the same place as the base of that name; a move that names `bases` is
 * drawn only to and from those. Under the drawing, ONE sentence in plain words, built from the
 * arrows (`K.flowSentence`), so what the user said and what the drawing shows can be read side
 * by side; and the same arrows as a list, folded, for a reader without the picture.
 *
 * Every place and arrow can be tapped, in the drawing or in the list: the tap opens a line
 * under the drawing that says what that part is and how to change it (a base: the question on
 * this page; anything else: tell Bosun, with the command to its session). Nothing changes
 * until the user presses Adopt. */
window.Keel = window.Keel || {};
(function (K) {
  'use strict';

  var el = K.el;
  var picked = {};      /* drawing key -> the part whose line is open */
  var listed = {};      /* drawing key -> the list is open (true) or closed (false), once the user has said */
  var WHO = { you: 'you', keel: 'Shipyard', house: 'the session', colleague: 'a teammate' };
  /* who makes a move, in words; `either`: the flow is Shipyard's own, so a step on the code
     host may be the user's or a teammate's */
  function actor(m, either) { return m.by === 'colleague' && either ? 'you or a teammate' : WHO[m.by] || m.by; }
  function either(flow) { return (flow || {}).source === 'keel'; }
  var APPROVE = { land: true, publish: true };
  /* Shipyard's steps that are the user's own button on the card: Approve, and Ship (c-758) */
  var BUTTONS = { land: true, publish: true, ship: true };
  var CARD = 'your card\'s branch', STARTED = 'the branch it started from';
  var HINT = { card: 'one card\'s own work', base: 'work starts here', work: 'made for this card',
    integration: 'where approved work collects', environment: 'where people see it', trunk: 'the main line', remote: 'your team\'s copy' };

  var STYLE = [
    '.fp-graph{height:260px;border:1px solid var(--hair);background:var(--s0);cursor:pointer}',
    '.fp-graph .graphwrap{touch-action:auto;cursor:pointer}',
    '.fp-graph .gedge{cursor:pointer}',
    '@media (max-width:899px){.fp-graph{height:calc(var(--fp-n) * 112px + 24px)}}',
    '.fp-said{margin:0;font-size:14px;line-height:1.5;color:var(--ink)}',
    '.fp-part{border-left:3px solid var(--accent);background:var(--s0);padding:8px 12px;font-size:13px;line-height:1.5;display:flex;flex-direction:column;gap:8px}',
    '.fp-part p{margin:0}',
    '.fp-list summary{cursor:pointer;font-size:13px;color:var(--ink-2);min-height:32px}',
    '.fp{display:flex;flex-direction:column;gap:4px;margin:8px 0 0;padding:0;list-style:none}',
    '.fp-row{display:flex;flex-wrap:wrap;gap:4px;align-items:center;font-size:13px}',
    '.fp-row button{border:0;background:none;color:var(--ink);font:inherit;padding:4px;min-height:32px;cursor:pointer;text-decoration:underline dotted}',
    '.fp-row .fp-arrow{color:var(--ink-2)}.fp-row.yours .fp-arrow{color:var(--accent-ink);font-weight:600}'
  ].join('\n');
  function styleOnce() {
    if (typeof document === 'undefined' || !document.head || document.getElementById('flowpicture-style')) return;
    var node = document.createElement('style');
    node.id = 'flowpicture-style';
    node.textContent = STYLE;
    document.head.appendChild(node);
  }

  /* ---------- places ---------- */

  function yours(m) { return m.by === 'you' || !!BUTTONS[m.step]; }
  /* the places a branch stands for: the card's own; each base by name; one place by its label */
  function placesOf(b, bases) {
    var label = String(b.label || b.id);
    if (b.kind === 'card') return [{ name: CARD, kind: 'card', base: false }];
    if (label.indexOf('{base}') >= 0) {
      if (!bases.length) return [{ name: STARTED, kind: 'base', base: false }];
      return bases.map(function (n) { return { name: label.replace(/\{base\}/g, n), kind: 'base', base: n }; });
    }
    var name = label.replace(/\{branch\}/g, CARD);
    return [{ name: name, kind: bases.indexOf(name) >= 0 ? 'base' : b.kind, base: bases.indexOf(name) >= 0 ? name : false }];
  }
  /* each arrow a move makes once its places are named: a move that names `bases` only to and
     from those, the same base on both ends where both are the card's base, never a place to itself */
  function arrows(flow, bases) {
    var byId = {};
    flow.branches.forEach(function (b) { byId[b.id] = b; });
    var out = [];
    flow.moves.forEach(function (m) {
      var from = byId[m.from] ? placesOf(byId[m.from], bases) : [{ name: m.from, kind: '' }];
      var to = byId[m.to] ? placesOf(byId[m.to], bases) : [{ name: m.to, kind: '' }];
      var both = byId[m.from] && byId[m.to] && byId[m.from].label === byId[m.to].label;
      from.forEach(function (f) {
        to.forEach(function (t) {
          if (f.name === t.name || (both && f.base !== t.base)) return;
          var named = m.bases && m.bases.length ? [f.base, t.base].filter(Boolean) : [];
          if (named.length && !named.some(function (n) { return m.bases.indexOf(n) >= 0; })) return;
          out.push({ move: m, from: f, to: t });
        });
      });
    });
    return out;
  }

  /* ---------- the words ---------- */

  function or(names) {
    var list = names.filter(function (n, i) { return names.indexOf(n) === i; });
    return list.length < 2 ? (list[0] || '') : list.slice(0, -1).join(', ') + ' or ' + list[list.length - 1];
  }
  function cap(text) { return text.charAt(0).toUpperCase() + text.slice(1); }
  /* what happens on one move, in plain words: Shipyard's own steps it can say itself, any
     other move its `about`, else its label and who makes it */
  function what(m, to, space, any) {
    var say = function (t) { return K.say ? K.say(space, t) : t; };
    if (m.step === 'land') return 'You press Approve, and Shipyard merges it into ' + to + ' on this computer.';
    if (m.step === 'publish') return say('You press Approve, and Shipyard marks the {change} ready.');
    if (m.step === 'ship') return say('You press Ship to send the fixes made after review.');
    if (m.step === 'pr') return say('The session opens a draft {change} to ' + to + '.');
    if (m.about && m.by !== 'keel' && m.by !== 'house') return m.about;
    return cap(actor(m, any)) + ': ' + m.label + '.';
  }
  function short(m, space) {
    if (APPROVE[m.step]) return 'Approve';
    return K.say ? K.say(space, m.label) : m.label;
  }

  /* the drawing's one sentence: where work starts, then each move once, in the flow's order */
  K.flowSentence = function (flow, opts) {
    opts = opts || {};
    var bases = opts.bases || [], rows = arrows(flow, bases), seen = {}, said = [];
    if (bases.length) said.push('Work starts on ' + or(bases) + '.');
    /* one of Shipyard's own steps from the same place says once where it goes, whichever
       moves of the flow draw it (one per base, say) */
    var group = function (r) { return r.move.by === 'keel' && r.move.step ? 'k:' + r.move.step + ':' + r.from.name : 'm:' + r.move.id; };
    rows.forEach(function (r) {
      if (seen[group(r)]) return;
      seen[group(r)] = true;
      var to = rows.filter(function (x) { return group(x) === group(r); }).map(function (x) { return x.to.name; });
      var where = to.length > 1 && r.from.kind === 'card' ? STARTED + ' (' + or(to) + ')' : or(to);
      said.push(what(r.move, where, opts.space, either(flow)));
    });
    if (opts.push) said.push('You press Push when your team should see it on ' + opts.push + '.');
    return said.join(' ');
  };

  /* ---------- the parts, and what a tap on one says ---------- */

  function partLine(part, opts) {
    var bits = [];
    if (part.place && part.place.base) {
      bits.push(el('p', { text: part.place.name + ' is a branch work starts from: you named it under "Where does work start?".' }));
      if (opts.onBases) bits.push(el('div', { class: 'ships-btns' }, el('button', { class: 'btn sm', onclick: opts.onBases }, 'Change where work starts')));
    } else if (part.place) {
      bits.push(el('p', { text: part.place.kind === 'card'
        ? 'Each card gets a branch of its own, cut from the branch it starts on. The session works there, and nothing else touches it.'
        : part.place.name + ' is ' + (HINT[part.place.kind] || 'a place your work passes through') + '. To change it, tell Bosun in its session.' }));
    } else {
      var m = part.move;
      bits.push(el('p', { text: yours(m)
        ? 'This is yours: a button on the card. Nothing happens here until you press it.'
        : m.by === 'colleague' && opts.either ? 'This is a picture of a step you or a teammate make outside Shipyard. Shipyard does not make it for you.'
        : 'This is a picture of what ' + (WHO[m.by] || m.by) + ' does. Shipyard does not change it by itself.' }));
      bits.push(el('p', { text: 'To change it, tell Bosun in its session, for example: "' + short(m, opts.space) +
        ' should happen differently: ...".' }));
    }
    if (!(part.place && part.place.base) && opts.attach && K.command) bits.push(K.command(opts.attach));
    bits.push(el('p', { class: 'ships-line', text: 'Nothing changes until you press Adopt.' }));
    return el('div', { class: 'fp-part', 'data-key': 'fp-part', role: 'status' }, bits);
  }
  function tap(key, id) {
    return function () {
      picked[key] = picked[key] === id ? null : id;
      if (K.renderBody) K.renderBody();
    };
  }
  function who(m, any) { return yours(m) ? 'you' : actor(m, any); }

  /* every arrow, a Push from each place a card lands on where the space offers it, then each
     place once (in the order work reaches it) and each arrow once */
  function diagram(flow, opts) {
    var rows = arrows(flow, opts.bases || []);
    if (opts.push && rows.length) {
      var remote = { name: opts.push, kind: 'remote' }, done = {};
      rows.filter(function (r) { return APPROVE[r.move.step]; }).forEach(function (r) {
        if (done[r.to.name]) return;
        done[r.to.name] = true;
        rows.push({ move: { id: 'push', by: 'you', label: 'Push' }, from: r.to, to: remote });
      });
    }
    var places = [], at = {}, edges = [], seen = {};
    var placeId = function (p) {
      if (at[p.name] === undefined) { at[p.name] = places.length; places.push(p); }
      return 'p' + at[p.name];
    };
    rows.forEach(function (r) {
      var a = placeId(r.from), b = placeId(r.to), label = short(r.move, opts.space) + ', ' + who(r.move, either(flow));
      var k = a + '>' + b + '>' + label;
      if (seen[k] === undefined) { seen[k] = edges.length; edges.push({ a: a, b: b, label: label, move: r.move }); }
      r.edge = 'e' + seen[k];
      r.a = a; r.b = b;
    });
    return { rows: rows, places: places, edges: edges };
  }
  var ICON = { card: 'git-branch', base: 'git-branch', work: 'git-branch', integration: 'git-branch',
    environment: 'globe', trunk: 'git-branch', remote: 'cloud' };
  function quoted(text) { return '"' + String(text).replace(/"/g, "'") + '"'; }
  /* the board's own line format (app/ui.board.js `parseLine`), so the drawing is the board's */
  function linesOf(d, narrow) {
    var lines = [];
    d.places.forEach(function (p, i) {
      lines.push('node p' + i + ' ' + (ICON[p.kind] || 'box') + ' ' + quoted(p.name) + (narrow ? '' : ' ' + quoted(HINT[p.kind] || '')));
    });
    d.edges.forEach(function (e) { lines.push('edge ' + e.a + ' -> ' + e.b + ' ' + quoted(e.label)); });
    d.edges.filter(function (e) { return yours(e.move); }).forEach(function (e) { lines.push('mark ' + e.b + ' accent'); });
    return lines;
  }
  /* draw once the host is in the page, and again only when the drawing or its width changed */
  function draw(key, d) {
    if (!K.boardDraw || typeof document === 'undefined' || !document.querySelector) return;
    setTimeout(function () {
      var host = document.querySelector('.fp-graph[data-key="' + key + '-graph"]');
      if (!host) return;
      /* on a phone the boxes carry the name alone, so the drawing is narrow enough to read; a
         tap on one says what it is */
      var narrow = !(K.isDesk && K.isDesk()), lines = linesOf(d, narrow);
      var sig = lines.join('\n') + '@' + (host.clientWidth || 0);
      if (host._sig === sig) return;
      host._sig = sig;
      host._still = true;
      var model = K.boardDraw.foldInto(K.boardDraw.newModel(), lines);
      model.inlineLabels = narrow;
      K.boardDraw.drawGraph(host, model, true);
    }, 0);
  }
  /* a tap in the drawing: the place or arrow under it */
  function tapped(key) {
    return function (ev) {
      for (var n = ev && ev.target; n && n.getAttribute; n = n.parentNode) {
        var nid = n.getAttribute('data-nid'), eid = n.getAttribute('data-eid');
        if (nid) return tap(key, nid)();
        if (eid) return tap(key, eid.replace('e_', 'e'))();
      }
    };
  }
  function partOf(d, id) {
    if (!id) return null;
    var i = Number(id.slice(1));
    if (id.charAt(0) === 'p' && d.places[i]) return { place: d.places[i] };
    if (id.charAt(0) === 'e' && d.edges[i]) return { move: d.edges[i].move };
    return null;
  }
  function listRow(key, r, opts) {
    var mine = yours(r.move);
    var button = function (id, text, cls) {
      return el('button', { type: 'button', class: cls || '', 'data-key': cls === 'fp-arrow' ? null : 'fp-place',
        'aria-expanded': picked[key] === id ? 'true' : 'false', onclick: tap(key, id) }, text);
    };
    return el('li', { class: 'fp-row' + (mine ? ' yours' : ''), 'data-key': 'fp-move', 'data-yours': mine ? 'yes' : 'no',
      'data-from': r.from.name, 'data-to': r.to.name },
      button(r.a, r.from.name),
      button(r.edge, el('span', {}, '→ ', el('span', { class: 'fp-what', text: short(r.move, opts.space) }), ', ',
        el('span', { class: 'fp-who', text: who(r.move, opts.either) }), ' →'), 'fp-arrow'),
      button(r.b, r.to.name));
  }

  function crowded(d) { return !(K.isDesk && K.isDesk()) && d.edges.length > d.places.length; }
  /* `opts`: {key, space, bases, push (a remote's name, drawn as a last place), attach, onBases} */
  K.flowPicture = function (flow, opts) {
    styleOnce();
    opts = Object.assign({}, opts || {}, { either: either(flow) });
    var key = opts.key || 'fp', d = diagram(flow, opts), open = partOf(d, picked[key]);
    draw(key, d);
    return el('div', { class: 'ships-side', 'data-key': key },
      el('div', { class: 'fp-graph', 'data-key': key + '-graph', 'data-morph': 'skip', role: 'img', style: '--fp-n:' + d.places.length,
        'aria-label': 'Where work goes: ' + d.edges.map(function (e) {
          return d.places[Number(e.a.slice(1))].name + ' to ' + d.places[Number(e.b.slice(1))].name + ' (' + e.label + ')';
        }).join('; '), onclick: tapped(key) }),
      open ? partLine(open, opts) : el('p', { class: 'ships-line', text: 'Tap any box or arrow to see what it is and how to change it.' }),
      el('p', { class: 'fp-said', 'data-key': key + '-said' }, el('strong', { text: 'In words: ' }), K.flowSentence(flow, opts)),
      /* c-758: on a phone, several arrows between the same two places leave the drawing too
         small to read, so the list starts open there; the user's own open or close is kept */
      el('details', { class: 'fp-list', 'data-key': key + '-list', open: (listed[key] === undefined ? crowded(d) : listed[key]) ? true : null,
        ontoggle: function (ev) { listed[key] = !!(ev && ev.target && ev.target.open); } }, el('summary', { text: 'The same drawing, as a list' }),
        el('ol', { class: 'fp', 'aria-label': 'how work moves, place to place' }, d.rows.map(function (r) { return listRow(key, r, opts); }))));
  };
  K.flowLinesOf = function (flow, opts) { return linesOf(diagram(flow, opts || {})); };
  K.flowPicked = function (key, id) { picked[key] = id; };
})(window.Keel);
