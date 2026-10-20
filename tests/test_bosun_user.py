"""What is left of Bosun as its own Unix user (docs/atlas/96-bosun.md, "Bosun's own user").

The mode is retired (c-648): Bosun runs as the user Keel runs as, and the `[console]` keys
that made it another user are ignored and named. What the mode left behind is tested here:
the harness still runs another user's config dir as that user, carrying only what the
caller set; the git gate lets a gated key fetch and push Keel's repo and nothing else, and
the receive hook takes `next` only forward and never `main`; `keel console attach` joins the
same session; `kb tested` records a green tree, Bosun's or his word only.
"""

import os
import pwd
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import console, gitgate, harness, housetier, merging
from keel.review import testrun
from keel import config as config_module
from tests.test_authority import BosunCase
from tests.test_console import console_toml

BOSUN = pwd.struct_passwd(("bosun", "x", 1002, 1002, "", "/home/bosun", "/bin/bash"))


class RunAsTest(unittest.TestCase):
    def test_our_own_config_dir_runs_our_claude(self):
        with mock.patch.object(harness, "owner_of", return_value=None):
            argv, env, cwd = harness.command(["agents", "--json"], {"A": "1"}, "/x")
        self.assertEqual((argv[1:], env, cwd), (["agents", "--json"], {"A": "1"}, "/x"))

    def test_another_users_config_dir_runs_as_that_user_with_only_what_was_set(self):
        env = dict(os.environ, CLAUDE_CONFIG_DIR="/home/bosun/.claude-keel", KEEL_HOME="/home/bosun/keel")
        with mock.patch.object(harness, "owner_of", return_value=BOSUN):
            argv, run_env, cwd = harness.command(["attach", "ab12"], env, "/home/bosun/keel")
        self.assertEqual(argv[:6], ["sudo", "-n", "-u", "bosun", "-H", "env"])
        self.assertEqual(argv[6:8], ["-C", "/home/bosun/keel"])
        self.assertIn("CLAUDE_CONFIG_DIR=/home/bosun/.claude-keel", argv)
        self.assertIn("KEEL_HOME=/home/bosun/keel", argv)
        self.assertIn("PATH=/home/bosun/.local/bin:/usr/local/bin:/usr/bin:/bin", argv)
        self.assertEqual(argv[-3:], ["/home/bosun/.local/bin/claude", "attach", "ab12"])
        self.assertFalse([word for word in argv if word.startswith("HOME=")],
                         "this user's own environment never travels")
        self.assertEqual((run_env, cwd), (None, "/home/bosun"))

    def test_its_default_dir_is_reached_unset_and_a_cwd_it_cannot_enter_is_its_home(self):
        env = dict(os.environ, CLAUDE_CONFIG_DIR="/home/bosun/.claude")
        with mock.patch.object(harness, "owner_of", return_value=BOSUN):
            argv, _, _ = harness.command(["-p", "x"], env, "/home/ubuntu/keel/state")
        self.assertFalse([word for word in argv if word.startswith("CLAUDE_CONFIG_DIR=")])
        self.assertEqual(argv[6:8], ["-C", "/home/bosun"])

    def test_a_dir_this_user_owns_or_cannot_see_has_no_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(harness.owner_of(tmp))
        self.assertIsNone(harness.owner_of("/no/such/dir"))
        self.assertIsNone(harness.owner_of(None))


class SameUserTest(unittest.TestCase):
    """Bosun runs as the user Keel runs as (c-648): the keys that made it its own Unix user
    are ignored and named, and its session is built for this user, from Keel's root."""

    def cfg(self, tmp: Path):
        path = console_toml(tmp)
        path.write_text(path.read_text().replace(
            "[console]\n", '[console]\nconfig_dir = "/home/bosun/.claude"\n'
                           'checkout = "/home/bosun/keel"\nboard_url = "http://127.0.0.1:8790"\n'))
        return config_module.load(path, ensure=False)

    def test_the_own_user_keys_are_ignored_and_named(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(console, "key_of", return_value="k"):
            cfg = self.cfg(Path(tmp))
            made = console.settings(cfg)
            env = console.launch_env(cfg)
            self.assertEqual(console.settings_path(cfg), housetier.bosun_settings_path(cfg))
        self.assertEqual(console.config_dir(cfg), cfg.spaces["personal"].config_dir)
        self.assertEqual((made["env"]["KEEL_HOME"], env["KEEL_HOME"]), (str(cfg.root), str(cfg.root)))
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(cfg.spaces["personal"].config_dir))
        for name in ("PATH", "KEEL_URL", "KEEL_HOST"):
            self.assertNotIn(name, made["env"])
        self.assertNotIn("KEEL_URL", env)
        commands = [hook["command"] for event in made["hooks"].values()
                    for entry in event for hook in entry["hooks"]]
        self.assertIn(f"{cfg.root}/bin/keel console memory", commands)
        self.assertIn(f"{cfg.root}/bin/kb console hook", commands)
        for key in ("config_dir", "checkout", "board_url"):
            self.assertTrue(any(line.startswith(f"[console] {key}: Bosun as its own Unix user is retired")
                                for line in cfg.warnings), key)

    def test_in_bypass_it_accepts_the_drains_wake(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(console, "key_of", return_value="k"):
            path = console_toml(Path(tmp))
            plain = console.settings(config_module.load(path, ensure=False))
            path.write_text(path.read_text().replace(
                "[console]\n", '[console]\npermission_mode = "bypassPermissions"\n'))
            bypass = console.settings(config_module.load(path, ensure=False))
        self.assertNotIn("crossSessionInbound", plain)
        self.assertEqual(bypass["crossSessionInbound"], "accept")

    def test_a_transcript_it_cannot_open_reads_as_no_turn(self):
        with mock.patch("builtins.open", side_effect=PermissionError):
            records = console.tail_records(Path("/home/bosun/.claude/projects/x/s.jsonl"))
        self.assertEqual(records, [])

    def test_attach_joins_the_running_session_from_keels_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self.cfg(Path(tmp))
            argv, env, cwd = console.attach_argv(cfg, "ab12cd34")
        self.assertEqual(argv[-2:], ["attach", "ab12cd34"])
        self.assertNotIn("sudo", argv)
        self.assertEqual((cwd, env["CLAUDE_CONFIG_DIR"]),
                         (str(cfg.root), str(cfg.spaces["personal"].config_dir)))


class GateTest(unittest.TestCase):
    root = Path("/home/ubuntu/keel")

    def test_only_git_fetch_and_push_on_this_repo(self):
        home = {"HOME": "/home/ubuntu"}
        with mock.patch.dict(os.environ, home):
            for said in ("git-upload-pack '/home/ubuntu/keel'", "git-receive-pack '/home/ubuntu/keel'",
                         "git-receive-pack 'keel'", "git-upload-pack '~/keel'"):
                with self.subTest(said=said):
                    self.assertEqual(gitgate.gate_argv(said, self.root)[1], str(self.root))
            for said in ("bash", "git-receive-pack '/home/ubuntu/other'", "cat ~/.config/x",
                         "git-upload-pack '/home/ubuntu/keel'; rm -rf /", None, ""):
                with self.subTest(said=said), self.assertRaises(gitgate.GateRefused):
                    gitgate.gate_argv(said, self.root)

    def test_next_only_forward_its_own_branches_and_never_main(self):
        forward = lambda old, new: new.startswith("f")        # noqa: E731
        a, f, b = "a" * 40, "f" * 40, "b" * 40
        self.assertEqual(gitgate.refusals([f"{a} {f} refs/heads/next",
                                           f"{a} {b} refs/heads/bosun/c-9",
                                           f"{gitgate.ZERO} {b} refs/heads/bosun/c-10"], forward), [])
        for line, said in ((f"{a} {f} refs/heads/main", "main moves on the user's deploy"),
                           (f"{a} {b} refs/heads/next", "only a fast-forward"),
                           (f"{a} {gitgate.ZERO} refs/heads/next", "never deleted"),
                           (f"{a} {f} refs/tags/v1", "only")):
            with self.subTest(line=line):
                self.assertIn(said, " ".join(gitgate.refusals([line], forward)))

    def test_the_receive_hook_judges_only_a_gated_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
            hook = Path(__file__).resolve().parent.parent / "bin" / "keel-git-receive"
            line = f"{'a' * 40} {'b' * 40} refs/heads/main\n"
            plain = subprocess.run([str(hook)], input=line, text=True, cwd=repo,
                                   env={k: v for k, v in os.environ.items() if k != gitgate.GATE_ENV})
            gated = subprocess.run([str(hook)], input=line, text=True, cwd=repo, capture_output=True,
                                   env=dict(os.environ, **{gitgate.GATE_ENV: gitgate.BOSUN}))
        self.assertEqual(plain.returncode, 0)
        self.assertEqual(gated.returncode, 1)
        self.assertIn("main moves on the user's deploy", gated.stderr)


class TestedVerbTest(BosunCase):
    def setUp(self):
        super().setUp()
        self.repo = self.dir / "repo"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        (self.repo / "f").write_text("x")
        git = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "add", "f"], check=True)
        subprocess.run([*git, "commit", "-q", "-m", "one"], check=True)
        self.sha = merging.git(self.repo, "rev-parse", "HEAD")
        toml = self.dir / "keel.toml"
        toml.write_text(toml.read_text().replace('[spaces.personal.repos]\nkeel = "~/keel"',
                                                 f'[spaces.personal.repos]\nkeel = "{self.repo}"'))

    def ran(self, kind, code=0, voice=True):
        testrun.record(self.repo, kind, "a run", code, voice=voice)

    def test_bosun_records_a_green_tree_the_deploy_then_skips(self):
        self.ran(testrun.FULL)
        code, _, err = self.as_bosun("tested", self.sha)
        self.assertEqual(code, 0, err)
        cfg = config_module.load(self.dir / "keel.toml", ensure=False)
        found = merging.tested_whole(cfg, merging.tree_of(self.repo, self.sha))
        self.assertEqual(found["card"], f"bosun {self.sha[:12]}")

    def test_only_a_green_full_run_with_voice_at_that_commit_counts(self):
        # `make test` is the core suite and what the change reaches: it proves no tree
        for kind, code, voice in ((testrun.CORE_REACHED, 0, True), (testrun.FULL, 1, True),
                                  (testrun.FULL, 0, False)):
            with self.subTest(kind=kind, code=code, voice=voice):
                self.ran(kind, code, voice)
                self.refused("make test-all", "tested", self.sha)
        self.ran(testrun.FULL)
        (self.repo / "f").write_text("y")
        git = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "commit", "-qam", "two"], check=True)
        later = merging.git(self.repo, "rev-parse", "HEAD")
        self.refused("make test-all", "tested", later)     # the run was at the commit before

    def test_a_house_cannot_and_an_unknown_commit_is_refused(self):
        card = self.create()
        code, _, err = self.kb("tested", self.sha, env={"KEEL_CARD": card})
        self.assertEqual(code, 1)
        self.assertIn("Bosun's or the user's", err)
        self.refused("push it first", "tested", "f" * 40)


if __name__ == "__main__":
    unittest.main()
