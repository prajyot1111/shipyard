"""The proof after `shipyard import` (c-620), and `shipyard import --verify` to run it again.

Each check compares the install with the snapshot it came from, never with itself:

- **counts**: rows per table, and cards per space and stage, equal to the source's;
- **card dirs**: every file under `state/cards/` the same bytes as the source's;
- **leftovers**: no stored value (the refs, an option, an event's ref, a board file) still
  under an old root, and every rewritten path that existed in the snapshot exists here;
- **integrity**: the board passes `integrity_check`;
- **plans**: `kb lint` over every plan on both boards, and only the findings the import
  introduced are reported;
- **doctor**: the single-machine doctor's lines, said and not counted, since a deck or a
  login the user has not started yet is not the import's fault.

The result goes to `state/import/report.md`. docs/atlas/87-import.md.
"""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
from pathlib import Path

from keel import doctor, importboard, importpaths, plangate, planlint
from keel.board import Board

TABLES = ("cards", "events", "requests", "holds", "asks")


def counts(conn: sqlite3.Connection, space_map: dict | None = None) -> dict:
    """Rows per table, and cards per space and stage; `space_map` names a source space under
    the one the import moved it to (`--map-space`)."""
    out = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}
    for space, stage, number in conn.execute(
            "SELECT space, stage, COUNT(*) FROM cards GROUP BY space, stage ORDER BY space, stage"):
        key = f"cards {(space_map or {}).get(space, space)}/{stage}"
        out[key] = out.get(key, 0) + number
    return out


def files_of(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def board_files(state: Path):
    root = state / "boards"
    return sorted(root.rglob("*.json")) if root.is_dir() else []


def stored(conn: sqlite3.Connection, state: Path):
    """`(where, JSON value)` for everything the rewrite touches on a board and its files."""
    for row in conn.execute("SELECT id, plan_ref, output_ref, options FROM cards"):
        yield f"cards/{row['id']}", [row["plan_ref"] or "", row["output_ref"] or "",
                                     importboard.as_json(row["options"]) or {}]
    for row in conn.execute("SELECT id, data FROM events WHERE data LIKE '%_ref%'"):
        data = importboard.as_json(row["data"])
        if isinstance(data, dict):
            yield f"events/{row['id']}", [data.get(key) for key in importboard.REF_FIELDS]
    for path in board_files(state):
        yield str(path.relative_to(state)), importboard.as_json(path.read_text(errors="replace"))


def leftovers(conn, state: Path, roots) -> list[str]:
    return [f"{where}: {text}" for where, value in stored(conn, state)
            for text in importpaths.leftovers(value, roots)]


def missing(conn, state: Path, source_state: Path) -> list[str]:
    """A rewritten path (one under the install's state) that the snapshot had and this lacks."""
    own = str(state) + "/"
    out = []
    for where, value in stored(conn, state):
        for text in importpaths.strings(value):
            if text.startswith(own) and not Path(text).exists() \
                    and (source_state / text[len(own):]).exists():
                out.append(f"{where}: {text}")
    return out


def compare(source: dict, here: dict) -> list[str]:
    return [f"{name}: source {source.get(name, 0)}, here {here.get(name, 0)}"
            for name in sorted(set(source) | set(here)) if source.get(name, 0) != here.get(name, 0)]


def card_dirs(source_state: Path, state: Path) -> list[str]:
    theirs, ours = files_of(source_state / "cards"), files_of(state / "cards")
    return [f"cards/{name}: {'missing' if name not in ours else 'differs'}"
            for name, digest in theirs.items() if ours.get(name) != digest]


# ----- plans -----

def lint_lines(board: Board, card_id: str, path: Path, words) -> set[str]:
    try:
        card = board.get(card_id)
        result = plangate.lint_file(path, card, events=board.events(card_id))
    except Exception as error:  # noqa: BLE001 - a plan the linter cannot read is a finding itself
        return {f"lint could not run: {type(error).__name__}"}
    out = set()
    for line in planlint.lines_of(result):
        for word in words:
            line = line.replace(word, "<state>/")
        out.add(line)
    return out


def plan_paths(conn) -> dict[str, str]:
    return {row["id"]: row["plan_ref"] for row in conn.execute(
        "SELECT id, plan_ref FROM cards WHERE plan_ref LIKE '%.md'")}


def new_findings(source_db: Path, db: Path, record: dict, state: Path, source_state: Path) -> list[str]:
    roots = dict(record.get("roots") or {})
    words = [str(state) + "/", str(source_state) + "/", *roots]
    out = []
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "source.db"
        with importboard.connect_ro(source_db) as src, sqlite3.connect(copy) as dst:
            src.backup(dst)
        src.close()
        dst.close()
        with Board(copy) as theirs, Board(db) as ours:
            for card_id, ref in plan_paths(ours.conn).items():
                where = Path(ref)
                was = importpaths.moved(ref, {str(state) + "/": str(source_state) + "/"})
                if not where.is_file() or not was or not Path(was).is_file():
                    continue
                fresh = lint_lines(ours, card_id, where, words) - lint_lines(theirs, card_id, Path(was), words)
                out += [f"{card_id}: {line}" for line in sorted(fresh)]
    return out


# ----- the whole check -----

def check(cfg, record: dict) -> dict:
    """Every check, as `{name: [problems]}`; `doctor` lines are said, never counted."""
    state = cfg.state_dir
    source_state = Path(record["source"]) / "state"
    source_db = source_state / "board.db"
    roots = dict(record.get("roots") or {})
    found = {}
    if not source_db.is_file():
        found["source"] = [f"the snapshot is gone ({source_db}); counts and card dirs not compared"]
    with importboard.connect_ro(cfg.db_path, live=True) as conn:
        here = counts(conn)
        found["integrity"] = [] if conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok" \
            else ["the board fails integrity_check"]
        found["leftovers"] = leftovers(conn, state, roots)
        found["missing"] = missing(conn, state, source_state) if source_db.is_file() else []
    conn.close()
    if source_db.is_file():
        with importboard.connect_ro(source_db) as src:
            theirs = counts(src, record.get("space_map"))
        # The one row the import adds: a `carried` for each relay meant for another host.
        theirs["events"] += len(record.get("dropped") or [])
        found["counts"] = compare(theirs, here)
        src.close()
        found["card dirs"] = card_dirs(source_state, state)
        found["plans"] = new_findings(source_db, cfg.db_path, record, state, source_state)
    found["doctor"] = doctor_lines(cfg)
    found["_counts"] = here
    return found


def doctor_lines(cfg) -> list[str]:
    try:
        report = doctor.gather(Path(cfg.source), single=True, probe_logins=False)
        return doctor.problems(report)
    except Exception as error:  # noqa: BLE001 - the doctor's failure is said, not the import's
        return [f"the doctor could not run: {type(error).__name__}: {error}"]


def failed(found: dict) -> list[str]:
    return [name for name, items in found.items()
            if name not in ("doctor", "_counts", "source") and items]


def report(found: dict, record: dict, extra: list[str] = ()) -> str:
    bad = failed(found)
    lines = ["# Import report", "",
             f"Imported from `{record['source']}` at {record['at']}.", "",
             f"**Verify: {'FAILED (' + ', '.join(bad) + ')' if bad else 'passed'}**", "",
             "## Counts here", ""]
    lines += [f"- {name}: {number}" for name, number in found["_counts"].items()]
    for name, items in found.items():
        if name == "_counts":
            continue
        lines += ["", f"## {name.capitalize()}", ""]
        lines += [f"- {item}" for item in items] or ["- none"]
    lines += ["", "## Relays dropped (they were for another host)", ""]
    lines += [f"- {d['card']} relay {d['relay']}: {d['what']} for {d['to']}"
              for d in record.get("dropped") or []] or ["- none"]
    lines += ["", "## Option paths under the snapshot's home, not on this machine", ""]
    lines += [f"- {line}" for line in record.get("absent") or []] or ["- none"]
    if extra:
        lines += ["", *extra]
    return "\n".join(lines) + "\n"



def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
