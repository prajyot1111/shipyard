"""c-653: a pull request's branch rewritten outside Keel, seen and said, with the by-hand way.

Five cards hit it on 2026-10-05: the remote branch was force-pushed (its commits replayed
onto another base) while the card's worktree kept the old history, the deck offered a Ship
that could only fail and counted 223 commits as waiting, and a house committed on top
unaware. A real repository stands in for the code host here: `origin.git` is the remote,
`tree` the card's worktree on its pull request's branch, `other` the colleague who rewrites
that branch. A second repository (`web`) stands in for a cross-repo card's other worktree.
The board, the stand-in adapter and the harness are `ShippingCase`'s. Keel moves no branch
here (c-659 is the tool that would): it says what is so and gives him the commands, which
these tests run as he would.
"""

import json
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from keel import adapters, cli, deckstate, house, shipping, shipreoffer, shipround, shipstep, shipwatch
from keel.board import SHIPPING_OPTION, Refused
from tests.test_shipping import MON_10, ShippingCase, comment, sight

BRANCH = "feature/st-41001/tidy"
IDENTITY = (("user.email", "t@example.invalid"), ("user.name", "T"))


def run(*argv, cwd, check=True) -> str:
    return subprocess.run(argv, cwd=cwd, check=check, capture_output=True, text=True).stdout.strip()


def write(cwd: Path, name: str, text: str, message: str) -> str:
    (cwd / name).write_text(text)
    run("git", "add", name, cwd=cwd)
    run("git", "commit", "-qm", message, cwd=cwd)
    return run("git", "rev-parse", "HEAD", cwd=cwd)


def remote(root: Path, name: str) -> SimpleNamespace:
    """A bare origin, the card's worktree on its pull request's branch with two commits
    pushed, and a colleague's clone."""
    at = SimpleNamespace(origin=root / f"{name}-origin.git", tree=root / f"{name}-tree", other=root / f"{name}-other")
    run("git", "init", "-q", "--bare", "-b", "main", str(at.origin), cwd=root)
    for clone in (at.tree, at.other):
        run("git", "clone", "-q", str(at.origin), str(clone), cwd=root)
        for key, value in IDENTITY:
            run("git", "config", key, value, cwd=clone)
    write(at.tree, "base.txt", "base\n", "base")
    run("git", "push", "-q", "origin", "HEAD:main", cwd=at.tree)
    run("git", "checkout", "-qb", BRANCH, cwd=at.tree)
    write(at.tree, "a.txt", "one\n", "the first")
    write(at.tree, "b.txt", "two\n", "the second")
    run("git", "push", "-qu", "origin", BRANCH, cwd=at.tree)
    return at


def rewrite(at: SimpleNamespace, fetch: bool = True) -> str:
    """The colleague replays the branch's two commits onto a moved base and force-pushes."""
    run("git", "fetch", "-q", "origin", cwd=at.other)
    run("git", "checkout", "-q", "main", cwd=at.other)
    again = run("git", "rev-list", "--count", "HEAD", cwd=at.other)
    write(at.other, "moved.txt", f"the base moved ({again})\n", "the base moved")
    run("git", "push", "-q", "origin", "main", cwd=at.other)
    run("git", "checkout", "-qB", BRANCH, f"origin/{BRANCH}", cwd=at.other)
    run("git", "rebase", "-q", "main", cwd=at.other)
    run("git", "push", "-qf", "origin", BRANCH, cwd=at.other)
    if fetch:
        run("git", "fetch", "-q", "origin", cwd=at.tree)
    return run("git", "rev-parse", "HEAD", cwd=at.other)


class RewrittenCase(ShippingCase):
    """The card's worktree is a real clone on its pull request's branch, two commits pushed."""

    def setUp(self):
        super().setUp()
        self.tree.rmdir()
        self.api = remote(self.dir, "api")
        self.tree = self.api.tree
        self.pushed = self.head()
        self.board.set_fields(self.card, {"options": {"worktree": str(self.tree), "base": "main"}}, "human")

    def write(self, name: str, text: str, message: str) -> str:
        return write(self.tree, name, text, message)

    def head(self, ref: str = "HEAD", tree: Path | None = None) -> str:
        return run("git", "rev-parse", ref, cwd=tree or self.tree)

    def rewrite(self, fetch: bool = True) -> str:
        return rewrite(self.api, fetch)

    def branches(self, tree: Path | None = None) -> str:
        return run("git", "branch", "--list", cwd=tree or self.tree)

    def record_heads(self, sha: str) -> None:
        self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: dict(self.shipped(), heads={"api": sha})}},
                              "drain")

    def facts(self) -> dict:
        return shipping.local_facts(self.cfg, self.board.get(self.card))

    def by_hand(self) -> list[dict]:
        return self.facts().get("by_hand") or []

    def typed(self, hand: list[dict], check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess:
        """He pastes the commands the card gave him into a shell. As a paste runs them: every
        line, whatever the one before it did (never `sh -e`), so each line must stop itself."""
        text = shipstep.commands_text(hand)
        self.assertTrue(text, hand)
        return subprocess.run(["sh", "-c", text], cwd=cwd or self.dir, check=check, capture_output=True, text=True)

    def refs(self, tree: Path | None = None) -> str:
        """Every ref of a clone and where HEAD is: what a paste must leave as it was."""
        tree = tree or self.tree
        return run("git", "for-each-ref", cwd=tree) + run("git", "rev-parse", "HEAD", cwd=tree)

    def colleague_pushes(self) -> str:
        """A colleague's commit on top of the pull request's branch: behind, never a rewrite."""
        run("git", "fetch", "-q", "origin", cwd=self.api.other)
        run("git", "checkout", "-qB", BRANCH, f"origin/{BRANCH}", cwd=self.api.other)
        theirs = write(self.api.other, "theirs.txt", "his\n", "a colleague's")
        run("git", "push", "-q", "origin", BRANCH, cwd=self.api.other)
        run("git", "fetch", "-q", "origin", cwd=self.tree)
        return theirs

    def drain_reads(self) -> dict:
        """The drain's read of the card's worktrees, as a pass makes it."""
        return shipping.keep_local(self.cfg, self.board, self.board.get(self.card), self.shipped())

    def notes(self) -> list[str]:
        return [e.get("text") or "" for e in self.board.events(self.card) if e["kind"] == "note"]

    def second(self, pull_request: bool = True) -> SimpleNamespace:
        """The card's other repo, `web`, with its own worktree (and pull request)."""
        web = remote(self.dir, "web")
        prs = {"api": {"pr": 4150, "branch": BRANCH}}
        if pull_request:
            prs["web"] = {"pr": 9, "branch": BRANCH}
        self.board.set_fields(self.card, {"repo": "api,web", "options": {
            "prs": prs, "worktrees": {"api": str(self.tree), "web": str(web.tree)}}}, "human")
        return web

    def a_kept_reply(self):
        self.told()
        self.verdict("c11", "not-valid", reply="The host pages at 40.")

    def ship(self, anyway: bool = False):
        return self.board.ship(self.card, "human", adapters.publisher(self.cfg, "work", anyway=anyway))


class DivergedTest(RewrittenCase):
    def test_a_rewritten_branch_is_diverged_and_none_of_it_is_work_to_ship(self):
        self.assertEqual(self.facts()["ahead"], 0)
        self.rewrite()
        self.write("c.txt", "three\n", "the house's own")
        facts = self.facts()
        self.assertEqual((facts["ahead"], facts["behind"]), (0, 3))
        self.assertEqual(facts["diverged"], {"ahead": 3, "behind": 3})
        self.assertFalse(facts["unchecked"], "nothing here is waiting to be shipped")

    def test_ship_refuses_a_diverged_push_with_the_reason_even_anyway(self):
        self.rewrite()
        self.write("c.txt", "three\n", "the house's own")
        for anyway in (False, True):
            with self.assertRaisesRegex(adapters.AdapterError, "diverged .*3 ahead, 3 behind"):
                self.ship(anyway)
        self.assertFalse(self.answers.exists(), "nothing was pushed or posted")

    def test_the_drain_says_it_once_and_the_batch_tells_the_house(self):
        self.rewrite()
        self.live()
        self.with_a_comment()
        self.assertEqual(self.shipped()["local"]["diverged"], {"ahead": 2, "behind": 3})
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10 + timedelta(minutes=5))
        self.assertEqual(len([n for n in self.notes() if "diverged" in n]), 1)
        self.assertIn("2 ahead of it and 3 behind", self.told_prompt())

    def test_the_note_the_refusal_and_the_record_say_one_sentence(self):
        """r1.F2: the deck draws `local.said` as given, so the three can never drift."""
        self.rewrite()
        self.with_a_comment()
        said = self.shipped()["local"]["said"]
        self.assertIn(said, self.notes())
        with self.assertRaises(adapters.AdapterError) as refused:
            self.ship()
        self.assertIn(said, str(refused.exception))

    # The clause as the release before c-699 wrote it, verbatim from origin/next's
    # keel/shipstep.py (`DIVERGED_NOTE`), and as it reads now (r2.F5).
    EARLIER_DIVERGED = "that branch was rewritten outside Keel, so nothing can be pushed until the worktree"
    NOW_DIVERGED = "that branch was rewritten outside Shipyard, so nothing can be pushed until the worktree"

    def test_a_sentence_just_said_under_the_engines_earlier_name_is_not_said_twice(self):
        """c-699 review, the class of F1 and F9: the out-of-step sentence is said once by
        comparing it with the card's newest one, which an earlier release may have written."""
        self.rewrite()
        card = self.board.get(self.card)
        facts = shipping.local_facts(self.cfg, card)
        self.assertIn(self.NOW_DIVERGED, facts["said"])
        earlier = facts["said"].replace(self.NOW_DIVERGED, self.EARLIER_DIVERGED)
        self.board.note(self.card, earlier, "drain", data={"local": shipping.kind_of(facts)})
        shipping.say_local(self.board, self.card, facts, {}, "drain")
        self.assertEqual([n for n in self.notes() if "diverged" in n], [earlier])

    def test_a_branch_that_was_behind_and_then_diverges_is_said_again(self):
        """r2.F9: the card's last word must not stay "replies can still be sent"."""
        self.colleague_pushes()
        self.drain_reads()
        self.write("c.txt", "three\n", "the house's own")
        self.drain_reads()
        self.drain_reads()
        said = [note for note in self.notes() if "behind" in note]
        self.assertEqual(len(said), 2, said)
        self.assertIn("diverged", said[-1])
        self.assertEqual(said[-1], self.shipped()["local"]["said"])

    def test_a_branch_only_behind_still_sends_what_needs_no_push(self):
        """r1.F8: a colleague's commit on the branch is not a rewrite, and hides no reply."""
        self.a_kept_reply()
        theirs = self.colleague_pushes()
        facts = self.facts()
        self.assertEqual((facts["ahead"], facts["behind"]), (0, 1))
        self.assertNotIn("diverged", facts)
        self.ship(anyway=True)
        self.assertEqual(len(self.answers.read_text().splitlines()), 1, "the kept reply went")
        self.typed(facts["by_hand"])
        self.assertEqual(self.head(), theirs, "and the commands it gives bring the branch up")
        self.assertNotIn("behind", {key for key, value in self.facts().items() if value})

    def test_a_worktree_no_pull_request_is_on_is_never_behind(self):
        """r1.F8: the card's other repo, cut from its base and never pushed, has its base as
        upstream; a base that moved must not refuse the Ship or be given commands."""
        web = self.second(pull_request=False)
        run("git", "checkout", "-q", "-b", "feature/local", "--track", "origin/main", cwd=web.tree)
        mine = write(web.tree, "w.txt", "w\n", "local work")
        rewrite(web)
        self.assertEqual(run("git", "rev-list", "--count", "HEAD..@{upstream}", cwd=web.tree), "1")
        facts = self.facts()
        self.assertEqual((facts["ahead"], facts["behind"]), (0, 0))
        self.assertNotIn("said", facts)
        self.assertNotIn("by_hand", facts)
        self.assertEqual(self.head(tree=web.tree), mine)


class ByHandTest(RewrittenCase):
    """In place of a tool that moves the branch: the exact commands, worked out read-only."""

    def test_the_commands_replay_the_card_s_own_commits_onto_the_rewritten_branch(self):
        self.record_heads(self.pushed)
        theirs = self.rewrite()
        self.write("c.txt", "three\n", "the house's own")
        before, branches = self.head(), self.branches()
        hand = self.by_hand()
        self.assertEqual((self.head(), self.branches()), (before, branches), "working it out moved nothing")
        self.typed(hand)
        self.assertEqual(self.head("HEAD~1"), theirs, "exactly its own commit, on top of theirs")
        self.assertEqual(run("git", "log", "-1", "--format=%s", cwd=self.tree), "the house's own")
        self.assertIn(before, run("git", "for-each-ref", "--format=%(objectname)", "refs/heads", cwd=self.tree),
                      "and a backup branch holds where it stood")
        facts = self.facts()
        self.assertEqual((facts["ahead"], facts["behind"]), (1, 0))
        self.assertNotIn("by_hand", facts)

    def test_a_space_whose_remote_is_not_origin_is_read_and_fetched_by_its_name(self):
        """c-665: `[spaces.<name>] remote` names the remote the worktree is read against, and
        the by-hand command and the house's batch say that name, never `origin`."""
        run("git", "remote", "rename", "origin", "upstream", cwd=self.tree)
        self.cfg.spaces["work"].remote = "upstream"
        self.record_heads(self.pushed)
        theirs = self.rewrite(fetch=False)
        run("git", "fetch", "-q", "upstream", cwd=self.tree)
        self.write("c.txt", "three\n", "the house's own")
        self.assertEqual(self.facts()["diverged"], {"ahead": 3, "behind": 3})
        self.typed(self.by_hand())
        self.assertEqual(self.head("HEAD~1"), theirs, "its own commit, on top of what upstream holds")
        said = shipround.batch_prompt(self.cfg, self.board.get(self.card),
                                      [{"kind": "rebase", "handle": "rebase", "base": "main"}], "a batch", 1)
        self.assertIn("git merge upstream/main", said)
        self.assertNotIn("origin", said)

    def test_with_no_recorded_head_the_remote_s_earlier_position_says_which_commits_are_its_own(self):
        theirs = self.rewrite()
        self.write("c.txt", "three\n", "the house's own")
        self.typed(self.by_hand())
        self.assertEqual(self.head("HEAD~1"), theirs)

    def test_with_no_commit_of_its_own_the_branch_is_moved_and_an_untracked_file_refuses_it(self):
        theirs = self.rewrite()
        before = self.head()
        (self.tree / "moved.txt").write_text("his own notes, never added\n")
        done = self.typed(self.by_hand(), check=False)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self.head(), before)
        self.assertEqual((self.tree / "moved.txt").read_text(), "his own notes, never added\n")
        (self.tree / "moved.txt").unlink()
        self.typed(self.by_hand())
        self.assertEqual(self.head(), theirs)

    def test_a_history_keel_cannot_place_gets_no_commands_and_says_it_needs_a_hand(self):
        self.rewrite()
        self.write("c.txt", "three\n", "the house's own")
        run("git", "reflog", "expire", "--expire=now", "--all", cwd=self.tree)
        facts = self.facts()
        self.assertEqual([one.get("command") for one in facts["by_hand"]], [None])
        self.assertIn(facts["by_hand"][0]["why"][:30].lower(), facts["said"].lower())

    def test_a_merge_among_its_own_commits_gets_no_commands(self):
        """c-651's rebase item has the house merge its base in; a replay would flatten it."""
        self.record_heads(self.pushed)
        self.rewrite()
        run("git", "merge", "-q", "--no-edit", "origin/main", cwd=self.tree)
        hand = self.by_hand()
        self.assertEqual([one.get("command") for one in hand], [None])
        self.assertIn("merge", hand[0]["why"])

    def test_the_terminal_s_refusal_carries_the_same_commands(self):
        self.record_heads(self.pushed)
        self.rewrite()
        self.write("c.txt", "three\n", "the house's own")
        hand = self.by_hand()
        with self.assertRaises(adapters.AdapterError) as refused:
            self.ship()
        self.assertIn(hand[0]["command"], str(refused.exception))
        self.assertIn(hand[0]["command"], shipstep.commands_text(hand), "the deck's block is the same text")
        self.assertEqual(len(str(refused.exception).splitlines()), 1, "one line: the deck shows the last")

    def test_each_worktree_of_a_cross_repo_card_gets_its_own(self):
        web = self.second()
        self.rewrite()
        rewrite(web)
        hand = self.by_hand()
        self.assertEqual([one["repo"] for one in hand], ["api", "web"])
        self.typed(hand)
        self.assertEqual((self.facts()["behind"], self.head(tree=web.tree)), (0, self.head(f"origin/{BRANCH}", web.tree)))


class PastedTest(RewrittenCase):
    """A paste runs every line whatever the one before it did, and the block may be stale
    (c-653 review, r4.F3 to r4.F5): each worktree's commands are ONE chain that stops itself."""

    def diverged(self, own: bool = True) -> list[dict]:
        self.record_heads(self.pushed)
        self.rewrite()
        if own:
            self.write("c.txt", "three\n", "the house's own")
        return self.by_hand()

    def test_a_worktree_that_is_not_there_runs_nothing_where_the_terminal_stands(self):
        hand = self.diverged()
        moved = self.dir / "moved-away"
        shutil.move(self.tree, moved)
        before = self.refs(self.api.other), self.refs(moved)
        done = self.typed(hand, check=False, cwd=self.api.other)      # a clone where the refs resolve
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual((self.refs(self.api.other), self.refs(moved)), before)

    def test_no_backup_no_move(self):
        hand = self.diverged()
        run("git", "branch", "keel/backup", cwd=self.tree)      # so `keel/backup/<...>` cannot be made
        before = self.head()
        done = self.typed(hand, check=False)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self.head(), before)
        self.assertIsNone(shipstep_under_way(self.tree))

    def stale(self, own: bool) -> None:
        hand = self.diverged(own)
        newer = self.write("later.txt", "later\n", "committed after the card was read")
        before = self.refs()
        self.typed(hand, check=False)
        self.assertEqual((self.head(), self.refs()), (newer, before))
        self.typed(self.by_hand())                       # the card's newer command does it
        self.assertEqual(self.facts()["behind"], 0)

    def test_a_replay_computed_before_one_more_commit_does_nothing(self):
        self.stale(own=True)

    def test_a_move_of_the_branch_computed_before_the_house_s_first_commit_does_nothing(self):
        """r4.F4: `checkout -B` from a stale block moved the branch off the new commit."""
        self.stale(own=False)

    def test_a_path_and_a_branch_with_shell_characters_are_quoted(self):
        hand = self.diverged()
        spaced = self.dir / "a tree; with $pace"
        shutil.move(self.tree, spaced)
        self.tree = spaced
        self.board.set_fields(self.card, {"options": {"worktree": str(spaced)}}, "human")
        self.typed(self.by_hand())
        self.assertEqual(self.facts()["behind"], 0)
        self.assertNotEqual(hand, self.by_hand())

    def test_the_fetch_names_its_refspec_so_a_narrowed_clone_still_moves_the_ref(self):
        hand = self.diverged()
        theirs = self.head(f"origin/{BRANCH}")
        run("git", "config", "remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/main", cwd=self.tree)
        again = rewrite(self.api, fetch=False)
        self.assertNotEqual(again, theirs)
        self.typed(hand)
        self.assertEqual(self.head("HEAD~1"), again, "replayed onto the branch as the remote holds it now")

    def test_unchanged_worktrees_keep_the_stored_commands_and_are_not_worked_out_again(self):
        self.diverged()
        stored = self.drain_reads()["local"]["by_hand"]
        with mock.patch.object(shipstep, "old_head", side_effect=AssertionError("worked out again")):
            self.assertEqual(self.by_hand(), json.loads(json.dumps(stored)))
        self.write("d.txt", "four\n", "one more")
        self.assertNotEqual(self.by_hand(), stored)


class UnreadTest(RewrittenCase):
    def test_a_git_read_that_failed_is_not_kept_and_the_next_pass_gives_the_command(self):
        """r4.D1: a reflog read that timed out was taken for "no earlier position", and the
        entry was then kept as stored, so the card said it needs a hand until something moved."""
        self.rewrite()
        self.write("c.txt", "three\n", "the house's own")
        real, failed = shipping.git, []

        def reflog_fails_once(root, *args):
            if args[0] == "reflog" and not failed:
                failed.append(args)
                return None                      # as a timeout or an OSError answers
            return real(root, *args)

        with mock.patch.object(shipping, "git", reflog_fails_once):
            first = self.drain_reads()["local"]["by_hand"]
            self.assertEqual((len(failed), first[0].get("command")), (1, None))
            again = self.drain_reads()["local"]["by_hand"]
        self.assertTrue(again[0].get("command"), again)
        self.typed(again)
        self.assertEqual(self.facts()["behind"], 0)


class RebuiltHereTest(RewrittenCase):
    """r-55's second gap (c-723), the c-240 case: the HOUSE rebuilt the branch on a moved base
    (with the user's yes), and the pull request's branch is still at the head Keel last
    pushed. Nothing outside Keel rewrote anything, and what is ahead is the rebuilt history
    to publish, so the user is given the push with a lease, never a replay onto the old."""

    def rebuilt(self) -> list[dict]:
        self.record_heads(self.pushed)
        run("git", "fetch", "-q", "origin", cwd=self.api.other)
        run("git", "checkout", "-q", "main", cwd=self.api.other)
        write(self.api.other, "moved.txt", "the base moved\n", "the base moved")
        run("git", "push", "-q", "origin", "main", cwd=self.api.other)
        run("git", "fetch", "-q", "origin", cwd=self.tree)
        run("git", "rebase", "-q", "origin/main", cwd=self.tree)
        return self.by_hand()

    def test_the_card_says_rebuilt_here_and_the_paste_publishes_it_with_a_lease(self):
        hand = self.rebuilt()
        facts, mine = self.facts(), self.head()
        self.assertEqual(facts["diverged"], {"ahead": 3, "behind": 2})
        self.assertIn("rebuilt here", facts["said"])
        self.assertNotIn("rewritten outside", facts["said"])
        # c-723 review r1.F7: what the paste replaces is named before it is pasted
        replaced = run("git", "rev-list", self.pushed, "^HEAD", cwd=self.tree).split()
        self.assertEqual(len(replaced), 2)
        self.assertIn("replaces 2 published commits", facts["said"])
        for sha in replaced:
            self.assertIn(sha[:7], facts["said"])
        self.assertIn(f"--force-with-lease=refs/heads/{BRANCH}:{self.pushed}", hand[0]["command"])
        self.assertIn("rebuilt here", shipround.astray_text(facts), "the house is told the same")
        self.assertNotIn("rewritten", shipround.astray_text(facts))
        self.typed(hand)
        self.assertEqual(self.head(f"refs/heads/{BRANCH}", self.api.origin), mine)
        self.assertEqual(self.head(f"keel/backup/{self.card}-{self.pushed[:7]}"), self.pushed,
                         "the published head is kept on a backup branch")
        self.assertEqual((self.head(), self.facts()["behind"]), (mine, 0))

    def test_a_push_to_the_branch_since_makes_the_paste_push_nothing(self):
        hand = self.rebuilt()
        theirs = self.colleague_pushes()
        done = self.typed(hand, check=False)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self.head(f"refs/heads/{BRANCH}", self.api.origin), theirs, "their commit stands")

    def test_an_entry_stored_before_c_723_is_worked_out_again(self):
        """c-723 review r2.F7: a card already in the c-240 state when this deploys kept the
        replay worked out before, while nothing it was worked out from moved."""
        hand = self.rebuilt()
        before = {key: value for key, value in hand[0].items() if key not in ("rebuilt", "replaces", "v")}
        before["command"] = f"git rebase --onto origin/{BRANCH} {self.pushed}"
        shipped = dict(self.shipped(), local={"ahead": 0, "behind": 2, "by_hand": [before]})
        self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: shipped}}, "drain")
        again = self.by_hand()
        self.assertTrue(again[0].get("rebuilt"), again)
        self.assertIn("--force-with-lease", again[0]["command"])
        self.assertIn("rebuilt here", self.facts()["said"])

    def test_ship_refuses_with_the_sentence_and_the_command(self):
        self.rebuilt()
        with self.assertRaisesRegex(adapters.AdapterError, "rebuilt here.*force-with-lease"):
            self.ship()
        self.assertFalse(self.answers.exists(), "nothing was pushed or posted")


def shipstep_under_way(tree: Path) -> str | None:
    """A rebase or a merge left under way in the worktree, or None."""
    git_dir = Path(run("git", "rev-parse", "--absolute-git-dir", cwd=tree))
    for name in ("rebase-merge", "rebase-apply", "MERGE_HEAD"):
        if (git_dir / name).exists():
            return name
    return None


class OutOfStepAsksTest(RewrittenCase):
    """What is not asked of a house whose branch is out of step (c-653 review, r3.F5)."""

    def behind_with_untold_review(self):
        self.live()
        self.with_a_comment()
        self.colleague_pushes()
        self.drain_reads()

    def test_a_merge_of_the_base_is_refused_while_the_branch_is_behind_or_diverged(self):
        self.behind_with_untold_review()
        with self.assertRaisesRegex(Refused, "out of step"):
            self.board.reoffer(self.card, "human", rebase=True)
        self.assertNotIn("reoffer", self.board.get(self.card)["options"])
        self.write("c.txt", "three\n", "the house's own")       # behind, and now diverged
        self.drain_reads()
        with self.assertRaisesRegex(Refused, "out of step"):
            self.board.reoffer(self.card, "human", rebase=True)

    def test_a_plain_ask_whose_only_offer_would_be_the_base_merge_is_refused_too(self):
        """r4.F7: with nothing else to offer, a plain ask on a branch behind its base was
        accepted, and the fill wrote a base-merge item the house could only defer."""
        self.colleague_pushes()
        shipped = dict(self.drain_reads(), seen=[])
        shipped["facts"] = dict(shipped.get("facts") or {}, behind=4)        # behind its base too
        self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: shipped}}, "human")
        with self.assertRaisesRegex(Refused, "out of step"):
            self.board.reoffer(self.card, "human")
        _, items, _ = shipreoffer.fill(shipped, sight(), {"by": "human", "rebase": False}, "main", MON_10)
        self.assertEqual(items, [], "and the fill adds no base merge of its own on such a branch")

    def test_a_batch_never_carries_the_base_merge_and_the_out_of_step_words_together(self):
        card = self.board.get(self.card)
        item = shipreoffer.rebase_item({}, "main", MON_10)
        local = {"ahead": 0, "behind": 3, "diverged": {"ahead": 2, "behind": 3}}
        plain = shipround.batch_prompt(self.cfg, card, [item], "his word", 1)
        held = shipround.batch_prompt(self.cfg, card, [item], "his word", 1, astray=local)
        self.assertIn(shipround.merge_of(item), plain)
        self.assertNotIn(shipround.merge_of(item), held)
        self.assertIn("2 ahead of it and 3 behind", held)


class KeepShippingTest(ShippingCase):
    """`Board.keep_shipping`: the drain's write of the record, laid over what the board holds."""

    def setUp(self):
        super().setUp()
        self.others_write(dict(self.shipped(), round=1, urgent="ci"))

    def others_write(self, record: dict) -> None:
        self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: record}}, "human")

    def without(self, record: dict, key: str) -> dict:
        return {k: v for k, v in record.items() if k != key}

    def test_a_key_the_step_removed_is_removed(self):
        read = self.shipped()
        kept = self.board.keep_shipping(self.card, read, self.without(read, "urgent"))
        self.assertEqual((kept, self.shipped()), (self.without(read, "urgent"),) * 2)

    def test_a_key_another_writer_deleted_since_the_read_stays_deleted(self):
        read = self.shipped()
        self.others_write(self.without(read, "urgent"))
        self.board.keep_shipping(self.card, read, dict(read, round=2))
        self.assertEqual(self.shipped(), dict(self.without(read, "urgent"), round=2))

    def test_with_no_read_to_compare_the_record_is_written_whole_but_for_the_lease(self):
        self.others_write(dict(self.shipped(), heads={"api": "a" * 40}, posted={"c11": "x"}))
        self.board.keep_shipping(self.card, None, {"round": 5, "heads": {"api": "b" * 40}})
        self.assertEqual(self.shipped(), {"round": 5, "heads": {"api": "a" * 40}})

    def test_what_another_writer_wrote_since_the_read_survives_the_step_s_own_keys(self):
        read = self.shipped()
        self.others_write(dict(read, posted={"c11": "x"}, heads={"api": "a" * 40}))
        self.board.keep_shipping(self.card, read, dict(read, round=2, heads={"api": "b" * 40}))
        self.assertEqual(self.shipped(), dict(read, round=2, posted={"c11": "x"}, heads={"api": "a" * 40}))


class BatchUndoneTest(ShippingCase):
    def his_ship_marks_the_draft_ready(self):
        """The stand-in adapter answers as the real one does when it flipped a draft."""
        script = self.dir / "answer.py"
        script.write_text(script.read_text().replace("'ready': []", "'ready': ['api']"))

    def retold_with_another_reply_kept(self) -> dict:
        """c11 answered and posted, then waiting again under the same handle (a comment edited
        on the host); c12 answered with a reply he has not shipped yet; the pull request a draft."""
        self.live()
        self.upkeep(MON_10 - timedelta(minutes=30))
        self.see(sight(comments=[comment(11, MON_10), comment(12, MON_10, "And the timeout?")]))
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10)
        shipping.LAST_POLLED.clear()
        self.upkeep(MON_10 + timedelta(minutes=5))
        self.verdict("c11", "not-valid", reply="The host pages at 40.")
        self.board.ship(self.card, "human", adapters.publisher(self.cfg, "work", anyway=True))
        self.verdict("c12", "not-valid", reply="Thirty seconds, as the host's.")
        shipped = self.shipped()
        again = dict(next(item for item in shipped["told"] if item["handle"] == "c11"), text="Why 40, again?")
        shipped.update(pending=[again], urgent="his word", facts=dict(shipped.get("facts") or {}, draft=True, waiting=1))
        self.board.set_fields(self.card, {"options": {SHIPPING_OPTION: shipped}}, "human")
        self.his_ship_marks_the_draft_ready()
        return self.shipped()

    def deliver_with_his_ship_in_between(self, read: dict, tell=None) -> None:
        take = shipwatch.take_batch

        def his_ship_lands_first(shipped, at):
            self.board.ship(self.card, "human", adapters.publisher(self.cfg, "work", anyway=True))
            return take(shipped, at)

        at, card = MON_10 + timedelta(minutes=30), self.board.get(self.card)
        with mock.patch.object(shipwatch, "take_batch", his_ship_lands_first), \
                mock.patch.object(house, "resume", **(tell or {"return_value": {"told": True}})):
            shipping.deliver(self.cfg, self.board, card, read, shipwatch.due(read, at), at, 1)

    def test_a_batch_taken_over_his_ship_changes_only_what_the_take_owns(self):
        """r4.F2: the take rewrote `facts` and `posted` whole from the pass's older read, so
        a draft his Ship had just marked ready read as a draft again, and the reply it had
        just posted was forgotten and would be said twice."""
        read = self.retold_with_another_reply_kept()
        self.assertEqual((set(read["posted"]), read["facts"]["draft"]), ({"c11"}, True))
        self.deliver_with_his_ship_in_between(read)
        shipped = self.shipped()
        self.assertIs(shipped["facts"]["draft"], False, "his Ship marked it ready")
        self.assertEqual(shipped["facts"]["waiting"], 0)
        self.assertEqual(set(shipped["posted"]), {"c12"}, "c11 is unanswered again; what his Ship posted stays")

    def test_and_its_undo_puts_back_only_those(self):
        read = self.retold_with_another_reply_kept()
        self.deliver_with_his_ship_in_between(read, tell={"side_effect": Refused("the relay broke")})
        shipped = self.shipped()
        self.assertIs(shipped["facts"]["draft"], False)
        self.assertEqual(shipped["facts"]["waiting"], 1)
        self.assertEqual(set(shipped["posted"]), {"c11", "c12"})
        self.assertEqual(shipped["pending"], read["pending"])

    def test_his_ship_between_the_drain_s_read_and_a_batch_that_cannot_be_told_keeps_what_it_posted(self):
        """r3.F3: the undo went back from the record as WRITTEN, which held his Ship's
        `posted` by then, to the pass's older read, so `posted` was deleted and the next
        Ship said the same reply twice."""
        self.told()
        self.verdict("c11", "not-valid", reply="The host pages at 40.")
        later = MON_10 + timedelta(minutes=20)
        self.see(sight(comments=[comment(11, MON_10, "Why is the cap 40?"), comment(12, later, "And the timeout?")]))
        shipping.LAST_POLLED.clear()
        self.upkeep(later)
        read, card = self.shipped(), self.board.get(self.card)
        self.assertTrue(read.get("pending"))
        take = shipwatch.take_batch

        def his_ship_lands_first(shipped, at):
            self.board.ship(self.card, "human", adapters.publisher(self.cfg, "work", anyway=True))
            return take(shipped, at)

        at = later + timedelta(minutes=6)
        with mock.patch.object(shipwatch, "take_batch", his_ship_lands_first), \
                mock.patch.object(house, "resume", side_effect=Refused("the relay broke")):
            shipping.deliver(self.cfg, self.board, card, read, shipwatch.due(read, at), at, 1)
        shipped = self.shipped()
        self.assertIn("c11", shipped.get("posted") or {}, "what his Ship posted is still recorded")
        self.assertEqual(shipped.get("pending"), read["pending"], "and the batch is back where it waited")
        self.assertEqual(shipped.get("round"), read.get("round"))


class ShipLeavesTheRecordTrueTest(RewrittenCase):
    """c-660: his Ship pushed 23 commits and the deck went on offering "Push 23 commits",
    because `local.ahead` stayed as the drain last read it until its next pass. The stand-in
    adapter pushes for real here, as the pack's does, and `kb ship` is the seam. `then` is
    what happens on the machine after the push and before `kb ship` reads the worktrees."""

    def kb_ship(self, then=None):
        checked = adapters.publisher(self.cfg, "work", anyway=True)

        def pushes(card):
            answer = json.loads(checked(card))
            if not shipping.sides(self.tree)[1]:       # as the adapter: a branch behind is skipped
                run("git", "push", "-q", "origin", BRANCH, cwd=self.tree)
            pushed = self.head()
            if then:
                then()
            return dict(answer, pushed={"api": pushed})
        args = SimpleNamespace(config=self.cfg, id=self.card, anyway=True)
        with mock.patch.object(adapters, "publisher", return_value=pushes):
            return cli.cmd_ship(self.board, args, "human")

    def deck_reads(self) -> dict:
        return deckstate.detail(self.cfg, self.board, self.card)["shipping"]["summary"]["local"]

    def said_behind(self) -> list[tuple[str, str]]:
        return [(e["actor"], e["text"]) for e in self.board.events(self.card)
                if e["kind"] == "note" and "behind" in (e.get("text") or "")]

    def test_the_record_says_nothing_waits_as_soon_as_his_ship_has_pushed(self):
        self.write("c.txt", "three\n", "the house's own")
        self.write("d.txt", "four\n", "and another")
        self.drain_reads()
        self.assertEqual(self.deck_reads()["ahead"], 2)
        self.kb_ship()
        self.assertEqual(self.deck_reads()["ahead"], 0, "no drain pass since: the deck offers no send that was made")
        self.drain_reads()
        self.assertEqual(self.deck_reads()["ahead"], 0)

    def test_a_pass_that_read_the_record_before_his_ship_leaves_what_the_ship_wrote(self):
        """r1.F1: the pass's own read of git may be from before the push, so its write is
        refused in the write's own transaction, and the pass goes on from the board's record."""
        self.write("c.txt", "three\n", "the house's own")
        self.drain_reads()
        read = self.shipped()
        self.kb_ship()
        stale = dict(read, local=dict(read["local"], ahead=7))
        kept = self.board.keep_shipping(self.card, read, stale, unless_moved=("shipped_at",))
        self.assertEqual(kept, self.shipped(), "the record as the board holds it, untouched")
        self.assertEqual(self.deck_reads()["ahead"], 0)
        again = shipping.keep_local(self.cfg, self.board, self.board.get(self.card), read)
        self.assertEqual(again.get("shipped_at"), self.shipped()["shipped_at"], "the pass goes on from the fresh record")

    def test_a_commit_made_while_the_push_ran_still_waits(self):
        self.write("c.txt", "three\n", "the house's own")
        self.drain_reads()
        self.kb_ship(then=lambda: self.write("d.txt", "four\n", "made while the push ran"))
        self.assertEqual(self.deck_reads()["ahead"], 1)

    def test_worktrees_unread_after_the_push_never_fail_the_ship_or_forget_the_kind(self):
        """r1.F2, r1.F3: the Ship's record is written whatever the read does; unread, the send
        is no longer offered, what was known of a branch behind stays, and nothing is said twice."""
        self.a_kept_reply()
        self.colleague_pushes()
        self.drain_reads()
        before = self.shipped()["local"]
        self.assertEqual((before["behind"], len(self.said_behind())), (1, 1))
        away = self.tree / ".git-away"
        self.kb_ship(then=lambda: (self.tree / ".git").rename(away))
        shipped = self.shipped()
        self.assertEqual(set(shipped["posted"]), {"c11"}, "the Ship is recorded")
        self.assertTrue(shipped.get("shipped_at"))
        self.assertFalse(shipped["local"].get("ahead"), "the send is no longer offered")
        self.assertEqual({key: shipped["local"].get(key) for key in ("behind", "said", "by_hand")},
                         {key: before.get(key) for key in ("behind", "said", "by_hand")})
        away.rename(self.tree / ".git")
        self.drain_reads()
        self.assertEqual(len(self.said_behind()), 1, "the next pass does not say it again")

    def test_the_first_write_alone_stops_offering_the_send(self):
        """r1.F2: `Board.ship` needs no git for that; what was read of a branch behind stays."""
        self.write("c.txt", "three\n", "the house's own")
        self.drain_reads()
        self.board.ship(self.card, "human", lambda card: {"shipping": True, "pushed": {"api": self.head()}, "sent": []})
        self.assertEqual(self.deck_reads(), {"behind": 0, "conflicts": False})

    def test_a_pass_that_read_between_his_ship_s_two_writes_does_not_say_it_again(self):
        """r1.D1: the pass read the record after the Ship's own write and before the Ship's
        read of the worktrees was kept, so its `before` holds no kind and `shipped_at` stands."""
        self.write("c.txt", "three\n", "the house's own")
        self.drain_reads()

        def pushes(card):
            run("git", "push", "-q", "origin", BRANCH, cwd=self.tree)
            pushed = self.head()
            self.colleague_pushes()
            return {"shipping": True, "pushed": {"api": pushed}, "sent": []}
        self.board.ship(self.card, "human", pushes)
        read = self.shipped()
        shipping.after_ship(self.cfg, self.board, self.card)
        shipping.keep_local(self.cfg, self.board, self.board.get(self.card), read)
        self.assertEqual([actor for actor, _ in self.said_behind()], ["human"])

    def test_a_base_never_fetched_is_no_conflict_known_to_either_read(self):
        """r1.D2, r1.D4: git cannot say whether HEAD conflicts with a base this clone does not
        hold, whatever it exits with, so neither read says it conflicts and the Ship's read
        is not unread: a commit made while the push ran is still counted."""
        run("git", "update-ref", "-d", "refs/remotes/origin/main", cwd=self.tree)
        self.write("c.txt", "three\n", "the house's own")
        self.assertIs(self.facts()["conflicts"], False, "the drain's read")
        self.drain_reads()
        self.kb_ship(then=lambda: self.write("d.txt", "four\n", "made while the push ran"))
        self.assertEqual((self.deck_reads().get("ahead"), self.deck_reads().get("conflicts")), (1, False))

    def test_a_branch_behind_again_an_hour_later_is_said_again(self):
        """r1.D3: the same sentence within a minute is the race between his Ship's read and a
        pass; the same sentence an hour later is a second change of kind, and is said."""
        self.colleague_pushes()
        self.drain_reads()
        self.typed(self.facts()["by_hand"])
        self.drain_reads()
        self.assertNotIn("said", self.shipped()["local"])
        write(self.api.other, "again.txt", "his\n", "a colleague's, again")
        run("git", "push", "-q", "origin", BRANCH, cwd=self.api.other)
        run("git", "fetch", "-q", "origin", cwd=self.tree)
        later = (datetime.fromisoformat(self.board.now()) + timedelta(hours=1)).isoformat(timespec="seconds")
        with mock.patch.object(self.board, "now", return_value=later):
            self.drain_reads()
        said = [text for _, text in self.said_behind()]
        self.assertEqual(len(said), 2, said)
        self.assertEqual(said[0], said[1], "the very sentence, said for the second change")

    def test_a_worktree_his_ship_finds_newly_behind_is_said_once_and_as_his(self):
        """r1.F7: the finding is his Ship's, never the drain's, and the next pass adds none."""
        self.write("c.txt", "three\n", "the house's own")
        self.drain_reads()
        self.kb_ship(then=self.colleague_pushes)
        self.assertEqual(self.deck_reads()["behind"], 1)
        self.assertEqual([actor for actor, _ in self.said_behind()], ["human"])
        self.drain_reads()
        self.assertEqual(len(self.said_behind()), 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
