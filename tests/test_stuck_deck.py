"""The stuck states outside setup, on the deck (c-678, `tests/fixtures/stuck-states.js`): a
blocked card's reading drawn as the stuck line with its fix, the services,
an unknown config key and the sign-in that ran out, under node against the DOM stand-in."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


class StuckStatesTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_each_stuck_state_says_what_happened_and_carries_its_fix(self):
        result = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "stuck-states.js"), str(APP)],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True}, result.stdout)

    def test_the_file_is_in_the_manifest_and_served(self):
        from keel import deckviews, serve
        scripts = json.loads((APP / "views.json").read_text())["scripts"]
        for name in ("ui.stuckcard.js", "ui.landpush.js"):
            with self.subTest(name):
                self.assertIn(name, scripts)
                self.assertEqual(serve.APP_FILES.get(f"/{name}"), name)
                self.assertIn(f'"/{name}"', deckviews.rendered(APP, "sw.js"))


if __name__ == "__main__":
    unittest.main()
