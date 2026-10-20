/* Voice, listening: the hold, the release, the watchdog, and the conversation.

   PUSH TO TALK IS THE DEFAULT (VP-2): a finger on the mic or the bar opens a listen, and
   lifting it sends. A Conversation (hands free, the microphone reopens after each answer)
   is rare, opened from the + menu, and keeps every behaviour it had (V2, V3, V13).

   `end` IS THE ONLY FLUSH. Every way a listen can finish that is not him letting go on
   purpose (a lost pointer, a stuck one, a stalled pipe, a quiet endpoint) sends `cut`,
   which drops what was heard, and never `end`, which would send the room. */
(function () {
  "use strict";
  var V = window.Voice, state = V.state, FLAGS = V.FLAGS, now = V.now;
  var say = function (o) { V.say(o); };
  var trace = function (e, r) { V.trace(e, r); };
  var render = function () { V.render(); };
  var closeMic = function () { V.closeMic(); };

  /* A LISTEN THE PAGE ARMED BY ITSELF has no pointerup coming, so it gets a backstop:
     twenty seconds with no detector (the page is the only clock), ninety with one (the
     gateway ends the utterance and this exists only for the gateway going quiet). A
     FINGER HAS NO CAP (c-424): only a pointer whose pointerup never came is released, at
     three minutes, and what it heard is dropped. */
  var AUTO_LISTEN_MAX_MS = 20000;
  var LISTEN_FAILSAFE_MS = 90000;
  var STUCK_POINTER_MS = 180000;
  var autoListenTimer = null;

  function clearListenTimer() {
    if (autoListenTimer) { clearTimeout(autoListenTimer); autoListenTimer = null; }
  }

  function detectorReady() {
    return !!(state.health && state.health.vad && state.health.vad.ready);
  }
  V.detectorReady = detectorReady;

  function armedFor() {
    if (!state.autoHeld) return { ms: STUCK_POINTER_MS, kind: "stuck" };
    if (detectorReady()) return { ms: LISTEN_FAILSAFE_MS, kind: "detector" };
    return { ms: AUTO_LISTEN_MAX_MS, kind: "auto" };
  }

  /* ------------------------------------------------- the listen watchdog (V13) */

  /* THE PAGE MUST SEE AUDIO LEAVE THE WORKLET, not merely believe the microphone is open:
     on 2026-09-21 the orb read "listening" for 62 seconds with no frame behind it. Three
     seconds of a listen with no frame is the failure; the page re-presses once with the
     microphone torn down, and then stops claiming to listen and asks for a tap. */
  var FRAME_WATCHDOG_MS = 3000;
  var frameWatch = null;

  function clearFrameWatch() {
    if (frameWatch) { clearTimeout(frameWatch); frameWatch = null; }
  }

  function watchFrames() {
    clearFrameWatch();
    state.lastFrame = now();
    frameWatch = setTimeout(frameCheck, FRAME_WATCHDOG_MS);
  }

  /* It keeps watching: a stream that dies mid-listen is the same failure. */
  function frameCheck() {
    frameWatch = null;
    if (!state.holding || state.paused) return;
    var quietFor = now() - state.lastFrame;
    if (quietFor < FRAME_WATCHDOG_MS) {
      frameWatch = setTimeout(frameCheck, FRAME_WATCHDOG_MS - quietFor);
      return;
    }
    if (!state.repressed) { rePress(); return; }
    micStalled("no frames after a second press");
  }

  function onFrame() {
    state.lastFrame = now();
    if (state.flowing) return;
    state.flowing = true;
    state.repressed = false;
    trace("frames", "first frame of this listen");
    render();      /* the bar stops saying it is opening and starts saying it is listening */
  }
  V.onFrame = onFrame;

  function rePress() {
    trace("repress", "no frames in " + (FRAME_WATCHDOG_MS / 1000) + "s");
    state.repressed = true;
    clearListenTimer();
    clearFrameWatch();
    state.holding = false;
    state.autoHeld = false;
    say({ type: "cut" });
    /* TORN DOWN FIRST: `openMic` returns early while a node exists, so pressing over a
       stream whose tracks have ended would rebuild nothing. */
    closeMic();
    state.autoHeld = true;
    press(null, "repress");
  }

  /* THE PAGE GIVING UP ON THE PIPE is a pause with a different word on the bar: the tracks
     really stopped, the listen retired, the gateway told. The conversation is left OPEN,
     because one tap repairs this. */
  function micStalled(why) {
    clearFrameWatch();
    state.stalled = true;
    state.flowing = false;
    state.repressed = false;
    trace("stalled", why);
    pauseVoice("stalled");
    render();
  }

  /* ------------------------------------------------------------ the hold */

  function press(ev, why) {
    if (ev && ev.preventDefault) ev.preventDefault();
    if (!state.connected) return;
    var gesture = !!ev;
    /* THE FIRST TOUCH AFTER AN AUTO-ARMED LISTEN FINISHES IT rather than restarting it: a
       fresh `start` resets the gateway's buffer and would throw away what he said. */
    if (state.autoHeld && state.holding) { release(null, "tap"); return; }
    /* A SECOND PRESS WHILE HOLDING IS IGNORED (the bar and Space both press). */
    if (state.holding) return;
    if (ev) V.askNotifyPermission();
    V.unlock();
    V.cutAudio();                       /* the interrupt half, always */
    if (FLAGS.pressWhileSpeaking === "cut_only" && state.bus.state === "speaking") {
      say({ type: "cut" });
      return;
    }
    state.holding = true;
    state.paused = false;
    state.stalled = false;
    state.flowing = false;
    state.note = "";
    state.error = "";
    state.face = "voice";
    state.heldSince = now();
    state.listen += 1;
    trace("press", why || (gesture ? "tap" : "auto"));
    var guard = armedFor();
    autoListenTimer = setTimeout(function () {
      if (!state.holding) return;
      if (guard.kind === "stuck") dropHold("failsafe-stuck");
      else release(null, "failsafe-" + guard.kind);
    }, guard.ms);
    /* THE WATCHDOG IS ARMED ON AN AUTOMATIC PRESS ONLY: a finger is its own watchdog. */
    if (state.autoHeld) watchFrames();
    /* `handsFree` arms the gateway's end-of-utterance detector, on an automatic listen
       only; `listen` is echoed back on `endpoint`; `conversation` says another utterance
       is expected after this turn. */
    say({ type: "start", handsFree: !!state.autoHeld, conversation: !!state.conversation,
          listen: state.listen });
    render();
    V.openMic().catch(function (err) {
      state.holding = false;
      state.autoHeld = false;
      clearListenTimer();
      clearFrameWatch();
      state.error = "microphone: " + err.message;
      say({ type: "cut" });
      /* A PRESS WITH NO GESTURE STALLS rather than ending the conversation (iOS wants a
         touch, and one touch repairs it); a real gesture that still could not open the
         microphone ends it. Neither path arms another listen. */
      if (!gesture) micStalled("the microphone would not open");
      else if (state.conversation) endConversation("the microphone would not open");
      render();
    });
  }
  V.press = press;

  function release(ev, why) {
    if (ev && ev.preventDefault) ev.preventDefault();
    state.autoHeld = false;
    clearListenTimer();
    clearFrameWatch();
    if (!state.holding) return;
    state.holding = false;
    trace("release", why || (ev ? "finger" : "auto"));
    /* THE MODE, THE SPACE AND THE ENGINE RIDE ON THE RELEASE, read at the moment he lets
       go, so a choice flipped mid-hold means what it shows when the words are sent. */
    say({ type: "end", mode: state.mode, space: state.space, engine: state.engine });
    /* "Capture next" is one take (VP-2). */
    if (state.mode === "capture") state.mode = "talk";
    render();
  }
  V.release = release;

  /* A RELEASE THAT WENT MISSING: the window lost focus, the pointer was cancelled or slid
     off, or the stuck guard fired. Nobody let go on purpose, so it is `cut`. */
  function dropHold(why) {
    state.autoHeld = false;
    clearListenTimer();
    clearFrameWatch();
    if (!state.holding) return;
    state.holding = false;
    trace("release", why);
    say({ type: "cut" });
    render();
  }
  V.dropHold = dropHold;

  /* ------------------------------------------------------- the launch */

  /* `?connect=c-272`, once per load and before the microphone: the same `connect` the
     spoken phrase makes, so there is one path into a house. */
  var connectTried = false;
  V.maybeConnect = function () {
    if (connectTried || !V.wantsCard) return;
    connectTried = true;
    say({ type: "connect", card: V.wantsCard });
  };

  /* `?listen=1` OPENS A CONVERSATION; `?listen=once` is one hands-free utterance, which is
     what the Capture shortcut (`?listen=once&mode=capture`) points at. */
  var autoListenTried = false;
  function maybeAutoListen() {
    if (autoListenTried) return;
    autoListenTried = true;
    var listen = V.query.get("listen");
    V.mirror();
    if (!listen) return;
    if (listen === "once") { state.autoHeld = true; press(null, "launch-once"); return; }
    openConversation("launch");
  }
  V.maybeAutoListen = maybeAutoListen;

  /* ------------------------------------------------------- the conversation (V2, V3) */

  /* THE RE-ARM WAITS FOR PLAYBACK TO END ON THIS PAGE, plus a guard SHORTER than the
     detector's minimum speech (300 ms), so an echo that survives cannot arm a hangover. */
  var REARM_GUARD_MS = 250;
  var PLAYBACK_POLL_MS = 100;

  function whenPlaybackEnds(then) {
    var done = false;
    function finish(reason) {
      if (done) return;
      done = true;
      trace("playback-end", reason);
      then();
    }
    function settle() {
      if (V.playbackBusy()) { check(); return; }
      finish("ended");
    }
    function check() {
      if (V.playbackBusy()) {
        if (now() - V.out.lastAt > V.PLAYBACK_CEILING_MS) { finish("ceiling"); return; }
        setTimeout(check, PLAYBACK_POLL_MS);
        return;
      }
      setTimeout(settle, REARM_GUARD_MS);
    }
    check();
  }

  /* THE SCREEN STAYS AWAKE ONLY WHILE A CONVERSATION IS LIVE. */
  var wakeLock = null;
  function holdWake() {
    if (wakeLock || !navigator.wakeLock) return;
    try {
      navigator.wakeLock.request("screen").then(function (lock) {
        if (!state.conversation) { try { lock.release(); } catch (e) {} return; }
        wakeLock = lock;
        lock.addEventListener("release", function () { wakeLock = null; });
      }).catch(function () { /* denied is not a failure of the conversation */ });
    } catch (e) { /* nor is a browser that has no such thing */ }
  }
  function dropWake() {
    if (!wakeLock) return;
    var lock = wakeLock;
    wakeLock = null;
    try { lock.release(); } catch (e) { /* already gone */ }
  }

  function openConversation(why, ev) {
    if (!state.connected) return;
    /* NO DETECTOR MEANS NO CONVERSATION: one automatic listen, and the note says why. */
    if (!detectorReady()) {
      state.note = "no detector here, so this is one turn";
      state.autoHeld = true;
      press(ev, "no-detector");
      render();
      return;
    }
    state.conversation = true;
    state.paused = false;
    state.quiet = 0;
    state.note = "";
    state.face = "voice";
    holdWake();
    state.autoHeld = true;
    press(ev, "conversation");
    render();
  }
  V.openConversation = openConversation;

  /* ENDING IS ALWAYS EXPLICIT AND IT ALWAYS SAYS WHY. */
  function endConversation(why) {
    var was = state.conversation;
    state.conversation = false;
    state.paused = false;
    state.partial = false;
    state.stalled = false;
    state.flowing = false;
    state.repressed = false;
    state.quiet = 0;
    dropWake();
    clearFrameWatch();
    if (state.holding) release(null, "ended");
    closeMic();
    if (was) {
      state.note = why ? "conversation ended, " + why : "conversation ended";
      say({ type: "pause", why: "ended" });
    }
    render();
  }
  V.endConversation = endConversation;

  /* PAUSE IS A GESTURE, NOT A WORD (V3). The listen in hand is retired FIRST, so an
     endpoint racing the tap names a listen that no longer exists and is dropped. */
  function pauseVoice(why) {
    if (state.paused) return;
    state.paused = true;
    state.pausedWhy = why || "tap";
    state.partial = false;
    state.listen += 1;
    if (state.holding) {
      state.holding = false;
      state.autoHeld = false;
    }
    state.flowing = false;
    clearListenTimer();
    clearFrameWatch();
    dropWake();
    closeMic();
    say({ type: "pause", why: why || "tap" });
    render();
  }
  V.pauseVoice = pauseVoice;

  function resumeVoice() {
    if (!state.paused) return;
    state.paused = false;
    state.quiet = 0;
    if (state.conversation) holdWake();
    armListen("resume");
  }

  /* THE ONE PLACE THE MICROPHONE REOPENS BY ITSELF: the conversation continuing, a held
     partial asking for the rest (V10), and a resume. */
  function armListen(reason) {
    if (!state.connected || state.paused) return;
    if (state.holding) return;
    trace("arm", reason || "conversation");
    whenPlaybackEnds(function () {
      if (!state.connected || state.paused || state.holding) return;
      if (!state.conversation && reason !== "partial" && reason !== "resume") return;
      state.autoHeld = true;
      press(null, reason || "conversation");
    });
  }
  V.armListen = armListen;

  /* A RUNAWAY IS CAPPED AT THE MINUTE: three listens in a row that hear nothing end it. */
  function heardNothing() {
    state.quiet += 1;
    if (state.conversation && state.quiet >= (FLAGS.quietLimit || 3)) {
      endConversation("nothing heard for a minute");
      return;
    }
    if (state.conversation) armListen("conversation");
  }
  V.heardNothing = heardNothing;

  /* ------------------------------------------------------ gateway messages */

  /* THE GATEWAY HEARD HIM STOP: a release his finger did not make, through the same
     `release`. Guarded on the listen it names and on `autoHeld`, so a stale endpoint
     cannot cut a real press short. A QUIET endpoint heard nothing: `cut`, never `end`. */
  function onEndpoint(msg) {
    if (msg.listen !== undefined && msg.listen !== state.listen) return;
    if (state.paused) return;
    if (msg.reason === "quiet") {
      trace("quiet", "the gateway heard nothing in that listen");
      clearListenTimer();
      clearFrameWatch();
      state.holding = false;
      state.autoHeld = false;
      say({ type: "cut" });
      heardNothing();
      render();
      return;
    }
    if (state.holding && state.autoHeld) release(null, "endpoint");
  }
  V.onEndpoint = onEndpoint;

  /* THE GATEWAY ASKING FOR THE MICROPHONE BY NAME (V13), after a switch. Inside a
     conversation only, never over a pause or a stall, never over a hold. */
  function onListenNow(msg) {
    if (!state.conversation || state.paused || state.stalled) return;
    if (state.holding) return;
    if (msg.generation !== undefined && msg.generation < state.generation) return;
    state.autoHeld = true;
    press(null, "listen-now");
    render();
  }
  V.onListenNow = onListenNow;

  V.socketLost = function () {
    state.holding = false;
    state.autoHeld = false;
    clearListenTimer();
    clearFrameWatch();
    state.flowing = false;
    state.repressed = false;
    state.stalled = false;
    if (state.conversation || state.paused) endConversation("the gateway went away");
  };

  /* ------------------------------------------------------ the gestures */

  /* WHAT A TOUCH ON THE BAR MEANS depends on one thing: whether a conversation is open.
     Outside one it is press and hold. Inside one the microphone is already open and the
     detector ends the sentence, so a tap pauses, except while it is SPEAKING, where a tap
     is the cut plus the next question. A stalled microphone is reopened from the tap
     itself, inside the gesture, before the pause branch. */
  function onOrbDown(ev) {
    if (ev && ev.preventDefault) ev.preventDefault();
    if (!state.connected) { if (ev) V.retry(); return; }
    if (ev) V.askNotifyPermission();
    if (state.stalled) {
      V.unlock();
      state.autoHeld = true;
      press(ev, "tap-after-stall");
      render();
      return;
    }
    if (state.paused) { V.unlock(); resumeVoice(); return; }
    if (state.conversation) {
      if (state.bus.state === "speaking") {
        state.autoHeld = true;            /* the cut re-arms the conversation's listen */
        press(ev, "cut-in");
        return;
      }
      pauseVoice("tap");
      return;
    }
    press(ev);
  }
  V.onOrbDown = onOrbDown;

  function onOrbUp(ev) {
    if (state.conversation || state.paused) { if (ev && ev.preventDefault) ev.preventDefault(); return; }
    release(ev);
  }
  V.onOrbUp = onOrbUp;

  /* A CANCELLED OR LEFT POINTER IS NOT HIM LETTING GO: an edge swipe, a call, a finger
     sliding off. Only a finger hold outside a conversation is dropped by it. */
  function onOrbLost(ev) {
    if (ev && ev.preventDefault) ev.preventDefault();
    if (state.holding && !state.autoHeld && !state.conversation) {
      dropHold("lost-" + (ev && ev.type ? ev.type : "pointer"));
    }
  }
  V.onOrbLost = onOrbLost;
})();
