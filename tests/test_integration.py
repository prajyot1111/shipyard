"""The integration branch (c-526): a Keel outcome lands on `next`, never on main, and every
Keel card builds from `next` and is reviewed against it; an `after` on such a card waits for
it to land (his D1, D2)."""

import json
import tempfile
import unittest
from pathlib import Path

from keel import adapters, authority, house, merging, views
from keel.board import Board
from keel.review import stagecheck
from tests.test_merging import RepoCase, sh


class IntegrationCase(RepoCase):
    def setUp(self):
        super().setUp()
        self.cfg.integration = {"keel": "next"}

    def card_branch(self, card_id: str, name: str, start: str | None = None) -> dict:
        """A second card's worktree and commit, cut from `start` (HEAD without one)."""
        tree = self.cfg.worktrees_dir / card_id
        sh(self.repo, "git", "worktree", "add", "-q", "-b", f"keel/{card_id}-x", str(tree),
           *([start] if start else []))
        (tree / f"{name}.txt").write_text(name + "\n")
        sh(tree, "git", "add", "."); sh(tree, "git", "commit", "-q", "-m", name)
        return {"id": card_id, "space": "personal", "repo": "keel", "title": name,
                "output_ref": f"keel/{card_id}-x"}


class LandsOnNextTest(IntegrationCase):
    def test_an_outcome_lands_on_next_and_main_does_not_move(self):
        main_before = sh(self.repo, "git", "rev-parse", "main")
        result = merging.publish(self.cfg, self.card)
        self.assertIn("merged into next", result)
        self.assertEqual(sh(self.repo, "git", "rev-parse", "main"), main_before)
        self.assertEqual(sh(self.repo, "git", "log", "-1", "--format=%s", "next"),
                         "Merge keel/c-1-thing: A thing (c-1)")
        self.assertFalse((self.repo / "new.txt").exists(), "the live checkout is untouched")
        self.assertIsNone(merging.target_has(self.cfg, self.card, sh(self.repo, "git", "rev-parse", "next")))

    def test_next_is_created_at_main_the_first_time(self):
        self.assertIsNone(merging.ref_head(self.repo, "next"))
        merging.publish(self.cfg, self.card)
        self.assertTrue(merging.ancestor(self.repo, "main", "next"))

    def test_his_own_commit_to_main_is_merged_into_next_first(self):
        merging.publish(self.cfg, self.card)
        (self.repo / "his.txt").write_text("direct\n")
        sh(self.repo, "git", "add", "."); sh(self.repo, "git", "commit", "-q", "-m", "his own")
        second = self.card_branch("c-2", "second", start="next")
        merging.publish(self.cfg, second)
        self.assertTrue(merging.ancestor(self.repo, "main", "next"), "a deploy stays a fast-forward")
        subjects = sh(self.repo, "git", "log", "--format=%s", "main..next")
        self.assertIn("Merge main into next", subjects)

    def test_a_conflict_between_main_and_next_is_not_the_house_s(self):
        merging.publish(self.cfg, self.card)
        (self.repo / "new.txt").write_text("his version\n")
        sh(self.repo, "git", "add", "."); sh(self.repo, "git", "commit", "-q", "-m", "his clash")
        second = self.card_branch("c-2", "second", start="next")
        with self.assertRaises(merging.MergeRefused) as caught:
            merging.publish(self.cfg, second)
        self.assertFalse(str(caught.exception).startswith("merge conflict"))
        self.assertIn("main has commits that conflict with next", str(caught.exception))

    def test_next_moved_while_the_suite_ran_is_built_again(self):
        other = self.card_branch("c-2", "other")
        moved = []

        def guard():
            if not moved:
                moved.append(merging.publish(self.cfg, other))
            return None
        landed = merging.land_card(self.cfg, self.card, guard=guard)
        self.assertIn("merged into next", landed["published"])
        subjects = sh(self.repo, "git", "log", "--format=%s", "main..next")
        self.assertIn("(c-1)", subjects)
        self.assertIn("(c-2)", subjects)

    def test_the_swap_refuses_a_stale_old_value(self):
        merging.publish(self.cfg, self.card)
        head = merging.ref_head(self.repo, "next")
        main = sh(self.repo, "git", "rev-parse", "main")
        self.assertFalse(merging.settle_integration(self.repo, "next", main, main))
        self.assertEqual(merging.ref_head(self.repo, "next"), head)

    def test_a_dirty_live_checkout_does_not_stop_a_landing_on_next(self):
        (self.repo / "README").write_text("mid-edit\n")
        self.assertIn("merged into next", merging.publish(self.cfg, self.card))

    def test_a_repo_without_an_entry_merges_into_main_as_before(self):
        self.cfg.integration = {}
        self.assertIn("merged into main", merging.publish(self.cfg, self.card))

    def test_the_pre_run_builds_on_next(self):
        merging.publish(self.cfg, self.card)
        second = self.card_branch("c-2", "second", start="next")
        record = merging.trial(self.cfg, second)
        self.assertEqual((record["target"], record["result"]), ("next", "green"))
        self.assertEqual(record["base"], merging.ref_head(self.repo, "next"))


class BaseTest(IntegrationCase):
    def test_a_new_worktree_starts_from_next(self):
        merging.publish(self.cfg, self.card)
        card = {"id": "c-3", "space": "personal", "repo": "keel", "title": "Three"}
        tree, = adapters.personal_worktrees(self.cfg, self.cfg.spaces["personal"], card)
        self.assertEqual(sh(tree, "git", "rev-parse", "HEAD"), merging.ref_head(self.repo, "next"))


    def test_the_review_base_is_next_and_a_cards_own_base_never_overrides_it(self):
        card = {"id": "c-3", "space": "personal", "repo": "keel", "options": {}}
        self.assertEqual(house.target_of(self.cfg, card), "main", "before anything lands: main")
        merging.publish(self.cfg, self.card)
        self.assertEqual(house.target_of(self.cfg, card), "next")
        # c-732 r1.F4: the integration branch is config, never a card field, whatever options.base says
        self.assertEqual(house.target_of(self.cfg, dict(card, options={"base": "develop"})), "next")
        self.cfg.integration = {}
        self.assertEqual(house.target_of(self.cfg, card), "main")

    def test_the_stage_check_refuses_a_branch_behind_next(self):
        merging.publish(self.cfg, self.card)
        behind = self.card_branch("c-2", "behind")          # cut from main, before c-1 landed
        tree = self.cfg.worktrees_dir / "c-2"
        with self.assertRaises(Exception) as caught:
            stagecheck.base_check(dict(behind, options={}), tree, "next")
        self.assertIn("next", str(caught.exception))
        stagecheck.base_check(dict(behind, options={}), tree, None)   # main: it contains main

    def test_config_names_the_branch_only_for_a_space_without_an_adapter(self):
        self.assertEqual(self.cfg.integration_of("personal", "keel"), "next")
        self.assertIsNone(self.cfg.integration_of("work", "keel"))
        self.assertIsNone(self.cfg.integration_of("personal", "harbor"))
        self.assertEqual(self.cfg.integrated, frozenset({("personal", "keel")}))


OUTCOME = """---
kind: outcome
card: c-1
title: A thing
repo: keel
---
# c-1 A thing

Built and green: the small change is on its branch.

## Where it stands

- Built.

## What is next

- His gate.

## Why this shape

- It is small.

## Open questions

- None.

## Evidence

```shell | the suite, green
make test
```

## Risk

{risk}
"""


class BosunOutcomeTest(IntegrationCase):
    """Bosun's outcome gate on a real repo (c-526, review F8): the facts read from git, the
    lint, the review record and the stamp; a clean one lands on next and main stays."""

    def setUp(self):
        super().setUp()
        from keel.review import stamp
        self.stamp = stamp
        self.records("c-1")

    def records(self, card_id):
        """The house's outcome, the harness's complete review round and its stamp."""
        self.card_id = card_id
        self.card_dir = self.cfg.cards_dir / card_id
        self.card_dir.mkdir(parents=True, exist_ok=True)
        self.outcome("Low: one file.")
        (self.card_dir / self.stamp.FINDINGS_FILE).write_text(json.dumps({"rounds": [
            {"round": 1, "complete": True, "findings": [], "risk": {"level": "low"}}]}))
        self.stamp_head()

    def outcome(self, risk):
        text = OUTCOME.replace("{risk}", risk).replace("c-1", self.card_id)
        (self.card_dir / "context.md").write_text(text)

    def stamp_head(self):
        head = sh(self.worktree, "git", "rev-parse", "HEAD")
        self.stamp.stamp_path(self.cfg, self.card_id).write_text(
            json.dumps({"head": head, "base": "main"}))

    def refusal(self):
        card = dict(self.card, options={})
        return authority.outcome_refusal(authority.outcome_facts(self.cfg, card))


    def test_a_commit_after_the_review_is_refused(self):
        (self.worktree / "late.txt").write_text("late\n")
        sh(self.worktree, "git", "add", "."); sh(self.worktree, "git", "commit", "-q", "-m", "late")
        self.assertIn("no review stamp covers", self.refusal())

    def test_an_open_round_is_refused(self):
        rounds = [{"round": 1, "complete": True, "findings": []}, {"round": 2, "complete": False}]
        (self.card_dir / self.stamp.FINDINGS_FILE).write_text(json.dumps({"rounds": rounds}))
        self.assertIn("pass 2 is still open", self.refusal())

    def test_a_change_to_bosun_s_memory_is_not_fenced_any_more(self):
        """Builder mode lands Bosun's own authority on next (his call, 2026-09-29); the fence
        that held it back served driven and console cards, retired in c-593."""
        (self.worktree / "bosun" / "memory").mkdir(parents=True)
        (self.worktree / "bosun" / "memory" / "x.md").write_text("wider\n")
        sh(self.worktree, "git", "add", "."); sh(self.worktree, "git", "commit", "-q", "-m", "wider")
        self.stamp_head()
        self.assertIsNone(self.refusal())

    def test_bosun_s_approval_lands_on_next_and_main_stays(self):
        from unittest import mock
        from keel import landing
        board = Board(self.cfg.db_path, switches={"merge_queue", authority.BUILDER, authority.SUPERUSER},
                      integrated=self.cfg.integrated, builds={"keel"})
        self.addCleanup(board.close)
        self.cfg.merge_queue = True
        card = board.create("personal", "A thing", repo="keel", actor="human",
                            autonomy="autonomous")
        moved = self.cfg.worktrees_dir / card          # the board numbers its cards c-001
        sh(self.repo, "git", "worktree", "move", str(self.worktree), str(moved))
        self.worktree = moved
        self.records(card)
        board.stage(card, "assigned", "human")
        board.stage(card, "building", "human", plan_ref="p.md")
        board.stage(card, "review", "house", output_ref="keel/c-1-thing")
        facts = authority.outcome_facts(self.cfg, board.get(card))
        board.approve(card, "outcome", authority.BOSUN,
                      bosun={"checked": "lint, review", "to": self.cfg.host, "facts": facts})
        relay = [e for e in board.events(card) if e["kind"] == "relay"][-1]
        board.carry(card, relay["id"], "drain")
        main = sh(self.repo, "git", "rev-parse", "main")
        with mock.patch.object(landing, "finish_house", return_value=None), \
                mock.patch.object(landing, "listed", return_value=None):
            self.assertEqual(landing.land(self.cfg, board, board.get(card), relay["id"]), 0)
        self.assertEqual(board.get(card)["stage"], "done")
        self.assertEqual(sh(self.repo, "git", "rev-parse", "main"), main)
        self.assertIn(f"({card})", sh(self.repo, "git", "log", "-1", "--format=%s", "next"))


class AfterTest(unittest.TestCase):
    """His D2: an `after` on a card that lands on next is met when it is done, not at review."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board = Board(Path(self.tmp.name) / "board.db", switches={"multi_after"},
                           integrated={("personal", "keel")})
        self.addCleanup(self.board.close)

    def at(self, repo, stage):
        card = self.board.create("personal", "first", repo=repo, actor="human",
                                 autonomy="autonomous")
        self.board.stage(card, "assigned", "human")
        self.board.stage(card, "building", "human", plan_ref="p.md")
        if stage in ("review", "done"):
            self.board.stage(card, "review", "human", output_ref="b")
        if stage == "done":
            self.board.approve(card, "outcome", "human")
        return card

    def waiter(self, first):
        card = self.board.create("personal", "second", repo="keel", actor="human")
        self.board.set_fields(card, {"after": first}, "human")
        return self.board.conn.execute("SELECT * FROM cards WHERE id = ?", (card,)).fetchone()

    def test_review_is_not_enough_on_an_integration_repo(self):
        first = self.at("keel", "review")
        self.assertEqual(views.waiting_for(self.board, self.waiter(first)), [first])


    def test_any_other_repo_keeps_review(self):
        first = self.at("harbor", "review")
        self.assertEqual(views.waiting_for(self.board, self.waiter(first)), [])


if __name__ == "__main__":
    unittest.main()


class LandedBranchTest(IntegrationCase):
    """c-535 (r-9): `git branch -d` checks the branch against the checkout's HEAD, which is
    main, so after every landing on `next` the card's branch stayed behind (c-530)."""

    def test_a_branch_landed_on_next_is_deleted(self):
        landed = merging.land_card(self.cfg, self.card)
        self.assertNotIn("keel/c-1-thing", sh(self.repo, "git", "branch", "--list"))
        self.assertEqual(landed["notes"], [])

    def test_a_branch_not_in_the_target_is_kept_and_said(self):
        notes = merging.clean_up(self.repo, self.worktree, "keel/c-1-thing", "main")
        self.assertIn("keel/c-1-thing", sh(self.repo, "git", "branch", "--list"))
        self.assertEqual(len(notes), 1)
        self.assertIn("is not in main", notes[0])
