"""V2-2: "Resume and open in app" brings a house back with NO turn and hands out its link.

He wants to type into a house in the Claude app without a "continue" turn going in first
(2026-09-24). `house.open_app` wakes an exited house (`house.wake`: no prompt, no model
turn, the same session and the same claude.ai link), leaves a listed idle house exactly as
it is, makes sure the card carries the link of the session it is on now, and returns it for
the page to open. A house in its turn is left alone too, and only its link is read (c-653).
It is refused where a resume would fork his own conversation (a session open in his
terminal, a Drop in hold).
"""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from keel import actions, drain, dropin, house, login, openapp, views
from keel.board import Board
from tests.helpers import SESSION, FakeHarness, FakeMachine, aged, background_row, make_config

LINK = "https://claude.ai/code/session_01Q7n8exxgqsxNsR3b2Fwi8J"
OLD_LINK = "https://claude.ai/code/session_01OLDOLDOLDOLDOLDOLDOLD1"
OTHER = "22222222-3333-4444-5555-666666666666"


def stamp(delta: timedelta) -> str:
    return (datetime.now().astimezone() + delta).isoformat(timespec="seconds")


class OpenAppCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = make_config(Path(self.tmp.name))
        self.cfg.drain_paused = True
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        self.fake = FakeHarness()
        self.fake.app_link = None                 # the log prints nothing unless a test says so
        for module in (dropin, actions, house, drain, login, openapp):
            patch = mock.patch.object(module, "harness", self.fake)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(drain, "machine", FakeMachine())
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(house.time, "sleep", lambda seconds: None)
        patch.start()
        self.addCleanup(patch.stop)
        self.kb = []
        patch = mock.patch.object(actions.subprocess, "run", side_effect=self.fake_kb)
        patch.start()
        self.addCleanup(patch.stop)

    def fake_kb(self, argv, **kwargs):
        """The deck's `kb` writes, carried out on this board as his."""
        self.kb.append(list(argv))
        args = [a for a in argv[1:] if a != "--json"]
        if args and args[0] == "unblock":
            self.board.unblock(args[1], "human")
        elif args and args[0] == "note":
            self.board.note(args[1], args[2], "human")
        return mock.Mock(returncode=0, stdout="null", stderr="")

    def card(self, link: str | None = LINK, blocked: bool = False, stage: str = "building") -> str:
        card_id = self.board.create("personal", "an errand", actor="human")
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, stage, "drain")
        self.board.set_session(card_id, SESSION, "drain", bg_id=SESSION[:8], app_link=link)
        if blocked:
            self.board.block(card_id, "which key do I use?", "drain")
        return card_id

    def open(self, card_id: str) -> dict:
        return actions.act(self.cfg, self.board, {"verb": "house.open_app", "id": card_id})

    def refused(self, card_id: str) -> str:
        with self.assertRaises(actions.ActionError) as refusal:
            self.open(card_id)
        return str(refusal.exception)

    def wakes(self) -> list:
        return getattr(self.fake, "wakes", [])

    def assert_no_turn(self):
        """No RESUME prompt, no turn of any kind, nothing stopped."""
        self.assertEqual(self.fake.resumes, [])
        self.assertEqual(getattr(self.fake, "turns", []), [])
        self.assertEqual(getattr(self.fake, "stops", []), [])


class NoTurnTest(OpenAppCase):
    def test_an_exited_house_is_woken_and_no_resume_prompt_is_sent(self):
        card_id = self.card()
        answer = self.open(card_id)
        self.assertEqual(self.wakes(), [SESSION])
        self.assert_no_turn()
        self.assertEqual(answer["link"], LINK)
        self.assertTrue(answer["woken"])

    def test_a_house_whose_conversation_is_gone_is_started_afresh_and_its_new_link_opened(self):
        """c-654: a wake of a conversation the harness no longer holds launches and then
        fails, so the house starts afresh from the card's record and that session is opened."""
        card_id = self.card(link=OLD_LINK)
        aged(self.board, card_id, 40)
        self.fake.gone, self.fake.started_as, self.fake.app_link = {SESSION}, OTHER, LINK
        answer = self.open(card_id)
        self.assertEqual((self.wakes(), self.fake.resumes), ([], []))
        self.assertEqual(len(self.fake.starts), 1)
        self.assertIn("context.md", self.fake.starts[0]["prompt"])
        self.assertEqual(self.board.get(card_id)["session_id"], OTHER)
        self.assertEqual(answer["link"], LINK)

    def test_a_done_card_whose_conversation_is_gone_is_refused_and_nothing_is_woken(self):
        """c-654 review: a done card's house is never started again, and a wake of a gone
        conversation only launches and fails."""
        card_id = self.card()
        self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="out.md")
        self.board.approve(card_id, "outcome", "human")
        aged(self.board, card_id, 40)
        self.fake.gone = {SESSION}
        self.assertIn("no longer holds", self.refused(card_id))
        self.assertEqual((self.wakes(), self.fake.starts), ([], []))

    def test_a_withheld_fresh_start_refuses_the_tap_until_his_own_unblock(self):
        card_id = self.card(link=OLD_LINK)
        self.board.record_hook(card_id, "Stop", {"session_id": SESSION})
        aged(self.board, card_id, 5)
        self.fake.gone, self.fake.started_as, self.fake.app_link = {SESSION}, OTHER, LINK
        self.assertIn("unblock the card yourself", self.refused(card_id))
        self.assertEqual((self.wakes(), self.fake.starts), ([], []))
        self.board.unblock(card_id, "human")
        self.assertEqual(self.open(card_id)["link"], LINK)
        self.assertEqual((len(self.fake.starts), self.board.get(card_id)["session_id"]), (1, OTHER))

    def test_a_listed_idle_house_is_not_restarted(self):
        card_id = self.card()
        self.fake.rows = [background_row(card_id, SESSION)]
        answer = self.open(card_id)
        self.assertEqual(self.wakes(), [])
        self.assert_no_turn()
        self.assertEqual(answer["link"], LINK)
        self.assertFalse(answer["woken"])


class RefusedLikeAResumeTest(OpenAppCase):
    def test_a_house_in_its_turn_is_left_alone_and_its_link_is_read(self):
        """c-653 review (r1.F1): c-135 was answering review with no link on record, and the
        tap that would fetch one was refused, so there was no way into it."""
        card_id = self.card(link=None)
        self.fake.rows = [background_row(card_id, SESSION, status="busy")]
        self.fake.app_link = LINK
        answer = self.open(card_id)
        self.assertEqual((answer["link"], answer["woken"]), (LINK, False))
        self.assertEqual(self.board.get(card_id)["options"]["app_link"], LINK)
        self.assertEqual(self.wakes(), [])
        self.assert_no_turn()

    def test_a_session_open_in_his_terminal_is_refused(self):
        card_id = self.card()
        self.fake.rows = [{"pid": 2, "cwd": "/x", "kind": "interactive", "startedAt": 0,
                           "sessionId": SESSION, "name": card_id, "status": "idle"}]
        self.assertIn("open in a terminal", self.refused(card_id))
        self.assertEqual(self.wakes(), [])

    def test_a_drop_in_hold_is_refused(self):
        card_id = self.card()
        self.board.set_fields(card_id, {"options": {views.DROPIN_HOLD_OPTION: {
            "at": stamp(timedelta()), "until": stamp(timedelta(minutes=10)),
            "session": SESSION, "seen": False}}}, "human")
        self.assertIn("Drop in handed you", self.refused(card_id))
        self.assertEqual(self.wakes(), [])


    def test_a_caller_cannot_send_it(self):
        card_id = self.card()
        with self.assertRaises(actions.ActionError):
            actions.act(self.cfg, self.board, {"verb": "house.open_app", "id": card_id,
                                               "caller": {"actor": "house", "card": card_id}})


class TheLinkIsTheCurrentOneTest(OpenAppCase):
    def test_the_link_returned_is_the_card_s_current_one(self):
        card_id = self.card(link=LINK)
        self.fake.app_link = "https://claude.ai/code/session_01SOMETHINGELSEENTIRELY"
        self.assertEqual(self.open(card_id)["link"], LINK)
        self.assertEqual(self.fake.links_asked, [], "a card that has its link polls nothing")

    def test_a_card_with_no_link_polls_the_log_and_keeps_what_it_finds(self):
        card_id = self.card(link=None)
        self.fake.app_link = LINK
        self.assertEqual(self.open(card_id)["link"], LINK)
        self.assertEqual(self.board.get(card_id)["options"].get("app_link"), LINK)
        self.assertEqual(self.fake.links_asked, [SESSION[:8]])

    def test_a_link_left_from_an_older_session_is_not_handed_out(self):
        """A resume that found no link keeps the old session's link in `options`, and that
        link opens a conversation the card is no longer on."""
        card_id = self.card(link=OLD_LINK)
        self.board.set_session(card_id, OTHER, "drain", bg_id=OTHER[:8])
        self.assertEqual(self.board.get(card_id)["options"].get("app_link"), OLD_LINK)
        self.fake.app_link = LINK
        self.assertEqual(self.open(card_id)["link"], LINK)
        self.assertEqual(self.fake.links_asked, [OTHER[:8]])


    def test_a_listed_house_is_polled_by_its_own_short_id(self):
        card_id = self.card(link=None)
        row = background_row(card_id, SESSION)
        row["id"] = "bg123456"
        self.fake.rows = [row]
        self.fake.app_link = LINK
        self.open(card_id)
        self.assertEqual(self.fake.links_asked, ["bg123456"])


class NoLinkTest(OpenAppCase):
    def test_no_link_says_so_and_leaves_the_house_awake(self):
        card_id = self.card(link=None, blocked=True)
        answer = self.open(card_id)
        self.assertIsNone(answer["link"])
        self.assertIn("awake", answer["note"])
        self.assertEqual(self.wakes(), [SESSION])
        self.assert_no_turn()
        self.assertTrue(self.board.get(card_id)["blocked_reason"], "the block is still his")

    def test_with_a_link_a_blocked_card_is_unblocked_as_a_resume_would(self):
        card_id = self.card(blocked=True)
        self.open(card_id)
        self.assertIsNone(self.board.get(card_id)["blocked_reason"])


if __name__ == "__main__":
    unittest.main()
