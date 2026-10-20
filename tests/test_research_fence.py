"""A research card's house cannot push or open a pull request (lane L review, item 4): the
adapter supplies extra deny entries for the card and `settings_for` merges them in; and a
house cannot change its own kind to get out from under them."""

import json
import tempfile
import unittest
from pathlib import Path

from keel import adapters, house
from keel.board import Board, Refused
from tests.helpers import make_config

DENY_VERB = """#!/bin/sh
card=$(cat)
case "$card" in
  *'"kind": "research"'*) echo '["Bash(git push:*)", "Bash(*adapters/work/pr*)"]' ;;
  *) echo '[]' ;;
esac
"""


class ExtraDenyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        verb = self.cfg.adapters_dir / "work" / "deny"
        verb.parent.mkdir(parents=True, exist_ok=True)
        verb.write_text(DENY_VERB)
        verb.chmod(0o755)
        self.board = Board(self.cfg.db_path)

    def tearDown(self):
        self.board.close()
        self.tmp.cleanup()

    def card(self, kind: str) -> dict:
        card_id = self.board.create("work", "look into it", repo="api", actor="human",
                                    options={"kind": kind})
        return self.board.get(card_id)

    def deny_of(self, card: dict) -> list[str]:
        return json.loads(house.settings_for(self.cfg, card).read_text())["permissions"]["deny"]

    def test_a_research_card_gets_the_adapters_extra_deny_entries(self):
        deny = self.deny_of(self.card("research"))
        self.assertIn("Bash(git push:*)", deny)
        self.assertIn("Bash(*adapters/work/pr*)", deny)
        self.assertIn("mcp__claude-in-chrome", deny, "the space's own deny list stays")

    def test_any_other_kind_gets_none(self):
        self.assertNotIn("Bash(git push:*)", self.deny_of(self.card("feature")))

    def test_a_space_without_the_verb_gets_none(self):
        (self.cfg.adapters_dir / "work" / "deny").unlink()
        self.assertEqual(adapters.extra_deny(self.cfg, self.card("research")), [])

    def test_a_broken_verb_refuses_rather_than_starting_an_unfenced_house(self):
        (self.cfg.adapters_dir / "work" / "deny").write_text("#!/bin/sh\necho oops\n")
        with self.assertRaises(adapters.AdapterError):
            adapters.extra_deny(self.cfg, self.card("research"))


class KindGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.board = Board(Path(self.tmp.name) / "board.db")
        self.card = self.board.create("work", "look into it", repo="api", actor="human",
                                      options={"kind": "research"})

    def tearDown(self):
        self.board.close()
        self.tmp.cleanup()

    def test_a_house_cannot_change_its_own_kind(self):
        with self.assertRaisesRegex(Refused, "options.kind"):
            self.board.set_fields(self.card, {"options": {"kind": "feature"}}, "house")
        self.assertEqual(self.board.get(self.card)["options"]["kind"], "research")

    def test_he_still_can(self):
        self.board.set_fields(self.card, {"options": {"kind": "feature"}}, "human")
        self.assertEqual(self.board.get(self.card)["options"]["kind"], "feature")


if __name__ == "__main__":
    unittest.main()
