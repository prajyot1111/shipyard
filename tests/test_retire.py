"""Lane RETIRE (RT-6): PR watch, the old review scanner, its inbox command, its lavish page and
the deck's PRs page are gone from Keel, and stay gone.

The replacements are live: a work pull request Keel's house built is a card in `shipping`
(`keel/shipping.py`), one that needs his review is a review card (`keel/reviewcards.py`),
and the fetcher's two settings are the space's own (`keel/reviewsettings.py`). What these
tests hold is that nothing in the repo reaches back for what was retired.
"""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from keel import adapters, config, deckdigest
from tests.helpers import TWO_MACHINE_TOML

ROOT = Path(__file__).resolve().parent.parent

class OneProviderRouteTest(unittest.TestCase):
    """The name-level guard (no file names a retired tool or the old route) lives with the
    work adapter, `packs/work/tests/test_retired.py`, because the names it greps for are
    the work tools' own and `make test`'s drift grep keeps those in the work pack."""

    def test_the_engine_knows_one_provider_route(self):
        self.assertEqual(adapters.PROVIDER_ROUTES, ("reviews",))
        self.assertEqual(deckdigest.PROVIDER_ROUTES, ("reviews",))
        self.assertNotIn("prs", deckdigest.SECTIONS)

    def test_the_retired_tools_history_is_still_served(self):
        """RT-4: nothing reads the two directories, but older cards link into them, so the
        deck still serves them (and `bin/keel-backup`'s helm set still keeps them)."""
        roots = [str(root) for root in config.load(TWO_MACHINE_TOML, ensure=False).artifact_roots]
        home = str(Path.home())
        for kept in ("/.claude/pr-watch/context", "/.claude/pr-reviews"):
            self.assertIn(home + kept, roots)


if __name__ == "__main__":
    unittest.main()
