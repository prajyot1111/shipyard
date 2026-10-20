"""Ask (P2-9): a question on a plan, cleared WITHOUT sending the plan back.

On any block or selection he picks Ask instead of Note. It does not wait for Send: `plan.ask`
records it as a mark on the card and resumes the house at once with a prompt that forbids
revising the plan and moving the card; the house answers with `kb reply`, which records the
answer on the card tied to the question's mark (one store, no poll), and the page pins it
under his question. The card stays at its gate, the plan file is unchanged, and his other
answers and notes wait for the final Send. A working house is not interrupted: the ask queues
behind the question before it (the reply hands it over), or is held until its turn ends (c-598).
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import actions, cli, house, planstate, prompts
from keel.board import Board, Refused
from tests.helpers import SESSION, CliCase, make_config
from tests.test_planstate import kb

RESUMED = {"bg_id": SESSION[:8], "session_id": SESSION}
PLAN = "---\nkind: plan\ncard: c-001\ntitle: t\n---\n# c-001 t\n\nThe summary.\n"


class AskCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = make_config(Path(tmp.name))
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        self.card = self.board.create("personal", "a planned card", repo="keel", autonomy="attended")
        self.plan = self.cfg.card_dir(self.card) / "plan.md"
        self.plan.parent.mkdir(parents=True, exist_ok=True)
        self.plan.write_text(PLAN)
        self.board.stage(self.card, "assigned", "human")
        self.board.stage(self.card, "planning", "drain", plan_ref=str(self.plan))
        self.board.set_session(self.card, SESSION, "drain", bg_id=SESSION[:8])
        self.resume = mock.patch.object(actions.house, "resume", return_value=dict(RESUMED)).start()
        self.busy = mock.patch.object(actions.house, "refuse_if_busy", return_value=None).start()
        mock.patch.object(actions, "run_kb", side_effect=self.kb).start()
        self.addCleanup(mock.patch.stopall)

    def kb(self, cfg, argv, **kwargs):
        """The deck's `kb`, as him, straight onto this board (the marks are the point)."""
        if argv[0] == "mark":
            data = json.loads(argv[2].split("=", 1)[1])
            return {"event": self.board.mark(argv[1], data, "human")}
        if argv[0] == "note":
            return {"event": self.board.note(argv[1], argv[2], "human")}
        if argv[0] == "relay":
            prompt = argv[argv.index("--prompt") + 1] if "--prompt" in argv else None
            return self.board.relay(argv[1], argv[2], "human", argv[argv.index("--to") + 1], prompt=prompt)
        raise AssertionError(f"unexpected kb {argv}")

    def ask(self, text="why a second store?", block="proposal.p1", quote=None):
        return actions.act(self.cfg, self.board, {"verb": "plan.ask", "id": self.card, "doc": "plan",
                                                  "block": block, "quote": quote, "text": text})

    def asks(self):
        return planstate.state_of(self.board.events(self.card), "plan")["asks"]


class AskTest(AskCase):

    def test_the_plan_file_and_the_gate_are_unchanged(self):
        before = self.plan.read_bytes()
        self.ask()
        self.assertEqual(self.plan.read_bytes(), before)
        card = self.board.get(self.card)
        self.assertEqual(card["stage"], "planning")
        self.assertEqual(actions.gate_of(card), "plan")
        self.assertEqual([e["kind"] for e in self.board.events(self.card)][-1], "mark")

    def test_the_other_answers_and_notes_wait_for_send(self):
        self.board.mark(self.card, {"what": "comment", "doc": "plan", "text": "a note"}, "human")
        self.ask()
        state = planstate.state_of(self.board.events(self.card), "plan")
        self.assertEqual([c["text"] for c in state["comments"]], ["a note"])
        self.assertNotIn("a note", self.resume.call_args.kwargs["prompt"])

    def test_an_ask_on_a_busy_house_is_held_until_its_turn_ends(self):
        """c-598: no longer refused. It is recorded, and held as a resume relay for this
        very machine, which its drain tells the house when the house's Stop kicks it."""
        self.busy.side_effect = house.Busy(f"{self.card}'s house is working right now")
        answer = self.ask()
        self.assertTrue(answer["held"])
        self.assertIn("when its turn ends", answer["note"])
        self.assertEqual([a["text"] for a in self.asks()], ["why a second store?"])
        self.resume.assert_not_called()
        (held,) = self.board.get(self.card)["derived"]["relays"]
        self.assertEqual((held["what"], held["to"]), ("resume", self.cfg.host))
        self.assertEqual(held["prompt"], prompts.plan_ask(self.card, self.asks()))

    def test_an_ask_on_a_house_in_his_terminal_is_refused_with_the_reason(self):
        self.busy.side_effect = house.InTerminal(f"{self.card}'s conversation is open in a terminal")
        with self.assertRaises(actions.ActionError) as caught:
            self.ask()
        self.assertIn("open in a terminal", str(caught.exception))
        self.assertEqual(self.asks(), [], "a refused ask leaves nothing on the card")
        self.resume.assert_not_called()

    def test_asks_in_a_row_queue_in_order(self):
        first = self.ask("first?")
        self.busy.side_effect = house.Busy("working on the first")
        second = self.ask("second?")
        self.assertEqual(self.resume.call_count, 1, "the second waits for the first")
        self.assertTrue(second["queued"])
        self.assertFalse(first.get("queued"))
        self.assertEqual([a["text"] for a in self.asks()], ["first?", "second?"])

    def test_an_ask_needs_its_gate_open(self):
        self.board.approve(self.card, "plan", "human")
        with self.assertRaises(actions.ActionError):
            self.ask()


class ReplyTest(AskCase):
    """`kb reply`: the house's answer, tied to his question, refused to anyone else."""

    def reply(self, ask, text, card=None):
        with mock.patch.dict(os.environ, {"KEEL_CARD": card or self.card}):
            return self.board.reply(self.card, ask, text, "house", caller_card=card or self.card)

    def test_the_reply_is_pinned_to_its_question(self):
        self.ask("first?")
        ask = self.asks()[0]["event"]
        self.reply(ask, "because the board is the only state")
        (only,) = self.asks()
        self.assertEqual(only["reply"]["text"], "because the board is the only state")
        self.assertEqual(self.board.get(self.card)["stage"], "planning")

    def test_the_reply_hands_the_house_the_next_question(self):
        self.ask("first?")
        self.busy.side_effect = house.Busy("busy")
        self.ask("second?")
        first, second = [a["event"] for a in self.asks()]
        out = self.reply(first, "one")
        self.assertEqual(out["next"]["event"], second)
        self.assertIsNone(self.reply(second, "two")["next"])

    def test_only_the_cards_own_house_may_reply_to_an_open_ask(self):
        self.ask()
        ask = self.asks()[0]["event"]
        with self.assertRaises(Refused):
            self.board.reply(self.card, ask, "x", "human", caller_card=None)
        with self.assertRaises(Refused):
            self.board.reply(self.card, ask, "x", "house", caller_card="c-999")
        with self.assertRaises(Refused):          # not an ask
            self.board.reply(self.card, ask - 1, "x", "house", caller_card=self.card)
        self.reply(ask, "answered")
        with self.assertRaises(Refused):          # already answered
            self.reply(ask, "again")


class KbReplyTest(CliCase):
    """`kb reply` from the house's own shell, as a house runs it."""

    def test_the_house_replies_and_reads_the_next_question(self):
        kb("repos")
        os.environ["KEEL_TOKEN"] = self.token
        card = json.loads(kb("create", "--space", "personal", "--title", "t", "--json")[1])["id"]
        for text in ("first?", "second?"):
            kb("mark", card, "--data", json.dumps({"what": "ask", "text": text}))
        events = json.loads(kb("show", card, "--json")[1])["events"]
        first, second = [a["event"] for a in planstate.open_asks(events)]
        os.environ.pop("KEEL_TOKEN")
        with mock.patch.dict(os.environ, {"KEEL_CARD": card}):
            code, out, err = kb("reply", card, "--ask", str(first), "--text", "one")
        self.assertEqual(code, 0, err)
        self.assertIn(f"kb reply {card} --ask {second}", out)
        self.assertIn("second?", out)
        with mock.patch.dict(os.environ, {"KEEL_CARD": "c-999"}):
            code, _, err = kb("reply", card, "--ask", str(second), "--text", "two")
        self.assertEqual(code, 1)
        self.assertIn("own house", err)


if __name__ == "__main__":
    unittest.main()
