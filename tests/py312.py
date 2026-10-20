"""Every Keel module imports under Python 3.12: the `py312` job of `make test` (J-3).

The box runs Keel on its own /usr/bin/python3, which is 3.12.3; the Mac runs 3.14. 3.14
evaluates annotations only when something reads them (PEP 649), so a module that names a
class in an annotation before the class exists imports on the Mac and raises NameError on
the box, at import, which takes down whichever role imported it. 3.12 evaluates every
annotation when the `def` runs, so importing each module under it is the check.

`python3 -m tests.py312` imports every module under `keel/` in a `python3.12` child,
compiles every Python script under `bin/`, and resolves each `keel` name a script imports. Its last line is the completion line the runner reads (`DONE`): `py312: ok, ...`,
or `py312: skipped, ...` with a note when the machine has no `python3.12` (the Mac gets
Homebrew's; the box has it as /usr/bin/python3 and /usr/bin/python3.12).

Run as `python3 -m tests.py312`, the `tests` package is imported first, so the fence scrubs
the environment and moves HOME before the child starts: an import that reads `~` reads the
throwaway one. The child runs this same file under 3.12 with `--child`, stdlib only.
"""

import ast
import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DONE = r"^py312: (ok|skipped)"
WANT = (3, 12)
TIMEOUT = 300


# ----- the parent: find the interpreter, run the child, say the verdict -----

def interpreter() -> str | None:
    return shutil.which("python3.12")


def check(root: Path, python: str | None) -> tuple[int, list[str]]:
    """(exit code, lines to print): one line per failure, then the completion line."""
    if python is None:
        return 0, ["py312: skipped, no python3.12 on PATH (the box runs Keel on "
                   "/usr/bin/python3, which is 3.12; brew install python@3.12 on a Mac)"]
    done = subprocess.run([python, "-I", str(Path(__file__).resolve()), "--child", str(root)],
                          capture_output=True, text=True, timeout=TIMEOUT,
                          stdin=subprocess.DEVNULL, cwd=root)
    try:
        report = json.loads(done.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return 1, [f"py312: FAILED, the {python} child said nothing readable "
                   f"(exit {done.returncode}): {(done.stdout + done.stderr).strip()[-2000:]}"]
    return verdict(report)


def verdict(report: dict) -> tuple[int, list[str]]:
    failures, modules, scripts = report["failures"], report["modules"], report["scripts"]
    counted = (f"{modules} module{'s' if modules != 1 else ''} and "
               f"{scripts} script{'s' if scripts != 1 else ''}")
    if failures:
        return 1, failures + [f"py312: FAILED, {len(failures)} of {counted} do not import "
                              f"under Python {report['version']}"]
    return 0, [f"py312: ok, {counted} import under Python {report['version']}"]


def main() -> int:
    import tests  # noqa: F401  the fence, before the child inherits this environment
    code, lines = check(ROOT, interpreter())
    print("\n".join(lines), flush=True)
    return code


# ----- the child, under 3.12: import, compile, resolve -----

def modules_of(root: Path) -> list[str]:
    """Every module under `keel/`, a package's too (`keel.review.findings`)."""
    return sorted(".".join(("keel", *path.relative_to(root / "keel").with_suffix("").parts))
                  for path in (root / "keel").rglob("*.py")
                  if path.stem != "__init__" and "__pycache__" not in path.parts)


def python_scripts(root: Path) -> list[Path]:
    """The `bin/` scripts that are Python: the box runs every one of them under 3.12."""
    found = []
    for path in sorted((root / "bin").iterdir()):
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        first = text.splitlines()[0] if text else ""
        if first.startswith("#!") and "python" in first:
            found.append(path)
    return found


def keel_imports(tree: ast.AST) -> list[tuple[str, list[str]]]:
    """(module, names) for every `keel` import anywhere in a script."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module \
                and (node.module == "keel" or node.module.startswith("keel.")):
            found.append((node.module, [alias.name for alias in node.names]))
        elif isinstance(node, ast.Import):
            found += [(alias.name, []) for alias in node.names
                      if alias.name == "keel" or alias.name.startswith("keel.")]
    return found


def failure(where: str, error: BaseException) -> str:
    return f"{where}: {type(error).__name__}: {error}"


def check_module(name: str) -> str | None:
    try:
        importlib.import_module(name)
    except BaseException as error:     # SystemExit and friends at import are failures too
        return failure(name, error)
    return None


def check_script(path: Path, root: Path) -> list[str]:
    where = str(path.relative_to(root))
    try:
        tree = compile(path.read_text(), str(path), "exec", ast.PyCF_ONLY_AST)
    except SyntaxError as error:
        return [failure(where, error)]
    problems = []
    for module, names in keel_imports(tree):
        try:
            loaded = importlib.import_module(module)
        except BaseException as error:
            problems.append(failure(f"{where} ({module})", error))
            continue
        for name in names:
            if name != "*" and not hasattr(loaded, name):
                try:
                    importlib.import_module(f"{module}.{name}")
                except BaseException:
                    problems.append(f"{where}: {module} has no {name}")
    return problems


def child(root: Path) -> int:
    sys.path.insert(0, str(root))
    failures = []
    if sys.version_info[:2] != WANT:
        failures.append(f"the child is Python {sys.version.split()[0]}, not "
                        f"{'.'.join(map(str, WANT))}")
    modules = modules_of(root)
    failures += [problem for problem in map(check_module, modules) if problem]
    scripts = python_scripts(root)
    for path in scripts:
        failures += check_script(path, root)
    print(json.dumps({"failures": failures, "modules": len(modules), "scripts": len(scripts),
                      "version": sys.version.split()[0]}), flush=True)
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--child"]:
        sys.exit(child(Path(sys.argv[2])))
    sys.exit(main())
