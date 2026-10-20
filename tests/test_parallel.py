"""The parallel runner (`tests/parallel.py`): what it prints and how it exits must mean what a
serial `python3 -m unittest discover -s tests -t . -v` means.

Every case runs real children over small synthetic modules in a temporary directory, put on
the children's `PYTHONPATH`, because what is being proved is the process boundary: the
counts crossing it, the fence inside each child, a child that dies, and the order output
comes back in.
"""

import io
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from tests import parallel, selector

PASSING = '''
import unittest

class Passing(unittest.TestCase):
    def test_one(self):
        pass

    def test_two(self):
        pass

    @unittest.skip("not today")
    def test_skipped(self):
        pass
'''

FAILING = '''
import unittest

class Failing(unittest.TestCase):
    def test_fails(self):
        self.assertEqual(1, 2)

    def test_errors(self):
        raise RuntimeError("boom")
'''

CRASHING = '''
import os
os._exit(3)
'''

# The children that must never read as a pass: each one ends before its module has run all
# of its tests, and two of them end with status 0.
EARLY_EXIT_ZERO = '''
import os
import unittest

class T(unittest.TestCase):
    def test_a(self):
        pass

    def test_x(self):
        os._exit(0)

    def test_z(self):
        pass
'''

SYS_EXIT_ZERO = '''
import sys
import unittest

class T(unittest.TestCase):
    def test_x(self):
        sys.exit(0)
'''

KILLED = '''
import os
import signal
import unittest

class T(unittest.TestCase):
    def test_x(self):
        os.kill(os.getpid(), signal.SIGKILL)
'''

FENCED = '''
import subprocess
import unittest

class ReachesOut(unittest.TestCase):
    def test_asks_launchctl(self):
        subprocess.run(["launchctl", "list"], capture_output=True)
'''

# A module that records when it ran, so the serial ordering can be read back.
STAMPING = '''
import os
import time
import unittest

class Stamps(unittest.TestCase):
    def test_stamp(self):
        start = time.time()
        time.sleep(0.5)
        with open(os.environ["STAMPS"], "a") as handle:
            handle.write(f"{__name__} {start} {time.time()}\\n")
'''


class RunnerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.env = dict(os.environ, PYTHONPATH=str(self.dir))

    def module(self, name: str, text: str) -> str:
        (self.dir / f"{name}.py").write_text(textwrap.dedent(text))
        return name

    def run_modules(self, modules: list[str], serial: dict | None = None,
                    workers: int = 4) -> tuple[int, str]:
        out = io.StringIO()
        code = parallel.run(modules, workers, serial=serial or {}, out=out, env=self.env)
        return code, out.getvalue()


class SummaryTest(RunnerCase):
    def test_a_passing_run_says_ok_with_the_serial_count_and_exits_zero(self):
        code, out = self.run_modules([self.module("synth_pass", PASSING)])
        self.assertEqual(code, 0, out)
        # three tests of its own plus the fence, counted once as a serial run counts it
        self.assertIn("Ran 4 tests in ", out)
        self.assertTrue(out.rstrip().endswith("OK (skipped=1)"), out)
        self.assertIn(parallel.FENCE_LINE + " ... ok", out)

    def test_failures_and_errors_are_counted_and_shown_and_the_run_exits_one(self):
        code, out = self.run_modules([self.module("synth_pass", PASSING),
                                      self.module("synth_fail", FAILING)])
        self.assertEqual(code, 1)
        self.assertIn("Ran 6 tests in ", out)
        self.assertTrue(out.rstrip().endswith("FAILED (failures=1, errors=1, skipped=1)"), out)
        self.assertIn("FAIL: test_fails (synth_fail.Failing.test_fails)", out)
        self.assertIn("ERROR: test_errors (synth_fail.Failing.test_errors)", out)
        self.assertIn("RuntimeError: boom", out)

    def test_output_comes_back_in_module_order_whatever_finishes_first(self):
        names = [self.module(f"synth_{letter}", PASSING) for letter in "abcdef"]
        code, out = self.run_modules(names, workers=6)
        self.assertEqual(code, 0, out)
        firsts = [out.index(f"(synth_{letter}.Passing.test_one)") for letter in "abcdef"]
        self.assertEqual(firsts, sorted(firsts))

    def test_a_child_that_dies_without_a_result_is_an_error_naming_its_module(self):
        code, out = self.run_modules([self.module("synth_pass", PASSING),
                                      self.module("synth_crash", CRASHING)])
        self.assertEqual(code, 1)
        self.assertIn("ERROR: synth_crash", out)
        self.assertIn("exited 3 without a complete result", out)
        self.assertIn("FAILED (errors=1, skipped=1)", out)


class ColourTest(RunnerCase):
    """c-553: every Claude Code background session sets FORCE_COLOR, and Python 3.14 then
    colours a child's traceback. The children run colour-free whatever the caller set."""

    def setUp(self):
        super().setUp()
        self.env.update(FORCE_COLOR="3")
        self.env.pop("PYTHON_COLORS", None)
        self.env.pop("NO_COLOR", None)

    def test_a_child_s_failures_read_plain_under_force_color(self):
        code, out = self.run_modules([self.module("synth_fail", FAILING)])
        self.assertEqual(code, 1)
        self.assertIn("RuntimeError: boom", out)
        self.assertNotIn("\x1b[", out)


    def test_a_unittest_job_s_ok_matches_its_done_line_under_force_color(self):
        # c-556: a coloured `OK` missed the adapters job's --done line, so a green run failed.
        job = parallel.Job("adapters", f"{sys.executable} -m unittest -v "
                           f"{self.module('synth_pass', PASSING)}", done=selector.ADAPTERS_DONE)
        parallel.run_job(job, env=self.env)
        self.assertEqual(job.code, 0, job.output)
        self.assertEqual(parallel.job_failure(job), "", job.output)


class IncompleteChildTest(RunnerCase):
    """A child counts only when it wrote its whole record after its whole module ran."""

    def assert_error_named(self, name: str, text: str):
        code, out = self.run_modules([self.module("synth_pass", PASSING),
                                      self.module(name, text)])
        self.assertEqual(code, 1, out)
        self.assertIn(f"ERROR: {name}", out)
        self.assertIn("FAILED (errors=1", out)
        self.assertNotIn("\nOK", out)
        return out

    def test_an_early_exit_with_status_zero_is_an_error_not_a_pass(self):
        out = self.assert_error_named("synth_early_exit", EARLY_EXIT_ZERO)
        self.assertIn("exited 0 without a complete result", out)

    def test_a_sigkilled_child_is_an_error(self):
        self.assert_error_named("synth_killed", KILLED)

    def test_sys_exit_inside_a_test_is_an_error(self):
        code, out = self.run_modules([self.module("synth_sys_exit", SYS_EXIT_ZERO)])
        self.assertEqual(code, 1, out)
        self.assertIn("synth_sys_exit", out)
        self.assertIn("FAILED (errors=1)", out)

    def test_a_record_that_finished_fewer_than_it_found_is_an_error(self):
        outcome = parallel.Outcome(module="m")
        parallel.check_record(outcome, {"discovered": 3, "finished": 2, "run": 2,
                                        "failures": [], "skipped": 0, "expected_failures": 0,
                                        "unexpected_successes": 0, "durations": [],
                                        "fence": ""})
        self.assertFalse(outcome.ok)
        self.assertIn("finished 2 of the 3 tests", outcome.failures[0][2])


class FenceTest(RunnerCase):
    def test_a_child_reaching_for_a_fenced_program_fails_the_one_fence_line(self):
        code, out = self.run_modules([self.module("synth_pass", PASSING),
                                      self.module("synth_fenced", FENCED)])
        self.assertEqual(code, 1)
        self.assertIn(parallel.FENCE_LINE + " ... FAIL", out)
        self.assertIn("launchctl list", out)
        # 3 + 1 of their own, plus the fence once, and only the fence failed
        self.assertIn("Ran 5 tests in ", out)
        self.assertIn("FAILED (failures=1, skipped=1)", out)


class SerialTest(RunnerCase):
    def test_a_serial_module_starts_after_every_parallel_one_has_finished(self):
        stamps = self.dir / "stamps"
        self.env["STAMPS"] = str(stamps)
        names = [self.module(f"synth_s{n}", STAMPING) for n in range(4)]
        code, out = self.run_modules(names, serial={"synth_s0": "a shared thing"})
        self.assertEqual(code, 0, out)
        lines = [line.split() for line in stamps.read_text().splitlines()]
        self.assertEqual(sorted(name for name, _, _ in lines), names, "each module runs once")
        rows = {name: (float(start), float(end)) for name, start, end in lines}
        last_parallel_end = max(end for name, (_, end) in rows.items() if name != "synth_s0")
        self.assertGreater(rows["synth_s0"][0], last_parallel_end)

    def test_the_parallel_ones_do_overlap(self):
        stamps = self.dir / "stamps"
        self.env["STAMPS"] = str(stamps)
        names = [self.module(f"synth_p{n}", STAMPING) for n in range(3)]
        code, out = self.run_modules(names, workers=3)
        self.assertEqual(code, 0, out)
        spans = [tuple(map(float, line.split()[1:])) for line in stamps.read_text().splitlines()]
        wall = max(end for _, end in spans) - min(start for start, _ in spans)
        self.assertLess(wall, sum(end - start for start, end in spans))


class JobTest(RunnerCase):
    def test_a_job_runs_beside_the_batch_and_its_output_follows_the_summary(self):
        out = io.StringIO()
        jobs = [parallel.Job("first", "echo from-the-first-job", done="first-job"),
                parallel.Job("second", "echo from-the-second-job", done="second-job")]
        code = parallel.run([self.module("synth_pass", PASSING)], 2, serial={}, out=out,
                            env=self.env, jobs=jobs)
        text = out.getvalue()
        self.assertEqual(code, 0, text)
        ran = text.index("Ran 4 tests")
        self.assertLess(ran, text.index("from-the-first-job"))
        self.assertLess(text.index("from-the-first-job"), text.index("from-the-second-job"))

    def test_a_job_that_fails_fails_the_run_even_when_every_module_passed(self):
        out = io.StringIO()
        code = parallel.run([self.module("synth_pass", PASSING)], 2, serial={}, out=out,
                            env=self.env, jobs=[parallel.Job("broken", "exit 3", done="never")])
        self.assertEqual(code, 1)
        self.assertIn("broken: exited 3", out.getvalue())

    def test_a_job_that_exits_zero_without_saying_it_finished_fails_the_run(self):
        out = io.StringIO()
        job = parallel.Job("quiet", "echo started; exit 0", done=r"^all done$")
        code = parallel.run([self.module("synth_pass", PASSING)], 2, serial={}, out=out,
                            env=self.env, jobs=[job])
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn("quiet: exited 0 but never printed its completion line", out.getvalue())


    def test_only_the_whole_discovery_is_recorded_as_the_full_suite(self):
        """c-544: `make test-all` leaves a `full` record for the review stamp; a run over named
        modules (the selector's targeted run, which records itself) leaves none."""
        from keel.review import testrun
        with mock.patch.object(parallel, "run", return_value=0), \
                mock.patch.object(parallel, "all_modules", return_value=["tests.test_where"]), \
                mock.patch.object(testrun, "record") as record:
            self.assertEqual(parallel.main([]), 0)
            self.assertEqual(parallel.main(["tests.test_where"]), 0)
        record.assert_called_once_with(parallel.ROOT, testrun.FULL, "make test-all", 0,
                                       voice=False)

    def test_the_full_record_says_voice_only_when_its_selftest_ran_green(self):
        """c-646: `kb tested` needs voice passing, and the skip note (no venv) exits 0 too."""
        ran = parallel.Job("voice", "x", done="^ok: ", output="ok: 12 checks\n")
        skipped = parallel.Job("voice", "x", done="^(ok: |voice selftest: skipped)",
                               output="voice selftest: skipped, no .venv-voice\n")
        red = parallel.Job("voice", "x", done="^ok: ", code=1, output="boom\n")
        self.assertTrue(parallel.voice_passed([ran]))
        for jobs in ([skipped], [red], []):
            with self.subTest(jobs=jobs):
                self.assertFalse(parallel.voice_passed(jobs))


class DiscoveryTest(unittest.TestCase):
    def test_all_modules_is_what_discovery_finds_in_the_same_order(self):
        modules = parallel.all_modules()
        self.assertIn("tests.test_parallel", modules)
        self.assertEqual(modules, sorted(modules))
        self.assertNotIn("tests.parallel", modules)
        self.assertNotIn("tests.helpers", modules)


    def test_every_serial_module_exists_and_says_why(self):
        modules = parallel.all_modules()
        for name, why in parallel.SERIAL.items():
            self.assertIn(name, modules)
            self.assertTrue(why.strip(), name)


FLAKY = '''
import os
import unittest
from pathlib import Path


class Flaky(unittest.TestCase):
    def test_steady(self):
        pass

    def test_once(self):
        mark = Path(os.environ["FLAKY_MARK"])
        if not mark.exists():
            mark.write_text("failed once")
            self.fail("the first time")
'''


class RerunTest(RunnerCase):
    """`--rerun LOG` (c-526): a red run's failures once more, and nothing else."""

    def red_log(self) -> Path:
        self.env["FLAKY_MARK"] = str(self.dir / "mark")
        code, out = self.run_modules([self.module("synth_flaky", FLAKY)])
        self.assertEqual(code, 1, out)
        log = self.dir / "red.log"
        log.write_text(out)
        return log

    def rerun(self, log: Path, jobs=None) -> tuple[int, str]:
        out = io.StringIO()
        return parallel.rerun(log, 2, jobs or [], out=out, env=self.env), out.getvalue()

    def test_only_the_failed_test_runs_again_and_passes(self):
        code, out = self.rerun(self.red_log())
        self.assertEqual(code, 0, out)
        self.assertIn("synth_flaky.Flaky.test_once", out)
        self.assertNotIn("test_steady", out)

    def test_a_log_that_names_nothing_is_not_a_pass(self):
        log = self.dir / "empty.log"
        log.write_text("Ran 3 tests in 1s\n\nFAILED (failures=1)\n")
        self.assertEqual(self.rerun(log)[0], 1)

    def test_a_fence_failure_is_not_rerun(self):
        log = self.dir / "fence.log"
        log.write_text(f"FAIL: {parallel.FENCE_LINE}\nRan 3 tests in 1s\n")
        code, out = self.rerun(log)
        self.assertEqual(code, 1)
        self.assertIn("no single test owns", out)

    def test_a_failed_job_reruns_whole_and_its_own_lines_are_not_tests(self):
        log = self.dir / "jobs.log"
        log.write_text("Ran 3 tests in 1s\n\nOK\nFAIL: test_y (adapters_mod.T.test_y)\n"
                       "adapters: exited 1 (`x`)\n")
        job = parallel.Job(name="adapters", command="echo OK", done="^OK$")
        code, out = self.rerun(log, [job, parallel.Job(name="voice", command="exit 1", done="x")])
        self.assertEqual(code, 0, out)
        self.assertIn("0 test(s) and 1 job(s)", out)


if __name__ == "__main__":
    unittest.main()
