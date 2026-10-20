"""The Journal's throughput and recurring gaps (c-524, BO-6; `keel/consolejournal.py`)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import consolejournal, deckstate, requests
from keel.board import Board
from tests.test_console import LifecycleCase
from tests.test_requests import RequestKbCase

NOW = "2026-09-26T12:00:00+00:00"


class BoardCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.board = Board(Path(tmp.name) / "board.db")
        self.addCleanup(self.board.close)

    def done(self, space: str, at: str) -> str:
        card = self.board.create(space, "t", stage="review", actor="human")
        self.board.stage(card, "done", "human")
        self.board.conn.execute("UPDATE events SET at = ? WHERE card = ? AND kind = 'stage'", (at, card))
        self.board.conn.commit()
        return card

    def resolved(self, gap: str, how: str, at: str) -> str:
        rid = requests.ask(self.board, f"in the way {gap} {how} {at}", "human")["id"]
        requests.take(self.board, rid, "bosun")
        requests.resolve(self.board, rid, "bosun", how, gap, "note",
                         card=self.keel_card() if how == "filed" else None)
        self.board.conn.execute("UPDATE requests SET updated_at = ? WHERE id = ?", (at, rid))
        self.board.conn.commit()
        return rid

    def keel_card(self) -> str:
        return self.board.create("personal", "fix", repo="keel", actor="human")


class ThroughputTest(BoardCase):
    def test_done_inside_seven_days_counts_by_space_and_every_space_shows(self):
        self.done("personal", "2026-09-25T09:00:00+00:00")
        self.done("personal", "2026-09-20T09:00:00+00:00")
        self.done("personal", "2026-09-19T11:59:00+00:00")     # a minute past the window
        self.done("work", "2026-09-19T12:00:00+00:00")         # exactly seven days: inside
        t = consolejournal.throughput(self.board, ["personal", "work"], NOW)
        self.assertEqual(t["done"], {"personal": 2, "work": 1})
        self.assertEqual(set(t), {"days", "done"}, "the console's cap counts went with it (c-593)")
        self.assertEqual(t["days"], consolejournal.DAYS)

    def test_done_by_his_approve_outcome_counts(self):
        """The main road to done is a gate, not a stage move: an `approve` event."""
        card = self.board.create("work", "t", stage="review", actor="human")
        self.board.approve(card, "outcome", "human")
        self.assertEqual(self.board.get(card)["stage"], "done")
        now = self.board.now()
        self.assertEqual(consolejournal.throughput(self.board, ["work"], now)["done"], {"work": 1})

    def test_a_card_done_twice_counts_once(self):
        card = self.done("personal", "2026-09-25T09:00:00+00:00")
        self.board.conn.execute("INSERT INTO events (card, at, kind, actor, data) VALUES "
                                "(?, ?, 'stage', 'human', '{\"to\": \"done\"}')",
                                (card, "2026-09-26T09:00:00+00:00"))
        self.assertEqual(consolejournal.throughput(self.board, ["personal"], NOW)["done"],
                         {"personal": 1})


class GapsTest(BoardCase):
    def test_gaps_group_by_tag_most_first_with_how_and_when_last(self):
        self.resolved("stale-scan", "fixed", "2026-09-20T10:00:00+00:00")
        self.resolved("unlisted-repo", "declined", "2026-09-21T10:00:00+00:00")
        self.resolved("stale-scan", "filed", "2026-09-24T10:00:00+00:00")
        self.resolved("stale-scan", "fixed", "2026-09-22T10:00:00+00:00")
        rows = consolejournal.gap_rows(self.board)
        self.assertEqual([(r["gap"], r["count"], r["recurring"]) for r in rows],
                         [("stale-scan", 3, True), ("unlisted-repo", 1, False)])
        self.assertEqual(rows[0]["hows"], {"fixed": 2, "filed": 1})
        self.assertEqual(rows[0]["last"], "2026-09-24T10:00:00+00:00")
        self.assertEqual(rows[0]["requests"], ["r-1", "r-3", "r-4"])
        self.assertEqual(consolejournal.gap_line(rows[0]),
                         "stale-scan  3  recurring  (2 fixed, 1 filed; last 2026-09-24; r-1, r-3, r-4)")

    def test_an_open_request_has_no_gap_yet(self):
        requests.ask(self.board, "still open", "human")
        self.assertEqual(consolejournal.gap_rows(self.board), [])


class GapsVerbTest(RequestKbCase):
    def test_kb_console_gaps_prints_one_line_per_tag(self):
        for n in range(2):
            card = self.create()
            self.kb("block", card, f"stuck {n}", "--keel", env={"KEEL_CARD": card})
            self.as_bosun("console", "take", f"r-{n + 1}")
            self.as_bosun("console", "resolve", f"r-{n + 1}", "--how", "declined", "--gap",
                          "stale-scan", "--note", "n")
        code, out, err = self.kb("console", "gaps")
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("stale-scan  2  recurring  (2 declined; last "), out)
        self.assertEqual(self.kb_json("console", "gaps")["gaps"], {"stale-scan": 2})


class StateTest(LifecycleCase):
    def test_the_console_entry_carries_throughput_and_gaps(self):
        board = Board(self.cfg.db_path)
        self.addCleanup(board.close)
        card = board.create("personal", "t", stage="review", actor="human")
        board.stage(card, "done", "human")
        rid = requests.ask(board, "one", "human")["id"]
        requests.take(board, rid, "bosun")
        requests.resolve(board, rid, "bosun", "fixed", "stale-scan", "n")
        with mock.patch.object(deckstate.harness, "agents_across", return_value=[]):
            entry = deckstate.build(self.cfg, board, rows=[])["console"]
        self.assertEqual(entry["throughput"]["done"], {"personal": 1, "work": 0})
        self.assertEqual([g["gap"] for g in entry["gaps"]], ["stale-scan"])

    def test_without_a_console_session_the_page_still_has_its_board_half(self):
        # With no Bosun host configured there is no console entry: Shipped, the asks and the
        # Journal still come (c-591 review).
        self.cfg.console = {}
        board = Board(self.cfg.db_path)
        self.addCleanup(board.close)
        rid = requests.ask(board, "one", "human")["id"]
        with mock.patch.object(deckstate.harness, "agents_across", return_value=[]):
            state = deckstate.build(self.cfg, board, rows=[])
        self.assertIsNone(state["console"])
        half = state["bosun"]
        self.assertIn("shipped", half)
        self.assertEqual([row["id"] for row in half["requests"]], [rid])
        self.assertEqual(half["counts"]["requests"], 1)


if __name__ == "__main__":
    unittest.main()
