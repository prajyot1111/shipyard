"""The drain's three ends of an IDLE house: two decided with him on ask a-72 (c-607), and
one on his explicit word for a re-offered batch (c-651), with what that batch's turn left
unjudged handed to him (c-654).

His answer (2026-09-30, a-72, A): "merge to done ends the card's idle house, and a shipping
house idle over 2 h is stopped; the next comment batch resumes it with its full
conversation; never a working house". All three are a drain step (`drain.idle_upkeep`) over
the pass's own listing, and each checks the house again on a fresh listing right before the
stop:

- **A merge made the card done** (`shipping.merged`: its pull request merged). Its house has
  nothing left to answer, so once the harness lists it idle it is ended (`merged-end` on the
  note), final: a done card is never resumed. A house that is working is left, and a later
  pass ends it once it is idle; the step finds it again by the card's own record (done, its
  shipping record's `facts` state `merged`, c-793, its session still listed), so nothing else remembers it.
- **A shipping house idle over `[keel] ship_idle_hours`** (2 by default, c-633) is closed as his Close idle house closes one
  (`closed-idle`, `keel/idleclose.py`): the next review batch, his gate answer or his Resume
  brings it back with `claude --resume`. Idle is the harness's word (listed, not in a turn,
  no background job of its own, not in a terminal, no voice hold, `idleclose.not_idle`), and
  the age is the board's own record of the turn ending: the current session's newest `Stop`
  hook with no turn started since (`views.turn_ended`). A house with no such record is never
  closed: how long it has been quiet is not evidence (CLAUDE.md, never infer stuck).
- **A shipping house whose turn on its re-offered batch has ended** (c-651, his explicit
  word: idle houses must not hold memory; `keel/shipreoffer.py`): the newest batch is the one
  `kb ship <id> reoffer` asked for, and by the board's order of events its own turn (the
  first turn start after it was told) has had its first `Stop`, with no turn started since.
  Closed at once, the same way and with the same mark, and only once (`closed_at`); once a
  later turn has started (his Talk, his Resume, his voice or his Drop in) the re-offer is
  over (`done_at`) and closes nothing. A normal batch keeps the two hours above.

A turn that ended is not an answer (c-654; c-151's house ended its turn with none of four
items judged and the note said "answered"). When the re-offered batch's turn ends, the
items of that batch with no verdict since they were told are counted
(`shipreplies.unjudged`). With any, the note says N of M were left unjudged, the mark keeps
their handles (`unjudged`) and the card is blocked for him under a mark of its own
(`unjudged`, `board.MARKS`; his, not mechanics, so no repair of Bosun's lifts it): the
watcher still looks at that card for a merge or a decline, and tells its house nothing
until he unblocks it (`shipping.watched`). The move to done lifts the block in its own
write, the items being moot (`Board._clear_stale_block`). Nothing
tells them again by itself, so there is no loop to bound: unblocked, his
`kb ship <id> reoffer` offers exactly those again.

The turn has ended, for this, in three ways (`close_reoffered`): its `Stop` with the house
listed idle, which is closed; the harness saying the session itself ended (`SessionEnd`);
and its `Stop` with the session listed no more and no `SessionEnd` on the board (a reboot,
a killed process). The last two close nothing, and are the cases that look at a card whose
session the pass's listing does not hold. A FAILED LISTING SETTLES NOTHING, anywhere in
this module: the plain listing answers a failure with an empty one, so the third way asks
the harness again and strictly (`unlisted`), and the watcher's early call below lists
strictly for the close too.

Only a RE-OFFERED batch is settled this way. A normal batch's house is kept two hours
after its turn ends so that a later turn can finish the judging: a house at shipping ends
a turn to ask him something, or while a background job of its own runs, and nothing nudges
it at a `Stop` there (`Board.stop_check` owns one rule, at building). Blocking the card at
that `Stop` would hand him a batch the house was still on. What a normal batch left
unjudged is the pane's "judging N", and his `kb ship <id> reoffer` offers it again.

A batch due behind a re-offer does not skip this (c-666, `before_batch`). The watcher
runs before this step, so a batch told on the pass after the re-offered turn ended moved
`round` past the mark, and nothing here saw a re-offer to settle. So the watcher, about to
tell a batch behind an open re-offer whose turn has ended, calls this module FIRST, for
that one card, in that pass, and `close_reoffered`'s own body (`settle_reoffered`) runs on
a strict listing, under the card's lock as any close:

- **Closed, or gone**: exactly the bookkeeping above (the close, the count, the note, the
  unjudged block). A card it blocked is told nothing until he unblocks it. A house it
  closed is told nothing on that pass and resumed by the batch on the next: `claude stop`
  returns before the listing lets the session go, and a tell decides from that listing.
  For the same reason the watcher names it to the drain (`result["closed"]`), which adds
  it to this step's skip set for the pass, so the two-hour close cannot stop it again.
- **The listing failed**: nothing is settled and nothing is told to that card on that
  pass. This is the one wait here, and it lasts until the listing answers.
- **The close is refused**, and what follows is decided by the KIND of refusal
  (`idleclose.NotIdle.kind`), never by its words:
  - a background job of the house's own, or a session open in his terminal: the re-offer
    is over (`done_at`, through `Board.mark_reoffer`), and when items of it have no
    verdict yet ONE note states that fact (`NOT_CLOSED_FACTS`, no tap advice) and names
    them, saying the house may still be judging them. No stop and no block: nothing
    automatic ends a house that is not idle, and a block at a bare `Stop` would be the
    false alarm described below. The batch is then taken as usual, and that house is an
    ordinary shipping house, kept by the two-hour rule.
  - a listed row with NO process (or a session gone between the two listings): that house
    is not running, so nothing can still be judging. It is the "gone" case above, with its
    count, its mark and its unjudged block (`NOT_RUNNING`). Safe without a new hook: this
    function is reached only once the batch's `Stop` or `SessionEnd` is on the board.
    Written under the card's lock too (`settle_gone`), which his Resume of that house
    holds while it starts the session: the lock is never waited for (busy, the card waits
    this pass), and under it the board is read again, so a resume on record by then makes
    the turn read over and nothing of "gone" is written.
  - the stop itself failed: nothing is settled and nothing is told on that pass, like a
    failed listing; the next pass tries again, as this step always did, and the card says
    so once (`STOP_FAILED_NOTE`), since review waits behind it.
  - the house is working (it started a turn between the two listings): nothing is
    written, and `shipping.deliver`'s own wait holds the batch until that turn ends.
  - anything else (a message or a tap of his on its way, a hold, a card that left
    shipping): nothing is written and nothing is held; the batch goes on to `deliver`,
    which does with it what it does on a card with no re-offer.

Every wait above is one line in `drain.log` with its reason, as `deliver`'s waits are.

Nothing is kept from one pass to the next, so nothing can go stale: each pass decides
from the board and a fresh listing. A card in the pass's skip set (the drain already
acted on its house in this pass) is left for the next pass, as this step leaves it. This
step, later in the same pass, finds the mark settled and does nothing more.

The deck says when the close is due before it happens (`derived.ship_idle`: "idle 1h40m,
closes at 2h", or "closes now" for a re-offer whose turn ended), so he is never surprised.
"""

from datetime import datetime, timedelta

from keel import (harness, house, housejobs, idleclose, shipreoffer, shipreplies, shipwatch, tellhouse,
                  terms, views)
from keel.board import SENDBACK_OPTION, SHIPPING_OPTION
from keel.config import Config

MERGED_MARK = "merged-end"
ENDED_NOTE = ("the {change} merged, so its idle house {bg} is ended: a done card "
              "is not resumed")
CLOSED_NOTE = ("session {bg} was idle at shipping for {age} (its turn ended {since}), so the "
               "drain closed it: " + idleclose.CLOSED_SAID)
REOFFER_NOTE = ("session {bg} ended its turn on its re-offered batch and is idle, so the drain "
                "closed it (an idle house does not hold memory): " + idleclose.CLOSED_SAID)
# c-654: a turn that ended with items unjudged is said as that, never as answered.
UNJUDGED_NOTE = ("session {bg} ended its turn on re-offered batch {batch} with {left} left unjudged "
                 "and is idle, so the drain closed it (an idle house does not hold "
                 "memory): " + idleclose.CLOSED_SAID)
UNJUDGED_BLOCK = ("the house's turn on re-offered batch {batch} {how} with {left} left unjudged "
                  "({handles}). Nothing tells them to it again by itself: the card needs "
                  "your re-offer. Unblock it, then `kb ship {id} reoffer` offers them again. Until "
                  "you unblock it no review is told to its house; its merge is still seen")
HOW = {shipreoffer.ENDED: "ended", shipreoffer.EXITED: "ended when its session did"}
UNLISTED = "ended, and its session is listed no more"
NOT_RUNNING = "ended, and its session is no longer running"
# c-666: a re-offer ended because a batch is due behind it and its house could not be
# closed as idle, for one of the two reasons a house can still be judging under. The note
# states the fact, by the refusal's kind (never the tap advice of `idleclose.not_idle`'s
# sentence); it stops and blocks nothing, promises no tell, and invites no re-offer.
NOT_CLOSED_FACTS = {idleclose.JOB: "a background job of its own is still running",
                    idleclose.TERMINAL: "it is open in your terminal"}
NOT_CLOSED_NOTE = ("the house's turn on re-offered batch {batch} ended and the house was not closed "
                   "as idle: {fact}. {left} of that batch {have} no verdict yet ({handles}); the house "
                   "may still be judging {them}. Nothing was stopped and the card is not blocked")
# Why `before_batch` tells a card nothing on a pass, as `drain.log` says it.
WAIT_SKIPPED = "the drain already acted on its house in this pass, so its re-offer is settled on the next"
WAIT_LISTING = "the listing failed, so its re-offer is not settled and nothing is told to it"
WAIT_STOP = "the stop of its idle house failed, so its re-offer is not settled; tried again on the next pass"
WAIT_LOCK = "its card's lock is held (a resume of its house is under way), so its re-offer is settled on the next pass"
# A stop that keeps failing holds the review behind it, so the card says it, once
# (`shipping.note_held_batch`): `why` is the harness's own line. It promises only what
# always holds: the settlement, not a tell, since a batch that left items unjudged blocks
# the card once the stop goes through.
STOP_FAILED_NOTE = ("Shipyard could not stop this idle house ({why}) and keeps trying. Its re-offered batch "
                    "is settled once the stop goes through; the review items waiting behind it are told "
                    "after that, or after your unblock if that batch left items unjudged")
WAIT_CLOSED = "its idle house was closed for the re-offer on this pass; the batch resumes it on the next"
WAIT_BLOCKED = "its re-offered batch left items unjudged, so the card is blocked for the owner"
WAIT_OPEN = "its re-offer could not be settled on this pass"


def now() -> datetime:
    return datetime.now().astimezone()


def ours(cfg: Config, card: dict, served: set[str], skip) -> bool:
    """A card with a session, in a space this pass serves."""
    return (bool(card.get("session_id")) and card["space"] in served and card["id"] not in skip
            and not card["derived"]["archived"])


def merged_done(card: dict) -> bool:
    """Done because its change merged. The watcher records the merge in the shipping
    record's `facts` (`shipwatch.fold`); `state` is where it was once read from, and nothing
    writes it with "merged" (c-793: read only there, this end never fired)."""
    shipped = (card.get("options") or {}).get("shipping") or {}
    return card["stage"] == "done" and "merged" in (shipped.get("state"), (shipped.get("facts") or {}).get("state"))


def end_merged(cfg: Config, board, card: dict) -> bool:
    """End a merged card's house if it is idle now, by the one rule a close asks, under the
    card's lock (`idleclose.close_here`); False (a later pass tries again) if not."""
    try:
        card, bg_id, ended = idleclose.close_here(cfg, board, card["id"], stages=("done",))
    except idleclose.NotIdle:
        return False
    jobs = housejobs.said(ended)
    said = terms.say(terms.of(cfg, card.get("space")), ENDED_NOTE).format(bg=bg_id)
    board.note(card["id"], said + (f"; {jobs}" if jobs else ""), "drain",
               mark=MERGED_MARK)
    return True


def idle_age(board, card: dict, at: datetime) -> timedelta | None:
    """How long the card's current session has been out of its turn, by the board's record."""
    since = views.turn_ended(reversed(board.events(card["id"])), card.get("session_id"))
    return at - since if since is not None else None


def close_idle(cfg: Config, board, card: dict, at: datetime) -> bool:
    """Close a shipping house idle over `cfg.ship_idle_hours`, checked again under the card's lock."""
    age = idle_age(board, card, at)
    if age is None or age < timedelta(hours=cfg.ship_idle_hours):
        return False
    try:
        card, bg_id, ended = idleclose.close_here(cfg, board, card["id"], stages=("shipping",))
    except idleclose.NotIdle:
        return False
    since = (at - age).astimezone().strftime("%H:%M")
    hours, minutes = divmod(int(age.total_seconds() // 60), 60)
    text = CLOSED_NOTE.format(bg=bg_id, age=f"{hours}h{minutes:02d}m", since=since)
    jobs = housejobs.said(ended)
    board.note(card["id"], text + (f"; {jobs}" if jobs else ""), "drain", mark=idleclose.MARK)
    return True


def close_reoffered(cfg: Config, board, card: dict, at: datetime, listed: bool = True) -> bool:
    """The idle step's settlement of a re-offer (`settle_reoffered`): True when a house was
    closed."""
    return settle_reoffered(cfg, board, card, at, listed)[0]


def settle_reoffered(cfg: Config, board, card: dict, at: datetime, listed: bool = True,
                     strict: bool = False, gone: str | None = None) -> tuple[bool, idleclose.NotIdle | None]:
    """Close a shipping house whose turn on its re-offered batch has ended (c-651, his word):
    an idle house must not hold memory. The batch's own turn is found by the board's order of
    events (`shipreoffer.batch_turn`); once a later turn has started the re-offer is over and
    closes nothing. Checked again under the card's lock, as any close; the mark it leaves
    (`Board.mark_reoffer`) keeps a close to once, so his Resume is not closed again.

    What the turn left unjudged is his (c-654). `listed`: the pass's listing holds the
    session; one it does not hold has nothing to close, and is settled when the harness
    said it ended (`EXITED`) or when its turn ended and the harness, asked again, does not
    list it (`unlisted`). A house that was stopped always gets its note, whatever became of
    the mark meanwhile; the block is written only with the mark, so once per batch.

    Whether a house was closed, and the refusal when the close of a listed house whose
    turn ended was refused (`idleclose.NotIdle`, with its `kind`), else None. `strict` (the
    watcher's early call, `before_batch`): the close lists strictly and a listing that
    fails raises `harness.HarnessError`, with nothing written. `gone` (that call too): its
    own strict listing shows no running session, in these words (`UNLISTED`,
    `NOT_RUNNING`), so no close is tried and a turn that ended is settled as gone."""
    shipped = (card.get("options") or {}).get(SHIPPING_OPTION) or {}
    if not shipreoffer.is_reoffer(shipped):
        return False, None
    mark = shipped[shipreoffer.RECORD_KEY]
    events = board.events(card["id"])
    state, started = shipreoffer.batch_turn(mark, events)
    fields = {"started": started} if started and not mark.get("started") else {}
    ended = state == shipreoffer.ENDED
    closed, why = close_now(cfg, board, card["id"], strict) if ended and listed and not gone else (None, None)
    how = (gone or UNLISTED) if ended else HOW.get(state)
    gone = state == shipreoffer.EXITED or (ended and (bool(gone) or (not listed and unlisted(cfg, card))))
    if closed is not None:
        fields["closed_at"] = shipwatch.stamp(at)
    elif gone or state == shipreoffer.OVER:
        fields["done_at"] = shipwatch.stamp(at)
    left = shipreplies.unjudged(card, events, mark["batch"]) if closed is not None or gone else []
    if left:
        fields["unjudged"] = left
    marked = bool(fields) and board.mark_reoffer(card["id"], mark["batch"], fields)
    count = left_of(card, mark["batch"], left)
    if closed is not None:
        note_closed(board, card["id"], mark["batch"], closed, count if left else None)
    if marked and left:
        how = how if closed is None else HOW[state]
        board.block(card["id"], UNJUDGED_BLOCK.format(batch=mark["batch"], how=how, left=count, id=card["id"],
                                                      handles=", ".join(left)), "drain",
                    mark=shipreoffer.UNJUDGED_MARK)
    return closed is not None, why


def left_of(card: dict, batch: int, left: list[str]) -> str:
    """"2 of 3 items": how many of a batch's told items have no verdict."""
    total = len(shipreplies.batch_items(card, batch))
    return f"{len(left)} of {total} {'item' if total == 1 else 'items'}"


def before_batch(cfg: Config, board, card: dict, shipped: dict, at: datetime, slots: int,
                 skipped: bool = False) -> tuple[dict, str | None, bool]:
    """The watcher, about to tell a batch behind an open re-offer whose turn has ended
    (c-666): settle that re-offer first, here and now. The record as it stands after; why
    the card is told nothing on this pass, or None when it may be; and whether its house
    was closed here (the idle step must not look at it again on this pass).

    Only where a batch WOULD be told: something is due or he sent something back, the card
    is not blocked, declined or paused, there is a slot, and a strict listing shows the
    house out of a turn. Everywhere else `shipping.deliver` waits by its own rules and the
    idle step settles the re-offer meanwhile, as it always did; a re-offer whose turn has
    not ended is not this function's. The outcomes, by the kind of the close's refusal, are
    the module's own words above."""
    asks = (card.get("options") or {}).get(SENDBACK_OPTION)
    if not shipreoffer.is_reoffer(shipped) or not (asks or shipwatch.due(shipped, at)):
        return shipped, None, False
    if cfg.drain_paused or card.get("blocked_reason") or shipped.get("state") == "declined" or slots <= 0:
        return shipped, None, False
    if not card.get("session_id") or not shipreoffer.turn_done(shipped, board.events(card["id"])):
        return shipped, None, False
    if skipped:
        return shipped, WAIT_SKIPPED, False
    as_now = dict(card, options=dict(card.get("options") or {}, **{SHIPPING_OPTION: shipped}))
    try:
        row = harness.find(card["session_id"], harness.agents(cfg.spaces[card["space"]].config_dir, strict=True))
        if housejobs.working(row):
            return shipped, None, False       # a later turn of its own: `deliver` waits for it
        live = housejobs.has_process(row)
        closed, refused = settle_reoffered(cfg, board, as_now, at, strict=True) if live else (False, None)
    except harness.HarnessError:
        return shipped, WAIT_LISTING, False
    kind = refused.kind if refused else None
    if not live or kind == idleclose.NO_PROCESS:      # not running, now or by the close's own listing
        if not settle_gone(cfg, board, card["id"], at, UNLISTED if row is None else NOT_RUNNING):
            return shipped, WAIT_LOCK, False
    elif kind == idleclose.STOP_FAILED:
        from keel import shipping     # noqa: PLC0415 - shipping builds on this module
        shipping.note_held_batch(board, card["id"], STOP_FAILED_NOTE.format(why=str(refused).partition(": ")[2]))
        return shipped, WAIT_STOP, False
    elif kind in NOT_CLOSED_FACTS:
        end_unclosed(board, as_now, at, NOT_CLOSED_FACTS[kind])
    elif refused:
        return shipped, None, False           # working, or a refusal that is not this function's
    held = board.get(card["id"])
    mark = ((held.get("options") or {}).get(SHIPPING_OPTION) or {}).get(shipreoffer.RECORD_KEY)
    if mark is not None:
        shipped = dict(shipped, **{shipreoffer.RECORD_KEY: mark})   # the mark as the board holds it now
    wait = (WAIT_CLOSED if closed else WAIT_BLOCKED if held.get("blocked_reason")
            else WAIT_OPEN if shipreoffer.is_reoffer(shipped) else None)
    return shipped, wait, closed


def settle_gone(cfg: Config, board, card_id: str, at: datetime, how: str) -> bool:
    """A re-offer whose turn ended and whose house is not running (`how`: `UNLISTED`,
    `NOT_RUNNING`), settled as gone UNDER THE CARD'S LOCK, which his Resume of that house
    holds while it starts the session and before it records its turn. The lock is never
    waited for: False when it is busy, and the card waits this pass. Under it the card is
    read again: with a turn on record since (the re-offer's reads over), a message being
    sent or a tap of his on its way, nothing is written."""
    try:
        with house.card_lock(cfg, card_id, wait=False):
            card = board.get(card_id)
            shipped = (card.get("options") or {}).get(SHIPPING_OPTION) or {}
            if (shipreoffer.turn_done(shipped, board.events(card_id)) and not tellhouse.telling(cfg, card_id)
                    and not (card.get("derived") or {}).get("relays")):
                settle_reoffered(cfg, board, card, at, gone=how)
    except house.LockBusy:
        return False
    return True


def on_its_batch(cfg: Config, card: dict) -> bool:
    """Is the card's house, by a strict listing, a session with a process behind it: one
    that can be ON a batch? True when the listing fails (nothing is concluded from that).
    A session listed no more, and a listed row with no process, are on nothing."""
    try:
        rows = harness.agents(cfg.spaces[card["space"]].config_dir, strict=True)
    except harness.HarnessError:
        return True
    return housejobs.has_process(harness.find(card.get("session_id") or "", rows))


def end_unclosed(board, card: dict, at: datetime, fact: str) -> None:
    """A re-offer whose turn ended and whose house was not closed for a reason it can still
    be judging under (`fact`, `NOT_CLOSED_FACTS`), with a batch about to be told behind it:
    over (`done_at`, laid over the board's mark by `Board.mark_reoffer`), and, when items
    of it have no verdict yet, one note saying why the house was not closed, which items,
    and that it may still be judging them. No stop, no block, and nothing on the mark that
    only the note needs."""
    batch = card["options"][SHIPPING_OPTION][shipreoffer.RECORD_KEY]["batch"]
    left = shipreplies.unjudged(card, board.events(card["id"]), batch)
    if board.mark_reoffer(card["id"], batch, {"done_at": shipwatch.stamp(at)}) and left:
        one = len(left) == 1
        board.note(card["id"], NOT_CLOSED_NOTE.format(
            batch=batch, fact=fact, left=left_of(card, batch, left), handles=", ".join(left),
            have="has" if one else "have", them="it" if one else "them"), "drain")


def note_closed(board, card_id: str, batch: int, closed: tuple, left: str | None) -> None:
    """The note of a house the drain stopped once its turn on a re-offered batch ended: that
    the turn ended, never that the batch was answered, and N of M left unjudged when any
    were. Written for every stop (c-654 review): a stop the card does not record reads as
    a house that exited on its own."""
    bg_id, stopped = closed
    text = UNJUDGED_NOTE.format(bg=bg_id, batch=batch, left=left) if left else REOFFER_NOTE.format(bg=bg_id)
    jobs = housejobs.said(stopped)
    board.note(card_id, text + (f"; {jobs}" if jobs else ""), "drain", mark=idleclose.MARK)


def unlisted(cfg: Config, card: dict) -> bool:
    """Does the harness, asked now and strictly, list no session for this card? False when
    the listing fails: `harness.agents` answers a failed listing with an empty one, and an
    empty listing must never be read as "its session is gone"."""
    try:
        rows = harness.agents(cfg.spaces[card["space"]].config_dir, strict=True)
    except harness.HarnessError:
        return False
    return harness.find(card["session_id"], rows) is None


def close_now(cfg: Config, board, card_id: str,
              strict: bool = False) -> tuple[tuple | None, idleclose.NotIdle | None]:
    """The house stopped by the one rule a close asks (`idleclose.close_here`), as `(its id,
    the jobs ended)`, or None and the refusal (`idleclose.NotIdle`, with its `kind`)."""
    try:
        _card, bg_id, stopped = idleclose.close_here(cfg, board, card_id, stages=("shipping",), strict=strict)
    except idleclose.NotIdle as refused:
        return None, refused
    return (bg_id, stopped), None


def upkeep(cfg: Config, board, rows: list[dict], served: set[str], skip=frozenset(),
           at: datetime | None = None) -> dict:
    """One pass: the merged cards' idle houses ended, the shipping houses whose turn on a
    re-offered batch ended or that idled too long closed. Only a card whose session this
    pass's listing holds is looked at again, but for a re-offer whose turn ended and whose
    session is listed no more (c-654: nothing is closed there, and what it left unjudged is
    his)."""
    at, done = at or now(), {"ended": [], "closed": []}
    for card in board.list_cards(stage="done") + board.list_cards(stage="shipping"):
        if not ours(cfg, card, served, skip):
            continue
        tended = card["stage"] == "shipping" and not card.get("blocked_reason")
        if harness.find(card["session_id"], rows) is None:
            if tended:
                close_reoffered(cfg, board, card, at, listed=False)
        elif merged_done(card) and end_merged(cfg, board, card):
            done["ended"].append(card["id"])
        elif tended and (close_reoffered(cfg, board, card, at) or close_idle(cfg, board, card, at)):
            done["closed"].append(card["id"])
    return done
