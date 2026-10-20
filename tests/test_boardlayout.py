"""Which layout the board's diagram is drawn in (K1 to K3, 2026-09-24).

b-009 read cleanly top to bottom in the walk and, in full screen, came out folded into rows
with an edge between its groups routed round the whole drawing: `layoutBest` scored a layout
only on whether it fit. Fit is now the gate and a readability cost is the choice
(`app/ui.boardlayout.js`), the fold is for a simple chain, and the shape is kept across full
screen. The layout itself runs in the browser, so these run the page's own code under node,
against the vendored ELK.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
FIXTURES = ROOT / "tests" / "fixtures"


def run_node(*argv):
    result = subprocess.run(["node", *map(str, argv)], capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


@unittest.skipUnless(shutil.which("node"), "node is not on this machine")
class ReadabilityTest(unittest.TestCase):
    """K1 and K2 as pure functions: the cost's parts, the choice, the fold rule."""

    def test_the_cost_function_prices_each_way_a_drawing_is_hard_to_read(self):
        said = run_node(FIXTURES / "board-readability.js", APP / "ui.boardlayout.js")
        self.assertEqual(said, {"ok": True}, said)


@unittest.skipUnless(shutil.which("node"), "node is not on this machine")
class LayoutChoiceTest(unittest.TestCase):
    """The real layout on b-009's shape and on W1's chain, at the stages that matter."""

    def test_b009_is_never_looped_round_the_outside_and_the_chain_still_folds(self):
        said = run_node(FIXTURES / "board-layout.js", APP, FIXTURES / "board-b009.txt")
        self.assertTrue(said.get("ok"), said)
        self.assertEqual(said["seen"]["b009"]["1440x900"]["outside"], 0)
        self.assertEqual(said["seen"]["chain"]["page"], "RIGHT:folded")


@unittest.skipUnless(shutil.which("node"), "node is not on this machine")
class PlanLookTest(unittest.TestCase):
    """P2-1: a diagram in a plan wraps its labels whole, carries an icon only where the
    source names one, and is laid out for the column; a board with no look is untouched."""

    def test_the_plan_look_and_the_column_choice(self):
        said = run_node(FIXTURES / "plan-diagram.js", APP, FIXTURES / "board-b009.txt")
        self.assertTrue(said.get("ok"), said)



if __name__ == "__main__":
    unittest.main()
