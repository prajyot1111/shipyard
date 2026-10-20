"""A first fetch after a long gap is calm, and says what it will file before it does
(`keel/fetchpreview.py`, c-742): each recurring card at most once however many intervals
were missed, one errand card per segment however many asks waited, and the preview names
exactly the cards the pass then files, having written nothing itself."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from keel import fetch, fetchloop, fetchpreview, recurring
from keel.board import Board
from tests.helpers import make_config
from tests.test_fetch import WORKER, add_ask

NOW = datetime(2026, 12, 20, 9, 0, tzinfo=timezone.utc)
WEEKLY = {"every_days": 7, "space": "personal", "title": "Weekly review", "brief": "look back"}
YEARLY = {"every_days": 365, "space": "personal", "title": "Yearly audit", "brief": "audit"}


class GapCase(unittest.TestCase):
    """A board whose weekly card last closed 400 days ago (57 missed weeks), whose yearly
    one closed 30 days ago, a key no card has carried, and a segment with three old asks."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.cfg.recurring = {"weekly": dict(WEEKLY), "yearly": dict(YEARLY),
                              "fresh": dict(WEEKLY, title="Never filed")}
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        self.board.now = lambda: NOW.isoformat(timespec="seconds")
        self.closed("weekly", 400)
        self.closed("yearly", 30)
        self.asker = self.cfg.segments_dir / "asker"
        (self.asker / "data" / "asks").mkdir(parents=True)
        (self.asker / "worker.md").write_text(WORKER)
        for number in (1, 2, 3):
            add_ask(self.asker, number)

    def closed(self, key: str, days_ago: int) -> None:
        card = self.board.create("personal", f"an earlier {key}", options={"recurring": key})
        self.board.conn.execute("UPDATE cards SET stage = 'done' WHERE id = ?", (card,))
        at = (NOW - timedelta(days=days_ago)).isoformat(timespec="seconds")
        self.board.conn.execute(
            "INSERT INTO events (card, at, kind, actor, text, data) VALUES (?, ?, 'stage', 'human', '', ?)",
            (card, at, '{"from": "review", "to": "done"}'))
        self.board.conn.commit()

    def filed(self) -> dict:
        """One pass's cards: the asks, then the recurring ones, as `fetch.run` orders them."""
        asked = fetch.asks(self.cfg, board=self.board)
        return {**{f"asks {name}": card for name, card in asked.items()},
                **{f"recurring {key}": card
                   for key, card in recurring.file_due(self.cfg, self.board, now=NOW).items()}}


class CalmTest(GapCase):
    def test_a_first_pass_after_a_long_gap_files_each_card_once_and_the_next_pass_none(self):
        first = self.filed()
        self.assertEqual(sorted(first), ["asks asker", "recurring fresh", "recurring weekly"])
        self.assertEqual(self.board.get(first["asks asker"])["title"], "asker: 3 asks")
        self.assertEqual(self.filed(), {}, "57 missed weeks are one card, not 57")
        self.assertEqual(self.filed(), {})

    def test_the_preview_names_what_the_pass_then_files_and_writes_nothing(self):
        before = sorted(str(path) for path in self.dir.rglob("*"))
        cards = len(self.board.list_cards())
        said = fetchpreview.lines(self.cfg, now=NOW)
        self.assertEqual(said, [
            "fetchers: 0 would run",
            "asks asker: 3 asks, one card in personal",
            'recurring weekly: one card in personal, "Weekly review" (the last one closed 400 days ago)',
            f"recurring yearly: no card (next on {(NOW + timedelta(days=335)).date().isoformat()})",
            'recurring fresh: one card in personal, "Never filed" (no card has carried it yet)',
            "cards: 3 would be filed, at most one for each line above "
            "(an ask a fetcher writes during the pass is not counted)"])
        self.assertEqual(sorted(str(path) for path in self.dir.rglob("*")), before)
        self.assertEqual(len(self.board.list_cards()), cards)
        self.assertEqual(len(self.filed()), 3, "the pass files what the preview counted")
        self.assertIn("cards: 0 would be filed", fetchpreview.lines(self.cfg, now=NOW)[-1])

    def test_asks_past_the_daily_cap_and_a_bad_worker_are_said_as_waiting(self):
        for _ in range(2):          # the worker's daily_cap is 2
            self.board.create("personal", "an earlier errand", options={"segment": "asker"})
        self.assertIn("asks asker: 3 asks wait, no card: daily cap reached (2/2)",
                      fetchpreview.lines(self.cfg, now=NOW))
        (self.asker / "worker.md").write_text("---\nspace: nowhere\n---\nbody\n")
        self.assertTrue(any(line.startswith("asks asker: 3 asks wait, no card: worker.md must name a space")
                            for line in fetchpreview.lines(self.cfg, now=NOW)))

    def test_the_role_says_its_first_pass_in_the_log_before_it_files(self):
        with mock.patch.object(fetchpreview, "lines", return_value=["cards: 2 would be filed"]):
            fetchloop.say_first_pass(self.cfg)
        self.assertIn("first pass: cards: 2 would be filed",
                      (self.cfg.logs_dir / fetch.LOG_NAME).read_text())


class NoBoardTest(unittest.TestCase):
    def test_an_install_with_no_board_yet_previews_without_making_one(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
            cfg = make_config(Path(tmp))
            cfg.recurring = {"weekly": dict(WEEKLY)}
            cfg.db_path.unlink(missing_ok=True)
            said = fetchpreview.lines(cfg, now=NOW)
            self.assertFalse(cfg.db_path.exists())
        self.assertEqual(said[1], 'recurring weekly: one card in personal, "Weekly review" '
                                  '(no card has carried it yet)')


if __name__ == "__main__":
    unittest.main()
