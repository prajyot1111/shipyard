"""`make drift`'s install half (`tests/installdrift.py`, c-722 r1.F7): once an owner's pack is
moved into the install, its `drift-terms` still hold the tree. Run here on a scratch tree and
a scratch install named by `KEEL_CONFIG`, with a made-up word.

c-733: the check runs behind the test fence, which drops `KEEL_CONFIG`, so it reads the
install the CALLER named (`fence.caller()`); a test hands its own environment in. It says
which install's terms it checked, or that none was named, and an install named whose terms
cannot be read fails it."""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tests import fence, installdrift

WORD = "zorblaxian"
ROOT = Path(__file__).resolve().parent.parent


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class InstallDriftTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.tree, self.install = base / "tree", base / "install"
        write(self.tree / "keel" / "core.py", "print('neutral')\n")
        write(self.tree / "docs" / "history.md", f"{WORD} is history\n")
        subprocess.run(["git", "init", "-q", str(self.tree)], check=True)
        write(self.install / "config.toml", "")
        write(self.install / "packs" / "owner" / "drift-terms", f"# the owner's words\n{WORD}\n")
        self.environ = {"KEEL_CONFIG": str(self.install / "config.toml")}

    def run_check(self) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = installdrift.main(self.tree, self.environ)
        return code, out.getvalue()

    def test_the_installs_pack_words_fail_the_tree_outside_docs(self):
        write(self.tree / "keel" / "leak.py", f"NAME = '{WORD.upper()}'\n")
        code, said = self.run_check()
        self.assertEqual(code, 1, said)
        self.assertIn("keel/leak.py: 1 hit", said)
        self.assertNotIn("docs/history.md", said)
        self.assertNotIn(WORD, said.lower(), "a hit is its file and a count, never the line's text")

    def test_a_line_break_grep_does_not_split_on_never_shows_the_word(self):
        """r2.F1: nothing grep prints is echoed but a name it was handed and a count, so a
        `\\r` or a form feed before the word cannot carry it out."""
        for mark in (b"\r", b"\x0c", b"\x0b", b"\xe2\x80\xa8"):
            with self.subTest(mark=mark):
                (self.tree / "keel" / "leak.py").write_bytes(b"x = 1" + mark + WORD.encode() + b"\n")
                code, said = self.run_check()
                self.assertEqual(code, 1, said)
                self.assertIn("keel/leak.py: 1 hit", said)
                self.assertNotIn(WORD, said.lower())

    def test_a_tracked_file_deleted_from_disk_is_not_an_error(self):
        """r2.F2: `git ls-files -c` lists it; grep is handed only files that are there."""
        write(self.tree / "keel" / "gone.py", "x = 1\n")
        subprocess.run(["git", "-C", str(self.tree), "add", "keel/gone.py"], check=True)
        (self.tree / "keel" / "gone.py").unlink()
        code, said = self.run_check()
        self.assertEqual(code, 0, said)
        write(self.tree / "keel" / "leak.py", f"{WORD}\n")
        code, said = self.run_check()
        self.assertEqual(code, 1, said)
        self.assertIn("keel/leak.py: 1 hit", said)

    def test_a_file_grep_cannot_read_fails_naming_it_without_greps_text(self):
        write(self.tree / "keel" / "locked.py", f"{WORD}\n")
        (self.tree / "keel" / "locked.py").chmod(0)
        try:
            code, said = self.run_check()
        finally:
            (self.tree / "keel" / "locked.py").chmod(0o644)
        self.assertEqual(code, 1, said)
        self.assertIn("keel/locked.py", said)
        self.assertNotIn("ermission", said, "grep's own words are never echoed")
        self.assertNotIn(WORD, said.lower())

    def test_a_term_in_a_files_path_is_a_hit_and_is_never_printed(self):
        """r3.F1: what a file is NAMED can be the install's own, and the name is what this
        check prints: a name holding a term is a hit even with clean contents, and every
        name is printed masked."""
        cases = {"clean": ("keel", f"{WORD}_notes.py", "x = 1\n"),
                 "holding it": ("keel", f"{WORD.upper()}.py", f"{WORD}\n"),
                 "in its folder": (f"app/{WORD}", "index.js", "x = 1\n")}
        for case, (folder, name, text) in cases.items():
            with self.subTest(case=case):
                path = self.tree / folder / name
                write(path, text)
                try:
                    code, said = self.run_check()
                finally:
                    path.unlink()
                self.assertEqual(code, 1, said)
                self.assertNotIn(WORD, said.lower())
                self.assertIn("<pack term>", said)

    def test_an_unreadable_file_whose_name_holds_a_term_is_masked(self):
        path = self.tree / "keel" / f"{WORD}.py"
        write(path, "x = 1\n")
        path.chmod(0)
        try:
            code, said = self.run_check()
        finally:
            path.chmod(0o644)
        self.assertEqual(code, 1, said)
        self.assertIn("could not be read", said)
        self.assertNotIn(WORD, said.lower())

    def test_a_file_name_with_a_colon_is_named_whole(self):
        write(self.tree / "keel" / "a:b.py", f"{WORD}\n{WORD}\n")
        code, said = self.run_check()
        self.assertEqual(code, 1, said)
        self.assertIn("keel/a:b.py: 2 hits", said)
        self.assertNotIn(WORD, said.lower())

    def test_a_clean_tree_passes_and_says_whose_terms_it_read(self):
        code, said = self.run_check()
        self.assertEqual(code, 0, said)
        self.assertIn("1 term", said)
        self.assertIn(str(self.install), said)
        self.assertNotIn(WORD, said)

    def test_a_tilde_is_the_callers_home_not_the_fences(self):
        """r1.F2: behind the fence `HOME` is a throwaway; `~` is the caller's."""
        self.environ = {"KEEL_CONFIG": "~/install/config.toml", "HOME": str(self.install.parent)}
        code, said = self.run_check()
        self.assertEqual(code, 0, said)
        self.assertIn(str(self.install), said)

    def test_the_trees_copy_of_the_same_pack_may_say_its_words(self):
        write(self.tree / "packs" / "owner" / "verbs" / "card", f"# {WORD}\n")
        self.assertEqual(self.run_check()[0], 0)

    def test_with_no_install_named_it_says_no_installs_terms_were_checked(self):
        self.environ = {}
        write(self.tree / "keel" / "leak.py", f"NAME = '{WORD}'\n")
        code, said = self.run_check()
        self.assertEqual(code, 0, said)
        self.assertIn("no install's terms", said)

    def test_a_config_named_that_is_not_an_installs_fails_and_says_why(self):
        """r1.F3: a renamed install config is a misconfiguration, never a pass."""
        renamed = self.install / "keel.toml"
        write(renamed, "")
        self.environ = {"KEEL_CONFIG": str(renamed)}
        code, said = self.run_check()
        self.assertEqual(code, 1, said)
        self.assertIn("not an install's config.toml", said)

    def test_a_sandbox_config_passes_and_says_no_installs_terms_were_checked(self):
        """r3.F3: the demo sandbox's toml is named on purpose (`demo/sandbox/run`), and its
        `.keel-sandbox` marker says so; without the marker the same toml still fails."""
        sandbox = self.install.parent / "sandbox"
        write(sandbox / "keel.toml", "")
        self.environ = {"KEEL_CONFIG": str(sandbox / "keel.toml")}
        code, said = self.run_check()
        self.assertEqual(code, 1, said)
        write(sandbox / ".keel-sandbox", "")
        code, said = self.run_check()
        self.assertEqual(code, 0, said)
        self.assertIn("sandbox", said)
        self.assertIn("no install's terms", said)

    def test_only_the_sandboxs_own_keel_toml_beside_its_marker_passes(self):
        """Fix check: the exemption is `keel.toml`, there as a file, beside the marker (the
        rule `demo/scenes/harbor` checks); another name or a missing file still fails."""
        sandbox = self.install.parent / "sandbox"
        write(sandbox / ".keel-sandbox", "")
        write(sandbox / "keel.tml", "")
        for named in (sandbox / "keel.tml", sandbox / "keel.toml"):      # the second is not there
            with self.subTest(named=named.name):
                self.environ = {"KEEL_CONFIG": str(named)}
                code, said = self.run_check()
                self.assertEqual(code, 1, said)

    def test_the_codes_own_config_named_passes_and_says_so(self):
        self.environ = {"KEEL_CONFIG": str(ROOT / "keel.toml")}
        code, said = self.run_check()
        self.assertEqual(code, 0, said)
        self.assertIn("no install's terms", said)

    def test_an_install_named_that_is_not_there_fails(self):
        self.environ = {"KEEL_CONFIG": str(self.install.parent / "gone" / "config.toml")}
        code, said = self.run_check()
        self.assertEqual(code, 1, said)
        self.assertIn("cannot be read", said)

    def test_an_installs_terms_that_cannot_be_read_fail(self):
        terms = self.install / "packs" / "owner" / "drift-terms"
        terms.unlink()
        terms.mkdir()
        code, said = self.run_check()
        self.assertEqual(code, 1, said)
        self.assertIn("cannot be read", said)


    def test_a_pack_directory_that_cannot_be_listed_fails(self):
        """r1.F4, r2.F4: glob skips a directory it may not list or search, so that is asked
        outright: no permissions at all, and read but not search (`r--`)."""
        owner, packs_dir = self.install / "packs" / "owner", self.install / "packs"
        for locked, mode in ((owner, 0), (packs_dir, 0), (owner, 0o444)):
            with self.subTest(locked=locked.name, mode=oct(mode)):
                locked.chmod(mode)
                try:
                    code, said = self.run_check()
                finally:
                    locked.chmod(0o755)
                self.assertEqual(code, 1, said)
                self.assertIn("cannot be read", said)

    def test_a_dangling_packs_link_fails(self):
        """r2.F4: an install's `packs` that is a link to nothing is not an install with none."""
        moved = self.install / "elsewhere"
        (self.install / "packs").rename(moved)
        (self.install / "packs").symlink_to(self.install / "gone")
        code, said = self.run_check()
        self.assertEqual(code, 1, said)
        self.assertIn("cannot be read", said)

    def test_a_dangling_pack_or_terms_link_fails(self):
        for link in (self.install / "packs" / "other", self.install / "packs" / "third" / "drift-terms"):
            with self.subTest(link=link.name):
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(self.install / "gone")
                try:
                    code, said = self.run_check()
                finally:
                    link.unlink()
                self.assertEqual(code, 1, said)
                self.assertIn("cannot be read", said)


    def test_an_install_with_no_pack_carrying_terms_passes_and_says_none_was_checked(self):
        """r1.F6: an install fresh from `shipyard init` has no pack terms; it is read, not refused."""
        (self.install / "packs" / "owner" / "drift-terms").write_text("# nothing yet\n")
        code, said = self.run_check()
        self.assertEqual(code, 0, said)
        self.assertIn("has no pack with drift terms", said)
        self.assertIn(str(self.install), said)


class GrepSaysOddThingsTest(unittest.TestCase):
    """r3.F2, r3.F4: what grep answers is never trusted into a pass. Its file listing (`-l`)
    or its count (`-c`) is replaced here, and the rest of it is the real one."""

    def setUp(self):
        InstallDriftTest.setUp(self)
        write(self.tree / "keel" / "leak.py", f"{WORD}\n")

    def answering(self, flag: str, code: int, out: bytes = b"", err: bytes = b""):
        real = installdrift.grep

        def fake(root, argv, text=None):
            if flag in argv:
                return subprocess.CompletedProcess(argv, code, out, err)
            return real(root, argv, text)
        return mock.patch.object(installdrift, "grep", side_effect=fake)

    def ended(self, flag: str, code: int, out: bytes = b"", err: bytes = b"") -> str:
        with self.answering(flag, code, out, err), self.assertRaises(SystemExit) as ended, \
             redirect_stdout(io.StringIO()):
            installdrift.main(self.tree, self.environ)
        said = str(ended.exception.code)
        self.assertNotIn(WORD, said.lower())
        return said

    def test_a_match_with_no_name_it_was_handed_fails(self):
        for out in (b"", b"./keel/leak.py\0", b"keel/elsewhere.py\0"):
            with self.subTest(out=out):
                said = self.ended("-l", 0, out)
                self.assertNotIn("keel/", said, "naming no file")

    def test_a_name_it_was_not_handed_beside_one_it_was_fails(self):
        said = self.ended("-l", 0, b"keel/leak.py\0keel/elsewhere.py\0")
        self.assertNotIn("keel/", said)

    def test_a_failure_whose_error_names_no_file_fails_without_its_words(self):
        said = self.ended("-l", 2, err=f"grep: {WORD}: no such thing\n".encode())
        self.assertIn("grep failed", said)

    def test_a_count_that_is_not_digits_fails(self):
        said = self.ended("-c", 0, out=f"{WORD}\n".encode())
        self.assertIn("did not count", said)

    def test_a_grep_ended_by_a_signal_fails_whatever_it_printed(self):
        """Fix check: any exit but 0 or 1 is a failure, a signal's negative one included,
        and the exit code is read before what grep printed."""
        write(self.tree / "keel" / f"{WORD}_named.py", "x = 1\n")
        for flag, out in (("-l", b""), ("-zc", b"0"), ("-zq", b""), ("-c", b"1")):
            with self.subTest(flag=flag):
                self.ended(flag, -9, out)


class CallerTest(unittest.TestCase):
    """r1.F6: `fence.caller()` is the environment before the fence, else this process's."""

    def test_it_is_the_environment_kept_before_the_scrub(self):
        with mock.patch.object(fence, "caller_env", {"KEEL_CONFIG": "/kept/config.toml"}):
            said = fence.caller()
            self.assertEqual(said, {"KEEL_CONFIG": "/kept/config.toml"})
            self.assertIsNot(said, fence.caller_env, "r2.F7: a copy, so a reader cannot change "
                             "what the runner and the selector start their children with")

    def test_with_nothing_kept_it_is_this_processs_own(self):
        with mock.patch.object(fence, "caller_env", {}), \
             mock.patch.dict(os.environ, {"KEEL_CONFIG": "/own/config.toml"}):
            said = fence.caller()
            self.assertEqual(said.get("KEEL_CONFIG"), "/own/config.toml")
            self.assertIsNot(said, os.environ, "a copy, so a reader cannot change the process's own")


class AsMakeRunsItTest(unittest.TestCase):
    """As `make drift` runs it: `python3 -m tests.installdrift`, whose import of the `tests`
    package puts up the fence. The install is the caller's, so a word of it that this very
    file holds fails the real tree."""

    def test_the_install_the_caller_named_is_read_behind_the_fence(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp).resolve() / "install"
            write(install / "config.toml", "")
            write(install / "packs" / "owner" / "drift-terms", f"{WORD}\n")
            env = {**os.environ, "KEEL_CONFIG": str(install / "config.toml")}
            done = subprocess.run([sys.executable, "-m", "tests.installdrift"], cwd=ROOT, env=env,
                                  capture_output=True, text=True)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("tests/test_installdrift.py", done.stdout)
        self.assertNotIn(WORD, done.stdout.lower() + done.stderr.lower())


if __name__ == "__main__":
    unittest.main()
