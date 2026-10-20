"""`make test-changed` and `make test`: the test modules a change can reach.

`make test-changed` runs only those: the quick loop a builder uses, and what a house runs
before review (c-544). `make test` (`--core`, c-646) runs the core suite (`tests/core.txt`,
`tests/suites.py`) with them and the Python 3.12 import check: what the landing runs on the
merged tree, with `BASE` the tree it lands on. Every module, voice included, is `make
test-all`: on demand, and at every deploy, which is the gate that runs every module before
main moves (`keel/deploy.py`). What ran is recorded for the review stamp
(`keel/review/testrun.py`).

The changed files are `git diff --name-only BASE...HEAD` plus what is uncommitted (staged,
unstaged and untracked). Each is placed by one rule, and the rule is printed beside it:

- **A Python file under `keel/`, `voice/`, `packs/`, `tests/`, or a Python script in
  `bin/`**: every test module that imports it, directly or through any chain of imports,
  from a static `ast` graph of those trees, plus `tests/test_<name>.py` by name; for
  `make test`, only the modules that import it themselves (a test module's whole chain),
  since the core suite runs anyway and through a chain nearly every module reaches every
  other. A change under `packs/` also runs the packs' own suites: each
  `packs/<name>/tests`, one after another, each in a process of its own (c-689); so does a
  change to the pack kit, `keel/packkit/` (c-735), which every pack on it runs on.
- **`app/**`**: the test modules that read app files, found by the paths they name.
- **`bin/<script>`**: the test modules that name the script.
- **`docs/**`, `etc/**`**: the guards (below), plus any test module naming the file.
- **`etc/shipyard.example.toml`**, the shipped config: `tests/test_config.py` and the test
  modules that name it (c-726 r1.F3; the tree tracks no `keel.toml`).
- **`tests/core.txt`**: `tests/test_suites.py`, which holds the list to the tree.
- **Anything else**: the test modules that name it by path or file name, if any.

The guards always run: the fence (`FenceCase`, one per child, as `tests/parallel.py`
does it), `tests/test_atlas.py`, and the drift grep (the Makefile's `drift`, a prerequisite
of the target). The voice selftest runs only when the change reaches it: `voice/**`, a
`bin/keel-voice*` script, a Python file that the voice package or `bin/keel-voice-selftest`
imports through any chain (the same graph), or the data it reads (`segments/voice/**`,
`segments/cloud-spend/**`, a pack's `hearing.json`).

FAIL-SAFE: a changed file no rule can place, and any change to the suite's own machinery
(`tests/__init__.py`, `tests/fence.py`, `tests/helpers.py`, `tests/boardleak.py`, the
runner, this file, `tests/suites.py`, the Makefile), runs every module (`make test-all`),
and says which file and why.
"""

import argparse
import ast
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from tests import py312, suites

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GRAPH_TREES = ("keel", "voice", "packs", "tests")
# Each pack's own suite, by convention (c-689): `packs/<name>/tests`.
ADAPTER_TESTS = "packs/*/tests"
# The pack kit (c-735): every pack on it runs on it, the install's own too, so a change to it
# owes the packs' suites whatever the import graph says.
KIT = "keel/packkit/"
SHIPPED_CONFIG = "etc/shipyard.example.toml"
# The suite's own machinery: a change here can change what every test means.
MACHINERY = {"tests/__init__.py", "tests/fence.py", "tests/helpers.py", "tests/boardleak.py",
             "tests/parallel.py", "tests/selector.py", "tests/suites.py", "Makefile"}
CORE_LIST = "tests/core.txt"
# What the voice selftest runs, and the data it reads by path: a change reaching any of them
# owes it (`Selector.voice_reason`).
VOICE_SELFTEST = "bin/keel-voice-selftest"
VOICE_DATA = ("segments/voice/", "segments/cloud-spend/")
GUARDS = ("tests.test_atlas",)
SKIP_DIRS = {"__pycache__", "node_modules", ".venv", ".venv-voice", "state"}


# ----- what changed -----

def git_lines(*args: str, root: Path = ROOT) -> list[str]:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"test-changed: git {' '.join(args)} failed: {done.stderr.strip()}")
    return [line for line in done.stdout.splitlines() if line.strip()]


def changed_files(base: str, root: Path = ROOT) -> list[str]:
    """Committed since the merge base with `base`, plus staged, unstaged and untracked."""
    names = set(git_lines("diff", "--name-only", f"{base}...HEAD", root=root))
    names |= set(git_lines("diff", "--name-only", "HEAD", root=root))
    names |= set(git_lines("ls-files", "-o", "--exclude-standard", root=root))
    return sorted(names)


# ----- the import graph -----

def is_python(path: Path) -> bool:
    if path.suffix == ".py":
        return True
    if path.suffix or not path.is_file():
        return False
    try:
        with open(path, "rb") as handle:
            first = handle.readline(200)
    except OSError:
        return False
    return first.startswith(b"#!") and b"python" in first


def python_files(root: Path) -> list[Path]:
    """Every Python file the graph covers: the four trees, and bin's Python scripts."""
    found = []
    for tree in GRAPH_TREES:
        for path in (root / tree).rglob("*"):
            if SKIP_DIRS.intersection(path.relative_to(root).parts):
                continue
            if path.is_file() and is_python(path):
                found.append(path)
    found += [path for path in sorted((root / "bin").glob("*")) if is_python(path)]
    return sorted(found)


def imported_names(tree: ast.AST) -> list[tuple[str, int, list[str]]]:
    """(module, relative level, names imported from it) for every import in the file,
    including those inside functions, and `importlib.import_module("x")` with a literal."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(alias.name, 0, []) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append((node.module or "", node.level, [a.name for a in node.names]))
        elif (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "import_module"
              and node.args and isinstance(node.args[0], ast.Constant)
              and isinstance(node.args[0].value, str)):
            found.append((node.args[0].value, 0, []))
    return found


def module_file(base: Path, dotted: str) -> list[Path]:
    """The file a dotted name is under `base`, with every package `__init__` on the way.
    Descent stops at the first plain module, so `keel.board.Board` is `keel/board.py`."""
    files, current = [], base
    for part in (part for part in dotted.split(".") if part):
        current = current / part
        if (current / "__init__.py").is_file():
            files.append(current / "__init__.py")
            continue
        if current.with_suffix(".py").is_file():
            files.append(current.with_suffix(".py"))
        break
    return files


def resolve(importer: Path, module: str, level: int, names: list[str],
            root: Path) -> set[Path]:
    """The files in this repo an import can mean. Searched where Keel's code puts itself on
    `sys.path`: the repo root (`keel`, `tests`), `voice/` (`harbor_voice`), and the
    importer's own directory and its parent (the work adapter's scripts and tests)."""
    if level:
        base = importer.parent
        for _ in range(level - 1):
            base = base.parent
        bases = [base]
    else:
        bases = [root, root / "voice", importer.parent, importer.parent.parent]
    found: set[Path] = set()
    for base in bases:
        if level == 0 and root not in (base, *base.parents):
            continue
        for name in names:                       # `from pkg import module`
            found.update(module_file(base, f"{module}.{name}" if module else name))
        found.update(module_file(base, module) if module else set())
        if found:
            break
    return {path for path in found if path != importer}


def import_graph(root: Path = ROOT) -> dict[Path, set[Path]]:
    """Each Python file to the repo files it imports."""
    graph = {}
    for path in python_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            tree = ast.Module(body=[], type_ignores=[])
        edges: set[Path] = set()
        for module, level, names in imported_names(tree):
            edges |= resolve(path, module, level, names, root)
        graph[path] = edges
    return graph


def dependents(graph: dict[Path, set[Path]], changed: Path, chain: bool = True) -> set[Path]:
    """Every file that imports `changed`, directly or (with `chain`) through a chain, and
    `changed`."""
    reverse: dict[Path, set[Path]] = {}
    for source, targets in graph.items():
        for target in targets:
            reverse.setdefault(target, set()).add(source)
    if not chain:
        return {changed} | reverse.get(changed, set())
    seen, todo = {changed}, [changed]
    while todo:
        for source in reverse.get(todo.pop(), ()):
            if source not in seen:
                seen.add(source)
                todo.append(source)
    return seen


# ----- what a test module names -----

def words(path: Path) -> set[str]:
    """The string constants and identifiers a test module contains."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return set()
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.add(node.value)
        elif isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.alias):
            found.add(node.name.rsplit(".", 1)[-1])
    return found


def names_file(said: set[str], rel: str) -> bool:
    """Does a test module name this file: its repo path inside a string, or its file name
    as a whole string (`ROOT / "app" / "ui.css"`)."""
    base = rel.rsplit("/", 1)[-1]
    return base in said or any(rel in text for text in said if len(text) >= len(rel))


# ----- the selection -----

@dataclass
class Selection:
    full: list[str] = field(default_factory=list)          # why the whole suite runs
    modules: dict[str, str] = field(default_factory=dict)  # dotted module -> why
    adapters: str = ""                                     # why the adapters suite runs
    voice: str = ""                                        # why the voice selftest runs
    core: bool = False                                     # `make test`: the core suite too
    placed: dict[str, str] = field(default_factory=dict)   # changed file -> its rule

    def add(self, module: str, why: str) -> None:
        self.modules.setdefault(module, why)


class Selector:
    """The graph and every test module's words, built once, then asked about each file."""

    def __init__(self, root: Path = ROOT):
        self.root = root
        self.graph = import_graph(root)
        self.tests = {path: words(path) for path in self.test_paths()}

    def test_paths(self) -> list[Path]:
        return sorted((self.root / "tests").glob("test*.py")) + sorted(
            self.root.glob(f"{ADAPTER_TESTS}/test*.py"))

    def dotted(self, path: Path) -> str:
        return ".".join(path.relative_to(self.root).with_suffix("").parts)

    def is_adapter_test(self, path: Path) -> bool:
        parts = path.relative_to(self.root).parts
        return len(parts) > 3 and (parts[0], parts[2]) == ("packs", "tests")

    def claim(self, selection: Selection, test: Path, why: str) -> None:
        if self.is_adapter_test(test):
            selection.adapters = selection.adapters or why
        else:
            selection.add(self.dotted(test), why)

    def naming(self, rel: str) -> list[Path]:
        return [test for test, said in self.tests.items() if names_file(said, rel)]

    def select(self, changed: list[str], core: bool = False) -> Selection:
        selection = Selection(core=core)
        for module in GUARDS:
            selection.add(module, "a guard, always run")
        if core:
            for module in suites.core_modules(self.root):
                selection.add(module, "core")
        for rel in changed:
            selection.placed[rel] = self.place(rel, selection)
        return selection

    def place(self, rel: str, selection: Selection) -> str:
        """Put one changed file's tests into `selection`; the rule it went by, or why the
        whole suite has to run."""
        path = self.root / rel
        head = rel.split("/", 1)[0]
        if rel in MACHINERY:
            selection.full.append(f"{rel}: the suite's own machinery")
            return "every module"
        if rel.endswith(".py") and head in GRAPH_TREES and not path.exists():
            selection.full.append(f"{rel}: deleted, so the graph cannot say who imported it")
            return "every module"
        selection.voice = selection.voice or self.voice_reason(rel, path)
        if head in ("packs", "adapters"):
            selection.adapters = selection.adapters or f"{rel} is a pack's"
        if rel.startswith(KIT):
            selection.adapters = selection.adapters or f"{rel} is the pack kit's"
        if head == "bin":
            graph = self.place_python(rel, path, selection) if path in self.graph else ""
            words = self.place_by_words(rel, selection, rule="the tests naming the script",
                                        placed_anyway=bool(selection.voice or graph))
            return ", ".join(part for part in (graph, words) if part)
        if path in self.graph or (rel.endswith(".py") and head in GRAPH_TREES):
            return self.place_python(rel, path, selection)
        if head == "app":
            return self.place_by_words(rel, selection, extra=lambda said: "app" in said,
                                       rule="the tests that read app files")
        if rel == SHIPPED_CONFIG:
            selection.add("tests.test_config", "the shipped example is the shipped config")
            return self.place_by_words(rel, selection,
                                       rule="test_config and the tests naming it",
                                       placed_anyway=True)
        if head in ("docs", "etc") or (head == "tests" and rel.endswith(".md")):
            self.place_by_words(rel, selection, rule="")
            return "the guards (the Atlas test and the drift grep), and tests naming it"
        if rel == CORE_LIST:
            selection.add("tests.test_suites", "the core list changed")
            return "test_suites, which holds the list to the tree"
        return self.place_by_words(rel, selection, rule="the tests naming it",
                                   placed_anyway=bool(selection.adapters or selection.voice))

    def voice_reason(self, rel: str, path: Path) -> str:
        """Why this file owes the voice selftest, or "" when it does not reach it."""
        if rel.split("/", 1)[0] == "voice" or rel.startswith("bin/keel-voice"):
            return f"{rel} changed"
        if rel.startswith(VOICE_DATA) or (rel.startswith("packs/")
                                          and rel.endswith("/hearing.json")):
            return f"{rel} is read by the voice selftest"
        if path not in self.graph:
            return ""
        voice = self.root / "voice"
        for user in sorted(dependents(self.graph, path) - {path}):
            if voice in user.parents or user == self.root / VOICE_SELFTEST:
                return f"{rel} is imported by {user.relative_to(self.root)}"
        return ""

    def place_python(self, rel: str, path: Path, selection: Selection) -> str:
        # `make test` (core) takes an extended module only when its own area changed: a file
        # it imports itself. Through a chain, nearly every module reaches nearly every other
        # (`tests/helpers.py` and the board's lazy imports join them), so the core suite
        # here, and the deploy, which runs every module (`make test-all`) before main moves,
        # are what cover the chain (c-646). A test module's own
        # chain (a case built on another module's case) is short and is followed whole.
        chain = not selection.core or rel.startswith("tests/")
        reached = dependents(self.graph, path, chain=chain)
        tests = [test for test in self.test_paths() if test in reached]
        by_name = self.root / "tests" / f"test_{path.stem}.py"
        if by_name.is_file() and by_name not in tests:
            tests.append(by_name)
        for test in tests:
            why = (f"{rel} is this module" if test == path
                   else f"named for {rel}" if test == by_name and test not in reached
                   else f"imports {rel}")
            self.claim(selection, test, why)
        # A test may read a module's source rather than import it (the voice package, which
        # the stdlib suite never imports, is read and copied by path).
        naming = [test for test in self.naming(rel) if test not in tests]
        for test in naming:
            self.claim(selection, test, f"names {rel}")
        how = "by the import graph" if chain else "importing it themselves"
        return f"{len(tests)} test module(s) {how}, {len(naming)} naming it"

    def place_by_words(self, rel: str, selection: Selection, rule: str, extra=None,
                       placed_anyway: bool = False) -> str:
        tests = [test for test, said in self.tests.items()
                 if names_file(said, rel) or (extra and extra(said))]
        for test in tests:
            self.claim(selection, test, f"names {rel}")
        if tests or placed_anyway or not rule:
            return f"{rule} ({len(tests)})" if rule else ""
        selection.full.append(f"{rel}: no rule places it and no test names it")
        return "every module"


# ----- running it -----
# A run that chose its modules says so on its own line; one that ran every module never
# does. `keel/merging.py` reads it (its NARROW): a chosen run proves no tree for the deploy.
SELECTED = "running {} test module(s):"


def report(changed: list[str], selection: Selection) -> str:
    target = "make test" if selection.core else "test-changed"
    lines = [f"{target}: {len(changed)} changed file(s)"]
    lines += [f"  {rel}  ->  {selection.placed.get(rel) or 'placed'}" for rel in changed]
    if selection.full:
        lines.append("running EVERY module (make test-all), because:")
        lines += [f"  {why}" for why in selection.full]
        return "\n".join(lines) + "\n"
    lines.append(SELECTED.format(len(selection.modules)))
    lines += [f"  {module}  ({why})" for module, why in sorted(selection.modules.items())]
    lines.append(f"  the packs' own suites  ({selection.adapters})" if selection.adapters
                 else "  not the packs' own suites: nothing reaches them")
    if selection.core:
        lines.append("  the Python 3.12 import check  (core)")
    lines.append(f"  the voice selftest  ({selection.voice})" if selection.voice
                 else VOICE_UNREACHED)
    return "\n".join(lines) + "\n"


def command(selection: Selection) -> list[str]:
    """What to run: every module (`make test-all`), or the runner over the chosen ones."""
    if selection.full:
        return ["make", "--no-print-directory", "test-all"]
    argv = [sys.executable, "-m", "tests.parallel", *sorted(selection.modules)]
    if selection.core:
        argv += ["--job", f"py312={PY312_COMMAND}", "--done", f"py312={PY312_DONE}"]
    if selection.adapters:
        argv += ["--job", f"adapters={ADAPTERS_COMMAND}", "--done", f"adapters={ADAPTERS_DONE}"]
    if selection.voice:
        argv += ["--job", f"voice={VOICE_COMMAND}", "--done", f"voice={VOICE_DONE}"]
    return argv


# Every pack's own suite, the tree's and the install's (`tests/packsuites.py`, c-726 r1.F4),
# one after another, each in its own process (two packs may both have a `suitefence`); the
# first that fails stops the job, and unittest's `OK` from the last is its completion line.
# The Makefile's `ADAPTERS_TESTS` is the same command.
ADAPTERS_COMMAND = "python3 tests/packsuites.py"
VOICE_COMMAND = "make --no-print-directory voice-test"
PY312_COMMAND = "python3 -m tests.py312"
# The Makefile's completion lines for the same three jobs (`tests/parallel.py`, `--done`).
ADAPTERS_DONE = r"^OK( \(.*\))?$"
VOICE_DONE = r"^(ok: |voice selftest: skipped)"
PY312_DONE = py312.DONE
# Said on its own line when nothing the change touched reaches the voice selftest.
# `keel/merging.py` reads it (its VOICE_UNREACHED): such a run proves no tree for the deploy,
# and the deploy refuses it.
VOICE_UNREACHED = "voice selftest: not run, nothing the change touched reaches it"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m tests.selector")
    parser.add_argument("--base", default="main")
    parser.add_argument("--core", action="store_true",
                        help="the core suite and the import check too (`make test`)")
    parser.add_argument("--dry-run", action="store_true", help="say what would run, run nothing")
    args = parser.parse_args(argv)
    changed = changed_files(args.base)
    selection = Selector().select(changed, core=args.core)
    sys.stdout.write(report(changed, selection))
    sys.stdout.flush()
    if args.dry_run:
        return 0
    from tests import fence                  # the full suite and the jobs get the caller's env
    code = subprocess.run(command(selection), cwd=ROOT, env=fence.caller_env or None).returncode
    record(selection, code)
    return code


def record(selection: Selection, code: int, root: Path = ROOT) -> None:
    """What ran, for the review stamp to show his gate (c-544, `keel/review/testrun.py`)."""
    from keel.review import testrun
    if selection.full:
        # `make test-all` recorded its own run first, voice included: keep what it said
        testrun.record(root, testrun.FULL, "; ".join(selection.full), code,
                       voice=testrun.voice_of(root))
    else:
        kind = testrun.CORE_REACHED if selection.core else testrun.TARGETED
        testrun.record(root, kind, f"{len(selection.modules)} test module(s)", code,
                       modules=len(selection.modules))


if __name__ == "__main__":
    sys.exit(main())
