"""Bosun's console (c-519): actor `bosun`, the session's lifecycle, and what
the deck draws of it (the console space is retired, c-593) (`keel/console.py`, docs/atlas/96-bosun.md).

Every launch here is a fake: nothing in this file starts a Claude session. The real start,
the idle wait and the resume after a Stop were proved on the box by hand, and the outcome of
c-519 says what they showed.
"""

import io
import json
import shutil
import subprocess
import os
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from keel import (actions, asks, bosunhello, cli, config as config_module, console, consolehandoff,
                  consoletaps, deckdigest,
                  deckstate, deployask, drain, serve)
from keel.board import Board, Refused
from tests.helpers import TWO_MACHINE_TOML, give_bosun_key, make_config, superuser_builder
from tests.test_cli import KbCase

ROOT = Path(__file__).resolve().parent.parent
SESSION = "b10ffe2f-60a6-4141-b3ef-62abdd02aadc"
RESUMED = "c20ffe2f-60a6-4141-b3ef-62abdd02aadc"
FRESH = "d30ffe2f-60a6-4141-b3ef-62abdd02aadc"


def console_toml(directory: Path) -> Path:
    path = directory / "keel.toml"
    path.write_text(
        "[keel]\n"
        f'state_dir = "{directory / "state"}"\n'
        f'adapters_dir = "{directory / "adapters"}"\n'
        'host = "box"\n'
        "[spaces.personal]\n"
        'config_dir = "~/nowhere"\n'
        "[spaces.personal.repos]\n"
        'keel = "~/keel"\n'
        "[console]\n"
        'host = "box"\n'
        "context_window = 200000\n")
    return path


class ConfigTest(unittest.TestCase):
    def test_the_console_table_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config_module.load(console_toml(Path(tmp)), ensure=False)
        self.assertNotIn("console", cfg.spaces, "the console space is retired (c-593)")
        self.assertEqual(console.conf(cfg)["context_window"], 200000)
        self.assertEqual(console.conf(cfg)["compact_at"], 70, "a key the toml leaves out takes its default")

    def test_a_two_machine_toml_still_loads_and_names_its_bosun_keys(self):
        """c-622: the config Keel had on two machines loads on one; the host tables are a
        warning, not a crash. r1.F7/F8: a `[console] host` naming the box reads as this one and is
        said, and the keys that made Bosun its own user are named as unsupported."""
        cfg = config_module.load(TWO_MACHINE_TOML, ensure=False)
        self.assertTrue(console.configured(cfg), "Bosun runs here, even off an install")
        self.assertEqual(console.conf(cfg)["permission_mode"], "bypassPermissions")
        self.assertNotIn("console", cfg.spaces, "the console space is retired (c-593)")
        said = "\n".join(cfg.warnings)
        self.assertIn("[hosts]: Shipyard runs on one machine now (c-622), so it is ignored", said)
        self.assertIn("[console] host names box, not this machine (mac)", said)
        for key in ("board_url", "config_dir", "checkout"):
            self.assertIn(f"[console] {key}:", said)


class ConsoleKbCase(KbCase):
    def setUp(self):
        super().setUp()
        os.environ["KEEL_CONFIG"] = str(console_toml(self.dir))
        self.addCleanup(os.environ.pop, "KEEL_BOSUN", None)

    def keel_card(self, title="t") -> str:
        """A personal card in Keel's repo: what Bosun files and builds (c-593)."""
        code, out, err = self.kb("create", "--space", "personal", "--title", title, "--repo", "keel")
        self.assertEqual(code, 0, err)
        return out

    def legacy_console_card(self, title="t") -> str:
        """A card filed in the console space before c-593 retired it: filed personal, then
        moved there under the board, since nothing may file one now."""
        card = self.create()
        board = Board(self.dir / "state" / "board.db")
        try:
            with board.tx():
                board.conn.execute("UPDATE cards SET space = 'console', title = ? WHERE id = ?",
                                   (title, card))
        finally:
            board.close()
        return card


class RetiredSpaceTest(ConsoleKbCase):
    """The console space is retired (c-593): nobody files there, and its old cards still read."""

    def test_nobody_files_a_console_card(self):
        code, _, err = self.kb("create", "--space", "console", "--title", "t")
        self.assertEqual(code, 1)
        self.assertIn("unknown space 'console'", err)
        board = Board(self.dir / "state" / "board.db")
        self.addCleanup(board.close)
        for actor in ("human", "cli", "bosun"):
            with self.assertRaises(Refused) as caught:
                board.create("console", "t", actor=actor)
            self.assertIn("retired", str(caught.exception))

    def test_an_old_console_card_still_shows_and_lists(self):
        old = self.legacy_console_card("an old console card")
        code, out, err = self.kb("show", old)
        self.assertEqual(code, 0, err)
        self.assertIn("an old console card", out)
        self.assertIn(old, [row["id"] for row in self.kb_json("list")])


class ActorTest(ConsoleKbCase):
    def note_actor(self, card, *argv, env=None):
        # A block: Bosun may write one on any card (c-522), so the actor is all it proves.
        code, _, err = self.kb(*argv, "block", card, "hello", env=env)
        board = Board(self.dir / "state" / "board.db")
        try:
            events = board.events(card, last=1)
        finally:
            board.close()
        return code, err, events[-1]["actor"] if code == 0 else None

    def test_bosun_is_never_him_even_holding_his_token(self):
        card = self.create()
        env = {"KEEL_BOSUN": self.bosun, "KEEL_TOKEN": self.token}
        self.assertEqual(self.note_actor(card, env=env)[2], "bosun")
        code, err, _ = self.note_actor(card, "--actor", "human", env=env)
        self.assertEqual(code, 1)
        self.assertIn("not Bosun's to claim", err)

    def test_a_house_holding_the_flag_is_still_not_bosun(self):
        card = self.create()
        code, err, _ = self.note_actor(card, env={"KEEL_BOSUN": self.bosun, "KEEL_CARD": card})
        self.assertEqual(code, 1)
        self.assertIn("a house is never Bosun", err)

    def test_nobody_else_may_claim_bosun(self):
        card = self.create()
        code, err, _ = self.note_actor(card, "--actor", "bosun")
        self.assertEqual(code, 1)
        self.assertIn("Bosun's session's alone", err)

class FakeHarness:
    """What `keel/console.py` calls on `keel.harness`, recorded; `rows` is the listing."""

    HarnessError = console.harness.HarnessError

    def __init__(self):
        self.rows, self.starts, self.resumes, self.stops = [], [], [], []

    def scoped_env(self, config_dir):
        return {"PATH": "/usr/bin", "KEEL_CARD": "c-9", "CLAUDE_CONFIG_DIR": str(config_dir)}

    def start_bg(self, cwd, prompt, **kwargs):
        self.starts.append(dict(kwargs, cwd=cwd, prompt=prompt))
        session = FRESH if self.starts[1:] else SESSION
        self.rows = [{"id": session[:8], "sessionId": session, "name": "Bosun", "status": "idle",
                      "kind": "background"}]
        return {"bg_id": session[:8], "session_id": session}

    def resume_bg(self, session_id, prompt, **kwargs):
        self.resumes.append(dict(kwargs, session_id=session_id, prompt=prompt))
        self.rows = [{"id": RESUMED[:8], "sessionId": RESUMED, "name": "Bosun", "status": "busy",
                      "kind": "background"}]
        return {"bg_id": RESUMED[:8], "session_id": RESUMED}

    def stop(self, bg_id, config_dir=None):
        self.stops.append(bg_id)
        self.rows = []

    listing_fails = False
    link = None

    def agents(self, config_dir=None, strict=False):
        if self.listing_fails:
            if strict:
                raise console.harness.HarnessError("claude agents exited 1:\nnot logged in")
            return []
        return list(self.rows)

    # the real matcher: by full id, by short id, or by the uuid's first eight characters
    find = staticmethod(console.harness.find)

    def remote_link(self, bg_id, config_dir=None):
        return self.link


class LifecycleCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.cfg = make_config(self.dir)
        self.cfg.host = "mac"
        self.cfg.console = {"host": "mac", "context_window": 1000}
        self.bosun = give_bosun_key(self.cfg.home)
        # Bosun's session takes the personal space's model and deny list (c-593)
        personal = self.cfg.spaces["personal"]
        personal.model, personal.deny = "opus", ["mcp__claude-in-chrome"]
        personal.allow = ["Bash(make check)"]      # a house's (c-769), never its own session's
        self.fake = FakeHarness()
        for patch in (mock.patch.object(console, "harness", self.fake),
                      mock.patch.object(consoletaps, "harness", self.fake),
                      mock.patch.object(console.house, "app_link",
                                        side_effect=lambda bg_id, _dir: f"https://claude.ai/code/session_{bg_id}")):
            patch.start()
            self.addCleanup(patch.stop)
        console.forget_view()
        console._asked_link.clear()


class StuckTest(LifecycleCase):
    """A row the listing keeps with no process (c-530's probe: a killed session stays listed
    with no pid and no status) is not up, and no tap refuses because of it."""

    def stick(self):
        consoletaps.start(self.cfg)
        self.fake.rows = [{"id": SESSION[:8], "sessionId": SESSION, "name": "Bosun",
                           "kind": "background", "state": "blocked"}]

    def stop_fails(self):
        def cannot(bg_id, config_dir=None):
            self.fake.stops.append(bg_id)
            raise console.harness.HarnessError(
                f"claude stop {bg_id} exited 1:\ncouldn't confirm {bg_id} stopped")
        self.fake.stop = cannot

    def test_status_says_stuck_and_not_up(self):
        self.stick()
        got = console.status(self.cfg)
        self.assertEqual((got["state"], got["up"], got["app_link"]), ("stuck", False, None))

    def test_start_past_a_stuck_row_starts_fresh_even_when_the_stop_cannot_confirm(self):
        self.stick()
        self.stop_fails()
        got = consoletaps.tap(self.cfg, "start")
        self.assertEqual((len(self.fake.starts), self.fake.resumes), (2, []))
        self.assertEqual(got["session_id"], FRESH)
        said = [row["what"] for row in got["history"][-2:]]
        self.assertIn("listed with no process (stuck)", said[0])
        self.assertIn("could not confirm", said[0])
        self.assertEqual(said[1], "started fresh past a stuck session")

    def test_stop_and_restart_never_refuse_a_stuck_row(self):
        self.stick()
        self.stop_fails()
        got = consoletaps.tap(self.cfg, "stop")
        self.assertIn("stuck", got["history"][-1]["what"])
        got = consoletaps.tap(self.cfg, "restart")
        self.assertEqual((got["session_id"], got["history"][-1]["what"]), (FRESH, "restarted"))

    def test_a_stop_that_works_says_so_and_start_resumes_the_conversation(self):
        self.stick()
        got = consoletaps.tap(self.cfg, "start")
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        self.assertEqual(self.fake.resumes[0]["session_id"], SESSION)
        said = [row["what"] for row in got["history"][-2:]]
        self.assertIn("listed with no process (stuck); stopped it", said[0])
        self.assertEqual((said[1], got["session_id"]), ("resumed", RESUMED))

    def test_only_the_listings_own_shape_is_stuck(self):
        self.assertTrue(console.stuck({"state": "blocked"}))
        self.assertFalse(console.stuck({"pid": 42, "status": "idle", "state": "blocked"}))
        self.assertFalse(console.stuck({"status": "idle"}))


class LifecycleTest(LifecycleCase):
    def test_start_launches_bosun_as_bosun(self):
        result = consoletaps.start(self.cfg)
        start = self.fake.starts[0]
        self.assertEqual((start["name"], start["model"], start["cwd"]), ("Bosun", "opus", self.cfg.root))
        # c-553: the key rides in its settings, never the launch env a daemon would keep
        self.assertNotIn("KEEL_BOSUN", start["env"])
        settings = json.loads(Path(start["settings_path"]).read_text())
        self.assertEqual(settings["env"]["KEEL_BOSUN"], self.bosun)
        self.assertNotIn("KEEL_CARD", start["env"], "Bosun is not a house")
        self.assertNotIn("KEEL_TOKEN", start["env"])
        self.assertEqual((result["state"], result["up"], result["session_id"]), ("idle", True, SESSION))
        self.assertEqual(result["app_link"], f"https://claude.ai/code/session_{SESSION[:8]}")
        self.assertEqual([tap["what"] for tap in result["history"]], ["started"])

    def test_its_settings_load_the_memory_and_deny_his_token(self):
        consoletaps.start(self.cfg)
        settings = json.loads(Path(self.fake.starts[0]["settings_path"]).read_text())
        hook = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        self.assertTrue(hook.endswith("bin/keel console memory"), hook)
        denied = " ".join(settings["permissions"]["deny"])
        self.assertIn(str(self.cfg.token_path), denied)
        for op in console.OPS:
            self.assertIn(f"Bash(*keel console {op}*)", settings["permissions"]["deny"])
        self.assertNotIn("Bash(make check)", settings["permissions"]["allow"])    # c-769
        # c-553: the key is in its env, so the file is 0600 beside the shared key, outside
        # state/ (no backup carries it), and Bosun's own tools are denied it
        path = Path(self.fake.starts[0]["settings_path"])
        self.assertEqual(settings["env"]["KEEL_BOSUN"], self.bosun)
        self.assertEqual(path.parent, console.housetier.shared_path(self.cfg).parent)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(str(self.cfg.state_dir), str(path))
        self.assertIn(f"Read(/{path})", settings["permissions"]["deny"])
        self.assertIn(f"Bash(*{path}*)", settings["permissions"]["deny"])
        self.assertIn(f"Bash(*{path.name}*)", settings["permissions"]["deny"])
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_its_guard_refuses_a_write_to_its_settings_file_however_it_is_spelled(self):
        """Review F3: outside Keel's root, so named by the file, not an authority path."""
        for command in ("sed -i s/x/y/ ~/.config/keel/credentials/bosun-settings.json",
                        "cd $HOME/.config/keel/credentials && echo {} > bosun-settings.json"):
            why = console.guard_verdict(self.cfg, {"tool_name": "Bash",
                                                   "tool_input": {"command": command}})
            self.assertIn("bosun-settings.json", why or "", command)
        why = console.guard_verdict(self.cfg, {"tool_name": "Edit", "tool_input": {
            "file_path": str(console.settings_path(self.cfg))}})
        self.assertIn("Bosun's own authority", why or "")
        self.assertIsNone(console.guard_verdict(self.cfg, {"tool_name": "Bash", "tool_input": {
            "command": "ls ~/.config/keel/credentials"}}))

    def test_its_settings_carry_the_stack_guard_every_house_gets(self):
        guard = self.dir / "guard.py"
        guard.write_text("# the stack guard\n")
        with mock.patch.object(self.cfg, "stack_guard_hook", guard):
            settings = console.settings(self.cfg)
        commands = {(group["matcher"], group["hooks"][0]["command"])
                    for group in settings["hooks"]["PreToolUse"]}
        self.assertEqual(commands, {(matcher, f"python3 {guard}")
                                    for matcher in console.house.GUARD_MATCHERS}
                         | {(console.GUARD_MATCHER, f"{self.cfg.root / 'bin' / 'keel'} console guard")})

    def test_bosun_may_not_tap_itself(self):
        with mock.patch.dict(os.environ, {"KEEL_BOSUN": self.bosun}), \
                mock.patch.object(console.config_module, "load", return_value=self.cfg), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(console.main(["stop"]), 1)
            self.assertEqual(console.main(["status"]), 0)
        self.assertEqual((self.fake.starts, self.fake.stops), ([], []))

    def test_a_second_tap_while_one_runs_is_refused(self):
        import fcntl
        path = console.lock_path(self.cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            with self.assertRaises(console.ConsoleError) as caught:
                consoletaps.tap(self.cfg, "start")
        self.assertIn("another tap", str(caught.exception))
        self.assertEqual(self.fake.starts, [])
        consoletaps.tap(self.cfg, "start")      # released: the next one goes
        self.assertEqual(len(self.fake.starts), 1)

    def test_a_launch_the_harness_refuses_says_why_and_changes_nothing(self):
        consoletaps.start(self.cfg)
        consoletaps.stop(self.cfg)
        before = console.read_state(self.cfg)
        self.fake.resume_bg = mock.Mock(side_effect=console.harness.HarnessError(
            "claude exited 1:\nNo conversation found with session ID b10ffe2f\n"))
        with self.assertRaises(console.ConsoleError) as caught:
            consoletaps.tap(self.cfg, "start")
        said = str(caught.exception)
        self.assertIn("No conversation found", said)
        self.assertIn("Restart starts it fresh", said)
        self.assertEqual(console.read_state(self.cfg), before)

    def test_start_while_up_is_refused(self):
        consoletaps.start(self.cfg)
        with self.assertRaises(console.ConsoleError):
            consoletaps.start(self.cfg)
        self.assertEqual(len(self.fake.starts), 1)

    def test_stop_then_start_resumes_the_same_conversation(self):
        consoletaps.start(self.cfg)
        stopped = consoletaps.stop(self.cfg)
        self.assertEqual((stopped["state"], stopped["up"], stopped["app_link"]), ("stopped", False, None))
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        again = consoletaps.start(self.cfg)
        self.assertEqual(self.fake.resumes[0]["session_id"], SESSION)
        self.assertEqual(len(self.fake.starts), 1, "Start after Stop is a resume, not a fresh start")
        self.assertEqual((again["session_id"], again["state"]), (RESUMED, "working"))
        self.assertEqual([tap["what"] for tap in again["history"]], ["started", "stopped", "resumed"])

    def test_restart_stops_and_starts_fresh(self):
        consoletaps.start(self.cfg)
        result = consoletaps.restart(self.cfg)
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        self.assertEqual((len(self.fake.starts), self.fake.resumes), (2, []))
        self.assertEqual(result["session_id"], FRESH)
        self.assertEqual([tap["what"] for tap in result["history"]], ["started", "stopped", "restarted"])

    def test_stop_when_not_running_is_refused(self):
        with self.assertRaises(console.ConsoleError):
            consoletaps.stop(self.cfg)

    def test_status_is_read_from_the_harness_not_the_file(self):
        consoletaps.start(self.cfg)
        self.fake.rows = []         # it exited on its own; the file still names it
        self.assertEqual(console.status(self.cfg)["state"], "stopped")
        self.assertEqual(console.status(self.cfg)["session_id"], SESSION)

    def test_never_started(self):
        self.assertEqual(console.status(self.cfg)["state"], "never")

    def test_a_tap_on_a_config_with_no_bosun_is_refused(self):
        """Off an install, a `[console]` table that names no host has no Bosun (the tracked
        keel.toml); any host it names is this machine (c-622)."""
        self.cfg.console = {}
        with self.assertRaises(console.ConsoleError) as caught:
            consoletaps.tap(self.cfg, "start")
        self.assertIn("has no Bosun", str(caught.exception))
        self.assertEqual(self.fake.starts, [], "nothing was started")
        self.cfg.console = {"host": "any-name"}
        self.assertEqual(consoletaps.tap(self.cfg, "start")["state"], "idle")

    def test_an_unknown_tap_is_refused(self):
        with self.assertRaises(console.ConsoleError):
            consoletaps.tap(self.cfg, "explode")

    def test_a_failed_listing_is_never_read_as_not_running(self):
        consoletaps.start(self.cfg)
        self.fake.listing_fails = True
        for op in console.OPS:
            with self.assertRaises(console.ConsoleError) as caught:
                consoletaps.tap(self.cfg, op)
            self.assertIn("could not tell whether Bosun is running", str(caught.exception))
        self.assertEqual((len(self.fake.starts), self.fake.resumes, self.fake.stops), (1, [], []))

    def test_a_restart_whose_launch_fails_keeps_its_stop(self):
        consoletaps.start(self.cfg)
        self.fake.start_bg = mock.Mock(side_effect=console.harness.HarnessError("claude exited 1:\nquota"))
        with self.assertRaises(console.ConsoleError):
            consoletaps.tap(self.cfg, "restart")
        history = [tap["what"] for tap in console.read_state(self.cfg)["history"]]
        self.assertEqual(history, ["started", "stopped"])

    def test_a_link_the_launch_missed_is_asked_for_again(self):
        with mock.patch.object(console.house, "app_link", return_value=None):
            consoletaps.start(self.cfg)
        self.assertIsNone(console.status(self.cfg)["app_link"])
        self.fake.link = "https://claude.ai/code/session_late"
        self.assertIsNone(console.status(self.cfg)["app_link"], "asked at most once a minute")
        console._asked_link.clear()
        self.assertEqual(console.status(self.cfg)["app_link"], "https://claude.ai/code/session_late")
        self.assertEqual(console.read_state(self.cfg)["app_link"], "https://claude.ai/code/session_late")

    def test_a_late_link_never_writes_over_a_tap_under_way(self):
        import fcntl
        with mock.patch.object(console.house, "app_link", return_value=None):
            consoletaps.start(self.cfg)
        console._asked_link.clear()
        self.fake.link = "https://claude.ai/code/session_late"
        path = console.lock_path(self.cfg)
        path.parent.mkdir(parents=True, exist_ok=True)     # the settings no longer live there (c-553)
        with open(path, "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            console.status(self.cfg)
        self.assertIsNone(console.read_state(self.cfg).get("app_link"), "the tap owns the file")
        self.assertEqual(console.status(self.cfg)["app_link"], "https://claude.ai/code/session_late",
                         "a link found under a tap is not thrown away for a minute")

    def test_a_session_recorded_by_its_short_id_is_still_found(self):
        consoletaps.start(self.cfg)
        data = console.read_state(self.cfg)
        console.write_state(self.cfg, dict(data, session_id=SESSION[:8]))
        self.assertEqual(console.status(self.cfg)["state"], "idle")

    def test_history_keeps_the_last_twenty(self):
        data = {}
        for n in range(25):
            data = console.noted(data, f"t{n}", "human", None)
        self.assertEqual([tap["what"] for tap in data["history"]][:1], ["t5"])
        self.assertEqual(len(data["history"]), console.HISTORY_MAX)


class TypedPromptTest(LifecycleCase):
    """c-731 r1.F4: what a tap types lands in the transcript as a user record, and neither
    the hello check nor the handoff note takes it for the user's message."""

    def typed(self, session, prompt):
        """The record the harness keeps of the prompt a tap typed into `session`."""
        path = console.config_dir(self.cfg) / "projects" / "-keel" / f"{session}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
        return console.tail_records(console.transcript_of(console.config_dir(self.cfg), session))

    def test_the_start_and_resume_prompts_a_tap_types_are_not_the_users_message(self):
        bosunhello.forget()
        self.addCleanup(bosunhello.forget)
        consoletaps.start(self.cfg)
        started = self.typed(SESSION, self.fake.starts[0]["prompt"])
        consoletaps.stop(self.cfg)
        consoletaps.start(self.cfg)
        resumed = self.typed(RESUMED, self.fake.resumes[0]["prompt"])
        self.assertIn("started fresh by the user's tap", self.fake.starts[0]["prompt"])
        self.assertIn("Started again by the user's tap", self.fake.resumes[0]["prompt"])
        self.assertEqual(sorted(bosunhello.sessions(self.cfg)), sorted([SESSION, RESUMED]))
        self.assertFalse(bosunhello.said(self.cfg), "Keel's own prompts are not a hello")
        self.assertEqual(consolehandoff.said(started + resumed), ([], ""))
        with open(console.transcript_of(console.config_dir(self.cfg), RESUMED), "a") as handle:
            handle.write(json.dumps({"type": "user", "message": {"content": "hello Bosun"}}) + "\n")
        self.assertTrue(bosunhello.said(self.cfg), "the same path does find the user's own message")


class TranscriptTest(LifecycleCase):
    def write_transcript(self, records):
        directory = self.dir / "cfg-personal" / "projects" / "-keel"
        directory.mkdir(parents=True)
        (directory / f"{SESSION}.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")

    def test_last_turn_model_and_context_come_from_the_newest_usage(self):
        self.write_transcript([
            {"type": "assistant", "timestamp": "2026-09-25T17:00:00Z",
             "message": {"model": "claude-opus-5-5", "usage": {"input_tokens": 10}}},
            {"type": "assistant", "timestamp": "2026-09-25T17:05:00Z",
             "message": {"model": "claude-opus-5-5", "usage": {
                 "input_tokens": 100, "cache_read_input_tokens": 200,
                 "cache_creation_input_tokens": 50, "output_tokens": 50}}},
            {"type": "user", "timestamp": "2026-09-25T17:06:00Z", "message": {"content": "hi"}},
        ])
        consoletaps.start(self.cfg)
        result = console.status(self.cfg)
        self.assertEqual(result["last_turn"], "2026-09-25T17:06:00Z")
        self.assertEqual(result["model"], "claude-opus-5-5")
        self.assertEqual(result["context"], {"used": 350, "window": 1000, "percent": 35, "compact_at": 70})

    def test_a_cut_first_line_is_skipped(self):
        path = self.dir / "t.jsonl"
        path.write_text('{"a": "' + "x" * 50 + '"}\n{"b": 1}\n')
        self.assertEqual(console.tail_records(path, size=20), [{"b": 1}])


def install_config(home: Path) -> config_module.Config:
    """An install's own config.toml (c-722: its memory lives beside it)."""
    home.mkdir(parents=True, exist_ok=True)
    path = home / "config.toml"
    path.write_text(console_toml(home).read_text())
    return config_module.load(path, ensure=False)


class MemoryTest(unittest.TestCase):
    def test_the_memory_is_the_index_then_each_file_in_order(self):
        """The shipped template names every file the hook reads, in its order."""
        for name in console.MEMORY_FILES:
            self.assertTrue((ROOT / "templates" / "memory" / "bosun" / name).is_file(), name)
        with tempfile.TemporaryDirectory() as tmp:
            cfg = install_config(Path(tmp).resolve() / "install")
            shutil.copytree(ROOT / "templates" / "memory" / "bosun", cfg.install_home / "memory" / "bosun")
            text = console.memory_text(cfg)
        positions = [text.index(f"memory/bosun/{name}") for name in console.MEMORY_FILES]
        self.assertEqual(positions, sorted(positions))

    def test_the_memory_bosun_reads_holds_every_file_in_order(self):
        """One owner's Bosun memory, wherever it is read from (c-722: the install's, else the
        checkout's): every file the hook prints is there, index first."""
        cfg = config_module.load(ensure=False)
        directory = console.memory_dir(cfg)
        if not (directory / "MEMORY.md").is_file():
            self.skipTest("no Bosun memory of an owner's here")
        for name in console.MEMORY_FILES:
            self.assertTrue((directory / name).is_file(), name)
        text = console.memory_text(cfg)
        positions = [text.index(str(directory / name)) for name in console.MEMORY_FILES]
        self.assertEqual(positions, sorted(positions))

    def test_the_installs_memory_is_read_and_the_checkouts_only_while_it_has_none(self):
        """c-722: the install's `memory/bosun` wins; an install from before the move reads the
        checkout's until the move brings it in."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = install_config(Path(tmp).resolve() / "install")
            code = Path(tmp).resolve() / "code"
            (code / "bosun" / "memory").mkdir(parents=True)
            (code / "bosun" / "memory" / "MEMORY.md").write_text("the checkout's index\n")
            cfg.root = code
            self.assertIn("the checkout's index", console.memory_text(cfg))
            own = cfg.install_home / "memory" / "bosun"
            own.mkdir(parents=True)
            (own / "MEMORY.md").write_text("the install's index\n")
            text = console.memory_text(cfg)
        self.assertIn("the install's index", text)
        self.assertNotIn("the checkout's index", text)
        self.assertIn(f"<!-- {own / 'MEMORY.md'} -->", text)


class ReachTest(LifecycleCase):
    def test_no_personal_space_means_no_entry(self):
        del self.cfg.spaces["personal"]
        self.assertIsNone(console.view(self.cfg))

    def test_the_deck_reads_the_status_itself_and_a_tap_refreshes_it(self):
        first = console.view(self.cfg)
        self.assertEqual(first["state"], "never")
        consoletaps.start(self.cfg)
        self.assertEqual(console.view(self.cfg)["state"], "never", "held for LOCAL_SECONDS")
        actions.act(self.cfg, None, {"verb": "console.stop"})
        self.assertEqual(console.view(self.cfg)["state"], "stopped", "a tap drops the held one")

    def test_the_deck_taps_bosun_and_refuses_a_config_with_none(self):
        result = actions.act(self.cfg, None, {"verb": "console.start"})
        self.assertEqual(result["console"]["session_id"], SESSION)
        self.cfg.console = {}
        with self.assertRaises(actions.ActionError) as caught:
            actions.act(self.cfg, None, {"verb": "console.stop"})
        self.assertIn("has no Bosun", str(caught.exception))
        self.assertIsNone(console.view(self.cfg), "and the deck draws no session for it")

    def test_a_caller_cannot_tap_bosun(self):
        with self.assertRaises(actions.ActionError):
            actions.act(self.cfg, None, {"verb": "console.start", "caller": {"actor": "house"}})

    def test_the_drain_never_counts_bosun_as_a_house(self):
        board = Board(self.cfg.db_path)
        self.addCleanup(board.close)
        rows = [{"kind": "background", "name": "Bosun", "status": "busy", "sessionId": SESSION}]
        self.assertEqual(drain.house_ids(board, rows), set())


class RetiredStateTest(LifecycleCase):
    """The deck's state and Harbor's digest with an old console card on the board (c-593)."""

    def test_an_old_console_card_loads_and_is_never_his(self):
        board = Board(self.cfg.db_path)
        self.addCleanup(board.close)
        mine = board.create("personal", "bosun's", actor="human")
        his = board.create("personal", "his", actor="human")
        with board.tx():
            board.conn.execute("UPDATE cards SET space = 'console' WHERE id = ?", (mine,))
        for card in (mine, his):
            board.block(card, "a question", "house")
        with mock.patch.object(deckstate.harness, "agents_across", return_value=[]):
            state = deckstate.build(self.cfg, board, rows=[])
            archived = deckstate.build(self.cfg, board, rows=[], scope="deck", archived=True)
        self.assertEqual(state["needs_you"], [his])
        self.assertNotIn("console", state["spaces"])
        self.assertIn(mine, [card["id"] for card in state["cards"]], "the whole document holds it")
        self.assertIn(mine, [card["id"] for card in archived["cards"]])
        doc = deckdigest.fold(state)
        self.assertEqual([row["id"] for row in doc["cards"]], [his])
        self.assertEqual([row["id"] for row in doc["queue"]], [his])
        self.assertNotIn("console", doc["spaceCounts"])


class BosunPageStateTest(LifecycleCase):
    """What the Bosun page reads (c-591): the cards Bosun builds, and the deploy asks."""

    def board(self):
        board = Board(self.cfg.db_path)
        self.addCleanup(board.close)
        return board

    def test_its_scope_is_the_cards_bosun_builds(self):
        board = self.board()
        board.builder = True
        board.builds = frozenset({'keel'})
        built = board.create("personal", "Bosun builds this", actor="human", repo="keel")
        errand = board.create("personal", "a house's errand", actor="human")
        aside = board.create("personal", "an old console card", actor="human", repo="keel")
        with board.tx():
            board.conn.execute("UPDATE cards SET space = 'console' WHERE id = ?", (aside,))
        work = board.create("work", "work", actor="human")
        with mock.patch.object(deckstate.harness, "agents_across", return_value=[]):
            doc = deckstate.build(self.cfg, board, rows=[], scope="bosun")
        self.assertEqual([card["id"] for card in doc["cards"]], [built])
        self.assertNotIn(errand, [card["id"] for card in doc["cards"]])
        self.assertNotIn(aside, [card["id"] for card in doc["cards"]])
        self.assertNotIn(work, [card["id"] for card in doc["cards"]])

    def test_the_deck_reads_builder_mode_off_the_config(self):
        # The deck's own Board carries the config's switches (c-591): before, `derived.bosun`
        # was false on every card the deck drew, so the page's scope was always empty.
        board = self.board()
        built = board.create("personal", "Bosun builds this", actor="human", repo="keel")
        superuser_builder(self.cfg)
        deck = deckstate.Deck(self.cfg)
        with mock.patch.object(deckstate.harness, "agents_across", return_value=[]):
            doc = deck.state(scope="bosun")
        self.assertEqual([card["id"] for card in doc["cards"]], [built])

    def found(self, sha, cards):
        return {"repo": "keel", "space": "personal", "target": "next", "trunk": "main",
                "sha": sha, "cards": cards}

    def test_shipped_reads_the_deploy_asks(self):
        board = self.board()
        self.assertEqual(deployask.shipped(board), {"pending": None, "last": None, "live": []})
        first = deployask.raise_deploy(board, self.found("a" * 40, ["c-1", "c-2"]))
        shipped = deployask.shipped(board)
        self.assertEqual((shipped["pending"]["ask"], shipped["pending"]["cards"]), (first["id"], ["c-1", "c-2"]))
        self.assertIsNone(shipped["last"])
        asks.answer(board, first["id"], "human", "A")
        deployask.record(board, first["id"], deployask.DEPLOYING, "deploying: the suite runs")
        shipped = deployask.shipped(board)
        self.assertIsNone(shipped["pending"])
        self.assertEqual(shipped["last"]["result"]["move"], "deploying")
        self.assertEqual(shipped["live"], [])
        deployask.record(board, first["id"], deployask.DEPLOYED, "main is at aaaaaaaa", sha="a" * 40)
        second = deployask.raise_deploy(board, self.found("b" * 40, ["c-3"]))
        shipped = deployask.shipped(board)
        self.assertEqual(shipped["pending"]["ask"], second["id"])
        self.assertEqual((shipped["last"]["ask"], shipped["last"]["result"]["move"]), (first["id"], "deployed"))
        self.assertEqual([row["cards"] for row in shipped["live"]], [["c-1", "c-2"]])

    def test_a_not_yet_is_no_result(self):
        board = self.board()
        row = deployask.raise_deploy(board, self.found("c" * 40, ["c-4"]))
        asks.answer(board, row["id"], "human", "B")
        self.assertEqual(deployask.shipped(board), {"pending": None, "last": None, "live": []})

    def test_the_state_carries_it(self):
        board = self.board()
        deployask.raise_deploy(board, self.found("d" * 40, ["c-5"]))
        entry = deckstate.console_entry(self.cfg, board, None)
        self.assertEqual(entry["shipped"]["pending"]["cards"], ["c-5"])


@unittest.skipUnless(shutil.which("node"), "node is not on this machine")
class ConsolePageRenderTest(unittest.TestCase):
    """`tests/fixtures/console-page.js`: the page's own modules, drawn and read back."""

    def test_the_console_draws_what_the_session_allows(self):
        result = subprocess.run(
            ["node", str(ROOT / "tests" / "fixtures" / "console-page.js"), str(ROOT / "app")],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True}, result.stdout)


class PageTest(unittest.TestCase):
    def test_the_console_is_its_own_shell_and_not_an_install(self):
        self.assertIn("/console", serve.CONSOLE_PATHS)
        # Each section is a route of the one shell (c-591), and the shell worker keeps them.
        worker = (ROOT / "app" / "sw.js").read_text()
        for section in ("queue", "shipped", "journal"):
            self.assertIn(f"/console/{section}", serve.CONSOLE_PATHS)
            self.assertIn(f"'/console/{section}'", worker)
        html = (ROOT / "app" / serve.CONSOLE_SHELL).read_text()
        self.assertIn('data-mode="console"', html)
        # Not an app of its own (2026-09-26): inside the deck's `/` scope a second install
        # is only a shortcut, and Bosun is one tap from the deck's header anyway.
        self.assertNotIn('rel="manifest"', html)
        refs = set(re.findall(r'(?:src|href)="([^"]+)"', html))
        for ref in refs:
            self.assertIn(ref, serve.APP_FILES, f"{ref} is referenced but not served")
        manifest = json.loads((ROOT / "app" / "console.webmanifest").read_text())
        self.assertEqual((manifest["scope"], manifest["start_url"]), ("/console", "/console"))


if __name__ == "__main__":
    unittest.main()
