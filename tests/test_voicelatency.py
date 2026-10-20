"""`keel voice latency` (D-5): per-stage timing read off the gateway's own transcript.

Every figure is the difference between two `at` stamps the gateway already writes, so the
fixture below is a transcript in the gateway's own record shapes, with times chosen so each
stage has one known answer. The report is read only, which is checked too.
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from keel import voice, voicelatency
from tests.helpers import make_config


def rec(at, kind, turn="", **fields):
    return {"at": at, "kind": kind, "turn": turn, **fields}


# Turn a: push to talk, a Harbor answer that streamed, first audio after it.
# Turn b: hands-free, the detector ended it, a one-shot Harbor answer, no first-audio
#         record (a turn from before D-5).
# Turn c: a typed turn with no end record at all.
RECORDS = [
    rec(100.0, "listen", handsFree=False),
    rec(104.0, "page", event="release", reason="finger"),
    rec(104.4, "said", "a", tier=""),
    rec(104.5, "digest", "a", tier="harbor"),
    rec(106.4, "answer-part", "a", tier="harbor"),
    rec(106.9, "first-audio", "a", tier="harbor"),
    rec(108.0, "answer", "a", tier="harbor"),
    rec(200.0, "endpoint", reason="hangover"),
    rec(200.2, "said", "b", tier=""),
    rec(204.2, "answer", "b", tier="harbor"),
    rec(300.0, "said", "c", tier=""),
    rec(301.0, "answer", "c", tier="instant"),
    rec(301.3, "first-audio", "c", tier="instant"),
]


class StagesTest(unittest.TestCase):
    def setUp(self):
        self.rows = {row["turn"]: row for row in voicelatency.turns(RECORDS)}

    def test_push_to_talk_is_measured_from_the_release(self):
        a = self.rows["a"]
        self.assertEqual((a["stt"], a["model"], a["tts"], a["total"]), (0.4, 2.0, 0.5, 2.9))

    def test_a_streamed_answer_counts_its_first_part_not_the_whole(self):
        self.assertEqual(self.rows["a"]["model"], 2.0)

    def test_hands_free_is_measured_from_the_detector(self):
        b = self.rows["b"]
        self.assertEqual((b["stt"], b["model"]), (0.2, 4.0))
        self.assertIsNone(b["tts"], "an older turn has no first-audio record")

    def test_an_end_record_is_used_once(self):
        self.assertIsNone(self.rows["c"]["end"])
        self.assertIsNone(self.rows["c"]["stt"])
        self.assertEqual(self.rows["c"]["model"], 1.0)

    def test_an_end_long_before_the_turn_belongs_to_another_listen(self):
        rows = voicelatency.turns([rec(0.0, "page", event="release"), rec(90.0, "said", "x")])
        self.assertIsNone(rows[0]["end"])

    def test_an_answer_that_was_not_spoken_is_not_first_words(self):
        rows = voicelatency.turns([rec(1.0, "said", "x"),
                                   rec(3.0, "answer", "x", spoken=False)])
        self.assertIsNone(rows[0]["model"])


class SummaryTest(unittest.TestCase):
    def test_percentiles_are_nearest_rank(self):
        values = [float(v) for v in range(1, 21)]
        self.assertEqual(voicelatency.percentile(values, 0.5), 10.0)
        self.assertEqual(voicelatency.percentile(values, 0.95), 19.0)
        self.assertIsNone(voicelatency.percentile([], 0.5))

    def test_it_is_per_tier(self):
        tiers = voicelatency.summary(voicelatency.turns(RECORDS))
        self.assertEqual(tiers["harbor"]["turns"], 2)
        self.assertEqual(tiers["harbor"]["model"]["n"], 2)
        self.assertEqual(tiers["harbor"]["tts"]["n"], 1)
        self.assertEqual(tiers["instant"]["turns"], 1)


class VerbTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = make_config(Path(tmp.name))
        self.path = voice.paths_from(self.cfg).data / "transcript.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("".join(json.dumps(r) + "\n" for r in RECORDS) + "not json\n")

    def run_verb(self, *extra):
        out = io.StringIO()
        with redirect_stdout(out):
            code = voice.latency(self.cfg, voice.paths_from(self.cfg), *extra)
        return code, out.getvalue()

    def test_the_report_names_each_stage_per_tier(self):
        code, text = self.run_verb()
        self.assertEqual(code, 0)
        self.assertIn("harbor: 2 turn(s)", text)
        self.assertIn("end to first audio", text)
        self.assertIn("transcript to first words", text)

    def test_json_carries_the_turns(self):
        code, text = self.run_verb(True)
        self.assertEqual(code, 0)
        doc = json.loads(text)
        self.assertEqual([row["turn"] for row in doc["turns"]], ["a", "b", "c"])

    def test_it_writes_nothing(self):
        before = (self.path.stat().st_mtime_ns, self.path.read_bytes())
        listing = sorted(os.listdir(self.path.parent))
        self.run_verb()
        self.assertEqual((self.path.stat().st_mtime_ns, self.path.read_bytes()), before)
        self.assertEqual(sorted(os.listdir(self.path.parent)), listing)


# H2 (lane H, 2026-09-24): the Harbor stamps between `said` and the answer.
# Turn h: tool-free, 1.0 s waiting for the conversation, 5.0 s in the process, 0.25 s pen.
# Turn t: two tools, 60 s in the process.
# Turn o: an older turn with no stamps at all.
STAMPED = [
    rec(10.0, "said", "h", tier="harbor"),
    rec(11.0, "harbor-start", "h", tier="harbor", warm=False),
    rec(16.0, "harbor-model", "h", tier="harbor", numTurns=1, tools=0),
    rec(16.25, "harbor-pen", "h", tier="harbor"),
    rec(16.5, "answer", "h", tier="harbor"),
    rec(17.0, "first-audio", "h", tier="harbor"),
    rec(100.0, "said", "t", tier="harbor"),
    rec(100.5, "harbor-start", "t", tier="harbor", warm=False),
    rec(160.5, "harbor-model", "t", tier="harbor", numTurns=3, tools=2),
    rec(160.6, "harbor-pen", "t", tier="harbor"),
    rec(161.5, "answer", "t", tier="harbor"),
    rec(200.0, "said", "o", tier="harbor"),
    rec(215.0, "answer", "o", tier="harbor"),
]


class HarborStampsTest(unittest.TestCase):
    def setUp(self):
        self.rows = {row["turn"]: row for row in voicelatency.turns(STAMPED)}

    def test_each_stage_between_the_stamps(self):
        h = self.rows["h"]
        self.assertEqual((h["wait"], h["run"], h["pen"], h["deliver"]), (1.0, 5.0, 0.25, 0.5))
        self.assertEqual(h["tools"], 0)

    def test_the_tool_count_rides_on_the_row(self):
        self.assertEqual(self.rows["t"]["tools"], 2)
        self.assertEqual(self.rows["t"]["run"], 60.0)

    def test_an_older_turn_has_no_stages_and_no_tool_count(self):
        o = self.rows["o"]
        self.assertIsNone(o["tools"])
        self.assertEqual((o["wait"], o["run"], o["pen"], o["deliver"]),
                         (None, None, None, None))
        self.assertEqual(o["model"], 15.0)

    def test_the_summary_splits_harbor_by_tools(self):
        tiers = voicelatency.summary(voicelatency.turns(STAMPED))
        self.assertEqual(tiers["harbor"]["turns"], 3)
        self.assertEqual(tiers["harbor, tool-free"]["turns"], 1)
        self.assertEqual(tiers["harbor, with tools"]["turns"], 1)
        self.assertEqual(tiers["harbor, with tools"]["run"]["p50"], 60.0)
        self.assertEqual(tiers["harbor, tool-free"]["model"]["p50"], 6.5)


    def test_a_tier_with_no_stamps_does_not_print_empty_harbor_stages(self):
        text = "\n".join(voicelatency.lines(voicelatency.summary(voicelatency.turns(RECORDS))))
        self.assertNotIn("spawn to model done", text)


if __name__ == "__main__":
    unittest.main()
