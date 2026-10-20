"""What a house's own test run was, recorded where the review stamp can read it (c-544).

`make test` (the core suite and what the change reaches, c-646) runs once per change, on the
merged tree where it lands (`keel/merging.py`). A house runs `make test-changed` before
review instead (`[house_tests]` in the install's `config.toml`), which is targeted, or every module when the
selector cannot tell. So that his gate can see which, every run of the selector
(`tests/selector.py`), `make test-core` and the whole `make test-all` (`tests/parallel.py`)
leave one record in the worktree's OWN git directory
(`git rev-parse --git-path keel-test-run.json`): per worktree, never committed, gone with
the worktree. The stamp hook (`keel/review/stamp.py`) copies it onto the stamp when it was
taken at the stamped head on a clean tree; any other record is not a run of that change.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from keel.review import repo

FILE = "keel-test-run.json"
TARGETED = "targeted"
CORE = "core"                    # `make test-core`: the core suite alone
CORE_REACHED = "core-reached"    # `make test`: the core suite and what the change reaches
FULL = "full"
NONE_SAID = "no test run was recorded at this head on a clean tree"


def path_of(root) -> Path | None:
    out = repo.git(root, "rev-parse", "--path-format=absolute", "--git-path", FILE)
    return Path(out.strip()) if out and out.strip() else None


def clean(root) -> bool:
    out = repo.git(root, "status", "--porcelain")
    return out is not None and not out.strip()


def record(root, kind: str, why: str, code: int, modules: int | None = None,
           voice: bool | None = None) -> None:
    """Write what ran at the worktree's HEAD. Never raises: a test run is never failed by
    the note it leaves about itself. `voice`: whether the voice selftest ran and passed (a
    full run's job says; a skip, with no venv, exits 0 too), None when nobody said."""
    try:
        path, head = path_of(root), repo.head_of(root)
        if path is None or head is None:
            return
        path.write_text(json.dumps({
            "head": head, "clean": clean(root), "kind": kind, "why": why, "exit": code,
            "modules": modules, "voice": voice,
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }, indent=2) + "\n")
    except OSError:
        return


def voice_of(root) -> bool | None:
    """What the record at the worktree's HEAD says of voice: how the selector, whose
    fallback runs `make test-all`, keeps what that run's own record said."""
    head = repo.head_of(root)
    return at_head(root, head).get("voice") if head else None


def at_head(root, head: str) -> dict:
    """The recorded run for `head` on a clean tree, or a `none` entry saying there was none."""
    path = path_of(root)
    try:
        found = json.loads(path.read_text()) if path else None
    except (OSError, ValueError):
        found = None
    if isinstance(found, dict) and found.get("head") == head and found.get("clean"):
        return found
    return {"kind": "none", "why": NONE_SAID}


def said(entry: dict | None) -> str:
    """One line for a person: which suite ran and how it ended."""
    if not entry or entry.get("kind") not in (TARGETED, CORE, CORE_REACHED, FULL):
        return NONE_SAID
    verdict = "green" if entry.get("exit") == 0 else f"red (exit {entry.get('exit')})"
    if entry["kind"] == FULL:
        return f"the full suite, {verdict}: {entry.get('why')}"
    if entry["kind"] == CORE:
        return f"the core suite alone, {entry.get('modules')} test module(s), {verdict}"
    if entry["kind"] == CORE_REACHED:
        return (f"the core suite and what the change reaches, {entry.get('modules')} test "
                f"module(s), {verdict}")
    return f"targeted, {entry.get('modules')} test module(s), {verdict}"


def worktrees(root) -> list[Path]:
    """Every worktree of the repo `root` is in, the main checkout first."""
    out = repo.git(root, "worktree", "list", "--porcelain") or ""
    return [Path(line.removeprefix("worktree ")) for line in out.splitlines()
            if line.startswith("worktree ")]


def full_green(root, head: str) -> dict | None:
    """A green `make test-all` with the voice selftest passing, recorded at `head` on a clean
    tree in any worktree of `root`'s repo: what `kb tested` needs before it records a tree
    as tested (c-646), since a narrow `make test` proves nothing about every module."""
    for tree in worktrees(root) or [Path(root)]:
        entry = at_head(tree, head)
        if entry.get("kind") == FULL and entry.get("exit") == 0 and entry.get("voice") is True:
            return dict(entry, worktree=str(tree))
    return None
