"""The judges' switch and their report: Keel's half (V10, c-313).

The gateway's half is the same rules in a different interpreter, so the effective-mode cases
come from `voice/harbor_voice/fixtures/judges_switch.json`, which `bin/keel-voice-selftest`
reads too. A rule that changes on one side and not the other fails here.

What is proved here, in the order it matters: the switch reads safe (a key nothing names is
`off`, `on` without a floor is held at `shadow`, a bad value is ignored), the verb refuses to
write the thing V10 forbids, a flip leaves a record, and the report counts agreement only
where Jev actually answered.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from keel import judges, voice
from tests.helpers import make_config

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "voice" / "harbor_voice" / "fixtures" / "judges_switch.json"


def toml_for(defaults: dict, floors: dict) -> str:
    """The two tables a `keel.toml` would carry, and nothing else: the reader must find them
    inside `[voice]` rather than at the top level."""
    lines = ["[voice]", 'port = 4390', "", "[voice.judges]"]
    lines += [f'"{key}" = "{mode}"' for key, mode in defaults.items()]
    lines += ["", "[voice.judge_floors]"]
    lines += [f'"{key}" = {value}' for key, value in floors.items()]
    return "\n".join(lines) + "\n"


class SwitchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.toml = self.dir / "keel.toml"
        self.state = self.dir / "state"
        (self.state / "voice").mkdir(parents=True)

    def write(self, defaults: dict, floors: dict | None = None, override: dict | None = None):
        self.toml.write_text(toml_for(defaults, floors or {}))
        if override is not None:
            (self.state / "voice" / judges.SWITCH_FILE).write_text(json.dumps(override))

    def table(self):
        return judges.effective(self.toml, self.state)


class FixtureTest(SwitchCase):
    """Every case in the shared fixture, which is the contract between the two readers."""

    def test_the_shared_cases(self):
        doc = json.loads(FIXTURE.read_text())
        self.assertTrue(doc["cases"], "the fixture has no cases")
        for case in doc["cases"]:
            with self.subTest(case["name"]):
                self.write(case["defaults"], case["floors"], case["override"])
                table = self.table()
                self.assertEqual(sorted(table), sorted(judges.KEYS))
                for key, want in case["expect"].items():
                    got = table[key]
                    for field, value in want.items():
                        self.assertEqual(got[field], value,
                                         f"{case['name']}: {key}.{field}")


class ReadingTest(SwitchCase):
    def test_a_missing_toml_and_a_missing_override_are_both_off_and_neither_raises(self):
        table = self.table()
        self.assertEqual({entry["mode"] for entry in table.values()}, {"off"})
        self.assertEqual({entry["from"] for entry in table.values()}, {"fallback"})

    def test_a_malformed_toml_is_off_rather_than_an_exception(self):
        self.toml.write_text("[voice.judges\nthis is not toml")
        self.assertEqual(self.table()["narrate"]["mode"], "off")

    def test_an_override_that_is_not_an_object_is_ignored(self):
        self.write({"narrate": "shadow"})
        (self.state / "voice" / judges.SWITCH_FILE).write_text('["narrate"]')
        self.assertEqual(self.table()["narrate"], {
            "mode": "shadow", "from": "default", "floor": None, "held": False, "asked": "shadow"})


class OverrideTest(SwitchCase):
    def test_writing_one_key_leaves_the_others_to_the_default(self):
        self.write({key: "shadow" for key in judges.KEYS})
        judges.write_override(self.state, "narrate", "off")
        table = self.table()
        self.assertEqual(table["narrate"]["mode"], "off")
        self.assertEqual(table["narrate"]["from"], "override")
        self.assertEqual(table["preturn.route"]["from"], "default")

    def test_clearing_hands_the_key_back_to_the_default(self):
        self.write({key: "shadow" for key in judges.KEYS})
        judges.write_override(self.state, "narrate", "off")
        judges.write_override(self.state, "narrate", None)
        self.assertEqual(self.table()["narrate"]["from"], "default")
        self.assertEqual(json.loads((self.state / "voice" / judges.SWITCH_FILE).read_text()), {})

    def test_it_refuses_a_key_or_a_mode_it_does_not_know(self):
        with self.assertRaises(judges.SwitchError):
            judges.write_override(self.state, "preturn.nonsense", "on")
        with self.assertRaises(judges.SwitchError):
            judges.write_override(self.state, "narrate", "loud")

    def test_no_reader_ever_sees_a_half_written_switch(self):
        """The write is a temp file and a rename, so the only two states a reader can find
        are the old file and the new one."""
        self.write({key: "shadow" for key in judges.KEYS})
        judges.write_override(self.state, "narrate", "off")
        leftovers = [p.name for p in (self.state / "voice").iterdir()
                     if p.name.endswith(".new")]
        self.assertEqual(leftovers, [])


class LogTest(SwitchCase):
    def line(self, **row):
        with (self.state / "voice" / judges.LOG_FILE).open("a") as out:
            out.write(json.dumps(row) + "\n")

    def call(self, turn, rule, jev, miss="", latency=0.4, judge="preturn", modes=None,
             real=True, facts=None):
        """A call line, and (unless `real` is False) the transcript line that makes its
        turn one that happened: the report counts only those (c-552)."""
        self.line(at="2026-09-20T10:00:00+0000", turn=turn, judge=judge,
                  modes=modes or {name: "shadow" for name in rule},
                  text=f"said in {turn}", rule=rule, jev=jev, latency=latency, miss=miss,
                  decided_by={name: "rule" for name in rule},
                  **({"facts": facts} if facts is not None else {}))
        if real:
            with (self.state / "voice" / judges.TRANSCRIPT_FILE).open("a") as out:
                out.write(json.dumps({"kind": "said", "turn": turn, "said": "x"}) + "\n")

    def test_the_three_kinds_of_line_are_read_apart(self):
        self.call("t-1", {"complete": True}, {"complete": {"value": True, "confidence": 0.9}})
        self.line(kind="outcome", turn="t-1", outcome="carried-on")
        judges.log_flip(self.state, "narrate",
                        {"mode": "shadow", "from": "default"},
                        {"mode": "off", "from": "override"})
        calls, outcomes, flips = judges.read_log(self.state)
        self.assertEqual(len(calls), 1)
        self.assertEqual(outcomes, {"t-1": "carried-on"})
        self.assertEqual(len(flips), 1)
        self.assertEqual(flips[0]["key"], "narrate")
        self.assertIn("@", flips[0]["by"])

    def test_a_line_that_is_not_json_is_skipped_rather_than_fatal(self):
        (self.state / "voice" / judges.LOG_FILE).write_text("{not json\n")
        self.call("t-2", {"complete": True}, {})
        calls, _outcomes, _flips = judges.read_log(self.state)
        self.assertEqual(len(calls), 1)

    def test_agreement_is_counted_only_where_jev_actually_answered(self):
        """A miss is an absence, not a disagreement. Counting it as either would flatter or
        damn the model, which is the one thing the evidence for a flip must not do."""
        self.call("t-1", {"complete": True}, {"complete": {"value": True, "confidence": 0.9}})
        self.call("t-2", {"complete": True}, {"complete": {"value": False, "confidence": 0.8}})
        self.call("t-3", {"complete": True}, {}, miss="timeout")
        calls, _outcomes, _flips = judges.read_log(self.state)
        entry = judges.per_key(calls)["preturn.complete"]
        self.assertEqual(entry["calls"], 3)
        self.assertEqual(entry["answered"], 2)
        self.assertEqual(entry["agreed"], 1)
        self.assertEqual(entry["misses"], {"timeout": 1})

    def test_one_call_line_feeds_every_key_it_was_asked_under(self):
        self.call("t-1", {"complete": True, "addressed": True, "route": "talk"},
                  {"complete": {"value": True, "confidence": 0.9}})
        calls, _outcomes, _flips = judges.read_log(self.state)
        tally = judges.per_key(calls)
        self.assertEqual(tally["preturn.complete"]["calls"], 1)
        self.assertEqual(tally["preturn.route"]["calls"], 1)
        self.assertEqual(tally["narrate"]["calls"], 0)


    def test_disagreements_are_newest_first_capped_and_carry_the_outcome(self):
        for i in range(4):
            self.call(f"t-{i}", {"complete": True},
                      {"complete": {"value": False, "confidence": 0.9}})
        self.line(kind="outcome", turn="t-3", outcome="barged-in")
        calls, outcomes, _flips = judges.read_log(self.state)
        found = judges.disagreements(calls, outcomes, limit=2)
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0]["turn"], "t-3")
        self.assertEqual(found[0]["outcome"], "barged-in")
        self.assertEqual(found[1]["outcome"], "unknown")


    def test_a_call_with_no_transcript_turn_is_skipped_and_counted(self):
        """c-542's residue: 16 narrate rows on the live log came from a selftest, with no
        turn behind them, and the report counted them as calls (c-552)."""
        self.write({key: "shadow" for key in judges.KEYS})
        self.call("t-1", {"narrate": True}, {"narrate": {"value": False, "confidence": 0.7}},
                  judge="narrate")
        for i in range(3):
            self.call(f"ghost-{i}", {"narrate": True},
                      {"narrate": {"value": False, "confidence": 0.9}}, judge="narrate",
                      latency=0.05, real=False)
        text = "\n".join(judges.report(self.toml, self.state))
        narrate = [line for line in text.splitlines() if line.startswith("narrate ")][-1]
        self.assertEqual(narrate.split()[1], "1")
        self.assertIn("skipped 3 call rows with no transcript turn", text)

    def test_words_are_printed_only_for_a_turn_shown_personal(self):
        """c-552: 'no work turn's words in any output'. The page in the work space, a
        pinned card this report cannot place, and a line with no facts all withhold."""
        self.write({key: "shadow" for key in judges.KEYS})
        disagree = {"complete": {"value": False, "confidence": 0.95}}
        self.call("mine", {"complete": True}, disagree,
                  facts={"space": "personal", "card": ""})
        self.call("work-page", {"complete": True}, disagree,
                  facts={"space": "work", "card": ""})
        self.call("pinned", {"complete": True}, disagree,
                  facts={"space": "personal", "card": "c-9"})
        self.call("old", {"complete": True}, disagree)
        text = "\n".join(judges.report(self.toml, self.state))
        self.assertIn("said in mine", text)
        for turn in ("work-page", "pinned", "old"):
            self.assertNotIn(f"said in {turn}", text)
            self.assertIn(f"turn {turn} (words withheld", text)


class VerbTest(unittest.TestCase):
    """`keel voice judge` and `keel voice judges`: the mechanisms behind V10's sentences."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.cfg.source = self.dir / "keel.toml"
        (self.dir / "state" / "voice").mkdir(parents=True, exist_ok=True)
        self.cfg.source.write_text(toml_for({key: "shadow" for key in judges.KEYS}, {}))

    def run_verb(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            if argv[0] == "judges":
                code = voice.judges(self.cfg)
            else:
                code = voice.judge(self.cfg, argv[1], argv[2])
        return code, out.getvalue()

    def test_on_is_refused_while_the_key_has_no_floor(self):
        """V10: nothing flips itself, and no floor is set until B0's number is recorded and
        the report has been read. A verb that refuses is that sentence as a mechanism."""
        code, said = self.run_verb("judge", "preturn.route", "on")
        self.assertEqual(code, 1)
        self.assertIn("no confidence floor", said)
        self.assertIn("judge_floors", said)
        self.assertFalse((self.cfg.state_dir / "voice" / judges.SWITCH_FILE).exists())

    def test_on_is_written_once_a_floor_exists(self):
        self.cfg.source.write_text(toml_for({key: "shadow" for key in judges.KEYS},
                                            {"preturn.route": 0.99}))
        code, said = self.run_verb("judge", "preturn.route", "on")
        self.assertEqual(code, 0)
        self.assertIn("shadow (default) -> on (override)", said)
        self.assertIn("no restart", said)


    def test_a_flip_leaves_a_line_in_the_log_and_a_no_op_does_not(self):
        self.run_verb("judge", "narrate", "off")
        _calls, _outcomes, flips = judges.read_log(self.cfg.state_dir)
        self.assertEqual(len(flips), 1)
        code, said = self.run_verb("judge", "narrate", "off")
        self.assertEqual(code, 0)
        self.assertIn("unchanged", said)
        _calls, _outcomes, flips = judges.read_log(self.cfg.state_dir)
        self.assertEqual(len(flips), 1, "an unchanged flip must not be recorded as one")


if __name__ == "__main__":
    unittest.main()
