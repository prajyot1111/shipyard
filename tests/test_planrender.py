"""The plan page's renderers, run under node and read back (`tests/fixtures/plan-render.js`).

The payload is the shape `GET /api/plan/<id>` answers, built from the sample plan by the
same parser and lint the route uses. What is held: the phone opens on what waits on him
with every recommendation already selected, his own pick reads as his, Read all is the
whole document, the desk puts the round beside it, nothing a house wrote becomes markup,
and a lint finding sits under the block it is about.
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from keel import planformat, planlint, planstate

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = (ROOT / "tests" / "fixtures" / "plan-sample.md").read_text().replace(
    "Does the outcome use the same page?", "Does the outcome use the same page? Recommend: yes.")


def payload() -> dict:
    doc = planformat.parse(SAMPLE)
    state = planstate.state_of([])
    return {"card": {"id": "c-900", "title": "t", "space": "personal", "stage": "planning",
                     "repo": "keel", "plan_ref": "/x/plan.md"},
            "gate": "plan", "doc_name": "plan", "doc": doc, "lint": planlint.lint(doc),
            "state": state, "round": planstate.summary(doc, state), "docs": ["plan"],
            "empty": None, "cost": {"bytes": len(SAMPLE)}, "receipt": None, "answerable": True}


@unittest.skipUnless(shutil.which("node"), "node is not on this machine")
class PlanRenderTest(unittest.TestCase):
    def test_the_plan_page_draws_what_it_says_it_draws(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload(), handle)
        try:
            result = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "plan-render.js"),
                                     str(ROOT / "app"), handle.name],
                                    capture_output=True, text=True, timeout=60)
        finally:
            Path(handle.name).unlink()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True}, result.stdout)


if __name__ == "__main__":
    unittest.main()


class FirstLoadTest(unittest.TestCase):
    """P4-7: the plan page's shell loads the core and the plan's renderers only; the board's
    drawing is fetched by `ui.planblocks.js` when the first diagram needs it."""


    def test_the_drawing_is_fetched_in_the_order_the_deck_loads_it(self):
        from keel import serve
        blocks = (ROOT / "app" / "ui.planblocks.js").read_text()
        wanted = re.search(r"var DRAWING = \[([^\]]+)\]", blocks).group(1)
        order = re.findall(r"'([^']+)'", wanted)
        self.assertEqual(order, ["/ui.boardlayout.js", "/ui.board.js", "/ui.planlook.js", "/ui.plandiagram.js"])
        for path in order:
            self.assertIn(path, serve.APP_FILES, f"{path} is not served")
