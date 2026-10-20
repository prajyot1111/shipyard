/* Voice, the view: one display state, the header, the composer and its bar, the chat.

   THE BAR NEVER LIES (the spec's second principle): its label always says what the next
   touch does, and "Listening" waits for audio. `displayState` is the ONE place that decides
   which word wins; everything else reads its answer.

   A HIDDEN PAGE RENDERS NOTHING (VP-7): state keeps moving, the DOM does not, and the page
   renders once when it is seen again. */
(function () {
  "use strict";
  var V = window.Voice, state = V.state, FLAGS = V.FLAGS, esc = V.esc, $ = V.$;
  var el = {};

  function grab() {
    ["top", "back", "backdot", "who", "ring", "whodot", "whoid", "whoname", "rec",
     "sheetbtn", "stage", "empty", "turns", "note", "pills", "convpill", "armedpill",
     "compose", "plus", "field", "send", "mic", "menu", "mconvname", "mconvdesc",
     "mcapturename", "mcapturedesc", "mspacename", "mspacedesc", "bar", "kbd", "control",
     "barchip", "barlabel", "barmeta", "barsub"].forEach(function (id) { el[id] = $(id); });
  }
  grab();
  V.el = el;

  /* ONE DISPLAY STATE. Down beats stalled beats paused beats partial beats the bus: a socket
     that is gone makes every other word a lie, a closed microphone is not listening whatever
     the bus last said, and while the page holds, the PAGE knows better than the bus: a hold
     before its first frame is `opening`, and "listening" waits for audio (V13). */
  function displayState() {
    if (!state.connected) return "down";
    if (state.stalled) return "stalled";
    if (state.paused) return "paused";
    if (state.partial) return "partial";
    if (state.holding) return state.flowing ? "listening" : "opening";
    return state.bus.state || "idle";
  }
  V.displayState = displayState;

  /* WHAT THE BAR SAYS, which is what the next touch does. Inside a conversation a tap
     pauses, except while it speaks, where a tap is the cut and the next question. */
  var CONVERSATION_LABEL = {
    idle: "Tap to pause", listening: "Listening, tap to pause",
    thinking: "Harbor is thinking", speaking: "Tap to cut in"
  };
  /* A pin is a card id, or Bosun (c-523), whose id is its name. */
  function named(pin) { return pin === "bosun" ? "Bosun" : (pin || ""); }
  function barLabel(s) {
    if (s === "down") return "Voice is down. Tap to retry";
    if (s === "stalled") return "Microphone stalled, tap to reopen";
    if (s === "paused") return "Paused, mic closed. Tap to resume";
    if (s === "partial") return "Go on";
    if (s === "opening") return "Opening the microphone";
    if (state.conversation) return CONVERSATION_LABEL[s] || CONVERSATION_LABEL.idle;
    if (s === "listening") return "Release to send";
    if (s === "thinking") return (named(state.pinned) || "Harbor") + " is thinking";
    if (s === "speaking") return "Hold to cut in";
    if (state.mode === "capture") return "Hold to capture to " + state.space;
    if (state.pinned) return "Hold to talk to " + named(state.pinned);
    return "Hold to talk";
  }
  V.barLabel = barLabel;

  function clock(ms) {
    var secs = Math.max(0, Math.floor(ms / 1000));
    return Math.floor(secs / 60) + ":" + (secs % 60 < 10 ? "0" : "") + (secs % 60);
  }

  function barMeta(s) {
    if (s === "listening" || s === "opening") return clock(V.now() - state.heldSince);
    if (s === "thinking") {
      var t = state.bus.turn || {};
      var since = Math.round(t.since || 0);
      return since ? since + "s" + (t.eta ? " of about " + Math.round(t.eta) + "s" : "") : "";
    }
    return "";
  }

  function barSub(s) {
    if (state.conversation || s !== "thinking") return "";
    return "Hold to talk over it";
  }

  /* ------------------------------------------------------------ the header */

  var HOLD_SECONDS = 300;    // a pin holds five minutes and is renewed by every turn (V4)

  function header() {
    var pinned = !!state.pinned;
    V.klass(el.who, "pinned", pinned);
    V.show(el.whoid, pinned);
    V.show(el.ring, pinned && !!state.pinnedUntil);
    V.show(el.whodot, !pinned);
    V.text(el.whoid, named(state.pinned));
    V.text(el.whoname, pinned ? (state.pinnedTitle || "a house") : "Harbor");
    if (el.whoid) el.whoid.setAttribute("data-space", state.pinnedSpace || "");
    if (el.who) el.who.setAttribute("aria-label", pinned
      ? "talking to " + state.pinned + (state.pinnedTitle ? ", " + state.pinnedTitle : "") +
        ", tap to go back to Harbor"
      : "talking to Harbor");
    if (pinned && state.pinnedUntil && el.ring) {
      var left = Math.max(0, state.pinnedUntil - Date.now() / 1000);
      var turn = Math.round(Math.min(1, left / HOLD_SECONDS) * 360);
      if (el.ring.style && el.ring.style.setProperty) el.ring.style.setProperty("--left", turn + "deg");
      el.ring.setAttribute("aria-label", Math.ceil(left / 60) + " minutes left on the hold");
    }
    var rec = state.health && state.health.record;
    V.show(el.rec, !!(rec && rec.recording));
    /* Q4, built as a static mark: a decision waiting is shown on the way back to the deck,
       and nothing here acts on it. */
    var alert = FLAGS.alertAtRest === "static_bar" && !!state.bus.alert;
    V.show(el.backdot, alert);
    if (el.back) el.back.setAttribute("aria-label",
      alert ? "back to the deck, a decision is waiting" : "back to the deck");
  }

  /* ----------------------------------------------------------- the dock */

  /* THE ONE-LINE REASON above the composer: the most important true thing that is not the
     bar's own label, or nothing. */
  function noteLine(s) {
    if (s === "down") {
      var since = state.downSince ? new Date(state.downSince) : null;
      var at = since ? " since " + (since.getHours() < 10 ? "0" : "") + since.getHours() + ":" +
        (since.getMinutes() < 10 ? "0" : "") + since.getMinutes() : "";
      return "Gateway not answering" + at + ". Retrying every " + (V.RECONNECT_MS / 1000) + "s.";
    }
    if (state.health && state.health.stt && !state.health.stt.ready) {
      return "Speech is not being heard here: " + (state.health.stt.why || "no speech model");
    }
    if (s === "stalled") return "No audio is reaching the gateway. Tap the bar to reopen the microphone.";
    if (s === "paused" && state.pausedWhy === "hidden") return "Paused when the screen locked. Tap to resume.";
    if (s === "partial") return "Held, waiting for the rest of the sentence.";
    if (state.error) return state.error;
    return state.note || "";
  }

  function menu() {
    var ready = V.detectorReady();
    V.text(el.mconvname, state.conversation ? "End conversation" : "Conversation");
    V.text(el.mconvdesc, state.conversation
      ? "Back to push to talk, and the microphone closes"
      : ready ? "Hands free: the microphone reopens after each answer"
              : "Needs the end-of-utterance detector, which this gateway has not got");
    var conv = $("mconv");
    if (conv) conv.disabled = !ready && !state.conversation;
    var armed = state.mode === "capture";
    V.text(el.mcapturename, armed ? "Cancel Capture next" : "Capture next");
    V.text(el.mcapturedesc, "The next hold files a card in " + state.space + ", with no answer");
    V.text(el.mspacename, "Captures go to " + state.space);
    V.text(el.mspacedesc, "Tap to file them in " + (state.space === "work" ? "personal" : "work") + " instead");
  }

  function dock(s) {
    var note = noteLine(s);
    V.show(el.note, !!note);
    V.text(el.note, note);
    V.klass(el.note, "crit", s === "down" || s === "stalled" || !!state.error);
    var armed = state.mode === "capture";
    V.show(el.convpill, state.conversation);
    V.show(el.armedpill, armed);
    V.show(el.pills, state.conversation || armed);
    /* THE VOICE FACE while he holds, and after a hold until the keyboard button (a
       conversation opens on it too); otherwise the field and the mic. */
    var voice = state.face === "voice" || state.holding;
    V.show(el.bar, voice);
    V.show(el.compose, !voice);
    var typed = !!(el.field && String(el.field.value || "").trim());
    V.show(el.send, typed);
    V.show(el.mic, !typed);
    menu();
    var label = barLabel(s);
    V.text(el.barlabel, label);
    if (el.control) {
      el.control.setAttribute("aria-label", label);
      el.control.setAttribute("data-bar", s);
    }
    if (el.bar) {
      el.bar.setAttribute("data-bar", s);
      el.bar.setAttribute("data-armed", armed ? "capture" : "");
    }
    V.text(el.barmeta, barMeta(s));
    var sub = barSub(s);
    V.show(el.barsub, !!sub);
    V.text(el.barsub, sub);
    V.show(el.barchip, !!state.pinned && !state.conversation);
    V.text(el.barchip, state.pinned);
    if (el.barchip) el.barchip.setAttribute("data-space", state.pinnedSpace || "");
    if (el.mic) el.mic.setAttribute("aria-label", armed ? "hold to capture" :
      state.pinned ? "hold to talk to " + state.pinned : "hold to talk");
  }

  /* ------------------------------------------------------------ the chat */

  var DONE = { done: 1, failed: 1, abandoned: 1, held: 1, superseded: 1, quiet: 1, cut: 1 };

  function waiting(t) { return !t.answer && !DONE[t.phase] && t.mode !== "capture"; }

  function saidHtml(t) {
    var mark = t.typed ? '<span class="v-mark mono">typed</span>' : "";
    var heard = (t.repairs && t.repairs.length)
      ? '<div class="v-heard">heard ' + t.repairs.map(function (r) {
          return '"' + esc(r.heard) + '" as "' + esc(r.readAs) + '"';
        }).join(", ") + "</div>" : "";
    return '<div class="v-said">' + esc(t.said) + mark + "</div>" + heard;
  }

  /* WHILE HARBOR WORKS: one narration line that changes, and under it the filler he heard.
     When the answer lands the narration folds behind the provenance line. */
  function liveHtml(t) {
    var lines = t.narration || [];
    if (!lines.length) {
      return '<div class="v-live-line">' + (t.tier === "house" ? "Waiting on the house" : "Working on it") +
        '<span class="v-dots" aria-hidden="true"><i></i><i></i><i></i></span></div>';
    }
    var now = lines[lines.length - 1];
    var filler = lines.length > 1 ? lines[0] : "";
    return '<div class="v-live-line">' + esc(now) +
      '<span class="v-dots" aria-hidden="true"><i></i><i></i><i></i></span></div>' +
      (filler ? '<div class="v-filler">' + esc(filler) + "</div>" : "");
  }

  /* THE GIVE-UP READS THE SAME HERE AND IN THE SHEET (bug 9). */
  V.answerWords = function (t) {
    if (t.gaveUp && !t.spoken && !t.answer) return { redirect: true, text: "Answered, on your queue." };
    if (t.answer) return { text: t.answer };
    if (t.mode === "capture") return { text: "" };
    if (t.phase === "failed") return { failed: true, text: t.error ? "Did not reach Harbor: " + t.error : "Did not reach Harbor." };
    if (DONE[t.phase]) return { quiet: true, text: t.prov || "" };
    return null;
  };

  function answerHtml(t, i) {
    if (waiting(t)) return liveHtml(t);
    var w = V.answerWords(t);
    var out = "";
    if (w && w.redirect) out += '<div class="v-redirect">' + esc(w.text) + "</div>";
    else if (w && w.failed) out += '<div class="v-answer v-failed">' + esc(w.text) + "</div>";
    else if (w && w.text && !w.quiet) {
      out += '<div class="v-answer' + (t.held ? " held" : "") + '">' + esc(w.text) + "</div>";
    }
    if (t.held) {
      out += '<div class="v-heldnote">Harbor answered while you were talking</div>' +
             '<button class="v-link" type="button" data-read="' + i + '">Read it out</button>';
    }
    var narr = (t.narration || []).length;
    if (t.prov && FLAGS.showTier === "every_answer") {
      out += narr
        ? '<button class="v-prov mono" type="button" data-open="' + i + '" aria-expanded="' +
          (t.open ? "true" : "false") + '">' + esc(t.prov) + "</button>"
        : '<div class="v-prov mono">' + esc(t.prov) + "</div>";
    }
    if (narr && t.open) {
      /* what the wait said, and how long routing took (bug 7: it was sent and never shown) */
      out += '<div class="v-narr">' + t.narration.map(function (l) {
        return "<div>" + esc(l) + "</div>";
      }).join("") + (t.routeSeconds ? '<div class="mono">routed in ' + t.routeSeconds.toFixed(2) + "s</div>" : "") +
        "</div>";
    }
    if (t.error && t.phase !== "failed") out += '<div class="v-err">' + esc(t.error) + "</div>";
    return out;
  }

  /* A CAPTURE'S RECEIPT: the card it became and where it sits, one tap from the deck. */
  function captureRow(t) {
    if (!t.card) return "";
    var space = t.space || state.space;
    return '<a class="v-receipt" href="/?view=cards&card=' + encodeURIComponent(t.card) +
      "&space=" + encodeURIComponent(space) + '">' +
      '<span class="v-ricon v-ricon-card" aria-hidden="true"></span>' +
      '<span class="v-rtext"><span class="v-rtitle">Captured <span class="mono">' + esc(t.card) +
      '</span></span><span class="v-rmeta">' + esc(space) + " inbox</span></span>" +
      '<span class="v-rchev" aria-hidden="true">›</span></a>';
  }

  /* WHERE THE REAL BOARD IS DRAWN: under the latest answer on the phone, in the right
     column on the desk. Everywhere else a board is a one-row receipt. */
  function embedHere(t, latest) {
    return latest && !V.isDesk() && t.boards && t.boards.length ? t.boards[t.boards.length - 1] : "";
  }

  var nodes = {};

  function turnNode(t) {
    var node = nodes[t.id];
    if (node) return node;
    node = document.createElement("article");
    node.className = "v-turn";
    node.innerHTML = '<div class="v-tbody"></div><div class="v-tboards"></div>';
    node._body = node.querySelector ? node.querySelector(".v-tbody") : null;
    node._boards = node.querySelector ? node.querySelector(".v-tboards") : null;
    nodes[t.id] = node;
    return node;
  }

  function paintTurn(t, i, latest) {
    var node = turnNode(t);
    V.klass(node, "latest", latest);
    V.klass(node, "captured", t.mode === "capture");
    V.klass(node, "typed", !!t.typed);
    var body = saidHtml(t) + answerHtml(t, i) + captureRow(t);
    if (node._body && node._sig !== body) { node._body.innerHTML = body; node._sig = body; }
    var embedId = embedHere(t, latest);
    var rows = (t.boards || []).filter(function (b) { return b !== embedId; }).map(V.boardRow).join("");
    var bsig = rows + "|" + embedId;
    if (node._boards && node._bsig !== bsig) {
      node._boards.innerHTML = rows;
      node._bsig = bsig;
    }
    var embed = embedId ? V.boardEmbed(embedId) : null;
    if (embedId && node._boards) {
      if (embed && embed.parentNode !== node._boards) {
        /* a placeholder built before the drawing code arrived goes with the rows */
        node._boards.innerHTML = rows;
        node._boards.appendChild(embed);
      }
      else if (!embed) node._bsig = "";          /* try again when it is ready */
    }
    return node;
  }

  function chat() {
    var host = el.turns;
    V.show(el.empty, !state.turns.length);
    if (!host) return;
    var keep = {};
    state.turns.forEach(function (t, i) {
      var node = paintTurn(t, i, i === state.turns.length - 1);
      keep[t.id] = 1;
      if (host.children && host.children[i] !== node && host.insertBefore) {
        host.insertBefore(node, host.children[i] || null);
      }
    });
    Object.keys(nodes).forEach(function (id) {
      if (keep[id]) return;
      if (nodes[id].parentNode && nodes[id].parentNode.removeChild) nodes[id].parentNode.removeChild(nodes[id]);
      delete nodes[id];
    });
    /* THE NEWEST WORDS STAY IN VIEW: a new turn, or the latest one growing, scrolls. A
       latest turn taller than the stage (a board under the answer, on the phone) is shown
       from its top, so his question and the answer are what he sees, and the board below. */
    var last = state.turns.length ? nodes[state.turns[state.turns.length - 1].id] : null;
    var mark = state.turns.length + ":" + (last ? (last._sig || "") + (last._bsig || "") : "");
    if (el.stage && mark !== chat.mark) {
      chat.mark = mark;
      var tall = last && last.offsetHeight > el.stage.clientHeight - 32;
      el.stage.scrollTop = tall ? last.offsetTop - el.stage.offsetTop - 16 : el.stage.scrollHeight;
    }
  }

  /* ------------------------------------------------------------- render */

  var owed = false;
  function render() {
    if (V.hidden()) { owed = true; return; }
    owed = false;
    var s = displayState();
    document.body.dataset.state = s;
    document.body.dataset.conversation = state.conversation ? "open" : "";
    document.body.dataset.face = (state.face === "voice" || state.holding) ? "voice" : "type";
    header();
    dock(s);
    chat();
    V.wave();
    if (V.desk) V.desk();
  }
  V.render = render;
  V.renderIfOwed = function () { if (owed) render(); };
})();
