"""ghosts: a row the harness lists as working with no process is a doctor problem (r-26).

c-561's superseded session 735f0cab, as 2.1.284 listed it on 2026-09-29: `state: working`,
no `status`, no `pid`, two days after its house stopped. Its landing was refused four times
and nothing on any surface named the row.
"""

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from keel import doctor, ghosts, harness, housejobs
from tests.helpers import make_config

GHOST = {"id": "735f0cab", "cwd": "/w/c-561", "kind": "background", "startedAt": 1,
         "sessionId": "735f0cab-f0ec-45c1-ae5d-375b33475509", "name": "c-561", "state": "working"}
LIVE = {"pid": 2933011, "id": "8174226b", "kind": "background", "name": "c-581",
        "sessionId": "8174226b-24a1-4fb2-822f-d6ebdf5651b2", "status": "busy", "state": "working"}
IDLE_JOB = {"pid": 2484851, "id": "e1585ad7", "kind": "background", "name": "c-576",
            "sessionId": "e1585ad7-560b-4b49-9ecd-9188b5a2dc12", "status": "busy", "state": "done"}


class GhostsCase(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = make_config(Path(tmp.name))

    def gathered(self, rows):
        with mock.patch.object(ghosts.harness, "agents", lambda config_dir, strict=False: list(rows)):
            return ghosts.gather(self.cfg)


class RuleTest(unittest.TestCase):
    def test_the_one_rule_reads_the_three_rows_seen_live(self):
        self.assertFalse(housejobs.working(GHOST))
        self.assertTrue(housejobs.ghost(GHOST))
        self.assertTrue(housejobs.working(LIVE))
        self.assertFalse(housejobs.ghost(LIVE))
        self.assertFalse(housejobs.working(IDLE_JOB))
        self.assertFalse(housejobs.ghost(IDLE_JOB))


class GatherTest(GhostsCase):
    def test_one_problem_per_ghost_naming_its_card(self):
        found = self.gathered([GHOST, LIVE, IDLE_JOB])
        self.assertEqual([row["card"] for row in found["rows"]], ["c-561"])
        problems = ghosts.problems(found)
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("c-561: the harness lists 735f0cab"))
        self.assertIn("claude stop 735f0cab", problems[0])
        self.assertEqual(ghosts.line(found), "ghost houses  1: c-561")

    def test_a_config_dir_two_spaces_share_is_asked_once(self):
        shared = self.cfg.spaces["personal"].config_dir
        for space in self.cfg.spaces.values():
            space.config_dir = shared
        found = self.gathered([GHOST])
        self.assertEqual(len(found["rows"]), 1)


    def test_a_listing_that_fails_is_unknown_not_healthy(self):
        def failing(config_dir, strict=False):
            raise harness.HarnessError("claude agents exited 1")
        with mock.patch.object(ghosts.harness, "agents", failing):
            found = ghosts.gather(self.cfg)
        self.assertIn("unknown", ghosts.line(found))

    def test_a_missing_claude_is_unknown_and_never_a_traceback(self):
        """The doctor reports a missing binary on its own line; this one must not crash it."""
        for error in (FileNotFoundError("claude"), subprocess.TimeoutExpired("claude", 5)):
            with self.subTest(error=type(error).__name__):
                def failing(config_dir, strict=False, error=error):
                    raise error
                with mock.patch.object(ghosts.harness, "agents", failing):
                    found = ghosts.gather(self.cfg)
                self.assertIn("unknown", ghosts.line(found))
                self.assertEqual(ghosts.problems(found), [])

    def test_the_doctor_counts_it_as_a_problem(self):
        report = {"config": {"ok": True}, "claude": {"ok": True}, "ghosts": self.gathered([GHOST])}
        self.assertTrue(any(line.startswith("c-561: the harness lists") for line in doctor.problems(report)))


if __name__ == "__main__":
    unittest.main()
