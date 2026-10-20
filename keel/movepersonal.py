"""`shipyard move-personal`: an owner's own things copied from the code checkout into the
install, once (c-722). docs/atlas/88-install.md, "Moving your own things into the install".

Before c-722 one owner's things lived in the tracked tree: Bosun's and the talker's memory,
the identity profile, the work pack, five segments, the history docs, and choices in the
tracked `keel.toml`. Every reader now prefers the install (`keel/memoryroot.py`,
`packs.roots`, `Config.segment_roots`), so copying them in is all a move needs. Run from the
install (`<install>/bin/shipyard move-personal`), it:

- COPIES, NEVER DELETES. The checkout is read, not written. The tree no longer carries these
  things (c-722 landing B), so a move after that deploy reads an older checkout, named with
  `--checkout`: the live one before the deploy, or a worktree of the commit before it.
- NEVER WRITES OVER the install. A file already there is skipped and said to be; a setting
  the install's `config.toml` already has is kept and said to be.
- SAYS EVERY FILE. Each item names where it reads and where it writes, then one line per
  file: `copy` or `skip`. `--dry-run` prints the same and writes nothing.
- POINTS A SPACE AT ITS COPY. A space's `contract` or `pipeline` that names a file the move
  copied (the work pack's pipeline, `adapters/work/pipeline.md`) is pointed at the install's
  copy, and a contract the checkout changed from the shipped one (one owner's own rules in
  `etc/space-personal.md`) is copied to `<install>/spaces/<space>/` and pointed at there.
  That is the one setting the install already has that a move changes: left alone it would
  name a file the tree no longer carries.
- COMMITS what it brought into a git repo of the install: `<install>/memory` (made one if
  it is not yet) and `<install>/packs`, before the settings are written, and only its own
  files: a rerun commits what an earlier run left, and the talker's own writes stay out.

A checkout's files are the ones git would show (tracked, and untracked but not ignored), so
the talker's uncommitted memory comes along and a segment's ignored `data/` does not; a
directory that is not in a git checkout is read whole.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from keel import builder, configedit, importconfig, memoryroot, settings, setupconfig
from keel import config as config_module

# The pack and the segments that are one owner's (the inventory of c-672).
PACK = "work"
SEGMENTS = ("daybook", "fathom", "instamart", "cloud-spend", "oci")
# The history docs that are one owner's story, kept in `<install>/history/` at the same path.
HISTORY = ("docs/decisions.md", "docs/plan.md", "docs/voice-next.md", "docs/voice-two-modes.md",
           "docs/voice-repoint.md", "docs/talker.md", "docs/vps-plan.md", "docs/blackboard.md",
           "docs/deck-mobile-audit.md", "docs/deck-mockup.html", "docs/deck-shots", "docs/board-shots",
           "docs/boards", "docs/probes", "docs/atlas/90-setup.md", "docs/atlas/91-worktrees.md",
           "docs/atlas/92-memory.md", "docs/atlas/93-workbench.md",
           "docs/atlas/94-flows-and-skills.md", "tests/live_deck.md", "tests/live_house.md",
           "tests/live_work_card.md",
           # the owner's tracked config, kept byte for byte (r1.F11): only some of its
           # settings are carried into the install's (`wanted`)
           "keel.toml")
HISTORY_DIR = "history"
# The talker's rulebook, the CLAUDE.md of its config dir, which the tree kept tracked until
# c-722 landing B: it moves beside the talker's memory, where `keel talker install` links it
# from (`memoryroot.RULEBOOK`).
TALKER_RULEBOOK = Path("spaces") / "harbor" / ".claude" / "CLAUDE.md"
# The talker's skill links, which the tree kept tracked until landing B (r1.F3): each is
# recorded, name to target, in the install (`memoryroot.SKILLS`), and `keel talker install`
# makes them again in the config dir (`talkerdirs.link_skills`).
TALKER_SKILLS = Path("spaces") / "harbor" / ".claude" / "skills"
# A space's keys that name a file in the code, and where a contract of the owner's own goes.
SPACE_FILES = ("contract", "pipeline")
SPACES_DIR = "spaces"
# The old name of a pack's directory: `adapters/<name>` was a link to `packs/<name>`.
ADAPTERS, PACKS = "adapters/", "packs/"
# The tables of the checkout's `keel.toml` whose settings are carried when the install's
# config lacks them, beside the `[keel]` switches the shipped example has. `[backup]` is not
# one (r1.F5): its sets, store and pull are the install's own; only `[backup] extra` crosses,
# derived from the sets the old config wrote (`extra_sets`).
TABLES = ("voice", "models", "recurring", *importconfig.CARRIED_TABLES)
# Never carried: retired tables and the ones that are a machine's, not a choice.
NEVER = ("recurring.restore-rehearsal",)
# The backup sets Keel itself knows (`config.BACKUP_SETS`); any other the old config writes is
# the owner's, named under `[backup] extra`.
CORE_SETS = config_module.BACKUP_SETS


# What a running install does to start reading what was just copied: the talker's memory
# and rulebook links are remade by its install, and Bosun reads its memory when it starts.
NEXT = ("Next: `keel doctor` names the install for each memory line; `keel talker install` points "
        "the talker's memory and rulebook links at the install; Restart Bosun on its page so it starts from "
        "the install's memory; the builder's clone of the memory repo is made by the next "
        "`shipyard init` or by Start on the first card for it.")


class MoveError(Exception):
    """A move that was not made; nothing was written."""


@dataclass
class Item:
    label: str
    source: Path
    target: Path
    repo: Path | None = None        # the install's git repo this item lands in


@dataclass
class Owned:
    target: Path
    source: Path
    placed: bool                    # copied by this run, not found there already


def unchanged(source: Path, target: Path) -> bool:
    """Whether `target` is still what was copied from `source`: the same link, or the same
    bytes."""
    if source.is_symlink() or target.is_symlink():
        return source.is_symlink() and target.is_symlink() and os.readlink(source) == os.readlink(target)
    return target.is_file() and filecmp.cmp(source, target, shallow=False)


def items(checkout: Path, home: Path, segments_dir: Path) -> list[Item]:
    found = [Item(f"the {PACK} pack", checkout / "packs" / PACK, home / "packs" / PACK, home / "packs")]
    found += [Item(f"segment {name}", checkout / "segments" / name, segments_dir / name) for name in SEGMENTS]
    memory = memoryroot.root(home)
    found += [Item(f"{part} memory" if part != memoryroot.IDENTITY else "the identity profile",
                   checkout / memoryroot.CHECKOUT[part], memoryroot.install_dir(part, home),
                   memory if part != memoryroot.IDENTITY else None)
              for part in memoryroot.PARTS]
    found.append(Item("the talker's rulebook", checkout / TALKER_RULEBOOK,
                      memoryroot.install_dir(memoryroot.TALKER, home) / memoryroot.RULEBOOK, memory))
    found += [Item(f"history {rel}", checkout / rel, home / HISTORY_DIR / rel) for rel in HISTORY]
    return found


@dataclass
class Point:
    space: str
    key: str
    value: str                      # the install path the key is pointed at


def space_files(raw: dict, checkout: Path, code: Path, home: Path,
                moved: list[Item]) -> tuple[list[Item], list[Point]]:
    """Each space file of `SPACE_FILES` the config names in the code: the copy a move makes of
    one the checkout changed from the shipped file (that owner's own words), and where the key
    then points: at that copy, or at the install's copy of a moved item it lies under. A key
    that names an absolute or home path is the install's own choice and is left."""
    copies, points = [], []
    for name, table in sorted((raw.get("spaces") or {}).items()):
        for key in SPACE_FILES:
            value = table.get(key) if isinstance(table, dict) else None
            if not isinstance(value, str) or value.startswith(("/", "~")):
                continue
            under = moved_copy(value, checkout, moved)
            if under is not None:
                points.append(Point(name, key, str(under)))
                continue
            source, shipped = checkout / value, Path(code) / value
            if source.is_file() and shipped.is_file() and not filecmp.cmp(source, shipped, shallow=False):
                target = home / SPACES_DIR / name / source.name
                copies.append(Item(f"the {name} space's {key}", source, target))
                points.append(Point(name, key, str(target)))
    return copies, points


def moved_copy(value: str, checkout: Path, moved: list[Item]) -> Path | None:
    """The install's copy of the checkout file `value` names, when it lies under an item the
    move copies (`adapters/<pack>` read as the `packs/<pack>` it linked to), else None."""
    names = [value] + ([PACKS + value[len(ADAPTERS):]] if value.startswith(ADAPTERS) else [])
    for item in moved:
        for name in names:
            path = checkout / name
            if item.source in path.parents:
                return item.target / path.relative_to(item.source)
    return None


def listed(checkout: Path, source: Path) -> list[Path]:
    """The files under `source` (or `source` itself), as git would show them in `checkout`."""
    if not source.exists():
        return []
    if source.is_file():
        return [source]
    done = subprocess.run(["git", "-C", str(checkout), "ls-files", "-co", "--exclude-standard", "-z",
                           "--", str(source.relative_to(checkout))],
                          capture_output=True, text=True)
    if done.returncode != 0:
        return sorted(path for path in source.rglob("*") if path.is_file() and ".git" not in path.parts)
    return sorted(checkout / name for name in done.stdout.split("\0") if name and (checkout / name).is_file())


def held(item: Item, target: Path) -> str | None:
    """Why the install counts `target` as held, or None: it is there, or (r2.F4) the install
    repo it lands in held it once, so a file removed there on purpose is never brought back."""
    if target.exists() or target.is_symlink():
        return f"already at {target}"
    if item.repo is not None and (item.repo / ".git").exists():
        done = subprocess.run(["git", "-C", str(item.repo), "log", "-1", "--format=%h", "--",
                               target.relative_to(item.repo).as_posix()], capture_output=True, text=True)
        if done.returncode == 0 and done.stdout.strip():
            return f"{item.repo.name} held it once and removed it since; kept removed"
    return None


def skill_links(checkout: Path) -> dict[str, str]:
    """`{name: target}` of each talker skill link the checkout tracks (`TALKER_SKILLS`)."""
    base = checkout / TALKER_SKILLS
    done = subprocess.run(["git", "-C", str(checkout), "ls-files", "-z", "--", TALKER_SKILLS.as_posix()],
                          capture_output=True, text=True)
    names = [checkout / name for name in done.stdout.split("\0") if name] if done.returncode == 0 else []
    return {path.name: os.readlink(path) for path in sorted(names)
            if path.is_symlink() and path.parent == base}


def skills_file(home: Path) -> Path:
    return memoryroot.install_dir(memoryroot.TALKER, home) / memoryroot.SKILLS


def skills_held(home: Path) -> str | None:
    """Why the install counts its skills record as held (`held`, r3.F7): there, or once
    committed in the memory repo and removed since."""
    target = skills_file(home)
    return held(Item("the talker's skill links", target, target, memoryroot.root(home)), target)


def pending(cfg, checkout: Path, code: Path) -> list[str]:
    """What a move from `checkout` would still bring into the install whose config is `cfg`,
    with the code at `code`, one line each; nothing once the install holds it all. The
    deploy's preflight asks this (`keel/deploypreflight.py`, r1.F1)."""
    home = cfg.install_home
    if home is None:
        return []
    checkout = Path(checkout).resolve()
    moved = items(checkout, home, Path(cfg.segments_dir))
    copies, points = space_files(tomllib.loads(Path(cfg.source).read_text()), checkout, code, home, moved)
    found = []
    for item in moved + copies:
        for path in listed(checkout, item.source):
            target = item.target / path.relative_to(item.source) if item.source.is_dir() else item.target
            if not held(item, target):
                found.append(f"{item.label}: {target} is not in the install yet")
                break
    text = Path(cfg.source).read_text()
    found += [f"[spaces.{point.space}] {point.key} still names the code's file, not {point.value}"
              for point in points if importconfig.current(text, f"spaces.{point.space}", point.key) != point.value]
    if skill_links(checkout) and not skills_held(home):
        found.append(f"the talker's skill links are not recorded in {skills_file(home)} yet")
    return found


class Move:
    def __init__(self, cfg, checkout: Path, dry: bool, say=print):
        self.home = cfg.install_home
        if self.home is None:
            raise MoveError(f"{cfg.source} is not an install's config: run it from the install "
                            f"(<install>/bin/shipyard move-personal)")
        self.cfg, self.checkout, self.dry, self.say = cfg, Path(checkout).resolve(), dry, say
        # The code this runs from (r3.F3): what the checkout is compared with. Never
        # `cfg.root`, which follows KEEL_HOME, and every Keel service sets KEEL_HOME to the
        # live checkout, so a move started from one would compare that checkout with itself.
        self.code = config_module.package_root()
        self.copied = self.skipped = self.carried = self.kept = 0
        self.points: list = []
        self.owned: dict[Path, list[Owned]] = {}     # repo -> the files of the move's in it

    def lacking(self) -> list[str]:
        """What the install still lacks that a move should bring: what a move from the named
        checkout would bring, and from the checkout the install runs (`cfg.root`, which a
        service's KEEL_HOME names) when that is another. Run from the code itself, which no
        longer carries the owner's things, the talker's rulebook the install lacks (r1.F10)."""
        found = pending(self.cfg, self.checkout, self.code)
        live = Path(self.cfg.root).resolve()
        if live not in (self.checkout, self.code):
            found += pending(self.cfg, live, self.code)
        own = memoryroot.install_dir(memoryroot.TALKER, self.home) / memoryroot.RULEBOOK
        if self.checkout == self.code and not own.is_file() and not (self.code / TALKER_RULEBOOK).is_file():
            found.append(f"the talker's rulebook: {own} is not in the install yet")
        return list(dict.fromkeys(found))

    def idle(self) -> list[str]:
        """r3.F6: what the install lacks, when this run would copy and point none of it; empty
        when nothing is lacking or the run brings something."""
        lacking = self.lacking()
        if not lacking:
            return []
        plan = Move(self.cfg, self.checkout, dry=True, say=lambda line: None)
        plan.code = self.code
        plan.gather()
        text = Path(self.cfg.source).read_text()
        pointed = [point for point in plan.points
                   if importconfig.current(text, f"spaces.{point.space}", point.key) != point.value]
        return [] if plan.copied or pointed else lacking

    def refusal(self, lacking: list[str]) -> str:
        return (f"a move from {self.checkout} would copy nothing, and the install still lacks: "
                + "; ".join(lacking[:3]) + ("; and more" if len(lacking) > 3 else "")
                + ". Name the checkout that still carries your own things, with --checkout "
                  "<that checkout> (the live one before the deploy, or a worktree of the commit "
                  "before it)")

    def gather(self) -> None:
        """Copy (or, on a dry run, say) each item and the skill links, and find the space files
        to point."""
        moved = items(self.checkout, self.home, Path(self.cfg.segments_dir))
        copies, self.points = space_files(tomllib.loads(Path(self.cfg.source).read_text()),
                                          self.checkout, self.code, self.home, moved)
        for item in moved + copies:
            self.copy(item)
        self.skills()

    def run(self) -> int:
        idle = self.idle()
        if idle and not self.dry:
            raise MoveError(self.refusal(idle))
        self.say(f"Moving your own things from the checkout {self.checkout} into the install {self.home}"
                 + (" (dry run: nothing is written)" if self.dry else ""))
        self.gather()
        # Committed before the settings are written (r1.F3): a refused settings write leaves
        # what was copied committed, and a rerun commits what an earlier run left.
        commits = [] if self.dry else self.commit()
        self.config()
        self.point()
        self.list_repos()
        if self.dry:
            self.say(f"\nDry run: would have copied {self.copied} files, skipped {self.skipped}; "
                     f"carried {self.carried} settings, kept {self.kept}. Nothing was written.")
            if idle:
                self.say(f"A real run would be refused: {self.refusal(idle)}")
            return 0
        self.say(f"\nDone: copied {self.copied} files, skipped {self.skipped}; carried "
                 f"{self.carried} settings, kept {self.kept}. Nothing was deleted from the checkout.")
        for repo in commits:
            self.say(f"Committed in {repo}")
        if self.copied:
            self.say(NEXT)
        return 0

    def copy(self, item: Item) -> None:
        files = listed(self.checkout, item.source)
        if not files:
            self.say(f"\n{item.label}: nothing at {item.source}")
            return
        self.say(f"\n{item.label}: {item.source} -> {item.target}")
        for path in files:
            target = item.target / path.relative_to(item.source) if item.source.is_dir() else item.target
            name = path.relative_to(item.source).as_posix() if item.source.is_dir() else path.name
            why = held(item, target)
            if item.repo is not None and (target.exists() or target.is_symlink() or not why):
                self.owned.setdefault(item.repo, []).append(Owned(target, path, not why))
            if why:
                self.skipped += 1
                self.say(f"  skip  {name} ({why})")
                continue
            self.copied += 1
            self.say(f"  copy  {name} -> {target}")
            if not self.dry:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target, follow_symlinks=False)

    def config(self) -> None:
        old_path = self.checkout / config_module.SHIPPED_CONFIG
        path = Path(self.cfg.source)
        self.say(f"\nsettings: {old_path} -> {path}")
        if not old_path.is_file():
            self.say("  nothing to carry: the checkout has no keel.toml")
            return
        old = importconfig.load_old(old_path)
        text = path.read_text()
        new = self.carry(text, old)
        if new != text and not self.dry:
            setupconfig.edit(self.cfg, lambda current: self.carry(current, old, quiet=True))

    def carry(self, text: str, old: dict, quiet: bool = False) -> str:
        repos = {key for space in self.cfg.spaces.values() for key in space.repos}
        for table, key, value in wanted(old, self.code):
            why = left_out(table, key, repos)
            if why:
                if not quiet:
                    self.say(f"  skip  [{table}] {key} ({why})")
                continue
            if importconfig.current(text, table, key) is not None:
                if not quiet:
                    self.kept += 1
                    self.say(f"  keep  [{table}] {key} (the install already sets it)")
                continue
            try:
                text = configedit.set_entry(text, table, key, value)
            except configedit.EditError as error:
                if not quiet:
                    self.say(f"  skip  [{table}] {key} ({error})")
                continue
            if not quiet:
                self.carried += 1
                self.say(f"  carry [{table}] {key} = {configedit.literal(value)}")
        return text

    def skills(self) -> None:
        """r1.F3: the talker's skill links, recorded name to target in the install, never
        over a record that is there; committed with the memory."""
        links, target = skill_links(self.checkout), skills_file(self.home)
        if not links:
            return
        self.say(f"\nthe talker's skill links: {self.checkout / TALKER_SKILLS} -> {target}")
        why = skills_held(self.home)
        if why:
            self.skipped += 1
            self.say(f"  skip  {target.name} ({why})")
            return
        self.copied += 1
        self.say(f"  copy  {', '.join(sorted(links))} -> {target}")
        if not self.dry:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(links, indent=1, sort_keys=True) + "\n")
            self.owned.setdefault(memoryroot.root(self.home), []).append(Owned(target, target, True))

    def point(self) -> None:
        """Each space file the tree no longer carries pointed at its copy in the install
        (`space_files`). One already pointed there is left; a dry run only says it."""
        for point in self.points:
            table = f"spaces.{point.space}"
            if importconfig.current(Path(self.cfg.source).read_text(), table, point.key) == point.value:
                continue
            self.say(f"  point [{table}] {point.key} = {point.value}")
            if not self.dry:
                setupconfig.edit(self.cfg, lambda current, table=table, point=point:
                                 configedit.set_entry(current, table, point.key, point.value))

    def list_repos(self) -> None:
        """Each own repo the move made or filled (the memory, r1.F1) listed as a personal repo
        the builder builds, as init lists packs: a change to it is then a card that lands by
        Approve outcome. One listed already is left as it is; a dry run only says it."""
        for key in builder.OWN_REPOS:
            path = self.home / key
            if not ((path / ".git").exists() or path in self.owned):
                continue
            text = Path(self.cfg.source).read_text()
            if builder.list_own(text, self.cfg, key, path) == text:
                continue
            self.say(f"  list  {key} = {path}")
            if not self.dry:
                setupconfig.edit(self.cfg, lambda current, key=key, path=path:
                                 builder.list_own(current, self.cfg, key, path))

    def commit(self) -> list[Path]:
        """Each install repo with the move's files in it committed: a file copied this run, or
        one an earlier run placed that still matches its source byte for byte (fix check 3),
        and nothing else. An edit since, by the talker or by hand, stays uncommitted for the
        user to review. A repo with nothing new is left as it is."""
        made = []
        for repo, files in sorted(self.owned.items()):
            there = [own.target for own in files if own.placed or unchanged(own.source, own.target)]
            if there and memoryroot.commit(repo, "Moved in from the code checkout (shipyard move-personal)", there):
                made.append(repo)
        return made


def wanted(old: dict, root: Path) -> list[tuple[str, str, object]]:
    """`(table, key, value)` for each setting of the old config a move may carry: every key of
    `TABLES` (nested tables walked), the `[keel]` switches the example has, and the owner's
    extra backup sets, named under `[backup] extra`."""
    found = []
    for table in TABLES:
        found += leaves(table, dig(old, table))
    found = [(table, key, value) for table, key, value in found
             if not any(table == never or table.startswith(never + ".") for never in NEVER)]
    keel = old.get("keel") or {}
    found += [("keel", key, keel[key]) for key in importconfig.switches(root) if key in keel]
    extra = extra_sets(old)
    if extra:
        found.append(("backup", "extra", extra))
    return found


def extra_sets(old: dict) -> list[str]:
    """The old config's own backup sets beyond Keel's: its `[backup] extra`, else the sets it
    wrote (`[backup] sets`, else every `[hosts.<name>] backup_sets`) less keel and code."""
    backup = old.get("backup") or {}
    if backup.get("extra"):
        return list(backup["extra"])
    written = list(backup.get("sets") or [])
    if "sets" not in backup:
        for table in (old.get("hosts") or {}).values():
            written += list((table or {}).get("backup_sets") or [])
    return list(dict.fromkeys(name for name in written if name not in CORE_SETS))


def left_out(table: str, key: str, repos: set[str]) -> str | None:
    """Why a setting is not carried, or None: a machine key belongs to the install's own
    `[machine]`, and a suite or branch named for a repo the install does not list would name
    a repo it does not have (c-621)."""
    if (table == "voice" and key in settings.VOICE_MACHINE_KEYS) or (table == "keel" and key in settings.MACHINE_KEYS):
        return "a machine key: the install's [machine] says it"
    if table in importconfig.CARRIED_TABLES and key not in repos:
        return f"no repo {key} in this install"
    return None


def dig(data: dict, table: str):
    for part in table.split("."):
        data = data.get(part) if isinstance(data, dict) else None
    return data


def leaves(table: str, value) -> list[tuple[str, str, object]]:
    if not isinstance(value, dict):
        return []
    found = []
    for key, inner in value.items():
        if isinstance(inner, dict):
            found += leaves(f"{table}.{key}", inner)
        else:
            found.append((table, key, inner))
    return found


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="shipyard move-personal",
                                     description="copy your own things from the code checkout into this install, once")
    parser.add_argument("--checkout", help="the checkout to copy from (default: the code this install runs)")
    parser.add_argument("--dry-run", action="store_true", help="print what would be copied; write nothing")
    args = parser.parse_args(argv)
    try:
        cfg = config_module.load(ensure=False)
        move = Move(cfg, Path(args.checkout).expanduser() if args.checkout else cfg.root, args.dry_run)
        return move.run()
    except (MoveError, config_module.ConfigError, importconfig.CarryError, setupconfig.SetupError,
            tomllib.TOMLDecodeError, OSError) as refusal:
        print(f"shipyard move-personal: {refusal}", file=sys.stderr)
        return 1
