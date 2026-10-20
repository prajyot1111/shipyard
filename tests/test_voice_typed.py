"""A typed turn is answered in text, and a turn that drew a board says which (VP-3, VP-5).

His decision of 2026-09-24: the voice page is a CHAT you can also talk to. A turn he TYPED
is answered in text only; a turn he SPOKE is spoken and shown. That holds inside a
Conversation too. It is one flag on the turn, set where the typed line enters the gateway
(`Gateway.on_typed`), and read at the one place a turn becomes sound (`Dispatcher._say`),
so there is no second path for a typed turn to drift along.

And the receipt for a board a turn drew is the real board, which the page can only draw if
the turn names it: `drawing.read_answer` notes the boards it pushed for the turn, the answer
record carries them through the say inbox, and the turn reports them as `boards`.

Every outside thing is a recorder, in the idiom of `tests/test_voice_stages.py`.
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "voice") not in sys.path:
    sys.path.insert(0, str(ROOT / "voice"))

from harbor_voice import dispatcher, drawing, filler, harbormsg, server   # noqa: E402


class Snap:
    doc = {"running": [], "queue": [], "reviews": []}
    age = 0.0
    healthy = True
    error = ""


class Bus:
    """Records every state the bus is told, so a typed turn can be seen to come to rest."""

    def __init__(self):
        self.states = []

    def set_state(self, state):
        self.states.append(state)

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class TypedCase(unittest.TestCase):
    def setUp(self):
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        self.tmp = Path(handle.name)
        self.spoken: list[str] = []
        self.bus = Bus()
        for module, name in ((drawing, "TRANSCRIPT"), (harbormsg, "TRANSCRIPT")):
            patch = mock.patch.object(module, name, self.tmp / "transcript.jsonl")
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(drawing, "REPORT_FILE", self.tmp / "report.txt")
        patch.start()
        self.addCleanup(patch.stop)

    def speak(self, text, generation, spk=None):
        self.spoken.append(text)
        return {"engines": ["fake"]}

    def deliver_answer(self, answer: str, boards=None):
        """Harbor, answering at once into the say inbox the way the worker does."""
        say = harbormsg.SayInbox(self.tmp / "say")

        def deliver(said, context="", turn_id="", **extra):
            say.write(answer, turn=turn_id, boards=boards)
            return True, "turn started"
        return deliver

    def make(self, deliver=None, **extra) -> dispatcher.Dispatcher:
        return dispatcher.Dispatcher(
            Snap(), self.bus, self.speak, harbormsg.SayInbox(self.tmp / "say"),
            self.tmp / "transcript.jsonl",
            deliver=deliver or self.deliver_answer("Two things need you."),
            filler_model=filler.NoFiller(),
            progress_inbox=harbormsg.SayInbox(self.tmp / "progress"),
            open_inbox=harbormsg.SayInbox(self.tmp / "opening"),
            queue_answer=lambda *a: True, **extra)

    def wait_done(self, d, seconds=5.0):
        deadline = time.time() + seconds
        while time.time() < deadline:
            turn = d.turn
            if turn is not None and turn.phase in ("done", "failed"):
                return turn
            time.sleep(0.02)
        self.fail("the turn never finished")


class ATypedTurnIsText(TypedCase):
    def test_a_typed_question_is_answered_and_not_spoken(self):
        d = self.make()
        d.answer("why did the box restart", typed=True)
        turn = self.wait_done(d)
        self.assertEqual(turn.answer, "Two things need you.")
        self.assertEqual(self.spoken, [], "a typed turn reached the speaker")
        self.assertFalse(turn.spoken)
        self.assertTrue(turn.as_json()["typed"])

    def test_the_same_question_spoken_is_still_spoken(self):
        """The control: the flag is the only difference."""
        d = self.make()
        d.answer("why did the box restart")
        turn = self.wait_done(d)
        self.assertIn("Two things need you.", self.spoken)
        self.assertFalse(turn.as_json()["typed"])

    def test_a_typed_turn_comes_to_rest_without_a_speaker_to_end_it(self):
        """The bus goes back to idle in the speaker's `finally`; a typed turn has no
        speaker call, so its end has to say so itself or the page reads thinking for ever."""
        d = self.make()
        d.answer("why did the box restart", typed=True)
        self.wait_done(d)
        self.assertEqual(self.bus.states[-1], "idle", self.bus.states)

    def test_a_typed_capture_plays_no_ack(self):
        d = self.make(file_capture=lambda said, space, heard: {"id": "c-9", "space": "personal"})
        turn = d.capture("rotate the backup key next week", typed=True)
        self.assertEqual(turn.card, "c-9")
        self.assertEqual(self.spoken, [])

    def test_a_streamed_part_of_a_typed_turn_is_refused(self):
        """R2 speaks Harbor's parts as they stream; a typed turn has none to speak."""
        d = self.make()
        turn = d.begin("draw it")
        turn.typed = True
        self.assertFalse(d._house_part(turn, "The drain picks it up."))
        self.assertEqual(self.spoken, [])

    def test_a_typed_turn_that_gave_up_still_shows_its_answer(self):
        """The give-up promise is about AUDIO ("I'll answer in text instead"). A typed turn
        was always text, so its answer is not hidden from the page it was typed on."""
        d = self.make()
        turn = d.begin("summarise every review")
        turn.typed = True
        turn.gave_up = True
        d._finish_silent(turn, "Four reviews are open.", dispatcher.HARBOR, "Harbor, 70s",
                         "gave up", queue=True, redact=not turn.typed)
        self.assertEqual(turn.answer, "Four reviews are open.")


class TheGatewayMarksTheTypedLine(unittest.TestCase):
    """`{"type": "text"}` from the page becomes a typed turn, and says so on the transcript."""

    def gateway(self):
        gw = server.Gateway.__new__(server.Gateway)
        gw.sent = []
        gw.broadcast = gw.sent.append
        calls = []

        class Fake:
            generation = 4

            def pinned(self):
                return ""

            def answer(self, **kwargs):
                calls.append(("answer", kwargs))

            def capture(self, **kwargs):
                calls.append(("capture", kwargs))
        gw.dispatcher = Fake()
        gw.take_partial = lambda: None
        gw.outcome = lambda *a: None
        gw.calls = calls
        return gw

    def settle(self, gw):
        deadline = time.time() + 2
        while not gw.calls and time.time() < deadline:
            time.sleep(0.01)

    def test_a_typed_line_is_a_typed_turn(self):
        gw = self.gateway()
        gw.on_typed({"type": "text", "text": "what is waiting on me", "mode": "talk"})
        self.settle(gw)
        kind, kwargs = gw.calls[0]
        self.assertEqual(kind, "answer")
        self.assertTrue(kwargs["typed"])
        self.assertTrue(gw.sent[0]["typed"], "the transcript line does not say it was typed")

    def test_a_typed_capture_is_typed_too(self):
        gw = self.gateway()
        gw.on_typed({"type": "text", "text": "an idea", "mode": "capture", "space": "work"})
        self.settle(gw)
        kind, kwargs = gw.calls[0]
        self.assertEqual(kind, "capture")
        self.assertTrue(kwargs["typed"])

    def test_the_repeat_key_asks_to_be_heard(self):
        """`r` on the desk is "say that again": typed by a key, and meant to be heard."""
        gw = self.gateway()
        gw.on_typed({"type": "text", "text": "say that again", "aloud": True})
        self.settle(gw)
        self.assertFalse(gw.calls[0][1]["typed"])
        self.assertFalse(gw.sent[0]["typed"])


class ATurnNamesTheBoardItDrew(TypedCase):
    RAW = 'Here is the flow.\n```board\nnode a box "Approve"\n```\nThe rest.\n'

    def test_read_answer_notes_the_board_for_the_turn(self):
        drawing.read_answer(self.RAW, push=lambda body: {"board": "b-014", "accepted": 1},
                            turn="t-1")
        self.assertEqual(drawing.drawn_for("t-1"), ["b-014"])
        self.assertEqual(drawing.drawn_for("t-1"), [], "the note is taken once")

    def test_a_refused_block_names_no_board(self):
        def refuse(body):
            raise RuntimeError("the board is closed")
        drawing.read_answer(self.RAW, push=refuse, turn="t-2")
        self.assertEqual(drawing.drawn_for("t-2"), [])

    def test_the_note_is_bounded(self):
        for i in range(drawing.DRAWN_KEEP + 5):
            drawing.note_drawn(f"t-{i}", ["b-1"])
        self.assertLessEqual(len(drawing.DRAWN), drawing.DRAWN_KEEP)

    def test_the_say_inbox_carries_the_boards(self):
        inbox = harbormsg.SayInbox(self.tmp / "say")
        inbox.write("I put it on the board.", turn="t-3", boards=["b-014"])
        self.assertEqual(inbox.claim("t-3")[0]["boards"], ["b-014"])


    def test_the_turn_reports_the_boards_its_answer_carried(self):
        d = self.make(deliver=self.deliver_answer("I put the flow on a board.", ["b-014"]))
        d.answer("walk me through the merge queue")
        turn = self.wait_done(d)
        self.assertEqual(turn.as_json()["boards"], ["b-014"])


if __name__ == "__main__":
    unittest.main()
