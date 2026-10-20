"""c-540: Keel and Bosun load fast, and a sent-back tracking card can reach his gate again.

- A page asks `/api/state?scope=deck|bosun`: only the cards it draws, each brief clipped,
  while every top-level list stays the whole board's. A bare `/api/state` is unchanged.
- The state and a card's detail are gzipped for a client that takes gzip, tagged per scope
  and encoding, and an unchanged one is a 304.
- The page's own files carry an ETag and `no-cache`, so a switch between the two PWAs costs
  a 304 per file rather than every script again, and a deploy still shows at once.
- r-19: a tracking card he sent back with every slice done says `regate`, and the deck's
  Back to your gate tap brings it to his outcome gate, which closes it.
"""

import gzip
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from keel import actions, adapters, artifacts, deckstate, harness, readings, serve
from keel.board import Board
from tests.test_card_tips import source
from tests.test_deck_css import js_function
from tests.test_serve import DeckCase, ServerCase
from tests.test_tracking_close import finish
from tests.test_drain import DrainCase

LONG = "word " * 300


def close_stamp(deck):
    if deck.stamp_conn is not None:
        deck.stamp_conn.close()


def seed_scopes(case) -> None:
    """An archived card, a card with a long brief, one carrying the retired driver option,
    and one Bosun builds."""
    b = case.board
    case.old = b.create("personal", "put away", actor="human", brief=LONG, options={"archived": True})
    case.long = b.create("personal", "a long brief", actor="human", brief=LONG)
    case.driven = b.create("personal", "Bosun drives this", actor="human", options={"driver": "bosun"})
    # builder mode (c-591): a personal card with a repo is Bosun's to build
    b.builder = True
    b.builds = frozenset({'keel'})
    case.built = b.create("personal", "Bosun builds this", actor="human", repo="keel")


class ScopeCase(DeckCase):
    def seed(self):
        super().seed()
        seed_scopes(self)

    def doc(self, scope=None, archived=False):
        return deckstate.build(self.cfg, self.board, rows=self.rows(), scope=scope, archived=archived)


class ScopedStateTest(ScopeCase):
    def test_a_bare_state_is_the_whole_board_as_before(self):
        doc = self.doc()
        ids = {c["id"] for c in doc["cards"]}
        self.assertIn(self.old, ids)
        long = next(c for c in doc["cards"] if c["id"] == self.long)
        self.assertEqual(long["brief"], LONG)
        self.assertNotIn("brief_clipped", long)
        self.assertEqual(doc["scope"], {"name": "all", "archived": True, "card": None, "steps": True})

    def test_the_deck_scope_leaves_archived_out_and_clips_briefs(self):
        doc = self.doc("deck")
        ids = {c["id"] for c in doc["cards"]}
        self.assertNotIn(self.old, ids)
        self.assertIn(self.long, ids)
        long = next(c for c in doc["cards"] if c["id"] == self.long)
        self.assertEqual(len(long["brief"]), deckstate.BRIEF_CHARS)
        self.assertTrue(long["brief_clipped"])
        self.assertIn(self.old, {c["id"] for c in self.doc("deck", archived=True)["cards"]})

    def test_every_top_level_list_is_the_whole_boards_in_every_scope(self):
        whole = self.doc()
        for scope in deckstate.SCOPES:
            doc = self.doc(scope)
            for key in ("needs_you", "queue", "backlog", "houses", "running", "waiting"):
                self.assertEqual(doc[key], whole[key], (scope, key))
            self.assertEqual({n: s["counts"] for n, s in doc["spaces"].items()},
                             {n: s["counts"] for n, s in whole["spaces"].items()}, scope)

    def test_the_bosun_scope_is_the_cards_bosun_builds(self):
        # c-591: the cards Bosun builds, nothing else (c-593 named the scope for it)
        doc = self.doc("bosun")
        self.assertIn(self.built, {c["id"] for c in doc["cards"]})
        self.assertNotIn(self.driven, {c["id"] for c in doc["cards"]})
        self.assertTrue(all(c["derived"]["bosun"] for c in doc["cards"]))

    def test_the_card_a_page_has_open_is_held_whatever_the_scope(self):
        """Review F2: a page holds the card it has open (the deck an archived card he was
        linked to) whatever its scope; each is in the state it asks for, marked."""
        for scope, card in (("bosun", self.long), ("deck", self.old), ("bosun", self.old)):
            doc = deckstate.build(
                self.cfg, self.board, rows=self.rows(), scope=scope, asked=card)
            held = {c["id"]: c for c in doc["cards"]}
            self.assertIn(card, held, scope)
            self.assertTrue(held[card]["outside"], scope)
            self.assertEqual(doc["scope"]["card"], card)
        doc = deckstate.build(self.cfg, self.board, rows=self.rows(), scope="bosun", asked=self.built)
        self.assertNotIn("outside", {c["id"]: c for c in doc["cards"]}[self.built], "in scope anyway")
        doc = deckstate.build(self.cfg, self.board, rows=self.rows(), scope="deck", asked="c-99999")
        self.assertEqual(len(doc["cards"]), len(self.doc("deck")["cards"]), "a card that is not there adds nothing")

    def test_a_listing_that_fails_fails_the_build_and_is_not_kept(self):
        """Review F9: before the listing ran in a thread, a `claude agents` that raised (a
        timeout, no binary) failed the request; it must not become "no houses" for 3 s."""
        deck = deckstate.Deck(self.cfg, board_factory=lambda: Board(self.cfg.db_path))
        self.addCleanup(close_stamp, deck)
        with mock.patch.object(deckstate.harness, "agents_across", side_effect=OSError("no claude")):
            with self.assertRaises(OSError):
                deck.state("deck")
        self.assertIsNone(deck.kept.agents.peek("all"), "a failed listing is not kept")
        with mock.patch.object(deckstate.harness, "agents_across", return_value=self.rows()):
            self.assertTrue(deck.state("deck")["houses"])

    def test_the_deck_caches_one_document_per_scope_and_a_write_drops_them_all(self):
        deck = deckstate.Deck(self.cfg, board_factory=lambda: Board(self.cfg.db_path))
        self.addCleanup(close_stamp, deck)
        with mock.patch.object(deckstate.harness, "agents_across", return_value=[]) as listing:
            whole, lean = deck.state(), deck.state("deck")
            self.assertIsNot(whole, lean)
            self.assertIs(deck.state("deck"), lean)
            self.assertEqual(listing.call_count, 1, "the scopes share one harness listing")
            deck.drop()
            self.assertIsNot(deck.state("deck"), lean)
            # a write lists the sessions again, on the reading's own thread (c-638)
            deadline = time.monotonic() + 5
            while listing.call_count < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(listing.call_count, 2)


class KeptReadingsTest(ScopeCase):
    """The deck's kept readings across scopes and failures (c-638 review r1.F1, F3, F6)."""

    def deck(self):
        deck = deckstate.Deck(self.cfg, board_factory=lambda: Board(self.cfg.db_path))
        self.addCleanup(close_stamp, deck)
        self.now = [0.0]
        deck.kept = readings.Readings(deck.moved, clock=lambda: self.now[0])
        self.addCleanup(self.shut, deck)
        return deck

    def shut(self, deck):
        """As `DeckServer.server_close` does: the readings first, then the stamp pinned
        shut, so no late refresh writes into a board the test is removing."""
        deck.kept.close()
        with deck.stamp_lock:
            if deck.stamp_conn is not None:
                deck.stamp_conn.close()
            deck.stamp_conn, deck.stamped_at = None, float("inf")

    def later(self, seconds):
        self.now[0] += seconds

    def settle(self, kept):
        """Until no refresh is in flight, its `on_change` included (`Kept.threads`)."""
        deadline = time.monotonic() + 5
        while (kept.reading or kept.threads) and time.monotonic() < deadline:
            time.sleep(0.005)

    def test_a_narrow_scope_never_narrows_the_links_a_wide_one_draws(self):
        work = self.board.create("work", "a work card", actor="human")
        asked = []

        def act_links(space, ids, strict=False):
            asked.append(sorted(ids))
            return {card_id: {"pr": f"pr-{card_id}"} for card_id in ids}
        deck = self.deck()
        with mock.patch.object(deckstate, "adapter_links", side_effect=act_links), \
                mock.patch.object(deckstate.harness, "agents_across", return_value=[]):
            deck.state("bosun")
            self.later(31)
            deck.drop()
            deck.state("bosun")
            self.settle(deck.kept.links)
            deck.drop()
            cards = {card["id"]: card for card in deck.state("deck")["cards"]}
        self.assertIn(work, asked[-1], "the Bosun page's refresh read every live work card")
        self.assertEqual(cards[work]["links"].get("pr"), f"pr-{work}")

    def test_a_refresh_that_fails_keeps_the_last_good_links(self):
        work = self.board.create("work", "a work card", actor="human")
        answers = iter([{work: {"pr": "pr-1"}}, None])

        def act_links(space, ids, strict=False):
            data = next(answers)
            if data is None:
                raise adapters.ReadingFailed("act links answered nothing")
            return data
        deck = self.deck()
        with mock.patch.object(deckstate, "adapter_links", side_effect=act_links), \
                mock.patch.object(deckstate.harness, "agents_across", return_value=[]):
            deck.state("deck")
            self.later(31)
            writes = deck.writes
            deck.drop()
            deck.state("deck")
            self.settle(deck.kept.links)
            self.assertEqual(deck.kept.links.peek("work")[1], {work: {"pr": "pr-1"}})
            self.assertEqual(deck.writes, writes + 1, "only the write itself told the pages")

    def test_a_reading_that_moved_drops_the_documents_and_tells_the_pages(self):
        deck = self.deck()
        with mock.patch.object(deckstate.harness, "agents_across", return_value=[]):
            deck.state("deck")
        self.assertTrue(deck.cached)
        writes = deck.writes
        deck.kept.verbs.get("work", lambda: {"card": []})
        deck.kept.verbs.get("work", lambda: {"card": ["merge"]}, stale=True)
        self.settle(deck.kept.verbs)
        self.assertEqual((deck.cached, deck.writes), ({}, writes + 1))

    def test_a_failed_listing_keeps_the_houses_it_last_saw(self):
        deck = self.deck()
        rows = self.rows()
        with mock.patch.object(deckstate.harness, "agents_across", return_value=rows):
            self.assertTrue(deck.state("deck")["houses"])
        with mock.patch.object(deckstate.harness, "agents_across",
                               side_effect=deckstate.harness.HarnessError("claude agents exited 1")):
            deck.kept.agents.refresh("all", deck.read_agents)
            self.settle(deck.kept.agents)
        self.assertEqual(deck.kept.agents.peek("all"), rows)


    def test_the_strip_reads_the_listing_now_and_a_changed_house_still_reaches_the_pages(self):
        """The live strip's fresh listing is never kept, so the kept reading's own refresh
        still sees the house that started and tells the pages (c-638 review r2.F2)."""
        deck = self.deck()
        rows = self.rows()
        listed = [[]]
        with mock.patch.object(deckstate.harness, "agents_across", side_effect=lambda dirs, strict=False: listed[0]):
            deck.state("deck")
            listed[0] = rows
            self.assertEqual(deck.listing(fresh=True)(), rows, "the strip sees it now")
            self.assertEqual(deck.kept.agents.peek("all"), [], "and keeps nothing")
            writes = deck.writes
            self.later(3)
            deck.drop()
            deck.state("deck")
            self.settle(deck.kept.agents)
        self.assertEqual(deck.kept.agents.peek("all"), rows)
        self.assertGreaterEqual(deck.writes, writes + 2, "the write, then the house")

    def test_a_failed_git_refresh_keeps_where_bosuns_cards_landed(self):
        deck = self.deck()
        good = {"/repo": frozenset({"c-1"})}
        answers = iter([good, merging_error()])

        def on_next(cfg, strict=False):
            answer = next(answers)
            if isinstance(answer, Exception):
                raise answer
            return answer
        with mock.patch.object(deckstate.bosuncards, "on_next", side_effect=on_next):
            self.assertEqual(deck.kept.on_next.get("next", lambda: deckstate.bosuncards.on_next(None, strict=True)), good)
            writes = deck.writes
            deck.kept.on_next.refresh("next", lambda: deckstate.bosuncards.on_next(None, strict=True))
            self.settle(deck.kept.on_next)
        self.assertEqual((deck.kept.on_next.peek("next"), deck.writes), (good, writes))

    def test_a_first_read_that_fails_is_answered_soft_once_and_read_again_off_the_request(self):
        """r2.F5: a provider that fails the strict read is answered as before, seeded as old,
        so the next build does not read it twice in line."""
        space = self.cfg.spaces["work"]
        strict_calls, soft_calls = [], []

        def providers_for(space, strict=False):
            (strict_calls if strict else soft_calls).append(1)
            if strict:
                raise OSError("a route answered nothing")
            return {"reviews": {}}
        kept = readings.Kept(30.0)
        self.addCleanup(kept.close)
        with mock.patch.object(deckstate.adapters, "providers_for", side_effect=providers_for):
            self.assertEqual(deckstate.space_providers(self.cfg, space, kept), {"reviews": {}})
            self.assertEqual(deckstate.space_providers(self.cfg, space, kept), {"reviews": {}})
            self.settle(kept)
        self.assertEqual(len(soft_calls), 1, "the second build answered the seeded reading")

    def test_a_closed_deck_starts_no_refresh_and_never_reopens_its_stamp(self):
        deck = self.deck()
        gate = threading.Event()

        def slow():
            gate.wait(5)
            return {"card": ["merge"]}
        deck.kept.verbs.get("work", lambda: {"card": []})
        worker = deck.kept.verbs.refresh("work", slow)
        closing = threading.Thread(target=deck.kept.close)
        closing.start()
        gate.set()
        closing.join(5)
        self.assertFalse(worker.is_alive(), "the refresh in flight was joined")
        self.assertIsNone(deck.kept.verbs.refresh("work", slow), "and no new one starts")
        self.assertEqual(deck.kept.verbs.peek("work"), {"card": []}, "nor does a late one land")
        with deck.stamp_lock:
            deck.stamp_conn, deck.stamped_at = None, float("inf")    # as server_close pins it
        deck.moved()
        self.assertIsNone(deck.stamp_conn, "a late move never reopens the stamp")
        self.assertEqual(deck.kept.links.get("new", lambda: ({"x"}, {})), ({"x"}, {}),
                         "a cold read after close answers its own reading")


def merging_error():
    from keel import merging
    return merging.MergeRefused("git did not answer")


class ColdBuildTest(unittest.TestCase):
    def test_the_listings_run_side_by_side_and_keep_their_order(self):
        seen = []

        def agents(config_dir, strict=False):
            seen.append(config_dir)
            return [{"sessionId": config_dir, "name": config_dir}]

        with mock.patch.object(harness, "agents", side_effect=agents):
            rows = harness.agents_across(["/b", "/a", "/b"])
        self.assertEqual([row["name"] for row in rows], ["/b", "/a"])
        self.assertEqual(sorted(seen), ["/a", "/b"])

    def test_one_build_resolves_the_artifact_roots_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            from tests.helpers import make_config
            cfg = make_config(Path(tmp))
            inside = cfg.cards_dir / "c-1" / "plan.md"
            inside.parent.mkdir(parents=True, exist_ok=True)
            inside.write_text("# p\n")
            with mock.patch.object(artifacts, "resolved_roots", wraps=artifacts.resolved_roots) as resolved:
                with artifacts.roots_held(cfg):
                    for _ in range(5):
                        self.assertTrue(artifacts.allowed(inside, cfg))
                    self.assertFalse(artifacts.allowed(Path(tmp).parent / "elsewhere.md", cfg))
                self.assertEqual(resolved.call_count, 1)
                self.assertTrue(artifacts.allowed(inside, cfg), "outside a build it resolves as before")
                self.assertEqual(resolved.call_count, 2)


class WireTest(ServerCase):
    def seed(self):
        super().seed()
        seed_scopes(self)

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

    def test_the_state_is_gzipped_for_a_browser_and_an_unchanged_one_is_a_304(self):
        zipped = {"Accept-Encoding": "gzip, deflate, br"}
        with mock.patch.object(deckstate.harness, "agents_across", return_value=self.rows()):
            status, head, body = self.get("/api/state?scope=deck", zipped)
            self.assertEqual((status, head.get("Content-Encoding")), (200, "gzip"))
            doc = json.loads(gzip.decompress(body))
            self.assertNotIn(self.old, {c["id"] for c in doc["cards"]})
            self.assertEqual(head["Vary"], "Accept-Encoding")
            tag = head["ETag"]
            status, head, body = self.get("/api/state?scope=deck", dict(zipped, **{"If-None-Match": tag}))
            self.assertEqual((status, body), (304, b""))
            # another scope, archived, or no gzip is another document, so another tag
            for path, headers in (("/api/state", zipped), ("/api/state?scope=deck&archived=1", zipped),
                                  ("/api/state?scope=deck", {})):
                status, head, _ = self.get(path, dict(headers, **{"If-None-Match": tag}))
                self.assertEqual(status, 200, path)
                self.assertNotEqual(head["ETag"], tag, path)
            status, head, body = self.get("/api/state")
            self.assertIsNone(head.get("Content-Encoding"), "a machine reader that asks no gzip gets none")
            self.assertIn(self.old, {c["id"] for c in json.loads(body)["cards"]})

    def test_the_open_card_rides_on_the_query_and_in_the_tag(self):
        with mock.patch.object(deckstate.harness, "agents_across", return_value=self.rows()):
            status, head, body = self.get(f"/api/state?scope=bosun&card={self.long}")
            self.assertEqual(status, 200)
            self.assertIn(self.long, {c["id"] for c in json.loads(body)["cards"]})
            status, other, _ = self.get("/api/state?scope=bosun")
            self.assertNotEqual(other["ETag"], head["ETag"])
            status, _, body = self.get("/api/state?scope=bosun&card=not-a-card")
            self.assertIsNone(json.loads(body)["scope"]["card"])


    def test_an_app_file_is_kept_and_revalidated_and_a_deploy_shows_at_once(self):
        app = self.dir / "app"
        app.mkdir()
        shutil.copy(Path(serve.__file__).resolve().parent.parent / "app" / "ui.core.js", app / "ui.core.js")
        self.server.RequestHandlerClass.app_dir = app
        for headers in ({"Accept-Encoding": "gzip"}, {}):
            status, head, body = self.get("/ui.core.js", headers)
            self.assertEqual((status, head["Cache-Control"]), (200, serve.REVALIDATE))
            tag = head["ETag"]
            status, head, body = self.get("/ui.core.js", dict(headers, **{"If-None-Match": tag}))
            self.assertEqual((status, body), (304, b""))
            self.assertEqual(head["Cache-Control"], serve.REVALIDATE)
            stat = (app / "ui.core.js").stat()
            os.utime(app / "ui.core.js", ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
            status, head, _ = self.get("/ui.core.js", dict(headers, **{"If-None-Match": tag}))
            self.assertEqual(status, 200, "a deploy moves the tag, so the next load gets it")
            self.assertNotEqual(head["ETag"], tag)

    def test_the_shells_are_still_never_stored(self):
        for path in ("/", "/console"):
            status, head, _ = self.get(path)
            self.assertEqual((status, head["Cache-Control"]), (200, serve.NO_STORE), path)


@unittest.skipUnless(shutil.which("node"), "node is not on this machine")
class PagesTest(unittest.TestCase):
    """The page's half, RUN under node (`tests/fixtures/deck-scope.js`, review r2.F1, F4):
    what each move asks `/api/state` for and that it then stops, the pane's and the Edit
    dialog's whole brief, and the Include archived switch's count."""

    def test_the_page_asks_for_its_scope_and_reads_briefs_whole(self):
        root = Path(serve.__file__).resolve().parent.parent
        result = subprocess.run(["node", str(root / "tests" / "fixtures" / "deck-scope.js"), str(root / "app")],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True}, result.stdout)


# ----- r-19: a sent-back tracking card with every slice done -----

class RegateTest(DrainCase):
    def fake_kb(self, cfg, argv, **kwargs):
        if argv[0] == "stage":
            note = argv[argv.index("--note") + 1] if "--note" in argv else None
            self.board.stage(argv[1], argv[2], "human", note=note)
        return self.board.get(argv[1])

    def test_a_sent_back_tracking_card_comes_back_to_his_gate_by_his_tap(self):
        """The reproduction of c-517: sent back with all slices done, it read review with no
        gate, and the drain would never bring it back. Red before c-540: no `regate`."""
        self.cfg.drain_paused = True
        parent = self.tracking(slices=2)
        for kid in self.board.children(parent):
            finish(self.board, kid["id"])
        self.board.stage(parent, "review", "drain")     # at his gate, as before c-649
        self.board.stage(parent, "building", "human", note="a misclick")
        for _ in range(2):
            self.once()
        derived = self.board.get(parent)["derived"]
        self.assertEqual(derived["parent_stage"], "review", "every reader still shows review")
        self.assertFalse(derived["outcome_gate"])
        self.assertTrue(derived["regate"], "the deck has a way to act")
        with mock.patch.object(actions, "run_kb", side_effect=self.fake_kb):
            actions.act(self.cfg, self.board, {"verb": "stage", "id": parent, "stage": "review",
                                               "note": "brought back to your gate from the deck"})
        card = self.board.get(parent)
        self.assertEqual(card["stage"], "review")
        self.assertTrue(card["derived"]["outcome_gate"])
        self.assertTrue(card["derived"]["needs_you"])
        self.assertFalse(card["derived"]["regate"])
        self.once()                                     # c-649: the drain closes it from review
        self.assertEqual(self.board.get(parent)["stage"], "done")

    def test_no_regate_while_a_slice_is_open_or_before_the_drain_brought_it(self):
        self.cfg.drain_paused = True
        parent = self.tracking(slices=2)
        kids = [kid["id"] for kid in self.board.children(parent)]
        finish(self.board, kids[0])
        self.assertFalse(self.board.get(parent)["derived"]["regate"])
        finish(self.board, kids[1])
        self.once()
        self.assertFalse(self.board.get(parent)["derived"]["regate"], "the drain closed it")


if __name__ == "__main__":
    unittest.main()
