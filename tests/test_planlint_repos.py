"""SH-12: a cross-repo card's `path:line` refs (the lint's C7) resolve against EACH of its
repos' worktrees, and pass when any one has the line.

A card with more than one repo has a worktree per repo: a work card records them
(`options.worktree` for the primary, `options.worktrees` for every repo, written by the
adapter's cut and by the shipping sync), a personal card's are `<id>` and `<id>-<repo>`
side by side under the worktrees directory. Its outcome may cite a file in its second repo,
which the primary's checkout does not have. The same rule holds wherever C7 runs: `kb lint`
and `kb stage` (`plangate`, which `bin/keel-plan-install` goes through too), the plan door
on the machine with the worktrees (`plandoor`), and the local plan page (`planroute`).
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from keel import plangate, planlint, planroute
from tests.helpers import make_config
from tests.test_planlint import SAMPLE

GIT_ID = ("-c", "user.name=t", "-c", "user.email=t@t")


def checkout(root: Path, files: dict) -> Path:
    """A git checkout at `root` whose HEAD has these files of so many lines."""
    root.mkdir(parents=True)
    subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "main"], check=True)
    for name, lines in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("\n".join(f"line {i}" for i in range(lines)) + "\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), *GIT_ID, "commit", "-q", "-m", "x"], check=True)
    return root


def c7(result: dict) -> list[str]:
    return [f["text"] for f in result["findings"] if f["rule"] == "C7"]


class CrossRepoCase(unittest.TestCase):
    """The sample cites `keel/prompts.py:12` (in the primary) and `keel/planstate.py:40-52`
    (only in the second repo's worktree)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.primary = checkout(self.dir / "cloud-wt", {"keel/prompts.py": 20})
        self.second = checkout(self.dir / "web-wt", {"keel/planstate.py": 60})
        self.plan = self.dir / "plan.md"
        self.plan.write_text(SAMPLE)

    def work_card(self, **options) -> dict:
        return {"id": "c-501", "space": "work", "repo": "api,web", "stage": "review",
                "options": {"worktree": str(self.primary), **options}}


class KbLintTest(CrossRepoCase):
    def test_a_ref_only_the_second_repo_has_passes(self):
        card = self.work_card(worktrees={"api": str(self.primary), "web": str(self.second)})
        self.assertEqual(c7(plangate.lint_file(self.plan, card, root=str(self.primary))), [])

    def test_without_the_second_worktree_it_is_refused_as_before(self):
        texts = c7(plangate.lint_file(self.plan, self.work_card(), root=str(self.primary)))
        self.assertEqual(len(texts), 1, texts)
        self.assertIn("planstate.py:40-52", texts[0])

    def test_a_ref_neither_has_is_refused_and_says_so(self):
        card = self.work_card(worktrees={"web": str(self.second)})
        self.plan.write_text(SAMPLE.replace("keel/prompts.py:12", "keel/nowhere.py:3"))
        texts = c7(plangate.lint_file(self.plan, card, root=str(self.primary)))
        self.assertEqual(len(texts), 1, texts)
        self.assertIn("nowhere.py:3", texts[0])
        self.assertIn("any of the card's 2 worktrees", texts[0])

    def test_a_personal_card_s_second_worktree_is_its_id_and_repo_beside_the_first(self):
        first = checkout(self.dir / "worktrees" / "c-7", {"keel/prompts.py": 20})
        checkout(self.dir / "worktrees" / "c-7-web", {"keel/planstate.py": 60})
        card = {"id": "c-7", "space": "personal", "repo": "keel,web", "stage": "review", "options": {}}
        self.assertEqual(c7(plangate.lint_file(self.plan, card, root=str(first))), [])


class PageTest(CrossRepoCase):
    def setUp(self):
        super().setUp()
        self.cfg = make_config(self.dir / "keel")
        self.card = self.work_card(worktrees={"web": str(self.second)})
        self.card["plan_ref"] = str(self.cfg.card_dir("c-501") / "plan.md")
        Path(self.card["plan_ref"]).parent.mkdir(parents=True, exist_ok=True)
        Path(self.card["plan_ref"]).write_text(SAMPLE)

    def test_the_local_plan_page_checks_every_worktree(self):
        resolve = planroute.resolver(self.cfg, self.card)
        self.assertIsNone(resolve("keel/planstate.py", 40, 52))
        self.assertIsNone(resolve("keel/prompts.py", 12, 12))
        self.assertIsNotNone(resolve("keel/nowhere.py", 1, 1))


class RootsTest(CrossRepoCase):
    def test_the_roots_are_the_given_one_then_the_recorded_ones_each_once_and_only_on_disk(self):
        card = self.work_card(worktrees={"api": str(self.primary), "web": str(self.second),
                                         "gone": str(self.dir / "gone")})
        self.assertEqual(planlint.card_roots(card, self.primary), [self.primary, self.second])


    def test_a_feature_review_card_s_member_checkouts_are_roots_too(self):
        """c-511, 2026-09-25: a feature review card keeps its members' checkouts in
        `options.review_worktrees`; the page and the door checked only `options.worktree`,
        so every ref into the second repo read as broken on its outcome page."""
        card = self.work_card(worktree=str(self.primary))
        card["options"]["review_worktrees"] = {"api#1": str(self.primary), "web#2": str(self.second)}
        self.assertEqual(planlint.card_roots(card, None), [self.primary, self.second])
        resolve = planlint.card_resolver(card, None)
        self.assertIsNone(resolve("keel/planstate.py", 40, 52))


if __name__ == "__main__":
    unittest.main()
