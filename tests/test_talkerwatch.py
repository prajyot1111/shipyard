"""The talker's output relay, its start stamp and fault file, and its health verdict."""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from keel import talker, talkerwatch

SESSION = "session_018on8q2KxLbtxsMyrx8TpFF"
URL = f"https://claude.ai/code/{SESSION}?from=cli"


class RelayTest(unittest.TestCase):
    def setUp(self):
        self.relay = talkerwatch.Relay(talker.URL_RE)

    def test_a_prompt_with_no_newline_is_seen(self):
        self.assertEqual(self.relay.feed(b"Enable Remote Control? (y/n) "),
                         {"prompt": "Enable Remote Control? (y/n)"})

    def test_any_trailing_yes_no_prompt_is_seen(self):
        self.assertIn("prompt", self.relay.feed(b"\x1b[1mTrust this folder? (y/n)\x1b[0m"))

    def test_a_yes_no_in_the_middle_of_output_is_not_a_prompt(self):
        self.assertEqual(self.relay.feed(b"answer with (y/n) when asked\nConnected\n"), {})

    def test_a_url_split_across_two_reads_is_still_found(self):
        half = len(URL) // 2
        self.assertEqual(self.relay.feed(URL[:half].encode()), {})
        self.assertEqual(self.relay.feed(URL[half:].encode() + b"\n"), {"session": SESSION})

    def test_the_same_session_is_reported_once_per_run(self):
        self.assertEqual(self.relay.feed(URL.encode() + b"\n"), {"session": SESSION})
        self.assertEqual(self.relay.feed(b"repaint " + URL.encode() + b"\n"), {})

    def test_a_prompt_after_the_session_is_not_a_fault(self):
        self.relay.feed(URL.encode() + b"\n")
        self.assertEqual(self.relay.feed(b"Something else? (y/n) "), {})


class VerdictTest(unittest.TestCase):
    NOW = 10_000.0

    def verdict(self, installed=True, running=True, started=NOW - 120, session_at=None,
                session="", fault=""):
        return talkerwatch.verdict(installed, running, self.NOW, started, session_at, session, fault)

    def test_not_installed_here_is_not_a_fault(self):
        self.assertEqual(self.verdict(installed=False, running=False)["state"], "not-installed")
        self.assertTrue(self.verdict(installed=False, running=False)["ok"])

    def test_installed_and_stopped_is_a_fault_and_carries_the_fault_text(self):
        found = self.verdict(running=False, fault="cannot assert consent")
        self.assertEqual((found["state"], found["ok"]), ("stopped", False))
        self.assertIn("cannot assert consent", found["reason"])

    def test_inside_the_first_minute_is_starting(self):
        found = self.verdict(started=self.NOW - 10)
        self.assertEqual((found["state"], found["ok"]), ("starting", True))

    def test_a_minute_with_no_session_is_a_fault(self):
        found = self.verdict(started=self.NOW - talkerwatch.NO_SESSION_AFTER)
        self.assertEqual((found["state"], found["ok"]), ("no-session", False))

    def test_a_session_from_an_earlier_run_is_not_this_runs(self):
        found = self.verdict(started=self.NOW - 120, session_at=self.NOW - 4000, session=SESSION)
        self.assertEqual((found["state"], found["ok"]), ("no-session", False))
        self.assertIn("earlier run", found["reason"])

    def test_a_session_recorded_this_run_is_serving(self):
        found = self.verdict(session_at=self.NOW - 100, session=SESSION)
        self.assertEqual((found["state"], found["ok"], found["session"]), ("serving", True, SESSION))

    def test_a_fault_wins_over_a_young_run(self):
        found = self.verdict(started=self.NOW - 5, fault="unanswered prompt")
        self.assertEqual((found["state"], found["ok"]), ("fault", False))


class HealthTest(unittest.TestCase):
    """`talker.health` reads the facts off the state files a real run leaves."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.paths = talker.Paths(root=root, state_dir=root / "state", home=root / "home")
        self.paths.state_dir.mkdir()

    def backdate(self, path: Path, seconds: float) -> None:
        when = time.time() - seconds
        os.utime(path, (when, when))

    @mock.patch("keel.talker.alive", return_value=True)
    def test_a_session_file_left_by_the_last_run_is_scoped_out_by_the_stamp(self, _alive):
        self.paths.session_file.write_text(SESSION + "\n")
        self.backdate(self.paths.session_file, 3600)
        talkerwatch.mark_start(self.paths.state_dir, now=time.time() - 90)
        found = talker.health(self.paths)
        self.assertEqual(found["state"], "no-session")
        self.assertIn(SESSION, found["reason"])

    @mock.patch("keel.talker.alive", return_value=True)
    def test_a_session_written_after_the_stamp_is_serving(self, _alive):
        talkerwatch.mark_start(self.paths.state_dir, now=time.time() - 90)
        self.paths.session_file.write_text(SESSION + "\n")
        self.assertEqual(talker.health(self.paths)["state"], "serving")

    def test_a_new_run_forgets_the_last_runs_fault(self):
        talkerwatch.write_fault(self.paths.state_dir, "old news")
        talkerwatch.mark_start(self.paths.state_dir)
        self.assertEqual(talkerwatch.read_fault(self.paths.state_dir), "")

    def test_stopped_is_a_fault_only_where_the_service_is_installed(self):
        self.assertEqual(talker.health(self.paths)["state"], "not-installed")
        unit = self.paths.manager.installed_dir
        unit.mkdir(parents=True)
        suffix = ".service" if self.paths.manager.kind == "systemd" else ".plist"
        (unit / f"{talker.LABEL}{suffix}").write_text("")
        self.assertEqual(talker.health(self.paths)["state"], "stopped")


if __name__ == "__main__":
    unittest.main()
