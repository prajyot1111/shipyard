"""A test that leaves a `Board` open fails, and says where the board was opened.

WHY. An open `Board` holds a SQLite connection, and the collector closes it whenever it
happens to run, with a `ResourceWarning: unclosed database` printed at THAT moment, inside
whichever test is running then. `tests/test_remote.py` compares what `kb` prints, so it
failed about one run in four on another test's garbage, and the fix of the day was to strip
warnings out of what it compared: the leak was hidden rather than found (c-417's leftover).
The collector is not deterministic; this is. Every `Board` opened while a test runs is
recorded, and when the test ends any still open is a failure of THAT test, naming the line
that opened it. The board is then closed, so nothing is left for the collector to find.

`install` is called once, from `tests/__init__.py`, beside the fence. A board opened outside
any test (a module import, `setUpClass`) is not tracked: nothing here can say whose it is.
"""

import sqlite3
import sys
import traceback
import unittest
from pathlib import Path

from keel import board as board_module

_OPENED: list | None = None     # (board, where) for the running test, None between tests
_INSTALLED = False


def still_open(board) -> bool:
    try:
        board.conn.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        return False
    return True


SKIP = {str(Path(__file__).resolve()), str(Path(board_module.__file__).resolve())}


def opened_at() -> str:
    """The innermost frame outside this file and the board module: who opened it."""
    for frame in reversed(traceback.extract_stack()[:-1]):
        path = Path(frame.filename)
        if str(path.resolve()) not in SKIP:
            return f"{path.parent.name}/{path.name}:{frame.lineno}"
    return "unknown"


def leaked(opened: list) -> list[str]:
    """Where each still-open board was opened; every one of them is closed on the way."""
    where = []
    for board, at in opened:
        if still_open(board):
            where.append(at)
            board.close()
    return where


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_init = board_module.Board.__init__
    original_run = unittest.TestCase.run

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        if _OPENED is not None:
            _OPENED.append((self, opened_at()))

    def run(self, result=None):
        global _OPENED
        outer, _OPENED = _OPENED, []
        try:
            returned = original_run(self, result)
            where = leaked(_OPENED)
        finally:
            _OPENED = outer
        if where and result is not None:
            try:
                raise AssertionError(f"left {len(where)} Board(s) open, opened at: "
                                     f"{', '.join(sorted(set(where)))}")
            except AssertionError:
                result.addFailure(self, sys.exc_info())
        return returned

    board_module.Board.__init__ = init
    unittest.TestCase.run = run
