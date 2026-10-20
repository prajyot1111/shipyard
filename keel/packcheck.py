"""`keel pack check <dir>` (c-735): run a pack's own suite and require the conformance
contracts its capabilities call for.

A pack that claims a code host (`[capabilities] codehost`) must hold `HostContract` (its
layer, against a world its stand-in serves) and `VerbsContract` (its executables over a
card's whole life); one that claims review requests (`reviews`) `ReviewsContract` too (a
review card's whole life); a pack with a guard (`[guard]`) must hold `GuardContract`. A pack's `tests/test_conformance.py` subclasses each
(`keel/packkit/conformance.py`). The suite runs in a process of its own, as the adapters job
runs it (`tests/packsuites.py`), with no bytecode written, and the check says in one line
whether it passed, how many tests ran, and which contract it holds or lacks.

It is what a connection draft is done by: `keel new pack <name> --kit` starts a pack on the
kit, and the draft is done when this is green (`keel/packdraft.py`).
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from keel import packs

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ("HostContract", "GuardContract", "VerbsContract", "ReviewsContract")
SECONDS = 1800


def needed(pack: packs.Pack) -> list[str]:
    """The contracts this pack's claims call for, in `CONTRACTS` order."""
    need = set()
    if "codehost" in pack.capabilities:
        need |= {"HostContract", "VerbsContract"}
    if "reviews" in pack.capabilities:
        need.add("ReviewsContract")
    if pack.guard_tools:
        need.add("GuardContract")
    return [name for name in CONTRACTS if name in need]


def check(folder) -> dict:
    """`{ok, ran, failed, contracts, missing, said}` for the pack in `folder`."""
    folder = Path(folder).resolve()
    try:
        pack = packs.load(folder)
    except packs.PackError as error:
        return verdict(folder.name, False, 0, 0, [], [], f"it does not load: {error}")
    suite = folder / "tests"
    if not suite.is_dir():
        return verdict(pack.name, False, 0, 0, [], needed(pack), "it has no suite (tests/)")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(ROOT)}
    try:
        done = subprocess.run([sys.executable, "-m", "keel.packcheck", "--suite", str(suite)], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=SECONDS)
    except subprocess.TimeoutExpired:
        return verdict(pack.name, False, 0, 0, [], [], f"its suite gave no answer in {SECONDS:g} seconds")
    try:
        ran = json.loads(done.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        why = (done.stderr.strip().splitlines() or ["it printed nothing"])[-1]
        return verdict(pack.name, False, 0, 0, [], needed(pack), f"its suite did not run: {why}")
    missing = [name for name in needed(pack) if name not in ran["contracts"]]
    failed = ran["failed"]
    said = done.stderr.strip() if failed else ""
    return verdict(pack.name, not failed and not missing and ran["ran"] > 0, ran["ran"], failed, ran["contracts"],
                   missing, said)


def verdict(name: str, ok: bool, ran: int, failed: int, contracts: list, missing: list, said: str) -> dict:
    if missing:
        said = (f"{said}\n" if said else "") + (f"it must hold {', '.join(missing)} for what it claims: subclass "
                                                f"{'each' if len(missing) > 1 else 'it'} in tests/test_conformance.py "
                                                f"(keel/packkit/conformance.py)")
    return {"name": name, "ok": ok, "ran": ran, "failed": failed, "contracts": contracts, "missing": missing,
            "said": said}


def line(found: dict) -> str:
    held = ", ".join(found["contracts"]) or "none needed"
    tests = f"{found['ran']} test{'s' if found['ran'] != 1 else ''}"
    if found["ok"]:
        return f"keel pack check: {found['name']} passes ({tests}; contracts held: {held})"
    failing = f", {found['failed']} failing" if found["failed"] else ""
    lacking = f"; lacks {', '.join(found['missing'])}" if found["missing"] else ""
    return f"keel pack check: {found['name']} does not pass ({tests}{failing}{lacking})"


# ----- in the suite's own process -----

def contracts_of(suite) -> set[str]:
    found = set()
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            found |= contracts_of(test)
        else:
            found |= {base.__name__ for base in type(test).__mro__ if base.__name__ in CONTRACTS
                      and base.__module__.startswith("keel.packkit.")}
    return found


def run_suite(folder: Path) -> dict:
    """Discover and run a pack's suite as `tests/packsuites.py` does; the counts on stdout."""
    loaded = unittest.defaultTestLoader.discover(str(folder), top_level_dir=str(folder))
    held = sorted(contracts_of(loaded), key=CONTRACTS.index)    # read first: a run lets each test go
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(loaded)
    return {"ran": result.testsRun, "failed": len(result.failures) + len(result.errors), "contracts": held}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--suite"] and len(argv) == 2:
        print(json.dumps(run_suite(Path(argv[1]))))
        return 0
    if len(argv) != 1:
        print("usage: keel pack check <pack folder>", file=sys.stderr)
        return 2
    found = check(argv[0])
    if found["said"] and not found["ok"]:
        print(found["said"], file=sys.stderr)
    print(line(found))
    return 0 if found["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
