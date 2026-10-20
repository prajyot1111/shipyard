"""The core and extended suites (c-646, `tests/core.txt`, `tests/suites.py`).

The core list is the one source of membership: every test module is core because the list
names it, or extended because it does not, so none is in two places or in none. What can go
wrong is the list itself (a name for a module that was renamed or deleted, a name twice) and
what `make test` does with it, so those are what is held here.
"""

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import parallel, selector, suites


class MembershipTest(unittest.TestCase):
    def test_the_core_list_names_only_test_modules_and_each_once(self):
        self.assertEqual(suites.problems(), [])

    def test_make_test_core_loads_exactly_the_modules_the_list_names(self):
        """Read independently of `suites.listed`: every line of `core.txt` that starts with
        a dotted name is one `make test-core` (`tests.parallel --core`) hands the runner."""
        text = (parallel.ROOT / "tests" / "core.txt").read_text(encoding="utf-8")
        named = set(re.findall(r"^(tests\.test_\w+)\s*(?:#.*)?$", text, re.MULTILINE))
        with mock.patch.object(parallel, "run", return_value=0) as ran, \
                mock.patch("keel.review.testrun.record"):
            parallel.main(["--core"])
        self.assertTrue(named)
        self.assertEqual(set(ran.call_args.args[0]), named)

    def test_a_stale_or_doubled_name_is_a_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_a.py").write_text("")
            (root / "tests" / "core.txt").write_text(
                "# a comment\ntests.test_a  # kept\ntests.test_gone\ntests.test_a\n")
            found = suites.problems(root)
            self.assertEqual(suites.core_modules(root), ["tests.test_a"])
            self.assertEqual(suites.extended_modules(root), [])
        self.assertEqual(found, ["tests.test_gone: no tests/test_gone.py",
                                 "tests.test_a: named 2 times"])


class MakeTestTest(unittest.TestCase):
    """`make test` is `tests/selector.py --core`: the core suite whatever changed, with the
    extended modules the change reaches and the import check; a change it cannot place is
    every module."""

    def setUp(self):
        self.selector = selector.Selector()

    def test_no_change_still_runs_every_core_module_and_the_import_check(self):
        chosen = self.selector.select([], core=True)
        self.assertEqual(chosen.full, [])
        self.assertLessEqual(set(suites.core_modules()), set(chosen.modules))
        argv = selector.command(chosen)
        self.assertEqual(argv[:3], [sys.executable, "-m", "tests.parallel"])
        self.assertIn(f"py312={selector.PY312_COMMAND}", argv)
        self.assertNotIn("tests.test_sandbox", argv, "an extended module nothing reached")
        self.assertIn(selector.VOICE_UNREACHED, selector.report([], chosen).splitlines())

    def test_an_extended_module_runs_when_its_area_changes(self):
        chosen = self.selector.select(["keel/sentences.py"], core=True)
        self.assertIn("tests.test_sentences", chosen.modules)
        self.assertNotIn("tests.test_sentences", suites.core_modules())

    def test_one_reached_only_through_a_chain_waits_for_test_all(self):
        """Through a chain nearly every module reaches every other, so `make test` takes an
        extended module only when it imports the changed file itself; `make test-changed`
        still follows the chain."""
        rel, far = "keel/voicelatency.py", "tests.test_sandbox"
        self.assertIn(far, self.selector.select([rel]).modules)
        self.assertNotIn(far, self.selector.select([rel], core=True).modules)

    def test_a_change_it_cannot_place_runs_every_module(self):
        chosen = self.selector.select(["Makefile"], core=True)
        self.assertEqual(selector.command(chosen)[-1], "test-all")

    def test_keel_full_suite_makes_make_test_run_test_all_and_unset_the_selector(self):
        """A deploy whose config names no `[deploy_tests]` sets KEEL_FULL_SUITE and runs
        `make test` (c-646). `make -n` still runs a recipe line naming $(MAKE), so the line
        is run for real here with $(MAKE) and python3 replaced by echoes: neither branch
        can start a suite."""
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "python3"
            fake.write_text('#!/bin/sh\necho "SELECTOR $*"\n')
            fake.chmod(0o755)
            env = {"PATH": f"{tmp}:/usr/bin:/bin", "HOME": tmp}
            for full in (True, False):
                with self.subTest(full=full):
                    done = subprocess.run(["make", "-n", "test", "MAKE=echo RECURSE"],
                                          cwd=parallel.ROOT, capture_output=True, text=True,
                                          timeout=30,
                                          env=dict(env, KEEL_FULL_SUITE="1") if full else env)
                    ran = [line for line in done.stdout.splitlines()
                           if line.startswith(("RECURSE", "SELECTOR"))]
                    self.assertEqual(ran, ["RECURSE --no-print-directory test-all"] if full
                                     else ["SELECTOR -m tests.selector --core --base main"],
                                     done.stdout + done.stderr)

    def test_an_edit_to_the_core_list_runs_its_check(self):
        chosen = self.selector.select(["tests/core.txt"])
        self.assertEqual(chosen.full, [])
        self.assertIn("tests.test_suites", chosen.modules)


if __name__ == "__main__":
    unittest.main()
