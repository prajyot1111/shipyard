/* Voice, the waveform: 32 bars in the voice bar, driven by real levels (VP-7).

   ALIVE, NOT BUSY (from the Jarvis study, decision VP-7). Each state has its own motion and
   the DIRECTION says who is talking: while he speaks the energy travels from both ends INTO
   the centre; while Harbor speaks it ripples from the centre OUTWARD. Idle breathes slowly,
   thinking is low bars with a highlight sweeping left to right. One eased energy per state,
   fast attack and slow release, so nothing jitters or cuts.

   THE LEVELS ARE REAL: his, from the worklet's own frames (`V.micLevel`); Harbor's, from the
   gateway's bus (`level`, else the RMS of `samples`), polled every 120 ms while it speaks.

   IT STOPS WHEN NOBODY CAN SEE IT (the loop is not scheduled while the page is hidden) and
   under reduced motion it draws each state's still shape once and does not animate. */
(function () {
  "use strict";
  var V = window.Voice, state = V.state;
  var BARS = 32, HALF = BARS / 2;
  var bars = [];
  var history = [];          // the last HALF levels, newest first
  var energy = 0;
  var frame = null;
  var idle = null;
  var last = 0;

  for (var i = 0; i < HALF; i++) history.push(0);

  function build() {
    var host = V.$("wave");
    if (!host || bars.length || !document.createElement) return;
    for (var k = 0; k < BARS; k++) {
      var b = document.createElement("span");
      b.className = "v-wbar";
      if (host.appendChild) host.appendChild(b);
      bars.push(b);
    }
  }

  function busLevel() {
    var bus = state.bus || {};
    if (typeof bus.level === "number" && bus.level > 0) return Math.min(1, bus.level);
    var s = bus.samples || [], sum = 0;
    for (var k = 0; k < s.length; k++) sum += s[k] * s[k];
    return s.length ? Math.min(1, Math.sqrt(sum / s.length) * 3) : 0;
  }

  /* Fast attack, slow release: 50 ms up, 350 ms down, and a little quicker while speaking. */
  function ease(target, dt, speaking) {
    var tau = target > energy ? 50 : (speaking ? 230 : 350);
    energy += (target - energy) * Math.min(1, dt / tau);
    return energy;
  }

  /* Bar i's height, 4 to 32px, for a face and a moment. */
  function heights(face, t) {
    var out = [], k;
    if (face === "listening" || face === "speaking") {
      for (k = 0; k < BARS; k++) {
        /* INWARD: the newest level sits at both ends. OUTWARD: at the centre. */
        var fromEdge = Math.min(k, BARS - 1 - k);
        var idx = face === "listening" ? fromEdge : (HALF - 1 - fromEdge);
        var lv = history[idx] || 0;
        out.push(4 + Math.round(lv * 28 * (0.7 + 0.3 * Math.sin(k * 1.7 + t / 180))));
      }
      return out;
    }
    if (face === "thinking") {
      var sweep = (t % 1600) / 1600 * BARS;
      for (k = 0; k < BARS; k++) {
        var near = Math.max(0, 1 - Math.abs(k - sweep) / 3);
        out.push(4 + Math.round(near * 8));
      }
      return out;
    }
    /* idle and connected idle: a slow breathe, 4 to 8px, three seconds a cycle */
    var breath = (Math.sin(t / 3000 * Math.PI * 2) + 1) / 2;
    for (k = 0; k < BARS; k++) out.push(4 + Math.round(breath * (k % 4 === 2 ? 4 : 2)));
    return out;
  }

  function faceOf(s) {
    if (s === "listening" || s === "opening") return "listening";
    if (s === "speaking") return "speaking";
    if (s === "thinking" || s === "partial") return "thinking";
    if (s === "paused" || s === "stalled" || s === "down") return "flat";
    return "idle";
  }

  function paint(face, t) {
    var h = face === "flat" ? null : heights(face, t);
    for (var k = 0; k < bars.length; k++) {
      var px = h ? h[k] : 2;
      var want = px + "px";
      if (bars[k].style && bars[k].style.height !== want) bars[k].style.height = want;
      if (face === "thinking" && h) V.klass(bars[k], "lit", h[k] > 6);
      else if (bars[k].className !== "v-wbar") bars[k].className = "v-wbar";
    }
  }

  function tick(t) {
    frame = null;
    if (V.hidden() || barHidden()) return;           /* renders nothing nobody can see */
    var s = V.displayState ? V.displayState() : "idle";
    var face = faceOf(s);
    var dt = last ? Math.min(100, t - last) : 16;
    last = t;
    var target = face === "listening" ? V.micLevel : face === "speaking" ? busLevel() : 0;
    history.unshift(ease(target, dt, face === "speaking"));
    history.length = HALF;
    paint(face, t);
    if (V.reducedMotion()) return;
    /* AT REST THE BREATH IS SLOW, so it is drawn a few times a second, not sixty. */
    if (face === "idle" || face === "flat") {
      idle = setTimeout(function () { idle = null; schedule(); }, 120);
    } else schedule();
  }

  function barHidden() {
    var bar = V.$("bar");
    return !!(bar && bar.hidden);
  }

  /* ONE FUTURE AT A TIME: the slow timer or the next frame, never both. */
  function schedule() {
    if (idle) { clearTimeout(idle); idle = null; }
    if (frame || !window.requestAnimationFrame) return;
    frame = window.requestAnimationFrame(tick);
  }

  /* Called by `render` on every change of state, and on becoming visible again. Under
     reduced motion it paints the still shape of the state and stops there. */
  V.wave = function () {
    build();
    if (!bars.length || V.hidden() || barHidden()) return;
    if (V.reducedMotion()) { paint(faceOf(V.displayState()), 0); return; }
    schedule();
  };
})();
