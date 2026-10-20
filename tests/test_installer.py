"""`shipyard init` (keel/installer.py): the core promise is that an install is made under the
directory chosen, and that running init again repairs without writing over a user's config
or board. Everything else init does (the checks, the login, the services, the doctor) is
proven by running it on a clean user; see docs/atlas/88-install.md.
"""

import contextlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import config as config_module
from keel import installer
from keel.board import Board


def init(home: Path) -> int:
    with mock.patch.object(installer.prereqs, "gather", return_value=[]), \
         mock.patch.object(installer.Init, "doctor"):
        return installer.Init(home, services="none", probe_login=False, open_deck=False,
                              say=lambda line: None).run()


def git(repo: Path, *argv: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *argv], capture_output=True, text=True,
                          check=True).stdout.strip()


class InitTest(unittest.TestCase):
    def test_init_makes_the_install_and_a_second_run_keeps_config_and_board(self):
        with tempfile.TemporaryDirectory() as scratch, mock.patch.dict(os.environ):
            home = Path(scratch).resolve() / "install"
            self.assertEqual(init(home), 0)

            cfg = config_module.load(home / "config.toml")
            self.assertEqual(cfg.state_dir, home / "state")
            self.assertEqual({space.config_dir for space in cfg.spaces.values()}, {home / "claude"})
            self.assertNotIn(cfg.serve_port, installer.RESERVED)
            # c-618: a fresh install lists no repo of the user's; Setup in the deck adds them.
            # c-619: only its own packs repo, which the in-app builder builds from its clone, and
            # (c-722) its own memory repo, seeded from the templates now the code holds no memory.
            self.assertEqual({name: space.repos for name, space in cfg.spaces.items()},
                             {"personal": {"packs": home / "packs", "memory": home / "memory"}})
            self.assertEqual(git(home / "packs", "branch", "--show-current"), "main")
            # c-621: no suite, retest or integration branch for a repo the install lacks.
            self.assertEqual((cfg.repo_tests, cfg.house_tests, cfg.integration, cfg.repo_retests,
                              cfg.deploy_tests), ({}, {}, {}, {}, {}))
            self.assertIn("[integration]", (home / "config.toml").read_text())
            self.assertEqual(git(home / "builder" / "packs", "remote", "get-url", "origin"), str(home / "packs"))
            key = home / "credentials" / "house-key"
            self.assertEqual((key.stat().st_mode & 0o777, key.parent.stat().st_mode & 0o777), (0o600, 0o700))
            minted = key.read_text()
            trusted = json.loads((home / "claude" / ".claude.json").read_text())["projects"]
            self.assertTrue(trusted[str(home)]["hasTrustDialogAccepted"])

            mine = (home / "config.toml").read_text() + "\n# his own edit\n"
            (home / "config.toml").write_text(mine)
            with Board(cfg.db_path) as board:
                card = board.create("personal", "kept across a re-run")
            (home / "bin" / "shipyard").unlink()

            self.assertEqual(init(home), 0)
            self.assertEqual((home / "config.toml").read_text(), mine)
            self.assertEqual(key.read_text(), minted, "a re-run keeps the install's key")
            self.assertTrue((home / "builder" / "packs" / ".git").is_dir())
            with Board(cfg.db_path) as board:
                self.assertEqual(board.get(card)["title"], "kept across a re-run")
            self.assertTrue(os.access(home / "bin" / "shipyard", os.X_OK))


class DefaultsTest(unittest.TestCase):
    def test_a_new_install_records_no_voice_and_backs_up_only_keels_own_sets(self):
        """c-722: recording every utterance is a choice the user makes, never a default;
        and the shipped example names no set that is one owner's."""
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
            home = Path(tmp).resolve() / "install"
            self.assertEqual(init(home), 0)
            cfg = config_module.load(home / "config.toml")
        self.assertFalse(cfg.voice_record)
        self.assertTrue(set(cfg.backup_sets) <= set(config_module.BACKUP_SETS), cfg.backup_sets)
        example = (installer.code_root() / installer.EXAMPLE).read_text()
        self.assertNotIn("harbor", example.split("[backup]")[1].split("\n[")[0])


class MemoryTest(unittest.TestCase):
    """c-722: the install's memory is seeded from the templates by init, once."""

    def run_init(self, home: Path) -> list[str]:
        said = []
        with mock.patch.dict(os.environ), \
                mock.patch.object(installer.prereqs, "gather", return_value=[]), \
                mock.patch.object(installer.Init, "doctor"):
            installer.Init(home, services="none", probe_login=False, open_deck=False,
                           say=said.append).run()
        return said

    def test_init_seeds_the_memory_once_when_the_checkout_holds_none(self):
        nowhere = {part: Path("no-such") / part for part in installer.memoryroot.PARTS}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(installer.memoryroot.CHECKOUT, nowhere):
            home = Path(tmp).resolve() / "install"
            said = self.run_init(home)
            self.assertIn(f"Memory:  {home / 'memory'} (seeded bosun, talker, identity from the templates)", said)
            self.assertTrue((home / "memory" / "bosun" / "MEMORY.md").is_file())
            self.assertEqual(git(home / "memory", "status", "--porcelain"), "")
            (home / "memory" / "bosun" / "MEMORY.md").write_text("mine\n")
            said = self.run_init(home)
            self.assertIn(f"Memory:  {home / 'memory'} (kept)", said)
            self.assertEqual((home / "memory" / "bosun" / "MEMORY.md").read_text(), "mine\n")

    def test_a_seeded_memory_is_the_installs_own_repo_beside_packs(self):
        """r1.F1: the memory repo is listed the way packs is, a personal repo the builder
        builds from its own clone, so a change to it is a card that lands by Approve outcome."""
        nowhere = {part: Path("no-such") / part for part in installer.memoryroot.PARTS}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(installer.memoryroot.CHECKOUT, nowhere):
            home = Path(tmp).resolve() / "install"
            self.run_init(home)
            cfg = config_module.load(home / "config.toml")
            self.assertEqual(cfg.spaces["personal"].repos, {"packs": home / "packs", "memory": home / "memory"})
            self.assertEqual(sorted(installer.builder.repos(cfg)), ["memory", "packs"])
            self.assertEqual(git(home / "builder" / "memory", "remote", "get-url", "origin"), str(home / "memory"))
            listed = (home / "config.toml").read_text()
            self.run_init(home)
            self.assertEqual((home / "config.toml").read_text(), listed, "a re-run lists it once")

    def test_no_memory_repo_is_listed_while_the_checkout_holds_the_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = Path(tmp) / "code"
            for rel in installer.memoryroot.CHECKOUT.values():
                (code / rel).mkdir(parents=True)
                (code / rel / "MEMORY.md").write_text("old\n")
            home = Path(tmp).resolve() / "install"
            home.mkdir()
            installer.memory_line(home, code)
            self.assertEqual(installer.builder.own_repos(home), {"packs": home / "packs"})

    def test_init_on_a_checkout_that_carries_memory_says_to_move_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = Path(tmp) / "code"
            for rel in installer.memoryroot.CHECKOUT.values():
                (code / rel).mkdir(parents=True)
            (code / "bosun" / "memory" / "MEMORY.md").write_text("old\n")
            home = Path(tmp).resolve() / "install"
            home.mkdir()
            line = installer.memory_line(home, code)
            self.assertFalse((home / "memory").exists())
        self.assertEqual(line, f"Memory:  read from the checkout at {code} for bosun until "
                               f"`shipyard move-personal` brings it into {home}")


@contextlib.contextmanager
def only_this_config(file: Path):
    """git reading `file` as its global config and nothing else: no system file, and none
    of the author the suite's fence puts in the environment (tests/fence.py)."""
    with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(file), "GIT_CONFIG_NOSYSTEM": "1"}):
        for name in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
            os.environ.pop(name, None)
        yield


class PrereqTest(unittest.TestCase):
    PAGE_LINE = ("       Required, and the install goes on: the setup page asks for it on "
                 "Check this computer (two fields and Save).")

    def run_init(self, home: Path, checks: list) -> tuple[int, list[str]]:
        said = []
        with mock.patch.dict(os.environ), \
                mock.patch.object(installer.prereqs, "gather", return_value=checks), \
                mock.patch.object(installer.Init, "doctor"):       # init changes its process's environment
            code = installer.Init(home, services="none", probe_login=False, open_deck=False,
                                  say=said.append).run()
        return code, "\n".join(str(line) for line in said).splitlines()

    def test_init_leaves_the_environment_of_its_caller_as_it_was(self):
        """Review F9: `run` clears and sets KEEL_ variables for its own process."""
        unset = subprocess.CompletedProcess([], 1, "", "")
        with mock.patch.dict(os.environ, {"KEEL_CARD": "c-1"}), tempfile.TemporaryDirectory() as tmp:
            before = dict(os.environ)
            with mock.patch.object(installer.prereqs.shutil, "which", return_value=None):
                check = installer.prereqs.claude_check()[0]
            self.run_init(Path(tmp) / "install", [check])
            self.assertEqual(dict(os.environ), before)

    def test_no_identity_is_required_and_the_doctor_says_where_to_set_it(self):
        """c-621: without it every landing failed at the merge commit. It is required (the
        page's Next waits for it, the doctor names it) and it does not stop init (c-679)."""
        unset = subprocess.CompletedProcess([], 1, "", "")
        check = installer.prereqs.identity_check(runner=lambda argv: unset)
        self.assertEqual(installer.prereqs.missing([check]), [check])
        self.assertEqual(installer.prereqs.blocking([check]), [])
        self.assertEqual(check["command"], "", "no name or email is printed to paste")
        report = {"config": {"ok": True}, "claude": {"ok": True}, "git_identity": check}
        self.assertIn("Your name and email for git: Git on this computer has no name and email set. When work "
                      "lands, git records who merged it (Type them into the two fields on the setup page's "
                      "Check this computer step, and press Save.)", installer.doctor.problems(report))
        report["config"]["path"] = "/i/config.toml"
        report["claude"].update(path="/bin/claude", version="2.1.0")
        self.assertIn("git identity  Your name and email for git: Git on this computer has no name and email "
                      "set. When work lands, git records who merged it", installer.doctor.render(report).splitlines())
        set_one = dict(check, ok=True, said="Maya Okafor <maya@example.com>")
        self.assertIn("git identity  Maya Okafor <maya@example.com>",
                      installer.doctor.render(dict(report, git_identity=set_one)).splitlines())

    def test_the_doctor_on_a_machine_with_no_git_says_git_is_missing_and_nothing_of_the_identity(self):
        """With no git there is no identity to read: the doctor shares gather's guard
        (`prereqs.git_checks`), so it says the git check's own sentence and fix."""
        real = installer.prereqs.shutil.which
        miss = "git: Git is not installed on this computer. Shipyard cuts a working copy for each card and lands its work with git"
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
            home = Path(tmp) / "install"
            self.assertEqual(init(home), 0)
            # the doctor asks the service manager which drains run and whether the user
            # lingers: both answered here, so no test reaches launchctl, systemctl or loginctl
            with mock.patch.object(installer.doctor.drainprobe, "drains", return_value=([], [])), \
                    mock.patch.object(installer.doctor.service, "linger_report", return_value={"applicable": False}), \
                    mock.patch.object(installer.prereqs.shutil, "which",
                                      lambda name, *rest, **more: None if name == "git" else real(name, *rest, **more)):
                fix = installer.prereqs.fix_words(installer.prereqs.git_check())
                report = installer.doctor.gather(home / "config.toml", single=True, probe_logins=False)
                checks = installer.prereqs.gather()
        self.assertNotIn("git_identity", report)
        self.assertIn(f"{miss} ({fix})", installer.doctor.problems(report))
        lines = installer.doctor.render(report).splitlines()
        self.assertIn(f"git           {miss}", lines)
        self.assertFalse(any(line.startswith("git identity") or "name and email" in line for line in lines), lines)
        self.assertNotIn("git identity", [check["name"] for check in checks], "the same guard as the page and init")

    def test_an_install_with_no_name_and_email_completes_and_says_the_page_asks(self):
        """c-679: the fields on Check this computer are reachable on a first install. The
        global file is an empty temp file, so the packs commit is made with none set."""
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "gitconfig"
            empty.write_text("")
            with only_this_config(empty):
                check = installer.prereqs.identity_check()
                self.assertFalse(check["ok"])
                home = Path(tmp) / "install"
                code, lines = self.run_init(home, [check])
                self.assertEqual(code, 0, lines)
                self.assertTrue((home / "config.toml").is_file())
                self.assertEqual(git(home / "packs", "log", "-1", "--format=%an"), "Shipyard")
                self.assertEqual(empty.read_text(), "", "init never sets the user's name and email")
        for part in ("       What happened: Git on this computer has no name and email set. "
                     "When work lands, git records who merged it.",
                     "       The fix: Type them into the two fields on the setup page's Check this computer "
                     "step, and press Save.", self.PAGE_LINE):
            self.assertIn(part, lines)
        self.assertFalse(any(line.startswith("Stopped") for line in lines), lines)

    def test_only_the_email_set_still_commits_the_packs_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            half = Path(tmp) / "gitconfig"
            half.write_text("[user]\n\temail = maya@example.com\n")
            with only_this_config(half):
                installer.packs_repo(Path(tmp) / "packs")
                self.assertEqual(git(Path(tmp) / "packs", "log", "-1", "--format=%an <%ae>"),
                                 "Shipyard <shipyard@localhost>")

    def test_another_required_miss_stops_init_and_is_said_in_three_parts(self):
        """c-679: what happened, the fix with its command, and that it is required, as the
        deck's Check this computer step says them."""
        unset = subprocess.CompletedProcess([], 1, "", "")
        with mock.patch.object(installer.prereqs.shutil, "which",
                               lambda name: "/bin/npm" if name == "npm" else None):
            check = installer.prereqs.claude_check()[0]
        identity = installer.prereqs.identity_check(runner=lambda argv: unset)
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "install"
            code, lines = self.run_init(home, [identity, check])
            self.assertFalse(home.exists(), "nothing is made on a machine that misses a required check")
        self.assertEqual(code, 1)
        for part in ("       What happened: Claude Code is not installed on this computer. "
                     "Shipyard runs every session with it.",
                     "       The fix: " + installer.prereqs.CLAUDE_FIX + " " + installer.prereqs.CLAUDE_NPM,
                     "           curl -fsSL https://claude.ai/install.sh | bash",
                     "       Required: setup stops until this is fixed.", self.PAGE_LINE):
            self.assertIn(part, lines)
        self.assertIn("Stopped: 1 thing to fix first. Do the fix above, then run this command again.", lines)


if __name__ == "__main__":
    unittest.main()
