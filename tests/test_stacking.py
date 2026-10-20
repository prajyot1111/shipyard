"""c-718: a waiting card stacked on the card it waits for, or independent of it.

What is held, each through its public seam:

- the choice is the owner's alone, in a space whose pack stacks; a stacked card waits for
  exactly one card, an ordinary card in its repos with the same base (r1.F8, r1.F12);
- a house cannot reach its own choice or base another way: not `after` on a stacked card,
  not another card's branch once named, not `options.base` under another actor's name
  (r1.F1, r1.F2);
- independent: its `after` holds nothing up; stacked: it starts once the parent names its
  branch and records a change;
- the base a stacked card is taken against is the parent's branch until the parent lands,
  everywhere a base is read (r1.F7), then the parent's base;
- that base is per repo (c-772): a card needs one repo in common with its parent, and in a
  repo the parent does not name it keeps its own base, before the parent lands and after;
- a parent done and archived later is landed, not dropped (r1.F5);
- the owner's Approve plan records the plan's `stack` batch, keeps an owner's earlier choice
  unless flipped, never fails the approve (r1.F13), and keeps the slices' answers for the
  split, which gives each slice its own (c-718's addition, r1.F9).
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import (cli, fixcheck, house, merging, planbrief, planformat, plangate, planstate, prompts, shipping,
                  shipround, stacking)
from keel.board import Board, Refused
from keel.review import stagecheck
from tests.helpers import make_config
from tests.test_cli import KbCase

WORK = frozenset({"work"})
PARENT_BRANCH = "feature/st-1/parent"


class StackCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.board = Board(self.dir / "board.db", stacks=WORK)
        self.parent = self.board.create("work", "the parent", repo="api", autonomy="attended")
        self.child = self.board.create("work", "the child", repo="api", after=self.parent)

    def tearDown(self):
        self.board.close()
        self.tmp.cleanup()

    def stack(self, value, card=None, actor="human"):
        self.board.set_fields(card or self.child, {"options": {stacking.OPTION: value}}, actor)

    def branch(self, pr=True):
        options = {"branch": PARENT_BRANCH} | ({"pr": 41} if pr else {})
        self.board.set_fields(self.parent, {"options": options}, "cli")


class OwnersChoiceTest(StackCase):
    def test_only_the_owner_records_a_choice(self):
        for actor in ("house", "drain", "cli", "bosun", "voice"):
            with self.subTest(actor=actor), self.assertRaises(Refused):
                self.stack(stacking.STACKED, actor=actor)
        with self.assertRaises(Refused):
            self.board.create("work", "filed stacked", repo="api", after=self.parent,
                              options={stacking.OPTION: stacking.STACKED}, actor="house")
        self.stack(stacking.STACKED)
        self.assertEqual(self.board.get(self.child)["options"][stacking.OPTION], stacking.STACKED)

    def test_the_base_is_the_owners_actors_alone(self):
        for actor in ("house", "cli", "drain"):              # r1.F2: a house shell without KEEL_CARD is cli
            with self.subTest(actor=actor), self.assertRaises(Refused):
                self.board.set_fields(self.child, {"options": {"base": "master"}}, actor)
        for actor in ("human", "voice"):
            self.board.set_fields(self.child, {"options": {"base": "master"}}, actor)

    def test_a_stacked_cards_after_is_the_owners_and_checked_again(self):   # r1.F1
        other = self.board.create("work", "another", repo="api")
        self.stack(stacking.STACKED)
        for actor in ("house", "cli", "drain"):
            with self.subTest(actor=actor), self.assertRaises(Refused):
                self.board.set_fields(self.child, {"after": other}, actor)
        with self.assertRaises(Refused) as refused:
            self.board.set_fields(self.child, {"after": f"{self.parent},{other}"}, "human")
        self.assertIn("ONE card", str(refused.exception))
        self.board.set_fields(self.child, {"after": other}, "human")
        plain = self.board.create("work", "no choice", repo="api", after=self.parent)
        self.board.set_fields(plain, {"after": other}, "house")    # no choice: as before

    def test_a_branch_is_named_once_then_only_the_owner_moves_it(self):     # r1.F1
        self.branch()
        self.board.set_fields(self.parent, {"options": {"branch": PARENT_BRANCH}}, "house")   # same: fine
        for actor in ("house", "cli", "drain"):
            with self.subTest(actor=actor), self.assertRaises(Refused):
                self.board.set_fields(self.parent, {"options": {"branch": "feature/elsewhere"}}, actor)
        self.board.set_fields(self.parent, {"options": {"branch": "feature/elsewhere"}}, "human")

    def test_the_choice_needs_a_pack_that_stacks_and_one_card_to_stack_on(self):
        mine = self.board.create("personal", "a personal one", repo="keel", after=self.parent)
        with self.assertRaises(Refused) as refused:
            self.stack(stacking.STACKED, card=mine)
        self.assertIn("does not stack cards", str(refused.exception))
        alone = self.board.create("work", "waits for nothing", repo="api")
        with self.assertRaises(Refused):
            self.stack(stacking.INDEPENDENT, card=alone)
        with self.assertRaises(Refused):
            self.stack("sideways")
        self.stack(None)                      # clearing is always the owner's

    def test_stacked_needs_an_ordinary_parent_in_its_repos_with_its_base(self):   # r1.F8, r1.F12
        web = self.board.create("work", "in web", repo="web", after=self.parent)
        with self.assertRaises(Refused) as refused:
            self.stack(stacking.STACKED, card=web)
        self.assertIn("not in web", str(refused.exception))
        research = self.board.create("work", "research", repo="api", options={"kind": "research"})
        reader = self.board.create("work", "reads it", repo="api", after=research)
        with self.assertRaises(Refused) as refused:
            self.stack(stacking.STACKED, card=reader)
        self.assertIn("research card", str(refused.exception))
        self.board.create("work", "a slice", repo="api", parent=self.parent)
        with self.assertRaises(Refused) as refused:
            self.stack(stacking.STACKED)
        self.assertIn("tracking card", str(refused.exception))
        self.stack(stacking.INDEPENDENT)      # independent asks nothing of the parent

    def test_a_base_other_than_the_parents_is_refused(self):     # r1.F12
        self.board.set_fields(self.parent, {"options": {"base": "release"}}, "human")
        self.board.set_fields(self.child, {"options": {"base": "master"}}, "human")
        with self.assertRaises(Refused) as refused:
            self.stack(stacking.STACKED)
        self.assertIn("merges into master", str(refused.exception))
        self.board.set_fields(self.child, {"options": {"base": "release"}}, "human")
        self.stack(stacking.STACKED)
        with self.assertRaises(Refused):
            self.board.set_fields(self.child, {"options": {"base": "master"}}, "human")


class WaitingTest(StackCase):
    def ready(self, card_id):
        self.board.stage(card_id, "assigned", "human")
        return self.board.get(card_id)["derived"]

    def test_with_no_choice_a_card_waits_as_before(self):
        derived = self.ready(self.child)
        self.assertEqual((derived["waiting_for"], derived["startable"], derived["stack"]),
                         ([self.parent], False, None))

    def test_independent_starts_at_once(self):
        self.stack(stacking.INDEPENDENT)
        derived = self.ready(self.child)
        self.assertEqual((derived["waiting_for"], derived["startable"]), ([], True))
        self.assertEqual(derived["after"], [self.parent])

    def test_stacked_starts_once_the_parent_names_its_branch_and_records_a_change(self):
        self.stack(stacking.STACKED)
        self.assertFalse(self.ready(self.child)["startable"])
        self.board.set_fields(self.parent, {"options": {"pr": 41}}, "cli")
        self.assertFalse(self.board.get(self.child)["derived"]["startable"])   # r1.F8: no branch
        self.branch()
        derived = self.board.get(self.child)["derived"]
        self.assertTrue(derived["startable"])
        self.assertEqual({k: derived["stack"][k] for k in ("choice", "on", "branch", "pushed", "landed")},
                         {"choice": "stacked", "on": self.parent, "branch": PARENT_BRANCH,
                          "pushed": True, "landed": False})

    def test_a_parent_done_and_archived_later_is_landed_not_dropped(self):     # r1.F5
        self.stack(stacking.STACKED)
        self.board.conn.execute("UPDATE cards SET stage = 'done' WHERE id = ?", (self.parent,))
        self.board.set_fields(self.parent, {"options": {"archived": True}}, "human")
        found = self.board.get(self.child)["derived"]["stack"]
        self.assertEqual((found["landed"], found["dropped"]), (True, False))
        self.board.conn.execute("UPDATE cards SET stage = 'building' WHERE id = ?", (self.parent,))
        self.assertTrue(self.board.get(self.child)["derived"]["stack"]["dropped"])


class BaseTest(StackCase):
    def setUp(self):
        super().setUp()
        self.cfg = make_config(self.dir / "cfg")
        self.branch()
        self.board.set_fields(self.parent, {"options": {"base": "release"}}, "human")
        self.stack(stacking.STACKED)

    def test_the_parents_branch_is_the_base_until_it_lands_then_the_parents_base(self):
        card = self.board.get(self.child)
        self.assertEqual((stacking.base_of(card), house.target_of(self.cfg, card)), (PARENT_BRANCH, PARENT_BRANCH))
        self.board.conn.execute("UPDATE cards SET stage = 'done' WHERE id = ?", (self.parent,))
        card = self.board.get(self.child)
        self.assertEqual(card["derived"]["stack"]["base"], "release")
        self.assertEqual((stacking.base_of(card), house.target_of(self.cfg, card)), ("release", "release"))

    def test_every_reader_of_the_base_reads_the_stacked_one(self):     # r1.F7, r2.F11
        card = self.board.get(self.child)
        self.assertEqual(shipping.base_of(card), PARENT_BRANCH)
        self.assertEqual(plangate.claim_base(self.cfg, card, self.dir), PARENT_BRANCH)

    def test_the_stage_check_holds_a_stacked_card_to_its_parents_branch(self):     # r2.F11
        origin, tree = self.dir / "origin.git", self.dir / "tree"
        sh("git", "init", "-q", "--bare", "-b", "release", str(origin))
        sh("git", "clone", "-q", str(origin), str(tree))
        commit(tree, "a", "base")
        sh("git", "-C", str(tree), "push", "-q", "origin", "HEAD:release")
        sh("git", "-C", str(tree), "checkout", "-qb", PARENT_BRANCH)
        commit(tree, "b", "the parent's")
        sh("git", "-C", str(tree), "push", "-q", "origin", f"HEAD:{PARENT_BRANCH}")
        sh("git", "-C", str(tree), "checkout", "-qb", "child", "origin/release")
        commit(tree, "c", "the child's own")
        card = self.board.get(self.child)
        with self.assertRaises(Refused) as refused:          # cut from the base: it lacks the parent
            stagecheck.base_check(card, tree)
        self.assertIn(f"origin/{PARENT_BRANCH}", str(refused.exception))
        sh("git", "-C", str(tree), "rebase", "-q", f"origin/{PARENT_BRANCH}")
        stagecheck.base_check(card, tree)                     # on the parent's branch: it holds


class PerRepoTest(StackCase):
    """c-772: the parent works in api alone; the card in api and web."""

    def setUp(self):
        super().setUp()
        self.cfg = make_config(self.dir / "cfg")
        self.branch()
        self.board.set_fields(self.parent, {"options": {"base": "release"}}, "human")
        self.both = self.board.create("work", "in both", repo="api,web", after=self.parent)

    def land(self):
        self.board.conn.execute("UPDATE cards SET stage = 'done' WHERE id = ?", (self.parent,))

    def test_one_shared_repo_is_enough_and_none_is_refused(self):
        self.stack(stacking.STACKED, card=self.both)
        found = self.board.get(self.both)["derived"]["stack"]
        self.assertEqual((found["choice"], found["repos"]), ("stacked", ["api"]))
        said = [e["text"] for e in self.board.events(self.both) if e["kind"] == "note"]
        self.assertEqual(len(said), 1)                       # read back: which repo is which
        self.assertIn(f"stacked on {self.parent} in api", said[0])
        self.assertIn("in web", said[0])
        elsewhere = self.board.create("work", "elsewhere", repo="web,docs", after=self.parent)
        with self.assertRaises(Refused) as refused:
            self.stack(stacking.STACKED, card=elsewhere)
        self.assertIn("not in web, docs", str(refused.exception))

    def test_a_card_in_its_parents_repos_alone_is_read_back_by_no_note(self):
        self.stack(stacking.STACKED)
        self.assertEqual(self.board.get(self.child)["derived"]["stack"]["repos"], ["api"])
        self.assertEqual([e for e in self.board.events(self.child) if e["kind"] == "note"], [])

    def test_the_base_is_the_parents_only_in_a_repo_the_parent_names(self):
        self.stack(stacking.STACKED, card=self.both)
        card = self.board.get(self.both)
        self.assertEqual((stacking.base_of(card, "api"), stacking.base_of(card, "web"), stacking.base_of(card)),
                         (PARENT_BRANCH, None, PARENT_BRANCH))
        self.assertEqual(stacking.split_repos(card), (["api"], ["web"]))
        self.land()
        card = self.board.get(self.both)
        self.assertEqual((stacking.base_of(card, "api"), stacking.base_of(card, "web")), ("release", None))

    def cut(self, card_id, **cut_from):
        """What the drain records at the cut (`options.cut_from`, its alone to write)."""
        options = dict(self.board.get(card_id)["options"], cut_from=cut_from)
        self.board.conn.execute("UPDATE cards SET options = ? WHERE id = ?", (json.dumps(options), card_id))

    def trees(self):
        return self.dir / self.both, self.dir / f"{self.both}-web"

    def test_each_reader_asks_about_its_own_repo(self):
        """No `options.base` on the card: the apart repo's base is its own rule's, here the
        branch it was cut from, and never the parent's branch."""
        self.stack(stacking.STACKED, card=self.both)
        self.cut(self.both, api="trunk", web="trunk")
        card, (api, web) = self.board.get(self.both), self.trees()
        self.assertEqual([merging.base_in(self.cfg, card, key) for key in (None, "api", "web")],
                         [PARENT_BRANCH, PARENT_BRANCH, "trunk"])
        self.assertEqual((house.target_of(self.cfg, card), house.target_of(self.cfg, card, "web")),
                         (PARENT_BRANCH, "trunk"))
        self.assertEqual((shipping.base_of(card), shipping.repo_base(self.cfg, card, "api", PARENT_BRANCH),
                          shipping.repo_base(self.cfg, card, "web", PARENT_BRANCH),
                          shipping.repo_base(self.cfg, card, None, PARENT_BRANCH)),
                         (PARENT_BRANCH, PARENT_BRANCH, "trunk", None))
        self.assertEqual((shipping.tree_base(self.cfg, card, api, PARENT_BRANCH),
                          shipping.tree_base(self.cfg, card, web, PARENT_BRANCH)), (PARENT_BRANCH, "trunk"))
        self.assertEqual(plangate.claim_base(self.cfg, card, api), PARENT_BRANCH)
        self.assertNotEqual(plangate.claim_base(self.cfg, card, web), PARENT_BRANCH)
        self.assertEqual(fixcheck.own_bases(self.cfg, card, [api, web]),
                         {str(api): PARENT_BRANCH, str(web): "trunk"})
        said = house.stack_apart(self.cfg, card, PARENT_BRANCH)
        self.assertIn(f"It is stacked on {self.parent} in api", said)
        self.assertIn(f"in web, which {self.parent} does not work in", said)
        self.assertIn(f"Its bases: `{PARENT_BRANCH}` in api, `trunk` in web.", said)
        self.assertIn("--worktree-base", said)

    def test_each_reader_after_the_parent_lands(self):
        """The parent merged into `release`: the card merges there in api, and keeps its own
        base in web, and every reader and both texts say so."""
        self.stack(stacking.STACKED, card=self.both)
        self.cut(self.both, api="trunk", web="trunk")
        self.land()
        card, (api, web) = self.board.get(self.both), self.trees()
        self.assertEqual((house.target_of(self.cfg, card), house.target_of(self.cfg, card, "web")),
                         ("release", "trunk"))
        self.assertEqual((shipping.base_of(card), shipping.repo_base(self.cfg, card, "web", "release")),
                         ("release", "trunk"))
        self.assertEqual(fixcheck.own_bases(self.cfg, card, [api, web]), {str(api): "release", str(web): "trunk"})
        said = house.stack_apart(self.cfg, card, "release")
        self.assertIn(f"It was stacked on {self.parent} in api, and {self.parent} has merged", said)
        self.assertIn("Its bases: `release` in api, `trunk` in web.", said)
        self.assertIn("--worktree-base", said)

    def test_after_landing_on_the_same_base_nothing_more_is_said(self):
        self.board.set_fields(self.parent, {"options": {"base": None}}, "human")
        self.stack(stacking.STACKED, card=self.both)
        self.cut(self.both, api="trunk", web="trunk")
        self.assertIn("Its bases", house.stack_apart(self.cfg, self.board.get(self.both), PARENT_BRANCH))
        self.land()
        card = self.board.get(self.both)
        self.assertEqual((house.target_of(self.cfg, card), house.stack_apart(self.cfg, card, "trunk")),
                         ("trunk", ""))

    def test_a_worktree_whose_base_or_repo_cannot_be_told_refuses_the_check(self):
        """An apart worktree never takes the stacked base by default: no base the rule can
        read, or a worktree that is no repo of the card's, is refused by name."""
        self.stack(stacking.STACKED, card=self.both)
        card, (api, web) = self.board.get(self.both), self.trees()
        with self.assertRaisesRegex(fixcheck.NoBase, f"cannot read a base for web \\({web}\\)"):
            fixcheck.own_bases(self.cfg, card, [api, web])
        self.cut(self.both, web="trunk")
        with self.assertRaisesRegex(fixcheck.NoBase, f"cannot tell which of its repos the worktree {self.dir}"):
            fixcheck.own_bases(self.cfg, self.board.get(self.both), [api, web, self.dir])

    def test_a_fresh_start_names_each_repos_base(self):
        self.board.set_fields(self.both, {"options": {"branch": "feature/st-2/both"}}, "cli")
        self.stack(stacking.STACKED, card=self.both)
        self.cut(self.both, api="trunk", web="trunk")
        said = prompts.afresh(self.board.get(self.both), self.dir, "go on", "old", cfg=self.cfg)
        self.assertIn(f"which merges into `{PARENT_BRANCH}` in api and `trunk` in web", said)
        self.land()
        said = prompts.afresh(self.board.get(self.both), self.dir, "go on", "old", cfg=self.cfg)
        self.assertIn("which merges into `release` in api and `trunk` in web", said)
        self.stack(stacking.STACKED)
        self.board.set_fields(self.child, {"options": {"branch": "feature/st-3/child"}}, "cli")
        self.assertIn("which merges into `release`:",
                      prompts.afresh(self.board.get(self.child), self.dir, "go on", "old", cfg=self.cfg))

    def test_create_and_the_plans_approve_read_the_choice_back_per_repo(self):
        made = self.board.create("work", "filed stacked", repo="api,web", after=self.parent,
                                 options={stacking.OPTION: stacking.STACKED}, actor="human")
        which = f"stacked on {self.parent} in api; in web, which {self.parent} does not work in"
        self.assertEqual([e["text"].startswith(f"this card is {which}")
                          for e in self.board.events(made) if e["kind"] == "note"], [True])
        rows = f"{self.both}: in both | stacked | shares the parser\n{self.child}: the child | stacked | same"
        doc = planformat.parse(PLAN.format(parent=self.parent, rows=rows), "plan.md")
        stacking.record(self.board, self.parent, doc, planstate.state_of(self.board.events(self.parent)))
        (said,) = [e["text"] for e in self.board.events(self.parent)
                   if e["kind"] == "note" and e["text"].startswith("stacking recorded")]
        self.assertIn(f"{self.both} {which}", said)
        self.assertIn(f"{self.child} stacked", said)
        self.assertNotIn(f"{self.child} stacked on", said)

    def test_a_parents_repo_set_is_checked_against_the_cards_stacked_on_it(self):
        """The parent's repos decide where its children are stacked: a set that leaves one
        sharing none is refused by name, and one that moves a child's split is said on it."""
        self.stack(stacking.STACKED, card=self.both)
        with self.assertRaisesRegex(Refused, f"{self.both} is stacked on {self.parent} and works in api, web: "
                                             f"with repo docs, {self.parent} would have no branch"):
            self.board.set_fields(self.parent, {"repo": "docs"}, "human")
        self.assertEqual(self.board.get(self.parent)["repo"], "api")
        self.stack(stacking.STACKED)

        def notes(card_id):
            return [e["text"] for e in self.board.events(card_id) if e["kind"] == "note"]
        before = (len(notes(self.both)), len(notes(self.child)))
        self.board.set_fields(self.parent, {"repo": "api,web"}, "human")
        self.assertEqual(notes(self.both)[-1], f"{self.parent}'s repos changed: this card is stacked on "
                                               f"{self.parent} in every repo it names (api,web)")
        self.assertEqual((len(notes(self.both)), len(notes(self.child))), (before[0] + 1, before[1]))
        self.board.set_fields(self.parent, {"repo": "api"}, "human")
        self.assertIn(f"{self.parent}'s repos changed: this card is stacked on {self.parent} in api; in web",
                      notes(self.both)[-1])

    def test_a_card_in_its_parents_repos_alone_has_one_base_everywhere(self):
        self.board.set_fields(self.parent, {"repo": "api,web"}, "human")
        self.stack(stacking.STACKED, card=self.both)
        card, (api, web) = self.board.get(self.both), self.trees()
        self.assertEqual([stacking.base_of(card, "api"), stacking.base_of(card, "web"), stacking.base_of(card),
                          shipping.base_of(card), shipping.repo_base(self.cfg, card, "web", PARENT_BRANCH),
                          shipping.tree_base(self.cfg, card, self.dir, PARENT_BRANCH),
                          plangate.claim_base(self.cfg, card, web)], [PARENT_BRANCH] * 7)
        self.assertEqual((fixcheck.own_bases(self.cfg, card, [api, web, self.dir]),
                          house.stack_apart(self.cfg, card, PARENT_BRANCH), stacking.other_base(card)),
                         ({}, "", ""))

    def test_a_text_with_one_base_says_another_repo_may_differ(self):
        self.stack(stacking.STACKED, card=self.both)
        item = {"kind": "rebase", "handle": "rebase", "base": PARENT_BRANCH}
        said = shipround.batch_prompt(self.cfg, self.board.get(self.both), [item], "now", 1)
        self.assertIn(stacking.OTHER_BASE, said)
        self.stack(stacking.STACKED)
        self.assertNotIn(stacking.OTHER_BASE, shipround.batch_prompt(self.cfg, self.board.get(self.child),
                                                                     [item], "now", 1))

    def test_a_card_whose_first_repo_is_not_the_parents_is_taken_against_its_own_base(self):
        first = self.board.create("work", "web first", repo="web,api", after=self.parent,
                                  options={"base": "release"}, actor="human")
        self.stack(stacking.STACKED, card=first)
        card = self.board.get(first)
        self.assertEqual((stacking.base_of(card), house.target_of(self.cfg, card), shipping.base_of(card)),
                         (None, "release", "release"))
        self.assertEqual(stacking.base_of(card, "api"), PARENT_BRANCH)


GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@x"]


def sh(*args):
    return subprocess.run([*GIT[:1], *GIT[1:], *args[1:]] if args[0] == "git" else list(args),
                          check=True, capture_output=True, text=True).stdout.strip()


def commit(tree: Path, name: str, message: str) -> None:
    (tree / name).write_text(message + "\n")
    sh("git", "-C", str(tree), "add", name)
    sh("git", "-C", str(tree), "commit", "-qm", message)


PLAN = """---
kind: plan
card: {parent}
title: the parent
---
# {parent} the parent

## Decisions

```batch stack
q: Stack each one on the card it waits for, or keep it independent?
choices: stacked, independent
{rows}
```
"""
CARD_ROWS = """{child}: the child | stacked | shares the parser this card adds
{other}: another | independent | touches nothing here
c-999: a card that is not waiting | stacked | a typo"""
SLICE_ROWS = """s1: Export stories as CSV (after Parse every story shape) | stacked | uses the new parser
s2: Tidy   the copy (after Parse every story shape) | independent | touches nothing here
{child}: the child | stacked | shares the parser"""


class ApproveTest(StackCase):
    def setUp(self):
        super().setUp()
        self.other = self.board.create("work", "another", repo="api", after=self.parent)

    def record(self, rows):
        doc = planformat.parse(PLAN.format(parent=self.parent, rows=rows.format(child=self.child, other=self.other)),
                               "plan.md")
        return stacking.record(self.board, self.parent, doc, planstate.state_of(self.board.events(self.parent)))

    def notes(self):
        return [e["text"] for e in self.board.events(self.parent) if e["kind"] == "note"]

    def test_approve_records_each_waiting_card_and_a_card_shaped_id_is_never_a_slice(self):   # r2.F8
        self.board.mark(self.parent, {"what": "answer", "block": "stack", "row": self.other,
                                      "choice": stacking.STACKED}, "human")
        self.record(CARD_ROWS)
        self.assertEqual([self.board.get(c)["options"].get(stacking.OPTION) for c in (self.child, self.other)],
                         ["stacked", "stacked"])
        self.assertNotIn(stacking.SPLIT_OPTION, self.board.get(self.parent)["options"])
        self.assertTrue(any("c-999: it does not wait for" in note for note in self.notes()), self.notes())
        writers = {e["actor"] for e in self.board.events(self.child) if e["kind"] == "set"}
        self.assertEqual(writers, {"human"})

    def test_slices_are_kept_with_the_slice_each_stacks_on(self):     # r2.F1, r2.F5
        self.record(SLICE_ROWS)
        self.assertEqual(self.board.get(self.parent)["options"][stacking.SPLIT_OPTION], {
            "Export stories as CSV": {"choice": "stacked", "on": "Parse every story shape"},
            "Tidy the copy": {"choice": "independent", "on": "Parse every story shape"}})
        self.assertIsNone(self.board.get(self.child)["options"].get(stacking.OPTION))
        self.assertTrue(any(f"{self.child}: this plan splits" in note for note in self.notes()), self.notes())

    def test_an_owners_earlier_choice_stands_unless_flipped(self):     # r1.F13
        self.stack(stacking.INDEPENDENT)
        self.record(CARD_ROWS)
        self.assertEqual(self.board.get(self.child)["options"][stacking.OPTION], "independent")
        self.board.mark(self.parent, {"what": "answer", "block": "stack", "row": self.child,
                                      "choice": stacking.STACKED}, "human")
        self.record(CARD_ROWS)
        self.assertEqual(self.board.get(self.child)["options"][stacking.OPTION], "stacked")

    def test_a_house_cannot_write_the_slices_answers(self):
        with self.assertRaises(Refused):
            self.board.set_fields(self.parent, {"options": {stacking.SPLIT_OPTION: {"x": "stacked"}}}, "house")


class SplitTest(StackCase):
    """c-718's addition: each slice has its answer from the start. r1.F9: checked per slice."""

    def setUp(self):
        super().setUp()
        self.big = self.board.create("work", "the big one", repo="api")

    def slices(self, ids):
        return {self.board.get(one)["title"]: self.board.get(one)["options"].get(stacking.OPTION) for one in ids}

    def approve(self, answers):
        self.board.set_fields(self.big, {"options": {stacking.SPLIT_OPTION: answers}}, "human")

    def split_note(self):
        return [e["text"] for e in self.board.events(self.big) if e["kind"] == "note"][-1]

    def test_the_owners_answer_on_each_slice(self):
        ids = self.board.split(self.big, [
            {"title": "parser", "brief": "b"},
            {"title": "export", "brief": "b", "after": ["parser"], "options": {stacking.OPTION: "stacked"}},
            {"title": "copy", "brief": "b", "after": ["parser"], "options": {stacking.OPTION: "independent"}}],
            "human")
        self.assertEqual(self.slices(ids), {"parser": None, "export": "stacked", "copy": "independent"})
        self.assertEqual(self.board.get(ids[1])["derived"]["stack"]["on"], ids[0])

    def test_a_slice_states_its_repos_and_its_stack_together(self):
        """c-771: stated repos and a stack answer on one slice, by the owner's split and by a
        house's after the approve; the repos are then the owner's to change, as on any card
        that carries a choice."""
        for actor, options in (("human", {stacking.OPTION: "stacked"}), ("house", None)):
            with self.subTest(actor=actor):
                big = self.board.create("work", "big", repo="api,web")
                self.board.set_fields(big, {"options": {stacking.SPLIT_OPTION: {
                    "export": {"choice": "stacked", "on": "parser"}}}}, "human")
                first, second = self.board.split(big, [
                    {"title": "parser", "brief": "b", "repo": "api"},
                    dict({"title": "export", "brief": "b", "after": ["parser"], "repo": "api"},
                         **({"options": options} if options else {}))], actor)
                card = self.board.get(second)
                self.assertEqual((card["repo"], card["options"][stacking.OPTION],
                                  card["options"]["provenance"]["repo"]), ("api", "stacked", "stated"))
                with self.assertRaisesRegex(Refused, "its repo is the owner's to change, not house's"):
                    self.board.set_fields(second, {"repo": "api,web"}, "house")

    def test_a_slice_stacked_on_one_with_fewer_repos_is_stacked_there_and_says_which(self):
        """c-772: one repo in common is enough. The slice is stacked where the slice it waits
        for works and cut from its own base elsewhere, said in the split's note, in the
        slice's own and under its `kb split` readback, for the owner's answer and the approved one."""
        for actor, options in (("human", {stacking.OPTION: "stacked"}), ("house", None)):
            with self.subTest(actor=actor):
                big = self.board.create("work", "big", repo="api,web")
                self.board.set_fields(big, {"options": {stacking.SPLIT_OPTION: {
                    "export": {"choice": "stacked", "on": "parser"}}}}, "human")
                first, second = self.board.split(big, [
                    {"title": "parser", "brief": "b", "repo": "api"},
                    dict({"title": "export", "brief": "b", "after": ["parser"]},
                         **({"options": options} if options else {}))], actor)
                card = self.board.get(second)
                self.assertEqual((card["repo"], card["options"][stacking.OPTION], card["derived"]["stack"]["repos"]),
                                 ("api,web", "stacked", ["api"]))
                which = f"stacked on {first} in api; in web, which {first} does not work in"
                (split,) = [e["text"] for e in self.board.events(big)
                            if e["kind"] == "note" and e["text"].startswith("stacking at the split")]
                self.assertIn(f"'export' {which}", split)
                self.assertEqual([e["text"].startswith(f"this card is {which}")
                                  for e in self.board.events(second) if e["kind"] == "note"], [True])
                self.assertIn(f"{second} is {which}", cli.split_aside(None, [card]))
                self.assertIsNone(cli.split_aside(None, [self.board.get(first)]))

    def test_a_slice_sharing_no_repo_with_the_one_it_stacks_on_is_refused_or_left_and_said(self):
        """c-771, c-772: a stacked slice needs a repo the slice it is stacked on has a branch
        in. The owner's answer refuses the split; the approved one is left off and said."""
        self.board.set_fields(self.big, {"repo": "api,web"}, "human")
        pieces = [{"title": "parser", "brief": "b", "repo": "api"},
                  {"title": "export", "brief": "b", "after": ["parser"], "repo": "web"}]
        with self.assertRaisesRegex(Refused, "slice 'export': c-\\d+ works in api, not in web"):
            self.board.split(self.big, [pieces[0], dict(pieces[1], options={stacking.OPTION: "stacked"})],
                             "human")
        self.assertEqual(self.board.children(self.big), [])
        self.approve({"export": {"choice": "stacked", "on": "parser"}})
        ids = self.board.split(self.big, pieces, "house")
        self.assertEqual(self.slices(ids), {"parser": None, "export": None})
        self.assertRegex(self.split_note(), "'export' left without a choice: c-\\d+ works in api, not in web")

    def test_a_slice_answer_that_cannot_stand_refuses_the_split(self):     # r1.F9
        for options, after in (({stacking.OPTION: "sideways"}, ["parser"]),
                               ({stacking.OPTION: "stacked"}, ["parser", "other"])):
            with self.subTest(options=options), self.assertRaises(Refused):
                self.board.split(self.big, [{"title": "parser", "brief": "b"}, {"title": "other", "brief": "b"},
                                            {"title": "x", "brief": "b", "after": after, "options": options}], "human")
        with self.assertRaises(Refused):
            self.board.split(self.big, [{"title": "parser", "brief": "b"},
                                        {"title": "x", "brief": "b", "after": ["parser"],
                                         "options": {stacking.OPTION: "stacked"}}], "house")

    def test_the_answers_approved_at_the_plan_gate_reach_the_houses_split(self):
        self.approve({"export": {"choice": "stacked", "on": "parser"},
                      "copy": {"choice": "independent", "on": "parser"}})
        ids = self.board.split(self.big, [
            {"title": "parser", "brief": "b"},
            {"title": " export ", "brief": "b", "after": ["parser"]},       # spaces compare as one
            {"title": "copy", "brief": "b", "after": ["parser"]}], "house")
        self.assertEqual(self.slices(ids), {"parser": None, " export ": "stacked", "copy": "independent"})
        self.assertNotIn(stacking.SPLIT_OPTION, self.board.get(ids[1])["options"])

    def test_a_renamed_slice_or_another_after_takes_no_answer_and_says_so(self):     # r2.F1
        self.approve({"export": {"choice": "stacked", "on": "parser"},
                      "import": {"choice": "stacked", "on": "parser"}})
        ids = self.board.split(self.big, [
            {"title": "parser", "brief": "b"}, {"title": "other", "brief": "b"},
            {"title": "export", "brief": "b", "after": ["other"]},          # the house's own after
            {"title": "import stories", "brief": "b", "after": ["parser"]}], "house")
        self.assertEqual(set(self.slices(ids).values()), {None})
        note = self.split_note()
        self.assertIn("'export' was approved stacked on 'parser', and the split has it after 'other'", note)
        self.assertIn("approved but matched no slice: 'import'", note)

    def test_a_card_stacked_on_the_card_being_split_is_blocked_once(self):     # r2.F5
        waiter = self.board.create("work", "waits for the big one", repo="api", after=self.big)
        self.board.set_fields(self.big, {"options": {"branch": "feature/big"}}, "cli")
        self.stack(stacking.STACKED, card=waiter)
        self.board.split(self.big, [{"title": "parser", "brief": "b"}], "house")
        reason = self.board.get(waiter)["blocked_reason"]
        self.assertIn(f"{self.big}, the card this one is stacked on, was split into slices", reason)
        self.assertIn(waiter, self.split_note())
        self.assertFalse(self.board.get(waiter)["derived"]["stack"]["pushed"])

    def test_the_block_at_the_split_is_a_block_and_a_blocked_one_is_named(self):     # fix check
        shipping, held = (self.board.create("work", title, repo="api", after=self.big) for title in ("ships", "held"))
        self.board.set_fields(self.big, {"options": {"branch": "feature/big"}}, "cli")
        for card in (shipping, held):
            self.stack(stacking.STACKED, card=card)
        options = dict(self.board.get(shipping)["options"], reoffer={"by": "human", "at": "2026-10-08T12:00:00+00:00"})
        self.board.conn.execute("UPDATE cards SET stage = 'shipping', options = ? WHERE id = ?",
                                (json.dumps(options), shipping))
        self.board.block(held, "waiting on a colleague", "human")
        self.board.split(self.big, [{"title": "parser", "brief": "b"}], "house")
        self.assertNotIn("reoffer", self.board.get(shipping)["options"])     # as `block` drops it
        self.assertEqual(self.board.get(held)["blocked_reason"], "waiting on a colleague")
        note = self.split_note()
        self.assertIn(f"blocked, as they were stacked on this card: {shipping}", note)
        self.assertIn(f"already blocked for another reason, so not blocked again (they need a new parent too): {held}", note)


class SyncTest(StackCase):
    def test_the_sync_records_a_stacked_cards_pull_requests_and_asks_for_the_repo(self):     # r2.F2
        from keel import shipsync
        self.board.set_fields(self.parent, {"options": {"branch": PARENT_BRANCH, "pr": 41}}, "cli")
        self.stack(stacking.STACKED)
        self.board.conn.execute("UPDATE cards SET stage = 'review', plan_ref = 'p', output_ref = 'o' WHERE id = ?",
                                (self.child,))
        prs = [{"repo": "api", "pr": 50, "branch": "feature/child", "draft": False},
               {"repo": "web", "pr": 7, "branch": "feature/child", "draft": False}]
        shipsync.settle(self.board, self.board.get(self.child), prs, dry_run=False)
        card = self.board.get(self.child)
        self.assertEqual((card["stage"], card["repo"], card["options"]["pr"]), ("shipping", "api", 50))
        self.assertEqual(set(card["options"]["prs"]), {"api", "web"})
        notes = [e["text"] for e in self.board.events(self.child) if e["kind"] == "note"]
        self.assertTrue(any("repo=api,web" in note for note in notes), notes)


class BaseCheckTest(unittest.TestCase):
    def test_a_slice_line_carries_the_owners_answer(self):
        from keel import actions, cli
        argv = actions.split_argv({"id": "c-1", "slices": [{"title": "a", "brief": "b"},
                                                           {"title": "c", "brief": "d", "after": "a",
                                                            "stack": "independent"}]})
        self.assertEqual(argv[-1], "c|d|a|stack=independent")
        self.assertEqual(cli.parse_slice(argv[-1]),
                         {"title": "c", "brief": "d", "after": ["a"], "options": {"stack": "independent"}})

    def test_a_part_that_would_be_read_as_another_is_refused_by_the_server(self):     # c-772 review
        from keel import actions
        good = {"title": "a", "brief": "b", "after": ["x"], "repo": ["api"]}
        for bad in ({"title": "a|stack=independent"}, {"brief": "b|c"}, {"after": ["x|repo=web"]},
                    {"repo": ["api|stack=independent"]}, {"repo": ["api,web"]}, {"repo": ["repo=api"]}):
            with self.subTest(bad=bad), self.assertRaises(actions.ActionError):
                actions.split_argv({"id": "c-1", "slices": [dict(good, **bad)]})
        self.assertEqual(actions.split_argv({"id": "c-1", "slices": [good]})[-1], "a|b|x|repo=api")
        for bad in ({"title": None}, {"brief": None}, {"after": [None]}, {"repo": [7]}):     # never "None"
            with self.subTest(bad=bad), self.assertRaisesRegex(actions.ActionError, "is text"):
                actions.split_argv({"id": "c-1", "slices": [dict(good, **bad)]})

    def test_a_slice_line_carries_its_repos(self):       # c-771
        from keel import actions, cli
        argv = actions.split_argv({"id": "c-1", "slices": [
            {"title": "a", "brief": "b", "repo": ["api", "web"]},
            {"title": "c", "brief": "d", "after": "a", "repo": "api", "stack": "stacked"},
            {"title": "e", "brief": "f", "repo": []}]})
        self.assertEqual(argv[3::2], ["a|b|repo=api,web", "c|d|a|repo=api|stack=stacked", "e|f"])
        self.assertEqual(cli.parse_slice(argv[5], ["a"]),
                         {"title": "c", "brief": "d", "after": ["a"], "repo": "api",
                          "options": {"stack": "stacked"}})


def stacking_pack(directory: Path) -> Path:
    """A pack that says it stacks, with the two executables the claim needs."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pack.toml").write_text('name = "work"\nversion = "1"\ndescription = "a pack"\n'
                                         '[adapter]\nspaces = ["work"]\n[capabilities]\nstacks = true\n')
    for verb in ("worktree", "ship"):
        (directory / verb).write_text("#!/bin/sh\nexit 1\n")
        (directory / verb).chmod(0o755)
    return directory


class KbApproveTest(KbCase):
    def setUp(self):
        super().setUp()
        stacking_pack(self.dir / "adapters" / "work")
        code, self.parent, err = self.kb("create", "--space", "work", "--title", "p", "--repo", "api",
                                         "--autonomy", "attended")
        self.assertEqual(code, 0, err)
        code, self.child, err = self.kb("create", "--space", "work", "--title", "c", "--repo", "api",
                                        "--after", self.parent)
        self.assertEqual(code, 0, err)
        self.plan = self.dir / "plans" / "plan.md"
        self.kb("stage", self.parent, "assigned", env={"KEEL_TOKEN": self.token})
        code, _, err = self.kb("stage", self.parent, "planning", "--plan", str(self.plan))
        self.assertEqual(code, 0, err)
        self.plan.parent.mkdir(parents=True, exist_ok=True)
        self.plan.write_text(PLAN.format(parent=self.parent, rows=CARD_ROWS.format(child=self.child, other="c-998")))

    def test_the_owners_approve_plan_records_the_stacking_and_a_house_cannot(self):
        code, _, err = self.kb("set", self.child, "options.stack=stacked", env={"KEEL_CARD": self.child})
        self.assertEqual(code, 1)
        self.assertIn("owner", err)
        code, _, err = self.kb("approve", self.parent, "plan", env={"KEEL_TOKEN": self.token})
        self.assertEqual(code, 0, err)
        self.assertEqual(self.kb_json("show", self.child)["options"].get("stack"), "stacked")

    def test_a_failure_while_recording_is_a_note_and_the_approve_stands(self):     # r1.F13
        with mock.patch.object(stacking, "record", side_effect=RuntimeError("the plan went away")):
            code, _, err = self.kb("approve", self.parent, "plan", env={"KEEL_TOKEN": self.token})
        self.assertEqual(code, 0, err)
        shown = self.kb_json("show", self.parent, "--events", "20")
        self.assertEqual(shown["stage"], "building")
        self.assertTrue(any("stacking not recorded" in (e.get("text") or "") for e in shown["events"]))


class BriefTest(unittest.TestCase):
    def test_only_a_stacking_space_is_asked_and_the_waiting_cards_are_named(self):    # r1.F14, r1.F15
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(Path(tmp))
            self.assertEqual(cfg.stacking, frozenset())
            cfg.spaces["work"].adapter_dir = stacking_pack(Path(tmp) / "adapters" / "work")
            self.assertEqual(cfg.stacking, frozenset({"work"}))
        self.assertNotIn("batch stack", planbrief.plan_block(True))
        alone = planbrief.plan_block(True, stacks=True, change="pull request")
        self.assertIn("ONLY IF your plan splits this card", alone)
        self.assertIn("`|repo=<key[,key]>`", alone)                       # c-771
        self.assertIn("Only if you split, show the breakdown", alone)      # r2.F9: conditional
        self.assertNotIn("      ```batch stack", alone)                    # r2.F9: no placeholder rows
        self.assertNotIn("wait for this one", alone)
        waiting = planbrief.plan_block(True, stacks=True, change="pull request",
                                       waiting=[{"id": "c-801", "title": "Export stories"}])
        self.assertIn("c-801 (Export stories)", waiting)
        self.assertIn("c-801: Export stories |", waiting)


if __name__ == "__main__":
    unittest.main()
