"""The pen: one reader of a ```board block, for a house's answer and for Harbor's.

THE THREE LAYERS OF THE DUPLICATE RULE ARE TESTED APART, on purpose. b-003 (c-302) is one
block drawn twice 6 ms apart, and three separate things now stop it: the fence mark never
survives into a body (`keel/sentences.py`), the pen compares NORMALISED op sequences
(here), and the store refuses an identical push from one caller inside ten seconds
(`tests/test_boards.py`, `DuplicateTest`). Each one alone would have been enough, which is
exactly why each needs a test that fails when only that one is removed: a belt-and-braces
guarded only end to end is a belt and braces where nobody notices the belt has gone.

AND THE TALKER USES THE SAME PEN. Harbor's answers reach him through the gateway rather
than through `keel converse`, so its push goes through the verb rather than through the
store in this process; the READING is the same code, which is the whole point of
"the talker needs to call verbs the same as the house does".
"""

import tempfile
import unittest
from unittest import mock
from pathlib import Path

from keel import boardpen, boards, sentences
from keel.board import Board
from tests.helpers import make_config

BLOCK = 'node a box "a card"\nnote a "one"\n'


class FakeDoor:
    """A push door that records what it was asked to draw and answers like the store."""

    def __init__(self, fail: str = "", duplicate: bool = False, accepted=None,
                 skipped: int = 0, reasons=()):
        self.bodies: list[str] = []
        self.fail = fail
        self.duplicate = duplicate
        self.accepted = accepted
        self.skipped = skipped
        self.reasons = list(reasons)

    def __call__(self, body: str) -> dict:
        if self.fail:
            raise boards.BoardError(self.fail)
        self.bodies.append(body)
        answer = {"board": "b-001", "url": "http://x/board/b-001", "duplicate": self.duplicate}
        if self.accepted is not None:
            answer.update(accepted=self.accepted, skipped=self.skipped, reasons=self.reasons)
        return answer


class PenReadingTest(unittest.TestCase):
    """What the pen takes out of an answer, and what it leaves for his ear."""

    def pen(self, **kwargs):
        door = FakeDoor(**kwargs)
        return boardpen.BoardPen(None, boardpen.talker_source(), push=door), door

    def test_a_block_is_drawn_and_the_sentence_stands_in_for_it(self):
        pen, door = self.pen()
        said = pen.take(f"Here it is:\n\n```board\n{BLOCK}```\n\nThat is the shape.")
        self.assertEqual(door.bodies, [BLOCK])
        self.assertNotIn("node a box", said)
        self.assertIn("Here it is:", said)
        self.assertTrue(said.endswith(boardpen.BOARD_DREW), said)

    def test_a_code_block_is_left_exactly_where_it_was(self):
        pen, door = self.pen()
        said = pen.take("Try this:\n\n```python\nmake test\n```\n")
        self.assertEqual(door.bodies, [])
        self.assertIn("make test", said)
        self.assertNotIn(boardpen.BOARD_DREW, said)

    def test_a_refusal_says_so_rather_than_claiming_it_drew(self):
        pen, _ = self.pen(fail="no room")
        said = pen.take(f"```board\n{BLOCK}```\nThere.")
        self.assertIn(boardpen.BOARD_REFUSED, said)
        self.assertNotIn(boardpen.BOARD_DREW, said)
        self.assertEqual(pen.failed, "no room")

    def test_a_store_that_says_duplicate_is_not_news_and_not_a_refusal(self):
        """The other door had it. It IS on the board, so he is not told it failed."""
        pen, _ = self.pen(duplicate=True)
        said = pen.take(f"```board\n{BLOCK}```\nThere.")
        self.assertNotIn(boardpen.BOARD_REFUSED, said)
        self.assertNotIn(boardpen.BOARD_DREW, said)
        self.assertEqual(pen.count, 1)

    def test_the_note_records_where_it_was_drawn_and_never_costs_the_turn(self):
        said = []
        door = FakeDoor()
        pen = boardpen.BoardPen(None, boardpen.card_source("c-301"), push=door,
                                note=said.append)
        pen.take(f"```board\n{BLOCK}```")
        self.assertEqual(len(said), 1)
        self.assertIn("b-001", said[0])

        def angry(_text):
            raise RuntimeError("the card is gone")

        pen = boardpen.BoardPen(None, boardpen.card_source("c-301"), push=FakeDoor(),
                                note=angry)
        self.assertEqual(pen.take(f"```board\n{BLOCK}```").strip(), boardpen.BOARD_DREW)


class PenReportTest(unittest.TestCase):
    """C1 (2026-09-23): the push returns a REPORT, and what he hears is built from it.

    `BoardPen.draw` used to count any push that did not raise as drawn, so a push where 21 of
    27 lines were refused (b-003), or none at all, was still spoken as "I have put that on
    the board." (B19, B22). Every case here is a push the store ANSWERED, which is exactly
    the case the old rule could not tell apart.
    """

    def pen(self, **kwargs):
        door = FakeDoor(**kwargs)
        return boardpen.BoardPen(None, boardpen.talker_source(), push=door), door

    def test_a_push_that_landed_nothing_does_not_say_it_drew(self):
        pen, _ = self.pen(accepted=0, skipped=5,
                          reasons=["no node called 'meaning' on this board"] * 5)
        said = pen.take(f"```board\n{BLOCK}```")
        self.assertNotIn(boardpen.BOARD_DREW, said)
        self.assertIn(boardpen.BOARD_REFUSED, said)
        self.assertIn("meaning", said, "the reason is said, in plain words")
        self.assertEqual(pen.count, 0)

    def test_a_partial_push_says_how_much_did_not_land(self):
        pen, _ = self.pen(accepted=6, skipped=21, reasons=["frames are gone"] * 21)
        said = pen.take(f"```board\n{BLOCK}```")
        self.assertNotIn(boardpen.BOARD_DREW, said)
        self.assertIn("21 of 27", said)
        self.assertEqual(pen.summary()["state"], boardpen.PARTIAL)

    def test_a_clean_push_says_it_is_on_the_board_and_nothing_about_a_walk(self):
        pen, _ = self.pen(accepted=2, skipped=0)
        self.assertEqual(pen.take(f"```board\n{BLOCK}```"), boardpen.BOARD_DREW)
        self.assertNotIn("walk", boardpen.BOARD_DREW.lower())

    def test_the_models_own_claim_is_stripped_from_an_answer_whose_push_failed(self):
        """The 14:21 transcript: Harbor said it had added the lines and nothing landed."""
        pen, _ = self.pen(fail="board-b-002-lines.txt is not a file on this machine")
        said = pen.take("I have added the exact lines to the board. Take a look.\n\n"
                        f"```board\n{BLOCK}```\n")
        self.assertNotIn("added the exact lines", said)
        self.assertIn("Take a look.", said)
        self.assertIn(boardpen.BOARD_REFUSED, said)
        self.assertNotIn("board-b-002-lines.txt", said, "no file path is spoken")

    def test_the_claim_is_kept_when_the_push_landed(self):
        pen, _ = self.pen(accepted=2)
        said = pen.take(f"I drew the two tiers on the board.\n\n```board\n{BLOCK}```\n")
        self.assertIn("I drew the two tiers", said)

    def test_only_the_lead_and_the_report_are_spoken(self):
        """N7: the prose before the block, capped to two sentences, and the report line."""
        pen, _ = self.pen(accepted=2)
        said = pen.take("One. Two. Three.\n\n"
                        f"```board\n{BLOCK}```\n\nThe first box is the card.")
        self.assertEqual(said, f"One. Two. {boardpen.BOARD_DREW}")
        self.assertIn("The first box is the card.", pen.written,
                      "the rest stays in the record")
        self.assertIn("Three.", pen.written)

    def test_a_streamed_fence_answers_with_the_line_its_report_earns(self):
        pen, _ = self.pen(accepted=0, skipped=2, reasons=["bad"] * 2)
        self.assertTrue(pen.on_fence(BLOCK).startswith(boardpen.BOARD_REFUSED))
        pen, _ = self.pen(accepted=2)
        self.assertEqual(pen.on_fence(BLOCK), boardpen.BOARD_DREW)
        self.assertEqual(pen.on_fence('node b box "b"\n'), "",
                         "a second clean block is not announced again")

    def test_a_streamed_turns_final_text_is_what_was_already_spoken(self):
        """The gateway compares the parts it spoke with the final answer and speaks any
        remainder (V13-G7), so the final text of a streamed drawing turn must be the lead it
        already heard, uncapped, and the same report line."""
        pen, _ = self.pen(accepted=2)
        line = pen.on_fence(BLOCK)
        said = pen.take(f"One. Two. Three.\n\n```board\n{BLOCK}```\n\nAfter.")
        self.assertEqual(said, f"One. Two. Three. {line}")

    def test_the_repair_note_carries_the_raw_reason_for_the_next_turn(self):
        pen, _ = self.pen(accepted=6, skipped=21,
                          reasons=["no node called 'meaning' on this board"] * 21)
        pen.take(f"```board\n{BLOCK}```")
        note = pen.repair_note()
        self.assertIn("21 of 27", note)
        self.assertIn("no node called 'meaning' on this board", note)
        clean, _ = self.pen(accepted=2)
        clean.take(f"```board\n{BLOCK}```")
        self.assertEqual(clean.repair_note(), "")

    def test_a_refusal_is_said_in_plain_words(self):
        for why, heard in (("x.txt is not a file on this machine", "not on this machine"),
                           ("/etc/x is outside what may go on a board: /a", "outside"),
                           ("b-001 already has 12 nodes; start another board", "twelve")):
            pen, _ = self.pen(fail=why)
            said = pen.take(f"```board\n{BLOCK}```")
            self.assertIn(heard, said, said)
            self.assertNotIn("/etc/x", said)


class PenDuplicateTest(unittest.TestCase):
    """THE PEN'S OWN LAYER of the b-003 fix, isolated from the other two.

    The two readings of one block are not the same STRING: the stream's carries whatever
    whitespace the deltas left, and before `strip_fences` it carried the closing ``` as
    well. Compared raw they are two blocks; normalised they are one.
    """

    def test_two_readings_that_differ_only_in_whitespace_are_one_push(self):
        door = FakeDoor()
        pen = boardpen.BoardPen(None, boardpen.talker_source(), push=door)
        pen.draw('node a box "a card"\nnote a "one"\n')
        pen.draw('  node   a  box "a card"\n\n  note a "one"\n')
        self.assertEqual(len(door.bodies), 1, door.bodies)
        self.assertEqual(pen.count, 1)


    def test_a_genuinely_different_block_is_a_second_push(self):
        door = FakeDoor()
        pen = boardpen.BoardPen(None, boardpen.talker_source(), push=door)
        pen.draw('node a box "a card"\n')
        pen.draw('node b box "another card"\n')
        self.assertEqual(len(door.bodies), 2)

    def test_an_empty_block_is_nothing_to_draw(self):
        door = FakeDoor()
        pen = boardpen.BoardPen(None, boardpen.talker_source(), push=door)
        self.assertFalse(pen.draw("   \n```\n# a comment\n"))
        self.assertEqual(door.bodies, [])


class FenceMarkTest(unittest.TestCase):
    """`keel/sentences.py`'s layer: a fence mark never survives into a body.

    This is the ROOT of b-003. A turn whose last delta ended with the closing ``` and no
    newline left that ``` on the cutter's buffer, and `flush` appends the buffer to the body
    it is closing, so the streamed reading of a block carried a line the finished text's
    reading did not, and the skipped log filled with `'```' is not an op`.
    """

    def test_a_turn_that_ends_mid_fence_still_yields_a_clean_body(self):
        cutter = sentences.Cutter()
        cutter.feed('```board\nnode a box "a"\n```')      # no trailing newline
        fences = [e for e in cutter.flush() if e["type"] == sentences.FENCE]
        self.assertEqual(len(fences), 1)
        self.assertNotIn(sentences.TICKS, fences[0]["body"])
        self.assertEqual(fences[0]["body"], 'node a box "a"\n')

    def test_the_finished_text_reading_drops_a_stray_mark_too(self):
        _, bodies = sentences.board_blocks('```board\nnode a box "a"\n```\n```\n')
        self.assertEqual(len(bodies), 1)
        self.assertNotIn(sentences.TICKS, bodies[0])

    def test_the_store_is_never_asked_whether_a_fence_mark_is_an_op(self):
        for line in (sentences.TICKS, sentences.TICKS + "board", "  ``` "):
            self.assertIsNone(boards.parse_line(line))


class TalkerSourceTest(unittest.TestCase):
    """The talker's pen is the house's pen with a different source, and it draws on the
    talker's own board: `--talker`, linked to no card."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = make_config(Path(self.tmp.name))
        self.cfg.serve_port = 8791
        self.addCleanup(self.tmp.cleanup)

    def test_the_default_door_is_the_store_and_the_source_decides_whose_board(self):
        pen = boardpen.BoardPen(self.cfg, boardpen.talker_source())
        said = pen.take(f"Right.\n\n```board\n{BLOCK}```\n")
        self.assertTrue(said.endswith(boardpen.BOARD_DREW), said)
        record = boards.read_record(self.cfg, "b-001")
        self.assertEqual(record["source"], {"kind": "talker", "card": None})
        self.assertEqual(record["actor"], "talker")
        self.assertIn('node a box "a card"', boards.ops_lines(self.cfg, "b-001"))

    def test_a_cards_pen_draws_on_that_card_as_the_house(self):
        board = Board(self.cfg.db_path)
        self.addCleanup(board.close)
        card = board.create("personal", "a card", actor="human")
        pen = boardpen.BoardPen(self.cfg, boardpen.card_source(card))
        pen.take(f"```board\n{BLOCK}```")
        record = boards.read_record(self.cfg, "b-001")
        self.assertEqual(record["source"], {"kind": "card", "card": card})
        self.assertEqual(record["actor"], "house")

    def test_the_pen_imports_nothing_the_gateway_may_not_have(self):
        """`voice/harbor_voice/drawing.py` imports this module from the gateway's own 3.12
        interpreter, which must never hold the store, the config or the artifact tokens. So
        the only import at module level is `keel.sentences`, which is `hashlib` and `re`."""
        source = (Path(boardpen.__file__)).read_text()
        top = source.split("class BoardPen", 1)[0]
        self.assertIn("from keel import sentences", top)
        for forbidden in ("from keel import boards", "import keel.boards", "from keel import config"):
            self.assertNotIn(forbidden, top, f"{forbidden} at module level")
        self.assertIn("from keel import boards", source, "the store door is imported lazily")


if __name__ == "__main__":
    unittest.main()


class HarborDrawingTest(unittest.TestCase):
    """The gateway's half (`voice/harbor_voice/drawing.py`): the push runs in the talker's
    folder (C2), and a drawing that did not land is recorded and carried (C1)."""

    def setUp(self):
        import sys
        voice = str(Path(__file__).resolve().parent.parent / "voice")
        if voice not in sys.path:
            sys.path.insert(0, voice)
        from harbor_voice import drawing
        self.drawing = drawing
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        here = Path(self.tmp.name)
        for name, value in (("TRANSCRIPT", here / "transcript.jsonl"),
                            ("REPORT_FILE", here / "board-report.txt")):
            patch = mock.patch.object(drawing, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_push_runs_in_the_talkers_own_folder(self):
        seen = {}

        def run(argv, **kwargs):
            seen.update(kwargs)
            return mock.Mock(returncode=0, stdout='{"board": "b-1"}', stderr="")

        with mock.patch.object(self.drawing.subprocess, "run", run):
            self.drawing.push_ops('node a box "a"\n')
        self.assertEqual(seen["cwd"], str(self.drawing.config.TALKER_CWD))

    def test_a_refused_drawing_is_recorded_with_its_turn_and_carried_once(self):
        import json

        def refuses(_body):
            raise RuntimeError("keel board: nothing was drawn: board-b-002-lines.txt is "
                               "not a file on this machine")

        said, count = self.drawing.lift(f"Here.\n\n```board\n{BLOCK}```\n", push=refuses,
                                        turn="t-42")
        self.assertEqual(count, 0)
        self.assertNotIn(boardpen.BOARD_DREW, said)
        records = [json.loads(line) for line in
                   self.drawing.TRANSCRIPT.read_text().splitlines()]
        self.assertEqual([r["kind"] for r in records], ["draw-failed"])
        self.assertEqual(records[0]["turn"], "t-42")
        self.assertEqual(records[0]["board"]["state"], "refused")
        carried = self.drawing.carried_report()
        self.assertTrue(carried.startswith(boardpen.REPORT_MARK), carried)
        self.assertIn("not a file on this machine", carried)
        self.assertEqual(self.drawing.carried_report(), "", "carried once")

    def test_a_clean_drawing_records_nothing(self):
        door = FakeDoor(accepted=2)
        self.drawing.lift(f"```board\n{BLOCK}```\n", push=door, turn="t-1")
        self.assertFalse(self.drawing.TRANSCRIPT.exists())
        self.assertEqual(self.drawing.carried_report(), "")

    def test_the_next_harbor_turn_is_framed_with_the_report(self):
        from harbor_voice import harbormsg
        self.drawing.REPORT_FILE.write_text(boardpen.REPORT_MARK + "it was refused\n")
        lines = []
        with mock.patch.object(harbormsg, "TURN_LOCK_FILE", self.drawing.REPORT_FILE.parent / "t.lock"), \
                mock.patch.object(harbormsg, "open_session", return_value=("s-1", True, "")), \
                mock.patch.object(harbormsg, "run_turn",
                                  lambda line, *a, **k: lines.append(line) or "Right."), \
                mock.patch.object(harbormsg, "count_turn"), \
                mock.patch.object(harbormsg, "log"), \
                mock.patch.object(harbormsg, "SayInbox"):
            harbormsg.send("draw it again")
            for _ in range(200):
                if lines:
                    break
                import time
                time.sleep(0.01)
        self.assertTrue(lines and "it was refused" in lines[0], lines)


class ReviewFindingsTest(unittest.TestCase):
    """The fresh-context review of lane C, F1 and F7: each is the exact sequence it named."""

    def pen(self, **kwargs):
        door = FakeDoor(**kwargs)
        return boardpen.BoardPen(None, boardpen.talker_source(), push=door), door

    def test_f1_a_streamed_claim_already_heard_is_not_taken_back_so_nothing_is_said_twice(self):
        """Cutter, then the pen, then the gateway's own spoken-versus-final check."""
        import sys
        voice = str(Path(__file__).resolve().parent.parent / "voice")
        if voice not in sys.path:
            sys.path.insert(0, voice)
        from harbor_voice import dispatcher
        raw = ("The queue feeds the worker. I drew the flow below.\n\n"
               f"```board\n{BLOCK}```\n\nAnd the rest.\n")
        pen, _ = self.pen(fail="board-b-002-lines.txt is not a file on this machine")
        cutter = sentences.Cutter()
        parts = []
        for event in cutter.feed(raw) + cutter.flush():
            if event["type"] == sentences.PART and not pen.silenced:
                parts.append(event["text"])
            elif event["type"] == sentences.FENCE and event["lang"] == "board":
                line = pen.on_fence(event["body"])
                if line:
                    parts.append(line)
        self.assertEqual(parts[:2], ["The queue feeds the worker.", "I drew the flow below."])
        self.assertTrue(parts[2].startswith(boardpen.BOARD_REFUSED), parts)
        final = pen.take(raw)
        self.assertEqual(dispatcher.answer_left(parts, final), ("", "covered"), final)
        self.assertNotIn("I drew the flow", pen.written, "the RECORD is still stripped")

    def test_f1_a_one_shot_turn_still_strips_the_claim(self):
        pen, _ = self.pen(fail="nope")
        said = pen.take(f"I drew the flow below.\n\n```board\n{BLOCK}```\n")
        self.assertNotIn("I drew the flow", said)

    def test_f7_an_empty_board_block_does_not_silence_the_rest(self):
        pen, door = self.pen(accepted=2)
        said = pen.take("Lead.\n\n```board\n```\n\nAfter the empty one.\n\n"
                        f"```board\n{BLOCK}```\n\nTail.")
        self.assertIn("After the empty one.", said)
        self.assertNotIn("Tail.", said)
        self.assertTrue(said.endswith(boardpen.BOARD_DREW), said)

    def test_f7_a_repeat_the_store_already_had_does_not_silence_the_rest(self):
        pen, _ = self.pen(duplicate=True)
        said = pen.take(f"Lead.\n\n```board\n{BLOCK}```\n\nStill said.")
        self.assertIn("Still said.", said)
        self.assertFalse(pen.silenced)

    def test_f7_a_streamed_empty_block_leaves_speech_on(self):
        pen, _ = self.pen(accepted=2)
        self.assertEqual(pen.on_fence("\n"), "")
        self.assertFalse(pen.silenced)
        pen.on_fence(BLOCK)
        self.assertTrue(pen.silenced)


class OncePerAnswerTest(unittest.TestCase):
    """N1 of the lane C follow-up (the verifier reproduced it): a block is pushed at most once
    per answer, whatever the first attempt came to."""

    def test_a_streamed_push_that_raised_is_not_pushed_again_by_the_final_pass(self):
        calls = []

        def flaky(body):
            calls.append(body)
            if len(calls) == 1:
                raise boards.BoardError("the board did not answer")
            return {"board": "b-001", "url": "u", "accepted": 2, "skipped": 0, "reasons": []}

        pen = boardpen.BoardPen(None, boardpen.talker_source(), push=flaky)
        heard = pen.on_fence(BLOCK)
        self.assertTrue(heard.startswith(boardpen.BOARD_REFUSED), heard)
        said = pen.take(f"Here.\n\n```board\n{BLOCK}```\n")
        self.assertEqual(len(calls), 1, "the block was pushed a second time at the end")
        self.assertNotIn(boardpen.BOARD_DREW, said)
        self.assertTrue(pen.repair_note(), "the next turn is told, and nothing landed behind it")
