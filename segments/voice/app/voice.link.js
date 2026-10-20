/* Voice, the link: the socket, the bus poll, and what each message from the gateway does.

   THE GENERATION NUMBER IS THE WHOLE OF BARGE-IN. Every audio chunk arrives with four bytes
   of generation in front of it, and a chunk from a turn he has already interrupted is
   dropped here rather than cancelled at the source.

   THE SOCKET NEEDS THE DECK'S COOKIE (c-451, I-9), and a deck that restarted holds a new
   one, so every reconnect fetches this app's own shell first. */
(function () {
  "use strict";
  var V = window.Voice, state = V.state, FLAGS = V.FLAGS;

  var ws = { sock: null, send: function () {} };
  V.ws = ws;
  /* ONE PING TIMER FOR THE PAGE, cleared on every close (bug 10: it was created in every
     `onopen` and never cleared, so a flapping gateway stacked them). */
  var pinger = null;
  var PING_MS = 25000;
  var RECONNECT_MS = 3000;
  V.RECONNECT_MS = RECONNECT_MS;

  function reconnect() {
    fetch(location.pathname, { cache: "no-store", credentials: "same-origin" })
      .then(function () { connect(); }, function () { connect(); });
  }

  function stopPing() {
    if (pinger) { clearInterval(pinger); pinger = null; }
  }

  function connect() {
    var scheme = location.protocol === "https:" ? "wss://" : "ws://";
    var sock = new WebSocket(scheme + location.host + "/voice/ws");
    sock.binaryType = "arraybuffer";
    ws.sock = sock;
    ws.send = function (payload) {
      if (sock.readyState === 1) sock.send(payload);
    };
    sock.onopen = function () {
      state.connected = true;
      state.downSince = 0;
      reportPresence();
      stopPing();
      pinger = setInterval(function () { say({ type: "ping" }); }, PING_MS);
      V.render();
      V.maybeConnect();
      V.maybeAutoListen();
    };
    sock.onclose = function () {
      stopPing();
      if (state.connected || !state.downSince) state.downSince = Date.now();
      state.connected = false;
      /* A DROPPED SOCKET ENDS THE LISTEN ON THE GATEWAY'S SIDE TOO, so nothing here may go
         on believing it holds one: a release after reconnect would send an `end` the
         gateway never saw a `start` for. The watchdog and the conversation go with it,
         and the microphone is really closed. */
      V.socketLost();
      V.render();
      setTimeout(reconnect, RECONNECT_MS);
    };
    sock.onmessage = function (ev) {
      if (typeof ev.data !== "string") return onAudio(ev.data);
      var msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      onEvent(msg);
    };
  }
  V.connect = connect;

  function say(obj) { ws.send(JSON.stringify(obj)); }
  V.say = say;

  /* WHETHER THIS PAGE CAN BE SEEN (c-438), on every visibility change and every open. A
     presence fact, never a command: the gateway uses it only to hold back speech nobody
     asked for. */
  function reportPresence(visible) {
    if (visible === undefined) visible = !V.hidden();
    say({ type: "presence", visible: !!visible });
  }
  V.reportPresence = reportPresence;

  /* THE TRACE (V13): what the page did, when, and about which listen, LOGGED by the gateway
     and never acted on. */
  var now = V.now;
  function trace(event, reason) {
    say({ type: "trace", event: event, reason: String(reason == null ? "" : reason),
          listen: state.listen ? String(state.listen) : "", at: Math.round(now()) });
  }
  V.trace = trace;

  function onAudio(buf) {
    var gen = new DataView(buf).getUint32(0);
    if (gen !== state.generation) return;      /* a turn he already moved on from */
    V.enqueue(buf.slice(4));
  }

  /* ---------------------------------------------------------- the messages */

  function onTranscript(msg) {
    state.quiet = 0;
    /* THE CONVERSATION WORDS, MATCHED HERE AS THE FLOOR: the gateway matches the same
       table first, and closing what is closed does nothing. */
    if (V.isPhrase(FLAGS.endPhrases, msg.text)) V.endConversation("you said that was all");
    else if (V.isPhrase(FLAGS.pausePhrases, msg.text)) V.pauseVoice("asked");
    state.generation = msg.generation || state.generation;
    state.current = newRow("t" + state.generation, msg.text, msg.mode || "talk");
    state.current.repairs = msg.repairs || [];
    state.current.generation = state.generation;
    state.current.typed = !!msg.typed;
    state.turns.push(state.current);
    state.turns = state.turns.slice(-FLAGS.transcriptKeep);
    /* A CAPTURE IS ONE TAKE (VP-2): the words are in, so "Capture next" is spent. */
    if (msg.mode === "capture" && state.mode === "capture") state.mode = "talk";
  }

  function onCaptured(msg) {
    /* THE CARD A CAPTURE BECAME, on the turn that was filed, before the next poll. */
    for (var k = state.turns.length - 1; k >= 0; k--) {
      var row = state.turns[k];
      if (row.generation === msg.generation || (msg.turn && row.turnId === msg.turn)) {
        row.card = msg.id || row.card;
        row.space = msg.space || row.space;
        break;
      }
    }
  }

  function onSpeak(msg) {
    state.generation = msg.generation || state.generation;
    /* THE FLOOR OF THE CHAIN: the gateway has no working synthesiser, so the page speaks. */
    if (msg.engine === "browser" && window.speechSynthesis) {
      V.speakHere(msg.text, msg.speaker, state.generation);
    }
  }

  function onEvent(msg) {
    var t = msg.type;
    if (t === "endpoint") return V.onEndpoint(msg);
    if (t === "listen-now") return V.onListenNow(msg);
    if (t === "listen") {
      /* REOPEN THE MICROPHONE: a conversation is open, or half a sentence is held (V10). */
      state.partial = msg.reason === "partial";
      V.armListen(msg.reason || "conversation");
    } else if (t === "partial") {
      state.partial = msg.state === "held";
    } else if (t === "connected") {
      setPinned(msg.card, msg.title, msg.space, msg.until);
      if (!msg.card && msg.why) state.note = msg.why;
    } else if (t === "conversation") {
      if (msg.state === "closed") V.endConversation(msg.why || "");
      else if (msg.state === "paused") V.pauseVoice(msg.why || "asked");
      return;
    } else if (t === "transcript") {
      onTranscript(msg);
    } else if (t === "speak") {
      onSpeak(msg);
      return;
    } else if (t === "captured") {
      onCaptured(msg);
    } else if (t === "error") {
      state.error = msg.where + ": " + msg.what;
      /* A LISTEN THAT PRODUCED NO WORDS COUNTS TOWARD THE CAP, and the gateway says so. */
      if (msg.where === "stt" && state.conversation) V.heardNothing();
    } else if (t === "notice") {
      notify(msg.text);
      return;
    } else if (t === "answer") {
      recordAnswer(msg);
      return;
    } else {
      return;          /* `pong`, and any type a newer gateway adds */
    }
    V.render();
  }
  V.onEvent = onEvent;

  /* HIS ANSWER TO ONE OF BOSUN'S ASKS, BY VOICE (c-523, BO-5). The one thing this page posts
     to /api/action, and only this: the Console's own answer body with `voice: true`, which
     the deck records as his, by voice, and refuses on any other verb. Harbor said his pick
     back and he said yes before the gateway sent this; the gateway holds no token, and the
     page, carrying the deck's cookie, is him. The result is a note, never spoken again. */
  function recordAnswer(msg) {
    if (!msg.ask || !msg.choice) return;
    var body = { verb: "console", sub: "answer", target: msg.ask, choice: msg.choice, voice: true };
    if (msg.words) body.words = msg.words;
    fetch("/api/action", { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        state.note = d && d.ok ? "Recorded for Bosun: " + msg.ask + " " + msg.choice
          : "Not recorded: " + ((d && d.error) || "refused");
        V.render();
      }, function () { state.note = "Not recorded: the deck did not answer"; V.render(); });
  }
  V.recordAnswer = recordAnswer;

  /* ------------------------------------------------------ best-effort attention */

  var notifyAsked = false;
  /* Asked only from a real gesture, which is what the API wants and the honest place. */
  V.askNotifyPermission = function () {
    if (notifyAsked || !("Notification" in window)) return;
    notifyAsked = true;
    if (Notification.permission === "default") {
      try { Notification.requestPermission(); } catch (e) { /* not fatal */ }
    }
  };
  function notify(text) {
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    if (!V.hidden()) return;
    try { new Notification("Harbor", { body: text, tag: "voice-answer" }); }
    catch (e) { /* best effort; nothing here can make this reliable */ }
  }

  /* ------------------------------------------------------------ the bus */

  /* THE ONE WRITER OF THE PIN, and every caller is the gateway telling the page: the
     `connected` broadcast, or the bus the poll reads (the dispatcher drops a pin by itself
     when the hold is gone, and that is not a socket message). */
  function setPinned(card, title, space, until) {
    state.pinned = card || "";
    state.pinnedTitle = state.pinned ? (title || state.pinnedTitle || "") : "";
    state.pinnedSpace = state.pinned ? (space || state.pinnedSpace || "") : "";
    state.pinnedUntil = state.pinned ? (Number(until) || state.pinnedUntil || 0) : 0;
    if (state.pinnedSpace) document.body.setAttribute("data-house", state.pinnedSpace);
    else document.body.removeAttribute("data-house");
  }
  V.setPinned = setPinned;

  var timer = null;
  function schedule(ms) { clearTimeout(timer); timer = setTimeout(poll, ms); }

  /* ONE SECOND AT REST, 120 MS WHILE A TURN IS LIVE, AND FIVE WHILE HIDDEN: a page nobody
     can see renders nothing and has nothing to hurry for (VP-7). */
  function poll() {
    fetch("/voice/state", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (b) {
        state.bus = b;
        setPinned(b.connected && b.connected.card, b.connected && b.connected.title,
                  b.connected && b.connected.space, b.connected && b.connected.until);
        applyTurn(b.turn || {});
        V.render();
        schedule(V.hidden() ? 5000 : (b.state === "idle" ? 1000 : 120));
      })
      .catch(function () {
        state.connected = false;
        V.render();
        schedule(2000);
      });
  }
  V.poll = poll;

  function newRow(id, said, mode) {
    return { id: id, said: said || "", answer: "", narration: [], prov: "", held: false,
             tier: "", repairs: [], gaveUp: false, spoken: true, typed: false,
             mode: mode || "talk", card: "", space: "", boards: [], phase: "" };
  }

  function findRow(turn) {
    for (var i = state.turns.length - 1; i >= 0; i--) {
      if (state.turns[i].turnId === turn.id) return state.turns[i];
    }
    var row = state.current && !state.current.turnId ? state.current : null;
    if (!row) {
      row = newRow(turn.id, turn.text, turn.mode);
      state.turns.push(row);
      state.turns = state.turns.slice(-FLAGS.transcriptKeep);
    }
    row.turnId = turn.id;
    return row;
  }

  /* THE PROVENANCE LINE, measured per turn: "Harbor · 9s · as it streamed · Google". */
  function provenance(turn, row) {
    var line = "";
    if (row.mode === "capture") {
      var secs = /([0-9.]+)s$/.exec(turn.provenance || "");
      if (turn.card) line = "captured · " + (secs ? secs[1] : (turn.since || 0).toFixed(1)) + "s";
      else line = turn.provenance || "";
    } else if (turn.provenance) {
      line = turn.provenance;
    } else if (turn.answer) {
      line = (turn.tier === "harbor" ? "Harbor, " : "board, ") + (turn.since || 0).toFixed(1) + "s";
    }
    /* WHICH ENGINE ACTUALLY SPOKE (V7), appended: it is not the chosen one whenever the
       chain demoted mid-answer, which is exactly the case worth seeing. */
    if (turn.spokeWith && turn.spokeWith.length && line) {
      line += ", " + turn.spokeWith.map(V.engineName).join(", then ");
    }
    return line.replace(/, /g, " · ").replace(/ \(/g, " · ").replace(/\)/g, "");
  }

  function applyTurn(turn) {
    if (!turn.id) return;
    var row = findRow(turn);
    row.said = turn.text || row.said;
    row.answer = turn.answer || row.answer;
    row.narration = turn.narration || row.narration;
    row.held = !!turn.held;
    row.tier = turn.tier || row.tier;
    row.phase = turn.phase;
    row.speaker = turn.speaker || row.speaker || "";
    row.since = turn.since || 0;
    row.eta = turn.eta || null;
    row.error = turn.error || "";
    row.routeSeconds = turn.routeSeconds || 0;
    if ("gaveUp" in turn) row.gaveUp = !!turn.gaveUp;
    if ("spoken" in turn) row.spoken = !!turn.spoken;
    if ("typed" in turn) row.typed = !!turn.typed;
    if (turn.mode) row.mode = turn.mode;
    if (turn.card) row.card = turn.card;
    if (turn.space) row.space = turn.space;
    if (turn.boards && turn.boards.length) row.boards = turn.boards.slice();
    var prov = provenance(turn, row);
    if (prov) row.prov = prov;
  }
  V.applyTurn = applyTurn;
  V.newRow = newRow;
})();
