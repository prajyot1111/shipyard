"""converse: one turn into a card's house, its guards, and what the hold does around it.

The `claude` binary is never run: `keel.harness` is the fake from `tests/helpers.py`, whose
`turn` records the call and answers, and whose `wake` records the session it put back.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from keel import converse, harness, house, housetalk, views
from keel.board import Board
from tests.helpers import SESSION, FakeHarness, background_row, make_config, make_repo


class ConverseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.repo = make_repo(self.dir / "repo")
        self.cfg = make_config(self.dir, repos={"keel": self.repo})
        self.board = Board(self.cfg.db_path)
        self.fake = FakeHarness()
        for module in (converse, house, housetalk):
            patch = mock.patch.object(module, "harness", self.fake)
            patch.start()
            self.addCleanup(patch.stop)
        self.card_id = self.building()

    def tearDown(self):
        self.board.close()
        self.tmp.cleanup()

    def building(self, **kwargs) -> str:
        card_id = self.board.create("personal", "Add keel doctor", repo="keel",
                                    autonomy="autonomous", **kwargs)
        self.board.stage(card_id, "assigned", "human")
        self.board.set_session(card_id, SESSION, "drain", bg_id=SESSION[:8])
        self.board.stage(card_id, "building", "drain")
        # The worktree a house would have: `placement` names it and a done card has none.
        house.worktree_for(self.cfg, self.board.get(card_id))
        return card_id

    def live(self, status="idle"):
        self.fake.rows = [background_row(self.card_id, SESSION, status=status)]

    def notes(self) -> list[str]:
        return [event["text"] for event in self.board.events(self.card_id)
                if event["kind"] == "note"]

    def hold(self) -> dict | None:
        return self.board.voice_hold_of(self.card_id)


class OneTurnTest(ConverseCase):
    def test_a_turn_stops_the_house_takes_the_turn_and_puts_it_back(self):
        """The whole shape of a one-shot turn (the phone Harbor's): stop, turn, wake. The
        hold is taken and given straight back, because nobody is pinned to this card."""
        self.live()
        self.fake.answer = "Yes, phase two is merged into phase one now."
        result = converse.answer(self.cfg, self.board, self.card_id, "merge two into one", 60)
        self.assertTrue(result["ok"])
        self.assertEqual(result["say"], "Yes, phase two is merged into phase one now.")
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        self.assertEqual(self.fake.wakes, [SESSION])
        self.assertEqual(len(self.fake.turns), 1)
        self.assertIsNone(self.hold())
        self.assertIsNone(result["held_until"])

    def test_the_turn_runs_under_the_card_s_own_settings_model_and_worktree(self):
        self.live()
        self.board.set_fields(self.card_id, {"model": "opus"}, "human")
        converse.answer(self.cfg, self.board, self.card_id, "what are you doing?", 60)
        call = self.fake.turns[0]
        self.assertEqual(call["session_id"], SESSION)
        self.assertEqual(call["model"], "opus")
        self.assertEqual(Path(call["settings_path"]),
                         self.cfg.card_dir(self.card_id) / "settings.json")
        self.assertEqual(Path(call["cwd"]), house.worktree_for(self.cfg,
                                                               self.board.get(self.card_id))[0])

    def test_the_framing_says_the_words_were_spoken_and_what_needs_a_spoken_yes(self):
        """His sentence arrives through speech recognition into a session with real tools
        and no permission prompts, so the turn carries the rule with it."""
        self.live()
        converse.answer(self.cfg, self.board, self.card_id, "drop the old branch", 60)
        prompt = self.fake.turns[0]["prompt"]
        self.assertIn("speech recognition", prompt)
        self.assertIn("wait for a spoken yes", prompt)
        self.assertIn("drop the old branch", prompt)

    def test_the_exchange_is_recorded_with_his_words_verbatim(self):
        self.live()
        self.fake.answer = "It is at review, waiting on you."
        converse.answer(self.cfg, self.board, self.card_id, "where are you up to", 60)
        self.assertIn('voice: "where are you up to"\n  -> "It is at review, waiting on you."',
                      self.notes())

    def test_a_long_answer_is_clipped_in_the_note_and_not_in_the_speech(self):
        self.live()
        self.fake.answer = "x" * (converse.ANSWER_CLIP + 50)
        result = converse.answer(self.cfg, self.board, self.card_id, "explain", 60)
        self.assertEqual(len(result["say"]), converse.ANSWER_CLIP + 50)
        self.assertIn("...", [note for note in self.notes() if note.startswith("voice:")][0])

    def test_a_turn_that_fails_gives_back_the_hold_and_says_so(self):
        self.live()
        self.fake.turn_fails = "the turn took longer than 60s"
        result = converse.answer(self.cfg, self.board, self.card_id, "explain", 60)
        self.assertFalse(result["ok"])
        self.assertIn("longer than 60s", result["say"])
        self.assertIsNone(self.hold())
        self.assertEqual(self.fake.wakes, [SESSION])


class PinnedTest(ConverseCase):
    def test_connect_takes_the_hold_stops_the_house_and_takes_no_turn(self):
        self.live()
        result = converse.connect(self.cfg, self.board, self.card_id)
        self.assertTrue(result["ok"])
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        self.assertEqual(getattr(self.fake, "turns", []), [])
        self.assertTrue(self.hold()["stopped"])
        self.assertIn(converse.CONNECTED_NOTE, self.notes())

    def test_a_stop_that_fails_here_is_a_spoken_refusal_and_holds_nothing(self):
        """r-17 on this machine: the same failed `claude stop` a house here can hit. It is
        answered as a refusal with the harness's reason, and no hold is left behind."""
        self.live()
        self.fake.stop_fails = True
        result = converse.connect(self.cfg, self.board, self.card_id)
        self.assertFalse(result["ok"])
        self.assertIn("claude stop failed", result["say"])
        self.assertIsNone(self.hold())
        result = converse.answer(self.cfg, self.board, self.card_id, "one question", 60)
        self.assertFalse(result["ok"])
        self.assertIn("claude stop failed", result["say"])
        self.assertIsNone(self.hold())
        self.assertEqual(getattr(self.fake, "turns", []), [])

    def test_connect_carries_what_the_page_needs_to_draw_the_header(self):
        """V8: the header names the card and takes the house's COLOUR while the pin holds,
        and a house's colour is its card's space. The title is what line 2 reads out, cut
        to a few words by the gateway; the whole one stays on the page."""
        self.live()
        result = converse.connect(self.cfg, self.board, self.card_id)
        card = self.board.get(self.card_id)
        self.assertEqual(result["space"], card["space"])
        self.assertEqual(result["title"], card["title"])

    def test_a_pinned_conversation_keeps_the_house_down_between_turns(self):
        """The whole reason the hold exists: two turns cost one stop and one wake, not two
        of each, so a turn is only ever as slow as the model."""
        self.live()
        converse.connect(self.cfg, self.board, self.card_id)
        self.fake.rows = []                      # voice stopped it; the listing agrees
        converse.answer(self.cfg, self.board, self.card_id, "first question", 60)
        converse.answer(self.cfg, self.board, self.card_id, "second question", 60)
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        self.assertEqual(getattr(self.fake, "wakes", []), [])
        self.assertEqual(len(self.fake.turns), 2)
        self.assertEqual(self.hold()["turns"], 2)

    def test_back_to_harbor_releases_the_hold_and_wakes_the_house(self):
        self.live()
        converse.connect(self.cfg, self.board, self.card_id)
        self.fake.rows = []
        converse.answer(self.cfg, self.board, self.card_id, "one question", 60)
        result = converse.release(self.cfg, self.board, self.card_id)
        self.assertEqual(result["say"], "Back to Harbor.")
        self.assertIsNone(self.hold())
        self.assertEqual(self.fake.wakes, [SESSION])
        self.assertIn("voice let this house go after 1 exchange; its session is awake again",
                      self.notes())

    def test_a_house_that_was_already_down_is_left_down(self):
        """A tracking card's session has usually been retired by the drain. Waking it would
        only hand `retire_tracking` the same session to stop again on its next pass."""
        self.fake.rows = []                      # nothing listed: the easy case
        converse.connect(self.cfg, self.board, self.card_id)
        self.assertEqual(getattr(self.fake, "stops", []), [])
        self.assertFalse(self.hold()["stopped"])
        self.assertIn(converse.CONNECTED_DOWN_NOTE, self.notes())
        converse.release(self.cfg, self.board, self.card_id)
        self.assertEqual(getattr(self.fake, "wakes", []), [])

    def test_releasing_a_card_nobody_is_holding_says_so_and_does_nothing(self):
        result = converse.release(self.cfg, self.board, self.card_id)
        self.assertTrue(result["ok"])
        self.assertEqual(getattr(self.fake, "wakes", []), [])


class GuardTest(ConverseCase):
    def test_a_building_house_is_refused_and_his_question_is_left_on_the_card(self):
        """Guard 1, idle only. Two turns in one transcript is the race the lock exists to
        stop, so the question goes on the card for the house to see at its next turn."""
        self.live(status="busy")
        result = converse.answer(self.cfg, self.board, self.card_id, "why the rewrite?", 60)
        self.assertFalse(result["ok"])
        self.assertIn("building right now", result["say"])
        self.assertEqual(getattr(self.fake, "turns", []), [])
        self.assertEqual(getattr(self.fake, "stops", []), [])
        self.assertIn('the user asked by voice, and the house could not be reached: "why the rewrite?"',
                      self.notes())

    def test_a_card_with_no_house_is_refused_with_the_offer_to_start_it(self):
        card_id = self.board.create("personal", "nothing yet", repo="keel")
        result = converse.answer(self.cfg, self.board, card_id, "hello", 60)
        self.assertFalse(result["ok"])
        self.assertIn("no house session yet", result["say"])

    def test_an_archived_card_is_refused(self):
        """There is nothing to talk to: the card is off the board."""
        self.live()
        self.board.set_fields(self.card_id, {"options": {"archived": True}}, "human")
        result = converse.answer(self.cfg, self.board, self.card_id, "hello", 60)
        self.assertFalse(result["ok"])
        self.assertIn("archived", result["say"])
        self.assertEqual(getattr(self.fake, "turns", []), [])

    def test_the_memory_floor_refuses_out_loud(self):
        """A turn is a whole `claude` process; one that gets the box OOM-killed takes the
        voice gateway with it."""
        self.live()
        self.cfg.memory_floor_mb = 2048
        with mock.patch.object(housetalk.machine, "available_mb", return_value=1000):
            result = converse.answer(self.cfg, self.board, self.card_id, "hello", 60)
        self.assertFalse(result["ok"])
        # one machine names itself as this machine, never "the Mac" or "the box" (c-634)
        self.assertEqual(result["say"], "This machine is short of memory. Try again in a minute.")
        self.assertEqual(getattr(self.fake, "turns", []), [])

    def test_a_machine_is_spoken_as_this_machine_or_its_key(self):
        """c-634: one function names a machine out loud, and no map of host names."""
        self.assertEqual(converse.spoken_host(self.cfg, self.cfg.host), "This machine")
        self.assertEqual(converse.spoken_host(self.cfg, None), "This machine")
        self.assertEqual(converse.spoken_host(self.cfg, "studio"), "Studio")


class HoldTakenAwayTest(ConverseCase):
    """He can end a conversation from the other end: Stop on the deck, an answer at a gate,
    or walking away long enough for the drain to clear the hold. The gateway cannot see any
    of that, so the next turn tells it."""

    def test_a_pinned_turn_whose_hold_has_gone_says_so_and_asks_to_be_unpinned(self):
        self.live()
        converse.connect(self.cfg, self.board, self.card_id)
        self.board.release_voice(self.card_id)          # his Stop tap, or the drain's repair
        result = converse.answer(self.cfg, self.board, self.card_id, "still there?", 60,
                                 pinned=True)
        self.assertFalse(result["ok"])
        self.assertTrue(result["unpin"])
        self.assertIn("stopped", result["say"])
        self.assertEqual(getattr(self.fake, "turns", []), [],
                         "the hold is gone, so the turn is not taken")

    def test_an_unpinned_caller_simply_takes_a_hold_of_its_own(self):
        """The phone Harbor's one-shot turn: nobody was pinned, so nothing was taken away."""
        self.live()
        result = converse.answer(self.cfg, self.board, self.card_id, "how far are you?", 60)
        self.assertTrue(result["ok"])
        self.assertNotIn("unpin", result)

    def test_a_pinned_turn_with_its_hold_still_there_is_an_ordinary_turn(self):
        self.live()
        converse.connect(self.cfg, self.board, self.card_id)
        self.fake.rows = []
        result = converse.answer(self.cfg, self.board, self.card_id, "carry on", 60,
                                 pinned=True)
        self.assertTrue(result["ok"])
        self.assertEqual(len(self.fake.turns), 1)


class DoneCardTest(ConverseCase):
    def test_a_done_card_runs_in_its_own_directory_and_is_told_it_cannot_change_anything(self):
        """V4: a done card (worktree reaped on the merge) can explain itself and no more.

        And it is asked by STAGE, never by looking: `house.placement` cuts the worktree it
        names, so a look would create the very thing being asked about."""
        self.live()
        self.board.stage(self.card_id, "review", "house", plan_ref="plan.md",
                         output_ref="branch")
        self.board.approve(self.card_id, "outcome", "human")
        self.assertEqual(self.board.get(self.card_id)["stage"], "done")
        converse.answer(self.cfg, self.board, self.card_id, "what did you build?", 60)
        call = self.fake.turns[0]
        self.assertEqual(Path(call["cwd"]), self.cfg.card_dir(self.card_id))
        self.assertIn("worktree is gone", call["prompt"])
        self.assertIn("offer to put it on a new card", call["prompt"])


class VerbTest(ConverseCase):
    def test_the_verb_prints_the_spoken_answer_and_exits_zero(self):
        self.live()
        self.fake.answer = "It is at review."
        with mock.patch.object(converse.config_module, "load", return_value=self.cfg), \
                mock.patch.object(converse, "open_board", return_value=self.board), \
                mock.patch("builtins.print") as printed:
            code = converse.main([self.card_id, "where are you"])
        self.assertEqual(code, 0)
        printed.assert_called_with("It is at review.")

    def test_a_refusal_is_still_a_sentence_and_exits_one(self):
        self.live(status="busy")
        with mock.patch.object(converse.config_module, "load", return_value=self.cfg), \
                mock.patch.object(converse, "open_board", return_value=self.board), \
                mock.patch("builtins.print") as printed:
            code = converse.main([self.card_id, "where are you", "--json"])
        self.assertEqual(code, 1)
        payload = json.loads(printed.call_args[0][0])
        self.assertFalse(payload["ok"])
        self.assertIn("building right now", payload["say"])

    def test_json_carries_the_hold_s_expiry_so_the_page_knows_when_its_pin_runs_out(self):
        self.live()
        with mock.patch.object(converse.config_module, "load", return_value=self.cfg), \
                mock.patch.object(converse, "open_board", return_value=self.board), \
                mock.patch("builtins.print") as printed:
            converse.main([self.card_id, "--connect", "--json"])
        payload = json.loads(printed.call_args[0][0])
        until = views.parse_at(payload["held_until"])
        self.assertGreater(until, datetime.now().astimezone())
        self.assertLessEqual(until, datetime.now().astimezone()
                             + timedelta(seconds=self.cfg.voice_hold_seconds + 2))

    def test_a_house_cannot_run_the_verb_at_all(self):
        """The other door on `board.HOLD_ACTORS`: the verb takes the hold itself, without
        going through `kb`, so a house that could run it would be holding a card the same
        way. `KEEL_CARD` is what the harness gives a house's own shell."""
        with mock.patch.dict(converse.os.environ, {converse.HOUSE_ENV: "c-001"}), \
                mock.patch.object(converse.config_module, "load") as load:
            code = converse.main([self.card_id, "hello"])
        self.assertEqual(code, 1)
        load.assert_not_called()

    def test_an_unknown_card_is_a_sentence_and_not_a_stack_trace(self):
        with mock.patch.object(converse.config_module, "load", return_value=self.cfg), \
                mock.patch.object(converse, "open_board", return_value=self.board), \
                mock.patch("builtins.print") as printed:
            code = converse.main(["c-999", "hello"])
        self.assertEqual(code, 1)
        self.assertIn("could not find a card", printed.call_args[0][0])


if __name__ == "__main__":
    unittest.main()


class NarratedTurnTest(ConverseCase):
    """A connected turn narrates its own activity when someone is listening (V5, c-317)."""

    def setUp(self):
        super().setUp()
        self.card = self.building()
        self.progress = self.dir / "progress"

    def lines(self):
        return [json.loads(p.read_text()) for p in sorted(self.progress.glob("*.json"))]

    def stream(self, *records):
        """A fake streamed turn: hand each record to the listener, then answer."""
        def turn_streamed(session_id, prompt, *, on_record=None, **kwargs):
            self.fake.turns = getattr(self.fake, "turns", []) + [
                dict(kwargs, session_id=session_id, prompt=prompt, streamed=True)]
            for record in records:
                if on_record is not None:
                    on_record(record)
            if getattr(self.fake, "turn_fails", None):
                raise harness.HarnessError(self.fake.turn_fails)
            return {"is_error": False, "result": "Done, it is on the card."}
        self.fake.turn_streamed = turn_streamed

    @staticmethod
    def tool(name, **inputs):
        return {"type": "assistant", "parent_tool_use_id": None,
                "message": {"content": [{"type": "tool_use", "name": name,
                                         "input": dict(inputs)}]}}

    def test_with_a_progress_directory_the_turn_streams_and_narrates(self):
        self.stream(self.tool("Edit", file_path="/home/x/plan.md"),
                    self.tool("Bash", command="make test"))
        result = converse.answer(self.cfg, self.board, self.card, "merge the phases", 60,
                                 progress=str(self.progress), turn_id="t1")
        self.assertTrue(result["ok"], result)
        self.assertEqual([line["action"] for line in self.lines()], ["edit", "test"])
        self.assertTrue(all(line["turn"] == "t1" for line in self.lines()))

    def test_with_no_progress_directory_it_is_the_plain_turn_it_always_was(self):
        """The phone Harbor asks one question with nobody listening."""
        self.stream(self.tool("Edit", file_path="/x"))
        result = converse.answer(self.cfg, self.board, self.card, "where are you up to", 60)
        self.assertTrue(result["ok"], result)
        self.assertFalse(self.progress.exists())
        self.assertTrue(self.fake.turns[-1].get("streamed") is None)

    def test_no_path_a_tool_was_given_ever_reaches_the_inbox(self):
        secret = "/home/ubuntu/keel/spaces/personal/.claude/headers.txt"
        self.stream(self.tool("Read", file_path=secret),
                    self.tool("Bash", command=f"cat {secret}"))
        converse.answer(self.cfg, self.board, self.card, "check it", 60,
                        progress=str(self.progress), turn_id="t1")
        written = "\n".join(p.read_text() for p in sorted(self.progress.glob("*.json")))
        self.assertNotIn(secret, written)
        self.assertNotIn("headers", written)

    def test_a_turn_that_is_ended_leaves_what_it_got_as_far_as_on_the_card(self):
        """His question was asked and the house did real work with it: a failure that
        leaves no trace is how a conversation loses a turn nobody can find afterwards."""
        self.stream(self.tool("Read", file_path="/x"), self.tool("Edit", file_path="/y"))
        self.fake.turn_fails = "the turn took longer than 60s, and it was ended"
        result = converse.answer(self.cfg, self.board, self.card, "merge the phases", 60,
                                 progress=str(self.progress), turn_id="t1")
        self.assertFalse(result["ok"])
        notes = "\n".join(e["text"] for e in self.board.events(self.card)
                          if e["kind"] == "note")
        self.assertIn("merge the phases", notes)
        self.assertIn("the turn was ended", notes)
        self.assertIn("read, edit", notes)

    def test_the_partial_record_names_no_path_either(self):
        secret = "/home/ubuntu/private/headers.txt"
        self.stream(self.tool("Read", file_path=secret))
        self.fake.turn_fails = "the turn took longer than 60s, and it was ended"
        converse.answer(self.cfg, self.board, self.card, "check it", 60,
                        progress=str(self.progress), turn_id="t1")
        notes = "\n".join(e["text"] for e in self.board.events(self.card)
                          if e["kind"] == "note")
        self.assertNotIn(secret, notes)

    def test_a_turn_that_did_nothing_worth_saying_says_nothing(self):
        self.stream({"type": "system", "subtype": "init"},
                    self.tool("TodoWrite", todos=[]))
        result = converse.answer(self.cfg, self.board, self.card, "hello", 60,
                                 progress=str(self.progress), turn_id="t1")
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.lines(), [])


# ----- the kept-alive conversation (V12) -----

class KeptAliveCase(ConverseCase):
    """A connected conversation is ONE `claude` process, owned by `keel serve`.

    `keel converse` never owns it: it asks the local server through `keel/housetier.py`,
    which is replaced here with a recorder. What is tested is the BOARD half's side of
    that seam: which path a turn takes, what it is allowed to send, and the order the
    hold, the session and the wake are ended in. The server's own half (the placement, the
    framing, the key, the board guards) is `tests/test_housetier.py`.
    """

    def setUp(self):
        super().setUp()
        self.card = self.building()
        self.progress = self.dir / "progress"
        self.calls = []
        self.events = [{"type": "action", "action": "read", "tool": "Read"},
                       {"type": "part", "text": "Phase two is merged."},
                       {"type": "part", "text": "The tests pass."}]
        self.away = None
        self.said_answer = "Phase two is merged. The tests pass."

        # EVERY CLIENT CALL NOW TAKES THE CARD AND NOT ITS ID (V12 slice 2), because the
        # card is what says which machine owns the conversation. The fakes record the id,
        # since that is what these tests are about.
        def fake_say(cfg, card, said, *, turn_id="", timeout=0, on_event=None, report="",
                     grammar=False):
            self.calls.append({"card": card["id"], "said": said, "turn_id": turn_id,
                               "timeout": timeout, "report": report, "grammar": grammar})
            for event in self.events:
                if on_event is not None:
                    on_event(event)
            if self.away is not None:
                raise self.away
            return {"is_error": False, "result": self.said_answer}

        self.opened = []
        self.closed = []
        self.close_answer = converse.housetier.Shut(converse.housetier.CLOSED)
        self.open_answer = converse.housetier.Opened(True, stopped=True)

        def fake_open(cfg, card, timeout=0):
            self.opened.append(card["id"])
            return self.open_answer

        def fake_close(cfg, card, wake=False):
            self.closed.append({"card": card["id"], "wake": wake})
            return self.close_answer

        patches = [mock.patch.object(converse.housetier, "say", fake_say),
                   mock.patch.object(converse.housetier, "open_session", fake_open),
                   mock.patch.object(converse.housetier, "close_session", fake_close)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def shut(self) -> list[str]:
        """The cards a close was asked for, in order."""
        return [one["card"] for one in self.closed]

    def pin(self):
        """Him already in a conversation with this card: the hold is live and the house
        is DOWN, which is what a hold means (`take_hold` stopped it when he connected)."""
        self.board.hold_voice(self.card, self.cfg.voice_hold_seconds, stopped=True, turns=0)
        self.fake.rows = []

    def lines(self):
        return [json.loads(p.read_text()) for p in sorted(self.progress.glob("*.json"))]

    def notes_on(self):
        return "\n".join(e["text"] for e in self.board.events(self.card)
                          if e["kind"] == "note")


class WhichPathTest(KeptAliveCase):
    def test_a_pinned_turn_goes_through_the_kept_alive_session(self):
        self.live()
        self.pin()
        result = converse.answer(self.cfg, self.board, self.card, "how far are you", 60,
                                 pinned=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["say"], "Phase two is merged. The tests pass.")
        self.assertEqual([call["said"] for call in self.calls], ["how far are you"])
        self.assertEqual(getattr(self.fake, "turns", []), [],
                         "a one-shot turn was taken as well")

    def test_the_board_grammar_is_given_to_a_house_once_per_version(self):
        """C4: a house spawned before a grammar change carries the old grammar, so the
        first turn of this version asks for the card, and the card remembers it was given."""
        from keel import boardgrammar
        self.live()
        self.pin()
        converse.answer(self.cfg, self.board, self.card, "how far", 60, pinned=True)
        converse.answer(self.cfg, self.board, self.card, "and now", 60, pinned=True)
        self.assertEqual([call["grammar"] for call in self.calls], [True, False])
        notes = [e["text"] for e in self.board.events(self.card) if e["kind"] == "note"]
        given = [n for n in notes if n.startswith(converse.GRAMMAR_GIVEN.format(
            version=boardgrammar.GRAMMAR_VERSION))]
        self.assertEqual(len(given), 1, notes)

    def test_the_unpinned_one_shot_is_exactly_the_turn_it_has_always_been(self):
        """The phone Harbor's single question (V6). Nothing about it may regress: it owns
        no process, so a kept-alive one would be started and thrown away every time."""
        self.live()
        self.fake.answer = "It is at review."
        result = converse.answer(self.cfg, self.board, self.card, "how far are you", 60)
        self.assertEqual(result["say"], "It is at review.")
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.fake.turns), 1)

    def test_the_switch_turns_the_whole_thing_off(self):
        """`[voice] kept_alive = false` is the one line back to the per-sentence shape."""
        self.live()
        self.pin()
        self.cfg.voice_kept_alive = False
        self.fake.answer = "It is at review."
        result = converse.answer(self.cfg, self.board, self.card, "how far", 60, pinned=True)
        self.assertEqual(result["say"], "It is at review.")
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.fake.turns), 1)


class WhatTheClientMaySendTest(KeptAliveCase):
    """THE BOARD HALF NAMES A CARD AND QUOTES HIM, AND SENDS NOTHING ELSE (review round 1).

    The placement and the framing are the server's, because the server is the thing that
    runs `claude`. This half could send them correctly every time and the route would
    still have to build its own, so it does not send them at all.
    """

    def test_it_sends_the_card_his_sentence_and_a_turn_id(self):
        self.live()
        self.pin()
        converse.answer(self.cfg, self.board, self.card, "drop the old branch", 60,
                        pinned=True, turn_id="t9")
        call = self.calls[0]
        self.assertEqual(call["card"], self.card)
        self.assertEqual(call["said"], "drop the old branch")
        self.assertEqual(call["turn_id"], "t9")

    def test_a_turn_nobody_named_still_gets_an_id_so_it_can_be_retried(self):
        """A broken stream is retried by turn id; a turn with no id could only be asked
        all over again, which is the double delivery the id exists to prevent."""
        self.live()
        self.pin()
        converse.answer(self.cfg, self.board, self.card, "how far", 60, pinned=True)
        self.assertTrue(self.calls[0]["turn_id"])


class TheFallbackTest(KeptAliveCase):
    def test_a_server_that_is_not_answering_falls_back_and_the_turn_still_lands(self):
        self.live()
        self.pin()
        self.events = []
        self.away = converse.housetier.Away("nothing answered")
        self.fake.answer = "It is at review."
        result = converse.answer(self.cfg, self.board, self.card, "how far", 60, pinned=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["say"], "It is at review.")
        self.assertEqual(len(self.fake.turns), 1, "the one-shot did not run")

    def test_and_the_card_says_the_answer_came_another_way(self):
        """If the conversation had already written his sentence into a house that then
        died, that house may have answered a question nobody heard. The card is where
        that is visible afterwards."""
        self.live()
        self.pin()
        self.events = []
        self.away = converse.housetier.Away("the conversation's process ended mid-turn")
        converse.answer(self.cfg, self.board, self.card, "how far", 60, pinned=True)
        self.assertIn("asked as a turn of its own", self.notes_on())

    def test_a_conversation_that_dies_after_it_has_spoken_is_not_asked_twice(self):
        """Falling back here would speak the beginning of an answer, then the whole of a
        second one: a turn paid for twice and heard one and a half times."""
        self.live()
        self.pin()
        self.away = converse.housetier.Away("the conversation's process ended mid-turn")
        result = converse.answer(self.cfg, self.board, self.card, "how far", 60,
                                 pinned=True, progress=str(self.progress), turn_id="t1")
        self.assertFalse(result["ok"])
        self.assertEqual(getattr(self.fake, "turns", []), [])
        self.assertIn("the turn was ended", self.notes_on())

    def test_a_turn_that_errored_is_a_spoken_failure_and_never_a_second_turn(self):
        self.live()
        self.pin()
        self.events = []
        self.away = harness.HarnessError("the turn took longer than 60s, and it was ended")
        result = converse.answer(self.cfg, self.board, self.card, "how far", 60, pinned=True)
        self.assertFalse(result["ok"])
        self.assertIn("did not come back", result["say"])
        self.assertEqual(getattr(self.fake, "turns", []), [])


class TheAnswerAsItStreamsTest(KeptAliveCase):
    def test_each_finished_sentence_is_left_for_the_gateway_as_a_part(self):
        """V12: the answer is spoken as it streams. The lines go down the channel the
        narration already uses, marked as parts, because that is the one the watch loop
        is already claiming."""
        self.live()
        self.pin()
        converse.answer(self.cfg, self.board, self.card, "how far", 60, pinned=True,
                        progress=str(self.progress), turn_id="t1")
        lines = self.lines()
        self.assertEqual([line.get("action") or "part" for line in lines],
                         ["read", "part", "part"])
        parts = [line for line in lines if line.get("part")]
        self.assertEqual([line["text"] for line in parts],
                         ["Phase two is merged.", "The tests pass."])
        self.assertTrue(all(line["turn"] == "t1" for line in lines))

    def test_a_code_block_is_never_spoken_and_never_written_as_a_part(self):
        """V12 round 2: a fence is on the page, not in his ear. The event travels so the
        blackboard can use it later; nothing in the inbox carries the code."""
        self.live()
        self.pin()
        self.events = [{"type": "fence", "lang": "python", "body": "print(1)\n"},
                       {"type": "part", "text": "That is the change."}]
        converse.answer(self.cfg, self.board, self.card, "show me", 60, pinned=True,
                        progress=str(self.progress), turn_id="t1")
        written = "\n".join(p.read_text() for p in sorted(self.progress.glob("*.json")))
        self.assertNotIn("print(1)", written)
        self.assertEqual([line["text"] for line in self.lines()], ["That is the change."])

    def test_the_card_still_records_the_whole_answer_as_it_always_did(self):
        self.live()
        self.pin()
        converse.answer(self.cfg, self.board, self.card, "how far", 60, pinned=True,
                        progress=str(self.progress), turn_id="t1")
        self.assertIn('voice: "how far"', self.notes_on())
        self.assertIn("Phase two is merged. The tests pass.", self.notes_on())

    def test_with_nobody_listening_no_part_is_written_anywhere(self):
        self.live()
        self.pin()
        converse.answer(self.cfg, self.board, self.card, "how far", 60, pinned=True)
        self.assertFalse(self.progress.exists())


class TheLifecycleTest(KeptAliveCase):
    def test_connect_warms_the_session_after_taking_the_hold_and_spends_nothing(self):
        """The boot happens under "Connecting you now" and the tone, which is the whole
        of why the first sentence of a conversation is not the slowest one."""
        self.live()
        result = converse.connect(self.cfg, self.board, self.card)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.opened, [self.card])
        self.assertEqual(self.calls, [], "connecting must cost no turn")
        self.assertIsNotNone(self.hold_of())

    def test_release_closes_the_session_BEFORE_the_house_is_woken(self):
        """The order is the requirement, not a nicety: `claude --resume --bg` is refused
        while a headless process still holds that session."""
        order = []
        self.live()
        self.pin()
        with mock.patch.object(converse.housetier, "close_session",
                               lambda cfg, card, wake=False: order.append("close")
                               or converse.housetier.Shut(converse.housetier.CLOSED)):
            self.fake.on_wake = lambda: order.append("wake")
            converse.release(self.cfg, self.board, self.card)
        self.assertEqual(order, ["close", "wake"])
        self.assertIsNone(self.hold_of())

    def test_a_close_that_failed_leaves_the_house_down_and_says_so(self):
        """Something still holds that session, so the wake would be refused. Waking
        anyway would leave a house down with its hold gone and nothing recorded."""
        self.live()
        self.pin()
        self.close_answer = converse.housetier.Shut(converse.housetier.FAILED)
        converse.release(self.cfg, self.board, self.card)
        self.assertEqual(getattr(self.fake, "wakes", []), [])
        self.assertIn("would not close", self.notes_on())
        self.assertIsNone(self.hold_of())

    def test_a_server_that_is_away_owns_nothing_so_the_wake_goes_ahead(self):
        self.live()
        self.pin()
        self.close_answer = converse.housetier.Shut(converse.housetier.AWAY)
        converse.release(self.cfg, self.board, self.card)
        self.assertEqual(self.fake.wakes, [SESSION])

    def test_a_one_shot_turn_closes_its_session_before_putting_the_house_back(self):
        order = []
        self.live()
        with mock.patch.object(converse.housetier, "close_session",
                               lambda cfg, card, wake=False: order.append("close")
                               or converse.housetier.Shut(converse.housetier.CLOSED)):
            self.fake.on_wake = lambda: order.append("wake")
            converse.answer(self.cfg, self.board, self.card, "how far", 60)
        self.assertEqual(order, ["close", "wake"])

    def hold_of(self):
        return self.board.voice_hold_of(self.card)


class BoardFenceTest(ConverseCase):
    """A ```board block in an answer is DRAWN, not read out loud (K3, K10).

    A house in a voice conversation has no shell to run `keel board push` in mid-sentence,
    so it writes the lines in a fenced block instead and `keel/boardpen.py` pushes them to
    that card's own board. What he hears in its place is one sentence, and what lands on the
    board is what `keel board push` would have landed.
    """

    def drew(self) -> list[str]:
        from keel import boards
        return boards.ops_lines(self.cfg, "b-001")

    def answer_with(self, text: str, **kwargs):
        self.live()
        self.fake.answer = text
        return converse.answer(self.cfg, self.board, self.card_id, "draw me the flow", 60,
                               **kwargs)

    def test_a_board_block_is_pushed_to_the_cards_own_board(self):
        from keel import boards
        result = self.answer_with('Here it is:\n\n```board\nnode a box "a card"\n'
                                  'node drain server "the drain"\nedge a -> drain "claimed"\n```'
                                  '\n\nThat is the shape.')
        self.assertTrue(result["ok"])
        self.assertEqual(result["drew"], 1)
        record = boards.read_record(self.cfg, "b-001")
        self.assertEqual(record["source"], {"kind": "card", "card": self.card_id})
        self.assertEqual(record["actor"], "house", "the house drew it, not the voice")
        self.assertIn('node a box "a card"', self.drew())

    def test_the_block_is_not_in_what_he_hears_and_the_sentence_stands_in_for_it(self):
        result = self.answer_with('Here it is:\n\n```board\nnode a box "a"\n'
                                  'note a "hi"\n```\n\nThat is the shape.')
        self.assertNotIn("node a box", result["say"])
        self.assertNotIn("```", result["say"])
        self.assertIn("Here it is:", result["say"])
        self.assertNotIn("That is the shape.", result["say"],
                         "N7: nothing after the block is spoken")
        self.assertTrue(any("That is the shape." in note for note in self.notes()),
                        "the rest stays on the card")
        self.assertTrue(result["say"].endswith(converse.BOARD_DREW), result["say"])

    def test_the_card_keeps_the_exchange_without_the_block_in_it(self):
        self.answer_with('```board\nnode a box "a"\nnote a "hi"\n```\nDone.')
        self.assertTrue(any("Done." in note for note in self.notes()), self.notes())
        self.assertFalse(any("node a box" in note for note in self.notes()), self.notes())
        self.assertTrue(any("b-001" in note for note in self.notes()),
                        "the card says where it was drawn")


    def test_two_blocks_in_one_answer_are_two_pushes_and_one_sentence(self):
        result = self.answer_with('```board\nnode a box "one"\n```\n'
                                  'and\n```board\nnode b box "two"\n```\n')
        self.assertEqual(result["drew"], 2)
        self.assertEqual(result["say"].count(converse.BOARD_DREW), 1, result["say"])
        self.assertEqual([line for line in self.drew() if line.startswith("node")],
                         ['node a box "one"', 'node b box "two"'])


    def parts_written(self, progress: Path) -> list[str]:
        import json
        return [json.loads(path.read_text()).get("text", "")
                for path in sorted(progress.glob("*.json"))
                if json.loads(path.read_text()).get("part")]

    def test_a_streamed_push_that_landed_nothing_never_says_it_drew(self):
        """C1, the house half of c-423: the cutter used to speak "I have put that on the
        board." as the fence closed, whatever the push then did. Every line here is refused,
        so what he hears must say so."""
        block = '```board\ndraw a picture\nnode a\n```\n'
        self.stream(block)
        progress = self.dir / "progress"
        result = self.answer_with(block, progress=str(progress))
        spoken = self.parts_written(progress)
        self.assertNotIn(converse.BOARD_DREW, spoken)
        self.assertTrue(any(line.startswith(converse.BOARD_REFUSED) for line in spoken),
                        spoken)
        self.assertEqual(result["board"]["state"], "refused")
        self.assertNotIn(converse.BOARD_DREW, result["say"])

    def test_f7_streamed_speech_stops_only_after_a_block_that_reported(self):
        """N7 held at the client: the parts after a block that reported are not written for
        the gateway; an EMPTY block silences nothing."""
        answer = ('Lead.\n\n```board\n```\n\nAfter the empty one.\n\n'
                  '```board\nnode a box "a"\n```\n\nTail.\n')
        self.stream(answer)
        progress = self.dir / "progress"
        self.answer_with(answer, progress=str(progress))
        spoken = self.parts_written(progress)
        self.assertIn("After the empty one.", spoken)
        self.assertNotIn("Tail.", spoken)
        self.assertEqual(spoken[-1], converse.BOARD_DREW, spoken)

    def test_a_troubled_push_rides_into_the_next_turn_once(self):
        """C1: the report goes into the NEXT turn's framing so the house repairs it there,
        with the raw reason, and only once."""
        result = self.answer_with('```board\nframe graph "x"\nnode a box "a"\n```\n')
        self.assertEqual(result["board"]["state"], "partial")
        self.assertTrue(any(note.startswith("board report:") for note in self.notes()),
                        self.notes())
        self.fake.answer = "Fixed."
        converse.answer(self.cfg, self.board, self.card_id, "and now", 60)
        prompt = self.fake.turns[-1]["prompt"]
        self.assertIn("board report:", prompt)
        self.assertIn("frames are gone", prompt)
        converse.answer(self.cfg, self.board, self.card_id, "and again", 60)
        self.assertNotIn("board report:", self.fake.turns[-1]["prompt"])

    def test_a_clean_push_carries_nothing_forward(self):
        self.answer_with('```board\nnode a box "a"\n```\n')
        self.fake.answer = "Yes."
        converse.answer(self.cfg, self.board, self.card_id, "and now", 60)
        self.assertNotIn("board report:", self.fake.turns[-1]["prompt"])

    def stream(self, block: str, pieces: int = 1):
        """Feed `block` to a streamed turn in `pieces` deltas."""
        size = max(1, len(block) // pieces)
        cuts = [block[i:i + size] for i in range(0, len(block), size)]
        self.fake.records = [
            {"type": "stream_event",
             "event": {"type": "content_block_delta",
                       "delta": {"type": "text_delta", "text": piece}}}
            for piece in cuts]

    def test_a_streamed_turn_pushes_the_block_as_the_fence_closes(self):
        """On a voice turn the picture is on the board before the sentence about it is
        spoken, which is the whole point of doing it on the event rather than at the end."""
        from keel import boards
        block = '```board\nnode a box "a"\nnote a "live"\n```\n'
        self.stream(block, pieces=2)
        drawn_when = {}
        real = boards.push

        def watching(*args, **kwargs):
            # `turns` is only created by the first turn, and a listener that raises is
            # swallowed by `housetalk.Listener._send`, so this must not raise.
            drawn_when["mid_turn"] = not getattr(self.fake, "turns", [])
            return real(*args, **kwargs)

        with mock.patch.object(boards, "push", watching):
            result = self.answer_with(block, progress=str(self.dir / "progress"))
        self.assertEqual(result["drew"], 1)
        self.assertTrue(drawn_when["mid_turn"], "the push waited for the end of the turn")
        self.assertIn('note a "live"', self.drew())

    def test_a_block_pushed_mid_turn_is_not_pushed_again_at_the_end(self):
        block = '```board\nnode a box "a"\nnote a "once"\n```\n'
        self.stream(block)
        result = self.answer_with(block, progress=str(self.dir / "progress"))
        self.assertEqual(result["drew"], 1)
        self.assertEqual(self.drew().count('note a "once"'), 1, self.drew())

    def test_the_b_003_shape_lands_once_rather_than_twice_six_milliseconds_apart(self):
        """THE BUG, exactly as b-003 holds it (c-302, 2026-09-21).

        The house wrote ONE board block in a spoken answer. The stream pushed it as the
        fence closed; the finished text carried the same block and was pushed again, 6 ms
        later, because the streamed reading had a trailing "```" on it that the finished
        one did not and the pen compared the RAW bodies. b-003 has frames 4 to 6 and 7 to 9
        identical, and `'```' is not an op` in its skipped log to show where the difference
        came from.

        THE STREAM ENDS MID-FENCE HERE, with no newline after the closing ticks, which is
        what puts them on the cutter's buffer and then into the body `flush` closes.
        """
        from keel import boards
        block = '```board\nnode a box "a card"\nnote a "one"\n```'
        self.stream(block, pieces=3)
        result = self.answer_with(block + "\n", progress=str(self.dir / "progress"))
        self.assertEqual(result["drew"], 1, "the same block was drawn twice")
        self.assertEqual(self.drew().count('note a "one"'), 1, self.drew())
        self.assertEqual(self.drew().count('node a box "a card"'), 1, self.drew())
        markers = [line for line in self.drew() if line.startswith(boards.PUSH_MARK)]
        self.assertEqual(len(markers), 1, "two pushes landed where one block was written")
        skipped = boards.board_dir(self.cfg, "b-001") / boards.SKIPPED_FILE
        self.assertNotIn("is not an op", skipped.read_text() if skipped.exists() else "")


class TheHouseEndsTheConversationTest(KeptAliveCase):
    """The house may say goodbye and END the conversation (2026-09-21, from his own session).

    Inside c-302 he said "Okay, you can exit the pouse now" and then "You can go back". The
    gateway's phrase table matched neither, so both reached the house as questions and the
    house answered "I can't end my own session, tap Stop on the deck". It is the second net:
    the framing tells the house to answer a request to leave with one short goodbye and the
    directive, and the verb reports it beside the sentence. The gateway then does exactly
    what a spoken leave phrase does; nothing here releases anything.
    """

    def leave_event(self):
        return [{"type": "part", "text": "All right, talk later."},
                {"type": "leave"}]

    def test_a_streamed_answer_that_ends_with_the_directive_asks_to_leave(self):
        self.live()
        self.pin()
        self.events = self.leave_event()
        self.said_answer = "All right, talk later.\n\n<<keel-leave>>"
        result = converse.answer(self.cfg, self.board, self.card, "you can go back", 60,
                                 pinned=True, progress=str(self.progress), turn_id="t1")
        self.assertTrue(result["leave"], result)
        self.assertEqual(result["say"], "All right, talk later.")

    def test_the_token_is_never_in_what_is_spoken_or_in_what_the_card_keeps(self):
        self.live()
        self.pin()
        self.events = self.leave_event()
        self.said_answer = "All right, talk later.\n\n<<keel-leave>>"
        result = converse.answer(self.cfg, self.board, self.card, "you can go back", 60,
                                 pinned=True, progress=str(self.progress), turn_id="t1")
        self.assertNotIn("keel-leave", result["say"])
        self.assertNotIn("keel-leave", self.notes_on())

    def test_the_one_shot_path_reads_it_off_the_finished_answer(self):
        """The phone Harbor's single question and a turn typed into the ask box have no
        stream at all, so the directive comes out of the whole text instead."""
        self.live()
        self.fake.answer = "Goodbye for now. <<keel-leave>>"
        result = converse.answer(self.cfg, self.board, self.card, "that's all", 60)
        self.assertTrue(result["leave"], result)
        self.assertEqual(result["say"], "Goodbye for now.")

    def test_an_ordinary_answer_asks_for_nothing(self):
        self.live()
        self.pin()
        result = converse.answer(self.cfg, self.board, self.card, "how far are you", 60,
                                 pinned=True)
        self.assertFalse(result["leave"], result)

    def test_a_directive_quoted_inside_a_sentence_is_text_and_not_a_goodbye(self):
        """He can ask how leaving works out loud. The token is stripped wherever it sits,
        because it is gibberish read aloud, and only one at the very end ends anything."""
        self.live()
        self.fake.answer = "You would end with <<keel-leave>> and I would read it there."
        result = converse.answer(self.cfg, self.board, self.card, "how does leaving work",
                                 60)
        self.assertFalse(result["leave"], result)
        self.assertNotIn("keel-leave", result["say"])
        self.assertIn("I would read it there.", result["say"])

    def test_the_hold_is_not_released_here_because_the_gateway_owns_that(self):
        """One release path, and it is the one the spoken phrase takes: the gateway hears
        `leave` and calls the same `keel converse --release` a tap on the header calls."""
        self.live()
        self.pin()
        self.events = self.leave_event()
        self.said_answer = "All right, talk later. <<keel-leave>>"
        converse.answer(self.cfg, self.board, self.card, "you can go back", 60, pinned=True)
        self.assertIsNotNone(self.board.voice_hold_of(self.card))

    def test_an_answer_that_was_only_the_directive_still_says_goodbye(self):
        """The framing asks for a sentence and then the token. A house that skipped the
        sentence would leave nothing to say once the token is out, and he would hear the
        gateway's "that did not come back" and then be taken out of the house."""
        self.live()
        self.fake.answer = "<<keel-leave>>"
        result = converse.answer(self.cfg, self.board, self.card, "that's all", 60)
        self.assertTrue(result["leave"], result)
        self.assertEqual(result["say"], converse.LEAVING_SAID)
        self.assertIn(converse.LEAVING_SAID, self.notes_on())
