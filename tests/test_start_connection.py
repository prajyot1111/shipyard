"""Choosing a connection, and the page that follows from it (c-758).

The two first-run screens under node (`tests/fixtures/start-connection.js`): Where finished
work goes as four choices in each state a new user meets it, How work ships opening with
what was chosen, and a connection's own step after them. Beside them, what the server hands
those pages, read through the reports the pages read (`firstrun.report`, the readiness rows,
the settings report, the flow as the state carries it), on a scratch install from
`shipyard init`: never a constant against itself."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import actions, firstrun, flows, readiness, settings
from keel import config as config_module
from keel.board import open_board
from tests.helpers import no_real_tools
from tests.test_installer import init

ROOT = Path(__file__).resolve().parent.parent
OTHER_WORDS = re.compile(r"\b(pack|packs|integration|integrations)\b")


class ScreensTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_two_screens_draw_each_state_as_a_new_user_meets_it(self):
        result = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "start-connection.js"), str(ROOT / "app")],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True}, result.stdout)


class HandedOutTest(unittest.TestCase):
    """What the two steps are handed, on an install with one connection turned on."""

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

    def steps(self):
        cfg = self.cfg()
        readiness.forget()
        with open_board(cfg) as board:
            return {step["id"]: step for step in firstrun.report(cfg, board)["steps"]}

    def test_how_work_ships_says_it_follows_from_the_step_before(self):
        self.assertTrue(self.steps()["defaults"]["about"].startswith(
            "This page follows from the one before: it starts from what you chose there."))

    def test_how_work_ships_says_only_question_one_is_asked_and_the_rest_is_optional(self):
        step = self.steps()["defaults"]
        self.assertIn("You answer question 1 here", step["about"])
        self.assertIn("already set by what you chose", step["about"])
        self.assertIn("Changing it is optional", step["about"])
        self.assertNotIn("a question at a time", step["about"])
        self.assertEqual(step["why"], "question 1 is answered here; the rest is already set by what you chose, "
                                      "and changing it is optional")
        self.assertIsNone(step["done"], "nothing to check: Next or Keep is the way on, never a conversation")

    def test_where_finished_work_goes_says_it_picks_the_tool_and_names_the_page_for_the_process(self):
        about = self.steps()["integrations"]["about"]
        self.assertIn("This step picks the tool that carries work to your team's code host.", about)
        self.assertIn("Your team's process (which branches, who approves) is not asked here: that is How work ships, "
                      "a later step.", about)

    def test_no_question_of_how_work_ships_repeats_the_step_befores_headline(self):
        steps = self.steps()
        asked = [one["ask"] for one in steps["defaults"]["asks"]]
        self.assertEqual(len(asked), 5)
        self.assertNotIn(steps["integrations"]["headline"], asked)

    def test_everything_the_two_steps_are_handed_says_connection(self):
        """One word on the two steps: the step texts, the step's reason, the rows of a space
        on a connection and of one on none, Turn on's and Turn off's answers, the two settings
        the step draws, and a connection's own step, as the pages are handed them."""
        on = self.act({"verb": "setup.pack.on", "pack": "sandbox", "space": "personal"})
        self.act({"verb": "setup.space.add", "space": "team"})
        steps = self.steps()
        cfg = self.cfg()
        ready = readiness.build(cfg)
        said = {"Turn on": on["note"]}
        for name in ("integrations", "defaults", "sandbox:try"):
            said[f"{name} about"] = steps[name]["about"]
        said["integrations why"] = steps["integrations"]["why"]
        for space in ("personal", "team"):
            for cap in ("tracker", "codehost", "reviews", "ci"):
                said[f"{space} {cap}"] = ready["spaces"][space][cap]["why"]
        helps = {row["id"]: row["help"] for row in settings.report(cfg)["schema"]}
        for key in ("space.fetch_before_work", "space.offer_push", "space.review_scan"):
            said[key] = helps[key]
        said["Turn off"] = self.act({"verb": "setup.pack.off", "space": "personal"})["note"]
        for where, text in said.items():
            self.assertNotRegex(text, OTHER_WORDS, where)
        self.assertEqual(said["Turn on"], "Work for personal now goes through sandbox.")
        self.assertEqual(said["team codehost"], "no connection is turned on for team")
        self.assertEqual(said["sandbox:try about"], "From the sandbox connection, for personal.")

    def test_a_connections_own_step_says_which_step_it_follows(self):
        """r1.F5: its screen sums its checks up only when it follows Where finished work goes."""
        self.act({"verb": "setup.pack.on", "pack": "sandbox", "space": "personal"})
        self.assertEqual(self.steps()["sandbox:try"]["after"], "integrations")

    def test_the_flow_a_space_on_github_is_handed_says_who_merges_as_the_connection_does(self):
        """The GitHub connection says "You merge on GitHub."; the flow the state carries for a
        space on it says the merge may be the user's, on the connection's own name for its host."""
        self.act({"verb": "setup.pack.on", "pack": "github", "space": "personal"})
        cfg = self.cfg()
        drawn = flows.drawn(cfg, cfg.spaces["personal"])
        merge = next(move for move in drawn["moves"] if move["id"] == "merge")
        self.assertEqual((drawn["name"], merge["by"]), ("General", "colleague"))
        self.assertEqual(merge["about"], "You or a teammate review and merge the pull request on GitHub. Shipyard never "
                                         "merges it. The card is done once it is merged.")
        self.assertNotIn("colleague", drawn["description"])


if __name__ == "__main__":
    unittest.main()
