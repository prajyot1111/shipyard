/* Voice, the wiring: which touch, key and event reaches which part, the test door, and go.

   THE COMPOSER (VP-1). The page is a chat you can also talk to. Typing sends a `text`
   line, which the gateway answers in text only (VP-3). Holding the mic opens a listen and
   turns the composer into the voice bar; lifting sends. The bar's keyboard button returns
   to typing. On the desk, Space holds while the field is not focused. */
(function () {
  "use strict";
  var V = window.Voice, state = V.state, $ = V.$;
  var el = V.el;

  function on(node, ev, fn) { if (node && node.addEventListener) node.addEventListener(ev, fn); }

  /* ------------------------------------------------------------ typing */

  var LINE = 24, MAX_LINES = 4;
  /* THE FIELD GROWS TO FOUR LINES, then scrolls inside itself. */
  function grow() {
    var f = el.field;
    if (!f || !f.style) return;
    f.style.height = "auto";
    f.style.height = Math.min(f.scrollHeight || LINE, LINE * MAX_LINES + 20) + "px";
  }

  function send() {
    var text = String((el.field && el.field.value) || "").trim();
    if (!text) return;
    if (!state.connected) { state.note = "Not sent: the gateway is not answering."; V.render(); return; }
    /* A TYPED LINE IS A TYPED TURN (VP-3): the gateway answers it in text only. The mode
       and the space ride on it exactly as they ride on `end`. */
    V.say({ type: "text", text: text, mode: state.mode, space: state.space, engine: state.engine });
    if (state.mode === "capture") state.mode = "talk";
    el.field.value = "";
    grow();
    V.render();
  }
  V.send = send;

  on(el.field, "input", function () { grow(); V.render(); });
  on(el.field, "keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
  });
  on(el.send, "click", send);

  /* ------------------------------------------------------------ holding */

  /* THE MIC IN THE COMPOSER: a hold, whose release may land anywhere, because the composer
     turns into the bar under his finger. So the end of this hold is listened for on the
     window, and a cancelled pointer is a dropped hold, never a send. Inside a conversation
     the mic only brings the bar back; the bar's own tap is the pause. */
  function micDown(ev) {
    if (state.conversation) { state.face = "voice"; V.render(); return; }
    V.onOrbDown(ev);
    if (!state.holding) return;
    var up = function (e) { off(); V.onOrbUp(e); };
    var cancel = function (e) { off(); V.onOrbLost(e); };
    function off() {
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel);
    }
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel);
  }
  on(el.mic, "pointerdown", micDown);
  on(el.mic, "contextmenu", function (e) { e.preventDefault(); });

  on(el.control, "pointerdown", V.onOrbDown);
  on(el.control, "pointerup", V.onOrbUp);
  on(el.control, "pointercancel", V.onOrbLost);
  on(el.control, "pointerleave", V.onOrbLost);
  on(el.control, "contextmenu", function (e) { e.preventDefault(); });
  on(el.kbd, "click", function () {
    state.face = "type";
    V.render();
    if (el.field && el.field.focus) el.field.focus();
  });
  window.addEventListener("blur", function () {
    if (state.holding && !state.autoHeld && !state.conversation) V.dropHold("lost-blur");
  });

  /* ------------------------------------------------------------ the + menu */

  function menu(open) {
    V.show(el.menu, open);
    if (el.plus) el.plus.setAttribute("aria-expanded", open ? "true" : "false");
  }
  on(el.plus, "click", function (e) { e.stopPropagation(); menu(!!el.menu.hidden); });
  on($("mconv"), "click", function (e) {
    menu(false);
    if (state.conversation) V.endConversation("you ended it");
    else V.openConversation("tap", e);
  });
  on($("mcapture"), "click", function () { menu(false); V.armCapture(state.mode !== "capture"); });
  on($("mspace"), "click", function () { V.setSpace(state.space === "work" ? "personal" : "work"); });
  document.addEventListener("click", function (e) {
    if (!el.menu || el.menu.hidden) return;
    var t = e.target;
    if (t && t.closest && (t.closest("#menu") || t.closest("#plus"))) return;
    menu(false);
  });

  on(el.convpill, "click", function () { V.endConversation("you ended it"); });
  on(el.armedpill, "click", function () { V.armCapture(false); });

  /* ------------------------------------------------------------ the header */

  /* THE TAP THAT GOES BACK TO HARBOR, beside the sentence that does. */
  on(el.who, "click", function () { if (state.pinned) V.say({ type: "disconnect" }); });
  on(el.sheetbtn, "click", V.openSheet);
  on(el.rec, "click", V.openSheet);
  on($("sheetclose"), "click", function () { var s = $("sheet"); if (s && s.close) s.close(); });

  /* ------------------------------------------------------------ the chat and the rail */

  on(el.turns, "click", function (e) {
    var t = e.target && e.target.closest ? e.target.closest("[data-read],[data-open]") : null;
    if (!t) return;
    if (t.dataset.read !== undefined) {
      var row = state.turns[+t.dataset.read];
      if (!row) return;
      row.held = false;
      /* A REPLAY OF TEXT ALREADY ON SCREEN, by the page, in the voice it was answered in. */
      if (window.speechSynthesis) V.speakHere(row.answer, row.speaker, 0);
    } else {
      var turn = state.turns[+t.dataset.open];
      if (turn) turn.open = !turn.open;
    }
    V.render();
  });
  on($("talkto"), "click", function (e) {
    var t = e.target && e.target.closest ? e.target.closest("[data-talk]") : null;
    if (t) V.onTalkTo(t.getAttribute("data-talk"));
  });

  /* ------------------------------------------------------------ keys */

  function typing(e) {
    var t = e.target || {};
    return t.tagName === "INPUT" || t.tagName === "TEXTAREA" || !!t.isContentEditable;
  }
  /* Space holds, Esc cuts, r asks for it again (spoken, so it says `aloud`), / types. */
  document.addEventListener("keydown", function (e) {
    if (e.repeat || typing(e)) {
      if (e.code === "Escape" && el.field && el.field.blur) el.field.blur();
      return;
    }
    if (e.code === "Space") { e.preventDefault(); V.onOrbDown(e); }
    else if (e.code === "Escape") {
      if (el.menu && !el.menu.hidden) { menu(false); return; }
      V.cutAudio();
      V.say({ type: "cut" });
    } else if (e.key === "r") {
      V.say({ type: "text", text: "say that again", mode: "talk", engine: state.engine, aloud: true });
    } else if (e.key === "/") {
      e.preventDefault();
      state.face = "type";
      V.render();
      if (el.field && el.field.focus) el.field.focus();
    }
  });
  document.addEventListener("keyup", function (e) {
    if (e.code === "Space" && !typing(e)) V.onOrbUp(e);
  });

  /* ------------------------------------------------------------ being seen */

  /* LEAVING THE FOREGROUND IS A PAUSE (V3), on both events that say so; coming back does
     not resume by itself, and a page nobody can see draws nothing until it is seen. */
  document.addEventListener("visibilitychange", function () {
    V.reportPresence();
    if (V.hidden()) {
      if (state.conversation || state.holding) V.pauseVoice("hidden");
      return;
    }
    V.renderIfOwed();
    V.render();
  });
  window.addEventListener("pagehide", function () {
    V.reportPresence(false);
    if (state.conversation || state.holding) V.pauseVoice("hidden");
  });
  window.addEventListener("pageshow", function () { V.reportPresence(); });
  window.addEventListener("resize", function () { V.render(); });

  /* "Voice is down. Tap to retry": the shell first for the cookie, then the socket. */
  V.retry = function () {
    if (V.ws.sock && V.ws.sock.readyState <= 1) return;
    fetch(location.pathname, { cache: "no-store", credentials: "same-origin" })
      .then(function () { V.connect(); }, function () { V.connect(); });
  };

  function loadHealth() {
    fetch("/voice/health", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (h) { state.health = h; V.render(); })
      .catch(function () {});
  }

  /* ------------------------------------------------------------- the test door */

  /* OPEN ONLY WHEN IT IS ASKED FOR. It adds no power: everything here is a read of state
     the page already draws, or an entry point the socket and his thumb already reach.
     `tests/fixtures/voice-listen.js` drives the whole listen path through it. */
  if (V.SELFTEST) {
    window.__voiceTest = {
      state: state, flags: V.FLAGS,
      event: V.onEvent, render: V.render, press: V.press, release: V.release, arm: V.armListen,
      tap: V.onOrbDown, lift: V.onOrbUp, converse: V.openConversation,
      label: function () { return el.barlabel ? el.barlabel.textContent : ""; },
      status: function () { return el.note && !el.note.hidden ? el.note.textContent : ""; },
      display: V.displayState,
      face: function () { return (el.bar && !el.bar.hidden) ? "voice" : "type"; },
      type: function (text) { if (el.field) el.field.value = text; V.render(); },
      send: send, mic: micDown,
      capture: V.armCapture, space: V.setSpace,
      frame: V.fakeFrame, micOpen: V.micOpen
    };
  }

  /* -------------------------------------------------------------------- go */

  grow();
  V.connect();
  V.poll();
  loadHealth();
  V.render();
})();
