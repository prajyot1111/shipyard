"""What the next full fetch pass would file, read and never written (c-742).

A fetch role that starts after a long gap files cards nobody watched it decide: one errand
card per segment whose asks waited, and one card per `[recurring.<key>]` that came due.
Each is at most one (`keel/fetch.py`'s asks are batched per segment, and `keel/recurring.py`
holds the next card of a key back while one is open), and this says which, before the pass:

- `keel fetch --preview` prints it and exits, on any config, a live install's included;
- the role logs the same lines, as `first pass: ...`, before the first pass of every start.

It reads the segments tree, the config and the board, the board through a read-only
connection, and decides with the same functions the pass uses (`fetch.read_worker`,
`recurring.due`). It runs no fetcher, so an ask a fetcher writes during the pass is not
counted, and the last line says so.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

from keel import fetch, recurring
from keel.config import Config


def board(cfg: Config) -> SimpleNamespace | None:
    """The board, read-only, as the one thing `recurring.due` asks of it (`conn`); None when
    there is no board yet."""
    if not cfg.db_path.exists():
        return None
    conn = sqlite3.connect(f"{cfg.db_path.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return SimpleNamespace(conn=conn)


def cards_today(found: SimpleNamespace | None, segment: str, today: str) -> int:
    """`fetch.cards_today`, as one read: this segment's cards created today."""
    if found is None:
        return 0
    return found.conn.execute(
        "SELECT COUNT(*) FROM cards WHERE json_extract(options, '$.segment') = ? "
        "AND substr(created_at, 1, 10) = ?", (segment, today)).fetchone()[0]


def ask_line(cfg: Config, found, segment, today: str) -> tuple[str, bool] | None:
    """One segment's asks: (the line, whether a card would be filed), or None with none."""
    pending = fetch.pending_asks(segment)
    if not pending or not (segment / "worker.md").is_file():
        return None
    waiting = f"asks {segment.name}: {len(pending)} ask{'' if len(pending) == 1 else 's'}"
    try:
        worker = fetch.read_worker(segment, set(cfg.spaces))
    except ValueError as why:
        return f"{waiting} wait, no card: {why}", False
    spent = cards_today(found, segment.name, today)
    if spent >= worker.daily_cap:
        return f"{waiting} wait, no card: daily cap reached ({spent}/{worker.daily_cap})", False
    return f"{waiting}, one card in {worker.space}", True


def recurring_line(found, key: str, table: dict, now: datetime) -> tuple[str, bool]:
    due, why = (recurring.due(found, key, table["every_days"], now) if found is not None
                else (True, "no card has carried it yet"))
    if due:
        return f"recurring {key}: one card in {table['space']}, \"{table['title']}\" ({why})", True
    return f"recurring {key}: no card ({why})", False


def lines(cfg: Config, now: datetime | None = None) -> list[str]:
    """What a full pass started now would do, one line each, the count of cards last."""
    now = now or datetime.now(timezone.utc)
    names = [path.name for path in fetch.fetchers(cfg)]
    said = [f"fetchers: {len(names)} would run" + (f" ({', '.join(names)})" if names else "")]
    found = board(cfg)
    try:
        today = now.astimezone().date().isoformat()
        rows = [ask_line(cfg, found, segment, today) for segment in fetch.segments(cfg)]
        rows = [row for row in rows if row]
        rows += [recurring_line(found, key, table, now) for key, table in cfg.recurring.items()]
    finally:
        if found is not None:
            found.conn.close()
    count = sum(1 for _, files in rows if files)
    said += [line for line, _ in rows]
    said.append(f"cards: {count} would be filed, at most one for each line above "
                f"(an ask a fetcher writes during the pass is not counted)")
    return said
