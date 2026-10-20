"""The install's memory (c-722, keel/memoryroot.py): Bosun's and the talker's memory and the
user's identity profile live in the install, seeded once from `templates/`, never overwritten,
and read before the checkout's, which is read only while the install has none."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from keel import memoryroot

ROOT = Path(__file__).resolve().parent.parent


def git(repo: Path, *argv: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *argv], capture_output=True, text=True,
                          check=True).stdout.strip()


def code_with_templates(path: Path) -> Path:
    """A code checkout that ships the templates and holds no memory of its own."""
    for source in sorted((ROOT / "templates").rglob("*")):
        if source.is_file():
            target = path / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    return path


def checkout_memory(code: Path) -> None:
    """The memory an older checkout carried in its own tree."""
    for part, rel in memoryroot.CHECKOUT.items():
        name = "about-me.md" if part == memoryroot.IDENTITY else memoryroot.INDEX
        (code / rel).mkdir(parents=True, exist_ok=True)
        (code / rel / name).write_text(f"the checkout's {part}\n")


class MemoryCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        self.code = code_with_templates(self.dir / "code")
        self.install = self.dir / "install"
        self.install.mkdir()


class SeedTest(MemoryCase):
    def test_a_new_install_is_seeded_from_the_templates_as_a_git_repo(self):
        seeded = memoryroot.seed(self.install, self.code)
        self.assertEqual(seeded, [memoryroot.BOSUN, memoryroot.TALKER, memoryroot.IDENTITY])
        bosun = self.install / "memory" / "bosun" / "MEMORY.md"
        self.assertEqual(bosun.read_text(), (self.code / "templates/memory/bosun/MEMORY.md").read_text())
        self.assertTrue((self.install / "memory" / "talker" / "MEMORY.md").is_file())
        self.assertTrue((self.install / "identity" / "about-you.md").is_file())
        self.assertEqual(git(self.install / "memory", "branch", "--show-current"), "main")
        self.assertEqual(git(self.install / "memory", "status", "--porcelain"), "")
        self.assertIn("bosun/MEMORY.md", git(self.install / "memory", "ls-files"))

    def test_seeding_again_never_overwrites_what_the_user_changed(self):
        memoryroot.seed(self.install, self.code)
        mine = self.install / "memory" / "bosun" / "identity.md"
        mine.write_text("my own words\n")
        (self.install / "identity" / "about-you.md").unlink()
        (self.install / "identity" / "about-me.md").write_text("me\n")
        self.assertEqual(memoryroot.seed(self.install, self.code), [])
        self.assertEqual(mine.read_text(), "my own words\n")
        self.assertFalse((self.install / "identity" / "about-you.md").exists())

    def test_seeding_again_commits_nothing_the_talker_or_a_user_wrote(self):
        """r1.F11: a re-run of init commits only what it seeded; the talker's own writes and
        an edit to Bosun's memory stay uncommitted, for a card or the user to review."""
        memoryroot.seed(self.install, self.code)
        head = git(self.install / "memory", "rev-parse", "HEAD")
        (self.install / "memory" / "talker" / "said-today.md").write_text("an unreviewed lesson\n")
        (self.install / "memory" / "bosun" / "identity.md").write_text("edited\n")
        shutil.rmtree(self.install / "identity")
        self.assertEqual(memoryroot.seed(self.install, self.code), [memoryroot.IDENTITY])
        self.assertEqual(git(self.install / "memory", "rev-parse", "HEAD"), head)
        self.assertEqual(sorted(line.strip() for line in git(self.install / "memory", "status", "--porcelain").splitlines()),
                         ["?? talker/said-today.md", "M bosun/identity.md"])

    def test_a_checkout_that_still_carries_memory_is_not_shadowed_by_templates(self):
        """Seeding then would hide the user's memory behind the templates; the move brings it."""
        checkout_memory(self.code)
        self.assertEqual(memoryroot.seed(self.install, self.code), [])
        self.assertFalse((self.install / "memory").exists())
        self.assertEqual(memoryroot.held_by_checkout(self.code),
                         [memoryroot.BOSUN, memoryroot.TALKER, memoryroot.IDENTITY])


class ReadTest(MemoryCase):
    def test_the_install_is_read_first(self):
        checkout_memory(self.code)
        (self.install / "memory" / "bosun").mkdir(parents=True)
        (self.install / "memory" / "bosun" / "MEMORY.md").write_text("mine\n")
        self.assertEqual(memoryroot.dir_of(memoryroot.BOSUN, self.install, self.code),
                         self.install / "memory" / "bosun")

    def test_the_checkout_is_read_only_while_the_install_has_none(self):
        checkout_memory(self.code)
        (self.install / "memory" / "talker").mkdir(parents=True)        # made, but empty
        for part in memoryroot.PARTS:
            self.assertEqual(memoryroot.dir_of(part, self.install, self.code),
                             self.code / memoryroot.CHECKOUT[part], part)
        self.assertEqual(memoryroot.dir_of(memoryroot.BOSUN, None, self.code),
                         self.code / "bosun" / "memory", "no install: the checkout's")

    def test_an_identity_profile_in_the_install_is_read(self):
        (self.install / "identity").mkdir()
        (self.install / "identity" / "about-me.md").write_text("me\n")
        self.assertEqual(memoryroot.dir_of(memoryroot.IDENTITY, self.install, self.code),
                         self.install / "identity")


class TemplateNewsTest(MemoryCase):
    def test_a_changed_template_is_said_and_never_written_over_yours(self):
        memoryroot.seed(self.install, self.code)
        self.assertEqual(memoryroot.template_news(self.install, self.code), [])
        shipped = self.code / "templates" / "memory" / "bosun" / "builder.md"
        shipped.write_text(shipped.read_text() + "\nA new lesson.\n")
        (self.code / "templates" / "memory" / "talker" / "new.md").write_text("new\n")
        news = memoryroot.template_news(self.install, self.code)
        self.assertEqual(news, ["templates/memory/bosun/builder.md changed",
                                "templates/memory/talker/new.md is new"])
        self.assertNotIn("A new lesson", (self.install / "memory" / "bosun" / "builder.md").read_text())

    def test_an_install_that_was_never_seeded_has_no_news(self):
        """The memory a move brought in was never a template's copy."""
        self.assertEqual(memoryroot.template_news(self.install, self.code), [])
        (self.install / "memory").mkdir()
        (self.install / "memory" / memoryroot.SEEDED).write_text(json.dumps({}))
        self.assertEqual(memoryroot.template_news(self.install, self.code), [])


class DoctorTest(MemoryCase):
    """The doctor says where each part is read from, and a template that moved on, as
    information: neither is a problem, and nothing is overwritten."""

    def cfg(self):
        return type("C", (), {"install_home": self.install, "root": self.code})

    def test_it_says_where_each_part_is_read_from_and_what_to_run(self):
        from keel import doctor
        checkout_memory(self.code)
        report = memoryroot.report(self.cfg())
        self.assertEqual(report["from_checkout"], [memoryroot.BOSUN, memoryroot.TALKER, memoryroot.IDENTITY])
        lines = memoryroot.lines(report)
        self.assertIn(f"memory        bosun {self.code / 'bosun' / 'memory'}", lines)
        self.assertIn("memory        read from the checkout for bosun, talker, identity until "
                      "`shipyard move-personal` brings it into the install", lines)
        self.assertEqual(doctor.problems({"config": {"ok": True}, "claude": {"ok": True}, "memory": report}), [])

    def test_a_template_that_moved_on_is_said(self):
        from keel import doctor
        memoryroot.seed(self.install, self.code)
        shipped = self.code / "templates" / "memory" / "talker" / "voice.md"
        shipped.write_text("newer\n")
        lines = memoryroot.lines(memoryroot.report(self.cfg()))
        self.assertIn(f"memory        bosun {self.install / 'memory' / 'bosun'}", lines)
        self.assertIn("memory        templates/memory/talker/voice.md changed since your install was "
                      "seeded; yours is kept, compare and take what you want", lines)


if __name__ == "__main__":
    unittest.main()
