"""Bosun woken for a paused house, and told of the work handed to it (c-584; c-593; c-734;
docs/atlas/96-bosun.md, "A paused house" and "Telling Bosun").

The drain blocks a house that auto mode paused on a permission prompt, marked
`permission-pause` (`keel/permpause.py`). That block, on ANY card in any space, wakes Bosun
once: `kb console wakes` lists the paused cards whose pause Bosun has not been told of, the
drain on Bosun's machine tells it (`consolewake.wake`, only when it is idle), and records a
`wake` event on each card with `kb console woke`, so one pause wakes it once. Bosun then
raises an ask naming the card (`bosun/memory/builder.md`, "A paused house").

TELLING BOSUN (c-734). The same wake carries the work the user hands Bosun from the deck: a
card the page files for Bosun to work with the user (a repo's or a space's CLAUDE.md draft,
a flow draft, a connection draft, the import), and every gate tap on a card Bosun builds
(Approve plan, Send back, Approve outcome), which resumes no house since such a card has
none. Each records a `tell` event on its card (`tell`, data `{what}`, one of `TELLS`); a
tell after the card's last `wake` is listed by `wakes` beside the pauses, and told the same
way, once. The second stranger run (2026-10-10) found a connection draft sitting at assigned
until the user nudged Bosun, and Approve plan on it answering "no session to resume".

This is what is left of the driven-card wakes (`keel/drive.py`, c-522), retired in c-593:
a house's plan, outcome, block, failed resume or review limit no longer wake Bosun. A tell
is the user's own tap on Bosun's own work, never a house's.
"""

import json

from keel import permpause
from keel.board import Board, Refused

SUBS = ("wakes", "woke")
USAGE = "wakes | woke --ids <c-N@event,...>"
WAKERS = ("drain",)
STATE = "paused"
SAID = "auto mode paused its house on a permission prompt"
# What a `tell` says to Bosun, by its `what`: fixed words only, since the message goes
# through a relay that may obey text it carries (`wake_prompt`).
TELLS = {"filed": "filed for you to work with the user",
         "plan": "the user approved its plan",
         "sendback": "the user sent it back",
         "outcome": "the user approved its outcome"}
# What the page says once a tell is recorded: the drain tells an idle Bosun on its next pass
TOLD = "Bosun is told at once, or as soon as it is free"
TOLD_NOTE = TOLD + "; no house is resumed for a card Bosun builds"


def is_pause(event: dict) -> bool:
    return event["kind"] == "block" and (event.get("data") or {}).get("paused") == "permission"


def told_up_to(events: list[dict]) -> int:
    """The newest event a wake told Bosun about: each `wake` records the event it covered, so
    a pause recorded while that wake was under way is still told on the next pass."""
    return max(((e.get("data") or {}).get("event") or 0 for e in events if e["kind"] == "wake"),
               default=0)


def pending(card: dict, events: list[dict]) -> dict | None:
    """The card's newest pause after the event its last wake covered, while the card is still
    blocked by it; None otherwise."""
    if not card.get("blocked_reason"):
        return None
    last_wake = told_up_to(events)
    for event in reversed(events):
        if event["id"] <= last_wake:
            return None
        if is_pause(event):
            return {"card": card["id"], "title": card["title"], "state": STATE, "said": SAID,
                    "event": event["id"], "at": event["at"], "text": event.get("text") or ""}
    return None


def wakes(board: Board) -> list[dict]:
    """Every card, in any space, whose house auto mode paused and Bosun was not yet told of,
    then every card with a tell Bosun was not yet told of (`tells`)."""
    found = []
    for card in board.list_cards(include_archived=False):
        if card["stage"] == "done" or not permpause.paused_block(card):
            continue
        waiting = pending(card, board.events(card["id"]))
        if waiting:
            found.append(waiting)
    return found + tells(board)


# ----- the tells (c-734) -----

# The newest tell of each card after the event its newest wake covered, by one read of the
# events table: a done card's outcome tell is told too, and the cards with none cost nothing.
PENDING_TELLS = (
    "SELECT e.card, e.id, e.at, e.data FROM events AS e "
    "WHERE e.kind = 'tell' AND e.id = (SELECT MAX(t.id) FROM events AS t WHERE t.card = e.card AND t.kind = 'tell') "
    "AND e.id > COALESCE((SELECT MAX(CAST(json_extract(w.data, '$.event') AS INTEGER)) FROM events AS w "
    "WHERE w.card = e.card AND w.kind = 'wake'), 0) ORDER BY e.id")


def what_of(data) -> str:
    """A stored tell's `what`; an unreadable one is said as a filing, the plainest news."""
    try:
        what = (json.loads(data or "{}") or {}).get("what")
    except ValueError:
        what = None
    return what if what in TELLS else "filed"


def tells(board: Board) -> list[dict]:
    """Every card whose newest tell Bosun was not yet told of, unarchived, as a wake's row."""
    found = []
    for row in board.conn.execute(PENDING_TELLS).fetchall():
        try:
            card = board.get(row["card"])
        except Refused:
            continue
        if (card.get("options") or {}).get("archived") is True:
            continue
        what = what_of(row["data"])
        found.append({"card": card["id"], "title": card["title"], "state": what, "said": TELLS[what],
                      "event": row["id"], "at": row["at"], "text": ""})
    return found


def tell(board: Board, card_id: str, what: str, actor: str = "human", cfg=None) -> int:
    """Record that Bosun is to be told `what` of the card, and (`cfg` given) ask for one
    ordinary drain pass now (`ask_pass`, r1.F18), whose wake tells an idle Bosun; the pass on
    the drain's clock is the fallback."""
    if what not in TELLS:
        raise Refused(f"a tell is one of {', '.join(TELLS)}, not {what!r}")
    with board.tx():
        board.get(card_id)
        event = board.record_event(card_id, "tell", actor, text=TELLS[what], data={"what": what})
    if cfg is not None:
        ask_pass(cfg)
    return event


def ask_pass(cfg) -> bool:
    """One ordinary pass, `keel drain --once`, as Approve outcome's landing asks for one
    (`actions.queue_landing`), started and not waited for, so the tap returns now. Only where
    a drain serves this install (its kick inbox is held, `kick.held_by_another`): no drain, no
    pass. It is an unscoped pass, so one started while another runs skips at once
    (`keel/passlock.py`) and passes never stack: the running pass, or the next on the drain's
    clock, tells Bosun. A pass keeps the drain's own rule of one wake a pass, and
    `consolewake` spaces wakes whatever starts them, so this never lands a second message on
    a Bosun just told. Never raises: the tell is recorded, and the next pass tells it."""
    import subprocess    # noqa: PLC0415 - only where a tap asks for a pass
    from keel import kick
    try:
        if not kick.held_by_another(kick.socket_path(cfg)):
            return False
        from keel.actions import deck_env    # noqa: PLC0415 - the deck's own environment for keel
        subprocess.Popen([str(cfg.root / "bin" / "keel"), "drain", "--once"], env=deck_env(cfg),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception:  # noqa: BLE001 - a pass asked for is a shortcut: the clock's pass is the fallback
        return False
    return True


def told(board: Board, card_id: str) -> bool:
    """Whether every tell on the card has reached Bosun (a card with none has nothing to tell)."""
    return not any(row["card"] == card_id for row in tells(board))


def woke(board: Board, told: list[str], actor: str) -> list[str]:
    """The wake's record on each card, `<card>@<event>`: the event it told Bosun about, so the
    same pause never wakes Bosun twice and one recorded after it (even mid-wake) does."""
    if actor not in WAKERS:
        raise Refused(f"woke is the drain's record of a wake, not {actor}'s")
    ids = []
    for item in told:
        card_id, _, event = item.partition("@")
        if not event.isdigit():
            raise Refused(f"woke takes <card>@<event>, as wakes gave it, not {item!r}")
        board.record_wake(card_id, actor, {"event": int(event)})
        ids.append(card_id)
    return ids


def wake_prompt(found: list[dict]) -> str:
    """The drain's message to Bosun: ids and fixed words ONLY. It goes through a model relay
    that may obey text it carries (c-530's probe), so nothing a house wrote (a title, a block
    reason, the user's words in a draft) is in it: Bosun reads each card on the board."""
    cards = ", ".join(f"{row['card']} ({row.get('said') or SAID})" for row in found)
    return f"Keel drain: new states on cards you watch, recorded on the board: {cards}."


# ----- the kb verb -----

def command(board: Board, args, actor: str) -> dict:
    if args.sub == "wakes":
        return {"wakes": wakes(board)}
    told = [c.strip() for c in str(args.ids or "").split(",") if c.strip()]
    return {"woke": woke(board, told, actor)}


def render(args, payload) -> str:
    if args.sub == "wakes":
        return "\n".join(f"{r['card']}: {r.get('said') or SAID}" for r in payload["wakes"]) or "nothing to wake for"
    return "woke for " + (", ".join(payload["woke"]) or "nothing")


# ----- on whichever board the caller holds -----

def call(board, actor: str, sub: str, **fields):
    """`wakes` and `woke` on the board."""
    if sub == "wakes":
        return wakes(board)
    return woke(board, fields["ids"], actor)
