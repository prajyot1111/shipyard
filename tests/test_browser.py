"""`bin/keel-browser`: what a stdlib test can say truthfully about a browser tool.

It cannot launch a browser. The suite runs behind a fence with a throwaway `HOME`
(`tests/fence.py`), and a test that started a Chromium would be the one thing this tool
exists to prevent: an unattended process holding hundreds of megabytes on a machine whose
other job is voice latency. So the browser is a FAKE NODE on PATH, which is enough to hold
everything about the tool that is not the browser itself:

- the arguments, and that each flag reaches the engine as the variable it is supposed to;
- the exit codes, including the engine's own passed through unchanged and the two this
  wrapper owns, 7 for a missing install and 5 for the hard timeout;
- the hard timeout killing the GROUP, proven with a fake engine that ignores SIGTERM and
  has a child of its own: after the run, neither is alive.

Two rules are held by GREP, and a grep can be wrong in one direction only. It can prove the
teardown is WRITTEN on every exit path of `bin/keel-browser.js` (every `die(` that follows a
successful launch is preceded by an `await closeBrowser()`, the watchdog closes, the EPIPE
handler closes, the bottom catch closes). It cannot prove the teardown WORKS, that Playwright
honours the close, or that no path was added that the pattern does not recognise. The
container proof in the card's record is what says the browser really goes down; these say a
future edit cannot quietly delete the line that makes it. `tests/test_deck_css.py` is the
same shape, for the same reason.

The pinned Playwright version and the install directory exist in two files
(`bin/keel-browser`, `keel/browser.py`). The two drifting apart is two different browsers
on one host, so they are checked against each other here.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from keel import browser
from tests.helpers import ROOT

TOOL = ROOT / "bin" / "keel-browser"
ENGINE = ROOT / "bin" / "keel-browser.js"
STEPS = ROOT / "bin" / "keel-browser-steps.js"

# A node that is not node: it prints what the wrapper handed it and exits with a code the
# test asks for, so the wrapper's argument handling is readable as a single line of output.
# `-e` is answered without a word because that is the wrapper's cheap resolve check.
FAKE_NODE = """#!/bin/sh
if [ "$1" = "-e" ]; then exit 0; fi
shift
echo "cmd=$1 url=$2 extra=$3"
echo "extra2=$4"
echo "settle=$HB_SETTLE_MS timeout=$HB_TIMEOUT_S seconds=$HB_SECONDS full=$HB_FULL_PAGE"
echo "width=${HB_WIDTH:-unset} height=${HB_HEIGHT:-unset} wait=$HB_WAIT_FOR"
echo "modules=$NODE_PATH browsers=$PLAYWRIGHT_BROWSERS_PATH"
exit ${FAKE_NODE_EXIT:-0}
"""

# A node that will not die politely and has a child of its own, which is the shape the group
# kill exists for: signalling the leader alone leaves the child parented to init.
STUBBORN_NODE = """#!/bin/sh
if [ "$1" = "-e" ]; then exit 0; fi
trap '' TERM
sh -c 'while :; do sleep 1; done' &
echo "$!" > "$STUBBORN_CHILD_PID"
wait
"""


class ToolCase(unittest.TestCase):
    """A fake install and a fake node, both under a temporary directory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.home = self.dir / ".keel-browser"

    def install(self) -> None:
        """What `resolvable` looks for: the module directory and a chromium build."""
        (self.home / "node_modules" / "playwright-core").mkdir(parents=True)
        (self.home / "browsers" / "chromium-1234").mkdir(parents=True)

    def fake_node(self, body: str = FAKE_NODE) -> Path:
        path = self.bin / "node"
        path.write_text(body)
        path.chmod(0o755)
        return path

    def run_tool(self, *argv, exit_code=None, extra_env=None, timeout=60):
        env = dict(os.environ, KEEL_BROWSER_HOME=str(self.home),
                   PATH=os.pathsep.join([str(self.bin), os.environ.get("PATH", "")]))
        if exit_code is not None:
            env["FAKE_NODE_EXIT"] = str(exit_code)
        env.update(extra_env or {})
        return subprocess.run([str(TOOL), *argv], capture_output=True, text=True, env=env,
                              timeout=timeout)


class ArgumentsTest(ToolCase):
    def setUp(self):
        super().setUp()
        self.install()
        self.fake_node()

    def test_the_tool_is_executable_and_parses(self):
        self.assertTrue(os.access(TOOL, os.X_OK), f"{TOOL} is not executable")
        done = subprocess.run(["bash", "-n", str(TOOL)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)


    def test_every_option_reaches_the_engine_as_its_own_variable(self):
        done = self.run_tool("shot", "http://x.test/p", "/tmp/out.png", "--full-page",
                             "--settle", "250", "--timeout", "9", "--width", "390",
                             "--height", "844", "--wait-for", "window.ready === true")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("cmd=shot url=http://x.test/p extra=/tmp/out.png", done.stdout)
        self.assertIn("settle=250 timeout=9 seconds=30 full=1", done.stdout)
        self.assertIn("width=390 height=844 wait=window.ready === true", done.stdout)

    def test_the_engine_is_pointed_at_the_keel_owned_install(self):
        """Never a worktree and never `state/`: one place per machine, and the browser path
        goes with the modules, so a run cannot pick up someone else's chromium."""
        done = self.run_tool("dom", "http://x.test")
        self.assertIn(f"modules={self.home / 'node_modules'}", done.stdout)
        self.assertIn(f"browsers={self.home / 'browsers'}", done.stdout)

    def test_requests_takes_seconds_and_the_others_keep_the_default(self):
        done = self.run_tool("requests", "http://x.test", "--seconds", "12")
        self.assertIn("seconds=12", done.stdout)

    def test_a_missing_positional_is_reported_as_what_it_is(self):
        for argv, said in ((("shot",), "shot needs a url"),
                           (("shot", "http://x.test"), "shot needs an output path"),
                           (("eval", "http://x.test"), "eval needs an expression"),
                           (("dom",), "dom needs a url"),
                           (("video", "http://x.test"), "video needs a steps file"),
                           (("video", "http://x.test", "s.json"), "video needs a steps file")):
            with self.subTest(argv=argv):
                done = self.run_tool(*argv)
                self.assertEqual(done.returncode, 2)
                self.assertIn(said, done.stderr)

    def test_video_hands_the_engine_its_steps_and_its_clip_with_a_longer_budget(self):
        """A scene is minutes of steps, so a video's default budget is 600s, not a page
        load's 60; `--timeout` still overrides it."""
        steps = self.dir / "s.json"
        steps.write_text("{}")
        done = self.run_tool("video", "http://x.test", str(steps), "/tmp/c.webm")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"cmd=video url=http://x.test extra={steps}", done.stdout)
        self.assertIn("extra2=/tmp/c.webm", done.stdout)
        self.assertIn("timeout=600", done.stdout)
        done = self.run_tool("video", "http://x.test", str(steps), "/tmp/c.webm", "--timeout", "30")
        self.assertIn("timeout=30", done.stdout)

    def test_video_refuses_a_missing_steps_file_and_a_clip_that_is_not_webm(self):
        steps = self.dir / "s.json"
        done = self.run_tool("video", "http://x.test", str(steps), "/tmp/c.webm")
        self.assertEqual(done.returncode, 2)
        self.assertIn("no steps file at", done.stderr)
        steps.write_text("{}")
        done = self.run_tool("video", "http://x.test", str(steps), "/tmp/c.mp4")
        self.assertEqual(done.returncode, 2)
        self.assertIn("writes a .webm", done.stderr)
        self.assertEqual(done.stdout, "", "the engine ran anyway")

    def test_a_flag_where_the_output_path_belongs_is_not_taken_for_one(self):
        done = self.run_tool("shot", "http://x.test", "--full-page")
        self.assertEqual(done.returncode, 2)
        self.assertIn("got the flag --full-page", done.stderr)

    def test_an_unknown_command_and_an_unknown_option_both_exit_2(self):
        done = self.run_tool("screenshot", "http://x.test")
        self.assertEqual(done.returncode, 2)
        self.assertIn("unknown command: screenshot", done.stderr)
        done = self.run_tool("dom", "http://x.test", "--sideways")
        self.assertEqual(done.returncode, 2)
        self.assertIn("unknown option: --sideways", done.stderr)

    def test_a_measurement_that_is_not_a_number_is_refused_before_the_browser_starts(self):
        """Left as a string these reach the engine's parseInt and quietly become the
        default, so `--timeout abc` would look like it had been honoured."""
        for flag in ("--settle", "--timeout", "--seconds", "--width", "--height"):
            with self.subTest(flag=flag):
                done = self.run_tool("dom", "http://x.test", flag, "abc")
                self.assertEqual(done.returncode, 2)
                self.assertIn(f"{flag} must be a whole number, got 'abc'", done.stderr)
                self.assertEqual(done.stdout, "", "the engine ran anyway")

    def test_the_engines_own_exit_code_comes_back_unchanged(self):
        """6 is the one a caller reads: the page never became ready, which is a different
        answer from the page being wrong, and nothing here may flatten the two."""
        for code in (0, 1, 2, 3, 4, 5, 6):
            with self.subTest(code=code):
                done = self.run_tool("dom", "http://x.test", exit_code=code)
                self.assertEqual(done.returncode, code)


class MissingInstallTest(ToolCase):
    def test_a_missing_install_names_the_command_and_exits_7(self):
        """Not a stack trace, and not exit 1: a house that gets MODULE_NOT_FOUND out of node
        goes and builds its own browser, which is what this whole tool replaces."""
        self.fake_node()
        done = self.run_tool("dom", "http://x.test")
        self.assertEqual(done.returncode, 7, done.stderr)
        self.assertIn(f"no browser install at {self.home}", done.stderr)
        self.assertIn(f"{TOOL} install", done.stderr)
        self.assertIn("keel-browser install", done.stderr)
        self.assertNotIn("MODULE_NOT_FOUND", done.stderr)

    def test_the_modules_without_a_chromium_build_is_still_a_missing_install(self):
        """Half an install is not an install: `install` downloads the browser separately
        from the npm package, so this is the state a killed install leaves behind."""
        self.fake_node()
        (self.home / "node_modules" / "playwright-core").mkdir(parents=True)
        done = self.run_tool("dom", "http://x.test")
        self.assertEqual(done.returncode, 7, done.stderr)

    def test_the_usage_error_comes_before_the_install_check(self):
        """A typo must say it is a typo even on a machine with no browser at all."""
        self.fake_node()
        done = self.run_tool("dom")
        self.assertEqual(done.returncode, 2)
        self.assertIn("needs a url", done.stderr)


# The watchdog's two waits, shortened: a slack of one second past the engine's own budget,
# and a fraction of a second between the TERM the fake ignores and the KILL. The default
# grace is five seconds, which was five of the seven each of these tests took.
QUICK_WATCHDOG = {"KEEL_BROWSER_HARD_SLACK_S": "1", "KEEL_BROWSER_HARD_GRACE_S": "0.3"}


class HardTimeoutTest(ToolCase):
    def test_the_hard_timeout_kills_the_group_and_leaves_no_child_behind(self):
        """The engine's watchdog is a timer inside node and cannot cover node itself being
        stuck. This fake ignores SIGTERM and has a child of its own, so signalling the
        leader alone would leave the child running: exactly the leak shape (57 Chrome
        processes, 17 of 18 GB of swap) the tool exists after.
        """
        self.install()
        self.fake_node(STUBBORN_NODE)
        pid_file = self.dir / "child.pid"
        done = self.run_tool("dom", "http://x.test", "--timeout", "1",
                             extra_env=dict(QUICK_WATCHDOG, STUBBORN_CHILD_PID=str(pid_file)))
        self.assertEqual(done.returncode, 5, done.stdout + done.stderr)
        self.assertIn("killed the browser's whole process group", done.stderr)
        self.assertIn("Nothing was measured", done.stderr)
        child = int(pid_file.read_text().strip())
        for _ in range(50):                       # the KILL is sent a moment after the TERM
            if not alive(child):
                break
            time.sleep(0.1)
        self.assertFalse(alive(child), f"pid {child} outlived the run it belonged to")

    def test_bash_does_not_narrate_its_own_job_bookkeeping(self):
        """`set -m` is what gives the engine its own process group, and it also makes bash
        announce a job that dies from a signal ("Killed: 9  env NODE_PATH=..."). That line
        is the shell talking about its own bookkeeping in the middle of a tool's output."""
        self.install()
        self.fake_node(STUBBORN_NODE)
        done = self.run_tool("dom", "http://x.test", "--timeout", "1",
                             extra_env=dict(QUICK_WATCHDOG,
                                            STUBBORN_CHILD_PID=str(self.dir / "child.pid")))
        self.assertNotIn("Killed", done.stderr)
        self.assertNotIn("Terminated", done.stderr)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is not on PATH")
class StepsTest(unittest.TestCase):
    """`bin/keel-browser-steps.js`, the half of `video` that needs no browser: what a steps
    file may say, checked before a browser starts, and the timeline a take becomes."""

    def check(self, doc) -> subprocess.CompletedProcess:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write(doc if isinstance(doc, str) else json.dumps(doc))
        self.addCleanup(os.unlink, f.name)
        return subprocess.run([NODE, str(STEPS), f.name], capture_output=True, text=True, timeout=30)

    def plan(self, doc) -> dict:
        done = self.check(doc)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_a_scene_resolves_its_names_and_keys_every_still(self):
        plan = self.plan({"viewport": {"width": 390, "height": 844},
                          "names": {"approve": "button.approve"},
                          "steps": [{"do": "click", "target": "approve", "label": "Approve it"},
                                    {"do": "type", "target": "#ask", "text": "why", "enter": True},
                                    {"do": "scroll", "y": 300},
                                    {"do": "wait", "for": "window.ready"},
                                    {"do": "eval", "js": "1", "still": False},
                                    {"do": "goto", "url": "http://x.test/plan"}]})
        self.assertEqual(plan["viewport"], {"width": 390, "height": 844})
        self.assertEqual(plan["scale"], 2)
        first, typed = plan["steps"][0], plan["steps"][1]
        self.assertEqual((first["key"], first["selector"], first["pause"]), ("01-approve-it", "button.approve", 400))
        self.assertEqual((typed["selector"], typed["enter"], typed["delay"]), ("#ask", True, 45))
        self.assertEqual([s["key"] for s in plan["steps"][2:]], ["03-scroll", "04-wait", "05-eval", "06-goto"])
        self.assertFalse(plan["steps"][4]["still"])

    def test_a_spoken_scene_names_its_mic_and_holds_to_talk(self):
        plan = self.plan({"mic": "line-1.wav", "steps": [{"do": "hold", "target": "#mic", "ms": 3800}]})
        self.assertEqual(plan["mic"], "line-1.wav")
        self.assertEqual((plan["steps"][0]["selector"], plan["steps"][0]["ms"]), ("#mic", 3800))
        for doc, said in (({"mic": "line.mp3", "steps": [{"do": "wait", "ms": 1}]}, "mic must name a .wav"),
                          ({"steps": [{"do": "hold", "target": "#mic"}]}, "hold needs ms")):
            with self.subTest(doc=doc):
                done = self.check(doc)
                self.assertEqual(done.returncode, 2, done.stdout)
                self.assertIn(said, done.stderr)

    def test_a_scene_may_carry_a_stylesheet_for_every_page(self):
        self.assertEqual(self.plan({"css": "x{display:none}", "steps": [{"do": "wait", "ms": 1}]})["css"], "x{display:none}")
        done = self.check({"css": "  ", "steps": [{"do": "wait", "ms": 1}]})
        self.assertEqual(done.returncode, 2)
        self.assertIn("css must be a non-empty stylesheet", done.stderr)

    def test_the_default_viewport_is_the_one_the_command_line_gave(self):
        self.assertEqual(self.plan({"steps": [{"do": "wait", "ms": 10}]})["viewport"],
                         {"width": 1600, "height": 1000})

    def test_a_bad_step_is_named_by_its_number_before_any_browser(self):
        for doc, said in (("not json", "not JSON"),
                          ({"steps": []}, "non-empty list"),
                          ({"steps": [{"do": "hover", "target": "#a"}]}, 'step 1: "do" must be one of'),
                          ({"steps": [{"do": "wait", "ms": 5}, {"do": "click"}]}, "step 2: click needs a target"),
                          ({"steps": [{"do": "type", "target": "#a"}]}, "type needs text"),
                          ({"steps": [{"do": "wait", "ms": 5, "for": "x"}]}, "exactly one of"),
                          ({"steps": [{"do": "scroll"}]}, "scroll needs a target"),
                          ({"steps": [{"do": "wait", "ms": 1, "label": "a"},
                                      {"do": "wait", "ms": 1, "label": "a"}]}, None),
                          ({"steps": [{"do": "wait", "ms": 1, "label": "a/b"}]}, "label"),
                          ({"scale": 4, "steps": [{"do": "wait", "ms": 1}]}, "scale must be between 1 and 3"),
                          ({"names": {"Bad Name": "#a"}, "steps": [{"do": "wait", "ms": 1}]}, "name \"Bad Name\"")):
            with self.subTest(doc=doc):
                done = self.check(doc)
                if said is None:            # the same label twice is two keys, 01-a and 02-a
                    self.assertEqual(done.returncode, 0, done.stderr)
                    continue
                self.assertEqual(done.returncode, 2, done.stdout)
                self.assertIn(said, done.stderr)

    def test_the_timeline_is_seconds_on_the_clips_clock_with_every_named_box(self):
        script = """
const s = require(process.argv[1]);
const plan = s.parse(JSON.stringify({scene: "t", names: {go: "#go", gone: "#gone"},
  steps: [{do: "click", target: "go", label: "go"}, {do: "eval", js: "1"}]}), {width: 800, height: 600});
const rows = [
  {i: 1, step: plan.steps[0], start: 1250, end: 2000, targetBox: {x: 10.4, y: 20.6, width: 30, height: 40},
   boxes: {go: {x: 10.4, y: 20.6, width: 30, height: 40}, gone: null}, still: "c.stills/01-go.png", text: "Go"},
  {i: 2, step: plan.steps[1], start: 2100, end: 2500, boxes: {go: null, gone: null}, value: 42}];
process.stdout.write(JSON.stringify(s.timeline(plan, {url: "http://x.test", video: "c.webm", t0: 1000, end: 3000}, rows)));
"""
        done = subprocess.run([NODE, "-e", script, str(STEPS)], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        doc = json.loads(done.stdout)
        self.assertEqual((doc["version"], doc["scene"], doc["video"], doc["duration"], doc["t0_epoch"]), (1, "t", "c.webm", 2.0, 1.0))
        go, ev = doc["steps"]
        self.assertEqual((go["start"], go["end"]), (0.25, 1.0))
        self.assertEqual(go["target_box"], {"x": 10, "y": 21, "w": 30, "h": 40})
        self.assertEqual(go["boxes"], {"go": {"x": 10, "y": 21, "w": 30, "h": 40}, "gone": None})
        self.assertEqual((go["still"], go["text"]), ("c.stills/01-go.png", "Go"))
        self.assertEqual((ev["target_box"], ev["value"]), (None, 42))


# A real browser, off unless asked for: the fence scrubs every KEEL_ variable and HOME, and a
# suite that launched Chromium unasked is what bin/keel-browser exists to prevent. Run it by
# hand with LIVE_BROWSER_HOME=~/.keel-browser (c-570's record has the run).
LIVE_HOME = os.environ.get("LIVE_BROWSER_HOME", "")

LIVE_PAGE = """<!doctype html><html><body>
<h1 id="title">Local page</h1><input id="q"><button id="go"
 onclick="document.getElementById('out').textContent='said '+document.getElementById('q').value">Go</button>
<p id="out"></p></body></html>"""


@unittest.skipUnless(LIVE_HOME and NODE, "a live browser run: set LIVE_BROWSER_HOME to an install")
class LiveVideoTest(unittest.TestCase):
    def test_three_steps_on_a_local_page_give_a_clip_three_stills_and_three_boxes(self):
        import http.server
        import threading
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "index.html").write_text(LIVE_PAGE)
        handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(tmp), **k)  # noqa: E731
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        steps = tmp / "steps.json"
        steps.write_text(json.dumps({"viewport": {"width": 640, "height": 480}, "names": {"out": "#out"},
                                     "css": "#title{display:none}",
                                     "steps": [{"do": "type", "target": "#q", "text": "hi", "label": "type"},
                                               {"do": "click", "target": "#go", "label": "click"},
                                               {"do": "wait", "for": "document.getElementById('out').textContent", "label": "said"}]}))
        clip = tmp / "take" / "clip.webm"
        done = subprocess.run([str(TOOL), "video", f"http://127.0.0.1:{server.server_port}/", str(steps), str(clip)],
                              capture_output=True, text=True, timeout=180,
                              env=dict(os.environ, KEEL_BROWSER_HOME=str(Path(LIVE_HOME).expanduser())))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertGreater(clip.stat().st_size, 0)
        stills = sorted((tmp / "take" / "clip.stills").glob("*.png"))
        self.assertEqual([p.name for p in stills], ["01-type.png", "02-click.png", "03-said.png"])
        self.assertEqual(stills[0].read_bytes()[16:24], (1280).to_bytes(4, "big") + (960).to_bytes(4, "big"))
        doc = json.loads((tmp / "take" / "clip.timeline.json").read_text())
        self.assertEqual(len(doc["steps"]), 3)
        self.assertTrue(all(s["boxes"]["out"] for s in doc["steps"]))
        self.assertIn("said hi", doc["steps"][2]["text"])
        self.assertNotIn("Local page", doc["steps"][0]["text"], "the css was on the page from its first paint")


class TeardownIsWrittenTest(unittest.TestCase):
    """A grep, and only a grep.

    What it can hold: that every exit path in the engine that could run with a browser open
    closes it first, and that the wrapper's trap covers the signals as well as EXIT. What it
    cannot hold: that the close succeeds, that Playwright honours it, or that a future path
    is one these patterns recognise. The container proof is what says the process really goes
    away; this says the line that makes it go away cannot be quietly deleted.
    """

    def setUp(self):
        self.engine = ENGINE.read_text()
        self.wrapper = TOOL.read_text()
        # The comments here quote what they explain, `channel: "chrome"` included, so a grep
        # over the raw file finds the thing it is looking for inside the paragraph saying why
        # that thing is NOT here. tests/test_deck_css.py caught itself doing exactly that.
        self.code = "\n".join(line for line in self.engine.splitlines()
                              if not line.lstrip().startswith("//"))

    def test_every_die_after_a_launch_closes_the_browser_first(self):
        """`die()` is a bare `process.exit`, so a `die` reached with a browser open and no
        close above it is a leaked Chromium. The launch's own catch is the exception: there
        is no browser yet when it runs.
        """
        after_launch = self.engine[self.engine.index("browser = await chromium.launch"):]
        naked = []
        for match in re.finditer(r"\n(\s*)die\((\d)", after_launch):
            before = after_launch[:match.start()]
            if "could not launch chromium" in after_launch[match.start():match.start() + 200]:
                continue
            tail = before[-400:]
            if "closeBrowser()" not in tail and "browser.close()" not in tail:
                naked.append(after_launch[match.start():match.start() + 60].strip())
        self.assertEqual(naked, [], f"die() with no teardown above it: {naked}")

    def test_the_watchdog_the_pipe_and_the_last_catch_all_close(self):
        for anchor in ('process.stdout.on("error"',      # EPIPE: does not throw, so nothing else catches it
                       "const watchdog = setTimeout",     # the budget: a bare exit would leak
                       "})().catch(async (e) =>"):        # anything thrown outside every block
            with self.subTest(anchor=anchor):
                block = self.engine[self.engine.index(anchor):][:900]
                self.assertTrue("browser.close()" in block or "closeBrowser()" in block,
                                f"{anchor} exits without taking the browser down")

    def test_the_watchdogs_backstop_is_not_unrefd(self):
        """An unref'd backstop cannot guarantee anything: if close() never settles and no
        other handle remains, the loop drains and node exits 0. A watchdog whose failure
        mode is "reports success" is the thing this file is built to avoid."""
        block = self.engine[self.engine.index("const watchdog = setTimeout"):][:900]
        self.assertIn("setTimeout(() => process.exit(5), 3000)", block)
        self.assertNotIn("setTimeout(() => process.exit(5), 3000).unref()", block)

    def test_the_wrappers_trap_covers_the_signals_and_not_only_exit(self):
        """The engine cannot close a browser after the shell around it is killed, so the
        shell's own death is an exit path too."""
        self.assertIn("trap cleanup EXIT INT TERM HUP", self.wrapper)

    def test_the_cleanup_signals_the_group_rather_than_the_leader(self):
        """`kill -TERM $pid` reaches node and leaves its Chromium children parented to
        init, which is the leak rather than the fix. The minus sign is the whole point."""
        block = self.wrapper[self.wrapper.index("cleanup() {"):]
        block = block[:block.index("\n}")]
        self.assertIn('kill -TERM "-$ENGINE_PID"', block)
        self.assertIn('kill -KILL "-$ENGINE_PID"', block)
        self.assertNotIn('kill -TERM "$ENGINE_PID"', block)

    def test_the_engine_launches_a_fresh_context_and_never_a_profile(self):
        """The safety property: no profile, no cookies, no saved session, no extension, so
        the tool can look at a page and can never be him on one."""
        self.assertIn("browser.newContext({ viewport:", self.code)
        for forbidden in ("userDataDir", "launchPersistentContext", "storageState",
                          'channel: "chrome"'):
            self.assertNotIn(forbidden, self.code,
                             "that would carry a profile, or the Mac's own Chrome")

    def test_the_engine_and_the_wrappers_probe_launch_the_same_browser(self):
        """`channel: "chromium"` is Playwright's own Chromium in new headless mode. A bare
        `{ headless: true }` is NOT the same thing: on 1.63.0 it resolves to
        chromium-headless-shell, the old headless build, which the install deliberately does
        not fetch. The wrapper's `check` probe has to launch what a real run launches, or it
        proves a browser nobody uses.
        """
        launch = 'chromium.launch({ channel: "chromium", headless: true'
        self.assertIn(launch, self.code)            # the engine adds `args` (a video's mic)
        self.assertIn(launch + " })", self.wrapper)
        self.assertIn("--no-shell", self.wrapper)


class OnePinTest(unittest.TestCase):
    """One Playwright version and one install directory, spelled in two files.

    The two drifting apart is two different browsers on one host, and nothing at runtime
    would say so: the doctor would report a healthy install of a version the tool does not
    use.
    """

    def assigned(self, path: Path, name: str) -> str:
        """The value alone: these lines carry a trailing comment saying why they are pinned."""
        found = re.search(rf'^{name}="?([^\s#"]+)', path.read_text(), re.M)
        self.assertIsNotNone(found, f"{path.name} does not set {name}")
        return found.group(1)

    def test_both_files_pin_the_same_playwright(self):
        pinned = self.assigned(TOOL, "PLAYWRIGHT_VERSION")
        self.assertRegex(pinned, r"^\d+\.\d+\.\d+$")
        self.assertEqual(browser.PLAYWRIGHT_VERSION, pinned)

    def test_both_files_name_the_same_install_directory(self):
        self.assertIn(f'KEEL_BROWSER_HOME:-$HOME/{browser.DEFAULT_HOME.lstrip("~/")}',
                      TOOL.read_text())

    def test_the_install_is_not_in_a_worktree_and_not_under_state(self):
        """A worktree is reaped, so the next house would download it again; `state/` is
        backed up nightly and does not want 400 MB of regenerable bytes in every snapshot."""
        self.assertTrue(browser.DEFAULT_HOME.startswith("~/"), browser.DEFAULT_HOME)
        self.assertNotIn("state", browser.DEFAULT_HOME)


class ReportTest(unittest.TestCase):
    """`keel.browser`, which is what `keel doctor` asks. It never launches anything."""

    class Cfg:
        def __init__(self, browsers_max, spaces):
            self.browsers_max = browsers_max
            self._spaces = spaces

        def served_spaces(self):
            return self._spaces

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / ".keel-browser"
        patched = mock.patch.dict(os.environ, {browser.HOME_VAR: str(self.home)})
        patched.start()
        self.addCleanup(patched.stop)

    def install(self):
        (self.home / "node_modules" / "playwright-core").mkdir(parents=True)
        (self.home / "browsers" / "chromium-1195").mkdir(parents=True)
        (self.home / "browsers" / "chromium_headless_shell-1195").mkdir(parents=True)

    def test_a_host_with_no_browser_slot_is_not_asked_for_a_browser(self):
        """The Mac: `~/harbor/bin/harbor-browser` is its tool and Keel's doctor does not go
        red over a Playwright install it has no use for."""
        found = browser.gather(self.Cfg(None, ["work"]))
        self.assertFalse(found["applicable"])
        self.assertIsNone(browser.problem(found))
        self.assertEqual(browser.line(found),
                         "browser       not applicable (no browsers_max for this host)")

    def test_a_host_that_serves_nothing_is_not_asked_either(self):
        found = browser.gather(self.Cfg(1, []))
        self.assertFalse(found["applicable"])
        self.assertIsNone(browser.problem(found))

    def test_a_missing_browser_on_the_browser_host_is_named_with_its_fix(self):
        found = browser.gather(self.Cfg(1, ["personal"]))
        self.assertTrue(found["applicable"])
        self.assertFalse(found["ok"])
        self.assertIn("options.browser", browser.problem(found))
        self.assertIn("keel-browser install", browser.problem(found))
        self.assertIn("MISSING", browser.line(found))

    def test_an_installed_browser_is_reported_with_its_version_and_builds(self):
        self.install()
        found = browser.gather(self.Cfg(1, ["personal"]))
        self.assertTrue(found["ok"])
        self.assertIsNone(browser.problem(found))
        self.assertIn(browser.PLAYWRIGHT_VERSION, browser.line(found))
        self.assertIn("2 chromium build(s)", browser.line(found))

    def test_half_an_install_is_not_ok(self):
        (self.home / "node_modules" / "playwright-core").mkdir(parents=True)
        found = browser.gather(self.Cfg(1, ["personal"]))
        self.assertFalse(found["ok"])
        self.assertIn("no chromium build", browser.problem(found))

    def test_nothing_is_created_by_looking(self):
        browser.gather(self.Cfg(1, ["personal"]))
        self.assertFalse(self.home.exists())


if __name__ == "__main__":
    unittest.main()
