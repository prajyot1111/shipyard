"""The drain role: reconcile exited houses, then start startable cards. Nothing else.

Every pass: read `claude agents --json` once per space config dir (a listing sees only
its own config dir's sessions); for each card at building (or at planning
with no plan delivered yet) whose session no agent carries, resume it once and after
that block it with the last thing it said; then start the startable cards in queue
order (`keel/tree.py`), each against its own pool. A card whose `options.slot` is `review`
counts against `reviews_max`, every other card against `houses_max`, and the two pools fill
independently: a full review pool never holds up a build, and a review never takes a
build slot. A house holds a slot only while it is doing something: an idle house at its
open plan gate holds none, and neither does an idle TRACKING card, whose stage is its
children's and whose own house has nothing left to do (`holds_slot`). A card at review, or
at planning with its plan gate open, is never touched; a tracking card is never resumed,
nudged or blocked either, and its idle session is ended once (`retire_tracking`); once
every slice is done it is closed to done with a rollup as its outcome (`close_tracking`,
lane X, c-649). A card Bosun builds (`derived.bosun`) is never a house's: whatever session
it still carries is neither resumed, woken nor blocked by a pass, and the card says so once
(`leave_to_bosun`, c-647).
`drain_paused` (the install's config.toml) is the safety catch: a paused drain reconciles but starts only
a card named explicitly with `--card`.

A card voice is holding (`options.voice_hold`, V4 guard 2) is nobody's but his for as long
as the hold lasts: `reconcile`, `retire_tracking` and `resume_quiet` all skip it, whatever
the listing says about its session, because voice stopped that session on purpose and is
taking turns into it. `release_holds` is the other half, and the reason the hold carries an
expiry: a conversation he walked away from is cleared here and the house is WOKEN (no
prompt, no model turn, `house.wake`), which is a repair and not a resume.

There is one more way a turn can end, with no hook behind it: the account's rate limit cuts
a house off mid-turn, so no `Stop` fires, the session stays LISTED and idle, and neither
reconcile (which wants it gone) nor the Stop nudge has anything to act on. Three houses sat
at `building` that way on 2026-09-20 holding the whole pool with no work happening, until
the human resumed them by hand. `idle_stuck` says when that has happened, from board facts
plus this pass's listing, and `resume_quiet` puts the house back once after
`idle_resume_minutes`, with the wait doubling, and blocks it after three attempts. Such a
house KEEPS its pool slot while it waits: it is coming back and will need the slot, and
freeing it would let the same pass start another house and over-subscribe the machine the
moment this one resumes. That is the opposite call from a tracking card's, and for the
opposite reason: a tracking card has no work of its own to come back to.

A quiet house is not always the rate limit. On 2026-09-24 the personal space's login could
not refresh, and every house turn ended at once on "Login expired · Please run /login" with
no Stop, which is the quiet shape exactly: the drain called it the rate limit and spent its
resumes on a login that could not work. So before a quiet house is put back, the drain asks
whether its space's login works (`keel/login.py`): at once when the house's own last words
name a lost login (`login.names_login` on the current turn's transcript or log, `turn_said`),
and otherwise just before a resume would be spent. The probe is one real call and its answer
is kept per space for ten minutes. A space whose login has EXPIRED has its quiet houses, and
any house of it that exited, blocked with one reason and a marker (`keel/loginhold.py`)
instead of resumed, and starts no new house until it works; every pass re-probes it (at most
once in ten minutes), and once the probe says good, the cards the drain held for it, and only
those, are resumed once each and unblocked (`login_upkeep`). A probe that cannot say
(`unknown`: a timeout, the network, a rate limit) is never read as expired: the quiet rule
goes on as before, except that a house whose own words named the login is left alone for
that pass rather than resumed into the same wall.

Reconcile is NOT capped by the pools. A house that was already running keeps its claim to
its slot, so putting it back is restoring and not starting; only the memory floor defers
it. What the pools bound is what a pass ADDS on top of that. So the pass's own resumes are
counted into both pools (`slot_of`), into the browser slot and into the memory gate BEFORE
`start_cards` reads them, and from board facts rather than a second listing: the listing is
taken once at the top of the pass, and a session minted mid-pass is not reliably listed for
a few seconds (`resumed_mid_turn`). Without that count, one pass on the box resumed two
houses and then started two more on a two-slot machine (2026-09-20, `<install>/history/docs/decisions.md`).
The human's tap on the deck (Approve, Send back, Resume) resumes a house directly, outside
any pass, and is never refused for a full pool: he is answering a house that is already
his. His taps can therefore take a machine over its limit, and because the next pass counts
those houses like any other, the drain never adds to it.

The drain CLAIMS a card before it starts it (`kb claim`), so a card it took and lost the
reply for is still its own to start (`claimed_unstarted`), and it reconciles the houses of
the spaces it serves.

Some of the human's taps arrive as `relay` events on the card (`Board.relay`): a tap held
for a house that was working (c-598), and Approve outcome's `land` (`keel/landing.py`). Each
pass carries the pending relays first, before reconcile: each is marked `carried` BEFORE it
is acted on, so it is carried at most once, and one whose card has moved to another session
since the tap is answered `superseded` instead. A `start` relay starts the card even on a
paused drain, as `--card` does, and waits (still pending) while its pool is full or the
memory gate is shut. A `resume` relay is TOLD to an idle house in its own session
(`keel/tellhouse.py`, c-598) and HELD, still pending, while the house is working (`hold`).
A thread of its own waits on the drain's kick inbox for its whole life (`keel/kick.py`,
`kick.Listener`, c-608): whoever writes a relay, and a house's Stop with a relay held for it,
kicks it, and `carry_pass` carries at once, even while a pass runs. One lock (`CARRY_LOCK`)
keeps the thread's carry and the pass's apart, and what the thread carries mid-pass the rest
of that pass leaves alone (`MIDPASS`), as it does its own carried cards. The same kick
starts a Deploy he just said (`deploy.kicked`, c-636): the `kb` that recorded it kicks.

The machine's limits (`[keel]`): its two pools, a browser slot (`browsers_max` houses whose card declares `options.browser`),
a memory gate (under `memory_floor_mb` available the pass starts and resumes nothing, and
each start or resume in a pass takes `house_mb` off the reading), and `house_nice`, the nice every
live house runs at so voice is scheduled ahead of houses. Every pass also records each live
house's peak memory on its card (`options.peak_mb`). The readings are `keel/machine.py`.
"""

import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from keel import (backup, backupdue, boardtrash, dropin, harness, house, housejobs, housetier, landing, login,
                  loginask, logins,
                  loginhold, logtrim, machine, merging, reviewcards, rotate, shipping, talker,
                  requests, trackclose, tree, views, where)
from keel import afresh, appservices, asks, consolewake, deploy, idleclose, kick, packclones, passlock, shipidle, pausewake, permpause, relay, restart, stackwatch, teardown, tellhouse
from keel.board import RELAY_WHATS, Board, Refused, open_board
from keel import config as config_module
from keel.config import Config

LOG_NAME = "drain.log"
LAST_LINES = 40
# The two pools. A card asks for the review pool with `options.slot = review`, which is
# what the deck's Launch review puts on the card it makes.
HOUSE_SLOT = "house"
REVIEW_SLOT = "review"
POOLS = (HOUSE_SLOT, REVIEW_SLOT)
# `options.peak_mb` is rewritten only when a house beats it by this much, so a house that
# breathes by a few MB does not put a `set` event on its card every pass.
PEAK_STEP_MB = 32


# ----- log -----

def log(cfg: Config, text: str) -> None:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    with open(cfg.logs_dir / LOG_NAME, "a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {text}\n")


def summary_line(summary: dict) -> str:
    if "skipped" in summary:
        return f"drain: {summary['skipped']}"
    fields = ("houses", "reviews", "browsers", "carried", "resumed", "stuck", "retired",
              "closing", "unclosed", "idle_ended", "idle_closed", "blocked", "denied", "recovered", "login", "relogged", "started", "paused",
              "memory")
    return "drain: " + " ".join(f"{name}={summary[name]}" for name in fields if name in summary)


# ----- what the harness and the board say -----

def house_ids(board: Board, rows: list[dict]) -> set[str]:
    """Card ids among the background agents whose house holds a pool slot.

    The one place the pool rule lives: the drain's counts and the deck's running list
    both read it. A house holds a slot while it is doing something (see `holds_slot`);
    one idling at its open plan gate holds none, so it stops blocking other starts."""
    by_card: dict[str, list[dict]] = {}
    for row in rows:
        name = row.get("name") or ""
        if row.get("kind") == "background" and board.exists(name):
            by_card.setdefault(name, []).append(row)
    return {card_id for card_id, card_rows in by_card.items()
            if holds_slot(board, board.get(card_id), card_rows)}


def holds_slot(board: Board, card: dict, rows: list[dict]) -> bool:
    """Building, planning before the plan lands, a busy row, or a resume mid-turn; at
    shipping only while the house is doing something.

    A card at planning with its plan delivered is waiting on the human, so an idle house
    there holds nothing. Send back resumes it into a new session the harness may not list
    as busy for a few seconds; `resumed_mid_turn` covers that gap from board facts.

    A TRACKING card is the third idle case, and the stage cannot see it: its stage is its
    children's, so it reads `building` while a slice builds and its own house has nothing
    left to do. c-277 held one of the box's two slots that way after its house split it into
    eight, and every pass logged `house pool full at 2` while one house was working
    (2026-09-20). It holds a slot only while its own session is doing something.

    A house the drain blocked for a permission pause (c-528) is another: it holds one
    only while the listing shows it busy."""
    if card["derived"]["tracking"]:
        return working_now(board, card, rows)
    if permpause.paused_block(card):
        # The drain blocked it for a permission prompt nobody can answer: it holds a slot
        # again only once the harness shows it working (`keel/permpause.py`).
        row = permpause.own_row(card, rows)
        return row is not None and row.get("status") == "busy"
    if card["stage"] == "building":
        return True
    if card["stage"] == "shipping":
        # c-600: the house lives on at shipping, and holds a slot only while it answers a batch
        return working_now(board, card, rows)
    if card["stage"] != "planning":
        return False
    if card["plan_ref"] is None:
        return True
    return working_now(board, card, rows)


def working_now(board: Board, card: dict, rows: list[dict]) -> bool:
    """This card's own session is doing something: a busy row, or a resume mid-turn."""
    # `status`, not `housejobs.working`: a slot is held by a house DOING something, and an
    # idle house waiting on a background job of its own (tests it started) still is.
    return any(row.get("status") == "busy" for row in rows) or resumed_mid_turn(board, card)


def resumed_mid_turn(board: Board, card: dict) -> bool:
    """The newest resume has no Stop or SessionEnd from the card's own session after it.

    A hook naming another session is the superseded one being retired, not this turn."""
    for event in reversed(board.events(card["id"])):
        if event["kind"] == "resume":
            return True
        data = event["data"] or {}
        if event["kind"] == "hook" and data.get("hook") in ("Stop", "SessionEnd"):
            if data.get("session_id") in (None, card.get("session_id")):
                return False
    return False


def empty_pools() -> dict:
    return dict.fromkeys(POOLS, 0)


def slot_of(card: dict) -> str:
    """The pool this card runs in: the review pool when it asks, the house pool otherwise."""
    return REVIEW_SLOT if (card.get("options") or {}).get("slot") == REVIEW_SLOT else HOUSE_SLOT


def limits(cfg: Config) -> dict:
    return {HOUSE_SLOT: cfg.houses_max, REVIEW_SLOT: cfg.reviews_max}


def pool_counts(board: Board, ids: set[str]) -> dict:
    """How many of these live houses sit in each pool."""
    counts = empty_pools()
    for card_id in ids:
        counts[slot_of(board.get(card_id))] += 1
    return counts


def reconcilable(card: dict) -> bool:
    """A house's card where its house is expected to be working (`house_stage`), and never
    a card Bosun builds (c-647): the session such a card still carries is a leftover, and
    putting it back would have a house build what Bosun is building."""
    return house_stage(card) and not card["derived"].get("bosun")


def house_stage(card: dict) -> bool:
    """At building, or at planning before the plan is delivered; never archived.

    Never a tracking card either, whatever stage its children give it: it has no work of
    its own, so its session being gone is not a house that exited. Resuming it would put a
    house back on a card with nothing to do, and the second pass would block it for being
    idle at `building`."""
    if card["derived"]["archived"] or not card.get("session_id"):
        return False
    if card["derived"]["tracking"]:
        return False
    if card["stage"] == "building":
        return True
    return card["stage"] == "planning" and card["plan_ref"] is None


def newest_event(board: Board, card_id: str, kind: str, hook: str | None = None) -> dict | None:
    for event in reversed(board.events(card_id)):
        if event["kind"] != kind:
            continue
        if hook is None or (event["data"] or {}).get("hook") == hook:
            return event
    return None


# His Stop keeps a house down (c-605); `house` holds the rule so a shipping batch reads it too.
stopped_by_him = house.stopped_by_him
closed_while_idle = house.closed_while_idle


def stop_message(board: Board, card_id: str) -> str | None:
    event = newest_event(board, card_id, "hook", hook="Stop")
    if event is None:
        return None
    return ((event["data"] or {}).get("payload") or {}).get("last_assistant_message") or None


def transcript_of(board: Board, card_id: str) -> str | None:
    for event in reversed(board.events(card_id)):
        path = (event["data"] or {}).get("transcript_path")
        if path:
            return path
    return None


def bg_id_of(board: Board, card_id: str) -> str | None:
    for event in reversed(board.events(card_id)):
        if event["kind"] in ("session", "resume") and (event["data"] or {}).get("bg_id"):
            return event["data"]["bg_id"]
    return None


def tail(text: str, n: int = LAST_LINES) -> str:
    return "\n".join(text.strip().splitlines()[-n:])


def last_output(cfg: Config, board: Board, card: dict) -> str:
    """The Stop event's last message, else the transcript's, else the stripped logs."""
    said = stop_message(board, card["id"])
    if said:
        return said
    transcript = transcript_of(board, card["id"])
    if transcript:
        said = harness.last_said(transcript, LAST_LINES)
        if said:
            return said
    bg_id = bg_id_of(board, card["id"])
    if not bg_id:
        return ""
    space = cfg.spaces.get(card["space"])
    return tail(harness.logs(bg_id, space.config_dir if space else None))


# ----- this machine's limits -----

def wants_browser(card: dict) -> bool:
    """The card declares it drives a browser: `options.browser` is true."""
    value = (card.get("options") or {}).get("browser")
    return value is True or str(value).lower() in ("true", "1", "yes")


def browser_count(board: Board, ids: set[str]) -> int:
    return sum(wants_browser(board.get(card_id)) for card_id in ids)


class MemoryGate:
    """Start nothing while available memory is under the floor. One reading per pass, and
    each start or resume takes `house_mb` off it, because a house takes seconds to grow and
    the next reading in the same pass would not see it yet. Off when the floor is 0; shut
    when the floor is set and the machine will not say."""

    def __init__(self, cfg: Config):
        self.floor, self.per_house = cfg.memory_floor_mb, cfg.house_mb
        self.available = machine.available_mb() if self.floor else None
        self.said = False

    def open(self) -> bool:
        return not self.floor or (self.available is not None and self.available >= self.floor)

    def take(self) -> None:
        if self.available is not None:
            self.available -= self.per_house

    def why(self) -> str:
        if self.available is None:
            return "memory gate: available memory unreadable; starting nothing"
        return (f"memory gate: {self.available} MB available, under {self.floor}; "
                f"starting nothing")

    def say_once(self, cfg: Config) -> None:
        if not self.said:
            self.said = True
            log(cfg, self.why())

    def reading(self) -> str | None:
        """The summary line's `memory=`: what is left after this pass's starts."""
        if not self.floor:
            return None
        return "unread" if self.available is None else f"{self.available}MB"


def current_rows(board: Board, rows: list[dict], ids: set[str]) -> dict[str, dict]:
    """Each live house's own agent row: the one carrying its card's session, else any."""
    found: dict[str, dict] = {}
    for row in rows:
        name = row.get("name") or ""
        if row.get("kind") != "background" or name not in ids or not row.get("pid"):
            continue
        if name not in found or row.get("sessionId") == board.get(name).get("session_id"):
            found[name] = row
    return found


def tend(cfg: Config, board: Board, rows: list[dict], ids: set[str]) -> None:
    """Record each live house's peak memory on its card and renice its tree; one `ps` for
    both. Never raises out of the pass: a house's bookkeeping must not stop the drain."""
    try:
        houses = current_rows(board, rows, ids)
        table = machine.process_table() if houses else None
        if not table:
            return
        for card_id, row in houses.items():
            record_peak(cfg, board, card_id, machine.tree_mb(table, int(row["pid"])))
            if cfg.house_nice:
                machine.renice(machine.tree(table, int(row["pid"])), cfg.house_nice)
    except Exception:  # noqa: BLE001 - peak and nice are bookkeeping, not the pass
        failed_step(cfg, board, "tending houses")


def record_peak(cfg: Config, board: Board, card_id: str, mb: int) -> None:
    recorded = (board.get(card_id).get("options") or {}).get("peak_mb") or 0
    if mb >= int(recorded) + PEAK_STEP_MB:
        board.set_fields(card_id, {"options": {"peak_mb": mb}}, "drain")


# ----- which cards are this drain's -----

claim_host = views.claim_host


def owned(cfg: Config, card: dict, served: set[str]) -> bool:
    """This drain's house: a card in a space it serves."""
    return card["space"] in served


def claimed_unstarted(cfg: Config, card: dict) -> bool:
    """Claimed and still at assigned: the drain claimed it and then went away (a crash, a
    lost reply) before the start. It is this drain's to start, since the claim keeps it
    from being startable. Keel runs on one machine, so a claim under any host name (the
    retired box, or this machine before a rename) is this drain's (c-622 r1.F1)."""
    return (claim_host(card) is not None and card["stage"] == "assigned"
            and not card["blocked_reason"] and not card["derived"]["archived"]
            and not card["derived"].get("bosun"))     # c-645: never a house on Bosun's card


# ----- the relays: the human's taps the drain carries -----

def relays_for(cfg: Config, card: dict) -> list[dict]:
    """The card's pending relays, oldest first. The deck addresses every relay to this
    machine (`--to`, `cfg.host`); one addressed to an older name (the retired box, or this
    machine before a rename) is carried here too, as Keel runs on one machine (c-622 r1.F1)."""
    return list(card["derived"].get("relays") or [])


# Every carry in this process holds it: the pass's own (`once`) and the kick thread's
# (`carry_pass`), so the two never carry at once (c-608). At most once is still the board's.
CARRY_LOCK = threading.RLock()


def carry_relays(cfg: Config, board: Board, rows: list[dict], served: set[str],
                 gate: MemoryGate) -> dict:
    """Carry every pending relay for a card this drain owns. Returns the count, the cards
    carried (reconcile leaves them alone this pass: the listing it holds predates them),
    and the pool slots a resume or a start took. Under `CARRY_LOCK`."""
    with CARRY_LOCK:
        return carry_locked(cfg, board, rows, served, gate)


def carry_locked(cfg: Config, board: Board, rows: list[dict], served: set[str],
                 gate: MemoryGate, midpass=None) -> dict:
    """With `midpass` (the kick thread's carry), each card is marked in it BEFORE anything is
    done to it, so a pass running alongside leaves it alone from that moment (c-608 review),
    and unmarked again when the carry left the card to the pass (all its taps held)."""
    done = {"carried": 0, "ids": set(), "pools": empty_pools(), "browsers": 0, "held": set(),
            "told": set()}
    for card in board.list_cards():
        relays = relays_for(cfg, card)
        if not relays or not owned(cfg, card, served):
            continue
        held = 0
        if midpass is not None:
            midpass.mark(card["id"])
        for relay in relays:
            if carry_one(cfg, board, board.get(card["id"]), relay, rows, gate, done):
                done["carried"] += 1
            elif relay["id"] in done["held"]:
                held += 1
        # An unknown kind alone must not hold reconcile off, and neither may a tap held for a
        # working house: the rest of the pass must still see that house (a permission pause).
        if any(relay.get("what") in CARRIED_KINDS for relay in relays) and held < len(relays):
            done["ids"].add(card["id"])
        elif midpass is not None:
            midpass.unmark(card["id"])
    tellhouse.join()        # the tells ran side by side; the pass goes on once they are done
    return done


DONE_WHY = "the card is done, and a done card's house is not resumed"


def superseded(cfg: Config, card: dict, relay: dict) -> str | None:
    """Why this relay is no longer the house's to act on, or None when it still is."""
    if relay["what"] not in carried_kinds(cfg):
        return f"this drain carries no {relay['what']} (it is switched off on {cfg.host})"
    if relay["what"] == "land":
        # Approve outcome carried here (`keel/landing.py`): it lands the card's branch and
        # does not touch the house, so neither a hold nor a new session changes it; only
        # the card leaving review does.
        return None if card["stage"] == "review" else f"the card is at {card['stage']}, no longer at review"
    if views.voice_hold(card.get("options")) and relay["what"] != "start":
        # A tap from the deck that would move a house he is talking to, carried a minute
        # later into the middle of the conversation. He is at the other end of that house
        # right now; the tap is his to make again when he is done.
        return "voice is talking to this house"
    if relay["what"] == "start":
        return None if card["stage"] == "assigned" else f"the card is at {card['stage']}, no longer waiting to start"
    if relay["what"] in ("resume", "rotate") and card["stage"] == "done":
        # A tap queued just before the card reached done (c-601 review): a done card is
        # never resumed (`house.refuse_if_done`), so it is dropped with a note, not a block.
        return DONE_WHY
    if relay["what"] == "resume" and relay.get("stage") and card["stage"] != relay["stage"]:
        # c-604: an Approve plan held while the house worked arrived 97 s later at review,
        # the house having built without it. His words for one stage are not told at
        # another: refused, and the card says why (`moved_why`), never applied stale.
        return moved_why(relay, card)
    if relay.get("session") and card.get("session_id") != relay["session"]:
        return "the house moved on to another session since the tap"
    if not card.get("session_id"):
        return "the card has no house session"
    return None


MOVED_WHY = "the card moved from {tapped} to {now} since the tap"


def moved_why(relay: dict, card: dict) -> str:
    return MOVED_WHY.format(tapped=relay["stage"], now=card["stage"])


def noted_why(why: str) -> bool:
    """A superseded tap the card must say it dropped: he tapped for something that is gone."""
    return why == DONE_WHY or why.startswith(MOVED_WHY.split("{")[0])


def take(cfg: Config, board: Board, card: dict, relay: dict, outcome: str = "taken",
         why: str | None = None) -> bool:
    """Mark the relay carried; False when another drain (or an earlier pass) already did."""
    try:
        board.carry(card["id"], relay["id"], "drain", outcome, why)
    except Refused as refusal:
        log(cfg, f"relay {relay['id']} on {card['id']} not carried: {refusal}")
        return False
    return True


# The relay kinds a drain on this code knows. It CARRIES `land` only with `merge_queue` on and
# `rotate` only with `rotate` on (`carried_kinds`), and it says which in `state/drain.json`
# when it starts, with the head this process loaded (`keel/restart.py`), which `keel doctor`
# compares with the checkout.
CARRIED_KINDS = RELAY_WHATS
ANNOUNCE_FILE = "drain.json"
_unknown_said: set[int] = set()


def carried_kinds(cfg: Config) -> list[str]:
    off = {"land": not cfg.merge_queue, "rotate": not cfg.rotate}
    return [kind for kind in CARRIED_KINDS if not off.get(kind)]


def announce(cfg: Config) -> Path:
    """Write this drain's pid, the relay kinds it carries and the head it loaded."""
    path = cfg.state_dir / ANNOUNCE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": os.getpid(), "kinds": carried_kinds(cfg),
                                "head": restart.loaded(), "waiting": restart.waiting(),
                                "since": restart.waiting_since(),
                                "at": datetime.now().astimezone().isoformat(timespec="seconds")}) + "\n")
    return path


def carry_one(cfg: Config, board: Board, card: dict, relay: dict, rows: list[dict],
              gate: MemoryGate, done: dict) -> bool:
    """One relay: superseded, carried, or (a start with no room) left pending.

    A kind this drain does not know is LEFT PENDING, with one log line per relay: a newer
    deck wrote it, and a drain on the new code carries it. It is never read as a stop."""
    if relay.get("what") not in CARRIED_KINDS:
        if relay["id"] not in _unknown_said:
            _unknown_said.add(relay["id"])
            log(cfg, f"relay {relay['id']} on {card['id']} is a {relay.get('what')!r}, which this "
                     f"drain does not know; left pending for a drain on newer code")
        return False
    why = superseded(cfg, card, relay)
    if why:
        if take(cfg, board, card, relay, "superseded", why):
            log(cfg, f"relay {relay['what']} on {card['id']} superseded: {why}")
            if noted_why(why):
                again = "" if why == DONE_WHY else "; tap again if it still stands"
                board.note(card["id"], f"the {relay['what']} the deck asked for was dropped: {why}{again}",
                           "drain")
        return False
    if relay["what"] == "start":
        return carry_start(cfg, board, card, relay, rows, gate, done)
    if relay["what"] == "land":
        return landing.carry(cfg, board, card, relay, take)
    if relay["what"] == "resume" and hold(cfg, card, relay, rows, done):
        return False
    if not take(cfg, board, card, relay):
        return False
    if relay["what"] == "resume":
        carry_resume(cfg, board, card, relay, gate, done)
    elif relay["what"] == "rotate":
        carry_rotate(cfg, board, card)
    elif relay["what"] == "stop":
        carry_stop(cfg, board, card)
    elif relay["what"] == "close-idle":
        carry_close_idle(cfg, board, card)
    elif relay["what"] == "finished":
        carry_finished(cfg, board, card)
    return True


def carry_rotate(cfg: Config, board: Board, card: dict) -> None:
    """His Rotate, carried here (`keel/rotate.py`): the checkpoint is asked for now, and a
    later pass starts the fresh session once it is written. A refusal is a note."""
    try:
        rotate.ask(cfg, board, card["id"], actor="drain")
    except Refused as refused:
        board.note(card["id"], f"the rotate the deck asked for was not carried on {cfg.host}: "
                               f"{refused}", "drain")
        return
    except Exception as error:  # noqa: BLE001 - one bad card must not stop the pass
        board.note(card["id"], f"the rotate the deck asked for failed on {cfg.host}: {error}", "drain")
        return
    log(cfg, f"relayed rotate of {card['id']} carried")


def hold(cfg: Config, card: dict, relay: dict, rows: list[dict], done: dict) -> bool:
    """A resume tapped for a house that is WORKING is HELD (c-598): not taken, not noted, left
    pending on the board, which is the whole of the hold. The house's Stop kicks this drain
    (`keel/kick.py`), and the next carry tells it. So is a second resume for a card told
    earlier in this pass: that house is in the turn the first one started."""
    row = harness.find(card.get("session_id") or "", rows)
    busy = housejobs.working(row) and (row or {}).get("kind") != dropin.INTERACTIVE
    if not busy and card["id"] not in done["told"]:
        return False
    if relay["id"] not in _held_said:
        _held_said.add(relay["id"])
        log(cfg, f"relayed resume of {card['id']} held: the house is working; it goes when its turn ends")
    done["held"].add(relay["id"])
    return True


_held_said: set[int] = set()


def carry_resume(cfg: Config, board: Board, card: dict, relay: dict, gate: MemoryGate,
                 done: dict) -> None:
    """The human's tap, carried here: never refused for a full pool or a shut gate, since
    he is answering a house that is already his. An idle house is TOLD in its own session
    (`keel/tellhouse.py`, c-598) and takes nothing new; an exited one is resumed and takes its
    `house_mb` off the reading, so the starts later in this pass do not spend memory it has
    just taken. The relay is already marked carried, so a house that turned busy since `hold`
    looked is told anyway: the harness queues the message for its next input."""
    try:
        result = house.resume(cfg, board, card["id"], prompt=relay.get("prompt") or None,
                              tell=True, when_busy=tellhouse.TELL, background=True)
    except house.Busy as busy:
        # His terminal, or a drop-in hold: the tap is not carried out, and the card says why.
        board.note(card["id"], f"the resume the deck asked for was not carried on {cfg.host}: {busy}", "drain")
        log(cfg, f"relayed resume of {card['id']} not carried: {busy}")
        return
    except Exception as error:  # noqa: BLE001 - one bad card must not stop the pass
        # a fresh start Keel would not make has blocked the card already, under its own
        # mark, which his unblock answers (`keel/afresh.py`): that block is left standing
        if not getattr(error, "said", False):
            board.block(card["id"], f"the resume the deck asked for failed on {cfg.host}: {error}", "drain",
                        mark="failed-resume")
        log(cfg, f"relayed resume of {card['id']} failed: {error}")
        sight(cfg, board, f"drain:resume:{card['id']}",
              f"resuming {card['id']} failed on {cfg.host}: {error}", card["id"])
        return
    if result.get("told"):
        # On its own thread (`tellhouse.deliver`, joined at the end of `carry_relays`), so one
        # slow relay does not hold up the next card's; what it came to is on the card.
        done["told"].add(card["id"])
        log(cfg, f"relayed resume of {card['id']} being told in its session")
        return
    gate.take()
    done["pools"][slot_of(card)] += 1
    done["browsers"] += wants_browser(card)
    log(cfg, f"relayed resume of {card['id']} carried")


def carry_finished(cfg: Config, board: Board, card: dict) -> None:
    """A `finished` relay (lane L; none is written since c-622, one already pending is still
    carried): end the card's house because its work was accepted, but only a house the harness does not list as working (in a turn,
    `housejobs.working`; an idle one with a leftover job is stopped, c-535). A working one
    is left running with a note, as the landing worker does (`landing.finish_house`): this
    relay is never an interrupt; `stop` is his."""
    space = cfg.spaces.get(card["space"])
    config_dir = space.config_dir if space else None
    row = harness.find(card.get("session_id") or "", harness.agents(config_dir))
    if row is None:
        return
    if housejobs.working(row):
        board.note(card["id"], f"the approved card's house {row.get('id')} is still working, "
                               f"so it was left running on {cfg.host}", "drain")
        return
    house.retire_session(board, card["id"], card.get("session_id"), config_dir,
                         "finished house", actor="drain")
    log(cfg, f"relayed finished of {card['id']} carried")


def carry_stop(cfg: Config, board: Board, card: dict) -> None:
    bg_id = bg_id_of(board, card["id"]) or (card.get("session_id") or "")[:8]
    space = cfg.spaces.get(card["space"])
    try:
        ended = housejobs.stop(bg_id, space.config_dir if space else None, harness.stop)
    except harness.HarnessError as error:
        board.note(card["id"], f"the stop the deck asked for failed on {cfg.host}: "
                               f"{str(error).splitlines()[0]}", "drain")
        return
    jobs = housejobs.said(ended)
    board.note(card["id"], f"session {bg_id} stopped from the deck, carried by {cfg.host}"
                           + (f"; {jobs}" if jobs else ""), "drain", mark="human-stop")
    log(cfg, f"relayed stop of {card['id']} carried ({bg_id})")


def carry_close_idle(cfg: Config, board: Board, card: dict) -> None:
    """His Close idle house, carried here (c-607). The deck checked the house was idle when
    he tapped; it is checked again here, under the card's lock on this machine's own listing
    (`idleclose.close_here`), and a house that is working now, is being told something, or
    has a job of its own running is left running with a note: this never interrupts one."""
    try:
        card, bg_id, ended = idleclose.close_here(cfg, board, card["id"])
    except idleclose.NotIdle as why:
        board.note(card["id"], f"the close the deck asked for was not carried on {cfg.host}: {why}", "drain")
        return
    board.note(card["id"], idleclose.said(bg_id, ended, cfg.host, card["stage"]), "drain", mark="closed-idle")
    log(cfg, f"relayed close-idle of {card['id']} carried ({bg_id})")


def carry_start(cfg: Config, board: Board, card: dict, relay: dict, rows: list[dict],
                gate: MemoryGate, done: dict) -> bool:
    """Retry's pass: start the card as `--card` would, paused or not; a full pool or a shut
    gate leaves the relay pending for a later pass, as the local Retry would wait."""
    if not (card["derived"]["startable"] or claimed_unstarted(cfg, card)):
        return False                       # blocked, or its `after` not ready yet: wait
    slot = slot_of(card)
    live = pool_counts(board, house_ids(board, rows))
    if live[slot] + done["pools"][slot] >= limits(cfg)[slot] or not gate.open():
        return False
    if not take(cfg, board, card, relay):
        return False
    if start_one(cfg, board, card):
        gate.take()
        done["pools"][slot] += 1
        done["browsers"] += wants_browser(card)
    return True


# ----- the four steps -----

def reconcile(cfg: Config, board: Board, rows: list[dict], served: set[str],
              gate: MemoryGate, carried: set[str] = frozenset()) -> dict:
    """Resume each exited house once; block it the second time with what it last said.

    A card already blocked is his and is passed over: before lane Q it was blocked AGAIN on
    every pass (one more `block` event every poll), and one held for its space's login would
    have had its unspent resume spent on the login that stopped it. A card whose space's
    login has expired is held for it (`hold_for_login`) instead of resumed.

    A resume starts a process, so a shut memory gate defers it to a later pass; the card
    keeps its unspent resume, and a block (which starts nothing) still happens.

    Not capped by `houses_max` or `reviews_max`: a house that was already running keeps its
    claim to its slot, so restoring it is not a start (the module docstring has the rule).
    It returns the card ids it resumed, because the listing this pass holds predates them
    and `once` needs them to count the pools before anything is started."""
    counts = {"resumed": 0, "blocked": 0, "login": 0, "resumed_ids": set()}
    for card in board.list_cards():
        if not house_stage(card) or not owned(cfg, card, served) or card["id"] in carried:
            continue
        if views.voice_hold(card.get("options")):
            continue                      # voice stopped it and is talking into it
        if views.dropin_hold(card.get("options")):
            continue                      # he is, or is about to be, in it at a terminal (U3)
        if harness.find(card["session_id"], rows) is not None:
            continue
        if card["blocked_reason"] is not None:
            continue                      # already his (or held for its login); see below
        if stopped_by_him(board, card["id"]):
            continue                      # his Stop put it down; it waits for his Resume
        if closed_while_idle(board, card["id"]):
            continue                      # he closed it idle (c-607): a batch or his tap brings it back
        if card["derived"].get("bosun"):
            leave_to_bosun(cfg, board, card)     # c-647: never a house on Bosun's card
            continue
        if login.is_expired(cfg, card["space"]):
            hold_for_login(cfg, board, card)     # its resume is kept for when the login works
            counts["login"] += 1
            continue
        # c-654 review: his unblock of a withheld fresh start is his word to start one, so
        # that card goes to the resume (which starts afresh), never to "exited twice"
        if not house.auto_resume_spent(board, card["id"]) or afresh.his_word(board, card):
            if not gate.open():
                gate.say_once(cfg)
                continue
            try:
                house.resume(cfg, board, card["id"], automatic=True,
                             expect_session=card["session_id"])
            except house.SessionMoved as moved:
                log(cfg, f"reconcile left {card['id']} alone: {moved}")   # the kick carried it
                continue
            except afresh.Withheld as withheld:
                # c-654: its conversation is gone and no new house was started; the card is
                # blocked with why, and the pass goes on to the next card
                log(cfg, f"reconcile blocked {card['id']}: {withheld}")
                counts["blocked"] += 1
                continue
            gate.take()
            counts["resumed"] += 1
            counts["resumed_ids"].add(card["id"])
            log(cfg, f"resumed {card['id']} ({card['session_id']})")
        else:
            block_exited(cfg, board, card)
            counts["blocked"] += 1
    return counts


# What the drain says, once per session, on a card Bosun builds whose leftover house session
# has exited: the one place the card shows that nothing put that house back.
LEFT_NOTE = "the drain does not resume a house on a card Bosun builds: house session"


def leave_to_bosun(cfg: Config, board: Board, card: dict) -> None:
    """A card Bosun builds that still carries a house's session (a start made by accident
    before Bosun took it, c-647), reached exactly where a house's card would be resumed: its
    session has exited, and nothing of his holds it. The drain neither resumes nor blocks
    it, and says so on the card once per session."""
    session = card["session_id"]
    marker = f"{LEFT_NOTE} {session[:8]}"
    if any(event["kind"] == "note" and marker in (event["text"] or "")
           for event in board.events(card["id"])):
        return
    board.note(card["id"], f"{marker} exited and was left so", "drain")
    log(cfg, f"left {card['id']} to Bosun: its house session {session[:8]} was not resumed")


# ----- a voice conversation nobody came back to -----

# What the drain says when it clears a hold that ran out. The wake costs no tokens, so this
# is a repair and not a resume, and the note says which so the record cannot be misread.
WOKEN_NOTE = "the voice conversation went quiet; the hold is cleared and the house is awake again"
LEFT_DOWN_NOTE = ("the voice conversation went quiet; the hold is cleared. Its session was "
                  "already stopped before voice reached it, so it is left as it was")


BOSUN_HOLD_NOTE = ("the voice conversation went quiet; the hold is cleared. Bosun builds this "
                   "card, so the drain woke no house on it")
BOSUN_CLOSE_FAILED_NOTE = ("the voice hold ran out and is cleared, but the live conversation "
                           "would not close. Bosun builds this card, so the drain puts no "
                           "house back on it")
CLOSE_FAILED_NOTE = ("the voice hold ran out but the live conversation would not close, so "
                     "the house is left down: the next pass puts it back")


def release_holds(cfg: Config, board: Board, served: set[str], gate: MemoryGate,
                  carried: set[str] = frozenset()) -> dict:
    """Clear every voice hold that has run out, and put its house back on its feet.

    The expiry is what makes an abandoned conversation heal itself: he closes the page
    mid-sentence and nothing else would ever let that house go. A hold whose turn STOPPED the
    house is woken here (`house.wake`: no prompt, no model turn, the same uuid and the same
    app link); a hold that found the house already down leaves it down, because waking a
    tracking card's retired session would only give `retire_tracking` something to stop again
    on the next pass.

    The hold is cleared BEFORE the wake on purpose. A wake that fails leaves an ordinary
    exited house, which `reconcile` already knows how to put back once; leaving the hold on
    instead would have the drain trying the same failing wake every thirty seconds forever.

    `skip` is every card released here, and the rest of the pass skips it: this pass's
    listing predates the wake, so reconcile would read a woken house as an exited one and
    resume it with a prompt it does not need. `ids` is the smaller set that also takes a
    pool slot, counted before anything is started.
    """
    done = {"released": 0, "ids": set(), "skip": set()}
    for card in board.list_cards():
        if not owned(cfg, card, served) or card["id"] in carried:
            continue
        held = views.voice_hold_expired(card.get("options"))
        if held is None:
            continue
        bosuns = card["derived"].get("bosun")     # c-647: its hold is cleared, no house woken
        if held.get("stopped") and not bosuns and not gate.open():
            gate.say_once(cfg)            # the hold waits for memory, like every other start
            continue
        # THE CONVERSATION IS CLOSED BEFORE ANYTHING ELSE (V12). A kept-alive one is a
        # `claude` holding this session, owned by this machine's `keel serve`, and the wake
        # below is refused while anything holds it. The drain runs in its own process, so
        # this is how it reaches the one that owns it; a server that is down owns none and
        # the answer says so.
        shut = housetier.close_session(cfg, card)
        board.release_voice(card["id"])
        done["released"] += 1
        # For the rest of THIS pass the card is left alone whatever happens next: the
        # listing was taken before the wake, so every later step would read the house as
        # exited and put it back with a prompt it does not need. The next pass, with a
        # fresh listing, treats it as the ordinary house it now is.
        done["skip"].add(card["id"])
        if shut.status == housetier.FAILED and bosuns:
            # c-647: the same failed close on a card Bosun builds. No pass puts a house
            # back on it, so the house's sentence below would be false here.
            board.note(card["id"], BOSUN_CLOSE_FAILED_NOTE, "drain")
            log(cfg, f"the voice conversation on {card['id']} would not close; Bosun builds it, "
                     f"so no house is put back")
            continue
        if shut.status == housetier.FAILED:
            # SOMETHING STILL HOLDS THAT SESSION, so the wake would be refused and the
            # house would be left down with no record of why. The hold is cleared either
            # way (keeping it would have the drain retrying a failing close forever) and
            # the next pass finds an ordinary exited house, which `reconcile` puts back.
            board.note(card["id"], CLOSE_FAILED_NOTE, "drain")
            log(cfg, f"the voice conversation on {card['id']} would not close; "
                     f"the house is left down for the next pass")
            continue
        if bosuns:
            board.note(card["id"], BOSUN_HOLD_NOTE, "drain")
            log(cfg, f"released the voice hold on {card['id']}; Bosun builds it, so no house was woken")
            continue
        if not held.get("stopped"):
            board.note(card["id"], LEFT_DOWN_NOTE, "drain")
            log(cfg, f"released the voice hold on {card['id']}; its session was already down")
            continue
        try:
            house.wake(cfg, board, card["id"])
        except Exception as error:  # noqa: BLE001 - one bad card must not stop the pass
            board.note(card["id"], f"the voice hold is cleared but waking the house failed "
                                   f"on {cfg.host}: {error}", "drain", mark="failed-resume")
            log(cfg, f"waking {card['id']} after its voice hold failed: {error}")
            sight(cfg, board, f"drain:resume:{card['id']}",
                  f"waking {card['id']} after a voice hold failed on {cfg.host}: {error}", card["id"])
            continue
        gate.take()
        board.note(card["id"], WOKEN_NOTE, "drain")
        log(cfg, f"released the voice hold on {card['id']} and woke its house")
        if holds_slot(board, board.get(card["id"]), []):
            done["ids"].add(card["id"])
    return done


# ----- a house he dropped into from a terminal (U3) -----

def dropin_upkeep(cfg: Config, board: Board, rows: list[dict], served: set[str],
                  carried: set[str] = frozenset()) -> set[str]:
    """Mark a drop-in hold seen once his terminal session is listed, and end the ones that
    are over (`dropin.verdict`). Returns the cards released here, which the rest of THIS pass
    skips like a released voice hold: the next pass treats each as the ordinary house it is.

    Only the listing can say he left: his terminal session carries none of the house's
    hooks (probed 2026-09-24), so no SessionEnd ever reaches the card."""
    released = set()
    for card in board.list_cards():
        if not owned(cfg, card, served) or card["id"] in carried:
            continue
        verdict = dropin.verdict(card, rows)
        if verdict is None:
            continue
        held = views.dropin_hold(card.get("options"))
        if verdict == dropin.MARK_SEEN:
            seen = dict(held, seen=True)
            board.set_fields(card["id"], {"options": {views.DROPIN_HOLD_OPTION: seen}}, "drain")
            continue
        board.set_fields(card["id"], {"options": {views.DROPIN_HOLD_OPTION: None}}, "drain")
        board.note(card["id"], dropin.RELEASE_NOTES[verdict], "drain")
        log(cfg, f"released the drop-in hold on {card['id']} ({verdict})")
        released.add(card["id"])
    return released


# The note the drain leaves when it ends a tracking card's own session, and the phrase the
# next pass looks for so one session is retired once and not every thirty seconds. It is the
# TEXT and not the event data, as it was when a drain could record its note over HTTP, so a
# note written then still reads as retired.
RETIRED_NOTE = "the tracking card's idle session"


def retire_tracking(cfg: Config, board: Board, rows: list[dict], served: set[str],
                    carried: set[str] = frozenset()) -> int:
    """End the session of every idle tracking card this drain owns. Returns how many.

    A card whose house split it into slices has nothing left to do itself: the slices carry
    the work, and a later resume would mint a fresh session anyway. The process it leaves
    behind still holds a few hundred MB on a 12 GB box, which is a whole house's worth of
    the memory gate for nothing. A busy session, or one mid-turn after a resume, is left
    alone: that is a house doing something, and this is not a stop of live work.
    """
    retired = 0
    for card in board.list_cards():
        if not card["derived"]["tracking"] or card["derived"]["archived"]:
            continue
        if not owned(cfg, card, served) or card["id"] in carried:
            continue
        if views.voice_hold(card.get("options")) or views.dropin_hold(card.get("options")):
            continue                      # "connect me to c-277" is a conversation, not idleness
        mine = [row for row in rows
                if row.get("kind") == "background" and row.get("name") == card["id"]]
        if not mine or working_now(board, card, mine):
            continue
        retired += retire_one(cfg, board, card)
    return retired


def retire_one(cfg: Config, board: Board, card: dict) -> bool:
    """Stop one tracking card's session and note it; False when it was already retired, or
    when the harness refused. A failed stop is noted too, so it is not tried every pass."""
    bg_id = bg_id_of(board, card["id"]) or (card.get("session_id") or "")[:8]
    if not bg_id or already_retired(board, card["id"], bg_id):
        return False
    space = cfg.spaces.get(card["space"])
    try:
        ended = housejobs.stop(bg_id, space.config_dir if space else None, harness.stop)
    except harness.HarnessError as error:
        board.note(card["id"], f"{RETIRED_NOTE} {bg_id} could not be stopped: "
                               f"{str(error).splitlines()[0]}", "drain")
        return False
    jobs = housejobs.said(ended)
    board.note(card["id"], f"{RETIRED_NOTE} {bg_id} stopped; its slices carry the work"
                           + (f"; {jobs}" if jobs else ""), "drain")
    log(cfg, f"retired the idle session of tracking card {card['id']} ({bg_id})")
    return True


def close_tracking(cfg: Config, board: Board, served: set[str],
                   carried: set[str] = frozenset()) -> dict:
    """Close each tracking card this drain owns whose slices are all done, with its rollup
    as its outcome, and take one back to tracking when a slice left done, at review or
    after it closed (`keel/trackclose.py`). Never fails the pass: a disk error is logged
    for its card alone, anything else zeroes the counts and the log says why."""
    try:
        return trackclose.upkeep(board, lambda card: (owned(cfg, card, served)
                                                      and card["id"] not in carried),
                                 lambda line: log(cfg, line))
    except Exception:  # noqa: BLE001 - closing is one card at a time, not the pass
        failed_step(cfg, board, "tracking close")
        return {"closed": 0, "back": 0}


def already_retired(board: Board, card_id: str, bg_id: str) -> bool:
    marker = f"{RETIRED_NOTE} {bg_id}"
    return any(event["kind"] == "note" and marker in (event["text"] or "")
               for event in board.events(card_id))


def block_exited(cfg: Config, board: Board, card: dict) -> None:
    said = last_output(cfg, board, card)
    reason = "house exited twice at " + card["stage"]
    if said:
        reason += "; it last said:\n" + said
    board.block(card["id"], reason, "drain", mark="failed-resume")
    log(cfg, f"blocked {card['id']}: exited twice")


# ----- a house whose turn ended with no Stop -----

# The shape, live on the box on 2026-09-20: at 09:49Z the account hit its session rate limit
# and three houses (c-311, c-312, c-313), each mid-turn at `building`, ended their turn with
# NO Stop hook. The last event on each card is this Notification, and `claude agents --json`
# listed each session as `idle`. Reconcile wants a session GONE from the listing and the
# Stop-hook nudge never ran, so the three sat at `building` holding the whole pool with no
# work happening until the human resumed them by hand at 10:00 (`<install>/history/docs/decisions.md`).
IDLE_PROMPT = "idle_prompt"
TURN_END_HOOKS = ("Stop", "SessionEnd")
# The prompt such a house is put back with, and the phrase that makes a `resume` event
# recognisably the drain's own. Anything else that resumed the house (his Resume, Approve or
# Send back, reconcile's own resume) does not carry it, which is what ends a streak.
STUCK_MARK = "your turn ended without finishing"
STUCK_PROMPT = (STUCK_MARK + ", most likely the account's rate limit. Carry on from where "
                "you stopped and take the card to its gate; it is still at {stage}.")
# Attempts before the card is blocked for the human, and the kinds of event that mean the
# card moved on, so the streak of attempts before them is history. A `session` event is NOT
# one of them: a resume mints a new session and records one.
STUCK_TRIES = 3
STREAK_ENDS = ("stage", "approve", "block", "unblock", "split")


def now() -> datetime:
    """The drain's clock for the quiet rule; a test hands it another one.

    A plain function, never `drain.time`: that name IS the `time` module, so patching its
    `sleep` also patches the one `subprocess` uses to wait for a child (`tests/test_drain.py`
    LoopTest). A clock to mock, rather than a sleep to swallow."""
    return datetime.now().astimezone()


def own_hook(card: dict, data: dict) -> bool:
    """This hook came from the session the card carries now, or names none at all. A hook
    naming another session is the superseded one being retired, not this turn."""
    return data.get("session_id") in (None, card.get("session_id"))


def needs_a_human(data: dict) -> bool:
    """A Notification that is not the plain idle prompt: a permission prompt, which nobody
    but the human can answer. It does fire under `--permission-prompts none` once auto mode
    passes its denial limit (c-521, 2026-09-25); putting that house back would only ask the
    same question again, so it is blocked instead (`permission_upkeep`)."""
    kind = (data.get("payload") or {}).get("notification_type")
    return bool(kind) and kind != IDLE_PROMPT


def quiet_turn(board: Board, card: dict) -> dict | None:
    """When this house's current turn began and when it went quiet inside it, or None when
    it is not quiet mid-turn.

    Walked newest first to the `resume` or `session` event the turn started with. A Stop or
    SessionEnd from the card's own session on the way means the turn ENDED, and an ended turn
    belongs to the Stop hook's nudge and block budget (`Board.stop_check`), never here. The
    instant it went quiet is the oldest idle Notification of this turn, which is how the box's
    09:49 limit reads as quiet from 09:50 rather than from the start of the turn.
    """
    since = None
    for event in reversed(board.events(card["id"])):
        if event["kind"] in ("resume", "session"):
            return {"since": since or event["at"]}
        data = event["data"] or {}
        if event["kind"] != "hook" or not own_hook(card, data):
            continue
        if data.get("hook") in TURN_END_HOOKS:
            return None
        if data.get("hook") == "Notification":
            if needs_a_human(data):
                return None
            since = event["at"]
    return None


def stuck_tries(board: Board, card: dict) -> int:
    """How many times in a row the drain has already put this house back for going quiet.

    Counted from its own `resume` events (their prompt carries `STUCK_MARK`) and stopped by
    anything that means the card moved on since: a resume that is not the drain's, a turn
    that really ended, or a stage move, a gate answer, a block, an unblock or a split. So the
    human's Resume, Approve or Send back puts the count back to zero and the schedule starts
    from its shortest wait again, which is what keeps the drain from arguing with him.
    """
    tries = 0
    for event in reversed(board.events(card["id"])):
        kind, data = event["kind"], event["data"] or {}
        if kind == "resume":
            if STUCK_MARK not in (event["text"] or ""):
                return tries
            tries += 1
        elif kind in STREAK_ENDS:
            return tries
        elif kind == "hook" and own_hook(card, data) and data.get("hook") in TURN_END_HOOKS:
            return tries
    return tries


def stuck_wait(cfg: Config, tries: int) -> int:
    """How long a quiet house is left alone before the drain acts: the machine's
    `idle_resume_minutes`, doubling with each attempt already made (10, 20 and 40 minutes by
    default, then 80 before the block). Never a tight loop: if the account is still limited
    the resume ends the same way, and asking again every ten minutes for hours would only
    spend the limit that is holding it up.
    """
    return cfg.idle_resume_minutes * 60 * (2 ** min(tries, STUCK_TRIES))


def idle_stuck(cfg: Config, board: Board, card: dict, rows: list[dict],
               at: datetime | None = None) -> dict | None:
    """This card's house is quiet mid-turn: since when, how many times the drain has put it
    back, when it acts next, and whether that is due now. None when the rule does not hold,
    which is almost every card.

    The one place the rule lives, as `holds_slot` is for the pools: the drain acts on it and
    the deck draws it from the same answer, so the two cannot say different things. All of
    the conditions:

    - the card is one reconcile would own (`reconcilable`: at `building`, or at `planning`
      before the plan lands; never archived, never tracking, and it has a session), and it is
      not blocked, because a blocked card is already the human's;
    - it has no pending relay, which every other step of a pass skips too;
    - its OWN session is in the listing and is not `busy`. Gone from the listing is
      reconcile's case and not this one; busy is a house working;
    - no Stop or SessionEnd from that session since the turn began. That is the second
      signal, and the one that protects a house waiting on a human answer: a house that needs
      him blocks its card, and a turn that ends at all fires Stop, which the nudge and the
      block budget already answer. An open plan gate is a third shape and is never at
      `building`, so a plan discussion (which lives there) is never touched either;
    - the newest Notification of this turn is the plain idle prompt and not a permission
      prompt (`needs_a_human`): the idle prompt fires for a house waiting on him as well, so
      it cannot be the whole signal;
    - it has been quiet longer than `stuck_wait`.
    """
    if not cfg.idle_resume_minutes:
        return None
    if not reconcilable(card) or card["blocked_reason"]:
        return None
    if views.voice_hold(card.get("options")) or views.dropin_hold(card.get("options")):
        return None                       # held: the process is down on purpose, not stuck
    if card["derived"].get("relays"):
        return None
    row = harness.find(card["session_id"], rows)
    if row is None or row.get("status") == "busy":
        return None
    turn = quiet_turn(board, card)
    since = views.parse_at(turn["since"]) if turn else None
    if since is None:
        return None
    tries = stuck_tries(board, card)
    wait = stuck_wait(cfg, tries)
    at = at or now()
    return {"since": turn["since"], "seconds": max(0, int((at - since).total_seconds())),
            "tries": tries, "blocking": tries >= STUCK_TRIES,
            "next_at": (since + timedelta(seconds=wait)).isoformat(timespec="seconds"),
            "due": (at - since).total_seconds() >= wait}


def resume_quiet(cfg: Config, board: Board, rows: list[dict], served: set[str],
                 gate: MemoryGate, carried: set[str] = frozenset()) -> dict:
    """Put back every house whose turn ended without one, and block it after `STUCK_TRIES`.

    A quiet house KEEPS its pool slot while it waits (`holds_slot` reads `building` and asks
    nothing else): it is coming back and it will need that slot, and freeing it would let the
    same pass start another house and over-subscribe the machine the moment this one resumes.
    That makes this cheap for the pools: the card is already counted through the listing, so
    a resume here adds nothing to them. It does take its `house_mb`, and a shut memory gate
    defers it to a later pass; a block, which starts nothing, still happens.
    """
    done = {"resumed": 0, "blocked": 0, "login": 0}
    for card in board.list_cards():
        if not owned(cfg, card, served) or card["id"] in carried:
            continue
        state = idle_stuck(cfg, board, card, rows)
        if state is None:
            continue
        verdict = quiet_login(cfg, board, card, state)
        if verdict == login.EXPIRED:
            hold_for_login(cfg, board, card)
            done["login"] += 1
            continue
        if verdict == login.UNKNOWN or not state["due"]:
            continue
        if state["blocking"]:
            block_quiet(cfg, board, card, state)
            done["blocked"] += 1
        elif not gate.open():
            gate.say_once(cfg)
        elif resume_quiet_one(cfg, board, card, state, gate):
            done["resumed"] += 1
    return done


def turn_said(cfg: Config, board: Board, card: dict) -> str:
    """What the house said in its CURRENT turn: the transcript's last assistant lines (where
    the harness writes its own API errors), else the log. Not `last_output`, which starts
    from the newest Stop message: a quiet turn has none, so that Stop is an older turn's."""
    transcript = transcript_of(board, card["id"])
    said = harness.last_said(transcript, LAST_LINES) if transcript else ""
    if said:
        return said
    bg_id = bg_id_of(board, card["id"])
    space = cfg.spaces.get(card["space"])
    return tail(harness.logs(bg_id, space.config_dir if space else None)) if bg_id else ""


def quiet_login(cfg: Config, board: Board, card: dict, state: dict) -> str | None:
    """What the space's login says about this quiet house, asked only when it matters:
    `expired` (hold it), `unknown` when its own words named the login and the probe could
    not say (leave it this pass rather than resume it into the same wall), else None (the
    ordinary quiet rule). The probe runs when the house's words name a lost login, or when a
    resume is about to be spent; `login.check` keeps it to one probe per space in ten
    minutes."""
    space = card["space"]
    if login.is_expired(cfg, space):
        return login.EXPIRED
    named = login.names_login(turn_said(cfg, board, card))
    if not named and not state["due"]:
        return None
    at = now()
    found = login.check(cfg, space, at=at)
    if found["state"] == login.EXPIRED:
        return login.EXPIRED
    if named and found["state"] == login.UNKNOWN:
        if found.get("at") == at.isoformat(timespec="seconds"):     # said once per probe
            log(cfg, f"{card['id']} last said its login is gone and the {space} probe could "
                     f"not say ({found.get('why')}); left until the next probe")
        return login.UNKNOWN
    return None


def hold_for_login(cfg: Config, board: Board, card: dict) -> None:
    """Block the card for its space's expired login, marked as the drain's own."""
    loginhold.hold(cfg, board, card, card["space"])
    space = card["space"]
    log(cfg, f"blocked {card['id']}: {login.gone(space, cfg.spaces[space].config_dir)}")


def minutes(seconds: int) -> int:
    return round(seconds / 60)


def resume_quiet_one(cfg: Config, board: Board, card: dict, state: dict,
                     gate: MemoryGate) -> bool:
    """One attempt: the fixed prompt through the usual resume path (`house.resume` retires
    the session it supersedes), then the note that puts the attempt in the record."""
    try:
        house.resume(cfg, board, card["id"], prompt=STUCK_PROMPT.format(stage=card["stage"]))
    except Exception as error:  # noqa: BLE001 - one bad card must not stop the pass
        board.note(card["id"], f"resuming this quiet house failed on {cfg.host}: {error}", "drain",
                   mark="failed-resume")
        log(cfg, f"resuming the quiet house on {card['id']} failed: {error}")
        sight(cfg, board, f"drain:resume:{card['id']}",
              f"resuming the quiet house on {card['id']} failed on {cfg.host}: {error}", card["id"])
        return False
    gate.take()
    board.note(card["id"], f"idle at {card['stage']} for {minutes(state['seconds'])} minutes "
                           f"with no Stop, most likely the account's rate limit; resumed "
                           f"(attempt {state['tries'] + 1} of {STUCK_TRIES})", "drain")
    log(cfg, f"resumed {card['id']}: idle at {card['stage']} for "
             f"{minutes(state['seconds'])}m with no Stop "
             f"(attempt {state['tries'] + 1} of {STUCK_TRIES})")
    return True


def block_quiet(cfg: Config, board: Board, card: dict, state: dict) -> None:
    """The end of the schedule: the account is limited for longer than the drain will wait,
    or something else is wrong, and either way it is his to look at."""
    said = last_output(cfg, board, card)
    reason = (f"idle at {card['stage']} {state['tries']} times: each turn ended with no Stop "
              f"and each resume ended the same way (most likely the account's rate limit)")
    if said:
        reason += "; it last said:\n" + said
    board.block(card["id"], reason, "drain")
    log(cfg, f"blocked {card['id']}: idle at {card['stage']} {state['tries']} times")


# ----- a house auto mode paused on a permission prompt -----

def permission_upkeep(cfg: Config, board: Board, rows: list[dict], served: set[str],
                      carried: set[str] = frozenset()) -> dict:
    """Block every house the harness shows paused on a permission prompt, naming the denied
    commands, and clear the drain's own such block once that session is busy again
    (`keel/permpause.py`). At any stage, while the card's own session is listed (c-584: only
    building and planning were looked at, so a pause at review went unseen). A done card
    is past pausing anyone. Starts nothing, so neither the pools nor the
    memory gate move."""
    done = {"denied": 0, "recovered": 0}
    for card in board.list_cards():
        if not owned(cfg, card, served) or card["id"] in carried or not card.get("session_id"):
            continue
        if card["derived"]["archived"] or card["derived"]["tracking"] or card["derived"].get("relays"):
            continue
        if permpause.recovered(board, card, rows):
            if permpause.clear(board, card):
                done["recovered"] += 1
                log(cfg, f"unblocked {card['id']}: its permission prompt closed and it is working again")
            continue
        if card["blocked_reason"] or card["stage"] == "done":
            continue
        what = permpause.waiting_for(board, card, rows)
        if what is None:
            continue
        permpause.block(board, card, what)
        done["denied"] += 1
        log(cfg, f"blocked {card['id']}: auto mode paused it on a permission prompt ({what})")
    return done


def jobs_upkeep(cfg: Config, board: Board, rows: list[dict], served: set[str],
                carried: set[str] = frozenset()) -> int:
    """Note on the card, once per job, every house of this drain's that is idle while a
    background job of its own still runs (`keel/housejobs.py`): c-526 idled thirty minutes
    behind a wait loop that could never end, and nothing on the card said so. It only
    tells; it starts, stops and resumes nothing. Returns how many notes it wrote."""
    noted = 0
    for card in board.list_cards():
        if not owned(cfg, card, served) or card["id"] in carried or not card.get("session_id"):
            continue
        space = cfg.spaces.get(card["space"])
        row = harness.find(card["session_id"], rows)
        if card["derived"]["archived"] or space is None or row is None:
            continue
        written = housejobs.note_idle(board, card, space.config_dir, row)
        if written:
            log(cfg, f"{card['id']} is idle with {written} background job(s) of its own running")
        noted += written
    return noted


def login_upkeep(cfg: Config, board: Board, served: set[str], gate: MemoryGate,
                 carried: set[str] = frozenset()) -> dict:
    """Probe again every served space whose login was last found expired (at most once in
    ten minutes, `login.check`), then put back the cards the drain held for a login that
    now works: each resumed once through `house.resume` and unblocked (`loginhold.restore`).
    Only a card `loginhold.held_space` names; his own blocks and unblocks are never touched.
    A resume starts a process, so a shut memory gate defers the rest to a later pass, and
    the resumed ids are counted into the pools like reconcile's."""
    done = {"relogged": 0, "ids": set()}
    at = now()
    for name in sorted(served):
        if login.is_expired(cfg, name):
            found = login.check(cfg, name, at=at)
            if found["state"] != login.EXPIRED:
                log(cfg, f"the {name} login answers again: {found['state']}")
    for card in board.list_cards():
        if not card["blocked_reason"] or card["id"] in carried or not owned(cfg, card, served):
            continue
        space = loginhold.held_space(board, card)
        if space is None or login.state_of(cfg, space) != login.GOOD:
            continue
        if card["derived"].get("bosun"):
            loginhold.release(board, card, space)     # c-647: the block goes, no house comes back
            log(cfg, f"unblocked {card['id']}: the {space} login works again; Bosun builds it")
            continue
        if not gate.open():
            gate.say_once(cfg)
            break
        if loginhold.restore(cfg, board, card, space):
            gate.take()
            done["relogged"] += 1
            done["ids"].add(card["id"])
            log(cfg, f"resumed {card['id']}: the {space} login works again")
    return done


def startable_cards(cfg: Config, board: Board, spaces: set[str]) -> list[dict]:
    """The cards this drain may start now: startable (or claimed here and not yet started),
    in a space it serves, with every repo they name on this disk (`keel/where.py`), in
    QUEUE order (`tree.in_order`): a tree's place, then a slice's
    place in its tree, each his `kb next` when he gave one and filing order otherwise. A
    card still waiting on its `after` is not startable, so no place starts it early."""
    cards = board.list_cards()
    return tree.in_order([card for card in cards
                          if (card["derived"]["startable"] or claimed_unstarted(cfg, card))
                          and where.startable_here(cfg, card, spaces)], cards)


def claim(cfg: Config, board: Board, card: dict) -> bool:
    """Take the card before starting it. A claim that was there first is not an error: the
    card is simply not this drain's to start now."""
    try:
        board.claim(card["id"], cfg.host, "drain")
    except Refused as refusal:
        log(cfg, f"not starting {card['id']}: {refusal}")
        return False
    return True


def start_one(cfg: Config, board: Board, card: dict) -> bool:
    if not claim(cfg, board, card):
        return False
    try:
        result = house.launch(cfg, board, card["id"])
    except house.LiveHouse as live:
        # its old house is still listed (c-605):
        # said once on the card, and nothing is started or stopped
        log(cfg, f"not starting {card['id']}: {live}")
        last = (board.events(card["id"], last=1) or [{}])[-1]
        if last.get("text") != str(live):
            board.note(card["id"], str(live), "drain")
        return False
    except house.AlreadyStarted as already:
        log(cfg, f"not starting {card['id']}: {already}")
        return False
    except Exception as error:  # noqa: BLE001 - one bad card must not stop the pass
        log(cfg, f"failed to start {card['id']}: {error}")
        sight(cfg, board, f"drain:start:{card['id']}",
              f"{card['id']} would not start on {cfg.host}: {error}", card["id"])
        return False
    log(cfg, f"started {card['id']} as {result['bg_id']} ({result['session_id']})")
    return True


def start_cards(cfg: Config, board: Board, spaces: set[str], live: dict,
                card_id: str | None, gate: MemoryGate, browsers: int = 0) -> dict:
    """Start the startable cards in queue order, each against its own pool's limit.

    The two pools fill independently, so a full review pool is passed over rather than
    stopping the pass: the next build in the list still starts. The browser slot is the
    same: a browser card waits while `browsers` (the live ones) fill `browsers_max`, and
    the card behind it still starts. So is a space whose login has expired: its cards wait
    and the other space's still start. The memory gate is not: shut, it starts nothing more.
    `--card` names one card and starts only that one, which is how a paused drain starts
    anything at all; a shut gate refuses it too. `browsers` in the result counts the
    browser cards started.
    """
    if card_id is not None:
        candidates = [card for card in startable_cards(cfg, board, spaces) if card["id"] == card_id]
        if not candidates:
            raise Refused(f"{card_id} is not startable (assigned, unblocked, unarchived, "
                          f"its `after` at review or done, in a space this drain serves or "
                          f"pinned here, its repo on this machine)")
        if not gate.open():
            raise Refused(gate.why())
        if login.is_expired(cfg, candidates[0]["space"]):
            space = candidates[0]["space"]
            raise Refused(login.block_reason(space, cfg.spaces[space].config_dir))
    elif cfg.drain_paused:
        return {**empty_pools(), "browsers": 0}
    else:
        candidates = startable_cards(cfg, board, spaces)
    limit, started, said = limits(cfg), {**empty_pools(), "browsers": 0}, set()
    for card in candidates:
        if login.is_expired(cfg, card["space"]):
            if card["space"] not in said:
                said.add(card["space"])
                gone = login.gone(card["space"], cfg.spaces[card["space"]].config_dir)
                log(cfg, f"{gone}; {card['id']} waits")
            continue
        slot = slot_of(card)
        if live[slot] + started[slot] >= limit[slot]:
            if slot not in said:
                said.add(slot)
                log(cfg, f"{slot} pool full at {limit[slot]}; {card['id']} waits")
            continue
        browser = wants_browser(card)
        if browser and cfg.browsers_max is not None \
                and browsers + started["browsers"] >= cfg.browsers_max:
            if "browser" not in said:
                said.add("browser")
                log(cfg, f"browser slot full at {cfg.browsers_max}; {card['id']} waits")
            continue
        if not gate.open():
            gate.say_once(cfg)
            break
        went = start_one(cfg, board, card)
        if went:
            gate.take()
            started[slot] += 1
            started["browsers"] += browser
    return started


def sight(cfg: Config, board, key: str, what: str, card: str | None = None) -> None:
    """A failure the drain keeps seeing becomes a request to Bosun (`keel/requests.py`):
    each is a sighting by key, and the `[console] repeat_after`-th inside `repeat_minutes`
    opens it. An expired login (its own hold, `keel/loginhold.py`) is not a sighting. Never fails the pass; `board` None opens one."""
    own = board is None
    try:
        board = board or open_board(cfg)
        try:
            requests.sight_on(board, cfg.console, key, what, "drain", card)
        finally:
            if own:
                board.close()
    except Exception as error:  # noqa: BLE001 - a sighting must not break a drain pass
        log(cfg, f"sighting {key} failed: {error}")


def failed_step(cfg: Config, board, name: str) -> None:
    """A step that raised: its traceback to the log, and a sighting keyed by the step."""
    trace = traceback.format_exc().strip()
    log(cfg, f"{name} failed:\n" + trace)
    last = trace.splitlines()[-1] if trace else "no traceback"
    sight(cfg, board, f"drain:step:{name.replace(' ', '-')}", f"the drain's {name} failed on {cfg.host}: {last}")


def talker_upkeep(cfg: Config, holding: bool = True) -> None:
    """Auto-reset the talker when its current run is older than a day (age off Keel's own
    pointer clock), or when Harbor's memory moved on main and it is between turns with no
    voice hold live (`holding`, c-538). One line per reset; never raises out of the pass (a
    talker problem must not stop the drain)."""
    try:
        result = talker.upkeep(cfg, holding=holding)
    except Exception:  # noqa: BLE001 - talker upkeep must not break a drain pass
        failed_step(cfg, None, "talker upkeep")
        return
    if result.get("reset"):
        log(cfg, f"talker auto-reset: {result['reason']}")


def voice_holding(board) -> bool:
    """Whether voice holds a house or Bosun right now: the talker's memory rotation waits
    for it (c-538). A board that cannot say reads as holding, which only waits."""
    try:
        if any(views.voice_hold(card.get("options")) for card in board.list_cards()):
            return True
        if hasattr(board, "conn"):
            from keel import bosunhold
            return bosunhold.live(board) is not None
        return False
    except Exception:  # noqa: BLE001 - a reading, never the pass
        return True


def log_upkeep(cfg: Config) -> None:
    """Cut back any log in `state/logs` that has passed its size (`keel/logtrim.py`). One
    line per cut, and like the talker's upkeep it never raises out of the pass."""
    try:
        cut = logtrim.trim(cfg.logs_dir)
    except Exception:  # noqa: BLE001 - log upkeep must not break a drain pass
        failed_step(cfg, None, "log upkeep")
        return
    if cut:
        log(cfg, f"logs cut back to their tail, the rest kept as .1: {', '.join(cut)}")


def backup_upkeep(cfg: Config) -> None:
    """Start the nightly pull when it is due and this machine is awake, which it is if the
    drain is passing (`backup.pull_upkeep`, c-440). Never raises out of the pass."""
    try:
        result = backup.pull_upkeep(cfg)
    except Exception:  # noqa: BLE001 - backup upkeep must not break a drain pass
        failed_step(cfg, None, "backup upkeep")
        return
    if result.get("started"):
        log(cfg, f"backup pull started: {result['reason']}")


def snapshot_upkeep(cfg: Config, board: Board) -> None:
    """Start the hourly snapshot the service manager did not, and say on the board when
    none has succeeded for two waking hours with one owed (`keel/backupdue.py`, c-750). On the board's
    clock, so inside the pass. Never raises out of it."""
    if not hasattr(board, "conn"):
        return
    try:
        result = backupdue.upkeep(cfg, board)
    except Exception:  # noqa: BLE001 - backup upkeep must not break a drain pass
        failed_step(cfg, board, "backup snapshot upkeep")
        return
    if result.get("started"):
        log(cfg, f"backup snapshot started: {result['reason']}")
    if result.get("notice"):
        log(cfg, f"backup overdue: {result['notice']} says so on the board")
    if result.get("notice_failed"):
        log(cfg, f"backup overdue notice failed: {result['notice_failed']}")
        sight(cfg, board, "drain:step:backup-overdue-notice",
              f"the drain could not say on the board that the backup is overdue on {cfg.host}: "
              f"{result['notice_failed']}")


def logins_upkeep(cfg: Config) -> int:
    """Check the most due rows of this machine's Logins list (`keel/logins.py`, c-558): a
    good one daily, a marked or red one sooner, at most two a pass. After the board is
    closed, since a Claude check is a turn of a few seconds. Each check is one log line.
    Returns how many it checked. Never raises out of the pass."""
    try:
        found = logins.upkeep(cfg)
    except Exception:  # noqa: BLE001 - a credential check must not break a drain pass
        failed_step(cfg, None, "logins upkeep")
        return 0
    for row_id in found["checked"]:
        log(cfg, f"logins: checked {row_id}")
    return len(found["checked"])


def login_asks_upkeep(cfg: Config, board: Board) -> None:
    """One ask per red row of this machine's Logins list, and none once it answers
    (`keel/loginask.py`). Never fails the pass."""
    if not hasattr(board, "conn"):
        return
    try:
        loginask.sync(board, cfg.host, logins.public(cfg))
    except Exception:  # noqa: BLE001 - an ask is one step, not the pass
        failed_step(cfg, board, "login asks")


def board_trash_upkeep(cfg: Config) -> None:
    """Purge the boards deleted more than 30 days ago (`boardtrash.purge`, BD-1): the one
    place a board leaves the trash for good, never a request. Never raises out of the pass."""
    try:
        gone = boardtrash.purge(cfg)
    except Exception:  # noqa: BLE001 - the trash must not break a drain pass
        failed_step(cfg, None, "board trash upkeep")
        return
    if gone:
        log(cfg, f"boards purged from the trash after 30 days: {', '.join(gone)}")


def served_spaces(cfg: Config, spaces: list[str] | None) -> set[str]:
    """The spaces this pass serves: the ones named, else every space."""
    return set(spaces) if spaces else set(cfg.served_spaces())


def once(cfg: Config, spaces: list[str] | None = None, card: str | None = None,
         board: Board | None = None, wait: bool = True) -> dict:
    """One pass, and only one at a time per install (`keel/passlock.py`, c-734 fix check). An
    unscoped pass that finds another under way does nothing, and its log line says it was
    skipped. A card-scoped one (`card`, a tap waiting on it) waits for the other to end, up to
    `passlock.WAIT_SECONDS`, and raises `passlock.Busy` when it does not, never skipping
    silently; with `wait` False (`--no-wait`, a tap that only nudges, Approve outcome's
    landing) it skips at once like an unscoped pass."""
    wait = passlock.WAIT_SECONDS if card and wait else 0
    with passlock.held(cfg, wait, say=lambda text: log(cfg, text)) as mine:
        if not mine:
            if wait:
                raise passlock.Busy(passlock.busy_sentence(card, wait))
            return {"skipped": passlock.SKIPPED}
        return one_pass(cfg, spaces, card, board)


def one_pass(cfg: Config, spaces: list[str] | None = None, card: str | None = None,
             board: Board | None = None) -> dict:
    """One pass: reconcile, then start. Returns the counts for the log line."""
    own = board is None
    served = served_spaces(cfg, spaces)
    board = board or open_board(cfg)
    MIDPASS.begin()
    try:
        # FIRST, before anything that can raise (r1.F6): this pass is the witness that the
        # machine is awake, and a pass that fails further down is still a machine awake
        # with a backup owed. It needs only the board, and it never raises.
        snapshot_upkeep(cfg, board)
        # Every space, whatever this pass serves: the pools are this machine's, so a house
        # of a space left out of `--space` still holds its slot.
        rows = harness.agents_across(space.config_dir for space in cfg.spaces.values())
        gate = MemoryGate(cfg)
        relayed = carry_relays(cfg, board, rows, served, gate)
        landing_upkeep(cfg, board)
        deploy_upkeep(cfg, board)
        login_asks_upkeep(cfg, board)
        rotate_upkeep(cfg, board, rows)
        # Before anything reads a card's state: a hold that ran out is not a hold, and the
        # house under it is an ordinary house again for the rest of this pass.
        # What the kick thread carries while this pass runs joins the skips as it happens.
        relayed["ids"] = PassSkips(relayed["ids"])
        holds = release_holds(cfg, board, served, gate, relayed["ids"])
        done_here = relayed["ids"] | holds["skip"] | dropin_upkeep(cfg, board, rows, served,
                                                                   relayed["ids"])
        relogged = login_upkeep(cfg, board, served, gate, done_here)
        done_here = done_here | relogged["ids"]
        counts = reconcile(cfg, board, rows, served, gate, done_here)
        # Before the quiet rule: a house paused on a permission prompt is blocked, never put
        # back with the rate limit's prompt.
        pauses = permission_upkeep(cfg, board, rows, served, done_here)
        quiet = resume_quiet(cfg, board, rows, served, gate, done_here)
        jobs = jobs_upkeep(cfg, board, rows, served, done_here)
        retired = retire_tracking(cfg, board, rows, served, done_here)
        closing = close_tracking(cfg, board, served, done_here)
        # The houses this pass resumed are not in `rows` (that is why they were resumed),
        # so their cards join the ones the listing gave before the pools are counted. A
        # union rather than a running total: a card whose stale row is still listed under
        # its name must fill one slot, not two.
        ids = house_ids(board, rows) | counts["resumed_ids"] | holds["ids"] | relogged["ids"]
        live = pool_counts(board, ids)
        live = {slot: live[slot] + relayed["pools"][slot] for slot in POOLS}
        browsers = browser_count(board, ids) + relayed["browsers"]
        tend(cfg, board, rows, ids)
        browsers += MIDPASS.take(live)
        ship_closed: set[str] = set()
        ship_resumed = ship_upkeep(cfg, board, served, live, gate, done_here, ship_closed)
        live[HOUSE_SLOT] += ship_resumed
        # c-718: after the watcher, so a parent it found merged this pass is done already
        stack_told = stack_upkeep(cfg, board, served, rows, live, gate)
        live[HOUSE_SLOT] += stack_told
        # a house the watcher closed for its re-offer is still in `rows`: not looked at again
        idled = idle_upkeep(cfg, board, rows, served, done_here | ship_closed)
        downs = teardown_upkeep(cfg, board, served, rows)
        review_upkeep(cfg, board, served)
        bosun_hold_upkeep(cfg, board)
        wake_upkeep(cfg, board)
        browsers += MIDPASS.take(live)
        started = start_cards(cfg, board, served, live, card, gate, browsers)
        holding = voice_holding(board)
    finally:
        MIDPASS.end()
        if own:
            board.close()
    talker_upkeep(cfg, holding)
    log_upkeep(cfg)
    backup_upkeep(cfg)
    logins_upkeep(cfg)
    board_trash_upkeep(cfg)
    pools = {slot: live[slot] + started[slot] for slot in POOLS}
    summary = {"houses": pools[HOUSE_SLOT], "reviews": pools[REVIEW_SLOT],
               "paused": cfg.drain_paused, "started": sum(started[slot] for slot in POOLS),
               "resumed": counts["resumed"], "blocked": counts["blocked"] + quiet["blocked"]}
    # A quiet house put back is counted apart from `resumed=`, which is a house that exited:
    # the two are different faults with different evidence, and the log line says which.
    if quiet["resumed"]:
        summary["stuck"] = quiet["resumed"]
    for key in ("denied", "recovered"):
        if pauses[key]:
            summary[key] = pauses[key]
    if counts["login"] + quiet["login"]:
        summary["login"] = counts["login"] + quiet["login"]
    if relogged["relogged"]:
        summary["relogged"] = relogged["relogged"]
    if relayed["carried"]:
        summary["carried"] = relayed["carried"]
    if relayed["held"]:
        summary["held"] = len(relayed["held"])
    if ship_resumed:
        summary["ship_resumed"] = ship_resumed
    if downs:
        summary["torn_down"] = downs
    for key in ("ended", "closed"):
        if idled[key]:
            summary[f"idle_{key}"] = len(idled[key])
    if retired:
        summary["retired"] = retired
    if jobs:
        summary["jobs"] = jobs
    if closing["closed"]:
        summary["closing"] = closing["closed"]
    if closing["back"]:
        summary["unclosed"] = closing["back"]
    if holds["released"]:
        summary["holds"] = holds["released"]
    if cfg.browsers_max is not None:
        summary["browsers"] = browsers + started["browsers"]
    if gate.reading() is not None:
        summary["memory"] = gate.reading()
    return summary


def answers_upkeep(cfg: Config, board) -> bool:
    """His answers to Bosun's asks, told to Bosun (c-521, `keel/asks.py`): on Bosun's machine
    only, and only when it is up and idle (`consolewake.wake`, a message into its live session,
    c-530). The message only names the answers; Bosun reads them with `kb console hook`,
    which confirms them. The answers are CLAIMED first, a lease, so each pass does not send
    again while Bosun reads; a claim nobody confirms runs out and the answers are pointed at
    again, at most `asks.POINTS_MAX` times (then they wait for the hook atop his next
    message, which takes a wake's claim). After a failed relay the wakes rest for
    `consolewake.BACKOFF_MINUTES`. A relay
    that certainly failed hands them back; one that may have sent keeps the claim. Either
    is sighted like any step. Never fails the pass. True once a wake was tried, whatever came
    of it: then nothing else wakes Bosun in this pass (`pause_upkeep` waits)."""
    tried = False
    try:
        if not consolewake.can_wake(cfg):
            return False
        pending = asks.call(board, "drain", "pending")
        if not pending:
            return False
        claimed = asks.call(board, "drain", "claim", ids=[row["id"] for row in pending], via="wake")
        if not claimed:
            return False
        ids = [row["id"] for row in claimed]
        tried = True
        try:
            done = consolewake.wake(cfg, consolewake.answers_note(ids), ", ".join(ids))
        except relay.RelayUnclear:
            raise           # it may have been sent: the lease runs out instead
        except BaseException:
            asks.call(board, "drain", "unclaim", ids=ids, via="wake")
            raise
        if done is None:
            asks.call(board, "drain", "unclaim", ids=ids, via="wake")
            return False            # nothing was sent, so the paused cards may go
        log(cfg, f"Bosun told of {', '.join(ids)}")
    except Exception:  # noqa: BLE001 - telling Bosun is one step, not the pass
        failed_step(cfg, board, "answer wake")
    return tried


def wake_upkeep(cfg: Config, board) -> None:
    """At most one wake of Bosun a pass: his answers first; a Bosun just told them is not yet
    listed as busy, and a second message would land mid-answer, so the paused houses wait
    for the next pass (c-522, c-584). Whatever starts the pass, no two wakes land back to
    back (`consolewake.SPACING_SECONDS`, c-734)."""
    if not answers_upkeep(cfg, board):
        pause_upkeep(cfg, board)


def bosun_hold_upkeep(cfg: Config, board) -> None:
    """A voice hold on Bosun that ran out (c-523, `keel/bosuntalk.py`): on Bosun's machine,
    the conversation is closed and Bosun woken if voice stopped it, then the hold cleared,
    as `release_holds` does for a house. Before the wakes, so a Bosun put back this pass is
    told what waits the next. Never fails the pass."""
    try:
        from keel import bosuntalk
        if bosuntalk.release_expired(cfg, board):
            log(cfg, "Bosun's voice hold ran out; the conversation is closed")
    except Exception:  # noqa: BLE001 - one step, not the pass
        failed_step(cfg, board, "bosun voice hold")


def pause_upkeep(cfg: Config, board) -> None:
    """Bosun woken for a house auto mode paused on a permission prompt, on any card (c-584,
    `keel/pausewake.py`): on Bosun's machine only, only when it is up and idle (the same
    `consolewake` message as his answers). Each card told gets a `wake` event, so a pause
    wakes Bosun once. A wake that did not happen writes nothing, and the next pass tries
    again. Never fails the pass."""
    try:
        if not consolewake.can_wake(cfg):
            return
        found = pausewake.call(board, "drain", "wakes")
        if not found:
            return
        ids = [row["card"] for row in found]
        done = consolewake.wake(cfg, pausewake.wake_prompt(found), "the paused houses: " + ", ".join(ids))
        if done is None:
            return
        pausewake.call(board, "drain", "woke", ids=[f"{row['card']}@{row['event']}" for row in found])
        log(cfg, f"Bosun woken for {', '.join(ids)}")
    except Exception:  # noqa: BLE001 - waking Bosun is one step, not the pass
        failed_step(cfg, board, "pause wake")


def landing_upkeep(cfg: Config, board: Board) -> None:
    """A landing worker that died is answered on its card, and (with `merge_queue` on) one
    card at review has its merged tree pre-run (`keel/landing.py`). Never fails the pass."""
    try:
        landing.upkeep(cfg, board)
    except Exception:  # noqa: BLE001 - the landings are one card each, not the pass
        failed_step(cfg, board, "landing upkeep")


def deploy_upkeep(cfg: Config, board: Board) -> None:
    """The deploy ask and his Deploy (`keel/deploy.py`, c-526): on the board's own host, an
    integration branch ahead of the trunk is asked about once per sha, and his Yes starts the
    worker. Never fails the pass."""
    try:
        deploy.upkeep(cfg, board)
    except Exception:  # noqa: BLE001 - a deploy is one step, not the pass
        failed_step(cfg, board, "deploy upkeep")


def idle_upkeep(cfg: Config, board: Board, rows: list[dict], served: set[str], skip) -> dict:
    """a-72 (c-607, `keel/shipidle.py`): a merged card's idle house ended, and a shipping house
    idle over two hours by its own Stop closed until its next batch; never a working house,
    each checked again on a fresh listing right before the stop. Never fails the pass."""
    try:
        return shipidle.upkeep(cfg, board, rows, served, skip)
    except Exception:  # noqa: BLE001 - one step, not the pass
        failed_step(cfg, board, "idle upkeep")
        return {"ended": [], "closed": []}


def ship_upkeep(cfg: Config, board: Board, served: set[str], live: dict, gate: MemoryGate,
                skip=frozenset(), closed: set | None = None) -> int:
    """The pull request watcher (`keel/shipping.py`, lane SHIP): look at the shipping cards'
    pull requests and tell each house its batch when one is due. Every batch, told into a
    live house or resuming an exited one, takes a HOUSE slot and the memory gate, like any
    start (c-600 review). The number of houses woken. Never fails the pass. `skip`: the cards
    this pass already acted on, as the idle step is given them (`shipidle.before_batch`);
    `closed` is filled with the cards whose idle house the watcher closed for a re-offer."""
    room = max(limits(cfg)[HOUSE_SLOT] - live[HOUSE_SLOT], 0) if gate.open() else 0
    try:
        result = shipping.upkeep(cfg, board, served, room, skip=skip)
    except Exception:  # noqa: BLE001 - the watcher is one step, not the pass
        failed_step(cfg, board, "shipping upkeep")
        return 0
    if closed is not None:
        closed.update(result.get("closed") or ())
    woken = len(result["told"]) + len(result["resumed"])
    for _ in range(woken):
        gate.take()
    return woken


def stack_upkeep(cfg: Config, board: Board, served: set[str], rows: list[dict], live: dict,
                 gate: MemoryGate) -> int:
    """Stacked cards (`keel/stackwatch.py`, c-718): a parent dropped blocks its card, a parent
    landed aims its card's change at the base and tells its house, a parent's branch that moved
    is told. A tell starts a turn, so it takes a HOUSE slot and the memory gate like a batch.
    The number of houses told. Never fails the pass."""
    room = max(limits(cfg)[HOUSE_SLOT] - live[HOUSE_SLOT], 0) if gate.open() else 0
    try:
        result = stackwatch.upkeep(cfg, board, served, rows, room)
    except Exception:  # noqa: BLE001 - stacking is one step, not the pass
        failed_step(cfg, board, "stacking upkeep")
        return 0
    for _ in result["told"]:
        gate.take()
    return len(result["told"])


def teardown_upkeep(cfg: Config, board: Board, served: set[str], rows: list[dict]) -> int:
    """A card that left building has its own containers torn down, once per building spell
    (`keel/teardown.py`, c-532), its worktree kept. How many cards. Never fails the pass."""
    try:
        done = teardown.upkeep(cfg, board, served, rows)
    except Exception:  # noqa: BLE001 - a teardown is one step, not the pass
        failed_step(cfg, board, "teardown upkeep")
        return 0
    if done:
        log(cfg, f"containers torn down for {', '.join(done)}: they left building")
    return len(done)


def review_upkeep(cfg: Config, board: Board, served: set[str]) -> None:
    """The review fetcher (`keel/reviewcards.py`, lane RC): a review card per pull request
    that needs him, a notice for one that closed first, new commits flagged on a posted
    one. It starts nothing: a review card runs when he assigns it, through `start_cards`
    below, in the review pool. Never fails the pass."""
    try:
        reviewcards.upkeep(cfg, board, served)
    except Exception:  # noqa: BLE001 - the fetcher is one step, not the pass
        failed_step(cfg, board, "review upkeep")


def rotate_upkeep(cfg: Config, board: Board, rows: list[dict]) -> None:
    """Start the fresh session of every rotation of this machine whose checkpoint is written
    (`keel/rotate.py`). Never fails the pass, and does nothing with `[keel] rotate` off."""
    if not cfg.rotate:
        return
    try:
        rotated = rotate.upkeep(cfg, board, rows)
    except Exception:  # noqa: BLE001 - a rotation is one card, not the pass
        failed_step(cfg, board, "rotate upkeep")
        return
    if rotated:
        log(cfg, f"rotated {rotated} house(s) into fresh sessions")


def run(cfg: Config) -> None:
    """Loop every `poll_seconds`, one log line per pass, never raising out of the loop."""
    log(cfg, f"drain up: houses_max={cfg.houses_max} reviews_max={cfg.reviews_max} "
             f"browsers_max={cfg.browsers_max} memory_floor={cfg.memory_floor_mb}MB "
             f"house_nice={cfg.house_nice} poll={cfg.poll_seconds}s "
             f"paused={cfg.drain_paused} spaces={','.join(cfg.served_spaces())} "
             f"host={cfg.host}")
    started_on = merging.code_head(cfg.root)
    config_on = config_stamp(cfg)
    packclones.reconcile(cfg)       # c-740: the packs repo ignores a pack cloned into its folder
    packs_on = packs_head(cfg)
    restart.started(started_on)
    announce(cfg)
    # A service the install never had is brought up, once per start (c-742).
    appservices.upkeep(cfg, lambda text: log(cfg, text), lambda step: failed_step(cfg, None, step))
    inbox = kick.Inbox.open(cfg)
    if inbox is None:
        why = ("ANOTHER DRAIN is listening on it; two drains on one state dir is a fault, and "
               "this one takes no kicks" if kick.held_by_another(kick.socket_path(cfg))
               else "it could not be bound")
        log(cfg, f"no kick inbox at {kick.socket_path(cfg)}: {why}; relays wait for the pass")
    kicks = kick.Listener(inbox, lambda: carry_pass(cfg),
                          lambda: failed_step(cfg, None, "kick thread")).start() if inbox else None
    try:
        while True:
            moved = ("code" if code_moved(cfg, started_on)
                     else "config" if config_moved(cfg, config_on)
                     else "packs" if packs_moved(cfg, packs_on) else None)
            if moved == "config" and not config_loads(cfg):
                config_on, moved = config_stamp(cfg), None
            if moved and restart_now(cfg, moved):
                log(cfg, f"{moved} moved since start; restarting between passes")
                if kicks is not None:
                    kicks.stop(timeout=None)    # a carry under way always finishes first
                os.execv(sys.executable, [sys.executable, *sys.argv])
            run_pass(cfg)
            rest(cfg, kicks)
    finally:
        if kicks is not None:
            kicks.stop()
        if inbox is not None:
            inbox.close()


def run_pass(cfg: Config) -> None:
    """One pass of the loop, its line in the log with how long it took; never raises."""
    began = time.monotonic()
    try:
        log(cfg, pass_line(once(cfg), time.monotonic() - began))
    except Exception:  # noqa: BLE001 - the loop is the thing that must not die
        failed_step(cfg, None, "pass")


def pass_line(summary: dict, seconds: float) -> str:
    """The pass's log line: its summary and how long it ran, so a long pass shows (c-608)."""
    return f"{summary_line(summary)} in {seconds:.1f}s"


def rest(cfg: Config, kicks) -> None:
    """Wait out `poll_seconds` between passes. The kicks need no wait here: the kick thread
    (`kick.Listener`, c-608) carries them the moment they come, even while a pass runs."""
    time.sleep(cfg.poll_seconds)


def carry_pass(cfg: Config) -> int:
    """A kick's pass: a Deploy he just said started (`deploy.kicked`, c-636), then the
    listing and `carry_relays` under `CARRY_LOCK`, so the listing is taken after any carry
    under way, and nothing else. The deploy goes first and on its own: no harness listing or
    carry delays it, and its failure is logged and changes nothing the carry reports (review
    F4, F5). Returns how many relays are still held; never raises (the kick thread must not
    die). What it carries while a pass runs is left alone by the rest of that pass
    (`MIDPASS`)."""
    try:
        board = open_board(cfg)
        try:
            try:
                deploy.kicked(cfg, board)   # his Deploy starts now, not at the next pass
            except Exception:  # noqa: BLE001 - the deploy's trouble is its own; the carry goes on
                failed_step(cfg, board, "deploy kick")
            with CARRY_LOCK:
                rows = harness.agents_across(space.config_dir for space in cfg.spaces.values())
                done = carry_locked(cfg, board, rows, served_spaces(cfg, None), MemoryGate(cfg),
                                    midpass=MIDPASS)
                MIDPASS.add(done)
        finally:
            board.close()
    except Exception:  # noqa: BLE001 - a kick is a shortcut; the pass is the fallback
        failed_step(cfg, None, "kick")
        return 0
    if done["carried"]:
        log(cfg, f"kick: carried={done['carried']}" + (f" held={len(done['held'])}" if done["held"] else ""))
    return len(done["held"])


class MidPass:
    """What the kick thread carried while a pass runs (c-608). The pass's listing predates
    it, so the rest of the pass leaves those cards alone, as it does the ones its own carry
    took (`PassSkips`), and the pool slots they took are counted before it starts anything."""

    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.ids: set[str] = set()
        self.pools, self.browsers = empty_pools(), 0

    def begin(self) -> None:
        with self.lock:
            self.running, self.ids = True, set()
            self.pools, self.browsers = empty_pools(), 0

    def end(self) -> None:
        with self.lock:
            self.running, self.ids = False, set()

    def add(self, done: dict) -> None:
        with self.lock:
            if not self.running:
                return
            self.ids |= done["ids"]
            for slot in POOLS:
                self.pools[slot] += done["pools"][slot]
            self.browsers += done["browsers"]

    def mark(self, card_id: str) -> None:
        with self.lock:
            if self.running:
                self.ids.add(card_id)

    def unmark(self, card_id: str) -> None:
        with self.lock:
            self.ids.discard(card_id)

    def has(self, card_id: str) -> bool:
        with self.lock:
            return card_id in self.ids

    def take(self, live: dict) -> int:
        """Add the slots carried since the last take to `live`; returns the browsers."""
        with self.lock:
            for slot in POOLS:
                live[slot] += self.pools[slot]
            browsers = self.browsers
            self.pools, self.browsers = empty_pools(), 0
        return browsers


MIDPASS = MidPass()


class PassSkips(set):
    """A pass's skips that also hold every card the kick thread carries while it runs."""

    def __contains__(self, card_id) -> bool:
        return set.__contains__(self, card_id) or MIDPASS.has(card_id)

    def __or__(self, other):
        return PassSkips(set(self) | set(other))


def restart_now(cfg: Config, moved: str = "code") -> bool:
    """The code moved: exec now unless this process is holding a conversation or answering
    a house call, which an exec would cut (`keel/restart.py`, c-557). The wait is said once
    per reason, and `state/drain.json` carries it."""
    now, said = restart.due(moved)
    if said:
        log(cfg, said)
        announce(cfg)       # so `keel doctor` on this machine says what it waits for
    return now


def code_moved(cfg: Config, started_on: str | None) -> bool:
    """True when the checkout is on a different commit than this process loaded. Checked
    between passes only, never mid-pass, so a restart interrupts nothing. In a process the
    drain shares with the deck this is the only code-moved restart (`cli.role_run` turns
    the deck's own `serve.follow_code` off there, c-637).

    A head that cannot be read (no repo, or a git that did not answer in `GIT_SECONDS` on a
    loaded box) is unknown, and unknown is NOT moved: this is called outside `run`'s try, so
    anything raised here ends the loop rather than one pass (`merging.git`, 2026-09-20)."""
    head = merging.code_head(cfg.root)
    return bool(head and started_on and head != started_on)


def packs_head(cfg: Config) -> dict | None:
    """The install's packs repo head (c-619), under the key `""`, and the head of each pack
    that is its own clone in the packs folder, by its folder (c-740, `keel/packclones.py`): a
    pack the user's Approve outcome landed, or one a `git pull` updated, is read by a drain
    started after it, so a move restarts this one, as the config does. None off an install,
    and a head that cannot be read is None: unknown is not moved."""
    home = cfg.install_home
    if not home or not (home / "packs" / ".git").exists():
        return None
    clones = packclones.nested(home / "packs")
    return {"": merging.code_head(home / "packs"),
            **{name: merging.code_head(path) for name, path in clones.items()}}


def packs_moved(cfg: Config, started: dict | None) -> bool:
    """The packs repo's head known at both readings and differing; a clone's head known now
    and not the one this drain started on (its first head counts, once: a clone seen with no
    head yet, mid-clone, is not counted until it has one, r1.F6); or a clone that had a head
    and whose folder is gone. A head that cannot be read now moves nothing."""
    now = packs_head(cfg)
    if not now or not started:
        return False
    if now.get("") and started.get("") and now[""] != started[""]:
        return True
    clones = (set(now) | set(started)) - {""}
    return any((now[key] is not None and now[key] != started.get(key)) if key in now
               else started[key] is not None for key in clones)


def config_stamp(cfg: Config) -> tuple[int, int] | None:
    """The config file's mtime and size, or None when it cannot be read."""
    try:
        found = Path(cfg.source).stat() if cfg.source else None
    except OSError:
        return None
    return (found.st_mtime_ns, found.st_size) if found else None


def config_loads(cfg: Config) -> bool:
    """The moved config loads as Keel loads it; one that does not is said once and the
    running config kept (the caller re-stamps), never exec'd into a drain that cannot start."""
    try:
        config_module.load(cfg.source, ensure=False)
    except Exception as error:  # noqa: BLE001 - anything load raises keeps the running config
        log(cfg, f"config moved but does not load: {error}; keeping the running one")
        return False
    return True


def config_moved(cfg: Config, started: tuple[int, int] | None) -> bool:
    """True when the config file changed since this process loaded it (the deck's Setup
    view wrote it, `keel/onboarding.py`, or a person did): the drain re-execs between
    passes, as for moved code, so a new space or repo is served without a restart by hand.
    A file that cannot be read now is unknown, and unknown is not moved."""
    now = config_stamp(cfg)
    return bool(now and started and now != started)
