"""Tests only, until the repo's file says how to run the app (c-678, decision `testsonly`).

A repo the install copied has a run rule only once its adopted CLAUDE.md has a "Run the
app:" line. Until then its sessions are told to run tests only, and, the part that is a
mechanism, a card on it cannot carry `options.browser`: the board refuses it at create and
at set. A repo outside the install's layout has no such rule and is left as it was."""

import tempfile
import unittest
from pathlib import Path

from keel import house, prompts, repocommands, tierrecord
from keel.board import Refused, open_board
from keel.config import Space
from tests.helpers import make_config, make_repo

TESTS_ONLY = "# api\n\n## Running the app\n- Sessions run tests only until this section says how to run the app.\n"
RUNS = "# api\n\n## Running the app\n- Run the app: `npm run dev -- --port 0`\n"


class Case(unittest.TestCase):
    def adopted(self, text: str) -> None:
        """The file as the user saved it: a line counts only from that text (review F3)."""
        self.tier.write_text(text)
        with open_board(self.cfg) as board:
            tierrecord.saved(board, self.tier, text)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        self.home = self.dir / "spaces" / "work" / "api"
        self.repo = make_repo(self.home / "repo")
        self.cfg = make_config(self.dir, repos={"keel": make_repo(self.dir / "elsewhere")})
        self.cfg.source = self.dir / "config.toml"
        self.cfg.spaces["work"] = Space(name="work", config_dir=self.dir / "cfg-work", repos={"api": self.repo},
                                        contract=None, adapter=None, house_review=False)
        self.tier = self.home / "CLAUDE.md"
        self.tier.write_text(TESTS_ONLY)


class RuleTest(Case):
    def test_a_copied_repo_has_a_run_rule_only_once_its_file_says_how(self):
        self.assertIs(repocommands.runs(self.cfg, "work", "api"), False)
        self.adopted(RUNS)
        self.assertIs(repocommands.runs(self.cfg, "work", "api"), True)
        self.assertEqual(repocommands.run_rule(self.cfg, "work", "api"), "npm run dev -- --port 0")

    def test_a_repo_outside_the_layout_has_no_rule_to_meet(self):
        self.assertIsNone(repocommands.runs(self.cfg, "personal", "keel"))
        self.assertIsNone(repocommands.runs(self.cfg, "work", None))


class BoardTest(Case):
    SAID = "api's CLAUDE.md does not say how to run the app yet, so a card on it cannot take the browser"

    def test_a_card_on_a_repo_with_no_run_rule_cannot_take_the_browser(self):
        with open_board(self.cfg) as board:
            with self.assertRaisesRegex(Refused, self.SAID):
                board.create("work", "look at the page", repo="api", options={"browser": True}, actor="human")
            card = board.create("work", "fix a test", repo="api", actor="human")
            with self.assertRaisesRegex(Refused, self.SAID):
                board.set_fields(card, {"options": {"browser": True}}, "human")
            self.assertNotIn("browser", board.get(card)["options"])

    def test_it_can_once_the_file_says_how_to_run_the_app(self):
        self.adopted(RUNS)
        with open_board(self.cfg) as board:
            card = board.create("work", "look at the page", repo="api", options={"browser": True}, actor="human")
            self.assertTrue(board.get(card)["options"]["browser"])

    def test_a_card_on_any_other_repo_is_as_it_was(self):
        with open_board(self.cfg) as board:
            card = board.create("personal", "look at the page", repo="keel", options={"browser": True}, actor="human")
            self.assertTrue(board.get(card)["options"]["browser"])
            errand = board.create("personal", "an errand", options={"browser": True}, actor="human")
            self.assertTrue(board.get(errand)["options"]["browser"])

    def test_a_card_moved_onto_such_a_repo_with_the_browser_is_refused_too(self):
        self.cfg.spaces["work"].repos["web"] = make_repo(self.dir / "web")
        with open_board(self.cfg) as board:
            card = board.create("work", "look at the page", repo="web", options={"browser": True}, actor="human")
            with self.assertRaisesRegex(Refused, self.SAID):
                board.set_fields(card, {"repo": "api"}, "human")


class BriefTest(Case):
    def card(self, **more):
        return dict({"id": "c-1", "space": "work", "repo": "api", "title": "A thing", "options": {}}, **more)

    def test_a_session_on_a_repo_with_no_run_rule_is_told_tests_only(self):
        said = house.app_block(self.cfg, self.card())
        self.assertIn("Run this repo's tests only.", said)
        self.assertIn("do not start the app", said)
        self.assertIn(str(self.tier), said)

    def test_a_session_on_a_repo_with_one_is_told_the_command(self):
        self.adopted(RUNS)
        said = house.app_block(self.cfg, self.card())
        self.assertIn("`npm run dev -- --port 0`", said)
        self.assertNotIn("tests only", said)

    def test_a_session_on_any_other_repo_is_told_nothing_of_it(self):
        self.assertIsNone(house.app_block(self.cfg, self.card(space="personal", repo="keel")))

    def test_the_block_is_part_of_what_the_session_can_do(self):
        text, _ = prompts.abilities(self.cfg, {}, run=lambda *a, **k: (_ for _ in ()).throw(OSError("no kb here")),
                                    space="work", app=house.app_block(self.cfg, self.card()))
        self.assertIn("### Running the app", text)


if __name__ == "__main__":
    unittest.main()
