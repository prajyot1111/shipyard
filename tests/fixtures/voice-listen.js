/* The voice page's listen watchdog, driven outside a browser (V13, the page half).
 *
 * On 2026-09-21 the orb read "listening" for 62 seconds in conversation mode while not one
 * audio frame reached the gateway. Nothing the page could see had failed: `openMic`
 * resolved and `state.holding` was true, so the only untrue thing was the word on the orb.
 * The repair is a watchdog on the frames themselves, an honest label, and a `trace` the
 * gateway logs, and all three are made of timers, socket messages and a microphone.
 *
 * That is the one shape a browser cannot be asked about from the outside: a screenshot
 * cannot prove that three seconds of silence re-pressed the orb once and only once. So the
 * page is loaded here with a stand-in DOM, a stand-in socket and a CLOCK THE TEST OWNS, in
 * the idiom of `board-fit.js` and `board-zoom.js`, and driven through the door the page
 * opens for `?selftest=1` (`window.__voiceTest`).
 *
 * Nothing here is a mock of the page's own logic: the real `app.js` runs, and what is
 * replaced is only what a browser would have supplied. The assertions are made against
 * what the page SENT over the socket and what it wrote on the orb, which are the two
 * things the gateway and his eyes actually see.
 *
 * Usage: node voice-listen.js <the page's scripts, in index.html's order>
 *
 * The page is several files sharing `window.Voice` (VP-6); they are run as one text, in
 * the order the browser loads them, exactly as the browser would run them.
 * Output: {"ok": true}, or a JSON object naming every check that failed.
 */
'use strict';
const fs = require('fs');

const SOURCE = process.argv.slice(2).map((f) => fs.readFileSync(f, 'utf8')).join('\n;\n');
const fails = [];
function check(name, ok) { if (!ok) fails.push(name); }
const flush = () => new Promise((r) => setImmediate(r));

/* ------------------------------------------------------------------ the page */

function load(opts) {
  opts = opts || {};
  const page = { micWorks: opts.micWorks !== false, sent: [], tracksStopped: 0,
                intervals: new Set() };

  /* THE CLOCK THE TEST OWNS. Three seconds of watchdog and twenty of playback ceiling are
     not three and twenty seconds of a test run, and a real timer would make this suite
     both slow and flaky. */
  const clock = { t: 0, seq: 0, jobs: [] };
  clock.set = (fn, ms) => {
    const id = ++clock.seq;
    clock.jobs.push({ id, at: clock.t + (ms || 0), fn });
    return id;
  };
  clock.clear = (id) => { clock.jobs = clock.jobs.filter((j) => j.id !== id); };
  clock.advance = async function (ms) {
    const until = clock.t + ms;
    for (;;) {
      clock.jobs.sort((a, b) => (a.at - b.at) || (a.id - b.id));
      const job = clock.jobs[0];
      if (!job || job.at > until) break;
      clock.jobs.shift();
      clock.t = job.at;
      job.fn();
      await flush();
    }
    clock.t = until;
    await flush();
  };
  page.clock = clock;

  /* ------------------------------------------------------------ the document */

  const nodes = {};
  function node(id) {
    if (nodes[id]) return nodes[id];
    nodes[id] = {
      id, textContent: '', innerHTML: '', className: '', hidden: false, disabled: false,
      dataset: {}, style: {}, scrollTop: 0, scrollHeight: 0, attrs: {}, on: {}, onclick: null,
      setAttribute(k, v) { this.attrs[k] = v; },
      querySelector() { return null; }, focus() {}, blur() {}, value: '',
      removeAttribute(k) { delete this.attrs[k]; },
      getAttribute(k) { return this.attrs[k]; },
      addEventListener(ev, fn) { this.on[ev] = fn; },
      querySelectorAll() { return []; },
      appendChild() {}, insertAdjacentHTML() {}, insertBefore() {}, remove() {},
      showModal() {}, close() {}
    };
    return nodes[id];
  }
  page.node = node;
  const body = node('body');
  const doc = {
    body, hidden: false, listeners: {},
    getElementById: node,
    createElement: () => node('made-' + (++clock.seq)),
    querySelector: () => null,
    addEventListener(ev, fn) { this.listeners[ev] = fn; }
  };

  /* --------------------------------------------------------------- the audio */

  function gain() {
    return {
      gain: {
        value: 1, cancelScheduledValues() {}, setValueAtTime() {},
        linearRampToValueAtTime() {}
      },
      connect: (x) => x
    };
  }
  function Ctx(o) {
    this.state = 'running';
    this.sampleRate = (o && o.sampleRate) || 16000;
    this.currentTime = 0;
    this.destination = {};
    this.audioWorklet = { addModule: () => Promise.resolve() };
    this.addEventListener = () => {};
    this.createGain = gain;
    this.createBuffer = (ch, n, rate) => ({
      duration: n / rate, getChannelData: () => new Float32Array(n)
    });
    this.createBufferSource = () => ({
      buffer: null, onended: null, connect: () => {}, start: () => {}, stop: () => {}
    });
    this.createMediaStreamSource = () => ({ connect: () => {} });
    this.resume = () => { this.state = 'running'; };
    this.close = () => { this.state = 'closed'; };
  }
  function Worklet() {
    this.port = { onmessage: null, postMessage() {} };
    this.connect = (x) => x;
    this.disconnect = () => {};
  }
  /* A SYNTHESISER THAT NEVER REPORTS BACK, which is the case the ceiling exists for: it
     says it is speaking from the first `speak()` and never fires `onend`. */
  const speechSynthesis = {
    speaking: false, pending: false,
    said: [], live: [],
    speak(u) { this.speaking = true; this.said.push(u.text); this.live.push(u); },
    cancel() { this.speaking = false; this.live = []; },
    getVoices() { return []; }
  };
  page.speech = speechSynthesis;
  /* A synthesiser that DOES report back, which is the other half of the ceiling: the
     page must not wait twenty seconds for an utterance that has plainly finished. */
  page.speechEnds = () => {
    speechSynthesis.speaking = false;
    const said = speechSynthesis.live.splice(0);
    said.forEach((u) => { if (u.onend) u.onend(); });
  };

  function Utterance(text) { this.text = text; this.onend = null; this.onerror = null; }

  /* -------------------------------------------------------------- the socket */

  function Socket() {
    this.readyState = 1;
    this.binaryType = '';
    this.onopen = null; this.onclose = null; this.onmessage = null;
    this.send = (payload) => {
      if (typeof payload === 'string') page.sent.push(JSON.parse(payload));
      else page.sent.push({ type: 'audio', bytes: payload.byteLength });
    };
    page.sock = this;
  }

  const health = {
    stt: { ready: true, backend: 'parakeet' }, tts: { backend: 'google' },
    vad: { ready: opts.vad !== false, backend: 'silero' },
    snapshot: { healthy: true, ageSeconds: 1 }, upSeconds: 10, judges: null
  };
  const bus = { state: 'idle', samples: [], alert: false, turn: {}, connected: null };
  page.bus = bus;
  /* A BOARD THE DECK SERVES (VP-5): /api/board/<id> answers its record and its lines. */
  page.boardLines = ['board "How the merge queue lands a card"', 'node approve user "Approve outcome"'];
  page.fetched = [];
  function fetchStub(url) {
    const u = String(url);
    page.fetched.push(u);
    const body = u.indexOf('/api/board/') >= 0
      ? { id: 'b-014', title: 'How the merge queue lands a card', nodes: 9, lines: page.boardLines }
      : u.indexOf('health') >= 0 ? health : bus;
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  }

  /* ----------------------------------------------------------------- the page */

  const store = {};
  const win = {
    VOICE_FLAGS: {
      whereVoiceLives: 'own_app', showTier: 'every_answer',
      pressWhileSpeaking: 'cut_and_listen', alertAtRest: 'static_bar',
      transcriptKeep: 40, busSamples: 64, micRate: 16000, ttsRate: 24000,
      modeDefault: 'talk', captureDefaultSpace: 'personal',
      engineDefault: 'google', engines: [],
      endPhrases: ["that's all"], pausePhrases: ['hold on'], quietLimit: 3
    },
    speechSynthesis,
    /* THE DECK'S OWN EMBED, as ui.planblocks.js hangs it on `window.Keel`: recorded, so the
       check can see the page hand it the board rather than draw one itself. */
    Keel: opts.keel ? opts.keel : undefined,
    AudioContext: Ctx,
    performance: { now: () => clock.t },
    listeners: {},
    addEventListener(ev, fn) { this.listeners[ev] = fn; },
    removeEventListener(ev, fn) { if (this.listeners[ev] === fn) delete this.listeners[ev]; }
  };
  page.win = win;
  page.doc = doc;

  new Function(
    'window', 'document', 'location', 'localStorage', 'navigator', 'history',
    'fetch', 'WebSocket', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval',
    'AudioWorkletNode', 'SpeechSynthesisUtterance', 'Notification', 'URL', 'Blob',
    SOURCE
  )(
    win, doc,
    { protocol: 'http:', host: 'keel.test', search: '?selftest=1&mode=talk',
      pathname: '/segments/voice/app/' },
    {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); }
    },
    {
      mediaDevices: {
        getUserMedia: () => (page.micWorks
          ? Promise.resolve({
              getTracks: () => [{ stop: () => { page.tracksStopped += 1; } }]
            })
          : Promise.reject(new Error('NotAllowedError')))
      }
    },
    { replaceState() {} },
    fetchStub, Socket, clock.set, clock.clear,
    /* INTERVALS ARE COUNTED, so a timer the page starts and never clears shows (bug 10). */
    (fn, ms) => { const id = clock.set(fn, ms); page.intervals.add(id); return id; },
    (id) => { page.intervals.delete(id); clock.clear(id); },
    Worklet, Utterance, undefined,
    { createObjectURL: () => 'blob:worklet' },
    function BlobStub() {}
  );

  page.api = () => win.__voiceTest;
  page.traces = () => page.sent.filter((m) => m.type === 'trace');
  page.events = () => page.traces().map((m) => m.event);
  page.starts = () => page.sent.filter((m) => m.type === 'start');
  page.since = (n) => page.sent.slice(n);
  return page;
}

/* A loaded page with its socket open, its health read, and nothing said yet. */
async function open(opts) {
  const page = load(opts);
  await flush();
  page.sock.onopen();
  await page.clock.advance(1);
  page.sent.length = 0;
  return page;
}

/* The conversation, opened by a tap on the control, up to and including the first press. */
async function converse(page) {
  page.api().converse('test', { preventDefault() {} });
  await page.clock.advance(1);
  return page;
}

const TAP = { preventDefault() {} };

/* ---------------------------------------------------------------- the checks */

async function main() {
  /* 1. THE DOOR IS SHUT UNLESS IT IS ASKED FOR. */
  {
    const page = load({});
    await flush();
    check('the self test door opens for ?selftest=1', !!page.api());
  }

  /* 2. THREE SECONDS OF A LISTEN WITH NO FRAMES RE-PRESSES, ONCE. */
  const watchdog = await open({});
  {
    const page = watchdog;
    await converse(page);
    const first = page.starts();
    check('opening a conversation starts a listen', first.length === 1);
    check('the first listen is hands free', first[0] && first[0].handsFree === true);
    check('the orb is not claiming to listen before the first frame',
          page.api().label() === 'Opening the microphone');
    check('the microphone is open as far as the page can tell', page.api().micOpen());

    const before = page.sent.length;
    await page.clock.advance(2900);
    check('nothing is repaired before three seconds',
          page.since(before).every((m) => m.type !== 'start'));

    await page.clock.advance(200);
    const after = page.since(before);
    const events = after.filter((m) => m.type === 'trace').map((m) => m.event);
    check('a silent listen traces the repress', events.indexOf('repress') === 0);
    check('the repress is followed by a press', events.indexOf('press') > 0);
    check('the listen that heard nothing is cut, never flushed',
          after.some((m) => m.type === 'cut') && after.every((m) => m.type !== 'end'));
    const starts = after.filter((m) => m.type === 'start');
    check('the repress opens a new listen', starts.length === 1);
    check('and it is the next listen number',
          starts[0] && starts[0].listen === first[0].listen + 1);
    check('the repress really tore the microphone down first', page.tracksStopped >= 1);
    check('the repress press says why it pressed',
          after.some((m) => m.type === 'trace' && m.event === 'press' &&
                            m.reason === 'repress'));
  }

  /* 3. A SECOND SILENT THREE SECONDS STOPS CLAIMING TO LISTEN, AND HIS TAP REOPENS IT. */
  {
    const page = watchdog;
    const before = page.sent.length;
    await page.clock.advance(3100);
    const after = page.since(before);
    check('the second failure traces the stall',
          after.some((m) => m.type === 'trace' && m.event === 'stalled'));
    check('and it does not press a third time',
          after.every((m) => m.type !== 'start'));
    check('the orb says the microphone stalled',
          page.api().label() === 'Microphone stalled, tap to reopen');
    check('the page has stopped claiming to hold', page.api().state.holding === false);
    check('the microphone is really closed', page.api().micOpen() === false);
    check('the gateway is told the microphone is shut',
          after.some((m) => m.type === 'pause' && m.why === 'stalled'));
    check('the conversation is left open for one tap',
          page.api().state.conversation === true);

    const beforeTap = page.sent.length;
    page.api().tap(TAP);
    await page.clock.advance(1);
    const tapped = page.since(beforeTap);
    check('his tap opens a listen from the gesture itself',
          tapped.filter((m) => m.type === 'start').length === 1);
    check('and it says so in the trace',
          tapped.some((m) => m.type === 'trace' && m.event === 'press' &&
                             m.reason === 'tap-after-stall'));
    check('the microphone is asked for again', page.api().micOpen());
    check('the orb is honest while it opens',
          page.api().label() === 'Opening the microphone');

    const beforeFrames = page.sent.length;
    page.api().frame();
    page.api().frame();
    page.api().frame();
    await flush();
    const framed = page.since(beforeFrames);
    check('the orb says listening once audio is flowing',
          page.api().label() === 'Listening, tap to pause');
    check('the frames trace is sent once per listen',
          framed.filter((m) => m.type === 'trace' && m.event === 'frames').length === 1);
    check('and the audio itself still goes up',
          framed.filter((m) => m.type === 'audio').length === 3);

    /* A LISTEN WITH AUDIO IN IT IS NEVER REPAIRED, however long he talks for: the
       watchdog is about the pipe, and a pipe that is moving frames is working. */
    const beforeMore = page.sent.length;
    for (let i = 0; i < 6; i++) {
      await page.clock.advance(2000);
      page.api().frame();
      await flush();
    }
    check('a listen that keeps sending frames is never repaired',
          page.since(beforeMore).every((m) => m.type !== 'start'));

    /* AND A PIPE THAT DIES IN THE MIDDLE IS THE SAME FAILURE as one that never started:
       the phone handing the microphone to another app says the same untrue word on the
       orb as a microphone that never opened. */
    const beforeGap = page.sent.length;
    await page.clock.advance(3100);
    const gap = page.since(beforeGap);
    check('frames that stop in the middle of a listen are repaired too',
          gap.some((m) => m.type === 'trace' && m.event === 'repress') &&
          gap.filter((m) => m.type === 'start').length === 1);
  }

  /* 4. A MICROPHONE THAT WILL NOT OPEN WITHOUT A GESTURE STALLS RATHER THAN ENDING IT. */
  {
    const page = await open({});
    await converse(page);
    page.api().event({ type: 'endpoint', listen: page.api().state.listen,
                       reason: 'hangover' });
    await page.clock.advance(1);
    /* THE REAL SHAPE OF THE 62 SECONDS: the stream is still there as far as the page can
       see (`openMic` returns early while `mic.node` exists, which is the whole reason the
       repress tears it down), so the listen opens, no frames come, the repress asks the
       platform again, and the platform refuses because there is no gesture behind it. */
    page.micWorks = false;
    const before = page.sent.length;
    page.api().event({ type: 'listen', reason: 'conversation' });
    await page.clock.advance(4000);
    const after = page.since(before);
    check('a listen with no frames behind it is repressed',
          after.some((m) => m.type === 'trace' && m.event === 'repress'));
    check('a refused automatic open says stalled rather than ending the conversation',
          after.some((m) => m.type === 'trace' && m.event === 'stalled'));
    check('and the conversation is kept for his tap',
          page.api().state.conversation === true);
    check('and the orb asks for the tap',
          page.api().label() === 'Microphone stalled, tap to reopen');

    /* AND HIS TAP IS ALLOWED TO FAIL HONESTLY: a platform that refuses a real gesture has
       refused the only thing there was left to try, so that ends the conversation. */
    const beforeTap = page.sent.length;
    page.api().tap(TAP);
    await page.clock.advance(10);
    check('a refused tap ends the conversation rather than asking for ever',
          page.api().state.conversation === false);
    check('and it says so', /conversation ended/.test(page.api().status()) ||
                            page.api().label() === 'Hold to talk');
    check('and nothing was armed after it',
          page.since(beforeTap).every((m) => m.type !== 'listen'));
  }

  /* 5. `listen-now` PRESSES INSIDE A CONVERSATION AND NOWHERE ELSE. */
  {
    const page = await open({});
    page.api().event({ type: 'listen-now', reason: 'connected', generation: 0 });
    await page.clock.advance(1);
    check('listen-now outside a conversation opens nothing',
          page.starts().length === 0 && page.api().state.holding === false);

    await converse(page);
    page.api().event({ type: 'endpoint', listen: page.api().state.listen,
                       reason: 'hangover' });
    await page.clock.advance(1);
    check('the endpoint released the listen', page.api().state.holding === false);

    let before = page.sent.length;
    page.api().event({ type: 'listen-now', reason: 'connected', generation: 0 });
    await page.clock.advance(1);
    let after = page.since(before);
    check('listen-now inside a conversation presses the orb',
          after.filter((m) => m.type === 'start').length === 1);
    check('the press names listen-now as its reason',
          after.some((m) => m.type === 'trace' && m.event === 'press' &&
                            m.reason === 'listen-now'));
    check('and the press is the automatic one',
          after.some((m) => m.type === 'start' && m.handsFree === true));

    before = page.sent.length;
    page.api().event({ type: 'listen-now', reason: 'connected', generation: 0 });
    await page.clock.advance(1);
    check('a second listen-now over a live hold does nothing',
          page.since(before).every((m) => m.type !== 'start'));

    page.api().tap(TAP);                 /* a tap in a conversation is the pause */
    await page.clock.advance(1);
    check('the tap paused it', page.api().state.paused === true);
    before = page.sent.length;
    page.api().event({ type: 'listen-now', reason: 'connected', generation: 0 });
    await page.clock.advance(1);
    check('listen-now may not reopen a microphone he paused',
          page.since(before).every((m) => m.type !== 'start'));
  }

  /* 6. THE TRACE IS A STORY, IN ORDER, AND EVERY LINE OF IT HAS THE SAME SHAPE. */
  {
    const page = await open({});
    await converse(page);
    page.api().frame();
    await flush();
    page.api().event({ type: 'endpoint', listen: page.api().state.listen,
                       reason: 'hangover' });
    await page.clock.advance(1);
    page.api().event({ type: 'listen', reason: 'conversation' });
    await page.clock.advance(600);
    const events = page.events();
    check('the trace tells the whole listen in order',
          JSON.stringify(events) ===
          JSON.stringify(['press', 'frames', 'release', 'arm', 'playback-end', 'press']));
    const shape = page.traces().every((m) =>
      typeof m.event === 'string' && typeof m.reason === 'string' &&
      typeof m.listen === 'string' && typeof m.at === 'number' &&
      Object.keys(m).sort().join(',') === 'at,event,listen,reason,type');
    check('every trace carries the event, the reason, the listen and the clock', shape);
    check('the trace names the listen it is about',
          page.traces().every((m) => m.listen !== ''));
    const quiet = page.sent.length;
    page.api().event({ type: 'endpoint', listen: page.api().state.listen,
                       reason: 'quiet' });
    await flush();
    check('a quiet endpoint is traced as well',
          page.since(quiet).some((m) => m.type === 'trace' && m.event === 'quiet'));
  }

  /* 7. PLAYBACK THAT NEVER REPORTS ITS END IS CAPPED, AND THE CAP SAYS SO. */
  {
    const page = await open({});
    await converse(page);
    page.api().frame();
    await flush();
    page.api().event({ type: 'endpoint', listen: page.api().state.listen,
                       reason: 'hangover' });
    await page.clock.advance(1);
    /* The floor of the chain: the page says it with the browser's own synthesiser, and
       this one never fires `onend`. */
    page.api().event({ type: 'speak', engine: 'browser', text: 'a long answer',
                       generation: 1 });
    await flush();
    check('the page really spoke it', page.speech.said.length === 1);
    const before = page.sent.length;
    const at = page.clock.t;
    page.api().event({ type: 'listen', reason: 'conversation' });
    await page.clock.advance(19000);
    check('the microphone does not open over the words',
          page.since(before).every((m) => m.type !== 'start'));
    await page.clock.advance(1600);
    const after = page.since(before);
    const ceiling = after.filter((m) => m.type === 'trace' && m.event === 'playback-end');
    check('playback is treated as ended at the ceiling',
          ceiling.length === 1 && ceiling[0].reason === 'ceiling');
    check('and the ceiling is twenty seconds from the last chunk',
          ceiling[0] && ceiling[0].at - at > 19000 && ceiling[0].at - at < 21000);
    check('and the listen opens after it',
          after.filter((m) => m.type === 'start').length === 1);
  }

  /* 8. PLAYBACK THAT DOES END RESOLVES ON ITS OWN, AND ONLY ONCE IT HAS. */
  {
    const page = await open({});
    await converse(page);
    page.api().event({ type: 'endpoint', listen: page.api().state.listen,
                       reason: 'hangover' });
    await page.clock.advance(1);
    page.api().event({ type: 'speak', engine: 'browser', text: 'short', generation: 1 });
    await flush();
    const before = page.sent.length;
    page.api().event({ type: 'listen', reason: 'conversation' });
    await page.clock.advance(400);
    check('nothing opens while the synthesiser is still speaking',
          page.since(before).every((m) => m.type !== 'start'));
    /* The utterance reports back, which is what a working synthesiser does. */
    page.speechEnds();
    const at = page.clock.t;
    await page.clock.advance(500);
    const after = page.since(before);
    const ends = after.filter((m) => m.type === 'trace' && m.event === 'playback-end');
    check('a synthesiser that finishes is noticed without waiting for the ceiling',
          ends.length === 1 && ends[0].reason === 'ended');
    check('and it is noticed within a poll and the re-arm guard',
          ends[0] && ends[0].at - at < 400);
    check('and the listen opens once', after.filter((m) => m.type === 'start').length === 1);
  }


  /* 9. A FINGER ON THE ORB IS NEVER CUT FOR TALKING LONG (c-424). The twenty second
     backstop was armed by every press, so a long sentence held under his finger was
     released at twenty seconds. A real press has no cap while the finger is down; only a
     stuck pointer (a lost `pointerup`) is ended, and only after 180 seconds. */
  {
    const page = await open({});
    page.api().tap(TAP);
    await page.clock.advance(1);
    check('a finger press starts a push to talk listen',
          page.starts().length === 1 && page.starts()[0].handsFree === false);
    const before = page.sent.length;
    await page.clock.advance(25000);
    check('a finger held for 25 seconds is not released',
          page.api().state.holding === true &&
          page.since(before).every((m) => m.type !== 'end'));
    await page.clock.advance(150000);
    check('nor at almost three minutes', page.api().state.holding === true);
    await page.clock.advance(6000);
    const after = page.since(before);
    check('a pointer stuck down for 180 seconds is released',
          page.api().state.holding === false);
    check('and what it heard is dropped with `cut`, never flushed with `end` (a lost '
          + 'release must not send the room)',
          after.some((m) => m.type === 'cut') && after.every((m) => m.type !== 'end'));
    check('and the trace says it was the stuck-pointer guard',
          after.some((m) => m.type === 'trace' && m.event === 'release' &&
                            m.reason === 'failsafe-stuck'));

    /* A real release still ends it at once, whatever the guard. */
    page.api().tap(TAP);
    await page.clock.advance(3000);
    const beforeLift = page.sent.length;
    page.api().lift(TAP);
    await flush();
    check('lifting the finger ends the listen at once',
          page.since(beforeLift).some((m) => m.type === 'end'));
  }

  /* 10. AN AUTOMATIC LISTEN WITH NO DETECTOR KEEPS ITS TWENTY SECONDS: nothing else would
     ever end it, and there is no finger to lift. */
  {
    const page = await open({ vad: false });
    await converse(page);
    check('with no detector the conversation is one automatic listen',
          page.starts().length === 1 && page.starts()[0].handsFree === true);
    const before = page.sent.length;
    /* Frames keep flowing, so the listen watchdog has nothing to repair and the only
       thing that can end this listen is the backstop. */
    for (let i = 0; i < 19; i++) {
      page.api().frame();
      await page.clock.advance(1000);
    }
    check('the automatic listen is still open at 19 seconds',
          page.api().state.holding === true);
    page.api().frame();
    await page.clock.advance(1500);
    const after = page.since(before);
    check('and it is released at twenty seconds',
          page.api().state.holding === false && after.some((m) => m.type === 'end'));
    check('by the automatic backstop, and it says so',
          after.some((m) => m.type === 'trace' && m.event === 'release' &&
                            m.reason === 'failsafe-auto'));
  }


  /* 11. THE PAGE SAYS WHETHER IT CAN BE SEEN, ALWAYS (c-438). It used to say it hid only
     during a conversation or a hold, so a phone pocketed after a push to talk kept its
     socket and read as "he is listening". Presence is a fact the page reports; it is
     not a command, so it carries nothing but the one boolean. */
  {
    const page = load({});
    await flush();
    page.sock.onopen();
    await page.clock.advance(1);
    const opened = page.sent.filter((m) => m.type === 'presence');
    check('the page says it is visible when its socket opens',
          opened.length === 1 && opened[0].visible === true);
    check('and the message is the boolean and nothing else',
          opened[0] && Object.keys(opened[0]).sort().join(',') === 'type,visible');

    const before = page.sent.length;
    page.doc.hidden = true;
    page.doc.listeners.visibilitychange();
    await flush();
    let after = page.since(before);
    check('hiding outside a conversation or a hold is reported',
          after.some((m) => m.type === 'presence' && m.visible === false));
    check('and it starts nothing', after.every((m) => m.type !== 'start'));

    const back = page.sent.length;
    page.doc.hidden = false;
    page.doc.listeners.visibilitychange();
    await flush();
    after = page.since(back);
    check('coming back is reported too',
          after.some((m) => m.type === 'presence' && m.visible === true));
    check('and coming back opens no microphone', after.every((m) => m.type !== 'start'));

    const gone = page.sent.length;
    page.win.listeners.pagehide();
    await flush();
    check('pagehide reports the page hidden',
          page.since(gone).some((m) => m.type === 'presence' && m.visible === false));
  }


  /* 12. A RELEASE THAT GOES MISSING SENDS NO ROOM AUDIO (lane D review, item 3). Space held
     and the window losing focus, or the orb losing its pointer capture, would otherwise
     never see a keyup or a pointerup, and the listen would run on until the stuck guard. */
  {
    const page = await open({});
    const key = { code: 'Space', repeat: false, target: { tagName: 'DIV' },
                  preventDefault() {} };
    page.doc.listeners.keydown(key);
    await page.clock.advance(1);
    check('Space starts a push to talk', page.api().state.holding === true);
    const before = page.sent.length;
    page.win.listeners.blur();
    await flush();
    const after = page.since(before);
    check('the window losing focus releases the hold', page.api().state.holding === false);
    check('and drops the listen with cut, never end',
          after.some((m) => m.type === 'cut') && after.every((m) => m.type !== 'end'));
    check('and the trace says the release was lost',
          after.some((m) => m.type === 'trace' && m.event === 'release' &&
                            m.reason === 'lost-blur'));

    /* ROUND 2, ITEM D: the real order is pointerdown, then pointercancel (an edge swipe,
       a call, the system taking the touch). Neither that nor pointerleave is him letting
       go, so neither may dispatch half a sentence. */
    const ctl = page.node('control');
    for (const lost of ['pointercancel', 'pointerleave']) {
      ctl.on.pointerdown({ preventDefault() {} });
      await page.clock.advance(1);
      check(`a pointerdown holds before ${lost}`, page.api().state.holding === true);
      const mark = page.sent.length;
      ctl.on[lost]({ preventDefault() {} });
      await flush();
      const gone = page.since(mark);
      check(`${lost} during a hold drops the listen with cut, never end`,
            page.api().state.holding === false && gone.some((m) => m.type === 'cut') &&
            gone.every((m) => m.type !== 'end'));
    }
    const up = page.sent.length;
    ctl.on.pointerdown({ preventDefault() {} });
    await page.clock.advance(1);
    ctl.on.pointerup({ preventDefault() {} });
    await flush();
    check('a real pointerup still sends the sentence with end',
          page.since(up).some((m) => m.type === 'end'));
  }


  /* 13. PUSH TO TALK IS WHERE THE PAGE RESTS (VP-2), AND THE COMPOSER IS A CHAT (VP-1). */
  {
    const page = await open({});
    const api = page.api();
    check('the page rests in talk, whatever the gateway\'s old mode default says',
          api.state.mode === 'talk');
    check('the bar\'s resting word is push to talk', api.label() === 'Hold to talk');
    check('the page opens on the composer, not the bar', api.face() === 'type');
    check('no conversation is open until he asks for one', api.state.conversation === false);

    /* A typed line is a `text` message with the mode it was typed in, and nothing else. */
    api.type('what is waiting on me');
    const before = page.sent.length;
    api.send();
    await flush();
    const sent = page.since(before);
    const text = sent.filter((m) => m.type === 'text');
    check('typing sends one text line', text.length === 1 && text[0].text === 'what is waiting on me');
    check('a typed line is sent in talk', text[0] && text[0].mode === 'talk');
    check('and it never asks to be heard', text[0] && !text[0].aloud);
    check('and typing opens no microphone', sent.every((m) => m.type !== 'start'));
    check('the field is cleared once it is sent', page.node('field').value === '');

    /* The gateway marks it typed, and the page keeps the mark on the turn. */
    api.event({ type: 'transcript', text: 'what is waiting on me', mode: 'talk', generation: 1,
                repairs: [], typed: true });
    const row = api.state.turns[api.state.turns.length - 1];
    check('a typed turn is marked typed in the transcript', row && row.typed === true);

    /* The mic in the composer is a hold, and its release may land anywhere. */
    const mark = page.sent.length;
    api.mic({ preventDefault() {} });
    await page.clock.advance(1);
    check('the composer mic starts a push to talk hold', api.state.holding === true &&
          page.since(mark).some((m) => m.type === 'start' && m.handsFree === false));
    check('and the composer becomes the voice bar', api.face() === 'voice');
    check('a hold says it is opening, never "Start a conversation" (bug 4)',
          api.label() === 'Opening the microphone');
    api.frame();
    await flush();
    check('with audio behind it the bar says what letting go does',
          api.label() === 'Release to send');
    const up = page.sent.length;
    page.win.listeners.pointerup({ preventDefault() {} });
    await flush();
    const ended = page.since(up).filter((m) => m.type === 'end');
    check('lifting the finger anywhere sends the sentence', ended.length === 1);
    check('and it is sent in talk', ended[0] && ended[0].mode === 'talk');
    check('the bar stays after a spoken turn', api.face() === 'voice');
    page.node('kbd').on.click();
    check('the keyboard button returns to typing', api.face() === 'type');
  }

  /* 14. CAPTURE NEXT IS ONE HOLD, ARMED FROM THE + MENU (VP-2). */
  {
    const page = await open({});
    const api = page.api();
    page.node('mcapture').on.click();
    check('Capture next arms a capture', api.state.mode === 'capture');
    check('and the bar says where it will be filed', api.label() === 'Hold to capture to personal');
    const ctl = page.node('control');
    ctl.on.pointerdown({ preventDefault() {} });
    await page.clock.advance(1);
    const mark = page.sent.length;
    ctl.on.pointerup({ preventDefault() {} });
    await flush();
    const end = page.since(mark).filter((m) => m.type === 'end')[0];
    check('the take is sent as a capture, to its space',
          end && end.mode === 'capture' && end.space === 'personal');
    check('and the next hold is talk again', api.state.mode === 'talk' && api.label() === 'Hold to talk');
    page.node('mspace').on.click();
    page.node('mcapture').on.click();
    check('the space follows the menu', api.label() === 'Hold to capture to work');
  }

  /* 15. CONVERSATION LIVES IN THE + MENU AND KEEPS ITS BEHAVIOUR. */
  {
    const page = await open({});
    const api = page.api();
    const mark = page.sent.length;
    page.node('mconv').on.click({ preventDefault() {} });
    await page.clock.advance(1);
    check('the menu opens a conversation', api.state.conversation === true);
    check('with a hands free listen', page.since(mark).some((m) => m.type === 'start' && m.handsFree === true));
    page.node('convpill').on.click();
    check('the Conversation pill ends it', api.state.conversation === false);
  }

  /* 16. THE PING TIMER IS ONE TIMER (bug 10): a socket that drops and opens again does not
     leave the last one running. */
  {
    const page = await open({});
    page.sock.onclose();
    await page.clock.advance(1);
    page.sock.onopen();
    await page.clock.advance(1);
    page.sock.onclose();
    await page.clock.advance(1);
    page.sock.onopen();
    await page.clock.advance(1);
    check('one ping timer after two reconnects', page.intervals.size === 1);
  }

  /* 17. A PAGE NOBODY CAN SEE DRAWS NOTHING, AND DRAWS ONCE WHEN IT IS SEEN (VP-7). */
  {
    const page = await open({});
    const api = page.api();
    page.doc.hidden = true;
    page.doc.listeners.visibilitychange();
    api.event({ type: 'connected', card: 'c-272', title: 'Event Replay', space: 'work' });
    check('a hidden page does not redraw', api.label() === 'Hold to talk');
    page.doc.hidden = false;
    page.doc.listeners.visibilitychange();
    check('and it catches up the moment it is seen', api.label() === 'Hold to talk to c-272');
  }

  /* 18. THE RECEIPT FOR A BOARD IS THE REAL BOARD, DRAWN BY THE DECK'S OWN EMBED (VP-5). */
  {
    const embedded = [];
    const keel = { planDiagram: {}, planBlocks: { block(b) { embedded.push(b); return page0node(); } } };
    let made = 0;
    function page0node() { made += 1; return { className: 'pblock', parentNode: null }; }
    const page = await open({ keel });
    const api = page.api();
    api.event({ type: 'transcript', text: 'walk me through the merge queue', mode: 'talk',
                generation: 3, repairs: [] });
    Object.assign(page.bus, { state: 'idle', turn: { id: 'b1', text: 'walk me through the merge queue',
      phase: 'done', tier: 'harbor', answer: 'I put the flow on a board.', boards: ['b-014'],
      provenance: 'Harbor, 9s', narration: [] } });
    await page.clock.advance(2100);
    const row = api.state.turns[api.state.turns.length - 1];
    check('the turn keeps the board it drew', row && row.boards && row.boards[0] === 'b-014');
    check('the page reads the board from the deck',
          page.fetched.some((u) => u.indexOf('/api/board/b-014') >= 0));
    check('and hands it to the deck\'s own board embed',
          embedded.length === 1 && embedded[0].type === 'board' && embedded[0].ref === 'b-014');
    check('with the board\'s own lines, not a copy of its shape',
          embedded[0] && embedded[0].ops === page.boardLines);
    await page.clock.advance(2100);
    check('and builds it once, however often the page renders', embedded.length === 1 && made === 1);
  }

  process.stdout.write(JSON.stringify(fails.length ? { ok: false, failed: fails }
                                                   : { ok: true }));
}

main().catch((err) => {
  process.stdout.write(JSON.stringify({ ok: false, failed: ['threw: ' + err.stack] }));
});
