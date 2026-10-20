"""keel/login.py: the words, the probe's verdicts, the ten-minute memory, and the one call
`harness.login_probe` makes. The words were read out of Claude Code 2.1.281 itself, and the
`Not logged in` answer was recorded from a real `claude -p` under a config dir with no
login (2026-09-24)."""

import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from keel import harness, login
from tests.helpers import FakeHarness, make_config

# What 2.1.281 prints when the login is gone, verbatim from the binary.
GONE = (
    "Login expired · Please run /login",
    "Not logged in · Please run /login",
    "OAuth token revoked · Please run /login",
    "Login expired · Run /login to sign in again, or re-authenticate your Anthropic profile",
    "Anthropic profile login expired · Re-authenticate your Anthropic profile",
    "Invalid API key · Fix external API key",
    "Authentication required · Sign in again to continue",
    'API Error: 401 {"type":"error","error":{"type":"authentication_error",'
    '"message":"OAuth token has expired. Please obtain a new token."}}',
)
# And what it prints for failures that are NOT a lost login, which must never read as one.
NOT_GONE = (
    "Could not refresh your login because another Claude Code process is refreshing it "
    "(or exited mid-refresh) · Try again in a minute; if it keeps happening, close "
    "other Claude Code windows or sign in again with /login",
    "Authentication error · This may be a temporary network issue, please try again",
    "You've hit your session limit · resets 9:40pm (Asia/Calcutta)",
    "API Error: 529 Overloaded. This is a server-side issue, usually temporary",
    "I rewrote the fetcher and the tests pass.",
)


def done(out: str, code: int, err: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["-p"], code, out, err)


class WordsTest(unittest.TestCase):
    def test_every_way_the_harness_says_the_login_is_gone(self):
        for text in GONE:
            self.assertTrue(login.names_login(text), text)

    def test_transient_failures_and_ordinary_words_are_not_a_lost_login(self):
        for text in NOT_GONE:
            self.assertFalse(login.names_login(text), text)
        self.assertFalse(login.names_login(None))


class ClassifyTest(unittest.TestCase):
    def test_the_recorded_answer_under_no_login_is_expired(self):
        found = login.classify(done("Not logged in · Please run /login\n", 1))
        self.assertEqual(found, {"state": login.EXPIRED,
                                 "why": "Not logged in · Please run /login"})


    def test_the_words_win_over_a_zero_exit(self):
        self.assertEqual(login.classify(done("Login expired · Please run /login", 0))["state"],
                         login.EXPIRED)

    def test_anything_else_is_unknown_and_says_why(self):
        found = login.classify(done("", 1, "You've hit your session limit · resets 9pm"))
        self.assertEqual(found["state"], login.UNKNOWN)
        self.assertIn("session limit", found["why"])

    def test_a_timeout_or_a_missing_binary_is_unknown(self):
        fake = FakeHarness()
        fake.login_probe = mock.Mock(side_effect=subprocess.TimeoutExpired(["claude"], 45))
        with mock.patch.object(login, "harness", fake):
            self.assertEqual(login.probe("/cfg")["state"], login.UNKNOWN)
        fake.login_probe = mock.Mock(side_effect=FileNotFoundError("claude"))
        with mock.patch.object(login, "harness", fake):
            self.assertEqual(login.probe("/cfg")["state"], login.UNKNOWN)


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = make_config(Path(self.tmp.name))
        self.fake = FakeHarness()
        patch = mock.patch.object(login, "harness", self.fake)
        patch.start()
        self.addCleanup(patch.stop)
        self.at = datetime.now().astimezone()

    def tearDown(self):
        self.tmp.cleanup()

    def probes(self) -> int:
        return len(getattr(self.fake, "probes", []))

    def test_an_answer_is_kept_for_ten_minutes_per_space(self):
        self.assertEqual(login.check(self.cfg, "personal", at=self.at)["state"], login.GOOD)
        login.check(self.cfg, "personal", at=self.at + timedelta(minutes=9))
        self.assertEqual(self.probes(), 1)
        login.check(self.cfg, "work", at=self.at + timedelta(minutes=9))
        self.assertEqual(self.probes(), 2, "another space is its own question")
        self.fake.login_answer = ("Login expired · Please run /login", 1)
        entry = login.check(self.cfg, "personal", at=self.at + timedelta(minutes=10))
        self.assertEqual(entry["state"], login.EXPIRED)
        self.assertEqual(entry["at"], (self.at + timedelta(minutes=10)).isoformat(timespec="seconds"))
        self.assertTrue(login.is_expired(self.cfg, "personal"))
        self.assertFalse(login.is_expired(self.cfg, "work"))


    def test_the_file_is_the_state_dirs_and_survives_a_bad_write(self):
        self.assertEqual(login.read(self.cfg), {})
        (self.cfg.state_dir / login.FILE).write_text("{not json")
        self.assertEqual(login.read(self.cfg), {})
        login.check(self.cfg, "personal", at=self.at)
        self.assertEqual(set(login.read(self.cfg)), {"personal"})


class ProbeCallTest(unittest.TestCase):
    def test_one_word_nothing_saved_the_prompt_before_the_variadic_flag_and_no_token(self):
        seen = {}

        def run_alone(argv, *, cwd=None, env=None, timeout=None):
            seen.update(argv=argv, env=env, timeout=timeout, cwd=cwd)
            return done("ok\n", 0)

        with mock.patch.dict("os.environ", {"KEEL_TOKEN": "his", "KEEL_LIVE_STATE": "1"}), \
                mock.patch.object(harness, "run_alone", side_effect=run_alone):
            self.assertEqual(login.probe("/spaces/personal/.claude")["state"], login.GOOD)
        argv = seen["argv"]
        self.assertEqual(argv[:2], ["-p", harness.LOGIN_PROMPT])
        for flag in ("--no-session-persistence", "--strict-mcp-config"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")
        self.assertEqual(argv[-2:], ["--tools", ""])
        self.assertEqual(seen["env"]["CLAUDE_CONFIG_DIR"], "/spaces/personal/.claude")
        self.assertNotIn("KEEL_TOKEN", seen["env"])
        self.assertNotIn("KEEL_LIVE_STATE", seen["env"])
        self.assertEqual(seen["timeout"], login.PROBE_TIMEOUT)
        self.assertFalse(Path(seen["cwd"]).exists(), "a scratch cwd, gone afterwards")


if __name__ == "__main__":
    unittest.main()
