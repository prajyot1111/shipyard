"""What a pack on the kit shares in its requirement checks (`ready`) and its Logins rows.

A pack's own module (the GitHub pack's `gh_ready.py`, named by `HostConfig.ready`) holds its
checks: `NAMES` in the order a person meets them, `CHECKS` by name, `rows()` and
`login_rows()`, each check a row `{name, ok, why, fix}` with the SPECIFIC sentences (which
account, which repo, which address). The kit's `ready` and `logins` verbs print them. This
module is what every such pack writes the same way: the row, the space's repos as the
engine hands them (`KEEL_SPACE_REPOS`, the paths joined by the path separator), which of
them live on the host, and the one clock a check keeps inside the engine's ten seconds.

A pack never installs anything and never signs anyone in: a fix is text to copy and run.
"""

import os
import time
from pathlib import Path

from keel.packkit import card as gc

BUDGET = 8.0      # seconds for one requirement: the engine stops a check at ten
CALL_SECONDS = 4  # one call's clock inside it


def row(name: str, ok: bool, why: str = "", fix: str = "") -> dict:
    return {"name": name, "ok": ok, "why": why, "fix": fix}


def repos() -> list[Path]:
    named = os.environ.get("KEEL_SPACE_REPOS") or ""
    return [Path(part) for part in named.split(os.pathsep) if part.strip()]


def on_host(paths: list[Path] | None = None) -> tuple[list[tuple[Path, object]], list[tuple[Path, str]]]:
    """The space's repos as (path, Repo) for those on the host, and (path, why) for the rest."""
    on, off = [], []
    for path in repos() if paths is None else paths:
        repo, why = gc.clone_repo(path)
        (on if repo else off).append((path, repo or why))
    return on, off


def clock(budget: float = BUDGET, call: float = CALL_SECONDS):
    """`(until, left)`: when the budget ends, and what one call may have of what is left
    (never more than `call`, never under a second)."""
    until = time.monotonic() + budget
    return until, lambda: max(1.0, min(call, until - time.monotonic()))
