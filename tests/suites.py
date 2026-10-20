"""Which test modules are core and which are extended (c-646): one list, `tests/core.txt`.

The core suite is the modules that guard Keel's core promises (the board's rules and gates,
what the drain starts and refuses, the house fence, relays, the landing, the deploy, and the
suite's own guards). `make test` runs it on every change, with the extended modules the
change can reach (`tests/selector.py --core`); `make test-core` runs it alone. Every other
`tests/test_*.py` is extended: it runs when its area changes, and in `make test-all`.

Membership is the list and nothing else, so a module is in exactly one place by
construction: named in `core.txt`, or extended by default. `problems` says what is wrong
with the list itself (a name that is no module, a name twice), and `tests/test_suites.py`
fails on any of it.
"""

from pathlib import Path

from tests import parallel

HERE = Path(__file__).resolve().parent
CORE_LIST = HERE / "core.txt"


def listed(path: Path = CORE_LIST) -> list[str]:
    """The names `core.txt` gives, in its order, comments and blank lines dropped."""
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        name = line.split("#", 1)[0].strip()
        if name:
            names.append(name)
    return names


def core_modules(root: Path = parallel.ROOT) -> list[str]:
    """The core modules that exist, in discovery order."""
    known = set(parallel.all_modules(root))
    return sorted(set(listed(root / "tests" / CORE_LIST.name)) & known)


def extended_modules(root: Path = parallel.ROOT) -> list[str]:
    """Every test module the core list does not name."""
    core = set(listed(root / "tests" / CORE_LIST.name))
    return [name for name in parallel.all_modules(root) if name not in core]


def problems(root: Path = parallel.ROOT) -> list[str]:
    """What is wrong with the list: a name that is not a test module, or one named twice."""
    names = listed(root / "tests" / CORE_LIST.name)
    known = set(parallel.all_modules(root))
    found = [f"{name}: no tests/{name.split('.')[-1]}.py" for name in names if name not in known]
    found += [f"{name}: named {names.count(name)} times"
              for name in sorted(set(names)) if names.count(name) > 1]
    return found
