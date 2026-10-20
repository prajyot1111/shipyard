"""harness: parsing against the recorded probe, the argv and env of a start, ANSI, last_said.

`harness.run` is replaced with a fake fed from `tests/fixtures/harness/`; no test here
runs the `claude` binary.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from keel import harness

FIX = Path(__file__).resolve().parent / "fixtures" / "harness"
ROWS = json.loads((FIX / "agents.json").read_text())
BG_OUT = (FIX / "bg-start.out").read_bytes().decode("utf-8", errors="replace")
PROBE_UUID = "083b13ff-f95b-47e3-835c-9456642a2c2c"


class FakeRun:
    """Answers `claude <argv>` from the recordings and remembers every call."""

    def __init__(self, rows=None, bg_out=BG_OUT, logs="", returncode=0):
        self.rows, self.bg_out, self.logs, self.returncode = rows or [], bg_out, logs, returncode
        self.calls = []

    def __call__(self, argv, *, cwd=None, env=None, timeout=120, raw=False):
        self.calls.append({"argv": list(argv), "cwd": cwd, "env": env, "raw": raw})
        if argv[0] == "agents":
            return subprocess.CompletedProcess(argv, self.returncode, json.dumps(self.rows), "")
        if argv[0] == "logs":
            return subprocess.CompletedProcess(argv, 0, self.logs, "")
        if argv[0] == "stop":
            return subprocess.CompletedProcess(argv, self.returncode, "", "nope")
        return subprocess.CompletedProcess(argv, self.returncode, self.bg_out, "")


class ParseTest(unittest.TestCase):
    def test_backgrounded_line_from_the_recording(self):
        self.assertEqual(harness.parse_backgrounded(BG_OUT), ("083b13ff", "keel-probe"))

    def test_missing_line_is_a_harness_error(self):
        with self.assertRaises(harness.HarnessError):
            harness.parse_backgrounded("warning: nothing started\n")

    def test_agents_rows_and_find(self):
        with mock.patch.object(harness, "run", FakeRun(rows=ROWS)):
            rows = harness.agents()
        self.assertEqual([row["name"] for row in rows], ["cloud-ab", "keel-probe"])
        self.assertEqual(harness.find(PROBE_UUID, rows)["id"], "083b13ff")
        self.assertEqual(harness.find("083b13ff", rows)["pid"], 96132)
        self.assertIsNone(harness.find("ffffffff-0000-0000-0000-000000000000", rows))
        self.assertIsNone(harness.find("", rows))

    def test_agents_survives_a_failing_binary(self):
        with mock.patch.object(harness, "run", FakeRun(rows=ROWS, returncode=1)):
            self.assertEqual(harness.agents(), [])

    def test_agents_and_logs_run_under_the_given_config_dir(self):
        fake = FakeRun(rows=ROWS, logs="x")
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/inherited/.claude"}), \
                mock.patch.object(harness, "run", fake):
            harness.agents("/personal/.claude")
            harness.agents()
            harness.logs("083b13ff", "/personal/.claude")
        self.assertEqual(fake.calls[0]["env"]["CLAUDE_CONFIG_DIR"], "/personal/.claude")
        # No config dir inherits this process's own, as it always did; but as a copy now,
        # without `harness.WITHHELD` (c-451), rather than as None.
        self.assertEqual(fake.calls[1]["env"]["CLAUDE_CONFIG_DIR"], "/inherited/.claude")
        self.assertEqual(fake.calls[2]["env"]["CLAUDE_CONFIG_DIR"], "/personal/.claude")

    def test_agents_across_unions_the_config_dirs_once_each(self):
        fake = FakeRun(rows=ROWS)
        with mock.patch.object(harness, "run", fake):
            rows = harness.agents_across(["/a", "/b", "/a"])
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual([row["name"] for row in rows], ["cloud-ab", "keel-probe"])

    def test_logs_strip_ansi(self):
        raw = "\x1b[1mbold\x1b[0m line\r\n\x1b]0;title\x07next \x1b[?25l"
        with mock.patch.object(harness, "run", FakeRun(logs=raw)):
            self.assertEqual(harness.logs("083b13ff"), "bold line\nnext ")

    def test_a_cursor_move_forward_is_a_space(self):
        """The TUI draws a run of spaces as `ESC [ n C`; stripped, the log read
        "Aprove outcome doethat" (c-601, e2e bug 12)."""
        raw = "Implement,\x1b[1Ctest,\x1b[Cand\x1b[3Cwrite"
        with mock.patch.object(harness, "run", FakeRun(logs=raw)):
            self.assertEqual(harness.logs("083b13ff"), "Implement, test, and   write")

    def test_a_redraw_by_cursor_moves_keeps_its_spaces_and_unchanged_letters(self):
        """c-604: the TUI's redraw jumps over unchanged cells (`ESC [ n G`, `ESC [ r ; c H`);
        stripped, a Logs sheet read "Writing held-tap t st in test"."""
        first = "\x1b[2;3HWriting held-tap test in test_drain.py"
        second = "\x1b[H\r\x1b[1B\x1b[2CWriting held-tap t\x1b[22Gst\x1b[25Gin\x1b[28Gtest_\x1b[33Gboard.py"
        with mock.patch.object(harness, "run", FakeRun(logs=first + second)):
            said = harness.logs("083b13ff")
        self.assertEqual(said.splitlines()[1], "  Writing held-tap test in test_board.py")

    def test_the_screen_holds_its_edges(self):
        """c-604 review: column 0 is clamped, private and colon parameters and a DCS string are
        read as escapes, a wide character takes two cells, and only the log's tail is drawn."""
        self.assertEqual(harness.screen("ab\x1b[0Gc"), "cb")
        self.assertEqual(harness.screen("\x1b[>4;2mhi\x1b[38:2::1:2:3mX"), "hiX")
        self.assertEqual(harness.screen("\x1bPq#0;2;0;0;0\x1b\\x"), "x")
        self.assertEqual(harness.screen("\u65e5\x1b[3Gx"), "\u65e5x")
        big = "old line\r\n" * (harness.SCREEN_TAIL // 10 + 10) + "last"
        self.assertEqual(harness.screen(big).splitlines()[-1], "last")
        self.assertLessEqual(len(harness.screen(big)), harness.SCREEN_TAIL)

    def test_a_redrawn_log_keeps_its_carriage_returns(self):
        """c-605 review: `claude logs` draws with `\\r` and its own row moves (`ESC [ 1 B`);
        read with newline translation each `\\r` became a new row, so every line slid down one
        more row and the spinner's letters landed inside finished ones
        ("one-line1docstring2on9all_reports"). The sample is a real `claude logs` of a live
        session on this box (2026-09-30), read as bytes: 1144 returns, no line feed."""
        raw = (FIX / "logs-redraw.out").read_bytes().decode("utf-8")
        self.assertNotIn("\n", raw)
        fake = FakeRun(logs=raw)
        with mock.patch.object(harness, "run", fake):
            shown = [line.rstrip() for line in harness.logs("083b13ff").splitlines()]
        self.assertTrue(fake.calls[0]["raw"])
        self.assertEqual(len(shown), 57)        # the TUI's own rows (`ESC [ 57 ; 1 H`)
        for line in ("  - Retry leaves a duplicate session running.",
                     "  - A house can dodge the code-flow board by claiming \"no change\".",
                     "● Agent \"Sandbox e2e third run\" finished · 41m 37s",
                     "✻ Waiting for 2 background agents to finish"):
            self.assertIn(line, shown)

    def test_run_raw_keeps_carriage_returns(self):
        with mock.patch.object(harness, "command", lambda argv, env, cwd: (["printf", "a\\rb\\n"], None, None)):
            self.assertEqual(harness.run(["logs", "x"], raw=True).stdout, "a\rb\n")

    def test_line_feeds_are_new_lines_even_after_a_placement(self):
        self.assertEqual(harness.screen("\x1b[2;1Hstatus\nline one\nline two\nline three"),
                         "\nstatus\nline one\nline two\nline three")

    def test_stderr_after_stdout_starts_on_a_fresh_screen(self):
        out = subprocess.CompletedProcess(["logs"], 0, "\x1b[3;5Hdrawn", "warning: one\nwarning: two\n")
        with mock.patch.object(harness, "run", lambda argv, **kw: out):
            said = harness.logs("083b13ff").splitlines()
        self.assertEqual(said[-3:], ["    drawn", "warning: one", "warning: two"])

    def test_the_screen_keeps_rows_and_erases_what_the_line_erases(self):
        self.assertEqual(harness.screen("one\r\ntwo\x1b[1;1Hzz\x1b[K"), "zz\ntwo")


class ModelFlagTest(unittest.TestCase):
    """B1: every house turn names its model. With no flag `claude` falls to the account's
    own default, which is how c-272 ran on Fable for five days (c-434)."""


    def test_no_model_is_a_harness_error_and_never_a_launch(self):
        for empty in (None, ""):
            with self.assertRaisesRegex(harness.HarnessError, "model"):
                harness.session_flags("/s.json", model=empty)


class StartTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeRun(rows=ROWS)
        patches = [mock.patch.object(harness, "run", self.fake),
                   mock.patch.object(harness, "RESOLVE_PAUSE", 0),
                   mock.patch.dict(os.environ, {"KEEL_HOME": "/keel/home"})]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_start_bg_flags_env_and_session_resolution(self):
        result = harness.start_bg(
            "/tmp/probe", "do the card", name="keel-probe", config_dir="/cfg",
            settings_path="/s.json", model="opus", add_dirs=["/other"], restricted=True,
            tools="Read,Write")
        self.assertEqual(result, {"bg_id": "083b13ff", "session_id": PROBE_UUID})
        start = self.fake.calls[0]
        self.assertEqual(start["cwd"], "/tmp/probe")
        self.assertEqual(start["argv"], [
            "--bg", "--name", "keel-probe", "--remote-control", "keel-probe", "do the card",
            "--permission-mode", "auto",
            "--permission-prompts", "none", "--settings", "/s.json", "--model", "opus",
            "--restricted", "--disallowed-tools", "Agent(fork)", "--add-dir", "/other",
            "--tools", "Read,Write"])
        self.assertNotIn("--session-id", start["argv"])
        variadics = [i for i, flag in enumerate(start["argv"])
                     if flag in ("--disallowed-tools", "--add-dir", "--tools")]
        self.assertLess(start["argv"].index("do the card"), min(variadics))
        env = start["env"]
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], "/cfg")
        self.assertEqual(env["KEEL_CARD"], "keel-probe")
        self.assertEqual(env["KEEL_HOME"], "/keel/home")
        self.assertTrue(env["PATH"].startswith("/keel/home/etc/house-bin" + os.pathsep
                                               + "/keel/home/bin" + os.pathsep))
        self.assertEqual(self.fake.calls[1]["argv"], ["agents", "--json"])
        self.assertEqual(self.fake.calls[1]["env"]["CLAUDE_CONFIG_DIR"], "/cfg")

    def test_start_bg_keeps_the_short_id_when_agents_never_lists_it(self):
        self.fake.rows = [ROWS[0]]
        result = harness.start_bg("/tmp/probe", "p", name="keel-probe", config_dir="/cfg",
                                  settings_path="/s.json", model="opus")
        self.assertEqual(result, {"bg_id": "083b13ff", "session_id": "083b13ff"})
        self.assertEqual(len(self.fake.calls), 1 + harness.RESOLVE_TRIES)

    def test_start_bg_raises_when_claude_fails(self):
        self.fake.returncode = 1
        with self.assertRaises(harness.HarnessError):
            harness.start_bg("/tmp/probe", "p", name="keel-probe", config_dir="/cfg",
                             settings_path="/s.json", model="opus")

    def test_resume_bg_uses_the_same_flags(self):
        result = harness.resume_bg(PROBE_UUID, "continue", cwd="/tmp/probe", config_dir="/cfg",
                                   settings_path="/s.json", model="opus", name="keel-probe")
        self.assertEqual(result["session_id"], PROBE_UUID)
        argv = self.fake.calls[0]["argv"]
        self.assertEqual(argv[:8], ["--resume", PROBE_UUID, "--bg", "--name", "keel-probe",
                                    "--remote-control", "keel-probe", "continue"])
        self.assertIn("--permission-prompts", argv)
        self.assertEqual(argv[-2:], ["--disallowed-tools", "Agent(fork)"])
        self.assertEqual(self.fake.calls[0]["env"]["KEEL_CARD"], "keel-probe")


class ConversationGoneTest(unittest.TestCase):
    """c-654: a promptless `claude -p --resume <id>` that can use no tool, and only its own "No
    conversation found" means the conversation is gone (both answers recorded on 2.1.289)."""

    GONE = f"No conversation found with session ID: {PROBE_UUID}\n"
    THERE = ("Error: No deferred tool marker found in the resumed session. Either the session was "
             "not deferred, the marker is stale (tool already ran), or it exceeds the tail-scan "
             "window. Provide a prompt to continue the conversation.\n")

    def gone(self, stderr="", session_id: str = PROBE_UUID, code: int = 1, stdout="", raises=None,
             listed=()) -> tuple[bool, list]:
        calls = []

        def run_alone(argv, **kwargs):
            calls.append(dict(kwargs, argv=list(argv)))
            if raises is not None:
                raise raises
            return subprocess.CompletedProcess(argv, code, stdout, stderr)

        def run(argv, **kwargs):           # the full listing, asked only for a short id
            return subprocess.CompletedProcess(argv, 0, json.dumps(list(listed)), "")
        with mock.patch.object(harness, "run_alone", run_alone), mock.patch.object(harness, "run", run):
            return harness.conversation_gone(session_id, cwd="/tmp/probe", config_dir="/cfg"), calls

    def test_only_the_harness_saying_so_makes_a_conversation_gone(self):
        said, calls = self.gone(self.GONE)
        self.assertTrue(said)
        self.assertEqual(calls[0]["argv"][:3], ["-p", "--resume", PROBE_UUID], "no prompt: no turn")
        self.assertEqual(calls[0]["argv"][-2:], ["--tools", ""], "and no tool it could use")
        self.assertEqual((calls[0]["cwd"], calls[0]["env"]["CLAUDE_CONFIG_DIR"]), ("/tmp/probe", "/cfg"))
        self.assertEqual(calls[0]["timeout"], 15)
        self.assertFalse(self.gone(self.THERE)[0])
        self.assertFalse(self.gone("Not logged in\n")[0], "any other failure is not a guess")

    def test_a_probe_that_overran_failed_or_exited_clean_is_not_gone(self):
        overran = subprocess.TimeoutExpired(["-p"], 15)
        self.assertFalse(self.gone(raises=overran)[0], "killed at its limit: nothing was said")
        self.assertFalse(self.gone(raises=OSError("no such directory"))[0])
        self.assertFalse(self.gone(self.GONE, code=0)[0], "the phrase on a call that succeeded")
        self.assertTrue(self.gone(stdout=self.GONE)[0], "the harness may say it on either stream")

    def test_a_short_id_is_asked_by_its_uuid_or_not_at_all(self):
        """`-p --resume <short id>` answers "is not a UUID" (probed), so the short id a card
        kept is resolved through the full listing, and one nothing resolves is never asked."""
        self.assertEqual(self.gone(self.GONE, session_id=PROBE_UUID[:8]), (False, []))
        failed = {"id": PROBE_UUID[:8], "sessionId": PROBE_UUID, "kind": "background", "state": "failed"}
        said, calls = self.gone(self.GONE, session_id=PROBE_UUID[:8], listed=[failed])
        self.assertTrue(said)
        self.assertEqual(calls[0]["argv"][2], PROBE_UUID)


class StopRetryTest(unittest.TestCase):
    """r-17: `claude stop` can answer that it could not confirm the stop because its
    background service may be restarting, and asks to be tried again in a moment. The stop
    does exactly that once; any other failure, or the same one twice, still raises."""

    RESTARTING = ("couldn't confirm b6761eaa was stopped, the background service may be "
                  "restarting. Try again in a moment.")

    ROW = {"id": "b6761eaa", "sessionId": "b6761eaa-0000-4000-8000-000000000000",
           "kind": "background", "status": "idle"}

    def setUp(self):
        self.answers = []
        self.calls = []
        # What `claude agents --json` answers after the retry, one listing per look: a list
        # of rows, or None for a listing that fails. Empty until a test says otherwise, so
        # a stop that is never confirmed finds the session gone.
        self.listings = []
        patches = [mock.patch.object(harness, "run", self.fake_run),
                   mock.patch.object(harness, "STOP_RETRY_PAUSE", 0),
                   mock.patch.object(harness, "STOP_LOOK_PAUSE", 0)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def fake_run(self, argv, *, cwd=None, env=None, timeout=120):
        self.calls.append(list(argv))
        if argv[0] == "agents":
            rows = self.listings.pop(0) if self.listings else []
            if rows is None:
                return subprocess.CompletedProcess(argv, 1, "", "the service did not answer")
            return subprocess.CompletedProcess(argv, 0, json.dumps(rows), "")
        code, err = self.answers.pop(0)
        return subprocess.CompletedProcess(argv, code, "", err)

    def test_the_restarting_answer_is_retried_once_and_then_it_stops(self):
        self.answers = [(1, self.RESTARTING + "\n"), (0, "")]
        harness.stop("b6761eaa")
        self.assertEqual(self.calls, [["stop", "b6761eaa"], ["stop", "b6761eaa"]])

    def test_the_same_answer_twice_is_settled_by_the_listing_when_it_is_gone(self):
        """r-25: the harness could not confirm the stop twice, while the session had in fact
        stopped. The listing no longer shows it, so it is stopped, and nothing raises."""
        self.answers = [(1, self.RESTARTING), (1, self.RESTARTING)]
        harness.stop("b6761eaa", "/cfg/work")
        self.assertEqual([call[0] for call in self.calls], ["stop", "stop", "agents"])

    def test_a_row_that_lingers_a_moment_is_looked_at_again(self):
        """A stopped row drops out of the listing within seconds, not at once
        (tests/fixtures/harness/README.md), so one sighting is not yet a refusal."""
        self.answers = [(1, self.RESTARTING), (1, self.RESTARTING)]
        self.listings = [[self.ROW], [self.ROW], []]
        harness.stop("b6761eaa")
        self.assertEqual([call[0] for call in self.calls].count("agents"), 3)

    def test_still_listed_is_a_refusal_naming_the_session_and_the_command(self):
        self.answers = [(1, self.RESTARTING), (1, self.RESTARTING)]
        self.listings = [[self.ROW]] * (harness.STOP_LOOKS + 1)
        with self.assertRaises(harness.HarnessError) as raised:
            harness.stop("b6761eaa", "/cfg/work")
        said = str(raised.exception)
        self.assertIn("b6761eaa is still running", said)
        self.assertIn("CLAUDE_CONFIG_DIR=/cfg/work claude stop b6761eaa", said)
        self.assertNotIn("background service", said, "the generic line came back")
        self.assertEqual([call[0] for call in self.calls].count("agents"), harness.STOP_LOOKS)


    def test_a_listing_that_fails_is_a_refusal_too(self):
        """A failed listing is not "nothing is running": it is not knowing, and not knowing
        never gets a connect past a stop."""
        self.answers = [(1, self.RESTARTING), (1, self.RESTARTING)]
        self.listings = [None] * harness.STOP_LOOKS
        with self.assertRaises(harness.HarnessError) as raised:
            harness.stop("b6761eaa", "/cfg/work")
        self.assertIn("claude stop b6761eaa", str(raised.exception))
        self.assertIn("could not", str(raised.exception))

    def test_any_other_failure_is_not_retried(self):
        self.answers = [(1, "no such session\n")]
        with self.assertRaisesRegex(harness.HarnessError, "no such session"):
            harness.stop("b6761eaa")
        self.assertEqual(len(self.calls), 1)


class LastSaidTest(unittest.TestCase):
    def test_reads_the_assistant_text_blocks_in_order(self):
        said = harness.last_said(FIX / "transcript.jsonl")
        self.assertEqual(said, "PONG\nRan the check.\nIt passed.\nPONG2")


class DefaultConfigDirTests(unittest.TestCase):
    """The machine-default profile is reached with CLAUDE_CONFIG_DIR unset (see harness)."""

    def test_default_dir_clears_the_variable(self):
        from pathlib import Path
        env = harness.point_env({"CLAUDE_CONFIG_DIR": "/elsewhere"}, Path.home() / ".claude")
        self.assertNotIn("CLAUDE_CONFIG_DIR", env)


    def test_child_env_puts_the_house_shims_first_on_the_path(self):
        """`etc/house-bin` before `bin` before everything else: its `open` has to WIN, or a
        house opens a Chrome tab on a machine nobody is sitting at."""
        from pathlib import Path
        from keel import config as config_module
        env = harness.child_env("c-1", Path.home() / ".claude")
        home = config_module.repo_root()
        first, second = env["PATH"].split(":")[:2]
        self.assertEqual(Path(first), home / "etc" / "house-bin")
        self.assertEqual(Path(second), home / "bin")


class RemoteLinkTest(unittest.TestCase):
    """The app link is read from the session's own log, escapes and all (probe 2026-09-17)."""

    LOG = ("\x1b[2m/rc\x1b[0m\n/remote-control\x1b[1mis active\x1b[0m · Continue here, on your phone, "
           "or at https://claude.ai/code/session_01Q7n8exxgqsxNsR3b2Fwi8J\nPONG\n")

    def test_the_newest_link_is_returned(self):
        fake = FakeRun(bg_out="", rows=[], logs=self.LOG)
        with mock.patch.object(harness, "run", fake):
            self.assertEqual(harness.remote_link("a24e839f", "/cfg"),
                             "https://claude.ai/code/session_01Q7n8exxgqsxNsR3b2Fwi8J")
        self.assertEqual(fake.calls[0]["argv"], ["logs", "a24e839f"])


    def test_a_bare_flag_never_swallows_the_prompt(self):
        self.assertEqual(harness.remote_flags("c-1", True), ["--remote-control", "c-1"])
        self.assertEqual(harness.remote_flags("c-1", False), [])


class ConnectedTurnTest(unittest.TestCase):
    """`turn` and `wake`, against the recordings of the 2026-09-20 probe (card c-315)."""

    TURN = (FIX / "turn.json").read_text()
    WAKE_OUT = (FIX / "bg-wake.out").read_text()
    WAKE_ERR = (FIX / "bg-wake.err").read_text()
    REFUSED = (FIX / "turn-refused.err").read_text()
    UUID = "4e53210b-dde7-4610-ab4c-350c86264b79"

    def fake(self, stdout="", stderr="", returncode=0):
        calls = []

        def run(argv, *, cwd=None, env=None, timeout=120, **extra):
            calls.append({"argv": list(argv), "cwd": cwd, "env": env, "timeout": timeout})
            return subprocess.CompletedProcess(argv, returncode, stdout, stderr)
        return run, calls

    def test_a_turn_asks_for_json_and_puts_the_prompt_before_the_variadic_flags(self):
        run, calls = self.fake(stdout=self.TURN)
        with mock.patch.object(harness, "run_alone", run):
            payload = harness.turn(self.UUID, "what did I ask you first?", cwd="/w",
                                   config_dir="/cfg", settings_path="/s.json", model="opus")
        self.assertEqual(harness.turn_answer(payload),
                         "You first asked me to answer in one short sentence what 2 + 2 is.")
        argv = calls[0]["argv"]
        self.assertEqual(argv[:5], ["-p", "--resume", self.UUID, "--output-format", "json"])
        self.assertEqual(argv[5], "what did I ask you first?")
        self.assertLess(argv.index("what did I ask you first?"), argv.index("--disallowed-tools"))
        self.assertEqual(calls[0]["env"]["CLAUDE_CONFIG_DIR"], "/cfg")

    def test_the_refusal_while_the_process_is_alive_is_the_message(self):
        """The recorded refusal is what a caller has to recognise: it is why a connected
        turn stops the house first."""
        run, _ = self.fake(stderr=self.REFUSED, returncode=1)
        with mock.patch.object(harness, "run_alone", run):
            with self.assertRaises(harness.HarnessError) as caught:
                harness.turn(self.UUID, "hello", cwd="/w", config_dir="/cfg",
                             settings_path="/s.json", model="opus")
        self.assertIn(harness.RUNNING_REFUSAL, str(caught.exception))

    def test_an_errored_turn_raises_with_what_it_said(self):
        run, _ = self.fake(stdout=json.dumps({"is_error": True, "result": "context too long"}))
        with mock.patch.object(harness, "run_alone", run):
            with self.assertRaises(harness.HarnessError) as caught:
                harness.turn(self.UUID, "hello", cwd="/w", config_dir="/cfg",
                             settings_path="/s.json", model="opus")
        self.assertIn("context too long", str(caught.exception))

    def test_a_wake_passes_no_flags_and_no_prompt(self):
        """Any flag starts a COPY under a new id (2.1.278 says so in its own note), so the
        wake is three words and nothing else."""
        run, calls = self.fake(stdout=self.WAKE_OUT, stderr=self.WAKE_ERR)
        with mock.patch.object(harness, "run", run):
            woken = harness.wake(self.UUID, cwd="/w", config_dir="/cfg", name="c-315")
        self.assertEqual(calls[0]["argv"], ["--resume", self.UUID, "--bg"])
        self.assertEqual(woken, {"bg_id": "4e53210b", "session_id": self.UUID})


# The turn budget a wedged fake overruns, and the grace between its TERM and its KILL. The
# grace was the harness's own two seconds and is not what these tests prove, so it is a
# fraction.
OVERRUN = 1
QUICK_GRACE = 0.3
# How long a fake may take to get wedged before its budget starts to count (`gated_popen`).
READY_WAIT = 60.0


def gated_popen(ready: Path):
    """`subprocess.Popen` whose timed waits start counting only once the fake is wedged.

    The budget used to count from the spawn, and under load (a parallel run beside other
    builders, load average 14 to 17) it ran out before bash had set its trap, started its
    child or written the pid file: the TERM then killed a bash that had not yet made the
    thing the test is about, and the test failed on a missing file. The fake now touches
    `ready` once its trap is set, its child is running and its line is written, and a
    timed wait first waits for that (up to `READY_WAIT`, or until the process has exited on
    its own). What is proved is unchanged: the turn still overruns its budget, the
    harness's own timeout path still kills the group, and the child must be gone.
    """
    real = subprocess.Popen

    class Gated(real):
        def gate(self):
            deadline = time.monotonic() + READY_WAIT
            while (not ready.exists() and self.poll() is None
                   and time.monotonic() < deadline):
                time.sleep(0.02)

        def wait(self, timeout=None):
            if timeout is not None:
                self.gate()
            return super().wait(timeout)

        def communicate(self, input=None, timeout=None):
            if timeout is not None:
                self.gate()
            return super().communicate(input, timeout)

    return Gated


class WedgedFakeCase(unittest.TestCase):
    """A real fake `claude` that ignores TERM and has a child of its own, and a Popen whose
    timed waits count from the moment the fake is wedged (`gated_popen`)."""

    SCRIPT = ""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.ready = self.dir / "ready"
        self.script = self.dir / "fake-claude"
        self.script.write_text(self.SCRIPT.replace("@READY@", str(self.ready)))
        self.script.chmod(0o755)
        self.child = self.dir / "child.pid"
        # The fake ignores TERM, so every test here waited out the whole grace before the
        # KILL. Its length is not what is proved; that the KILL comes, to the group, is.
        for target, name, value in ((harness, "GROUP_GRACE", QUICK_GRACE),
                                    (harness.subprocess, "Popen", gated_popen(self.ready))):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return False
        return True

    def child_is_gone(self) -> bool:
        """The fake's child, read from the pid file the fake wrote before it was ready."""
        child = int(self.child.read_text().strip())
        deadline = time.monotonic() + 30
        while self.alive(child) and time.monotonic() < deadline:
            time.sleep(0.05)
        return not self.alive(child)


class TurnTimeoutTest(WedgedFakeCase):
    """A turn that overruns takes its CHILDREN with it.

    `subprocess.run(timeout=...)` kills the process it started and nothing that process
    started, so a wedged turn would leave a `claude` and its children holding memory on a
    12 GB box, which is the leak `bin/keel-browser` exists to prevent. This runs a REAL
    process group: a fake `claude` that ignores SIGTERM and has a child of its own.
    """

    SCRIPT = """#!/bin/bash
trap '' TERM                      # ignore the polite signal, exactly like a wedged process
sleep 300 &                       # the child that a leader-only kill would leave behind
echo $! > "$1"
: > "@READY@"                     # wedged: the budget may start counting now
sleep 300
"""

    def test_the_whole_group_is_killed_when_a_turn_overruns(self):
        with mock.patch.object(harness, "claude_bin", return_value=str(self.script)):
            with self.assertRaises(subprocess.TimeoutExpired):
                harness.run_alone([str(self.child)], timeout=OVERRUN)
        self.assertTrue(self.child_is_gone(), "the child of a wedged turn was left running")


class StreamedTurnTest(unittest.TestCase):
    """`turn_streamed`: the same turn with a reader on its stdout (V5, c-317).

    The records are the ones probed on the box against Claude Code 2.1.278 and recorded in
    `state/cards/c-317/probe/README.md`. The point of most of these is that nothing
    `run_alone` guarantees was given up to get the stream: same group, same group kill.
    """

    UUID = "11111111-2222-4333-8444-555555555555"

    def stream(self, *records):
        """A fake `claude` that writes one JSON record per line, in order."""
        return "\n".join(json.dumps(r) for r in records) + "\n"

    def fake(self, out: str, code: int = 0, err: str = ""):
        calls = []

        def stream_alone(argv, *, cwd=None, env=None, timeout=None, on_line=None):
            calls.append({"argv": argv, "cwd": cwd, "timeout": timeout})
            for line in out.splitlines(keepends=True):
                if on_line is not None:
                    on_line(line)
            return subprocess.CompletedProcess(argv, code, out, err)
        return stream_alone, calls

    def test_the_result_record_is_the_same_payload_a_json_turn_returns(self):
        """Streaming adds records BEFORE the one Keel already understands, it does not
        replace it, which is why `turn_answer` reads a streamed turn unchanged."""
        out = self.stream(
            {"type": "system", "subtype": "init", "session_id": self.UUID},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "/x"}}]}},
            {"type": "result", "subtype": "success", "result": "I merged the two phases.",
             "duration_ms": 4120})
        stream_alone, calls = self.fake(out)
        with mock.patch.object(harness, "stream_alone", stream_alone):
            payload = harness.turn_streamed(self.UUID, "merge them", cwd="/w",
                                            config_dir="/cfg", settings_path="/s.json", model="opus")
        self.assertEqual(harness.turn_answer(payload), "I merged the two phases.")
        self.assertEqual(calls[0]["argv"][:6],
                         ["-p", "--resume", self.UUID, "--output-format", "stream-json",
                          "--verbose"])

    def test_every_record_but_the_result_reaches_the_listener_as_it_arrives(self):
        out = self.stream(
            {"type": "system", "subtype": "init"},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {}}]}},
            {"type": "rate_limit_event"},
            {"type": "result", "result": "done"})
        seen = []
        stream_alone, _ = self.fake(out)
        with mock.patch.object(harness, "stream_alone", stream_alone):
            harness.turn_streamed(self.UUID, "x", cwd="/w", config_dir="/cfg",
                                  settings_path="/s.json", model="opus", on_record=seen.append)
        self.assertEqual([r["type"] for r in seen],
                         ["system", "assistant", "rate_limit_event"])

    def test_a_line_that_is_not_a_record_is_not_an_error(self):
        out = "not json at all\n" + self.stream({"type": "result", "result": "fine"})
        stream_alone, _ = self.fake(out)
        with mock.patch.object(harness, "stream_alone", stream_alone):
            payload = harness.turn_streamed(self.UUID, "x", cwd="/w", config_dir="/cfg",
                                            settings_path="/s.json", model="opus")
        self.assertEqual(harness.turn_answer(payload), "fine")

    def test_a_listener_that_raises_never_costs_the_answer(self):
        """A narration that failed is a quieter wait, never a lost turn. The guard is in
        `stream_alone`, so this drives the real one rather than the fake."""
        out = self.stream({"type": "assistant", "message": {"content": []}},
                          {"type": "result", "result": "still answered"})
        script = self.write_script(out)
        with mock.patch.object(harness, "claude_bin", return_value=str(script)):
            payload = harness.turn_streamed(self.UUID, "x", cwd=script.parent,
                                            config_dir=None, settings_path="/s.json", model="opus",
                                            on_record=self.explode)
        self.assertEqual(harness.turn_answer(payload), "still answered")

    @staticmethod
    def explode(_record):
        raise RuntimeError("the narrator fell over")

    def write_script(self, out: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        script = Path(tmp.name) / "fake-claude"
        script.write_text("#!/usr/bin/env python3\nimport sys\nsys.stdout.write("
                          + repr(out) + ")\n")
        script.chmod(0o755)
        return script

    def test_a_turn_that_streams_no_result_is_an_error_not_a_silence(self):
        out = self.stream({"type": "assistant", "message": {"content": []}})
        stream_alone, _ = self.fake(out)
        with mock.patch.object(harness, "stream_alone", stream_alone):
            with self.assertRaises(harness.HarnessError):
                harness.turn_streamed(self.UUID, "x", cwd="/w", config_dir="/cfg",
                                      settings_path="/s.json", model="opus")


class StreamedGroupTest(WedgedFakeCase):
    """The streamed turn keeps the process group and the group kill (c-315's fix round).

    A reader on the pipe is the only thing added, and a wedged turn must still take its
    children with it. Same real fake-claude shape as `TurnTimeoutTest`, with output on
    stdout first so there is something to have read.
    """

    SCRIPT = """#!/bin/bash
trap '' TERM
echo '{"type": "assistant", "message": {"content": []}}'
sleep 300 &
echo $! > "$1"
: > "@READY@"                     # wedged: the budget may start counting now
sleep 300
"""

    def test_a_wedged_streamed_turn_takes_its_children_with_it(self):
        heard = []
        with mock.patch.object(harness, "claude_bin", return_value=str(self.script)):
            with self.assertRaises(subprocess.TimeoutExpired):
                harness.stream_alone([str(self.child)], timeout=OVERRUN, on_line=heard.append)
        self.assertTrue(heard, "the reader saw nothing before the kill")
        self.assertTrue(self.child_is_gone(), "the child of a wedged streamed turn was left running")

    def test_what_was_heard_before_the_kill_is_on_the_timeout(self):
        """The partial is what `converse.record_stopped` writes onto the card."""
        with mock.patch.object(harness, "claude_bin", return_value=str(self.script)):
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                harness.stream_alone([str(self.child)], timeout=OVERRUN)
        self.assertIn("assistant", caught.exception.output or "")


# ----- the kept-alive conversation (V12) -----

# A STAND-IN THAT IS A REAL PROCESS, because the mechanics being tested here ARE the
# process: a pipe on stdin, records arriving on stdout while the caller waits, EOF when
# stdin closes, and a process group that goes as a group. A mock with a fake pipe would
# pass every one of those without any of them being true. It speaks the shape the probe
# recorded on 2026-09-20 (`--input-format stream-json`): one user record in per sentence,
# `stream_event` text deltas out, then one `result` record.
FAKE_CONVERSATION = r'''#!{python}
import json, sys, time

MODE = sys.argv[1] if len(sys.argv) > 1 else "answer"
turn = 0
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    turn += 1
    said = json.loads(line)["message"]["content"][0]["text"]
    if MODE == "wedge":
        time.sleep(300)
    if MODE == "die":
        sys.exit(3)
    print(json.dumps({"type": "assistant", "parent_tool_use_id": None,
                      "message": {"content": [{"type": "tool_use", "name": "Read",
                                               "input": {}}]}}), flush=True)
    for piece in ("Phase two ", "is merged. ", "The tests pass."):
        print(json.dumps({"type": "stream_event",
                          "event": {"type": "content_block_delta",
                                    "delta": {"type": "text_delta", "text": piece}}}),
              flush=True)
    print(json.dumps({"type": "result", "is_error": False, "num_turns": turn,
                      "result": "Phase two is merged. The tests pass.",
                      "heard": said}), flush=True)
sys.stderr.write("done\n")
'''


class ConversationTest(unittest.TestCase):
    """One kept-alive `claude` that takes sentence after sentence (V12).

    Every case runs a real process, spawned through the one replaceable name
    (`harness.popen_alone`), so what is proved is the plumbing and not a mock of it.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.script = self.dir / "fake-claude"
        self.script.write_text(FAKE_CONVERSATION.replace("{python}", sys.executable))
        self.script.chmod(0o755)
        self.argv = []

    def open(self, mode="answer", **kwargs):
        def spawn(argv, *, cwd=None, env=None):
            self.argv.append(list(argv))
            return subprocess.Popen([str(self.script), mode], cwd=cwd, env=env,
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, bufsize=1,
                                    start_new_session=True)

        with mock.patch.object(harness, "popen_alone", spawn):
            talk = harness.open_conversation(PROBE_UUID, cwd=self.dir, config_dir=None,
                                             settings_path="/s.json",
                                             **dict({"model": "opus"}, **kwargs))
        self.addCleanup(talk.close)
        return talk

    def test_every_sentence_is_one_write_into_the_same_process(self):
        """The whole of V12: the session is resumed ONCE, and the second sentence pays
        nothing for the first one's start."""
        talk = self.open()
        first = talk.say("where are you up to")
        second = talk.say("and the tests?")
        self.assertEqual(harness.turn_answer(first), "Phase two is merged. The tests pass.")
        self.assertEqual(first["heard"], "where are you up to")
        self.assertEqual(second["heard"], "and the tests?")
        self.assertEqual(second["num_turns"], 2)
        self.assertEqual(len(self.argv), 1, "a second process was started")

    def test_it_is_asked_for_the_streaming_shape_under_the_card_s_own_flags(self):
        self.open(model="opus", add_dirs=["/other"], restricted=True)
        argv = self.argv[0]
        self.assertEqual(argv[:3], ["-p", "--resume", PROBE_UUID])
        for flag in ("--input-format", "stream-json", "--output-format", "--verbose",
                     "--include-partial-messages"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--model") + 1], "opus")
        self.assertIn("--restricted", argv)
        self.assertEqual(argv[argv.index("--settings") + 1], "/s.json")


    def test_a_process_that_dies_is_a_harness_error_and_the_object_is_dead(self):
        talk = self.open("die")
        with self.assertRaises(harness.HarnessError):
            talk.say("where are you up to")
        self.assertFalse(talk.alive)
        with self.assertRaises(harness.HarnessError):
            talk.say("again")

    def test_a_turn_that_overruns_is_ended_and_the_object_is_dead(self):
        talk = self.open("wedge")
        with self.assertRaises(harness.HarnessError) as caught:
            talk.say("where are you up to", timeout=1)
        self.assertIn("it was ended", str(caught.exception))
        self.assertFalse(talk.alive)

    def test_closing_shuts_stdin_and_the_process_goes_by_itself(self):
        """Which is also what happens when `keel serve` exits: the pipe closes, and
        nothing of the conversation is left running."""
        talk = self.open()
        talk.say("where are you up to")
        pid = talk.proc.pid
        talk.close()
        self.assertFalse(talk.alive)
        with self.assertRaises((ProcessLookupError, OSError)):
            os.killpg(os.getpgid(pid), 0)

    def test_a_wedged_conversation_is_killed_as_a_group_on_close(self):
        talk = self.open("wedge")
        pid = talk.proc.pid
        talk.close()
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                os.killpg(os.getpgid(pid), 0)
            except (ProcessLookupError, OSError):
                return
            time.sleep(0.1)
        self.fail("the wedged conversation's group was left running")


class StreamTextTest(unittest.TestCase):
    """Only the words the house is SAYING come out of a record (V12)."""

    def delta(self, kind, text):
        return {"type": "stream_event", "event": {"type": "content_block_delta",
                                                  "delta": {"type": kind, "text": text}}}

    def test_a_text_delta_is_the_answer_arriving(self):
        self.assertEqual(harness.stream_text(self.delta("text_delta", "Phase ")), "Phase ")

    def test_thinking_and_tool_input_are_not(self):
        """Neither is spoken, and one of them would read a tool's arguments out loud."""
        self.assertEqual(harness.stream_text(self.delta("thinking_delta", "hmm")), "")
        self.assertEqual(harness.stream_text(self.delta("input_json_delta", '{"path":')), "")

