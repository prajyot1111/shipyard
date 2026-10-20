"""The deck's half of deleting a board (lane BD, BD-3): the confirm's words, the menus, the
trash behind Include deleted, and a line for every action. Greps and one node fixture, as the other deck
tests are: a stdlib suite cannot run the page. The screenshots in the lane's report are the
render."""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from keel import serve
from tests.test_deck_css import js_function

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
MODULE = APP / "ui.boarddelete.js"


def source(name: str) -> str:
    return (APP / name).read_text(encoding="utf-8")


def board_tip_keys() -> set[str]:
    text = source("ui.tips.js")
    start = text.index("var BOARD_TIPS = {")
    block = text[start:text.index("};", start)]
    return set(re.findall(r"^\s*'([a-z-]+)':", block, re.M))


class ConfirmWordsTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_confirm_names_where_the_board_is_used(self):
        result = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "board-delete.js"), str(MODULE)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True})


class EveryActionHasALineTest(unittest.TestCase):
    def test_every_drawn_key_has_a_line_and_every_line_is_drawn(self):
        text = source("ui.boarddelete.js")
        drawn = set(re.findall(r"'(board-(?:delete|delete-stack|restore))'", text))
        self.assertEqual(drawn, board_tip_keys())


