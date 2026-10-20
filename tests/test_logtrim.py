"""Log upkeep: a log past its size is copied aside and cut back to its tail, in place."""

import tempfile
import unittest
from pathlib import Path

from keel import logtrim


class TrimTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.logs = Path(scratch.name)

    def lines(self, count: int) -> bytes:
        return b"".join(b"line %04d\n" % index for index in range(count))

    def test_a_log_past_its_size_keeps_its_tail_and_the_whole_of_it_goes_aside(self):
        log = self.logs / "drain.log"
        log.write_bytes(self.lines(1000))                       # 10 bytes a line
        self.assertEqual(logtrim.trim(self.logs, max_bytes=5000, keep=95), ["drain.log"])
        self.assertEqual((self.logs / "drain.log.1").read_bytes(), self.lines(1000))
        kept = log.read_bytes()
        self.assertEqual(kept, self.lines(1000)[-90:], "the tail starts on a line boundary")
        self.assertTrue(kept.endswith(b"line 0999\n"))


    def test_a_service_that_holds_the_log_open_keeps_writing_at_the_new_end(self):
        """launchd and systemd hold a service's stderr open in append mode for as long as
        it runs. After a cut its next write must land after the tail, not at the old
        offset with a hole of zero bytes before it."""
        log = self.logs / "keel.err.log"
        log.write_bytes(self.lines(1000))
        with open(log, "ab", buffering=0) as held:
            logtrim.trim(self.logs, max_bytes=5000, keep=95)
            held.write(b"written after the cut\n")
        self.assertEqual(log.read_bytes(), self.lines(1000)[-90:] + b"written after the cut\n")

    def test_the_older_generation_is_replaced_not_stacked(self):
        log = self.logs / "drain.log"
        for _ in range(2):
            log.write_bytes(self.lines(1000))
            logtrim.trim(self.logs, max_bytes=5000, keep=95)
        self.assertEqual(sorted(path.name for path in self.logs.iterdir()),
                         ["drain.log", "drain.log.1"])

    def test_only_logs_are_touched(self):
        other = self.logs / "voice-session.json"
        other.write_bytes(self.lines(1000))
        self.assertEqual(logtrim.trim(self.logs, max_bytes=5000), [])
        self.assertEqual(other.read_bytes(), self.lines(1000))


if __name__ == "__main__":
    unittest.main()
