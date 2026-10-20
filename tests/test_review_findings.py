"""Lane FC, FC-1 and FC-7: a review finding is ONE block, `finding <id>`, carrying everything
about it: its severity, the member pull request on a feature card, its `path:line`, the
claim, the evidence, the verifier's word (disputed with both sides), a suggestion, the
drafted public comment and the choice with its reason. The lint holds the fields posting
reads; the old batch-and-comments shape stays readable for an outcome already written, and a
new one in it is refused. Every pull request here is invented.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from keel import planformat, planlint, planreview, planstate
from keel.planinline import plain
from tests.helpers import make_repo

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = (FIXTURES / "review-sample.md").read_text()
FEATURE = (FIXTURES / "review-feature-sample.md").read_text()
OLD = (FIXTURES / "review-sample-batch.md").read_text()
MEMBERS = ["api#4150", "web#2200"]
GIT = ("git", "-c", "user.name=t", "-c", "user.email=t@x")


def resolve_all(path, start, end):
    return None


def lint(text, **kwargs):
    kwargs.setdefault("resolve", resolve_all)
    return planlint.lint_text(text, "context.md", repo_card=True, **kwargs)


def errors(result):
    return [f for f in result["findings"] if f["level"] == "error"]


def rules(result):
    return sorted({f["rule"] for f in errors(result)})


def texts(result):
    return " | ".join(f["text"] for f in errors(result))


def block(text, block_id):
    doc = planformat.parse(text, "context.md")
    return next(b for b in planformat.all_blocks(doc["blocks"]) if b.get("id") == block_id)


class ParseTest(unittest.TestCase):
    def test_a_finding_block_carries_every_field(self):
        one = block(SAMPLE, "r1-f1")
        self.assertEqual(one["type"], "finding")
        self.assertEqual((one["severity"], one["path"], one["start"], one["end"]), ("high", "app/loader.py", 40, 40))
        self.assertEqual(one["verifier"], "kept")
        self.assertEqual(one["rec"], "post")
        self.assertEqual(one["choices"], ["post", "edit", "drop"])
        self.assertIn("before the settings load", plain(one["claim"]))
        self.assertTrue(one["comment"].startswith("The cap is read at import time"))
        self.assertIn("always be the default. Could it", one["comment"].replace("\n", " "))
        self.assertTrue(one.get("evidence") and one.get("suggestion") and one.get("because"))
        self.assertNotIn("problems", one)

    def test_a_range_and_a_disputed_verdict_keep_both_sides(self):
        two = block(SAMPLE, "r1-f2")
        self.assertEqual((two["start"], two["end"]), (5, 6))
        self.assertEqual(two["verifier"], "disputed")
        self.assertTrue(two.get("for") and two.get("against"))

    def test_a_comment_keeps_its_paragraphs(self):
        self.assertIn("with it.\n\nA literal", block(SAMPLE, "r1-f2")["comment"])

    def test_a_line_wrapped_at_the_fence_width_is_one_line(self):
        self.assertIn("so it looks like it will always be the default", block(SAMPLE, "r1-f1")["comment"])
        text = SAMPLE.replace("  Small one", "  Small one").replace(
            "comment: Small one: `list` shadows the builtin here.",
            "comment:\n  Two points:\n  - the name\n  - the loop")
        self.assertEqual(block(text, "r1-f3")["comment"], "Two points:\n- the name\n- the loop")

    def test_a_one_line_comment_is_the_line(self):
        self.assertEqual(block(SAMPLE, "r1-f3")["comment"], "Small one: `list` shadows the builtin here.")

    def test_the_member_is_a_field(self):
        self.assertEqual(block(FEATURE, "r1-f2")["member"], "web#2200")

    def test_the_path_line_is_a_reference_the_lint_can_check(self):
        refs = list(planlint.refs_of(block(SAMPLE, "r1-f1")))
        self.assertIn(("app/loader.py", 40, 40), [(r["path"], r["start"], r["end"]) for r in refs if r["kind"] == "path"])

    def test_each_wrong_field_is_a_problem_of_its_own(self):
        bad = ("```finding x1\nseverity: urgent\nat: nowhere\nverifier: maybe\nchoice: ship\n```\n")
        got = planformat.parse("---\nkind: review\n---\n# t\n\nsummary.\n\n## Findings\n\n" + bad, "context.md")
        problems = " | ".join(p["text"] for p in got["problems"])
        for words in ("severity", "urgent", "path:line", "claim", "comment", "verifier", "ship"):
            self.assertIn(words, problems)

    def test_a_disputed_finding_says_both_sides(self):
        text = SAMPLE.replace("  against: the fixture pins the settings, so the expression is a literal in effect\n", "")
        self.assertIn("both sides", " ".join(block(text, "r1-f2").get("problems", [])))


class LintTest(unittest.TestCase):

    def test_a_finding_with_no_choice_is_refused(self):
        text = SAMPLE.replace("choice: drop\nbecause: low, style only\n", "")
        self.assertIn("C29", rules(lint(text)))

    def test_a_severity_that_is_not_one_of_the_four_is_refused(self):
        self.assertIn("C29", rules(lint(SAMPLE.replace("severity: low", "severity: trivial"))))

    def test_a_path_line_that_does_not_resolve_is_refused(self):
        def only_short(path, start, end):
            return "it has 20 lines" if end > 20 else None
        self.assertIn("C7", rules(lint(SAMPLE, resolve=only_short)))

    def test_the_old_batch_shape_is_refused_for_a_new_outcome(self):
        found = lint(OLD)
        self.assertIn("C29", rules(found))
        self.assertIn("```finding", texts(found))

    def test_the_old_shape_stays_readable_where_it_was_already_written(self):
        found = lint(OLD, legacy=True)
        self.assertTrue(found["ok"], planlint.lines_of(found))
        self.assertTrue(any(f["rule"] == "C29" and f["level"] == "warn" for f in found["findings"]))

    def test_a_snippets_section_is_refused_beside_finding_blocks(self):
        text = SAMPLE.replace("## Verdict", "## Snippets\n\n```python app/loader.py:36-44 | why\nCAP = 1\n```\n\n## Verdict")
        self.assertIn("C29", rules(lint(text)))

    def test_a_feature_finding_names_a_member_in_its_field(self):
        text = FEATURE.replace("member: web#2200\nat: src/Details.js:88", "at: src/Details.js:88")
        found = lint(text, review={"members": MEMBERS, "surviving": [], "ledger": []})
        self.assertIn("C32", rules(found))
        self.assertIn("r1-f2 names no member", texts(found))
        stranger = FEATURE.replace("member: web#2200\nat: src/Details.js:88", "member: web#9\nat: src/Details.js:88")
        self.assertIn("C32", rules(lint(stranger, review={"members": MEMBERS, "surviving": [], "ledger": []})))


class MemberWorktreeTest(unittest.TestCase):
    """FC-1: a feature finding's path:line resolves in ITS member's worktree, not any."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.trees = {}
        for label, path, lines in (("api#4150", "app/routes.py", 60), ("web#2200", "src/Details.js", 100)):
            repo = make_repo(root / label.split("#")[0])
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text("".join(f"line {n}\n" for n in range(1, lines + 1)))
            subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True, capture_output=True)
            subprocess.run([*GIT, "commit", "-q", "-m", "x"], cwd=repo, check=True, capture_output=True)
            self.trees[label] = str(repo)

    def review(self):
        return {"members": MEMBERS, "surviving": [], "ledger": [], "worktrees": self.trees}

    def test_each_finding_resolves_in_its_own_member(self):
        self.assertNotIn("C32", rules(lint(FEATURE, review=self.review())))

    def test_a_finding_on_the_wrong_member_is_refused(self):
        text = FEATURE.replace("member: web#2200\nat: src/Details.js:88", "member: api#4150\nat: src/Details.js:88")
        found = lint(text, review=self.review())
        self.assertIn("C32", rules(found))
        self.assertIn("api#4150", texts(found))


class RoundTest(unittest.TestCase):
    """A finding's pick is a row mark on its own block, composed like a batch row."""

    def test_an_edit_on_a_finding_is_his_words(self):
        doc = planformat.parse(SAMPLE, "context.md")
        events = [{"id": 1, "kind": "mark", "actor": "human", "at": "t",
                   "data": {"what": "answer", "doc": "outcome", "block": "r1-f1", "row": "r1-f1",
                            "choice": "edit", "other": "Could the cap be read per call?"}}]
        state = planstate.state_of(events, "outcome")
        text = planstate.compose(doc, state, "approve", "c-900")
        self.assertIn("r1-f1", text)
        self.assertIn("THE USER CHOSE edit", text)
        self.assertIn("Could the cap be read per call?", text)
        self.assertEqual(planstate.summary(doc, state)["changed"], 1)
        self.assertEqual(planstate.summary(doc, state)["decisions"], 4)

    def test_the_counts_see_a_finding_as_a_decision(self):
        self.assertEqual(planformat.parse(SAMPLE, "context.md")["counts"]["decisions"], 4)


class ItemsTest(unittest.TestCase):
    """One reading of a review's findings, whatever shape it was written in."""

    def test_the_new_shape(self):
        got = planreview.items(planformat.parse(SAMPLE, "context.md"))
        self.assertEqual([(i["id"], i["path"], i["line"], i["rec"], i["mark"]) for i in got],
                         [("r1-f1", "app/loader.py", 40, "post", ("r1-f1", "r1-f1")),
                          ("r1-f2", "tests/test_loader.py", 5, "post", ("r1-f2", "r1-f2")),
                          ("r1-f3", "app/loader.py", 12, "drop", ("r1-f3", "r1-f3"))])

    def test_the_old_shape(self):
        got = planreview.items(planformat.parse(OLD, "context.md"))
        self.assertEqual([(i["id"], i["path"], i["line"], i["mark"]) for i in got],
                         [("r1-f1", "app/loader.py", 40, ("findings", "r1-f1")),
                          ("r1-f2", "tests/test_loader.py", 5, ("findings", "r1-f2")),
                          ("r1-f3", "app/loader.py", 12, ("findings", "r1-f3"))])
        self.assertTrue(got[0]["comment"].startswith("The cap is read at import time"))


if __name__ == "__main__":
    unittest.main()
