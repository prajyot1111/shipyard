"""`bin/keel-backup`'s md5 (c-724): the proof of every object the backup writes.

The tool takes a file's md5 from the system's own tool where there is one, since a run
asks for dozens and a Python started for each was a quarter of a slim's time. That makes
the system tool part of the proof, so: it is used only when it proves itself on
`/dev/null`; whatever ran, a digest is 32 lower-case hex characters or it is nothing; and
two digests are the same only when both are digests (`same_md5`), so an empty string never
"equals" an empty string.

The end-to-end tests run the real tool on the slim tests' scratch store, home and keys
(`tests/backupslimcase.py`) with a `PATH` whose `md5sum` and `md5` are stand-ins that
misbehave. The unit tests read the tool's own md5 block, between its two marker comments,
and call its functions.
"""

import hashlib
import os
import subprocess
import unittest

from tests.backupslimcase import OLD, SlimCase, TOOL

EMPTY = "d41d8cd98f00b204e9800998ecf8427e"


def md5_block() -> str:
    text = TOOL.read_text()
    return text[text.index("# md5: begin"):text.index("# md5: end")]


class BrokenToolCase(SlimCase):
    def shims(self, body: str) -> str:
        """A PATH whose `md5sum` and `md5` are this script, ahead of everything else."""
        bin_dir = self.root / "md5-shims"
        bin_dir.mkdir(exist_ok=True)
        for name in ("md5sum", "md5"):
            (bin_dir / name).write_text("#!/bin/bash\n" + body + "\n")
            (bin_dir / name).chmod(0o755)
        return f"{bin_dir}{os.pathsep}{os.environ['PATH']}"


class FallBackTest(BrokenToolCase):
    """A system tool that does not prove itself is not used: the run goes by Python (or
    by a tool further down the list that does prove itself), and its proofs are real."""

    def snapshot_is_proven(self, body: str) -> None:
        self.old_tree(self.live)
        took = self.tool("snapshot", PATH=self.shims(body))
        self.assertEqual(took.returncode, 0, took.stdout + took.stderr)
        self.assertEqual(len(self.snapshots()), 1)
        key, md5 = next(iter(self.snapshots().items()))
        listing = (self.home / "work" / "keel" / "listing.tsv")
        if listing.exists():
            self.assertIn(md5, listing.read_text(), "what it listed is the object's real md5")
        self.assertEqual(self.tool("verify", "--set", "keel").returncode, 0)

    def test_a_tool_that_prints_nothing_is_not_used(self):
        self.snapshot_is_proven("cat > /dev/null")

    def test_a_tool_that_prints_something_else_is_not_used(self):
        self.snapshot_is_proven("cat > /dev/null; echo 'usage: md5 [-pqrtx]'")

    def test_a_tool_that_fails_is_not_used(self):
        self.snapshot_is_proven("cat > /dev/null; exit 3")

    def test_a_tool_that_says_one_digest_for_everything_is_not_used(self):
        """The red case. The one comparison with the tool's word on BOTH sides and no
        journal to ask: `--purge --unproven` removes an object that is, byte for byte, what
        the snapshot's own name holds. A tool that gives one answer for every file made
        any object that, and the only copy of an original went."""
        self.old_store(OLD)
        other = self.store / "slim-old" / "keel" / f"{OLD}.tar.gz.gpg"
        other.parent.mkdir(parents=True)
        other.write_bytes(b"the only copy of some snapshot's original")
        before = self.objects()
        done = self.tool("slim", "--purge", "--unproven", OLD, "--set", "keel",
                         PATH=self.shims("cat > /dev/null; echo ffffffffffffffffffffffffffffffff"))
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)


class BreaksLaterTest(BrokenToolCase):
    """A tool that proved itself and then stops giving digests: nothing it says after
    that is a digest, so nothing is proven by it."""

    def later(self, then: str) -> str:
        # The empty file's md5 for no bytes, as the real tool gives; `then` for any others.
        return self.shims('data="$(cat | head -c 1 | wc -c)"\n'
                          f'if [ "$data" -eq 0 ]; then echo {EMPTY}; else {then}; fi')

    def test_a_snapshot_is_not_counted_proven_when_the_digest_tool_is_broken(self):
        for then in ("true", "echo not-a-digest", "exit 1"):
            with self.subTest(then=then):
                self.reset()
                self.old_tree(self.live)
                took = self.tool("snapshot", PATH=self.later(then))
                self.assertNotEqual(took.returncode, 0, took.stdout + took.stderr)
                self.assertNotIn("proven by md5", took.stdout + took.stderr)
                self.assertFalse((self.store / "sets" / "keel" / "latest.json").exists(),
                                 "no commit point names a snapshot nobody proved")


class Md5UnitTest(unittest.TestCase):
    def call(self, script: str, **env) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", "-c", 'PY=python3\n' + md5_block() + "\n" + script],
                              capture_output=True, text=True, env=dict(os.environ, **env))

    def test_a_file_gives_its_md5_and_an_unreadable_or_missing_one_gives_nothing(self):
        if os.geteuid() == 0:
            self.skipTest("root reads every file")
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            good, sealed = os.path.join(tmp, "good"), os.path.join(tmp, "sealed")
            with open(good, "wb") as handle:
                handle.write(b"some bytes\n" * 1000)
            with open(sealed, "wb") as handle:
                handle.write(b"x")
            os.chmod(sealed, 0)
            want = hashlib.md5(b"some bytes\n" * 1000).hexdigest()
            for tool in ("", "python"):                  # the system's own, and Python's
                with self.subTest(tool=tool or "the system's"):
                    force = f'MD5_TOOL={tool}\n' if tool else ""
                    done = self.call(force + f'md5_of "{good}"; echo "rc=$?"; md5_of "{sealed}"; echo "rc=$?"; '
                                             f'md5_of "{tmp}/none"; echo "rc=$?"')
                    self.assertEqual(done.stdout.split(), [want, "rc=0", "rc=1", "rc=1"], done.stderr)

    def test_two_digests_are_the_same_only_when_both_are_digests(self):
        cases = {(EMPTY, EMPTY): 0, ("", ""): 1, (EMPTY, ""): 1, ("", EMPTY): 1, ("x", "x"): 1,
                 (EMPTY, EMPTY.upper()): 1, (EMPTY, EMPTY[:-1] + "f"): 1, (EMPTY + "\n" + EMPTY, EMPTY): 1}
        for (one, two), want in cases.items():
            with self.subTest(one=one, two=two):
                done = self.call('same_md5 "$A" "$B"; echo $?', A=one, B=two)
                self.assertEqual(done.stdout.strip(), str(want), done.stderr)


if __name__ == "__main__":
    unittest.main()
