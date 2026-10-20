"""Which text of a tier file the user adopted or saved (c-678 review F3).

Keel reads commands out of a repo's CLAUDE.md and runs them (`keel/repocommands.py`), so the
file that is read has to be one the user put there. Two taps put a tier there, and each
leaves the user's note with `data(path, text)`: the file's real path and the sha256 of the
text that was WRITTEN (an adopted draft loses its audit notes on the way, so the draft's own
digest would never match the file):

- Adopt (`onboarding.adopt_locked`), on the proposal's card, beside where it went.
- Save on the Setup page (`onboarding.save_tier`), which has no card: `saved` records it
  under `SAVES`, an id no card has, the way an ask's or a request's events sit in the same
  table under theirs.

`held(cfg, path, board)` is the file's text when it is the newest recorded text for that
path, else None: edited by hand, by a session, or written before records were kept.
`standing(board, path)` tells those apart, for the sentence and for the drafts list:
`held` (its lines run), `changed` (a record exists and the file is no longer that text) and
`never` (no record: a file from before records were kept, or written by hand). Only
the user's own note counts (`kind = 'note'`, `actor = 'human'`), so a house or the builder
cannot record one. `read` is the one-read form the commands use: the standing and the text
it was decided on. The lookup has an index of its own (`events_tier`, `keel/board.py`).
The template written when a repo is copied records nothing; it names no command. A caller
with only the config is handed its own board for the one query; one that holds a board
passes it (a state build, a tap, the push worker), so none is opened for the record.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

SAVES = "setup"
NEWEST = ("SELECT json_extract(data, '$.written') FROM events WHERE kind = 'note' AND actor = 'human' "
          "AND json_extract(data, '$.tier') = ? ORDER BY id DESC LIMIT 1")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def data(path: Path | str, text: str) -> dict:
    """What a note carries so `held` finds it: the tier's real path and the written text's digest."""
    return {"tier": os.path.realpath(path), "written": digest(text)}


def saved(board, path: Path, text: str) -> None:
    """The user's Save of `path` with `text`, recorded under `SAVES`."""
    with board.tx():
        board.record_event(SAVES, "note", "human", text=f"saved {path}", data=data(path, text))


def newest(board, path: Path | str) -> str | None:
    """The digest of the text the user last adopted or saved at `path`, or None."""
    row = board.conn.execute(NEWEST, (os.path.realpath(path),)).fetchone()
    return row[0] if row else None


HELD, CHANGED, NEVER = "held", "changed", "never"


def standing(board, path: Path | str) -> str:
    """`held`, `changed` or `never`: how the file at `path` stands against its record."""
    recorded = newest(board, path)
    if recorded is None:
        return NEVER
    try:
        return HELD if digest(Path(path).read_text()) == recorded else CHANGED
    except OSError:
        return CHANGED


def read(cfg, path: Path, board=None) -> tuple[str, str | None]:
    """`(standing, text)` of the file at `path`, from ONE read of it: the text that was
    checked against the record is the text the caller parses (review r2.F9). The text is
    None for a file that cannot be read, which stands as `changed` where a record exists."""
    try:
        text = Path(path).read_text()
    except OSError:
        text = None
    if board is not None:
        recorded = newest(board, path)
    else:
        from keel.board import open_board     # noqa: PLC0415 - the board opens with the config's switches
        with open_board(cfg) as own:
            recorded = newest(own, path)
    if recorded is None:
        return NEVER, text
    return (HELD if text is not None and digest(text) == recorded else CHANGED), text


def stands(cfg, path: Path, board=None) -> str:
    """`standing`, for a caller with only the config."""
    if board is not None:
        return standing(board, path)
    from keel.board import open_board     # noqa: PLC0415 - the board opens with the config's switches
    with open_board(cfg) as own:
        return standing(own, path)


def held(cfg, path: Path, board=None) -> str | None:
    """The file's text when it is what the user last adopted or saved there, else None."""
    try:
        text = Path(path).read_text()
    except OSError:
        return None
    if board is not None:
        return text if newest(board, path) == digest(text) else None
    from keel.board import open_board     # noqa: PLC0415 - the board opens with the config's switches
    with open_board(cfg) as own:
        return text if newest(own, path) == digest(text) else None
