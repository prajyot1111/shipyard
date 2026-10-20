// keel-browser-steps.js - what a `keel-browser video` steps file may say, and the timeline it
// becomes. Pure: no browser, no page, so tests/test_browser.py can hold it with a bare node.
//
// A STEPS FILE IS A SCENE, NOT A SCRIPT.
//
//   {
//     "viewport": { "width": 1920, "height": 1080 },   the clip's size, in CSS pixels
//     "scale": 2,                                         the stills' device pixel ratio
//     "names": { "approve": "button.approve" },          elements the scene NAMES
//     "steps": [ { "do": "click", "target": "approve", "label": "approve it" }, ... ]
//   }
//
// The verbs a scene needs and no more: click, type, scroll, wait, eval, goto for a scene that
// moves between pages by address, and hold (press a target for `ms`, then let go), which is
// hold-to-talk. `mic` names a WAV the page hears as its microphone (Chromium's fake capture
// device, so a spoken line is a real voice turn and not a typed one); a 16-bit PCM file,
// relative to the steps file. `css` is a stylesheet on every page of the clip from before its
// first paint (an init script), for what a recording must never show even for a frame. A target is a name from `names` or a
// Playwright selector. Every step may carry a `label` (the still's file name and the
// timeline's key) and a `pause` in ms, held after the action so the clip shows its effect.
//
// THE TIMELINE IS WHY THIS EXISTS. The edit (c-568's Remotion slice) zooms onto a finding,
// flies a card from one screen to the next, and ripples out from an Approve. Each of those has
// to land on the element the step touched, not on a pixel somebody guessed from a frame, so
// after every step the engine measures every named element's box and writes it here, beside
// the time the step began and ended in the clip.

const VERBS = ["click", "type", "scroll", "wait", "eval", "goto", "hold"];
const MAX_STEPS = 200;

function fail(msg) {
  const e = new Error(msg);
  e.steps = true;
  throw e;
}

function isObject(v) {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

function positiveInt(v, what) {
  if (!Number.isInteger(v) || v <= 0) fail(`${what} must be a whole number above 0, got ${JSON.stringify(v)}`);
  return v;
}

// Parse and check the whole file BEFORE a browser starts, so a typo in step 14 costs a line
// of stderr rather than a minute of recording thrown away.
function parse(text, dflt) {
  let doc;
  try { doc = JSON.parse(text); } catch (e) { fail("the steps file is not JSON: " + e.message); }
  if (!isObject(doc)) fail("the steps file must be an object with a steps list");
  const vp = doc.viewport || {};
  if (!isObject(vp)) fail("viewport must be an object with width and height");
  const viewport = {
    width: positiveInt(vp.width ?? dflt.width, "viewport.width"),
    height: positiveInt(vp.height ?? dflt.height, "viewport.height"),
  };
  const scale = doc.scale ?? 2;
  if (typeof scale !== "number" || scale < 1 || scale > 3) fail(`scale must be between 1 and 3, got ${JSON.stringify(scale)}`);
  const names = doc.names ?? {};
  if (!isObject(names)) fail("names must be an object of name to selector");
  for (const [k, v] of Object.entries(names)) {
    if (!/^[a-z0-9][a-z0-9_-]*$/.test(k)) fail(`name ${JSON.stringify(k)}: use lowercase letters, digits, - and _`);
    if (typeof v !== "string" || !v) fail(`name ${k}: its selector must be a non-empty string`);
  }
  if (!Array.isArray(doc.steps) || doc.steps.length === 0) fail("steps must be a non-empty list");
  if (doc.steps.length > MAX_STEPS) fail(`at most ${MAX_STEPS} steps in one clip, got ${doc.steps.length}`);
  if (doc.mic !== undefined && (typeof doc.mic !== "string" || !/\.wav$/i.test(doc.mic))) fail("mic must name a .wav file");
  if (doc.css !== undefined && (typeof doc.css !== "string" || !doc.css.trim())) fail("css must be a non-empty stylesheet");
  const labels = new Set();
  const steps = doc.steps.map((s, i) => step(s, i, names, labels));
  return { viewport, scale, names, steps, mic: doc.mic || "", css: doc.css || "", scene: typeof doc.scene === "string" ? doc.scene : "" };
}

function step(s, i, names, labels) {
  const at = `step ${i + 1}`;
  if (!isObject(s)) fail(`${at}: must be an object`);
  if (!VERBS.includes(s.do)) fail(`${at}: "do" must be one of ${VERBS.join(", ")}, got ${JSON.stringify(s.do)}`);
  const label = s.label ?? `${s.do}`;
  if (typeof label !== "string" || !/^[a-z0-9][a-z0-9 _-]*$/i.test(label)) fail(`${at}: label ${JSON.stringify(label)}: letters, digits, spaces, - and _`);
  const key = `${String(i + 1).padStart(2, "0")}-${label.toLowerCase().replace(/[ _]+/g, "-")}`;
  if (labels.has(key)) fail(`${at}: label ${label} repeats`);
  labels.add(key);
  const pause = s.pause ?? 400;
  if (!Number.isInteger(pause) || pause < 0 || pause > 60000) fail(`${at}: pause must be 0 to 60000 ms`);
  const out = { do: s.do, key, label, pause };
  const target = () => {
    if (typeof s.target !== "string" || !s.target) fail(`${at}: ${s.do} needs a target (a name or a selector)`);
    out.target = s.target;
    out.selector = names[s.target] ?? s.target;
  };
  if (s.do === "click") target();
  if (s.do === "hold") {
    target();
    out.ms = positiveInt(s.ms, `${at}: hold needs ms`);
  }
  if (s.do === "type") {
    target();
    if (typeof s.text !== "string") fail(`${at}: type needs text`);
    out.text = s.text;
    out.delay = s.delay ?? 45;              // a hand's typing speed, so the clip reads as typing
    out.enter = s.enter === true;
  }
  if (s.do === "scroll") {
    if (s.target !== undefined) target();
    else if (!Number.isInteger(s.y)) fail(`${at}: scroll needs a target to bring into view, or y in pixels`);
    else out.y = s.y;
  }
  if (s.do === "wait") {
    const kinds = ["ms", "for", "target"].filter((k) => s[k] !== undefined);
    if (kinds.length !== 1) fail(`${at}: wait takes exactly one of ms, for (a JS expression) or target`);
    if (s.ms !== undefined) out.ms = positiveInt(s.ms, `${at}: ms`);
    if (s.for !== undefined) {
      if (typeof s.for !== "string" || !s.for) fail(`${at}: for must be a JS expression`);
      out.for = s.for;
    }
    if (s.target !== undefined) target();
    out.timeout = s.timeout ?? 30000;
  }
  if (s.do === "eval") {
    if (typeof s.js !== "string" || !s.js) fail(`${at}: eval needs js`);
    out.js = s.js;
  }
  if (s.do === "goto") {
    if (typeof s.url !== "string" || !s.url) fail(`${at}: goto needs a url`);
    out.url = s.url;
  }
  out.still = s.still !== false;
  return out;
}

// A box, rounded to whole CSS pixels: the edit scales it by the still's scale itself.
function box(b) {
  if (!b) return null;
  return { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) };
}

function seconds(ms) {
  return Math.round(ms) / 1000;
}

// The timeline file. `t0` is the moment the page (and so the clip) began; every time in the
// file is seconds from there, which is the clip's own clock.
function timeline(plan, meta, rows) {
  return {
    version: 1,
    scene: plan.scene,
    url: meta.url,
    video: meta.video,
    viewport: plan.viewport,
    scale: plan.scale,
    names: plan.names,
    duration: seconds(meta.end - meta.t0),
    t0_epoch: seconds(meta.t0),       // wall clock at the clip's 0, to line up other logs (Harbor's)
    steps: rows.map((r) => ({
      i: r.i,
      key: r.step.key,
      do: r.step.do,
      label: r.step.label,
      target: r.step.target ?? null,
      start: seconds(r.start - meta.t0),
      end: seconds(r.end - meta.t0),
      target_box: box(r.targetBox),
      still: r.still ?? null,
      boxes: Object.fromEntries(Object.entries(r.boxes || {}).map(([k, b]) => [k, box(b)])),
      text: r.text ?? "",
      ...(r.value !== undefined ? { value: r.value } : {}),
    })),
  };
}

module.exports = { parse, timeline, box, VERBS, MAX_STEPS };

// Run directly, it checks a steps file and prints what it would do: `node keel-browser-steps.js
// <steps.json>`. The tests use it, and so can anyone writing a scene.
if (require.main === module) {
  const fs = require("fs");
  try {
    const plan = parse(fs.readFileSync(process.argv[2], "utf8"), { width: 1600, height: 1000 });
    process.stdout.write(JSON.stringify(plan) + "\n");
  } catch (e) {
    process.stderr.write("keel-browser: " + e.message + "\n");
    process.exit(2);
  }
}
