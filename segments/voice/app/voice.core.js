/* Voice, the page half: the namespace, the flags, the one state object, and the prefs.

   THE PAGE HOLDS NO STATE OF ITS OWN THAT THE GATEWAY DOES NOT ALSO SAY, and it calls
   /api/action for one thing only: his answer to one of Bosun's asks, said back to him and
   confirmed before the gateway hands it here (c-523, `voice.link.js` recordAnswer), which the
   deck refuses on any other verb. Everything it draws comes from GET /voice/state and the
   socket; everything else it does is "he pressed", "he let go", "he typed". A misheard word
   cannot merge anything, because nothing here can merge.

   ONE NAMESPACE, SEVERAL FILES, NO BUILD STEP. Each file is an IIFE that hangs its part on
   `window.Voice` (V), in the order index.html loads them: core, audio, link, listen, wave,
   board, view, desk, sheet, app. A name is only read at call time, so a later file may be
   called from an earlier one. `tests/fixtures/voice-listen.js` loads them in the same order. */
(function () {
  "use strict";
  var V = window.Voice = window.Voice || {};

  V.FLAGS = window.VOICE_FLAGS || {
    /* The gateway's recommended answers, so the page still works with it down. `engines`
       is empty rather than guessed: a control offering engines this machine may not have
       would be the page inventing a fact. */
    whereVoiceLives: "own_app", showTier: "every_answer",
    pressWhileSpeaking: "cut_and_listen", alertAtRest: "static_bar",
    transcriptKeep: 40, busSamples: 64, micRate: 16000, ttsRate: 24000,
    modeDefault: "talk", captureDefaultSpace: "personal",
    engineDefault: "google", engines: []
  };
  var FLAGS = V.FLAGS;

  /* THE TEST DOOR, SHUT UNLESS IT IS ASKED FOR (V13): `?selftest=1`, or `selftest` in
     flags.js, hangs `window.__voiceTest` on the page (app.js). */
  V.SELFTEST = /[?&]selftest=1/.test(location.search) || !!FLAGS.selftest;

  /* ONE CLOCK, THE PAGE'S OWN: monotonic milliseconds since load, which is what a trace's
     `at` is, and a phone correcting its wall clock cannot move it. */
  V.now = function () {
    try { return window.performance.now(); } catch (e) { return Date.now(); }
  };

  V.$ = function (id) { return document.getElementById(id); };

  V.esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  };

  /* A class on or off, through `className` rather than `classList`, so the node fixture's
     stand-in elements need nothing a browser would not give them anyway. */
  V.klass = function (node, name, on) {
    if (!node) return;
    var list = String(node.className || "").split(/\s+/).filter(function (c) {
      return c && c !== name;
    });
    if (on) list.push(name);
    node.className = list.join(" ");
  };
  V.show = function (node, on) { if (node) node.hidden = !on; };
  V.text = function (node, value) {
    if (node && node.textContent !== value) node.textContent = value;
  };

  V.stored = function (k) {
    try { return localStorage.getItem("voice." + k); } catch (e) { return null; }
  };
  V.store = function (k, v) {
    try { localStorage.setItem("voice." + k, v); } catch (e) { /* a private window */ }
  };

  /* THE ONE STATE OBJECT. Every file reads and writes this and nothing else; `render`
     (voice.view.js) computes the single display state out of it in one place. */
  V.state = {
    generation: 0,
    connected: false,
    downSince: 0,          // when the socket last went away (wall clock), for the reason line
    health: null,
    bus: { state: "idle", samples: [], level: 0, alert: false },
    turns: [],             // what is drawn: {id, said, answer, narration[], prov, ...}
    current: null,
    /* THE CONVERSATION (V2) AND THE PAUSE (V3) are the page's, because the gateway answers
       one utterance at a time; `paused` and `partial` sit on top of the bus state. */
    conversation: false,
    paused: false,
    partial: false,
    listen: 0,             // which listen is in hand; the gateway echoes it on `endpoint`
    quiet: 0,              // listens in a row that heard nothing
    /* WHETHER AUDIO IS REALLY LEAVING THE WORKLET (V13): `flowing` from the first frame,
       `lastFrame` when the last one came, `repressed` the cheap repair spent, `stalled`
       the page giving up on the pipe and asking for a tap. */
    flowing: false,
    lastFrame: 0,
    repressed: false,
    stalled: false,
    holding: false,
    autoHeld: false,       // this hold was armed by the page, not by a finger
    heldSince: 0,          // for the bar's timer
    /* THE CARD HE IS CONNECTED TO (V4): the gateway's fact, drawn as it last said it. */
    pinned: "", pinnedTitle: "", pinnedSpace: "", pinnedUntil: 0,
    /* WHICH FACE THE COMPOSER SHOWS (VP-1): "type", the field and the mic, or "voice",
       the full-width bar. A hold turns it to voice (and so does opening a conversation);
       the bar's keyboard button turns it back. */
    face: "type",
    note: "",
    error: ""
  };
  var state = V.state;

  /* ------------------------------------------------------ mode, space, engine */

  /* TALK IS WHERE THE PAGE RESTS (VP-2). 802 talk turns against 23 captures: push to talk
     is the default, and a capture is one hold, armed from the + menu as "Capture next" and
     disarmed by the take. `mode` is what the NEXT release sends; it is never remembered.
     `?mode=capture` (the home-screen Capture shortcut) arms it for this launch only. */
  var SPACES = { personal: 1, work: 1 };
  var ENGINES = (FLAGS.engines || []).filter(function (e) { return e && e.id; });
  var ENGINE_IDS = {};
  ENGINES.forEach(function (e) { ENGINE_IDS[e.id] = 1; });
  V.ENGINES = ENGINES;

  function pick(valid, candidates) {
    for (var i = 0; i < candidates.length; i++) {
      var v = String(candidates[i] || "").toLowerCase();
      if (v === "converse") v = "talk";
      if (valid[v]) return v;
    }
    return null;
  }
  var query = new URLSearchParams(location.search);
  V.query = query;
  state.mode = query.get("mode") === "capture" ? "capture" : "talk";
  state.space = pick(SPACES, [query.get("space"), V.stored("space"),
                              FLAGS.captureDefaultSpace]) || "personal";
  state.engine = pick(ENGINE_IDS, [query.get("engine"), V.stored("engine"),
                                   FLAGS.engineDefault]) ||
                 (ENGINES.length ? ENGINES[0].id : "");
  if (query.get("engine")) V.store("engine", state.engine);
  /* `?connect=c-272`: the deck's "Talk to this house" opens the page connected (V6). A
     launch instruction, dropped from the URL by `mirror`, never remembered. */
  V.wantsCard = String(query.get("connect") || "").trim();

  V.engineInfo = function (id) {
    for (var i = 0; i < ENGINES.length; i++) { if (ENGINES[i].id === id) return ENGINES[i]; }
    return null;
  };
  /* The engine the control calls it, so the provenance line and the sheet agree. */
  V.engineName = function (backend) {
    for (var i = 0; i < ENGINES.length; i++) {
      if (ENGINES[i].backend === backend || ENGINES[i].id === backend) return ENGINES[i].label;
    }
    return backend;
  };
  V.spaceName = function (space) { return space === "work" ? "Work" : "Personal"; };

  /* `?engine=` follows the choice; `listen`, `connect` and `mode` are launch instructions
     and are dropped, so a reload does not open the microphone or take a pin again. */
  V.mirror = function () {
    try {
      var q = new URLSearchParams(location.search);
      if (state.engine) q.set("engine", state.engine);
      q.delete("listen");
      q.delete("connect");
      q.delete("mode");
      var rest = q.toString();
      history.replaceState(null, "", location.pathname + (rest ? "?" + rest : ""));
    } catch (e) { /* a page that cannot rewrite its URL still works */ }
  };

  V.setEngine = function (id) {
    if (!ENGINE_IDS[id] || id === state.engine) return;
    state.engine = id;
    V.store("engine", id);
    V.mirror();
    V.render();
  };
  V.cycleEngine = function () {
    if (ENGINES.length < 2) return;
    var i = 0;
    for (var n = 0; n < ENGINES.length; n++) { if (ENGINES[n].id === state.engine) i = n; }
    V.setEngine(ENGINES[(i + 1) % ENGINES.length].id);
  };

  /* THE PALETTE IS THE SPACE, the deck's own rule: only colour changes with the switch. */
  V.setSpace = function (space) {
    if (!SPACES[space]) return;
    state.space = space;
    V.store("space", space);
    try { document.documentElement.setAttribute("data-mode", space); } catch (e) { /* stub */ }
    V.render();
  };

  /* "Capture next": armed for one hold, disarmed by the take or by a second tap. */
  V.armCapture = function (on) {
    state.mode = on ? "capture" : "talk";
    V.render();
  };

  /* ------------------------------------------------------ the phrase tables */

  /* THE SAME MATCH THE GATEWAY MAKES: the WHOLE utterance, lower-cased, whitespace
     collapsed, trailing punctuation dropped, against a table flags.js serves. Never a
     substring: "that's all I could find" cannot end a conversation. */
  function normalise(said) {
    return String(said == null ? "" : said).split(/\s+/).join(" ")
      .replace(/^\s+/, "").replace(/[.!?\s]+$/, "").toLowerCase();
  }
  function isPhrase(table, said) {
    if (!table || !table.length) return false;
    return table.indexOf(normalise(said)) >= 0;
  }
  V.normalise = normalise;
  V.isPhrase = isPhrase;

  /* Whether the page can be seen. A hidden page renders nothing (VP-7). */
  V.hidden = function () {
    try { return !!document.hidden; } catch (e) { return false; }
  };
  V.isDesk = function () {
    try { return !!(window.matchMedia && window.matchMedia("(min-width:900px)").matches); }
    catch (e) { return false; }
  };
  V.reducedMotion = function () {
    try {
      return !!(window.matchMedia &&
                window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    } catch (e) { return false; }
  };

  /* Filled in by voice.view.js; a call before it has loaded draws nothing. */
  V.render = V.render || function () {};
})();
