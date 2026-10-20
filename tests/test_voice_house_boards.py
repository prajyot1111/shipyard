"""A connected house's drawing is a turn's receipt too (VP-8, 2026-09-24).

VP-5 made a turn name the boards its answer drew, and only Harbor's could: Harbor's fenced
blocks are pushed by the gateway itself (`drawing.read_answer`), so it knows their ids. A
house draws with `keel board push --card c-NNN` from its own shell, which writes to the
deck's board store directly, and the gateway never heard about it: a connected turn that
drew a board showed no receipt.

So when a connected turn's answer lands, the gateway asks the deck's board list which of the
connected card's boards were touched since the turn began, and the turn carries those ids as
`boards`, the same field Harbor's drawings ride on. These tests run the REAL deck (`keel
serve` on a free port, a scratch board store) and the real dispatcher; only the house is a
stand-in, and it draws with the same `boards.push(..., card=...)` the verb runs.
"""

import http.server
import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "voice") not in sys.path:
    sys.path.insert(0, str(ROOT / "voice"))

from harbor_voice import config as vconfig                            # noqa: E402
from harbor_voice import connected, dispatcher, drawing, filler, harbormsg  # noqa: E402

from keel import boards                                                # noqa: E402
from tests import test_serve as deck_tests                             # noqa: E402

DRAWING = 'board "How the merge queue drains"\nnode q box "the queue"\nnode m box "merge"\n'


class Snap:
    doc = {"running": [], "queue": [], "reviews": []}
    age = 0.0
    healthy = True
    error = ""


class Bus:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class HouseBoardsCase(deck_tests.ServerCase):
    def setUp(self):
        super().setUp()
        self.vtmp = self.dir / "voice"
        self.vtmp.mkdir(parents=True, exist_ok=True)
        self.spoken: list[str] = []
        self.work = self.board.create("personal", "The merge queue", repo="keel",
                                      actor="human")
        self.other = self.board.create("personal", "Another house", repo="keel",
                                       actor="human")
        self.port(self.server.server_address[1])
        for module, name in ((drawing, "TRANSCRIPT"), (harbormsg, "TRANSCRIPT")):
            patch = mock.patch.object(module, name, self.vtmp / "transcript.jsonl")
            patch.start()
            self.addCleanup(patch.stop)

    def port(self, number: int) -> None:
        patch = mock.patch.object(vconfig, "SERVE_PORT", number)
        patch.start()
        self.addCleanup(patch.stop)

    def dispatcher(self) -> dispatcher.Dispatcher:
        def speak(text, generation, spk=None):
            self.spoken.append(text)
            return {"engines": ["fake"], "firstAudioAt": time.time()}

        d = dispatcher.Dispatcher(
            Snap(), Bus(), speak, harbormsg.SayInbox(self.vtmp / "say"),
            self.vtmp / "transcript.jsonl",
            deliver=lambda *a, **k: (False, "a fixture"),
            filler_model=filler.NoFiller(),
            progress_inbox=harbormsg.SayInbox(self.vtmp / "progress"),
            open_inbox=harbormsg.SayInbox(self.vtmp / "opening"),
            queue_answer=lambda *a: True)
        d.pin_to(self.work, time.time() + 600, "The merge queue", "personal")
        return d

    def connected_turn(self, draws=None):
        """One connected turn; `draws()` runs inside the house's turn, as its shell would."""
        def ask(card, said, turn="", progress="", **rest):
            if draws:
                draws()
            return {"ok": True, "say": "I put the queue on a board."}

        d = self.dispatcher()
        with mock.patch.object(connected, "ask", ask):
            started = time.monotonic()
            turn = d.answer("draw me the merge queue")
            deadline = time.time() + 10
            while time.time() < deadline and turn.phase != "done":
                time.sleep(0.02)
        self.assertEqual(turn.phase, "done")
        return turn, time.monotonic() - started

    def draw(self, card: str) -> str:
        return boards.push(self.cfg, DRAWING, card=card)["board"]

    def records(self) -> list[dict]:
        path = self.vtmp / "transcript.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]


class TheHousesDrawingIsTheReceipt(HouseBoardsCase):
    def test_a_board_the_house_drew_during_the_turn_is_reported(self):
        drawn = []
        turn, _ = self.connected_turn(lambda: drawn.append(self.draw(self.work)))
        self.assertEqual(turn.as_json()["boards"], drawn)
        self.assertEqual(turn.tier, dispatcher.HOUSE)

    def test_a_board_of_another_card_is_not_reported(self):
        turn, _ = self.connected_turn(lambda: self.draw(self.other))
        self.assertEqual(turn.as_json()["boards"], [])

    def test_a_board_last_touched_before_the_turn_is_not_reported(self):
        self.draw(self.work)
        time.sleep(0.01)
        turn, _ = self.connected_turn()
        self.assertEqual(turn.as_json()["boards"], [])

    def test_an_older_board_drawn_on_again_during_the_turn_is_reported(self):
        """The house's push continues its live board, so the id is the old one and its
        update time is this turn's."""
        first = self.draw(self.work)
        time.sleep(0.01)
        turn, _ = self.connected_turn(lambda: boards.push(
            self.cfg, 'node r box "rebase"', card=self.work))
        self.assertEqual(turn.as_json()["boards"], [first])

    def test_only_the_connected_card_s_boards_among_several(self):
        drawn = []

        def both():
            self.draw(self.other)
            drawn.append(self.draw(self.work))
        turn, _ = self.connected_turn(both)
        self.assertEqual(turn.as_json()["boards"], drawn)


class SlowDeck(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(5)
        try:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"rows": []}')
        except OSError:
            pass

    def log_message(self, *args):
        pass


class ADeckThatFailsNeverCostsTheTurn(HouseBoardsCase):
    def test_a_deck_that_does_not_answer_ends_the_turn_with_no_receipt_and_one_line(self):
        self.port(1)
        turn, _ = self.connected_turn(lambda: self.draw(self.work))
        self.assertEqual(turn.answer, "I put the queue on a board.")
        self.assertEqual(turn.as_json()["boards"], [])
        failed = [rec for rec in self.records() if rec["kind"] == "house-boards-failed"]
        self.assertEqual(len(failed), 1, self.records())
        self.assertEqual(failed[0]["card"], self.work)

    def test_a_slow_deck_does_not_hold_the_turn_open(self):
        slow = http.server.ThreadingHTTPServer(("127.0.0.1", 0), SlowDeck)
        slow.daemon_threads = True
        threading.Thread(target=slow.serve_forever, daemon=True).start()
        self.addCleanup(slow.server_close)
        self.addCleanup(slow.shutdown)
        self.port(slow.server_address[1])
        turn, took = self.connected_turn(lambda: self.draw(self.work))
        self.assertEqual(turn.as_json()["boards"], [])
        self.assertLess(took, drawing.HOUSE_LIST_TIMEOUT + 2.0,
                        "a slow deck held the turn open")
        failed = [rec for rec in self.records() if rec["kind"] == "house-boards-failed"]
        self.assertEqual(len(failed), 1, self.records())


class TheListIsReadRight(unittest.TestCase):
    """The filter on its own: the card, the time, and a closed board left out."""

    def rows(self):
        return [
            {"id": "b-3", "source": {"kind": "card", "card": "c-7"},
             "updated": "2026-09-24T20:00:05.000000+05:30", "closed": None},
            {"id": "b-2", "source": {"kind": "card", "card": "c-8"},
             "updated": "2026-09-24T20:00:04.000000+05:30", "closed": None},
            {"id": "b-1", "source": {"kind": "card", "card": "c-7"},
             "updated": "2026-09-24T20:00:03.000000+05:30", "closed": None},
            {"id": "b-4", "source": {"kind": "card", "card": "c-7"},
             "updated": "2026-09-24T20:00:06.000000+05:30",
             "closed": "2026-09-24T20:00:06.000000+05:30"},
            {"id": "b-5", "source": {"kind": "talker", "card": None},
             "updated": "2026-09-24T20:00:07.000000+05:30", "closed": None},
            {"id": "b-6", "source": {"kind": "card", "card": "c-7"},
             "updated": "not a stamp", "closed": None},
        ]

    def test_the_card_s_boards_since_the_start_oldest_first(self):
        from datetime import datetime
        since = datetime.fromisoformat("2026-09-24T20:00:02+05:30").timestamp()
        self.assertEqual(drawing.card_boards_since(self.rows(), "c-7", since), ["b-1", "b-3"])
        since = datetime.fromisoformat("2026-09-24T20:00:04+05:30").timestamp()
        self.assertEqual(drawing.card_boards_since(self.rows(), "c-7", since), ["b-3"])

    def test_no_card_names_nothing(self):
        self.assertEqual(drawing.card_boards_since(self.rows(), "", 0.0), [])


if __name__ == "__main__":
    unittest.main()
