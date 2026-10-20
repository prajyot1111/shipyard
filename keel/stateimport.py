"""`shipyard import <dir>`: his Keel brought into an install from a snapshot (c-620).

`<dir>` is a `keel` backup set unpacked on this machine (`bin/keel-backup pull`, then
`restore --local --into <dir>`): `state/` with the board, and `segments/<name>/data`. The
import reads it and never writes it. Run from the install (`<install>/bin/shipyard import`),
it brings in, by an allowlist:

- `state/board.db`: copied through sqlite's backup, migrated, edited in one transaction
  (`keel/importboard.py`), checked, then renamed into place;
- `state/cards/`, `state/boards/` (its trash too, every JSON in it with its paths moved),
  `state/voice/`, `state/review-settings.json`; everything else under `state/` is named as
  skipped (`console/`, `console.json`, `login.json`, `logs/`, `worktrees/`, ...);
- each segment the old config fetches: its tracked code from the checkout, its data from
  the snapshot, into `<install>/segments/<name>/`;
- the choices in the old config (`keel/importconfig.py`).

Refused, before anything is written: a snapshot whose board fails `integrity_check`; a card
in a space the install will not have; uncommitted memory in the checkout that the install
does not hold yet (c-722, `memory_paths`); an install that was imported already (`--replace` moves its `state/` aside first, refused once its drain has
started a house); a Keel drain running as this user that is not this install's
(`keel/drainprobe.py`), and this install's own drain or deck. A run stops part way with
its record `in-progress`, and running it again resumes it. `--dry-run` writes nothing and prints
every change. Every real run ends with `keel/importverify.py`. docs/atlas/87-import.md.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from keel import drainprobe, importboard, importconfig, importpaths, importverify, memoryroot, setupconfig
from keel import config as config_module

ALLOWED = ("cards", "boards", "voice", "review-settings.json")
BOARD_FILES = ("board.db", "board.db-wal", "board.db-shm")
NEVER_COPIED = (".attached", ".lock")
# Where a checkout kept the memory before it moved to the install (c-722, `keel/memoryroot.py`).
MEMORY = tuple(path.as_posix() for path in memoryroot.CHECKOUT.values())
IMPORT_DIR = "import"
IN_PROGRESS, DONE = "in-progress", "done"


class Refused(Exception):
    """An import that was not made; nothing was written."""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----- the source -----

def source_board(source: Path) -> Path:
    db = source / "state" / "board.db"
    if not db.is_file():
        raise Refused(f"{source} has no state/board.db: unpack a keel set there "
                      f"(bin/keel-backup restore --local --into {source})")
    wal = db.with_name("board.db-wal")
    if wal.is_file() and wal.stat().st_size:
        raise Refused(f"{wal} is beside the board: that is a live board, not a snapshot; "
                      f"take one with `keel backup run --force --set keel` and restore it")
    with importboard.connect_ro(db) as conn:
        verdict = conn.execute("PRAGMA integrity_check").fetchone()[0]
    conn.close()
    if verdict != "ok":
        raise Refused(f"{db} fails integrity_check ({verdict}); take a fresh snapshot")
    return db


def memory_paths(home: Path | None) -> list[str]:
    """The checkout's memory paths still read (c-722): each part the install does not hold."""
    return [memoryroot.CHECKOUT[part].as_posix() for part in memoryroot.PARTS
            if not memoryroot.in_install(part, home)]


def dirty_memory(checkouts, paths=MEMORY) -> list[str]:
    """Uncommitted changes under the memory paths of each checkout, by path."""
    found = []
    if not paths:
        return found
    for checkout in dict.fromkeys(Path(c) for c in checkouts):
        if not (checkout / ".git").exists():
            continue
        out = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain", "--", *paths],
                             capture_output=True, text=True).stdout
        found += [f"{checkout}/{line[3:]}" for line in out.splitlines() if line.strip()]
    return found


def checkouts(cfg, old_path: Path) -> list[Path]:
    """Where the memory comes from: the code checkout, and the old config's own."""
    return [cfg.root, old_path.parent]


def foreign_spaces(conn, spaces: set[str]) -> dict[str, int]:
    rows = conn.execute("SELECT space, COUNT(*) FROM cards GROUP BY space").fetchall()
    return {space: number for space, number in rows if space not in spaces}


# ----- files -----

def wanted(path: Path) -> bool:
    return not any(part in NEVER_COPIED or part.endswith(".lock") for part in path.parts)


def file_plan(source_state: Path, state: Path) -> tuple[list[tuple[Path, Path]], list[str]]:
    """`(copies, skipped)`: every file the allowlist takes, and every top-level entry it does not."""
    copies, skipped = [], []
    for entry in sorted(source_state.iterdir()):
        if entry.name in BOARD_FILES:
            continue
        if entry.name not in ALLOWED:
            skipped.append(f"state/{entry.name}{'/' if entry.is_dir() else ''}")
            continue
        files = [entry] if entry.is_file() else sorted(p for p in entry.rglob("*") if p.is_file())
        for path in files:
            relative = path.relative_to(source_state)
            if wanted(relative):
                copies.append((path, state / relative))
            else:
                skipped.append(f"state/{relative}")
    return copies, skipped


def board_json(source: Path, roots) -> tuple[str | None, list[str]]:
    """A board file's text with its paths moved, or None when it is not JSON with any."""
    if "boards" not in source.parts or source.suffix != ".json":
        return None, []
    value = importboard.as_json(source.read_text(errors="replace"))
    if value is None:
        return None, []
    new, changes = importpaths.rewrite(value, roots)
    if not changes:
        return None, []
    return json.dumps(new, indent=1), [f"{where}: {old} -> {moved}" for where, old, moved in changes]


def copy_files(copies, roots) -> None:
    for source, target in copies:
        target.parent.mkdir(parents=True, exist_ok=True)
        text, _ = board_json(source, roots)
        if text is None:
            shutil.copy2(source, target)
        else:
            target.write_text(text)


# ----- segments -----

def fetched(old: dict, source: Path) -> list[str]:
    """Every segment any host of the old config fetches; with no hosts, every one with data."""
    hosts = old.get("hosts") or {}
    names = {name for table in hosts.values() for name in (table.get("fetch") or [])}
    if not hosts:
        names = {path.parent.name for path in (source / "segments").glob("*/data")}
    return sorted(names)


def segment_plan(cfg, old: dict, source: Path) -> tuple[list[tuple[Path, Path]], list[str]]:
    copies, notes = [], []
    target = cfg.segments_dir
    for name in fetched(old, source):
        listed = subprocess.run(["git", "-C", str(cfg.root), "ls-files", "-z", f"segments/{name}"],
                                capture_output=True, text=True).stdout.split("\0")
        code = [cfg.root / item for item in listed if item]
        if not code:
            notes.append(f"segment {name}: not in the checkout, skipped")
            continue
        copies += [(path, target / path.relative_to(cfg.root / "segments")) for path in code]
        data = source / "segments" / name / "data"
        found = sorted(p for p in data.rglob("*") if p.is_file()) if data.is_dir() else []
        copies += [(path, target / name / "data" / path.relative_to(data)) for path in found]
        notes.append(f"segment {name}: {len(code)} code file(s), {len(found)} data file(s)")
    return copies, notes


# ----- the record -----

def record_path(cfg) -> Path:
    return cfg.state_dir / IMPORT_DIR / "record.json"


def read_record(cfg) -> dict | None:
    try:
        return json.loads(record_path(cfg).read_text())
    except (OSError, ValueError):
        return None


def started_since(cfg, mark: int) -> int:
    if not cfg.db_path.is_file():
        return 0
    with importboard.connect_ro(cfg.db_path, live=True) as conn:
        found = conn.execute("SELECT COUNT(*) FROM events WHERE kind IN ('session', 'resume') "
                             "AND id > ?", (mark,)).fetchone()[0]
    conn.close()
    return found


def card_count(cfg) -> int:
    if not cfg.db_path.is_file():
        return 0
    with importboard.connect_ro(cfg.db_path, live=True) as conn:
        found = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    conn.close()
    return found


def deck_running(cfg) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", cfg.serve_port)) == 0


def snapshot_events(source: Path) -> int:
    db = source / "state" / "board.db"
    if not db.is_file():
        return 0
    with importboard.connect_ro(db) as conn:
        found = conn.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]
    conn.close()
    return found


def refuse_again(cfg, replace: bool, source: Path) -> bool:
    """Whether this run resumes one that stopped part way; refused when it may not run.
    The house check's mark is the last import's last event, else the snapshot's."""
    record = read_record(cfg)
    resuming = bool(record) and record.get("status") == IN_PROGRESS
    if resuming and record["source"] != str(source):
        raise Refused(f"an import from {record['source']} stopped part way at {record['at']}; "
                      f"run it again from that snapshot, or --replace")
    if record and not resuming and not replace:
        raise Refused(f"already imported from {record['source']} at {record['at']}; "
                      f"--replace moves this install's state aside and imports again")
    if not record and card_count(cfg) and not replace:
        raise Refused(f"this install's board already has {card_count(cfg)} card(s); import goes "
                      f"into a fresh install, or --replace moves its state aside first")
    mark = (record or {}).get("events_max") or snapshot_events(source)
    started = started_since(cfg, mark) if (replace or resuming) else 0
    if started:
        raise Refused(f"this install's drain has started {started} house(s) since the import; "
                      f"importing again would lose their work, so nothing was moved")
    return resuming


def replace_state(cfg) -> Path:
    """`state/` moved aside to `state/pre-import-<time>/`; a new empty `state/` in its place."""
    state = cfg.state_dir
    aside = state.with_name(f"{state.name}.moving")
    state.rename(aside)
    state.mkdir()
    kept = state / f"pre-import-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    aside.rename(kept)
    for name in ("logs", "cards"):
        (state / name).mkdir(exist_ok=True)
    return kept


# ----- one run -----

class Run:
    def __init__(self, cfg, args, say=print):
        self.cfg, self.args, self.say = cfg, args, say
        self.home = setupconfig.install_of(cfg)
        self.source = Path(args.source).expanduser().resolve()
        self.old_path = Path(args.old_config or cfg.root / "keel.toml").expanduser()
        self.old = importconfig.load_old(self.old_path)
        self.work_dir = args.work_config_dir or importconfig.default_work_dir(self.old)

    def context(self) -> importboard.Context:
        box = next((t.get("ssh") for t in (self.old.get("hosts") or {}).values() if t.get("ssh")), "<source>")
        repos = importconfig.old_space(self.old, "personal").get("repos") or {}
        old_work = importconfig.default_work_dir(self.old)
        return importboard.Context(
            state=self.cfg.state_dir, repos=importconfig.personal_repos(self.cfg, self.old),
            projects=importconfig.projects_dir(self.cfg, self.old),
            work_kept=Path(self.work_dir).expanduser() == Path(old_work).expanduser(),
            work_dir=self.work_dir, box=box, box_repos={k: str(v) for k, v in repos.items()},
            host=self.cfg.host, space_map=self.space_map())

    def roots(self, conn) -> dict[str, str]:
        own = str(self.cfg.state_dir) + "/"
        values = list(importboard.stored_values(conn))
        values += [importboard.as_json(p.read_text(errors="replace"))
                   for p in importverify.board_files(self.source / "state")]
        found = importpaths.find_roots(values, own, self.checkout())
        overrides = [importpaths.parse_root(item) for item in self.args.root or ()]
        return importpaths.mapping(found, own, overrides)

    def checkout(self) -> str:
        """The old checkout's name, which every old state root ends in (`<name>/state/`)."""
        parent = self.old_path.resolve().parent
        return parent.name if (parent / ".git").exists() else importpaths.DEFAULT_CHECKOUT

    def space_map(self) -> dict[str, str]:
        found = {}
        for item in getattr(self.args, "map_space", None) or ():
            old, sep, new = item.partition("=")
            if not (sep and old.strip() and new.strip()):
                raise Refused(f"--map-space {item!r}: write it OLD=NEW, e.g. console=personal")
            found[old.strip()] = new.strip()
        return found

    def refuse(self, conn) -> None:
        spaces = importconfig.spaces_after(self.cfg, self.old)
        mapped = self.space_map()
        unknown = sorted(new for new in mapped.values() if new not in spaces)
        if unknown:
            raise Refused(f"--map-space names a space this install will not have: {', '.join(unknown)}")
        foreign = {name: number for name, number in foreign_spaces(conn, spaces).items()
                   if name not in mapped}
        if foreign:
            raise Refused("cards in a space this install will not have: " + ", ".join(
                f"{name} ({number})" for name, number in sorted(foreign.items()))
                + "; carry them into one it has with --map-space OLD=NEW (e.g. "
                + f"--map-space {sorted(foreign)[0]}=personal)")
        dirty = dirty_memory(checkouts(self.cfg, self.old_path), memory_paths(self.home))
        if dirty:
            raise Refused("uncommitted memory in the checkout; commit it first: " + ", ".join(dirty))
        if self.args.dry_run:
            return
        why = drainprobe.refusal(Path(self.cfg.source))
        if why:
            raise Refused(why)
        _, ours = drainprobe.drains(Path(self.cfg.source))
        if ours or deck_running(self.cfg):
            raise Refused("this install is running (" + ("; ".join(ours) or f"its deck answers on "
                          f"{self.cfg.serve_port}") + "); `shipyard service stop` first")

    def prepare(self) -> dict:
        db = source_board(self.source)
        with importboard.connect_ro(db) as conn:
            self.refuse(conn)
            roots = self.roots(conn)
            plan = importboard.plan(conn, roots, self.context())
            events_max = conn.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]
        conn.close()
        copies, skipped = file_plan(self.source / "state", self.cfg.state_dir)
        segments, notes = segment_plan(self.cfg, self.old, self.source)
        text = Path(self.cfg.source).read_text()
        carried, config_notes = importconfig.carry(self.cfg, text, self.old, self.work_dir)
        return {"db": db, "roots": roots, "plan": plan, "copies": copies, "skipped": skipped,
                "segments": segments, "segment_notes": notes, "config_diff": importconfig.diff(text, carried),
                "config_notes": config_notes, "events_max": events_max}

    def show(self, made: dict) -> None:
        say, plan = self.say, made["plan"]
        say(f"Import from {self.source} into {self.home} (old config {self.old_path}, "
            f"work Claude dir {self.work_dir})")
        say("\nOld roots:")
        for old, new in made["roots"].items():
            say(f"  {old} -> {new}")
        say(f"\nBoard changes ({len(plan.lines())}):")
        for line in plan.lines():
            say(f"  {line}")
        say(f"\nBlocked by the import ({len(plan.blocks)}):")
        for card, reasons in plan.blocks.items():
            say(f"  {card}: {'; '.join(reasons)}")
        say(f"\nWorktrees cut again ({len(plan.recuts)}):")
        for item in plan.recuts:
            say(f"  {item['card']}: git -C {item['repo']} worktree add {item['path']} {item['branch']}")
        for command in plan.fetches:
            say(f"  to bring a branch over first: {command}")
        say(f"\nRelays for another host, marked carried ({importboard.DROPPED}) ({len(plan.dropped)}):")
        for item in plan.dropped:
            say(f"  {item['card']} relay {item['relay']}: {item['what']} for {item['to']}")
        say(f"\nOption paths under the snapshot's home, not on this machine ({len(plan.absent)}):")
        for line in plan.absent:
            say(f"  {line}")
        say(f"\nFree text mentioning an old root, not rewritten: {plan.mentions}")
        say(f"\nFiles copied ({len(made['copies'])}):")
        for source, target in made["copies"]:
            say(f"  {source.relative_to(self.source)} -> {target}")
            for line in board_json(source, made["roots"])[1]:
                say(f"    {line}")
        say(f"\nSkipped ({len(made['skipped'])}):")
        for name in made["skipped"]:
            say(f"  {name}")
        say(f"\nSegments ({len(made['segments'])} file(s)):")
        for note in made["segment_notes"]:
            say(f"  {note}")
        say("\nConfig:")
        say(made["config_diff"] or "  (no change)")
        for note in made["config_notes"]:
            say(f"  {note}")
        for line in self.claude_dirs():
            say(line)

    def claude_dirs(self) -> list[str]:
        """The old machines' Claude config dirs, which are not imported, and their memory."""
        dirs = [t.get("config_dirs", {}).values() for t in (self.old.get("hosts") or {}).values()]
        found = [str(d) for group in dirs for d in group]
        if (self.old.get("console") or {}).get("config_dir"):
            found.append(str(self.old["console"]["config_dir"]))
        lines = ["\nNot imported, the old machines' Claude config dirs (their auto-memory stays there):"]
        for name in dict.fromkeys(found):
            memory = sorted(Path(name).expanduser().glob("projects/*/memory/*.md"))
            lines.append(f"  {name}: {len(memory) or 'no'} memory file(s) readable here")
            lines += [f"    {path}" for path in memory]
        return lines

    def write(self, made: dict) -> dict:
        """Every write, behind a record that says `in-progress` until the last one is made,
        so a run that stops part way is resumed by running it again."""
        if self.args.replace and self.cfg.state_dir.is_dir():
            self.say(f"moved the install's state aside to {replace_state(self.cfg)}")
        plan = made["plan"]
        record = {"status": IN_PROGRESS, "source": str(self.source), "at": now(),
                  "old_config": str(self.old_path), "work_config_dir": self.work_dir,
                  "roots": made["roots"], "events_max": made["events_max"],
                  "space_map": self.space_map()}
        keep(self.cfg, record)
        for item in plan.recuts:
            error = importboard.recut(item)
            if error:
                importboard.failed_recut(plan.edits, item["card"], error)
                plan.blocks.setdefault(item["card"], []).append(error.splitlines()[0])
        building = self.cfg.state_dir / IMPORT_DIR / "board.db.importing"
        importboard.build(made["db"], building, plan.edits, plan.dropped)
        importconfig.apply(self.cfg, self.old, self.work_dir)
        copy_files(made["copies"], made["roots"])
        copy_files(made["segments"], {})
        for name in BOARD_FILES[1:]:
            (self.cfg.state_dir / name).unlink(missing_ok=True)
        building.replace(self.cfg.db_path)
        record.update(status=DONE, blocked=plan.blocks, recut=[item["card"] for item in plan.recuts],
                      dropped=plan.dropped, absent=plan.absent, skipped=made["skipped"])
        keep(self.cfg, record)
        return record


def keep(cfg, record: dict) -> None:
    record_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    record_path(cfg).write_text(json.dumps(record, indent=1) + "\n")


def verify(cfg, record: dict, say=print, extra=()) -> int:
    cfg = config_module.load(Path(cfg.source), ensure=False)
    found = importverify.check(cfg, record)
    text = importverify.report(found, record, list(extra))
    importverify.write(cfg.state_dir / IMPORT_DIR / "report.md", text)
    bad = importverify.failed(found)
    for name, items in found.items():
        if name != "_counts" and items:
            say(f"{name}: {len(items)}")
            for item in items[:20]:
                say(f"  {item}")
    say(f"verify {'FAILED: ' + ', '.join(bad) if bad else 'passed'}; report at "
        f"{cfg.state_dir / IMPORT_DIR / 'report.md'}")
    return 1 if bad else 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="shipyard import", description=__doc__.split("\n\n")[0])
    p.add_argument("source", nargs="?", help="a keel set unpacked on this machine")
    p.add_argument("--old-config", help="the old keel.toml (default: the checkout's)")
    p.add_argument("--root", action="append", metavar="OLD=NEW", help="map an old state root")
    p.add_argument("--work-config-dir", help="the work space's Claude dir (default: the old config's)")
    p.add_argument("--dry-run", action="store_true", help="print every change, write nothing")
    p.add_argument("--map-space", action="append", metavar="OLD=NEW",
                   help="carry an old space's cards into one this install has (e.g. console=personal)")
    p.add_argument("--replace", action="store_true", help="move this install's state aside and import again")
    p.add_argument("--verify", action="store_true", help="run the checks of the last import again")
    return p


def main(argv: list[str], say=print) -> int:
    args = parser().parse_args(argv)
    try:
        cfg = config_module.load(config_module.config_path(), ensure=False)
        setupconfig.install_of(cfg)
        if args.verify:
            record = read_record(cfg)
            if not record:
                raise Refused("this install has no import to verify")
            return verify(cfg, record, say)
        if not args.source:
            raise Refused("usage: shipyard import <dir> [--dry-run] [--old-config <toml>]")
        return run(cfg, args, say)
    except (Refused, setupconfig.SetupError, importconfig.CarryError, importpaths.RootError) as error:
        print(f"shipyard import: refused: {error}", file=sys.stderr)
        return 1


def run(cfg, args, say=print) -> int:
    if not args.dry_run and refuse_again(cfg, args.replace, Path(args.source).expanduser().resolve()):
        say("resuming the import that stopped part way")
    job = Run(cfg, args, say)
    made = job.prepare()
    job.show(made)
    if args.dry_run:
        say("\nDry run: nothing was written.")
        return 0
    record = job.write(made)
    return verify(cfg, record, say, job.claude_dirs())
