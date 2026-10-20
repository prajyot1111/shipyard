"""c-551, the deck's half: a card at his gate that his Approve could not publish.

The adapter's `act links` may carry `unpublished` (the work adapter's own word is tested in
`packs/work/tests/test_readiness.py`). Here the adapter is a stub: the deck lifts the
line out of the links into the card's `unpublished`, reads it from the push for a card
whose house is on another machine, and hands it to the outcome page, never the plan page.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import deckstate, planroute
from keel.board import Board
from tests.helpers import make_config

LINE = "Not publishable: no pull request is open for it. Send back."


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.cfg = make_config(self.dir)
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        self.card = self.board.create("work", "stuck like c-512", repo="api", autonomy="autonomous")
        self.board.stage(self.card, "assigned", "human")
        self.board.stage(self.card, "building", "drain", plan_ref="plan.md")
        self.board.stage(self.card, "review", "house", output_ref="branch")
        self.act({self.card: {"unpublished": LINE}})

    def act(self, links: dict) -> None:
        """`adapters/work/act` answering `links` with these, and recording that it ran."""
        path = self.cfg.spaces["work"].adapter_dir / "act"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!/bin/sh\ntouch {self.dir}/asked\n"
                        f"[ \"$1\" = links ] && echo '{json.dumps(links)}' || echo '{{}}'\n")
        path.chmod(0o755)

    def view(self) -> dict:
        state = deckstate.build(self.cfg, self.board, rows=[])
        return next(c for c in state["cards"] if c["id"] == self.card)


class CardViewTest(Case):
    def test_the_line_is_lifted_out_of_the_links_onto_the_card(self):
        view = self.view()
        self.assertEqual(view["unpublished"], LINE)
        self.assertNotIn("unpublished", view["links"])

    def test_a_card_the_adapter_says_nothing_about_has_none(self):
        self.act({})
        self.assertIsNone(self.view()["unpublished"])


class OneCardTest(Case):
    def test_read_here_when_the_house_is_here(self):
        self.assertEqual(deckstate.unpublished_of(self.cfg, self.board.get(self.card), None), LINE)

    def test_a_card_not_at_the_gate_is_never_asked(self):
        card = dict(self.board.get(self.card), stage="building")
        self.assertIsNone(deckstate.unpublished_of(self.cfg, card, None))
        self.assertFalse((self.dir / "asked").exists())

    def test_a_space_without_an_adapter_is_never_asked(self):
        card = dict(self.board.get(self.card), space="personal")
        self.assertIsNone(deckstate.unpublished_of(self.cfg, card, None))
        self.assertFalse((self.dir / "asked").exists())


class OutcomePageTest(Case):
    def test_the_outcome_page_carries_it_and_the_plan_page_does_not(self):
        self.assertEqual(planroute.payload(self.cfg, self.board, self.card, "outcome")["card"]["unpublished"], LINE)
        self.assertIsNone(planroute.payload(self.cfg, self.board, self.card, "plan")["card"]["unpublished"])


PRS = [{"repo": "api", "pr": 4140, "url": "https://host/api/pr/4140"},
       {"repo": "web", "pr": 812, "url": "https://host/web/pr/812"}]


class OutcomePullsTest(Case):
    """c-565: the outcome page links each of the card's pull requests, from the same links."""

    def test_the_outcome_page_lists_each_pull_request_and_the_plan_page_none(self):
        self.act({self.card: {"pr": PRS[0]["url"], "prs": PRS}})
        self.assertEqual(planroute.payload(self.cfg, self.board, self.card, "outcome")["card"]["pulls"], PRS)
        self.assertEqual(planroute.payload(self.cfg, self.board, self.card, "plan")["card"]["pulls"], [])

    def test_a_shipping_card_lists_them_too_and_carries_no_unpublished_line(self):
        self.act({self.card: {"prs": PRS, "unpublished": LINE}})
        with mock.patch.object(self.board, "get", return_value=dict(self.board.get(self.card), stage="shipping")):
            card = planroute.payload(self.cfg, self.board, self.card, "outcome")["card"]
        self.assertEqual(card["pulls"], PRS)
        self.assertIsNone(card["unpublished"])

    def test_a_card_before_its_gate_never_asks_the_adapter(self):
        with mock.patch.object(self.board, "get", return_value=dict(self.board.get(self.card), stage="building")):
            card = planroute.payload(self.cfg, self.board, self.card, "outcome")["card"]
        self.assertEqual(card["pulls"], [])
        self.assertFalse((self.dir / "asked").exists())

if __name__ == "__main__":
    unittest.main()
