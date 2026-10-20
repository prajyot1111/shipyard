"""The live strip: what a work house is doing now, on its card, while he is watching (c-599).

One line per live card: its status (working, idle, exited; "waiting on a prompt" is the
board's newest Notification, `notice`), how long its turn has run, its last tool, its todo
progress, its jobs, what the harness says it is doing, and when each was so. Facts with
ages, never a verdict: nothing here says a house is stuck. The facts come from the harness
alone (`claude agents --json`, its job record and its transcript, `keel/livetail.py`), and
they are held IN MEMORY: nothing is written to the board, and a restarted deck has none
until the next read.

Two reads, and what each costs:

- **While a deck watches** (an `/api/events` stream is open). The deck's `Watcher` thread
  exists only then. Every `LIVE_SECONDS` it reads the houses (the deck's shared listing,
  `Deck.listing`), holds the facts in `Strip` and says `live <c-id> <json>` on the event
  stream, which the page patches in place, fetching nothing. The last stream closing ends
  the thread. Nobody watching costs nothing.
- **When the state document is built** (`deckstate`), from the listing that build already
  makes.

What the strip carries is redacted where it is read (`livetail.safe`): a tool call is its
name and a short line from the field that says what it does, secrets hidden, and an MCP
tool is its name alone.
"""

import json
import sys
import threading
import time
import traceback
from datetime import datetime

from keel import deckevents, harness, housejobs, housemem, livetail
from keel.config import Config

VERB = "live"
LIVE_SECONDS = 3.0          # how often a watched deck reads its houses
CLOSE_SECONDS = 30.0        # how long a closing deck waits for its watcher's last read
REPUBLISH_SECONDS = 30.0    # a card's facts are said again this often while watched, moved or not
WORKING, IDLE, EXITED = "working", "idle", "exited"
LIVE_STAGES = ("planning", "building", "review", "shipping")
# Board events that begin a house's turn, and the hooks that end one (`drain.quiet_turn`).
TURN_STARTS = ("resume", "session")
TURN_ENDS = ("Stop", "SessionEnd")
NOTICE_CHARS = 160


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ----- which cards, which row -----

def watched(cfg: Config, cards: list[dict]) -> list[dict]:
    """The cards whose house is worth a line: live or blocked, with a session, not
    archived, in a space this machine serves."""
    served = cfg.served_spaces()
    return [card for card in cards
            if card.get("session_id") and card.get("space") in served
            and not (card.get("derived") or {}).get("archived")
            and (card.get("stage") in LIVE_STAGES or card.get("blocked_reason"))]


def card_of(card_id: str, space: str, stage: str, blocked_reason, session_id, options: str) -> dict:
    """A card as `watched` reads it, from the board's own columns (`Deck.strip_cards`)."""
    try:
        opts = json.loads(options or "{}")
    except ValueError:
        opts = {}
    opts = opts if isinstance(opts, dict) else {}
    return {"id": card_id, "space": space, "stage": stage, "blocked_reason": blocked_reason,
            "session_id": session_id, "options": opts, "derived": {"archived": opts.get("archived") is True}}


def row_of(card: dict, rows: list[dict]) -> dict | None:
    """The agents row for this card's session, by uuid or by the house's name."""
    row = harness.find(card.get("session_id") or "", rows)
    if row is None:
        row = next((r for r in rows if r.get("name") == card["id"] and r.get("kind") == "background"), None)
    return row


def status_of(row: dict | None) -> str:
    if row is None:
        return EXITED
    return WORKING if housejobs.working(row) else IDLE


# ----- one card's facts -----

def card_facts(cfg: Config, card: dict, rows: list[dict], at: str | None = None,
               procs: dict | None = None) -> dict:
    """What the harness says of this card's house now. `at` is when it was read: the page
    measures every age against it. `procs` is this machine's process table (`housemem.table`), which gives
    `mem_mb`, the RSS of the listed pid's tree (c-607); None when the row has no pid."""
    from keel import dropin     # noqa: PLC0415 - dropin reaches housejobs, as this does
    space = cfg.spaces[card["space"]]
    row = row_of(card, rows)
    bg_id = (row or {}).get("id") or (card.get("session_id") or "")[:8]
    record = livetail.job(space.config_dir, bg_id)
    path = livetail.transcript_path(space.config_dir, card.get("session_id") or "",
                                    (row or {}).get("cwd"), record.get("transcript"))
    facts = {"at": at or now_iso(), "host": cfg.host, "session": card.get("session_id"),
             "status": status_of(row),
             "house": dropin.row_facts(row),
             "mem_mb": housemem.mem_mb((row or {}).get("pid"), procs or {}, job_pids(space.config_dir, row)),
             "detail": record.get("detail"), "detail_at": record.get("updated_at"),
             "agents": record.get("agents") or [],
             "jobs": [dict(job, label=livetail.safe(job.get("label"), livetail.TODO_CHARS))
                      for job in (housejobs.of_row(space.config_dir, row) if row else [])]}
    facts.update(livetail.tail(path))
    return facts


def job_pids(config_dir, row: dict | None) -> list:
    """The pids the house's job record names for its background shells, when it names any
    (c-607 review: a shell reparented to pid 1 is no longer under the house's own pid)."""
    if not row:
        return []
    bg_id = row.get("id") or (row.get("sessionId") or "")[:8]
    return [task.get("pid") for task in housejobs.fan(config_dir, bg_id) if task.get("pid")]


def facts_for(cfg: Config, cards: list[dict], rows: list[dict]) -> dict:
    """`{card id: facts}` for every watched card here; a card that cannot be read is left
    out rather than failing the rest."""
    at, out = now_iso(), {}
    own = watched(cfg, cards)
    # one process table per read, and only when a listed house has a pid to look up (c-607)
    procs = housemem.table() if any((row_of(card, rows) or {}).get("pid") for card in own) else {}
    for card in own:
        try:
            out[card["id"]] = card_facts(cfg, card, rows, at, procs)
        except Exception:  # noqa: BLE001 - one unreadable house is not the strip
            traceback.print_exc(file=sys.stderr)
    return out


def same(one: dict | None, other: dict | None) -> bool:
    """Equal but for when they were read: a read that found nothing new is not news."""
    if one is None or other is None:
        return one is other
    return {k: v for k, v in one.items() if k != "at"} == {k: v for k, v in other.items() if k != "at"}


# ----- the newest Notification (the board's, drawn at once) -----

def notice(card: dict, events: list[dict]) -> dict | None:
    """The newest Notification of the house's current turn: `{type, message, at}`, or None.

    Walked newest first to the event the turn began with. A Stop or SessionEnd from the
    card's own session on the way means the turn ended, and what it asked is over. The
    hook reaches the board within seconds of the harness firing it, so this is what shows
    a permission prompt at once, well before the drain would block the card."""
    for event in reversed(events):
        if event["kind"] in TURN_STARTS:
            return None
        data = event.get("data") or {}
        if event["kind"] != "hook" or data.get("session_id") not in (None, card.get("session_id")):
            continue
        if data.get("hook") in TURN_ENDS:
            return None
        if data.get("hook") == "Notification":
            payload = data.get("payload") or {}
            return {"type": payload.get("notification_type") or "notification",
                    "message": livetail.safe(payload.get("message"), NOTICE_CHARS), "at": event["at"]}
    return None


NOTICE_SLACK_SECONDS = 2.0


def written_past(notice: dict, facts: dict | None) -> bool:
    """The transcript has a record newer than the notice (by more than the slack the two
    clocks' writes need): the house carried on, so what it asked has been answered. The page
    applies the same rule to a newer reading (`app/ui.live.js`)."""
    try:
        wrote = datetime.fromisoformat(str((facts or {}).get("wrote_at")).replace("Z", "+00:00"))
        said = datetime.fromisoformat(str(notice.get("at")).replace("Z", "+00:00"))
        return (wrote - said).total_seconds() > NOTICE_SLACK_SECONDS
    except (ValueError, TypeError):
        return False


# ----- the deck: what it holds -----

class Strip:
    """The newest facts per card, held by the deck process, never the board. `publish` is
    the event stream's send, for the tests."""

    def __init__(self, clock=time.time, publish=None):
        self.clock = clock
        self.publish = publish or deckevents.HUB.send
        self.lock = threading.Lock()
        self.by_card: dict[str, dict] = {}

    def accept(self, host: str, cards: dict, gone=(), full: bool = False, quiet: bool = False) -> list[str]:
        """Take this machine's facts; `full` says `cards` is all of them, so a card no
        longer named is gone. Says `live <id> <facts>` for each that moved, or that has
        not been said for REPUBLISH_SECONDS (so a page's "read 2s ago" stays true of a house
        that is doing nothing new while it is watched), and `live <id> null` for each gone;
        returns their ids. `quiet` holds them and says nothing: the watcher's first read,
        which the page's own document already carries."""
        host = str(host or "").strip()
        if not host:
            raise ValueError("live facts need the host they came from")
        cards = {str(k): v for k, v in (cards or {}).items() if isinstance(v, dict)}
        now, said = self.clock(), []
        with self.lock:
            if full:
                gone = list(gone) + [card_id for card_id, held in self.by_card.items()
                                     if held["host"] == host and card_id not in cards]
            for card_id, facts in cards.items():
                held = self.by_card.get(card_id)
                facts = dict(facts, host=host)
                stale = held is not None and now - held["said"] >= REPUBLISH_SECONDS
                news = held is None or not same(held["facts"], facts) or stale
                if news and not quiet:
                    said.append((card_id, facts))
                self.by_card[card_id] = {"facts": facts, "host": host, "got": now,
                                         "said": now if news else held["said"]}
            for card_id in gone:
                held = self.by_card.get(str(card_id))
                if held and held["host"] == host:
                    del self.by_card[str(card_id)]
                    said.append((str(card_id), None))
        for card_id, facts in said:
            self.publish(f"{VERB} {card_id} {json.dumps(facts, separators=(',', ':'))}")
        return [card_id for card_id, _ in said]

    def of(self, card_id: str) -> dict | None:
        with self.lock:
            held = self.by_card.get(card_id)
            return dict(held["facts"]) if held else None

    def of_session(self, card: dict, fresh: float | None = None) -> dict | None:
        """`of`, only when it was read of the card's CURRENT session (a read from before a
        resume says nothing about the session that replaced it) and, with `fresh`, no older
        than that many seconds."""
        with self.lock:
            held = self.by_card.get(card["id"])
            if held is None or held["facts"].get("session") != card.get("session_id"):
                return None
            if fresh is not None and self.clock() - held["got"] > fresh:
                return None
            return dict(held["facts"])

# ----- the deck: the watcher -----

class Watcher:
    """The deck's thread while a stream is open: its houses every LIVE_SECONDS. `watching`
    says whether anybody is (the hub's count)."""

    def __init__(self, deck, watching=None, wait=None):
        self.deck = deck
        self.watching = watching or (lambda: deckevents.HUB.count() > 0)
        self.stop = threading.Event()
        self.wait = wait or self.stop.wait
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.cards: list[dict] = []
        self.stamp = None
        self.primed = False     # the deck's first read of its own houses is held, not said

    def ensure(self) -> None:
        """Start the thread unless it runs."""
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self.run, name="keel-live-watch", daemon=True)
            self.thread.start()

    def close(self, timeout: float = CLOSE_SECONDS) -> None:
        """Stop reading and wait for a read in flight to finish. Setting `stop` alone left
        a `claude agents` running after the server closed, writing into a config dir its
        owner was already removing (c-599 follow-up); the join makes close mean done."""
        self.stop.set()
        with self.lock:
            thread = self.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def run(self) -> None:
        """Read while anybody watches. The exit is decided under the lock `ensure` takes,
        and asks once more: a stream that opened as this was leaving is read, not missed."""
        try:
            while True:
                while self.watching() and not self.stop.is_set():
                    try:
                        self.step()
                    except Exception:  # noqa: BLE001 - a bad read is the next one's to redo
                        traceback.print_exc(file=sys.stderr)
                    self.wait(LIVE_SECONDS)
                with self.lock:
                    if self.watching() and not self.stop.is_set():
                        continue
                    return
        finally:
            with self.lock:
                self.thread = None

    def step(self) -> None:
        cfg = self.deck.cfg
        cards = self.local_cards()
        rows = []
        if cards:
            with self.deck.lock:
                # as it is now, not a kept reading up to two seconds old (c-638 review)
                join = self.deck.listing(fresh=True)
            rows = join()
        self.deck.strip.accept(cfg.host, facts_for(cfg, cards, rows), full=True, quiet=not self.primed)
        self.primed = True

    def local_cards(self) -> list[dict]:
        """The watched cards, read off the board again only when it moved."""
        stamp = self.deck.board_stamp()
        if stamp != self.stamp:
            self.cards = watched(self.deck.cfg, self.deck.strip_cards())
            self.stamp = stamp
        return self.cards
