"""Lane GRP, GR-5: the Reviews page draws a feature card's members and a held card's wait,
and the held card's one way out is Review now anyway (`tests/fixtures/review-groups.js`,
under node against the deck's DOM stand-in). Every pull request there is invented."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ReviewGroupsDeckTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_members_the_wait_line_and_review_now_anyway(self):
        done = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "review-groups.js"), str(ROOT / "app")],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        got = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertTrue(got.get("ok"), got.get("fails"))


if __name__ == "__main__":
    unittest.main()
