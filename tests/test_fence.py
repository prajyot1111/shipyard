"""The fence's own proof: the stand-ins refuse and record, and the environment a house on
the box would pass in is not the environment the tests run in (tests/fence.py)."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from unittest import mock

from keel import browserinstall, deckstate, readiness
from keel import config as config_module
from keel.board import Board
from tests import fence
from tests.helpers import ROOT, make_config


class StateBuildTest(unittest.TestCase):
    """Building the whole state in a test never runs the real `node` (c-678 review F18): the
    browser step asked it for its version, once per process, for any test that built the
    state, and the fence's PATH stand-ins cannot cover node (the deck's fixture tests run
    the real one). The fence stands in for the probe itself. What the prerequisites check
    asks (`git --version`, the harness's version and help, c-632) is not this test's."""

    def test_building_the_state_never_starts_node(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = make_config(Path(tmp.name))
        readiness.forget()
        self.addCleanup(readiness.forget)
        ran = []
        real_run, real_popen = subprocess.run, subprocess.Popen

        def run(argv, *args, **rest):
            ran.append(argv)
            return real_run(argv, *args, **rest)

        class Popen(real_popen):
            def __init__(self, argv, *args, **rest):
                ran.append(argv)
                super().__init__(argv, *args, **rest)
        board = Board(cfg.db_path)
        self.addCleanup(board.close)
        with mock.patch("subprocess.run", run), mock.patch("subprocess.Popen", Popen):
            state = deckstate.build(cfg, board, rows=[])
        names = sorted({Path(str(argv[0] if isinstance(argv, (list, tuple)) else argv).split()[0]).name for argv in ran})
        self.assertNotIn("node", names, ran)
        step = next(one for one in state["firstrun"]["steps"] if one["id"] == "browser")
        self.assertEqual(step["node"], fence.NODE, "the browser step read the suite's stand-in")

    def test_the_real_probe_is_still_there_for_the_test_that_means_it(self):
        self.assertIsNot(browserinstall.probe, browserinstall.node)
        self.assertTrue(callable(browserinstall.node))


class StandInTest(unittest.TestCase):
    """A deliberate call to each fenced name, against a log of this test's own, so the
    run's real log stays empty and `FenceCase` still passes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / "calls.log"
        self.env = dict(os.environ, **{fence.LOG_VAR: str(self.log)})

    def call(self, name, *argv) -> subprocess.CompletedProcess:
        return subprocess.run([name, *argv], capture_output=True, text=True, env=self.env)

    def test_a_deliberate_systemctl_is_refused_and_recorded(self):
        done = self.call("systemctl", "--user", "restart", "dev.keel.service")
        self.assertEqual(done.returncode, fence.REFUSED)
        line = self.log.read_text().strip()
        self.assertIn("systemctl --user restart dev.keel.service", line)
        self.assertIn(f"cwd={os.getcwd()}", line)

    def test_every_fenced_name_is_on_the_path_and_refuses(self):
        for name in fence.FENCED:
            with self.subTest(name=name):
                self.assertEqual(self.call(name, "--version").returncode, fence.REFUSED)
        self.assertEqual(len(self.log.read_text().splitlines()), len(fence.FENCED))

    def test_a_test_that_needs_one_of_these_names_may_supply_its_own(self):
        """The stand-in is only what nobody asked for: a fake earlier on PATH wins."""
        mine = Path(self.tmp.name) / "bin"
        mine.mkdir()
        (mine / "systemctl").write_text("#!/bin/sh\necho mine\n")
        (mine / "systemctl").chmod(0o755)
        self.env["PATH"] = os.pathsep.join([str(mine), self.env["PATH"]])
        done = self.call("systemctl", "status")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "mine"))
        self.assertFalse(self.log.exists(), "nothing was recorded")

    def test_a_run_that_reached_for_one_of_them_ends_non_zero(self):
        """The whole mechanism, in a child of its own: the call is swallowed by its caller
        (as `keel/prompts.py` swallows `kb help`), the test it sits in passes, and the run
        still fails. This is the `atexit` half, which is the backstop for a single module
        and for the adapters suite; the `load_tests` half runs in every `make test` as
        `FenceCase`. The child installs its own fence, so its log is its own.
        """
        program = ("import subprocess\n"
                   "from tests import fence\n"
                   "subprocess.run(['systemctl', '--user', 'restart', 'dev.keel.service'],\n"
                   "               capture_output=True)\n"
                   "print('the caller never noticed')\n")
        done = subprocess.run([sys.executable, "-c", program], cwd=ROOT,
                              capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("the caller never noticed", done.stdout)
        self.assertIn("systemctl --user restart dev.keel.service", done.stderr)

    def test_the_check_names_every_recorded_call(self):
        self.call("iptables", "-S", "INPUT")
        lines = [line for line in self.log.read_text().splitlines() if line.strip()]
        said = fence.report(lines)
        self.assertIn("iptables -S INPUT", said)
        self.assertIn("change this machine", said)


class ScrubbedEnvironmentTest(unittest.TestCase):
    """What a house on the box has in its environment must not be what a test sees."""

    def test_no_keel_variable_of_the_callers_survives(self):
        self.assertEqual([key for key in os.environ if key.startswith("KEEL_")
                          if key != fence.LOG_VAR], [])

    def test_home_is_a_throwaway_and_not_the_real_one(self):
        home = Path(os.environ["HOME"])
        self.assertTrue(home.is_dir())
        self.assertNotEqual(home, fence.real_home)
        self.assertEqual(Path(os.environ["XDG_CONFIG_HOME"]), home / ".config")

    def test_a_commit_has_an_author_without_reading_the_real_git_config(self):
        """Moving `HOME` takes `~/.gitconfig` with it, and production code under test does
        commit (keel/adapters.py scaffolds a new project repo). The identity is passed in
        the environment, never written with `git config`."""
        self.assertEqual(os.environ["GIT_AUTHOR_EMAIL"], os.environ["GIT_COMMITTER_EMAIL"])
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "-C", tmp, "init", "-q", "-b", "main"], check=True)
            Path(tmp, "a").write_text("a\n")
            subprocess.run(["git", "-C", tmp, "add", "a"], check=True)
            done = subprocess.run(["git", "-C", tmp, "commit", "-q", "-m", "x"],
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            who = subprocess.run(["git", "-C", tmp, "log", "-1", "--format=%an <%ae>"],
                                 capture_output=True, text=True).stdout.strip()
        self.assertEqual(who, f"{fence.GIT_NAME} <{fence.GIT_EMAIL}>")

    def test_a_child_process_inherits_the_scrubbed_environment(self):
        """Tests build a subprocess environment out of `os.environ`, so the scrub has to
        live there and not in a wrapper only the careful remember to use."""
        done = subprocess.run([sys.executable, "-c",
                               "import os; print(os.environ['HOME']); "
                               "print([k for k in os.environ if k.startswith('KEEL_')])"],
                              capture_output=True, text=True, env=dict(os.environ))
        home, keys = done.stdout.splitlines()
        self.assertEqual(home, os.environ["HOME"])
        self.assertEqual(keys, f"['{fence.LOG_VAR}']")

    def test_the_repo_toml_now_resolves_its_state_under_the_throwaway_home(self):
        """A home-anchored `state_dir` (the shipped example's `~/.shipyard/state`, as the old
        tracked config's `~/keel/state` was) is a live board. This is the reading that made
        `bin/kb help` create it during the suite (2026-09-20)."""
        cfg = config_module.load(ROOT / "etc" / "shipyard.example.toml", ensure=False)
        self.assertTrue(str(cfg.state_dir).startswith(os.environ["HOME"]), cfg.state_dir)


if __name__ == "__main__":
    unittest.main()
