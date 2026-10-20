"""Lane RC, RC-4 (the engine's half): his Approve of a review card hands the adapter's
`publish` what to post: the findings he kept at their lines (his words for an edit), one
summary, the verdict, and the ledger a re-review reads. Never auto-posted: only Approve runs
`publish`. The adapter is a stand-in that records its argv and stdin; every pull request is
invented.
"""

import json
import tempfile
import unittest
from pathlib import Path

from keel import adapters, reviewround
from keel.board import Board
from keel.review import stamp
from tests.helpers import make_config

SAMPLE = (Path(__file__).parent / "fixtures" / "review-sample.md").read_text()
# lane RC's shape, which an outcome already at his gate may still be written in (lane FC)
OLD = (Path(__file__).parent / "fixtures" / "review-sample-batch.md").read_text()


def script(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


class ReviewApproveCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        work = self.cfg.adapters_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        self.log, self.answers = self.dir / "calls.log", self.dir / "answers.log"
        script(work / "publish", f'echo "publish $*" >> {self.log}\n'
                                 f'if [ "$2" = "--answer" ]; then cat >> {self.answers}; echo >> {self.answers}; fi\n'
                                 f'echo \'{{"published": "review", "pr": 4150}}\'\n')
        self.card = self.at_gate()

    def at_gate(self) -> str:
        card_id = self.board.create("work", "Review: Tidy the loader", repo="api", actor="drain",
                                    options={"kind": "review", "review_key": "api:4150", "slot": "review",
                                             "pr": 4150, "review_head": "abc123def4567890"})
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="https://example.invalid/pr/4150")
        card_dir = self.cfg.card_dir(card_id)
        card_dir.mkdir(parents=True, exist_ok=True)
        (card_dir / "context.md").write_text(SAMPLE)
        stamp.save_rounds(card_dir, [{"round": 1, "head": "abc123def4567890", "complete": True, "findings": [
            {"id": f"r1.F{n}", "axis": "standards", "severity": level, "verify": "kept", "claim": "x",
             "path": "app/loader.py", "line": 40} for n, level in ((1, "high"), (2, "medium"), (3, "low"))]}])
        return card_id

    def mark(self, **data):
        self.board.mark(self.card, dict({"what": "answer", "doc": "outcome"}, **data), "human")

    def approve(self):
        return self.board.approve(self.card, "outcome", "human", publish=adapters.publisher(self.cfg, "work"))

    def answer(self):
        return json.loads(self.answers.read_text().splitlines()[-1])["review"]


class AnswerTest(ReviewApproveCase):
    def test_approve_posts_only_the_kept_findings_at_their_lines_the_summary_and_the_verdict(self):
        card = self.approve()
        self.assertEqual(card["stage"], "done")
        review = self.answer()
        self.assertEqual([(c["row"], c["path"], c["line"]) for c in review["comments"]],
                         [("r1-f1", "app/loader.py", 40), ("r1-f2", "tests/test_loader.py", 5)])
        self.assertTrue(review["comments"][0]["text"].startswith("The cap is read at import time"))
        self.assertEqual(review["verdict"], "changes")
        self.assertIn("so a larger account no longer stops at the first forty rows", review["summary"])
        self.assertIn("2 inline comments (1 high, 1 medium), reviewed at abc123def4", review["summary"])
        self.assertEqual(review["head"], "abc123def4567890")
        self.assertEqual(review["severity"], "high")
        self.assertEqual([(entry["id"], entry["choice"]) for entry in review["ledger"]],
                         [("r1-f1", "post"), ("r1-f2", "post"), ("r1-f3", "drop")])
        self.assertEqual(review["ledger"][2]["line"], 12)

    def test_his_picks_win_an_edit_posts_his_words_and_a_drop_posts_nothing(self):
        # lane FC: a finding's pick is a row mark on its own block, the comment field's words his edit
        self.mark(block="r1-f1", row="r1-f1", choice="edit", other="Could the cap be read per call?")
        self.mark(block="r1-f2", row="r1-f2", choice="drop")
        self.mark(block="r1-f3", row="r1-f3", choice="post")
        self.mark(block="verdict", option="comment")
        self.approve()
        review = self.answer()
        self.assertEqual([(c["row"], c["text"]) for c in review["comments"]],
                         [("r1-f1", "Could the cap be read per call?"),
                          ("r1-f3", "Small one: `list` shadows the builtin here.")])
        self.assertEqual(review["verdict"], "comment")
        self.assertEqual(review["severity"], "high")      # r1-f1, kept in his words

    def test_the_house_severity_rides_on_each_comment(self):
        self.approve()
        self.assertEqual([c["severity"] for c in self.answer()["comments"]], ["high", "medium"])

    def test_an_edit_left_empty_refuses_and_nothing_is_handed_on(self):
        self.mark(block="r1-f1", row="r1-f1", choice="edit")
        with self.assertRaisesRegex(adapters.AdapterError, "r1-f1 is marked edit with no words"):
            self.approve()
        self.assertEqual(self.board.get(self.card)["stage"], "review")
        self.assertFalse(self.answers.exists())

    def test_a_verdict_in_his_own_words_is_refused(self):
        self.mark(block="verdict", other="merge it after lunch")
        with self.assertRaisesRegex(adapters.AdapterError, "comment only, request changes or approve"):
            self.approve()
        self.assertFalse(self.answers.exists())

    def test_nothing_posts_before_his_approve(self):
        self.assertFalse(self.log.exists())
        self.assertIsNone(reviewround.answer_for(self.cfg, dict(self.board.get(self.card), stage="building")))


class OldShapeTest(ReviewApproveCase):
    """An outcome written in lane RC's batch-and-comments shape before lane FC still posts."""

    def setUp(self):
        super().setUp()
        (self.cfg.card_dir(self.card) / "context.md").write_text(OLD)

    def test_the_old_shape_posts_what_it_always_did(self):
        self.mark(block="findings", row="r1-f1", choice="edit", other="Could the cap be read per call?")
        self.mark(block="findings", row="r1-f2", choice="drop")
        self.approve()
        review = self.answer()
        self.assertEqual([(c["row"], c["path"], c["line"], c["text"][:28]) for c in review["comments"]],
                         [("r1-f1", "app/loader.py", 40, "Could the cap be read per ca")])
        self.assertEqual([(e["id"], e["choice"]) for e in review["ledger"]],
                         [("r1-f1", "post"), ("r1-f2", "drop"), ("r1-f3", "drop")])


if __name__ == "__main__":
    unittest.main()
