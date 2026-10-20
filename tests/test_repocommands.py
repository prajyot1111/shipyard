"""A repo's commands, read from its adopted CLAUDE.md (keel/repocommands.py, c-678): the test
command a landing runs, the prepare command a fresh worktree and the landing's merged tree
get, and the branch work lands on. On a temp config laid out as an install's, with a real
git repo as the copy; no remote is reached and nothing outside the temp directory is run."""

import os
import signal
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from keel import actions, adapters, deckstate, merging, readiness, repocommands, tierrecord
from keel.board import Board, open_board
from keel.config import Space
from tests.helpers import make_config, make_repo

FILE = """# api: how to work in this repo

## Prepare and test
- Prepare a fresh copy: `touch prepared.marker`
- Run the tests: `test -f prepared.marker && test -f new.txt`

## Where work lands
- Finished work lands on `main`.
"""


def sh(cwd, *args):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        self.home = self.dir / "spaces" / "work" / "api"
        self.repo = make_repo(self.home / "repo")
        self.cfg = make_config(self.dir)
        self.cfg.source = self.dir / "config.toml"          # an install's config: it has a layout
        self.cfg.spaces["work"] = Space(name="work", config_dir=self.dir / "cfg-work", repos={"api": self.repo},
                                        contract=None, adapter=None, house_review=False)
        self.tier = self.home / "CLAUDE.md"
        self.adopted(FILE)
        self.card = {"id": "c-1", "space": "work", "repo": "api", "title": "A thing", "options": {}}

    def adopted(self, text: str) -> None:
        """The repo's file as the user saved it: the record a line needs before it runs (F3)."""
        self.tier.write_text(text)
        with open_board(self.cfg) as board:
            tierrecord.saved(board, self.tier, text)

    def built(self) -> Path:
        """The card's worktree, cut as a house's is, with one commit of work on its branch."""
        [tree] = adapters.worktree(self.cfg, self.card)
        (tree / "new.txt").write_text("built\n")
        sh(tree, "git", "add", "new.txt")
        sh(tree, "git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "the work")
        return tree


class CommandsTest(Case):
    def test_the_test_command_is_the_configs_else_the_files(self):
        self.assertEqual(repocommands.tests_of(self.cfg, "work", "api"), "test -f prepared.marker && test -f new.txt")
        self.cfg.repo_tests["api"] = "make test"
        self.assertEqual(repocommands.tests_of(self.cfg, "work", "api"), "make test", "[tests] in the config wins")
        self.assertIsNone(repocommands.tests_of(self.cfg, "personal", "keel"), "a repo with neither has none")

    def test_the_prepare_command_and_where_work_lands_are_the_files(self):
        self.assertEqual(repocommands.prepare_of(self.cfg, "work", "api"), "touch prepared.marker")
        self.assertEqual(repocommands.lands_of(self.cfg, "work", "api"), "main")
        self.tier.unlink()
        self.assertIsNone(repocommands.prepare_of(self.cfg, "work", "api"))


class PrepareTest(Case):
    def test_a_worktree_is_prepared_when_it_is_cut_and_not_again(self):
        [tree] = adapters.worktree(self.cfg, self.card)
        self.assertEqual(tree, self.home / "trees" / "c-1")
        self.assertTrue((tree / "prepared.marker").is_file())
        (tree / "prepared.marker").unlink()
        adapters.worktree(self.cfg, self.card)
        self.assertFalse((tree / "prepared.marker").exists(), "a worktree that is there is not prepared again")

    def test_a_prepare_that_fails_refuses_the_cut_and_leaves_no_worktree(self):
        self.adopted(FILE.replace("touch prepared.marker", "echo no lockfile >&2; exit 3"))
        with self.assertRaises(adapters.AdapterError) as refused:
            adapters.worktree(self.cfg, self.card)
        self.assertIn("could not prepare a fresh copy of api", str(refused.exception))
        self.assertIn("no lockfile", str(refused.exception))
        self.assertFalse((self.home / "trees" / "c-1").exists())
        self.adopted(FILE)
        [tree] = adapters.worktree(self.cfg, self.card)
        self.assertTrue((tree / "prepared.marker").is_file(), "the next cut prepares it again")

    def test_the_merged_tree_is_prepared_before_its_tests_run(self):
        """The test command needs what prepare makes: it passes only on a prepared tree."""
        self.built()
        result = merging.publish(self.cfg, self.card)
        self.assertIn("merged into main", result)
        self.assertTrue((self.repo / "new.txt").is_file())

    def test_a_merged_tree_that_cannot_be_prepared_lands_nothing(self):
        self.built()
        self.adopted(FILE.replace("touch prepared.marker", "exit 4"))
        with self.assertRaises(merging.MergeRefused) as refused:
            merging.publish(self.cfg, self.card)
        self.assertIn("the merged tree could not be prepared", str(refused.exception))
        self.assertFalse((self.repo / "new.txt").exists())


class GroupTest(Case):
    """Prepare runs as the suite does (review F5): its own process group, ended whole."""

    CHILD = "sleep 600 >/dev/null 2>&1 & echo $! > child.pid; wait"

    def gone(self, pid: int) -> bool:
        """Whether the process is gone or only waiting to be reaped (asked, never timed)."""
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        return not state or state.startswith("Z")

    def test_a_prepare_that_runs_out_of_time_takes_its_children_with_it(self):
        tree = self.dir / "tree"
        tree.mkdir()
        with self.assertRaises(repocommands.PrepareFailed) as failed:
            repocommands.prepare(self.CHILD, tree, seconds=1)
        self.assertIn("did not finish in 1s", str(failed.exception))
        pid = int((tree / "child.pid").read_text())
        self.addCleanup(lambda: self.gone(pid) or os.kill(pid, signal.SIGKILL))
        self.assertTrue(self.gone(pid), "the child the prepare command started was left running")

    def test_a_prepare_in_a_landing_stops_at_the_taps_budget(self):
        self.built()
        self.adopted(FILE.replace("touch prepared.marker", "sleep 600"))
        with mock.patch.dict(os.environ, {merging.TAP_ENV: "1"}), self.assertRaises(merging.Outran) as outran:
            merging.publish(self.cfg, self.card)
        self.assertIn("preparing the merged tree ran past the tap's 1 s", str(outran.exception))
        self.assertFalse((self.repo / "new.txt").exists(), "nothing landed")


class SaysTest(Case):
    def test_approve_says_whether_the_landing_is_tested_and_why_not(self):
        self.assertIn("lands only if it is green", actions.landing_note(self.cfg, self.card))
        self.adopted(FILE.replace("- Run the tests: `test -f prepared.marker && test -f new.txt`\n", ""))
        self.assertIn("lands untested, since api's CLAUDE.md has no Run the tests line",
                      actions.landing_note(self.cfg, self.card))
        elsewhere = dict(self.card, space="personal", repo="keel")
        self.assertIn("lands untested, since keel has no test command", actions.landing_note(self.cfg, elsewhere))

    def test_the_state_names_the_repos_whose_work_lands_untested(self):
        board = Board(self.cfg.db_path)
        self.addCleanup(board.close)
        # the state reads the machine's readiness too: the phone row never asks the real tool
        asked = mock.patch.object(readiness, "serve_status", return_value={"missing": True})
        asked.start()
        self.addCleanup(asked.stop)
        self.assertEqual(deckstate.build(self.cfg, board, rows=[])["spaces"]["work"]["untested"], {})
        self.adopted("# api\n")
        said = deckstate.build(self.cfg, board, rows=[])["spaces"]["work"]["untested"]
        self.assertEqual(said, {"api": "api's CLAUDE.md has no Run the tests line, so Approve lands this without running any tests."})

    def test_a_state_build_reads_the_records_on_its_own_board_and_opens_no_other(self):
        """It opened a board per repo, twice, on every state request (review r2.F8)."""
        board = Board(self.cfg.db_path)
        self.addCleanup(board.close)
        asked = mock.patch.object(readiness, "serve_status", return_value={"missing": True})
        asked.start()
        self.addCleanup(asked.stop)
        self.adopted("# api\n")
        with mock.patch("keel.board.open_board", side_effect=AssertionError("a second board was opened")):
            built = deckstate.build(self.cfg, board, rows=[])
            card = {"id": "c-1", "space": "work", "repo": "api"}
            self.assertIn("lands untested", actions.landing_note(self.cfg, card, board))
        self.assertIn("api", built["spaces"]["work"]["untested"])

    def test_the_record_lookup_has_an_index(self):
        board = Board(self.cfg.db_path)
        self.addCleanup(board.close)
        plan = board.conn.execute(
            "EXPLAIN QUERY PLAN SELECT data FROM events WHERE kind = 'note' AND actor = 'human' "
            "AND json_extract(data, '$.tier') = ? ORDER BY id DESC LIMIT 1", ("x",)).fetchall()
        self.assertIn("events_tier", " ".join(str(tuple(row)) for row in plan))


class LandsOnTest(Case):
    """c-734: the "Finished work lands on" line is retired. A file that names another branch
    checks nothing out in Keel's copy, and the sentence says the line moves nothing and where
    a card naming no base lands (until c-734, `apply_lands` switched the copy)."""

    def test_a_file_that_lands_elsewhere_moves_nothing_and_says_so(self):
        sh(self.repo, "git", "branch", "develop")
        self.adopted(FILE.replace("`main`", "`develop`"))
        said = repocommands.lands_said(self.cfg, "work", "api")
        self.assertEqual(sh(self.repo, "git", "symbolic-ref", "--short", "HEAD"), "main")
        self.assertIn("\"Finished work lands on `develop`\" line moves nothing", said)
        self.assertIn("else on main", said)
        self.assertIn("add it as a base on How work ships", said)

    def test_a_file_that_names_no_branch_says_nothing(self):
        self.adopted(FILE.replace("- Finished work lands on `main`.\n", ""))
        self.assertIsNone(repocommands.lands_said(self.cfg, "work", "api"))


if __name__ == "__main__":
    unittest.main()
