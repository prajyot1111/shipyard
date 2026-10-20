"""The Logins list (c-558, `keel/logins.py`): which rows a machine has, how a row's state is
read from its last check, a newer mark and its login's end, when a row is due a check, and
the marks a failed turn or fetch leaves. Every check here is a stub: nothing reaches a real
`claude`, rclone or key."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from keel import health, login, loginask, loginprobe, logins
from keel.board import Board
from tests.helpers import make_config

TRANSCRIPT = ("That turn did not come back: Failed to authenticate: OAuth session expired "
              "and could not be refreshed")


def stamp(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat(timespec="seconds")


def credentials(config_dir: Path, ends: datetime) -> None:
    """A credentials file carrying only the instant its login ends, as the harness writes it."""
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / ".credentials.json").write_text(json.dumps(
        {"claudeAiOauth": {"refreshTokenExpiresAt": int(ends.timestamp() * 1000)}}))


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.cfg = make_config(self.dir)
        self.cfg.host = "box"
        self.now = datetime(2026, 9, 27, 8, 0, tzinfo=timezone.utc)
        self.personal = self.cfg.spaces["personal"].config_dir
        self.talker_dir = self.dir / "harbor" / ".claude"
        patch = mock.patch.object(logins, "claude_specs", self.claude_specs_with_talker)
        patch.start()
        self.addCleanup(patch.stop)
        self.checks = []

    def claude_specs_with_talker(self, cfg):
        """The real specs, plus the talker's dir as if the talker were installed here."""
        specs = ORIGINAL_SPECS(cfg)
        specs.append(logins.Login(id="claude:harbor", kind="claude", label="Claude talker and voice",
                                  where=str(self.talker_dir), target=str(self.talker_dir),
                                  fix=loginprobe.claude_fix(self.talker_dir)))
        return specs

    def spec(self, row_id):
        return next(one for one in logins.specs(self.cfg) if one.id == row_id)

    def row(self, row_id, at=None):
        return next(r for r in logins.public(self.cfg, at or self.now) if r["id"] == row_id)


ORIGINAL_SPECS = logins.claude_specs


class RowsTest(Case):
    def test_a_served_space_is_a_row_its_houses_depend_on(self):
        rows = {r["id"]: r for r in logins.public(self.cfg, self.now)}
        personal = rows["claude:personal"]
        self.assertEqual(personal["where"], str(self.personal))
        self.assertTrue(personal["houses"])
        self.assertEqual(personal["state"], "unknown")
        self.assertEqual(personal["host"], "box")
        self.assertFalse(rows["claude:harbor"]["houses"])
        # c-678: what the guided sign-in's block on a red row needs: the spaces that run
        # under the dir (its Check again probes the first), and the sign-in file's stamp
        self.assertEqual((personal["spaces"], personal["stamp"]), (["personal"], None))
        self.assertEqual(rows["claude:harbor"]["spaces"], [])

    def test_two_spaces_sharing_a_dir_are_one_row(self):
        self.cfg.spaces["work"].config_dir = self.personal
        mine = [r for r in logins.public(self.cfg, self.now) if r["where"] == str(self.personal)]
        self.assertEqual(len(mine), 1)
        self.assertIn("personal", mine[0]["label"])
        self.assertIn("work", mine[0]["label"])

class StateTest(Case):
    def test_a_mark_newer_than_the_check_reads_expired_and_the_next_check_clears_it(self):
        logins.keep(self.cfg, self.spec("claude:harbor"), {"state": "good"}, None,
                    self.now - timedelta(hours=2))
        self.assertEqual(self.row("claude:harbor")["state"], "good")
        logins.mark(self.cfg, "claude:harbor", "a turn said: Login expired",
                    at=self.now - timedelta(hours=1))
        row = self.row("claude:harbor")
        self.assertEqual((row["state"], row["marked"]), ("expired", True))
        self.assertIn("Login expired", row["why"])
        logins.keep(self.cfg, self.spec("claude:harbor"), {"state": "good"}, None, self.now)
        self.assertEqual(self.row("claude:harbor")["state"], "good")

    def test_a_login_past_its_thirty_days_is_expired_whatever_the_last_check_said(self):
        credentials(self.talker_dir, self.now - timedelta(minutes=5))
        logins.keep(self.cfg, self.spec("claude:harbor"), {"state": "good"}, None, self.now)
        row = self.row("claude:harbor")
        self.assertEqual(row["state"], "expired")
        self.assertIn("30 days", row["why"])

    def test_a_login_within_two_days_of_its_end_is_ending(self):
        credentials(self.talker_dir, self.now + timedelta(days=1))
        row = self.row("claude:harbor")
        self.assertTrue(row["ending"])
        self.assertEqual(row["expires"][:10], "2026-09-28")
        credentials(self.talker_dir, self.now + timedelta(days=20))
        self.assertFalse(self.row("claude:harbor")["ending"])

    def test_a_space_dir_reads_the_drains_own_login_answer(self):
        login.record(self.cfg, "personal", {"state": login.EXPIRED, "why": "Login expired"},
                     self.now)
        personal = next(r for r in logins.public(self.cfg, self.now) if r["houses"])
        self.assertEqual(personal["state"], "expired")


class UpkeepTest(Case):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(logins, "check", self.fake_check)
        patch.start()
        self.addCleanup(patch.stop)
        self.answers = {}

    def fake_check(self, cfg, spec):
        self.checks.append(spec.id)
        return {"state": self.answers.get(spec.id, "good"), "why": ""}, None

    def test_at_most_two_checks_a_pass_then_nothing_until_a_day_has_passed(self):
        first = logins.upkeep(self.cfg, self.now)
        self.assertEqual(len(first["checked"]), 2)
        logins.upkeep(self.cfg, self.now)
        self.assertEqual(len(self.checks), len(logins.specs(self.cfg)))
        self.checks.clear()
        logins.upkeep(self.cfg, self.now + timedelta(hours=23))
        self.assertEqual(self.checks, [])
        logins.upkeep(self.cfg, self.now + timedelta(hours=25))
        self.assertEqual(len(self.checks), 2)

    def test_a_mark_is_checked_on_the_next_pass_first(self):
        for _ in range(3):
            logins.upkeep(self.cfg, self.now)
        self.checks.clear()
        logins.mark(self.cfg, "claude:harbor", "a turn said: Not logged in",
                    at=self.now + timedelta(minutes=1))
        logins.upkeep(self.cfg, self.now + timedelta(minutes=2))
        self.assertEqual(self.checks, ["claude:harbor"])

    def test_a_red_row_is_checked_every_ten_minutes(self):
        self.answers["claude:harbor"] = "expired"
        for _ in range(3):
            logins.upkeep(self.cfg, self.now)
        self.checks.clear()
        logins.upkeep(self.cfg, self.now + timedelta(minutes=5))
        self.assertEqual(self.checks, [])
        logins.upkeep(self.cfg, self.now + timedelta(minutes=11))
        self.assertEqual(self.checks, ["claude:harbor"])

    def test_a_space_dirs_check_is_kept_where_the_drains_hold_reads_it(self):
        self.answers = {spec.id: "expired" for spec in logins.specs(self.cfg)}
        for _ in range(3):
            logins.upkeep(self.cfg, self.now)
        self.assertTrue(login.is_expired(self.cfg, "personal"))

    def test_good_at_is_when_a_row_was_last_seen_good(self):
        for _ in range(3):
            logins.upkeep(self.cfg, self.now)
        self.assertEqual(self.row("claude:harbor")["good_at"], stamp(self.now))
        logins.mark(self.cfg, "claude:harbor", "Login expired", at=self.now + timedelta(minutes=1))
        logins.remember(self.cfg, self.now + timedelta(minutes=2))
        self.assertEqual(self.row("claude:harbor", self.now + timedelta(minutes=2))["good_at"],
                         stamp(self.now))


class EventTest(Case):

    def test_a_turn_naming_a_lost_login_marks_its_dirs_row(self):
        self.assertTrue(logins.saw(self.cfg, self.talker_dir, TRANSCRIPT, at=self.now))
        self.assertEqual(self.row("claude:harbor")["state"], "expired")

    def test_other_failures_and_other_dirs_mark_nothing(self):
        self.assertFalse(logins.saw(self.cfg, self.talker_dir, "the network went away"))
        self.assertFalse(logins.saw(self.cfg, self.dir / "elsewhere", TRANSCRIPT))
        self.assertIsNone((logins.read(self.cfg)["rows"].get("claude:harbor") or {}).get("mark"))

    def test_a_refused_fetch_marks_the_rows_its_segment_declares(self):
        segment = self.dir / "segments" / "spend"
        segment.mkdir(parents=True)
        (segment / "segment.md").write_text("---\nname: spend\nlogins: google-tts, jev\n---\n")
        marked = logins.saw_fetch(self.cfg, segment, "FAILED (exit 1)\nHTTP 400: API key not valid")
        self.assertEqual(marked, ["google-tts", "jev"])
        self.assertEqual(logins.saw_fetch(self.cfg, segment, "FAILED (exit 1)\ntimeout"), [])

    def test_mark_ok_counts_as_a_good_check(self):
        logins.mark(self.cfg, "drive", "the store refused the login", at=self.now)
        logins.mark(self.cfg, "drive", "", ok=True, at=self.now + timedelta(minutes=1))
        entry = logins.read(self.cfg)["rows"]["drive"]
        self.assertEqual(entry["state"], "good")
        self.assertNotIn("mark", entry)


class ProbeTest(unittest.TestCase):
    def test_a_dir_never_logged_in_is_missing_only_when_the_probe_agrees(self):
        """c-560: the probe the hold's release makes decides; the dir's files only name it."""
        expired = {"state": "expired", "why": "Not logged in"}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(login, "probe", return_value=expired):
            self.assertEqual(loginprobe.claude(Path(tmp))["state"], "missing")
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(login, "probe", return_value={"state": "good"}):
            self.assertEqual(loginprobe.claude(Path(tmp))["state"], "good")

    def test_a_dir_with_a_login_is_probed(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(login, "probe", return_value={"state": "expired", "why": "x"}):
            (Path(tmp) / ".claude.json").write_text(json.dumps({"oauthAccount": {"a": 1}}))
            self.assertEqual(loginprobe.claude(Path(tmp))["state"], "expired")

    def test_the_forecast_reads_only_the_instant(self):
        with tempfile.TemporaryDirectory() as tmp:
            ends = datetime(2026, 10, 27, 5, 21, 52, tzinfo=timezone.utc)
            credentials(Path(tmp), ends)
            self.assertEqual(loginprobe.forecast(tmp), ends)
            self.assertIsNone(loginprobe.forecast(Path(tmp) / "none"))

    def test_rclones_refusal_is_expired(self):
        done = mock.Mock(returncode=1, stdout="", stderr=(
            'Failed to create file system: couldn\'t fetch token: oauth2: "invalid_grant" '
            '"Token has been expired or revoked."'))
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(loginprobe, "run", return_value=done), \
                mock.patch.object(loginprobe.shutil, "which", return_value="/bin/rclone"):
            conf = Path(tmp) / "rclone.conf"
            conf.write_text("[keel-drive]\n")
            found = loginprobe.drive(conf, "rclone:keel-drive:keel-backup")
        self.assertEqual(found["state"], "expired")

    def test_a_key_is_set_or_unset_never_red_and_never_read(self):
        """Both voice keys are optional, and install leaves an empty file for each on
        purpose: one never set is `unset`, which is not red (c-560)."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertEqual(loginprobe.key("google", home, systemd=True)["state"], "unset")
            from keel import voice
            source = voice.credentials_dir(home) / voice.KEYS["google"][0]
            source.parent.mkdir(parents=True)
            source.write_text("")
            empty = loginprobe.key("google", home, systemd=True)
            self.assertEqual(empty["state"], "unset")
            self.assertFalse(logins.red(empty))
            row = dict(empty, id="google-tts", label="Google TTS key", host="box", houses=False)
            self.assertEqual(health.login_items([row]), [])
            board = Board(make_config(home / "keel").db_path)
            self.addCleanup(board.close)
            self.assertEqual(loginask.sync(board, "box", [row])["raised"], [])
            source.write_text("not-read")
            with mock.patch.object(Path, "read_text", side_effect=AssertionError("read")):
                self.assertEqual(loginprobe.key("google", home, systemd=True)["state"], "good")

    def test_a_keychain_item_not_found_is_unset_and_any_other_failure_unknown(self):
        """macOS: `security` exits 44 for an item that is not there; any other failure (a
        locked keychain, a denied read) says nothing about whether the key is set."""
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "security"
            for code, state in ((0, "good"), (44, "unset"), (51, "unknown")):
                fake.write_text(f"#!/bin/sh\nexit {code}\n")
                fake.chmod(0o755)
                with mock.patch.dict(os.environ, {"PATH": tmp}):
                    found = loginprobe.key("google", Path(tmp), systemd=False)
                self.assertEqual(found["state"], state, code)
            self.assertIn("exit 51", found["why"])

    def test_an_adapters_rows_are_cleaned_and_a_failed_verb_is_unknown(self):
        space = mock.Mock()
        out = json.dumps({"logins": [{"id": "code-host", "label": "a token", "state": "expired",
                                      "why": "HTTP 401", "fix": "renew it"},
                                     {"id": "", "state": "good"},
                                     {"id": "odd", "state": "weird"}]})
        with mock.patch.object(loginprobe.adapters, "run", return_value=out):
            found, rows = loginprobe.adapter(space)
        self.assertEqual(found["state"], "good")
        self.assertEqual([(r["id"], r["state"]) for r in rows], [("code-host", "expired"), ("odd", "unknown")])
        with mock.patch.object(loginprobe.adapters, "run",
                               side_effect=loginprobe.adapters.AdapterError("exited 1")):
            found, rows = loginprobe.adapter(space)
        self.assertEqual((found["state"], rows), ("unknown", []))


if __name__ == "__main__":
    unittest.main()
