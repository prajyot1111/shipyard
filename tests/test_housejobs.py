"""A house's background jobs (c-534): seen while it lives, ended by pid when it is stopped.

The job record is written by hand in the harness's own shape (`jobs/<id>/state.json` and
`adopt.json`, as c-526's left them), and the job itself is a REAL process: a shell leading
its own session with a `sleep` under it, orphaned the way `claude stop` orphans one, so
what is ended is proven by the kernel rather than by a mock.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from keel import harness, housejobs
from keel.board import Board

ROOT = Path(__file__).resolve().parent.parent
BG = "3f9b8d06"
TASK = "bs6e3ga2f"
# The middle process starts the job in a session of its own and exits at once, so the job
# is nobody's child here: the machine reaps it, as it reaps a shell a stopped house left.
SPAWN = ("import subprocess; p = subprocess.Popen(['bash', '-c', 'sleep 60 & wait'], "
         "start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); print(p.pid)")


def spawn_job() -> int:
    out = subprocess.run([sys.executable, "-c", SPAWN], capture_output=True, text=True, timeout=30)
    pid = int(out.stdout.strip())
    deadline = time.monotonic() + 5
    while len(housejobs.in_session(pid)) < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    return pid


class JobCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.tmp.name)
        self.dir = self.config_dir / "jobs" / BG
        self.dir.mkdir(parents=True)
        self.pids: list[int] = []

    def tearDown(self):
        for pid in self.pids:           # a job a test left running on purpose
            for member in housejobs.in_session(pid) or [pid]:
                try:
                    os.kill(member, 9)
                except OSError:
                    pass
        self.tmp.cleanup()

    def job(self) -> int:
        pid = spawn_job()
        self.pids.append(pid)
        return pid

    def state(self, tasks: int, started_ms: int, label: str = "make test") -> None:
        (self.dir / "state.json").write_text(json.dumps({
            "state": "idle", "inFlight": {"tasks": tasks, "queued": 0, "kinds": ["local_bash"]},
            "fan": [{"id": TASK, "kind": "shell", "label": label, "startedAt": started_ms}]}))

    def adopt(self, pid: int, ticks, written_ms: int | None = None) -> None:
        (self.dir / "adopt.json").write_text(json.dumps({
            "writtenAtMs": written_ms or int(time.time() * 1000), "origin": "exit",
            "shells": [{"taskId": TASK, "pid": pid, "procStart": str(ticks), "startTimeTicks": ticks,
                        "command": "while pgrep -f tests.parallel; do sleep 5; done",
                        "description": "the final suite"}]}))

    def harness_stop(self, pid: int, ticks=None):
        """A `claude stop` that writes the record the harness writes when a session exits."""
        calls = []

        def stop(bg_id, config_dir):
            calls.append((bg_id, config_dir))
            self.adopt(pid, housejobs.start_ticks(pid) if ticks is None else ticks)
        return stop, calls


class RunningTest(JobCase):
    def test_a_live_session_lists_its_shells_in_flight(self):
        self.state(1, 1790413540697, label="while pgrep -f tests.parallel; do sleep 5; done")
        self.assertEqual(housejobs.running(self.config_dir, BG),
                         [{"id": TASK, "label": "while pgrep -f tests.parallel; do sleep 5; done",
                           "started_at": 1790413540697}])

    def test_nothing_in_flight_is_nothing_running(self):
        """A stopped session keeps its fan but counts nothing in flight (c-526's state)."""
        self.state(0, 1)
        self.assertEqual(housejobs.running(self.config_dir, BG), [])
        (self.dir / "state.json").write_text(json.dumps({"state": "stopped", "fan": [{"id": TASK, "kind": "shell"}]}))
        self.assertEqual(housejobs.running(self.config_dir, BG), [])
        (self.dir / "state.json").write_text("not json")
        self.assertEqual(housejobs.running(self.config_dir, BG), [])
        self.assertEqual(housejobs.running(self.config_dir, "nosuchid"), [])

    def test_only_a_row_out_of_its_turn_counts(self):
        """The listing's shape for c-526, probed live: busy by status, done by state."""
        self.state(1, 1)
        self.assertEqual(housejobs.of_row(self.config_dir, {"id": BG, "status": "busy", "state": "working"}), [])
        self.assertEqual(len(housejobs.of_row(self.config_dir, {"id": BG, "status": "busy", "state": "done"})), 1)
        self.assertEqual(housejobs.of_row(self.config_dir, None), [])


class StopTest(JobCase):
    def test_a_stop_ends_the_shell_and_everything_it_started(self):
        pid = self.job()
        self.assertEqual(len(housejobs.in_session(pid)), 2, "the shell and its sleep")
        self.state(1, int(time.time() * 1000))
        stop, calls = self.harness_stop(pid)
        ended = housejobs.stop(BG, self.config_dir, stop, wait=5, grace=2)
        self.assertEqual(calls, [(BG, self.config_dir)])
        self.assertEqual([(job["task"], job["pid"], job["outcome"]) for job in ended],
                         [(TASK, pid, housejobs.ENDED)])
        self.assertEqual(housejobs.in_session(pid), [])
        self.assertFalse(housejobs.alive(pid))
        self.assertEqual(housejobs.said(ended), f"ended its background job {TASK} (pid {pid})")

    def test_a_pid_that_is_not_the_recorded_process_is_left(self):
        """Pid reuse: the start time does not match, so it is somebody else's process."""
        pid = self.job()
        self.state(1, int(time.time() * 1000) - 3_600_000)      # an hour off, for ps off Linux
        stop, _ = self.harness_stop(pid, ticks=1)
        ended = housejobs.stop(BG, self.config_dir, stop, wait=5, grace=1)
        self.assertEqual(ended[0]["outcome"], housejobs.UNPROVEN)
        self.assertTrue(housejobs.alive(pid))
        self.assertIn("could not be proven", housejobs.said(ended))

    def test_a_failed_stop_ends_nothing(self):
        pid = self.job()
        self.state(1, int(time.time() * 1000))
        self.adopt(pid, housejobs.start_ticks(pid))

        def refuses(bg_id, config_dir):
            raise harness.HarnessError("claude stop failed")
        with self.assertRaises(harness.HarnessError):
            housejobs.stop(BG, self.config_dir, refuses, wait=1)
        self.assertTrue(housejobs.alive(pid))

    def test_an_older_record_is_not_this_stop_and_no_job_means_no_wait(self):
        pid = self.job()
        self.adopt(pid, housejobs.start_ticks(pid), written_ms=1)
        began = time.monotonic()
        ended = housejobs.stop(BG, self.config_dir, lambda bg_id, config_dir: None)
        self.assertLess(time.monotonic() - began, 2, "nothing was in flight, so nothing waits")
        self.assertEqual(ended, [])
        self.assertTrue(housejobs.alive(pid))

    def test_a_shell_already_gone_is_said_to_be_gone(self):
        self.state(1, 1)
        stop, _ = self.harness_stop(2 ** 22 + 12345, ticks=5)
        ended = housejobs.stop(BG, self.config_dir, stop, wait=1)
        self.assertEqual(ended[0]["outcome"], housejobs.GONE)
        self.assertEqual(housejobs.said(ended), "")


class NoteTest(JobCase):
    def test_the_drain_notes_each_job_once(self):
        board = Board(self.config_dir / "board.db")
        self.addCleanup(board.close)
        card_id = board.create("personal", "x", brief="y", repo="keel")
        self.state(1, 1790413540697, label="make test")
        row = {"id": BG, "status": "busy", "state": "done"}
        self.assertEqual(housejobs.note_idle(board, board.get(card_id), self.config_dir, row), 1)
        self.assertEqual(housejobs.note_idle(board, board.get(card_id), self.config_dir, row), 0)
        notes = [e["text"] for e in board.events(card_id) if e["kind"] == "note"]
        self.assertEqual(len(notes), 1)
        self.assertIn(f"idle with its background job {TASK} still running since", notes[0])
        self.assertTrue(notes[0].endswith(": make test"))
        self.assertEqual(housejobs.note_idle(board, board.get(card_id), self.config_dir,
                                             {"id": BG, "status": "busy", "state": "working"}), 0)


class EveryStopTest(unittest.TestCase):
    """Every house stop goes through `housejobs.stop`, so none can leave a job behind. The
    one exception is voice's pause, whose session is woken again (`keel/housetalk.py`)."""

    ALLOWED = {"harness.py", "housejobs.py", "housetalk.py"}

    def test_nothing_else_calls_harness_stop(self):
        calls = re.compile(r"\bharness\.stop\(")
        found = [f"{path.name}:{n}" for path in sorted((ROOT / "keel").rglob("*.py"))
                 if path.name not in self.ALLOWED
                 for n, line in enumerate(path.read_text().splitlines(), 1) if calls.search(line)]
        self.assertEqual(found, [])


class TicksTest(unittest.TestCase):
    @unittest.skipUnless(Path("/proc/self/stat").exists(), "Linux only")
    def test_start_ticks_reads_field_22_past_a_command_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            stat = Path(tmp) / "7" / "stat"
            stat.parent.mkdir()
            fields = ["S"] + [str(n) for n in range(4, 22)] + ["63705402"] + ["0"] * 30
            stat.write_text("7 (bash -c (odd) name) " + " ".join(fields) + "\n")
            with mock.patch.object(housejobs, "PROC", Path(tmp)):
                self.assertEqual(housejobs.start_ticks(7), 63705402)


class LstartProofTest(unittest.TestCase):
    """Off Linux (no /proc), a pid is the recorded shell only when `ps -o lstart` sits within
    START_SLACK of the task's `startedAt`; a reused pid started later is refused (c-635)."""

    def proven(self, began, started_ms):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(housejobs, "PROC", Path(tmp) / "missing"), \
                mock.patch.object(housejobs, "started_epoch", return_value=began):
            return housejobs.proven({"pid": 7}, started_ms)

    def test_a_start_within_the_slack_is_the_shell(self):
        self.assertIs(self.proven(1000.0 + housejobs.START_SLACK - 1, 1_000_000), True)

    def test_a_reused_pid_started_past_the_slack_is_refused(self):
        self.assertIs(self.proven(1000.0 + housejobs.START_SLACK + 1, 1_000_000), False)

    def test_no_lstart_or_no_recorded_start_cannot_tell(self):
        self.assertIsNone(self.proven(None, 1_000_000))
        self.assertIsNone(self.proven(1000.0, None))



class RetireSessionTest(JobCase):
    """A caller, end to end: `house.retire_session` (a superseded, finished or rotated-out
    session) ends the job its stop left and names it on the card."""

    def test_the_stop_ends_the_job_and_the_note_names_it(self):
        from keel import house
        pid = self.job()
        self.state(1, int(time.time() * 1000))
        stop, calls = self.harness_stop(pid)
        session = BG + "-0000-4000-8000-000000000000"
        fake = mock.Mock(HarnessError=harness.HarnessError, stop=stop,
                         agents=lambda config_dir: [{"id": BG, "sessionId": session}],
                         find=harness.find)
        board = Board(self.config_dir / "board.db")
        self.addCleanup(board.close)
        card_id = board.create("personal", "x", brief="y", repo="keel")
        with mock.patch.object(house, "harness", fake):
            self.assertTrue(house.retire_session(board, card_id, session, self.config_dir,
                                                 "superseded session"))
        self.assertEqual(calls, [(BG, self.config_dir)])
        self.assertEqual(housejobs.in_session(pid), [])
        notes = [e["text"] for e in board.events(card_id) if e["kind"] == "note"]
        self.assertEqual(notes, [f"superseded session {BG} stopped; ended its background job "
                                 f"{TASK} (pid {pid})"])


class DeckStopTest(JobCase):
    """His Stop on the deck (`actions.act_stop`): the job goes with the session, and the
    card's note says which one."""

    def test_the_tap_ends_the_job_and_notes_it(self):
        from keel import actions
        pid = self.job()
        self.state(1, int(time.time() * 1000))
        stop, calls = self.harness_stop(pid)
        fake = mock.Mock(HarnessError=harness.HarnessError, stop=stop)
        notes = []
        card = {"id": "c-1", "options": {}, "session_id": BG + "-0000"}
        with mock.patch.object(actions, "card_of", return_value=card), \
                mock.patch.object(actions, "bg_and_dir", return_value=(BG, self.config_dir)), \
                mock.patch.object(actions, "run_kb", side_effect=lambda cfg, argv: notes.append(argv)), \
                mock.patch.object(actions, "harness", fake):
            self.assertEqual(actions.act_stop(None, None, {"card": "c-1"}), {"stopped": BG})
        self.assertEqual(calls, [(BG, self.config_dir)])
        self.assertEqual(housejobs.in_session(pid), [])
        self.assertEqual(notes, [["note", "c-1", f"session {BG} stopped from the deck; ended its "
                                                 f"background job {TASK} (pid {pid})", "--mark", "human-stop"]])


class StaleStateTest(unittest.TestCase):
    """c-600 sandbox run: a finished turn left `state: working` with `status: idle`."""

    def test_status_idle_is_never_working(self):
        from keel import housejobs as hj
        self.assertFalse(hj.working({"pid": 1, "state": "working", "status": "idle"}))
        self.assertTrue(hj.working({"pid": 1, "state": "working", "status": "busy"}))
        self.assertTrue(hj.working({"pid": 1, "state": "working"}))
        self.assertFalse(hj.working({"pid": 1, "state": "done", "status": "busy"}))


if __name__ == "__main__":
    unittest.main()
