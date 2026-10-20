/* Voice, the sheet: what is answering, recording, the judges, everything said, and what a
   locked phone does. Opened from the header's ⋯ (and from REC, which explains itself here).

   The copy says what is true of the product today (bug 8): the old "reads and never acts"
   was written before Harbor could file and move cards. */
(function () {
  "use strict";
  var V = window.Voice, state = V.state, esc = V.esc;

  function rows(list) {
    return "<dl>" + list.map(function (r) {
      return "<div class=\"v-srow\"><dt>" + esc(r[0]) + "</dt><dd>" + (r[2] ? r[1] : esc(String(r[1]))) + "</dd></div>";
    }).join("") + "</dl>";
  }

  /* THE JUDGES (V10): each key's switch and where its value came from, and the classifier. */
  function judgeRows(j) {
    if (!j) return [["judges", "this gateway is older than the judges"]];
    var keys = j.keys || {}, jev = j.jev || {}, out = [];
    Object.keys(keys).forEach(function (name) {
      var e = keys[name], said = e.mode + " (" + e.from + ")";
      if (e.floor !== null && e.floor !== undefined) said += ", floor " + e.floor;
      if (e.held) said += ", held: no floor";
      out.push([name, said]);
    });
    out.push(["classifier", jev.ready ? jev.model + ", key set, " + jev.retention
                                      : "not reachable: " + (jev.why || "unknown")]);
    if (jev.calls) {
      var missed = 0;
      Object.keys(jev.misses || {}).forEach(function (k) { missed += jev.misses[k]; });
      out.push(["calls", jev.calls + " asked, " + missed + " missed"]);
    }
    return out;
  }

  function voiceRows(h) {
    var info = V.engineInfo(state.engine);
    var engine = info ? info.label + (info.note ? ", " + info.note : "") : (h.tts && h.tts.backend) || "";
    var switcher = V.ENGINES.length > 1
      ? ' <button class="v-link" type="button" id="engineswitch">Switch</button>' : "";
    var rec = h.record || {};
    var recLine = rec.recording
      ? "on, " + rec.count + " takes, " + rec.megabytes + " MB, kept " + rec.keepDays +
        " days. Turn it off with [voice] record = false"
      : "off";
    return [
      ["speaking voice", esc(engine) + switcher, true],
      ["the chain", (h.tts && (h.tts.chain || []).join(", then ")) || (h.tts && h.tts.backend) || ""],
      ["hearing", h.stt && h.stt.ready ? h.stt.backend : "not ready: " + ((h.stt && h.stt.why) || "")],
      ["end of sentence", h.vad && h.vad.ready ? h.vad.backend + ", " + h.vad.hangoverSeconds + "s hangover"
                                               : "no detector, so no Conversation"],
      ["recording", recLine]
    ];
  }

  function history() {
    if (!state.turns.length) return "<p>Nothing yet.</p>";
    return state.turns.slice().reverse().map(function (t) {
      var w = V.answerWords(t) || { text: "still working" };
      return '<div class="v-sturn"><div class="v-said">' + esc(t.said) +
        (t.typed ? '<span class="v-mark mono">typed</span>' : "") + "</div>" +
        '<div class="v-sanswer' + (w.redirect ? " v-redirect" : "") + '">' +
        esc(w.text || (t.card ? "Captured " + t.card : "")) + "</div>" +
        '<div class="v-prov mono">' + esc(t.prov || "") + "</div></div>";
    }).join("");
  }

  function paint(h) {
    var body = V.$("sheetbody");
    if (!body) return;
    body.innerHTML = h
      ? "<h2>Speech</h2>" + rows(voiceRows(h)) +
        "<h2>Harbor</h2>" + rows([
          ["what it can do", "Answer, file captures, and move cards the way the phone talker does. Approving a gate stays a tap on the deck."],
          ["state it reads", h.snapshot && h.snapshot.healthy ? h.snapshot.ageSeconds + "s old"
                                                               : "stale: " + ((h.snapshot && h.snapshot.error) || "")],
          ["up", Math.round(h.upSeconds / 60) + " min"]]) +
        "<h2>Judges</h2>" + rows(judgeRows(h.judges)) +
        "<h2>Everything said</h2>" + history() +
        "<h2>Locked phone</h2><p class=\"v-snote\">Locking the phone pauses a conversation and closes the microphone. An answer you were not there to hear goes to your inbox as a card.</p>"
      : "<h2>Voice</h2>" + rows([["gateway", "not answering"]]) + "<h2>Everything said</h2>" + history();
    var sw = V.$("engineswitch");
    if (sw) sw.onclick = function () { V.cycleEngine(); paint(state.health); };
  }

  V.openSheet = function () {
    var sheet = V.$("sheet");
    paint(state.health);
    fetch("/voice/health", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (h) { state.health = h; paint(h); V.render(); })
      .catch(function () { paint(null); });
    if (sheet && sheet.showModal && !sheet.open) sheet.showModal();
  };
})();
