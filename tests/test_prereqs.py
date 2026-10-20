"""The machine's checks (keel/prereqs.py, c-679): every check that fails carries what
happened, the fix (with a command to copy where one command does it) and whether it is
required, the installer's line says those three parts, and git's name and email are written
to git's global setting, only where git has none, and read back. git's global file is a temp
file throughout, inside a patch of the environment that is undone."""

import contextlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import prereqs

UNSET = subprocess.CompletedProcess([], 1, "", "")
DONE = subprocess.CompletedProcess([], 0, "", "")
OLD_HELP = subprocess.CompletedProcess([], 0, "Usage: claude [options]\n  --print\n", "")
BG = "claude --bg (background sessions)"
NODE = "node, for the house browser (bin/keel-browser)"
IDENTITY_FIX = "Type them into the two fields on the setup page's Check this computer step, and press Save."


def failing(platform: str = "darwin", npm: bool = False) -> dict[str, dict]:
    """One failing reading of every check by name, each through the check's own function,
    as `platform` would read it, with npm on PATH or not."""
    def which(name):
        return "/bin/npm" if npm and name == "npm" else None
    with mock.patch.object(prereqs.sys, "platform", platform), mock.patch.object(prereqs, "job_path", return_value=()):
        with mock.patch.object(prereqs.shutil, "which", which):
            tools = [check for check in prereqs.gather(["browser"]) if not check["ok"]]
        with mock.patch.object(prereqs.shutil, "which", return_value="/bin/claude"), \
                mock.patch.object(prereqs, "run", return_value=OLD_HELP):
            features = [check for check in prereqs.claude_check() if not check["ok"]]
        with mock.patch.dict("sys.modules", {"sqlite3": None}):
            sqlite = prereqs.sqlite_check()
        found = [prereqs.os_check("win32"), prereqs.python_check((3, 9, 0)), sqlite,
                 prereqs.identity_check(runner=lambda argv: UNSET), prereqs.wsl_check(2, False),
                 *tools, *features]
    return {check["name"]: check for check in found}


class ThreePartsTest(unittest.TestCase):
    def test_every_failing_check_says_what_happened_the_fix_and_whether_it_is_required(self):
        found = failing()
        self.assertEqual(set(found), {"os", "python", "sqlite3", "git", "git identity", "wsl systemd", "claude", BG,
                                      "claude agents --json (the session list)", NODE, "gpg"})
        for check in found.values():
            with self.subTest(check=check["name"]):
                self.assertFalse(check["ok"])
                self.assertTrue(check["label"])
                self.assertRegex(check["what"], r"^[A-Z].*\.$")
                self.assertRegex(check["fix"], r"^[A-Z].*\.$")
                self.assertIs(check["required"], check["name"] != "gpg", "gpg alone is for backup, not to install")

    def test_a_command_homebrew_or_xcode_gives_is_carried_on_macos_only(self):
        self.assertEqual(prereqs.mac_only("x", "darwin"), "x")
        self.assertEqual(prereqs.mac_only("x", "linux"), "")
        mac, linux = failing("darwin"), failing("linux")
        self.assertEqual({name: mac[name]["command"] for name in ("git", "python", "sqlite3", NODE)},
                         {"git": "xcode-select --install", "python": "brew install python",
                          "sqlite3": "brew install python", NODE: "brew install node"})
        self.assertEqual({name: linux[name]["command"] for name in ("git", "python", "sqlite3", NODE)},
                         {"git": "", "python": "", "sqlite3": "", NODE: ""})
        self.assertEqual((mac[BG]["command"], linux[BG]["command"]), ("claude update", "claude update"))
        self.assertEqual(mac["os"]["command"], "", "no command changes the operating system")

    def test_claude_codes_fix_leads_with_the_native_installer_and_npm_is_the_root_fallback(self):
        """c-729: npm's global install fails for a user without root (EACCES), so the one
        command is the native installer, which needs none; the fix says how to get its folder
        on PATH, and names npm only where npm is, as the fallback for a user with root."""
        with_npm, without = failing(npm=True)["claude"], failing(npm=False)["claude"]
        self.assertEqual((with_npm["command"], without["command"]), (prereqs.CLAUDE_INSTALL,) * 2)
        self.assertEqual(prereqs.CLAUDE_INSTALL, "curl -fsSL https://claude.ai/install.sh | bash")
        self.assertEqual(without["fix"], prereqs.CLAUDE_FIX)
        self.assertEqual(with_npm["fix"], prereqs.CLAUDE_FIX + " " + prereqs.CLAUDE_NPM)
        self.assertIn('export PATH="$HOME/.local/bin:$PATH"', prereqs.CLAUDE_FIX)
        self.assertTrue(prereqs.CLAUDE_NPM.startswith("If you are root"), prereqs.CLAUDE_NPM)
        self.assertIn("npm install -g @anthropic-ai/claude-code", prereqs.CLAUDE_NPM)

    def test_no_check_prints_a_name_or_an_email_to_paste(self):
        """A pasted placeholder would pass the check as a real identity, so none is printed."""
        check = failing()["git identity"]
        self.assertEqual((check["fix"], check["command"]), (IDENTITY_FIX, ""))
        printed = " ".join(prereqs.line(item) + prereqs.fix_words(item) for item in failing().values())
        for word in ("Your Name", "you@example.com", "user.name \"", "user.email \""):
            self.assertNotIn(word, printed)

    def test_a_help_probe_that_did_not_answer_could_not_be_checked_not_too_old(self):
        def run(argv):
            return subprocess.CompletedProcess(argv, 0, "2.1.0\n", "") if argv[-1] == "--version" else None
        with mock.patch.object(prereqs.shutil, "which", return_value="/bin/claude"), \
                mock.patch.object(prereqs, "run", run):
            check = prereqs.claude_check()[1]
        self.assertEqual((check["ok"], check["said"], check["command"]), (False, "could not be checked", ""))
        self.assertEqual(check["what"], "Claude Code did not answer when asked for its help, so this could not "
                                        "be checked. Shipyard starts every session that way.")
        self.assertEqual(check["fix"], "Check again. If it keeps happening, update Claude Code.")

    def test_a_passing_check_carries_no_fix(self):
        check = prereqs.os_check("darwin")
        self.assertEqual((check["ok"], check["label"], check["what"], check["fix"], check["command"]),
                         (True, "Operating system", "", "", ""))

    def test_the_line_for_a_miss_says_the_three_parts(self):
        found = failing()
        self.assertEqual(prereqs.line(found[BG]).splitlines(), [
            "  MISS Claude Code can run sessions in the background: missing from --help",
            "       What happened: Claude Code on this computer is too old to run sessions in the background. "
            "Shipyard starts every session that way.",
            "       The fix: Update Claude Code.",
            "           claude update",
            "       Required: setup stops until this is fixed."])
        self.assertEqual(prereqs.line(found["git identity"]).splitlines(), [
            "  MISS Your name and email for git: user.name and user.email not set",
            "       What happened: Git on this computer has no name and email set. "
            "When work lands, git records who merged it.",
            "       The fix: " + IDENTITY_FIX,
            "       Required, and the install goes on: the setup page asks for it on "
            "Check this computer (two fields and Save)."])
        soft = dict(found[BG], required=False)
        self.assertEqual(prereqs.line(soft).splitlines()[-1], "       Not required: setup goes on without it.")
        self.assertEqual(prereqs.line(prereqs.os_check("darwin")), "  ok   Operating system: macOS")

    def test_only_a_miss_the_page_fixes_lets_init_go_on(self):
        found = failing()
        self.assertEqual(prereqs.blocking([found["git identity"], found[BG]]), [found[BG]])
        self.assertEqual(prereqs.missing([found["git identity"], found[BG]]), [found["git identity"], found[BG]])

    def test_the_fix_in_one_sentence_ends_with_its_command(self):
        found = failing()
        self.assertEqual(prereqs.fix_words(found[BG]), "Update Claude Code. `claude update`")
        self.assertEqual(prereqs.fix_words(found["git identity"]), IDENTITY_FIX)

    def test_a_miss_in_one_line_is_its_label_and_what_happened(self):
        """What readiness's row and the doctor say (review F2)."""
        self.assertEqual(prereqs.miss_words(failing()["git identity"]),
                         "Your name and email for git: Git on this computer has no name and email set. "
                         "When work lands, git records who merged it")
        self.assertEqual(prereqs.miss_words({"name": "git", "ok": False, "said": "not found"}), "git: not found")

    def test_wsl_is_asked_on_linux_only_passes_with_systemd_and_wsl1_is_told_to_convert(self):
        """c-804 review F2, F4: off Linux nothing is asked, whatever the environment says."""
        with mock.patch.object(prereqs.sys, "platform", "darwin"):
            self.assertIsNone(prereqs.wsl_check())
        self.assertIsNone(prereqs.wsl_check(0))
        self.assertTrue(prereqs.wsl_check(2, True)["ok"])
        wsl1 = prereqs.wsl_check(1, True)
        self.assertEqual((wsl1["ok"], wsl1["required"], wsl1["said"]), (False, True, "WSL1"))
        self.assertIn("wsl --set-version <distro> 2", wsl1["fix"])


class GpgTest(unittest.TestCase):
    """c-757: every backup copy is encrypted with gpg and nothing checked for it, so the
    first teammate's backup was turned on and never wrote a copy. It is a check of this
    computer now: for backup, never a reason an install stops."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.bin = Path(tmp.name) / "bin"
        self.bin.mkdir()

    def gpg(self, where: Path) -> Path:
        tool = where / "gpg"
        tool.write_text("#!/bin/sh\necho 'gpg (GnuPG) 2.4.7'\n")
        tool.chmod(0o755)
        return tool

    def check(self, elsewhere=None, platform="darwin") -> dict:
        with mock.patch.object(prereqs, "job_path", return_value=(str(self.bin),)), \
                mock.patch.object(prereqs.shutil, "which", return_value=elsewhere), \
                mock.patch.object(prereqs.sys, "platform", platform):
            return prereqs.gpg_check()

    def test_a_computer_with_no_gpg_says_so_with_its_fix_and_install_command(self):
        check = self.check()
        self.assertEqual((check["name"], check["label"], check["ok"], check["said"]),
                         ("gpg", "gpg, for backup", False, "not installed"))
        self.assertEqual(check["what"], "The gpg program is not installed on this computer. Shipyard encrypts every backup "
                                        "copy with it. It is needed only for Back up: the install and everything else "
                                        "work without it.")
        self.assertEqual(check["fix"], "Install gpg (on Linux, your package manager's gnupg), then press Check again.")
        self.assertEqual((check["command"], self.check(platform="linux")["command"]), ("brew install gnupg", ""))

    def test_it_is_never_a_reason_an_install_stops(self):
        check = self.check()
        self.assertIs(check["required"], False)
        self.assertEqual((prereqs.missing([check]), prereqs.blocking([check])), ([], []))
        self.assertEqual(prereqs.line(check).splitlines()[-1], "       Not required: setup goes on without it.")

    def test_it_is_one_of_this_computers_checks(self):
        with mock.patch.object(prereqs, "job_path", return_value=(str(self.bin),)), \
                mock.patch.object(prereqs.shutil, "which", return_value=None):
            self.assertEqual([check["name"] for check in prereqs.gather()][-1], "gpg")

    def test_gpg_where_the_backups_jobs_look_passes_with_its_version(self):
        tool = self.gpg(self.bin)
        check = self.check()
        self.assertEqual((check["ok"], check["said"], check["required"]),
                         (True, f"gpg (GnuPG) 2.4.7 ({tool})", False))

    def test_a_gpg_that_is_there_and_does_not_run_is_a_miss_with_its_own_words(self):
        """r1.F9: the tool asks `gpg --version` before every copy and dies when it fails, so a
        file named gpg that will not run (a broken link's target, the wrong architecture)
        must not pass the row and the turn-on."""
        tool = self.bin / "gpg"
        tool.write_text("#!/bin/sh\necho 'gpg: bad CPU type in executable' >&2\nexit 126\n")
        tool.chmod(0o755)
        check = self.check()
        self.assertEqual((check["ok"], check["said"], check["required"]), (False, "does not run", False))
        self.assertEqual(check["what"], f"The gpg program at {tool} does not run: gpg: bad CPU type in executable. "
                                        "Shipyard encrypts every backup copy with it. It is needed only for Back "
                                        "up: the install and everything else work without it.")
        self.assertEqual((check["fix"], check["command"]),
                         ("Install gpg again (on Linux, your package manager's gnupg), then press Check again.",
                          "brew install gnupg"))

    def test_gpg_only_this_shell_can_see_is_a_miss_that_says_where_it_is(self):
        """The hourly job is handed a fixed PATH: a gpg outside it cannot encrypt a copy."""
        other = self.bin.parent / "elsewhere"
        other.mkdir()
        check = self.check(elsewhere=str(self.gpg(other)))
        self.assertFalse(check["ok"])
        self.assertIn(f"The gpg program is at {other / 'gpg'}, where the backup's jobs do not look. They look in {self.bin}.",
                      check["what"])


@contextlib.contextmanager
def global_file(text: str = ""):
    """git reading a temp file holding `text` as its global config, and no system file."""
    with tempfile.TemporaryDirectory() as tmp:
        file = Path(tmp) / "gitconfig"
        file.write_text(text)
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(file), "GIT_CONFIG_NOSYSTEM": "1"}):
            yield file


def runner(has: dict, fail: str | None = None, writes: list | None = None):
    """A stand-in for git: `has` is what it holds, and a write of the key `fail` is refused."""
    def run(argv):
        if "--get" in argv:
            value = has.get(argv[-1], "")
            return subprocess.CompletedProcess(argv, 0 if value else 1, value + "\n" if value else "", "")
        if writes is not None:
            writes.append(argv)
        if argv[-2] == fail:
            return subprocess.CompletedProcess(argv, 255, "", "error: could not lock config file\n")
        has[argv[-2]] = argv[-1]
        return DONE
    return run


@unittest.skipUnless(prereqs.shutil.which("git"), "git is not on this machine")
class RealGitIdentityTest(unittest.TestCase):
    def test_a_saved_name_and_email_are_what_git_then_reads(self):
        with global_file() as file:
            before = prereqs.identity_check()
            self.assertEqual((before["ok"], before["values"]), (False, {"name": "", "email": ""}))
            after = prereqs.save_identity("  Maya Okafor ", "maya@example.com")
            self.assertEqual((after["ok"], after["said"]), (True, "Maya Okafor <maya@example.com>"))
            self.assertEqual(after["values"], {"name": "Maya Okafor", "email": "maya@example.com"})
            self.assertEqual(prereqs.identity_check()["said"], "Maya Okafor <maya@example.com>")
            self.assertIn("Maya Okafor", file.read_text())

    def test_a_name_git_already_has_survives_a_save_carrying_another(self):
        """Review F1: the server holds the rule, whatever the page sends."""
        with global_file("[user]\n\tname = Old Name\n") as file:
            after = prereqs.save_identity("New Name", "maya@example.com")
            self.assertEqual(after["said"], "Old Name <maya@example.com>")
            self.assertIn("name = Old Name", file.read_text())
            self.assertNotIn("New Name", file.read_text())

    def test_a_save_is_refused_once_git_has_both(self):
        text = "[user]\n\tname = Old Name\n\temail = old@example.com\n"
        with global_file(text) as file:
            with self.assertRaisesRegex(ValueError, "^git already has a name and email$"):
                prereqs.save_identity("New Name", "new@example.com")
            self.assertEqual(file.read_text(), text)

    def test_a_value_that_begins_with_a_dash_is_refused_and_never_reaches_git(self):
        """Review F3. git 2.54 stores `--unset` as the literal value (probed); an older or
        newer git may read it as an option, so it is refused here whichever git runs."""
        text = "[user]\n\temail = old@example.com\n"
        with global_file(text) as file:
            with self.assertRaisesRegex(ValueError, "^your name for git cannot begin with a dash$"):
                prereqs.save_identity("--unset", "old@example.com")
            self.assertEqual(file.read_text(), text)

    def test_a_missing_or_two_line_value_is_refused_and_nothing_is_written(self):
        cases = (("", "maya@example.com", "git needs your name: it is empty"),
                 ("Maya", " ", "git needs your email: it is empty"),
                 ("Maya\nOkafor", "maya@example.com", "your name for git must be one line of plain text"),
                 ("Maya\u2028Okafor", "maya@example.com", "your name for git must be one line of plain text"),
                 ("Maya", "maya\x7f@example.com", "your email for git must be one line of plain text"))
        with global_file() as file:
            for name, email, why in cases:
                with self.subTest(name=name, email=email), self.assertRaises(ValueError) as refusal:
                    prereqs.save_identity(name, email)
                self.assertEqual(str(refusal.exception), why)
            self.assertEqual(file.read_text(), "")


class IdentityTest(unittest.TestCase):
    def test_only_the_email_missing_says_so_and_only_the_email_is_written(self):
        has, writes = {"user.name": "Maya"}, []
        check = prereqs.identity_check(runner=runner(has))
        self.assertEqual(check["what"], "Git on this computer has no email set. When work lands, git records who merged it.")
        self.assertEqual(check["values"], {"name": "Maya", "email": ""})
        after = prereqs.save_identity("Someone Else", "maya@example.com", runner=runner(has, writes=writes))
        self.assertEqual(writes, [["git", "config", "--global", "user.email", "maya@example.com"]])
        self.assertEqual(after["said"], "Maya <maya@example.com>")

    def test_a_second_write_git_refuses_says_the_first_was_saved(self):
        """Review F4: the writes are one after the other and the first is not taken back."""
        has, writes = {}, []
        with self.assertRaises(ValueError) as refusal:
            prereqs.save_identity("Maya", "maya@example.com", runner=runner(has, fail="user.email", writes=writes))
        self.assertEqual(str(refusal.exception),
                         "git could not save your email: error: could not lock config file. Your name was saved.")
        self.assertEqual([argv[-2] for argv in writes], ["user.name", "user.email"])
        self.assertEqual(has, {"user.name": "Maya"})

    def test_a_first_write_git_refuses_writes_nothing(self):
        has, writes = {}, []
        with self.assertRaises(ValueError) as refusal:
            prereqs.save_identity("Maya", "maya@example.com", runner=runner(has, fail="user.name", writes=writes))
        self.assertEqual(str(refusal.exception), "git could not save your name: error: could not lock config file.")
        self.assertEqual((len(writes), has), (1, {}))

    def test_git_that_does_not_run_is_said(self):
        def run(argv):
            return UNSET if "--get" in argv else None
        with self.assertRaisesRegex(ValueError, r"^git could not save your name: git did not run\.$"):
            prereqs.save_identity("Maya", "maya@example.com", runner=run)

    def test_an_identity_that_could_not_be_read_is_not_one_that_is_missing(self):
        """A read that timed out, or that git answered with anything but "no such key", says
        nothing about what git has: Save writes nothing, and the row says it was not checked."""
        broken = subprocess.CompletedProcess([], 128, "", "fatal: bad config line 1\n")
        for unread in (None, broken):
            has, writes = {"user.email": "old@example.com"}, []
            stand_in = runner(has, writes=writes)

            def run(argv, unread=unread, stand_in=stand_in):
                return unread if argv[-2:] == ["--get", "user.name"] else stand_in(argv)
            with self.subTest(unread=unread):
                with self.assertRaises(ValueError) as refusal:
                    prereqs.save_identity("Maya", "maya@example.com", runner=run)
                self.assertEqual(str(refusal.exception),
                                 "git's settings could not be read just now, so nothing was saved; try again")
                self.assertEqual((writes, has), ([], {"user.email": "old@example.com"}))
                check = prereqs.identity_check(runner=run)
                self.assertEqual((check["ok"], check["said"], check["command"]), (False, "could not be checked", ""))
                self.assertEqual(check["what"], "Git's settings could not be read just now, so your name and "
                                                "email could not be checked. When work lands, git records who merged it.")
                self.assertEqual(check["fix"], "Check again. If it keeps happening, run `git config --list` "
                                               "in a terminal to see what git says.")
                self.assertIs(check["page"], False, "the two fields are not offered over a value nobody could read")


if __name__ == "__main__":
    unittest.main()
