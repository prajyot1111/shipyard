"""Rotating a house on demand (R6, c-436, decision N9): checkpoint, a fresh session,
rehydrate, the card's session moved to it, the old one stopped, a note on the card."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from keel import actions, drain, house, rotate
from keel.board import Board, Refused
from tests.helpers import SESSION, FakeHarness, FakeMachine, background_row, make_config

FRESH = "f00dcafe-0000-4000-8000-000000000001"


class RotateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.cfg.host = "box"
        self.cfg.rotate = True             # rotation is dormant unless switched on
        self.board = Board(self.cfg.db_path, switches={"rotate"})
        self.addCleanup(self.board.close)
        self.fake = FakeHarness()
        self.fake.stops = []
        for module in (house, rotate, drain):
            patch = mock.patch.object(module, "harness", self.fake)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(drain, "machine", FakeMachine())
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(house, "APP_LINK_PAUSE", 0)
        patch.start()
        self.addCleanup(patch.stop)
        self.card = self.board.create("personal", "an errand", brief="look into it", actor="human")
        self.board.stage(self.card, "assigned", "human")
        self.board.claim(self.card, "box", "drain")
        self.board.stage(self.card, "building", "drain")
        self.board.set_session(self.card, SESSION, "drain", bg_id=SESSION[:8])

    def checkpoint(self):
        path = rotate.checkpoint_path(self.cfg, self.card)
        path.write_text("## Summary\n\nhalf way\n")
        future = time.time() + 5
        os.utime(path, (future, future))
        return path


class AskTest(RotateCase):
    def test_the_house_is_asked_for_a_checkpoint_and_the_card_says_so(self):
        rotate.ask(self.cfg, self.board, self.card)
        prompt = self.fake.resumes[0]["prompt"]
        self.assertIn(str(rotate.checkpoint_path(self.cfg, self.card)), prompt)
        self.assertIn("handoff", prompt)
        card = self.board.get(self.card)
        self.assertEqual(card["options"]["rotate"]["state"], rotate.CHECKPOINTING)
        self.assertIn("rotating", self.board.events(self.card)[-1]["text"])

    def test_a_working_house_or_a_held_one_is_not_asked(self):
        self.fake.rows = [background_row(self.card, SESSION, status="busy")]
        with self.assertRaises(house.Busy):
            rotate.ask(self.cfg, self.board, self.card)
        self.fake.rows = []
        self.board.hold_voice(self.card, 300, stopped=True)
        with self.assertRaises(Refused):
            rotate.ask(self.cfg, self.board, self.card)
        self.assertEqual(self.fake.resumes, [])

    def test_the_checkpoint_turn_is_not_nudged_back_to_work(self):
        """It ends at building without staging, which the Stop hook would otherwise send
        back to work: the one turn that must end where it is."""
        rotate.ask(self.cfg, self.board, self.card)
        self.assertIsNone(self.board.stop_check(self.card, {}))


class AskedCase(RotateCase):
    """A rotation asked, with a start that hands back the fresh session; no tests of its own."""

    def asked(self):
        rotate.ask(self.cfg, self.board, self.card)
        self.fake.start_bg = lambda cwd, prompt, **kw: (self.fake.starts.append(dict(kw, cwd=cwd, prompt=prompt))
                                                        or {"bg_id": FRESH[:8], "session_id": FRESH})


class FinishTest(AskedCase):
    def test_a_written_checkpoint_starts_the_fresh_session_and_retires_the_old(self):
        self.asked()
        path = self.checkpoint()
        self.fake.rows = [background_row(self.card, SESSION, status="idle")]
        self.assertEqual(rotate.upkeep(self.cfg, self.board, self.fake.rows), 1)
        prompt = self.fake.starts[0]["prompt"]
        self.assertIn(str(path), prompt)
        self.assertIn("## The card", prompt, "the fresh session gets the card's brief")
        card = self.board.get(self.card)
        self.assertEqual(card["session_id"], FRESH)
        self.assertNotIn("rotate", card["options"])
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        self.assertIn("rotated", self.board.events(self.card)[-1]["text"])

    def test_nothing_happens_while_the_checkpoint_turn_is_working(self):
        self.asked()
        self.fake.rows = [background_row(self.card, SESSION, status="busy")]
        self.assertEqual(rotate.upkeep(self.cfg, self.board, self.fake.rows), 0)
        self.assertEqual(self.fake.starts, [])

    def test_a_pass_right_after_the_ask_waits_for_the_turn_to_show(self):
        self.asked()
        self.fake.rows = []
        self.assertEqual(rotate.upkeep(self.cfg, self.board, self.fake.rows), 0)
        self.assertEqual(self.board.get(self.card)["options"]["rotate"]["state"], rotate.CHECKPOINTING)

    def test_a_turn_that_ended_with_no_checkpoint_drops_the_rotation(self):
        self.asked()
        self.board.set_fields(self.card, {"options": {"rotate": dict(
            self.board.get(self.card)["options"]["rotate"], at="2026-09-01T00:00:00+00:00")}}, "drain")
        self.fake.rows = [background_row(self.card, SESSION, status="idle")]
        rotate.upkeep(self.cfg, self.board, self.fake.rows)
        self.assertEqual(self.fake.starts, [])
        self.assertNotIn("rotate", self.board.get(self.card)["options"])
        self.assertIn("rotation dropped", self.board.events(self.card)[-1]["text"])

    def test_the_drain_finishes_it_on_its_own_pass(self):
        self.asked()
        self.checkpoint()
        self.fake.rows = [background_row(self.card, SESSION, status="idle")]
        drain.once(self.cfg, board=self.board)
        self.assertEqual(self.board.get(self.card)["session_id"], FRESH)


class FreshTrustTest(RotateCase):
    def test_the_fresh_session_starts_in_a_trusted_cwd(self):
        """Claude Code 2.1.281 refuses `--bg` in an untrusted directory (lane T)."""
        AskedCase.asked(self)
        self.checkpoint()
        claude_json = self.cfg.spaces["personal"].config_dir / ".claude.json"
        seen = []
        start = self.fake.start_bg
        self.fake.start_bg = lambda cwd, prompt, **kw: (
            seen.append(str(cwd) in json.loads(claude_json.read_text())["projects"])
            or start(cwd, prompt, **kw))
        self.fake.rows = [background_row(self.card, SESSION, status="idle")]
        rotate.upkeep(self.cfg, self.board, self.fake.rows)
        self.assertEqual(seen, [True])


class ForkRotationTest(RotateCase):
    """c-730 r2.F2, r2.F4: a fork's review house rotated into a fresh session starts under the
    same flags as its first start (`house.harness_flags`)."""

    def test_a_fork_s_review_house_is_rotated_confined_and_without_its_settings(self):
        from tests.helpers import make_repo
        self.cfg.spaces["personal"].repos["keel"] = make_repo(self.dir / "repo")
        card = self.board.create("personal", "Review: from a fork", repo="keel", actor="human",
                                 options={"kind": "review", "review_key": "keel:12", "pr": 12, "review_fork": True})
        self.board.stage(card, "assigned", "human")
        self.board.set_session(card, SESSION, "drain", bg_id=SESSION[:8])
        rotate.start_fresh(self.cfg, self.board, self.board.get(card), SESSION)
        start = self.fake.starts[-1]
        self.assertEqual((start["setting_sources"], start["restricted"], start["tools"]),
                         ("user", True, house.FORK_REVIEW_TOOLS))


class CancelledTest(AskedCase):
    """Review finding 2: the rotation acts only on the session it asked; anything that moves
    the card on cancels it, and a start that keeps failing ends it, once."""

    def test_a_resume_after_the_ask_cancels_the_rotation(self):
        self.asked()
        house.resume(self.cfg, self.board, self.card, prompt="sent back: do it again")
        self.assertNotIn("rotate", self.board.get(self.card)["options"])
        self.checkpoint()
        self.assertEqual(rotate.upkeep(self.cfg, self.board, []), 0)
        self.assertEqual(self.fake.starts, [])

    def test_a_new_session_after_the_ask_cancels_the_rotation(self):
        self.asked()
        self.checkpoint()
        other = "0ddba11e-0000-4000-8000-000000000002"
        self.board.set_session(self.card, other, "drain", bg_id=other[:8])
        self.fake.rows = [background_row(self.card, other, status="idle")]
        rotate.upkeep(self.cfg, self.board, self.fake.rows)
        self.assertEqual(self.fake.starts, [])
        self.assertEqual(self.fake.stops, [])
        self.assertEqual(self.board.get(self.card)["session_id"], other)
        self.assertNotIn("rotate", self.board.get(self.card)["options"])
        self.assertIn("another session", self.board.events(self.card)[-1]["text"])

    def test_a_start_that_fails_is_tried_once_more_then_ended(self):
        self.asked()
        self.checkpoint()
        tries = []

        def fails(cwd, prompt, **kw):
            tries.append(1)
            raise house.harness.HarnessError("claude exited 1")
        self.fake.start_bg = fails
        self.fake.rows = [background_row(self.card, SESSION, status="idle")]
        for _ in range(4):
            rotate.upkeep(self.cfg, self.board, self.fake.rows)
        self.assertEqual(len(tries), 2)
        card = self.board.get(self.card)
        self.assertNotIn("rotate", card["options"])
        self.assertEqual(card["session_id"], SESSION)
        self.assertIsNotNone(self.board.stop_check(self.card, {}), "the Stop nudge is back")


class SerializedTest(AskedCase):
    """Round 3 finding 2: rotation and resume take one per-card lock around start plus
    set_session, the set is compare-and-swap, and the new session is recorded first."""

    def test_a_resume_waits_while_the_fresh_session_is_being_started(self):
        import threading
        self.asked()
        self.checkpoint()
        self.fake.rows = [background_row(self.card, SESSION, status="idle")]
        seen = {}

        def start(cwd, prompt, **kw):
            other = threading.Thread(target=self.resume_in_thread)
            other.start()
            other.join(timeout=0.5)
            seen["resume_finished_during_start"] = not other.is_alive()
            seen["thread"] = other
            self.fake.starts.append(dict(kw, cwd=cwd, prompt=prompt))
            return {"bg_id": FRESH[:8], "session_id": FRESH}
        self.fake.start_bg = start
        rotate.upkeep(self.cfg, self.board, self.fake.rows)
        seen["thread"].join(timeout=10)
        self.assertFalse(seen["resume_finished_during_start"])
        self.assertEqual(self.fake.resumes[-1]["session_id"], FRESH, "the resume ran after, on the new session")

    def resume_in_thread(self):
        board = Board(self.cfg.db_path)
        try:
            house.resume(self.cfg, board, self.card, prompt="his send back")
        finally:
            board.close()

    def test_the_session_is_set_only_while_it_is_still_the_rotation_s(self):
        self.asked()
        self.checkpoint()
        self.fake.rows = [background_row(self.card, SESSION, status="idle")]
        other = "0ddba11e-0000-4000-8000-000000000002"

        def start(cwd, prompt, **kw):
            self.board.set_session(self.card, other, "drain", bg_id=other[:8])   # a writer without the lock
            return {"bg_id": FRESH[:8], "session_id": FRESH}
        self.fake.start_bg = start
        rotate.upkeep(self.cfg, self.board, self.fake.rows)
        self.assertEqual(self.board.get(self.card)["session_id"], other)
        self.assertIn(FRESH[:8], self.fake.stops, "the session nobody recorded is stopped")
        self.assertNotIn(SESSION[:8], self.fake.stops)

    def test_the_new_session_is_recorded_before_anything_that_can_fail(self):
        self.asked()
        self.checkpoint()
        self.fake.rows = [background_row(self.card, SESSION, status="idle")]
        with mock.patch.object(rotate.sessionorigin, "declare", side_effect=OSError("disk full")):
            rotate.upkeep(self.cfg, self.board, self.fake.rows)
            rotate.upkeep(self.cfg, self.board, self.fake.rows)
        self.assertEqual(self.board.get(self.card)["session_id"], FRESH)
        self.assertEqual(len(self.fake.starts), 1, "a failure after the record never starts a second one")
        self.assertNotIn("rotate", self.board.get(self.card)["options"])


class DormantTest(RotateCase):
    def test_with_the_flag_off_the_deck_refuses_and_no_drain_carries_a_rotate(self):
        self.cfg.rotate = False
        with self.assertRaises(actions.ActionError):
            actions.act(self.cfg, self.board, {"verb": "house.rotate", "id": self.card})
        self.board.relay(self.card, "rotate", "human", "box")
        drain.once(self.cfg, board=self.board)
        self.assertEqual(self.fake.resumes, [])
        self.assertNotIn("rotate", self.board.get(self.card)["options"])
        self.assertNotIn("rotate", drain.carried_kinds(self.cfg))


class DormantUpkeepTest(RotateCase):
    """Round 4 finding 1: with rotation off the drain finishes nothing, and nobody but the
    drain writes `options.rotate`."""

    def test_the_drain_does_not_finish_a_rotation_with_the_flag_off(self):
        rotate.ask(self.cfg, self.board, self.card)
        self.checkpoint()
        self.cfg.rotate = False
        self.fake.rows = [background_row(self.card, SESSION, status="idle")]
        drain.once(self.cfg, board=self.board)
        self.assertEqual(self.fake.starts, [])

    def test_a_house_or_the_cli_cannot_write_options_rotate(self):
        for actor in ("house", "cli", "human", "hook"):
            with self.assertRaises(Refused):
                self.board.set_fields(self.card, {"options": {"rotate": {"state": "checkpointing"}}}, actor)

    def test_no_rotate_relay_can_be_written_with_the_flag_off(self):
        off = Board(self.cfg.db_path)
        self.addCleanup(off.close)
        with self.assertRaises(Refused):
            off.relay(self.card, "rotate", "human", "box")


class DeckTest(RotateCase):
    def test_the_deck_rotates_the_house(self):
        with mock.patch.object(actions, "run_kb", side_effect=lambda cfg, argv, **kw: None):
            actions.act(self.cfg, self.board, {"verb": "house.rotate", "id": self.card})
        self.assertEqual(len(self.fake.resumes), 1)

    def test_a_relayed_rotate_is_carried_by_the_drain_that_holds_the_house(self):
        self.board.relay(self.card, "rotate", "human", "box")
        drain.once(self.cfg, board=self.board)
        self.assertEqual(self.board.get(self.card)["options"]["rotate"]["state"], rotate.CHECKPOINTING)


if __name__ == "__main__":
    unittest.main()
