"""What the sandbox end-to-end run of 2026-09-30 found on the deck (c-604).

The page's half runs under node (`tests/fixtures/deck-sandbox-run.js`): the create form's repo
chips and its close with a field focused (the removeChild error), a done card's words, the
header's Voice link, Resume house at an open plan gate, and `talk` split into two keys. The
server's half is here: a done card's refusal says where its worktree really is.
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from keel import house
from keel.board import Refused

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("node"), "node is not on this machine")
class DeckTest(unittest.TestCase):
    def test_the_page_draws_what_the_run_asked_for(self):
        result = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "deck-sandbox-run.js"), str(ROOT / "app")],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["fails"], [])


class DoneRefusalTest(unittest.TestCase):
    """A resume on a done card said "its worktree is gone" of a worktree the teardown kept."""

    def refusal(self, options: dict) -> str:
        with self.assertRaises(Refused) as caught:
            house.refuse_if_done({"id": "c-1", "stage": "done", "options": options})
        return str(caught.exception)

    def test_a_kept_worktree_is_named_as_kept(self):
        with tempfile.TemporaryDirectory() as kept:
            said = self.refusal({"worktree": kept})
        self.assertIn(f"its worktree is kept at {kept}", said)
        self.assertNotIn("gone", said)

    def test_a_reaped_worktree_is_gone_and_none_is_none(self):
        self.assertIn("its worktree is gone", self.refusal({"worktree": "/nowhere/c-1"}))
        self.assertIn("it has no worktree", self.refusal({}))


if __name__ == "__main__":
    unittest.main()
