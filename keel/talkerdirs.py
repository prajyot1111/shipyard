"""The talker's config dir and run dirs: the `.claude.json` seed, the memory link, and the
numbered run directories that rotate, prune and forget.

Split out of `keel/talker.py` (which re-exports every name here) when that module passed
600 lines. The functions take the talker's `Paths`; nothing here imports `keel.talker`.
Every `.claude.json` write goes through `keel/claudejson.py`, atomically.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from keel import claudejson, memoryroot

SEED_KEYS = ("hasCompletedOnboarding", "lastOnboardingVersion", "theme", "installMethod",
             "oauthAccount", "userID", "firstStartTime", "hasUsedRemoteControl", "autoUpdates",
             "remoteDialogSeen")   # a Mac-era seed; `start` asserts consent itself (`claudejson`)
KEEP_RUNS = 5                # numbered run dirs kept when pruning; older ones are removed


def project_slug(cwd: Path) -> str:
    """Claude Code's name for a project dir: the cwd with every `/` turned into `-`."""
    return str(cwd).replace("/", "-")


def seed_claude_json(source: Path | None, target: Path, cwd: Path) -> dict:
    """A fresh config dir's `.claude.json`: onboarding and account state copied from
    `source`, no `projects` map and no cached blobs, plus a trust entry for `cwd`
    (server mode refuses an untrusted directory). Returns the seeded dict."""
    data = json.loads(source.read_text()) if source and source.exists() else {}
    seeded = {key: data[key] for key in SEED_KEYS if key in data}
    seeded["projects"] = {str(cwd): {"allowedTools": [], "mcpServers": {},
                                     "hasTrustDialogAccepted": True}}
    if target.exists():
        current = claudejson.read(target)   # Unreadable propagates: never written over
        current.setdefault("projects", {}).update(seeded["projects"])
        for key, value in seeded.items():
            current.setdefault(key, value)
        seeded = current
    claudejson.write(target, seeded)
    return seeded


def link_memory(paths: Paths) -> Path:
    """Point the config dir's auto-memory path for the talker cwd at talker/memory/."""
    link = paths.memory_link
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        shutil.rmtree(link)
    link.symlink_to(paths.memory_src, target_is_directory=True)
    return link


def link_rules(paths: Paths) -> bool:
    """Point the config dir's CLAUDE.md at the talker's rulebook (`paths.rules_src`, c-722
    landing B); True when it points there now. Only a missing entry, a dangling link, or a
    link Keel made (to the install's rulebook or the shipped one) is replaced (r2.F8): a file,
    or a link someone pointed elsewhere on purpose, is theirs, and the caller says so
    (`rules_note`)."""
    link, source = paths.rules_link, paths.rules_src
    if source is None:
        return False
    if link.is_symlink():
        if link.exists() and Path(os.readlink(link)) not in managed_rules(paths):
            return False
    elif link.exists():
        return False
    link.parent.mkdir(parents=True, exist_ok=True)
    link.unlink(missing_ok=True)
    link.symlink_to(source)
    return True


def managed_rules(paths: Paths) -> set[Path]:
    """The rulebooks a link of Keel's may point at: the install's, and the shipped one."""
    return {paths.memory_src / memoryroot.RULEBOOK,
            paths.root / memoryroot.TEMPLATE[memoryroot.TALKER] / memoryroot.RULEBOOK}


def rules_note(paths: Paths) -> str:
    """What `link_rules` did, in one line, for `install` and every `start` (r2.F8)."""
    link, source = paths.rules_link, paths.rules_src
    if source is None:
        if link.is_file() and not link.is_symlink():
            return f"using {link}, the config dir's own; the install holds no rulebook yet"
        return (f"no rulebook linked: {paths.memory_src} holds none, and it was not seeded from the "
                f"template, so the shipped one is not for it; `shipyard move-personal --checkout "
                f"<the old checkout>` brings yours in")
    if link.is_symlink() and Path(os.readlink(link)) == source:
        return f"linked {link} -> {source}"
    return (f"kept {link}: yours, not a link Keel made; to use the rulebook beside the memory "
            f"({source}), move yours there and run `keel talker install` again")


def link_skills(paths: Paths) -> list[str]:
    """Make each skill link the install records (`memoryroot.SKILLS`, r1.F3) in the config
    dir's `skills/`, never over an entry that is there; the names made."""
    record = paths.memory_src / memoryroot.SKILLS
    try:
        wanted = json.loads(record.read_text())
    except (OSError, ValueError):
        return []
    made = []
    for name, target in sorted(wanted.items() if isinstance(wanted, dict) else []):
        link = paths.skills_dir / str(name)
        if "/" in str(name) or link.exists() or link.is_symlink():
            continue
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(str(target), target_is_directory=True)
        made.append(str(name))
    return made


# ----- run dirs: rotate, prune, seed trust -----

def run_dirs(paths: Paths) -> list[tuple[int, Path]]:
    """The numbered run dirs under run_base, sorted by index (empty when none exist yet)."""
    base = paths.run_base
    found = []
    if base.is_dir():
        for child in base.iterdir():
            if child.is_dir() and child.name.isdigit():
                found.append((int(child.name), child))
    return sorted(found)


def prune_runs(paths: Paths, keep: int = KEEP_RUNS) -> list[Path]:
    """Remove numbered run dirs older than the last `keep`, never the current one. Their
    transcripts live in the config dir (not here), so conversation history is preserved;
    this only stops the empty run dirs from accumulating without bound."""
    current = paths.run_index()
    removed = []
    for index, path in run_dirs(paths):
        if index != current and index <= current - keep:
            shutil.rmtree(path, ignore_errors=True)
            forget_run(paths, path)   # its config-dir slug dir and .claude.json trust entry
            removed.append(path)
    return removed


def forget_run(paths: Paths, run_dir: Path) -> None:
    """Remove a pruned run's leftovers in the config dir: the auto-memory/transcript slug
    directory and the trust entry in .claude.json. Their transcripts are 0-byte Remote
    Control stubs, so nothing of value is lost; this stops both from growing without bound."""
    slug = paths.config_dir / "projects" / project_slug(run_dir)
    shutil.rmtree(slug, ignore_errors=True)
    cj = paths.config_dir / ".claude.json"
    try:
        data = claudejson.read(cj)
    except (OSError, claudejson.Unreadable):
        return
    if data.get("projects", {}).pop(str(run_dir), None) is not None:
        claudejson.write(cj, data)


def seed_trust(paths: Paths, source: Path | None = None) -> None:
    """Add a trust entry for the current cwd to the config dir's .claude.json (reusing
    install's `seed_claude_json`), so Remote Control does not refuse the new directory.
    The seed is `paths.seed_source` unless a caller names one."""
    seed_claude_json(source or paths.seed_source, paths.config_dir / ".claude.json", paths.cwd)


def rotate(paths: Paths, keep: int = KEEP_RUNS, source: Path | None = None) -> int:
    """Bump the run-dir pointer to the next number, seed trust and re-link memory for the
    new cwd, prune old run dirs. Returns the new index. Memory (talker/memory) is unchanged;
    only the config dir's auto-memory link for the new cwd is remade to point at it."""
    nxt = paths.run_index() + 1
    paths.cwd_pointer.parent.mkdir(parents=True, exist_ok=True)
    paths.cwd_pointer.write_text(f"{nxt}\n")
    paths.cwd.mkdir(parents=True, exist_ok=True)
    seed_trust(paths, source)
    link_memory(paths)
    prune_runs(paths, keep)
    return nxt
