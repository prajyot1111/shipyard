"""A pack that is its own clone inside the install's packs folder (c-740; docs/atlas/62-packs.md,
"A pack someone shared").

A team keeps its pack in a repo of its own, and a colleague plugs it in with one line:
`git clone <its address> <install>/packs/<name>`. Keel finds it as it finds any pack there
(`packs.roots`): this module only says which folders of the packs folder are such clones, and
keeps the install's packs repo from seeing them. The packs repo ignores each one by a marked
block in its own `info/exclude` (the block `keel/buildout.py` writes for build output, written
the same way), so its status stays clean and nothing of the shared pack is ever added to it.
The block is reconciled wherever Keel looks at the packs folder: the Setup report (so Look
again writes it), the drain's start, and `shipyard init`.

A clone is a real folder with a real `.git` directory. A link is never followed, and a folder
the packs repo tracks is not one. Each clone that holds a pack is also one of the install's
own repos, under the key `pack-<name>` (`builder.own_repos`), so Bosun builds it from a clone
of its own and an approved change lands in the pack's repo, never in the packs repo.
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

from keel import buildout, packs

BEGIN = "# shipyard: packs that are their own clones (c-740)"
END = "# shipyard: end of cloned packs"
KEY = "pack-"
# What a folder's name may not carry into an exclude line as written: git reads these as a
# pattern's own marks, so each is escaped.
MARKS = "\\*?[]"


def found(packs_dir: Path) -> dict[str, Path]:
    """`{folder name: path}` of each clone in the packs folder: a folder with a repo of its
    own (`nested`) that the packs repo tracks no path under (r1.F3). Empty when git cannot
    say what the packs repo tracks: a folder is a clone only once that is known."""
    clones = nested(packs_dir)
    held = tracked_under(packs_dir, list(clones)) if clones else set()
    if held is None:
        return {}
    return {name: path for name, path in clones.items() if name not in held}


def tracked(packs_dir: Path) -> list[str]:
    """The folders with a repo of their own that the packs repo still tracks paths under
    (r1.F3): none is a clone until `git rm -r --cached <name>` there, committed."""
    clones = nested(packs_dir)
    return sorted((tracked_under(packs_dir, list(clones)) or set()) if clones else ())


def tracked_under(packs_dir: Path, names: list[str]) -> set[str] | None:
    """Which of `names` the packs repo's index holds a path under; None when git cannot say.
    A packs folder that is no repo yet tracks nothing (and git is not asked: it would answer
    for whatever repo the folder lies inside)."""
    if not (Path(packs_dir) / ".git").exists():
        return set()
    try:
        done = subprocess.run(["git", "-C", str(packs_dir), "ls-files", "-z"],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    # r2.F4: compared case-folded, since the index's `Mine/...` is the folder `mine` on a
    # disk that folds case; the whole index is read, a packs repo's being small
    held = {path.split("/", 1)[0].casefold() for path in done.stdout.split("\0") if path}
    return {name for name in names if name.casefold() in held}


def nested(packs_dir: Path) -> dict[str, Path]:
    """`{folder name: path}` of each folder of the packs folder with a repo of its own: a
    real directory (no link) with a real `.git` directory. Empty when the folder cannot be
    listed. The landing guard and the restart check read these, tracked or not."""
    clones = {}
    try:
        entries = sorted(os.scandir(packs_dir), key=lambda entry: entry.name)
    except OSError:
        return clones
    for entry in entries:
        path = Path(entry.path)
        if entry.name.startswith(".") or "\n" in entry.name or entry.is_symlink() or not entry.is_dir():
            continue
        if (path / ".git").is_dir() and not (path / ".git").is_symlink():
            clones[entry.name] = path
    return clones


def own(home: Path) -> dict[str, Path]:
    """`{repo key: path}` of each clone that holds the pack its folder is named for (r1.F5: a
    clone under another name is renamed first, so it is never listed under the wrong one): the
    install's own repos beside packs and memory, `pack-<name>` each."""
    return {KEY + name: path for name, path in found(Path(home) / packs.PACKS).items()
            if packs.NAME.match(name) and pack_name(path) == name}


def pack_name(path: Path) -> str | None:
    """The `name` the folder's `pack.toml` gives, or None when it has none that reads."""
    try:
        name = tomllib.loads((path / packs.PACK_FILE).read_text()).get("name")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    return name if isinstance(name, str) else None


def gone(home: Path, repos: dict) -> list[str]:
    """The keys of `repos` (a space's `{key: path}`) that were listed for a cloned pack whose
    folder is no repo of its own any more (r1.F5): `pack-*`, a path inside the install's packs
    folder, and no `.git` there now. Read off the disk alone, so a git that cannot answer
    takes nothing out."""
    folder = (Path(home) / packs.PACKS).resolve()
    held = {path.resolve() for path in nested(folder).values()}
    return sorted(key for key, path in repos.items()
                  if key.startswith(KEY) and Path(path).resolve().parent == folder
                  and Path(path).resolve() not in held)


def pattern(name: str) -> str:
    """The exclude line for one clone: its folder at the packs repo's root, and nothing else."""
    return "/" + "".join("\\" + char if char in MARKS else char for char in name) + "/"


def block_for(packs_dir: Path) -> str:
    """The marked block for the clones there now; empty when there is none."""
    lines = [pattern(name) for name in found(packs_dir)]
    return "\n".join((BEGIN, *lines, END)) + "\n" if lines else ""


def ensure_ignored(packs_dir: Path) -> bool:
    """The block in the packs repo's `info/exclude`, as the clones now are; True when written.
    Never raises: a repo git cannot read keeps what it has."""
    path = buildout.exclude_file(packs_dir)
    if path is None:
        return False
    return buildout.put_block(path, BEGIN, END, block_for(packs_dir))


def reconcile(cfg) -> bool:
    """`ensure_ignored` for the install's packs repo; nothing off an install."""
    home = getattr(cfg, "install_home", None)
    if not home or not (Path(home) / packs.PACKS / ".git").exists():
        return False
    return ensure_ignored(Path(home) / packs.PACKS)
