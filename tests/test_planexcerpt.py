"""Lane FC, FC-2 (the server's half): a finding's code is pulled from the worktree AT RENDER.

The house writes where a finding is (`at: path:line`), never the code: the server reads the
lines around it from the card's worktree at HEAD (a feature card's: that member's), four
lines of context either side, and hands them to the page on the finding block, so the code
he reads is the code the comment will land on and cannot drift from it. A card whose house
is on the other machine gets the lines from that machine's door, beside its C7 refs.
Every repo here is invented.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from keel import planexcerpt, planformat
from tests.helpers import make_repo
from tests.test_serve import ServerCase

GIT = ("git", "-c", "user.name=t", "-c", "user.email=t@x")
SAMPLE = (Path(__file__).parent / "fixtures" / "review-sample.md").read_text()
FEATURE = (Path(__file__).parent / "fixtures" / "review-feature-sample.md").read_text()


def commit(repo: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "x"], cwd=repo, check=True, capture_output=True)


def numbered(count: int, word: str = "line") -> str:
    return "".join(f"{word} {n}\n" for n in range(1, count + 1))


class ExcerptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(Path(self.tmp.name) / "api")
        commit(self.repo, {"app/loader.py": numbered(50), "tests/test_loader.py": numbered(8)})

    def test_four_lines_either_side_with_the_finding_s_lines_marked(self):
        got = planexcerpt.excerpt(self.repo, "app/loader.py", 40, 40)
        self.assertEqual((got["first"], got["start"], got["end"]), (36, 40, 40))
        self.assertEqual(got["lines"], [f"line {n}" for n in range(36, 45)])
        self.assertEqual(got["lang"], "python")

    def test_a_range_near_the_top_starts_at_line_one(self):
        got = planexcerpt.excerpt(self.repo, "tests/test_loader.py", 2, 3)
        self.assertEqual(got["first"], 1)
        self.assertEqual(got["lines"], [f"line {n}" for n in range(1, 8)])


    def test_it_is_head_that_is_read_not_a_file_edited_since(self):
        (self.repo / "app" / "loader.py").write_text("edited but not committed\n")
        self.assertEqual(planexcerpt.excerpt(self.repo, "app/loader.py", 40, 40)["lines"][4], "line 40")

    def test_a_missing_file_or_line_says_why_and_draws_no_code(self):
        self.assertIn("no such file", planexcerpt.excerpt(self.repo, "app/gone.py", 1, 1)["why"])
        self.assertIn("50 lines", planexcerpt.excerpt(self.repo, "app/loader.py", 60, 60)["why"])
        self.assertNotIn("lines", planexcerpt.excerpt(self.repo, "app/gone.py", 1, 1))

    def test_every_finding_of_a_document_gets_its_excerpt(self):
        doc = planformat.parse(SAMPLE, "context.md")
        found = planexcerpt.for_doc(doc, lambda member: [self.repo])
        self.assertEqual(sorted(found), ["r1-f1", "r1-f2", "r1-f3"])
        planexcerpt.attach(doc, found)
        block = next(b for b in doc["blocks"] if b.get("id") == "r1-f2")
        self.assertEqual((block["code"]["start"], block["code"]["end"]), (5, 6))


class FeatureTreesTest(unittest.TestCase):
    """A feature finding's code comes from ITS member's worktree (`options.review_worktrees`)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.api, self.web = make_repo(root / "api"), make_repo(root / "web")
        commit(self.api, {"app/routes.py": numbered(60, "route")})
        commit(self.web, {"src/Details.js": numbered(100, "toast")})
        self.card = {"id": "c-901", "repo": "api,web", "space": "work",
                     "options": {"review_members": [{"label": "api#4150"}, {"label": "web#2200"}],
                                 "review_worktrees": {"api#4150": str(self.api),
                                                      "web#2200": str(self.web)}}}

    def test_each_member_s_lines_are_its_own(self):
        doc = planformat.parse(FEATURE, "context.md")
        found = planexcerpt.for_doc(doc, planexcerpt.trees_for(self.card, None))
        self.assertEqual(found["r1-f1"]["lines"][4], "route 40")
        self.assertEqual(found["r1-f2"]["lines"][4], "toast 88")
        self.assertEqual(found["r1-f2"]["lang"], "javascript")


class RouteTest(ServerCase):
    """`GET /api/plan/<id>?doc=outcome` carries each finding's lines, read from the worktree."""

    def setUp(self):
        super().setUp()
        self.card = self.board.create("personal", "Review: tidy the loader", repo="keel", actor="human",
                                      options={"kind": "review", "review_key": "keel:1", "slot": "review"})
        tree = make_repo(self.cfg.worktrees_dir / self.card)
        commit(tree, {"app/loader.py": numbered(50), "tests/test_loader.py": numbered(8)})
        self.tree = tree
        card_dir = self.cfg.card_dir(self.card)
        card_dir.mkdir(parents=True, exist_ok=True)
        (card_dir / "context.md").write_text(SAMPLE)

    def finding(self, block_id: str) -> dict:
        answer = self.get_json(f"/api/plan/{self.card}?doc=outcome")
        return next(b for b in answer["doc"]["blocks"] if b.get("id") == block_id)

    def test_the_card_names_the_pull_request_each_finding_links_to(self):
        self.board.set_fields(self.card, {"options": {"review_pr": {"url": "https://example.invalid/pr/1"},
                                                      "review_members": [{"label": "keel#1", "url": "https://example.invalid/pr/1"},
                                                                         {"label": "web#2", "url": "https://example.invalid/pr/2"}]}}, "human")
        prs = self.get_json(f"/api/plan/{self.card}?doc=outcome")["card"]["prs"]
        self.assertEqual(prs, {"pr": "https://example.invalid/pr/1", "keel#1": "https://example.invalid/pr/1",
                               "web#2": "https://example.invalid/pr/2"})

    def test_the_page_gets_the_lines_the_worktree_has_now(self):
        code = self.finding("r1-f1")["code"]
        self.assertEqual((code["first"], code["lines"][4]), (36, "line 40"))
        commit(self.tree, {"app/loader.py": "".join(f"moved {n}\n" for n in range(1, 51))})
        self.assertEqual(self.finding("r1-f1")["code"]["lines"][4], "moved 40")


if __name__ == "__main__":
    unittest.main()
