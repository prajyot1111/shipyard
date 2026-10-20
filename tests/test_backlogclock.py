"""c-673: the backlog clock against the real writers. Each tap of his and each pass over
many cards is driven through the function the deck or the script calls, on a card that
reached review 8 days ago, with the board's clock pinned and the harness faked.

`kb` runs in process (`TapCase.kb`): the real verb handlers of `keel/cli.py`, on the pinned
board, as him. A real `bin/kb` would stamp its events with the wall clock.
"""

import contextlib
import io
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from keel import actions, asks, cli, dropin, flowmoves, flows, house, idleclose, outcomeboards, shipupgrade, tellhouse
from keel.board import Board, Refused
from tests.helpers import SESSION, FakeHarness, background_row, make_config, make_repo

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=timezone.utc)
FLOW = '''name = "Ours"
description = "Staging base, dev review on his word."

[[branch]]
id = "card"
label = "card branch"
kind = "card"

[[branch]]
id = "dev"
label = "dev_review"
kind = "environment"

[[move]]
id = "to-dev"
label = "Merge to dev review"
from = "card"
to = "dev"
by = "you"
stages = ["review", "shipping"]
group = "Try it live"
pushes = ["dev"]
prompt = "Merge {branch} into {target} and push it; resolve conflicts yourself."
about = "Puts the work on dev review to try it live."
'''


class TapCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.settled)       # before the directory goes: no tell outlives a test
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir, repos={"keel": make_repo(self.dir / "repo")})
        self.cfg.host = "mac"
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        self.fake = FakeHarness()
        for target, name, stand_in in ((house, "harness", self.fake), (actions, "harness", self.fake),
                                       (idleclose, "harness", self.fake), (actions, "run_kb", self.kb),
                                       (actions, "run_keel", lambda *a, **k: "")):
            patch = mock.patch.object(target, name, stand_in)
            patch.start()
            self.addCleanup(patch.stop)
        self.today = self.days_ago(0)

    def days_ago(self, days: float) -> str:
        stamp = (NOW - timedelta(days=days)).isoformat(timespec="seconds")
        self.board.now = lambda: stamp
        return stamp

    def settled(self) -> None:
        """Every background tell the tap started has finished (`tellhouse.send_alone`)."""
        tellhouse.join(10)
        with tellhouse._threads_lock:
            self.assertEqual([thread.name for thread in tellhouse._threads if thread.is_alive()], [])

    def act(self, **body):
        """A tap as the deck sends it, waited for: its tell runs on a thread of its own."""
        try:
            return actions.act(self.cfg, self.board, body)
        finally:
            self.settled()

    def kb(self, cfg, argv, timeout=None, stdin="", voice=False):
        """`actions.run_kb` without the process: the verb's own handler, as him."""
        args = cli.build_parser().parse_args([*argv, "--json"])
        args.config = cfg
        try:
            return args.handler(self.board, args, "voice" if voice else "human")
        except Refused as refusal:
            raise actions.ActionError(str(refusal)) from None

    def old_review(self, days: float = 8, session: str = SESSION, options: dict | None = None) -> str:
        """A card whose house brought it to review `days` ago; its session is on record."""
        self.reached = self.days_ago(days)
        card_id = self.board.create("personal", "sat at review", repo="keel", actor="human", options=options)
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        self.board.set_session(card_id, session, "drain", bg_id=session[:8])
        self.board.stage(card_id, "review", "house", plan_ref="plan.md", output_ref="out.md")
        self.days_ago(0)
        self.before = len(self.board.events(card_id))
        return card_id

    def his(self, card_id: str) -> list[tuple[str, str]]:
        """(kind, text) of every event of his the tap or the pass wrote."""
        return [(e["kind"], e["text"]) for e in self.board.events(card_id)[self.before:]
                if e["actor"] in ("human", "voice")]

    def assert_still_backlog(self, card_id: str):
        derived = self.board.get(card_id)["derived"]
        self.assertTrue(derived["backlog"])
        self.assertFalse(derived["needs_you"])
        self.assertEqual(derived["backlog_since"], self.reached)

    def assert_brought_out(self, card_id: str):
        derived = self.board.get(card_id)["derived"]
        self.assertFalse(derived["backlog"])
        self.assertEqual(derived["backlog_since"], self.today)


class PassTest(TapCase):
    """c-673 review F1, F3: a pass over many cards writes under his name, and is not his
    action on any one of them."""

    def test_the_outcome_boards_backfill_leaves_a_card_in_the_backlog(self):
        card_id = self.old_review()
        pick = {"card": card_id, "stage": "review", "host": self.cfg.host, "title": "",
                "reasons": ["no Code flow board"], "plan_boards": []}
        outcomeboards.send(self.cfg, self.board, pick)
        self.assertEqual([kind for kind, _ in self.his(card_id)], ["relay", "set"])
        [relay] = self.board.get(card_id)["derived"]["relays"]
        self.assertEqual((relay["what"], relay["to"]), ("resume", "mac"), "the drain still carries it")
        self.assertIn("board-only turn", relay["prompt"])
        self.assert_still_backlog(card_id)

    def test_the_ship_upgrade_leaves_a_card_in_the_backlog(self):
        card_id = self.old_review()
        old = {"round": 2, "batch": [{"handle": "c11"}], "since": self.reached}
        self.board.set_fields(card_id, {"options": {"shipping": old, "ship_now": True}}, "drain")
        self.before = len(self.board.events(card_id))
        steps = shipupgrade.apply(self.cfg, self.board, self.board.get(card_id))
        self.assertTrue(steps)
        self.assertEqual([kind for kind, _ in self.his(card_id)], ["set", "note"])
        self.assert_still_backlog(card_id)

    def test_close_all_idle_leaves_every_card_in_the_backlog(self):
        sessions = [SESSION, "0abc7777-0000-4000-8000-000000000007", "0abc6666-0000-4000-8000-000000000006"]
        cards = [self.old_review(session=session) for session in sessions]
        self.fake.rows = [background_row(card_id, session) for card_id, session in zip(cards, sessions)]
        result = self.act(verb=idleclose.VERB, ids=cards)
        self.assertEqual((len(result["closed"]), result["refused"]), (3, {}))
        for card_id in cards:
            [note] = [e for e in self.board.events(card_id) if (e["data"] or {}).get("stop") == "idle"]
            self.assertEqual((note["actor"], note["data"]), ("human", {"bulk": True, "stop": "idle"}))
            self.assertTrue(self.board.get(card_id)["derived"]["closed_idle"], "the mark means what it meant")
            self.assert_still_backlog(card_id)

    def test_his_close_of_one_idle_house_is_his_action_on_that_card(self):
        card_id = self.old_review()
        self.fake.rows = [background_row(card_id, SESSION)]
        self.act(verb=idleclose.VERB, id=card_id)
        self.assertEqual(self.board.events(card_id)[-1]["data"], {"stop": "idle"})
        self.assertTrue(self.board.get(card_id)["derived"]["closed_idle"])
        self.assert_brought_out(card_id)

    def test_one_close_carried_to_another_machine_is_his_too(self):
        card_id = self.old_review()
        self.board.relay(card_id, "close-idle", "human", "mini")
        self.assert_brought_out(card_id)


ASKED = ("note", "resume asked from the deck")


class ResumeTest(TapCase):
    """c-673 review 3: his TAP counts, whatever became of it. One event of his per Resume,
    written after the attempt by its outcome; only a tap refused because the conversation
    is open in a terminal (or for no house, or a done card) writes nothing."""

    FAILS = "claude --resume --bg failed"

    def tap(self, card_id: str, **body) -> dict:
        return self.act(verb="house.resume", id=card_id, **body)

    def refused(self, card_id: str, **body) -> str:
        with self.assertRaises(actions.ActionError) as caught:
            self.tap(card_id, **body)
        return str(caught.exception)

    def test_his_resume_of_an_exited_house_brings_the_card_out(self):
        card_id = self.old_review()
        self.tap(card_id)
        self.assertEqual(len(self.fake.resumes), 1)
        self.assertEqual(self.his(card_id), [ASKED])
        self.assert_brought_out(card_id)

    def test_his_resume_of_an_idle_live_house_is_told_and_brings_the_card_out(self):
        card_id = self.old_review()
        self.fake.rows = [background_row(card_id, SESSION)]
        self.fake.relay_answer = "sent"
        self.tap(card_id)
        self.assertEqual(len(self.fake.relays), 1, "the message went, on its own thread, and was waited for")
        self.assertEqual(self.fake.resumes, [], "told in its own session, never resumed")
        self.assertEqual(self.his(card_id), [ASKED])
        self.assert_brought_out(card_id)

    def test_a_tell_that_fails_or_is_unclear_on_its_thread_leaves_his_ask_standing(self):
        for answer in ("failed", "unclear"):
            with self.subTest(answer):
                card_id = self.old_review()
                self.fake.rows = [background_row(card_id, SESSION)]
                self.fake.relay_answer, self.fake.relays = answer, []
                self.fake.resume_bg = mock.Mock(side_effect=self.fake.HarnessError(self.FAILS))
                self.tap(card_id)
                self.assertEqual(len(self.fake.relays), 1)
                self.assertEqual(self.his(card_id), [ASKED])
                self.assert_brought_out(card_id)

    def test_a_tap_held_for_a_working_house_is_its_relay_alone(self):
        card_id = self.old_review()
        self.fake.rows = [background_row(card_id, SESSION, status="busy")]
        result = self.tap(card_id)
        self.assertTrue(result["held"])
        self.assertEqual(self.his(card_id), [("relay", "resume")])
        self.assert_brought_out(card_id)

    def blocked(self) -> str:
        card_id = self.old_review()
        self.board.block(card_id, "which key?", "house")
        self.before = len(self.board.events(card_id))
        return card_id

    def test_his_words_that_reach_the_house_are_his_answers_note_and_no_ask(self):
        card_id = self.blocked()
        self.tap(card_id, said="the one in the vault")
        self.assertEqual(self.his(card_id), [("unblock", None), ("note", "answered the block: the one in the vault")])
        self.assert_brought_out(card_id)

    def test_his_words_on_a_resume_that_fails_leave_the_ask(self):
        """Review 2's gap: his answer is noted only once the house has it, so a failure
        with words left nothing of his."""
        card_id = self.blocked()
        self.fake.resume_bg = mock.Mock(side_effect=self.fake.HarnessError(self.FAILS))
        self.assertEqual(self.refused(card_id, said="the one in the vault"), f"resume failed: {self.FAILS}")
        self.assertEqual(self.his(card_id), [ASKED])
        self.assertEqual(self.board.get(card_id)["blocked_reason"], "which key?", "nothing went, so it stays blocked")
        self.assert_brought_out(card_id)

    def test_a_plain_resume_that_fails_leaves_the_ask_and_the_same_refusal(self):
        card_id = self.old_review()
        self.fake.resume_bg = mock.Mock(side_effect=self.fake.HarnessError(self.FAILS))
        self.assertEqual(self.refused(card_id), f"resume failed: {self.FAILS}")
        self.assertEqual(self.his(card_id), [ASKED])
        self.assert_brought_out(card_id)

    def test_a_listing_that_fails_is_read_as_no_live_house_and_the_tap_resumes(self):
        card_id = self.old_review()
        self.fake.rows, self.fake.listing_fails = [background_row(card_id, SESSION)], True
        result = self.tap(card_id)
        self.assertEqual(result["session_id"], SESSION)
        self.assertEqual(len(self.fake.resumes), 1)
        self.assertEqual(self.his(card_id), [ASKED])
        self.assert_brought_out(card_id)

    def test_a_listing_that_cannot_run_is_a_refusal_in_words_with_his_ask_noted(self):
        card_id = self.old_review()
        self.fake.agents = mock.Mock(side_effect=OSError("claude: not found"))
        self.assertEqual(self.refused(card_id), "resume failed: claude: not found")
        self.assertEqual(self.fake.resumes, [])
        self.assertEqual(self.his(card_id), [ASKED])
        self.assert_brought_out(card_id)

    def test_a_refusal_raised_by_the_resume_is_noted_as_asked(self):
        """Any refusal but the terminal one, stood in for here: he was on the card."""
        card_id = self.old_review()
        refusal = house.Refused(f"{card_id} is refused, in the resume's own words")
        with mock.patch.object(house, "resume", side_effect=refusal):
            self.assertEqual(self.refused(card_id), f"{card_id} is refused, in the resume's own words")
        self.assertEqual(self.his(card_id), [ASKED])
        self.assert_brought_out(card_id)

    def test_a_card_with_no_model_is_blocked_by_the_drain_and_his_ask_is_noted(self):
        """The real refusal (`house.require_model`): the card is blocked under the drain,
        then the tap is refused in the same words, and his ask follows."""
        card_id = self.old_review()
        self.board.conn.execute("UPDATE cards SET model = NULL WHERE id = ?", (card_id,))
        said = self.refused(card_id)
        self.assertTrue(said.startswith(f"no model on {card_id}, and a house never runs on the account's default."))
        self.assertEqual(self.fake.resumes, [])
        written = [(e["kind"], e["actor"], e["text"]) for e in self.board.events(card_id)[self.before:]]
        self.assertEqual(written, [("block", "drain", said), ("note", "human", ASKED[1])])
        self.assertEqual(self.board.get(card_id)["blocked_reason"], said)
        self.assert_brought_out(card_id)

    def test_a_note_that_cannot_be_written_never_changes_the_tap(self):
        card_id = self.old_review()
        with mock.patch.object(self.board, "note", side_effect=Refused("the board says no")), \
                contextlib.redirect_stderr(io.StringIO()) as said:
            result = self.tap(card_id)
        self.assertEqual(result["session_id"], SESSION)
        self.assertIn("was not noted", said.getvalue())
        self.fake.resume_bg = mock.Mock(side_effect=self.fake.HarnessError(self.FAILS))
        with mock.patch.object(self.board, "note", side_effect=sqlite3.OperationalError("locked")), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.refused(card_id), f"resume failed: {self.FAILS}")
        self.assertEqual(self.his(card_id), [])

    def test_a_tap_that_is_not_a_resume_of_this_card_writes_nothing(self):
        cases = {}
        card_id = self.old_review()
        self.fake.rows = [dict(background_row(card_id, SESSION), kind=dropin.INTERACTIVE)]
        cases[card_id] = (f"{card_id}'s conversation is open in a terminal; a resume would start a second "
                          f"copy of it. Carry on there, or quit it first")
        self.assert_refused_untouched(card_id, cases[card_id])
        self.fake.rows = []
        held = self.old_review()
        # no `until`: such a hold holds, whatever the clock says (`views.dropin_holding`)
        self.board.set_fields(held, {"options": {"dropin_hold": {"at": self.today, "session": SESSION}}}, "human")
        self.assert_refused_untouched(held, f"Drop in handed you {held}'s conversation to resume in a terminal, "
                                            f"so it is not resumed here as well. Quit that session, or wait "
                                            f"for the hold to run out if you never opened it", backlog=False)
        # Both at once, the state that broke in review 2: the hold is asked first, so its
        # sentence answers, and the listing is not what refuses.
        self.fake.rows = [dict(background_row(held, SESSION), kind=dropin.INTERACTIVE)]
        self.assert_refused_untouched(held, f"Drop in handed you {held}'s conversation to resume in a terminal, "
                                            f"so it is not resumed here as well. Quit that session, or wait "
                                            f"for the hold to run out if you never opened it", backlog=False)
        self.fake.rows = []
        gone = self.old_review()
        self.board.conn.execute("UPDATE cards SET session_id = NULL WHERE id = ?", (gone,))
        self.assert_refused_untouched(gone, f"{gone} has no house session to resume; use Retry")
        done = self.old_review()
        self.board.conn.execute("UPDATE cards SET stage = 'done' WHERE id = ?", (done,))
        self.before = len(self.board.events(done))
        self.assertIn("done", self.refused(done))
        self.assertEqual(self.board.events(done)[self.before:], [])

    def assert_refused_untouched(self, card_id: str, sentence: str, backlog: bool = True):
        self.before = len(self.board.events(card_id))
        self.assertEqual(self.refused(card_id), sentence)
        self.assertEqual(self.board.events(card_id)[self.before:], [], "nothing at all, of his or anyone's")
        self.assertEqual(self.fake.resumes, [])
        if backlog:
            self.assert_still_backlog(card_id)


class FlowMoveTest(TapCase):
    """What happened on 2026-10-06, through the deck's own verb: a flow move tapped on a
    card 8 days at review. The move records its own events, so it writes no Resume ask."""

    def setUp(self):
        super().setUp()
        path = self.dir / "flow.toml"       # a checkout's config has no space directory
        path.write_text(FLOW)
        patch = mock.patch.object(flows, "space_file", lambda cfg, space: path)
        patch.start()
        self.addCleanup(patch.stop)
        self.card_id = self.old_review(options={"branch": "feature/x"})

    def move(self) -> dict:
        return self.act(verb=flowmoves.VERB, id=self.card_id, move="to-dev")

    def test_his_flow_move_is_its_grant_and_its_note_and_brings_the_card_out(self):
        self.assertTrue(self.board.get(self.card_id)["derived"]["backlog"])
        self.move()
        self.assertEqual(len(self.fake.resumes), 1)
        self.assertEqual(self.his(self.card_id),
                         [("set", None), ("note", "flow move asked: Merge to dev review (to-dev)")])
        self.assert_brought_out(self.card_id)

    def test_a_flow_move_whose_tell_fails_is_still_him_on_the_card(self):
        self.fake.resume_bg = mock.Mock(side_effect=self.fake.HarnessError("claude --resume --bg failed"))
        with self.assertRaises(actions.ActionError):
            self.move()
        self.assertEqual(self.his(self.card_id), [("set", None), ("set", None)], "the grant, then taken back")
        self.assertFalse(self.board.get(self.card_id)["options"].get(flowmoves.OPTION))
        self.assert_brought_out(self.card_id)


class TapTest(TapCase):
    """c-673 review F4: the other taps the rule names, each through its own writer."""

    def test_his_stop_brings_the_card_out(self):
        card_id = self.old_review()
        self.fake.rows = [background_row(card_id, SESSION)]
        self.act(verb="house.stop", id=card_id)
        [(kind, text)] = self.his(card_id)
        self.assertEqual(kind, "note")
        self.assertEqual(self.board.events(card_id)[-1]["data"], {"stop": "human"})
        self.assert_brought_out(card_id)

    def test_his_queued_approve_outcome_brings_the_card_out_while_it_lands(self):
        card_id = self.old_review()
        self.board.switches = {"merge_queue"}
        self.board.relay(card_id, "land", "human", "mac", sha="a" * 40)
        self.assertEqual(self.his(card_id), [("relay", "land")])
        derived = self.board.get(card_id)["derived"]
        self.assertEqual((derived["backlog"], derived["backlog_since"]), (False, self.today))

    def answered(self, actor: str, **how) -> str:
        card_id = self.old_review()
        ask = asks.raise_ask(self.board, "bosun", "decision", "keep the old name?", "two callers use it",
                             ["yes|keep it", "no|rename it"], card=card_id)
        self.before = len(self.board.events(card_id))
        asks.answer(self.board, ask["id"], actor, letter="A", **how)
        self.assertEqual([e["kind"] for e in self.board.events(card_id)[self.before:]], ["ask"])
        return card_id

    def test_his_answer_to_an_ask_by_tap_and_by_voice_brings_the_card_out(self):
        for actor in ("human", "voice"):
            with self.subTest(actor):
                card_id = self.answered(actor)
                self.assertEqual([kind for kind, _ in self.his(card_id)], ["ask"])
                self.assert_brought_out(card_id)

    def test_an_answer_bosun_records_from_chat_is_bosuns_and_moves_nothing(self):
        card_id = self.answered("bosun", by="chat", message="yes, keep it")
        self.assertEqual(self.his(card_id), [])
        self.assert_still_backlog(card_id)


if __name__ == "__main__":
    unittest.main()
