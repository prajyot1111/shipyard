"""The find system (lane FIND, 2026-09-24): one find bar on every deck page.

The engine is pure JavaScript (`app/ui.findcore.js`) and each page declares its facets,
sorts, views and view modes in one table (`app/ui.findpages.js`), so both are read under
node: the parser, the URL round trip, multi-select with counts, Include adding rather than
swapping, the saved views and every page's own table (`tests/fixtures/find-core.js`). The
component and the pages that draw it are read the same way against the deck's DOM stand-in
(`tests/fixtures/find-ui.js`). What only a browser can say (overflow inside a control, the
44px targets, the design budgets at 390, 900 and 1440) is `bin/keel-find-audit`, which the
fence keeps out of this suite because it starts a browser.
"""

import json
import shutil
import subprocess
import unittest

from keel import deckstate, deckviews, serve
from tests.helpers import ROOT

APP = ROOT / "app"
FIXTURES = ROOT / "tests" / "fixtures"


def node(script: str, *args: str) -> dict:
    result = subprocess.run(["node", str(FIXTURES / script), *args], capture_output=True,
                            text=True, timeout=60, check=False)
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return json.loads(result.stdout.strip().splitlines()[-1])


class TheEngine(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_parser_url_counts_include_views_and_page_tables(self):
        got = node("find-core.js", str(APP))
        self.assertEqual(got, {"ok": True}, got)


class ThePagesDrawIt(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_cards_and_the_board_list_through_the_bar(self):
        got = node("find-ui.js", str(APP))
        self.assertEqual(got, {"ok": True}, got)


class TheModulesAreServed(unittest.TestCase):
    NAMES = ("ui.findcore.js", "ui.findpages.js", "ui.find.js", "ui.find.css")

    def test_every_file_is_served_cached_and_loaded(self):
        # The page and the worker as the server sends them, filled from app/views.json (c-634).
        html = deckviews.rendered(APP, "index.html")
        sw = deckviews.rendered(APP, "sw.js")
        for name in self.NAMES:
            self.assertEqual(serve.APP_FILES.get("/" + name), name, name)
            self.assertTrue(f"'/{name}'" in sw or f'"/{name}"' in sw, f"{name} is not in the service worker's shell")
            self.assertIn('"/' + name + '"', html, f"{name} is not loaded by the page")


class TheCardsCountsLeaveReviewCardsOut(unittest.TestCase):
    """2026-09-24: a review card is listed on Reviews only; the space's Cards counts (the
    card count and the backlog the Now glance points at Cards for) leave it out, and the
    needs-you count keeps one at his gate, as Attention does."""

    @staticmethod
    def card(cid, review=False, **derived):
        base = {"archived": False, "needs_you": False, "backlog": False}
        return {"id": cid, "space": "work", "options": {"review_key": "api:1"} if review else {},
                "derived": base | derived}

    def test_the_counts(self):
        cards = [self.card("c-1"), self.card("c-2", backlog=True),
                 self.card("c-3", review=True, backlog=True), self.card("c-4", review=True, needs_you=True),
                 self.card("c-5", review=True)]
        self.assertEqual(deckstate.space_counts(cards, "work"), {"cards": 2, "needs_you": 1, "backlog": 1})
