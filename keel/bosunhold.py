"""Bosun's voice hold (c-523, BO-5): one row on the board saying voice is talking to Bosun.

A house's hold is `options.voice_hold` on its card (`keel/converse.py`). Bosun has no card,
so its hold is the one row of the board's `holds` table keyed `bosun`, with the same shape
(`at`, `until`, `stopped`, `turns`) and read by the same rule (`views.voice_hold`): an
expired hold is not a hold, it is a conversation nobody is having any more. His answer at
c-523's plan gate put it on the board rather than in `state/console.json`, because the board
is Keel's one store, and the Mac reaches it over HTTP the way it reaches every card.

WHO READS IT. `keel/bosuntalk.py` takes and releases it (the box's `keel converse bosun`),
the Mac's door refuses a Bosun conversation the board does not say is held, the Mac's drain
clears one that ran out and wakes Bosun, his Console taps end the conversation before they
act, the deck's state says `voice` (`deckstate.console_entry`), and the voice digest says
it to Harbor.

WHO WRITES IT. The same actors as a card's hold (`board.HOLD_ACTORS`: voice, the drain, him).
A house is refused by actor; Bosun is refused too, because a Bosun that held itself would be
telling the drain and his taps to leave it alone.

`kb console held` reads it; `kb console hold [--seconds N] [--stopped yes|no] [--turns N]`
takes or refreshes it; `kb console hold --release` clears it.
"""

import json
from datetime import datetime, timedelta

from keel import views
from keel.board import HOLD_ACTORS, Board, Refused

NAME = "bosun"
SUBS = ("held", "hold")
USAGE = "held | hold [--seconds <n>] [--stopped yes|no] [--turns <n>] [--release]"
ARGUMENTS = ((("--seconds",), {"type": int, "metavar": "n",
                               "help": "hold: how long it holds before it runs out"}),
             (("--stopped",), {"choices": ("yes", "no"),
                               "help": "hold: whether taking it stopped Bosun's session"}),
             (("--turns",), {"type": int, "metavar": "n", "help": "hold: exchanges so far"}),
             (("--release",), {"action": "store_true", "help": "hold: clear it"}))
# The fields the wire carries for these sub-verbs (`requests.argv`, `remote.BODIES`).
WIRE = ("seconds", "stopped", "turns")
DEFAULT_SECONDS = 300


def raw(board: Board) -> dict | None:
    """The row as written, live or run out; None when there is none."""
    row = board.conn.execute("SELECT hold FROM holds WHERE name = ?", (NAME,)).fetchone()
    if row is None:
        return None
    try:
        held = json.loads(row[0])
    except ValueError:
        return {}
    return held if isinstance(held, dict) else {}


def as_options(held: dict | None) -> dict:
    return {views.VOICE_HOLD_OPTION: held} if held is not None else {}


def live(board: Board) -> dict | None:
    """Bosun's LIVE hold, or None: the reading every caller asks."""
    return views.voice_hold(as_options(raw(board)))


def expired(board: Board) -> dict | None:
    """The hold when it has run out: what the drain clears."""
    return views.voice_hold_expired(as_options(raw(board)))


def refuse(actor: str) -> None:
    if actor not in HOLD_ACTORS:
        raise Refused(f"Bosun's voice hold is voice's, the drain's or the user's to write; not {actor}'s")


def take(board: Board, actor: str, seconds: int = DEFAULT_SECONDS, stopped: bool | None = None,
         turns: int | None = None) -> dict:
    """Take or refresh it; `at` is set once and `stopped` once, exactly as a card's hold."""
    refuse(actor)
    now = datetime.now().astimezone()
    with board.tx():
        # A ROW THAT RAN OUT IS NOT CARRIED INTO A NEW HOLD: its `at`, `stopped` and `turns`
        # were another conversation's. The caller repairs it first (`bosuntalk.connect`).
        held = dict(raw(board) or {}) if live(board) else {}
        held["until"] = (now + timedelta(seconds=seconds)).isoformat(timespec="seconds")
        held.setdefault("at", now.isoformat(timespec="seconds"))
        if stopped is not None:
            held.setdefault("stopped", stopped)
        if turns is not None:
            held["turns"] = turns
        board.conn.execute(
            "INSERT INTO holds (name, hold, updated_at) VALUES (?, ?, ?) ON CONFLICT(name) "
            "DO UPDATE SET hold = excluded.hold, updated_at = excluded.updated_at",
            (NAME, json.dumps(held), board.now()))
    return held


def release(board: Board, actor: str) -> dict | None:
    """Clear it; the hold as it stood, which says whether Bosun is to be woken."""
    refuse(actor)
    with board.tx():
        held = raw(board)
        board.conn.execute("DELETE FROM holds WHERE name = ?", (NAME,))
    return held


def command(board: Board, args, actor: str) -> dict:
    if args.sub == "held":
        return board.bosun_hold_state()
    if args.release:
        return {"released": release(board, actor)}
    stopped = None if args.stopped is None else args.stopped == "yes"
    return {"hold": take(board, actor, args.seconds or DEFAULT_SECONDS, stopped=stopped,
                         turns=args.turns)}


def render(args, payload: dict) -> str:
    if args.sub == "held":
        held = payload["hold"]
        if held:
            return f"voice holds Bosun until {held.get('until')} ({held.get('turns') or 0} exchanges)"
        return "run out, not yet cleared" if payload["expired"] else "voice does not hold Bosun"
    if "released" in payload:
        return "released" if payload["released"] is not None else "there was no hold"
    return f"voice holds Bosun until {payload['hold']['until']}"

