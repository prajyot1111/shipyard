"""A house whose conversation the harness no longer holds starts afresh (c-654).

The harness keeps a transcript for its retention period only. A resume of a session whose
conversation is gone launches normally, keeps its id and ends four seconds later with no
turn (c-015, c-017, c-037 sat at "judging 1" for it), so the harness is asked BEFORE the
launch (`harness.conversation_gone`), and a house whose conversation is gone is started as a
new one from the card's own record (`start`, which is `house.launch` itself).

Replacing a card's session is not undone, so one answer of the harness is never enough
(c-654 review). A house is started afresh only when ALL of these hold (`wanted`):

1. **The harness lists no live process for the session.** The row is the one the resume's
   own busy check fetched. A live session is never asked about at all: it has a
   conversation by being alive, and a second house beside it would be a twin nothing owns.
   With no row the harness is asked again, strictly (`no_process`): a listing that failed
   answers an empty one, and that is never read as "no process".
2. **The harness says the conversation is gone**, asked in the directory the resume itself
   would run in (the resume's placement, the directory Drop in's command enters, the one a
   wake uses), by a probe that can use no tool and is killed whole after 15 seconds. A probe
   that overran or failed is "not gone".
3. **The board shows no turn the card's house really ran in the last `RECENT_DAYS` days**:
   no `Stop` hook and no `Notification`, whichever session id it carries. A resume mints a
   new id, so a session minted yesterday that died before its first Stop has no turn of its
   own while the card shows the conversation in use the day before (`last_used`). Only
   those hooks are use. A `resume` or `session` event and a `SessionEnd` are not: the
   doomed resume of a gone conversation writes exactly a resume and then a SessionEnd,
   with no Stop (c-015, c-017 and c-037 on 2026-10-05, last really used 32 or more days
   before), and those must start afresh. The harness keeps a transcript 30 days by
   default, so a conversation that ran a turn two weeks ago and is reported gone is two
   facts that disagree, and Keel does not pick one: the card is blocked for him with both
   (`RECENT`), the session and the one before it named, nothing started, nothing stopped.

**At most one fresh start stands unproven** (`TWICE`). A house started afresh whose own
session never ran a turn (no `Stop`, blocked or not, and no `Notification` of it), and
whose conversation the harness then says is gone too, is the launch that exits in its
first seconds, the class this card is about: a second fresh start is refused and the card
blocked with both sessions named. The drain's once-only automatic resume is spent by a
fresh start as by any resume (`house.auto_resume_spent` reads the note `start` leaves), so
its next pass blocks the card and starts nothing.

**Both blocks are HIS, and his unblock is his answer** (`answered`). Each has its own mark
(`afresh-withheld`, `afresh-twice`, `board.MARKS`) with no `mechanics` in it, so Bosun's
unblock, resume and retry repairs are refused on it by the rule that is already there
(`repair.refuse_unless_mechanics`), and each carries the session it is about. Once HE has
unblocked it, the next resume, Drop in or open in app starts the house afresh, conditions
1 and 2 still required: one start, for that session. The answer is durable. A caller that
catches the refusal and blocks again on top (Bosun's resume repair, were it let in) only
restates it, and is looked past; the callers Keel owns leave the block standing instead
(`Withheld.said`: `shipping.put_back`, `drain.carry_resume`, `landing.refused_here`); and
the drain's own resume goes to the fresh start, not to "exited twice", for a card he has
just answered (`his_word`). It is consumed by the fresh start it allows, and never carries
to another session. The block's text says whose unblock counts.

A house just started afresh and not yet in the listing is not asked about at all by his
Drop in or his open in app (`here`, `NotListed`): it may be starting, a resume command for
it would start a copy, and "gone" for it would block a house in its first seconds. He is
told to tap again, and that Resume house says what became of one that stays unlisted.
Once he has unblocked the `afresh-twice` block for that session the taps go on to `wanted`
again, which allows the one more start.

A done card has no house to start (`house.refuse_if_done`), so one whose conversation is
gone is refused in plain words by Resume and open in app (`here`, `DONE`). His Drop in asks
the same question (`done_gone`) and hands out a fresh session in the card's record instead
(c-787, `dropin.from_record`): his terminal's, not a house.
The voice wake (`house.wake` after a voice conversation, `drain.release_holds`) does not
ask: voice has just taken a turn in that conversation, so it is there, and the question
would cost the wake its second and a half.
"""

from datetime import datetime, timedelta

from keel import adapters, dropin, harness, house, housejobs, prompts, terms, views
from keel.board import Board, Refused
from keel.config import Config

# How recent a turn on the card contradicts "gone". Under half the harness's default
# retention (30 days), so a shortened retention is still told apart from a conversation
# that cannot have expired.
RECENT_DAYS = 14
# The hooks that say a session really ran a turn. Never its `SessionEnd`, nor a `resume`
# or `session` event: a resume of a gone conversation writes those and runs nothing.
TURN_HOOKS = ("Stop", "Notification")
# The marks of the two blocks `wanted` writes (`board.MARKS`), by the kind their data says
# (`withheld`), with the session they are about (`session`). Both are HIS, not mechanics.
RECENT_KIND, TWICE_KIND = "afresh", "twice"
MARK_OF = {RECENT_KIND: "afresh-withheld", TWICE_KIND: "afresh-twice"}
# The key of the data `start` leaves on its note: `{old, new, automatic, previous}`.
NOTE_KEY = "afresh"
STARTED = ("the old conversation had expired (the harness no longer holds session {old}{previous}), "
           "so it could not be resumed: a new house, {new}, was started from the card's own "
           "record (c-654)")
FAILED = ("{id}'s old conversation had expired (the harness no longer holds session {old}) "
          "and a new house would not start from the card's record: {why}")
BEFORE = "; the session before it was {previous}"
RECENT = ("the harness says the conversation of {id}'s house is gone, though the card shows it "
          "was used {ago} ({what}), inside the {limit} days a transcript is surely kept. Nothing "
          "was started and nothing was stopped. Its session is {old}{previous}: look for it by "
          "hand first if you want it. To start a fresh house from the card's record at its next "
          "resume, unblock the card yourself: only your own unblock counts, not Bosun's (c-654)")
TWICE = ("{id}'s house was not started afresh a second time: session {new} was itself started "
         "afresh, in place of {old} whose conversation was gone, never ran a turn, and the "
         "harness says its conversation is gone too. Nothing was started and nothing was "
         "stopped. To allow one more fresh start at its next resume, unblock the card "
         "yourself: only your own unblock counts, not Bosun's (c-654)")
DONE = ("{id} is done and the harness no longer holds its house's conversation (session "
        "{old}): there is nothing to open, and a done card's house is not started again")


class Withheld(harness.HarnessError):
    """No house was started, afresh or by resume, and the card says why: a start that
    failed (`launch` blocked it) or a fresh start Keel would not make (`withhold`). A
    HarnessError, so a caller with something to put back (a review batch,
    `shipping.put_back`) puts it back as for any start that failed. `said`: the card's
    block already is this refusal, under its own mark, and a caller leaves it standing
    (`shipping.put_back`, `drain.carry_resume`, `landing.refused_here`)."""

    said = False


class NotListed(Refused):
    """The house Keel has just started afresh is not in the harness's listing yet, so there
    is nothing to join and nothing is asked of it."""


# Every call of the harness goes through `house.harness`, the one name a test replaces.


def now() -> datetime:
    return datetime.now().astimezone()


def same(one, other) -> bool:
    """One session: the same id, or a card's short id and the uuid it begins."""
    one, other = str(one or ""), str(other or "")
    if not one or not other:
        return False
    return one == other or (8 in (len(one), len(other)) and (one.startswith(other) or other.startswith(one)))


def ran(event: dict) -> bool:
    """Is this event a session really running a turn (`TURN_HOOKS`)? A `Stop` the hook
    blocked counts as much: the house ran to it."""
    return event["kind"] == "hook" and (event.get("data") or {}).get("hook") in TURN_HOOKS


def last_used(events: list[dict]) -> tuple[datetime, str, str | None] | None:
    """When the board last shows the CARD's house running a turn, by which hook and under
    which session id. Whichever session: a resume mints a new id, so a session minted
    yesterday that died before its first Stop has no turn of its own, while the card shows
    the conversation in use the day before under the id it had then (c-654 review)."""
    for event in reversed(events):
        at = views.parse_at(event.get("at")) if ran(event) else None
        if at is not None:
            return at, event["data"]["hook"], event["data"].get("session_id")
    return None


def previous(events: list[dict], session_id: str) -> str | None:
    """The session the card was on before this one, by its newest event naming another."""
    for event in reversed(events):
        named = (event.get("data") or {}).get("session_id") if event["kind"] in ("session", "resume", "hook") else None
        if named and not same(named, session_id):
            return str(named)
    return None


def answered(events: list[dict], session_id: str, kind: str) -> dict | None:
    """Has HE answered the withheld block of this kind for THIS session: the newest such
    block (`withheld` and `session` in its data), with an unblock of his own after it and
    no fresh start since? The unblock event, or None. Bosun's unblock and the drain's are
    not his answer. A later block that merely restates the refusal (it quotes the block's
    own text: a caller that caught the refusal and blocked again on top, as Bosun's resume
    repair does) is looked past; any other block between the two means the unblock
    answered that one, not this. The answer is durable (a block written after it does not
    take it back) and is consumed by the fresh start it allows; it never carries to
    another session."""
    found = None
    for index in range(len(events) - 1, -1, -1):
        event, data = events[index], events[index].get("data") or {}
        if event["kind"] == "note" and isinstance(data.get(NOTE_KEY), dict):
            return None
        if event["kind"] == "block" and data.get("withheld") == kind and same(data.get("session"), session_id):
            found = index
            break
    if found is None:
        return None
    said = events[found].get("text") or ""
    for event in events[found + 1:]:
        if event["kind"] == "unblock" and event.get("actor") == "human":
            return event
        if event["kind"] == "block" and said not in (event.get("text") or ""):
            return None
    return None


def his_word(board: Board, card: dict) -> bool:
    """For the drain's own resume of an exited house (`drain.reconcile`): he has answered a
    withheld fresh start of this card's session, and nothing has acted on it yet (no resume
    or start since his unblock). Such a card goes to the resume, which starts afresh, even
    with the drain's one automatic resume spent."""
    events, session_id = board.events(card["id"]), card.get("session_id")
    for kind in MARK_OF:
        unblock = answered(events, session_id, kind)
        if unblock and not any(event["id"] > unblock["id"] and event["kind"] in ("resume", "session")
                               for event in events):
            return True
    return False


def before(events: list[dict]) -> dict | None:
    """The fresh start the card's newest turn start is, as its note recorded it
    (`{old, new, automatic, previous}`), or None when a resume or another start came since."""
    for event in reversed(events):
        data = event.get("data") or {}
        if event["kind"] == "note" and isinstance(data.get(NOTE_KEY), dict):
            return data[NOTE_KEY]
        if event["kind"] in ("resume", "session"):
            return None
    return None


def unproven(events: list[dict], session_id: str) -> dict | None:
    """The fresh start this session is, when nothing on the board shows it ran a turn (no
    `Stop`, blocked or not, and no `Notification` of it): its note's data, else None."""
    earlier = before(events)
    if not earlier or not same(earlier.get("new"), session_id):
        return None
    proven = any(ran(event) and same(event["data"].get("session_id"), session_id) for event in events)
    return None if proven else earlier


def withhold(board: Board, card: dict, why: str, kind: str) -> None:
    """Block the card for him, under the kind's own mark and with the session it is about,
    and raise: nothing starts. The block is his, and his unblock answers it (`answered`)."""
    board.block(card["id"], why, "drain", mark=MARK_OF[kind], data={"session": card["session_id"]})
    refusal = Withheld(why)
    refusal.said = True
    raise refusal


def no_process(session_id: str, row: dict | None, config_dir) -> bool:
    """Condition 1: the harness lists no live process for the session. A row with a process
    says no. With NO row the harness is asked again and strictly: a listing that failed
    answers an empty one (`harness.agents`), and an empty listing is never read as "its
    session has no process" where a session is about to be replaced (c-654 review)."""
    if row is not None:
        return not housejobs.has_process(row)
    try:
        rows = house.harness.agents(config_dir, strict=True)
    except harness.HarnessError:
        return False
    return not housejobs.has_process(house.harness.find(session_id, rows))


def wanted(board: Board, card: dict, row: dict | None, cwd, config_dir, at: datetime | None = None) -> bool:
    """Should this card's house start afresh rather than be resumed? True only when all three
    of the module's conditions hold; False when the resume should go ahead and say what it
    says; `Withheld`, the card blocked, when the harness says gone and the board says no."""
    session_id = card["session_id"]
    if not no_process(session_id, row, config_dir):
        return False
    if not house.harness.conversation_gone(session_id, cwd=cwd, config_dir=config_dir):
        return False
    events = board.events(card["id"])
    earlier = unproven(events, session_id)
    if earlier and not answered(events, session_id, TWICE_KIND):
        withhold(board, card, TWICE.format(id=card["id"], new=session_id, old=earlier.get("old")), TWICE_KIND)
    if earlier:
        return True        # his unblock of that refusal is his word for this one start
    used = last_used(events)
    age = (at or now()) - used[0] if used else None
    if age is not None and age < timedelta(days=RECENT_DAYS) and not answered(events, session_id, RECENT_KIND):
        ago = "today" if age.days < 1 else f"{age.days} {'day' if age.days == 1 else 'days'} ago"
        other = previous(events, session_id)
        withhold(board, card, RECENT.format(
            id=card["id"], old=session_id, ago=ago, limit=RECENT_DAYS,
            previous=BEFORE.format(previous=other) if other else "",
            what=f"a {used[1]} of session {used[2]} at {used[0].isoformat(timespec='seconds')}"), RECENT_KIND)
    return True


def start(cfg: Config, board: Board, card: dict, prompt: str, actor: str = "drain",
          automatic: bool = False) -> dict:
    """A NEW house for a card whose session the harness cannot resume (`wanted` said so),
    under the card's lock the caller holds. It is `launch` itself, so the worktree, the
    settings and fence, the model and the name are the ones any start or resume of this card
    uses; its first prompt is the brief, then where the card's record of the lost
    conversation is (`prompts.afresh`), then `prompt`, what the resume would have said.
    Nothing is ended: the old session has no process (`wanted`) and no conversation. The
    start is the new house's turn start on the board (its `session` event), with a note in
    plain words that keeps the old session's whole id, so he can look for it by hand, and
    whether this was the drain's once-only resume (`automatic`).

    A start that fails leaves the card blocked by `launch`, as any start does, and raises
    `Withheld` with both halves of why."""
    card_id, old = card["id"], str(card["session_id"])
    other = previous(board.events(card_id), old)
    extra = prompts.afresh(card, cfg.card_dir(card_id), prompt, old,
                           change=terms.of(cfg, card.get("space"))["change"], cfg=cfg)
    try:
        result = house.launch_here(cfg, board, card_id, extra=extra)
    except (adapters.AdapterError, harness.HarnessError, OSError) as error:
        why = (str(error).splitlines() or [type(error).__name__])[0]
        raise Withheld(FAILED.format(id=card_id, old=old, why=why)) from error
    board.note(card_id, STARTED.format(old=old, new=result["bg_id"],
                                       previous=BEFORE.format(previous=other) if other else ""), actor,
               data={NOTE_KEY: {"old": old, "new": result["session_id"], "automatic": bool(automatic),
                                "previous": other}})
    house.end_rotation(board, card)
    return dict(result, afresh=True)


def done_gone(cfg: Config, card: dict, cwd=None) -> bool:
    """A DONE card's conversation is gone: no live process for its session, and the harness,
    asked in `cwd` (the directory a resume would enter), says gone. A done card's house is
    never started again, so nothing is started on it: Drop in hands out a session on
    the card's record instead (c-787), and Resume and open in app refuses (`here`)."""
    space = adapters.space_of(cfg, card)
    row = house.harness.find(card["session_id"], house.harness.agents(space.config_dir))
    return no_process(card["session_id"], row, space.config_dir) and house.harness.conversation_gone(
        card["session_id"], cwd=cwd or house.wake_cwd(cfg, card), config_dir=space.config_dir)


def if_gone(cfg: Config, board: Board, card_id: str, prompt: str, actor: str = "human",
            cwd=None) -> dict | None:
    """`here` under the card's lock, for his Drop in (`actions.act_dropin`)."""
    with house.card_lock(cfg, card_id):
        return here(cfg, board, board.get(card_id), prompt, actor, cwd)


def here(cfg: Config, board: Board, card: dict, prompt: str, actor: str = "human",
         cwd=None) -> dict | None:
    """For a caller that hands out or wakes the card's session rather than resuming it with
    a prompt (his Drop in, his Resume and open in app), and holds the card's lock: a house
    that has exited and whose conversation is gone (`wanted`) is started afresh with
    `prompt`, and the start is returned; None when there is nothing to recover (no session,
    a voice hold, a session with a live process, a conversation that is there). `cwd`: the
    directory the caller's own command or wake would use, read and not made. A done card
    whose conversation is gone is `Refused`: nothing would open it."""
    if not card.get("session_id") or views.voice_hold(card.get("options")):
        return None
    if card["stage"] == "done":
        if done_gone(cfg, card, cwd):
            raise Refused(DONE.format(id=card["id"], old=card["session_id"]))
        return None
    space = adapters.space_of(cfg, card)
    row = house.harness.find(card["session_id"], house.harness.agents(space.config_dir))
    cwd = cwd or house.wake_cwd(cfg, card)
    events = board.events(card["id"])
    # A house just started afresh, not listed and with no turn to its name (c-654 review):
    # never handed out as a resume and never woken, whatever else is so. It is not asked
    # about either (it may be starting), until he has answered the refusal of a second start
    # for it: then it is asked about again (`wanted`), which allows the one more start, and
    # when that starts nothing (the listing failed or shows a process, the probe overran)
    # the answer is the same "not listed yet".
    starting = row is None and bool(unproven(events, card["session_id"]))
    not_listed = NotListed(dropin.NOT_LISTED.format(id=card["id"], new=str(card["session_id"])[:8]))
    if starting and not answered(events, card["session_id"], TWICE_KIND):
        raise not_listed
    if not wanted(board, card, row, cwd, space.config_dir):
        if starting:
            raise not_listed
        return None
    house.require_model(cfg, board, card)
    return start(cfg, board, card, prompt, actor)
