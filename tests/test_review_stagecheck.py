"""The pipeline's preship and risk steps, held at `kb stage review` (HP-2).

A house started with the pipeline cannot stage review on a branch that does not contain its
base's current head, with a surviving finding it has neither fixed nor answered, with a
surviving high finding its outcome does not name, or with a Risk lower than the one Keel
computed. And the lint refuses a repo card's outcome with no Evidence or no Risk (C26, C27).
"""

import argparse
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from keel import planlint, plangate
from keel.board import Refused
from keel.review import prep, stagecheck, stamp
from tests.helpers import ROOT, SESSION, make_config, make_repo

GIT = ("git", "-c", "user.name=t", "-c", "user.email=t@x")

OUTCOME = """---
kind: outcome
card: c-001
title: Add a thing
repo: keel
---
# c-001 Add a thing

## Where it stands

Built and tested.

## What is next

His review.

## Why this shape

It is the smallest change.

```board Code flow: the thing
b-001
```

### Read it in this order

1. tests/test_thing.py:12 the test that pins it

## Open questions

None.

## Evidence

`make test` passed; tests/test_thing.py:12 asserts it.
{risk}"""
RISK = "\n## Risk\n\n{level}: {why}\n"


def sh(cwd, *args):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


def finding(fid, severity, verify="kept"):
    return {"id": fid, "axis": "spec", "severity": severity, "path": "a.py", "line": 1,
            "claim": "wrong", "evidence": "a.py:1", "suggestion": "fix", "verify": verify,
            "verify_reason": "", "verify_evidence": "", "public_comment": None}


class LintTest(unittest.TestCase):
    def lint(self, text, ships=True):
        return planlint.lint_text(text, "context.md", repo_card=True, ships=ships)

    def rules(self, result):
        return {f["rule"] for f in result["findings"] if f["level"] == "error"}

    def test_a_shipped_outcome_without_risk_is_refused(self):
        result = self.lint(OUTCOME.format(risk=""))
        self.assertFalse(result["ok"])
        self.assertIn("C27", self.rules(result))

    def test_a_risk_that_names_no_level_is_refused(self):
        result = self.lint(OUTCOME.format(risk=RISK.format(level="Some", why="it is fine")))
        self.assertIn("C27", self.rules(result))

    def test_a_risk_with_its_level_holds(self):
        result = self.lint(OUTCOME.format(risk=RISK.format(level="Medium", why="touches auth")))
        self.assertTrue(result["ok"], planlint.lines_of(result))

    def test_a_shipped_outcome_without_evidence_is_refused(self):
        text = OUTCOME.format(risk=RISK.format(level="low", why="docs only"))
        text = text.replace("`make test` passed; tests/test_thing.py:12 asserts it.", "It works.")
        self.assertIn("C26", self.rules(self.lint(text)))

    def test_an_errand_s_outcome_needs_no_risk(self):
        self.assertTrue(self.lint(OUTCOME.format(risk=""), ships=False)["ok"])


class StageCheckCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.repo = make_repo(self.dir / "repo")
        self.wt = self.dir / "wt"
        sh(self.repo, "git", "worktree", "add", "-q", "-b", "keel/c-001", str(self.wt))
        (self.wt / "a.py").write_text("x = 1\n")
        sh(self.wt, *GIT, "add", "a.py")
        sh(self.wt, *GIT, "commit", "-q", "-m", "the change")
        self.cards = self.dir / "cards"
        self.card_dir = self.cards / "c-001"
        self.card_dir.mkdir(parents=True)
        self.write_outcome("low", "nothing risky")
        self.card = {"id": "c-001", "space": "personal", "repo": "keel", "stage": "building",
                     "session_id": SESSION, "options": {"review_session": SESSION,
                                                        "worktree": str(self.wt)}}
        self.stamp_heads(self.wt)

    def stamp_heads(self, *trees):
        """A stamp naming each worktree's head, as a closed pass writes it (c-581)."""
        heads = {str(tree.resolve()): sh(tree, "git", "rev-parse", "HEAD") for tree in trees}
        (self.card_dir / stamp.STAMP_FILE).write_text(json.dumps({"heads": heads, "round": 1}))

    def write_outcome(self, level, why, extra=""):
        (self.card_dir / "context.md").write_text(
            OUTCOME.format(risk=RISK.format(level=level, why=why)) + extra)

    def check(self, card=None):
        stagecheck.check(card or self.card, self.card_dir)

    def rounds(self, found, level="low"):
        stamp.save_rounds(self.card_dir, [{"round": 1, "head": "abc", "complete": True,
                                           "findings": found, "risk": {"level": level, "why": "x"}}])


class BaseTest(StageCheckCase):
    def test_a_branch_that_contains_its_base_passes(self):
        self.check()

    def test_a_branch_behind_its_base_is_refused_with_the_fix(self):
        (self.repo / "b.txt").write_text("moved on\n")
        sh(self.repo, *GIT, "add", "b.txt")
        sh(self.repo, *GIT, "commit", "-q", "-m", "main moves on")
        with self.assertRaises(Refused) as caught:
            self.check()
        self.assertIn("rebase main", str(caught.exception))
        sh(self.wt, *GIT, "rebase", "-q", "main")
        self.check()

    def test_a_base_that_moved_only_on_the_space_s_remote_is_read_there(self):
        """c-665 review F1: the stage check and the review's diff read the base on the space's
        own remote, which the brief tells the house to fetch, not on one named origin."""
        remote = self.dir / "remote.git"
        sh(self.dir, "git", "clone", "-q", "--bare", str(self.repo), str(remote))
        sh(self.repo, "git", "remote", "add", "upstream", str(remote))
        other = self.dir / "other"
        sh(self.dir, "git", "clone", "-q", str(remote), str(other))
        (other / "b.txt").write_text("moved on\n")
        sh(other, *GIT, "add", "b.txt")
        sh(other, *GIT, "commit", "-q", "-m", "main moves on, on the remote only")
        sh(other, "git", "push", "-q", "origin", "HEAD:main")
        self.check()            # a remote named origin is not this clone's: the local main is read
        with self.assertRaises(Refused) as caught:
            stagecheck.check(self.card, self.card_dir, remote="upstream")
        self.assertIn("rebase upstream/main", str(caught.exception))
        with self.assertRaises(prep.PrepError):
            prep.prepare(self.card_dir, "gone", [self.wt], remote="upstream")
        prep.prepare(self.card_dir, "main", [self.wt], remote="upstream")
        seen = json.loads((self.card_dir / stamp.PREP_FILE).read_text())["worktrees"][0]
        self.assertEqual(seen["ref"], "upstream/main")

    def test_the_prep_line_a_refusal_prints_names_a_remote_that_is_not_origin(self):
        """c-665 review pass 2: the stage check tells the house the same prep command its
        brief does, `--remote` included; with the default remote the text is as it was."""
        (self.card_dir / stamp.STAMP_FILE).unlink()
        root = str(self.wt.resolve())
        for remote, flag in ((None, ""), ("origin", ""), ("upstream", " --remote upstream")):
            with self.subTest(remote=remote), self.assertRaises(Refused) as caught:
                stagecheck.check(self.card, self.card_dir, remote=remote)
            self.assertIn(f"`keel-review prep --dir {self.card_dir} --base <base>{flag} --worktree {root}` "
                          f"(no --since)", str(caught.exception))

    def test_a_card_base_option_is_the_base(self):
        sh(self.repo, "git", "branch", "release")
        (self.repo / "b.txt").write_text("moved on\n")
        sh(self.repo, *GIT, "add", "b.txt")
        sh(self.repo, *GIT, "commit", "-q", "-m", "main moves on")
        self.check(dict(self.card, options=dict(self.card["options"], base="release")))

    def test_a_house_started_before_the_pipeline_is_not_held(self):
        (self.repo / "b.txt").write_text("moved on\n")
        sh(self.repo, *GIT, "add", "b.txt")
        sh(self.repo, *GIT, "commit", "-q", "-m", "main moves on")
        self.check(dict(self.card, options={"worktree": str(self.wt)}))

    def test_a_review_card_is_never_held(self):
        (self.repo / "b.txt").write_text("moved on\n")
        sh(self.repo, *GIT, "add", "b.txt")
        sh(self.repo, *GIT, "commit", "-q", "-m", "main moves on")
        self.check(dict(self.card, options=dict(self.card["options"], review_key="r#1")))


class FindingsTest(StageCheckCase):
    def test_an_unanswered_surviving_finding_is_refused(self):
        self.rounds([finding("r1.F1", "low")])
        with self.assertRaises(Refused) as caught:
            self.check()
        self.assertIn("r1.F1", str(caught.exception))
        self.assertIn("keel-review answer", str(caught.exception))

    def test_a_refuted_finding_needs_no_answer(self):
        self.rounds([finding("r1.F1", "medium", verify="refuted")])
        self.check()

    def test_a_surviving_high_finding_must_be_named_in_the_outcome(self):
        self.rounds([finding("r1.F1", "high", verify="disputed")], level="high")
        (self.card_dir / stamp.ANSWERS_FILE).write_text(json.dumps(
            {"r1.F1": {"did": "declined", "why": "the plan keeps it"}}))
        self.write_outcome("high", "one disputed finding")
        with self.assertRaises(Refused) as caught:
            self.check()
        self.assertIn("r1.F1", str(caught.exception))
        self.write_outcome("high", "r1.F1 is disputed and left for him")
        self.check()

    def test_a_risk_lower_than_keel_computed_is_refused(self):
        self.rounds([], level="medium")
        with self.assertRaises(Refused) as caught:
            self.check()
        self.assertIn("medium", str(caught.exception))
        self.write_outcome("high", "raised on purpose")
        self.check()


class StageVerbTest(StageCheckCase):
    def test_kb_stage_review_refuses_a_prepared_card_behind_its_base(self):
        from keel.review import prep
        prep.prepare(self.card_dir, "main", [self.wt])
        (self.repo / "b.txt").write_text("moved on\n")
        sh(self.repo, *GIT, "add", "b.txt")
        sh(self.repo, *GIT, "commit", "-q", "-m", "main moves on")
        args = argparse.Namespace(verb="stage", stage="review", id="c-001", plan=None)
        (self.card_dir / "context.md").write_text("## Where it stands\n\nnot the format\n")
        with self.assertRaises(Refused) as caught:
            plangate.check_stage(args, lambda: self.card, self.cards)
        self.assertIn("behind its base", str(caught.exception))

    def test_a_card_that_never_prepared_costs_no_read_of_the_card(self):
        (self.card_dir / "context.md").write_text("## Where it stands\n\nnot the format\n")
        args = argparse.Namespace(verb="stage", stage="review", id="c-001", plan=None)
        reads = []
        plangate.check_stage(args, lambda: reads.append(1) or self.card, self.cards)
        self.assertEqual(reads, [])


class PreshipFirstTest(StageCheckCase):
    """c-604: in the sandbox no house did preship first (push and draft came last) and none
    ran `keel check`, while the brief said both. In a `preship_first` space `kb stage review`
    now holds the order: the draft before the review pass, and a receipt on HEAD."""

    BUILD = {"kind": "stage", "actor": "drain", "at": "2026-09-30T10:00:00+00:00", "data": {"to": "building"}}

    def setUp(self):
        super().setUp()
        self.cfg = argparse.Namespace(spaces={"personal": argparse.Namespace(preship_first=True)})
        self.args = argparse.Namespace(verb="stage", stage="review", id="c-001", plan=None)
        (self.card_dir / "context.md").write_text("## Where it stands\n\nnot the format\n")

    def with_events(self, drafted_at):
        events = [self.BUILD]
        if drafted_at:
            events.append({"kind": "set", "actor": "house", "at": drafted_at, "data": {"options": {"pr": 7}}})
        return dict(self.card, events=events)

    def reviewed_at(self, at):
        stamp.save_rounds(self.card_dir, [{"round": 1, "head": "abc", "complete": True, "at": at,
                                           "findings": [], "risk": {"level": "low", "why": "x"}}])

    def stage(self, card):
        stagecheck.preship_first_check(card, self.card_dir)

    def test_a_review_taken_before_the_draft_is_refused_with_what_to_run(self):
        self.reviewed_at("2026-09-30T10:20:00+00:00")
        for late in ("2026-09-30T10:30:00+00:00", None):
            with self.assertRaises(Refused) as caught:
                self.stage(self.with_events(late))
            self.assertIn("preship first", str(caught.exception))
            self.assertIn("git push -u origin HEAD", str(caught.exception))
            self.assertIn(f"`keel-review prep --dir {self.card_dir} --base <base>` (no --since)",
                          str(caught.exception))
        with self.assertRaises(Refused) as caught:      # c-665: the space's own remote, in both commands
            stagecheck.preship_first_check(self.with_events(None), self.card_dir, "upstream")
        self.assertIn("git push -u upstream HEAD", str(caught.exception))
        self.assertIn(f"--dir {self.card_dir} --base <base> --remote upstream` (no --since)", str(caught.exception))
        self.stage(self.with_events("2026-09-30T10:10:00+00:00"))

    def test_a_house_that_reviewed_too_early_recovers_by_drafting_and_reviewing_again(self):
        """c-604 review: the check read the trip's EARLIEST pass, which no later push, draft
        and review could ever undo."""
        stamp.save_rounds(self.card_dir, [
            {"round": 1, "head": "abc", "complete": True, "at": "2026-09-30T10:20:00+00:00",
             "findings": [], "risk": {"level": "low", "why": "x"}},
            {"round": 2, "head": "abc", "complete": True, "at": "2026-09-30T10:40:00+00:00",
             "findings": [], "risk": {"level": "low", "why": "x"}}])
        self.stage(self.with_events("2026-09-30T10:30:00+00:00"))

    def test_a_head_no_receipt_covers_is_refused_with_keel_check(self):
        self.reviewed_at("2026-09-30T10:20:00+00:00")
        card = self.with_events("2026-09-30T10:10:00+00:00")
        (self.wt / "a.py").write_text("x = 2\n")
        sh(self.wt, *GIT, "commit", "-q", "-am", "a fix after the review")
        with self.assertRaises(Refused) as caught:
            self.stage(card)
        self.assertIn("keel check c-001", str(caught.exception))
        self.stamp_heads(self.wt)
        self.stage(card)

    def test_kb_stage_review_holds_it_only_in_a_preship_first_space(self):
        (self.wt / "a.py").write_text("x = 2\n")
        sh(self.wt, *GIT, "commit", "-q", "-am", "a commit no receipt covers")
        card = self.with_events(None)
        with self.assertRaises(Refused) as caught:
            plangate.contract_checks(self.args, lambda: card, self.cards, None, self.cfg)
        self.assertIn("keel check c-001", str(caught.exception))
        self.cfg.spaces["personal"].preship_first = False
        plangate.contract_checks(self.args, lambda: card, self.cards, None, self.cfg)


class NothingToLandTest(StageCheckCase):
    """r-32, r-33: a card that only retargeted pull requests says `change: none`; with the
    branch proving it, it reaches his gate with no stamp, no preship order and no draft.
    The proof is the card's own worktree, read with git (c-622 r1.F3, F4)."""

    def setUp(self):
        super().setUp()
        self.cfg = make_config(self.dir / "keel", repos={"keel": self.repo})
        self.cfg.spaces["personal"].preship_first = True
        (self.card_dir / stamp.STAMP_FILE).unlink()      # nothing was built, so nothing was stamped
        self.empty = self.dir / "wt-empty"               # a branch with no commit over main
        sh(self.repo, "git", "worktree", "add", "-q", "-b", "keel/c-001-empty", str(self.empty))

    def change_none(self, worktree: Path, **options) -> dict:
        """The record saying `change: none`, and the card as its house left it."""
        (self.card_dir / "context.md").write_text(
            "---\nkind: outcome\ncard: c-001\ntitle: Retarget\nchange: none\n---\n# Retarget\n\n"
            "Five pull requests retargeted; nothing to land.\n\n## Where it stands\n\nDone.\n\n"
            "## What is next\n\nNothing.\n\n## Why this shape\n\nNo code was needed.\n\n"
            "## Open questions\n\nNone.\n\n## Evidence\n\n```text retarget.log | the retarget output\nPR 7: base changed\n```\n\n"
            "## Risk\n\nlow: nothing ships\n")
        return dict(self.card, events=[PreshipFirstTest.BUILD], session_id=SESSION,
                    options=dict(self.card.get("options") or {}, review_session=SESSION, base="main",
                                 worktree=str(worktree), **options))

    def stage(self, card) -> argparse.Namespace:
        args = argparse.Namespace(verb="stage", stage="review", id="c-001", plan=None)
        plangate.contract_checks(args, lambda: card, self.cards, None, self.cfg)
        return args

    def test_a_card_claimed_under_another_host_name_is_verified_here_by_its_own_branch(self):
        """r-51 (c-622): one machine is every card's machine. A claim naming another host
        (a board brought over from two machines, a drain once started under another name)
        is verified here: no commit over its base passes, and two are sent to preship."""
        claim = {"host": "box", "at": "2026-09-30T10:00:00+00:00"}
        self.assertTrue(self.stage(self.change_none(self.empty, claim=claim)).nothing_to_land)
        (self.wt / "a.py").write_text("x = 2\n")
        sh(self.wt, *GIT, "commit", "-q", "-am", "a second commit")
        with self.assertRaises(Refused) as caught:
            self.stage(self.change_none(self.wt, claim=claim))
        self.assertIn("keel check c-001", str(caught.exception))

    def test_a_card_whose_worktree_is_not_here_is_never_verified_by_the_callers_checkout(self):
        """c-622 r1.F3: the deck's `kb` runs in a clean live checkout; that is not the card's."""
        os.chdir(self.repo)                               # clean, on main: no commit over it
        self.addCleanup(os.chdir, ROOT)
        card = self.change_none(self.dir / "gone")
        with self.assertRaises(Refused):
            self.stage(card)


if __name__ == "__main__":
    unittest.main()
