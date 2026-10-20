/* Voice, the board a turn drew: the REAL board, drawn by the deck's own renderer (VP-5).

   Never a second rendering. The voice page is same origin with the deck, so it borrows the
   plan pages' board embed as it is: `K.planBlocks.block({type: "board", ...})` from
   /ui.planblocks.js, the frame with "Open board" and "What hangs on this board", which
   fetches the board's own drawing code (/ui.boardlayout.js, /ui.board.js, /ui.planlook.js,
   /ui.plandiagram.js) the first time a diagram needs it and asks for a render when it has
   run (`K.renderBody`). The board's lines come from GET /api/board/<id>, the same lines the
   plan route puts on an embed. A tap on the drawing, or Open board, goes to the board's own
   full screen view with its walk (`/board/<id>?full=1`).

   Nothing streams and nothing takes the page over mid-turn (his call after the latency
   benchmark): the embed appears once the turn names its board, like any other receipt.

   This file edits none of the board's files; lane Z owns them and this only calls them. */
(function () {
  "use strict";
  var V = window.Voice;
  var boards = {};           // id -> {state: "loading"|"ready"|"missing", title, nodes, lines, why}
  var embeds = {};           // id -> {node, drawn: whether the drawing code was there}
  var deck = null;           // the promise of the deck's embed code

  function script(src) {
    return new Promise(function (resolve, reject) {
      var tag = document.createElement("script");
      tag.src = src;
      tag.onload = resolve;
      tag.onerror = function () { reject(new Error(src)); };
      document.head.appendChild(tag);
    });
  }

  /* THE DECK'S CORE AND THE PLAN PAGES' BLOCKS, fetched once, the first time a turn names
     a board, so a session that draws nothing never fetches them. */
  function needDeck() {
    if (deck) return deck;
    var K = window.Keel;
    if (K && K.planBlocks) { deck = Promise.resolve(); return deck; }
    deck = script("/ui.core.js").then(function () { return script("/ui.planblocks.js"); })
      .then(function () {
        /* THE EMBED ASKS FOR A RENDER when the board's drawing code has run; an embed built
           before that is a placeholder, so it is built again. */
        window.Keel.renderBody = function () {
          Object.keys(embeds).forEach(function (id) { if (!embeds[id].drawn) delete embeds[id]; });
          V.render();
        };
        V.render();
      })
      .catch(function () { deck = null; });
    return deck;
  }

  function need(id) {
    if (boards[id]) return boards[id];
    boards[id] = { state: "loading" };
    fetch("/api/board/" + encodeURIComponent(id), { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : r.json().then(function (b) { throw new Error(b.error || r.status); }); })
      .then(function (b) {
        boards[id] = { state: "ready", title: b.title || id, nodes: b.nodes || 0,
                       lines: b.lines || [] };
        V.render();
      })
      .catch(function (err) {
        boards[id] = { state: "missing", why: String(err && err.message || err) };
        V.render();
      });
    needDeck();
    return boards[id];
  }
  V.boardInfo = function (id) { return need(id); };

  /* THE EMBED FOR ONE BOARD, built once and kept: the view moves the same node into
     whichever column shows it, so the drawing is never thrown away by a render. Null until
     the lines and the deck's code are both here. */
  V.boardEmbed = function (id) {
    var info = need(id), K = window.Keel;
    if (info.state !== "ready" || !K || !K.planBlocks) return null;
    if (embeds[id]) return embeds[id].node;
    var node = K.planBlocks.block({ type: "board", id: "vb-" + id, ref: id, ops: info.lines,
                                    board_title: info.title });
    node.className += " v-embed";
    embeds[id] = { node: node, drawn: !!K.planDiagram };
    return node;
  };

  V.boardHref = function (id) { return "/board/" + encodeURIComponent(id) + "?full=1"; };

  /* THE COMPACT RECEIPT: one row, one tap to the board full screen with its walk. */
  V.boardRow = function (id) {
    var info = need(id);
    var title = info.state === "ready" ? info.title : info.state === "missing" ? "not found" : "loading";
    var meta = info.state === "ready" ? info.nodes + " node" + (info.nodes === 1 ? "" : "s")
      : info.state === "missing" ? info.why : "";
    return '<a class="v-receipt" href="' + V.boardHref(id) + '">' +
      '<span class="v-ricon v-ricon-board" aria-hidden="true"></span>' +
      '<span class="v-rtext"><span class="v-rtitle"><span class="mono">' + V.esc(id) +
      "</span> " + V.esc(title) + '</span><span class="v-rmeta">' + V.esc(meta) + "</span></span>" +
      '<span class="v-rchev" aria-hidden="true">›</span></a>';
  };
})();
