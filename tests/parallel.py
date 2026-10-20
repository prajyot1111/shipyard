"""The suite across worker processes: one child per test module, the output printed in order.

`python3 -m tests.parallel` runs every `tests/test_*.py` module, each in its own child
process, `min(cpu_count, 8)` at a time, and prints what a serial
`python3 -m unittest discover -s tests -t . -v` prints: every test's verbose line, module by
module in name order, then the failures, then one `Ran N tests` line and `OK` or `FAILED`,
with exit status 1 on any failure; that is `make test-all`. Named modules
(`python3 -m tests.parallel tests.test_x`) run only those, which is how `make test` and
`make test-changed` run their selection (`tests/selector.py`), and `--core` runs the core
list (`tests/core.txt`, `tests/suites.py`), which is `make test-core`.

Each child is `python3 -m tests.parallel --child <module>`, which imports the `tests`
package first, so the fence (`tests/fence.py`) and the Board leak check
(`tests/boardleak.py`) are installed in every child exactly as in a serial run. The fence
records per process, so every child runs `FenceCase` after its module and reports the
verdict separately; the parent counts the fence as ONE test, as a serial run does, and fails
it if any child's fence recorded a call. A child that dies without a result (a crash, or
the fence's own `atexit` guard) is an error named after its module.

Other suites that share nothing with these modules (the work adapter's, the voice
selftest) are passed as `--job NAME=COMMAND`: each starts with the batch, in its own shell,
outside the worker pool (the voice selftest spends its time waiting, not computing), and its
output is printed after the summary, in the order given, as the Makefile printed it when
the suites ran one after another. A job counts only when it exits 0 AND its last line
matches the completion line given with `--done NAME=REGEX`; every job must have one.

A child counts only by its complete result record, written in one rename after its whole
module ran and carrying how many tests it found and how many it finished. Whatever its exit
status, a child whose record is missing, partial or short is an error named after its
module: `os._exit(0)` in a test ends a child with 0 and the rest of its module unrun.

`SERIAL` lists the modules that cannot share the machine with another one; they run one at
a time after the parallel batch, each with the shared resource named beside it.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
import warnings
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WORKERS_MAX = 8
SEP1, SEP2 = "=" * 70, "-" * 70
FENCE_LINE = ("test_nothing_reached_the_machine "
              "(tests.fence.FenceCase.test_nothing_reached_the_machine)")

# Modules that must not run beside another module, and the resource each one shares. Empty
# means none was found: every server a test starts binds port 0, and every path a test
# writes is under its own temporary directory (checked 2026-09-24 over three full parallel
# runs; see the Atlas, "The test fence", for how to add one).
SERIAL: dict[str, str] = {}


@dataclass
class Outcome:
    """What one child reported: its counts, its failure blocks, its durations, its output."""
    module: str
    run: int = 0
    failures: list = field(default_factory=list)      # [flavour, description, traceback]
    skipped: int = 0
    expected_failures: int = 0
    unexpected_successes: int = 0
    durations: list = field(default_factory=list)     # [description, seconds]
    fence: str = ""                                   # the fence's failure text, if any
    output: str = ""
    code: int = 0
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.failures and not self.unexpected_successes \
            and not self.fence


def all_modules(root: Path = ROOT) -> list[str]:
    """Every test module, in the order discovery runs them."""
    return sorted(f"tests.{path.stem}" for path in (root / "tests").glob("test*.py"))


def workers_for(count: int | None = None) -> int:
    return max(1, min(count or os.cpu_count() or 1, WORKERS_MAX))


# The child: one module, under the fence, verdicts to a JSON file.

def child(module: str, result_path: Path) -> int:
    """Run one module the way `unittest` would, write its verdict, exit 0 when it passed."""
    import tests  # noqa: F401  the fence and the leak check, before the module is imported
    from tests import fence
    stream = unittest.runner._WritelnDecorator(sys.stderr)
    result = unittest.TextTestResult(stream, True, 2)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames([module])
    discovered = suite.countTestCases()
    with warnings.catch_warnings():
        if not sys.warnoptions:
            warnings.simplefilter("default")      # what `python3 -m unittest` sets
        result.startTestRun()
        try:
            suite(result)
        finally:
            result.stopTestRun()
    fenced = unittest.TestResult()
    fence.FenceCase("test_nothing_reached_the_machine")(fenced)
    report = verdict(result, fenced)
    report.update(discovered=discovered, finished=result.testsRun)
    # Written whole or not at all: the parent reads a missing or partial record as an error.
    partial = result_path.with_suffix(".partial")
    partial.write_text(json.dumps(report), encoding="utf-8")
    os.replace(partial, result_path)
    return 0 if result.wasSuccessful() and not report["fence"] else 1


def verdict(result: unittest.TestResult, fenced: unittest.TestResult) -> dict:
    blocks = ([["ERROR", str(test), text] for test, text in result.errors]
              + [["FAIL", str(test), text] for test, text in result.failures])
    fence_text = "".join(text for _, text in fenced.failures + fenced.errors)
    return {"run": result.testsRun, "failures": blocks, "skipped": len(result.skipped),
            "expected_failures": len(result.expectedFailures),
            "unexpected_successes": len(result.unexpectedSuccesses),
            "durations": [[str(test), seconds]
                          for test, seconds in getattr(result, "collectedDurations", [])],
            "fence": fence_text}


# The parent: schedule, collect, print in order.

def plain(env: dict | None) -> dict:
    """The children's environment, colour off whatever the caller set (c-553): a Claude Code
    background session sets FORCE_COLOR, and Python 3.14 then colours a child's traceback,
    so the text a verdict carries would not match what a serial run prints.
    `PYTHON_COLORS=0` wins over FORCE_COLOR in the interpreter; NO_COLOR covers the rest."""
    env = dict(os.environ if env is None else env)
    env.update(PYTHON_COLORS="0", NO_COLOR="1")
    return env


def launch(module: str, env: dict | None = None) -> Outcome:
    """One child, its output to a file (no pipe to fill), its verdict read back."""
    with tempfile.TemporaryDirectory(prefix="keel-par-") as scratch:
        out_path, result_path = Path(scratch) / "out", Path(scratch) / "result.json"
        started = time.monotonic()
        with open(out_path, "wb") as out:
            done = subprocess.run(
                [sys.executable, "-m", "tests.parallel", "--child", module,
                 "--result", str(result_path)],
                cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                env=plain(env))
        outcome = Outcome(module=module, code=done.returncode,
                          seconds=time.monotonic() - started,
                          output=out_path.read_text(encoding="utf-8", errors="replace"))
        record = result_path.read_text(encoding="utf-8") if result_path.exists() else None
        read_record(outcome, record)
        return outcome


RECORD_KEYS = ("run", "failures", "skipped", "expected_failures", "unexpected_successes",
               "durations", "fence", "discovered", "finished")


def read_record(outcome: Outcome, text: str | None) -> None:
    """A child counts only by its complete record, WHATEVER its exit status: a test that
    calls `os._exit(0)` ends the child with 0 and the rest of its module unrun, and an exit
    status alone would read that as a pass. Missing, partial or short is an error named
    after the module."""
    try:
        record = json.loads(text) if text is not None else None
    except ValueError:
        record = None
    if not isinstance(record, dict) or any(key not in record for key in RECORD_KEYS):
        outcome.run, outcome.failures = 0, [[
            "ERROR", outcome.module,
            f"the child running {outcome.module} exited {outcome.code} without a complete "
            f"result, so its tests are not counted; its output is above\n"]]
        return
    check_record(outcome, record)


def check_record(outcome: Outcome, record: dict) -> None:
    for key in RECORD_KEYS[:7]:
        setattr(outcome, key, record[key])
    if record["finished"] < record["discovered"] and not outcome.failures:
        outcome.failures = [["ERROR", outcome.module,
                             f"{outcome.module} finished {record['finished']} of the "
                             f"{record['discovered']} tests it found\n"]]


def schedule(modules: list[str], serial: dict[str, str], workers: int,
             env: dict | None = None, printer=None) -> list[Outcome]:
    """The parallel batch longest-first, then the serial ones one at a time; outcomes are
    handed to `printer` in `modules` order, each as soon as it and all before it are in."""
    parallel = [name for name in modules if name not in serial]
    ordered = sorted(parallel, key=weight, reverse=True)
    results: dict[str, Outcome] = {}
    shown = 0

    def flush():
        nonlocal shown
        while shown < len(modules) and modules[shown] in results:
            if printer:
                printer(results[modules[shown]])
            shown += 1

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(launch, name, env): name for name in ordered}
        pending = set(futures)
        while pending:
            finished = {future for future in pending if future.done()}
            for future in finished:
                results[futures[future]] = future.result()
            pending -= finished
            flush()
            if pending:
                time.sleep(0.05)
    for name in [name for name in modules if name in serial]:
        results[name] = launch(name, env)
        flush()
    flush()
    return [results[name] for name in modules]


def weight(module: str) -> int:
    """How long a module is likely to take, for longest-first packing: its size on disk."""
    path = ROOT / Path(*module.split(".")).with_suffix(".py")
    return path.stat().st_size if path.exists() else 0


def summary(outcomes: list[Outcome], seconds: float, durations: int | None = None) -> str:
    """The tail a serial run prints: the fence line, failures, durations, the count, OK."""
    fences = [o.fence for o in outcomes if o.fence]
    lines = [FENCE_LINE + (" ... FAIL" if fences else " ... ok")]
    blocks = [block for o in outcomes for block in o.failures]
    blocks += [["FAIL", FENCE_LINE, text] for text in fences]
    for flavour, description, text in blocks:
        lines += [SEP1, f"{flavour}: {description}", SEP2, text.rstrip("\n")]
    if durations:
        lines += slowest(outcomes, durations)
    ran = sum(o.run for o in outcomes) + 1
    lines += [SEP2, f"Ran {ran} test{'s' if ran != 1 else ''} in {seconds:.3f}s", ""]
    lines.append(status_line(outcomes, len(fences)))
    return "\n".join(lines) + "\n"


def status_line(outcomes: list[Outcome], fence_failures: int) -> str:
    fails = sum(1 for o in outcomes for b in o.failures if b[0] == "FAIL") + fence_failures
    errors = sum(1 for o in outcomes for b in o.failures if b[0] == "ERROR")
    parts = [(key, value) for key, value in (
        ("failures", fails), ("errors", errors),
        ("skipped", sum(o.skipped for o in outcomes)),
        ("expected failures", sum(o.expected_failures for o in outcomes)),
        ("unexpected successes", sum(o.unexpected_successes for o in outcomes))) if value]
    ok = all(o.ok for o in outcomes) and not fence_failures
    info = ", ".join(f"{key}={value}" for key, value in parts)
    return ("OK" if ok else "FAILED") + (f" ({info})" if info else "")


def slowest(outcomes: list[Outcome], count: int) -> list[str]:
    rows = sorted((row for o in outcomes for row in o.durations), key=lambda r: -r[1])
    lines = ["", f"Slowest test durations (top {count})", SEP2]
    lines += [f"{seconds:<10.3f}s {name}" for name, seconds in rows[:count]]
    modules = sorted(outcomes, key=lambda o: -o.seconds)[:15]
    lines += ["", "Slowest modules (wall seconds in their own process)", SEP2]
    lines += [f"{o.seconds:<10.3f}s {o.module}" for o in modules]
    return lines + [""]


@dataclass
class Job:
    """A whole other suite run beside the batch: its command, its output, its exit code."""
    name: str
    command: str
    done: str = ""              # a regex its LAST non-blank line must match to count
    env: dict | None = None     # None: this process's own environment
    code: int = 0
    output: str = ""
    seconds: float = 0.0


def run_job(job: Job, env: dict | None = None) -> Job:
    env = job.env if job.env is not None else env
    started = time.monotonic()
    with tempfile.TemporaryFile() as out:
        job.code = subprocess.run(job.command, shell=True, cwd=ROOT, stdout=out,
                                  stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                  env=plain(env)).returncode
        out.seek(0)
        job.output = out.read().decode("utf-8", errors="replace")
    job.seconds = time.monotonic() - started
    return job


def job_failure(job: Job) -> str:
    """Why a job does not count, or "". An exit status of 0 is not enough: a suite that
    ends early with 0 has not run, so it must also have printed its own completion line."""
    if job.code:
        return f"{job.name}: exited {job.code} (`{job.command}`)"
    lines = [line for line in job.output.splitlines() if line.strip()]
    if not job.done or not lines or not re.search(job.done, lines[-1]):
        return (f"{job.name}: exited 0 but never printed its completion line "
                f"(/{job.done}/), so it did not finish")
    return ""


def parse_job(text: str) -> Job:
    name, sep, command = text.partition("=")
    if not sep or not name.strip() or not command.strip():
        raise argparse.ArgumentTypeError(f"a job is NAME=COMMAND, got {text!r}")
    return Job(name=name.strip(), command=command.strip())


def run(modules: list[str], workers: int, serial: dict[str, str] | None = None,
        durations: int | None = None, out=None, env: dict | None = None,
        jobs: list[Job] | None = None) -> int:
    out = out or sys.stderr
    started = time.monotonic()

    def show(outcome: Outcome):
        out.write(outcome.output)
        out.flush()

    with ThreadPoolExecutor(max_workers=max(1, len(jobs or []))) as beside:
        running = [beside.submit(run_job, job, env) for job in jobs or []]
        outcomes = schedule(modules, SERIAL if serial is None else serial, workers, env, show)
        out.write(summary(outcomes, time.monotonic() - started, durations))
        out.flush()
        finished = [future.result() for future in running]
    failed = []
    for job in finished:
        out.write(job.output)
        why = job_failure(job)
        if why:
            failed.append(job)
            out.write(why + "\n")
        out.flush()
    if finished:
        out.write("".join(f"{job.name}: {job.seconds:.1f}s, exit {job.code}\n" for job in finished))
        out.write(f"all suites: {time.monotonic() - started:.1f}s wall\n")
    passed = all(o.ok for o in outcomes) and not failed
    return 0 if passed else 1


# A red run's failures, once more (c-526, `keel/deploy.py`): `--rerun <log>` reads what a
# full run printed and runs ONLY what it names as failed, each test id in a child of its own
# (a child loads a dotted name, a test as well as a module) and each failed job again. It
# exits 0 only when every one of them passes; a log that names nothing it can rerun, or a
# fence failure (which no single test owns), is a failure, never a pass.

FAILED_LINE = re.compile(r"^(?:FAIL|ERROR): (.+)$", re.MULTILINE)


def failed_ids(text: str) -> list[str] | None:
    """The dotted ids a run's log names as failed, or None when one cannot be rerun alone."""
    ids = []
    # Only the batch's own blocks: the jobs' output (a job's unittest has FAIL lines of its
    # own) is printed after the batch's `Ran N tests` line, and a job reruns whole.
    batch = re.split(r"^Ran \d+ tests? in ", text, maxsplit=1, flags=re.MULTILINE)[0]
    for desc in FAILED_LINE.findall(batch):
        desc = desc.strip()
        if desc == FENCE_LINE:
            return None
        found = re.search(r"\(([\w.]+)\)$", desc)
        name = found.group(1) if found else desc
        if not re.fullmatch(r"[\w.]+", name) or name.startswith("unittest."):
            return None
        ids.append(name)
    return list(dict.fromkeys(ids))


def failed_jobs(text: str, jobs: list[Job]) -> list[Job]:
    return [job for job in jobs
            if re.search(rf"^{re.escape(job.name)}: (exited \d+ \(|exited 0 but never printed)",
                         text, re.MULTILINE)]


def rerun(log: Path, workers: int, jobs: list[Job], out=None, env: dict | None = None) -> int:
    out = out or sys.stderr
    try:
        text = log.read_text(errors="replace")
    except OSError as error:
        out.write(f"rerun: cannot read {log}: {error}\n")
        return 1
    ids = failed_ids(text)
    if ids is None:
        out.write("rerun: the log names a failure no single test owns (the fence, or a module "
                  "that did not load); nothing is rerun, and that is not a pass\n")
        return 1
    again = failed_jobs(text, jobs)
    if not ids and not again:
        out.write("rerun: the log names no failed test and no failed job; nothing to rerun, "
                  "and that is not a pass\n")
        return 1
    out.write(f"rerun: {len(ids)} test(s) and {len(again)} job(s) once more: "
              f"{', '.join(ids + [job.name for job in again])}\n")
    return run(ids, workers, jobs=again, out=out, env=env)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m tests.parallel")
    parser.add_argument("modules", nargs="*", help="dotted test modules; none means all")
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--durations", type=int, default=None)
    parser.add_argument("--job", type=parse_job, action="append", default=[],
                        metavar="NAME=COMMAND", help="another suite, run beside the batch")
    parser.add_argument("--done", type=parse_job, action="append", default=[],
                        metavar="NAME=REGEX",
                        help="the line a job's output must end with; every job needs one")
    parser.add_argument("--core", action="store_true",
                        help="the core modules (tests/core.txt) rather than every one")
    parser.add_argument("--rerun", type=Path, default=None, metavar="LOG",
                        help="run only what a red run's LOG names as failed, once")
    parser.add_argument("--child", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--result", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        return child(args.child, Path(args.result))
    if args.core and args.modules:
        parser.error("--core names its own modules; give modules or --core, not both")
    if args.core:
        from tests import suites
        modules = suites.core_modules()
    else:
        modules = args.modules or all_modules()
    # The jobs get the caller's environment, not this process's fenced one: each is a suite
    # the Makefile ran with it, and each fences itself (the adapters suite's
    # `suitefence.py`, the voice selftest's own scratch home).
    done = {entry.name: entry.command for entry in args.done}
    for job in args.job:
        if job.name not in done:
            parser.error(f"job {job.name!r} has no --done {job.name}=REGEX, and a job that "
                         f"cannot say it finished cannot count as passing")
        job.done = done[job.name]
    from tests import fence
    for job in args.job:
        job.env = dict(fence.caller_env) or None
    if args.rerun is not None:
        return rerun(args.rerun, workers_for(args.workers), args.job)
    code = run(modules, workers_for(args.workers), durations=args.durations, jobs=args.job)
    if args.core or not args.modules:
        # The core suite or the whole discovery, recorded for the review stamp (c-544).
        from keel.review import testrun
        if args.core:
            testrun.record(ROOT, testrun.CORE, "make test-core", code, modules=len(modules))
        else:
            testrun.record(ROOT, testrun.FULL, "make test-all", code, voice=voice_passed(args.job))
    return code


def voice_passed(jobs: list[Job]) -> bool:
    """The voice job finished green and did not skip (its skip note exits 0 too)."""
    from keel import merging
    voice = next((job for job in jobs if job.name == "voice"), None)
    return (voice is not None and not job_failure(voice)
            and not merging.VOICE_SKIP_LINE.search(voice.output))


if __name__ == "__main__":
    sys.exit(main())
