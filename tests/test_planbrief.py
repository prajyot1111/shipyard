"""The plan pages in a house's brief (P4-1): what every NEW plan and outcome is told.

With `[keel] plan_pages` on (the default and keel.toml) the brief carries the format card
generated from the parser, the lint to run before a stage, the board rule and Ask, and
none of lavish's lines; the record starts as an outcome in the format. With it off the
brief is the plan styles, word for word as the contract said them.
"""

import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from keel import config as config_module, house, outcomeboards, planbrief, plancard, planformat, planlint, prompts
from keel.board import Board
from tests.helpers import make_config

ROOT = Path(__file__).resolve().parent.parent


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.addCleanup(self.tmp.cleanup)

    def abilities(self, **kwargs) -> str:
        with mock.patch.object(prompts, "board_verbs", return_value=("- `kb show <id>`: x", None)):
            return prompts.abilities(self.cfg, {}, **kwargs)[0]



class OnTest(Case):

    def test_a_fenced_house_is_given_the_format_and_not_the_surface_it_cannot_open(self):
        text = self.abilities(plan_pages=True, restricted=True, tools="Read,Write,Edit,Bash")
        self.assertIn(planbrief.HEADING, text)
        self.assertIn(planbrief.FENCED_FORMAT.strip(), text)
        self.assertNotIn(prompts.FENCED_SURFACE.strip(), text)

    def test_a_house_with_no_shell_writes_no_plan_and_is_told_nothing_about_one(self):
        text = self.abilities(plan_pages=True, tools="Read,Write")
        self.assertNotIn(planbrief.HEADING, text)


class LiteralBoardPushTest(Case):
    """r-56 (c-723): the house guard reads a `push` word beside a word the shell fills in as
    git through a variable, so the brief's own board command was refused when the house ran
    it as the brief wrote it. The brief knows the card and its directory when it is written,
    so every board push it shows names them literally."""

    def test_every_board_push_a_house_is_sent_names_the_card_and_its_folder_literally(self):
        """Every prompt builder that sends a house board push text (c-723 fix check): the
        brief's abilities, for a house with a shell and a fenced one, and the outcome boards
        backfill (`outcomeboards.prompt_for`), which is sent to a house outside the brief."""
        folder = self.cfg.card_dir("c-12")
        env = {"KEEL_CARD": "c-12", "KEEL_CARD_DIR": str(folder)}
        sent = {}
        for restricted, tools in ((False, None), (True, "Read,Write,Edit,Bash")):
            with mock.patch.object(prompts, "board_verbs", return_value=("- `kb show <id>`: x", None)):
                sent[f"abilities, restricted={restricted}"] = prompts.abilities(
                    self.cfg, env, plan_pages=True, restricted=restricted, tools=tools)[0]
        pick = {"card": "c-12", "stage": "review", "title": "A card", "host": "mac",
                "reasons": ["no Code flow board"], "plan_boards": [], "folder": str(folder)}
        sent["outcome boards backfill"] = outcomeboards.prompt_for(pick)
        for name, text in sent.items():
            pushes = [line for line in text.splitlines() if "board push --" in line]
            with self.subTest(prompt=name):
                self.assertTrue(pushes, text)
                for line in pushes:
                    self.assertNotIn("$", line)
                    self.assertIn("--card c-12", line)
                self.assertTrue(any(f"--file {folder}/" in line for line in pushes), pushes)


class PaneTest(unittest.TestCase):
    def test_the_pane_shows_the_copy_block_of_a_format_outcome_whole(self):
        from keel import deckstate
        text = ("---\nkind: outcome\ncard: c-1\n---\n# c-1 t\n\n## PR body\n\n"
                "````copy PR body\n## Intent\nWhy.\n\n## Risk\nLow.\n````\n\n## Evidence\n\nx\n")
        self.assertEqual(deckstate.pr_body(text), "## Intent\nWhy.\n\n## Risk\nLow.")
        self.assertEqual(deckstate.pr_body("## PR body\n\nplain\n"), "plain")



class BriefTest(Case):
    def setUp(self):
        super().setUp()
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        self.card_id = self.board.create("personal", "Title: with a colon", repo="keel", actor="human")

    def brief(self):
        with mock.patch.object(house.prompts, "board_verbs", return_value=("- `kb show <id>`: x", None)):
            return house.brief_for(self.cfg, self.board.get(self.card_id))

    def test_the_whole_brief_carries_the_card_when_the_switch_is_on(self):
        self.assertIn(plancard.format_card(), self.brief())
        self.cfg.plan_pages = False
        self.board.set_fields(self.card_id, {"title": "again"}, "human")
        self.assertNotIn(plancard.format_card(), self.brief())

    def test_the_record_starts_as_an_outcome_the_stage_will_lint(self):
        self.brief()
        text = (self.cfg.card_dir(self.card_id) / "context.md").read_text()
        doc = planformat.parse(text, "context.md")
        self.assertTrue(doc["format"])
        self.assertEqual((doc["kind"], doc["meta"]["card"], doc["meta"]["title"]),
                         ("outcome", self.card_id, "Title: with a colon"))
        for heading in house.CONTEXT_SECTIONS:
            self.assertIn(f"## {heading}\n", text)
        refused = planlint.lint(doc)
        self.assertFalse(refused["ok"], "an empty record does not pass the review gate")
        self.assertTrue(all(f["rule"] == "C26" for f in refused["findings"]))


class ExplainTest(unittest.TestCase):
    """c-719: an outcome explains what was actually done; the five sections are its frame,
    and a board is used only where it explains better than prose (the owner's word: no new
    mandatory board)."""

    SAYS = ("explains what was actually done", "short frame", "sections of your own",
            "only where it explains better than prose", "a sentence or two saying what it shows")

    def test_the_brief_says_an_outcome_explains_what_was_done(self):
        text = " ".join(planbrief.plan_block(True).split())
        for words in self.SAYS:
            self.assertIn(words, text)

    def test_the_card_the_spec_and_the_contract_say_it_too(self):
        for text in (plancard.format_card(), (ROOT / "docs" / "plan-format.md").read_text(),
                     (ROOT / "etc" / "house-contract.md").read_text()):
            self.assertIn("explains what was actually done", " ".join(text.split()))

    def test_the_record_it_starts_with_says_it_where_the_user_never_reads_it(self):
        text = planbrief.context_skeleton({"id": "c-1", "title": "t"}, True)
        self.assertIn("short frame", text)
        doc = planformat.parse(text, "context.md")
        self.assertNotIn("frame", repr(doc["blocks"]), "the guidance is a comment, never drawn")
        self.assertTrue(all(f["rule"] == "C26" for f in planlint.lint(doc)["findings"]))


if __name__ == "__main__":
    unittest.main()
