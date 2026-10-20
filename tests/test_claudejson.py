"""A config dir's `.claude.json`: atomic writes, consent asserted, a corrupt file left alone.

Every path here is a temporary directory. No test names a real config dir."""

import json
import tempfile
import threading
import unittest
from pathlib import Path

from keel import claudejson, talker


# Big enough that a truncate-then-write is observable from another thread: the old
# `Path.write_text` left the file empty or half written for the length of the write.
BULK = {f"key{i}": "x" * 200 for i in range(400)}


class Reader(threading.Thread):
    """Parses the file in a loop until told to stop, and counts what it could not parse."""

    def __init__(self, path: Path):
        super().__init__(daemon=True)
        self.path, self.stop, self.torn, self.reads = path, threading.Event(), [], 0

    def run(self):
        while not self.stop.is_set():
            try:
                text = self.path.read_text()
            except FileNotFoundError:
                continue
            self.reads += 1
            try:
                json.loads(text)
            except ValueError:
                self.torn.append(len(text))


def hammer(path: Path, write, times: int = 150) -> Reader:
    reader = Reader(path)
    reader.start()
    try:
        for i in range(times):
            write(i)
    finally:
        reader.stop.set()
        reader.join(timeout=10)
    return reader


class AtomicWriteTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / ".claude.json"

    def test_a_reader_never_sees_a_partial_file(self):
        claudejson.write(self.path, BULK)
        reader = hammer(self.path, lambda i: claudejson.write(self.path, dict(BULK, n=i)))
        self.assertGreater(reader.reads, 0)
        self.assertEqual(reader.torn, [])

    def test_the_file_is_private_and_no_temporary_is_left(self):
        claudejson.write(self.path, {"a": 1})
        self.assertEqual(oct(self.path.stat().st_mode & 0o777), "0o600")
        self.assertEqual([p.name for p in self.dir.iterdir()], [".claude.json"])

    def test_seed_and_forget_are_atomic_too(self):
        """The two writers that ran while a live server had the file open (c-444)."""
        paths = talker.Paths(root=self.dir, state_dir=self.dir / "state")
        cj = paths.config_dir / ".claude.json"
        claudejson.write(cj, BULK)
        run = self.dir / "talker" / "home" / "7"

        def churn(i):
            talker.seed_claude_json(self.dir / "absent.json", cj, run)
            talker.forget_run(paths, run)

        reader = hammer(cj, churn, times=100)
        self.assertGreater(reader.reads, 0)
        self.assertEqual(reader.torn, [])
        self.assertEqual(json.loads(cj.read_text())["key3"], BULK["key3"])


class ConsentTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / ".claude.json"

    def test_a_config_missing_the_key_gets_it_and_keeps_everything_else(self):
        self.path.write_text(json.dumps({"oauthAccount": {"emailAddress": "x"},
                                         "hasUsedRemoteControl": True, "numStartups": 9}))
        self.assertTrue(claudejson.ensure_consent(self.path))
        data = json.loads(self.path.read_text())
        self.assertIs(data["remoteDialogSeen"], True)
        self.assertEqual(data["oauthAccount"], {"emailAddress": "x"})
        self.assertIs(data["hasUsedRemoteControl"], True)
        self.assertEqual(data["numStartups"], 9)

    def test_an_explicit_false_is_turned_true(self):
        """`setdefault` would have left this alone, which is why the seed never fixed it."""
        self.path.write_text(json.dumps({"remoteDialogSeen": False}))
        self.assertTrue(claudejson.ensure_consent(self.path))
        self.assertIs(json.loads(self.path.read_text())["remoteDialogSeen"], True)

    def test_already_there_is_not_rewritten(self):
        self.path.write_text('{"remoteDialogSeen": true}')
        before = self.path.stat().st_mtime_ns
        self.assertFalse(claudejson.ensure_consent(self.path))
        self.assertEqual(self.path.stat().st_mtime_ns, before)

    def test_no_file_is_created_with_the_key(self):
        self.assertTrue(claudejson.ensure_consent(self.path))
        self.assertEqual(json.loads(self.path.read_text()), {"remoteDialogSeen": True})

    def test_a_file_that_does_not_parse_is_refused_and_left_byte_for_byte(self):
        self.path.write_text('{"oauthAccount": {"emailAddress": "x"}, trunc')
        with self.assertRaises(claudejson.Unreadable):
            claudejson.ensure_consent(self.path)
        self.assertEqual(self.path.read_text(), '{"oauthAccount": {"emailAddress": "x"}, trunc')


if __name__ == "__main__":
    unittest.main()
