"""The code-moved restart says what it loaded and waits for quiet (c-557, r-25).

r-25 read `ps` (pid 86069, started 09-25) as a stale Mac door, but `os.execv` keeps the pid
and the start time: the door had re-exec'd on every follow. What was really wrong: nobody
could see which code a process loaded, and the exec cut a live conversation."""

import json
import os
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import subprocess

from keel import drain, housetalk, restart, serve
from tests.helpers import ROOT
from tests.test_drain import DrainCase
from tests.test_serve import ServerCase

OLD, NEW = "a" * 40, "b" * 40


class Execed(Exception):
    """What the fake `os.execv` raises, so the loop ends where the process would."""


class RestartWaitsForQuietTest(DrainCase):
    SUMMARY = {"houses": 0, "reviews": 0, "resumed": 0, "blocked": 0, "started": 0, "paused": False}

    def setUp(self):
        super().setUp()
        restart.started(None)
        self.addCleanup(restart.started, None)

    def loop(self, busy: list[str], heads: list[str], passes: int | None = None):
        """Run the drain loop with HEAD reading `heads` in turn and the process `busy` in
        turn, until it execs or has slept `passes` times (default `len(busy) + 1`)."""
        sleeps = []
        passes = len(busy) + 1 if passes is None else passes

        def sleep(_seconds):
            sleeps.append(1)
            if len(sleeps) >= passes:
                raise KeyboardInterrupt

        with mock.patch.object(drain, "once", return_value=self.SUMMARY), \
                mock.patch.object(drain.merging, "code_head", side_effect=heads), \
                mock.patch.object(restart, "busy", side_effect=busy), \
                mock.patch.object(drain.os, "execv", side_effect=Execed), \
                mock.patch.object(drain, "rest", lambda cfg, inbox: sleep(cfg.poll_seconds)):
            try:
                drain.run(self.cfg)
            except (Execed, KeyboardInterrupt) as ended:
                return ended, len(sleeps)
        return None, len(sleeps)

    def test_an_open_conversation_holds_the_restart_and_the_wait_is_said_once(self):
        """Red before c-557: the loop exec'd on the first look, with the conversation open."""
        open_on = "a conversation is open on c-272"
        ended, passes = self.loop([open_on, open_on, ""], [OLD, NEW, NEW, NEW])
        self.assertIsInstance(ended, Execed, "the restart never came once it was quiet")
        self.assertEqual(passes, 2, "two passes ran on the old code while it waited")
        log = self.log_text()
        self.assertEqual(log.count("the restart waits: " + open_on), 1)
        self.assertIn("code moved since start; restarting between passes", log)

    def test_the_wait_is_announced_for_the_doctor_on_this_machine(self):
        self.loop(["a house call in flight"] * 2, [OLD] + [NEW] * 2, passes=2)
        said = restart.announced(self.cfg.state_dir)
        self.assertEqual((said["head"], said["waiting"]), (OLD, "a house call in flight"))
        self.assertTrue(said["since"])

    def test_quiet_restarts_at_once(self):
        ended, passes = self.loop([""], [OLD, NEW])
        self.assertIsInstance(ended, Execed)
        self.assertEqual(passes, 0)

    def test_the_loaded_head_is_announced(self):
        self.loop([""], [OLD, OLD, OLD])
        said = json.loads((self.cfg.state_dir / drain.ANNOUNCE_FILE).read_text())
        self.assertEqual(said["head"], OLD)
        self.assertEqual(restart.announced(self.cfg.state_dir)["head"], OLD)


class WhatIsBusyTest(unittest.TestCase):
    def test_a_conversation_open_or_opening_is_busy(self):
        sessions = housetalk.Sessions()
        self.assertEqual(sessions.busy(), "")
        opener = sessions.openers.setdefault("c-272", threading.Lock())
        with opener:
            self.assertEqual(sessions.busy(), "a conversation is opening on c-272")
        self.assertEqual(sessions.busy(), "")
        sessions.live["c-272"] = housetalk.Entry(talk=mock.Mock(alive=True))
        self.assertEqual(sessions.busy(), "a conversation is open on c-272")

    def test_a_call_in_flight_is_busy_until_it_ends(self):
        calls = restart.InFlight()
        with calls.held(restart.HOUSE_CALL):
            with calls.held(restart.DECK_ACTION):
                self.assertEqual(calls.busy(), "a deck action and a house call in flight")
            self.assertEqual(calls.busy(), "a house call in flight")
        self.assertEqual(calls.busy(), "")

    def test_a_call_that_raises_still_leaves(self):
        calls = restart.InFlight()
        with self.assertRaises(RuntimeError), calls.held(restart.HOUSE_CALL):
            raise RuntimeError("the call failed")
        self.assertEqual(calls.busy(), "")

    def test_a_dead_drain_announces_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "drain.json").write_text(json.dumps({"pid": 2 ** 22 + 7, "head": OLD}))
            self.assertIsNone(restart.announced(Path(tmp)))
            (Path(tmp) / "drain.json").write_text(json.dumps({"pid": os.getpid()}))
            self.assertIsNone(restart.announced(Path(tmp)), "older code said no head")


def git_head(ref: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", ref], capture_output=True,
                          text=True, check=True).stdout.strip()


class SlowRelease(restart.InFlight):
    """The real counting, with a release that lags the reply by 0.2 s (c-561). The handler
    sends its answer inside `CALLS.held`, so the count drops after the client wakes; a test
    that asserts on it without waiting for the handler fails here on every machine, not
    only on a loaded one."""

    @contextmanager
    def held(self, what: str):
        with super().held(what):
            try:
                yield
            finally:
                time.sleep(0.2)


def slow_release(case) -> None:
    """Patch `restart.CALLS` with a fresh `SlowRelease` for one test, which also keeps any
    count a test leaves behind out of the next one."""
    patch = mock.patch.object(restart, "CALLS", SlowRelease())
    patch.start()
    case.addCleanup(patch.stop)


def finished(case, handler_class) -> threading.Event:
    """Set once `handler_class.do_POST` has returned, which is after its `CALLS.held`
    block released the count: the signal the test waits on before it asserts (c-561)."""
    done = threading.Event()
    original = handler_class.do_POST

    def do_POST(handler):
        try:
            return original(handler)
        finally:
            done.set()

    patch = mock.patch.object(handler_class, "do_POST", do_POST)
    patch.start()
    case.addCleanup(patch.stop)
    return done


NEVER_FINISHED = "the handler's do_POST never returned, so its in-flight count was never released"


class ACallInFlightHoldsTheRestartTest(ServerCase):
    """Through the real handler and counting (F7 of the review): while a house call is
    being answered, `restart.due()` says wait."""

    def setUp(self):
        super().setUp()
        restart.started(None)
        self.addCleanup(restart.started, None)
        slow_release(self)

    def test_the_deck_holds_it_for_a_house_call(self):
        seen = []
        done = finished(self, serve.Handler)

        def house(handler, method):
            seen.append(restart.due())
            handler.reply_json(200, {"ok": True})

        with mock.patch.object(serve.Handler, "house", house):
            status, _, _ = self.fetch("/api/house/open", b"{}")
            self.assertTrue(done.wait(5), NEVER_FINISHED)
        self.assertEqual(status, 200)
        self.assertEqual(seen, [(False, "code moved since start; the restart waits: a house call in flight")])
        self.assertEqual(restart.due(), (True, None))


class StampTest(unittest.TestCase):
    """`restart.stamp` and `restart.moved` (c-742 r1.F8), which the fetch role's own restart
    reads: on a real config file, with only the checkout's head stood in for."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config = Path(tmp.name) / "config.toml"
        self.config.write_text("[keel]\n")
        os.utime(self.config, ns=(1_000_000_000, 1_000_000_000))
        self.cfg = mock.Mock(root=Path(tmp.name), source=self.config)
        self.head = OLD
        patch = mock.patch("keel.merging.code_head", lambda root: self.head)
        patch.start()
        self.addCleanup(patch.stop)
        self.started = restart.stamp(self.cfg)

    def moved(self) -> str | None:
        return restart.moved(self.cfg, self.started)

    def test_the_stamp_is_the_head_and_the_config_file_as_it_stands(self):
        self.assertEqual(self.started, (OLD, (1_000_000_000, len("[keel]\n"))))
        self.assertIsNone(self.moved(), "nothing moved")

    def test_a_new_head_is_moved_code(self):
        self.head = NEW
        self.assertEqual(self.moved(), "code")

    def test_a_config_touched_or_grown_is_a_moved_config(self):
        os.utime(self.config, ns=(2_000_000_000, 2_000_000_000))
        self.assertEqual(self.moved(), "config", "touched: the same bytes at another time")
        self.config.write_text("[keel]\npoll_seconds = 5\n")
        os.utime(self.config, ns=(1_000_000_000, 1_000_000_000))
        self.assertEqual(self.moved(), "config", "grown: another size at the same time")

    def test_code_is_said_before_config_when_both_moved(self):
        self.head = NEW
        os.utime(self.config, ns=(2_000_000_000, 2_000_000_000))
        self.assertEqual(self.moved(), "code")

    def test_what_cannot_be_read_is_unknown_and_unknown_is_never_moved(self):
        self.config.unlink()
        self.assertEqual(restart.stamp(self.cfg), (OLD, None))
        self.assertIsNone(self.moved(), "a config that is gone is not a moved one")
        self.head = None
        self.assertIsNone(self.moved(), "a head git could not say is not a moved one")
        # ... and a process that started not knowing never restarts on what it then learns
        self.started = restart.stamp(self.cfg)
        self.head = NEW
        self.config.write_text("[keel]\n")
        self.assertIsNone(self.moved())

    def test_a_config_with_no_file_behind_it_has_no_stamp(self):
        self.cfg.source = None
        self.assertEqual(restart.stamp(self.cfg), (OLD, None))


if __name__ == "__main__":
    unittest.main()
