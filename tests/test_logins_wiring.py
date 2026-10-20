"""The Logins list where it meets the rest of Keel (c-558): a drain pass raises and then
withdraws this machine's login asks (and none for a mark no check has run since), a dir with
no login holds its space's houses, the voice gateway's hooks mark and unmark a key, and a
key's refusal outlives its presence check."""

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from keel import asks, drain, login, loginask, loginhold, logins
from tests.test_drain import DrainCase
from tests.helpers import SESSION, background_row, make_config

VOICE = Path(__file__).resolve().parent.parent / "voice"
if str(VOICE) not in sys.path:
    sys.path.insert(0, str(VOICE))


def red_row(**extra):
    return dict({"id": "claude:work", "label": "Claude work", "state": "expired",
                 "why": "a turn said: Not logged in", "where": "/Users/p/.claude",
                 "fix": "claude auth login", "houses": True, "good_at": None}, **extra)

class DrainPassTest(DrainCase):
    def test_a_pass_raises_this_machines_ask_and_a_later_one_withdraws_it(self):
        with mock.patch.object(logins, "public", return_value=[red_row(host=self.cfg.host)]), \
                mock.patch.object(logins, "upkeep", return_value={"checked": [], "red": 1}):
            self.once()
        held = loginask.rows_for(self.board, self.cfg.host)
        self.assertEqual([a["state"] for a in held], ["open"])
        with mock.patch.object(logins, "public", return_value=[red_row(state="good")]), \
                mock.patch.object(logins, "upkeep", return_value={"checked": [], "red": 0}):
            self.once()
        self.assertEqual(asks.get(self.board, held[0]["id"])["state"], "withdrawn")

    def personal_asks(self):
        return [a for a in loginask.rows_for(self.board, self.cfg.host)
                if loginask.facts_of(a)["id"] == "claude:personal"]

    def test_a_mark_no_check_has_run_since_asks_nothing_until_the_check_confirms_it(self):
        """c-560: words can mark falsely, so the pass that sees a fresh mark checks it before
        any ask: a false mark never reaches his Needs you, and a true one asks a pass later."""
        logins.mark(self.cfg, "claude:personal", "a turn said: Login expired")
        self.once()
        self.assertIn("logins: checked claude:personal", self.log_text())
        self.assertEqual(self.personal_row()["state"], "good")
        self.assertEqual(self.personal_asks(), [], "the check it got found the login working")
        logins.mark(self.cfg, "claude:personal", "a turn said: Login expired",
                    at=logins.now() + timedelta(minutes=1))
        self.fake.login_answer = ("Not logged in · Please run /login", 1)
        with mock.patch.object(logins, "now", return_value=logins.now() + timedelta(minutes=2)):
            self.once()
            self.assertEqual(self.personal_asks(), [])
            self.once()
        self.assertEqual([a["state"] for a in self.personal_asks()], ["open"])

    def personal_row(self) -> dict:
        return next(row for row in logins.public(self.cfg) if row["id"] == "claude:personal")

    def test_a_mark_whose_check_cannot_say_is_checked_again_soon_and_asks_once_confirmed(self):
        """c-560: a check that answers unknown neither refutes nor confirms a mark, so the
        row stays red and is asked again at RED_EVERY, not a day later."""
        self.start = datetime.now().astimezone()
        logins.mark(self.cfg, "claude:personal", "a turn said: Login expired", at=self.start)
        self.fake.login_answer = ("Connection error", 1)
        self.pass_at(0)
        self.assertEqual(self.personal_asks(), [])
        self.fake.login_answer = ("Not logged in · Please run /login", 1)
        self.pass_at(11)
        self.pass_at(12)
        self.assertEqual([a["state"] for a in self.personal_asks()], ["open"])

    def test_a_mark_no_check_can_settle_asks_after_two_red_periods(self):
        """A broken login and a flaky check look the same to him, so a mark only unknown
        answers follow is asked about once it is two RED_EVERY periods old."""
        self.start = datetime.now().astimezone()
        logins.mark(self.cfg, "claude:personal", "a turn said: Login expired", at=self.start)
        self.fake.login_answer = ("Connection error", 1)
        self.pass_at(0)
        self.pass_at(11)
        self.assertEqual(self.personal_asks(), [])
        self.pass_at(22)
        self.pass_at(33)
        self.assertEqual([a["state"] for a in self.personal_asks()], ["open"])

    def test_a_mark_the_holds_probe_refuted_is_not_revived_by_its_next_unknown_one(self):
        """c-560: the hold's good probe lands in `login.json` before the list's pass, so the
        list's own check in that pass drops the refuted mark; a later unknown probe of the
        hold's then has no mark to bring back, and no ask is raised on a working login."""
        self.start = datetime.now().astimezone()
        logins.mark(self.cfg, "claude:personal", "a turn said: Login expired", at=self.start)
        self.fake.login_answer = ("ok", 0)
        login.check(self.cfg, "personal", at=self.start + timedelta(minutes=1))
        self.pass_at(1)
        self.fake.login_answer = ("Connection error", 1)
        login.check(self.cfg, "personal", at=self.start + timedelta(minutes=21))
        self.pass_at(21)
        self.assertEqual(self.personal_asks(), [])

    def pass_at(self, minutes: int) -> dict:
        """One pass `minutes` from now by every clock it reads: the drain's, the board's and
        the Logins list's."""
        at = self.start + timedelta(minutes=minutes)
        with mock.patch.object(drain, "now", return_value=at), \
                mock.patch.object(logins, "now", return_value=at), \
                mock.patch.object(self.board, "now", return_value=at.isoformat(timespec="seconds")):
            return self.once()

    def test_a_dir_with_no_login_holds_its_houses_and_logging_in_releases_them_once(self):
        """c-560: the list's `missing` reaches the drain's hold as an expired login, and the
        hold and its release ask the one probe: once the harness answers for the login (on
        macOS it lives in the keychain, with no file to see), the next list check does not
        hold the houses again. Only the harness boundary is stubbed."""
        self.start = datetime.now().astimezone()
        (self.cfg.spaces["personal"].config_dir / ".credentials.json").unlink()
        self.fake.login_answer = ("Not logged in · Please run /login", 1)
        card_id = self.housed()
        self.fake.rows.append(background_row(card_id, SESSION))
        self.board.record_hook(card_id, "Notification", {
            "hook_event_name": "Notification", "notification_type": "idle_prompt",
            "session_id": SESSION, "transcript_path": f"/t/{SESSION}.jsonl"})
        self.cfg.drain_paused = True
        self.pass_at(0)
        self.assertEqual(self.pass_at(1).get("login"), 1)
        self.assertEqual(self.fake.resumes, [])
        self.assertEqual(loginhold.held_space(self.board, self.board.get(card_id)), "personal")
        self.fake.login_answer = ("ok", 0)
        self.assertEqual(self.pass_at(12).get("relogged"), 1)
        self.assertIsNone(self.board.get(card_id)["blocked_reason"])
        self.fake.rows[-1] = background_row(card_id, SESSION, status="busy")
        self.pass_at(13)
        checks = self.log_text().count("logins: checked claude:personal")
        self.pass_at(24 * 60 + 13)
        self.assertGreater(self.log_text().count("logins: checked claude:personal"), checks,
                           "the list's daily check ran")
        self.assertEqual(login.state_of(self.cfg, "personal"), login.GOOD)
        self.fake.rows[-1] = background_row(card_id, SESSION)
        self.assertNotIn("login", self.pass_at(24 * 60 + 14))
        self.assertIsNone(self.board.get(card_id)["blocked_reason"])
        self.assertEqual(len([r for r in self.fake.resumes if "login" in r["prompt"]]), 1)

    def test_a_check_that_raises_never_fails_the_pass(self):
        with mock.patch.object(logins, "upkeep", side_effect=RuntimeError("boom")):
            self.assertIn("houses", self.once())


class KeyMarkTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = make_config(Path(tmp.name))
        self.spec = logins.Login(id="google-tts", kind="key", label="Google TTS key", where="x",
                                 target="google")
        self.now = datetime(2026, 9, 27, 8, 0, tzinfo=timezone.utc)

    def state(self, at):
        return logins.state_of(self.cfg, self.spec, logins.read(self.cfg), at)["state"]

    def test_a_refused_key_stays_red_through_its_presence_check_until_a_success(self):
        logins.mark(self.cfg, "google-tts", "Google TTS answered HTTP 403", at=self.now)
        logins.keep(self.cfg, self.spec, {"state": "good", "why": ""}, None,
                    self.now + timedelta(minutes=1))
        self.assertEqual(self.state(self.now + timedelta(minutes=2)), "expired")
        logins.mark(self.cfg, "google-tts", "", ok=True, at=self.now + timedelta(minutes=3))
        self.assertEqual(self.state(self.now + timedelta(minutes=4)), "good")


class GatewayHookTest(unittest.TestCase):
    """The gateway marks into its own state dir, never one a config load would find."""

    def setUp(self):
        from harbor_voice import config, loginmark
        self.loginmark = loginmark
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name)
        patch = mock.patch.object(config, "STATE", self.state)
        patch.start()
        self.addCleanup(patch.stop)
        for kept in (loginmark._last, loginmark._seen):
            kept.clear()
            self.addCleanup(kept.clear)
        self.where = logins.At(self.state)

    def marked(self, row_id):
        return "mark" in (logins.read(self.where)["rows"].get(row_id) or {})

    def test_a_refusal_marks_once_a_minute_and_the_next_success_unmarks(self):
        self.assertTrue(self.loginmark.refused("google-tts", "Google TTS answered HTTP 403"))
        self.assertFalse(self.loginmark.refused("google-tts", "HTTP 403"), "once a minute")
        self.assertTrue(self.marked("google-tts"))
        self.assertTrue(self.loginmark.works("google-tts"))
        self.assertFalse(self.marked("google-tts"))
        self.assertFalse(self.loginmark.works("google-tts"), "an unchanged file is not read")

    def test_a_mark_written_later_by_anyone_comes_off_on_the_next_success(self):
        self.loginmark.works("google-tts")
        logins.mark(self.where, "google-tts", "the cloud-spend fetch was refused: API key not valid")
        self.assertTrue(self.loginmark.works("google-tts"))
        self.assertFalse(self.marked("google-tts"))

    def test_a_look_that_fails_is_tried_again(self):
        with mock.patch.object(logins, "unmark_at", side_effect=[False, True]) as looked:
            self.assertFalse(self.loginmark.works("jev"))
            self.assertTrue(self.loginmark.works("jev"))
        self.assertEqual(looked.call_count, 2)

    def test_a_failed_harbor_turn_marks_the_talker_dirs_row_in_the_gateways_state(self):
        from harbor_voice import config, harbormsg
        with mock.patch.object(config, "TALKER_CONFIG_DIR", Path("/k/spaces/harbor/.claude")), \
                mock.patch.object(harbormsg, "log"):
            harbormsg.report_failure("s", "hello", "RuntimeError: Failed to authenticate: "
                                     "OAuth session expired and could not be refreshed")
        self.assertTrue(self.marked("claude:harbor"))


if __name__ == "__main__":
    unittest.main()
