"""Recurring cards: work the fetch role files again on a schedule, decided from the board.

`[recurring.<key>]` in the install's config.toml names one: how often (`every_days`), and the card to file
(`space`, `title`, `brief`, and optionally `repo`, `autonomy`, `model`). Every card filed for
it carries `options.recurring = <key>`, and that is the whole memory. There is no schedule
file and no "last run" stamp: the next one is due when no card carrying the key is open and
the newest one reached `done` at least `every_days` ago. A key no card has ever carried is
due now. So a card that is still at review holds the next one back, however late it runs,
and the clock starts when the human closes it, not when a timer fired.

The first was the quarterly restore rehearsal (c-288), which c-622 retired with the
bootstrap it ran; no card ships recurring now.
"""

from datetime import datetime, timedelta, timezone

from keel import cardspec
from keel.board import Board
from keel.config import Config

OPTION = "recurring"


def carrying(board: Board, key: str) -> list[dict]:
    """Every card carrying the key, newest first, with when it reached done (or None)."""
    rows = board.conn.execute(
        "SELECT id, stage, updated_at FROM cards WHERE json_extract(options, '$.recurring') = ? "
        "ORDER BY created_at DESC, id DESC", (key,)).fetchall()
    found = []
    for row in rows:
        done_at = None
        if row["stage"] == "done":
            event = board.conn.execute(
                "SELECT at FROM events WHERE card = ? AND kind = 'stage' "
                "AND json_extract(data, '$.to') = 'done' ORDER BY id DESC LIMIT 1",
                (row["id"],)).fetchone()
            done_at = event["at"] if event else row["updated_at"]
        found.append({"id": row["id"], "stage": row["stage"], "done_at": done_at})
    return found


def parse_at(text: str) -> datetime:
    at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def due(board: Board, key: str, every_days: int, now: datetime | None = None) -> tuple[bool, str]:
    """Whether the key is due, and why, in one line for the fetch log."""
    now = now or datetime.now(timezone.utc)
    cards = carrying(board, key)
    if not cards:
        return True, "no card has carried it yet"
    open_ones = [card["id"] for card in cards if card["stage"] != "done"]
    if open_ones:
        return False, f"{', '.join(open_ones)} is still open"
    last = max(parse_at(card["done_at"]) for card in cards)
    next_at = last + timedelta(days=every_days)
    if now >= next_at:
        return True, f"the last one closed {(now - last).days} days ago"
    return False, f"next on {next_at.date().isoformat()}"


def file_card(board: Board, key: str, table: dict) -> str:
    return board.create(
        table["space"], table["title"], brief=table.get("brief", ""),
        autonomy=table.get("autonomy", "autonomous"), repo=table.get("repo"),
        model=table.get("model"), options={OPTION: key}, actor="fetch", stage="assigned")


def file_due(cfg: Config, board: Board | None = None, now: datetime | None = None) -> dict:
    """File every recurring card that is due. Returns {key: card id} for the ones filed."""
    if not cfg.recurring:
        return {}
    own = board is None
    board = board or Board(cfg.db_path, defaults=cardspec.defaults_from(cfg))
    filed = {}
    try:
        for key, table in cfg.recurring.items():
            is_due, _ = due(board, key, table["every_days"], now)
            if is_due:
                filed[key] = file_card(board, key, table)
    finally:
        if own:
            board.close()
    return filed


__all__ = ["OPTION", "carrying", "due", "file_card", "file_due"]
