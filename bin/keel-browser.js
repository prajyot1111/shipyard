// keel-browser.js - the engine behind bin/keel-browser.
//
// Driven by the wrapper, never run directly: NODE_PATH, PLAYWRIGHT_BROWSERS_PATH and the
// option environment come from there. Kept in its own file for the reason the tool it was
// ported from gives, which is that argument checking in bash and a browser session in node
// are two different jobs and reading them interleaved helps nobody.
//
// A PORT OF ~/harbor/bin/harbor-browser.js, WITH ONE DELIBERATE DIFFERENCE.
//
// Harbor launches `channel: "chrome"`: the Google Chrome installed on the Mac, which is why
// it needs no browser download and is 12MB. The box has no Chrome and no way to get one, so
// this launches Playwright's own Chromium out of the Keel-owned install instead, and the
// failure message points at `bin/keel-browser install` rather than at repairing Chrome.
// Everything else here is Harbor's, comments included: each one is a scar and the scar is
// the same on both machines.
//
// Everything below that looks like an odd choice is a scar. The comments say whose.

const fs = require("fs");
const path = require("path");
const os = require("os");
const { chromium } = require("playwright-core");
const steps = require(path.join(__dirname, "keel-browser-steps.js"));

const [, , cmd, url, extra, extra2] = process.argv;

const SETTLE = int(process.env.HB_SETTLE_MS, 3000);
const BUDGET = int(process.env.HB_TIMEOUT_S, 60) * 1000;
const SECONDS = int(process.env.HB_SECONDS, 30);
const FULL = process.env.HB_FULL_PAGE === "1";
const WIDTH = int(process.env.HB_WIDTH, 1600);
const HEIGHT = int(process.env.HB_HEIGHT, 1000);
// A CONDITION TO WAIT FOR, INSTEAD OF GUESSING HOW LONG TO SLEEP.
//
// `--settle` is a fixed pause, and a fixed pause is a bet on how busy the machine is. It
// lost: a render gate asked the dashboard what it had drawn 2500ms after domcontentloaded,
// and under load the page's own /api/state fetch had not landed yet. A dashboard that has
// not fetched anything is a complete, valid, EMPTY page, so the probe answered with
// well-formed JSON full of zeroes and every assertion failed for the wrong reason, a
// different set each run. Three of six gate runs went red that way.
//
// So a caller that knows what "ready" means for its page says so, and this WAITS for it
// rather than sleeping. Empty means the old behaviour, unchanged, which is what every
// other caller still gets.
const WAIT_FOR = process.env.HB_WAIT_FOR || "";

function int(v, dflt) {
  const n = parseInt(v || "", 10);
  return Number.isFinite(n) ? n : dflt;
}
// gaveUp: closing the browser to stop a leak makes whatever was in flight reject, so the
// ordinary error path fires straight after the watchdog and would report "page.waitForTimeout:
// target closed" with exit 3. That is the tool blaming the page for something the tool did.
// The watchdog has already said the true thing and the catch has already awaited the close,
// so the only job left is to exit with the code that means "gave up".
let gaveUp = false;
function die(code, msg) {
  if (gaveUp) process.exit(5);
  process.stderr.write("keel-browser: " + msg + "\n");
  process.exit(code);
}

// Every recovery path needs the same thing: get the browser down, but never wait forever
// for it. Review pointed out that the watchdog got a bounded backstop and the two catch
// blocks modelled on it did not, so in the drain-to-zero-handles case they described, the
// loop would empty with the close promise unsettled and node would exit 0 saying nothing.
// That is the "reports success" shape again, so the bound lives in one place and every
// path uses it.
async function closeBrowser() {
  if (!browser) return;
  await Promise.race([
    browser.close().catch(() => {}),
    new Promise((resolve) => setTimeout(resolve, 3000)),
  ]);
}

// A PIPE THAT CLOSES EARLY IS NOT AN EXCEPTION.
//
// `keel-browser dom <url> | head` is an ordinary thing to type, and head closing the pipe
// surfaces as an 'error' event on the stream rather than a throw. So neither the command
// try/catch nor the bottom .catch runs, the process dies on the spot, and the Chromium it
// launched keeps running: the exact leak this file spent two commits closing, on the one
// path that does not throw.
process.stdout.on("error", (e) => {
  if (!e || e.code !== "EPIPE") return;
  setTimeout(() => process.exit(0), 3000);
  const done = () => process.exit(0);
  if (browser) browser.close().then(done, done);
  else done();
});

// THE BUDGET LIVES IN THIS PROCESS, NOT IN A `timeout` IN FRONT OF IT.
//
// Both of the browser memories this was ported from record the same trap: the Mac has no
// `timeout` command, so `timeout 30 chrome ...` dies as command-not-found and the browser
// never runs at all. The empty output then reads as a broken page rather than a broken
// command line, which is the worst shape a measurement can take. A wrapper that needed an
// external timeout to be safe would have reintroduced it, so the clock is here. The wrapper
// still kills the process group a slack later, which covers what a timer inside this process
// cannot: node itself wedging.
//
// unref() so it never keeps an otherwise finished process alive.
//
// It also has to take the browser down with it. Raised in review: the first version called
// die() straight from the timer, and die() is a bare process.exit, so a run that hit its
// budget left a headless Chromium parented to nothing. On a schedule that is a slow leak of
// exactly the kind nobody notices until the machine is out of memory. The second timer is
// there because close() can itself hang, and a watchdog that can hang is not one.
let browser = null;
const watchdog = setTimeout(() => {
  gaveUp = true;
  process.stderr.write(
    `keel-browser: gave up after ${BUDGET / 1000}s on ${url}. Nothing was written. `
    + `Raise it with --timeout if the page is genuinely this slow.\n`);
  // NOT unref'd. Review caught this: an unref'd backstop cannot guarantee anything,
  // because if close() never settles and no other libuv handle remains, the loop simply
  // drains and node exits 0. A watchdog whose failure mode is "reports success" is the
  // thing this whole file is built to avoid.
  setTimeout(() => process.exit(5), 3000);
  const done = () => process.exit(5);
  if (browser) browser.close().then(done, done);
  else done();
}, BUDGET);
watchdog.unref();

// A video's steps are read and checked BEFORE the browser starts: a typo in step 14 is a
// line of stderr, not a minute of recording thrown away.
let plan = null;
if (cmd === "video") {
  try {
    plan = steps.parse(fs.readFileSync(extra, "utf8"), { width: WIDTH, height: HEIGHT });
  } catch (e) {
    die(2, (e.steps ? "" : "could not read the steps file: ") + firstLine(e));
  }
}

(async () => {
  try {
    // `channel: "chromium"` IS PLAYWRIGHT'S OWN CHROMIUM IN NEW HEADLESS MODE, and leaving
    // it out is not the same thing. Measured in the container on 1.63.0: a bare
    // `{ headless: true }` resolves to chromium-headless-shell, the OLD headless build, and
    // fails outright when the install skipped it ("Executable doesn't exist at
    // .../chrome-headless-shell"). Fetching the shell as well is 266 MB for a renderer that
    // is not the renderer, and the whole point of this tool is checking a CSS change against
    // what a real Chrome paints. So the install fetches Chromium alone and this names it.
    //
    // It is NOT `channel: "chrome"`, which is what harbor-browser uses: that is the Google
    // Chrome installed on the Mac, and the box has none. The build comes from
    // PLAYWRIGHT_BROWSERS_PATH, which the wrapper points at Keel's own install.
    //
    // Either way, no profile, no cookies, no saved session and no extension come with it.
    // That is the safety property, not a limitation: this can LOOK at a page and cannot BE
    // anyone on one, which is the right amount of power for an unattended tool.
    // A scene with a `mic` hears that WAV as its microphone, and is never asked for leave.
    const args = plan && plan.mic
      ? ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
         "--use-file-for-fake-audio-capture=" + path.resolve(path.dirname(extra), plan.mic)]
      : [];
    browser = await chromium.launch({ channel: "chromium", headless: true, args });
  } catch (e) {
    // Separated from every other failure because the fix is completely different: this one
    // is "install or repair the browser", not "look at your page".
    die(2, "could not launch chromium: " + firstLine(e)
         + "\n  The browser is Keel's own, under KEEL_BROWSER_HOME (~/.keel-browser)."
         + "\n  Check it with: bin/keel-browser check");
  }

  // Inside a try, and the reason is the one the watchdog fix was about. Review caught that
  // these two sat between the launch try and the goto try, owned by neither: a throw here
  // reached the bottom .catch, which calls die(), which is a bare process.exit, and the
  // browser launched one line above would have been left running. Every path that can
  // throw after a successful launch has to take the browser down with it.
  let context;
  let page;
  let t0 = 0;
  let videoDir = null;
  try {
    if (plan) {
      // The clip is recorded at the viewport's own size (Playwright's default shrinks it to
      // fit 800x800), and the page is painted at `scale` so every still is sharp enough for
      // the edit to push in on. The raw recording lands in a directory of our own and is
      // saved to the caller's path once the page closes.
      videoDir = fs.mkdtempSync(path.join(os.tmpdir(), "keel-browser-video-"));
      context = await browser.newContext({
        viewport: plan.viewport,
        deviceScaleFactor: plan.scale,
        recordVideo: { dir: videoDir, size: plan.viewport },
      });
    } else {
      context = await browser.newContext({ viewport: { width: WIDTH, height: HEIGHT } });
    }
    if (plan && plan.css) {
      // BEFORE THE FIRST PAINT, on every page the clip visits: a style added after load
      // leaves the frames between the paint and the step that added it in the clip.
      await context.addInitScript((css) => {
        const add = () => {
          const style = document.createElement("style");
          style.textContent = css;
          (document.head || document.documentElement).appendChild(style);
        };
        if (document.documentElement) add();
        else new MutationObserver((_, seen) => {
          if (document.documentElement) { seen.disconnect(); add(); }
        }).observe(document, { childList: true });
      }, plan.css);
    }
    page = await context.newPage();
    t0 = Date.now();                // the clip's own clock starts with its page
  } catch (e) {
    await closeBrowser();
    die(3, "could not open a page: " + firstLine(e));
  }

  // Kept and only reported on failure. A page that renders correctly while logging a
  // warning is not a finding, but a page that renders WRONG is usually explained by
  // something in here, and having to re-run to find out wastes the slow part.
  const consoleErrors = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text().slice(0, 300));
  });
  page.on("pageerror", (e) => consoleErrors.push(firstLine(e).slice(0, 300)));

  const requests = [];
  page.on("request", (r) => requests.push({ url: r.url(), type: r.resourceType() }));

  try {
    // domcontentloaded, NOT networkidle. A dev server's HMR socket, or a dashboard that
    // polls on a timer, never reaches networkidle, so waiting for it means waiting for the
    // whole budget and then failing on a page that was ready in a second.
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: Math.min(BUDGET, 30000) });
  } catch (e) {
    await closeBrowser();
    die(3, "could not load " + url + ": " + firstLine(e));
  }

  // WAITED FOR BEFORE THE SETTLE, AND ITS FAILURE HAS ITS OWN EXIT CODE.
  //
  // 6 rather than 3, because "the page never became ready" and "the page is wrong" want
  // opposite handling by the caller. A checker that cannot tell them apart has to treat a
  // slow machine as a broken page, which is the flake this exists to remove; one that can
  // is free to say `skip` and mean it. The settle still runs afterwards, so a caller can
  // wait for the data and then still give the paint a moment.
  if (WAIT_FOR) {
    try {
      await page.waitForFunction(WAIT_FOR, null,
                                 { timeout: Math.max(1000, BUDGET - 10000), polling: 100 });
    } catch (e) {
      const saw = consoleErrors.length
        ? "\n  " + consoleErrors.length + " console error(s), first: " + consoleErrors[0]
        : "";
      await closeBrowser();
      die(6, "the page never became ready on " + url
           + "\n  waited for: " + WAIT_FOR
           + "\n  Nothing was measured, so do not read this run as a verdict on the page."
           + saw);
    }
  }

  try {
    if (cmd === "requests") {
      // Sit and watch. The point of this command is what the page does OVER TIME, so the
      // settle is the measurement window rather than a pause before one.
      await page.waitForTimeout(SECONDS * 1000);
      report(requests, SECONDS);
    } else if (cmd === "shot") {
      await page.waitForTimeout(SETTLE);
      const out = path.resolve(extra);
      fs.mkdirSync(path.dirname(out), { recursive: true });
      await page.screenshot({ path: out, fullPage: FULL });

      // ASSERT THE FILE, DO NOT ASSUME IT.
      //
      // This check is the whole reason neither tool uses a browser bridge here. One such
      // bridge reported a successful screenshot while silently writing no file in headless
      // and background contexts, which is precisely the context these run in: tmux,
      // --permission-mode auto, on a schedule, inside a house. A capture tool whose failure
      // mode is a confident success message is worse than one that cannot capture at all.
      // Playwright writes in-process through fs, so this assertion should never fire. It is
      // here because "should never fire" is exactly what was believed last time.
      let size = 0;
      try { size = fs.statSync(out).size; } catch (e) { size = 0; }
      if (size === 0) {
        await closeBrowser();
        die(4, "screenshot reported success but wrote no file at " + out
             + "\n  Do not treat this run as evidence of anything.");
      }
      process.stdout.write(out + "\n");
      process.stderr.write(`  ${(size / 1024).toFixed(0)}KB, ${WIDTH}x${HEIGHT}`
                           + (FULL ? ", full page" : "") + "\n");
    } else if (cmd === "dom") {
      await page.waitForTimeout(SETTLE);
      process.stdout.write(await page.content());
    } else if (cmd === "video") {
      const failed = await record(page, context, t0);
      if (failed) {
        await closeBrowser();
        die(3, failed);
      }
    } else if (cmd === "eval") {
      await page.waitForTimeout(SETTLE);
      const value = await page.evaluate(extra);
      process.stdout.write(
        (typeof value === "string" ? value : JSON.stringify(value, null, 2)) + "\n");
    } else {
      await closeBrowser();
      die(1, "unknown command: " + cmd);
    }
  } catch (e) {
    await closeBrowser();
    die(3, cmd + " failed on " + url + ": " + firstLine(e));
  }

  if (consoleErrors.length) {
    process.stderr.write(`  ${consoleErrors.length} console error(s) on the page:\n`);
    for (const line of consoleErrors.slice(0, 5)) process.stderr.write("    " + line + "\n");
  }

  await closeBrowser();
  process.exit(0);
// The last net. Anything that throws outside the blocks above still must not exit while
// leaving a browser running, so the close happens here too rather than being assumed
// unreachable. It is two lines, and "unreachable" is what was believed about newContext.
})().catch(async (e) => {
  await closeBrowser();
  die(3, firstLine(e));
});

// PLAY THE SCENE, AND SAY WHERE EVERYTHING WAS.
//
// Returns an error line, or "" when the clip, the stills and the timeline are all written.
// A step that fails still leaves the timeline of the steps before it (with `failed` set), so
// a take that broke at step 9 says so in the file the take index points at, not only in a
// terminal nobody watched.
async function record(page, context, t0) {
  const out = path.resolve(extra2);
  const stem = out.replace(/\.webm$/, "");
  const stillsDir = stem + ".stills";
  const timelinePath = stem + ".timeline.json";
  fs.mkdirSync(stillsDir, { recursive: true });
  const rows = [];
  let failed = "";
  for (let i = 0; i < plan.steps.length && !failed; i++) {
    const s = plan.steps[i];
    const row = { i: i + 1, step: s, start: Date.now() };
    try {
      row.targetBox = await act(page, s, row);
      if (s.pause) await page.waitForTimeout(s.pause);
      row.end = Date.now();
      row.boxes = await measure(page);
      row.text = await page.evaluate(() => (document.body ? document.body.innerText : ""));
      if (s.still) {
        row.still = path.relative(path.dirname(timelinePath), path.join(stillsDir, s.key + ".png"));
        await page.screenshot({ path: path.join(stillsDir, s.key + ".png") });
      }
    } catch (e) {
      row.end = Date.now();
      failed = `step ${i + 1} (${s.label}) failed: ${firstLine(e)}`;
    }
    rows.push(row);
  }
  // Saved once the page closes, which is also what finishes the clip's last frames.
  const saved = page.video().saveAs(out);
  const end = Date.now();
  await context.close();
  await saved;
  fs.rmSync(path.dirname(await page.video().path()), { recursive: true, force: true });
  const doc = steps.timeline(plan, { url, video: path.basename(out), t0, end }, rows);
  if (failed) doc.failed = failed;
  fs.writeFileSync(timelinePath, JSON.stringify(doc, null, 2) + "\n");
  if (failed) return failed + "\n  the steps before it are in " + timelinePath;
  let size = 0;
  try { size = fs.statSync(out).size; } catch (e) { size = 0; }
  if (size === 0) return "the clip reported success but wrote no file at " + out;
  process.stdout.write(out + "\n" + stillsDir + "\n" + timelinePath + "\n");
  process.stderr.write(`  ${(size / 1024).toFixed(0)}KB, ${plan.steps.length} steps, `
                       + `${doc.duration}s, ${plan.viewport.width}x${plan.viewport.height} at ${plan.scale}x\n`);
  return "";
}

// One step. Returns the box of the element it acted on, measured just before it acted, which
// is where the edit draws the pointer.
async function act(page, s, row) {
  const el = s.selector ? page.locator(s.selector).first() : null;
  let at = null;
  if (el && s.do !== "wait") {
    await el.waitFor({ state: "visible", timeout: 15000 });
    if (s.do !== "scroll") await el.scrollIntoViewIfNeeded();
    at = await el.boundingBox();
  }
  if (s.do === "click") await el.click();
  else if (s.do === "hold") {
    // Pointer down on the target's middle, held, then up: what a thumb on a talk button does.
    await page.mouse.move(at.x + at.width / 2, at.y + at.height / 2);
    await page.mouse.down();
    await page.waitForTimeout(s.ms);
    await page.mouse.up();
  }
  else if (s.do === "type") {
    await el.click();
    await el.pressSequentially(s.text, { delay: s.delay });
    if (s.enter) await el.press("Enter");
  } else if (s.do === "scroll") {
    // Smooth, so the clip shows the page travel rather than a cut.
    if (el) await el.evaluate((n) => n.scrollIntoView({ behavior: "smooth", block: "center" }));
    else await page.evaluate((y) => window.scrollBy({ top: y, behavior: "smooth" }), s.y);
    await page.waitForTimeout(700);
    if (el) at = await el.boundingBox();
  } else if (s.do === "wait") {
    if (s.ms) await page.waitForTimeout(s.ms);
    else if (s.for) await page.waitForFunction(s.for, null, { timeout: s.timeout, polling: 100 });
    else await el.waitFor({ state: "visible", timeout: s.timeout });
  } else if (s.do === "eval") {
    const value = await page.evaluate(s.js);
    row.value = value === undefined ? null : value;
  } else if (s.do === "goto") {
    // Relative to the page it is on, so a scene names deck paths and not a port.
    await page.goto(new URL(s.url, page.url()).href, { waitUntil: "domcontentloaded", timeout: 30000 });
  }
  return at;
}

// Every element the scene names, where it is now; null for one not on the page.
async function measure(page) {
  const boxes = {};
  for (const [name, selector] of Object.entries(plan.names)) {
    const el = page.locator(selector).first();
    boxes[name] = (await el.count()) ? await el.boundingBox({ timeout: 1000 }).catch(() => null) : null;
  }
  return boxes;
}

// COUNTING REQUESTS IS THE POINT, AND IT NO LONGER NEEDS A PROXY.
//
// A polling surface's render guard is stated as a number: over six poll cycles the deck
// fetched one card's HTML 7 times before the fix and 1 after. Getting that number used to
// mean standing a logging proxy in front of the server and reading its log, which is a
// second moving part to build and to trust. The browser already knows, so this asks it.
function report(rows, seconds) {
  const byUrl = new Map();
  for (const r of rows) {
    const k = r.url.split("?")[0];
    const cur = byUrl.get(k) || { n: 0, type: r.resourceType || r.type };
    cur.n += 1;
    byUrl.set(k, cur);
  }
  const sorted = [...byUrl.entries()].sort((a, b) => b[1].n - a[1].n);
  process.stdout.write(`${rows.length} request(s) over ${seconds}s\n\n`);
  process.stdout.write("  " + "count".padEnd(6) + "type".padEnd(12) + "url\n");
  for (const [u, v] of sorted) {
    process.stdout.write("  " + String(v.n).padEnd(6) + String(v.type).padEnd(12)
                         + shorten(u) + "\n");
  }
  process.stdout.write(`\n  A polling surface should show ONE fetch for anything that did`
                       + ` not change.\n`);
}

function shorten(u) {
  try {
    const p = new URL(u);
    return p.pathname === "/" ? p.origin + "/" : p.pathname;
  } catch (e) { return u; }
}

function firstLine(e) {
  return String((e && e.message) || e).split("\n")[0];
}
