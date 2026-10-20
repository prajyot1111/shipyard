"""c-718: a stacked card at shipping whose parent was squash-merged, seen and said with the
by-hand way, through the existing out-of-step machinery (`keel/shipstep.py`).

A real repository stands in for the code host: the card's worktree is on its pull request's
branch, cut from its parent's branch (`feature/parent`, the two commits `remote` pushes),
with one commit of its own on top. The parent is then merged into `main` by a colleague,
squashed or with a merge commit. Keel moves no branch: it says what is so and gives the
commands (a backup branch, the replay of only the card's own commits onto the base, a push
with a lease), which the test runs as the user would.
"""

import json
from pathlib import Path
from unittest import mock

from keel import fixcheck, shipping, stacking
from keel.review import prep, stamp as review_stamp
from tests.test_shipstep import BRANCH, RewrittenCase, remote, run, write

PARENT = "feature/parent"


def merge_parent(at, squash: bool) -> None:
    """A colleague merges the parent's branch into `main`, squashed or with a merge commit."""
    other = at.other
    run("git", "fetch", "-q", "origin", cwd=other)
    run("git", "checkout", "-q", "main", cwd=other)
    run("git", "reset", "-q", "--hard", "origin/main", cwd=other)
    if squash:
        run("git", "merge", "-q", "--squash", f"origin/{PARENT}", cwd=other)
        run("git", "commit", "-qm", "the parent, squashed", cwd=other)
    else:
        run("git", "merge", "-q", "--no-ff", "-m", "merge the parent", f"origin/{PARENT}", cwd=other)
    run("git", "push", "-q", "origin", "main", cwd=other)
    run("git", "fetch", "-q", "origin", cwd=at.tree)


class SquashedParentTest(RewrittenCase):
    def setUp(self):
        super().setUp()
        self.parent_head = self.head()
        run("git", "push", "-q", "origin", f"HEAD:refs/heads/{PARENT}", cwd=self.tree)
        self.own = write(self.tree, "c.txt", "the child's\n", "the child's own")
        run("git", "push", "-q", "origin", "HEAD", cwd=self.tree)
        parent = self.board.create("work", "the parent", repo="api", actor="human",
                                   options={"branch": PARENT, "pr": 41})
        self.board.conn.execute("UPDATE cards SET stage = 'done', options = ? WHERE id = ?",
                                (json.dumps({"branch": PARENT, "pr": 41, "shipping": {"heads": {"api": self.parent_head}}}),
                                 parent))
        options = dict(self.board.get(self.card)["options"], stack=stacking.STACKED)
        self.board.conn.execute("UPDATE cards SET \"after\" = ?, options = ? WHERE id = ?",
                                (parent, json.dumps(options), self.card))
        self.parent = parent

    def merge_parent(self, squash: bool) -> None:
        merge_parent(self.api, squash)

    def test_a_squashed_parent_gives_the_replay_and_the_lease_push_by_hand(self):
        self.merge_parent(squash=True)
        facts = self.facts()
        self.assertTrue(facts.get("restack"), facts)
        self.assertIn(f"{self.parent}, which this card was stacked on, was squash-merged into main", facts["said"])
        (entry,) = facts["by_hand"]
        self.assertIn("git rebase --onto origin/main", entry["command"])
        self.assertIn("--force-with-lease=", entry["command"])
        self.typed(facts["by_hand"])
        theirs = run("git", "log", "--format=%s", f"origin/main..origin/{self.branch()}", cwd=self.tree)
        self.assertEqual(theirs, "the child's own")
        self.assertIn("keel/backup/", self.branches())
        self.assertFalse(self.facts().get("restack"))

    def test_moved_merged_in_then_squashed_still_gives_the_replay(self):     # r1.F6
        other = self.api.other
        run("git", "fetch", "-q", "origin", cwd=other)
        run("git", "checkout", "-qB", PARENT, f"origin/{PARENT}", cwd=other)
        moved = write(other, "fix.txt", "the review fix\n", "the parent's review fix")
        run("git", "push", "-q", "origin", PARENT, cwd=other)
        run("git", "fetch", "-q", "origin", cwd=self.tree)
        run("git", "merge", "-q", "--no-ff", "-m", "bring the parent in", f"origin/{PARENT}", cwd=self.tree)
        run("git", "push", "-q", "origin", "HEAD", cwd=self.tree)
        options = json.loads(self.board.conn.execute("SELECT options FROM cards WHERE id = ?",
                                                     (self.parent,)).fetchone()[0])
        options["shipping"]["heads"]["api"] = moved
        self.board.conn.execute("UPDATE cards SET options = ? WHERE id = ?", (json.dumps(options), self.parent))
        self.merge_parent(squash=True)
        facts = self.facts()
        (entry,) = facts["by_hand"]
        self.assertIn("command", entry, entry)
        self.typed(facts["by_hand"])
        theirs = run("git", "log", "--format=%s", f"origin/main..origin/{self.branch()}", cwd=self.tree)
        self.assertEqual(theirs, "the child's own")

    def test_a_parent_head_this_clone_lacks_is_said_with_the_fetch(self):     # r2.F4
        gone = "f" * 40
        options = json.loads(self.board.conn.execute("SELECT options FROM cards WHERE id = ?",
                                                     (self.parent,)).fetchone()[0])
        options["shipping"]["heads"]["api"] = gone
        self.board.conn.execute("UPDATE cards SET options = ? WHERE id = ?", (json.dumps(options), self.parent))
        self.merge_parent(squash=True)
        facts = self.facts()
        self.assertTrue(facts.get("restack"), facts)
        self.assertIn(f"last pushed head {gone[:10]} is not in this clone", facts["said"])
        self.assertIn(f"fetch origin {gone}", facts["said"])
        self.assertFalse(any(entry.get("command") for entry in facts["by_hand"]))

    def test_a_merge_commit_needs_nothing(self):
        self.merge_parent(squash=False)
        self.assertFalse(self.facts().get("restack"))

    def test_the_drain_says_it_once(self):
        self.merge_parent(squash=True)
        self.drain_reads()
        self.drain_reads()
        said = [note for note in self.notes() if "was squash-merged" in note]
        self.assertEqual(len(said), 1, self.notes())

    def branch(self) -> str:
        return run("git", "symbolic-ref", "--short", "HEAD", cwd=self.tree)


class PerRepoTest(RewrittenCase):
    """c-772: the card works in api and web and is stacked on a card that works in api alone.
    Two real repositories: in api its branch is cut from the parent's (`feature/parent`), in
    web from `main`. NEITHER card names an `options.base`: the first repo's base is the pull
    request's own destination, as the record keeps it, and the other repo's is the one rule's
    (`merging.base_in`), here the branch the user's checkout of that repo has out."""

    def arrange(self, order: str) -> dict:
        self.web = remote(self.dir, "web")
        self.trees = {"api": self.tree, "web": self.web.tree}
        self.parent_head = self.head()
        run("git", "push", "-q", "origin", f"HEAD:refs/heads/{PARENT}", cwd=self.tree)
        write(self.tree, "c.txt", "the child's\n", "the child's own")
        run("git", "push", "-q", "origin", "HEAD", cwd=self.tree)
        for at in (self.api, self.web):        # the user's own checkout of each repo, on `main`
            run("git", "fetch", "-q", "origin", cwd=at.other)
            run("git", "checkout", "-qB", "main", "origin/main", cwd=at.other)
        self.cfg.spaces["work"].repos.update(api=self.api.other, web=self.web.other)
        self.parent = self.board.create("work", "the parent", repo="api", actor="human",
                                        options={"branch": PARENT, "pr": 41})
        self.board.conn.execute("UPDATE cards SET options = ? WHERE id = ?", (json.dumps(
            {"branch": PARENT, "pr": 41, "shipping": {"heads": {"api": self.parent_head}}}), self.parent))
        first, second = order.split(",")
        options = {key: value for key, value in self.board.get(self.card)["options"].items() if key != "base"}
        options.update(stack=stacking.STACKED, worktree=str(self.trees[first]),
                       worktrees={second: str(self.trees[second])},
                       prs={"api": {"pr": 4150, "branch": BRANCH}, "web": {"pr": 4151, "branch": BRANCH}},
                       shipping=dict(options["shipping"], base="main"))
        self.board.conn.execute("UPDATE cards SET repo = ?, \"after\" = ?, options = ? WHERE id = ?",
                                (order, self.parent, json.dumps(options), self.card))
        card = self.board.get(self.card)
        self.assertNotIn("base", card["options"])
        self.assertEqual(stacking.split_repos(card), (["api"], ["web"]))
        return card

    def land(self, squash: bool = True) -> None:
        merge_parent(self.api, squash)
        self.board.conn.execute("UPDATE cards SET stage = 'done' WHERE id = ?", (self.parent,))

    def web_main_conflicts(self) -> None:
        """A colleague's change on web's `main` that the card's web branch conflicts with."""
        other = self.web.other
        run("git", "checkout", "-q", "main", cwd=other)
        write(other, "a.txt", "theirs\n", "a colleague's a.txt")
        run("git", "push", "-q", "origin", "main", cwd=other)
        run("git", "fetch", "-q", "origin", cwd=self.web.tree)

    def each_worktree_against_its_own_base(self, order: str) -> None:
        card = self.arrange(order)
        self.assertEqual([shipping.tree_base(self.cfg, card, self.trees[key], shipping.base_of(card))
                          for key in ("api", "web")], [PARENT, "main"])
        facts = self.facts()
        self.assertEqual((facts["conflicts"], facts.get("restack")), (False, None))
        self.web_main_conflicts()            # the parent's branch is no ref in web at all
        self.assertTrue(self.facts()["conflicts"])

    def test_each_worktree_is_read_against_its_own_repos_base(self):
        self.each_worktree_against_its_own_base("api,web")

    def test_each_worktree_is_read_against_its_own_repos_base_web_first(self):
        self.each_worktree_against_its_own_base("web,api")

    def squashed(self, order: str) -> None:
        self.arrange(order)
        self.land()
        facts = self.facts()
        self.assertTrue(facts.get("restack"), facts)
        self.assertEqual([entry["repo"] for entry in facts["by_hand"]], ["api"])
        self.assertIn(f"{self.parent}, which this card was stacked on, was squash-merged into main", facts["said"])
        self.typed(facts["by_hand"])
        own = run("git", "log", "--format=%s", f"origin/main..origin/{BRANCH}", cwd=self.tree)
        self.assertEqual(own, "the child's own")
        self.assertFalse(self.facts().get("restack"))
        self.web_main_conflicts()            # and web is still read against its own base
        self.assertTrue(self.facts()["conflicts"])

    def test_a_squashed_parent_gives_the_replay_in_the_stacked_repo_alone(self):
        self.squashed("api,web")

    def test_a_squashed_parent_gives_the_replay_in_the_stacked_repo_alone_web_first(self):
        self.squashed("web,api")

    def test_a_merge_commit_needs_nothing_in_either_repo(self):
        self.arrange("web,api")
        self.land(squash=False)
        self.assertFalse(self.facts().get("restack"))

    def checked(self, order: str) -> None:
        card = self.arrange(order)
        said = fixcheck.run(self.cfg, card, self.trees[order.split(",")[0]])
        self.assertIn("FULL PASS", said)
        card_dir = self.cfg.card_dir(self.card)
        seen = json.loads((card_dir / review_stamp.PREP_FILE).read_text())["worktrees"]
        self.assertEqual({Path(one["path"]).name: one["base"] for one in seen},
                         {"api-tree": PARENT, "web-tree": "main"})
        diff = (card_dir / prep.DIFF_FILE).read_text()
        self.assertIn("c.txt", diff)
        self.assertNotIn("a/a.txt", diff.split("web-tree")[0] if order == "api,web" else diff.split("api-tree")[1])

    def test_keel_check_prepares_each_worktree_against_its_own_base_with_no_stamp(self):
        self.checked("api,web")

    def test_keel_check_prepares_each_worktree_against_its_own_base_web_first(self):
        self.checked("web,api")

    def test_keel_check_runs_from_a_directory_inside_a_worktree(self):
        """A house often runs it from a subdirectory: that is its worktree, not a stray one."""
        card = self.arrange("api,web")
        for tree in (self.tree, self.web.tree):
            inside = tree / "src" / "deep"
            inside.mkdir(parents=True, exist_ok=True)
            with self.subTest(tree=tree.name):
                self.assertIn("FULL PASS", fixcheck.run(self.cfg, card, inside))
        seen = json.loads((self.cfg.card_dir(self.card) / review_stamp.PREP_FILE).read_text())["worktrees"]
        self.assertEqual({Path(one["root"]).name: one["base"] for one in seen},
                         {"api-tree": PARENT, "web-tree": "main"})

    def test_an_already_checked_card_is_told_so_before_any_base_is_asked(self):
        card = self.arrange("api,web")
        del self.cfg.spaces["work"].repos["web"]            # a base that cannot be read now
        with mock.patch.object(fixcheck, "plan", return_value=("checked", "")):
            self.assertIn("nothing to run", fixcheck.run(self.cfg, card, self.tree))

    def test_keel_check_refuses_when_the_other_repos_base_cannot_be_read(self):
        card = self.arrange("api,web")
        del self.cfg.spaces["work"].repos["web"]
        with self.assertRaisesRegex(fixcheck.NoBase, "cannot read a base for web"):
            fixcheck.run(self.cfg, card, self.tree)


del RewrittenCase      # imported for its fixture only: its own tests run in their own module

if __name__ == "__main__":
    import unittest
    unittest.main()
