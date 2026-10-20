"""The deck says when a space's login has expired (lane Q, Q4): the space's entry on the
state document, the health verdict, and the banner the page draws on Now and Attention.

The page half is a grep, as `tests/test_deck_css.py` explains for the rest of the page: a
stdlib suite cannot run the script. The real render at 390 and 1440 is recorded in the
lane's report."""

import json
import os
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from keel import deckstate, harness, health, login
from keel.board import Board
from tests.helpers import make_config

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = make_config(Path(self.tmp.name))
        self.board = Board(self.cfg.db_path)

    def tearDown(self):
        self.board.close()
        self.tmp.cleanup()

    def test_each_space_carries_its_kept_login_answer_and_the_fix(self):
        doc = deckstate.build(self.cfg, self.board, rows=[])
        self.assertIsNone(doc["spaces"]["personal"]["login"], "never probed: nothing to say")
        at = datetime.now().astimezone()
        login.record(self.cfg, "personal", {"state": login.EXPIRED, "why": "Login expired"}, at)
        doc = deckstate.build(self.cfg, self.board, rows=[])
        entry = doc["spaces"]["personal"]["login"]
        self.assertEqual(entry["state"], login.EXPIRED)
        self.assertEqual(entry["at"], at.isoformat(timespec="seconds"))
        self.assertEqual(entry["fix"], "run CLAUDE_CONFIG_DIR="
                         f"{self.cfg.spaces['personal'].config_dir} claude, then /login")
        self.assertIsNone(doc["spaces"]["work"]["login"])
        # c-678: the one command the guided sign-in shows, for the banner's block
        self.assertTrue(entry["signin"].endswith(" auth login"), entry["signin"])
        self.assertIn(f"CLAUDE_CONFIG_DIR={self.cfg.spaces['personal'].config_dir} ", entry["signin"])
        self.assertIsNone(entry["stamp"], "no sign-in file there yet")

    def test_a_dir_never_logged_in_is_not_called_expired(self):
        """c-560: a served dir with no login is held as expired, but he never logged it in,
        so the hold's reason and the banner's flag say so instead."""
        login.record(self.cfg, "personal", {"state": login.EXPIRED}, datetime.now().astimezone())
        config_dir = self.cfg.spaces["personal"].config_dir
        self.assertTrue(login.public(self.cfg, "personal")["never_logged_in"])
        self.assertNotIn("expired", login.block_reason("personal", config_dir))
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / ".credentials.json").write_text("{}")
        self.assertFalse(login.public(self.cfg, "personal")["never_logged_in"])
        self.assertIn("expired", login.block_reason("personal", config_dir))

    def test_the_state_says_whether_every_space_signs_in_there(self):
        """The banner may say "no session can run" only then (review F15)."""
        login.record(self.cfg, "personal", {"state": login.EXPIRED}, datetime.now().astimezone())
        for space in self.cfg.spaces.values():
            space.config_dir = self.cfg.spaces["personal"].config_dir
        self.assertIs(login.public(self.cfg, "personal")["only"], True)
        other = next(name for name in self.cfg.spaces if name != "personal")
        self.cfg.spaces[other].config_dir = self.cfg.spaces["personal"].config_dir.parent / "another"
        self.assertIs(login.public(self.cfg, "personal")["only"], False)

    def test_a_half_written_account_file_is_not_read_as_never_logged_in(self):
        """c-560: Claude Code rewrites `.claude.json` often; one caught mid-write says
        nothing, so the wording falls back to expired rather than flipping."""
        login.record(self.cfg, "personal", {"state": login.EXPIRED}, datetime.now().astimezone())
        config_dir = self.cfg.spaces["personal"].config_dir
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / ".claude.json").write_text('{"oauthAccount": {"emailAdd')
        self.assertFalse(login.public(self.cfg, "personal")["never_logged_in"])
        self.assertIn("expired", login.block_reason("personal", config_dir))
        self.assertIn("LOGIN EXPIRED", login.said(login.read(self.cfg)["personal"], config_dir))

    def test_the_default_profile_reads_its_account_from_the_homes_claude_json(self):
        """c-560: the default profile keeps `.claude.json` beside `~/.claude`, not in it."""
        home = Path(self.tmp.name) / "home"
        (home / ".claude").mkdir(parents=True)
        (home / ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": "u"}}))
        with mock.patch.dict(os.environ, {"HOME": str(home)}), \
                mock.patch.object(harness, "DEFAULT_CONFIG_DIR", home / ".claude"):
            self.assertTrue(harness.is_default_config_dir(home / ".claude"))
            self.assertTrue(login.ever_logged_in(home / ".claude"))
            entry = {"state": login.EXPIRED, "at": datetime.now().astimezone().isoformat()}
            self.assertTrue(login.said(entry, home / ".claude").startswith("LOGIN EXPIRED"))


class VerdictTest(unittest.TestCase):
    BASE = {"talker": {"state": "serving", "ok": True}, "voice": {"installed": False},
            "drain": {"alive": True, "age_seconds": 20}, "backup": {"writes": False, "pulls": False},
            "idle": {"applicable": False}}

    @staticmethod
    def row(state, houses=False, **extra):
        return dict({"host": "box", "label": "Claude personal", "state": state, "houses": houses}, **extra)

    def test_an_expired_login_houses_run_under_is_red_and_named(self):
        found = health.verdict(dict(self.BASE, logins=[self.row("expired", houses=True),
                                                       self.row("good", label="Claude work")]))
        self.assertEqual(found, {"level": "red", "reasons": ["login: box Claude personal expired"]})

    def test_any_other_red_row_is_amber(self):
        for state in ("expired", "missing"):
            found = health.verdict(dict(self.BASE, logins=[self.row(state, label="Drive")]))
            self.assertEqual(found, {"level": "amber", "reasons": [f"login: box Drive {state}"]})

    def test_a_login_about_to_end_is_amber(self):
        found = health.verdict(dict(self.BASE, logins=[self.row(
            "good", ending=True, expires="2026-09-28T17:00:00+00:00")]))
        self.assertEqual(found["reasons"], ["login: box Claude personal ends 2026-09-28"])

    def test_good_unknown_or_never_probed_say_nothing(self):
        for rows in ([], [self.row("good")], [self.row("unknown")]):
            self.assertEqual(health.verdict(dict(self.BASE, logins=rows))["level"], "green")

    def test_the_fact_is_the_kept_answers_never_a_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(Path(tmp))
            cfg.spaces["personal"].config_dir.mkdir(parents=True)
            login.record(cfg, "personal", {"state": login.EXPIRED}, datetime.now().astimezone())
            with mock.patch.object(login, "probe") as probe:
                facts = health.gather(cfg)
            probe.assert_not_called()
        personal = next(r for r in facts["logins"] if r["id"] == "claude:personal")
        self.assertEqual((personal["state"], personal["houses"]), ("expired", True))


class PageTest(unittest.TestCase):
    def setUp(self):
        self.views = (APP / "ui.views.js").read_text()
        self.css = (APP / "ui.css").read_text()

    def test_now_and_attention_open_with_the_login_banner(self):
        self.assertIn("function loginBanner()", self.views)
        for view in ("viewNow", "viewAttention"):
            body = self.views[self.views.index(f"function {view}()"):]
            body = body[:body.index("\n  }\n")]
            self.assertIn("loginBanner()", body, view)

    def test_the_banner_reads_the_spaces_login_and_says_the_fix(self):
        body = self.views[self.views.index("function loginBanner()"):]
        body = body[:body.index("\n  }\n")]
        for needle in ("App.data.spaces", ".login", "'expired'", ".fix", "role: 'alert'"):
            self.assertIn(needle, body)


if __name__ == "__main__":
    unittest.main()
