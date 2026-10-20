"""A question typed on one of Harbor's boards (c-422, C3 of the overnight clearance).

THE BUG. `boardask.ask_talker` ran `bin/keel-voice ask <text>`, which called
`harbormsg.send`, which started Harbor's turn on a DAEMON thread and returned "turn
started" in about 50 ms. The command then exited and took the thread with it, mid
`claude -p`: nothing reached the transcript or the say inbox, and the deck showed "It
answers out loud", which was false. And the turn lock was a `threading.Lock`, so even a
thread that lived would have raced a spoken turn on one Harbor transcript.

THE FIX, as settled: a cross-process file lock around Harbor's turn, shared by the gateway
and the CLI, and `keel-voice ask --wait --json` running the turn in the FOREGROUND, called
from the board ask's existing turn-id thread (B15). No new route on the gateway.
"""

import importlib.machinery
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "voice") not in sys.path:
    sys.path.insert(0, str(ROOT / "voice"))

from harbor_voice import drawing, harbormsg                              # noqa: E402

from keel import boardask                                                # noqa: E402
from tests.helpers import make_config                                    # noqa: E402


class TypedCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        for module, name, value in (
                (harbormsg, "TURN_LOCK_FILE", self.dir / "harbor-turn.lock"),
                (harbormsg, "TRANSCRIPT", self.dir / "transcript.jsonl"),
                (drawing, "TRANSCRIPT", self.dir / "transcript.jsonl"),
                (drawing, "REPORT_FILE", self.dir / "board-report.txt")):
            patch = mock.patch.object(module, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        for name in ("count_turn", "log", "report_failure"):
            patch = mock.patch.object(harbormsg, name)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(harbormsg, "open_session", return_value=("s-1", True, ""))
        patch.start()
        self.addCleanup(patch.stop)

    def records(self) -> list[dict]:
        path = self.dir / "transcript.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]


class ForegroundTurnTest(TypedCase):
    def test_the_turn_is_finished_before_the_call_returns(self):
        """Red before C3: the only entry point returned "turn started" while the model was
        still running, on a thread the CLI's exit then killed."""
        def slow(line, timeout, session, existed, model=None):
            time.sleep(0.3)
            return "The drain is paused."

        with mock.patch.object(harbormsg, "run_turn", slow):
            started = time.time()
            result = harbormsg.run_turn_now("is the drain running", context="board b-003")
        self.assertGreaterEqual(time.time() - started, 0.3)
        self.assertTrue(result["ok"])
        self.assertEqual(result["answer"], "The drain is paused.")

    def test_the_turn_is_in_the_transcript_as_a_typed_one(self):
        with mock.patch.object(harbormsg, "run_turn", return_value="Two houses."):
            harbormsg.run_turn_now("what is running", source="deck")
        typed = [r for r in self.records() if r["kind"] == "typed-ask"]
        self.assertEqual(len(typed), 1)
        self.assertEqual((typed[0]["mode"], typed[0]["source"]), ("typed", "deck"))
        self.assertEqual(typed[0]["said"], "what is running")
        self.assertEqual(typed[0]["answer"], "Two houses.")

    def test_the_context_names_the_board_it_was_asked_from(self):
        lines = []
        with mock.patch.object(harbormsg, "run_turn",
                               lambda line, *a, **k: lines.append(line) or "Yes."):
            harbormsg.run_turn_now("what is this", context="asked from the deck board b-003")
        self.assertIn("asked from the deck board b-003", lines[0])

    def test_a_drawing_in_the_answer_is_drawn_and_counted(self):
        pushed = []
        with mock.patch.object(harbormsg, "run_turn",
                               return_value='Here.\n```board\nnode a box "a"\n```\n'), \
                mock.patch.object(drawing, "push_ops",
                                  lambda body, **_: pushed.append(body) or {"board": "b-9"}):
            result = harbormsg.run_turn_now("draw it")
        self.assertEqual(result["drew"], 1)
        self.assertEqual(len(pushed), 1)
        self.assertNotIn("node a box", result["answer"])


class CrossProcessLockTest(TypedCase):
    """The lock is a FILE lock, so a turn in another process is seen."""

    HOLDER = """
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from harbor_voice import harbormsg
harbormsg.TURN_LOCK_FILE = Path(sys.argv[2])
with harbormsg.conversation_turn(wait=0):
    print("held", flush=True)
    time.sleep(30)
"""

    def hold_elsewhere(self) -> subprocess.Popen:
        holder = subprocess.Popen(
            [sys.executable, "-c", self.HOLDER, str(ROOT / "voice"),
             str(self.dir / "harbor-turn.lock")],
            stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        return holder

    def test_a_typed_ask_while_another_process_holds_the_turn_is_busy(self):
        self.hold_elsewhere()
        with mock.patch.object(harbormsg, "run_turn") as run:
            result = harbormsg.run_turn_now("anything")
        self.assertFalse(result["ok"])
        self.assertTrue(result["busy"])
        run.assert_not_called()

    def test_the_gateways_own_turn_waits_for_the_other_process(self):
        holder = self.hold_elsewhere()
        started = time.time()
        threading_done = []

        def release_soon():
            time.sleep(0.4)
            holder.kill()

        import threading
        threading.Thread(target=release_soon, daemon=True).start()
        with harbormsg.conversation_turn(wait=5):
            threading_done.append(time.time() - started)
        self.assertGreaterEqual(threading_done[0], 0.3)

    def test_the_lock_is_given_back(self):
        with harbormsg.conversation_turn(wait=0):
            pass
        with harbormsg.conversation_turn(wait=0):
            pass


def load_keel_voice():
    loader = importlib.machinery.SourceFileLoader("keel_voice_cli", str(ROOT / "bin" / "keel-voice"))
    spec = importlib.util.spec_from_loader("keel_voice_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class CommandTest(TypedCase):
    def setUp(self):
        super().setUp()
        self.cli = load_keel_voice()

    def run_cli(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["keel-voice", *argv]), redirect_stdout(out):
            code = self.cli.main()
        return code, out.getvalue()

    def test_ask_wait_json_prints_the_answer_harbor_gave(self):
        with mock.patch.object(harbormsg, "run_turn_now",
                               return_value={"ok": True, "answer": "It is paused.", "drew": 0,
                                             "turn": "t1"}) as now:
            code, out = self.run_cli("ask", "--wait", "--json", "--context", "board b-3",
                                     "is", "the", "drain", "on")
        self.assertEqual(code, 0)
        payload = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(payload["answer"], "It is paused.")
        self.assertEqual(payload["tier"], "harbor")
        self.assertEqual(now.call_args.kwargs.get("context"), "board b-3")

    def test_the_bare_ask_waits_for_the_answer_too(self):
        """The bare form used to exit with the turn still running on a daemon thread."""
        with mock.patch.object(harbormsg, "run_turn_now",
                               return_value={"ok": True, "answer": "Yes.", "drew": 0}), \
                mock.patch.object(harbormsg, "send") as send:
            code, out = self.run_cli("ask", "anything", "at", "all")
        send.assert_not_called()
        self.assertEqual(code, 0)
        self.assertIn("answer:  Yes.", out)

    def test_busy_is_its_own_exit(self):
        with mock.patch.object(harbormsg, "run_turn_now",
                               return_value={"ok": False, "busy": True, "answer": "busy"}):
            code, out = self.run_cli("ask", "--wait", "--json", "hello")
        self.assertEqual(json.loads(out.strip().splitlines()[-1])["busy"], True)
        self.assertNotEqual(code, 0)


class BoardAskTest(unittest.TestCase):
    """The deck's half: it waits for the JSON and never claims it was sent."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = make_config(Path(self.tmp.name))

    def fake(self, stdout: str, code: int = 0):
        seen = {}

        def run(argv, timeout):
            seen["argv"], seen["kwargs"] = argv, {"timeout": timeout}
            return code, stdout, ""

        return run, seen

    def test_it_runs_ask_wait_json_with_the_board_as_context(self):
        run, seen = self.fake(json.dumps({"tier": "harbor", "ok": True,
                                          "answer": "The drain is paused.", "drew": 0}))
        with mock.patch.object(boardask, "run_ask", run):
            ok, say = boardask.ask_talker(self.cfg, "is it on", board_id="b-003")
        self.assertEqual((ok, say), (True, "The drain is paused."))
        argv = seen["argv"]
        self.assertEqual(argv[2:5], ["ask", "--wait", "--json"])
        self.assertIn("asked from the deck board b-003", argv)
        self.assertGreater(seen["kwargs"]["timeout"], 120, "a Harbor turn may take 120 s")

    def test_busy_is_one_sentence(self):
        run, _ = self.fake(json.dumps({"tier": "harbor", "ok": False, "busy": True,
                                       "answer": "busy"}), code=4)
        with mock.patch.object(boardask, "run_ask", run):
            ok, say = boardask.ask_talker(self.cfg, "hello", board_id="b-003")
        self.assertFalse(ok)
        self.assertEqual(say, boardask.HARBOR_BUSY)

    def test_a_drawing_on_the_board_is_mentioned(self):
        run, _ = self.fake(json.dumps({"tier": "harbor", "ok": True, "answer": "Here.",
                                       "drew": 1}))
        with mock.patch.object(boardask, "run_ask", run):
            ok, say = boardask.ask_talker(self.cfg, "draw it", board_id="b-003")
        self.assertTrue(ok)
        self.assertIn("Here.", say)


if __name__ == "__main__":
    unittest.main()


class ReviewDeadlineTest(TypedCase):
    """F3 and F4 of the lane C review: one deadline per turn and per lock, no orphans."""

    HOLDER = CrossProcessLockTest.HOLDER

    def test_f3_the_lost_conversation_retry_shares_the_turns_deadline(self):
        timeouts = []

        def fake(argv, **kwargs):
            timeouts.append(kwargs["timeout"])
            if len(timeouts) == 1:
                time.sleep(0.3)
                return mock.Mock(returncode=1, stdout="",
                                 stderr="No conversation found with session ID: x")
            return mock.Mock(returncode=0, stdout='{"result": "ok"}', stderr="")

        with mock.patch.object(harbormsg.subprocess, "run", fake):
            harbormsg.run_turn("hi", 1.0, "s-1", True)
        self.assertEqual(len(timeouts), 2)
        self.assertLessEqual(timeouts[1], 0.75, timeouts)

    def test_f3_the_decks_wait_is_above_the_typed_asks_worst_case(self):
        self.assertGreater(boardask.TALKER_TIMEOUT, harbormsg.TYPED_WORST)
        self.assertGreaterEqual(harbormsg.TYPED_WORST,
                                harbormsg.config.HARBOR_TURN_TIMEOUT + drawing.PUSH_BUDGET)

    def test_f4_one_deadline_covers_both_locks(self):
        import threading
        holder = CrossProcessLockTest.hold_elsewhere(self)          # the file lock, elsewhere
        harbormsg._TURN_LOCK.acquire()                               # and this process's lock
        threading.Timer(0.3, harbormsg._TURN_LOCK.release).start()
        started = time.time()
        with self.assertRaises(harbormsg.TurnBusy):
            harbormsg.acquire_turn(wait=0.5)
        self.assertLess(time.time() - started, 0.75, "the two waits were added together")
        holder.kill()

    def test_f4_a_spoken_turn_behind_a_typed_one_says_so_at_once_and_its_own_busy(self):
        holder = CrossProcessLockTest.hold_elsewhere(self)
        opening, say = self.dir / "opening", self.dir / "say"
        progress = self.dir / "progress"
        with mock.patch.object(harbormsg, "OPENING_DIR", opening), \
                mock.patch.object(harbormsg, "PROGRESS_DIR", progress), \
                mock.patch.object(harbormsg, "SAY_DIR", say), \
                mock.patch.object(harbormsg.config, "HARBOR_TURN_TIMEOUT", 0.4), \
                mock.patch.object(harbormsg, "run_turn") as run:
            ok, _ = harbormsg.send("what is running", turn_id="t-7")
            # THE WORKER ALWAYS WRITES ITS LINE, so it is waited for INSIDE the patches
            # even when an assertion fails; otherwise a red run writes into the checkout.
            try:
                said = [json.loads(p.read_text()) for p in sorted(progress.glob("*.json"))]
                self.assertTrue(ok)
                self.assertEqual([r["text"] for r in said], [harbormsg.TYPED_FIRST],
                                 "said before the wait, not after")
                self.assertEqual(said[0]["turn"], "t-7")
                # FOLLOW-UP N2: the opening channel is claimed once per turn, so a line put there
                # would take the place of Harbor's own opener for this turn.
                self.assertEqual(list(opening.glob("*.json")), [], "the turn's opener was used up")
                deadline = time.time() + 5
                while not list(say.glob("*.json")) and time.time() < deadline:
                    time.sleep(0.05)
            finally:
                for thread in threading.enumerate():
                    if thread.name == "voice-turn":
                        thread.join(5)
        answer = json.loads(sorted(say.glob("*.json"))[0].read_text())["text"]
        self.assertEqual(answer, harbormsg.BUSY_SPOKEN)
        self.assertNotEqual(harbormsg.BUSY_SPOKEN, harbormsg.BUSY_TYPED)
        # FOLLOW-UP N3: the holder may be a refine or another spoken turn, so the busy
        # sentence names no holder it cannot know.
        self.assertNotIn("typed", harbormsg.BUSY_SPOKEN.lower())
        run.assert_not_called()
        holder.kill()




class OrphanTest(unittest.TestCase):
    """F3: a typed ask that outlives the deck's wait takes its whole process group with it."""

    def test_the_asks_whole_process_group_is_killed_on_timeout(self):
        import os
        import signal
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "bin").mkdir()
        pidfile = root / "grandchild.pid"
        (root / "bin" / "keel-voice").write_text(
            "import subprocess, sys, time\n"
            f"child = subprocess.Popen(['sleep', '30'])\n"
            f"open({str(pidfile)!r}, 'w').write(str(child.pid))\n"
            "time.sleep(30)\n")
        cfg = make_config(root)
        cfg.root = root
        with mock.patch.object(boardask, "TALKER_TIMEOUT", 1.0):
            ok, say = boardask.ask_talker(cfg, "hello")
        self.assertFalse(ok)
        pid = int(pidfile.read_text())
        time.sleep(0.2)
        alive = True
        try:
            os.kill(pid, 0)
            waited = os.waitpid(pid, os.WNOHANG) if False else None
            state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True,
                                   text=True).stdout.strip()
            alive = bool(state) and not state.startswith("Z")
        except ProcessLookupError:
            alive = False
        if alive:
            os.kill(pid, signal.SIGKILL)
        self.assertFalse(alive, "the claude -p under the ask kept running")


class WrittenTest(TypedCase):
    """F6: on Harbor's path the whole answer is kept and shown; only speech is capped."""

    def test_the_typed_ask_returns_and_records_the_whole_text(self):
        raw = ('One. Two. Three.\n```board\nnode a box "a"\n```\nAfter the block.\n')
        with mock.patch.object(harbormsg, "run_turn", return_value=raw), \
                mock.patch.object(drawing, "push_ops", lambda body, **_: {"board": "b-9", "accepted": 1}):
            result = harbormsg.run_turn_now("draw it")
        self.assertNotIn("After the block.", result["answer"])
        self.assertIn("After the block.", result["written"])
        self.assertIn("Three.", result["written"])
        typed = [r for r in self.records() if r["kind"] == "typed-ask"][0]
        self.assertIn("After the block.", typed["written"])

    def test_a_spoken_harbor_answer_logs_what_was_written_beside_it(self):
        raw = 'Here.\n```board\nnode a box "a"\n```\nThe rest of it.\n'
        with mock.patch.object(drawing, "push_ops", lambda body, **_: {"board": "b-9", "accepted": 1}):
            said = harbormsg.draw_and_say(raw, turn="t-3")
        self.assertNotIn("The rest of it.", said)
        written = [r for r in self.records() if r["kind"] == "answer-written"]
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["turn"], "t-3")
        self.assertIn("The rest of it.", written[0]["written"])

    def test_the_deck_shows_the_whole_text(self):
        cfg = make_config(self.dir)
        out = json.dumps({"tier": "harbor", "ok": True, "answer": "Here. I have put that on the board.",
                          "written": "Here. The rest of it. I have put that on the board.", "drew": 1})
        with mock.patch.object(boardask, "run_ask", return_value=(0, out, "")):
            ok, say = boardask.ask_talker(cfg, "draw it", board_id="b-1")
        self.assertIn("The rest of it.", say)
