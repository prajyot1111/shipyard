"""The first run's screens under node (c-678, `tests/fixtures/start-steps.js`): one block per
screen of the first-run design, each drawn from a state and a Setup report as the server
gives them and read back. The frame the screens sit in is `tests/test_start_deck.py`; both
build their page with `tests/fixtures/start-page.js`.

Every screen that is its own file (`app/ui.signin.js` and the `app/ui.start*.js` files) is
listed in the deck's manifest before `ui.start.js`, which reads it, and is served."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
# The screens `ui.start.js` reads from their own files, in the order the manifest loads them.
SCREENS = ("ui.signin.js", "ui.startchecks.js", "ui.startbosun.js", "ui.startrepos.js", "ui.startmemory.js", "ui.startdrafts.js",
           "ui.startlands.js", "ui.startships.js", "ui.startbrowser.js",
           "ui.startbackup.js", "ui.startcard.js", "ui.startdone.js")


class StartStepsTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_each_screen_draws_what_the_design_says(self):
        result = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "start-steps.js"), str(APP)],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True}, result.stdout)

    def test_every_screen_file_is_loaded_before_the_stepper_and_served(self):
        from keel import deckviews, serve
        scripts = json.loads((APP / "views.json").read_text())["scripts"]
        page = deckviews.rendered(APP, "index.html")
        for name in SCREENS:
            with self.subTest(name):
                self.assertIn(name, scripts)
                self.assertLess(scripts.index(name), scripts.index("ui.start.js"))
                self.assertEqual(serve.APP_FILES.get(f"/{name}"), name)
                self.assertIn(f'"/{name}"', deckviews.rendered(APP, "sw.js"))
                self.assertLess(page.index(f'<script src="/{name}">'), page.index('<script src="/ui.start.js">'))

    def test_the_fixtures_load_every_script_of_the_manifest_the_stepper_reads(self):
        """A screen file that is in the manifest and not in the fixtures' module list would be
        drawn by nothing under test."""
        helper = (ROOT / "tests" / "fixtures" / "start-page.js").read_text()
        for name in SCREENS:
            self.assertIn(f"'{name}'", helper, f"{name} is not loaded by tests/fixtures/start-page.js")


if __name__ == "__main__":
    unittest.main()
