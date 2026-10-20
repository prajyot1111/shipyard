"""The deck's renderers, run under node and read back (`tests/fixtures/deck-pane.js`).

`tests/test_deck_css.py` greps the page's source for what must and must not be in it; this
runs the page's own modules against a DOM stand-in (`tests/fixtures/deck-dom.js`) at a
phone width and at a desk width and checks what they DRAW: the card pane's order and its
action row, what the inspector lists, where Cards opens, what More leads with, Attention's
rows and the header's health dot. The fixture names every check it runs; this test fails
with the names of the ones that did not hold.
"""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("node"), "node is not on this machine")
class DeckPaneTest(unittest.TestCase):
    def test_the_renderers_draw_what_the_deck_says_they_draw(self):
        result = subprocess.run(
            ["node", str(ROOT / "tests" / "fixtures" / "deck-pane.js"), str(ROOT / "app")],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True}, result.stdout)


if __name__ == "__main__":
    unittest.main()
