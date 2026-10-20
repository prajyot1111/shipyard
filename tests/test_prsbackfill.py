"""prsbackfill: the one-time fill of `options.prs` from a card's own `options.pr` (c-584).

c-573, a two-repo card at review, recorded its primary repo's pull request only as
`options.pr` and its second repo's in `options.prs`, so every per-repo reader saw one.
"""

import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from keel import prsbackfill
from keel.board import Board


class BackfillTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.board = Board(Path(tmp.name) / "board.db")
        self.addCleanup(self.board.close)

    def card(self, stage="review", repo="front,back", options=None) -> str:
        card = self.board.create("work", "a card", repo=repo, actor="human")
        self.board.stage(card, "assigned", "human")
        self.board.stage(card, "building", "drain")
        if stage in ("review", "shipping"):
            self.board.stage(card, "review", "house", plan_ref="/p.md", output_ref="https://pr/1")
        if options:
            self.board.set_fields(card, {"options": options}, "house")
        return card

    def c573(self, **kw) -> str:
        return self.card(options={"pr": 2203, "branch": "feature/x",
                                  "prs": {"back": {"pr": 4150, "branch": "feature/x"}}}, **kw)

    def run_it(self, dry_run=False) -> str:
        out = io.StringIO()
        prsbackfill.run(self.board, dry_run=dry_run, out=out)
        return out.getvalue()


    def test_a_dry_run_writes_nothing(self):
        card = self.c573()
        self.assertIn("dry run: not written", self.run_it(dry_run=True))
        self.assertEqual(set(self.board.get(card)["options"]["prs"]), {"back"})

    def test_a_second_run_changes_nothing(self):
        self.c573()
        self.run_it()
        self.assertEqual(self.run_it().strip(), "0 cards filled")

    def test_only_review_and_shipping_and_only_what_is_missing(self):
        self.card(stage="building", options={"pr": 7})                         # not at a gate
        self.card(options={"pr": 8, "prs": {"front": {"pr": 8, "branch": "b"}}})  # already there
        self.card()                                                             # no pull request
        self.assertEqual(self.run_it().strip(), "0 cards filled")

    def test_a_one_repo_card_with_no_prs_gets_one(self):
        card = self.card(repo="front", options={"pr": 9, "branch": "b"})
        self.run_it()
        self.assertEqual(self.board.get(card)["options"]["prs"], {"front": {"pr": 9, "branch": "b"}})


if __name__ == "__main__":
    unittest.main()
