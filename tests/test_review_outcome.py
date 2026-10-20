"""Lane RC: a review card's outcome, in the plan format's `review` kind (RC-2, RC-5).

The lint holds the shape his Approve depends on: an orientation at the top (what the change
does, its code path as a board by id, a reading order), every finding a row he can post,
edit or drop with a path:line and a drafted comment, exactly one verdict, and on a
re-review no finding raised again on lines that did not change. Every pull request here is
invented.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from keel import plangate, planlint
from keel.review import ledger, stamp
from tests.helpers import make_repo

GIT = ("git", "-c", "user.name=t", "-c", "user.email=t@x")


def sh(cwd, *args):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()

SAMPLE = (Path(__file__).parent / "fixtures" / "review-sample.md").read_text()


def resolve_all(path, start, end):
    return None


def lint(text, **kwargs):
    kwargs.setdefault("resolve", resolve_all)
    return planlint.lint_text(text, "context.md", repo_card=True, **kwargs)


def rules(result, level="error"):
    return sorted({f["rule"] for f in result["findings"] if f["level"] == level})


class ReviewLintTest(unittest.TestCase):
    def test_the_sample_review_passes(self):
        result = lint(SAMPLE)
        self.assertEqual(result["kind"], "review")
        self.assertTrue(result["ok"], planlint.lines_of(result))

    def test_c28_the_orientation_is_missing(self):
        text = SAMPLE.split("## Orientation")[0] + "## Findings" + SAMPLE.split("## Findings")[1]
        self.assertIn("C28", rules(lint(text)))

    def test_c28_the_orientation_is_not_first(self):
        head, rest = SAMPLE.split("## Orientation")
        orientation, tail = rest.split("## Findings")
        text = head + "## Findings" + tail.replace("## Verdict", "## Orientation" + orientation + "## Verdict")
        self.assertIn("C28", rules(lint(text)))

    def test_c28_the_orientation_embeds_its_code_path_by_id(self):
        text = SAMPLE.replace("```board The loader's code path\nb-1\n```\n", "")
        self.assertIn("C28", rules(lint(text)))

    def test_c28_the_orientation_gives_a_reading_order(self):
        text = SAMPLE.replace("1. `app/loader.py:12` where a page is asked for\n"
                              "2. `app/loader.py:40` the new constant and where it is read\n"
                              "3. `tests/test_loader.py:5` the one new test\n", "- the loader\n")
        self.assertIn("C28", rules(lint(text)))

    def test_c29_a_finding_with_no_path_line(self):
        text = SAMPLE.replace("at: app/loader.py:12\n", "")
        found = lint(text)
        self.assertIn("C29", rules(found))
        self.assertTrue(any("r1-f3" in f["text"] for f in found["findings"] if f["rule"] == "C29"))

    def test_c29_a_finding_with_no_drafted_comment(self):
        text = SAMPLE.replace("comment: Small one: `list` shadows the builtin here.\n", "")
        self.assertIn("C29", rules(lint(text)))

    def test_c29_the_findings_are_post_edit_or_drop(self):
        text = SAMPLE.replace("choice: drop", "choice: defer")
        self.assertIn("C29", rules(lint(text)))

    def test_c29_a_surviving_finding_that_is_not_a_row(self):
        found = lint(SAMPLE, review={"surviving": ["r1-F1", "r1-F2", "r1-F3", "r1-F4"], "ledger": []})
        self.assertIn("C29", rules(found))
        self.assertTrue(any("r1-f4" in f["text"] for f in found["findings"]))

    def test_c29_no_findings_says_none_with_a_reason(self):
        head, rest = SAMPLE.split("## Findings")
        tail = rest.split("## Verdict")[1]
        ok = lint(head + "## Findings\n\nNone: the reviewer found nothing and the verifier agreed.\n\n## Verdict" + tail)
        self.assertNotIn("C29", rules(ok))
        bare = lint(head + "## Findings\n\n## Verdict" + tail)
        self.assertIn("C29", rules(bare))

    def test_c30_exactly_one_verdict(self):
        self.assertIn("C30", rules(lint(SAMPLE.replace("```decision verdict", "```decision overall"))))
        second = SAMPLE + SAMPLE[SAMPLE.index("```decision verdict"):].replace("```decision verdict", "```decision verdict2")
        self.assertIn("C30", rules(lint(second)))

    def test_c30_the_verdict_is_comment_changes_or_approve_and_nothing_else(self):
        self.assertIn("C30", rules(lint(SAMPLE.replace("option comment: Comment only", "option merge: Merge it"))))
        self.assertIn("C30", rules(lint(SAMPLE.replace("other: no\n", ""))))

    def test_c31_a_finding_raised_again_on_lines_that_did_not_change(self):
        ledger = [{"id": "r1-F3", "path": "app/loader.py", "line": 12, "choice": "drop"}]
        found = lint(SAMPLE, review={"surviving": [], "ledger": ledger})
        self.assertIn("C31", rules(found))

    def test_c31_passes_when_the_line_is_elsewhere(self):
        ledger = [{"id": "r1-F3", "path": "app/loader.py", "line": 99, "choice": "drop"}]
        self.assertNotIn("C31", rules(lint(SAMPLE, review={"surviving": [], "ledger": ledger})))


class LedgerLinesTest(unittest.TestCase):
    """A ledger line is carried to where it sits now, or dropped when the change touched it."""

    DIFF = ("diff --git a/app/loader.py b/app/loader.py\n--- a/app/loader.py\n+++ b/app/loader.py\n"
            "@@ -3,0 +4,2 @@\n+one\n+two\n@@ -20,2 +22,1 @@\n-x\n-y\n+z\n")

    def test_a_line_below_an_insert_moves_down(self):
        self.assertEqual(ledger.moved(12, ledger.hunks(self.DIFF)["app/loader.py"]), 14)

    def test_a_line_above_every_hunk_stays(self):
        self.assertEqual(ledger.moved(2, ledger.hunks(self.DIFF)["app/loader.py"]), 2)

    def test_a_line_the_change_touched_is_gone(self):
        self.assertIsNone(ledger.moved(21, ledger.hunks(self.DIFF)["app/loader.py"]))

    def test_a_line_below_a_shrink_moves_up(self):
        self.assertEqual(ledger.moved(40, ledger.hunks(self.DIFF)["app/loader.py"]), 41)

    def test_carried_keeps_only_the_unchanged(self):
        kept = ledger.carried([{"id": "r1.F1", "path": "app/loader.py", "line": 21, "choice": "post"},
                               {"id": "r1.F3", "path": "app/loader.py", "line": 12, "choice": "drop"},
                               {"id": "r1.F4", "path": "other.py", "line": 5, "choice": "drop"}], self.DIFF)
        self.assertEqual([(k["id"], k["line"]) for k in kept], [("r1.F3", 14), ("r1.F4", 5)])


class ReReviewStageTest(unittest.TestCase):
    """RC-5 at `kb stage review`: the lint is handed the core's rounds and the ledger moved
    through the real diff since the head he reviewed, so a finding he dropped is refused
    again on lines that did not change and allowed on lines that did."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.repo = make_repo(self.dir / "repo")
        app = self.repo / "app"
        app.mkdir()
        (app / "loader.py").write_text("".join(f"line {n}\n" for n in range(1, 61)))
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_loader.py").write_text("".join(f"t {n}\n" for n in range(1, 11)))
        sh(self.repo, *GIT, "add", "-A")
        sh(self.repo, *GIT, "commit", "-qm", "the pull request at the head he reviewed")
        self.reviewed = sh(self.repo, "git", "rev-parse", "HEAD")
        self.card_dir = self.dir / "card"
        self.card_dir.mkdir()

    def push(self, touch_line_12: bool):
        lines = (self.repo / "app" / "loader.py").read_text().splitlines(keepends=True)
        if touch_line_12:
            lines[11] = "line 12, rewritten\n"
        else:
            lines[49] = "line 50, rewritten\n"
        (self.repo / "app" / "loader.py").write_text("".join(lines))
        sh(self.repo, *GIT, "commit", "-qam", "new commits since his review")

    def record(self, head: str, complete: bool = True):
        stamp.save_rounds(self.card_dir, [{"round": 1, "head": head, "complete": complete, "findings": [
            {"id": "r1.F1", "axis": "standards", "severity": "high", "verify": "kept", "claim": "x", "path": "app/loader.py", "line": 40},
            {"id": "r1.F2", "axis": "standards", "severity": "medium", "verify": "kept", "claim": "x", "path": "tests/test_loader.py", "line": 5},
            {"id": "r1.F3", "axis": "standards", "severity": "low", "verify": "unverified", "claim": "x", "path": "app/loader.py", "line": 12}]}])

    def lint(self, card_options: dict):
        path = self.card_dir / "context.md"
        path.write_text(SAMPLE)
        card = {"id": "c-900", "repo": "api", "options": dict({"review_key": "api:4150",
                                                                 "kind": "review"}, **card_options)}
        return plangate.lint_file(path, card, root=str(self.repo))

    def posted(self):
        return {"review_posted": {"head": self.reviewed, "round": 1, "ledger": [
            {"id": "r1.F3", "path": "app/loader.py", "line": 12, "choice": "drop", "claim": "a name"}]}}

    def test_a_head_the_core_has_not_reviewed_is_refused(self):
        self.record("0" * 40)
        self.assertIn("C29", rules(self.lint({})))

    def test_a_reviewed_head_passes(self):
        self.record(sh(self.repo, "git", "rev-parse", "HEAD"))
        result = self.lint({})
        self.assertTrue(result["ok"], planlint.lines_of(result))

    def test_a_dropped_finding_on_unchanged_lines_is_refused(self):
        self.push(touch_line_12=False)
        self.record(sh(self.repo, "git", "rev-parse", "HEAD"))
        self.assertIn("C31", rules(self.lint(self.posted())))

    def test_a_dropped_finding_whose_lines_changed_may_be_raised_again(self):
        self.push(touch_line_12=True)
        self.record(sh(self.repo, "git", "rev-parse", "HEAD"))
        result = self.lint(self.posted())
        self.assertNotIn("C31", rules(result))
        self.assertTrue(result["ok"], planlint.lines_of(result))


if __name__ == "__main__":
    unittest.main()
