/* Voice, audio: the answer coming down, his voice going up, and the browser's own floor.

   DOWN: 24 kHz PCM16 with a 4-byte generation in front, queued gapless on one context; a
   cut is a 30 ms ramp, never a bare stop. UP: an inline-Blob AudioWorklet, 16 kHz mono
   PCM16, streamed only while he holds, echo cancellation and noise suppression on, into a
   zero-gain sink. `speechSynthesis` is the floor of the gateway's chain. */
(function () {
  "use strict";
  var V = window.Voice, state = V.state, FLAGS = V.FLAGS, now = V.now;

  /* PCM16 up, as it is captured: an AudioWorklet rather than MediaRecorder, whose chunk
     boundaries and Safari container support are both awkward for a speech model. */
  var WORKLET = 'class P extends AudioWorkletProcessor{' +
    'process(inputs){var c=inputs[0]&&inputs[0][0];' +
    'if(c&&c.length)this.port.postMessage(new Float32Array(c));return true}}' +
    'registerProcessor("cap",P)';

  var mic = { ctx: null, node: null, stream: null, rate: 16000 };
  /* `lastAt` is WALL time, when the last thing to play was handed to a player (the
     playback ceiling is measured from it); `out.at` is when queued samples END in the
     context's own clock, which says nothing about `speechSynthesis`. */
  var out = { ctx: null, gain: null, at: 0, lastAt: 0, sources: [] };
  /* What the page itself asked the browser to say and has not heard back about. */
  var speech = { out: 0 };
  V.out = out;
  V.speech = speech;
  /* HIS LEVEL, from the frames themselves, for the waveform while he holds (VP-7). */
  V.micLevel = 0;

  /* THE PLAYBACK CEILING: twenty seconds after the last thing was handed to a player,
     playback counts as ended, so a synthesiser that never reports back cannot hold a
     conversation open for ever (voice.listen.js reads it too). */
  V.PLAYBACK_CEILING_MS = 20000;

  /* iOS gives an AudioContext no sound until a gesture resumes it, so both are unlocked
     inside the first press: the answer is audible on the first turn, not the second. */
  V.unlock = function () {
    if (out.ctx && out.ctx.state === "suspended") out.ctx.resume();
    if (mic.ctx && mic.ctx.state === "suspended") mic.ctx.resume();
  };

  /* iOS INTERRUPTS AUDIO CONTEXTS AND DOES NOT ASK (a call, Siri, another app taking the
     microphone). An interrupted or suspended context inside a live conversation is a
     pause, the same one a tap makes, and his tap resumes it from a gesture. Guarded on a
     live conversation: a suspended context before the first press is ordinary. */
  function watchContext(ctx) {
    if (!ctx || !ctx.addEventListener) return ctx;
    ctx.addEventListener("statechange", function () {
      var now = ctx.state;
      if (now !== "interrupted" && now !== "suspended") return;
      if (!state.conversation || state.paused) return;
      V.pauseVoice(now === "interrupted" ? "interrupted" : "suspended");
    });
    return ctx;
  }

  function playback() {
    if (out.ctx) return out.ctx;
    try { out.ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: FLAGS.ttsRate }); }
    catch (e) { out.ctx = new (window.AudioContext || window.webkitAudioContext)(); }
    watchContext(out.ctx);
    out.gain = out.ctx.createGain();
    out.gain.connect(out.ctx.destination);
    out.at = out.ctx.currentTime;
    return out.ctx;
  }

  V.enqueue = function (pcm) {
    var ctx = playback();
    var n = pcm.byteLength / 2;
    if (!n) return;
    var view = new DataView(pcm);
    var buf = ctx.createBuffer(1, n, FLAGS.ttsRate);
    var ch = buf.getChannelData(0);
    for (var i = 0; i < n; i++) ch[i] = view.getInt16(i * 2, true) / 32768;
    var src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(out.gain);
    var start = Math.max(ctx.currentTime + 0.02, out.at);
    src.start(start);
    out.at = start + buf.duration;
    out.lastAt = now();
    out.sources.push(src);
    src.onended = function () {
      var k = out.sources.indexOf(src);
      if (k >= 0) out.sources.splice(k, 1);
    };
  };

  /* THE CUT: a 30 ms gain ramp to zero, then stop the sources (a bare stop clicks). A cut
     also ends the page's own utterances, and `cancel()` does not reliably report each one
     back, so the count is dropped here rather than waited for. */
  V.cutAudio = function () {
    if (out.ctx) {
      var t = out.ctx.currentTime;
      try {
        out.gain.gain.cancelScheduledValues(t);
        out.gain.gain.setValueAtTime(out.gain.gain.value, t);
        out.gain.gain.linearRampToValueAtTime(0.0001, t + 0.03);
      } catch (e) { /* a context that has gone away cannot click */ }
      setTimeout(function () {
        out.sources.forEach(function (s) { try { s.stop(); } catch (e) {} });
        out.sources = [];
        if (out.ctx) {
          out.at = out.ctx.currentTime;
          try { out.gain.gain.setValueAtTime(1, out.ctx.currentTime); } catch (e) {}
        }
      }, 40);
    }
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    speech.out = 0;
  };

  /* THE FLOOR OF THE CHAIN SPEAKS HERE. Since V13 there is one voice, and the gateway sends
     `voice_speaker`'s answer rather than a role, so the second-voice branch below can only
     fire for a gateway older than that. Kept, because the page is correct against both
     halves of a rolling deploy. */
  var HOUSE_VOICE_HINTS = ["veena", "rishi", "lekha", "en-in", "en_in", "india"];
  function houseVoice() {
    var all = [];
    try { all = window.speechSynthesis.getVoices() || []; } catch (e) { all = []; }
    if (all.length < 2) return null;
    var mine = all.filter(function (v) { return v["default"]; })[0] || all[0], i, h, name;
    for (i = 0; i < all.length; i++) {
      if (all[i] === mine) continue;
      name = (all[i].name + " " + (all[i].lang || "")).toLowerCase();
      for (h = 0; h < HOUSE_VOICE_HINTS.length; h++) {
        if (name.indexOf(HOUSE_VOICE_HINTS[h]) >= 0) return all[i];
      }
    }
    for (i = 0; i < all.length; i++) { if (all[i] !== mine) return all[i]; }
    return null;
  }

  /* THE SEQUENCING POINT (V8): the gateway's tone is audio and the words are the page's
     own synthesiser, two players that would start together, so the words wait until the
     queued audio ends. Counted from the moment they are asked for, with the ceiling as a
     backstop, so `whenPlaybackEnds` never re-arms over the page's own words. */
  function speakHere(text, speaker, generation) {
    var say = String(text || ""), voice = null;
    if (speaker === "house") {
      voice = houseVoice();
      if (!voice) say = "House: " + say;
    }
    var u = new SpeechSynthesisUtterance(say);
    if (voice) u.voice = voice;
    var wait = 0;
    if (out.ctx && out.at > out.ctx.currentTime) {
      wait = Math.ceil((out.at - out.ctx.currentTime) * 1000);
    }
    function sayIt() {
      speech.out += 1;
      out.lastAt = now();
      var over = false;
      function done() {
        if (over) return;
        over = true;
        speech.out = Math.max(0, speech.out - 1);
      }
      u.onend = done;
      u.onerror = done;
      setTimeout(done, V.PLAYBACK_CEILING_MS);
      window.speechSynthesis.speak(u);
    }
    out.lastAt = now();
    if (!wait) { sayIt(); return; }
    speech.out += 1;
    setTimeout(function () {
      speech.out = Math.max(0, speech.out - 1);
      if (generation && generation !== state.generation) return;
      sayIt();
    }, wait);
  }
  V.speakHere = speakHere;

  /* Every player the page has, asked on one loop: the scheduled samples, the page's own
     utterances, and the synthesiser's own word for itself. */
  function playbackBusy() {
    try {
      if (out.ctx && out.at > out.ctx.currentTime + 0.01) return true;
    } catch (e) { /* a context that has gone away has nothing left to play */ }
    if (speech.out > 0) return true;
    try {
      if (window.speechSynthesis &&
          (window.speechSynthesis.speaking || window.speechSynthesis.pending)) return true;
    } catch (e) { /* a browser with no synthesiser is never speaking */ }
    return false;
  }
  V.playbackBusy = playbackBusy;

  function resample(input, from, to) {
    if (from === to) return input;
    var ratio = from / to;
    var n = Math.floor(input.length / ratio);
    var o = new Float32Array(n);
    for (var i = 0; i < n; i++) {
      var x = i * ratio, j = Math.floor(x), f = x - j;
      o[i] = (input[j] || 0) * (1 - f) + (input[j + 1] || 0) * f;
    }
    return o;
  }

  function toPCM16(floats) {
    var b = new ArrayBuffer(floats.length * 2), v = new DataView(b);
    for (var i = 0; i < floats.length; i++) {
      var s = Math.max(-1, Math.min(1, floats[i]));
      v.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }
    return b;
  }

  /* The level of one frame, for the waveform: the frame's RMS, eased by the wave itself. */
  function levelOf(floats) {
    var sum = 0;
    for (var i = 0; i < floats.length; i++) sum += floats[i] * floats[i];
    return floats.length ? Math.min(1, Math.sqrt(sum / floats.length) * 4) : 0;
  }

  V.openMic = function () {
    if (mic.node) return Promise.resolve(true);
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      return Promise.reject(new Error("this browser will not give a microphone"));
    }
    var Ctx = window.AudioContext || window.webkitAudioContext;
    try { mic.ctx = new Ctx({ sampleRate: FLAGS.micRate }); }
    catch (e) { mic.ctx = new Ctx(); }
    watchContext(mic.ctx);
    mic.rate = mic.ctx.sampleRate;
    return navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
    }).then(function (stream) {
      mic.stream = stream;
      return mic.ctx.audioWorklet.addModule(
        URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" })));
    }).then(function () {
      var src = mic.ctx.createMediaStreamSource(mic.stream);
      mic.node = new AudioWorkletNode(mic.ctx, "cap");
      mic.node.port.onmessage = function (ev) {
        if (!state.holding || !state.connected) return;
        /* EVERY FRAME COUNTS, INCLUDING A FRAME OF SILENCE: the watchdog watches the PIPE,
           not the speech, so it is told before the send. */
        V.onFrame();
        V.micLevel = levelOf(ev.data);
        var f = resample(ev.data, mic.rate, FLAGS.micRate);
        V.ws.send(toPCM16(f));
      };
      src.connect(mic.node);
      /* A zero gain rather than the destination: some browsers stop pulling a worklet
         that goes nowhere, and the speaker would play his own voice back at him. */
      var mute = mic.ctx.createGain();
      mute.gain.value = 0;
      mic.node.connect(mute).connect(mic.ctx.destination);
      return true;
    }).then(function (ok) {
      if (mic.ctx && mic.ctx.state === "suspended") mic.ctx.resume();
      return ok;
    });
  };

  /* CLOSED, NOT MUTED (V3). Pause means the microphone is really shut: every track stopped,
     the worklet disconnected, the capture context closed and the record dropped, so the
     phone's own recording indicator goes off. The PLAYBACK context is never closed here:
     iOS would need a new gesture before the next answer could be heard. Between the turns
     of a live conversation this is not called; the page simply stops sending. */
  function closeMic() {
    try {
      if (mic.node) { mic.node.port.onmessage = null; mic.node.disconnect(); }
      if (mic.stream) {
        mic.stream.getTracks().forEach(function (tr) { try { tr.stop(); } catch (e) {} });
      }
      if (mic.ctx && mic.ctx.state !== "closed") { mic.ctx.close(); }
    } catch (e) { /* a microphone that has already gone away is already closed */ }
    mic = { ctx: null, node: null, stream: null, rate: FLAGS.micRate };
    V.micLevel = 0;
  }
  V.closeMic = closeMic;

  V.micOpen = function () { return !!mic.node; };
  /* One message from the worklet, exactly as the real one arrives (the test door). */
  V.fakeFrame = function () {
    if (!mic.node || !mic.node.port || !mic.node.port.onmessage) return false;
    mic.node.port.onmessage({ data: new Float32Array(128) });
    return true;
  };

  V.watchContext = watchContext;
})();
