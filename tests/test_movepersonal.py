"""`shipyard move-personal` (keel/movepersonal.py, c-722): the one-time copy of an owner's own
things from the code checkout into the install. It copies and never deletes, never writes
over what the install has, says every file it copied and skipped, has a dry run, and commits
the memory repo. Run here on a scratch install made by init and a fake checkout."""

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from keel import movepersonal
from tests.test_installer import init

OLD_TOML = """\
[keel]
houses_max = 9

[backup]
sets = ["harbor", "helm", "code"]
pull = true

[voice]
record = true
vad_hangover = 1.5

[models]
converse = "claude-sonnet-x"
"""


def git(repo: Path, *argv: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *argv], capture_output=True, text=True,
                          check=True).stdout.strip()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def fake_checkout(path: Path) -> Path:
    """A checkout holding one owner's things where the tree used to keep them."""
    write(path / "packs" / "work" / "pack.toml", 'name = "work"\n')
    write(path / "packs" / "work" / "verbs" / "card", "#!/bin/sh\n")
    (path / "packs" / "work" / "verbs" / "card").chmod(0o755)
    for name in movepersonal.SEGMENTS:
        write(path / "segments" / name / "segment.md", f"# {name}\n")
    write(path / "bosun" / "memory" / "MEMORY.md", "the owner's Bosun index\n")
    write(path / "talker" / "memory" / "MEMORY.md", "the owner's talker index\n")
    write(path / "identity" / "about-me.md", "the owner\n")
    write(path / "docs" / "decisions.md", "decided\n")
    write(path / "keel.toml", OLD_TOML)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    git(path, "add", "-A")
    git(path, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "tree")
    # the talker writes its memory as it talks: uncommitted, and still the owner's
    write(path / "talker" / "memory" / "said-today.md", "an uncommitted lesson\n")
    return path


class MoveCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        self.home = self.dir / "install"
        self.assertEqual(init(self.home), 0)
        # An install from before c-722: its memory was read from the checkout.
        shutil.rmtree(self.home / "memory", ignore_errors=True)
        shutil.rmtree(self.home / "identity", ignore_errors=True)
        config = self.home / "config.toml"      # and its config listed no memory repo
        config.write_text(re.sub(r'\nmemory = "[^"]*"', "", config.read_text())
                          .replace('repos = ["packs", "memory"]', 'repos = ["packs"]'))
        os.environ["KEEL_CONFIG"] = str(self.home / "config.toml")
        self.checkout = fake_checkout(self.dir / "checkout")

    def move(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = movepersonal.main(["--checkout", str(self.checkout), *argv])
        return code, out.getvalue()


class MoveTest(MoveCase):
    def test_a_dry_run_writes_nothing_and_says_each_file(self):
        before = (self.home / "config.toml").read_text()
        code, said = self.move("--dry-run")
        self.assertEqual(code, 0, said)
        self.assertIn("dry run: nothing is written", said)
        self.assertIn(f"  copy  pack.toml -> {self.home / 'packs' / 'work' / 'pack.toml'}", said)
        self.assertIn(f"  copy  said-today.md -> {self.home / 'memory' / 'talker' / 'said-today.md'}", said)
        self.assertIn('  carry [backup] extra = ["harbor", "helm"]', said)
        self.assertFalse((self.home / "packs" / "work").exists())
        self.assertFalse((self.home / "memory").exists())
        self.assertEqual((self.home / "config.toml").read_text(), before)

    def test_it_copies_everything_never_over_what_is_there_and_deletes_nothing(self):
        write(self.home / "segments" / "daybook" / "segment.md", "the install's own\n")
        code, said = self.move()
        self.assertEqual(code, 0, said)
        self.assertEqual((self.home / "segments" / "daybook" / "segment.md").read_text(), "the install's own\n")
        self.assertIn(f"  skip  segment.md (already at {self.home / 'segments' / 'daybook' / 'segment.md'})", said)
        for name in movepersonal.SEGMENTS[1:]:
            self.assertTrue((self.home / "segments" / name / "segment.md").is_file(), name)
        self.assertEqual((self.home / "memory" / "bosun" / "MEMORY.md").read_text(), "the owner's Bosun index\n")
        self.assertEqual((self.home / "memory" / "talker" / "said-today.md").read_text(), "an uncommitted lesson\n")
        self.assertEqual((self.home / "identity" / "about-me.md").read_text(), "the owner\n")
        self.assertEqual((self.home / "history" / "docs" / "decisions.md").read_text(), "decided\n")
        self.assertTrue(os.access(self.home / "packs" / "work" / "verbs" / "card", os.X_OK), "a verb stays executable")
        # nothing left the checkout
        self.assertTrue((self.checkout / "bosun" / "memory" / "MEMORY.md").is_file())
        self.assertTrue((self.checkout / "packs" / "work" / "pack.toml").is_file())
        # the memory repo and the packs repo hold what came in, committed
        self.assertEqual(git(self.home / "memory", "status", "--porcelain"), "")
        self.assertIn("bosun/MEMORY.md", git(self.home / "memory", "ls-files"))
        self.assertEqual(git(self.home / "packs", "status", "--porcelain"), "")
        self.assertIn("work/pack.toml", git(self.home / "packs", "ls-files"))

    def test_settings_the_install_lacks_are_carried_and_its_own_are_kept(self):
        text = (self.home / "config.toml").read_text() + '\n[backup]\nsets = ["keel"]\n'
        (self.home / "config.toml").write_text(text)
        code, said = self.move()
        self.assertEqual(code, 0, said)
        mine = tomllib.loads((self.home / "config.toml").read_text())
        example = tomllib.loads(text)
        # r1.F5: only `extra` crosses; the install's own sets (its board) and its store stay
        self.assertEqual(mine["backup"], {"sets": ["keel"], "extra": ["harbor", "helm"]})
        self.assertEqual(mine["models"]["converse"], example.get("models", {}).get("converse", "claude-sonnet-x"))
        self.assertEqual(mine["voice"]["vad_hangover"], example["voice"]["vad_hangover"],
                         "a setting the install has is the install's")
        self.assertIn("  keep  [voice] vad_hangover (the install already sets it)", said)

    def test_the_extra_sets_come_from_a_host_tables_backup_sets_too(self):
        """r1.F5: an old two-machine config named its sets under `[hosts.<name>]`."""
        old = OLD_TOML.replace('[backup]\nsets = ["harbor", "helm", "code"]\npull = true\n', "")
        (self.checkout / "keel.toml").write_text(old + '\n[hosts.mac]\nbackup_sets = ["harbor", "code"]\n')
        code, said = self.move()
        self.assertEqual(code, 0, said)
        self.assertEqual(tomllib.loads((self.home / "config.toml").read_text())["backup"], {"extra": ["harbor"]})

    def test_a_machine_key_and_a_suite_for_a_repo_the_install_lacks_are_not_carried(self):
        """The install's [machine] holds its own ports and addresses, and a suite named for a
        repo the install does not list would name a repo it does not have (c-621)."""
        old = OLD_TOML.replace("[voice]\n", "[voice]\nport = 4390\n")
        (self.checkout / "keel.toml").write_text(old + '\n[tests]\nkeel = "make test"\npacks = "make check"\n')
        code, said = self.move()
        self.assertEqual(code, 0, said)
        mine = tomllib.loads((self.home / "config.toml").read_text())
        self.assertNotEqual(mine["voice"].get("port"), 4390)
        self.assertNotIn("keel", mine.get("tests", {}))
        self.assertEqual(mine["tests"]["packs"], "make check", "the install lists packs")
        self.assertIn("  skip  [voice] port (a machine key: the install's [machine] says it)", said)
        self.assertIn("  skip  [tests] keel (no repo keel in this install)", said)

    def test_a_refused_settings_write_still_leaves_what_was_copied_committed(self):
        """r1.F3: the copies are committed before the settings are written, and a rerun
        commits what an earlier run copied and did not commit; the talker's own writes stay out."""
        from keel import setupconfig
        with mock.patch.object(movepersonal.setupconfig, "edit",
                               side_effect=setupconfig.SetupError("the config moved under us")):
            code, _ = self.move()
        self.assertEqual(code, 1)
        self.assertEqual(git(self.home / "memory", "status", "--porcelain"), "")
        # a copy that a crash left uncommitted is committed by the next run
        git(self.home / "memory", "rm", "-q", "--cached", "bosun/MEMORY.md")
        git(self.home / "memory", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
            "commit", "-qm", "lost")
        write(self.home / "memory" / "talker" / "new-today.md", "the talker's own\n")
        code, said = self.move()
        self.assertEqual(code, 0, said)
        self.assertEqual(git(self.home / "memory", "status", "--porcelain"), "?? talker/new-today.md")
        self.assertIn("bosun/MEMORY.md", git(self.home / "memory", "ls-files"))

    def test_a_second_run_copies_nothing(self):
        self.move()
        code, said = self.move()
        self.assertEqual(code, 0, said)
        self.assertIn("copied 0 files", said)
        self.assertNotIn("  copy  ", said)

    def test_a_rerun_never_commits_a_moved_file_edited_since(self):
        """Fix check 3: a rerun commits only what the move placed and that still matches its
        source byte for byte (or is new this run); an edit since, by the talker or by hand,
        stays uncommitted for him to review."""
        self.move()
        edited = self.home / "memory" / "talker" / "said-today.md"
        edited.write_text("the talker wrote more since\n")
        write(self.checkout / "talker" / "memory" / "new-lesson.md", "learned after the first move\n")
        code, said = self.move()
        self.assertEqual(code, 0, said)
        self.assertEqual(git(self.home / "memory", "status", "--porcelain"), "M talker/said-today.md")
        self.assertIn("talker/new-lesson.md", git(self.home / "memory", "ls-files"))

    def test_the_moved_memory_is_listed_as_the_installs_own_repo(self):
        """r1.F1: once the memory repo is in the install, it is a personal repo the builder
        builds, the way packs is, so a change to it is a card; listed once, never by a dry run."""
        before = (self.home / "config.toml").read_text()
        self.move("--dry-run")
        self.assertEqual((self.home / "config.toml").read_text(), before)
        code, said = self.move()
        self.assertEqual(code, 0, said)
        self.assertIn(f"  list  memory = {self.home / 'memory'}", said)
        mine = tomllib.loads((self.home / "config.toml").read_text())
        self.assertEqual(mine["spaces"]["personal"]["repos"]["memory"], str(self.home / "memory"))
        self.assertEqual(sorted(mine["builder"]["repos"]), ["memory", "packs"])
        listed = (self.home / "config.toml").read_text()
        self.move()
        self.assertEqual((self.home / "config.toml").read_text(), listed)
        self.assertEqual(init(self.home), 0, "init after the move keeps the listing")
        self.assertEqual(tomllib.loads((self.home / "config.toml").read_text())["builder"]["repos"],
                         mine["builder"]["repos"])

    def test_the_talkers_rulebook_moves_beside_its_memory(self):
        """c-722 landing B: the config dir's CLAUDE.md leaves the tree; it is the talker's
        own, so it is copied to `memory/talker/CLAUDE.md` and committed with the memory."""
        write(self.checkout / "spaces" / "harbor" / ".claude" / "CLAUDE.md", "the owner's talker rules\n")
        code, said = self.move()
        self.assertEqual(code, 0, said)
        self.assertEqual((self.home / "memory" / "talker" / "CLAUDE.md").read_text(), "the owner's talker rules\n")
        self.assertIn("talker/CLAUDE.md", git(self.home / "memory", "ls-files"))

    def test_a_space_file_the_tree_no_longer_carries_is_pointed_at_its_copy(self):
        """c-722 landing B: the work space's pipeline named `adapters/work/...`, which leaves
        the tree with the pack, and the personal contract carried one owner's own rules. The
        pipeline points at the install's pack, the changed contract is copied and pointed
        at, and a contract the checkout left as shipped is left as it is."""
        write(self.checkout / "packs" / "work" / "pipeline.md", "the pack's pipeline\n")
        shipped = Path(movepersonal.__file__).resolve().parent.parent / "etc" / "space-personal.md"
        write(self.checkout / "etc" / "space-personal.md", shipped.read_text() + "\n## The owner's rules\n")
        write(self.checkout / "etc" / "space-work.md", (shipped.parent / "space-work.md").read_text())
        config = self.home / "config.toml"
        self.assertEqual(tomllib.loads(config.read_text())["spaces"]["personal"]["contract"], "etc/space-personal.md")
        config.write_text(config.read_text() + '\n[spaces.work]\nconfig_dir = "~/x"\ncontract = "etc/space-work.md"\n'
                          'pipeline = "adapters/work/pipeline.md"\n')
        code, said = self.move("--dry-run")
        self.assertEqual(code, 0, said)
        self.assertIn(f"  point [spaces.work] pipeline = {self.home / 'packs' / 'work' / 'pipeline.md'}", said)
        self.assertEqual(tomllib.loads(config.read_text())["spaces"]["work"]["pipeline"], "adapters/work/pipeline.md")
        code, said = self.move()
        self.assertEqual(code, 0, said)
        spaces = tomllib.loads(config.read_text())["spaces"]
        self.assertEqual(spaces["work"]["pipeline"], str(self.home / "packs" / "work" / "pipeline.md"))
        own = self.home / "spaces" / "personal" / "space-personal.md"
        self.assertEqual(spaces["personal"]["contract"], str(own))
        self.assertTrue(own.read_text().endswith("## The owner's rules\n"))
        self.assertEqual(spaces["work"]["contract"], "etc/space-work.md", "a shipped contract stays the code's")
        code, said = self.move()
        self.assertNotIn("  point ", said, "pointed once")

    def test_the_old_config_is_kept_whole_in_history(self):
        """r1.F11: only some settings are carried, so the tracked config itself is kept."""
        code, said = self.move()
        self.assertEqual(code, 0, said)
        self.assertEqual((self.home / "history" / "keel.toml").read_text(), OLD_TOML)

    def test_the_talkers_skill_links_are_recorded_once(self):
        """r1.F3: the tracked skill links leave the tree; their names and targets are kept in
        the install's talker memory, committed, and never written over."""
        skills = self.checkout / "spaces" / "harbor" / ".claude" / "skills"
        skills.mkdir(parents=True)
        (skills / "lavish").symlink_to("/elsewhere/skills/lavish", target_is_directory=True)
        git(self.checkout, "add", "-A")
        git(self.checkout, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "skills")
        self.assertEqual(movepersonal.pending(self.cfg(), self.checkout, self.checkout)[-1:],
                         [f"the talker's skill links are not recorded in {self.home / 'memory' / 'talker' / 'skills.json'} yet"])
        code, said = self.move()
        self.assertEqual(code, 0, said)
        record = self.home / "memory" / "talker" / "skills.json"
        self.assertEqual(json.loads(record.read_text()), {"lavish": "/elsewhere/skills/lavish"})
        self.assertIn("talker/skills.json", git(self.home / "memory", "ls-files"))
        self.assertEqual(movepersonal.pending(self.cfg(), self.checkout, self.checkout), [])
        code, said = self.move()
        self.assertIn("  skip  skills.json", said)

    def test_a_move_from_the_code_that_carries_nothing_is_refused_naming_the_checkout(self):
        """r1.F10: run with no --checkout from code that no longer holds the owner's things
        (a scratch tree stands in for it, as the package root and KEEL_HOME both), a move
        would copy nothing; while the install lacks the rulebook it is refused."""
        from keel import config as config_module
        code_root = self.dir / "code"
        code_root.mkdir()
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"KEEL_HOME": str(code_root)}), \
                mock.patch.object(config_module, "package_root", return_value=code_root), \
                mock.patch("sys.stderr", err), redirect_stdout(io.StringIO()):
            code = movepersonal.main([])
            self.assertEqual(code, 1)
            self.assertIn("--checkout", err.getvalue())
            self.assertFalse((self.home / "memory").exists(), "nothing was written")
            (self.home / "memory" / "talker").mkdir(parents=True)
            (self.home / "memory" / "talker" / "CLAUDE.md").write_text("the user's rules\n")
            self.assertEqual(movepersonal.main([]), 0, "no longer refused once the install holds it")

    def test_a_real_run_that_would_clear_nothing_the_install_lacks_is_refused(self):
        """r3.F6: --checkout naming a tree that carries nothing (the tree after the removal,
        a wrong directory) while the checkout the install runs still holds things to move:
        refused, naming --checkout. A dry run is never refused; it says a real one would be."""
        empty = self.dir / "after-the-removal"
        empty.mkdir()
        err, out = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"KEEL_HOME": str(self.checkout)}), \
                mock.patch("sys.stderr", err), redirect_stdout(out):
            code = movepersonal.main(["--checkout", str(empty)])
            self.assertEqual(code, 1)
            self.assertIn("would copy nothing", err.getvalue())
            self.assertIn("--checkout", err.getvalue())
            self.assertIn("the work pack", err.getvalue(), "it says what the install still lacks")
            self.assertFalse((self.home / "packs" / "work").exists(), "nothing was written")
            self.assertEqual(movepersonal.main(["--checkout", str(empty), "--dry-run"]), 0)
        self.assertIn("A real run would be refused", out.getvalue())
        code, said = self.move()
        self.assertEqual(code, 0, said)

    def test_a_skills_record_the_install_removed_on_purpose_is_never_brought_back(self):
        """r3.F7: skills.json counts as held once the memory repo held it, in the move and in
        what the deploy asks of it."""
        skills = self.checkout / "spaces" / "harbor" / ".claude" / "skills"
        skills.mkdir(parents=True)
        (skills / "lavish").symlink_to("/elsewhere/skills/lavish", target_is_directory=True)
        git(self.checkout, "add", "-A")
        git(self.checkout, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "skills")
        self.move()
        git(self.home / "memory", "rm", "-q", "talker/skills.json")
        git(self.home / "memory", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "no skills")
        code, said = self.move()
        self.assertEqual(code, 0, said)
        self.assertFalse((self.home / "memory" / "talker" / "skills.json").exists())
        self.assertIn("skills.json (memory held it once and removed it since; kept removed)", said)
        self.assertEqual(movepersonal.pending(self.cfg(), self.checkout, self.checkout), [])

    def test_a_file_the_install_removed_on_purpose_is_never_brought_back(self):
        """r2.F4: the memory repo once held it and removed it since; a later move (or the
        deploy's preflight, which asks `pending`) counts it as held."""
        self.move()
        git(self.home / "memory", "rm", "-q", "talker/said-today.md")
        git(self.home / "memory", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "forgotten")
        code, said = self.move()
        self.assertEqual(code, 0, said)
        self.assertFalse((self.home / "memory" / "talker" / "said-today.md").exists())
        self.assertIn("said-today.md (memory held it once and removed it since; kept removed)", said)
        self.assertEqual(movepersonal.pending(self.cfg(), self.checkout, self.checkout), [])

    def cfg(self):
        from keel import config as config_module
        return config_module.load(ensure=False)

    def test_a_config_that_is_not_an_install_is_refused(self):
        os.environ["KEEL_CONFIG"] = str(self.checkout / "keel.toml")
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            code, _ = self.move()
        self.assertEqual(code, 1)
        self.assertIn("run it from the install", err.getvalue())


if __name__ == "__main__":
    unittest.main()
