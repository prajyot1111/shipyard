"""`keel pack check <dir>` (c-735): a pack's own suite is run, and it must hold the pack to
the conformance contracts its capabilities call for (`keel/packkit/conformance.py`).

The packs here are scratch ones whose suites are a few lines, so the check itself is what
is held: what it runs, what it requires, and what it says. The packs that ship are held by
their own suites (each one's `test_conformance.py`).
"""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from keel import packcheck

STANDIN = """import unittest
from keel.packkit import standin
from keel.packkit.conformance import HostContract
from keel.packkit.layer import Repo


class Host(HostContract, unittest.TestCase):
    def host_layer(self):
        return standin

    def host_repo(self, name):
        return Repo(name, standin.BASE)

    def host_serve(self, world):
        standin.use(world)
"""
PASSING = "import unittest\n\n\nclass Plain(unittest.TestCase):\n    def test_it(self):\n        self.assertTrue(True)\n"
FAILING = PASSING.replace("assertTrue(True)", "assertTrue(False)")


class PackCheckTest(unittest.TestCase):
    def pack(self, toml: str, **tests: str) -> Path:
        made = tempfile.TemporaryDirectory(prefix="keel-packcheck-")
        self.addCleanup(made.cleanup)
        folder = Path(made.name) / "demo"
        (folder / "tests").mkdir(parents=True)
        (folder / "pack.toml").write_text('name = "demo"\nversion = "1"\ndescription = "d"\n' + toml)
        (folder / "providers").mkdir()
        for verb in ("publish", "publishable", "ship", "review", "providers/reviews"):
            (folder / verb).write_text("#!/bin/sh\n")
            (folder / verb).chmod(0o755)
        for name, text in tests.items():
            (folder / "tests" / f"{name}.py").write_text(text)
        return folder

    def test_a_pack_with_no_claim_needs_only_its_own_suite_to_pass(self):
        found = packcheck.check(self.pack("", test_plain=PASSING))
        self.assertEqual((found["ok"], found["ran"], found["missing"]), (True, 1, []))

    def test_a_failing_suite_fails_the_check(self):
        found = packcheck.check(self.pack("", test_plain=FAILING))
        self.assertEqual((found["ok"], found["failed"]), (False, 1))

    def test_a_code_host_must_hold_the_host_and_verbs_contracts_and_is_told_which_it_lacks(self):
        found = packcheck.check(self.pack("[capabilities]\ncodehost = true\n", test_conformance=STANDIN))
        self.assertEqual(found["contracts"], ["HostContract"])
        self.assertEqual((found["ok"], found["missing"]), (False, ["VerbsContract"]))
        self.assertIn("VerbsContract", found["said"])

    def test_a_suite_that_gives_no_answer_in_time_is_one_line(self):
        """r1.F7: the suite's clock running out is a verdict, never a traceback."""
        import subprocess
        from unittest import mock

        def never(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        with mock.patch.object(packcheck, "SECONDS", 7), mock.patch.object(packcheck.subprocess, "run", never):
            found = packcheck.check(self.pack("", test_plain=PASSING))
        self.assertEqual((found["ok"], found["said"]), (False, "its suite gave no answer in 7 seconds"))
        self.assertEqual(packcheck.line(found), "keel pack check: demo does not pass (0 tests)")

    def test_only_a_pack_that_claims_review_requests_must_hold_the_review_card_s_life(self):
        """r1.F1: a review card's life is `ReviewsContract`, asked of a pack that claims `reviews`."""
        found = packcheck.check(self.pack("[capabilities]\ncodehost = true\nreviews = true\n",
                                          test_conformance=STANDIN))
        self.assertEqual(found["missing"], ["VerbsContract", "ReviewsContract"])

    def test_the_verb_prints_one_line_and_exits_by_the_result(self):
        folder = self.pack("", test_plain=PASSING)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(packcheck.main([str(folder)]), 0)
        self.assertEqual(out.getvalue().strip().splitlines()[-1],
                         "keel pack check: demo passes (1 test; contracts held: none needed)")
        from keel import cli
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.keel_main(["pack", "check", str(folder)]), 0)


if __name__ == "__main__":
    unittest.main()
