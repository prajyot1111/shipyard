"""`make test-changed` (`tests/selector.py`) on synthetic trees and synthetic diffs.

Each case builds a small repo shaped like Keel's in a temporary directory, so what is proved
is the rule and not today's import graph: a change reaches exactly the test modules it can,
and anything the selector cannot place, or any change to the suite's own machinery, runs the
full suite and says why.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests import selector

TREE = {
    "keel/__init__.py": "",
    "keel/a.py": "VALUE = 1\n",
    "keel/b.py": "from keel import a\n",
    "keel/c.py": "import json\n",
    "keel/d.py": "def later():\n    from keel.b import thing\n",
    "tests/__init__.py": "",
    "tests/fence.py": "",
    "tests/helpers.py": "",
    "tests/test_atlas.py": "import unittest\n",
    "tests/test_a.py": "import unittest\n",
    "tests/test_b.py": "from keel import b\n",
    "tests/test_c.py": "import keel.c\n",
    "tests/test_d.py": "from keel import d\n",
    "tests/test_app.py": 'ROOT = None\nAPP = ROOT / "app"\n',
    "tests/test_kb.py": 'KB = ROOT / "bin" / "kb"\n',
    "tests/test_config.py": 'import unittest\n',
    "tests/test_toml.py": 'TOML = ROOT / "etc" / "shipyard.example.toml"\n',
    "tests/test_theme.py": 'TEXT = "cp $KEEL_HOME/etc/theme.css here"\n',
    "tests/test_voiceread.py": 'SRC = ROOT / "voice" / "harbor_voice" / "bus.py"\n',
    "app/ui.css": "body {}\n",
    "bin/kb": "#!/usr/bin/env python3\nfrom keel import c\n",
    "bin/keel-voice-selftest": "#!/usr/bin/env python3\n",
    "packs/work/tracker.py": "import json\n",
    "packs/work/tests/test_tracker.py": "import tracker\n",
    "packs/other/host.py": "import json\n",
    "packs/other/tests/test_host.py": "import host\nfrom keel import e\n",
    "keel/e.py": "VALUE = 5\n",
    "keel/packkit/__init__.py": "VERSION = 1\n",
    "keel/packkit/card.py": "import json\n",
    "voice/harbor_voice/__init__.py": "",
    "voice/harbor_voice/bus.py": "from . import __name__ as n\n",
    "docs/atlas/10-cards.md": "# Cards\n",
    "etc/theme.css": "x {}\n",
    "etc/shipyard.example.toml": "[keel]\n",
    "segments/foo/notes.txt": "nothing reads this\n",
    "Makefile": "test:\n",
}


class SelectorCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for rel, text in TREE.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.selector = selector.Selector(self.root)

    def pick(self, *changed: str) -> selector.Selection:
        return self.selector.select(list(changed))

    def modules(self, *changed: str) -> set[str]:
        selection = self.pick(*changed)
        self.assertEqual(selection.full, [], "expected a targeted run")
        return set(selection.modules)


class PythonTest(SelectorCase):
    def test_a_module_reaches_its_importers_transitively_and_its_namesake(self):
        # a <- b <- test_b, and b <- d (inside a function) <- test_d; test_a by name
        self.assertEqual(self.modules("keel/a.py"),
                         {"tests.test_atlas", "tests.test_a", "tests.test_b", "tests.test_d"})

    def test_an_unrelated_module_is_left_out(self):
        self.assertEqual(self.modules("keel/c.py"), {"tests.test_atlas", "tests.test_c"})

    def test_a_changed_test_module_runs_itself(self):
        self.assertEqual(self.modules("tests/test_c.py"), {"tests.test_atlas", "tests.test_c"})

    def test_the_guard_runs_even_when_nothing_else_does(self):
        self.assertEqual(self.modules("docs/atlas/10-cards.md"), {"tests.test_atlas"})

    def test_an_adapter_module_runs_the_adapter_suite(self):
        selection = self.pick("packs/work/tracker.py")
        self.assertEqual(selection.full, [])
        self.assertTrue(selection.adapters)
        self.assertFalse(selection.voice)

    def test_any_pack_s_own_tests_are_the_adapter_suite_s_and_never_a_module_of_the_batch(self):
        """c-689: every pack with a `tests/` of its own, not only the work pack's. A change
        to engine code that only another pack's test imports still owes the packs' suites."""
        selection = self.pick("packs/other/host.py", "packs/other/tests/test_host.py")
        self.assertEqual(selection.full, [])
        self.assertTrue(selection.adapters)
        self.assertEqual(set(selection.modules), {"tests.test_atlas"})
        engine = self.pick("keel/e.py")
        self.assertEqual(engine.adapters, "imports keel/e.py")
        self.assertEqual(set(engine.modules), {"tests.test_atlas"})

    def test_a_change_to_the_pack_kit_runs_every_pack_s_own_suite(self):
        """c-735: every pack on the kit runs on it, the install's own included, which no
        import graph of this tree can see, so a change to the kit owes the packs' suites."""
        selection = self.pick("keel/packkit/card.py")
        self.assertEqual(selection.full, [])
        self.assertEqual(selection.adapters, "keel/packkit/card.py is the pack kit's")

    def test_a_voice_module_runs_the_voice_selftest_and_the_tests_that_read_it(self):
        selection = self.pick("voice/harbor_voice/bus.py")
        self.assertTrue(selection.voice)
        self.assertIn("tests.test_voiceread", selection.modules)

    def test_nothing_under_voice_leaves_the_selftest_out(self):
        self.assertFalse(self.pick("keel/a.py").voice)


class FileRuleTest(SelectorCase):
    def test_an_app_file_runs_the_tests_that_read_app_files(self):
        self.assertEqual(self.modules("app/ui.css"), {"tests.test_atlas", "tests.test_app"})

    def test_a_script_runs_the_tests_that_name_it(self):
        self.assertEqual(self.modules("bin/kb"), {"tests.test_atlas", "tests.test_kb"})

    def test_a_voice_script_runs_the_selftest(self):
        self.assertTrue(self.pick("bin/keel-voice-selftest").voice)

    def test_the_shipped_example_runs_test_config_and_the_tests_naming_it(self):
        """c-726 r1.F3: the shipped config is the example; the tree tracks no keel.toml."""
        self.assertEqual(self.modules("etc/shipyard.example.toml"),
                         {"tests.test_atlas", "tests.test_config", "tests.test_toml"})

    def test_an_etc_file_runs_the_guards_and_the_tests_naming_it(self):
        self.assertEqual(self.modules("etc/theme.css"), {"tests.test_atlas", "tests.test_theme"})


class FailSafeTest(SelectorCase):
    def assert_full(self, rel: str, reason: str):
        selection = self.pick("keel/c.py", rel)
        self.assertTrue(selection.full, f"{rel} should have run the full suite")
        self.assertTrue(any(rel in why and reason in why for why in selection.full),
                        selection.full)
        self.assertEqual(selector.command(selection)[-1], "test-all")

    def test_a_file_no_rule_places_runs_everything_and_says_so(self):
        self.assert_full("segments/foo/notes.txt", "no rule places it")

    def test_the_suites_own_machinery_runs_everything(self):
        for rel in ("tests/fence.py", "tests/__init__.py", "tests/helpers.py",
                    "tests/boardleak.py", "tests/parallel.py", "tests/selector.py",
                    "tests/suites.py", "Makefile"):
            with self.subTest(rel=rel):
                self.assert_full(rel, "machinery")

    def test_a_deleted_module_runs_everything(self):
        self.assert_full("keel/gone.py", "deleted")


class CommandTest(SelectorCase):
    def test_a_targeted_run_is_the_runner_over_the_modules_with_the_jobs_it_needs(self):
        argv = selector.command(self.pick("keel/a.py", "packs/work/tracker.py"))
        self.assertEqual(argv[:3], [sys.executable, "-m", "tests.parallel"])
        self.assertIn("tests.test_b", argv)
        self.assertIn(f"adapters={selector.ADAPTERS_COMMAND}", argv)
        self.assertIn(f"adapters={selector.ADAPTERS_DONE}", argv)
        self.assertFalse(any(arg.startswith("voice=") for arg in argv))

    def test_the_adapters_job_runs_each_pack_s_own_suite_and_ends_ok_only_when_all_passed(self):
        """c-689: the job is one command over every `packs/<name>/tests`, each suite in a
        process of its own (two packs may both have a `suitefence`), and the Makefile runs
        the same command."""
        suite = ("import unittest\nclass T(unittest.TestCase):\n    def test_{name}(self):\n"
                 "        self.assertTrue({ok})\n")

        def run(other_passes: bool) -> subprocess.CompletedProcess:
            (self.root / "packs/work/tests/test_tracker.py").write_text(suite.format(name="tracker", ok=True))
            (self.root / "packs/other/tests/test_host.py").write_text(suite.format(name="host", ok=other_passes))
            return self.adapters()

        done = run(True)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertRegex(done.stdout.strip().splitlines()[-1], selector.ADAPTERS_DONE)
        for name in ("test_tracker", "test_host"):
            self.assertIn(name, done.stdout)
        self.assertNotEqual(run(False).returncode, 0)
        makefile = (selector.ROOT / "Makefile").read_text()
        self.assertIn(f"ADAPTERS_TESTS = {selector.ADAPTERS_COMMAND.replace('$', '$$')}\n", makefile)

    def adapters(self, **env) -> subprocess.CompletedProcess:
        """The adapters job, run in the fixture tree as the runner runs it."""
        (self.root / "tests").mkdir(exist_ok=True)
        (self.root / "tests" / "packsuites.py").write_text((selector.ROOT / "tests" / "packsuites.py").read_text())
        base = {key: value for key, value in os.environ.items() if key != "KEEL_CONFIG"}
        return subprocess.run(selector.ADAPTERS_COMMAND, shell=True, cwd=self.root, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              env={**base, "PYTHON_COLORS": "0", "NO_COLOR": "1", **env})

    def test_the_installs_own_packs_suites_run_too(self):
        """c-726 r1.F4: a pack the install holds (its work pack) is not in the tree, so its
        suite runs from the install KEEL_CONFIG names, and fails the job as a tree pack's does."""
        suite = ("import unittest\nclass T(unittest.TestCase):\n    def test_{name}(self):\n"
                 "        self.assertTrue({ok})\n")
        install = self.root.parent / (self.root.name + "-install")
        self.addCleanup(lambda: __import__("shutil").rmtree(install, ignore_errors=True))
        (install / "packs" / "own" / "tests").mkdir(parents=True)
        (install / "config.toml").write_text("")
        (self.root / "packs/other/tests/test_host.py").write_text(suite.format(name="host", ok=True))
        (self.root / "packs/work/tests/test_tracker.py").write_text(suite.format(name="tracker", ok=True))
        own = install / "packs" / "own" / "tests" / "test_own.py"
        own.write_text(suite.format(name="installs_own", ok=True))
        done = self.adapters(KEEL_CONFIG=str(install / "config.toml"))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("test_installs_own", done.stdout)
        self.assertRegex(done.stdout.strip().splitlines()[-1], selector.ADAPTERS_DONE)
        self.assertNotIn("test_installs_own", self.adapters().stdout, "no install named, none read")
        own.write_text(suite.format(name="installs_own", ok=False))
        self.assertNotEqual(self.adapters(KEEL_CONFIG=str(install / "config.toml")).returncode, 0)
        self.assertEqual(list((install / "packs" / "own" / "tests").rglob("*.pyc")), [],
                         "nothing is written into the install")

    def test_the_report_gives_a_reason_for_every_module(self):
        changed = ["keel/a.py"]
        text = selector.report(changed, self.pick(*changed))
        self.assertIn("tests.test_b  (imports keel/a.py)", text)
        self.assertIn("tests.test_a  (named for keel/a.py)", text)
        self.assertIn("tests.test_atlas  (a guard, always run)", text)
        self.assertIn(selector.VOICE_UNREACHED, text.splitlines())


class ChangedFilesTest(unittest.TestCase):
    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)

    def test_committed_staged_unstaged_and_untracked_are_all_changes(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.git("init", "-q", "-b", "main")
        for name in ("committed", "staged", "unstaged", "same"):
            (self.root / name).write_text("0\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "work")
        (self.root / "committed").write_text("1\n")
        self.git("commit", "-q", "-am", "on the branch")
        (self.root / "staged").write_text("1\n")
        self.git("add", "staged")
        (self.root / "unstaged").write_text("1\n")
        (self.root / "untracked").write_text("1\n")
        self.assertEqual(selector.changed_files("main", self.root),
                         ["committed", "staged", "unstaged", "untracked"])


class RealTreeTest(unittest.TestCase):
    def test_this_repo_s_graph_sees_the_board_imported_widely(self):
        """A sanity check on the real tree: the board is imported by most of the suite, so
        a change to it must reach far more than a handful of modules."""
        chosen = selector.Selector().select(["keel/board.py"])
        self.assertEqual(chosen.full, [])
        self.assertGreater(len(chosen.modules), 20)
        self.assertIn("tests.test_board", chosen.modules)

    def test_what_the_voice_package_imports_and_reads_owes_the_selftest(self):
        """c-646: `harbor_voice.index` imports `keel/deckdigest.py`, and the selftest reads
        the voice and cloud-spend segments and each pack's `hearing.json` by path."""
        chooser = selector.Selector()
        for rel in ("keel/deckdigest.py", "segments/voice/segment.md",
                    "segments/cloud-spend/record.py", "packs/work/hearing.json"):
            for core in (False, True):
                with self.subTest(rel=rel, core=core):
                    self.assertTrue(chooser.select([rel], core=core).voice)



class RecordTest(SelectorCase):
    """c-544: what ran is left in the worktree's git dir for the review stamp to read."""

    def setUp(self):
        super().setUp()
        git = ("git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@x")
        subprocess.run((*git, "init", "-q"), check=True)
        subprocess.run((*git, "add", "-A"), check=True)
        subprocess.run((*git, "commit", "-q", "-m", "tree"), check=True)
        self.head = subprocess.run((*git, "rev-parse", "HEAD"), capture_output=True, text=True,
                                   check=True).stdout.strip()

    def test_a_targeted_run_is_recorded_with_its_module_count(self):
        from keel.review import testrun
        selection = self.pick("keel/c.py")
        selector.record(selection, 0, root=self.root)
        got = testrun.at_head(self.root, self.head)
        self.assertEqual((got["kind"], got["modules"], got["exit"]), (testrun.TARGETED, 2, 0))
        self.assertFalse(list(self.root.glob(testrun.FILE)), "never in the tree itself")

    def test_a_fallback_is_recorded_as_full_with_why(self):
        from keel.review import testrun
        # the fallback's `make test-all` recorded first, saying voice ran (c-646): kept
        testrun.record(self.root, testrun.FULL, "make test-all", 1, voice=True)
        selector.record(self.pick("segments/foo/notes.txt"), 1, root=self.root)
        got = testrun.at_head(self.root, self.head)
        self.assertEqual((got["kind"], got["exit"], got["voice"]), (testrun.FULL, 1, True))
        self.assertIn("no rule places it", got["why"])
        self.assertIn("red (exit 1)", testrun.said(got))

    def test_a_corrupt_record_and_a_directory_with_no_git_are_none_and_never_raise(self):
        from keel.review import testrun
        testrun.path_of(self.root).write_text("{not json")
        self.assertEqual(testrun.at_head(self.root, self.head)["kind"], "none")
        with tempfile.TemporaryDirectory() as bare:
            testrun.record(bare, testrun.FULL, "make test", 0)
            self.assertEqual(testrun.at_head(bare, self.head)["kind"], "none")
            self.assertEqual(list(Path(bare).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
