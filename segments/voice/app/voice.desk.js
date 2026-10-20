/* Voice, the desk: the studio's two outer columns and the status chips (VP-1).

   At 900px and up the page is three columns: WHO YOU CAN TALK TO (Harbor, then the houses
   the deck lists), THE CHAT, and WHAT THE TURN TOUCHED (the real board it drew, else the
   card he is connected to with its plan's round). The phone has none of this and fetches
   none of it: only a visible column does any work.

   It reads the deck's own documents, its live part of GET /api/state and GET /api/plan/<id>,
   same origin.
   Nothing here acts on the board: choosing a house is the same `connect` the spoken phrase
   sends, and every other control is a link into the deck. */
(function () {
  "use strict";
  var V = window.Voice, state = V.state, esc = V.esc, $ = V.$;
  var doc = null, docAt = 0, docLoading = false, docTag = null;
  var plans = {};
  var DOC_EVERY_MS = 10000;
  /* THE DECK'S LIVE CARDS, NOT THE WHOLE BOARD (c-549). This column draws the houses the
     deck lists and the card he is connected to. It used to read a bare /api/state every ten
     seconds, 2 MB raw and 493 KB gzipped, archived and done cards and whole briefs included.
     The live part holds every card with a house and every top-level list, about 46 KB
     gzipped. Its ETag is the deck's revision, whose coarse clock moves every fifteen
     seconds, so a read within the same step is a 304. */
  var DOC_URL = "/api/state?scope=deck&part=live";

  function loadDoc() {
    if (docLoading || (doc && Date.now() - docAt < DOC_EVERY_MS)) return;
    docLoading = true;
    var headers = docTag ? { "If-None-Match": docTag } : {};
    fetch(DOC_URL, { cache: "no-store", credentials: "same-origin", headers: headers })
      .then(function (r) {
        if (r.status === 304) return null;
        if (!r.ok) return Promise.reject(r.status);
        docTag = r.headers.get("ETag");
        return r.json();
      })
      .then(function (d) {
        docAt = Date.now(); docLoading = false;
        if (d) { doc = d; V.render(); }
      })
      .catch(function () { docLoading = false; docAt = Date.now(); });
  }

  function cardById(id) {
    var cards = (doc && doc.cards) || [];
    for (var i = 0; i < cards.length; i++) { if (cards[i].id === id) return cards[i]; }
    return null;
  }

  /* A house's state in the deck's own words: at a gate, blocked, or its stage. */
  function stateWord(c) {
    var d = c.derived || {};
    if (c.blocked_reason) return "blocked";
    if (d.plan_gate || d.outcome_gate) return "at your gate";
    return c.stage || "";
  }

  /* THE HOUSES YOU CAN TALK TO: every card with a house the deck knows of, both spaces,
     the one he is connected to first. */
  function houses() {
    var ids = (doc && doc.houses) || [];
    var list = ids.map(cardById).filter(Boolean);
    list.sort(function (a, b) { return (b.id === state.pinned) - (a.id === state.pinned); });
    return list.slice(0, 8);
  }

  function talkTo() {
    var host = $("talkto");
    if (!host) return;
    var rows = ['<li><button type="button" class="v-trow' + (state.pinned ? "" : " on") +
      '" data-talk=""><span class="v-who-dot" aria-hidden="true"></span>' +
      '<span class="v-tname">Harbor</span><span class="v-tstate">' +
      (state.pinned ? "tap to go back" : "talking") + "</span></button></li>"];
    houses().forEach(function (c) {
      var on = c.id === state.pinned;
      rows.push('<li><button type="button" class="v-trow' + (on ? " on" : "") + '" data-talk="' +
        esc(c.id) + '"><span class="v-tid mono" data-space="' + esc(c.space) + '">' + esc(c.id) +
        '</span><span class="v-tname">' + esc(c.title) + '</span><span class="v-tstate">' +
        esc(on ? "talking" : stateWord(c)) + "</span></button></li>");
    });
    if (!doc) rows.push('<li class="v-tnone">Reading the deck</li>');
    else if (!houses().length) rows.push('<li class="v-tnone">No house is running</li>');
    var html = rows.join("");
    if (host._sig !== html) { host.innerHTML = html; host._sig = html; }
  }

  /* THIS SESSION: what the turns on this page filed and drew, newest first. */
  function session() {
    var host = $("session");
    if (!host) return;
    var rows = [];
    state.turns.slice().reverse().forEach(function (t) {
      (t.boards || []).forEach(function (b) {
        rows.push('<li><a href="' + V.boardHref(b) + '">Board <span class="mono">' + esc(b) +
          "</span></a></li>");
      });
      if (t.card) {
        rows.push('<li><a href="/?view=cards&card=' + encodeURIComponent(t.card) +
          '">Captured <span class="mono">' + esc(t.card) + "</span></a></li>");
      }
    });
    if (state.pinned) rows.unshift('<li>Entered <span class="mono">' + esc(state.pinned) + "</span></li>");
    var html = rows.length ? rows.slice(0, 8).join("") : '<li class="v-tnone">Nothing filed or drawn yet</li>';
    if (host._sig !== html) { host.innerHTML = html; host._sig = html; }
  }

  function latestBoard() {
    for (var i = state.turns.length - 1; i >= 0; i--) {
      var b = state.turns[i].boards || [];
      if (b.length) return b[b.length - 1];
    }
    return "";
  }

  function plan(id) {
    if (plans[id]) return plans[id];
    plans[id] = { state: "loading" };
    fetch("/api/plan/" + encodeURIComponent(id), { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (p) { plans[id] = { state: "ready", round: p.round || {}, lint: p.lint || {}, empty: p.empty }; V.render(); })
      .catch(function () { plans[id] = { state: "none" }; V.render(); });
    return plans[id];
  }

  function planLine(p) {
    if (p.state === "loading") return "Reading its plan";
    if (p.state !== "ready" || p.empty) return "No plan on this card";
    var r = p.round, n = r.decisions || 0;
    var line = n + " decision" + (n === 1 ? "" : "s");
    if (r.changed) line += ", " + r.changed + " changed";
    if (r.notes) line += ", " + r.notes + " note" + (r.notes === 1 ? "" : "s");
    return line;
  }

  /* THE CARD HE IS TALKING TO: what it is, where it stands, its plan's round, and the way
     into the deck. No action buttons: this page never acts (the deck does). */
  function cardHtml(id) {
    var c = cardById(id) || { id: id, title: state.pinnedTitle, space: state.pinnedSpace };
    var p = plan(id);
    return '<div class="v-card">' +
      '<div class="v-card-head"><span class="mono" data-space="' + esc(c.space) + '">' + esc(c.id) +
      '</span><span class="v-card-title">' + esc(c.title || "") + "</span></div>" +
      '<div class="v-card-meta mono">' + esc([c.stage, c.space].filter(Boolean).join(" · ")) + "</div>" +
      '<div class="v-card-plan">' + esc(planLine(p)) + "</div>" +
      '<div class="v-card-links">' + (p.state === "ready" && !p.empty
        ? '<a class="v-btn" href="/plan/' + encodeURIComponent(id) + '">Open plan</a>' : "") +
      '<a class="v-btn" href="/?view=cards&card=' + encodeURIComponent(id) + "&space=" +
      encodeURIComponent(c.space || "") + '">Open in the deck</a></div></div>';
  }

  /* WHAT THE TURN TOUCHED: the real board, else the house, else what could appear here. */
  function touched() {
    var host = $("touchedbody");
    if (!host) return;
    /* While connected, the house wins unless the newest turn itself drew a board. */
    var last = state.turns[state.turns.length - 1];
    var board = state.pinned ? ((last && last.boards && last.boards.length) ? last.boards[last.boards.length - 1] : "")
      : latestBoard();
    var key = board ? "board:" + board : state.pinned ? "card:" + state.pinned : "none";
    if (board) {
      var embed = V.boardEmbed(board);
      if (host._key !== key || (embed && embed.parentNode !== host)) {
        host.innerHTML = "";
        if (embed) host.appendChild(embed);
        else host.innerHTML = V.boardRow(board);
        host._key = embed ? key : "";
      }
      return;
    }
    var html = state.pinned ? cardHtml(state.pinned)
      : '<p class="v-tnone">A board Harbor draws, a card it files, or the house you enter shows here.</p>';
    if (host._key !== key || host._sig !== html) { host.innerHTML = html; host._sig = html; host._key = key; }
  }

  /* THE STATUS CHIPS: what is answering, in mono, true at the last health read. */
  function chips() {
    var host = $("chips");
    if (!host) return;
    var h = state.health, out = [];
    if (h) {
      out.push(["STT " + (h.stt && h.stt.ready ? "ready" : "down"), h.stt && h.stt.ready ? "" : "crit"]);
      var tts = h.tts || {};
      out.push(["TTS " + V.engineName(tts.preferred || tts.backend || ""), ""]);
      if (h.record && h.record.recording) out.push(["REC " + h.record.megabytes + " MB", "crit"]);
      var keys = (h.judges && h.judges.keys) || {}, modes = {};
      Object.keys(keys).forEach(function (k) { modes[keys[k].mode] = 1; });
      if (Object.keys(modes).length) out.push(["Judges " + Object.keys(modes).join("/"), ""]);
    }
    if (state.bus.alert) out.push(['<a href="/?view=attention">Needs a decision</a>', "warn", true]);
    var html = out.map(function (c) {
      return '<span class="v-chip mono ' + c[1] + '">' + (c[2] ? c[0] : esc(c[0])) + "</span>";
    }).join("");
    if (host._sig !== html) { host.innerHTML = html; host._sig = html; }
  }

  V.desk = function () {
    if (!V.isDesk()) return;
    loadDoc();
    chips();
    talkTo();
    session();
    touched();
  };

  /* CHOOSING WHO TO TALK TO: a house is the spoken phrase's own `connect`; Harbor, while
     connected, is the header's own `disconnect`. */
  V.onTalkTo = function (card) {
    if (!card) { if (state.pinned) V.say({ type: "disconnect" }); return; }
    if (card === state.pinned) return;
    V.say({ type: "connect", card: card });
  };
})();
