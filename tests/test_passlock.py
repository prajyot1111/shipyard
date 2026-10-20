"""One drain pass at a time per install (c-734 fix check; keel/passlock.py).

A tell asks for a `drain --once` pass of its own (`pausewake.ask_pass`), beside the loop's
pass, so passes could overlap or stack. Every pass now holds a lock on
`<state>/drain-pass.lock`. An unscoped pass that finds it held does nothing and says so in the
log, and the loop runs its next pass on its next tick. A card-scoped pass (Retry,
create-and-start, the landing) waits for it, and when the wait runs out fails plainly, never
skipping silently."""

import errno
import io
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from keel import actions, cli, drain, passlock, pausewake
from keel.board import open_board
from tests.helpers import make_config


class Stop(Exception):
    pass


class LockCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = make_config(Path(tmp.name))
        self.logged = []
        patch = mock.patch.object(drain, "log", side_effect=lambda cfg, text: self.logged.append(text))
        patch.start()
        self.addCleanup(patch.stop)
        passlock.said.clear()
        self.addCleanup(passlock.said.clear)

    def hold(self):
        """Another pass holding the lock until the returned release is called."""
        holder = passlock.held(self.cfg)
        self.assertTrue(holder.__enter__())
        return lambda: holder.__exit__(None, None, None)


class UnscopedTest(LockCase):
    def test_two_passes_started_together_only_one_runs_its_steps(self):
        inside, release, ran = threading.Event(), threading.Event(), []

        def steps(*args):
            ran.append(args)
            inside.set()
            release.wait(10)
            return {"houses": 0}

        with mock.patch.object(drain, "one_pass", side_effect=steps):
            first = threading.Thread(target=drain.once, args=(self.cfg,))
            first.start()
            self.assertTrue(inside.wait(10))
            second = drain.once(self.cfg)
            release.set()
            first.join(10)
        self.assertEqual(len(ran), 1, "the second pass ran none of its steps")
        self.assertEqual(second, {"skipped": passlock.SKIPPED})
        self.assertEqual(drain.summary_line(second), f"drain: {passlock.SKIPPED}")

    def test_ask_pass_just_starts_its_pass_which_skips_harmlessly(self):
        """No peek at the lock (a peek takes it for a moment, and could make the loop's own
        pass skip): the pass is started, and as an unscoped pass it skips while one runs."""
        from keel import kick
        with mock.patch.object(kick, "held_by_another", return_value=True), \
                mock.patch("subprocess.Popen"), \
                mock.patch.object(passlock.fcntl, "flock") as flock:
            self.assertTrue(pausewake.ask_pass(self.cfg))
        flock.assert_not_called()       # the lock is free, and still not touched
        release = self.hold()
        with mock.patch.object(kick, "held_by_another", return_value=True), \
                mock.patch("subprocess.Popen") as started, \
                mock.patch.object(drain, "one_pass") as steps:
            self.assertTrue(pausewake.ask_pass(self.cfg))
            self.assertEqual(started.call_args.args[0][1:], ["drain", "--once"])
            self.assertEqual(drain.once(self.cfg), {"skipped": passlock.SKIPPED})
        release()
        steps.assert_not_called()

    def test_the_loop_still_runs_after_a_skipped_pass(self):
        """The loop's own first pass finds a pass under way and is skipped; its next tick runs."""
        release = self.hold()
        ticks = []

        def rest(cfg, kicks):
            ticks.append(1)
            if len(ticks) == 1:
                release()       # the other pass ends
                return
            raise Stop

        with mock.patch.object(drain, "one_pass", return_value={"houses": 0}) as steps, \
                mock.patch.object(drain, "rest", side_effect=rest), \
                mock.patch.object(drain.merging, "code_head", return_value="abc"), \
                mock.patch.object(drain, "config_stamp", return_value=None), \
                mock.patch.object(drain, "packs_head", return_value=None), \
                mock.patch.object(drain, "code_moved", return_value=False), \
                mock.patch.object(drain, "config_moved", return_value=False), \
                mock.patch.object(drain, "packs_moved", return_value=False), \
                mock.patch.object(drain.restart, "started"), \
                mock.patch.object(drain, "announce"), \
                mock.patch.object(drain.kick.Inbox, "open", return_value=None), \
                self.assertRaises(Stop):
            drain.run(self.cfg)
        self.assertEqual(steps.call_count, 1, "the skipped pass ran nothing, the next ran")
        passes = [line for line in self.logged if line.startswith("drain: ")]
        self.assertTrue(passes[0].startswith(f"drain: {passlock.SKIPPED}"), passes)
        self.assertTrue(passes[1].startswith("drain: houses=0"), passes)


class CardScopedTest(LockCase):
    def run_keel(self, cfg, argv, timeout=actions.SLOW_SECONDS):
        """`actions.run_keel`, with the keel command parsed and run in this process."""
        self.assertEqual(argv[:3], ["drain", "--once", "--card"])
        args = cli.build_role_parser().parse_args(argv)
        err = io.StringIO()
        with redirect_stderr(err):
            code = cli.role_drain(cfg, args)
        if code != 0:
            raise actions.ActionError(err.getvalue().strip().splitlines()[-1])
        return ""

    def test_queue_landing_under_a_held_lock_returns_at_once(self):
        """Approve outcome's landing only nudges the drain (`--no-wait`): with another pass
        running it skips at once, the tap returns now, and the queued relay is the next pass's."""
        release = self.hold()
        try:
            with mock.patch.object(drain, "one_pass") as steps, \
                    mock.patch.object(actions, "run_keel", side_effect=self.run_keel) as ran, \
                    mock.patch.object(actions, "run_kb") as kb, \
                    mock.patch.object(actions, "pinned_sha", return_value="a" * 40), \
                    mock.patch.object(actions, "landing_note", return_value="queued to land"):
                began = time.monotonic()
                done = actions.queue_landing(self.cfg, {"id": "c-7"}, "")
                took = time.monotonic() - began
        finally:
            release()
        self.assertLess(took, 5, "the tap returns now, not after the 90 s wait")
        self.assertIn("--no-wait", ran.call_args.args[1])
        steps.assert_not_called()
        self.assertEqual(kb.call_args_list[0].args[1][:3], ["relay", "c-7", "land"], "queued for the next pass")
        self.assertEqual(done["relayed"], "land")
        self.assertIn(f"drain: {passlock.SKIPPED} (once)", self.logged)

    def test_a_card_pass_waits_for_a_held_lock_and_then_runs(self):
        release = self.hold()
        out = {}
        with mock.patch.object(drain, "one_pass", return_value={"houses": 0}) as steps:
            waiting = threading.Thread(target=lambda: out.update(got=drain.once(self.cfg, card="c-1")))
            waiting.start()
            waiting.join(1)
            self.assertTrue(waiting.is_alive(), "still waiting for the other pass")
            steps.assert_not_called()
            release()
            waiting.join(10)
        self.assertEqual(out["got"], {"houses": 0})
        self.assertEqual(steps.call_args.args[2], "c-1", "it ran, for its card")

    def test_retry_gives_its_pass_the_wait_and_a_full_pass_budget(self):
        """r2.F2: the wait for the lock comes on top of the pass's own SLOW_SECONDS, so a
        pass that waited is not killed mid-pass by the deck's timeout."""
        with open_board(self.cfg) as board:
            card = board.create("personal", "Retry me", brief="", actor="human")
            board.stage(card, "assigned", "human")
        with mock.patch.object(actions, "run_keel", return_value="") as ran, \
                mock.patch.object(actions, "run_kb"), open_board(self.cfg) as board:
            actions.act_retry(self.cfg, board, {"verb": "retry", "id": card})
        self.assertEqual(ran.call_args.args[1][:3], ["drain", "--once", "--card"])
        self.assertEqual(ran.call_args.kwargs.get("timeout"), passlock.WAIT_SECONDS + actions.SLOW_SECONDS)

    def test_create_and_start_gives_its_pass_the_wait_and_a_full_pass_budget(self):
        self.cfg.drain_paused = True        # the one case create-and-start runs a pass itself
        kb = mock.Mock(side_effect=lambda cfg, argv, **kw: {"id": "c-1"} if argv[0] == "create" else {})
        with mock.patch.object(actions, "run_keel", return_value="") as ran, \
                mock.patch.object(actions, "run_kb", kb), open_board(self.cfg) as board:
            actions.act(self.cfg, board, {"verb": "create", "space": "personal", "title": "t", "start": True})
        self.assertEqual(ran.call_args.args[1], ["drain", "--once", "--card", "c-1"])
        self.assertEqual(ran.call_args.kwargs.get("timeout"), passlock.WAIT_SECONDS + actions.SLOW_SECONDS)

    def test_a_wait_that_runs_out_is_a_failure_retry_reports(self):
        """Retry's `keel drain --once --card` with the lock held past the wait: the CLI exits
        non-zero with a sentence, and act_retry raises it rather than report success."""
        with open_board(self.cfg) as board:
            card = board.create("personal", "Retry me", brief="", actor="human")
            board.stage(card, "assigned", "human")

        release = self.hold()
        try:
            with mock.patch.object(passlock, "WAIT_SECONDS", 0.3), \
                    mock.patch.object(drain, "one_pass") as steps, \
                    mock.patch.object(actions, "run_keel", side_effect=self.run_keel), \
                    mock.patch.object(actions, "run_kb"), \
                    open_board(self.cfg) as board, \
                    self.assertRaises(actions.ActionError) as failed:
                actions.act_retry(self.cfg, board, {"verb": "retry", "id": card})
        finally:
            release()
        steps.assert_not_called()
        self.assertIn(f"the drain pass for {card} did not run", str(failed.exception))
        self.assertIn("another pass held the pass lock", str(failed.exception))


class UnusableTest(LockCase):
    def test_a_flock_error_other_than_held_runs_the_pass_unlocked_and_says_so_once(self):
        unsupported = OSError(errno.ENOLCK, "No locks available")
        with mock.patch.object(passlock.fcntl, "flock", side_effect=unsupported), \
                mock.patch.object(drain, "one_pass", return_value={"houses": 0}) as steps:
            drain.once(self.cfg)
            drain.once(self.cfg, card="c-1")
        self.assertEqual(steps.call_count, 2, "both passes ran, unguarded")
        said = [line for line in self.logged if "pass lock cannot be used" in line]
        self.assertEqual(len(said), 1, said)
        self.assertIn("No locks available", said[0])

    def test_a_lock_file_that_cannot_be_opened_lets_the_pass_run(self):
        with mock.patch.object(passlock.os, "open", side_effect=PermissionError("read-only")), \
                mock.patch.object(drain, "one_pass", return_value={"houses": 0}) as steps:
            drain.once(self.cfg)
        steps.assert_called_once()


if __name__ == "__main__":
    unittest.main()
