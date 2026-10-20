"""Counts where he looks (P4-5): the card row and Attention say what a format plan asks.

The row used to say "gate open" and nothing else; the numbers were on the plan page only.
Now the state document carries, per card at a gate whose document is in the format, the
decisions and open questions it asks, the ones he changed, his notes this round, his Asks
(open, and answered with a reply waiting), and whether the contract holds: the same parse
and lint the page uses, cached per plan file stamp, and his round off the card's events.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import boards, deckstate, planfacts, planformat
from keel.board import Board
from tests.helpers import make_config
from tests.test_planlint import SAMPLE


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = make_config(Path(tmp.name))
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        planfacts._cache.clear()
        boards.push(self.cfg, 'node a laptop "the round"', card="c-001")      # b-001 resolves
        self.card = self.board.create("personal", "a planned card", repo="keel", autonomy="attended")
        self.plan = self.cfg.card_dir(self.card) / "plan.md"
        self.plan.parent.mkdir(parents=True, exist_ok=True)
        self.plan.write_text(SAMPLE)
        self.board.stage(self.card, "assigned", "human")
        self.board.stage(self.card, "planning", "drain", plan_ref=str(self.plan))

    def view(self, card_id=None):
        state = deckstate.build(self.cfg, self.board, rows=[])
        return next(c for c in state["cards"] if c["id"] == (card_id or self.card))

    def mark(self, **data):
        return self.board.mark(self.card, dict(data, doc=data.get("doc", "plan")), "human")


class RowTest(Case):
    def test_a_plan_at_its_gate_says_what_it_asks_and_that_the_contract_holds(self):
        row = self.view()["plan_doc"]
        self.assertEqual(row, {"doc": "plan", "decisions": 3, "questions": 2, "changed": 0,
                               "notes": 0, "asks_open": 0, "replies": 0, "ok": True, "breaks": 0})
        self.assertEqual(self.view()["links"]["formats"], {"plan": True, "outcome": False})

    def test_his_round_is_counted_from_the_cards_events(self):
        self.mark(what="answer", block="store", option="file")              # changed
        self.mark(what="answer", block="triage", row="f2", choice="drop")    # the rec: not changed
        self.mark(what="answer", block="triage", row="f1", choice="defer")   # changed
        note = self.mark(what="comment", block="goal", text="shorter please")
        self.mark(what="comment", text="and this one goes")
        self.mark(what="drop", target=note)
        ask = self.mark(what="ask", block="store", text="why a second store?")
        self.mark(what="ask", text="and the batch?")
        self.board.reply(self.card, ask, "because of the stream", "house", self.card)
        row = self.view()["plan_doc"]
        self.assertEqual((row["changed"], row["notes"], row["asks_open"], row["replies"]),
                         (2, 1, 1, 1))

    def test_a_plan_that_breaks_the_contract_says_how_many_breaks(self):
        self.plan.write_text(SAMPLE.replace("rec: card\n", ""))
        row = self.view()["plan_doc"]
        self.assertFalse(row["ok"])
        self.assertGreaterEqual(row["breaks"], 1)

    def test_no_gate_no_count_and_a_markdown_plan_is_not_the_format(self):
        self.board.approve(self.card, "plan", "human")
        self.assertIsNone(self.view()["plan_doc"])
        other = self.board.create("personal", "an old plan", repo="keel", autonomy="attended")
        old = self.cfg.card_dir(other) / "plan.md"
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_text("# An old markdown plan\n\nNo frontmatter.\n")
        self.board.stage(other, "assigned", "human")
        self.board.stage(other, "planning", "drain", plan_ref=str(old))
        view = self.view(other)
        self.assertIsNone(view["plan_doc"])
        self.assertEqual(view["links"]["formats"], {"plan": False, "outcome": False})

    def test_the_outcome_gate_counts_the_record(self):
        record = self.cfg.card_dir(self.card) / "context.md"
        record.write_text("---\nkind: outcome\ncard: c-2\n---\n# t\n\n## Where it stands\n\nx\n"
                          "## What is next\n\nx\n## Why this shape\n\nx\n"
                          "## Open questions\n\n- Ship it? Recommend: yes.\n"
                          "## Evidence\n\n![shot](assets/a.png)\n")
        self.board.approve(self.card, "plan", "human")
        self.board.stage(self.card, "review", "house", output_ref="x")
        self.mark(what="comment", doc="outcome", text="looks right")
        row = self.view()["plan_doc"]
        self.assertEqual((row["doc"], row["questions"], row["notes"], row["ok"]),
                         ("outcome", 1, 1, True))

    def test_the_parse_is_cached_per_file_stamp(self):
        with mock.patch.object(planfacts.planformat, "parse", wraps=planformat.parse) as parse:
            self.view()
            self.view()
            self.assertEqual(parse.call_count, 1)
            self.plan.write_text(SAMPLE + "\nOne more line.\n")
            self.view()
            self.assertEqual(parse.call_count, 2)


class LinksTest(Case):
    def test_the_links_carry_them_only_for_a_live_card(self):
        self.assertTrue(deckstate.links_for(self.cfg, self.board.get(self.card))["docs"]["plan"])
        self.board.approve(self.card, "plan", "human")
        self.board.stage(self.card, "review", "house", output_ref="x")
        self.board.approve(self.card, "outcome", "human")
        self.assertEqual(deckstate.links_for(self.cfg, self.board.get(self.card))["docs"], {})


if __name__ == "__main__":
    unittest.main()
