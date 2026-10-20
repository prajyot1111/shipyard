"""Recurring cards (`keel/recurring.py`): due from the board alone, filed once, and the
clock starting when the last one closed (c-288, the quarterly restore rehearsal)."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from keel import config as config_module, fetch, recurring
from keel.board import Board
from tests.helpers import ROOT, make_config

TABLE = {"every_days": 91, "space": "personal", "title": "Quarterly restore rehearsal",
         "brief": "run bin/keel-rehearse", "repo": "keel", "autonomy": "autonomous"}
KEY = "restore-rehearsal"


class RecurringCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.cfg.recurring = {KEY: dict(TABLE)}
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        self.now = datetime(2026, 12, 20, tzinfo=timezone.utc)

    def closed(self, days_ago: int) -> str:
        """A card carrying the key, walked to done, its done event dated `days_ago`."""
        card = self.board.create("personal", "an earlier rehearsal", options={"recurring": KEY})
        self.board.conn.execute("UPDATE cards SET stage = 'done' WHERE id = ?", (card,))
        at = (self.now - timedelta(days=days_ago)).isoformat(timespec="seconds")
        self.board.conn.execute(
            "INSERT INTO events (card, at, kind, actor, text, data) VALUES (?, ?, 'stage', 'human', '', ?)",
            (card, at, '{"from": "review", "to": "done"}'))
        self.board.conn.commit()
        return card

    def filed(self) -> dict:
        return recurring.file_due(self.cfg, self.board, now=self.now)


class DueTest(RecurringCase):
    def test_a_key_no_card_has_carried_is_due_and_files_one_assigned_card(self):
        filed = self.filed()
        self.assertEqual(list(filed), [KEY])
        card = self.board.get(filed[KEY])
        self.assertEqual((card["stage"], card["autonomy"], card["repo"], card["space"]),
                         ("assigned", "autonomous", "keel", "personal"))
        self.assertEqual(card["options"]["recurring"], KEY)
        self.assertEqual(card["title"], TABLE["title"])

    def test_an_open_card_holds_the_next_one_so_a_pass_every_minute_files_once(self):
        first = self.filed()
        self.assertEqual(self.filed(), {})
        self.assertEqual(self.filed(), {})
        due, why = recurring.due(self.board, KEY, 91, self.now)
        self.assertFalse(due)
        self.assertIn(f"{first[KEY]} is still open", why)

    def test_the_clock_starts_when_the_last_one_closed(self):
        self.closed(days_ago=90)
        self.assertEqual(self.filed(), {})
        self.assertIn("next on", recurring.due(self.board, KEY, 91, self.now)[1])
        self.closed(days_ago=200)          # an older one changes nothing: the newest counts
        self.assertEqual(self.filed(), {})

    def test_past_the_interval_it_is_due(self):
        self.closed(days_ago=92)
        self.assertEqual(list(self.filed()), [KEY])

    def test_no_table_files_nothing(self):
        self.cfg.recurring = {}
        self.assertEqual(self.filed(), {})
        self.assertEqual(self.board.list_cards(), [])

    def test_the_fetch_pass_files_and_logs_it(self):
        self.board.close()
        filed = fetch.due_cards(self.cfg)
        self.assertEqual(list(filed), [KEY])
        log = (self.cfg.state_dir / "logs" / fetch.LOG_NAME).read_text()
        self.assertIn(f"recurring {KEY}: {filed[KEY]} filed", log)


class ConfigTest(unittest.TestCase):
    def load(self, table: str) -> config_module.Config:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keel.toml"
            path.write_text('[spaces.personal]\nconfig_dir = "/c"\n' + table)
            return config_module.load(path, ensure=False)


    def test_a_bad_table_is_refused(self):
        for bad, said in (('every_days = 0\nspace = "personal"\ntitle = "t"', "every_days"),
                          ('every_days = "91"\nspace = "personal"\ntitle = "t"', "every_days"),
                          ('every_days = 91\nspace = "nowhere"\ntitle = "t"', "space"),
                          ('every_days = 91\nspace = "personal"\ntitle = "t"\nevery = 3', "unknown keys"),
                          ('every_days = 91\nspace = "personal"', "title"),
                          ('every_days = 91\nspace = "personal"\ntitle = "t"\nautonomy = "maybe"', "autonomy")):
            with self.subTest(said=said), self.assertRaises(config_module.ConfigError) as caught:
                self.load(f"[recurring.x]\n{bad}\n")
            self.assertIn(said, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
