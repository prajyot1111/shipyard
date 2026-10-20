"""Workspace trust for a house's cwd, in its space's `.claude.json`.

Claude Code 2.1.281 refuses `claude --bg` (a start AND a `--resume ... --bg`) in a
directory its config dir has not trusted: "Workspace not trusted. Run `claude` in <cwd>
once and accept the trust prompt, then retry." Nobody is there to accept a prompt for a
house, and every house cwd is new (a card dir, a worktree), so c-452 blocked on the box
the evening the box updated (2026-09-23). `claude -p` does not ask. So every start of a
background session records the trust itself, first, where Claude Code reads it:
`projects[<cwd>].hasTrustDialogAccepted` in the `.claude.json` that config dir's claude
reads (`file_of`), the same entry `talkerdirs.seed_claude_json` writes for the talker's run
dirs.

Which file that is depends on how the config dir is reached (c-601). claude reads
`$CLAUDE_CONFIG_DIR/.claude.json` when the variable is set, and `~/.claude.json` (in the
HOME, not in `~/.claude`) when it is not. Keel reaches the default dir `~/.claude` with the
variable UNSET (`harness.point_env`: the keychain login is keyed by it), so a space on the
default dir is trusted in `~/.claude.json`; writing `~/.claude/.claude.json` instead made
every house start there fail "Workspace not trusted" (the sandbox e2e, 2026-09-30).

The write goes through `keel/claudejson.py`: atomic, and never over a file that does not
parse (it holds the login). That refusal is `Untrusted`, which the launch turns into a
block reason rather than a start that is bound to fail.

`forget` takes the entry away when the directory is gone for good (a worktree reaped by
the merge, an errand's house retired), so the file does not grow by one entry per card
forever. It removes only a path under Keel's state dir: an entry anywhere else is his,
or another tool's, and Keel never added it. Trust inherits from a parent directory on
2.1.281 (tests/fixtures/harness/README.md), so trusting `state/` once would also have
done; the per-cwd entry is what the error message asks for, and what survives a version
that stops inheriting.
"""

from __future__ import annotations

from pathlib import Path

from keel import claudejson

ENTRY = {"allowedTools": [], "mcpServers": {}, "hasTrustDialogAccepted": True}
TRUSTED = "hasTrustDialogAccepted"


class Untrusted(OSError):
    """The trust entry could not be written, so the session is not started. An `OSError`,
    so every caller that already turns a failed start into a block or a note does so here."""


def spellings(cwd) -> list[str]:
    """The cwd as given and as resolved: `claude` keys a project by the directory it sees,
    and a symlink on the way (macOS `/tmp`, a linked state dir) would miss the entry."""
    given = Path(cwd).expanduser()
    names = [str(given), str(given.resolve())]
    return list(dict.fromkeys(names))


def projects_of(path: Path, data: dict) -> dict:
    projects = data.setdefault("projects", {})
    if not isinstance(projects, dict):
        raise claudejson.Unreadable(f"{path}: `projects` is not an object")
    return projects


def file_of(config_dir) -> Path:
    """The `.claude.json` claude reads for `config_dir`: `~/.claude.json` for the default
    dir (reached with CLAUDE_CONFIG_DIR unset, `harness.is_default_config_dir`), else
    `<config_dir>/.claude.json`. HOME is read at the call, not at import."""
    home = Path.home()
    given = Path(config_dir).expanduser()
    if given.resolve() == (home / ".claude").resolve():
        return home / claudejson.NAME
    return given / claudejson.NAME


def grant(config_dir, cwd) -> bool:
    """Trust `cwd` in the `.claude.json` claude reads for `config_dir` (`file_of`), merging
    with any entry it already has. True when the file was written, False when the cwd was
    already trusted. `Untrusted` when the file does not parse; nothing is written then."""
    path = file_of(config_dir)
    try:
        return rewrite(path, lambda data: trust_in(path, data, cwd))
    except claudejson.Unreadable as error:
        raise Untrusted(f"{path} does not parse, so {cwd} could not be trusted and the "
                        f"house was not started (Shipyard never writes over it: it holds the "
                        f"login). Repair the file, then unblock the card: {error}") from None


def rewrite(path: Path, change) -> bool:
    """Apply `change` (True when it changed the dict) to the file and write it, atomically.

    The file is claude's own, and live claude processes write it too (c-601 review). So the
    change is worked out on one read, and when there is something to write the file is READ
    AGAIN and the change applied to that, just before the write, which goes through
    `claudejson.write` (a temp file renamed over it): the window in which a claude's write
    can be lost is the one between that second read and the rename, not the whole call."""
    if not change(claudejson.read(path)):
        return False
    data = claudejson.read(path)
    if not change(data):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    claudejson.write(path, data)
    return True


def trust_in(path: Path, data: dict, cwd) -> bool:
    projects = projects_of(path, data)
    changed = False
    for name in spellings(cwd):
        entry = projects.get(name)
        if isinstance(entry, dict) and entry.get(TRUSTED) is True:
            continue
        merged = dict(entry) if isinstance(entry, dict) else {}
        for key, value in ENTRY.items():
            merged.setdefault(key, value)
        merged[TRUSTED] = True
        projects[name] = merged
        changed = True
    return changed


def under(path: Path, root: Path) -> bool:
    """`path` strictly inside `root` (the root itself is not one of its houses)."""
    return path != root and path.is_relative_to(root)


def forget(config_dir, cwd, state_dir) -> bool:
    """Remove `cwd`'s trust entry when it lies under `state_dir`. True when the file was
    written. Never raises for a file that does not parse or cannot be read: whatever
    called this (a merge, an approve) already succeeded."""
    root = Path(state_dir).expanduser().resolve()
    if not under(Path(cwd).expanduser().resolve(), root):
        return False
    path = file_of(config_dir)

    def drop(data: dict) -> bool:
        projects = data.get("projects")
        if not isinstance(projects, dict):
            return False
        return bool([projects.pop(name) for name in spellings(cwd) if name in projects])
    try:
        return rewrite(path, drop)
    except (OSError, claudejson.Unreadable):
        return False
