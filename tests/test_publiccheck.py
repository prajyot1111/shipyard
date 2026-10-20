"""The public check (`tests/publiccheck.py`, c-699): one install's own names found in a tree,
with no allowlist and `docs/` read. Every tree here is a scratch one and every name is made
up: nothing reads this developer's git identity, home or host (the seams are filled)."""

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

from tests import publiccheck
from tests.helpers import make_repo

# Spelled in parts, so this file passes the checks it tests (as `tests/test_atlas.py` spells
# its dash): a home path, a tailnet host and an address are never written whole here.
HOME = "/" + "Users/ada"
GRACE = "/" + "Users/grace"
TAILNET = "tail9." + "ts.net"
AT = "@"
NAMES = publiccheck.Names(names=["lovelace"], emails=[f"ada{AT}lovelace.dev"], home=HOME,
                          hosts=["analytical", f"analytical.{TAILNET}"], terms=["acme(?:corp)?", "trackr"])


def tree(files: dict, links: dict | None = None) -> Path:
    """A scratch git repo holding `files` (untracked, as a new file is) and `links`."""
    root = make_repo(Path(tempfile.mkdtemp(prefix="publiccheck-")))
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text) if isinstance(text, bytes) else path.write_text(text)
    for name, target in (links or {}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, root / name)
    return root


def commit(root: Path, message: str) -> str:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@x",
                    "commit", "-q", "--allow-empty", "-m", message], check=True)
    done = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
    return done.stdout.strip()


def run(root: Path, *args: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = publiccheck.main(["--root", str(root), *args], names=NAMES)
    return code, out.getvalue()


class TreeTest(unittest.TestCase):
    def test_each_kind_is_found_with_its_file_and_line_and_docs_are_read(self):
        root = tree({
            "keel/x.py": f"# decided by Lovelace\nHOME = '{HOME}/keel'\n",
            "docs/history.md": f"It ran on analytical.{TAILNET}.\nMail ada{AT}lovelace.dev.\n",
            "talker/memory/note.md": "The AcmeCorp tracker is trackr.\n",
        })
        self.assertEqual(sorted(publiccheck.check(root, NAMES)), sorted([
            ("keel/x.py", 1, "name"), ("keel/x.py", 2, "home path"),
            ("docs/history.md", 1, "host"), ("docs/history.md", 2, "email"),
            ("docs/history.md", 2, "name"), ("talker/memory/note.md", 1, "pack term")]))

    def test_it_runs_as_a_script_from_anywhere_with_no_pythonpath(self):
        """c-729: `python3 tests/publiccheck.py` finds its own tree, as `-m` from the root does."""
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        with tempfile.TemporaryDirectory() as tmp:
            done = subprocess.run(["python3", str(publiccheck.ROOT / "tests" / "publiccheck.py"), "--help"],
                                  cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr[-500:])
        self.assertIn("--strict", done.stdout)

    def test_a_name_inside_another_word_is_not_a_hit(self):
        root = tree({"a.md": "The lovelaced adapter, and analytically so.\n"})
        self.assertEqual(publiccheck.check(root, NAMES), [])

    def test_the_rules_that_need_no_install(self):
        """Another person's home, host or address is a finding whoever runs the check; a
        stand-in, an example domain, a robot's address and a file name are not."""
        nobody = publiccheck.Names()
        root = tree({
            "bad.md": f"{GRACE}/x\nbox.{TAILNET}\nwrite to grace{AT}hopper.dev\n",
            "fine.md": f"/Users/you/x and /home/ubuntu\nhost.example.ts.net\nsam{AT}example.com, "
                       f"noreply{AT}anthropic.com, git{AT}github.com:o/r.git, icon{AT}2x.png, a{AT}b.invalid\n",
        })
        self.assertEqual(publiccheck.check(root, nobody),
                         [("bad.md", 1, "home path"), ("bad.md", 2, "host"), ("bad.md", 3, "email")])

    def test_a_link_out_of_the_tree_is_a_finding_and_one_inside_is_not(self):
        root = tree({"packs/sandbox/pack.toml": "name = 'sandbox'\n"},
                    links={"adapters/sandbox": "../packs/sandbox", "skills/mine": f"{HOME}/.claude/skills/mine",
                           "skills/up": "../../elsewhere"})
        self.assertEqual(sorted(publiccheck.check(root, NAMES)),
                         [("skills/mine", 0, "symlink"), ("skills/up", 0, "symlink")])

    def test_a_file_it_cannot_read_is_passed_over(self):
        root = tree({"app/icon.png": b"\x89PNG\r\n\x1a\n\xff\xfe lovelace"})
        self.assertEqual(publiccheck.check(root, NAMES), [])


class RangeTest(unittest.TestCase):
    def test_a_range_adds_its_new_images_and_its_commit_messages(self):
        root = tree({"app/old.png": b"\x89PNG old"})
        base = commit(root, "the first tree")
        (root / "docs").mkdir()
        (root / "docs" / "shot.png").write_bytes(b"\x89PNG new")
        (root / "docs" / "note.md").write_text("plain words\n")
        head = commit(root, "Add a shot\n\nSeen on trackr by Lovelace.")
        found = publiccheck.check(root, NAMES, f"{base}..{head}")
        self.assertEqual(sorted(found), sorted([
            ("docs/shot.png", 0, "new image"), (f"commit {head[:12]}", 3, "name"),
            (f"commit {head[:12]}", 3, "pack term")]))
        self.assertEqual(publiccheck.check(root, NAMES), [], "no range: neither is read")


class ModesTest(unittest.TestCase):
    def setUp(self):
        self.dirty = tree({"etc/x.toml": 'token = "sk-live-0123456789"  # lovelace\n'})
        self.clean = tree({"etc/x.toml": "port = 8800\n"})

    def test_report_mode_exits_0_whatever_it_finds(self):
        code, out = run(self.dirty)
        self.assertEqual(code, 0)
        self.assertIn("report only, nothing fails on it): 1 findings in 1 files", out)
        self.assertIn("by kind: name 1", out)
        self.assertIn("by directory: etc 1", out)

    def test_strict_exits_1_on_a_finding_and_0_on_a_clean_tree(self):
        self.assertEqual(run(self.dirty, "--strict")[0], 1)
        code, out = run(self.clean, "--strict")
        self.assertEqual((code, out.strip()), (0, "public check (strict): nothing of one install's in the tree"))

    def test_it_prints_where_and_what_kind_never_the_term_or_the_line(self):
        _, out = run(self.dirty, "--list")
        self.assertIn("etc/x.toml:1: name", out)
        for secret in ("sk-live", "lovelace", "token"):
            self.assertNotIn(secret, out.lower())


class PathsTest(unittest.TestCase):
    """Review F10: a file's NAME can hold what its text does not, and what is printed is the
    path, so a path that holds a name is a finding and is printed masked."""

    def setUp(self):
        self.root = tree({"identity/about-lovelace.md": "plain words\n",
                          "docs/trackr/notes.md": "It was decided by Lovelace.\n",
                          "docs/plain.md": "plain words\n"})

    def test_a_name_in_a_file_name_is_a_finding_on_line_0_under_a_masked_path(self):
        self.assertEqual(sorted(publiccheck.check(self.root, NAMES)), sorted([
            ("identity/about-<name>.md", 0, "name"),
            ("docs/<pack term>/notes.md", 0, "pack term"), ("docs/<pack term>/notes.md", 1, "name")]))

    def test_nothing_printed_holds_the_name_a_path_carries(self):
        code, out = run(self.root, "--list")
        self.assertEqual(code, 0)
        self.assertIn("identity/about-<name>.md:0: name", out)
        for secret in ("lovelace", "trackr"):
            self.assertNotIn(secret, out.lower())

    def test_top_level_files_masked_with_a_two_word_kind_are_counted_apart(self):
        """Fix check: `<pack term>.md` was grouped by its first word, so it read `<pack`
        and two files counted as one. Only a commit's `commit <sha>` is grouped by a word."""
        root = tree({"trackr.md": "plain\n", "trackr.txt": "plain\n", "my notes.md": "by Lovelace\n"})
        commit(root, "about trackr")
        head = commit(root, "more on trackr")
        code, out = run(root, "--range", f"{head}~1..{head}")
        self.assertEqual(code, 0)
        tops = out.split("by directory: ", 1)[1].strip().split(", ")
        self.assertEqual(sorted(tops), ["<pack term>.md 1", "<pack term>.txt 1", "commit 1", "my notes.md 1"])

    def test_a_new_image_named_for_someone_is_masked_too(self):
        root = tree({"a.md": "plain\n"})
        base = commit(root, "the first tree")
        (root / "lovelace.png").write_bytes(b"\x89PNG new")
        head = commit(root, "Add a picture")
        self.assertEqual(publiccheck.range_findings(root, NAMES, f"{base}..{head}"), [("<name>.png", 0, "new image")])


class CopyrightTest(unittest.TestCase):
    """The owner names themself as the copyright holder in NOTICE: that one line, in that
    form, is let through (`ALLOWED`); the same name anywhere else is still a finding."""

    def test_the_copyright_line_of_notice_passes_and_the_name_elsewhere_does_not(self):
        root = tree({"NOTICE": "Shipyard\nCopyright 2026 Ada Lovelace\n\nMaintained by Lovelace.\n",
                     "README.md": "Copyright 2026 Ada Lovelace\n"})
        self.assertEqual(sorted(publiccheck.check(root, NAMES)),
                         [("NOTICE", 4, "name"), ("README.md", 1, "name")])

    def test_the_drift_check_lets_the_same_one_line_through_and_no_other(self):
        """`tests/personal.py` reads names too, file by file; it shares the one table."""
        from tests import personal     # noqa: PLC0415
        text = "Shipyard\nCopyright 2026 Ada Lovelace\nCopyright 2026 Ada Lovelace\nBy Lovelace.\n"
        self.assertEqual([hit.split(":")[0] for hit in personal.hits_in(text, ["lovelace"], "NOTICE")], ["3", "4"])
        self.assertEqual(len(personal.hits_in(text, ["lovelace"], "README.md")), 3)

    def test_the_first_line_of_the_form_is_the_allowed_one_whatever_name_it_carries(self):
        """A copyright line naming someone else comes first: the owner's line after it is
        a finding, in both guards."""
        from tests import personal     # noqa: PLC0415
        text = "Copyright 2026 Grace Hopper\nCopyright 2026 Ada Lovelace\n"
        root = tree({"NOTICE": text})
        self.assertEqual(publiccheck.check(root, NAMES), [("NOTICE", 2, "name")])
        self.assertEqual([hit.split(":")[0] for hit in personal.hits_in(text, ["lovelace"], "NOTICE")], ["2"])

    def test_an_email_or_a_pack_term_on_the_allowed_line_is_still_reported(self):
        root = tree({"NOTICE": "Copyright 2026 Ada Lovelace Trackr\n"})
        self.assertEqual(publiccheck.check(root, NAMES), [("NOTICE", 1, "pack term")])
        root = tree({"NOTICE": f"Copyright 2026 Ada Lovelace <ada{AT}lovelace.dev>\n"})
        self.assertEqual(sorted(kind for _, _, kind in publiccheck.check(root, NAMES)), ["email", "name"])

    def test_only_the_first_copyright_line_is_let_through(self):
        root = tree({"NOTICE": "Copyright 2026 Ada Lovelace\nCopyright 2026 Ada Lovelace\n"})
        self.assertEqual(publiccheck.check(root, NAMES), [("NOTICE", 2, "name")])


class LetThroughTest(unittest.TestCase):
    """c-722 landing B: strict in `make drift`, so what passes is two tables, each entry
    with its reason, and nothing else."""

    def test_a_vendored_copyright_line_passes_its_email_and_nothing_more(self):
        vendored = "app/vendor/highlight/core.min.js"
        line = f"  (c) 2006-2024 Josh Goebel <hello{AT}joshgoebel.com> and other contributors"
        root = tree({vendored: f"/*!\n{line}\n*/\nmail me: x{AT}people.dev\n", "app/x.js": line + "\n"})
        self.assertEqual(sorted(publiccheck.check(root, NAMES)),
                         [("app/vendor/highlight/core.min.js", 4, "email"), ("app/x.js", 1, "email")])

    def test_a_waiting_folder_is_counted_apart_and_fails_nothing(self):
        """The table is the test's own, so this holds after the owner's folder and its entry
        are gone from the tree."""
        root = tree({"old/memory/a.md": "Lovelace\n", "README.md": "plain\n"})
        with mock.patch.object(publiccheck, "WAITING", [("old/memory/", "the owner's own step")]):
            code, out = run(root, "--strict", "--list")
        self.assertEqual(code, 0, out)
        self.assertIn("nothing of one install's in the tree", out)
        self.assertIn("1 findings wait in old/memory/: the owner's own step", out)
        self.assertNotIn("old/memory/a.md", out)

    def test_each_waiting_folder_is_still_in_the_tree(self):
        """The entry goes in the commit that removes its folder: the table only shrinks."""
        gone = [prefix for prefix, _ in publiccheck.WAITING if not publiccheck.tracks(publiccheck.ROOT, prefix)]
        self.assertEqual(gone, [], "a WAITING folder has left the tree; take its entry out too")

    def test_a_folder_counts_as_in_the_tree_only_while_git_tracks_it(self):
        """c-726 r1.F8: an untracked leftover of a removed folder is not the folder."""
        root = tree({"kept/a.md": "x\n"})
        subprocess.run(["git", "-C", str(root), "add", "kept"], check=True)
        (root / "left").mkdir()
        (root / "left" / "b.md").write_text("an untracked leftover\n")
        self.assertTrue(publiccheck.tracks(root, "kept/"))
        self.assertFalse(publiccheck.tracks(root, "left/"))


class HostTest(unittest.TestCase):
    """c-725 r2.F5, r3.F5: a host is found as a whole word, except one that is a common word
    of a fixed list (`keel`), found only where it stands as a host."""

    def names_for(self, root: Path, host: str):
        return publiccheck.install_names(None, root, git=lambda _root, _key: "",
                                         home=lambda: Path(HOME), hostname=lambda: host)

    def test_a_host_that_is_a_common_word_is_found_only_as_a_host(self):
        root = tree({"a.md": "keel run, the keel.toml, Keel's deck\n",
                     "b.md": "http://keel:8800/ and ssh me@keel\n", "c.md": "keel.local\n"})
        names = self.names_for(root, "keel")
        self.assertEqual(names.common, ["keel"])
        self.assertEqual(sorted(publiccheck.check(root, names)), [("b.md", 1, "host"), ("c.md", 1, "host")])

    def test_a_machines_own_name_is_found_in_prose_a_config_line_and_a_command(self):
        root = tree({"a.md": "built on ada-mac last night\n", "b.toml": 'host = "ada-mac"\n',
                     "c.sh": "KEEL_HOST=ada-mac ssh ada-mac\n", "d.md": "nothing here\n"})
        names = self.names_for(root, "ada-mac")
        self.assertEqual(names.common, [])
        self.assertEqual(sorted(where for where, _, _ in publiccheck.check(root, names)), ["a.md", "b.toml", "c.sh"])

    def test_a_machines_name_that_has_leaked_is_found_in_prose_wherever_it_stands(self):
        """r3.F5: what counts as common is a fixed list of product and dictionary words, never
        the tree under check, so a name that leaked into the tree cannot hide itself there."""
        root = tree({"a.md": "built on adasmac last night\n", "b.md": "adasmac again\n"})
        names = self.names_for(root, "adasmac")
        self.assertEqual(names.common, [])
        self.assertEqual(sorted(where for where, _, _ in publiccheck.check(root, names)), ["a.md", "b.md"])

    def test_the_common_words_are_a_fixed_list_whatever_the_tree_holds(self):
        """r3.F5: `keel` is common in an empty tree too."""
        self.assertEqual(self.names_for(tree({}), "keel").common, ["keel"])
        self.assertEqual(self.names_for(tree({}), "harbor").common, ["harbor"])

    def test_an_example_host_in_the_installs_config_is_no_ones(self):
        install = Path(tempfile.mkdtemp(prefix="publiccheck-install-"))
        (install / "config.toml").write_text(f'# url = "https://deck.example.{TAILNET}"\n'
                                             f'url = "https://deck.{TAILNET}"\n')
        names = publiccheck.install_names(install, tree({}), git=lambda _root, _key: "",
                                          home=lambda: Path(HOME), hostname=lambda: "mac")
        self.assertEqual(names.hosts, [f"deck.{TAILNET}"])


class UnreadTest(unittest.TestCase):
    """Review F4: report mode never fails `make drift`. A pack term that grep reads and
    Python does not, and a git that will not list the tree, are each said in one line."""

    BAD = "trackr[[:space:]]*(id"       # an ERE bracket class and an open group: grep -E's, not re's

    def names(self):
        return publiccheck.Names(names=["lovelace"], terms=[self.BAD, "acme"])

    def run_with(self, root: Path, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = publiccheck.main(["--root", str(root), *args], names=self.names())
        return code, out.getvalue()

    def test_a_term_python_cannot_read_is_skipped_and_said_without_the_term(self):
        root = tree({"a.md": "Acme and Lovelace.\n"})
        code, out = self.run_with(root)
        self.assertEqual(code, 0)
        self.assertIn("1 pack term could not be read as a pattern and was skipped", out)
        self.assertIn("by kind: name 1, pack term 1", out, "the terms it can read are still looked for")
        self.assertNotIn("trackr", out)
        self.assertNotIn("[[:space:]]", out)

    def test_a_posix_class_python_would_read_as_something_else_is_skipped_too(self):
        names = publiccheck.Names(terms=["acme[[:space:]]corp", "trackr"])
        with warnings.catch_warnings():
            warnings.simplefilter("error")       # a warning let through would raise here
            patterns = names.patterns()
        self.assertEqual((names.skipped, [kind for kind, _ in patterns]), (1, ["pack term"]))

    def test_strict_fails_on_a_term_it_cannot_read_even_in_a_clean_tree(self):
        code, out = self.run_with(tree({"a.md": "plain\n"}), "--strict")
        self.assertEqual(code, 1)
        self.assertIn("1 pack term could not be read", out)
        self.assertNotIn("trackr", out)

    def test_strict_does_not_fail_on_an_installs_own_term_it_cannot_read(self):
        """c-726 r1.F8: a term from the install's packs that Python cannot read is said, and
        fails nothing: only a term from the tree's own packs fails --strict."""
        names = publiccheck.Names(names=["lovelace"], terms=[self.BAD, "acme"], tree_terms=["acme"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = publiccheck.main(["--root", str(tree({"a.md": "plain\n"})), "--strict"], names=names)
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("1 pack term could not be read", out.getvalue())

    def test_a_git_that_cannot_list_the_tree_is_said_and_report_mode_exits_0(self):
        bare = Path(tempfile.mkdtemp(prefix="publiccheck-nogit-"))      # no repository here
        (bare / "a.md").write_text("Lovelace\n")
        code, out = self.run_with(bare)
        self.assertEqual((code, out.strip()),
                         (0, "public check (report only, nothing fails on it): git could not list the tree, "
                             "so nothing was read"))
        self.assertEqual(self.run_with(bare, "--strict")[0], 1)

    def test_a_range_git_cannot_read_is_said_the_same_way(self):
        root = tree({"a.md": "plain\n"})
        commit(root, "the first tree")
        code, out = self.run_with(root, "--range", "nowhere..HEAD")
        self.assertEqual(code, 0)
        self.assertIn("git could not read the range, so nothing was read", out)
        self.assertEqual(self.run_with(root, "--range", "nowhere..HEAD", "--strict")[0], 1)


class NamesTest(unittest.TestCase):
    def test_an_installs_names_come_from_git_its_home_its_host_its_config_and_its_packs(self):
        install = Path(tempfile.mkdtemp(prefix="publiccheck-install-"))
        (install / "config.toml").write_text(f'url = "https://deck.{TAILNET}:8800"\n')
        (install / "packs" / "job").mkdir(parents=True)
        (install / "packs" / "job" / "drift-terms").write_text("# the employer\nacme(?:corp)?\ntrackr\n")
        root = tree({})
        git = {"user.name": "Ada K. Lovelace", "user.email": f"countess{AT}lovelace.dev"}
        names = publiccheck.install_names(install, root, git=lambda _root, key: git[key],
                                          home=lambda: Path(HOME),
                                          hostname=lambda: f"Analytical.{TAILNET}")
        self.assertEqual(names.names, ["countess", "lovelace"], "a word under four letters is left out")
        self.assertEqual(names.emails, [f"countess{AT}lovelace.dev"])
        self.assertEqual(names.home, HOME)
        self.assertEqual(names.hosts, ["analytical", f"analytical.{TAILNET}", f"deck.{TAILNET}"])
        self.assertEqual(names.terms, ["acme(?:corp)?", "trackr"])

    def test_with_no_install_and_no_identity_only_the_tree_is_known(self):
        names = publiccheck.install_names(None, tree({}), git=lambda _root, _key: "",
                                          home=lambda: Path(HOME), hostname=lambda: "mac")
        self.assertEqual((names.names, names.emails, names.hosts, names.terms), ([], [], [], []))

    def test_the_install_is_the_one_keel_config_names(self):
        self.assertEqual(publiccheck.install_of("/tmp/mine"), Path("/tmp/mine"))
        self.assertEqual(publiccheck.install_of(None, {"KEEL_CONFIG": "/tmp/mine/config.toml"}),
                         Path("/tmp/mine").resolve())
        self.assertIsNone(publiccheck.install_of(None, {"KEEL_CONFIG": "/tmp/mine/keel.toml"}))
        self.assertIsNone(publiccheck.install_of(None, {}))

    def test_a_tilde_is_the_callers_home_not_the_fences(self):
        """c-733 r2.F3: the same reading as the install half of `make drift`
        (`packs.install_packs`): behind the fence `HOME` is a throwaway."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            said = publiccheck.install_of(None, {"KEEL_CONFIG": "~/mine/config.toml", "HOME": str(home)})
        self.assertEqual(said, home / "mine")


if __name__ == "__main__":
    unittest.main()
