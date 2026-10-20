"""What the Journal tab reads beside the moves (c-524, BO-6; docs/atlas/96-bosun.md).

- THROUGHPUT: per space, the cards that reached done in the last `DAYS` days. (The console
  space's in-flight count against its cap went with that space, c-593.)
- GAPS: every gap tag a resolved request carries (`keel/requests.py`), most requests first,
  with how each ended and when last, so the gaps Keel keeps hitting stand out. A tag named on
  `RECURRING` requests or more is recurring: the second time is a pattern, not news.

Both are reads of the board alone.
"""

from datetime import datetime, timedelta, timezone

from keel.board import Board

DAYS = 7
RECURRING = 2
HOWS = ("fixed", "filed", "declined", "escalated")


def moment(stamp: str) -> datetime:
    at = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def throughput(board: Board, spaces, now: str, days: int = DAYS) -> dict:
    """Cards moved to done inside the window, once each, by space (every space in `spaces`,
    even at nought): what the Journal's tiles draw."""
    since = moment(now) - timedelta(days=days)
    # Done is reached by a stage move and by a gate: his Approve outcome and a landing record
    # `approve` events (`Board._move`), both with `to: done` (c-524 review r2.F2). The date
    # floor keeps the json_extract and the rows to the window's; with no index on `at`, the
    # stage and approve events are still walked. Stamps are local ISO time with an offset
    # (`board.now`), so text order is time order only within a day: the day's margin covers
    # any offset, and the exact edge is checked below.
    floor = (since - timedelta(days=1)).astimezone(timezone.utc).strftime("%Y-%m-%d")
    rows = board.conn.execute(
        "SELECT DISTINCT e.card, c.space, e.at FROM events AS e JOIN cards AS c ON c.id = e.card "
        "WHERE e.kind IN ('stage', 'approve') AND e.at >= ? AND json_extract(e.data, '$.to') = 'done'", (floor,))
    done: dict[str, set] = {space: set() for space in spaces}
    for row in rows:
        if moment(row["at"]) >= since:
            done.setdefault(row["space"], set()).add(row["card"])
    return {"days": days, "done": {space: len(cards) for space, cards in done.items()}}


def gap_rows(board: Board) -> list[dict]:
    """One row per gap tag: how many requests ended under it, by how, when last, which."""
    rows = board.conn.execute(
        "SELECT id, n, gap, how, updated_at FROM requests WHERE gap IS NOT NULL ORDER BY n")
    tags: dict[str, dict] = {}
    for row in rows:
        tag = tags.setdefault(row["gap"], {"gap": row["gap"], "count": 0, "hows": {},
                                           "last": None, "requests": []})
        tag["count"] += 1
        tag["hows"][row["how"]] = tag["hows"].get(row["how"], 0) + 1
        tag["requests"].append(row["id"])
        if tag["last"] is None or row["updated_at"] > tag["last"]:
            tag["last"] = row["updated_at"]
    out = sorted(tags.values(), key=lambda tag: (-tag["count"], tag["gap"]))
    for tag in out:
        tag["recurring"] = tag["count"] >= RECURRING
    return out


def gap_line(tag: dict) -> str:
    """One gap as `kb console gaps` prints it."""
    hows = ", ".join(f"{tag['hows'][how]} {how}" for how in HOWS if tag["hows"].get(how))
    mark = "  recurring" if tag["recurring"] else ""
    return (f"{tag['gap']}  {tag['count']}{mark}  ({hows}; last {str(tag['last'])[:10]}; "
            f"{', '.join(tag['requests'])})")
