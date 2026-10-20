"""`options.cut_from` is the drain's record (r2.D1; keel/board.py).

The cut records the usual branch a card was cut from (`adapters.cut_point`, r2.F1), and the
landing and the house's target prefer it. A house or Bosun that could write it would aim its
own landing, as `options.base` (the owner's) and `options.branch` (written once) are guarded
against. So only the drain writes it, and no create brings it in. A re-cut by the drain
overwrites that repo's entry (r2.D3, `tests/test_usualbranch.py`), and the reader takes only
a branch name (`merging.cut_from`)."""

import tempfile
import unittest
from pathlib import Path

from keel import board as board_module
from keel import merging
from keel.board import Board, Refused
from tests.test_requests import RequestKbCase

VALUE = '{"shop":"elsewhere"}'


class ThroughKbTest(RequestKbCase):
    def test_a_house_and_bosun_are_refused_setting_it(self):
        card = self.create()
        for who, env in (("a house", {"KEEL_CARD": card}), ("Bosun", {"KEEL_BOSUN": self.bosun})):
            with self.subTest(who):
                code, _, err = self.kb("set", card, f"options.cut_from={VALUE}", env=env)
                self.assertEqual(code, 1, who)
                self.assertIn("options.cut_from", err)
        self.assertNotIn("cut_from", self.board().get(card)["options"])

    def test_no_create_brings_it_in(self):
        code, _, err = self.kb("create", "--space", "personal", "--title", "x", "--option", f"cut_from={VALUE}")
        self.assertEqual(code, 1)
        self.assertIn("options.cut_from", err)


class OnTheBoardTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.board = Board(Path(tmp.name) / "board.db")
        self.addCleanup(self.board.close)
        self.card = self.board.create("personal", "a card", actor="human")

    def put(self, value: dict, actor: str):
        self.board.set_fields(self.card, {"options": {"cut_from": value}}, actor)

    def test_only_the_drain_writes_it(self):
        for actor in ("house", "bosun", "human", "voice", "cli"):
            with self.subTest(actor), self.assertRaisesRegex(Refused, "options.cut_from"):
                self.put({"shop": "elsewhere"}, actor)
        self.put({"shop": "main"}, "drain")
        self.assertEqual(self.board.get(self.card)["options"]["cut_from"], {"shop": "main"})

    def test_the_board_and_the_reader_name_one_option(self):
        self.assertEqual(board_module.CUT_FROM_OPTION, merging.CUT_FROM)


if __name__ == "__main__":
    unittest.main()
