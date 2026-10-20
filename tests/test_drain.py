"""drain: reconcile against a fake harness, the pause, houses_max, `after`, and the loop."""

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from keel import afresh, authority, deckstate, drain, house, login
from keel.board import Board, Refused
from tests.helpers import SESSION, FakeHarness, FakeMachine, aged, background_row, make_config, signed_in


class DrainCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = signed_in(make_config(self.dir))
        self.board = Board(self.cfg.db_path)
        self.fake = FakeHarness()
        for module in (drain, house, login):
            patch = mock.patch.object(module, "harness", self.fake)
            patch.start()
            self.addCleanup(patch.stop)
        self.machine = FakeMachine()
        patch = mock.patch.object(drain, "machine", self.machine)
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        self.board.close()
        self.tmp.cleanup()

    def once(self, **kwargs) -> dict:
        return drain.once(self.cfg, board=self.board, **kwargs)

    def assigned(self, title="a card", **kwargs) -> str:
        card_id = self.board.create("personal", title, **kwargs)
        self.board.stage(card_id, "assigned", "human")
        return card_id

    def housed(self, stage="building", session=SESSION, autonomy="autonomous", plan_ref=None,
               **kwargs) -> str:
        """A card with a recorded session at `stage` (errand, so no git is needed)."""
        card_id = self.board.create("personal", "housed", autonomy=autonomy, **kwargs)
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, stage, "drain", plan_ref=plan_ref,
                         output_ref="out" if stage == "review" else None)
        self.board.set_session(card_id, session, "drain", bg_id=session[:8])
        return card_id

    def log_text(self) -> str:
        return (self.cfg.logs_dir / "drain.log").read_text()

    def tracking(self, session="77777777-0000-4000-8000-000000000077", status="idle",
                 slices=2) -> str:
        """A housed card at building that has been cut into slices, its own session listed.

        This is c-277 on 2026-09-20: the house split the card, the Stop hook recorded that
        it was tracking, and the session it left behind sat idle in `claude agents`.
        """
        card_id = self.housed(session=session)
        self.board.split(card_id, [{"title": chr(65 + n)} for n in range(slices)], "house")
        self.board.record_hook(card_id, "Stop", {"session_id": session}, {"tracking": True})
        self.fake.rows.append(dict(background_row(card_id, session), status=status))
        return card_id

    def at_gate(self, session, status="idle", **kwargs) -> str:
        """An attended card at planning with its plan delivered, its house listed."""
        card_id = self.housed(stage="planning", autonomy="attended", plan_ref="p.md",
                              session=session, **kwargs)
        self.fake.rows.append(dict(background_row(card_id, session), status=status))
        return card_id

    def dead(self, mark="a", **kwargs) -> str:
        """A card at building whose session no agent row carries: a house that exited."""
        return self.housed(session=f"{mark * 8}-0000-4000-8000-{mark * 12}", **kwargs)


class ReconcileTest(DrainCase):
    FRESH = "f00dcafe-0000-4000-8000-000000000009"

    def used(self, days: int) -> str:
        """A house at building that ended a turn `days` days ago, whose conversation the
        harness now says is gone."""
        card_id = self.housed()
        self.board.record_hook(card_id, "Stop", {"session_id": SESSION})
        aged(self.board, card_id, days)
        self.fake.gone, self.fake.started_as = {SESSION}, self.FRESH
        return card_id

    def test_a_withheld_fresh_start_blocks_that_card_and_the_pass_goes_on_until_his_unblock(self):
        card_id = self.used(5)
        other = self.dead()
        summary = self.once()
        self.assertEqual((summary["blocked"], summary["resumed"], self.fake.starts), (1, 1, []))
        self.assertEqual([r["session_id"] for r in self.fake.resumes], [self.board.get(other)["session_id"]])
        blocked = self.board.get(card_id)["blocked_reason"]
        self.assertIn("was used 5 days ago", blocked)
        self.assertIn(SESSION, blocked)
        self.once()
        self.assertEqual(len([e for e in self.board.events(card_id) if e["kind"] == "block"]), 1,
                         "blocked once: it is his now")
        self.board.unblock(card_id, "human")
        self.once()
        self.assertEqual((len(self.fake.starts), self.board.get(card_id)["session_id"]), (1, self.FRESH))

    def test_his_unblock_reaches_the_fresh_start_even_with_the_automatic_resume_spent(self):
        """c-654 review: with the drain's one resume spent, the pass after his unblock blocked
        the card again as "exited twice", on top of his answer."""
        card_id = self.housed()
        self.board.record_resume(card_id, "drain", "carry on", {"session_id": SESSION, "automatic": True})
        self.board.record_hook(card_id, "Stop", {"session_id": SESSION})
        aged(self.board, card_id, 5)
        self.fake.gone, self.fake.started_as = {SESSION}, self.FRESH
        with self.assertRaises(afresh.Withheld):
            house.resume(self.cfg, self.board, card_id)
        self.board.unblock(card_id, "human")
        self.once()
        card = self.board.get(card_id)
        self.assertEqual((len(self.fake.starts), card["session_id"], card["blocked_reason"]), (1, self.FRESH, None))

    def test_a_fresh_start_that_fails_in_the_drain_s_own_resume_is_a_block_not_a_failed_pass(self):
        card_id = self.housed()
        aged(self.board, card_id, 40)
        self.fake.gone, self.fake.fail = {SESSION}, "claude would not start"
        summary = self.once()
        self.assertEqual(summary["blocked"], 1)
        self.assertIn("claude would not start", self.board.get(card_id)["blocked_reason"])

    def test_a_carried_tap_leaves_the_withheld_block_standing_for_his_unblock(self):
        """c-654 review: the carried resume blocked again on top as a failed resume, and his
        unblock was never read as his answer."""
        card_id = self.used(5)
        self.board.relay(card_id, "resume", "human", self.cfg.host, prompt="carry on")
        self.once()
        newest = [e for e in self.board.events(card_id) if e["kind"] == "block"][-1]
        self.assertEqual((newest["data"].get("withheld"), newest["data"].get("session")), ("afresh", SESSION))
        self.board.unblock(card_id, "human")
        self.board.relay(card_id, "resume", "human", self.cfg.host, prompt="carry on")
        self.once()
        self.assertEqual((len(self.fake.starts), self.board.get(card_id)["session_id"]), (1, self.FRESH))

    def test_a_gone_conversation_is_started_afresh_once_and_blocked_when_that_house_dies_too(self):
        """c-654 review: a fresh start spends the drain's one automatic resume. Before, it
        left no mark, so a fresh house that died in its first seconds was started again on
        every pass, with no block and no bound."""
        card_id = self.housed()
        aged(self.board, card_id, 40)
        fresh = "f00dcafe-0000-4000-8000-000000000009"
        self.fake.gone, self.fake.started_as = {SESSION, fresh}, fresh
        summary = self.once()
        self.assertEqual((summary["resumed"], len(self.fake.starts), self.fake.resumes), (1, 1, []))
        self.assertEqual(self.board.get(card_id)["session_id"], fresh)
        summary = self.once()
        self.assertEqual((summary["resumed"], summary["blocked"]), (0, 1))
        self.assertEqual(len(self.fake.starts), 1, "exactly one start")
        self.assertIn("exited twice", self.board.get(card_id)["blocked_reason"])

    def test_exited_house_is_resumed_once_then_blocked_with_the_stop_message(self):
        card_id = self.housed()
        summary = self.once()
        self.assertEqual((summary["resumed"], summary["blocked"], summary["houses"]), (1, 0, 1))
        self.assertEqual(self.fake.resumes[0]["session_id"], SESSION)
        self.assertEqual(self.board.events(card_id)[-1]["kind"], "resume")
        self.assertIsNone(self.board.get(card_id)["blocked_reason"])
        self.board.record_hook(card_id, "Stop", {"last_assistant_message": "I got halfway, then the tests hung."})
        summary = self.once()
        self.assertEqual((summary["resumed"], summary["blocked"]), (0, 1))
        self.assertEqual(len(self.fake.resumes), 1)
        card = self.board.get(card_id)
        self.assertEqual(card["stage"], "building")
        self.assertIn("exited twice at building", card["blocked_reason"])
        self.assertIn("I got halfway, then the tests hung.", card["blocked_reason"])
        self.assertTrue(card["derived"]["needs_you"])
        self.assertIn([card_id], [[c["id"]] for c in self.board.needs_you()])
        self.assertEqual(self.board.events(card_id)[-1]["actor"], "drain")

    def test_a_house_the_kick_resumed_mid_pass_is_not_resumed_again_by_reconcile(self):
        """c-608 review: the kick thread carries his resume while the pass runs, after the
        pass took its listing and its snapshot of the cards. Reconcile, reading that stale
        snapshot, must not resume the house a second time."""
        card_id = self.housed()
        moved = "99999999-0000-4000-8000-000000000099"
        snapshot = self.board.list_cards

        def listing_then_the_kick(*args, **kwargs):
            cards = snapshot(*args, **kwargs)
            # The kick's carry lands between reconcile's read and its act.
            self.board.set_session(card_id, moved, "drain", bg_id=moved[:8])
            return cards

        with mock.patch.object(self.board, "list_cards", side_effect=listing_then_the_kick):
            counts = drain.reconcile(self.cfg, self.board, [], {"personal"}, drain.MemoryGate(self.cfg))
        self.assertEqual(counts["resumed"], 0)
        self.assertEqual(self.fake.resumes, [])
        self.assertIn(f"reconcile left {card_id} alone", self.log_text())

    def test_a_house_that_exits_after_his_resume_is_put_back_once_more(self):
        """c-605 review: his Resume spent the drain's one automatic resume, so a house that
        exited after it was blocked. Only the drain's own resume counts."""
        card_id = self.housed()
        self.assertEqual(self.once()["resumed"], 1)                # the drain's own
        self.board.record_event(card_id, "resume", "drain", data={"session_id": SESSION})  # his tap
        summary = self.once()
        self.assertEqual((summary["resumed"], summary["blocked"]), (1, 0))
        summary = self.once()
        self.assertEqual((summary["resumed"], summary["blocked"]), (0, 1))

    def test_a_house_he_stopped_is_not_resumed_until_his_resume(self):
        """c-605: the drain resumed a house he had stopped 11 s earlier, as if it had
        exited. His Stop's marked note keeps it down; his Resume's event ends that."""
        card_id = self.housed()
        self.board.note(card_id, "session aaaaaaaa stopped from the deck", "human", mark="human-stop")
        for _ in range(2):
            summary = self.once()
            self.assertEqual((summary["resumed"], summary["blocked"]), (0, 0))
        self.assertEqual(self.fake.resumes, [])
        self.assertIsNone(self.board.get(card_id)["blocked_reason"])
        self.assertTrue(self.board.get(card_id)["derived"]["held_by_stop"], "the deck can say so")
        self.board.record_event(card_id, "resume", "human")      # his Resume, then it exits
        self.assertFalse(self.board.get(card_id)["derived"]["held_by_stop"])
        self.assertFalse(drain.stopped_by_him(self.board, card_id))

    def test_a_house_he_closed_idle_is_not_resumed_by_the_drain_but_his_tap_ends_that(self):
        """c-607: closing an idle house frees its memory, so the drain's resume of an exited
        house passes it over too; it is not his Stop, so nothing says it waits for Resume."""
        card_id = self.housed()
        self.board.note(card_id, "session aaaaaaaa closed while idle", "human", mark="closed-idle")
        for _ in range(2):
            summary = self.once()
            self.assertEqual((summary["resumed"], summary["blocked"]), (0, 0))
        self.assertEqual(self.fake.resumes, [])
        derived = self.board.get(card_id)["derived"]
        self.assertEqual((derived["closed_idle"], derived["held_by_stop"]), (True, False))
        self.assertFalse(drain.stopped_by_him(self.board, card_id))
        self.board.record_event(card_id, "resume", "human")      # his tap resumed it
        self.assertFalse(self.board.get(card_id)["derived"]["closed_idle"])
        self.assertFalse(drain.closed_while_idle(self.board, card_id))

    def test_a_house_he_closed_idle_comes_back_on_his_gate_tap_with_its_conversation(self):
        """c-607: a gate answer and his Resume both reach the house through `house.resume`
        (`actions.resume_with`, `act_resume`); a closed house is resumed, never refused."""
        card_id = self.housed(stage="review", plan_ref="p.md")
        self.board.note(card_id, "closed while idle", "human", mark="closed-idle")
        house.resume(self.cfg, self.board, card_id, prompt="he sent it back: fix the name")
        self.assertEqual([r["session_id"] for r in self.fake.resumes], [SESSION])
        self.assertFalse(self.board.get(card_id)["derived"]["closed_idle"])

    def test_only_he_or_the_drain_marks_a_close(self):
        card_id = self.housed()
        with self.assertRaises(Refused):
            self.board.note(card_id, "closed", "house", mark="closed-idle")

    def test_a_house_that_exited_on_its_own_after_an_older_stop_is_still_resumed(self):
        card_id = self.housed()
        self.board.note(card_id, "stopped", "human", mark="human-stop")
        self.board.set_session(card_id, "bbbbbbbb-0000-4000-8000-000000000009", "drain", bg_id="bbbbbbbb")
        self.assertEqual(self.once()["resumed"], 1)

    def test_only_he_or_the_drain_marks_a_stop(self):
        card_id = self.housed()
        with self.assertRaises(Refused):
            self.board.note(card_id, "stopped", "house", mark="human-stop")

    def test_block_reason_falls_back_to_the_transcript_then_the_logs(self):
        with_transcript = self.housed()
        self.board.record_event(with_transcript, "resume", "drain", data={"automatic": True})
        self.board.record_hook(with_transcript, "SessionEnd", {"transcript_path": "/t.jsonl", "reason": "other"})
        self.fake.said = "from the transcript"
        self.fake.logs_text = "\n".join(f"log line {i}" for i in range(50))
        self.once()
        self.assertIn("from the transcript", self.board.get(with_transcript)["blocked_reason"])
        no_transcript = self.housed(session="bbbbbbbb-0000-4000-8000-000000000003")
        self.board.record_event(no_transcript, "resume", "drain", data={"automatic": True})
        self.fake.said = ""
        self.once()
        reason = self.board.get(no_transcript)["blocked_reason"]
        self.assertIn("log line 49", reason)
        self.assertNotIn("log line 9\n", reason)
        self.assertEqual(self.fake.logs_dir_asked, self.cfg.spaces["personal"].config_dir)

    def test_agents_are_listed_under_every_space_config_dir(self):
        self.once()
        self.assertEqual(self.fake.listed_dirs,
                         [str(space.config_dir) for space in self.cfg.spaces.values()])

    def test_a_listed_house_is_left_alone(self):
        card_id = self.housed()
        self.fake.rows = [background_row(card_id, SESSION)]
        summary = self.once()
        self.assertEqual((summary["resumed"], summary["blocked"], summary["houses"]), (0, 0, 1))
        self.assertEqual(self.fake.resumes, [])

    def test_review_and_an_open_plan_gate_are_never_touched(self):
        at_review = self.housed(stage="review", plan_ref="p.md")
        waiting = self.housed(stage="planning", autonomy="attended", plan_ref="p.md",
                              session="cccccccc-0000-4000-8000-000000000004")
        self.once()
        self.once()
        for card_id in (at_review, waiting):
            card = self.board.get(card_id)
            self.assertIsNone(card["blocked_reason"], card_id)
            self.assertNotIn("resume", [e["kind"] for e in self.board.events(card_id)])
        self.assertEqual(self.fake.resumes, [])

    def test_a_house_that_died_before_delivering_its_plan_is_resumed(self):
        card_id = self.housed(stage="planning", autonomy="attended",
                              session="dddddddd-0000-4000-8000-000000000005")
        self.once()
        self.assertEqual(self.fake.resumes[0]["session_id"], "dddddddd-0000-4000-8000-000000000005")
        self.assertEqual(self.fake.resumes[0]["prompt"],
                         "continue from where you stopped; the card is still at planning")
        self.assertEqual(self.board.get(card_id)["stage"], "planning")

    def test_an_idle_tracking_parent_is_never_resumed_nudged_or_blocked(self):
        """The dead-house path must not reach a card whose children carry its stage.

        c-277 on the box, 07:16:05Z 2026-09-20: its idle session had just been stopped by
        hand, and the very next pass read `building` (a slice was building), found no agent
        row for the session, and recorded `block drain "house exited twice at building; it
        last said: ..."`. The sequence below is that one: the `split` recorded, a Stop from
        the card's own session after it, a child at building, and the session gone."""
        self.cfg.drain_paused = True        # the slices are startable; these passes are reconcile
        card_id = self.tracking()
        child = self.board.children(card_id)[0]["id"]
        self.board.stage(child, "building", "drain")
        self.assertEqual(self.board.get(card_id)["derived"]["parent_stage"], "building")
        self.fake.rows = []                 # its session is gone from the listing as well
        self.once()
        self.once()
        card = self.board.get(card_id)
        self.assertEqual(self.fake.resumes, [])
        self.assertIsNone(card["blocked_reason"])
        self.assertNotIn("resume", [e["kind"] for e in self.board.events(card_id)])
        self.assertNotIn("block", [e["kind"] for e in self.board.events(card_id)])
        self.assertEqual(drain.house_ids(self.board, self.fake.rows), set())

    def test_archived_and_sessionless_cards_are_skipped(self):
        archived = self.housed(options={"archived": True})
        no_session = self.board.create("personal", "no session")
        self.board.stage(no_session, "assigned", "human")
        self.board.stage(no_session, "building", "drain")
        self.once()
        self.assertEqual(self.fake.resumes, [])
        self.assertIsNone(self.board.get(archived)["blocked_reason"])


class RetireTrackingTest(DrainCase):
    """A tracking card's own session has nothing left to do, so the drain ends it once."""

    def setUp(self):
        super().setUp()
        self.cfg.drain_paused = True        # the slices are startable; this is about the parent

    def notes(self, card_id: str) -> list[str]:
        return [e["text"] for e in self.board.events(card_id) if e["kind"] == "note"]

    def test_an_idle_tracking_session_is_stopped_once_and_noted(self):
        card_id = self.tracking()
        self.assertEqual(self.once()["retired"], 1)
        self.assertEqual(self.fake.stops, ["77777777"])
        self.assertEqual(self.notes(card_id),
                         ["the tracking card's idle session 77777777 stopped; its slices carry the work"])
        self.assertEqual(self.once().get("retired", 0), 0, "once per session, not every pass")
        self.assertEqual(self.fake.stops, ["77777777"])

    def test_the_pass_after_the_retire_does_not_read_it_as_a_house_that_exited(self):
        """The drain stopping the session itself is the same fact the dead-house path reads:
        no agent row at `building`. By hand it produced the c-277 block (2026-09-20); done
        by the drain it must not, on that pass or any after it."""
        card_id = self.tracking()
        self.board.stage(self.board.children(card_id)[0]["id"], "building", "drain")
        self.assertEqual(self.once()["retired"], 1)
        self.fake.rows = []                 # `claude stop` took the row out of the listing
        self.once()
        self.once()
        card = self.board.get(card_id)
        self.assertIsNone(card["blocked_reason"])
        self.assertEqual(self.fake.resumes, [])
        self.assertEqual(self.fake.stops, ["77777777"])

    def test_a_busy_tracking_session_is_left_alone(self):
        self.tracking(status="busy")
        self.assertEqual(self.once().get("retired", 0), 0)
        self.assertEqual(getattr(self.fake, "stops", []), [])

    def test_a_tracking_session_resumed_mid_turn_is_left_alone(self):
        card_id = self.tracking()
        self.board.record_event(card_id, "resume", "drain")
        self.assertEqual(self.once().get("retired", 0), 0)
        self.assertEqual(getattr(self.fake, "stops", []), [])

    def test_a_session_the_harness_no_longer_lists_is_not_stopped(self):
        self.tracking()
        self.fake.rows = []
        self.assertEqual(self.once().get("retired", 0), 0)
        self.assertEqual(getattr(self.fake, "stops", []), [])

    def test_a_plain_house_at_building_is_never_retired(self):
        card_id = self.housed()
        self.fake.rows = [background_row(card_id, SESSION)]
        self.assertEqual(self.once().get("retired", 0), 0)
        self.assertEqual(getattr(self.fake, "stops", []), [])

    def test_a_failed_stop_is_noted_and_not_tried_again(self):
        card_id = self.tracking()
        self.fake.stop_fails = True
        self.assertEqual(self.once().get("retired", 0), 0)
        self.assertIn("could not be stopped", self.notes(card_id)[0])
        self.once()
        self.assertEqual(self.fake.stops, ["77777777"])


class StartTest(DrainCase):
    def test_paused_drain_starts_nothing_unless_the_card_is_named(self):
        self.cfg.drain_paused = True
        first, second = self.assigned("first"), self.assigned("second")
        summary = self.once()
        self.assertEqual((summary["started"], summary["paused"]), (0, True))
        self.assertEqual(self.fake.starts, [])
        summary = self.once(card=second)
        self.assertEqual(summary["started"], 1)
        self.assertEqual(self.fake.starts[0]["name"], second)
        self.assertEqual(self.board.get(second)["stage"], "building")
        self.assertEqual(self.board.get(first)["stage"], "assigned")
        inbox = self.board.create("personal", "not assigned")
        with self.assertRaises(Refused):
            self.once(card=inbox)

    def test_houses_max_counts_listed_houses_and_starts_oldest_first(self):
        self.cfg.houses_max = 2
        running = self.housed()
        self.fake.rows = [background_row(running, SESSION),
                          {"kind": "interactive", "name": "cloud-ab", "sessionId": "x"}]
        first, second = self.assigned("older"), self.assigned("newer")
        summary = self.once()
        self.assertEqual((summary["houses"], summary["started"]), (2, 1))
        self.assertEqual([s["name"] for s in self.fake.starts], [first])
        self.assertEqual(self.board.get(second)["stage"], "assigned")
        self.assertIn("house pool full at 2", self.log_text())

    def test_a_review_card_fills_its_own_pool_and_leaves_the_build_pool_alone(self):
        """`options.slot = review` counts against `reviews_max`, and only against it."""
        self.cfg.houses_max, self.cfg.reviews_max = 1, 1
        build = self.assigned("a build")
        first = self.assigned("first review", options={"slot": "review"})
        second = self.assigned("second review", options={"slot": "review"})
        summary = self.once()
        self.assertEqual([s["name"] for s in self.fake.starts], [build, first])
        self.assertEqual((summary["houses"], summary["reviews"], summary["started"]), (1, 1, 2))
        self.assertEqual(self.board.get(second)["stage"], "assigned")
        self.assertIn("review pool full at 1", self.log_text())

    def test_a_full_review_pool_does_not_hold_up_a_build_behind_it(self):
        self.cfg.houses_max, self.cfg.reviews_max = 2, 0
        review = self.assigned("a review", options={"slot": "review"})
        build = self.assigned("a build behind it")
        self.assertEqual(self.once()["started"], 1)
        self.assertEqual([s["name"] for s in self.fake.starts], [build])
        self.assertEqual(self.board.get(review)["stage"], "assigned")

    def test_a_live_review_house_counts_against_the_review_pool_only(self):
        self.cfg.houses_max, self.cfg.reviews_max = 1, 1
        running = self.housed(options={"slot": "review"})
        self.fake.rows = [background_row(running, SESSION)]
        waiting = self.assigned("another review", options={"slot": "review"})
        build = self.assigned("a build")
        summary = self.once()
        self.assertEqual([s["name"] for s in self.fake.starts], [build])
        self.assertEqual((summary["houses"], summary["reviews"]), (1, 1))
        self.assertEqual(self.board.get(waiting)["stage"], "assigned")

    def test_an_idle_house_at_its_plan_gate_holds_no_slot_and_a_third_card_starts(self):
        self.cfg.houses_max = 2
        self.fake.rows = []
        self.at_gate("11111111-0000-4000-8000-000000000011")
        self.at_gate("22222222-0000-4000-8000-000000000012")
        third = self.assigned("third")
        summary = self.once()
        self.assertEqual([s["name"] for s in self.fake.starts], [third])
        self.assertEqual((summary["houses"], summary["started"]), (1, 1))

    def test_an_idle_gate_house_beside_a_building_one_leaves_room_for_one_more(self):
        self.cfg.houses_max = 2
        building = self.housed()
        self.fake.rows = [background_row(building, SESSION)]
        self.at_gate("11111111-0000-4000-8000-000000000011")
        first, second = self.assigned("older"), self.assigned("newer")
        summary = self.once()
        self.assertEqual([s["name"] for s in self.fake.starts], [first])
        self.assertEqual(summary["houses"], 2)
        self.assertEqual(self.board.get(second)["stage"], "assigned")
        self.assertIn("house pool full at 2", self.log_text())

    def test_a_busy_house_at_its_plan_gate_still_fills_the_pool(self):
        """Nudged, or in a discussion, the house is working: it keeps its slot."""
        self.cfg.houses_max = 2
        self.fake.rows = []
        self.at_gate("11111111-0000-4000-8000-000000000011", status="busy")
        self.at_gate("22222222-0000-4000-8000-000000000012", status="busy")
        waiting = self.assigned("waits")
        summary = self.once()
        self.assertEqual((summary["houses"], summary["started"]), (2, 0))
        self.assertEqual(self.board.get(waiting)["stage"], "assigned")
        self.assertIn("house pool full at 2", self.log_text())

    def test_a_review_pool_card_at_its_gate_counts_only_while_busy(self):
        self.cfg.houses_max, self.cfg.reviews_max = 1, 1
        self.fake.rows = []
        gate = self.at_gate("11111111-0000-4000-8000-000000000011", options={"slot": "review"})
        first = self.assigned("a review", options={"slot": "review"})
        summary = self.once()
        self.assertEqual([s["name"] for s in self.fake.starts], [first])
        self.assertEqual(summary["reviews"], 1)
        self.fake.rows = [dict(background_row(gate, "11111111-0000-4000-8000-000000000011"), status="busy")]
        second = self.assigned("another review", options={"slot": "review"})
        self.board.stage(first, "review", "house", plan_ref="p.md", output_ref="out")
        summary = self.once()
        self.assertEqual((summary["reviews"], summary["started"]), (1, 0))
        self.assertEqual(self.board.get(second)["stage"], "assigned")

    def test_a_house_resumed_at_its_gate_counts_until_its_turn_ends(self):
        """Send back mints a new session the harness may not list as busy yet."""
        self.cfg.houses_max = 1
        self.fake.rows = []
        old, new = "11111111-0000-4000-8000-000000000011", "33333333-0000-4000-8000-000000000013"
        gate = self.at_gate(old)
        self.board.record_hook(gate, "Stop", {"session_id": old})
        self.board.record_event(gate, "resume", "drain")
        self.board.set_session(gate, new, "drain", bg_id=new[:8])
        self.board.record_hook(gate, "SessionEnd", {"session_id": old, "reason": "other"})
        waiting = self.assigned("waits")
        self.assertEqual(self.once()["started"], 0, "the superseded session ending is not this turn")
        self.board.record_hook(gate, "Stop", {"session_id": new})
        self.assertEqual(self.once()["started"], 1)
        self.assertEqual(self.board.get(waiting)["stage"], "building")

    def test_an_idle_tracking_parent_holds_no_slot_and_the_next_card_starts(self):
        """The bug as it happened: an idle parent at `building` held one of the box's two
        house slots and the drain logged `house pool full at 2` every pass (2026-09-20)."""
        self.cfg.houses_max = 2
        self.fake.rows = []
        building = self.housed()
        self.fake.rows.append(background_row(building, SESSION))
        parent = self.tracking()
        summary = self.once()
        self.assertNotIn(parent, drain.house_ids(self.board, self.fake.rows))
        self.assertEqual((summary["houses"], summary["started"]), (2, 1))
        self.assertEqual(self.fake.starts[0]["name"], self.board.children(parent)[0]["id"],
                         "the slot the parent was holding goes to its own first slice")

    def test_a_busy_tracking_parent_still_holds_its_slot(self):
        """Its own session is working (a resume, a drop-in), so it is a house like any other."""
        self.cfg.houses_max = 1
        self.fake.rows = []
        self.tracking(status="busy")
        waiting = self.assigned("waits")
        summary = self.once()
        self.assertEqual((summary["houses"], summary["started"]), (1, 0))
        self.assertEqual(self.board.get(waiting)["stage"], "assigned")
        self.assertIn("house pool full at 1", self.log_text())

    def test_a_tracking_parent_resumed_mid_turn_holds_its_slot(self):
        """A resume with no Stop of its own after it is a turn in flight, as at a plan gate."""
        self.cfg.houses_max = 1
        self.fake.rows = []
        card_id = self.tracking()
        self.board.record_event(card_id, "resume", "drain")
        waiting = self.assigned("waits")
        self.assertEqual(self.once()["started"], 0)
        self.assertEqual(self.board.get(waiting)["stage"], "assigned")

    def test_after_waits_for_the_sibling_to_reach_review(self):
        first = self.assigned("first")
        second = self.assigned("second", after=first)
        self.assertEqual(self.once()["started"], 1)
        self.assertEqual([s["name"] for s in self.fake.starts], [first])
        self.fake.rows = [background_row(first, SESSION)]
        self.assertEqual(self.once()["started"], 0)
        self.board.stage(first, "review", "house", plan_ref="p.md", output_ref="branch")
        self.assertEqual(self.once()["started"], 1)
        self.assertEqual(self.fake.starts[1]["name"], second)

    def test_next_puts_a_card_first_but_never_ahead_of_its_wait(self):
        from keel import tree
        self.cfg.houses_max = 1
        first = self.assigned("first")
        blocked = self.assigned("waits", after=first)
        later = self.assigned("later")
        tree.to_front(self.board, blocked, "human")
        tree.to_front(self.board, later, "human")
        self.assertEqual(self.once()["started"], 1)
        self.assertEqual([s["name"] for s in self.fake.starts], [later])
        self.assertEqual(self.board.get(blocked)["stage"], "assigned")

    def test_only_served_spaces_start_and_a_failed_start_does_not_end_the_pass(self):
        work = self.board.create("work", "work card")
        self.board.stage(work, "assigned", "human")
        personal = self.assigned("personal card")
        self.assertEqual(self.once(spaces=["personal"])["started"], 1)
        self.assertEqual(self.fake.starts[0]["name"], personal)
        self.fake.fail = "no binary"
        again = self.assigned("another")
        summary = self.once(spaces=["personal"])
        self.assertEqual(summary["started"], 0)
        self.assertIn("house failed to start", self.board.get(again)["blocked_reason"])
        self.assertIn(f"failed to start {again}", self.log_text())


class OneHousePerCardTest(DrainCase):
    """Retry's own `keel drain --once --card` and the looping drain on the SAME machine both
    passed the claim (a same-host claim is a no-op) and started two houses on one card
    (c-601, e2e bug 2). Whichever path starts first, the other starts nothing."""

    def test_two_starters_on_one_host_start_one_house(self):
        import threading
        import time as clock
        card_id = self.assigned()
        entered = threading.Event()

        def slow_start(name):
            entered.set()
            clock.sleep(0.4)        # the first start is mid-flight, the card still at assigned

        self.fake.on_start = slow_start
        results = {}

        def starter(key):
            with Board(self.cfg.db_path) as board:
                results[key] = drain.start_one(self.cfg, board, board.get(card_id))

        first = threading.Thread(target=starter, args=("loop",))
        first.start()
        self.assertTrue(entered.wait(5))
        second = threading.Thread(target=starter, args=("retry",))
        second.start()
        first.join(10)
        second.join(10)
        self.assertEqual(len(self.fake.starts), 1, "one house per card")
        self.assertEqual(sorted(results.values()), [False, True])
        self.assertEqual(self.board.get(card_id)["stage"], "building")
        self.assertIsNone(self.board.get(card_id)["blocked_reason"], "the loser blocks nothing")


    def test_a_card_whose_house_is_still_listed_live_is_not_started_again(self):
        """c-605: Retry reset a card whose house was still live and a second session
        started beside it. The start refuses under the card's lock, says so once on the
        card, and stops nothing."""
        card_id = self.housed()
        self.fake.rows = [background_row(card_id, SESSION)]
        self.board.stage(card_id, "assigned", "human", note="retry from the deck")
        for _ in range(2):
            self.assertFalse(drain.start_one(self.cfg, self.board, self.board.get(card_id)))
        self.assertEqual(self.fake.starts, [])
        self.assertEqual(getattr(self.fake, "stops", []), [])
        notes = [e["text"] for e in self.board.events(card_id) if e["kind"] == "note"]
        self.assertEqual(sum("is still live" in text for text in notes), 1, notes)
        self.fake.rows = []                  # it ended: now the start goes ahead
        self.assertTrue(drain.start_one(self.cfg, self.board, self.board.get(card_id)))


class OldHostNameTest(DrainCase):
    def test_a_card_claimed_and_relayed_under_an_old_name_is_started_and_carried(self):
        """c-622 r1.F1: one machine, so a claim or a relay naming another host (the box, or
        this machine before a rename) is this machine's: the card starts, the relay is carried."""
        card_id = self.assigned()
        self.board.claim(card_id, "box", "drain")
        self.board.relay(card_id, "start", "human", "box")
        self.once()
        self.assertEqual([start["name"] for start in self.fake.starts], [card_id])
        self.assertEqual(self.board.get(card_id)["stage"], "building")
        self.assertEqual(self.board.pending_relays(card_id), [], "the relay was carried")


class DoneRelayTest(DrainCase):
    def test_a_resume_queued_before_done_is_dropped_with_a_note_not_a_block(self):
        """c-601 review: the tap was carried into `house.refuse_if_done` and blocked the done
        card with failed-resume."""
        card_id = self.housed(stage="review", plan_ref="p.md")
        self.board.relay(card_id, "resume", "human", self.cfg.host, prompt="carry on")
        self.board.stage(card_id, "done", "human")
        self.once()
        card = self.board.get(card_id)
        self.assertIsNone(card["blocked_reason"])
        carried = [e for e in self.board.events(card_id) if e["kind"] == "carried"]
        self.assertEqual(carried[-1]["data"]["outcome"], "superseded")
        notes = [e["text"] for e in self.board.events(card_id) if e["kind"] == "note"]
        self.assertTrue(any("was dropped" in n for n in notes), notes)
        self.assertEqual(self.fake.resumes, [])


class HeldApproveTest(DrainCase):
    """c-604, from the sandbox: Approve plan on a working house was held; the Stop's nudge
    at building sent the house on without his prompt, and the held tap arrived 97 s later
    with the card at review. His tap goes first, and a stale one is refused with a note."""

    def approved_while_working(self) -> str:
        card_id = self.housed(stage="planning", autonomy="attended", plan_ref="p.md")
        self.board.approve(card_id, "plan", "human", relay={"to": self.cfg.host, "prompt": "go, and keep X"})
        self.assertEqual(self.board.get(card_id)["stage"], "building")
        return card_id

    def test_the_stop_nudge_waits_for_his_held_tap(self):
        card_id = self.approved_while_working()
        self.assertIsNone(self.board.stop_check(card_id, {"hook_event_name": "Stop"}))
        hooks = [e for e in self.board.events(card_id) if e["kind"] == "hook"]
        self.assertTrue(hooks[-1]["data"].get("tap_waiting"))
        self.assertEqual(self.board.stop_blocks(card_id), 0, "no nudge spent")
        from keel import ending
        self.assertIsNone(ending.check(self.cfg, self.board, card_id, {}), "no turn-end rule either")
        self.once()
        self.assertEqual(self.board.pending_relays(card_id), [], "the tap was carried")
        self.assertEqual(self.board.stop_check(card_id, {})["decision"], "block",
                         "once his tap is carried the nudge is back")

    def test_a_tap_whose_card_moved_on_is_refused_with_a_note(self):
        card_id = self.approved_while_working()
        self.assertEqual(self.board.pending_relays(card_id)[0]["stage"], "building")
        self.board.stage(card_id, "review", "house", output_ref="out")
        self.once()
        carried = [e for e in self.board.events(card_id) if e["kind"] == "carried"]
        self.assertEqual(carried[-1]["data"]["outcome"], "superseded")
        notes = [e["text"] for e in self.board.events(card_id) if e["kind"] == "note"]
        self.assertTrue(any("moved from building to review" in n for n in notes), notes)
        self.assertEqual(self.fake.resumes, [])


class HeldTapReviewTest(DrainCase):
    """c-604 review: the hold yields only the nudge, only to this house's own fresh tap, and
    only a gate's tap is refused when the stage moved."""

    def test_a_tap_for_another_session_another_host_or_long_ago_silences_nothing(self):
        card_id = self.housed()
        self.board.relay(card_id, "resume", "human", self.cfg.host, prompt="x")
        tap = self.board.pending_relays(card_id)[0]
        self.assertIsNotNone(self.board.held_tap(card_id))
        from keel import views
        self.assertIsNone(views.held_tap([tap], "another-session"))
        self.assertIsNone(views.held_tap([tap], SESSION, host="elsewhere"))
        later = datetime.now().astimezone() + timedelta(minutes=31)
        self.assertIsNone(views.held_tap([tap], SESSION, now=later))
        self.assertIsNone(self.board.held_tap(card_id, session="a-superseded-one"))

    def test_the_staging_turn_still_runs_the_turn_end_checks(self):
        card_id = self.housed(stage="review", plan_ref="p.md")
        self.cfg.card_dir(card_id)
        (self.cfg.cards_dir / card_id / "context.md").write_text("# nothing yet\n")
        self.board.relay(card_id, "resume", "human", self.cfg.host, prompt="and also this")
        from keel import ending
        decision = ending.check(self.cfg, self.board, card_id, {})
        self.assertEqual((decision or {}).get("decision"), "block", "the record check still acts")

    def test_a_comment_typed_at_building_is_still_told_at_review(self):
        card_id = self.housed()
        self.board.relay(card_id, "resume", "human", self.cfg.host, prompt="also rename it")
        self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="out")
        self.once()
        carried = [e for e in self.board.events(card_id) if e["kind"] == "carried"]
        self.assertEqual(carried[-1]["data"]["outcome"], "taken")


class LaunchExpectTest(DrainCase):
    def test_a_caller_starting_a_house_at_another_stage_says_which(self):
        """c-600 starts a house for a shipping card; the guard takes the stage it expects."""
        card_id = self.board.create("personal", "later", autonomy="autonomous")
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        with self.assertRaises(house.AlreadyStarted):
            house.launch(self.cfg, self.board, card_id)
        house.launch(self.cfg, self.board, card_id, expect="building")
        self.assertEqual(len(self.fake.starts), 1)


class PoolAfterAResumeTest(DrainCase):
    """The pass's own resumes fill the pools before anything is started.

    The box, 2026-09-20 09:00Z, `houses_max = 2`: a service restart left two houses'
    sessions gone, and one pass resumed c-310 and c-311 and then started c-312 and c-313.
    The listing is taken once at the top of the pass, so the two sessions it had just
    resumed were not in it, the pool read empty and `start_cards` filled it again. Four
    houses on a two-slot machine:
    `drain: houses=4 reviews=0 browsers=0 resumed=2 blocked=0 started=2 paused=False`.
    The counts come from the board (the resumed cards), never from a second listing: a
    session minted mid-pass is not reliably listed for a few seconds (`resumed_mid_turn`).
    """

    def test_two_resumes_fill_a_two_slot_machine_and_nothing_starts(self):
        self.cfg.houses_max = 2
        self.dead("a"), self.dead("b")
        first, second = self.assigned("older"), self.assigned("newer")
        summary = self.once()
        self.assertEqual((summary["resumed"], summary["started"], summary["houses"]), (2, 0, 2))
        self.assertEqual(self.fake.starts, [])
        self.assertIn("house pool full at 2", self.log_text())
        for card_id in (first, second):
            self.assertEqual(self.board.get(card_id)["stage"], "assigned")

    def test_the_pass_after_it_reads_the_same_two_houses_from_the_listing(self):
        """The resumed sessions are listed busy now, and the answer does not change."""
        self.cfg.houses_max = 2
        one, two = self.dead("a"), self.dead("b")
        waiting = self.assigned("waits")
        self.once()
        self.fake.rows = [dict(background_row(card_id, self.board.get(card_id)["session_id"]),
                               status="busy") for card_id in (one, two)]
        summary = self.once()
        self.assertEqual((summary["resumed"], summary["started"], summary["houses"]), (0, 0, 2))
        self.assertEqual(self.fake.starts, [])
        self.assertEqual(self.board.get(waiting)["stage"], "assigned")

    def test_one_resume_leaves_the_second_slot_for_a_start(self):
        self.cfg.houses_max = 2
        self.dead("a")
        card_id = self.assigned("startable")
        summary = self.once()
        self.assertEqual((summary["resumed"], summary["started"], summary["houses"]), (1, 1, 2))
        self.assertEqual([s["name"] for s in self.fake.starts], [card_id])

    def test_reconcile_restores_every_house_it_owns_past_the_pool(self):
        """A house that was already running keeps its claim to its slot, so resuming it is
        restoring and not starting: reconcile is not capped by `houses_max`. What the pool
        then stops is the pass adding a fourth house on top of the three it restored."""
        self.cfg.houses_max = 1
        self.dead("a"), self.dead("b"), self.dead("c")
        waiting = self.assigned("waits")
        summary = self.once()
        self.assertEqual((summary["resumed"], summary["started"], summary["houses"]), (3, 0, 3))
        self.assertEqual(len(self.fake.resumes), 3)
        self.assertEqual(self.board.get(waiting)["stage"], "assigned")

    def test_a_resumed_review_house_fills_the_review_pool_only(self):
        self.cfg.houses_max, self.cfg.reviews_max = 1, 1
        self.dead("a", options={"slot": "review"})
        build = self.assigned("a build")
        review = self.assigned("a review", options={"slot": "review"})
        summary = self.once()
        self.assertEqual([s["name"] for s in self.fake.starts], [build])
        self.assertEqual((summary["houses"], summary["reviews"]), (1, 1))
        self.assertEqual(self.board.get(review)["stage"], "assigned")
        self.assertIn("review pool full at 1", self.log_text())

    def test_a_resumed_build_house_leaves_the_review_pool_alone(self):
        self.cfg.houses_max, self.cfg.reviews_max = 1, 1
        self.dead("a")
        review = self.assigned("a review", options={"slot": "review"})
        build = self.assigned("a build")
        summary = self.once()
        self.assertEqual([s["name"] for s in self.fake.starts], [review])
        self.assertEqual((summary["houses"], summary["reviews"]), (1, 1))
        self.assertEqual(self.board.get(build)["stage"], "assigned")
        self.assertIn("house pool full at 1", self.log_text())

    def test_a_resumed_browser_house_fills_the_browser_slot(self):
        self.cfg.houses_max, self.cfg.browsers_max = 3, 1
        self.dead("a", options={"browser": True})
        waiting = self.assigned("another browser card", options={"browser": True})
        plain = self.assigned("a plain card")
        summary = self.once()
        self.assertEqual([s["name"] for s in self.fake.starts], [plain])
        self.assertEqual((summary["browsers"], summary["houses"]), (1, 2))
        self.assertEqual(self.board.get(waiting)["stage"], "assigned")
        self.assertIn("browser slot full at 1", self.log_text())

    def test_a_resume_takes_a_house_off_the_memory_reading(self):
        """A resume starts a process, so the gate must see it before the pass starts one."""
        self.cfg.houses_max, self.cfg.memory_floor_mb, self.cfg.house_mb = 3, 2048, 700
        self.machine.memory = 2600
        self.dead("a")
        waiting = self.assigned("waits")
        summary = self.once()
        self.assertEqual((summary["resumed"], summary["started"], summary["memory"]),
                         (1, 0, "1900MB"))
        self.assertEqual(self.board.get(waiting)["stage"], "assigned")


class DeckTapTest(DrainCase):
    """Approve, Send back and Resume on the deck resume a house directly (the deck's
    `actions.resume_with`, then `house.resume`), outside any drain pass, so they never
    consult a pool. The human's tap is never refused for a full pool: he is answering a
    house that is already his, and a refusal would put his own answer in a queue.

    The drain's side of the bargain is that its NEXT pass counts those houses like any
    other. So three taps on a two-slot box put three houses on it (the planner had to
    stagger three plan approvals by hand on 2026-09-20 to avoid exactly that), and from
    then on the drain starts nothing: a tap may take the machine over its limit, the drain
    never adds to it.
    """

    def test_a_tap_is_never_refused_and_the_next_pass_counts_the_house_it_resumed(self):
        self.cfg.houses_max = 2
        self.fake.rows = []
        gates = [self.at_gate(f"{mark * 8}-0000-4000-8000-{mark * 12}") for mark in "123"]
        for card_id in gates:
            house.resume(self.cfg, self.board, card_id, prompt="approved; build it")
        self.assertEqual(len(self.fake.resumes), 3, "a tap is never refused for a full pool")
        waiting = self.assigned("waits")
        summary = self.once()
        self.assertEqual((summary["houses"], summary["started"]), (3, 0))
        self.assertEqual(self.fake.starts, [])
        self.assertEqual(self.board.get(waiting)["stage"], "assigned")
        self.assertIn("house pool full at 2", self.log_text())


class QuietHouseTest(DrainCase):
    """A house the account's rate limit stopped: idle at `building`, its turn ended with no
    Stop, and until now nothing in Keel acted on it.

    The box, 2026-09-20. At 09:49Z the account hit its session rate limit and three houses
    (c-311, c-312, c-313), each mid-turn at `building`, ended their turn with NO Stop hook:
    the last event on each card is the idle-prompt Notification below, and `claude agents
    --json` listed each session as `idle`. Reconcile wants a session GONE from the listing,
    and the Stop-hook nudge never ran because no Stop fired, so all three sat at `building`
    holding the whole pool, doing nothing, until the human resumed them by hand at 10:00.

    The clock is injected (`drain.now`), never slept through: `drain.time` IS the `time`
    module, and patching its `sleep` while a real child runs is the race LoopTest documents.
    """

    def setUp(self):
        super().setUp()
        self.cfg.drain_paused = True        # nothing here is about starting a card
        self.started = datetime.now().astimezone()

    def pass_at(self, minutes: int, **kwargs) -> dict:
        """One pass, `minutes` after the events this test recorded, by the drain's clock."""
        with mock.patch.object(drain, "now", return_value=self.at(minutes)):
            return self.once(**kwargs)

    def at(self, minutes: int) -> datetime:
        return datetime.now().astimezone() + timedelta(minutes=minutes)

    def notify(self, card_id: str, session: str = SESSION, kind: str = "idle_prompt") -> None:
        """The Notification the harness fires about a minute after a session goes quiet."""
        self.board.record_hook(card_id, "Notification", {
            "hook_event_name": "Notification", "message": "Claude is waiting for your input",
            "notification_type": kind, "session_id": session})

    def quiet(self, session=SESSION, status="idle", notification="idle_prompt", **kwargs) -> str:
        """A housed card whose own session is listed, idle, and last said nothing but the
        Notification: the live shape above."""
        card_id = self.housed(session=session, **kwargs)
        self.fake.rows.append(dict(background_row(card_id, session), status=status))
        self.notify(card_id, session, notification)
        return card_id

    def notes(self, card_id: str) -> list[str]:
        return [e["text"] for e in self.board.events(card_id) if e["kind"] == "note"]

    def test_the_live_sequence_waits_then_resumes_with_a_growing_wait_then_blocks(self):
        self.fake.logs_text = "I was rewriting the fetcher when the limit hit."
        card_id = self.quiet()
        self.assertEqual(self.pass_at(5).get("stuck", 0), 0, "nothing before the threshold")
        self.assertEqual(self.fake.resumes, [])
        self.assertEqual(self.pass_at(11)["stuck"], 1)
        self.assertIn("your turn ended without finishing", self.fake.resumes[0]["prompt"])
        self.assertIn("attempt 1 of 3", self.notes(card_id)[-1])
        self.assertEqual(self.board.events(card_id)[-2]["kind"], "resume")
        self.assertEqual(self.pass_at(15).get("stuck", 0), 0, "the second wait is twice the first")
        self.assertEqual(self.pass_at(25)["stuck"], 1)
        self.assertEqual(self.pass_at(35).get("stuck", 0), 0, "and the third twice that")
        self.assertEqual(self.pass_at(45)["stuck"], 1)
        self.assertEqual(len(self.fake.resumes), 3)
        self.assertIsNone(self.board.get(card_id)["blocked_reason"], "three attempts, no block yet")
        self.assertEqual(self.pass_at(60).get("blocked", 0), 0)
        self.assertEqual(self.pass_at(90)["blocked"], 1)
        reason = self.board.get(card_id)["blocked_reason"]
        self.assertIn("idle at building 3 times", reason)
        self.assertIn("I was rewriting the fetcher when the limit hit.", reason)
        self.assertTrue(self.board.get(card_id)["derived"]["needs_you"])
        self.assertEqual(len(self.fake.resumes), 3, "a blocked card is his, not the drain's")

    def test_a_house_that_ended_its_turn_is_the_stop_path_and_never_this_one(self):
        """The second signal. A house that needs the human blocks its card or ends its turn,
        and a turn that ends fires Stop, which `Board.stop_check` answers with a nudge and
        then a block. So a Stop since the turn began means this rule is not the one."""
        card_id = self.quiet()
        self.board.record_hook(card_id, "Stop", {"session_id": SESSION,
                                                 "last_assistant_message": "which of the two?"})
        self.notify(card_id)
        self.assertEqual(self.pass_at(200).get("stuck", 0), 0)
        self.assertEqual(self.fake.resumes, [])
        self.assertIsNone(self.board.get(card_id)["blocked_reason"])

    def test_a_permission_prompt_is_a_human_answer_and_is_never_resumed(self):
        """The idle prompt fires for a house waiting on the human too, so the notification
        alone cannot say. A permission prompt names itself, and nobody but he can answer it."""
        card_id = self.quiet(notification="permission_prompt")
        self.assertEqual(self.pass_at(200).get("stuck", 0), 0)
        self.assertEqual(self.fake.resumes, [])

    def test_a_blocked_card_is_already_his(self):
        card_id = self.quiet()
        self.board.block(card_id, "I need the credentials", "hook")
        self.assertEqual(self.pass_at(200).get("stuck", 0), 0)
        self.assertEqual(self.fake.resumes, [])

    def test_a_tracking_card_is_never_touched(self):
        card_id = self.tracking()
        self.notify(card_id, "77777777-0000-4000-8000-000000000077")
        summary = self.pass_at(200)
        self.assertEqual(summary.get("stuck", 0), 0)
        self.assertEqual(self.fake.resumes, [])
        self.assertIsNone(self.board.get(card_id)["blocked_reason"])

    def test_a_busy_row_cancels_it(self):
        self.quiet(status="busy")
        self.assertEqual(self.pass_at(200).get("stuck", 0), 0)
        self.assertEqual(self.fake.resumes, [])

    def test_a_session_gone_from_the_listing_stays_reconcile_case(self):
        """Gone is a house that exited: reconcile resumes it once and blocks it the second
        time. This rule is for a session that is still listed and still idle."""
        self.quiet()
        self.fake.rows = []
        summary = self.pass_at(200)
        self.assertEqual((summary["resumed"], summary.get("stuck", 0)), (1, 0))

    def test_a_card_with_a_pending_relay_is_skipped(self):
        """His tap is carried instead of the quiet-house resume (a relay under an old host
        name is this machine's, c-622 r1.F1)."""
        card_id = self.quiet()
        self.board.relay(card_id, "resume", "human", "box", prompt="his tap")
        self.assertEqual(self.pass_at(200).get("stuck", 0), 0)
        self.assertEqual([r["prompt"] for r in self.fake.resumes], ["his tap"])

    def test_his_own_resume_puts_the_count_back_to_the_start(self):
        """A resume, an approval or a send back is him answering the house; the drain's
        streak is over and the first wait is the short one again."""
        card_id = self.quiet()
        self.assertEqual(self.pass_at(11)["stuck"], 1)
        house.resume(self.cfg, self.board, card_id, prompt="have another go")
        self.notify(card_id)
        self.assertEqual(self.pass_at(15)["stuck"], 1, "ten minutes again, not twenty")
        self.assertIn("attempt 1 of 3", self.notes(card_id)[-1])

    def test_the_memory_floor_defers_it(self):
        self.cfg.memory_floor_mb, self.cfg.house_mb = 2048, 700
        self.machine.memory = 1000
        self.quiet()
        self.assertEqual(self.pass_at(30).get("stuck", 0), 0)
        self.assertEqual(self.fake.resumes, [])
        self.assertIn("memory gate", self.log_text())
        self.machine.memory = 4096
        self.assertEqual(self.pass_at(30)["stuck"], 1)

    def test_a_resume_takes_its_house_off_the_memory_reading(self):
        self.cfg.memory_floor_mb, self.cfg.house_mb = 2048, 700
        self.machine.memory = 2600
        self.quiet()
        self.assertEqual(self.pass_at(30)["memory"], "1900MB")

    def test_the_rule_is_off_when_the_machine_sets_no_wait(self):
        self.cfg.idle_resume_minutes = 0
        self.quiet()
        self.assertEqual(self.pass_at(600).get("stuck", 0), 0)
        self.assertEqual(self.fake.resumes, [])

    def test_a_quiet_house_keeps_its_slot_while_it_waits(self):
        """It is coming back, and it needs its slot when it does. Freeing it would let the
        pass start another house and over-subscribe the machine on the next resume."""
        self.cfg.drain_paused = False
        self.cfg.houses_max = 1
        card_id = self.quiet()
        waiting = self.assigned("waits")
        summary = self.pass_at(5)
        self.assertEqual((summary["houses"], summary["started"]), (1, 0))
        self.assertIn(card_id, drain.house_ids(self.board, self.fake.rows))
        self.assertEqual(self.board.get(waiting)["stage"], "assigned")


class LoopTest(DrainCase):
    def test_run_logs_every_pass_and_survives_a_failing_one(self):
        """No child process may run while this test owns the loop's wait (`drain.rest`
        since c-598; it was `time.sleep`, and the history below is why git is stubbed).

        `drain.time` IS the `time` module, so patching its `sleep` replaces `time.sleep`
        for the whole process, and the fake below is what drives the loop. `drain.run`
        shells git twice over (`merging.code_head`, once before the loop and again inside
        `code_moved`), `merging.git` always passes a `timeout`, and on POSIX a
        `subprocess.run` WITH a timeout busy-waits: every poll of `waitpid(WNOHANG)` that
        finds the child not yet reaped is followed by `time.sleep(0.0005)`. That sleep is
        the git wait wearing the drain's clothes, and it landed in the counter below. An
        idle Mac reaps on the first poll every time, so nothing showed here; a loaded
        machine loses that race, and this test then raised its KeyboardInterrupt inside
        `code_head` before `drain.once` had ever run, leaving only the `drain up:` line in
        the log. That is c-320, and `tests/test_poller.py`'s board-away case is the same
        fault (c-321): the pair failing together is one race attempted twice, not state
        leaking between them, which is also why neither fails alone.

        So `code_head` is stubbed and there is no child to wait on. The seam, never the
        assertion: the counter is meant to see the drain's own wait and nothing else.
        """
        passes = []

        def sleep(seconds):
            passes.append(seconds)
            if len(passes) == 2:
                raise KeyboardInterrupt

        with mock.patch.object(drain, "once", side_effect=[RuntimeError("boom"), {
                "houses": 0, "reviews": 0, "resumed": 0, "blocked": 0, "started": 0,
                "paused": False}]), \
                mock.patch.object(drain.merging, "code_head", return_value="a930320"), \
                mock.patch.object(drain, "rest", lambda cfg, inbox: sleep(cfg.poll_seconds)):
            with self.assertRaises(KeyboardInterrupt):
                drain.run(self.cfg)
        log = self.log_text()
        self.assertIn("drain up:", log)
        self.assertIn("pass failed:", log)
        self.assertIn("RuntimeError: boom", log)
        self.assertIn("drain: houses=0 reviews=0 resumed=0 blocked=0 started=0 paused=False", log)
        self.assertEqual(passes, [1, 1])

    def test_house_ids_counts_only_background_rows_named_for_a_live_card(self):
        building = self.housed()
        done = self.housed(stage="review", plan_ref="p", session="eeeeeeee-0000-4000-8000-000000000006")
        rows = [background_row(building, SESSION), background_row(done, "e"),
                background_row("keel-probe", "f"), dict(background_row(building, SESSION), kind="interactive")]
        self.assertEqual(drain.house_ids(self.board, rows), {building})

    def test_house_ids_leaves_out_an_idle_plan_gate_house_and_keeps_a_busy_one(self):
        undelivered = self.housed(stage="planning", autonomy="attended", session="a")
        idle = self.housed(stage="planning", autonomy="attended", plan_ref="p", session="b")
        busy = self.housed(stage="planning", autonomy="attended", plan_ref="p", session="c")
        rows = [background_row(undelivered, "a"), background_row(idle, "b"),
                dict(background_row(busy, "c"), status="busy"),
                background_row(busy, "d")]
        self.assertEqual(drain.house_ids(self.board, rows), {undelivered, busy})


class LogUpkeepTest(DrainCase):
    def test_a_pass_cuts_back_a_log_that_has_outgrown_its_size_and_says_so(self):
        self.cfg.logs_dir.mkdir(parents=True, exist_ok=True)
        err = self.cfg.logs_dir / "keel.err.log"
        err.write_bytes(b"x" * 99 + b"\n" + b"the newest line\n")
        with mock.patch.object(drain.logtrim, "LOG_MAX_BYTES", 50), \
                mock.patch.object(drain.logtrim, "TAIL_BYTES", 20):
            self.once()
        self.assertEqual(err.read_bytes(), b"the newest line\n")
        self.assertTrue((self.cfg.logs_dir / "keel.err.log.1").exists())
        self.assertIn("logs cut back to their tail, the rest kept as .1: keel.err.log",
                      self.log_text())

    def test_a_log_upkeep_that_fails_is_logged_and_the_pass_goes_on(self):
        with mock.patch.object(drain.logtrim, "trim", side_effect=RuntimeError("no")):
            summary = self.once()
        self.assertIn("houses", summary)
        self.assertIn("log upkeep failed", self.log_text())


class BackupUpkeepTest(DrainCase):
    def test_every_pass_offers_the_pull_and_says_when_it_starts_one(self):
        with mock.patch.object(drain.backup, "pull_upkeep",
                               return_value={"started": True, "reason": "last pull 30h ago"}) as up:
            self.once()
        up.assert_called_once_with(self.cfg)
        self.assertIn("backup pull started: last pull 30h ago", self.log_text())

    def test_a_backup_upkeep_that_fails_is_logged_and_the_pass_goes_on(self):
        with mock.patch.object(drain.backup, "pull_upkeep", side_effect=RuntimeError("no")):
            summary = self.once()
        self.assertIn("houses", summary)
        self.assertIn("backup upkeep failed", self.log_text())


class VoiceHoldTest(DrainCase):
    """A card voice is holding is nobody's but his: every step of a pass leaves it alone,
    and the expiry is what puts an abandoned conversation right (card c-315, V4 guard 2)."""

    def setUp(self):
        super().setUp()
        self.cfg.drain_paused = True         # nothing here is about starting a card

    def held(self, card_id: str, seconds: int = 300, stopped: bool = True) -> str:
        self.board.hold_voice(card_id, seconds, stopped=stopped, turns=1)
        return card_id

    def notes(self, card_id: str) -> list[str]:
        return [e["text"] for e in self.board.events(card_id) if e["kind"] == "note"]

    def test_reconcile_leaves_a_held_house_alone_even_though_its_session_is_gone(self):
        """Voice STOPPED that session on purpose. Resuming it would take a turn into the
        transcript he is talking into, which is the race the lock exists to stop."""
        card_id = self.held(self.dead())
        counts = self.once()
        self.assertEqual((counts["resumed"], counts["blocked"]), (0, 0))
        self.assertEqual(self.fake.resumes, [])
        self.assertIsNone(self.board.get(card_id)["blocked_reason"])

    def test_a_tracking_card_is_not_retired_while_he_is_talking_to_it(self):
        """"Connect me to c-277" is the obvious thing to say to a card that was split, and
        its own session is exactly the one `retire_tracking` would stop."""
        card_id = self.held(self.tracking())
        self.once()
        self.assertEqual(getattr(self.fake, "stops", []), [])

    def test_a_held_house_is_never_read_as_quiet_and_stuck(self):
        card_id = self.held(self.housed())
        self.fake.rows.append(background_row(card_id, SESSION))
        self.board.record_hook(card_id, "Notification", {
            "notification_type": "idle_prompt", "session_id": SESSION})
        self.assertIsNone(drain.idle_stuck(self.cfg, self.board, self.board.get(card_id),
                                           self.fake.rows,
                                           at=datetime.now().astimezone() + timedelta(hours=3)))

    def test_a_connected_turn_ends_the_quiet_because_its_stop_hook_fires(self):
        """The turn a conversation takes DOES fire the card's Stop hook (probed 2026-09-20),
        under the card's own session id, so the moment the hold is released the house does
        not look like a house whose turn ended without one."""
        card_id = self.housed()
        self.fake.rows.append(background_row(card_id, SESSION))
        self.board.record_hook(card_id, "Notification", {
            "notification_type": "idle_prompt", "session_id": SESSION})
        self.board.hold_voice(card_id, 300, stopped=True)
        self.board.stop_check(card_id, {"hook_event_name": "Stop", "session_id": SESSION})
        self.board.release_voice(card_id)
        self.assertIsNone(drain.idle_stuck(self.cfg, self.board, self.board.get(card_id),
                                           self.fake.rows,
                                           at=datetime.now().astimezone() + timedelta(hours=3)))

    def test_a_tap_from_the_deck_is_superseded_rather_than_carried_into_the_conversation(self):
        card_id = self.held(self.housed())
        self.board.relay(card_id, "resume", "human", self.cfg.host, prompt="carry on")
        self.once()
        carried = [e for e in self.board.events(card_id) if e["kind"] == "carried"]
        self.assertEqual(carried[-1]["data"]["outcome"], "superseded")
        self.assertIn("voice is talking", carried[-1]["text"])
        self.assertEqual(self.fake.resumes, [])

    def test_an_expired_hold_is_cleared_and_the_house_is_woken_without_a_prompt(self):
        """The repair: he closed the page mid-sentence, and nothing else would ever let that
        house go. A wake costs no tokens, so this is not a resume."""
        card_id = self.held(self.dead(), seconds=-1)
        summary = self.once()
        self.assertEqual(summary["holds"], 1)
        self.assertEqual(self.fake.wakes, [self.board.get(card_id)["session_id"]])
        self.assertIsNone(self.board.voice_hold_of(card_id))
        self.assertIn(drain.WOKEN_NOTE, self.notes(card_id))
        self.assertEqual(self.fake.resumes, [], "a wake is not a resume")

    def test_an_expired_hold_closes_the_conversation_BEFORE_it_wakes_the_house(self):
        """V12. A kept-alive conversation is a `claude` holding that session, and a wake
        is refused while anything holds it. The drain runs in its own process, so it asks
        the server that owns it; the ORDER is what makes the repair work at all."""
        order = []
        card_id = self.held(self.dead(), seconds=-1)
        self.fake.on_wake = lambda: order.append("wake")
        with mock.patch.object(drain.housetier, "close_session",
                               lambda cfg, card, wake=False:
                               order.append(("close", card["id"]))
                               or drain.housetier.Shut(drain.housetier.CLOSED)):
            self.once()
        self.assertEqual(order, [("close", card_id), "wake"])

    def test_a_conversation_that_would_not_close_leaves_the_house_down_and_says_so(self):
        """V12, review round 2: a wake is refused while anything holds the session, so a
        close that failed must not be followed by one. The hold goes either way, because
        keeping it would have the drain retrying a failing close forever."""
        card_id = self.held(self.dead(), seconds=-1)
        with mock.patch.object(drain.housetier, "close_session",
                               lambda cfg, card, wake=False:
                               drain.housetier.Shut(drain.housetier.FAILED)):
            self.once()
        self.assertEqual(getattr(self.fake, "wakes", []), [])
        self.assertIn(drain.CLOSE_FAILED_NOTE, self.notes(card_id))
        self.assertIsNone(self.board.voice_hold_of(card_id))

    def test_the_talker_s_memory_rotation_waits_while_voice_holds_a_house(self):
        """c-538: the phone talker rotates for a memory change only when no voice hold is live."""
        self.assertFalse(drain.voice_holding(self.board))
        self.held(self.dead())
        self.assertTrue(drain.voice_holding(self.board))
        with mock.patch.object(drain.talker, "upkeep", return_value={}) as upkeep:
            self.once()
        self.assertEqual(upkeep.call_args.kwargs, {"holding": True})

    def test_bosun_s_voice_hold_counts_too(self):
        from keel import bosunhold
        bosunhold.take(self.board, "voice")
        self.assertTrue(drain.voice_holding(self.board))

    def test_a_house_voice_found_already_down_is_left_down(self):
        card_id = self.held(self.dead(), seconds=-1, stopped=False)
        self.once()
        self.assertEqual(getattr(self.fake, "wakes", []), [])
        self.assertIn(drain.LEFT_DOWN_NOTE, self.notes(card_id))

    def test_the_wake_waits_for_memory_and_the_hold_waits_with_it(self):
        card_id = self.held(self.dead(), seconds=-1)
        self.cfg.memory_floor_mb = 2048
        self.machine.memory = 1000
        self.once()
        self.assertEqual(getattr(self.fake, "wakes", []), [])
        self.assertIsNotNone(self.board.get(card_id)["options"].get("voice_hold"))

    def test_a_wake_that_fails_still_leaves_the_hold_cleared(self):
        """A house that is down is a shape reconcile already knows how to put back once.
        Keeping the hold would have the drain trying the same failing wake forever."""
        card_id = self.held(self.dead(), seconds=-1)
        self.fake.wake_fails = True
        self.once()
        self.assertIsNone(self.board.voice_hold_of(card_id))
        self.assertTrue(any("waking the house failed" in note for note in self.notes(card_id)))


class IdleJobsTest(DrainCase):
    """A house idle while a background job of its own runs (c-534): the drain notes it on the
    card once per job, and the deck's `jobs` reads the same record. Neither acts on it."""

    def job_state(self, tasks: int = 1) -> None:
        jobs = Path(self.cfg.spaces["personal"].config_dir) / "jobs" / SESSION[:8]
        jobs.mkdir(parents=True, exist_ok=True)
        (jobs / "state.json").write_text(json.dumps({
            "inFlight": {"tasks": tasks}, "fan": [
                {"id": "bs6e3ga2f", "kind": "shell", "startedAt": 1790413540697,
                 "label": "while pgrep -f tests.parallel; do sleep 5; done"}]}))

    def test_an_idle_house_with_a_job_is_noted_once_and_left_alone(self):
        card_id = self.housed()
        # The listing's shape for such a house, probed live: busy by status, done by state.
        self.fake.rows.append(dict(background_row(card_id, SESSION), status="busy", state="done"))
        self.job_state()
        self.assertEqual(self.once().get("jobs"), 1)
        self.assertEqual(self.once().get("jobs"), None, "once per job, not every pass")
        notes = [e["text"] for e in self.board.events(card_id) if e["kind"] == "note"]
        self.assertEqual(len(notes), 1)
        self.assertIn("idle with its background job bs6e3ga2f still running", notes[0])
        self.assertEqual((self.fake.resumes, getattr(self.fake, "stops", [])), ([], []))
        self.assertIn("idle with 1 background job(s)", self.log_text())
        card = self.board.get(card_id)
        facts = {"bg_id": SESSION[:8], "status": "busy", "state": "done"}
        self.assertEqual([job["id"] for job in deckstate.jobs_of(self.cfg, card, facts)], ["bs6e3ga2f"])
        self.assertEqual(deckstate.jobs_of(self.cfg, card, dict(facts, state="working")), [])
        self.assertEqual(deckstate.jobs_of(self.cfg, card, None), [])

    def test_a_house_in_its_turn_or_one_with_nothing_in_flight_is_not_noted(self):
        card_id = self.housed()
        self.fake.rows.append(background_row(card_id, SESSION, status="busy"))     # in a turn
        self.job_state()
        self.assertIsNone(self.once().get("jobs"))
        self.fake.rows = [dict(background_row(card_id, SESSION), status="idle")]
        self.job_state(tasks=0)
        self.assertIsNone(self.once().get("jobs"))


class BosunCardTest(DrainCase):
    """c-647: a card Bosun builds is never a house's, whatever session it still carries."""

    def setUp(self):
        super().setUp()
        repo = self.dir / "keel"
        for argv in (["init", "-q", "-b", "main", str(repo)],
                     ["-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                      "--allow-empty", "-m", "init"]):
            subprocess.run(["git", *argv], check=True, capture_output=True)
        self.cfg.spaces["personal"].repos["keel"] = repo
        self.board.close()
        self.board = Board(self.cfg.db_path, switches={authority.BUILDER}, builds=["keel"])

    def test_a_leftover_house_session_on_bosun_s_card_is_never_resumed_or_blocked(self):
        mine = self.dead(repo="keel")
        planning = self.dead(mark="b", repo="keel", stage="planning")
        theirs = self.dead(mark="c", repo="keel", actor="human", options={"worker": "house"})
        self.assertEqual([self.board.get(c)["derived"]["bosun"] for c in (mine, planning, theirs)],
                         [True, True, False])
        for _ in range(2):
            self.once()
        self.assertEqual([r["session_id"] for r in self.fake.resumes],
                         [self.board.get(theirs)["session_id"]], "only the house's card")
        self.assertEqual(self.fake.starts, [])
        for card_id in (mine, planning):
            self.assertIsNone(self.board.get(card_id)["blocked_reason"])
            self.assertEqual(len(self.said(card_id)), 1, "said once, where he would look")
        self.assertIsNotNone(self.board.get(theirs)["blocked_reason"], "a house's card: exited twice")
        other = "dddddddd-0000-4000-8000-dddddddddddd"
        self.board.set_session(mine, other, "drain", bg_id=other[:8])
        for _ in range(2):
            self.once()
        self.assertEqual([other[:8] in note for note in self.said(mine)], [False, True],
                         "a second leftover session is said once too")

    def said(self, card_id: str) -> list[str]:
        return [e["text"] for e in self.board.events(card_id) if e["kind"] == "note" and e["actor"] == "drain"]

    def test_a_listed_quiet_session_on_bosun_s_card_is_left_running_and_unsaid(self):
        card_id = self.housed(repo="keel")
        self.fake.rows.append(dict(background_row(card_id, SESSION), status="idle"))
        self.board.record_hook(card_id, "Notification", {
            "hook_event_name": "Notification", "notification_type": "idle_prompt", "session_id": SESSION})
        later = datetime.now().astimezone() + timedelta(hours=3)
        self.assertIsNone(drain.idle_stuck(self.cfg, self.board, self.board.get(card_id), self.fake.rows, at=later))
        with mock.patch.object(drain, "now", return_value=later):
            self.once()
        self.assertEqual((self.fake.resumes, self.fake.starts, getattr(self.fake, "stops", [])), ([], [], []))
        self.assertEqual((self.board.get(card_id)["blocked_reason"], self.said(card_id)), (None, []))

    def test_a_guard_a_house_s_card_would_stop_at_keeps_the_note_unsaid(self):
        """F6: said only where a house's card would have reached the resume."""
        card_id = self.dead(repo="keel")
        self.board.block(card_id, "waiting on him", "human")
        self.once()
        self.assertEqual(self.said(card_id), [])

    def test_an_expired_voice_hold_on_bosun_s_card_is_cleared_and_wakes_no_house(self):
        card_id = self.dead(repo="keel")
        self.board.hold_voice(card_id, -1, stopped=True, turns=1)
        self.cfg.memory_floor_mb, self.machine.memory = 2048, 1000    # shut: a house's hold would wait
        self.once()
        self.assertIsNone(self.board.voice_hold_of(card_id))
        self.assertEqual((getattr(self.fake, "wakes", []), self.fake.resumes), ([], []))

    def test_a_conversation_that_would_not_close_on_bosun_s_card_promises_no_house_back(self):
        card_id = self.dead(repo="keel")
        self.board.hold_voice(card_id, -1, stopped=True, turns=1)
        with mock.patch.object(drain.housetier, "close_session",
                               lambda cfg, card, wake=False: drain.housetier.Shut(drain.housetier.FAILED)):
            self.once()
        self.once()
        self.assertIsNone(self.board.voice_hold_of(card_id))
        said = self.said(card_id)
        self.assertIn(drain.BOSUN_CLOSE_FAILED_NOTE, said)
        self.assertNotIn(drain.CLOSE_FAILED_NOTE, said, "no pass puts a house back on this card")
        self.assertEqual((getattr(self.fake, "wakes", []), self.fake.resumes, self.fake.starts,
                          getattr(self.fake, "stops", [])), ([], [], [], []))
