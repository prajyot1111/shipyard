"""An outcome's `path:line` refs resolve at the card's branch tip, not at HEAD of whatever
checkout the lint happens to run in (r-23, c-554).

Found 2026-09-27: `kb console plan c-551 --outcome` runs where the board lives, in the live
checkout on main, and refused `adapters/work/readiness.py:94` as "no such file": a file the
card's branch adds, which main does not have yet. The house's own worktree held the branch
and passed. So an outcome is read at the card's tip (`options.branch`, the branch or sha
`output_ref` names, then `options.landing.sha` once the branch is gone), in any checkout of
the repo, since worktrees share one ref store. A plan stays pinned at its `at:`, and a ref
that is not on the branch still refuses.
"""

import argparse
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from keel import cli, plangate, planlint
from tests.helpers import make_config

GIT_ID = ("-c", "user.name=t", "-c", "user.email=t@t")


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def write(root: Path, name: str, lines: int) -> str:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text("\n".join(f"line {i}" for i in range(lines)) + "\n")
    git(root, "add", ".")
    git(root, *GIT_ID, "commit", "-q", "-m", "x")
    return git(root, "rev-parse", "HEAD")


def outcome(ref: str) -> str:
    return ("---\nkind: outcome\ncard: c-901\ntitle: T\nrepo: keel\n---\n"
            f"# T\n\nThe change adds {ref}.\n")


def c7(text: str, resolve) -> list[str]:
    result = planlint.lint_text(text, "context.md", repo_card=True, resolve=resolve)
    return [f["text"] for f in result["findings"] if f["rule"] == "C7"]


class TipCase(unittest.TestCase):
    """A repo on main without `new.py`, and a branch `keel/c-901-x` that adds it (30 lines)
    and is NOT checked out: the live checkout's shape when Bosun lints."""

    BRANCH = "keel/c-901-x"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.repo = self.dir / "keel"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        self.base = write(self.repo, "old.py", 10)
        git(self.repo, "checkout", "-q", "-b", self.BRANCH)
        self.tip = write(self.repo, "new.py", 30)
        git(self.repo, "checkout", "-q", "main")

    def card(self, **options) -> dict:
        return {"id": "c-901", "space": "personal", "repo": "keel", "stage": "review",
                "output_ref": self.BRANCH, "options": options}


class OutcomeAtTipTest(TipCase):
    def test_a_file_the_branch_adds_resolves_from_a_checkout_on_main(self):
        resolve = planlint.card_resolver(self.card(), self.repo)
        self.assertEqual(c7(outcome("new.py:20"), resolve), [])

    def test_a_ref_the_branch_does_not_have_still_refuses_and_names_the_branch(self):
        resolve = planlint.card_resolver(self.card(), self.repo)
        found = c7(outcome("new.py:40"), resolve)
        self.assertEqual(len(found), 1)
        self.assertIn("it has 30 lines", found[0])
        self.assertIn(self.BRANCH, found[0])
        self.assertIn("no such file", c7(outcome("gone.py:1"), resolve)[0])

    def test_output_ref_as_branch_at_sha_and_options_branch_are_read(self):
        card = self.card()
        card["output_ref"] = f"branch {self.BRANCH} @ {self.tip[:10]}"
        self.assertEqual(c7(outcome("new.py:20"), planlint.card_resolver(card, self.repo)), [])
        card = self.card(branch=self.BRANCH)
        card["output_ref"] = "https://example.invalid/pull/1"
        self.assertEqual(c7(outcome("new.py:20"), planlint.card_resolver(card, self.repo)), [])

    def test_the_landing_sha_serves_once_the_branch_is_deleted(self):
        git(self.repo, "branch", "-q", "-D", self.BRANCH)
        card = self.card(landing={"state": "landed", "sha": self.tip})
        self.assertEqual(c7(outcome("new.py:20"), planlint.card_resolver(card, self.repo)), [])

    def test_no_tip_the_checkout_has_reads_head_as_before(self):
        card = self.card()
        card["output_ref"] = "keel/c-901-never-pushed"
        found = c7(outcome("new.py:20"), planlint.card_resolver(card, self.repo))
        self.assertEqual(len(found), 1)
        self.assertIn("at HEAD: no such file", found[0])

    def test_a_plan_is_still_read_at_its_at_not_at_the_tip(self):
        plan = ("---\nkind: plan\ncard: c-901\ntitle: T\nrepo: keel\n"
                f"at: {self.base}\n---\n# T\n\nIt reads new.py:20 today.\n")
        found = c7(plan, planlint.card_resolver(self.card(), self.repo))
        self.assertEqual(len(found), 1)
        self.assertIn(self.base[:10], found[0])


class ScopeTest(TipCase):
    """Review r1: a review reads its detached head, a cross-repo card falls back per repo,
    and Approve outcome's facts read the card at its landed sha."""

    def test_a_review_reads_its_detached_head_not_a_stale_branch_of_that_name(self):
        git(self.repo, "checkout", "-q", "--detach", "main")
        review = outcome("new.py:20").replace("kind: outcome", "kind: review")
        found = c7(review, planlint.card_resolver(self.card(branch=self.BRANCH), self.repo))
        self.assertEqual(len(found), 1)
        self.assertIn("at HEAD: no such file", found[0])

    def test_a_cross_repo_card_reads_each_repo_at_the_tip_it_has(self):
        web = self.dir / "web"
        web.mkdir()
        git(web, "init", "-q", "-b", "main")
        write(web, "page.js", 8)
        resolve = planlint.card_resolver(self.card(worktrees={"web": str(web)}), self.repo)
        self.assertEqual(c7(outcome("new.py:20 and page.js:8"), resolve), [])
        self.assertIn("in any of the card's 2 worktrees", c7(outcome("page.js:9"), resolve)[0])

    def test_a_sha_tip_is_named_short(self):
        git(self.repo, "branch", "-q", "-D", self.BRANCH)
        card = self.card(landing={"sha": self.tip})
        found = c7(outcome("new.py:31"), planlint.card_resolver(card, self.repo))
        self.assertIn(f"does not resolve at {self.tip[:10]}: it has 30 lines", found[0])

    def test_approve_outcome_s_facts_read_a_landed_card_from_another_repo(self):
        from keel import authority
        git(self.repo, "branch", "-q", "-D", self.BRANCH)
        cfg = make_config(self.dir / "home", repos={"keel": self.repo})
        card_dir = cfg.cards_dir / "c-901"
        card_dir.mkdir(parents=True)
        elsewhere = self.dir / "other"
        elsewhere.mkdir()
        git(elsewhere, "init", "-q", "-b", "main")
        write(elsewhere, "unrelated.py", 5)
        cwd = os.getcwd()
        os.chdir(elsewhere)
        self.addCleanup(os.chdir, cwd)
        card = self.card(landing={"sha": self.tip})
        for ref, bad in (("new.py:20", False), ("new.py:31", True)):
            (card_dir / "context.md").write_text(outcome(ref))
            errors = [e for e in authority.outcome_facts(cfg, card)["errors"] if e.startswith("C7")]
            self.assertEqual(bool(errors), bad, errors)


class CardRootTest(TipCase):
    """D1: `kb lint` and `kb console plan` read the card's own checkout, not the caller's cwd."""

    def setUp(self):
        super().setUp()
        self.cfg = make_config(self.dir / "home", repos={"keel": self.repo})
        self.cfg.cards_dir.joinpath("c-901").mkdir(parents=True)
        self.cfg.cards_dir.joinpath("c-901", "context.md").write_text(outcome("new.py:20"))
        self.elsewhere = self.dir / "other"
        self.elsewhere.mkdir()
        git(self.elsewhere, "init", "-q", "-b", "main")
        write(self.elsewhere, "unrelated.py", 5)
        cwd = os.getcwd()
        os.chdir(self.elsewhere)
        self.addCleanup(os.chdir, cwd)

    def test_the_card_root_is_its_worktree_then_its_repo(self):
        self.assertEqual(plangate.card_root(self.cfg, self.card()), str(self.repo))
        worktree = self.cfg.worktrees_dir / "c-901"
        git(self.repo, "worktree", "add", "-q", str(worktree), self.BRANCH)
        self.assertEqual(plangate.card_root(self.cfg, self.card()), str(worktree))
        self.assertIsNone(plangate.card_root(self.cfg, dict(self.card(), repo="")))

    def test_console_plan_from_another_repo_reads_the_card_at_its_tip(self):
        board = FakeBoard(self.card())
        args = argparse.Namespace(target="c-901", outcome=True, config=self.cfg)
        got = cli.console_plan(board, args)
        self.assertNotIn("C7", got["lint"])

    def test_kb_lint_from_another_repo_reads_the_card_at_its_tip(self):
        board = FakeBoard(self.card())
        args = argparse.Namespace(id="c-901", file=None, outcome=True, root=None, config=self.cfg)
        found = cli.cmd_lint(board, args, "house")["findings"]
        self.assertEqual([f for f in found if f["rule"] == "C7"], [])


class FakeBoard:
    def __init__(self, card: dict):
        self.card = card

    def get(self, card_id: str) -> dict:
        return self.card

    def events(self, card_id: str) -> list:
        return []


if __name__ == "__main__":
    unittest.main()
