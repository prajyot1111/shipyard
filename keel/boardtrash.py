"""Deleting a board: the trash, the restore and the purge (lane BD, 2026-09-24).

His words: "I need an option to delete boards too." Until this a board could only be closed,
and closing keeps it in every list. A delete is a MOVE, not a flag:
`state/boards/<b-id>/` goes to `state/boards/.trash/<b-id>/`, whole. That is the choice that
keeps every reader simple (BD-1): `boards.records` walks `state/boards/` and never matches
`.trash`, and `boards.read_record` opens `<b-id>/`, so the list, the search, a card's boards,
its stacks, the live board and the voice gateway's receipt all stop seeing it without one of
them being told. A `deleted_at` on the record would have had to be checked by every one of
those, and the one that forgot would show a deleted board.

WHO MAY DELETE, said once, here (`may_delete`). A house deletes only boards whose source is
its OWN card, Harbor only its own talker boards, and every other board is his alone: a
caller that is neither a house on that card, the talker on its own, nor him proved by his
token is refused, exactly as `--actor human` is. Every delete, by anyone, lands in the trash,
the record says who did it and when (`deleted`), and only he restores.

THE PURGE is the drain's upkeep (`drain.board_trash_upkeep`), never a request: a board in the
trash for more than `KEEP_DAYS` days is removed, and `<b-id>.purged` stays behind so the id is
never minted again (an embed or a link that still names it must not open somebody else's
board). Until then the trash is under `state/`, so the `keel` backup set carries it.
"""

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from keel import boards
from keel.config import human_token, same_secret

KEEP_DAYS = 30
TOMBSTONE = ".purged"


def trash_root(cfg) -> Path:
    return boards.root(cfg) / boards.TRASH_DIR


def trash_dir(cfg, board_id: str) -> Path:
    boards.board_dir(cfg, board_id)                 # the id's own check, and its refusal
    return trash_root(cfg) / board_id


def stamp(cfg) -> int:
    """The trash's own change stamp: a board moved in or out moves it. One stat, for the
    plan page's tag, whose embeds change when a board is deleted or restored."""
    try:
        return trash_root(cfg).stat().st_mtime_ns
    except OSError:
        return 0


def trashed_record(cfg, board_id: str) -> dict | None:
    """The record of a board in the trash, or None when it is not there."""
    try:
        return json.loads((trash_dir(cfg, board_id) / boards.BOARD_FILE).read_text())
    except (OSError, ValueError):
        return None


def write_at(directory: Path, record: dict) -> None:
    """The record, written whole and moved into place, wherever the board now sits."""
    temp = directory / f"{boards.TEMP_PREFIX}{boards.BOARD_FILE}"
    temp.write_text(json.dumps(record, indent=1) + "\n")
    os.replace(temp, directory / boards.BOARD_FILE)


# ----- who may -----

def whose(source: dict) -> str:
    if source.get("kind") == "card":
        return f"{source.get('card')}'s board"
    return "the talker's board"


def may_delete(board_id: str, record: dict, caller: dict | None) -> None:
    """A house its own card's boards, the talker its own, him any; nobody else anything."""
    caller = caller or {}
    source = record.get("source") or {}
    card = caller.get("card")
    if card:
        if source.get("kind") == "card" and source.get("card") == str(card):
            return
        raise boards.BoardError(f"{card} may delete only its own card's boards, and {board_id} "
                                f"is {whose(source)}")
    if caller.get("actor") == "talker":
        if source.get("kind") == "talker":
            return
        raise boards.BoardError(f"the talker may delete only its own boards, and {board_id} "
                                f"is {whose(source)}")
    if caller.get("actor") == "human":
        return
    raise boards.BoardError(f"deleting {whose(source)} is the user's: from the deck, or with KEEL_TOKEN "
                            f"at the desk")


def may_restore(caller: dict | None) -> None:
    if (caller or {}).get("actor") != "human":
        raise boards.BoardError("a board comes back from the trash only by the user's hand: the deck's "
                                "Restore, or keel board restore with KEEL_TOKEN at the desk")


def local_caller(cfg) -> dict:
    """`boards.local_caller`, with a terminal that holds his token counted as him.

    Every other `keel board` verb treats a bare terminal as him; delete and restore do not,
    because they are the two verbs whose rule is "his alone" (BD-1)."""
    caller = boards.local_caller()
    if caller["actor"] == "cli" and not caller.get("card"):
        token = os.environ.get("KEEL_TOKEN") or ""
        if token and same_secret(token, human_token(cfg.token_path)):
            caller = dict(caller, actor="human")
    return caller


# ----- the verbs -----

def delete(cfg, board_ids: list[str], caller: dict | None) -> dict:
    """Move these boards to the trash. Every one is checked before any is moved, so a stack
    holding one board that is not the caller's is refused whole."""
    ids = list(dict.fromkeys(str(board_id) for board_id in board_ids))
    if not ids:
        raise boards.BoardError("delete names at least one board")
    with boards.store_lock(cfg):
        found = [(board_id, boards.read_record(cfg, board_id)) for board_id in ids]
        for board_id, record in found:
            may_delete(board_id, record, caller)
        rows = [move_to_trash(cfg, record, caller) for _board_id, record in found]
    return {"deleted": rows, "count": len(rows)}


def move_to_trash(cfg, record: dict, caller: dict | None) -> dict:
    """One board into the trash, with who did it. A board that was its source's LIVE board
    stops being live by leaving: the live board is the newest open one in `state/boards/`."""
    was_live = boards.row_of(cfg, record)["live"]
    record["deleted"] = {"at": boards.now(), "by": boards.who(caller),
                         "actor": (caller or {}).get("actor") or "cli"}
    boards.write_record(cfg, record)
    trash_root(cfg).mkdir(parents=True, exist_ok=True)
    os.replace(boards.board_dir(cfg, record["id"]), trash_dir(cfg, record["id"]))
    return dict(trash_row(record), live_cleared=was_live)


def restore(cfg, board_id: str, caller: dict | None) -> dict:
    """Bring a board back from the trash, his alone. Its `updated` is left as it was, so a
    restore puts it back where it stood rather than making it live over a newer one."""
    may_restore(caller)
    with boards.store_lock(cfg):
        record = trashed_record(cfg, board_id)
        if record is None:
            boards.read_record(cfg, board_id)       # "no board called" when there is none
            raise boards.BoardError(f"{board_id} is not in the trash")
        if boards.board_dir(cfg, board_id).exists():
            raise boards.BoardError(f"{board_id} is already on the board list")
        record.pop("deleted", None)
        record["restored"] = {"at": boards.now(), "by": boards.who(caller)}
        write_at(trash_dir(cfg, board_id), record)
        os.replace(trash_dir(cfg, board_id), boards.board_dir(cfg, board_id))
        return boards.row_of(cfg, record)


def purge_at(record: dict) -> str:
    try:
        when = datetime.fromisoformat((record.get("deleted") or {}).get("at") or "")
    except (TypeError, ValueError):
        return ""
    return (when + timedelta(days=KEEP_DAYS)).isoformat()


def trash_row(record: dict) -> dict:
    return {"id": record["id"], "title": record.get("title") or "",
            "summary": record.get("summary") or "", "source": record.get("source") or {},
            "actor": record.get("actor") or "", "created": record.get("created"),
            "updated": record.get("updated"), "closed": record.get("closed"),
            "nodes": record.get("nodes") or 0, "attachments": record.get("attachments") or 0,
            "live": False, "deleted": record.get("deleted") or {}, "purge_at": purge_at(record)}


def trashed(cfg) -> list[dict]:
    """Every board in the trash, the most recently deleted first."""
    base = trash_root(cfg)
    if not base.is_dir():
        return []
    rows = []
    for entry in base.iterdir():
        if boards.ID_RE.match(entry.name) and entry.is_dir():
            record = trashed_record(cfg, entry.name)
            if record is not None:
                rows.append(trash_row(record))
    return sorted(rows, key=lambda row: (row["deleted"].get("at") or "", row["id"]), reverse=True)


def purge(cfg, now: datetime | None = None) -> list[str]:
    """Remove every board deleted more than `KEEP_DAYS` days ago; the ids it removed.

    A board whose delete stamp cannot be read is KEPT: the purge is the one thing here that
    cannot be undone, so it acts only on a date it can read."""
    now = now or datetime.now(timezone.utc)
    gone = []
    with boards.store_lock(cfg):
        for row in trashed(cfg):
            try:
                deleted = datetime.fromisoformat(row["deleted"].get("at") or "")
            except (TypeError, ValueError):
                continue
            if deleted.tzinfo is None:
                deleted = deleted.replace(tzinfo=timezone.utc)
            if now - deleted <= timedelta(days=KEEP_DAYS):
                continue
            shutil.rmtree(trash_dir(cfg, row["id"]))
            (trash_root(cfg) / f"{row['id']}{TOMBSTONE}").touch()
            gone.append(row["id"])
    return sorted(gone)


def deleted_block(cfg, board_id: str) -> dict | None:
    """What an embed of a deleted board shows instead of it (BD-2), or None."""
    record = trashed_record(cfg, board_id)
    if record is None:
        return None
    return dict(record.get("deleted") or {}, id=board_id, title=record.get("title") or "",
                purge_at=purge_at(record))


def render_deleted(payload: dict) -> str:
    lines = []
    for row in payload.get("deleted") or []:
        line = f"{row['id']}  in the trash, restorable until {row['purge_at'][:10]}"
        if row.get("live_cleared"):
            line += "  (it was the live board; the next push starts or continues another)"
        lines.append(line)
    return "\n".join(lines) or "nothing deleted"
