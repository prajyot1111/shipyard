"""The fetch role's loop (`keel/fetchloop.py`, c-742): what a pass files is filed under one
lock, so two roles on one install file each card once."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import cli, fetch, fetchloop, recurring
from keel.board import Board
from tests.helpers import make_config, write_toml
from tests.test_fetch import WORKER, add_ask

WEEKLY = {"every_days": 7, "space": "personal", "title": "Weekly review", "brief": "look back"}


class LoopCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        Board(self.cfg.db_path).close()

    def cards(self) -> list[str]:
        with Board(self.cfg.db_path) as board:
            return sorted(card["title"] for card in board.list_cards())

    def log_text(self) -> str:
        return (self.cfg.logs_dir / fetch.LOG_NAME).read_text()


class FilingTest(LoopCase):
    """r1.F3: `recurring.file_due` reads "due" and then creates, with nothing across the
    two, so a second role whose pass lands between them filed the same card again."""

    def setUp(self):
        super().setUp()
        self.cfg.recurring = {"weekly": dict(WEEKLY)}
        asker = self.cfg.segments_dir / "asker"
        (asker / "data" / "asks").mkdir(parents=True)
        (asker / "worker.md").write_text(WORKER)
        add_ask(asker, 1)

    def test_two_interleaved_passes_file_each_card_once(self):
        file_card, others = recurring.file_card, []

        def interleaved(board, key, table):
            """The other role's whole filing step lands after this one read "due"."""
            if not others:
                others.append(None)
                others[0] = fetchloop.file_cards(self.cfg)
            return file_card(board, key, table)

        with mock.patch.object(recurring, "file_card", interleaved):
            asked, due, why = fetchloop.file_cards(self.cfg)
        self.assertEqual((sorted(asked), sorted(due)), (["asker"], ["weekly"]))
        self.assertEqual((why, others), ("", [({}, {}, "another fetch role is filing")]),
                         "the pass that found the lock held filed nothing, and says why")
        self.assertEqual(self.cards(), ["Weekly review", "asker: 1 ask"])
        self.assertIn("filing skipped: another fetch role is filing", self.log_text())

    def test_the_lock_is_let_go_so_the_next_pass_files(self):
        fetchloop.file_cards(self.cfg)
        self.assertFalse(fetch.lock_path(self.cfg, fetchloop.FILING).exists())
        add_ask(self.cfg.segments_dir / "asker", 2)
        self.assertEqual(sorted(fetchloop.file_cards(self.cfg)[0]), ["asker"])


class Execed(Exception):
    """Stands in for the exec: the process would be replaced here."""


class Stopped(Exception):
    """The loop was still running when the test had seen enough passes."""


class MovingCase(LoopCase):
    """A segment whose fetcher, a real one run as the role runs it, moves the checkout's
    head while it runs: the deploy that lands mid-fetch. Nothing in the loop is replaced but
    the head it reads, its sleep and its exec."""

    def setUp(self):
        super().setUp()
        self.head = self.dir / "head"
        self.mover = self.cfg.segments_dir / "mover"
        self.mover.mkdir(parents=True)
        (self.mover / "fetch.py").write_text(
            "import pathlib\n"
            f"pathlib.Path({str(self.head)!r}).write_text('head-2')\n"
            "pathlib.Path('summary.json').write_text('{}')\n")
        self.lock = fetch.lock_path(self.cfg, "mover")

    def loop(self, start, passes: int = 3) -> tuple[type, list[bool]]:
        """Run `start()` until it execs or has slept `passes` times: (how it ended, whether
        the segment's lock was held at each exec)."""
        self.head.write_text("head-1")
        (self.mover / "summary.json").unlink(missing_ok=True)
        execs, sleeps = [], []

        def execv(*argv):
            execs.append(self.lock.exists())
            raise Execed

        def sleep(_seconds):
            sleeps.append(1)
            if len(sleeps) >= passes:
                raise Stopped

        with mock.patch("keel.merging.code_head", lambda root: self.head.read_text()), \
                mock.patch.object(fetch, "interpreter", lambda cfg: sys.executable), \
                mock.patch.object(fetchloop.time, "sleep", sleep), \
                mock.patch.object(fetchloop.os, "execv", execv):
            try:
                start()
            except (Execed, Stopped) as ended:
                return type(ended), execs
        return type(None), execs


class FollowTest(MovingCase):
    """The role as a process of its own follows its checkout and its config itself (c-742),
    and the exec never lands while a fetcher runs (r1.F8)."""

    def run_role(self, passes: int = 3) -> tuple[type, list[bool]]:
        return self.loop(lambda: fetchloop.run(self.cfg), passes)

    def moves_config(self, text: str) -> None:
        """The fetcher rewrites the role's config file, as a save from the deck would."""
        self.cfg.source = write_toml(self.dir)
        (self.mover / "fetch.py").write_text(
            "import pathlib\n"
            f"config = pathlib.Path({str(self.cfg.source)!r})\n"
            f"config.write_text(config.read_text() + {text!r})\n"
            "pathlib.Path('summary.json').write_text('{}')\n")

    def test_code_that_moves_during_a_fetch_restarts_the_role_after_the_pass(self):
        ended, held = self.run_role()
        self.assertEqual((ended, held), (Execed, [False]), "the exec found the segment's lock held")
        self.assertTrue((self.mover / "summary.json").is_file(), "the fetcher finished first")
        said = self.log_text()
        self.assertLess(said.index("mover        ok"), said.index("code moved since start; restarting between passes"))

    def test_a_config_saved_during_a_fetch_restarts_the_role_after_the_pass(self):
        self.moves_config("\n# saved from the deck\n")
        self.assertEqual(self.run_role(), (Execed, [False]))
        self.assertIn("config moved since start; restarting between passes", self.log_text())

    def test_a_config_that_no_longer_loads_is_said_once_and_the_role_keeps_running(self):
        self.moves_config("\nthis is not toml [\n")
        self.assertEqual(self.run_role(passes=4), (Stopped, []))
        self.assertEqual(self.log_text().count("config moved but does not load"), 1)

    def test_with_its_own_restart_off_it_runs_on_through_a_move(self):
        self.assertEqual(self.loop(lambda: fetchloop.run(self.cfg, follow=False)), (Stopped, []))
        self.assertEqual(self.head.read_text(), "head-2", "the code did move")


class SharedProcessTest(MovingCase):
    def roles(self, roles: str) -> tuple[type, list[bool]]:
        """`keel run --roles <roles>` with the fetch role first, so its loop is the one this
        thread runs, and no other role started."""
        with mock.patch.object(cli.threading, "Thread"):
            return self.loop(lambda: cli.role_run(self.cfg, mock.Mock(roles=roles)))

    def test_beside_another_role_the_fetch_role_never_execs_the_process(self):
        """r1.F5: the deck beside it may hold a conversation, a house call or a deck action,
        which an exec cuts; its restart, or the drain's, waits for those and is the
        process's. The fetch role's own is for a process of its own."""
        for roles in ("fetch,serve", "fetch,drain", "fetch,serve,drain"):
            with self.subTest(roles):
                self.assertEqual(self.roles(roles), (Stopped, []))
                self.assertEqual(self.head.read_text(), "head-2", "the code did move")
        self.assertEqual(self.roles("fetch")[0], Execed, "alone, it follows the move itself")


if __name__ == "__main__":
    unittest.main()
