"""A warm copy of the board, refreshed off the hot path.

WHY WARM. The answer hop is budgeted at 5 ms typical and 20 ms worst case, and building
the board document costs two `kb` subprocesses and one `claude agents --json`. Running
those inside the turn would put real time into the one hop this design claims is free.
So a background thread keeps a parsed copy and the turn reads a reference.

WHAT IT IS BUILT FROM NOW (2026-09-18, decision V16). THE DECK: one loopback
`GET http://127.0.0.1:<serve_port>/api/state`, folded by `keel/deckdigest.py` into the
document `index.py` reduces. The deck is the tailnet root, it is up whenever the phone
can reach voice at all, and it already carries everything either Harbor is asked about
out loud, the review cards included and a pull request on its card. When it does not answer,
`board_only_doc` builds the narrower document from `kb list --json`, `kb needs-you --json`
and `claude agents --json`, and the document says which of the two it is (`source`).

THIS DOCSTRING USED TO CARRY A BYTE COUNT AND NOTHING CAUGHT IT DRIFTING, 19 TIMES OVER
(c-201), so there is no byte count here. There is an endpoint again, and the risk that
came with it the first time is answered differently this time: the reduction is capped
per section in `keel/deckdigest.py`, every section carries its real count beside its
capped sample, and the selftest measures the digest rather than describing it. The
fallback path still costs three subprocesses on a cadence, bounded by FETCH_TIMEOUT.

WHY IT IS ALLOWED TO BE SLIGHTLY OLD. Everything built from it is a reading of a record,
and a record read two seconds ago is still a reading of that record. What it must never
be is INCONSISTENT: one part of a turn reading a fresh document while another reads a
stale one would make a count and the list under it disagree. So a turn takes ONE
reference at its start and everything in that turn reads the same object.

WHY IT BACKS OFF WHEN NOBODY IS LISTENING (c-201). The 2.0 s cadence below ran 24 hours
a day whether or not a voice session had been open in the last week, and it now spawns
processes rather than opening a socket, which makes the idle cost worse rather than
better. `live_fn` (wired to Gateway.is_live in server.py) lets the loop fall back to
IDLE_REFRESH_SECONDS the rest of the time, and `kick()` (called from Gateway.add_client,
the same place presence is already logged) forces one fetch the moment the app opens, so
the document is warm again well before a person can finish speaking a first utterance.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time

from . import config
from .index import deckdigest

# Fast enough that narration notices a new dispatch or a new card within a couple of
# seconds, slow enough that the view is not being asked for the trimmed document six
# times a minute for an unchanged answer, while somebody is actually there to hear it.
# The dashboard itself polls at ten seconds.
REFRESH_SECONDS = 2.0

# HOW OFTEN THE LOOP POLLS WHEN `live_fn` SAYS NOBODY IS THERE (c-201). Most of a day has
# no voice session open at all, and the 2.0 s cadence above was never conditioned on
# that: it ran, full cost, 24 hours a day. 30 s keeps `/voice/health` honestly reporting
# a real age instead of going fully cold, and `kick()` closes the gap between "idle" and
# "a turn is starting" to about one fetch rather than up to 30 s of staleness.
IDLE_REFRESH_SECONDS = float(30.0)

FETCH_TIMEOUT = 4.0


class Snapshot:
    """One reader, many turns. Thread safe by never mutating what it hands out."""

    def __init__(self, refresh: float = REFRESH_SECONDS,
                idle_refresh: float = IDLE_REFRESH_SECONDS, live_fn=None):
        # NO `url` ANY MORE, and it is not a defaulted-to-None leftover either. This used
        # to be `self.url = url or config.STATE_URL`, read at construction; `config` no
        # longer defines STATE_URL, so keeping the parameter would have crashed the
        # gateway at startup on `server.py`'s bare `Snapshot(live_fn=self.is_live)`.
        # Where the board is now lives in `board_doc()`, which is a function and not a
        # piece of per-instance state.
        self.refresh = refresh
        self.idle_refresh = idle_refresh
        # DEFAULTS TO "ALWAYS LIVE", so a bare Snapshot() -- every existing caller and
        # test that does not pass live_fn -- keeps polling at `refresh` exactly as before.
        # Only Gateway wires the real presence signal (is_live) in.
        self._live_fn = live_fn
        self._doc: dict = {}
        self._at = 0.0
        self._error = ""
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    # -- reading ---------------------------------------------------------- #

    @property
    def doc(self) -> dict:
        """The current document. Never None: an empty dict is what every verb sees
        before the first fetch lands, and every verb renders honestly against one
        ("Nothing is running", "The queue is empty") rather than raising."""
        with self._lock:
            return self._doc

    @property
    def age(self) -> float:
        with self._lock:
            return time.time() - self._at if self._at else float("inf")

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    @property
    def healthy(self) -> bool:
        """Fresh enough to answer from. A stale snapshot is not an error to hide: it is
        reported on /voice/health and it is why a turn falls to Harbor.

        BUDGETED AGAINST WHICHEVER INTERVAL IS ACTUALLY IN EFFECT (c-201 review round
        1), not against `refresh` alone. A document `idle_refresh` seconds old while
        nobody has been present is not stale, it is exactly on schedule; budgeting it
        against the fast interval made it read unhealthy for roughly two thirds of
        every idle cycle, which made the Voice dashboard card and `keel-voice-gateway
        status` show a false "every turn goes to Harbor" warning most of the day and
        made the one surface that reports staleness unable to tell ordinary idle apart
        from a genuinely dead refresh thread -- the actual failure this property exists
        to name. Safe: any real turn only happens while a client is connected, which is
        exactly when `live_fn` (Gateway.is_live) is true and the budget is back to the
        tight one.
        """
        budget = self.refresh if self._is_live() else self.idle_refresh
        return self.age < budget * 5 and not self.error

    # -- keeping it warm --------------------------------------------------- #

    def fetch(self) -> bool:
        try:
            doc = board_doc()
        except Exception as exc:                                        # noqa: BLE001
            with self._lock:
                self._error = f"{exc.__class__.__name__}: {exc}"
            return False
        with self._lock:
            # REPLACED, never merged. A merge would leave a section that has genuinely
            # emptied showing its last non-empty value, which is a stale fact spoken as a
            # current one, and that is the whole class of failure this package is about.
            self._doc = doc
            self._at = time.time()
            self._error = ""
        return True

    def kick(self) -> None:
        """Wake the loop now instead of waiting out the current interval.

        Called from Gateway.add_client when the app opens, so the document is fetched
        fresh right away rather than staying up to `idle_refresh` seconds stale until a
        turn actually needs it. Cheap and rare: it fires on presence returning, not on
        every message.
        """
        self._wake.set()

    def _is_live(self) -> bool:
        """`live_fn()`, guarded (review round 1, c-201). A presence check that raises
        must not be allowed to kill the poll thread: that would freeze `doc` at
        whatever it last fetched, forever, silently, which is the exact failure class
        this package is built to refuse. Defaults to "live" on error, the same
        direction a missing live_fn already takes, so the worst a broken predicate
        costs is polling at the fast cadence rather than backing off."""
        if self._live_fn is None:
            return True
        try:
            return bool(self._live_fn())
        except Exception:                                                # noqa: BLE001
            return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.fetch()
            if self._stop.is_set():
                break
            interval = self.refresh if self._is_live() else self.idle_refresh
            self._wake.wait(interval)
            self._wake.clear()

    def start(self) -> "Snapshot":
        self.fetch()                       # once, synchronously, so the first turn works
        self._thread = threading.Thread(target=self._loop, name="voice-snapshot",
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=2.0)


# --------------------------------------------------------------------------- #
# Where the board comes from.
# --------------------------------------------------------------------------- #

def _kb(*argv: str) -> list:
    """One `kb` reading, as JSON. Raises with kb's own words when it refuses.

    KEEL_HOME IS PASSED EXPLICITLY rather than left to the environment. The gateway runs
    under launchd with almost nothing in its environment, and a `kb` that silently reads
    a different board than the one the talker writes to is the exact failure this package
    is built to refuse: a confident answer about the wrong record.
    """
    if config.RUN_NONCE and "create" in argv:
        argv = (*argv, "--option", f"run_nonce={config.RUN_NONCE}")
    done = subprocess.run([str(config.KB), *argv, "--json"],
                          capture_output=True, text=True, timeout=FETCH_TIMEOUT,
                          env={**os.environ, "KEEL_HOME": str(config.KEEL_HOME)})
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or f"kb {argv[0]} failed")
    return json.loads(done.stdout)


def _agents() -> list:
    """Which sessions the harness says are alive, or nothing.

    BEST EFFORT, UNLIKE `_kb`. The board is the fact; liveness is a decoration on it, and
    a harness that cannot answer must not be able to empty the whole document. A card
    whose session cannot be confirmed reads as `exited`, which is the honest direction.
    """
    try:
        done = subprocess.run(["claude", "agents", "--json"], capture_output=True,
                              text=True, timeout=FETCH_TIMEOUT)
    except Exception:                                                   # noqa: BLE001
        return []
    if done.returncode != 0:
        return []
    try:
        return json.loads(done.stdout)
    except ValueError:
        return []


def _talker_up() -> bool:
    """Is Harbor himself running? The pid file plus a signal 0, which is what
    `keel talker status` uses: a remote-control session is not a kind the harness lists,
    so `claude agents --json` cannot answer this one."""
    try:
        pid = int(config.TALKER_PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _queue_row(card: dict) -> dict:
    """One "waiting on you" card, in the shape the shared queue fold reads.

    `kind` IS NOT WHAT DECIDES IT, and that is the trap this function exists for. Voice
    counts approvals and notices through `verbs.pending_queue`, which calls the SAME fold
    the deck and the queue CLI call (`harbor_queue_fold.qsection`), and that fold decides
    from what a row CARRIES rather than from its `kind` label: a row labelled `approval`
    with no choices, no `on_approve`, no command and no `by_hand` reads as `fyi` and is
    counted as a notice. A gate spoken as a notice is the exact sentence the queue verb
    was repaired for ("Nothing needs a decision" while two entries needed one), so the
    row says out loud what the gate actually is: something only his own hands can answer.

    `kb approve` REFUSES WITHOUT THE DECK'S HUMAN TOKEN, which is why `by_hand` is the
    honest field here rather than `on_approve`: there is no command voice could stage
    that would answer this, and saying otherwise would be a promise the mechanism breaks.
    """
    gate = bool(card["derived"].get("plan_gate") or card["derived"].get("outcome_gate"))
    row = {"id": card["id"], "status": "pending",
           "kind": "approval" if gate else "notice",
           "what": (f"{card['title']}: {card['blocked_reason']}"
                    if card.get("blocked_reason") else card["title"]),
           # SO AN OLD NOTICE CAN FOLD. The fold refuses to hide anything it cannot date,
           # so a row with no stamp is read out as fresh news forever.
           "at": card.get("updated_at") or ""}
    if gate:
        row["by_hand"] = ("approve it on the deck"
                          if card["derived"].get("outcome_gate") else
                          "answer the plan gate on the deck")
    return row


def needs_you_rows() -> list:
    """What is waiting on him, right now, in the shape `verbs.pending_queue` reads.

    THE ONE READ THAT IS NOT WARM. `board_doc` below is polled on a cadence and carries
    everything else; this is called by the one code-rendered answer
    (`verbs.waiting_answer`), which is about what is waiting AT THE MOMENT HE ASKS, so it
    pays one subprocess rather than speaking a document that may be thirty seconds old.
    """
    return [_queue_row(card) for card in _kb("needs-you")]


def board_doc(port: int | None = None) -> dict:
    """The document the gateway reads. THE DECK FIRST, the board alone as the fallback.

    WHY THE DECK (2026-09-18, decision V16). He asked voice about the deck's PR Review
    screen and was told the data was on the work side and out of reach. It was not: the
    deck's own state document on this machine was serving `providers.work.reviews` while
    this function hard-coded `"reviews": []`. Nothing technical was in the way; the
    document was simply narrower than the screen he was looking at. It is the deck's now,
    so anything the deck shows, either space, can be answered from the digest.

    THIS REVERSES "THE GATEWAY NEVER TALKS TO THE DECK", which was the shape after the
    cutover repointed voice at `kb`. The reason it is safe to reverse: the deck is the
    tailnet root, it is always up (launchd, KeepAlive), the gateway already sits BEHIND
    it as the `/voice/` tier, and the read is loopback and unauthenticated by the same
    trust boundary `kb` already has. The old reason was that voice should not depend on a
    view server it did not own; it owns neither, and it now depends on the one that is up
    whenever the phone can reach voice at all, with a fallback for when it is not.

    THE FALLBACK IS NOT SILENT. A deck that does not answer, or answers something this
    cannot fold, drops to `board_only_doc` and the document says `"source": "board"`, so
    the framing tells the model which record it has rather than letting it answer about
    a review screen it cannot see.
    """
    try:
        state = deckdigest.fetch_state(port if port is not None else config.SERVE_PORT)
        return deckdigest.fold(state, harbor_running=_talker_up())
    except Exception:                                                   # noqa: BLE001
        return board_only_doc()


def board_only_doc() -> dict:
    """The board through `kb` alone: what there is when the deck does not answer.

    The same keys `fold` produces, so nothing downstream has to know which path it came
    from; the sections the deck alone can fill (the provider routes, the segments, the
    drain pill) are empty, and the digest renders an empty section honestly. `running`
    rows carry id, name, state, at and space; `queue` rows carry what, kind, status and
    id; `counts` carries running, notices and cards.
    """
    cards = _kb("list")
    needs = _kb("needs-you")
    live = {row.get("sessionId") for row in _agents()}
    running = [{"id": c["id"], "name": c["title"], "space": c["space"],
                "state": c["stage"] if c.get("session_id") in live else "exited",
                "at": c["updated_at"]}
               for c in cards
               if c["stage"] in ("planning", "building") and c.get("session_id")]
    queue = [_queue_row(c) for c in needs]
    return {
        "source": "board",
        "at": "",
        "counts": {"running": len(running), "notices": len(queue), "cards": len(cards)},
        "harbor": {"running": _talker_up()},
        "running": running,
        "queue": queue,
        "cards": [deckdigest.card_row(card) for card in deckdigest.order_cards(cards)],
        # THE TOPICS A SPACE ACTUALLY USES, derived the same way the deck's Cards route
        # derives them (keel/deckstate.py's `space_topics`): the distinct topics of that
        # space's unarchived cards, and `kb list` is already only those. The refine picks
        # from this list rather than inventing a topic, which is how the deck's grouping
        # stays a grouping instead of a long tail of one-card topics.
        "topics": _topics(cards),
        "spaceCounts": {},
        "providers": {}, "segments": [], "drain": {},
    }


def _topics(cards: list) -> dict:
    out: dict = {}
    for card in cards:
        topic = str(card.get("topic") or "").strip()
        if topic:
            out.setdefault(card.get("space") or "personal", set()).add(topic)
    return {space: sorted(topics) for space, topics in out.items()}
