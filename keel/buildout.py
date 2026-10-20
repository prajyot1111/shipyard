"""Build output a house never commits (c-734, point 13; docs/atlas/89-onboarding.md, "The layout").

The box test's house ran a Python suite, then `git add`ed its `__pycache__/*.pyc` and took
them out in a second commit. A rule in the brief would be forgotten on the day it matters, so
it is git's own: a copy the install made (`keel/repolayout.py`) carries the caches and
dependency folders of the common toolchains in its `info/exclude`, which every worktree of the
copy shares, so `git add -A` or `git add .` leaves them out and naming one asks for `-f`. The
repo's own `.gitignore` is the team's and is never touched; a folder the user attached is the
user's own checkout and is left alone. Written at the copy (`reposetup`) and reconciled at
every card cut (`adapters.worktree`), as the push fence is, so a copy made before has it too.
Only what is never source is listed: a cache, a dependency tree, a desktop's own file; a
pattern the copy already tracks paths under is left out (r1.F11).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

BEGIN = "# shipyard: build output a house never commits (c-734)"
END = "# shipyard: end"
PATTERNS = ("__pycache__/", "*.py[cod]", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/",
            "node_modules/", ".DS_Store")
# Each pattern as a pathspec `git ls-files` reads: a pattern the copy already tracks paths
# under is left out (r1.F11: a repo that vendors node_modules on purpose keeps adding it).
TRACKED = {"__pycache__/": ":(glob)**/__pycache__/**", "*.py[cod]": ":(glob)**/*.py[cod]",
           ".pytest_cache/": ":(glob)**/.pytest_cache/**", ".mypy_cache/": ":(glob)**/.mypy_cache/**",
           ".ruff_cache/": ":(glob)**/.ruff_cache/**", "node_modules/": ":(glob)**/node_modules/**",
           ".DS_Store": ":(glob)**/.DS_Store"}


def block_for(repo: Path) -> str | None:
    """The block for this copy: every pattern it tracks nothing under. None when git cannot say."""
    keep = []
    for pattern in PATTERNS:
        try:
            done = subprocess.run(["git", "-C", str(repo), "ls-files", "--", TRACKED[pattern]],
                                  capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        if done.returncode != 0:
            return None
        if not done.stdout.strip():
            keep.append(pattern)
    return "\n".join((BEGIN, *keep, END)) + "\n"


def reconcile(cfg, space_name: str | None, key: str | None) -> bool:
    """`ensure` for a repo the install copied into its layout; nothing for any other."""
    from keel import repofile    # noqa: PLC0415 - the layout's reader, light
    space = (getattr(cfg, "spaces", None) or {}).get(space_name or "")
    first = str(key or "").split(",")[0].strip()
    if space is None or first not in space.repos or repofile.tier_of(cfg, space_name, first) is None:
        return False
    return ensure(Path(space.repos[first]))


def exclude_file(repo: Path) -> Path | None:
    """The copy's `info/exclude` (in its common git dir, shared by every worktree), or None."""
    try:
        done = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0 or not done.stdout.strip():
        return None
    common = Path(done.stdout.strip())
    return (common if common.is_absolute() else Path(repo) / common) / "info" / "exclude"


def ensure(repo: Path) -> bool:
    """The block in the copy's `info/exclude`, once, replacing an older one; True when written.
    Never raises: a copy git cannot read keeps what it has."""
    path, block = exclude_file(repo), block_for(repo)
    if path is None or block is None:
        return False
    return put_block(path, BEGIN, END, block)


def put_block(path: Path, begin: str, end: str, block: str) -> bool:
    """`block` (its `begin` line to its `end` line) in the exclude file `path`, once, replacing
    an older one; an empty `block` takes an older one out. Every other line is kept. True when
    written, and never raises (`keel/packclones.py` writes its own block with this, c-740)."""
    try:
        text = path.read_text() if path.exists() else ""
    except OSError:
        return False
    held = begin in text and end in text
    if (block and block in text) or not (block or held):
        return False
    if held:
        head, _, rest = text.partition(begin)
        text = head + rest.partition(end)[2].lstrip("\n")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + ("" if not text or text.endswith("\n") else "\n") + block)
    except OSError:
        return False
    return True
