"""The verdict per judge key (c-552): flip on, drop, or needs more data.

What is proved here, in the order it matters: nothing the verdict prints carries what was
said; only personal rows on a real turn inside the window count; truth comes from a label
first and an outcome second, and agreement with the rule is never taken for it; the bar
reaches each of its three answers; and `keel voice judges --since` runs it.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

from keel import judges, judgeverdict as verdict, voice
from tests.helpers import make_config

SECRET = "the words he said"


class VerdictCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "state"
        (self.state / "voice").mkdir(parents=True)
        self.labels_path = Path(self.tmp.name) / "labels.json"
        self.minute = 0

    def line(self, **row):
        with (self.state / "voice" / judges.LOG_FILE).open("a") as out:
            out.write(json.dumps(row) + "\n")

    def call(self, turn, answer, rule, value, confidence, *, day="2026-10-01",
             facts=None, text=SECRET, latency=0.35, real=True, gap=1, miss=""):
        """One preturn call line, a minute (or `gap` minutes) after the last one."""
        self.minute += gap
        at = f"{day}T{10 + self.minute // 60:02d}:{self.minute % 60:02d}:00+0000"
        row = {"at": at, "turn": turn, "judge": "preturn", "modes": {answer: "shadow"},
               "text": text, "rule": {answer: rule},
               "jev": {} if miss else {answer: {"value": value, "confidence": confidence}},
               "latency": None if miss else latency, "miss": miss, "questions": 5,
               "facts": {"space": "personal", "card": "", "pinned": False,
                         "hands_free": True} if facts is None else facts}
        if facts is False:
            del row["facts"]
        self.line(**row)
        if real:
            with (self.state / "voice" / judges.TRANSCRIPT_FILE).open("a") as out:
                out.write(json.dumps({"kind": "said", "turn": turn}) + "\n")

    def outcome(self, turn, what, **fields):
        self.line(kind="outcome", turn=turn, outcome=what, **fields)

    def labels(self, doc):
        self.labels_path.write_text(json.dumps(doc))

    def run_it(self, since="2026-10-01", days=7, space_of=None, words=()):
        return verdict.verdict(self.state, date.fromisoformat(since), days=days,
                               label_paths=[self.labels_path],
                               space_of=space_of or (lambda card: ""), words=words)


class NumbersTest(unittest.TestCase):
    def test_wilson_matches_the_hand_numbers_c542_published(self):
        lower, _ = verdict.wilson(3, 3)
        self.assertAlmostEqual(lower, 0.44, places=2)
        lower, _ = verdict.wilson(12, 12)
        self.assertAlmostEqual(lower, 0.76, places=2)


    def test_the_bar(self):
        self.assertEqual(verdict.decide(30, 20, 0.9, 1.0, 0.8), "flip on")
        self.assertEqual(verdict.decide(29, 20, 0.9, 1.0, 0.8), "needs more data")
        self.assertEqual(verdict.decide(33, 0, 0.0, 1.0, 1.0), "drop")
        self.assertEqual(verdict.decide(40, 10, 0.2, 0.7, 0.9), "drop")
        self.assertEqual(verdict.decide(40, 3, 0.44, 1.0, 0.94), "needs more data")


class FlipOnTest(VerdictCase):
    def test_thirty_confident_right_calls_over_a_worse_rule_flip_on(self):
        for i in range(34):
            self.call(f"t{i}", "card", "none", "c-5", 0.97)
            self.outcome(f"t{i}", "connected", card="c-5")
        doc = self.run_it()
        card = doc["keys"]["preturn.card"]
        self.assertEqual(card["truthed"], 34)
        self.assertEqual(card["rule_right"], 0)
        self.assertEqual(card["verdict"], "flip on")

    def test_the_output_carries_no_words_in_any_line(self):
        for i in range(5):
            self.call(f"t{i}", "route", "talk", "board_read", 0.95)
        text = "\n".join(verdict.lines(self.run_it()))
        self.assertNotIn(SECRET, text)
        self.assertIn("preturn.route", text)
        self.assertIn("t0", text)          # listed to label, by id only


class TruthTest(VerdictCase):
    def test_agreement_is_not_truth_so_an_unlabelled_route_waits_for_a_label(self):
        for i in range(40):
            self.call(f"t{i}", "route", "talk", "talk", 0.99)
        route = self.run_it()["keys"]["preturn.route"]
        self.assertEqual(route["truthed"], 0)
        self.assertEqual(route["verdict"], "needs more data")
        self.assertEqual(len(route["todo"]), verdict.TODO_CAP)

    def test_a_label_beats_an_outcome_and_null_is_out_of_both_rates(self):
        self.call("a", "card", "none", "c-5", 0.95)
        self.outcome("a", "connected", card="c-5")
        self.call("b", "card", "none", "none", 0.95)
        self.outcome("b", "answered")
        self.labels({"a": {"card": "none"}, "b": {"card": None}})
        card = self.run_it()["keys"]["preturn.card"]
        self.assertEqual((card["truthed"], card["rule_right"], card["confident_right"]),
                         (1, 1, 0))

    def test_a_push_to_talk_listen_is_addressed_by_definition(self):
        facts = {"space": "personal", "card": "", "pinned": False, "hands_free": False}
        self.call("a", "addressed", True, False, 0.6, facts=facts)
        self.call("b", "addressed", True, False, 0.6)          # hands-free: needs a label
        entry = self.run_it()["keys"]["preturn.addressed"]
        self.assertEqual((entry["truthed"], entry["todo"]), (1, ["b"]))

    def test_prefetch_truth_is_the_first_section_read_and_none_when_it_read_nothing(self):
        self.call("a", "prefetch", "none", "reviews", 0.95)
        self.outcome("a", "reads", sections=["reviews", "card"])
        self.call("b", "prefetch", "none", "none", 0.95)
        self.outcome("b", "reads", sections=[])
        self.call("c", "prefetch", "none", "cards", 0.95)      # no reads row: unknown
        entry = self.run_it()["keys"]["preturn.prefetch"]
        self.assertEqual((entry["truthed"], entry["confident_right"], entry["todo"]),
                         (2, 2, ["c"]))

    def test_a_held_half_that_got_the_rest_was_not_complete(self):
        self.call("a", "complete", True, False, 0.92)
        self.outcome("a", "carried-on")
        self.assertEqual(self.run_it()["keys"]["preturn.complete"]["confident_right"], 1)

    def test_a_miss_counts_as_a_turn_and_never_as_an_answer(self):
        self.call("a", "complete", True, None, 0, miss="timeout")
        entry = self.run_it()["keys"]["preturn.complete"]
        self.assertEqual((entry["turns"], entry["answered"]), (1, 0))


class WhichRowsTest(VerdictCase):

    def test_the_window_is_since_for_days(self):
        self.call("before", "complete", True, True, 0.9, day="2026-09-30")
        self.call("in", "complete", True, True, 0.9, day="2026-10-07")
        self.call("after", "complete", True, True, 0.9, day="2026-10-08")
        self.assertEqual(self.run_it()["rows"], 1)

    def test_a_work_card_excludes_the_row_and_taints_its_session(self):
        spaces = {"c-1": "work", "c-2": "personal"}
        work = {"space": "personal", "card": "c-1", "pinned": True, "hands_free": True}
        self.call("w", "complete", True, True, 0.9, facts=work)
        self.call("same-session", "complete", True, True, 0.9)
        self.call("later", "complete", True, True, 0.9, gap=20)
        mine = {"space": "", "card": "c-2", "pinned": True, "hands_free": True}
        self.call("pinned-mine", "complete", True, True, 0.9, facts=mine, gap=1)
        entry = self.run_it(space_of=lambda card: spaces.get(card, ""))["keys"][
            "preturn.complete"]
        self.assertEqual((entry["turns"], entry["personal"]), (4, 2))

    def test_the_page_in_the_work_space_excludes_its_session(self):
        self.call("a", "complete", True, True, 0.9,
                  facts={"space": "work", "card": "", "pinned": False, "hands_free": True})
        self.call("b", "complete", True, True, 0.9)
        self.assertEqual(self.run_it()["keys"]["preturn.complete"]["personal"], 0)

    def test_an_adapter_word_in_the_text_excludes_its_session(self):
        import re
        self.call("a", "complete", True, True, 0.9, text="ask about Zorblax today")
        self.call("b", "complete", True, True, 0.9)
        doc = self.run_it(words=[re.compile(r"\bZorblax\b", re.I)])
        self.assertEqual(doc["keys"]["preturn.complete"]["personal"], 0)

    def test_a_row_from_before_c552_counts_only_by_a_label(self):
        self.call("old", "complete", True, True, 0.9, facts=False)
        self.call("old-marked", "complete", True, True, 0.9, facts=False)
        self.labels({"old-marked": {"space": "personal", "complete": True}})
        entry = self.run_it()["keys"]["preturn.complete"]
        self.assertEqual((entry["personal"], entry["truthed"]), (1, 1))

    def test_a_connected_card_places_the_turn_when_the_facts_do_not(self):
        self.call("a", "card", "none", "c-1", 0.95,
                  facts={"space": "", "card": "", "pinned": False, "hands_free": True})
        self.outcome("a", "connected", card="c-1")
        entry = self.run_it(space_of=lambda card: "work")["keys"]["preturn.card"]
        self.assertEqual(entry["personal"], 0)


class VocabularyTest(unittest.TestCase):
    def test_it_reads_every_adapter_hearing_table_without_naming_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            table = Path(tmp) / "someone" / "hearing.json"
            table.parent.mkdir()
            table.write_text(json.dumps({"words": {"zorblax": {"said": "Zorblaxx",
                                                               "heard": "x"}}}))
            found = verdict.vocabulary(Path(tmp))
        self.assertTrue(any(p.search("the Zorblaxx thing") for p in found))
        self.assertTrue(any(p.search("zorblax") for p in found))

    def test_it_reads_the_packs_of_every_root_it_is_given(self):
        """c-722 landing B: an install's own pack is not under the code's `adapters/`, so the
        words come from every root a pack is found in (`packs.roots`)."""
        with tempfile.TemporaryDirectory() as tmp:
            for root, word in (("adapters", "zorblax"), ("install-packs", "quuxly")):
                table = Path(tmp) / root / "pack" / "hearing.json"
                table.parent.mkdir(parents=True)
                table.write_text(json.dumps({"words": {word: {"said": word.title(), "heard": "x"}}}))
            found = verdict.vocabulary(Path(tmp) / "adapters", Path(tmp) / "install-packs")
        for word in ("zorblax", "quuxly"):
            self.assertTrue(any(p.search(word) for p in found), word)


class VerbTest(unittest.TestCase):
    def test_since_runs_the_verdict_and_a_bad_date_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(Path(tmp))
            (cfg.state_dir / "voice").mkdir(parents=True, exist_ok=True)
            out = io.StringIO()
            with redirect_stdout(out):
                code = voice.judges(cfg, since="2026-10-01")
            self.assertEqual(code, 0)
            self.assertIn("window 2026-10-01 to 2026-10-07", out.getvalue())
            self.assertIn("preturn.bargein", out.getvalue())
            with redirect_stdout(io.StringIO()):
                self.assertEqual(voice.judges(cfg, since="next week"), 1)


if __name__ == "__main__":
    unittest.main()
