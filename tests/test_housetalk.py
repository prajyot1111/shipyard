"""housetalk: the machine half of a connected turn, and the sessions it owns (V12).

Nothing here touches the board, and that is the point of the module: slice 2 runs this
half on the machine where the house lives, behind the door, and it must therefore take
plain data and answer with plain data. A test that needed a `Board` would be the first
sign the split had leaked.

The `claude` binary is never run: `harness.open_conversation` and the one-shot `turn` are
replaced with recorders.
"""

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from keel import harness, house, housetalk
from keel.board import Board
from tests.helpers import SESSION, FakeHarness, background_row, make_config, make_repo

ANSWER = "Phase two is merged. The tests pass."


class FakeTalk:
    """One kept-alive conversation, as `harness.Conversation` behaves to its caller."""

    def __init__(self, records=None, fails="", stays_alive=False):
        self.stays_alive = stays_alive
        self.said: list[str] = []
        self.records = records if records is not None else [
            {"type": "assistant",
             "message": {"content": [{"type": "tool_use", "name": "Read", "input": {}}]}},
            {"type": "stream_event",
             "event": {"type": "content_block_delta",
                       "delta": {"type": "text_delta", "text": "Phase two is merged. "}}},
            {"type": "stream_event",
             "event": {"type": "content_block_delta",
                       "delta": {"type": "text_delta", "text": "The tests pass."}}}]
        self.fails = fails
        self.closed = 0
        self.last_said = time.time()
        self.dead = False

    @property
    def alive(self):
        return not self.dead

    def say(self, text, *, on_record=None, timeout=None, on_written=None):
        if self.fails == "before the write":
            self.dead = True
            raise harness.HarnessError("the conversation would not take the sentence")
        self.said.append(text)
        if on_written is not None:
            on_written()
        self.last_said = time.time()
        if self.fails:
            self.dead = not self.stays_alive
            raise harness.HarnessError(self.fails)
        for record in self.records:
            on_record(record)
        return {"is_error": False, "result": ANSWER}

    def close(self, timeout=None):
        self.closed += 1
        self.dead = True


class HousetalkCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.repo = make_repo(self.dir / "repo")
        self.cfg = make_config(self.dir, repos={"keel": self.repo})
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        self.fake = FakeHarness()
        for module in (housetalk, house):
            patch = mock.patch.object(module, "harness", self.fake)
            patch.start()
            self.addCleanup(patch.stop)
        self.card_id = self.board.create("personal", "Add keel doctor", repo="keel")
        self.board.stage(self.card_id, "assigned", "human")
        self.board.set_session(self.card_id, SESSION, "drain", bg_id=SESSION[:8])
        self.board.stage(self.card_id, "building", "drain")
        house.worktree_for(self.cfg, self.board.get(self.card_id))
        self.card = self.board.get(self.card_id)
        self.plan = housetalk.plan(self.cfg, self.card)

    def sessions(self, talk=None):
        """A registry whose conversations are `FakeTalk`s, with the opens recorded."""
        opened = []
        sessions = housetalk.Sessions()
        self.addCleanup(sessions.close_all)

        def open_one(session_id, **kwargs):
            opened.append(dict(kwargs, session_id=session_id))
            return talk or FakeTalk()

        self.fake.open_conversation = open_one
        return sessions, opened


class ThePlanTest(HousetalkCase):
    """The plain data the machine half takes, which is the whole interface slice 2 reuses."""

    def test_it_is_json_able_and_names_everything_a_turn_needs(self):
        import json
        json.dumps(self.plan)
        self.assertEqual(self.plan["card"], self.card_id)
        self.assertEqual(self.plan["session_id"], SESSION)
        self.assertTrue(self.plan["worktree"])
        self.assertEqual(Path(self.plan["settings_path"]),
                         self.cfg.card_dir(self.card_id) / "settings.json")
        self.assertEqual(Path(self.plan["cwd"]),
                         house.worktree_for(self.cfg, self.card)[0])

    def test_a_done_card_talks_in_its_own_directory_and_says_so(self):
        """Its worktree went with the merge, so there is nowhere else and nothing to
        change; the framing is what tells the house so (`prompts.converse`)."""
        self.board.stage(self.card_id, "review", "house", plan_ref="plan.md",
                         output_ref="branch")
        self.board.approve(self.card_id, "outcome", "human")
        plan = housetalk.plan(self.cfg, self.board.get(self.card_id))
        self.assertFalse(plan["worktree"])
        self.assertEqual(Path(plan["cwd"]), self.cfg.card_dir(self.card_id))


class TheGuardsTest(HousetalkCase):
    """The two guards that are facts about the MACHINE, not about the board."""

    def test_a_house_that_is_working_is_busy_and_one_that_is_down_is_not(self):
        self.assertFalse(housetalk.busy(self.plan))
        self.fake.rows = [background_row(self.card_id, SESSION, status="busy")]
        self.assertTrue(housetalk.busy(self.plan))
        self.fake.rows = [background_row(self.card_id, SESSION, status="idle")]
        self.assertFalse(housetalk.busy(self.plan))

    def test_the_memory_floor_is_asked_of_the_machine_and_off_when_unset(self):
        with mock.patch.object(housetalk.machine, "available_mb", return_value=100):
            self.assertTrue(housetalk.memory_short(500))
            self.assertFalse(housetalk.memory_short(0))
        with mock.patch.object(housetalk.machine, "available_mb", return_value=None):
            self.assertTrue(housetalk.memory_short(500))

    def test_stopping_the_house_is_what_makes_the_door_free(self):
        self.fake.rows = [background_row(self.card_id, SESSION, status="idle")]
        self.assertTrue(housetalk.stop_house(self.plan))
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        self.assertFalse(housetalk.stop_house(self.plan), "a house already down")


class OneConversationTest(HousetalkCase):
    def test_the_first_sentence_carries_the_framing_and_the_next_carries_his_words(self):
        """V12: in a kept-alive conversation the house is told the rules ONCE. Repeating
        them every sentence is what a one-shot turn had to do, and it is tokens spent on
        something the transcript already holds."""
        sessions, opened = self.sessions()
        sessions.say(self.plan, "where are you up to", framing="RULES: where are you up to",
                     plain="where are you up to")
        sessions.say(self.plan, "and the tests?", framing="RULES: and the tests?",
                     plain="and the tests?")
        talk = sessions.entry(self.card_id).talk
        self.assertEqual(talk.said, ["RULES: where are you up to", "and the tests?"])
        self.assertEqual(len(opened), 1, "the second sentence started a second process")


    def test_what_the_house_does_and_what_it_says_both_arrive_as_events(self):
        """The two kinds a listener gets, in order: an action to narrate, then the
        answer's own sentences, cut as they stream."""
        sessions, _ = self.sessions()
        seen = []
        sessions.say(self.plan, "where are you up to", framing="f", plain="p",
                     on_event=seen.append)
        self.assertEqual([event["type"] for event in seen],
                         ["action", "part", "part"])
        self.assertEqual(seen[0], {"type": "action", "action": "read", "tool": "Read"})
        self.assertEqual([event["text"] for event in seen[1:]],
                         ["Phase two is merged.", "The tests pass."])

    def test_an_action_the_vocabulary_cannot_name_says_nothing_at_all(self):
        """The egress rule is `keel/narration.py`'s and this half does not soften it."""
        sessions, _ = self.sessions(FakeTalk(records=[
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "SomeMcpThing", "input": {"path": "/secret"}}]}}]))
        seen = []
        sessions.say(self.plan, "hello", framing="f", plain="p", on_event=seen.append)
        self.assertEqual(seen, [])

    def test_the_same_action_twice_running_is_one_event(self):
        read = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {}}]}}
        sessions, _ = self.sessions(FakeTalk(records=[read, read]))
        seen = []
        sessions.say(self.plan, "hello", framing="f", plain="p", on_event=seen.append)
        self.assertEqual([event["type"] for event in seen], ["action"])

    def test_the_tail_of_the_answer_is_flushed_so_no_sentence_is_lost(self):
        """The last sentence has no whitespace after it, so without the flush it would
        be cut off, and the gateway would speak all of the answer but the end."""
        sessions, _ = self.sessions(FakeTalk(records=[
            {"type": "stream_event",
             "event": {"type": "content_block_delta",
                       "delta": {"type": "text_delta", "text": "No full stop here"}}}]))
        seen = []
        sessions.say(self.plan, "hello", framing="f", plain="p", on_event=seen.append)
        self.assertEqual([event["text"] for event in seen], ["No full stop here"])


class OneConversationPerCardTest(HousetalkCase):
    def test_opening_twice_reuses_the_live_one_and_never_doubles(self):
        sessions, opened = self.sessions()
        sessions.open(self.plan)
        sessions.open(self.plan)
        self.assertEqual(len(opened), 1)
        self.assertEqual(sessions.count(), 1)

    def test_a_dead_one_is_replaced_rather_than_reused(self):
        talk = FakeTalk()
        sessions, opened = self.sessions(talk)
        sessions.open(self.plan)
        talk.dead = True
        sessions.open(self.plan)
        self.assertEqual(len(opened), 2)
        self.assertEqual(sessions.count(), 1)

    def test_a_turn_that_fails_leaves_no_session_behind(self):
        """A conversation whose process died must not be handed the next sentence: the
        caller falls back, and the next open starts a fresh one."""
        sessions, opened = self.sessions(FakeTalk(fails="the process ended"))
        with self.assertRaises(harness.HarnessError):
            sessions.say(self.plan, "hello", framing="f", plain="p")
        self.assertEqual(sessions.count(), 0)


class TheIdleDeadlineTest(HousetalkCase):
    """A conversation lives exactly as long as the hold that justifies it."""

    def test_one_that_has_gone_quiet_past_the_hold_is_closed(self):
        talk = FakeTalk()
        sessions, _ = self.sessions(talk)
        sessions.open(self.plan)
        talk.last_said = time.time() - 400
        self.assertEqual(sessions.reap(300), [self.card_id])
        self.assertEqual(talk.closed, 1)
        self.assertEqual(sessions.count(), 0)


    def test_closing_them_all_is_what_a_server_does_on_its_way_out(self):
        talk = FakeTalk()
        sessions, _ = self.sessions(talk)
        sessions.open(self.plan)
        sessions.close_all()
        self.assertEqual(talk.closed, 1)
        self.assertEqual(sessions.count(), 0)


class TheOneShotTest(HousetalkCase):
    """The path nothing may regress: the phone Harbor's single question (V6)."""

    def test_it_is_the_plain_turn_it_has_always_been_with_no_process_kept(self):
        sessions, opened = self.sessions()
        self.fake.answer = "It is at review."
        payload = housetalk.one_shot(self.plan, "RULES: how far are you", timeout=60)
        self.assertEqual(harness.turn_answer(payload), "It is at review.")
        self.assertEqual(self.fake.turns[0]["session_id"], SESSION)
        self.assertEqual(opened, [])
        self.assertEqual(sessions.count(), 0)

    def test_with_a_listener_it_streams_the_same_events(self):
        seen = []
        housetalk.one_shot(self.plan, "RULES: how far are you", timeout=60,
                           on_event=seen.append)
        self.assertTrue(self.fake.streamed, "a listener must get the streamed turn")
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()


class ClosingMidTurnTest(HousetalkCase):
    """His release must not sit behind a turn that has minutes left to run."""

    class SlowTalk(FakeTalk):
        def __init__(self):
            super().__init__()
            self.let_go = None

        def say(self, text, *, on_record=None, timeout=None, on_written=None):
            if on_written is not None:
                on_written()
            self.let_go.wait(10)
            raise harness.HarnessError("the conversation's process ended mid-turn")

    def test_a_close_does_not_wait_out_a_turn_that_is_still_running(self):
        import threading
        talk = self.SlowTalk()
        talk.let_go = threading.Event()
        sessions, _ = self.sessions(talk)
        failed = []

        def turn():
            try:
                sessions.say(self.plan, "how far", framing="f", plain="p")
            except harness.HarnessError as error:
                failed.append(error)

        worker = threading.Thread(target=turn, daemon=True)
        worker.start()
        time.sleep(0.2)
        with mock.patch.object(housetalk, "CLOSE_WAIT", 0.3):
            started = time.time()
            self.assertTrue(sessions.close(self.card_id))
        self.assertLess(time.time() - started, 3.0)
        self.assertEqual(talk.closed, 1)
        talk.let_go.set()
        worker.join(timeout=5)
        # AND THE TURN IT ENDED IS AN ORDINARY FAILURE, NOT A DEAD CONVERSATION: falling
        # back would ask the house the question he has just walked away from.
        self.assertTrue(failed and not isinstance(failed[0], housetalk.Dead), str(failed))


class TheTurnIsAskedOnceTest(HousetalkCase):
    """A TURN IS IDENTIFIED BY ITS ID, AND ASKING TWICE ASKS THE HOUSE ONCE (finding B).

    A sentence written to the process cannot be un-written, so a client whose stream broke
    must attach to the turn that is already running rather than start another.
    """

    def test_a_second_say_with_the_same_id_does_not_write_a_second_sentence(self):
        sessions, _ = self.sessions()
        first = sessions.say(self.plan, "how far", framing="f", plain="p", turn_id="t1")
        again = sessions.say(self.plan, "how far", framing="f", plain="p", turn_id="t1")
        talk = sessions.entry(self.card_id).talk
        self.assertEqual(talk.said, ["f"], "the sentence was written twice")
        self.assertEqual(again, first)

    def test_attaching_replays_only_what_the_caller_has_not_had(self):
        sessions, _ = self.sessions()
        first = []
        sessions.say(self.plan, "how far", framing="f", plain="p", turn_id="t1",
                     on_event=first.append)
        again = []
        sessions.say(self.plan, "how far", framing="f", plain="p", turn_id="t1",
                     seen=len(first) - 1, on_event=again.append)
        self.assertEqual(again, first[-1:])

    def test_a_turn_still_running_is_followed_rather_than_started_again(self):
        """The real case: the stream broke while the house was still writing."""
        import threading
        talk = self.SlowTalk() if hasattr(self, "SlowTalk") else None
        let_go = threading.Event()

        class Blocking(FakeTalk):
            def say(inner, text, *, on_record=None, timeout=None, on_written=None):
                inner.said.append(text)
                if on_written is not None:
                    on_written()
                on_record(inner.records[1])
                let_go.wait(10)
                on_record(inner.records[2])
                return {"is_error": False, "result": ANSWER}

        talk = Blocking()
        sessions, _ = self.sessions(talk)
        got = []
        worker = threading.Thread(
            target=lambda: sessions.say(self.plan, "how far", framing="f", plain="p",
                                        turn_id="t1"), daemon=True)
        worker.start()
        time.sleep(0.3)
        follower = []

        def attach():
            follower.append(sessions.say(self.plan, "how far", framing="f", plain="p",
                                         turn_id="t1", seen=1, on_event=got.append))

        second = threading.Thread(target=attach, daemon=True)
        second.start()
        time.sleep(0.2)
        let_go.set()
        worker.join(timeout=10)
        second.join(timeout=10)
        self.assertEqual(talk.said, ["f"], "the house was asked twice")
        self.assertEqual(harness.turn_answer(follower[0]), ANSWER)
        self.assertEqual([event["text"] for event in got], ["The tests pass."])

    def test_a_sentence_that_never_reached_the_process_says_so(self):
        """The one failure the caller may fall back on: it cannot have been answered."""
        sessions, _ = self.sessions(FakeTalk(fails="before the write"))
        with self.assertRaises(housetalk.NotSent):
            sessions.say(self.plan, "how far", framing="f", plain="p", turn_id="t1")
        self.assertEqual(sessions.count(), 0)


class TheFramingAfterAFailureTest(HousetalkCase):
    """A turn that errored must not make the NEXT sentence pay for the framing again."""

    def test_the_turn_is_counted_as_soon_as_the_line_is_written(self):
        talk = FakeTalk(fails="the turn errored", stays_alive=True)
        sessions, _ = self.sessions(talk)
        with self.assertRaises(harness.HarnessError):
            sessions.say(self.plan, "how far", framing="RULES", plain="p", turn_id="t1")
        talk.fails = ""
        talk.dead = False
        sessions.say(self.plan, "and now", framing="RULES", plain="just his words",
                     turn_id="t2")
        self.assertEqual(talk.said, ["RULES", "just his words"])


class TheOpenRaceTest(HousetalkCase):
    """Two threads that both find no conversation must still start ONE process."""

    def test_two_opens_at_once_start_one_claude(self):
        import threading
        started = []
        sessions = housetalk.Sessions()
        self.addCleanup(sessions.close_all)

        def open_one(session_id, **kwargs):
            # A REAL OPEN IS NOT INSTANT: it spawns and reads a transcript, which is the
            # window the second thread used to start a process of its own in.
            time.sleep(0.4)
            started.append(session_id)
            return FakeTalk()

        self.fake.open_conversation = open_one
        got = []
        threads = [threading.Thread(target=lambda: got.append(sessions.open(self.plan)),
                                    daemon=True) for _ in range(2)]
        for thread in threads:
            thread.start()
            time.sleep(0.05)         # the second arrives while the first is still opening
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(len(started), 1, f"{len(started)} processes were started")
        self.assertEqual(sessions.count(), 1)
        self.assertIs(got[0], got[1], "the two callers hold different conversations")
