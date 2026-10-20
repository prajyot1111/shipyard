"""How work ships: Bosun's draft of a space's flow, shown back beside the one the space has
(keel/flowcards.py, c-678). The draft card is filed by the user's tap, Bosun writes the flow
in its own folder and stages the card, the Setup report draws it, and Adopt writes it. On a
real scratch install from `shipyard init`; no session is started and no remote is reached."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import actions, firstrun, flowcards, flows, onboarding, readiness
from keel import config as config_module
from keel.board import open_board
from tests.helpers import no_real_tools
from tests.test_installer import init

DRAFT = """name = "Staging first"
description = "Work goes to a staging branch first, and a release moves it to main."

[[branch]]
id = "card"
label = "card branch"
kind = "card"

[[branch]]
id = "base"
label = "{base}"
kind = "base"

[[branch]]
id = "live"
label = "the live site"
kind = "environment"

[[move]]
id = "land"
label = "Approve outcome"
from = "card"
to = "base"
by = "keel"
step = "land"
stages = ["review"]

[[move]]
id = "release"
label = "Release"
from = "base"
to = "live"
by = "colleague"
"""


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        no_real_tools(self)
        readiness.forget()
        self.addCleanup(readiness.forget)
        for name, value in (("keel.prereqs.gather", []), ("keel.readiness.serve_status", {"missing": True})):
            fake = mock.patch(name, return_value=value)
            fake.start()
            self.addCleanup(fake.stop)
        self.home = Path(tmp.name).resolve() / "install"
        self.assertEqual(init(self.home), 0)

    def cfg(self):
        return config_module.load(self.home / "config.toml", ensure=False)

    def act(self, body):
        cfg = self.cfg()
        with open_board(cfg) as board:
            return actions.act(cfg, board, body)

    def opened(self) -> str:
        return self.act({"verb": "setup.flow.draft", "space": "personal"})["card"]

    def drafted(self, card: str, text: str = DRAFT) -> Path:
        """Bosun's two moves on the card: building, then review with the flow written."""
        cfg = self.cfg()
        out = self.home / "builder" / "cards" / card / "flow.toml"
        with open_board(cfg) as board:
            board.stage(card, "building", "bosun")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text)
            board.stage(card, "review", "bosun", output_ref=str(out))
        return out

    def shown(self):
        cfg = self.cfg()
        with open_board(cfg) as board:
            return flowcards.shown(cfg, board, "personal")


class DraftCardTest(Case):
    def test_the_users_tap_files_a_card_that_waits_for_bosun(self):
        card = self.opened()
        cfg = self.cfg()
        with open_board(cfg) as board:
            found = board.get(card)
        self.assertEqual((found["stage"], found["space"]), ("inbox", "personal"))
        self.assertEqual(found["options"]["flow_proposal"], "personal")
        self.assertTrue(found["options"]["flow_draft"])
        out = self.home / "builder" / "cards" / card / "flow.toml"
        self.assertIn(str(out), found["brief"])
        self.assertIn(f"keel flow check {out} --space personal", found["brief"])
        self.assertIn(f"kb stage {card} review --output {out}", found["brief"])
        self.assertIn("This card is Bosun's. No session is started on it", found["brief"])

    def test_a_space_has_one_open_draft(self):
        card = self.opened()
        with self.assertRaisesRegex(actions.ActionError, f"{card} is already proposing the personal flow"):
            self.opened()

    def test_it_is_refused_for_a_space_that_is_not_there(self):
        with self.assertRaisesRegex(actions.ActionError, "there is no space 'nowhere'"):
            self.act({"verb": "setup.flow.draft", "space": "nowhere"})


class ShownTest(Case):
    def test_nothing_is_shown_with_no_draft(self):
        self.assertIsNone(self.shown())

    def test_a_card_bosun_has_not_finished_shows_no_flow_yet(self):
        card = self.opened()
        self.assertEqual(self.shown(), {"card": card, "stage": "inbox", "draft": True, "flow": None, "error": None})

    def test_a_draft_at_review_is_shown_as_the_deck_draws_a_flow(self):
        card = self.opened()
        self.drafted(card)
        found = self.shown()
        self.assertEqual((found["card"], found["stage"], found["error"]), (card, "review", None))
        self.assertEqual(found["flow"]["name"], "Staging first")
        self.assertEqual(found["flow"]["description"],
                         "Work goes to a staging branch first, and a release moves it to main.")
        self.assertEqual([m["id"] for m in found["flow"]["moves"]], ["land", "release"])

    def test_a_draft_that_does_not_check_says_why_and_draws_nothing(self):
        card = self.opened()
        self.drafted(card, DRAFT.replace('to = "live"', 'to = "nowhere"'))
        found = self.shown()
        self.assertIsNone(found["flow"])
        self.assertIn("nowhere", found["error"])

    def test_the_report_carries_it_per_space(self):
        card = self.opened()
        self.drafted(card)
        report = onboarding.report(self.cfg())
        self.assertEqual(report["spaces"]["personal"]["flow_draft"]["card"], card)
        self.assertEqual(report["spaces"]["personal"]["flow_draft"]["flow"]["name"], "Staging first")


class AdoptTest(Case):
    def test_adopt_writes_bosuns_draft_as_the_spaces_flow(self):
        card = self.opened()
        self.drafted(card)
        self.act({"verb": "setup.flow.adopt", "card": card})
        cfg = self.cfg()
        self.assertEqual(flows.space_file(cfg, "personal").read_text(), DRAFT)
        self.assertEqual(flows.of(cfg, cfg.spaces["personal"]).source, "space")
        with open_board(cfg) as board:
            self.assertEqual(board.get(card)["stage"], "done")
        self.assertIsNone(self.shown())


class StepTest(Case):
    def step(self):
        cfg = self.cfg()
        with open_board(cfg) as board:
            return next(s for s in firstrun.report(cfg, board)["steps"] if s["id"] == "defaults")

    def test_the_step_says_whether_each_space_shows_its_plans(self):
        step = self.step()
        self.assertIsNone(step["done"])
        self.assertEqual(step["plans"], {"personal": False})
        self.act({"verb": "setup.settings.save",
                  "changes": [{"table": "space", "space": "personal", "key": "autonomy", "value": "attended"}]})
        self.assertEqual(self.step()["plans"], {"personal": True})

    def test_the_step_is_headed_as_the_design_heads_it(self):
        step = self.step()
        self.assertEqual(step["headline"], "How does your team ship its work?")
        # c-758, the owner's word: only question 1 is asked of everyone, and the rest is optional
        self.assertIn("You answer question 1 here: which branches work starts from.", step["about"])
        # r1.F3: it says what question 1's Save does, since it is no Adopt
        self.assertIn("It applies when you press Save, to new cards only.", step["about"])
        # c-732: and that nothing changes before Adopt
        self.assertIn("nothing changes until you press Adopt.", step["about"])
        # fix check D8: a space with nothing to draw is promised no drawing
        self.assertIn("The rest is already set by what you chose, and the page shows it.", step["about"])
        self.assertNotIn("the drawing shows it", step["about"])


if __name__ == "__main__":
    unittest.main()
