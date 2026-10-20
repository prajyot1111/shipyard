"""The first-run stepper's deck view (c-632, `app/ui.start.js`): a fresh install with no
`?view=` lands on Start and a finished one stays on Now, Next is off on a required step until it
is done, Skip sends `firstrun.skip`, `K.openStep` routes to the step for a space, a needs
panel's Set it up opens it, and the file is registered everywhere the deck looks. One node
run over the real modules, as the other deck tests do."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


class StartDeckTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_stepper_routes_and_draws_its_screen(self):
        result = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "start-deck.js"), str(APP)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True}, result.stdout)

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_a_setup_action_never_blanks_the_screen_and_reads_the_verdict_after(self):
        """c-729: the screen is kept and the row marked working through the action and a
        restart, the report is asked for until the new process answers, then the state."""
        result = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "start-working.js"), str(APP)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True}, result.stdout)

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_a_reopened_event_stream_reads_the_state(self):
        """c-729: after a deck restart the stream comes back and nothing else says `state`."""
        result = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "deck-reopen.js"), str(APP)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True}, result.stdout)

    def test_the_route_is_registered_everywhere_the_deck_looks(self):
        """The manifest's row, its rail rule, and what the server draws from it (c-634)."""
        from keel import deckviews, serve
        row = next(v for v in deckviews.load(APP)["views"] if v["key"] == "start")
        self.assertEqual((row["name"], row["render"], row["script"], row["rail"]),
                         ("Start", "viewStart", "ui.start.js", "until-finished"))
        self.assertEqual(serve.APP_FILES.get("/ui.start.js"), "ui.start.js")
        self.assertIn('"/ui.start.js"', deckviews.rendered(APP, "sw.js"))
        self.assertIn('<script src="/ui.start.js">', deckviews.rendered(APP, "index.html"))
        # the Check this computer screen, its own file loaded before the stepper (c-679)
        page = deckviews.rendered(APP, "index.html")
        self.assertEqual(serve.APP_FILES.get("/ui.startchecks.js"), "ui.startchecks.js")
        self.assertIn('"/ui.startchecks.js"', deckviews.rendered(APP, "sw.js"))
        self.assertLess(page.index('<script src="/ui.startchecks.js">'), page.index('<script src="/ui.start.js">'))


if __name__ == "__main__":
    unittest.main()
