"""Readings the deck keeps between builds and refreshes off the request path (c-638).

A state build used to run every slow reading it shows, each time: the work pack's `act
links` (half a second of a Python start and its own lookups), the adapters' verbs and
provider routes, git for where Bosun's done cards landed, and `claude agents` per config
dir. On a 636-card board those were most of what was left of a 3.4 s `/api/state` once the
disk walk was gone (2026-10-04, his word: everything is local, it should be milliseconds).

So the deck (`deckstate.Deck`) holds one `Kept` per reading. The first ask in a process
reads it, since there is nothing to show yet. After that every ask answers at once with the
newest reading, and one older than its `fresh` seconds, or one the caller knows is short
(`stale`), is read again on a thread of its own, one at a time per key. When a refresh
reads something different, `on_change` runs (`Deck.moved`): the documents are dropped and
the pages told, so a new link or a house that started is drawn a refresh later, not a poll.
`ahead` reads on a thread and hands back its join, for a cold build that reads the board
meanwhile, and for the live strip, which wants the listing as it is now.

Each `read` RAISES when it fails (`strict`): a refresh that fails keeps the last good
reading, and a first read that fails is the caller's to answer as it always did. A soft
failure stored as a reading would have shown no links, or no house, for a whole window.
These are readings of things outside the board (an adapter, git, the harness), never a copy
of the board, which stays the one store.
"""

from __future__ import annotations

import threading
import time
from typing import Callable


class Kept:
    """Readings by key, each answered at once once read, refreshed after `fresh` seconds."""

    def __init__(self, fresh: float, on_change: Callable[[], None] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.fresh = fresh
        self.on_change = on_change
        self.clock = clock
        self.lock = threading.Lock()
        self.held: dict = {}            # key -> (when the read STARTED, value)
        self.reading: set = set()       # keys a refresh is running for
        self.threads: set = set()       # the refreshes in flight, for `close`
        self.closed = False

    def peek(self, key):
        """The value held for `key`, or None; never reads."""
        with self.lock:
            entry = self.held.get(key)
        return None if entry is None else entry[1]

    def age(self, key) -> float | None:
        """Seconds since `key`'s held reading started, or None when nothing is held."""
        with self.lock:
            entry = self.held.get(key)
        return None if entry is None else self.clock() - entry[0]

    def get(self, key, read: Callable[[], object], stale: bool = False):
        """The newest reading for `key`. `stale` says the caller knows it is out of date: it
        is still answered, and read again now."""
        with self.lock:
            entry = self.held.get(key)
        if entry is None:
            started = self.clock()
            value = read()
            self.store(key, started, value)
            held = self.peek(key)
            return value if held is None else held      # a closed Kept holds nothing: answer the read
        at, value = entry
        if stale or self.clock() - at > self.fresh:
            self.refresh(key, read)
        return value

    def seed(self, key, value) -> None:
        """Hold `value` as already old: what a caller answered when the first strict read
        failed. The next ask answers it at once and reads again on a thread, rather than
        every build failing and falling back in line (c-638 review)."""
        with self.lock:
            self.held.setdefault(key, (float("-inf"), value))

    def store(self, key, started: float, value) -> tuple | None:
        """Hold `value` unless a reading that started later is held; the entry replaced."""
        with self.lock:
            old = self.held.get(key)
            if self.closed or (old is not None and old[0] > started):
                return old
            self.held[key] = (started, value)
            return old

    def ahead(self, key, read: Callable[[], object]) -> Callable[[], object]:
        """Read `key` on a thread now and hand back its join, which answers the reading (or
        raises what the read raised; nothing is kept then). Its reading is kept unless a
        newer one landed meanwhile, and it never calls `on_change`: its caller is a cold
        build, which wants the reading and holds the deck's lock."""
        out: dict = {}
        started = self.clock()

        def run():
            try:
                out["value"] = read()
            except BaseException as error:  # noqa: BLE001 - handed to the join, raised there
                out["error"] = error

        worker = threading.Thread(target=run, name="kept-ahead", daemon=True)
        worker.start()

        def join():
            worker.join()
            if "error" in out:
                raise out["error"]
            self.store(key, started, out["value"])
            return out["value"]
        return join

    def refresh(self, key, read: Callable[[], object]) -> threading.Thread | None:
        """Read `key` again on a thread, unless a read of it is running; the thread."""
        with self.lock:
            if key in self.reading or self.closed:
                return None
            self.reading.add(key)
            worker = threading.Thread(target=self._refresh, args=(key, read), name="kept-reading",
                                      daemon=True)
            self.threads.add(worker)
            # started under the lock, so `close` never sees a thread it cannot join yet (a
            # close between the add and the start raised "cannot join thread before it is
            # started" in a deck's teardown under load, c-644's land)
            worker.start()
        return worker

    def _refresh(self, key, read) -> None:
        started = self.clock()
        try:
            value = read()
        except Exception:  # noqa: BLE001 - a failed refresh keeps the last reading
            value, failed = None, True
        else:
            failed = False
        try:
            old = None if failed else self.store(key, started, value)
            with self.lock:
                self.reading.discard(key)
                closed = self.closed
            if not (failed or closed) and (old is None or old[1] != value) and self.on_change is not None:
                self.on_change()
        finally:
            # left in `threads` until `on_change` has returned, so `close` joins it whole
            with self.lock:
                self.threads.discard(threading.current_thread())

    def close(self, seconds: float = 5.0) -> None:
        """No refresh starts, lands or tells anyone from now; the ones in flight are joined
        (a `claude agents` writing into a config dir its owner is removing, c-599)."""
        with self.lock:
            self.closed = True
            running = list(self.threads)
        deadline = time.monotonic() + seconds
        for worker in running:
            worker.join(max(0.0, deadline - time.monotonic()))


class Readings:
    """The deck's kept readings, one `Kept` each, all telling the deck when they move."""

    def __init__(self, on_change: Callable[[], None] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.links = Kept(30.0, on_change, clock)          # `act links`, per space
        self.verbs = Kept(60.0, on_change, clock)          # `act verbs`, per space
        self.providers = Kept(30.0, on_change, clock)      # `providers/<route>`, per space
        self.on_next = Kept(5.0, on_change, clock)         # git: Bosun's done cards on next
        self.agents = Kept(2.0, on_change, clock)          # `claude agents`, every config dir

    def close(self) -> None:
        for kept in (self.links, self.verbs, self.providers, self.on_next, self.agents):
            kept.close()
