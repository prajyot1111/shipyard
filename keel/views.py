"""Derived views over a card row.

Nothing here is stored. `attach` turns a `cards` row into the plain dict every read
returns: `options` decoded and a `derived` dict holding the gates, needs-you, kind,
startable, archived, backlog (with its override and the stamp it is measured from), the
cards that came out of this one (`follow_ups`, the other end of the stored `from`), and
(for a card with children) `tracking`, the parent stage and the tally of the slices. The
rules are the ones in `docs/layout.md`
under "Derived, never stored".
"""

import json
import sqlite3
from datetime import datetime, timedelta

from keel import settings

# The stages a card waiting on this one (`after`) counts as far enough: its outcome is at
# his gate, or approved (a work card whose pull request is ready is `shipping`, lane SHIP).
WAITABLE = ("review", "shipping", "done")

# `options.backlog`: the human's manual override of the date rule. "backlog" always
# backlogs the card, "active" never does, "auto" (or no key at all) leaves it to the date.
BACKLOG_ON = "backlog"
BACKLOG_OFF = "active"
BACKLOG_AUTO = "auto"
BACKLOG_CHOICES = (BACKLOG_ON, BACKLOG_OFF, BACKLOG_AUTO)
DEFAULT_BACKLOG_DAYS = settings.default("keel", "backlog_days")
# c-673: the backlog clock starts again at HIS own action on a card at its outcome gate.
# His actors are his token (a tap in the deck, his `kb`) and voice acting for him, the two
# `deployask.DEPLOYERS` and `cli.FLOW_MOVERS` name. A house, the drain, a hook, a shell
# (`cli`), Bosun and the talker never move it.
HIS_ACTORS = ("human", "voice")
# A `set` of these options alone is written under his name and is not his action on that
# card. `backlog` is the rule's own switch: `auto` hands a card back to the date it had,
# not to today. The others are one pass over many cards: the outcome boards backfill
# (`outcomeboards.send`) and the ship upgrade (`shipupgrade.apply`).
NOT_HIS_OPTIONS = ("backlog", "outcome_boards_sent", "shipping", "ship_now")
# What a pass over many cards puts on a note or a relay it writes under his name
# (`his_action`): the ship upgrade's note, the outcome boards backfill's `kb relay --bulk`,
# and each note of Close all idle (`kb note --bulk`, beside its `closed-idle` mark).
BULK_DATA = {"bulk": True}
# A review card at the inbox backlogs when its pull request has been quiet this long, unless
# the fetcher wrote its space's own `review_backlog_days` on the card (lane RC).
DEFAULT_REVIEW_BACKLOG_DAYS = 15
# `options.claim` ({host, at}): a drain has taken this card (`Board.claim`), so it is not
# startable for any other drain.
CLAIM_OPTION = "claim"
# `options.voice_hold` ({at, until, stopped, turns}): voice is talking to this card's house
# (`keel converse`), so nothing automatic may resume it, stop it or nudge it until the hold
# is released or its `until` passes. It is ONE key on the card because Keel has one store:
# the drain, both Stop hook bodies, `house.resume` and the deck all read it from here.
VOICE_HOLD_OPTION = "voice_hold"
# `options.dropin_hold` ({at, until, session, seen}): Drop in handed him `claude --resume`
# for this card's EXITED house (U3), so he is, or is about to be, in its conversation at a
# terminal. Nothing may resume it or stop it meanwhile: a resume would start a second copy
# of that conversation. `seen` is the drain's mark that his terminal session was listed;
# from then on the hold lasts while it stays listed, whatever `until` says (`keel/dropin.py`).
DROPIN_HOLD_OPTION = "dropin_hold"
# `options.notice_key`: the card is a segment's notice (`bin/keel-backup`,
# `segments/cloud-spend/fetch.py`), open until it is staged done. Q8 counts it in needs-you.
NOTICE_OPTION = "notice_key"


def parse_at(text: str | None) -> datetime | None:
    """An ISO stamp from the board as an aware datetime; anything unreadable is None."""
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


# A house being rotated into a fresh session (`keel/rotate.py`): its checkpoint turn ends
# at building without staging, and the Stop hook must let it (`Board.stop_check`).
ROTATE_OPTION = "rotate"


def rotating(options: dict | None) -> bool:
    return ((options or {}).get(ROTATE_OPTION) or {}).get("state") == "checkpointing"


def voice_hold(options: dict | None, at: datetime | None = None) -> dict | None:
    """The card's LIVE voice hold, or None when there is none or it has expired.

    An expired hold is not a hold: it is a conversation nobody is having any more, and the
    drain's job is to clear it and put the house back on its feet (`drain.release_holds`).
    A hold with no readable `until` is treated as live, because the safe answer to "is he
    talking to this house" is yes; the drain's repair still reaches it, through the `at`.
    """
    held = (options or {}).get(VOICE_HOLD_OPTION)
    if not isinstance(held, dict):
        return None
    until = parse_at(held.get("until"))
    if until is None:
        return held
    return held if until > (at or datetime.now().astimezone()) else None


def voice_hold_expired(options: dict | None, at: datetime | None = None) -> dict | None:
    """The card's hold when it has run out: what the drain releases. None when there is
    no hold at all, or when the one there is still live."""
    held = (options or {}).get(VOICE_HOLD_OPTION)
    if not isinstance(held, dict) or voice_hold(options, at) is not None:
        return None
    return held


def dropin_hold(options: dict | None) -> dict | None:
    """The card's drop-in hold as recorded, live or not; None when there is none. The
    drain skips a card that carries one: the due ones are released before anything reads."""
    held = (options or {}).get(DROPIN_HOLD_OPTION)
    return held if isinstance(held, dict) else None


def dropin_holding(options: dict | None, at: datetime | None = None) -> dict | None:
    """The drop-in hold while it holds on the record alone: he was seen in the session, or
    its `until` has not passed (an unreadable one holds, as a voice hold's does)."""
    held = dropin_hold(options)
    if held is None or held.get("seen"):
        return held
    until = parse_at(held.get("until"))
    return held if until is None or until > (at or datetime.now().astimezone()) else None


def notice(row: sqlite3.Row, options: dict) -> bool:
    """An OPEN segment notice: the card carries `options.notice_key` and is not done.

    The key is what makes a card a notice (the segments look their notice up by it); the
    `notice` topic they also set is a grouping word he can change, so it decides nothing.
    Archived is left to the caller, which folds it in for needs-you as it does for gates.
    """
    return bool(options.get(NOTICE_OPTION)) and row["stage"] != "done"


def backlog_override(options: dict) -> str | None:
    """The manual override on the card, or None when it is `auto` or absent."""
    value = options.get("backlog")
    return value if value in (BACKLOG_ON, BACKLOG_OFF) else None


def his_action(kind: str, data: dict | None) -> bool:
    """Whether an event one of HIS_ACTORS wrote is his own action on that card (c-673). His
    tap counts whatever became of it, so every kind is his (a note, a flow move ask, a set,
    an unblock, a mark, an answer, a relay, a Resume asked, one house closed), less two: a
    write marked as one of a pass over many cards, and the rule's own switch."""
    data = data or {}
    if data.get("bulk"):
        return False    # a pass over many cards: its note or its relay (`BULK_DATA`)
    if kind == "set" and set(data) == {"options"}:
        return not set(data["options"] or {}) <= set(NOT_HIS_OPTIONS)
    return True


def later(reached: str | None, acted: str | None) -> str | None:
    """The newer of two board stamps; `reached` when the other is absent or unreadable."""
    first, second = parse_at(reached), parse_at(acted)
    return acted if first and second and second > first else reached


def backlog(board, outcome_gate: bool, override: str | None, since: str | None) -> bool:
    """A card that has sat at its outcome gate longer than `backlog_days`.

    Date alone, plus his manual move, nothing else: no cap, no ordering, no rank. Only a
    card at its outcome gate can backlog, so a plan gate never does, and the override
    decides outright in either direction when it is set. `since` is `backlog_since`, the
    one instant both the rule and the deck's length read.
    """
    if not outcome_gate:
        return False
    if override is not None:
        return override == BACKLOG_ON
    since, at = parse_at(since), parse_at(board.now())
    if since is None or at is None:
        return False
    return at - since > timedelta(days=board.backlog_days)


def review_quiet_since(row: sqlite3.Row, options: dict) -> str | None:
    """A review card at the inbox (lane RC): when its pull request last moved, the stamp the
    fetcher keeps on the card (`options.review_pr.activity`, refreshed every poll). None for
    any other card, and for a review card past the inbox (his Review tap is the answer)."""
    if not options.get("review_key") or row["stage"] != "inbox":
        return None
    pr = options.get("review_pr") or {}
    return pr.get("activity") or pr.get("created")


def review_backlog(board, row: sqlite3.Row, options: dict, override: str | None) -> bool:
    """A review card waiting for his Review whose pull request has been quiet longer than
    the space's `review_backlog_days` (lane RC): derived from the activity stamp, never a
    stored move, so a push or a comment brings it back by itself. His override decides
    outright, as for any card."""
    quiet = review_quiet_since(row, options)
    if quiet is None:
        return False
    if override is not None:
        return override == BACKLOG_ON
    since, at = parse_at(quiet), parse_at(board.now())
    days = (options.get("review_pr") or {}).get("backlog_days") or DEFAULT_REVIEW_BACKLOG_DAYS
    if since is None or at is None:
        return False
    return at - since > timedelta(days=int(days))


def review_backlog_since(row: sqlite3.Row, options: dict) -> str | None:
    """When a review card at the inbox went quiet (its pull request's last activity)."""
    return review_quiet_since(row, options)


def backlog_since(board, row: sqlite3.Row, outcome_gate: bool) -> str | None:
    """The stamp the backlog rule measures from: when this card entered its outcome gate, or
    his newest own action on it since (`board.backlog_clock`, c-673).

    `backlog` says a card has sat too long; this says since when, so the deck can put a
    length on it ("at review 41 days"). `derived` reads it once and gives that one answer
    to the rule and to the deck, so the two cannot disagree. None for a card that is not at
    its outcome gate, where the date means nothing.
    """
    return board.backlog_clock(row) if outcome_gate else None


def gate_since(board, row: sqlite3.Row, waits: dict) -> str | None:
    """When the thing this card waits on him for OPENED (F5): the block, the plan gate,
    the outcome gate or the notice, in that order, which is the order the deck names them.
    None for a card that waits on nothing. Not `updated_at`, which any note, set or
    voice-hold release moves, so a gate open for two days used to read "2m"."""
    for kind in ("blocked", "plan", "outcome", "notice"):
        if waits[kind]:
            return board.opened_since(row, kind)
    if waits.get("ask"):
        return waits["ask"]["at"]
    return waits["prepared"][0]["at"] if waits.get("prepared") else None


def event_dict(row: sqlite3.Row) -> dict:
    event = dict(row)
    event["data"] = json.loads(event["data"]) if event["data"] else None
    return event


def relay_dict(event: dict) -> dict:
    """A pending relay as a card read carries it: its event id, what, for whom, since when,
    the session it was tapped for, the stage the card was at when he tapped (c-604: a tap
    whose card has moved on since is refused with a note, `drain.superseded`), and the
    prompt a resume carries."""
    data = event["data"] or {}
    return {"id": event["id"], "what": data.get("what"), "to": data.get("to"), "at": event["at"],
            "session": data.get("session"), "stage": data.get("stage"), "held": bool(data.get("held")),
            "prompt": data.get("prompt")}


# The relays a house's Stop yields to (`held_tap`, c-604): his words or his stop go first.
HELD_TAPS = ("resume", "stop")


HELD_TAP_MAX = timedelta(minutes=30)


def held_tap(relays: list[dict], session: str | None, host: str | None = None,
             now: datetime | None = None) -> dict | None:
    """The first of a card's pending relays that is his tap for THIS house, or None: a
    `resume` or `stop` for the card's current session (c-604 review), addressed to `host`
    when it is known, and younger than HELD_TAP_MAX, so a stale tap, one for a session since
    replaced or one for another machine never silences a Stop's checks."""
    now = now or datetime.now().astimezone()
    for relay in relays or []:
        if relay.get("what") not in HELD_TAPS or relay.get("session") != session or not session:
            continue
        if host and relay.get("to") != host:
            continue
        at = parse_at(relay.get("at"))
        if at is not None and now - at <= HELD_TAP_MAX:
            return relay
    return None


# How a tracking card's slices are counted for `tracking_tally`, in the order the sentence
# says them: what is moving first, what has not started last.
TRACKING_BUCKETS = (("building", ("planning", "building")),
                    ("at review", ("review",)),
                    ("shipping", ("shipping",)),
                    ("done", ("done",)),
                    ("waiting", ("inbox", "assigned")))


def tracking_tally(children: list[sqlite3.Row]) -> str | None:
    """Where a tracking card's slices stand, in a few words: `1 of 8 building, 7 waiting`.

    A tracking card does no work of its own, so this, and not the stage it borrows from its
    children, is the honest answer to where it is. It is derived here rather than in each
    reader so the deck's word, `kb list` and `kb show` cannot say it differently.
    """
    if not children:
        return None
    stages = [child["stage"] for child in children]
    parts = []
    for label, group in TRACKING_BUCKETS:
        count = sum(stage in group for stage in stages)
        if not count:
            continue
        parts.append(f"{count} of {len(stages)} {label}" if not parts else f"{count} {label}")
    return ", ".join(parts)


def parent_stage(children: list[sqlite3.Row]) -> str | None:
    """done when every child is, review when any child is, else building."""
    if not children:
        return None
    stages = [child["stage"] for child in children]
    if all(stage == "done" for stage in stages):
        return "done"
    if any(stage == "review" for stage in stages):
        return "review"
    return "building"


def all_done(children: list[sqlite3.Row]) -> bool:
    """Every slice is done: a tracking card's tally is complete (lane X). False for none."""
    return bool(children) and all(child["stage"] == "done" for child in children)


def tracking_stage(row: sqlite3.Row, children: list[sqlite3.Row]) -> str | None:
    """A tracking card's stage as every reader shows it: its children's (`parent_stage`),
    except that a card whose slices are all done is `done` only once it is CLOSED (by the
    drain, c-649, or his Approve outcome); until the drain's next pass it reads `review`.
    c-277 read `done` for four days on a tally nobody had looked at, while it sat stored at
    `building`."""
    stage = parent_stage(children)
    if stage == "done" and row["stage"] != "done":
        return "review"
    return stage


def effective_stage(board, row: sqlite3.Row) -> str:
    """A tracking card's stage is its children's; any other card's is its own."""
    return tracking_stage(row, tracked(row, board.children(row["id"]))) or row["stage"]


def archived(row: sqlite3.Row) -> bool:
    """`options.archived` true: the card is history, never needs you, never starts."""
    return json.loads(row["options"] or "{}").get("archived") is True


def tracked(row: sqlite3.Row, children: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """The children that make `row` a tracking card: its unarchived ones, and none at all
    when `row` is archived itself.

    c-427: c-014 was archived, a card was filed under it, and it came back on the board as
    a tracking card whose stage followed that child. Archived is history, at either end:
    an archived parent tracks nothing, and an archived child is not a slice still in play.
    """
    if archived(row):
        return []
    return [child for child in children if not archived(child)]


def claim_host(card: dict) -> str | None:
    """The host whose drain took this card (a card as a read returns it), or None."""
    held = (card.get("options") or {}).get(CLAIM_OPTION)
    return held.get("host") if isinstance(held, dict) else None


def claimed(row: sqlite3.Row) -> bool:
    """A drain has taken this card and will start it; no other drain may."""
    return bool(json.loads(row["options"] or "{}").get(CLAIM_OPTION))


def afters(text: str | None) -> list[str]:
    """The cards an `after` names, in order, once each. The column is one TEXT field holding
    ids separated by commas (`c-311,c-313`), so a value written when a card could wait on
    only one card is already a list of one and nothing had to migrate."""
    return list(dict.fromkeys(part.strip() for part in (text or "").split(",") if part.strip()))


def after_text(ids: list[str]) -> str | None:
    """The column's form of a list of ids; None for none."""
    return ",".join(dict.fromkeys(ids)) or None


def waiting_for(board, row: sqlite3.Row) -> list[str]:
    """The cards this one still waits for: each `after` not yet at review or done, or not
    yet done when its repo lands on an integration branch (c-526, his D2: only then is its
    work on the branch the waiting card starts from). A card that is gone from the board is
    still waited for, since nothing can finish it."""
    from keel import stacking   # noqa: PLC0415 - stacking reads this module's rules
    chosen = stacking.choice(row)
    if chosen == stacking.INDEPENDENT:
        return []           # c-718: cut from the base, it holds nothing up
    left, ids = [], afters(row["after"])
    for card_id in ids:
        found = board.conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if found is not None and chosen == stacking.STACKED and card_id == ids[0] and stacking.pushed(board, found):
            continue        # c-718: stacked, it is cut from that branch once it is pushed
        if found is None or effective_stage(board, found) not in waitable(board, found):
            left.append(card_id)
    return left


def stack_of(board, row: sqlite3.Row) -> dict | None:
    from keel import stacking   # noqa: PLC0415 - stacking reads this module's rules
    return stacking.derive(board, row)


def waitable(board, row: sqlite3.Row) -> tuple:
    """The stages at which a card no longer holds up the cards that wait on it."""
    repo = (row["repo"] or "").split(",")[0].strip()
    if (row["space"], repo) in getattr(board, "integrated", ()):
        return ("done",)
    return WAITABLE


# `options.worker` (c-645): who works the card, set by him when it is created or before it
# starts. A text value from WORKERS, so a later worker ("you") is one more name, not a
# migration. Absent: the card gets the rule's answer (`bosun_eligible`), as every card did
# before there was a worker.
WORKER_OPTION = "worker"
WORKERS = ("house", "bosun")


def bosun_eligible(board, row) -> bool:
    """A personal card with a repo, in builder mode, that Bosun may build: the superuser
    builds every one; the in-app builder only those on `[builder] repos` (`Board.builds`),
    and a personal card on any other repo is a house's (docs/atlas/96-bosun.md, "Builder
    mode" and "The builder")."""
    repo = str(row["repo"] or "").split(",")[0].strip()
    if not (getattr(board, "builder", False) and row["space"] == "personal" and repo):
        return False
    return getattr(board, "superuser", False) or repo in getattr(board, "builds", ())


def worker_of(row) -> str | None:
    try:
        options = row["options"]
    except (KeyError, IndexError):      # a card read without its options says no worker
        return None
    if isinstance(options, str):
        options = json.loads(options or "{}")
    found = (options or {}).get(WORKER_OPTION)
    return found if found in WORKERS else None


def bosun_builds(board, row) -> bool:
    """Bosun's to build, never a house's: a card he may build whose worker is not a house
    (c-645). The one gate of the drain (`startable`), Bosun's queue (`derived.bosun`) and his
    approvals (`Board._approve_as_bosun`)."""
    return bosun_eligible(board, row) and worker_of(row) != "house"


def startable(board, row: sqlite3.Row, tracking: bool) -> bool:
    """Assigned, unblocked, unarchived, unclaimed, not tracking, not Bosun's to build, and
    EVERY card its `after` names at review or done."""
    if tracking or row["stage"] != "assigned" or row["blocked_reason"] or archived(row):
        return False
    if bosun_builds(board, row):
        return False
    if claimed(row):
        return False
    return not waiting_for(board, row)


def open_ask(board, card_id: str) -> dict | None:
    """The newest open ask Bosun has raised about this card, or None."""
    conn = getattr(board, "conn", None)
    if conn is None:
        return None
    found = conn.execute("SELECT id, question, kind, created_at FROM asks WHERE card = ? AND state = 'open' "
                         "ORDER BY n DESC LIMIT 1", (card_id,)).fetchone()
    return ({"id": found["id"], "question": found["question"], "kind": found["kind"],
             "at": found["created_at"]} if found else None)


# His Stop tap's note carries this in its data (`board.MARKS["human-stop"]`, c-605), and his
# Close idle house tap's the other (`board.MARKS["closed-idle"]`, c-607).
HUMAN_STOP = {"stop": "human"}
CLOSED_IDLE = {"stop": "idle"}


def stop_kind(events_newest_first) -> str | None:
    """Why the house is down by his hand, if it is: `human` (his Stop) or `idle` (his Close
    idle house), whichever marked note is newer than the last turn start (`resume`,
    `session`) and than his Retry (a move to assigned); None when neither is."""
    for event in events_newest_first:
        data = event["data"] or {}
        if event["kind"] in ("resume", "session"):
            return None
        if event["kind"] == "stage" and data.get("to") == "assigned":
            return None
        if event["kind"] == "note" and data.get("stop") in (HUMAN_STOP["stop"], CLOSED_IDLE["stop"]):
            return data["stop"]
    return None


def stop_holds(events_newest_first) -> bool:
    """His Stop holds the house down until his Resume or Retry: one rule for the drain, a
    shipping batch and the deck's `derived.held_by_stop`. A house he closed while idle is
    not held by it (`closed_idle`): its next batch or his gate tap brings it back."""
    return stop_kind(events_newest_first) == HUMAN_STOP["stop"]


def closed_idle(events_newest_first) -> bool:
    """He closed the house while it was idle (c-607), and no turn has started since: the
    drain's resume of an exited house passes it over, a batch or his tap resumes it."""
    return stop_kind(events_newest_first) == CLOSED_IDLE["stop"]


def down_by_him(board, row) -> str | None:
    """`stop_kind` read straight off the events table, for a card with a session."""
    conn = getattr(board, "conn", None)
    if conn is None or not row["session_id"]:
        return None
    rows = conn.execute("SELECT kind, data FROM events WHERE card = ? AND kind IN "
                        "('resume', 'session', 'stage', 'note') ORDER BY id DESC", (row["id"],))
    return stop_kind({"kind": kind, "data": json.loads(data) if data else None} for kind, data in rows)


def held_by_stop(board, row) -> bool:
    return down_by_him(board, row) == HUMAN_STOP["stop"]


# a-72 (c-607): a shipping house idle `[keel] ship_idle_hours` is closed by the drain
# (`keel/shipidle.py`); the Board carries the setting (`Board.ship_idle_hours`, c-633), so the
# deck says the hours the drain keeps.


def turn_ended(events_newest_first, session_id: str | None) -> datetime | None:
    """When the session's current turn ended, by the board's own record: its newest `Stop`
    hook, with no turn started since (`resume`, which a batch told into it writes too, or
    `session`). None when there is no such record: quiet time is never taken for it."""
    for event in events_newest_first:
        data = event["data"] or {}
        if event["kind"] in ("resume", "session"):
            return None
        if event["kind"] == "hook" and data.get("hook") == "Stop" and session_id \
                and data.get("session_id") == session_id and not data.get("stop_blocked"):
            # a Stop the hook blocked did not end the turn: the house carried on (c-607 review)
            try:
                return datetime.fromisoformat(event["at"])
            except (TypeError, ValueError):
                return None
    return None


def reoffer_turn_ended(conn, row) -> bool:
    """Is the card's newest batch a re-offer whose own turn has ended (c-651,
    `shipreoffer.batch_turn`), so the drain closes its house on its next pass?"""
    from keel import shipreoffer   # here, not at the top: shipreoffer reads this module
    shipped = json.loads(row["options"] or "{}").get("shipping") or {}
    if not shipreoffer.is_reoffer(shipped):
        return False
    mark = shipped[shipreoffer.RECORD_KEY]
    rows = conn.execute("SELECT id, kind, data, at FROM events WHERE card = ? AND id > ? "
                        "AND kind IN ('resume', 'session', 'hook', 'set') ORDER BY id",
                        (row["id"], int(mark.get("after") or 0)))
    events = [{"id": id_, "kind": kind, "data": json.loads(data) if data else None, "at": at}
              for id_, kind, data, at in rows]
    return shipreoffer.batch_turn(mark, events)[0] == shipreoffer.ENDED


def ship_auto(board, row, options: dict) -> dict | None:
    """A shipping card's two automatic-handling switches (c-655, `keel/shipauto.py`), each
    `{on, by}`: its own option, else its space's as the Board carries it. None off shipping."""
    if row["stage"] != "shipping":
        return None
    from keel import shipauto      # here, not at the top: shipauto reads shipreoffer, which reads this
    of_space = getattr(board, "ship_auto", None)
    return shipauto.chosen(of_space(row["space"]) if callable(of_space) else None, options)


def ship_handover(board, row, options: dict) -> dict | None:
    """What his hand-over would give a shipping card's house now, as the deck's button and
    lines count it (`shipauto.handover`). None off shipping, with nothing looked at yet, or
    for a card whose pull request was declined (so its chip, the digest and its page agree).
    It is derived for every shipping card on every read, so it reads little: the turn's
    events only after the mark of the batch told last (none when nothing marks it), a `set`
    event as whether it took a hold and nothing of the record it carries, and a verdict as
    its handle and time, never its diffs."""
    conn = getattr(board, "conn", None)
    shipped = options.get("shipping")
    if conn is None or row["stage"] != "shipping" or not shipped:
        return None
    if shipped.get("state") == "declined":
        return None       # it stays at shipping with nothing answered there: the verb refuses it
    from keel import shipauto, shipreoffer      # here, not at the top: both read this module
    events, after = [], shipauto.turn_after(shipped)
    if after is not None:
        marks = ", ".join("?" for _ in shipauto.TURN_KINDS)
        holds = ", ".join(f"json_type(data, '$.options.{key}')" for key in shipreoffer.HOLDS)
        for id_, kind, data, at, *held in conn.execute(
                f"SELECT id, kind, CASE WHEN kind = 'set' THEN NULL ELSE data END, at, {holds} FROM events "
                f"WHERE card = ? AND id > ? AND kind IN ({marks}) ORDER BY id", (row["id"], after, *shipauto.TURN_KINDS)):
            taken = {key: {} for key, kind_of in zip(shipreoffer.HOLDS, held) if kind_of == "object"}
            events.append({"id": id_, "kind": kind, "at": at,
                           "data": {"options": taken} if kind == "set" else json.loads(data) if data else None})
    events += [{"id": id_, "kind": "verdict", "at": at, "data": {"handle": handle}}
               for id_, handle, at in conn.execute(
                   "SELECT id, json_extract(data, '$.handle'), at FROM events WHERE card = ? AND kind = 'verdict' "
                   "ORDER BY id", (row["id"],))]
    return shipauto.handover({"options": options}, sorted(events, key=lambda event: event["id"]))


def ship_sendback(board, row, options: dict) -> list | None:
    """What he sent back on a shipping card that its house has not been told yet (c-663,
    `shipsendback.waiting`): `[{handle, text, at, held}]`, oldest first, `held` the sentence
    saying why it is not on its way (declined, archived, blocked, his own Stop of the house,
    the drain paused, a batch he re-offered still open), else None. None off shipping."""
    if row["stage"] != "shipping":
        return None
    from keel import shipsendback      # here, not at the top: it reads shipreoffer, which reads this
    from keel import terms             # here too: the board's own words, else the base ones
    words = getattr(board, "words", None)
    change = (words(row["space"]) if words else terms.BASE)["change"]
    return shipsendback.waiting(options, shipsendback.held(
        options, bool(row["blocked_reason"]), archived(row), change, stopped=held_by_stop(board, row),
        paused=bool(getattr(board, "drain_paused", False))))


def ship_prepared(board, row, options: dict) -> list | None:
    """The shipping card's items whose fix the house prepared and that wait on his answer
    (r-55, c-723, `shipreplies.waiting_on`): `[{handle, why, at}]`. None off shipping."""
    conn = getattr(board, "conn", None)
    if conn is None or row["stage"] != "shipping" or not options.get("shipping"):
        return None
    from keel import shipreplies      # here, not at the top: it is the shipping lane's
    return shipreplies.waiting_on(conn, row["id"], options)


def ship_idle(board, row) -> dict | None:
    """A shipping card's `{since, close_at}`: when its house's turn ended and when the drain
    closes it if it is still listed idle then (a-72), which the deck says ahead ("idle 1h40m,
    closes at 2h"); for a re-offered batch whose turn ended, at once (`reoffer`, c-651).
    None off shipping or with no Stop on record."""
    conn = getattr(board, "conn", None)
    if conn is None or row["stage"] != "shipping" or not row["session_id"]:
        return None
    rows = conn.execute("SELECT kind, data, at FROM events WHERE card = ? AND kind IN "
                        "('resume', 'session', 'hook') ORDER BY id DESC", (row["id"],))
    since = turn_ended(({"kind": kind, "data": json.loads(data) if data else None, "at": at}
                        for kind, data, at in rows), row["session_id"])
    if since is None:
        return None
    if reoffer_turn_ended(conn, row):
        # c-651: a re-offered batch whose turn ended closes on the drain's next pass
        said = since.isoformat(timespec="seconds")
        return {"since": said, "close_at": said, "hours": 0, "reoffer": True}
    hours = getattr(board, "ship_idle_hours", None) or settings.default("keel", "ship_idle_hours")
    return {"since": since.isoformat(timespec="seconds"),
            "close_at": (since + timedelta(hours=hours)).isoformat(timespec="seconds"),
            "hours": hours}


def derived(board, row: sqlite3.Row) -> dict:
    from keel import tree   # here, not at the top: tree reads this module's rules
    children = tracked(row, board.children(row["id"]))
    tracking = bool(children)
    plan_gate = (not tracking and row["stage"] == "planning"
                 and row["autonomy"] == "attended" and row["plan_ref"] is not None)
    # A tracking card is at an outcome gate only while it waits at review with every slice
    # done (brought there before c-649, or by his Back to your gate): the drain closes it on
    # its next pass (`keel/trackclose.py`), and his Approve meanwhile closes it too.
    outcome_gate = row["stage"] == "review" and (not tracking or all_done(children))
    # r-19 (c-540): a tracking card he sent back with every slice done. Every reader shows it
    # at review (`tracking_stage`), but the drain will not close it until a slice changes,
    # which never happens once all are done; the deck offers him Back to your gate, and the
    # drain closes it from review on its next pass (c-649).
    regate = tracking and all_done(children) and row["stage"] not in ("review", "shipping", "done")
    blocked = row["blocked_reason"] is not None
    is_archived = archived(row)
    options = json.loads(row["options"] or "{}")
    override = backlog_override(options)
    since = backlog_since(board, row, outcome_gate)
    is_backlog = backlog(board, outcome_gate, override, since) or review_backlog(board, row, options, override)
    is_notice = notice(row, options)
    ask = open_ask(board, row["id"])
    relays = board.pending_relays(row["id"])
    is_landing = landing_now(row, options, relays)
    down = down_by_him(board, row)
    prepared = ship_prepared(board, row, options)
    return {
        "plan_gate": plan_gate,
        "outcome_gate": outcome_gate,
        "regate": regate and not archived(row),
        # Q8: gates, blocked cards and segment notices, never a general queue (N3). The
        # backlog rule is unchanged: only an outcome gate can backlog.
        # An outcome gate whose approve is on record and landing (c-535) is not his until
        # the landing answers: a refusal blocks it, which needs him again.
        "needs_you": ((plan_gate or (outcome_gate and not is_landing) or blocked or is_notice
                       or ask is not None or bool(prepared)) and not is_archived and not is_backlog),
        "landing": is_landing,
        # Bosun's open ask about this card (c-521, `keel/asks.py`): {id, question, kind},
        # which makes the card need him until he answers it (decision D3).
        "ask": ask,
        "notice": is_notice,
        "kind": "errand" if row["repo"] is None else "house",
        "startable": startable(board, row, tracking),
        # Bosun builds it (builder mode): its queue, never the drain's; the deck labels it.
        "bosun": bosun_builds(board, row),
        # c-645: who works it, as the pane and the form say it; `eligible` says Bosun could
        "worker": "bosun" if bosun_builds(board, row) else "house",
        "worker_eligible": bosun_eligible(board, row),
        "parent_stage": tracking_stage(row, children),
        # This card has children, so it tracks them and works at nothing itself. `kind` is
        # not this question: it answers errand or house (a repo or none), and a split never
        # changes it, which is why c-277 still read `house` after it was cut into eight
        # (2026-09-20). Every reader that must not treat a tracking card as a working house
        # reads this flag: `drain.holds_slot`, `drain.reconcilable`, the deck and `kb list`.
        "tracking": tracking,
        "tracking_tally": tracking_tally(children),
        # Every card its `after` names, and the ones of those not yet at review or done.
        "after": afters(row["after"]),
        "waiting_for": waiting_for(board, row),
        # c-718: stacked on the card it waits for, or independent of it, and what is known of
        # that card's branch (`keel/stacking.py`); None with no choice.
        "stack": stack_of(board, row),
        # A tracking card's outline (`keel/tree.py`): its slices by step, what each waits
        # for, which could start now, what each unblocks. None on any other card.
        "tree": tree.outline(board, row, children),
        # The follow-ups filed out of this card. It is here so every read carries it (the
        # CLI, the deck's state document), and it decides nothing above it: a follow-up
        # never touches a gate, a stage, `startable` or needs-you at either end.
        "follow_ups": board.follow_ups(row["id"]),
        "archived": is_archived,
        "backlog": is_backlog,
        "backlog_override": override,
        "backlog_since": since or review_backlog_since(row, options),
        "gate_since": gate_since(board, row, {"blocked": blocked, "plan": plan_gate,
                                              "outcome": outcome_gate, "notice": is_notice,
                                              "ask": ask, "prepared": prepared}),
        # The human's taps waiting for the house's own machine (`Board.relay`), oldest first.
        "relays": relays,
        # A review card's one word (lane RC), and the highest severity he posted on it: what
        # the deck's find bar filters and sorts by.
        "review": review_state(row, options),
        "review_severity": ((options.get("review_posted") or {}).get("severity")
                            if options.get("review_key") else None),
        # Lane GRP (GR-3): a held review card's wait for its story's other side, with the
        # hours left in the window; None for every other card.
        "review_wait": review_wait(board, row, options),
        # Voice is talking to this house right now: when the hold runs out, or None. The
        # deck shows it where "Open in Claude app" sits, because a held house has been
        # stopped on purpose and that link cannot work until it is woken.
        # c-605 review: HE stopped this house and nothing has started it since; the drain
        # and a review batch leave it down until his Resume or Retry, and the deck says so.
        "held_by_stop": down == HUMAN_STOP["stop"],
        # c-607: he closed it while it was idle; its next batch or his tap resumes it
        "closed_idle": down == CLOSED_IDLE["stop"],
        # a-72 (c-607): when a shipping house's turn ended, and when the drain closes it if
        # the harness still lists it idle then
        "ship_idle": ship_idle(board, row),
        # c-655: whether each kind of review goes to the house by itself, and what his
        # hand-over would give it now
        "ship_auto": ship_auto(board, row, options),
        "ship_handover": ship_handover(board, row, options),
        "ship_sendback": ship_sendback(board, row, options),
        # r-55 (c-723): the items whose fix the house prepared and that wait on his answer
        "ship_prepared": prepared,
        "voice_hold": (voice_hold(json.loads(row["options"] or "{}")) or {}).get("until"),
    }


def landing_now(row: sqlite3.Row, options: dict, relays: list[dict]) -> bool:
    """The card's Approve outcome is on record and landing (`keel/landing.py`): at review,
    unblocked, with a `land` relay pending or its merged-tree suite running. c-533 sat 14
    minutes under needs you meanwhile (c-535)."""
    if row["stage"] != "review" or row["blocked_reason"] is not None:
        return False
    return (any(relay.get("what") == "land" for relay in relays)
            or (options.get("landing") or {}).get("state") == "testing")


REVIEW_STATES = ("held", "waiting", "reviewing", "gate", "posted", "new", "closed")
# Lane GRP (GR-3): `options.review_wait` ({story, sibling_repo, since, hours}), written by the
# review fetcher on an inbox review card whose story's other side has a branch and no pull
# request yet; cleared when the sibling joins, the window runs out, or he says Review now.
REVIEW_WAIT_OPTION = "review_wait"
DEFAULT_SIBLING_HOURS = 48


def held(row, options: dict) -> dict | None:
    """The card's wait, while it holds: an inbox review card carrying one (a row, or a card
    as a read returns it)."""
    wait = options.get(REVIEW_WAIT_OPTION)
    if not isinstance(wait, dict) or row["stage"] != "inbox" or not options.get("review_key"):
        return None
    return wait


def held_wait(card: dict) -> dict | None:
    """`held` for a card as a read returns it."""
    return held(card, card.get("options") or {})


def review_wait(board, row: sqlite3.Row, options: dict) -> dict | None:
    """The wait as the deck draws it: the stored facts and `hours_left` in the window,
    counted from `since` to the board's now (never below 0)."""
    wait = held(row, options)
    if wait is None:
        return None
    hours = int(wait.get("hours") or DEFAULT_SIBLING_HOURS)
    since, at = parse_at(wait.get("since")), parse_at(board.now())
    gone = (at - since).total_seconds() / 3600 if since and at else 0
    return dict(wait, hours=hours, hours_left=max(0, int(round(hours - gone))))


def review_state(row: sqlite3.Row, options: dict) -> str | None:
    """Where a review card stands (lane RC), in the one word the deck's Reviews chips and
    `kb` both read: held for its story's other side (lane GRP), waiting for his Review tap,
    reviewing, at his gate, posted, new commits since his review, or closed (the pull
    request merged or was declined first). None for any card that is not a review card."""
    if not options.get("review_key"):
        return None
    stage = row["stage"]
    if options.get("review_closed") or notice(row, options):
        return "closed"
    if held(row, options):
        return "held"
    if stage == "inbox":
        return "waiting"
    if stage == "review":
        return "gate"
    if stage == "done":
        return "new" if options.get("review_new") else "posted"
    return "reviewing"


def attach(board, row: sqlite3.Row) -> dict:
    card = dict(row)
    card["options"] = json.loads(card["options"] or "{}")
    card["derived"] = derived(board, row)
    return card
