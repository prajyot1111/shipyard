"""`keel talker`: URL parsing against the recorded server log, the plist, one owner's
memory index, the config dir's settings shape, and start/url/status/stop against a fake claude."""

import json
import os
import plistlib
import re
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from keel import talker

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "spaces" / "harbor" / ".claude"

# Recorded from `claude remote-control --name harbor-probe` on 2026-09-16 (2.1.273), stdout
# to a file, no TTY: the session URL is wrapped in an OSC 8 hyperlink and carries a
# `?from=cli` suffix (OSC 8, BEL-terminated); the environment URL must not match.
RECORDED = (
    "\x1b[2K\x1b[G·✔︎· Connected · probe-cwd · HEAD\n"
    "    Capacity: 1/32 · New sessions will be created in the current directory\n"
    "    \x1b]8;;https://claude.ai/code/session_018on8q2KxLbtxsMyrx8TpFF?from=cli\x07Attached\x1b]8;;\x07\n"
    "\n"
    "Continue coding in the Claude mobile app or https://claude.ai/code?environment=env_01DV5xYxG6NWUxQ5AWwsnXpE\n"
    "space to show QR code\n"
)
RECORDED_SINGLE = (
    "Resuming session session_018on8q2KxLbtxsMyrx8TpFF (0m ago)…\n"
    "    Single session · exits when complete\n"
    "Continue coding in the Claude mobile app or https://claude.ai/code/session_018on8q2KxLbtxsMyrx8TpFF\n"
)
SESSION = "session_018on8q2KxLbtxsMyrx8TpFF"


class UrlTest(unittest.TestCase):
    def test_session_id_from_hyperlinked_server_log(self):
        self.assertEqual(talker.session_in(RECORDED), SESSION)

    def test_url_drops_the_from_cli_suffix(self):
        self.assertEqual(talker.newest_url(RECORDED), f"https://claude.ai/code/{SESSION}")


    def test_environment_url_alone_is_not_a_session(self):
        self.assertIsNone(talker.newest_url(
            "Continue coding in the Claude mobile app or https://claude.ai/code?environment=env_01DV\n"))

    def test_newest_wins(self):
        text = RECORDED + "\nContinue at https://claude.ai/code/session_02newer\n"
        self.assertEqual(talker.session_in(text), "session_02newer")


class PlistTest(unittest.TestCase):
    def setUp(self):
        self.paths = talker.Paths(root=Path("/x/keel"), state_dir=Path("/x/keel/state"))

    def test_renders_a_keepalive_agent_for_start_in_talker_dir(self):
        plist = plistlib.loads(talker.render_plist(self.paths, home=Path("/Users/me")))
        self.assertEqual(plist["Label"], "dev.keel.talker")
        self.assertEqual(plist["ProgramArguments"], ["/x/keel/bin/keel", "talker", "start"])
        self.assertEqual(plist["WorkingDirectory"], "/x/keel/talker/home")
        self.assertTrue(plist["KeepAlive"])
        self.assertTrue(plist["RunAtLoad"])
        self.assertEqual(plist["StandardOutPath"], "/x/keel/state/logs/talker.log")
        self.assertEqual(plist["StandardErrorPath"], "/x/keel/state/logs/talker.log")

    def test_environment(self):
        env = plistlib.loads(talker.render_plist(self.paths, home=Path("/Users/me")))["EnvironmentVariables"]
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], "/x/keel/spaces/harbor/.claude")
        self.assertEqual(env["KEEL_HOME"], "/x/keel")
        path = env["PATH"].split(":")
        self.assertEqual(path[:3], ["/Users/me/.local/bin", "/opt/homebrew/bin", "/x/keel/bin"])

    def test_command_shapes(self):
        self.assertEqual(talker.command(), ["claude", "remote-control", "--name", "Harbor", "--capacity", "1"])
        self.assertEqual(talker.command(SESSION),
                         ["claude", "remote-control", "--name", "Harbor", "--session-id", SESSION])

    def test_the_server_runs_on_the_pinned_converse_model(self):
        # J-4: with no model the server ran on the config dir's (the account's) default.
        with mock.patch.dict(os.environ, {"ANTHROPIC_MODEL": "haiku"}):
            env = talker.environment(self.paths)
        self.assertEqual(env["ANTHROPIC_MODEL"], "opus")

    def test_the_model_comes_from_the_models_table(self):
        from tests.helpers import make_config
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(Path(tmp))
            cfg.turn_models = dict(cfg.turn_models, converse="opus[1m]")
            paths = talker.paths_from(cfg)
        self.assertEqual(talker.environment(paths)["ANTHROPIC_MODEL"], "opus[1m]")

    def test_memory_link_is_the_auto_memory_path_for_the_cwd(self):
        # cwd is the current numbered run dir (talker/home/1 with no pointer), so the
        # auto-memory slug carries the run number.
        self.assertEqual(self.paths.memory_link,
                         Path("/x/keel/spaces/harbor/.claude/projects/-x-keel-talker-home-1/memory"))


class SeedTest(unittest.TestCase):
    def test_seed_keeps_onboarding_drops_projects_and_caches_adds_trust(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "old.json"
            source.write_text(json.dumps({
                "hasCompletedOnboarding": True, "lastOnboardingVersion": "2.1.220",
                "installMethod": "native", "oauthAccount": {"emailAddress": "x"},
                "projects": {"/old": {"hasTrustDialogAccepted": True}},
                "cachedGrowthBookFeatures": {"big": "blob"}, "tipsHistory": {"a": 1}}))
            target = Path(tmp) / ".claude.json"
            seeded = talker.seed_claude_json(source, target, Path("/x/keel/talker/home"))
            self.assertTrue(seeded["hasCompletedOnboarding"])
            self.assertEqual(seeded["oauthAccount"], {"emailAddress": "x"})
            self.assertNotIn("cachedGrowthBookFeatures", seeded)
            self.assertNotIn("tipsHistory", seeded)
            self.assertEqual(list(seeded["projects"]), ["/x/keel/talker/home"])
            self.assertTrue(seeded["projects"]["/x/keel/talker/home"]["hasTrustDialogAccepted"])
            self.assertEqual(oct(target.stat().st_mode & 0o777), "0o600")


def owner_memory() -> Path:
    """The talker's memory as Keel reads it (c-722): the install's when the config names an
    install that holds one, else the checkout's."""
    from keel import config as config_module, memoryroot
    return memoryroot.talker_dir(config_module.load(ensure=False))


@unittest.skipUnless((owner_memory() / "MEMORY.md").is_file(),
                     "no talker memory of an owner's here: a tree without one, and no install holding one")
class MemoryIndexTest(unittest.TestCase):
    """One owner's talker memory, wherever it is read from: the index, its tiers, its files."""
    LINE = re.compile(r"^- \[[^\]]+\]\(([^)]+\.md)\): \S")

    def setUp(self):
        self.memory = owner_memory()

    def index_lines(self) -> list[str]:
        return (self.memory / "MEMORY.md").read_text().splitlines()

    def test_every_index_line_points_at_an_existing_file(self):
        entries = [line for line in self.index_lines() if line.startswith("- [")]
        self.assertGreater(len(entries), 40)
        for line in entries:
            match = self.LINE.match(line)
            self.assertIsNotNone(match, f"malformed index line: {line[:60]}")
            self.assertTrue((self.memory / match.group(1)).is_file(), f"missing body: {match.group(1)}")

    def test_every_body_file_has_exactly_one_line(self):
        text = (self.memory / "MEMORY.md").read_text()
        for path in self.memory.glob("*.md"):
            if path.name == "MEMORY.md":
                continue
            self.assertEqual(text.count(f"]({path.name})"), 1, f"{path.name} lines in the index")

    def test_two_tiers_and_the_retired_lines(self):
        lines = self.index_lines()
        live, history = lines.index("## Live"), lines.index("## History (the old mechanism, not how Keel works)")
        self.assertLess(live, history)
        for name in ("two-model-controls", "harbor-supervision", "talking-to-a-live-conductor"):
            line = next(l for l in lines if f"]({name}.md)" in l)
            self.assertGreater(lines.index(line), history, f"{name} must sit under History")
            self.assertIn("retired", line)
        for name in ("keel-is-the-engine", "cards-from-conversation", "where-things-are", "voice",
                     "card-it-means-inbox", "his-words-go-on-the-card-verbatim", "never-pattern-kill"):
            line = next(l for l in lines if f"]({name}.md)" in l)
            self.assertLess(lines.index(line), history, f"{name} must be live")

    def test_new_memories_have_frontmatter_and_no_em_dashes(self):
        for name in ("keel-is-the-engine", "cards-from-conversation", "where-things-are", "MEMORY"):
            text = (self.memory / f"{name}.md").read_text()
            self.assertNotIn("—", text, f"em-dash in {name}.md")
            if name != "MEMORY":
                self.assertTrue(text.startswith("---\nname: " + name), name)


class InstallStateTest(unittest.TestCase):
    """c-711: under an install's config every file the talker keeps is in the install's
    state, and only the run dirs, the config dir and the memory stay with the code."""

    def test_the_talkers_files_are_the_installs_and_its_folders_the_checkouts(self):
        from keel import config as config_module
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(os.path.realpath(tmp)) / "install"
            install.mkdir()
            toml = install / "config.toml"
            toml.write_text(f'[keel]\nstate_dir = "{install / "state"}"\n')
            cfg = config_module.load(toml, ensure=False)
            paths = talker.paths_from(cfg)
            state = install / "state"
            self.assertEqual(paths.config, str(toml))
            self.assertEqual(
                [paths.cwd_pointer, paths.session_file, paths.handoff_file, paths.pid_file, paths.log],
                [state / "talker-cwd", state / "talker.session", state / "talker-handoff",
                 state / "talker.pid", state / "logs" / "talker.log"])
            self.assertEqual(paths.run_base, cfg.root / "talker" / "home")
            self.assertEqual(paths.config_dir, cfg.root / "spaces" / "harbor" / ".claude")
            # No pointer was carried over: the first start is run dir 1, whatever number the
            # old state had reached.
            self.assertEqual(paths.cwd, cfg.root / "talker" / "home" / "1")
            state.mkdir()
            (state / "talker-cwd").write_text("7\n")
            self.assertEqual(paths.cwd, cfg.root / "talker" / "home" / "7")


class ConfigDirTest(unittest.TestCase):
    def settings(self) -> dict:
        return json.loads((CONFIG_DIR / "settings.json").read_text())

    def test_denies_every_mcp_tool_and_forks(self):
        deny = self.settings()["permissions"]["deny"]
        self.assertIn("Agent(fork)", deny)
        mcp = [rule for rule in deny if rule.startswith("mcp__")]
        self.assertGreaterEqual(len(mcp), 3)
        # His secrets on the box are denied by name too (c-451): the talker runs his Bash, and
        # neither the human token nor the house key is anything Harbor has a use for.
        # And wherever the config's state dir is (c-711): an install's token and house key
        # are not under the one path named here, so the Read deny is by file name too.
        secrets = {"Read(//home/ubuntu/keel/state/human.token)", "Bash(*human.token*)",
                   "Read(//home/ubuntu/keel/state/house.key)", "Bash(*house.key*)",
                   "Read(//**/human.token)", "Read(//**/house.key)"}
        self.assertEqual(set(deny) - set(mcp), {"Agent(fork)"} | secrets)
        self.assertNotIn("allow", self.settings()["permissions"])

    def test_guard_hook_on_bash_and_push_notifications(self):
        settings = self.settings()
        bash = [h for h in settings["hooks"]["PreToolUse"] if h["matcher"] == "Bash"]
        self.assertEqual(len(bash), 1)
        self.assertIn("guard-stack-invariants.py", bash[0]["hooks"][0]["command"])
        self.assertTrue(settings["agentPushNotifEnabled"])


    def test_runtime_files_are_ignored(self):
        ignored = (CONFIG_DIR / ".gitignore").read_text().split()
        for name in ("projects/", "sessions/", "cache/", "history.jsonl", "shell-snapshots/",
                     "telemetry/", "file-history/", "paste-cache/", "session-env/", "uploads/",
                     "backups/", "plugins/", ".claude.json"):
            self.assertIn(name, ignored)


FAKE_CLAUDE = """#!/bin/sh
# A stand-in for `claude remote-control`: prints the recorded lines, then waits for TERM.
if [ "$1" = "agents" ]; then echo "[]"; exit 0; fi
printf '%s\\n' "args: $*"
printf '    \\033]8;;https://claude.ai/code/session_018on8q2KxLbtxsMyrx8TpFF?from=cli\\007Attached\\033]8;;\\007\\n'
trap 'exit 0' TERM INT
while :; do sleep 1; done
"""


# The c-444 shape: the consent question with NO trailing newline, then a wait for an answer
# that must never come. If anything is read from stdin it is recorded, so the test can say
# nothing answered it.
FAKE_PROMPT = """#!/bin/sh
if [ "$1" = "agents" ]; then echo "[]"; exit 0; fi
printf 'Enable Remote Control? (y/n) '
if read -r answer; then echo "$answer" > "{answered}"; fi
trap 'exit 0' TERM INT
while :; do sleep 1; done
"""


class StartStopTest(unittest.TestCase):
    """start/url/status/stop through bin/keel with a fake `claude` first on PATH."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        fake = self.dir / "bin" / "claude"
        fake.parent.mkdir()
        fake.write_text(FAKE_CLAUDE)
        fake.chmod(0o755)
        (self.dir / "keel.toml").write_text(
            f'[keel]\nstate_dir = "{self.dir / "state"}"\n[spaces.personal]\nconfig_dir = "~/nowhere"\n')
        # KEEL_HOME IS THE TEMPORARY DIRECTORY, not this checkout: `start` writes the config
        # dir's .claude.json now (consent, c-444), and the config dir is under the root.
        # Pointed at ROOT, a test run would write into this checkout's spaces/harbor/.claude.
        self.env = dict(os.environ, PATH=f"{fake.parent}:{os.environ['PATH']}",
                        KEEL_HOME=str(self.dir), KEEL_CONFIG=str(self.dir / "keel.toml"))
        self.env.pop("CLAUDE_CONFIG_DIR", None)
        self.state = self.dir / "state"

    def tearDown(self):
        pid = self.state / "talker.pid"
        if pid.exists():
            self.keel("stop")
        self.tmp.cleanup()

    def keel(self, *argv) -> subprocess.CompletedProcess:
        return subprocess.run([str(ROOT / "bin" / "keel"), "talker", *argv], env=self.env,
                              capture_output=True, text=True, timeout=30)

    def wait_for(self, path: Path, timeout=10) -> None:
        deadline = time.time() + timeout
        while not path.exists() and time.time() < deadline:
            time.sleep(0.1)
        self.assertTrue(path.exists(), f"{path} never appeared")

    def test_start_records_pid_and_session_then_stop_ends_it(self):
        (self.state / "logs").mkdir(parents=True)
        log = open(self.state / "logs" / "talker.log", "wb")
        server = subprocess.Popen([str(ROOT / "bin" / "keel"), "talker", "start"], env=self.env,
                                  stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        try:
            self.wait_for(self.state / "talker.session")
            self.assertEqual((self.state / "talker.session").read_text().strip(), SESSION)
            pid = int((self.state / "talker.pid").read_text())
            self.assertNotEqual(pid, server.pid, "the pid file must name claude, not the wrapper")
            self.assertIn("claude", talker.process_command(pid))
            self.assertEqual(self.keel("url").stdout.strip(), f"https://claude.ai/code/{SESSION}")
            status = self.keel("status")
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn(f"running (pid {pid})", status.stdout)
            self.assertIn(SESSION, status.stdout)
            stopped = self.keel("stop")
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            self.assertEqual(server.wait(timeout=10), 0)
            self.assertFalse(talker.alive(pid))
            self.assertFalse((self.state / "talker.pid").exists())
            self.assertEqual(self.keel("status").returncode, 1)
        finally:
            log.close()
            if server.poll() is None:
                server.terminate()
                server.wait(timeout=10)

    def serve(self, script: str | None = None) -> subprocess.Popen:
        """`keel talker start` in the background, its output in the log; `script` replaces
        the fake claude for this test."""
        if script is not None:
            (self.dir / "bin" / "claude").write_text(script)
        (self.state / "logs").mkdir(parents=True, exist_ok=True)
        log = open(self.state / "logs" / "talker.log", "wb")
        self.addCleanup(log.close)
        server = subprocess.Popen([str(ROOT / "bin" / "keel"), "talker", "start"], env=self.env,
                                  stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)

        def reap():
            if server.poll() is None:
                server.terminate()
                server.wait(timeout=10)
        self.addCleanup(reap)
        return server

    def config_json(self) -> Path:
        return self.dir / "spaces" / "harbor" / ".claude" / ".claude.json"

    def test_start_records_consent_in_the_config_before_the_server_reads_it(self):
        cj = self.config_json()
        cj.parent.mkdir(parents=True)
        cj.write_text(json.dumps({"oauthAccount": {"emailAddress": "x"}, "hasUsedRemoteControl": True}))
        self.serve()
        self.wait_for(self.state / "talker.session")
        data = json.loads(cj.read_text())
        self.assertIs(data["remoteDialogSeen"], True)
        self.assertEqual(data["oauthAccount"], {"emailAddress": "x"})
        self.assertIs(data["hasUsedRemoteControl"], True)
        self.assertEqual(oct(cj.stat().st_mode & 0o777), "0o600")

    def test_a_config_that_does_not_parse_is_refused_not_written_over(self):
        cj = self.config_json()
        cj.parent.mkdir(parents=True)
        cj.write_text('{"oauthAccount": {"emailAddress": "x"}, trunc')
        server = self.serve()
        self.assertEqual(server.wait(timeout=20), 2)
        self.assertEqual(cj.read_text(), '{"oauthAccount": {"emailAddress": "x"}, trunc')
        self.assertIn("does not parse", (self.state / "talker.fault").read_text())
        self.assertFalse((self.state / "talker.pid").exists(), "no server was launched")

    def test_a_prompt_with_no_newline_is_logged_faulted_and_never_answered(self):
        """c-444: server mode stuck on "Enable Remote Control? (y/n)" for two days, status
        exit 0, nothing in the log, because the relay read LINES and the prompt has none."""
        self.serve(FAKE_PROMPT.format(answered=self.dir / "answered"))
        self.wait_for(self.state / "talker.fault")
        self.assertIn("Enable Remote Control? (y/n)", (self.state / "talker.fault").read_text())
        log = (self.state / "logs" / "talker.log").read_text()
        self.assertIn("Enable Remote Control? (y/n)", log)
        self.assertIn("talker: FAULT unanswered prompt", log)
        status = self.keel("status")
        self.assertEqual(status.returncode, 1, status.stdout)
        self.assertIn("health: fault", status.stdout)
        self.assertFalse((self.dir / "answered").exists(), "something answered the prompt")


class RunDirTest(unittest.TestCase):
    """The cwd pointer and run-dir rotation: fresh bumps the dir, re-links memory, prunes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "state").mkdir()
        (self.root / "talker" / "memory").mkdir(parents=True)
        self.paths = talker.Paths(root=self.root, state_dir=self.root / "state")
        self.nosource = self.root / "nosource"   # a source .claude.json that does not exist

    def pointer(self) -> Path:
        return self.root / "state" / "talker-cwd"

    def test_default_run_index_is_first_and_cwd_is_numbered(self):
        self.assertEqual(self.paths.run_index(), talker.FIRST_RUN)
        self.assertEqual(self.paths.cwd, self.root / "talker" / "home" / "1")

    def test_pointer_is_read(self):
        self.pointer().write_text("4\n")
        self.assertEqual(self.paths.run_index(), 4)
        self.assertEqual(self.paths.cwd, self.root / "talker" / "home" / "4")

    def test_a_bad_pointer_falls_back_to_first(self):
        self.pointer().write_text("garbage")
        self.assertEqual(self.paths.run_index(), talker.FIRST_RUN)

    def test_rotate_bumps_the_pointer_relinks_memory_and_seeds_trust(self):
        new = talker.rotate(self.paths, source=self.nosource)
        self.assertEqual(new, 2)
        self.assertEqual(self.pointer().read_text().strip(), "2")
        self.assertEqual(self.paths.run_index(), 2)
        cwd = self.root / "talker" / "home" / "2"
        self.assertTrue(cwd.is_dir())
        link = self.paths.memory_link
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), (self.root / "talker" / "memory").resolve())
        data = json.loads((self.paths.config_dir / ".claude.json").read_text())
        self.assertTrue(data["projects"][str(cwd)]["hasTrustDialogAccepted"])

    def test_rotate_twice_increments(self):
        talker.rotate(self.paths, source=self.nosource)
        talker.rotate(self.paths, source=self.nosource)
        self.assertEqual(self.paths.run_index(), 3)

    def test_prune_keeps_the_last_n_run_dirs(self):
        base = self.root / "talker" / "home"
        base.mkdir(parents=True)
        for i in range(1, 9):
            (base / str(i)).mkdir()
        self.pointer().write_text("8\n")
        removed = talker.prune_runs(self.paths, keep=5)
        left = sorted(int(p.name) for p in base.iterdir() if p.name.isdigit())
        self.assertEqual(left, [4, 5, 6, 7, 8])
        self.assertEqual(sorted(int(p.name) for p in removed), [1, 2, 3])

    def test_prune_never_removes_the_current_run_dir(self):
        base = self.root / "talker" / "home"
        base.mkdir(parents=True)
        for i in (1, 2, 3):
            (base / str(i)).mkdir()
        self.pointer().write_text("2\n")     # current is 2, keep only 1
        talker.prune_runs(self.paths, keep=1)
        left = sorted(int(p.name) for p in base.iterdir() if p.name.isdigit())
        self.assertIn(2, left)               # kept even though 2 <= 2 - 1
        self.assertNotIn(1, left)

    def test_a_fresh_run_dir_transcript_is_left_on_disk(self):
        # rotate does not touch talker/memory; the canonical memory survives a reset.
        (self.root / "talker" / "memory" / "MEMORY.md").write_text("durable\n")
        talker.rotate(self.paths, source=self.nosource)
        self.assertEqual((self.root / "talker" / "memory" / "MEMORY.md").read_text(), "durable\n")


class ResetPredicateTest(unittest.TestCase):
    """reset_due fires when the run is older than the max age, off Keel's owned pointer clock."""

    NOW = 1_000_000.0
    DAY = 86400

    def due(self, mtime, max_age=86400):
        return talker.reset_due(self.NOW, mtime, max_age)

    def test_no_pointer_never_resets(self):
        self.assertIsNone(self.due(None))

    def test_young_run_never_resets(self):
        self.assertIsNone(self.due(self.NOW - 10))               # 10s old
        self.assertIsNone(self.due(self.NOW - (self.DAY - 1)))   # just under a day

    def test_old_run_resets_with_a_reason(self):
        reason = self.due(self.NOW - (self.DAY + 100))
        self.assertIsNotNone(reason)
        self.assertIn("old", reason)

    def test_exactly_at_the_max_age_resets(self):
        self.assertIsNotNone(self.due(self.NOW - self.DAY))



class VerbArgvTest(unittest.TestCase):
    """The new verbs' argv and the shell incantation."""

    def parse(self, *argv):
        return talker.build_parser().parse_args(argv)

    def test_fresh_shell_and_status_parse(self):
        self.assertEqual(self.parse("fresh").verb, "fresh")
        self.assertEqual(self.parse("status").verb, "status")
        shell = self.parse("shell")
        self.assertEqual(shell.verb, "shell")
        self.assertFalse(shell.print_only)
        self.assertTrue(self.parse("shell", "--print").print_only)

    def test_shell_incantation_names_the_run_dir_and_config(self):
        paths = talker.Paths(root=Path("/x/keel"), state_dir=Path("/x/keel/state"))
        self.assertEqual(
            talker.shell_incantation(paths),
            "cd /x/keel/talker/home/1 && CLAUDE_CONFIG_DIR=/x/keel/spaces/harbor/.claude claude")


class UpkeepTest(unittest.TestCase):
    """The drain's talker upkeep: rotate only on an old session, only when running."""

    def setUp(self):
        from tests.helpers import make_config
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = make_config(Path(self.tmp.name))
        self.cfg.talker_reset_max_age_seconds = 3600

    def age_pointer(self, seconds: float) -> None:
        """Write the run-dir pointer and backdate its mtime by `seconds` (the owned clock)."""
        p = talker.paths_from(self.cfg).cwd_pointer
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("1\n")
        when = time.time() - seconds
        os.utime(p, (when, when))

    def test_no_reset_when_the_talker_is_not_running(self):
        # no state/talker.pid, so alive(None) is False
        self.assertFalse(talker.upkeep(self.cfg)["reset"])

    @mock.patch("keel.talker.do_fresh")
    @mock.patch("keel.talker.alive", return_value=True)
    def test_reset_fires_on_an_old_run(self, _alive, do_fresh):
        self.age_pointer(5000)                 # > 3600
        result = talker.upkeep(self.cfg, now=time.time())
        self.assertTrue(result["reset"])
        do_fresh.assert_called_once()

    @mock.patch("keel.talker.do_fresh")
    @mock.patch("keel.talker.alive", return_value=True)
    def test_no_reset_when_the_run_is_young(self, _alive, do_fresh):
        self.age_pointer(1)
        result = talker.upkeep(self.cfg, now=time.time())
        self.assertFalse(result["reset"])
        do_fresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
