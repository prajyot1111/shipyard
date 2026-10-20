"""The leak check itself: a test that leaves a Board open fails, one that closes it or uses
it as a context manager does not (`tests/boardleak.py`)."""

import tempfile
import unittest
from pathlib import Path

from keel.board import Board


class Inner(unittest.TestCase):
    """Run by the tests below through their own result. Its methods are not named `test_`,
    so discovery never runs them on their own."""

    db: Path

    def leaks(self):
        Board(self.db).create("personal", "left open")

    def closes(self):
        board = Board(self.db)
        board.create("personal", "closed")
        board.close()

    def in_a_with(self):
        with Board(self.db) as board:
            board.create("personal", "in a with")


def run(name: str, db: Path) -> unittest.TestResult:
    Inner.db = db
    result = unittest.TestResult()
    Inner(name).run(result)
    return result


class LeakCheckTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "board.db"

    def test_a_board_left_open_fails_the_test_that_opened_it(self):
        result = run("leaks", self.db)
        self.assertEqual(len(result.failures), 1)
        message = result.failures[0][1]
        self.assertIn("left 1 Board(s) open", message)
        self.assertIn("test_boardleak.py", message)

    def test_a_closed_board_passes(self):
        result = run("closes", self.db)
        self.assertEqual((result.failures, result.errors), ([], []))

    def test_a_board_is_a_context_manager_that_closes(self):
        result = run("in_a_with", self.db)
        self.assertEqual((result.failures, result.errors), ([], []))

