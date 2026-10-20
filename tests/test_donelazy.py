"""c-549: pages draw live cards first and bring done cards in behind the draw, and the voice
page stops downloading itself and the whole board.

- `?part=live` is the scope without its done cards and with every top-level list; `?part=done`
  is those cards alone, tagged on what they are, so a refresh that moved none is a 304.
- A done card that needs him, has a house, is blocked, is a review card or is the open card
  stays in the live part. The two parts are the whole scope, with no card in both.
- A bare `/api/state`, and a scope with no part, are what they were.
- A segment app's files other than its shell are gzipped, tagged and revalidated.
- The page's half runs under node in `tests/fixtures/deck-done.js`.
"""

import gzip
import json
import shutil
import subprocess
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from keel import deckstate, serve
from tests.test_serve import DeckCase, ServerCase
from tests.test_tracking_close import finish

ROOT = Path(__file__).resolve().parent.parent


def seed_done(case) -> None:
    """Two done cards, a done review card, and a done card that is blocked."""
    b = case.board
    case.done = []
    for title in ("shipped one", "shipped two"):
        card = b.create("personal", title, actor="human", repo="keel")
        b.stage(card, "assigned", "human")
        finish(b, card)
        case.done.append(card)
    case.posted = b.create("work", "a posted review", actor="human", repo="api",
                           options={"review_key": "api#7"})
    b.stage(case.posted, "assigned", "human")
    finish(b, case.posted)
    case.stuck = b.create("personal", "done but blocked", actor="human", repo="keel")
    b.stage(case.stuck, "assigned", "human")
    finish(b, case.stuck)
    b.block(case.stuck, "something after done", "drain")


class PartCase(DeckCase):
    def seed(self):
        super().seed()
        seed_done(self)

    def doc(self, scope="deck", asked=None):
        return deckstate.build(self.cfg, self.board, rows=self.rows(), scope=scope, asked=asked)


class PartTest(PartCase):
    def test_the_two_parts_are_the_whole_scope_with_no_card_in_both(self):
        doc = self.doc()
        live, done = deckstate.part_of(doc, "live"), deckstate.part_of(doc, "done")
        live_ids, done_ids = {c["id"] for c in live["cards"]}, {c["id"] for c in done["cards"]}
        self.assertFalse(live_ids & done_ids)
        self.assertEqual(live_ids | done_ids, {c["id"] for c in doc["cards"]})
        self.assertEqual(done_ids, set(self.done))
        self.assertEqual((live["scope"]["part"], done["scope"]["part"]), ("live", "done"))
        self.assertNotIn("part", doc["scope"], "the cached document is never changed")
        self.assertEqual(len(doc["cards"]), len(live_ids) + len(done_ids))

    def test_the_live_part_keeps_every_top_level_list_and_the_done_part_none(self):
        doc = self.doc()
        live, done = deckstate.part_of(doc, "live"), deckstate.part_of(doc, "done")
        for key in doc:
            if key != "cards" and key != "scope":
                self.assertEqual(live[key], doc[key], key)
        self.assertEqual(set(done), {"now", "cards", "scope"})

    def test_a_done_card_anything_reads_stays_live(self):
        live = {c["id"] for c in deckstate.part_of(self.doc(), "live")["cards"]}
        self.assertIn(self.posted, live, "Reviews lists a posted review by default")
        self.assertIn(self.stuck, live, "a blocked card is on Attention")
        asked = self.done[0]
        live = {c["id"] for c in deckstate.part_of(self.doc(asked=asked), "live", asked)["cards"]}
        self.assertIn(asked, live, "the page's open card")
        view = next(c for c in self.doc()["cards"] if c["id"] == self.done[1])
        self.assertTrue(deckstate.in_done_part(view))
        for extra in ({"house": {"status": "idle"}}, {"derived": dict(view["derived"], needs_you=True)}):
            self.assertFalse(deckstate.in_done_part(dict(view, **extra)), extra)

    def test_the_console_scope_splits_the_same_way(self):
        # The Bosun page's scope is the cards Bosun builds (c-591): builder mode, a personal
        # card with a repo.
        b = self.board
        b.builder = True
        mine = b.create("personal", "a card Bosun builds", actor="human", repo="keel")
        b.stage(mine, "assigned", "human")
        finish(b, mine)
        doc = self.doc("console")
        self.assertIn(mine, {c["id"] for c in deckstate.part_of(doc, "done")["cards"]})
        self.assertNotIn(mine, {c["id"] for c in deckstate.part_of(doc, "live")["cards"]})


class PartWireTest(ServerCase):
    def seed(self):
        super().seed()
        seed_done(self)

    def get(self, path, headers=None):
        request = urllib.request.Request(self.base + path)
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, dict(error.headers), error.read()

    def ids(self, body):
        return {c["id"] for c in json.loads(body)["cards"]}

    def test_the_parts_travel_and_a_bare_state_is_unchanged(self):
        with mock.patch.object(deckstate.harness, "agents_across", return_value=self.rows()):
            _, _, whole = self.get("/api/state?scope=deck")
            _, live_head, live = self.get("/api/state?scope=deck&part=live")
            _, done_head, done = self.get("/api/state?scope=deck&part=done")
            self.assertEqual(self.ids(live) | self.ids(done), self.ids(whole))
            self.assertEqual(self.ids(done), set(self.done))
            self.assertNotIn("part", json.loads(whole)["scope"])
            self.assertIn("health", json.loads(live), "the live part is the page's whole document")
            self.assertNotEqual(live_head["ETag"], done_head["ETag"])
            _, _, bare = self.get("/api/state")
            self.assertEqual(json.loads(bare)["scope"], {"name": "all", "archived": True, "card": None, "steps": True})
            _, _, ignored = self.get("/api/state?part=live")
            self.assertEqual(self.ids(ignored), self.ids(bare), "a part means nothing without a scope")

    def test_the_done_part_is_a_304_until_a_done_card_moves(self):
        zipped = {"Accept-Encoding": "gzip"}
        with mock.patch.object(deckstate.harness, "agents_across", return_value=self.rows()):
            status, head, body = self.get("/api/state?scope=deck&part=done", zipped)
            self.assertEqual((status, head.get("Content-Encoding")), (200, "gzip"))
            self.assertEqual({c["id"] for c in json.loads(gzip.decompress(body))["cards"]}, set(self.done))
            tag, live_tag = head["ETag"], self.get("/api/state?scope=deck&part=live", zipped)[1]["ETag"]
            # a write to a live card moves the live part and not the done part
            self.board.note(self.inbox, "a live card moved", "human")
            self.server.RequestHandlerClass.deck.drop()
            status, head, body = self.get("/api/state?scope=deck&part=done", dict(zipped, **{"If-None-Match": tag}))
            self.assertEqual((status, body), (304, b""))
            status, _, _ = self.get("/api/state?scope=deck&part=live", dict(zipped, **{"If-None-Match": live_tag}))
            self.assertEqual(status, 200)
            # a card reaching done moves the done part
            b = self.board
            b.stage(self.inbox, "assigned", "human")
            finish(b, self.inbox)
            self.server.RequestHandlerClass.deck.drop()
            status, head, body = self.get("/api/state?scope=deck&part=done", dict(zipped, **{"If-None-Match": tag}))
            self.assertEqual(status, 200)
            self.assertIn(self.inbox, {c["id"] for c in json.loads(gzip.decompress(body))["cards"]})

    def test_a_segment_apps_files_are_kept_and_its_shell_is_not(self):
        app = self.cfg.segments_dir / "alpha" / "app"
        (app / "app.js").write_text("console.log('alpha');\n" * 100)
        (app / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 2000)
        status, head, body = self.get("/segments/alpha/app/app.js", {"Accept-Encoding": "gzip"})
        self.assertEqual((status, head.get("Content-Encoding"), head["Cache-Control"]), (200, "gzip", serve.REVALIDATE))
        self.assertEqual(gzip.decompress(body), (app / "app.js").read_bytes())
        status, _, body = self.get("/segments/alpha/app/app.js", {"Accept-Encoding": "gzip", "If-None-Match": head["ETag"]})
        self.assertEqual((status, body), (304, b""))
        status, head, _ = self.get("/segments/alpha/app/icon.png", {"Accept-Encoding": "gzip"})
        self.assertEqual((status, head.get("Content-Encoding"), head["Cache-Control"]), (200, None, serve.REVALIDATE))
        self.assertIn("ETag", head)
        status, head, _ = self.get("/segments/alpha/app/")
        self.assertEqual((status, head["Cache-Control"]), (200, serve.NO_STORE))
        self.assertIn("Set-Cookie", head, "the shell still hands out the page's cookie")


class VoiceDeskTest(unittest.TestCase):
    def test_the_desk_column_reads_the_live_part_conditionally(self):
        source = (ROOT / "segments" / "voice" / "app" / "voice.desk.js").read_text()
        self.assertIn('"/api/state?scope=deck&part=live"', source)
        self.assertNotIn('fetch("/api/state"', source, "never the whole board")
        self.assertIn("If-None-Match", source)


@unittest.skipUnless(shutil.which("node"), "node is not on this machine")
class DonePagesTest(unittest.TestCase):
    def test_the_page_draws_live_first_and_merges_done_behind_it(self):
        result = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "deck-done.js"), str(ROOT / "app")],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1]), {"ok": True})


if __name__ == "__main__":
    unittest.main()
