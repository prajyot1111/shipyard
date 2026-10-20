"""The walk you read (Z1 and Z3 of lane Z, card c-453, visual only).

The walk showed its step as a raw line under the diagram. It is now a callout that flows out
of the lit node, placed from the laid-out coordinates on the side with room, and a caption
bar at the bottom on a phone or when the node is at the stage's edge. The callout and the
highlight are view state only (B3): nothing about stepping is ever a board op.
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
MODULE = APP / "ui.boardcallout.js"


@unittest.skipUnless(shutil.which("node"), "node is not on this machine")
class PlacementTest(unittest.TestCase):
    def test_the_callout_is_placed_off_its_node_and_the_keyboard_is_view_state(self):
        result = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "board-callout.js"),
                                 str(MODULE)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True}, result.stdout)


class ViewStateTest(unittest.TestCase):
    """B3: view state is never board ops. The module that steps the walk has no way to
    write: no request of any kind, and no call into the model's fold."""

    def test_the_callout_module_cannot_reach_the_board(self):
        source = MODULE.read_text()
        for needle in ("fetch(", "K.post", "XMLHttpRequest", "/api/", "sendBeacon",
                       "applyOp", "foldInto", "WebSocket"):
            self.assertNotIn(needle, source, f"{needle} in the walk's callout")


if __name__ == "__main__":
    unittest.main()
