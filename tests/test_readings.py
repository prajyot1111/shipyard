"""The deck's kept readings (keel/readings.py, c-638): read once, answered at once after,
refreshed off the request path, and the deck told only when a reading moved."""

import threading
import time
import unittest

from keel import readings


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class KeptTest(unittest.TestCase):
    def setUp(self):
        self.clock, self.moves = Clock(), []
        self.kept = readings.Kept(10.0, lambda: self.moves.append(1), self.clock)

    def settle(self):
        deadline = time.monotonic() + 5
        while (self.kept.reading or self.kept.threads) and time.monotonic() < deadline:
            time.sleep(0.005)

    def test_the_first_ask_reads_and_later_asks_answer_without_reading(self):
        calls = []
        read = lambda: calls.append(1) or len(calls)        # noqa: E731
        self.assertEqual(self.kept.get("k", read), 1)
        self.clock.now = 9.0
        self.assertEqual(self.kept.get("k", read), 1)
        self.assertEqual(len(calls), 1, "fresh: nothing read again")

    def test_an_old_reading_is_answered_and_read_again_on_its_own_thread(self):
        value, gate = ["a"], threading.Event()

        def read():
            gate.wait(5)
            return value[0]
        calls = []
        counted = lambda: calls.append(1) or read()        # noqa: E731
        gate.set()
        self.kept.get("k", counted)
        gate.clear()
        value[0], self.clock.now = "b", 11.0
        self.assertEqual(self.kept.get("k", counted), "a", "answered at once, the old reading")
        self.assertEqual(self.kept.get("k", counted), "a")
        self.assertIsNone(self.kept.refresh("k", counted), "one refresh at a time per key")
        deadline = time.monotonic() + 5
        while len(calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertEqual((len(calls), self.kept.reading), (2, {"k"}), "one read in flight")
        gate.set()
        self.settle()
        self.assertEqual(self.kept.peek("k"), "b")
        self.assertEqual(self.moves, [1], "the deck is told it moved")

    def test_a_refresh_that_reads_the_same_tells_nobody(self):
        self.kept.get("k", lambda: {"x": 1})
        self.kept.get("k", lambda: {"x": 1}, stale=True)
        self.settle()
        self.assertEqual(self.moves, [])

    def test_a_refresh_that_fails_keeps_the_last_reading(self):
        self.kept.get("k", lambda: "good")

        def broken():
            raise OSError("adapter gone")
        self.kept.get("k", broken, stale=True)
        self.settle()
        self.assertEqual((self.kept.peek("k"), self.moves), ("good", []))
        self.assertEqual(self.kept.reading, set())

    def test_ahead_reads_on_a_thread_and_never_overwrites_a_newer_reading(self):
        gate = threading.Event()
        join = self.kept.ahead("k", lambda: gate.wait(5) and "old")
        self.clock.now = 1.0
        self.kept.get("k", lambda: "new")            # a reading that started later lands first
        gate.set()
        self.assertEqual(join(), "old", "the join answers its own reading")
        self.assertEqual(self.kept.peek("k"), "new", "but the newer one is kept")
        self.assertEqual(self.moves, [], "and nobody is told by an ahead read")

    def test_ahead_raises_what_its_read_raised_and_keeps_nothing(self):
        def broken():
            raise OSError("no claude")
        with self.assertRaises(OSError):
            self.kept.ahead("k", broken)()
        self.assertIsNone(self.kept.peek("k"))

    def test_a_first_read_that_fails_is_raised_and_not_kept(self):
        def broken():
            raise OSError("no claude")
        with self.assertRaises(OSError):
            self.kept.get("k", broken)
        self.assertIsNone(self.kept.peek("k"))


class CloseWhileStartingTest(unittest.TestCase):
    """A close that lands between a refresh's add and its start (seen on c-644's land, under
    load: "cannot join thread before it is started" in a deck's teardown, which then leaked
    its Board) waits for the start instead, and joins a started thread."""

    def test_a_close_racing_a_refresh_never_joins_an_unstarted_thread(self):
        kept = readings.Kept(10.0, None, Clock())
        errors, real_start = [], threading.Thread.start

        def closer():
            try:
                kept.close(seconds=2)
            except RuntimeError as error:
                errors.append(error)

        def slow_start(thread):
            # the close runs in the window the old code left open, before the start
            other = threading.Thread(target=closer)
            real_start(other)
            time.sleep(0.05)
            real_start(thread)
            slow_start.closers.append(other)
        slow_start.closers = []
        from unittest import mock
        with mock.patch.object(threading.Thread, "start", slow_start):
            kept.refresh("k", lambda: 1)
        for other in slow_start.closers:
            other.join(5)
        self.assertEqual(errors, [])


class SpaceLinksTest(unittest.TestCase):
    """`act links` from the deck's kept reading (deckstate.space_links): read once, answered
    at once, and read again when a card is asked that the reading does not cover."""

    def test_links_are_read_once_and_a_new_card_is_read_again_off_the_request(self):
        from unittest import mock
        from types import SimpleNamespace
        from keel import deckstate
        asked, moved = [], []
        kept = readings.Kept(30.0, lambda: moved.append(1))
        space = SimpleNamespace(name="work")

        def act_links(space, ids, strict=False):
            asked.append(list(ids))
            return {card_id: {"pr": f"pr-{card_id}"} for card_id in ids}
        with mock.patch.object(deckstate, "adapter_links", side_effect=act_links):
            self.assertEqual(deckstate.space_links(space, ["c-1"], kept), {"c-1": {"pr": "pr-c-1"}})
            self.assertEqual(deckstate.space_links(space, ["c-1"], kept), {"c-1": {"pr": "pr-c-1"}})
            self.assertEqual(asked, [["c-1"]], "the second build reads nothing")
            self.assertEqual(deckstate.space_links(space, ["c-1", "c-2"], kept), {"c-1": {"pr": "pr-c-1"}},
                             "a card that just went live is answered without, at once")
            deadline = time.monotonic() + 5
            while kept.reading or not moved:
                if time.monotonic() > deadline:
                    self.fail("the refresh never landed")
                time.sleep(0.005)
            self.assertEqual(asked[-1], ["c-1", "c-2"])
            self.assertEqual(deckstate.space_links(space, ["c-1", "c-2"], kept)["c-2"], {"pr": "pr-c-2"})


if __name__ == "__main__":
    unittest.main()
