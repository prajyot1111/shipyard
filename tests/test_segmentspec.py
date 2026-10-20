"""What a segment's segment.md may say (keel/segmentspec.py, c-634): every shipped segment
passes, each bad frontmatter is refused with its reason, and `keel doctor` reports a
failing segment as a problem while the fetch role is left to run it."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from keel import segmentspec

ROOT = Path(__file__).resolve().parent.parent
GOOD = "---\nname: {name}\nspace: personal\ncadence: hourly\n---\n\n# {name}\n"


class SegmentSpecTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def segment(self, spec: str | None, name: str = "alpha", files=("fetch.py",)) -> Path:
        directory = self.root / name
        directory.mkdir()
        if spec is not None:
            (directory / "segment.md").write_text(spec.format(name=name))
        for part in files:
            (directory / part).parent.mkdir(parents=True, exist_ok=True)
            (directory / part).write_text("")
        return directory

    def test_every_shipped_segment_passes(self):
        for directory in sorted((ROOT / "segments").iterdir()):
            if directory.is_dir() and not directory.name.startswith((".", "_")):
                self.assertEqual(segmentspec.check(directory, ["personal", "work"]), [], directory.name)

    def test_a_good_one_passes_with_each_optional_key(self):
        spec = GOOD.replace("---\n\n", "card-span: 2\nlogins: google-tts   # a note\n---\n\n")
        self.assertEqual(segmentspec.check(self.segment(spec), ["personal"]), [])

    def test_each_bad_frontmatter_is_refused_with_its_reason(self):
        cases = {
            None: "it has no segment.md",
            GOOD.replace("name: {name}", "name: beta"): "name is beta, and the directory is",
            GOOD.replace("space: personal", "space: home"): "space home is not a space here",
            GOOD.replace("space: personal\n", ""): "space is missing",
            GOOD.replace("cadence: hourly", "cadence: weekly"): "cadence weekly is not one of",
            GOOD.replace("---\n\n", "card-span: wide\n---\n\n"): "card-span wide is not a whole number",
            GOOD.replace("---\n\n", "card-span: 9\n---\n\n"): "card-span 9 is not a whole number",
            GOOD.replace("---\n\n", "colour: red\n---\n\n"): "colour is not a segment.md key",
        }
        for index, (spec, said) in enumerate(cases.items()):
            problems = segmentspec.check(self.segment(spec, f"s{index}"), ["personal"])
            self.assertTrue(any(said in problem for problem in problems), (said, problems))

    def test_nothing_to_look_at_is_a_problem_and_an_app_or_a_service_is_enough(self):
        self.assertIn("there is nothing to look at", segmentspec.check(
            self.segment(GOOD, "bare", files=()), ["personal"])[0])
        self.assertEqual(segmentspec.check(self.segment(GOOD, "app", files=("app/index.html",)), ["personal"]), [])
        self.assertEqual(segmentspec.check(self.segment(GOOD, "svc", files=("service.json",)), ["personal"]), [])

    def test_doctor_reports_a_failing_segment_and_the_first_root_wins(self):
        from keel import doctor
        self.segment(GOOD, "alpha")
        self.segment(GOOD.replace("cadence: hourly", "cadence: weekly"), "beta")
        later = tempfile.TemporaryDirectory()
        self.addCleanup(later.cleanup)
        other = Path(later.name)
        (other / "alpha").mkdir()       # a second alpha, behind the first root: not read
        (other / "gamma").mkdir()       # no segment.md at all
        cfg = SimpleNamespace(segment_roots=[self.root, other], spaces={"personal": None})
        found = segmentspec.report(cfg)
        self.assertEqual(sorted(found), ["alpha", "beta", "gamma"])
        self.assertEqual(found["alpha"], [])
        report = {"config": {"ok": True}, "claude": {"ok": True}, "segments": found}
        problems = doctor.problems(report)
        self.assertIn("segment beta: cadence weekly is not one of hourly, daily, none", problems)
        self.assertIn("segments      3, 2 with problems: beta, gamma", segmentspec.line(found))


if __name__ == "__main__":
    unittest.main()
