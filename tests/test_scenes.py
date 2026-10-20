"""`demo/scenes/`: the demo's scene files, and the recorder's sweep and index (c-570).

No browser and no sandbox here: the recorder's pure parts (the sweep, the index, the filling
of `{{key}}`) are held directly, and every scene file is put through the same checker the
engine runs before a browser starts (`bin/keel-browser-steps.js`, with a bare node).
"""

import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from tests.helpers import ROOT

SCENES = ROOT / "demo" / "scenes"
STEPS = ROOT / "bin" / "keel-browser-steps.js"
NODE = shutil.which("node")
PHONE = {"02", "06", "07", "10"}


def load(name: str):
    loader = importlib.machinery.SourceFileLoader(f"scenes_{name}", str(SCENES / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


record = load("record")
harbor = load("harbor")


def scene_files() -> list[Path]:
    return sorted(SCENES.glob("[0-9][0-9]-*.json"))


class SceneFilesTest(unittest.TestCase):

    @unittest.skipUnless(NODE, "node is not on PATH")
    def test_every_scene_passes_the_checker_the_engine_runs_first(self):
        for path in scene_files():
            with self.subTest(scene=path.name):
                text = re.sub(r"\{\{[a-z_]+\}\}", "c-9999", path.read_text())
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                    f.write(text)
                self.addCleanup(os.unlink, f.name)
                done = subprocess.run([NODE, str(STEPS), f.name], capture_output=True, text=True, timeout=30)
                self.assertEqual(done.returncode, 0, done.stderr)

    def test_no_scene_types_an_em_dash_or_names_a_machine(self):
        for path in [*scene_files(), SCENES / "harbor-memory.md"]:
            with self.subTest(file=path.name):
                text = path.read_text()
                self.assertNotIn("\u2014", text)
                self.assertNotRegex(text, r"127\.0\.0\.1|localhost|:\d{4}/|/home/")


class SweepTest(unittest.TestCase):
    def test_a_hit_is_named_by_where_and_the_term_number_never_the_words(self):
        patterns = [re.compile("acme", re.I), re.compile(r"wid(g|j)et", re.I)]
        hits = record.sweep_texts({"step 01-a": "nothing here", "harbor 01.txt": "the ACME widget"}, patterns)
        self.assertEqual(hits, [{"in": "harbor 01.txt", "term": 1}, {"in": "harbor 01.txt", "term": 2}])
        self.assertNotIn("acme", json.dumps(hits).lower())

    def test_a_take_sweeps_its_page_text_and_its_harbor_answers(self):
        take = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, take, True)
        (take / "clip.timeline.json").write_text(json.dumps({"steps": [{"key": "01-a", "text": "page words"}]}))
        (take / "harbor").mkdir()
        (take / "harbor" / "01.txt").write_text("his answer")
        self.assertEqual(record.take_texts(take), {"step 01-a": "page words", "harbor 01.txt": "his answer"})

    def test_this_machines_paths_are_a_hit_too(self):
        """Bosun's Logins panel prints config paths: scene 9's first takes showed it and swept
        clean against the word list alone."""
        text = "missing: no login in /home/someone/keel/spaces/harbor/.claude"
        hits = record.sweep_texts({"step 05-x": text, "step 06-y": "Deploy next to main?"}, record.MACHINE, "machine")
        self.assertTrue(hits)
        self.assertEqual({h["in"] for h in hits}, {"step 05-x"})

    def test_a_sweep_refuses_an_empty_word_list_and_a_take_with_nothing_to_read(self):
        take = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, take, True)
        empty = take / "terms"
        empty.write_text("# only a comment\n")
        with unittest.mock.patch.object(record, "TERMS", empty), self.assertRaises(record.RecordError):
            record.sweep(take)
        with unittest.mock.patch.object(record, "terms", lambda: [re.compile("acme", re.I)]):
            self.assertFalse(record.sweep(take)["clean"], "a take with no timeline and no answers read nothing")

    def test_the_spoken_answer_is_swept_as_well_as_the_written_one(self):
        """The page shows `written` and the audio says `answer`; they differ when Harbor drew."""
        take = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, take, True)
        (take / "harbor").mkdir()
        (take / "harbor" / "01.txt").write_text("what the page shows")
        (take / "harbor" / "01.said.txt").write_text("what he hears")
        self.assertEqual(set(record.take_texts(take)), {"harbor 01.txt", "harbor 01.said.txt"})

    def test_the_word_list_is_there_so_a_sweep_can_fail(self):
        """A sweep with no terms passes anything, so the recorder refuses one. Where no pack
        in the tree carries a list (c-722: an owner's pack lives in the install), there is
        nothing to sweep for, and the refusal above is what stands."""
        if not list(record.TERMS.glob("*/drift-terms")):
            self.skipTest("no pack in this tree carries a drift-terms list")
        self.assertTrue(record.terms(), "a drift-terms list with no term in it")


class IndexTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)

    def entry(self, take: str, ok=True, clean=True) -> dict:
        return {"take": take, "ok": ok, "sweep": {"clean": clean, "hits": []}}

    def test_the_first_clean_take_is_kept_and_a_later_one_only_when_asked(self):
        record.record_entry(self.home, "04-start", self.entry("take-1", clean=False))
        row = record.record_entry(self.home, "04-start", self.entry("take-2"))
        self.assertEqual(row["kept"], "take-2")
        row = record.record_entry(self.home, "04-start", self.entry("take-3"))
        self.assertEqual(row["kept"], "take-2")
        self.assertEqual(record.keep(self.home, "04-start", "take-3")["kept"], "take-3")

    def test_a_failed_or_dirty_take_can_never_be_the_kept_one(self):
        record.record_entry(self.home, "05-plan", self.entry("take-1", ok=False))
        record.record_entry(self.home, "05-plan", self.entry("take-2", clean=False))
        for take in ("take-1", "take-2"):
            with self.subTest(take=take), self.assertRaises(record.RecordError):
                record.keep(self.home, "05-plan", take)
        self.assertIsNone(record.load_index(self.home)["scenes"]["05-plan"]["kept"])

    def test_a_kept_take_that_resweeps_dirty_hands_over_or_is_dropped(self):
        record.record_entry(self.home, "02-checkin", self.entry("take-1"))
        record.record_entry(self.home, "02-checkin", self.entry("take-2"))
        row = record.record_entry(self.home, "02-checkin", self.entry("take-1", clean=False))
        self.assertEqual(row["kept"], "take-2")
        row = record.record_entry(self.home, "02-checkin", self.entry("take-2", clean=False))
        self.assertIsNone(row["kept"])

    def test_a_scene_where_harbor_speaks_waits_for_his_text(self):
        """The clip is swept before `harbor capture` writes his answers, so it cannot be kept
        on the page's text alone."""
        waiting = dict(self.entry("take-1"), speaks=True, harbor=None)
        self.assertIsNone(record.record_entry(self.home, "06-journey", waiting)["kept"])
        captured = dict(waiting, harbor=[{"n": 1, "engine": "google"}])
        self.assertEqual(record.record_entry(self.home, "06-journey", captured)["kept"], "take-1")

    def test_a_run_that_exited_badly_is_not_ok(self):
        take = self.home / "t"
        take.mkdir()
        entry = record.entry_of(take, {"seed": "morning"}, 3)
        self.assertFalse(entry["ok"])
        self.assertIn("exited 3", entry["failed"])

    def test_a_resweep_replaces_the_takes_row_rather_than_adding_one(self):
        record.record_entry(self.home, "02-checkin", self.entry("take-1", clean=False))
        row = record.record_entry(self.home, "02-checkin", self.entry("take-1"))
        self.assertEqual(len(row["takes"]), 1)
        self.assertEqual(row["kept"], "take-1")


class CaptureTest(unittest.TestCase):
    def test_each_turn_in_the_window_once_with_its_last_line(self):
        path = Path(tempfile.mkdtemp()) / "transcript.jsonl"
        self.addCleanup(shutil.rmtree, path.parent, True)
        rows = [{"at": 5, "turn": "early", "answer": "before the take"},
                {"at": 11, "turn": "a", "answer": "half"},
                {"at": 12, "turn": "a", "answer": "half and the rest"},
                {"at": 13, "turn": "", "kind": "presence"},
                {"at": 14, "turn": "b", "answer": "second"},
                {"at": 40, "turn": "late", "answer": "after it"}]
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
        found = harbor.answers_in(path, 10, 30)
        self.assertEqual([(r["turn"], r["answer"]) for r in found], [("a", "half and the rest"), ("b", "second")])

    def test_the_voice_is_the_one_the_page_says_spoke(self):
        timeline = {"steps": [{"text": "Harbor · 8s · Google"}, {"text": "the needs you page"}]}
        self.assertEqual(harbor.live_engine(timeline), "google")
        self.assertEqual(harbor.live_engine({"steps": [{"text": "Harbor · 5s · Kokoro"}]}), "kokoro-onnx")
        self.assertEqual(harbor.live_engine({"steps": [{"text": "no provenance"}]}), "")


class HarborCaptureTest(unittest.TestCase):
    """`capture` end to end, with the engines stubbed: both texts written, the voice pinned
    to the one the page names, and no audio at all when the page names none."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.take = self.home / "recordings" / "06-journey" / "take-1"
        self.take.mkdir(parents=True)
        self.state = self.home / "voice"
        self.state.mkdir()
        (self.state / "transcript.jsonl").write_text(json.dumps(
            {"at": 102, "turn": "t1", "answer": "said aloud", "written": "said aloud, and drawn"}) + "\n")
        self.config = type("Config", (), {"DATA": self.state})
        self.spoke = []
        fake = lambda text, out, only="": self.spoke.append((text, only)) or {"engine": only, "wav": out.name}  # noqa: E731
        patcher = unittest.mock.patch.object(harbor, "synthesize", fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def timeline(self, provenance: str) -> None:
        (self.take / "clip.timeline.json").write_text(json.dumps(
            {"t0_epoch": 100, "duration": 10, "steps": [{"text": provenance}]}))

    def test_both_texts_are_written_and_the_voice_is_the_live_one(self):
        self.timeline("Harbor · 9s · Google")
        kept = harbor.capture(self.home, "06", "take-1", self.config)
        self.assertEqual((self.take / "harbor" / "01.txt").read_text().strip(), "said aloud, and drawn")
        self.assertEqual((self.take / "harbor" / "01.said.txt").read_text().strip(), "said aloud")
        self.assertEqual(self.spoke, [("said aloud", "google")])
        self.assertEqual((kept[0]["live"], kept[0]["engine"]), ("google", "google"))

    def test_a_page_that_names_no_voice_gets_no_audio(self):
        self.timeline("Harbor · 9s · browser")
        with self.assertRaises(SystemExit):
            harbor.capture(self.home, "06", "take-1", self.config)
        self.assertEqual(self.spoke, [])


class HarborFenceTest(unittest.TestCase):
    def test_the_sandbox_harbor_is_denied_the_live_state_and_the_machines_sessions(self):
        deny = harbor.fence(Path("/home/someone/keel"))["permissions"]["deny"]
        for rule in ("Read(//home/someone/keel/state/**)", "Bash(claude agents*)", "Bash(*KEEL_CONFIG=*)",
                     "Bash(*KEEL_LIVE_STATE*)"):
            self.assertIn(rule, deny)


class FillTest(unittest.TestCase):
    def test_every_key_is_filled_or_the_take_is_refused(self):
        self.assertEqual(record.filled('{"start": "/plan/{{card}}"}', {"card": "c-9211"}), '{"start": "/plan/c-9211"}')
        with self.assertRaisesRegex(record.RecordError, "--set for: card"):
            record.filled('{"start": "/plan/{{card}}"}', {})

    def test_the_recorder_refuses_outside_the_sandbox(self):
        with self.assertRaisesRegex(record.RecordError, "demo/sandbox/run"):
            record.sandbox()


if __name__ == "__main__":
    unittest.main()
