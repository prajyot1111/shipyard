"""r-55's first gap (c-723): at shipping, a house that prepared a fix needing the owner's yes
(c-240: a branch rebuilt on a new base, which replaces published commits) could only record
`valid` with a note, which read as done, and its question lived only in its end-of-turn
text. A `prepared` verdict puts the card in needs you with the house's question, and the
owner's answer is a send-back, told to the house as its next item like any other.

The stand-ins are `tests/test_shipping.py`'s.
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from keel import commentsroute, shipreplies
from keel.board import SHIPPING_OPTION, Refused
from tests.helpers import SESSION
from tests.test_shipping import MON_10, ShippingCase

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "ship-prepared.js"
ASKED = ("Rebuilt the six commits on the new triage base at c-240-rebuilt and ran the suite there; "
         "the card's branch is untouched. Move the card's branch to it?")


class PreparedCase(ShippingCase):
    def prepared(self):
        self.told()
        self.verdict("c11", "prepared", why=ASKED, summary="rebuild on the new base")


class WaitsOnTheOwnerTest(PreparedCase):
    def test_a_prepared_verdict_puts_the_card_in_needs_you_with_the_house_s_question(self):
        self.prepared()
        card = self.board.get(self.card)
        self.assertTrue(card["derived"]["needs_you"])
        self.assertEqual([(one["handle"], one["why"]) for one in card["derived"]["ship_prepared"]],
                         [("c11", ASKED)])
        self.assertEqual(card["derived"]["gate_since"], card["derived"]["ship_prepared"][0]["at"])
        self.assertIn(self.card, [one["id"] for one in self.board.needs_you()])
        events = self.board.events(self.card)
        self.assertEqual(shipreplies.summary(card, events)["judging"], 0, "judged: it waits on the owner")
        self.assertEqual(shipreplies.kept(card, events), [], "nothing is posted for it")

    def test_the_owner_s_send_back_is_the_answer_and_the_card_no_longer_waits_on_them(self):
        self.prepared()
        self.board.send_back(self.card, "human", "c11: yes, move the card's branch to it")
        card = self.board.get(self.card)
        self.assertEqual((card["derived"]["ship_prepared"], card["derived"]["needs_you"]), ([], False))
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})     # its turn ended
        self.assertEqual(self.upkeep(MON_10 + timedelta(minutes=30))["told"], [self.card])
        told = "\n".join(path.read_text() for path in (self.cfg.card_dir(self.card) / "told").iterdir())
        self.assertIn("c11: yes, move the card's branch to it", told, "told the house as its next item")

    def test_a_newer_verdict_on_the_item_ends_the_wait(self):
        self.prepared()
        self.verdict("c11", "valid", commits=[{"sha": "abc1234", "diff": "abc1234 Rebuild\n"}])
        card = self.board.get(self.card)
        self.assertEqual((card["derived"]["ship_prepared"], card["derived"]["needs_you"]), ([], False))

    def test_a_send_back_from_before_the_question_is_not_its_answer(self):
        self.told()
        self.board.send_back(self.card, "human", "and rename CAP")
        self.verdict("c11", "prepared", why=ASKED)
        self.assertEqual([one["handle"] for one in self.board.get(self.card)["derived"]["ship_prepared"]], ["c11"])

    def test_a_prepared_verdict_asks_its_question_and_carries_no_reply(self):
        self.told()
        for change, said in (({"why": ""}, "says why"), ({"reply": "Done."}, "no reply")):
            data = dict({"handle": "c11", "verdict": "prepared", "why": ASKED}, **change)
            with self.subTest(said=said), self.assertRaisesRegex(Refused, said):
                self.board.verdict(self.card, data, "house", self.card)
        self.verdict("c11", "prepared", why=ASKED, commits=[{"sha": "abc1234", "diff": "abc1234 Rebuild\n"}])
        self.assertEqual(self.board.get(self.card)["derived"]["ship_prepared"][0]["handle"], "c11",
                         "the prepared commits are shown for the owner to look at")

    def test_the_house_is_told_how_to_ask(self):
        self.told()
        self.assertIn("--verdict prepared", self.told_prompt())
        # r-55's side note (c-723): the guard refuses a quoted push at shipping, so it says so
        self.assertIn("never quote a push command in --why, the guard refuses it at shipping",
                      " ".join(self.told_prompt().split()))


class KindsAndAnswersTest(PreparedCase):
    """c-723 review r1.F5, F6, F9: several prepared items, the item kinds, who may record one,
    and a card the owner put away."""

    def told_items(self, *items) -> None:
        shipped = dict(self.board.get(self.card)["options"][SHIPPING_OPTION],
                       told=[dict(item, batch=1, told_at="2026-09-21T10:00:00+00:00") for item in items])
        self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: shipped}}, "drain")

    def waiting(self) -> list[str]:
        return [one["handle"] for one in self.board.get(self.card)["derived"]["ship_prepared"]]

    def test_a_send_back_answers_only_the_prepared_items_it_names(self):
        self.told_items({"handle": "c11", "kind": "comment", "text": "rebuild it"},
                        {"handle": "c12", "kind": "comment", "text": "and squash the fixups"})
        self.verdict("c11", "prepared", why=ASKED)
        self.verdict("c12", "prepared", why="Squashed the fixups on c-1-squashed. Move the branch?")
        self.board.send_back(self.card, "human", "c11: yes, move it")
        self.assertEqual(self.waiting(), ["c12"], "c12 was never answered")
        self.assertTrue(self.board.get(self.card)["derived"]["needs_you"])
        self.board.send_back(self.card, "human", "and drop the dead import")
        self.assertEqual(self.waiting(), ["c12"], "a send-back that names no item answers none")
        self.board.send_back(self.card, "human", "c12: no, keep the history")
        self.assertEqual((self.waiting(), self.board.get(self.card)["derived"]["needs_you"]), ([], False))

    def test_one_send_back_with_two_answers_answers_both_whatever_their_case(self):
        """c-723 review r2.F6: the deck's second Answer adds its own line to the draft."""
        self.told_items({"handle": "c11", "kind": "comment", "text": "rebuild it"},
                        {"handle": "c12", "kind": "comment", "text": "and squash the fixups"})
        self.verdict("c11", "prepared", why=ASKED)
        self.verdict("c12", "prepared", why="Squashed the fixups on c-1-squashed. Move the branch?")
        self.board.send_back(self.card, "human", "c11: yes, move it\nC12: no, keep the history")
        self.assertEqual((self.waiting(), self.board.get(self.card)["derived"]["needs_you"]), ([], False))

    def test_an_answer_from_before_the_question_answers_nothing(self):
        self.told_items({"handle": "c11", "kind": "comment", "text": "rebuild it"})
        self.board.send_back(self.card, "human", "c11: do what you think best")
        self.verdict("c11", "prepared", why=ASKED)
        self.assertEqual(self.waiting(), ["c11"])

    def test_the_owner_s_own_send_back_is_never_prepared_and_the_rebase_item_may_be(self):
        self.told_items({"handle": "his-1", "kind": "his", "text": "rename CAP"},
                        {"handle": "rebase", "kind": "rebase", "base": "main"})
        with self.assertRaisesRegex(Refused, "never prepared"):
            self.verdict("his-1", "prepared", why=ASKED)
        self.verdict("rebase", "prepared", why="Rebuilt on main at c-1-rebuilt, which replaces pushed commits. Move it?")
        self.assertEqual(self.waiting(), ["rebase"], "c-240's was a rebuild on a new base: the owner's call")

    def test_only_the_card_s_own_house_records_a_prepared_verdict(self):
        self.told()
        data = {"handle": "c11", "verdict": "prepared", "why": ASKED}
        for actor, caller in (("house", "c-999"), ("human", None), ("bosun", self.card)):
            with self.subTest(actor=actor), self.assertRaisesRegex(Refused, "own house"):
                self.board.verdict(self.card, data, actor, caller)
        self.assertEqual(self.waiting(), [])

    def test_an_archived_card_leaves_needs_you_with_its_question_kept(self):
        """A shipping card never backlogs (only an outcome gate does, `views.backlog`), so
        archived is the one way the owner puts it away."""
        self.prepared()
        self.board.set_fields(self.card, {"options": {"archived": True}}, "human")
        card = self.board.get(self.card)
        self.assertEqual((card["derived"]["needs_you"], self.waiting()), (False, ["c11"]))
        self.assertNotIn(self.card, [one["id"] for one in self.board.needs_you()])


@unittest.skipUnless(shutil.which("node"), "node is not on this machine")
class DeckTest(PreparedCase):
    def test_the_deck_says_it_waits_on_the_owner_and_answer_opens_send_back(self):
        """The comments page and the card's pane, drawn by the real modules under node
        (`tests/fixtures/ship-prepared.js`, as `tests/fixtures/comments-page.js` draws them)."""
        self.prepared()
        payload = commentsroute.payload(self.cfg, self.board, self.board.get(self.card), ["plan", "outcome", "comments"])[1]
        self.assertEqual(payload["card"]["derived"]["ship_prepared"][0]["handle"], "c11")
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "payload.json"
            data.write_text(json.dumps(payload))
            done = subprocess.run(["node", str(FIXTURE), str(ROOT / "app"), str(data)], capture_output=True,
                                  text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), {"ok": True})
