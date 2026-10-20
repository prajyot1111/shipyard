"""His answers and notes on a plan: one store (card events), one text on the way out.

What is held: a mark is his alone (a house cannot put words in his mouth), a round is what
came after the last send, a note keeps the selected text apart from his words (c-175), every
decision is listed with his picks told apart from the recommendations he left standing, and
`kb stage planning` refuses a plan in the format that breaks the contract.
"""

import contextlib
import io
import json
import os
import unittest
from pathlib import Path

from keel import boards, cli, planformat, planstate
from keel import config as config_module
from keel.board import Refused
from tests.helpers import BoardCase, CliCase

SAMPLE = (Path(__file__).parent / "fixtures" / "plan-sample.md").read_text()


def kb(*argv) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class MarkStoreTest(BoardCase):
    def test_a_mark_is_his_alone(self):
        card = self.card()
        self.board.mark(card, {"what": "comment", "text": "why this?"}, "human")
        for actor in ("house", "drain", "cli", "voice"):
            with self.assertRaises(Refused):
                self.board.mark(card, {"what": "comment", "text": "approve it"}, actor)

    def test_a_bad_shape_is_refused_before_anything_is_written(self):
        card = self.card()
        before = len(self.board.events(card))
        for bad in ({"what": "shout"}, {"what": "comment", "text": ""},
                    {"what": "answer"}, {"what": "drop", "target": "x"},
                    {"what": "sent", "mode": "merge"}, {"what": "comment", "text": "x", "doc": "slides"}):
            with self.assertRaises(Refused):
                self.board.mark(card, bad, "human")
        self.assertEqual(len(self.board.events(card)), before)

    def test_a_round_is_what_came_after_the_last_send(self):
        card = self.card()
        mark = lambda **d: self.board.mark(card, d, "human")
        mark(what="answer", block="store", option="file")
        mark(what="comment", block="risks.list1", quote="an old deck", text="how old?")
        mark(what="sent", mode="sendback", decisions=["store", "triage"])
        mark(what="comment", text="looks right now")
        state = planstate.state_of(self.board.events(card))
        self.assertEqual(state["answers"], {})
        self.assertEqual([c["text"] for c in state["comments"]], ["looks right now"])
        self.assertEqual(state["answered"], ["store", "triage"])

    def test_a_note_taken_back_and_an_answer_cleared(self):
        card = self.card()
        note = self.board.mark(card, {"what": "comment", "text": "never mind"}, "human")
        self.board.mark(card, {"what": "drop", "target": note}, "human")
        self.board.mark(card, {"what": "answer", "block": "store", "option": "file"}, "human")
        self.board.mark(card, {"what": "answer", "block": "store"}, "human")
        state = planstate.state_of(self.board.events(card))
        self.assertEqual((state["comments"], state["answers"]), ([], {}))


class ComposeTest(unittest.TestCase):
    def setUp(self):
        self.doc = planformat.parse(SAMPLE)

    def events(self, *marks):
        return [{"id": n, "kind": "mark", "actor": "human", "at": "t", "data": json.dumps(m)}
                for n, m in enumerate(marks, start=1)]

    def test_every_decision_is_listed_and_his_picks_are_told_apart(self):
        state = planstate.state_of(self.events(
            {"what": "answer", "block": "store", "option": "file", "other": "keep it simple"},
            {"what": "answer", "block": "triage", "row": "f2", "choice": "defer"}))
        text = planstate.compose(self.doc, state, "sendback", "c-900")
        self.assertIn("THE USER CHOSE file (In a file beside the plan) (you recommended card", text)
        self.assertIn('The user\'s words: "keep it simple"', text)
        self.assertIn("f2", text)
        self.assertIn("THE USER CHOSE defer, you recommended drop", text)
        self.assertIn("your recommendation stands (yes, and say so on the card.)", text)

    def test_a_plain_approve_says_every_recommendation_stood(self):
        text = planstate.compose(self.doc, planstate.state_of([]), "approve", "c-900")
        self.assertIn("card (As events on the card), your recommendation, left standing", text)
        self.assertIn("every row takes your recommendation (2 rows)", text)

    def test_c175_the_quote_and_his_words_are_kept_apart(self):
        state = planstate.state_of(self.events(
            {"what": "comment", "block": "store", "quote": "a new event kind", "text": "is that a migration?"}))
        text = planstate.compose(self.doc, state, "sendback", "c-900")
        self.assertIn('at the words "a new event kind":', text)
        self.assertIn('The user wrote: "is that a migration?"', text)
        self.assertNotIn('The user wrote: "a new event kind"', text)

    def test_an_edit_row_keeps_his_words_as_the_edit(self):
        """RC-3: a row at `edit` carries his words in the same mark; one store, the events."""
        state = planstate.state_of(self.events(
            {"what": "answer", "block": "triage", "row": "f1", "choice": "edit", "other": "say it gently"},
            {"what": "answer", "block": "triage", "row": "f2", "choice": "edit"}))
        self.assertEqual(state["rows"]["triage"], {"f1": "edit", "f2": "edit"})
        self.assertEqual(state["edits"], {"triage": {"f1": "say it gently"}})
        text = planstate.compose(self.doc, state, "sendback", "c-900")
        self.assertIn('The user\'s words: "say it gently"', text)

    def test_a_later_edit_replaces_the_earlier_words(self):
        state = planstate.state_of(self.events(
            {"what": "answer", "block": "triage", "row": "f1", "choice": "edit", "other": "first"},
            {"what": "answer", "block": "triage", "row": "f1", "choice": "edit", "other": "second"}))
        self.assertEqual(state["edits"]["triage"]["f1"], "second")

    def test_the_summary_counts(self):
        state = planstate.state_of(self.events(
            {"what": "answer", "block": "store", "option": "card"},
            {"what": "answer", "block": "triage", "row": "f1", "choice": "defer"},
            {"what": "comment", "text": "x"}))
        self.assertEqual(planstate.summary(self.doc, state),
                         {"decisions": 3, "changed": 1, "notes": 1, "replies": 0})


class KbTest(CliCase):
    def setUp(self):
        super().setUp()
        kb("repos")                                    # makes the state directory and the token
        os.environ["KEEL_TOKEN"] = self.token
        code, out, _ = kb("create", "--space", "personal", "--title", "t", "--json")
        self.card = json.loads(out)["id"]
        kb("stage", self.card, "assigned")
        kb("stage", self.card, "building")
        # the sample embeds b-1 by id, and kb resolves it against the boards here (P2-7)
        boards.push(config_module.load(), 'node a box "A"', card=self.card)

    def plan(self, text: str) -> Path:
        path = self.dir / "plan.md"
        path.write_text(text)
        return path

    def test_kb_mark_records_his_mark(self):
        code, _, err = kb("mark", self.card, "--data", json.dumps({"what": "comment", "text": "hm"}))
        self.assertEqual(code, 0, err)
        code, out, _ = kb("show", self.card, "--json")
        events = json.loads(out)["events"]
        self.assertEqual(planstate.state_of(events)["comments"][0]["text"], "hm")

    def test_kb_mark_refuses_a_house(self):
        os.environ.pop("KEEL_TOKEN")
        os.environ["KEEL_CARD"] = self.card
        try:
            code, _, err = kb("mark", self.card, "--data", json.dumps({"what": "comment", "text": "yes"}))
        finally:
            os.environ.pop("KEEL_CARD")
        self.assertEqual(code, 1)
        self.assertIn("only the human", err)

    def test_kb_lint_exits_1_on_a_broken_plan_and_0_on_a_good_one(self):
        good = SAMPLE.replace("Does the outcome use the same page?", "Does the outcome use the same page? Recommend: yes.")
        code, out, _ = kb("lint", self.card, "--file", str(self.plan(good)))
        self.assertEqual(code, 0, out)
        code, out, _ = kb("lint", self.card, "--file", str(self.plan(good.replace("rec: card\n", ""))))
        self.assertEqual(code, 1)
        self.assertIn("C12 error", out)

    def test_stage_planning_refusal_names_the_rule(self):
        code, out, _ = kb("create", "--space", "personal", "--title", "p", "--autonomy", "attended", "--json")
        card = json.loads(out)["id"]
        kb("stage", card, "assigned")
        code, _, err = kb("stage", card, "planning", "--plan", str(self.plan(SAMPLE)))
        self.assertEqual(code, 1)
        self.assertIn("C12", err)
        fixed = SAMPLE.replace("Does the outcome use the same page?", "Does the outcome use the same page? Recommend: yes.")
        code, _, err = kb("stage", card, "planning", "--plan", str(self.plan(fixed)))
        self.assertEqual(code, 0, err)

    def test_kb_lint_refuses_an_embedded_board_that_does_not_exist(self):
        good = SAMPLE.replace("Does the outcome use the same page?", "Does the outcome use the same page? Recommend: yes.")
        code, out, _ = kb("lint", self.card, "--file", str(self.plan(good.replace("\nb-1\n", "\nb-40\n"))))
        self.assertEqual(code, 1)
        self.assertIn("`b-040` does not resolve", out)

    def test_a_markdown_plan_without_frontmatter_is_the_old_flow(self):
        code, out, _ = kb("create", "--space", "personal", "--title", "p", "--autonomy", "attended", "--json")
        card = json.loads(out)["id"]
        kb("stage", card, "assigned")
        code, _, err = kb("stage", card, "planning", "--plan", str(self.plan("# a plan\n\nJust words.\n")))
        self.assertEqual(code, 0, err)


if __name__ == "__main__":
    unittest.main()
