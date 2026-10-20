"""The deck's event stream: what changed, said once, to whoever is looking.

`GET /api/events` is a server-sent event channel (`keel/serve.py` serves it, the page
opens one in `app/ui.core.js`). The page used to ask every five seconds whether anything
had happened; now it is told, and the five second poll is only what runs while the stream
is shut.

Five lines, one event each:

    state <rev>          the state document moved (`deckstate.Deck.rev`, the ONE
                         function that names a revision: what a line here carries is
                         exactly what `/api/state` answers as its ETag)
    card <c-id> <rev>    that card gained an event or was written to
    board <b-id> <line>  that board's `ops.log` reached that many lines
    tick <step>          fifteen seconds passed and NOTHING else did: re-render the ages
                         you are holding, fetch nothing. It is `Deck.rev`'s coarse clock,
                         said on its own rather than inside a `state` line, because the
                         page answers `state` with a whole `/api/state` fetch and an idle
                         deck was refetching the document four times a minute to move some
                         ages. Published by the subscriber's own sweep only, at most once
                         per step, and never beside a `state` that already carries it
    live <c-id> <json>   what that card's house is doing now (the live strip, c-599,
                         `keel/livestrip.py`), or `null` once it is gone: the facts
                         themselves, so the page patches the card and fetches nothing.
                         Published by `livestrip.Strip` only while somebody watches
    ping                 nothing happened; the channel is still here

TWO THINGS FEED IT, and each covers what the other cannot.

1. The writers publish. Every place that drops the state cache, appends a card event or
   folds a push calls `HUB.state()`, `HUB.card()` or `HUB.board()`, so a write made in
   THIS process reaches the page as it lands.
2. The subscriber's own thread sweeps. A `kb` at the desk, a `keel board push` from a
   house's shell and the drain all write from ANOTHER process and can publish nothing, so
   the thread holding a stream open also watches the two numbers that would move: the
   deck's revision (a stat on the board file, inside `Deck.rev`) and the size of the one
   board that page has open. That is a stat every quarter second per subscriber, which is
   what buys a push from a shell landing on his phone in well under a second.

The subscriber's thread also watches the client itself, on a quiet queue and every
`HANGUP_EVERY` lines, because a board being written to hard keeps that queue full and a
check that waited for a quiet moment would never run.

THE HUB HOLDS NO LOCK A WRITER NEEDS. Its own lock covers the subscriber list and nothing
else, and a publish never blocks: a subscriber whose queue is full is a subscriber that
has stopped reading, and it is dropped rather than allowed to wedge the writer that found
it. The cap is deliberately small, because this is one human's deck: eight streams is
already several tabs and a phone, and the oldest goes when a ninth arrives.
"""

import queue
import threading

MAX_SUBSCRIBERS = 8
QUEUE_DEPTH = 64          # a subscriber this far behind has stopped reading
PING_SECONDS = 15.0       # a quiet channel says so, so nothing in between times it out
SWEEP_SECONDS = 0.25      # how often a subscriber's own thread looks for another process
HANGUP_EVERY = 16         # lines between hangup checks while the queue never goes quiet


class Stream:
    """One subscriber. `get` blocks for at most `timeout`; None means nothing arrived."""

    def __init__(self) -> None:
        self.queue: queue.Queue = queue.Queue(maxsize=QUEUE_DEPTH)
        self.closed = False

    def put(self, line: str) -> bool:
        """False when this subscriber is too far behind to keep."""
        try:
            self.queue.put_nowait(line)
            return True
        except queue.Full:
            return False

    def get(self, timeout: float) -> str | None:
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None


class Hub:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.streams: list[Stream] = []

    # ----- subscribing -----

    def open(self) -> Stream:
        """A new subscriber, at the cost of the oldest one when the cap is reached."""
        stream = Stream()
        with self.lock:
            while len(self.streams) >= MAX_SUBSCRIBERS:
                self.streams.pop(0).closed = True
            self.streams.append(stream)
        return stream

    def close(self, stream: Stream) -> None:
        stream.closed = True
        with self.lock:
            if stream in self.streams:
                self.streams.remove(stream)

    def count(self) -> int:
        with self.lock:
            return len(self.streams)

    def drop_all(self) -> None:
        """Every subscriber told to go. The tidy exit, and what a test resets with."""
        with self.lock:
            for stream in self.streams:
                stream.closed = True
            self.streams = []

    # ----- publishing -----

    def send(self, line: str) -> None:
        """Hand one line to every subscriber. Never blocks, never raises."""
        with self.lock:
            streams = list(self.streams)
        for stream in streams:
            if not stream.put(line):
                self.close(stream)

    def state(self, rev: str) -> None:
        self.send(f"state {rev}")

    def card(self, card_id: str, rev: str) -> None:
        self.send(f"card {card_id} {rev}")

    def board(self, board_id: str, cursor: int) -> None:
        self.send(f"board {board_id} {cursor}")


HUB = Hub()
