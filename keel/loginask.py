"""The login ask: a red row on the Logins list, named on his Needs you with its fix (c-558).

A row of `keel/logins.py` that reads expired or missing raises one ask, raiser `drain`: the
drain calls `sync` for this machine's rows every pass, and it is idempotent: at most one ask per row per RED EPISODE, an episode being
everything since the row was last seen good (`good_at`). So an ask he answered Later is not
raised again while the row stays red, and a row that works and then fails again asks anew.

The ask is withdrawn by the drain the moment its row answers good (or, a voice key, reads
`unset`: it is optional, so no longer red), whatever he said. Option
A ("Logged in") carries the facts (`login`: the host, the row, its label and its one-liner),
which is how the deck draws the copy button on the ask itself. His answer is recorded and
never handed to Bosun as work (`asks.answer` marks it told at once, as it does the deploy
ask's): there is nothing for Bosun to carry out, since the row's own machine checks it again
within ten minutes of it going red (`logins.RED_EVERY`).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from keel import asks
from keel.board import Board

RAISER = "drain"
LOGIN_KEY = "login"
RECENT = 200            # the newest login asks a pass reads; each row has at most a few
RED = ("expired", "missing")
# A row that closes its open ask, and why: one that works, and a voice key no longer set,
# which is optional and so not red (c-560).
SETTLED = {"good": "{label} answers again", "unset": "{label} is no longer set"}


def facts_of(row: dict) -> dict | None:
    options = row.get("options") or []
    if isinstance(options, str):
        options = json.loads(options or "[]")
    first = options[0] if options else {}
    return first.get(LOGIN_KEY) if isinstance(first, dict) else None


def is_login(row: dict) -> bool:
    return facts_of(row) is not None


def question(row: dict) -> str:
    return f"Log {row['label']} back in on the {row['host']}?"[:asks.QUESTION_MAX]


def why(row: dict) -> str:
    said = f": {row['why']}" if row.get("why") else ""
    fix = f" The fix: {row['fix']}" if row.get("fix") else ""
    return (f"{row['label']} on the {row['host']} is {row['state']}{said}.{fix}")[:asks.WHY_MAX]


def options_for(row: dict) -> list[dict]:
    facts = {"host": row["host"], "id": row["id"], "label": row["label"],
             "fix": row.get("fix"), "where": row.get("where") or ""}
    return [{"letter": "A", "label": "Logged in",
             "does": (f"Nothing to carry out: the {row['host']} checks it again within ten "
                      f"minutes, and this ask closes itself when it answers."),
             LOGIN_KEY: facts},
            {"letter": "B", "label": "Later",
             "does": ("It stays red on the deck's health, and no new ask comes until it has "
                      "worked again.")}]


def raise_login(board: Board, row: dict) -> dict:
    with board.tx():
        aid, n = asks.next_id(board)
        at = board.now()
        board.conn.execute(
            "INSERT INTO asks (id, n, kind, actor, card, question, why, options, state, "
            "created_at, updated_at) VALUES (?, ?, 'approval', ?, NULL, ?, ?, ?, 'open', ?, ?)",
            (aid, n, RAISER, question(row), why(row), json.dumps(options_for(row)), at, at))
        asks.record(board, aid, None, "raised", RAISER, f"asked (login): {question(row)}",
                    host=row["host"], login=row["id"])
    return asks.get(board, aid)


def rows_for(board: Board, host: str) -> list[dict]:
    """This host's newest login asks, newest first."""
    found = board.conn.execute(
        "SELECT * FROM asks WHERE actor = ? AND options LIKE ? ORDER BY n DESC LIMIT ?",
        (RAISER, f'%"{LOGIN_KEY}": {{%', RECENT)).fetchall()
    return [one for one in (asks.as_dict(r) for r in found)
            if (facts_of(one) or {}).get("host") == host]


def withdraw(board: Board, ask: dict, reason: str) -> None:
    with board.tx():
        found = asks.get(board, ask["id"])
        if found["state"] != "open":
            return
        board.conn.execute("UPDATE asks SET state = 'withdrawn', words = ?, updated_at = ? "
                           "WHERE id = ?", (reason, board.now(), ask["id"]))
        asks.record(board, ask["id"], None, "withdrawn", RAISER, f"withdrawn: {reason}")


def instant(text) -> datetime | None:
    try:
        found = datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    return found if found.tzinfo else found.replace(tzinfo=timezone.utc)


def in_episode(ask: dict, good_at: datetime | None) -> bool:
    """The ask was raised since the row was last seen good (or it never was)."""
    raised = instant(ask.get("created_at"))
    return good_at is None or raised is None or raised > good_at


def sync(board: Board, host: str, rows: list[dict]) -> dict:
    """Raise, keep or withdraw this host's login asks to match its rows. Returns
    `{"raised": [ids], "withdrawn": [ids]}`. A row that is `unknown` changes nothing: a
    network blip is not the login working. Nor does a row red only for a mark no check has
    settled yet (`unverified`): words can mark falsely, and the drain checks a marked row
    first, on its next pass, and again at `RED_EVERY` while the checks answer unknown, until
    the mark is two of those old (c-560)."""
    if not hasattr(board, "conn") or not isinstance(rows, list):
        return {"raised": [], "withdrawn": []}
    held = rows_for(board, host)
    raised, gone = [], []
    listed = {row.get("id") for row in rows if isinstance(row, dict)}
    for row in rows:
        if not isinstance(row, dict) or not row.get("id") or not row.get("label"):
            continue
        row = dict(row, host=host)
        mine = [a for a in held if facts_of(a)["id"] == row["id"]]
        opened = [a for a in mine if a["state"] == "open"]
        if row.get("state") in RED and not row.get("unverified"):
            good_at = instant(row.get("good_at"))
            if not opened and not any(in_episode(a, good_at) for a in mine):
                raised.append(raise_login(board, row)["id"])
        elif row.get("state") in SETTLED:
            for ask in opened:
                withdraw(board, ask, SETTLED[row["state"]].format(label=row["label"]))
                gone.append(ask["id"])
    for ask in held:
        if ask["state"] == "open" and facts_of(ask)["id"] not in listed:
            withdraw(board, ask, "the machine no longer lists this login")
            gone.append(ask["id"])
    return {"raised": raised, "withdrawn": gone}
