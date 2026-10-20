"""The git questions the pipeline asks of a house's worktree, each answered or None.

A question git cannot answer (no repo, no such ref, a timeout) is None, and the callers
treat None as "cannot tell", which never refuses: a gate that fires on a broken git would
hold a house for Keel's fault rather than its own.

The base is a branch name (`main`, or a work card's `options.base`). Its current head is
`origin/<base>` when the worktree has that ref (fetched first where a remote exists), else
the local branch: a personal repo with no remote is its own origin.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from keel.config import DEFAULT_REMOTE

GIT_SECONDS = 20
FETCH_SECONDS = 60


def git(cwd, *args, timeout: int = GIT_SECONDS) -> str | None:
    if not cwd:
        return None
    try:
        done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def head_of(cwd) -> str | None:
    """The worktree's HEAD, or None when it cannot be read (then nothing is refused)."""
    out = git(cwd, "rev-parse", "HEAD")
    return out.strip() or None if out else None


def root_of(cwd) -> Path | None:
    out = git(cwd, "rev-parse", "--show-toplevel")
    return Path(out.strip()) if out and out.strip() else None


def root_key(cwd) -> str | None:
    """The key a worktree's head is recorded under in a pass and the stamp: its root, resolved."""
    root = root_of(cwd)
    return str(root.resolve()) if root else None


def repo_name(cwd) -> str:
    """The repo a worktree belongs to: the directory holding its common `.git`."""
    out = git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if out and out.strip():
        common = Path(out.strip())
        return (common.parent if common.name == ".git" else common).name.removesuffix(".git")
    return Path(str(cwd)).name


def main_branch(cwd) -> str | None:
    """The branch the repo's main checkout has out: the target a personal card merges to."""
    out = git(cwd, "worktree", "list", "--porcelain") or ""
    for line in out.splitlines():
        if line.startswith("branch "):
            return line.split(" ", 1)[1].removeprefix("refs/heads/")
        if not line.strip():
            break
    return None


def resolves(cwd, ref: str) -> bool:
    return git(cwd, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") is not None


def fetch_base(cwd, base: str, remote: str | None = None) -> None:
    """Bring `<remote>/<base>` up to date where the clone has that remote; a failure is
    ignored, and the last fetched head is what is checked. `remote` is the space's
    (`config.remote_of`, c-665), handed in by a caller that has the card or the space;
    `origin` when it is handed none."""
    remote = remote or DEFAULT_REMOTE
    if git(cwd, "remote", "get-url", remote) is not None:
        git(cwd, "fetch", "-q", remote, base, timeout=FETCH_SECONDS)


def remote_flag(remote: str | None) -> str:
    """` --remote <name>` for `keel-review prep`, as the brief and a refusal print it: said
    only where the space's remote is not the default, so every other text is unchanged."""
    return f" --remote {remote}" if remote and remote != DEFAULT_REMOTE else ""


def base_ref(cwd, base: str | None, remote: str | None = None) -> str | None:
    """The ref that is the base's current head: `<remote>/<base>`, else `<base>`, else None."""
    if not base:
        return None
    for ref in (f"{remote or DEFAULT_REMOTE}/{base}", base):
        if resolves(cwd, ref):
            return ref
    return None


def contains(cwd, ref: str) -> bool | None:
    """True when HEAD contains `ref`; None when git cannot say."""
    try:
        done = subprocess.run(["git", "-C", str(cwd), "merge-base", "--is-ancestor", ref, "HEAD"],
                              capture_output=True, timeout=GIT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    return {0: True, 1: False}.get(done.returncode)


def diff(cwd, ref: str) -> str:
    """The branch's change against the base: what a reviewer reads."""
    return git(cwd, "diff", f"{ref}...HEAD") or ""


def patch_id(cwd, ref: str | None) -> str | None:
    """A fingerprint of the branch's change that a clean rebase does not move
    (`git patch-id --stable`): the same change on a newer base is the same review."""
    if not ref:
        return None
    text = diff(cwd, ref)
    if not text.strip():
        return None
    try:
        done = subprocess.run(["git", "-C", str(cwd), "patch-id", "--stable"], input=text,
                              capture_output=True, text=True, timeout=GIT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    ids = sorted(line.split()[0] for line in done.stdout.splitlines() if line.strip())
    return ",".join(ids) or None
