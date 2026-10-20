"""Lane H (2026-09-24): Harbor's voice turn, measured honestly.

Measured on the box that morning: a trivial Harbor turn is about 5 s, and yet `keel voice
latency` reported Harbor's "transcript to first words" at p50 14.8 s. Three things made the
report dishonest (turns that used tools, house turns filed under Harbor, and gaps with no
stamps to split them), and two made the transcript itself say more than happened (a capture
counted as two turns, and a streamed answer with code in it spoken twice). Each test below
drives the gateway's own code with every outside thing replaced, and reads back the records
the gateway wrote.
"""

import importlib.machinery
import importlib.util
import io
import json
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "voice") not in sys.path:
    sys.path.insert(0, str(ROOT / "voice"))

from harbor_voice import config as vconfig                            # noqa: E402
from harbor_voice import (connected, dispatcher, drawing, filler,     # noqa: E402
                          harbormsg, harborlive, stamps, verbs)

from keel import narration, sentences, voicelatency                   # noqa: E402


class Snap:
    doc = {"running": [], "queue": [], "reviews": []}
    age = 0.0
    healthy = True
    error = ""


class Bus:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def make_dispatcher(tmp: Path, spoken: list, **extra) -> dispatcher.Dispatcher:
    """A dispatcher whose every outside thing is a recorder, writing into `tmp`."""
    def speak(text, generation, spk=None):
        spoken.append(text)
        return {"engines": ["fake"], "firstAudioAt": time.time()}

    return dispatcher.Dispatcher(
        Snap(), Bus(), speak, harbormsg.SayInbox(tmp / "say"), tmp / "transcript.jsonl",
        deliver=extra.pop("deliver", lambda *a, **k: (False, "a fixture")),
        filler_model=filler.NoFiller(),
        progress_inbox=harbormsg.SayInbox(tmp / "progress"),
        open_inbox=harbormsg.SayInbox(tmp / "opening"),
        queue_answer=lambda *a: True, **extra)


def records(tmp: Path) -> list[dict]:
    path = tmp / "transcript.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def wait_done(turn, seconds: float = 5.0) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline and turn.phase != "done":
        time.sleep(0.02)


class TmpCase(unittest.TestCase):
    def setUp(self):
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        self.tmp = Path(handle.name)
        self.spoken: list[str] = []


def vad_measure():
    """`bin/keel-voice-vad-measure`, loaded as a module (it has no .py suffix)."""
    path = ROOT / "bin" / "keel-voice-vad-measure"
    loader = importlib.machinery.SourceFileLoader("vad_measure", str(path))
    spec = importlib.util.spec_from_loader("vad_measure", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class OneUtteranceIsOneTurnTest(TmpCase):
    """H4: `--gaps` on the box found seven turns "logged twice 0.0 s apart with identical
    text". Each was ONE capture: a capture writes `captured` and then `answer`, both carrying
    his words, and `--gaps` counted every such record as a turn of its own."""

    def test_a_capture_is_one_turn_to_gaps(self):
        d = make_dispatcher(self.tmp, self.spoken,
                            file_capture=lambda said, space, heard: {"id": "c-9",
                                                                     "space": "work"})
        d.capture("Just like we did for vibration replay, we can have those two")
        out = io.StringIO()
        with redirect_stdout(out):
            vad_measure().gaps(self.tmp / "transcript.jsonl")
        self.assertIn("none", out.getvalue(), out.getvalue())

    def test_two_real_turns_close_together_are_still_a_gap(self):
        d = make_dispatcher(self.tmp, self.spoken,
                            file_capture=lambda said, space, heard: {"id": "c-9",
                                                                     "space": "work"})
        d.capture("the first half of a sentence")
        d.capture("and the rest of it")
        out = io.StringIO()
        with redirect_stdout(out):
            vad_measure().gaps(self.tmp / "transcript.jsonl")
        self.assertIn("'the first half of a sentence'  ->  'and the rest of it'",
                      out.getvalue())
        self.assertEqual(out.getvalue().count("  ->  "), 1, out.getvalue())


CODE_ANSWER = ("The fix is one line.\n\n```python\nprint(total / count)\n```\n\n"
               "It divides by the count now.")


class StreamedCodeIsNotSpokenTwiceTest(TmpCase):
    """H5: a streamed Harbor answer with a code block in it was spoken whole AGAIN, code
    included. The cutter spoke "There is a code block..." in the block's place, the final
    answer still carried the code, so the two never matched (V13-G7) and the gateway decided
    nothing of it had been heard."""

    def streamed_turn(self, raw: str, final: str):
        def deliver(said, context="", turn_id="", **extra):
            def run():
                cutter = sentences.Cutter()
                for event in cutter.feed(raw) + cutter.flush():
                    if event["type"] == sentences.PART:
                        narration.leave_part(self.tmp / "progress", event["text"],
                                             turn=turn_id)
                        time.sleep(0.05)
                time.sleep(0.1)
                harbormsg.SayInbox(self.tmp / "say").write(final, turn=turn_id)
            threading.Thread(target=run, daemon=True).start()
            return True, "turn started"

        d = make_dispatcher(self.tmp, self.spoken, deliver=deliver)
        with mock.patch.object(vconfig, "HARBOR_KEPT_ALIVE", True):
            turn = d.answer("what did you change")
        wait_done(turn)
        return turn

    def test_a_covered_answer_with_code_finishes_silently(self):
        final = drawing.read_answer(CODE_ANSWER)["said"]
        turn = self.streamed_turn(CODE_ANSWER, final)
        # What the filler said over the wait is not the answer; the answer starts at its
        # first sentence.
        heard = self.spoken[self.spoken.index("The fix is one line."):]
        self.assertEqual(heard, ["The fix is one line.", sentences.FENCE_SAID,
                                 "It divides by the count now."], heard)
        kinds = [rec["kind"] for rec in records(self.tmp)]
        self.assertIn("answer-covered", kinds)
        self.assertEqual(turn.answer, final, "the page and the record keep the whole answer")

    def test_the_remainder_after_a_code_block_is_spoken_without_the_code(self):
        final = drawing.read_answer(CODE_ANSWER)["said"]
        left, why = dispatcher.answer_left(["The fix is one line."], final)
        self.assertEqual(why, "the stream stopped short")
        self.assertNotIn("print", left)
        self.assertTrue(left.startswith(sentences.FENCE_SAID), left)

    def test_a_cut_stream_speaks_the_whole_answer_without_the_code(self):
        final = drawing.read_answer(CODE_ANSWER)["said"]
        left, why = dispatcher.answer_left([], final)
        self.assertNotIn("print", left)
        self.assertIn(sentences.FENCE_SAID, left)

    def test_one_stand_in_line_per_answer_as_the_cutter_says_it(self):
        raw = CODE_ANSWER + "\n\n```sh\nmake test\n```\n\nAnd run it."
        cutter = sentences.Cutter()
        parts = [e["text"] for e in cutter.feed(raw) + cutter.flush()
                 if e["type"] == sentences.PART]
        final = drawing.read_answer(raw)["said"]
        self.assertEqual(dispatcher.answer_left(parts, final), ("", "covered"))

    def test_the_stand_in_line_is_the_cutters_own(self):
        """Restated in `verbs` (the voice package imports nothing from `keel/`), so the
        copy is held to the original here."""
        self.assertEqual(verbs.FENCE_SAID, sentences.FENCE_SAID)


class HouseTurnsAreTheHousesTest(TmpCase):
    """H3: a turn he said to a connected house is reported under the house tier, never
    Harbor's. On the box 5 of the 13 turns `keel voice latency` called Harbor's were house
    turns, and a house turn's time is the house's model and tools, not Harbor's."""

    def connected_turn(self):
        d = make_dispatcher(self.tmp, self.spoken)
        d.pin_to("c-317", time.time() + 600, "the narration one", "work")

        def ask(card, said, turn="", progress="", **rest):
            return {"ok": True, "say": "The tests pass."}

        with mock.patch.object(connected, "ask", ask):
            turn = d.answer("did the tests pass")
            wait_done(turn)
        return turn

    def test_the_said_record_already_names_the_house(self):
        self.connected_turn()
        said = [rec for rec in records(self.tmp) if rec["kind"] == "said"]
        self.assertEqual([rec["tier"] for rec in said], ["house"], said)

    def test_the_report_files_it_under_the_house(self):
        self.connected_turn()
        tiers = voicelatency.summary(voicelatency.turns(records(self.tmp)))
        self.assertEqual(list(tiers), ["house"], tiers)

    def test_a_connected_record_outranks_any_harbor_label(self):
        """Whatever else a record says, a turn that went to a house is the house's: the
        `said` of an older gateway said Harbor, and a record written after the answer by a
        Harbor-side writer carries `harbor` by construction."""
        recs = [{"at": 1.0, "kind": "said", "turn": "t", "tier": "harbor"},
                {"at": 1.1, "kind": "connected", "turn": "t", "card": "c-317"},
                {"at": 4.0, "kind": "answer", "turn": "t", "tier": "house"},
                {"at": 4.2, "kind": "answer-written", "turn": "t", "tier": "harbor"}]
        self.assertEqual(voicelatency.turns(recs)[0]["tier"], "house")

    def test_an_ordinary_turn_is_still_harbors(self):
        recs = [{"at": 1.0, "kind": "said", "turn": "t", "tier": "harbor"},
                {"at": 4.0, "kind": "answer", "turn": "t", "tier": "harbor"}]
        self.assertEqual(voicelatency.turns(recs)[0]["tier"], "harbor")


ENVELOPE = json.loads((ROOT / "tests" / "fixtures" / "harness" / "turn.json").read_text())


class Done:
    """What `subprocess.run` hands back."""

    def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


class HarborCase(TmpCase):
    """`harbormsg.send` with its files in `tmp`, its session fixed, and no `claude`."""

    def setUp(self):
        super().setUp()
        for module, name, value in (
                (harbormsg, "TURN_LOCK_FILE", self.tmp / "harbor-turn.lock"),
                (harbormsg, "TRANSCRIPT", self.tmp / "transcript.jsonl"),
                (harbormsg, "SAY_DIR", self.tmp / "say"),
                (harbormsg, "PROGRESS_DIR", self.tmp / "progress"),
                (drawing, "TRANSCRIPT", self.tmp / "transcript.jsonl"),
                (drawing, "REPORT_FILE", self.tmp / "board-report.txt"),
                # c-552: a kept-alive turn writes its deck reads to the judges' log.
                (vconfig, "JUDGES_LOG", self.tmp / "judges.jsonl")):
            patch = mock.patch.object(module, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        for name in ("count_turn", "log", "report_failure"):
            patch = mock.patch.object(harbormsg, name)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(harbormsg, "open_session", return_value=("s-1", True, ""))
        patch.start()
        self.addCleanup(patch.stop)

    def send(self, turn_id: str = "t-1") -> str:
        """One spoken turn; what landed in the say inbox."""
        ok, _ = harbormsg.send("is the drain running", turn_id=turn_id)
        self.assertTrue(ok)
        inbox = harbormsg.SayInbox(self.tmp / "say")
        deadline = time.time() + 5
        while time.time() < deadline:
            got = inbox.claim(turn_id)
            if got:
                return str(got[0].get("text") or "")
            time.sleep(0.02)
        self.fail("the turn never answered")

    def stamps_of(self, turn_id: str = "t-1") -> list[dict]:
        return [rec for rec in records(self.tmp) if rec.get("turn") == turn_id
                and rec["kind"].startswith("harbor-")]


class HarborTurnIsStampedTest(HarborCase):
    """H2 and H1's measurable half: every Harbor turn says when its `claude` started, when
    the answer came back and how many tools it used, and when the pen was done."""

    def fake_run(self, rounds: int, took: float = 0.05):
        def run(argv, **kwargs):
            time.sleep(took)
            return Done(json.dumps(dict(ENVELOPE, num_turns=rounds,
                                        result="The drain is paused.")))
        return run

    def test_a_one_shot_turn_writes_its_three_stamps_in_order(self):
        with mock.patch.object(harbormsg.subprocess, "run", self.fake_run(3)):
            answer = self.send()
        self.assertEqual(answer, "The drain is paused.")
        got = self.stamps_of()
        self.assertEqual([rec["kind"] for rec in got],
                         [stamps.SPAWN, stamps.MODEL, stamps.PEN], got)
        spawn, model, pen = got
        self.assertGreaterEqual(model["at"] - spawn["at"], 0.05)
        self.assertLessEqual(model["at"], pen["at"])
        self.assertEqual((model["tools"], model["numTurns"]), (2, 3))
        self.assertEqual(model["durationMs"], ENVELOPE["duration_ms"])
        self.assertFalse(spawn["warm"])
        self.assertTrue(all(rec["tier"] == "harbor" for rec in got))

    def test_the_gateway_and_the_report_agree_end_to_end(self):
        """His words through the real dispatcher and the real `send`, a `claude` that used
        two tools, and `keel voice latency`'s reading of the one transcript they wrote."""
        d = make_dispatcher(self.tmp, self.spoken, deliver=harbormsg.send)
        with mock.patch.object(harbormsg.subprocess, "run", self.fake_run(3, took=0.2)):
            turn = d.answer("what is building")
            wait_done(turn)
        self.assertEqual(turn.answer, "The drain is paused.")
        rows = voicelatency.turns(records(self.tmp))
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual((row["tier"], row["tools"]), ("harbor", 2))
        self.assertGreaterEqual(row["run"], 0.2)
        for stage in ("wait", "pen", "deliver", "model"):
            self.assertIsNotNone(row[stage], stage)
        tiers = voicelatency.summary(rows)
        self.assertEqual(tiers["harbor, with tools"]["turns"], 1)
        self.assertEqual(tiers["harbor, tool-free"]["turns"], 0)

    def test_a_tool_free_turn_says_zero_tools(self):
        with mock.patch.object(harbormsg.subprocess, "run", self.fake_run(1)):
            self.send()
        self.assertEqual(self.stamps_of()[1]["tools"], 0)

    def test_a_failed_turn_still_says_when_it_started(self):
        def refuse(argv, **kwargs):
            return Done("", 1, "something broke")
        with mock.patch.object(harbormsg.subprocess, "run", refuse):
            self.send()
        self.assertEqual([rec["kind"] for rec in self.stamps_of()], [stamps.SPAWN])

    def test_the_envelope_is_read_for_what_it_says_and_nothing_else(self):
        self.assertEqual(stamps.envelope(ENVELOPE),
                         {"numTurns": 1, "tools": 0, "durationMs": 5038})
        self.assertEqual(stamps.envelope({"num_turns": True}), {})
        self.assertEqual(stamps.envelope(None), {})


class FakeProcess:
    """The kept-alive `claude`, replaying a turn's stream records."""

    def __init__(self, stream: list, result: dict):
        self.stream, self.result, self.turns_seen = stream, result, 0

    def say(self, text, deadline, on_record):
        for record in self.stream:
            on_record(record)
        return self.result


def delta(text: str) -> dict:
    return {"type": "stream_event",
            "event": {"type": "content_block_delta",
                      "delta": {"type": "text_delta", "text": text}}}


TOOL = {"type": "assistant", "message": {"content": [
    {"type": "tool_use", "name": "Bash", "input": {"command": "kb list"}}]}}


class KeptAliveTurnTest(HarborCase):
    """The same stamps on the kept-alive path (R2), and H1's one short line before a tool
    heard as a preamble rather than as an answer he then hears twice."""

    def live_turn(self, stream: list, result: dict) -> dict:
        process = FakeProcess(stream, result)
        live = harborlive.LiveHarbor()

        def process_for(session, existed, turns):
            return process
        with mock.patch.object(live, "process_for", process_for), \
                mock.patch.object(live, "idle_later"):
            return live.turn("line", "s-1", True, 0, "t-2", self.tmp / "progress", 10.0,
                             lambda text: None)

    def parts(self) -> list[str]:
        return [rec["text"] for rec in harbormsg.SayInbox(self.tmp / "progress").claim("t-2")]

    def test_the_turn_hands_back_its_clock(self):
        read = self.live_turn([delta("The drain is paused.")],
                              {"type": "result", "result": "The drain is paused.",
                               "num_turns": 1})
        clock = read["clock"]
        self.assertLessEqual(clock["spawnAt"], clock["doneAt"])
        self.assertEqual(clock["envelope"]["tools"], 0)

    def test_a_line_before_a_tool_is_a_preamble_not_a_second_answer(self):
        read = self.live_turn(
            [delta("Let me check the board."), TOOL, delta("The drain is paused.")],
            {"type": "result", "result": "The drain is paused.", "num_turns": 2})
        parts = self.parts()
        self.assertEqual(parts, ["Let me check the board.", "The drain is paused."])
        self.assertEqual(read["said"], "Let me check the board. The drain is paused.")
        self.assertEqual(dispatcher.answer_left(parts, read["said"]), ("", "covered"))

    def judge_rows(self) -> list[dict]:
        path = self.tmp / "judges.jsonl"
        return ([json.loads(line) for line in path.read_text().splitlines()]
                if path.exists() else [])

    def test_a_turn_writes_the_deck_reads_it_made_as_section_names(self):
        """c-552: the truth `preturn.prefetch` is scored against. The section only, never
        the command, so a card id or a search term never reaches the log."""
        show = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "kb show c-77"}}]}}
        grep = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Grep", "input": {"pattern": "drain"}}]}}
        self.live_turn([delta("Let me look."), grep, show, TOOL, delta("It is paused.")],
                       {"type": "result", "result": "It is paused.", "num_turns": 4})
        rows = self.judge_rows()
        self.assertEqual([(r["turn"], r["outcome"], r["sections"]) for r in rows],
                         [("t-2", "reads", ["card", "cards"])])
        self.assertNotIn("c-77", json.dumps(rows))

    def test_a_turn_that_read_nothing_says_so(self):
        self.live_turn([delta("The drain is paused.")],
                       {"type": "result", "result": "The drain is paused.", "num_turns": 1})
        self.assertEqual([r["sections"] for r in self.judge_rows()], [[]])

    def test_kept_alive_turn_writes_the_stamps(self):
        read = {"said": "Yes.", "written": "Yes.", "drew": 0, "raw": "Yes.",
                "streamed": True,
                "clock": {"spawnAt": 10.0, "warm": True, "doneAt": 11.0,
                          "envelope": {"numTurns": 2, "tools": 1}}}
        with mock.patch.object(harborlive.LIVE, "turn", return_value=read):
            said = harbormsg.kept_alive_turn("line", "s-1", True, "t-3")
        self.assertEqual(said, "Yes.")
        got = self.stamps_of("t-3")
        self.assertEqual([rec["kind"] for rec in got], [stamps.SPAWN, stamps.MODEL, stamps.PEN])
        self.assertTrue(got[0]["warm"])
        self.assertEqual(got[1]["tools"], 1)


if __name__ == "__main__":
    unittest.main()
