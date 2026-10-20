"""Pages that say what they need (c-631, c-628 S3).

Each deck view declares the readiness rows it needs in `VIEWS`, and `K.needs` draws what is
missing, what it unlocks and the step that sets it up. Held here: no view is hidden for a
missing adapter any more, every name a view needs is a readiness row, and the Setup link is
built in one place (`K.stepHref`, which opens the step in the stepper, c-632). `tests/fixtures/needs-deck.js` renders
the pages under node and names every check that did not hold.
"""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from keel import deckviews, readiness
from tests.test_deck_css import js_function

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


def app_sources() -> dict:
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(APP.glob("*.js"))}


class NeedsSourceTest(unittest.TestCase):

    def test_every_need_is_a_readiness_row(self):
        core = (APP / "ui.core.js").read_text(encoding="utf-8")
        # the views' needs are the manifest's rows (app/views.json, c-634)
        named = [name for view in deckviews.load(APP)["views"] for name in view.get("needs", [])]
        self.assertTrue(named)
        for name in named:
            self.assertIn(name, readiness.STEPS)
        unlocks = core.split("var UNLOCKS = {", 1)[1].split("};", 1)[0]
        for name in re.findall(r"^\s*(\w+):", unlocks, re.M):
            self.assertIn(name, readiness.STEPS)

    def test_the_setup_link_is_built_only_in_step_href(self):
        """c-632: it opens the step in the stepper now; nothing else spells the link."""
        for name, text in app_sources().items():
            if name == "ui.core.js":
                text = text.replace(js_function("ui.core.js", "stepHref"), "")
            self.assertNotIn("view=setup", text, name)
            self.assertNotIn("view=start", text, name)


class NeedsDeckTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_pages_draw_their_needs(self):
        result = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "needs-deck.js"), str(APP)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True}, result.stdout)


if __name__ == "__main__":
    unittest.main()
