"""Close idle house (c-607): his tap that ends a house the harness lists as idle, to give its
memory back, knowing it comes back by itself when it is next needed.

His words (2026-09-30): "if I know that I am not going to review now or I don't expect any
activity right now then I can close it, and it will just pick it up with 5 to 15 seconds
delay". So it is a human stop, like Stop session, with a different mark on its note
(`closed-idle`, `board.MARKS`), and a different afterwards:

- **Stop session** (c-605's `human-stop`) holds the house down until his Resume or Retry:
  the drain's resume of an exited house passes it over and a review batch waits for it.
- **Close idle house** (`closed-idle`) is passed over by the drain's resume of an exited
  house too (`drain.reconcile`: closing it was the point), but the next review batch at
  shipping (`shipping.deliver`), a gate tap of his on the card (`actions.resume_with`) or
  his Resume brings it back with `claude --resume`, its conversation continuing.

Only ever an IDLE house: the deck offers it only while the harness lists the house out of a
turn, and every check here is made again when the tap lands (`not_idle`), on the listing of
the machine that holds the house (the deck's own, or its door's `house` answer, and once
more by that machine's drain when it carries the relay). A house that is working, has a
background job of its own running, is open in a terminal or is being talked to by voice is
refused with the reason. The drain writes the relay's note only when it carries his tap,
and ends an idle house of its own accord in three cases alone (`keel/shipidle.py`), each
by `close_here`: a merged card's idle house (ask a-72, `merged-end`, final), a shipping
house the harness has listed idle for over two hours since its own Stop (ask a-72), and a
shipping house whose turn on its re-offered batch has ended (his word, c-651; what that
turn left unjudged is handed to him, c-654); the last two with this same mark, so the next
batch brings the house back.
"""

from keel import adapters, dropin, harness, house, housejobs, tellhouse, views

VERB = "house.close_idle"
MARK = "closed-idle"
# c-607 review: only where something brings the house back by itself: at review his gate
# answer (or Resume), at shipping the next review batch. At planning or building nothing
# would, so a closed house there would sit until he noticed; Stop session is his way there.
STAGES = ("review", "shipping")
# What the card says once the house is closed (the deck's house word says it too), by stage.
CLOSED_SAID = "closed while idle: the next review or your tap resumes it (about 5 to 15 s)"
SAID_BY_STAGE = {"shipping": CLOSED_SAID,
                 "review": "closed while idle: your answer at the gate or your Resume brings it "
                           "back (about 5 to 15 s)"}


# The kinds of refusal (`NotIdle.kind`, `refusal`), for a caller that decides by WHICH it
# is and never by its words (`shipidle.before_batch`, c-666): the sentences are for his tap.
TELLING, RELAY, DROPIN, NO_PROCESS, TERMINAL = "telling", "relay", "dropin", "no-process", "terminal"
WORKING, VOICE, JOB = "working", "voice", "job"
STAGE, NO_SESSION, STOP_FAILED = "stage", "no-session", "stop-failed"


class NotIdle(Exception):
    """The house may not be closed as idle now; the message says why, and `kind` which
    reason it is."""

    def __init__(self, why: str, kind: str | None = None):
        super().__init__(why)
        self.kind = kind


def closed_said(stage: str | None) -> str:
    return SAID_BY_STAGE.get(stage or "", CLOSED_SAID)


def not_idle(card: dict, row: dict | None, config_dir=None, cfg=None) -> str | None:
    """Why this house may not be closed as idle now, or None when it may. `row` is the
    listing's row for the card's session (or a door's `row_facts` of it); `config_dir`,
    when the house is on this machine, lets its own background jobs be seen; `cfg`, there
    too, lets a tell in flight be seen (`tellhouse.telling`, c-607 review: the message takes
    7 to 17 s and its turn start is recorded only after it). One rule for his tap, the drain
    carrying it, and both of the drain's own ends (`keel/shipidle.py`)."""
    found = refusal(card, row, config_dir, cfg)
    return found[1] if found else None


def refusal(card: dict, row: dict | None, config_dir=None, cfg=None) -> tuple[str, str] | None:
    """`not_idle` with its kind: `(kind, the sentence)`, or None when the house may be closed."""
    if cfg is not None and tellhouse.telling(cfg, card["id"]):
        return TELLING, "a message is being sent to it right now"
    if (card.get("derived") or {}).get("relays"):
        return RELAY, "a tap of the user's is on its way to it"
    if views.dropin_hold(card.get("options")):
        return DROPIN, "the user is in it, or about to be, at a terminal (Drop in)"
    if row is None or not housejobs.has_process(row):
        return NO_PROCESS, "the harness lists no live session for it"
    if row.get("kind") == dropin.INTERACTIVE:
        return TERMINAL, "it is open in a terminal; close it there"
    if housejobs.working(row):
        return WORKING, "the house is working (the harness lists it in a turn); Stop session interrupts it"
    if views.voice_hold(card.get("options")):
        return VOICE, "voice is talking to it"
    if config_dir is not None and housejobs.of_row(config_dir, row):
        return JOB, "it is idle, but a background job of its own is running; Stop session ends both"
    return None


def close_here(cfg, board, card_id: str, stages=STAGES, strict: bool = False) -> tuple[dict, str, list[dict]]:
    """Every close on the house's own machine (his tap here, the drain carrying it, the
    drain's own ends): UNDER THE CARD'S LOCK, which `tellhouse.deliver` holds for its decision
    and its in-flight mark, the card and a fresh listing are read, `not_idle` is asked, and
    the house is stopped. So a close and a tell serialize: a tell decided first is seen in
    flight and the close is refused; a close first leaves an exited house the tell resumes.
    Raises NotIdle with the reason. Returns the card, the stopped id and the jobs it ended.
    `strict`: a listing that fails raises `harness.HarnessError`, for the one caller that
    acts on the refusal's kind (`shipidle.before_batch`) and must not take a failed
    listing for "no live session"."""
    with house.card_lock(cfg, card_id):
        card = board.get(card_id)
        if card["stage"] not in stages:
            raise NotIdle(f"it is at {card['stage']}, where nothing would bring it back; "
                          f"Stop session ends it", STAGE)
        if not card.get("session_id"):
            raise NotIdle("it has no recorded house session", NO_SESSION)
        config_dir = adapters.space_of(cfg, card).config_dir
        row = harness.find(card["session_id"], harness.agents(config_dir, strict=strict))
        why = refusal(card, row, config_dir, cfg)
        if why:
            raise NotIdle(why[1], why[0])
        bg_id = row.get("id") or card["session_id"][:8]
        try:
            ended = housejobs.stop(bg_id, config_dir, harness.stop)
        except harness.HarnessError as error:
            raise NotIdle(f"the stop failed: {str(error).splitlines()[0]}", STOP_FAILED) from None
        return card, bg_id, ended


def said(bg_id: str, ended: list[dict], host: str | None = None, stage: str | None = None) -> str:
    """The note his tap leaves, marked `closed-idle`."""
    by = f", carried by {host}" if host else ""
    text = f"session {bg_id} {closed_said(stage)}{by}"
    jobs = housejobs.said(ended)
    return text + (f"; {jobs}" if jobs else "")
