"""merging: Approve outcome on a personal repo card merges its branch, or refuses whole."""

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from keel import drain, merging, trust
from tests.helpers import make_config


def sh(cwd, *args):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    sh(path, "git", "init", "-q", "-b", "main")
    sh(path, "git", "config", "user.email", "t@example.invalid")
    sh(path, "git", "config", "user.name", "t")
    (path / "README").write_text("hello\n")
    sh(path, "git", "add", "."); sh(path, "git", "commit", "-q", "-m", "first")
    return path


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.repo = make_repo(self.dir / "repo")
        self.cfg = make_config(self.dir, repos={"keel": self.repo})
        self.cfg.worktrees_dir.mkdir(parents=True, exist_ok=True)
        self.worktree = self.cfg.worktrees_dir / "c-1"
        sh(self.repo, "git", "worktree", "add", "-q", "-b", "keel/c-1-thing", str(self.worktree))
        (self.worktree / "new.txt").write_text("built\n")
        sh(self.worktree, "git", "add", "."); sh(self.worktree, "git", "commit", "-q", "-m", "the work")
        self.card = {"id": "c-1", "space": "personal", "repo": "keel", "title": "A thing",
                     "output_ref": "keel/c-1-thing @ abc"}

    def tearDown(self):
        self.tmp.cleanup()


class MergeTest(RepoCase):
    def test_merges_with_a_merge_commit_and_cleans_up(self):
        result = merging.publish(self.cfg, self.card)
        self.assertIn("merged into main", result)
        self.assertEqual(sh(self.repo, "git", "log", "-1", "--format=%s"), "Merge keel/c-1-thing: A thing (c-1)")
        self.assertTrue((self.repo / "new.txt").is_file())
        self.assertFalse(self.worktree.exists())
        self.assertNotIn("keel/c-1-thing", sh(self.repo, "git", "branch", "--list"))

    def test_a_reaped_worktree_is_forgotten_in_the_spaces_claude_json(self):
        """The trust entry a launch wrote for the worktree goes with it (lane T), and an
        entry Keel did not add, outside the state dir, stays."""
        claude_json = self.cfg.spaces["personal"].config_dir / ".claude.json"
        trust.grant(self.cfg.spaces["personal"].config_dir, self.worktree)
        data = json.loads(claude_json.read_text())
        data["projects"]["/his/own/project"] = {"hasTrustDialogAccepted": True}
        claude_json.write_text(json.dumps(data))
        merging.publish(self.cfg, self.card)
        projects = json.loads(claude_json.read_text())["projects"]
        self.assertEqual(list(projects), ["/his/own/project"])

    def test_runs_the_repo_test_command_first_and_refuses_a_red_suite(self):
        self.cfg.repo_tests["keel"] = "echo boom; exit 3"
        with self.assertRaises(merging.MergeRefused) as caught:
            merging.publish(self.cfg, self.card)
        self.assertIn("exited 3", str(caught.exception))
        self.assertIn("boom", str(caught.exception))
        self.assertEqual(sh(self.repo, "git", "log", "-1", "--format=%s"), "first")
        self.assertTrue(self.worktree.exists())

    def test_a_red_suite_names_its_failed_tests_and_keeps_the_whole_output(self):
        """c-535 (r-13): the refusal kept a 15 line tail, which for c-534 named no test. Its
        first line (what the block, the note and the CLI carry) names every FAIL and ERROR
        line and the failed job, and the whole output is kept in the card's directory."""
        noise = "; ".join(f"echo line {n}" for n in range(40))
        self.cfg.repo_tests["keel"] = (
            "echo 'FAIL: test_a (tests.test_x.X.test_a)'; echo 'ERROR: test_b (tests.test_y.Y.test_b)'; "
            f"{noise}; echo 'voice: exited 1 (`make voice-test`)'; exit 1")
        with self.assertRaises(merging.MergeRefused) as caught:
            merging.publish(self.cfg, self.card)
        first = str(caught.exception).splitlines()[0]
        self.assertIn("tests.test_x.X.test_a", first)
        self.assertIn("tests.test_y.Y.test_b", first)
        self.assertIn("voice: exited 1", first)
        log = self.cfg.cards_dir / "c-1" / merging.SUITE_LOG
        self.assertIn(str(log), first)
        self.assertIn("line 0", log.read_text())

    def test_the_suite_an_approve_runs_never_sees_his_token(self):
        """The kb the deck runs for an Approve holds KEEL_TOKEN, and the merge runs inside
        that kb: the suite on the merged tree is the house's own code (c-451, round 3). Nor
        does any git call the merge makes get it."""
        seen = self.dir / "suite-env.txt"
        self.cfg.repo_tests["keel"] = f"env > {seen}"
        real_run, git_envs = merging.subprocess.run, []

        def run(argv, *args, **kwargs):
            git_envs.append(kwargs.get("env"))
            return real_run(argv, *args, **kwargs)
        with mock.patch.dict(os.environ, {"KEEL_TOKEN": "his-token-value", "KEEL_LIVE_STATE": "1"}), \
                mock.patch.object(merging.subprocess, "run", side_effect=run):
            self.assertIn("merged", merging.publish(self.cfg, self.card))
        text = seen.read_text()
        self.assertNotIn("his-token-value", text)
        self.assertNotIn("KEEL_LIVE_STATE", text)
        self.assertTrue(git_envs)
        self.assertTrue(all(env is not None and "KEEL_TOKEN" not in env for env in git_envs), git_envs[:1])


    def test_refuses_a_dirty_checkout_untouched(self):
        (self.repo / "README").write_text("edited\n")
        with self.assertRaises(merging.MergeRefused) as caught:
            merging.publish(self.cfg, self.card)
        self.assertIn("uncommitted changes", str(caught.exception))
        self.assertEqual(sh(self.repo, "git", "log", "-1", "--format=%s"), "first")

    def test_a_conflict_is_aborted_and_refused(self):
        (self.repo / "new.txt").write_text("theirs\n")
        sh(self.repo, "git", "add", "."); sh(self.repo, "git", "commit", "-q", "-m", "conflicting")
        with self.assertRaises(merging.MergeRefused):
            merging.publish(self.cfg, self.card)
        self.assertEqual(sh(self.repo, "git", "status", "--porcelain"), "")
        self.assertEqual(sh(self.repo, "git", "log", "-1", "--format=%s"), "conflicting")

    def test_a_merge_git_refuses_without_a_conflict_carries_gits_words_not_a_conflict(self):
        """c-621: a user with no committer identity was told "main moved", the drain sent the
        card back to building, and the house looped on a merge that had no conflict."""
        sh(self.repo, "git", "config", "--unset", "user.name")
        sh(self.repo, "git", "config", "user.useConfigOnly", "true")
        bare = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_AUTHOR", "GIT_COMMITTER"))}
        bare.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        with mock.patch.dict(os.environ, bare, clear=True), \
                self.assertRaises(merging.MergeRefused) as caught:
            merging.publish(self.cfg, self.card)
        said = str(caught.exception)
        self.assertFalse(said.startswith("merge conflict"), said)
        self.assertIn("not on a conflict", said)
        self.assertIn("ident", said)
        self.assertEqual(sh(self.repo, "git", "log", "-1", "--format=%s"), "first")

    def test_nothing_to_merge_is_none(self):
        self.assertIsNone(merging.publish(self.cfg, dict(self.card, output_ref="https://x/pr/1", id="c-9")))
        self.assertIsNone(merging.publish(self.cfg, dict(self.card, repo=None)))
        self.cfg.spaces["personal"].adapter_dir = self.dir
        self.assertIsNone(merging.publish(self.cfg, self.card))

    def test_branch_is_the_worktree_head_first_then_the_outcome_words(self):
        self.assertEqual(merging.branch_of(dict(self.card, output_ref=""), self.worktree), "keel/c-1-thing")
        self.assertEqual(merging.branch_of(dict(self.card, output_ref="branch other @ 1"), self.worktree), "keel/c-1-thing")
        gone = self.dir / "gone"
        self.assertEqual(merging.branch_of(dict(self.card, output_ref="branch keel/x-y @ 8b4347c"), gone), "keel/x-y")
        self.assertEqual(merging.branch_of(dict(self.card, output_ref="keel/x-y @ 8b4347c"), gone), "keel/x-y")
        self.assertIsNone(merging.branch_of(dict(self.card, output_ref="https://x/pr/1"), gone))


class MergedTreeTest(RepoCase):
    """E5 (c-298): the suite runs on the tree that LANDS, and the landing is a fast-forward.

    The branch used to be tested as it was and merged into a main that had moved, so the
    tree that landed was never the tree that was tested. These build the merge commit in a
    temporary worktree, test that, and let `--ff-only` refuse a main that moved meanwhile."""

    def commit_on_main(self, name: str, text: str = "x\n", message: str = "moved") -> str:
        (self.repo / name).write_text(text)
        sh(self.repo, "git", "add", "."); sh(self.repo, "git", "commit", "-q", "-m", message)
        return sh(self.repo, "git", "rev-parse", "HEAD")

    def test_a_branch_green_alone_and_red_once_merged_is_refused_and_main_is_untouched(self):
        (self.worktree / "check.sh").write_text("test ! -f poison\n")
        sh(self.worktree, "git", "add", "."); sh(self.worktree, "git", "commit", "-q", "-m", "check")
        self.cfg.repo_tests["keel"] = "sh check.sh"
        self.assertEqual(subprocess.run("sh check.sh", shell=True, cwd=self.worktree).returncode, 0,
                         "green on the branch alone")
        moved = self.commit_on_main("poison")
        with self.assertRaises(merging.MergeRefused) as caught:
            merging.publish(self.cfg, self.card)
        self.assertIn("on the merged tree", str(caught.exception))
        self.assertEqual(sh(self.repo, "git", "rev-parse", "HEAD"), moved)
        self.assertTrue(self.worktree.is_dir(), "the card's worktree is kept for the house")
        self.assertFalse(merging.trial_path(self.cfg, "c-1").exists(), "the trial tree is gone")

    def test_the_tree_that_lands_is_the_tree_that_was_tested(self):
        self.commit_on_main("other.txt")
        seen = self.dir / "tested"
        self.cfg.repo_tests["keel"] = f"git rev-parse 'HEAD^{{tree}}' > {seen}"
        merging.publish(self.cfg, self.card)
        self.assertEqual(seen.read_text().strip(), sh(self.repo, "git", "rev-parse", "HEAD^{tree}"))
        self.assertEqual(sh(self.repo, "git", "log", "-1", "--format=%s"),
                         "Merge keel/c-1-thing: A thing (c-1)")

    def test_a_main_that_moves_while_the_suite_runs_is_built_again_once(self):
        runs = self.dir / "runs"
        self.cfg.repo_tests["keel"] = (
            f"echo run >> {runs}; if [ $(wc -l < {runs}) -eq 1 ]; then "
            f"git -C {self.repo} -c user.name=t -c user.email=t@x commit -q --allow-empty -m moved; fi")
        result = merging.publish(self.cfg, self.card)
        self.assertIn("merged into main", result)
        self.assertEqual(len(runs.read_text().splitlines()), 2, "tested again on the new head")
        parents = sh(self.repo, "git", "log", "-1", "--format=%P").split()
        self.assertEqual(sh(self.repo, "git", "log", "-1", "--format=%s", parents[0]), "moved")

    def test_a_main_that_moves_every_time_is_refused_not_chased(self):
        self.cfg.repo_tests["keel"] = (
            f"git -C {self.repo} -c user.name=t -c user.email=t@x commit -q --allow-empty -m moved")
        with self.assertRaises(merging.MergeRefused) as caught:
            merging.publish(self.cfg, self.card)
        self.assertIn("moved twice", str(caught.exception))
        self.assertEqual(sh(self.repo, "git", "log", "-1", "--format=%s"), "moved")

    def test_a_branch_this_machine_does_not_have_is_named_not_called_a_conflict(self):
        """c-306: a card built on the other machine. Its worktree is not here and neither is
        its branch; the old answer was "main moved", which sent the house to merge a main
        that had not moved."""
        card = dict(self.card, id="c-2", output_ref="keel/c-2-elsewhere @ abc")
        with self.assertRaises(merging.MergeRefused) as caught:
            merging.publish(self.cfg, card)
        self.assertNotIn("merge conflict", str(caught.exception))
        self.assertIn("elsewhere", str(caught.exception))

    def test_the_pre_run_records_the_merged_tree_and_lands_nothing(self):
        """R5: what Approve outcome would find, worked out before the tap."""
        before = sh(self.repo, "git", "rev-parse", "HEAD")
        self.cfg.repo_tests["keel"] = "test -f new.txt"
        green = merging.trial(self.cfg, self.card)
        self.assertEqual((green["result"], green["base"]), ("green", before))
        self.assertEqual(green["branch"], sh(self.worktree, "git", "rev-parse", "HEAD"))
        self.cfg.repo_tests["keel"] = "exit 4"
        self.assertEqual(merging.trial(self.cfg, self.card)["result"], "red")
        self.assertEqual(sh(self.repo, "git", "rev-parse", "HEAD"), before)
        self.assertTrue(self.worktree.is_dir())


class LocalLandingTest(RepoCase):
    """c-665: a landing is local, and what it publishes says so."""

    def test_nothing_is_pushed_and_the_answer_says_so(self):
        remote = self.dir / "remote.git"
        sh(self.dir, "git", "init", "-q", "--bare", "-b", "main", str(remote))
        sh(self.repo, "git", "remote", "add", "origin", str(remote))
        sh(self.repo, "git", "push", "-q", "origin", "main")
        before = sh(remote, "git", "rev-parse", "refs/heads/main")
        answer = merging.publish(self.cfg, self.card)
        self.assertEqual(sh(remote, "git", "rev-parse", "refs/heads/main"), before)
        self.assertIn("merged into main locally, not pushed", answer)


class SlowGitTest(unittest.TestCase):
    """A git that outlives its timeout is a refusal, never an exception nobody catches.

    `subprocess.run(timeout=...)` raises `TimeoutExpired`, which is a `SubprocessError` and
    NOT an `OSError`, so `code_head`'s `except (MergeRefused, OSError)` never caught it. On a
    loaded box that exception came out of `merging.code_head` through `drain.code_moved`,
    which `drain.run` calls OUTSIDE its try, and ended the drain loop instead of logging one
    failed pass (2026-09-20). A head that cannot be read is unknown, and unknown must read as
    "not moved": never a crash, and never a restart either.

    The instrument is a real slow `git` first on PATH with a tenth of a second to run in, so
    the timeout is the one the code passes rather than a mocked exception.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        binaries = self.dir / "bin"
        binaries.mkdir()
        slow = binaries / "git"
        slow.write_text("#!/bin/sh\nsleep 5\n")
        slow.chmod(0o755)
        saved = os.environ["PATH"]
        os.environ["PATH"] = os.pathsep.join([str(binaries), saved])
        self.addCleanup(os.environ.__setitem__, "PATH", saved)
        patch = mock.patch.object(merging, "GIT_SECONDS", 0.1)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_git_that_times_out_refuses_with_the_reason(self):
        with self.assertRaises(merging.MergeRefused) as caught:
            merging.git(self.dir, "rev-parse", "HEAD")
        self.assertIn("no answer in 0.1s", str(caught.exception))


    def test_an_unknown_head_reads_as_not_moved(self):
        cfg = make_config(self.dir)
        cfg.root = self.dir
        self.assertFalse(drain.code_moved(cfg, "a930320"))

    def test_a_test_command_that_never_finishes_refuses_rather_than_raising(self):
        with self.assertRaises(merging.MergeRefused) as caught:
            merging.run_tests("sleep 5", self.dir, seconds=0.1)    # `[keel] merge_test_seconds`
        self.assertIn("did not finish in 0.1s", str(caught.exception))


if __name__ == "__main__":
    unittest.main()


class TheTapsBudgetTest(RepoCase):
    """Round 4 finding 4: the suite used to outlive the deck's 180 second wait, orphaned
    when kb was killed and leaving the `.landing` tree behind, and every retap started
    another. The suite runs in its own process group within the tap's budget, is killed as
    a group when that runs out, the tree is removed, and the card is told once."""

    def setUp(self):
        super().setUp()
        # A mark nothing else on the machine carries, matched as the whole command line of a
        # `sleep`: a looser pattern matched the shell of whoever was watching the test run.
        self.MARK = f"61.{os.getpid()}{int(time.time() * 1000) % 100000}"

    def survivors(self) -> str:
        return subprocess.run(["pgrep", "-f", f"^sleep {self.MARK}$"], capture_output=True, text=True).stdout.strip()

    def budget(self, seconds: str):
        return mock.patch.dict(os.environ, {merging.TAP_ENV: seconds})

    def test_a_suite_that_outruns_the_tap_is_killed_as_a_group(self):
        self.addCleanup(lambda: self.assertEqual(self.survivors(), ""))
        started = time.time()
        with self.budget("1"), self.assertRaises(merging.Outran):
            merging.run_tests(f"sleep {self.MARK} & sleep {self.MARK}; wait", self.worktree, "abc")
        self.assertLess(time.time() - started, 10)
        self.assertEqual(self.survivors(), "", "a child of the suite outlived the tap")

    def test_the_landing_tree_goes_and_main_is_untouched(self):
        main = sh(self.repo, "git", "rev-parse", "main")
        self.cfg.repo_tests["keel"] = f"sleep {self.MARK}"
        with self.budget("1"), self.assertRaises(merging.Outran):
            merging.publish(self.cfg, self.card)
        self.assertFalse(merging.trial_path(self.cfg, "c-1").exists())
        self.assertEqual(sh(self.repo, "git", "rev-parse", "main"), main)
        self.assertEqual(self.survivors(), "")

    def test_the_card_is_told_once_how_to_land_it_and_is_not_blocked(self):
        from argparse import Namespace
        from keel import cli
        from keel.board import Board, Refused
        board = Board(self.cfg.db_path)
        self.addCleanup(board.close)
        card = board.create("personal", "A thing", repo="keel", actor="human")
        board.stage(card, "assigned", "human"); board.stage(card, "building", "drain")
        board.stage(card, "review", "house", plan_ref="p.md", output_ref="keel/c-1-thing @ abc")
        self.cfg.repo_tests["keel"] = f"sleep {self.MARK}"
        args = Namespace(id=card, gate="outcome", config=self.cfg, said=None, relay=None, to=None)
        with mock.patch.object(merging, "branch_of", return_value="keel/c-1-thing"), \
                self.budget("1"), self.assertRaises(Refused) as caught:
            cli.cmd_approve(board, args, "human")
        said = str(caught.exception)
        self.assertIn(f"kb approve {card} outcome", said)
        self.assertIn("merge_queue", said)
        self.assertEqual(len(said.splitlines()), 1)
        found = board.get(card)
        self.assertEqual((found["stage"], found["blocked_reason"]), ("review", None))
        self.assertEqual(sum("ran longer than" in (e.get("text") or "") for e in board.events(card)), 1)

    def test_a_retap_while_the_suite_runs_is_refused_and_starts_nothing(self):
        from argparse import Namespace
        from keel import cli
        from keel.board import Board, Refused
        board = Board(self.cfg.db_path)
        self.addCleanup(board.close)
        card = board.create("personal", "A thing", repo="keel", actor="human")
        args = Namespace(id=card, gate="outcome", config=self.cfg, said=None, relay=None, to=None)
        with merging.approve_lock(self.cfg, card), \
                mock.patch.object(merging, "publish") as publish, \
                self.assertRaises(Refused) as caught:
            cli.cmd_approve(board, args, "human")
        publish.assert_not_called()
        self.assertIn("still running", str(caught.exception))
        self.assertIn(f"kb approve {card} outcome", str(caught.exception))
