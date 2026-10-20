"""The board half of `shipyard import` (c-620): every edit the copied board takes, worked out
from the source alone, then made in one transaction on the copy.

`plan` reads the source board (never writes it) and returns a `Plan`: one `Edit` per row and
column that changes, each with the `table/id field: old -> new` lines the dry run prints, plus
the cards it blocks and the worktrees it cuts again. `apply` makes exactly those edits, so a
dry run and a real run of one source agree line for line.

What changes, and nothing else:
- a stored path under an old state root moves to the install's (`keel/importpaths.py`):
  `plan_ref`, `output_ref`, the same two keys in an event's data, every string in `options`;
- what only two machines needed is cleared: `options.host` (the pin), `options.claim`,
  `options.publishing` (the door's marker), a landing, rotation or drop-in hold in flight, an
  open ask's `claimed_by`/`claimed_at`, a waiting request's `taken_by`; a pending relay for
  another host is marked carried, "dropped by import" (the one row added);
- an open personal card's session id, which names a session on the box, is cleared and the
  card blocked (Resume starts fresh from its card dir); a work card keeps its id while the
  work space keeps its Claude dir;
- an open personal card that had a worktree gets it cut again from its branch on this
  machine, or is blocked naming the branch that is still on the box.
No other event is added or edited beyond the ref rewrite.
docs/atlas/87-import.md.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from keel import adapters, importpaths
from keel.board import (Board, CLAIM_OPTION, DROPIN_HOLD_OPTION, LANDING_OPTION, PUBLISHING_OPTION,
                        ROTATE_OPTION, WORKED_STAGES)
from keel.board import now as board_now

REF_FIELDS = ("plan_ref", "output_ref")
# A card's pin to one machine (`options.host`), what the two-machine placement read (c-622).
PIN_OPTION = "host"
# What only two machines, or a house mid-step on the old one, needed: the pin, the claim,
# the door's marker, a landing or rotation in flight, a drop-in hold.
CLEARED = (PIN_OPTION, CLAIM_OPTION, PUBLISHING_OPTION, LANDING_OPTION, ROTATE_OPTION,
           DROPIN_HOLD_OPTION)
KEYS = {"cards": "id", "events": "id", "asks": "id", "requests": "id"}
# A path an option names on a box home (`/home/<user>/...`) that this machine lacks.
BOX_HOME = "/home/"
DROPPED = "dropped by import"
CLEARED_WORD = "(cleared)"


@dataclass
class Edit:
    table: str
    key: object
    column: str
    old: object
    new: object
    lines: list[str] = field(default_factory=list)


@dataclass
class Plan:
    roots: dict[str, str]
    edits: list[Edit] = field(default_factory=list)
    blocks: dict[str, list[str]] = field(default_factory=dict)
    recuts: list[dict] = field(default_factory=list)
    fetches: list[str] = field(default_factory=list)
    mentions: int = 0
    dropped: list[dict] = field(default_factory=list)       # pending relays to another host
    absent: list[str] = field(default_factory=list)         # option paths not on this machine

    def lines(self) -> list[str]:
        return [line for edit in self.edits for line in edit.lines]


@dataclass
class Context:
    """What the card rules need to know about this machine."""
    state: Path                         # the install's state dir
    repos: dict[str, Path]              # personal repos by key, once carried
    projects: Path | None = None
    work_kept: bool = True              # the work space keeps the old Claude dir
    work_dir: str = ""
    host: str = ""                      # the install's own host name
    box: str = "<source>"               # how a fetch reaches the source machine (its ssh name)
    box_repos: dict[str, str] = field(default_factory=dict)   # each repo's path there
    space_map: dict[str, str] = field(default_factory=dict)   # --map-space OLD=NEW


def connect_ro(path: Path, live: bool = False) -> sqlite3.Connection:
    """A board read without writing it: a snapshot nobody writes as immutable (no WAL, no
    lock), a `live` one (the install's own, a deck may hold it) read only."""
    conn = sqlite3.connect(f"file:{path}?mode=ro{'' if live else '&immutable=1'}", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def as_json(text):
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def shown(value, empty: str = CLEARED_WORD) -> str:
    if value is None:
        return empty
    return value if isinstance(value, str) else json.dumps(value)


def stored_values(conn: sqlite3.Connection):
    """Every value the rewrite looks at, for finding the old roots."""
    for row in conn.execute("SELECT plan_ref, output_ref, options FROM cards"):
        yield row["plan_ref"] or ""
        yield row["output_ref"] or ""
        yield as_json(row["options"]) or {}
    for row in conn.execute("SELECT data FROM events WHERE data LIKE '%_ref%'"):
        data = as_json(row["data"])
        if isinstance(data, dict):
            yield from (data.get(key) or "" for key in REF_FIELDS)


def free_text(conn: sqlite3.Connection):
    """What the import never rewrites, for counting mentions."""
    for row in conn.execute("SELECT brief, blocked_reason FROM cards"):
        yield row["brief"] or ""
        yield row["blocked_reason"] or ""
    for row in conn.execute("SELECT text, data FROM events"):
        yield row["text"] or ""
        data = as_json(row["data"])
        if isinstance(data, dict):
            yield json.dumps({k: v for k, v in data.items() if k not in REF_FIELDS})
    for row in conn.execute("SELECT question, why, words, message FROM asks"):
        yield from (row[name] or "" for name in ("question", "why", "words", "message"))


# ----- one card -----

def ref_edits(card, roots) -> list[Edit]:
    out = []
    for name in REF_FIELDS:
        new = importpaths.moved(card[name] or "", roots)
        if new is not None:
            out.append(Edit("cards", card["id"], name, card[name], new,
                            [f"cards/{card['id']} {name}: {card[name]} -> {new}"]))
    return out


def option_edit(card, roots) -> tuple[Edit | None, dict]:
    options = as_json(card["options"]) or {}
    new, changes = importpaths.rewrite(options, roots, "options")
    lines = [f"cards/{card['id']} {where}: {old} -> {moved}" for where, old, moved in changes]
    for name in CLEARED:
        if name in new:
            lines.append(f"cards/{card['id']} options.{name}: {shown(new.pop(name))} -> {CLEARED_WORD}")
    if not lines:
        return None, options
    return Edit("cards", card["id"], "options", card["options"], json.dumps(new), lines), options


def session_rule(card, options: dict, ctx: Context) -> str | None:
    """Why this card's session id does not come along, or None when it does."""
    if card["stage"] == "done" or not card["session_id"]:
        return None
    if card["space"] == "personal":
        where = options.get(PIN_OPTION) or "the source"
        return f"imported: the session stayed on {where}; Resume starts fresh from the card dir"
    if card["space"] == "work" and not ctx.work_kept:
        return (f"imported: the session is in the old Claude dir, not {ctx.work_dir}; "
                f"Resume starts fresh from the card dir")
    return None


def tree_dirs(card, ctx: Context) -> list[tuple[str, Path]]:
    """`(repo key, worktree)` as the install derives them (`adapters.worktree_dirs`)."""
    keys = adapters.repos_of(dict(card))
    return [(key, ctx.state / "worktrees" / (card["id"] if index == 0 else f"{card['id']}-{key}"))
            for index, key in enumerate(keys)]


def repo_here(key: str, ctx: Context) -> Path | None:
    path = ctx.repos.get(key) or (ctx.projects / key if ctx.projects else None)
    return path if path is not None and (path / ".git").exists() else None


def branch_in(repo: Path, card_id: str) -> str | None:
    try:
        return adapters.card_branch(repo, {"id": card_id})
    except adapters.AdapterError:
        return None


def tree_rules(card, ctx: Context, plan: Plan) -> list[str]:
    """Each worktree of an open personal card that had one: cut again here, or a reason."""
    if card["space"] != "personal" or card["stage"] not in WORKED_STAGES or card["stage"] == "done":
        return []
    reasons = []
    for key, path in tree_dirs(card, ctx):
        repo = repo_here(key, ctx)
        branch = branch_in(repo, card["id"]) if repo else None
        if branch:
            plan.recuts.append({"card": card["id"], "repo": str(repo), "path": str(path), "branch": branch})
            continue
        if repo is None:
            reasons.append(f"imported: repo {key} is not on this machine")
            continue
        # an older Keel's card branch, under the name it cut it with
        wanted = adapters.branch_name(adapters.LEGACY_BRANCH, card["id"], "*")
        reasons.append(f"imported: branch {wanted} is on the source")
        there = ctx.box_repos.get(key, f"<{key} on the source>")
        plan.fetches.append(f"git -C {repo} fetch {ctx.box}:{there} "
                            f"'+refs/heads/{wanted}:refs/heads/{wanted}'")
    return reasons


def absent(card_id: str, options: dict) -> list[str]:
    """Option paths on a box home that are not on this machine (said, not changed)."""
    return [f"cards/{card_id} {where}: {text} is not on this machine"
            for where, text in walk(options, "options")
            if text.startswith(BOX_HOME) and not Path(text).exists()]


def walk(value, where: str):
    """`(where, string)` for every string in a JSON value."""
    if isinstance(value, str):
        yield where, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from walk(item, f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, f"{where}[{index}]")


def card_plan(card, ctx: Context, plan: Plan) -> None:
    moved = ctx.space_map.get(card["space"])
    if moved:
        plan.edits.append(Edit("cards", card["id"], "space", card["space"], moved,
                               [f"cards/{card['id']} space: {card['space']} -> {moved}"]))
    plan.edits += ref_edits(card, plan.roots)
    edit, options = option_edit(card, plan.roots)
    if edit:
        plan.edits.append(edit)
    plan.absent += absent(card["id"], json.loads(edit.new) if edit else options)
    reasons = []
    why = session_rule(card, options, ctx)
    if why:
        plan.edits.append(Edit("cards", card["id"], "session_id", card["session_id"], None,
                               [f"cards/{card['id']} session_id: {card['session_id']} -> {CLEARED_WORD}"]))
        reasons.append(why)
    reasons += tree_rules(card, ctx, plan)
    if reasons:
        plan.blocks[card["id"]] = reasons
        new = "; ".join(([card["blocked_reason"]] if card["blocked_reason"] else []) + reasons)
        plan.edits.append(Edit("cards", card["id"], "blocked_reason", card["blocked_reason"], new,
                               [f"cards/{card['id']} blocked_reason: {shown(card['blocked_reason'], '(none)')} -> {new}"]))


# ----- events and asks -----

def event_edits(conn, roots) -> list[Edit]:
    out = []
    for row in conn.execute("SELECT id, card, data FROM events WHERE data LIKE '%_ref%' ORDER BY id"):
        data = as_json(row["data"])
        if not isinstance(data, dict):
            continue
        lines, new = [], dict(data)
        for name in REF_FIELDS:
            moved = importpaths.moved(data.get(name) or "", roots) if isinstance(data.get(name), str) else None
            if moved is not None:
                new[name] = moved
                lines.append(f"events/{row['id']} ({row['card']}) data.{name}: {data[name]} -> {moved}")
        if lines:
            out.append(Edit("events", row["id"], "data", row["data"], json.dumps(new), lines))
    return out


def ask_edits(conn) -> list[Edit]:
    out = []
    for row in conn.execute("SELECT id, claimed_by, claimed_at FROM asks WHERE state = 'open' "
                            "AND (claimed_by IS NOT NULL OR claimed_at IS NOT NULL) ORDER BY n"):
        for name in ("claimed_by", "claimed_at"):
            if row[name] is not None:
                out.append(Edit("asks", row["id"], name, row[name], None,
                                [f"asks/{row['id']} {name}: {row[name]} -> {CLEARED_WORD}"]))
    return out


def request_edits(conn) -> list[Edit]:
    """A waiting request's taker was Bosun on the old machine, which starts fresh: open again."""
    out = []
    for row in conn.execute("SELECT id, state, taken_by FROM requests WHERE state IN ('open', 'taken') "
                            "AND taken_by IS NOT NULL ORDER BY n"):
        out.append(Edit("requests", row["id"], "taken_by", row["taken_by"], None,
                        [f"requests/{row['id']} taken_by: {row['taken_by']} -> {CLEARED_WORD}"]))
        if row["state"] == "taken":
            out.append(Edit("requests", row["id"], "state", "taken", "open",
                            [f"requests/{row['id']} state: taken -> open"]))
    return out


def dropped_relays(conn, host: str) -> list[dict]:
    """Every relay no `carried` names yet, addressed to a host that is not this install."""
    rows = conn.execute(
        "SELECT * FROM events AS r WHERE r.kind = 'relay' AND NOT EXISTS (SELECT 1 FROM events AS c "
        "WHERE c.card = r.card AND c.kind = 'carried' AND json_extract(c.data, '$.relay') = r.id) "
        "ORDER BY r.id").fetchall()
    out = []
    for row in rows:
        data = as_json(row["data"]) or {}
        if data.get("to") != host:
            out.append({"relay": row["id"], "card": row["card"], "what": data.get("what"), "to": data.get("to")})
    return out


# ----- the whole board -----

def plan(conn: sqlite3.Connection, roots: dict[str, str], ctx: Context) -> Plan:
    out = Plan(roots=roots)
    for card in conn.execute("SELECT * FROM cards ORDER BY created_at, id").fetchall():
        card_plan(card, ctx, out)
    out.edits += event_edits(conn, roots)
    out.edits += ask_edits(conn)
    out.edits += request_edits(conn)
    out.dropped = dropped_relays(conn, ctx.host)
    out.mentions = sum(importpaths.mentions(text, roots) for text in free_text(conn))
    return out


def recut(item: dict) -> str | None:
    """`git worktree add` for one card; the error when git refuses, else None."""
    path = Path(item["path"])
    if (path / ".git").exists():
        return None
    try:
        adapters.git(Path(item["repo"]), "worktree", "add", str(path), item["branch"])
    except adapters.AdapterError as error:
        return str(error)
    return None


def failed_recut(edits: list[Edit], card_id: str, error: str) -> None:
    """A recut git refused blocks the card instead, said in its blocked_reason."""
    why = f"imported: its worktree could not be cut again ({error.splitlines()[0]})"
    for edit in edits:
        if edit.table == "cards" and edit.key == card_id and edit.column == "blocked_reason":
            edit.new = f"{edit.new}; {why}"
            return
    edits.append(Edit("cards", card_id, "blocked_reason", None, why, [f"cards/{card_id} blocked_reason: (none) -> {why}"]))


def drop(conn, item: dict) -> None:
    """A relay for another host marked carried (superseded), as a drain would, so this
    install's drain never acts on a tap meant for a machine that is gone."""
    conn.execute("INSERT INTO events (card, at, kind, actor, text, data) VALUES (?, ?, 'carried', "
                 "'drain', ?, ?)", (item["card"], board_now(), f"{DROPPED}: it was for {item['to']}",
                                    json.dumps({"relay": item["relay"], "outcome": "superseded"})))


def build(source: Path, target: Path, edits: list[Edit], dropped=()) -> None:
    """The source copied to `target` through sqlite's backup, migrated (opening it as a
    Board does that), every edit made in one transaction (each refused unless the column
    still holds the source's value), then checked."""
    target.unlink(missing_ok=True)
    with connect_ro(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    src.close()
    dst.close()
    board = Board(target)
    try:
        with board.tx() as conn:
            for edit in edits:
                one(conn, edit)
            for item in dropped:
                drop(conn, item)
        board.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        verdict = board.conn.execute("PRAGMA integrity_check").fetchone()[0]
        board.conn.execute("PRAGMA journal_mode=DELETE")
    finally:
        board.close()
    if verdict != "ok":
        raise sqlite3.DatabaseError(f"the imported board fails integrity_check: {verdict}")


def one(conn, edit: Edit) -> None:
    key = KEYS[edit.table]
    found = conn.execute(f"SELECT {edit.column} FROM {edit.table} WHERE {key} = ?", (edit.key,)).fetchone()
    if found is None or found[0] != edit.old:
        raise sqlite3.IntegrityError(f"{edit.table}/{edit.key} {edit.column} is not what the plan read")
    conn.execute(f"UPDATE {edit.table} SET {edit.column} = ? WHERE {key} = ?", (edit.new, edit.key))
