"""The adapters job (c-689, c-726 r1.F4): every pack's own suite, one after another, each in a
process of its own (two packs may both have a `suitefence`); the first that fails stops the
job, and unittest's `OK` from the last is its completion line.

The tree's packs (`packs/<name>/tests`), and, when `KEEL_CONFIG` names an install's
`config.toml` outside this tree, the install's own packs too (`<install>/packs/<name>/tests`):
an owner's work pack left the tree for the install's packs repo, and its suite still runs at
every landing that reaches it and at every deploy, as `tests/installdrift.py` reads its
terms. Nothing is written into the install: no bytecode is cached.

Run as `python3 tests/packsuites.py` from the tree's root (the Makefile's `ADAPTERS_TESTS` and
`tests/selector.py`'s `ADAPTERS_COMMAND`). Standard library only, and nothing imported from
the tree, so it runs the same in a scratch tree.
"""

import os
import subprocess
import sys
from pathlib import Path


def install_packs(root: Path, named: str | None) -> Path | None:
    """`<install>/packs` when `named` is an install's `config.toml` outside `root` (the rule
    of `keel.packs.install_packs`), else None."""
    if not named:
        return None
    path = Path(named).expanduser().resolve()
    if path.name != "config.toml" or path.parent == root.resolve():
        return None
    return path.parent / "packs"


def suites(root: Path, named: str | None) -> list[Path]:
    found = sorted(path for path in root.glob("packs/*/tests") if path.is_dir())
    own = install_packs(root, named)
    if own is not None:
        found += sorted(path for path in own.glob("*/tests") if path.is_dir())
    return found


def main(root: Path) -> int:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    found = suites(root, os.environ.get("KEEL_CONFIG"))
    for suite in found:
        print(f"packsuites: {suite}", flush=True)
        done = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(suite), "-v"],
                              cwd=root, env=env)
        if done.returncode != 0:
            return done.returncode
    if not found:
        print("OK (no pack suites)")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path.cwd()))
