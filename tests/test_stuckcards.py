"""The stuck states outside setup (keel/stuckcards.py, c-678): a block read into what
happened and its fix (a session that will not start, a landing that was refused), the fixes
that are the page's verbs, the services restarted, and an unknown config key removed or
renamed. On temp configs and temp git repos; the service manager is a fake that answers as
launchd does, no session is started, and nothing outside the temp directory is run."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import actions, onboarding, readiness, stuckcards
from keel import config as config_module
from keel.board import open_board
from keel.config import Space
from tests.helpers import make_config, make_repo
from tests.test_installer import init
from tests.test_repocommands import Case as CopiedRepo
from tests.test_tierrecord import Pressed

TESTS = ("outcome not merged: tests failed on the merged tree (your branch merged onto 1a2b3c4d) (`npm test` exited 1); "
         "nothing was merged; failed: tests.test_a.A.test_one, tests.test_b.B.test_two; the whole output is in /x/merged-tests.log")


def sh(cwd, *args):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        self.home = self.dir / "spaces" / "work" / "api"
        self.repo = make_repo(self.home / "repo")
        self.other = make_repo(self.dir / "attached")
        self.cfg = make_config(self.dir, repos={"keel": make_repo(self.dir / "elsewhere")})
        self.cfg.source = self.dir / "config.toml"
        self.cfg.spaces["work"] = Space(name="work", config_dir=self.dir / "cfg-work", contract=None, adapter=None,
                                        repos={"api": self.repo, "mine": self.other}, house_review=False, model="opus")
        (self.home / "CLAUDE.md").write_text("# api\n")

    def card(self, reason, **more):
        return dict({"id": "c-9", "space": "work", "repo": "api", "title": "A thing", "stage": "review",
                     "blocked_reason": reason, "options": {}, "model": "opus"}, **more)


class PressedFixTest(Pressed, CopiedRepo):
    """Each fix that clears the way and lands, pressed on a card a landing really refused
    (c-678 fix check): its own verb, then the deck's unblock of that block, then Approve. A
    bare Approve after the verb is refused on a blocked card where landings are queued."""

    def lock(self) -> Path:
        """A lock a git that died left in Keel's copy, long enough ago to be stale."""
        lock = self.repo / ".git" / "index.lock"
        lock.write_text("")
        at = lock.stat().st_mtime - 3600
        os.utime(lock, (at, at))
        return lock

    def dirty(self) -> Path:
        """A change in Keel's copy that was never committed."""
        (self.repo / "README").write_text("changed by hand\n")
        return self.repo / "README"

    def queued(self, kind: str, label: str, verb: str):
        """Approve queued, refused by the worker, the card blocked; then the fix pressed and
        the drain's pass again. The board, the card id and what `kb` was sent by the press."""
        from keel.board import Board     # noqa: PLC0415
        card = self.at_review()["id"]
        board = Board(self.cfg.db_path, switches={"merge_queue"})
        self.addCleanup(board.close)
        sent = self.pressing(board)
        actions.act(self.cfg, board, {"verb": "approve", "id": card, "gate": "outcome"})
        self.assertEqual(self.drained(board, card), 1)
        blocked = board.get(card)
        found = stuckcards.read(self.cfg, blocked, board)
        self.assertEqual((found["kind"], found["fix"]["label"]), (kind, label), blocked["blocked_reason"])
        self.assertEqual(found["fix"], {"label": label, "body": {"verb": verb, "id": card}, "then": "land",
                                        "expect": blocked["blocked_reason"]})
        sent.clear()
        self.press(board, found["fix"], card)
        self.assertEqual([argv[0] for argv in sent if argv[0] != "note"], ["unblock", "relay"],
                         "the fix's own verb is the page's; then the block is lifted, then Approve is queued")
        self.assertEqual(self.drained(board, card), 0, board.get(card)["blocked_reason"])
        landed = board.get(card)
        self.assertEqual((landed["stage"], landed["options"]["landing"]["state"]), ("done", "landed"))
        self.assertTrue((self.repo / "new.txt").is_file())

    def in_the_tap(self, reason: str, label: str):
        """The queue off: the block a refused tap left, the fix pressed, the card landed."""
        card = self.at_review()["id"]
        self.cfg.merge_queue = False
        with open_board(self.cfg) as board:
            sent = self.pressing(board)
            board.block(card, reason, "drain", mark="landing-refused")
            fix = stuckcards.read(self.cfg, board.get(card), board)["fix"]
            self.assertEqual(fix["label"], label)
            self.press(board, fix, card)
            self.assertEqual([argv[0] for argv in sent if argv[0] != "note"], ["unblock", "approve"])
            self.assertEqual(board.get(card)["stage"], "done")
        self.assertTrue((self.repo / "new.txt").is_file())

    def test_remove_the_stale_lock_and_land_lands_a_queued_card(self):
        lock = self.lock()
        self.queued("land-lock", "Remove the stale lock and land", "land.unlock")
        self.assertFalse(lock.exists())

    def test_set_them_aside_and_land_lands_a_queued_card(self):
        changed = self.dirty()
        self.queued("land-dirty", "Set them aside and land", "land.aside")
        self.assertNotEqual(changed.read_text(), "changed by hand\n", "set aside as a stash")

    def test_remove_the_stale_lock_and_land_lands_in_the_tap_where_the_queue_is_off(self):
        lock = self.lock()
        self.in_the_tap(f"outcome not merged: fatal: Unable to create '{lock}': File exists.",
                        "Remove the stale lock and land")
        self.assertFalse(lock.exists())

    def test_set_them_aside_and_land_lands_in_the_tap_where_the_queue_is_off(self):
        self.dirty()
        self.in_the_tap(f"outcome not merged: {self.repo} has uncommitted changes on main; commit or stash them, "
                        f"then approve again", "Set them aside and land")


class ReadTest(Case):
    def test_a_card_that_is_not_blocked_or_is_blocked_on_a_question_reads_as_nothing(self):
        self.assertIsNone(stuckcards.read(self.cfg, self.card(None)))
        self.assertIsNone(stuckcards.read(self.cfg, self.card("Which heading did you mean?")))

    def test_no_model_named(self):
        found = stuckcards.read(self.cfg, self.card("no model on c-9, and a house never runs on the account's default. "
                                                    "Name one (`kb set c-9 model=opus`, the space's default) and unblock it.",
                                                    stage="assigned", model=None))
        self.assertEqual(found["kind"], "no-model")
        self.assertEqual(found["what"], "No session started for c-9: this card names no model, and Shipyard never guesses one.")
        self.assertEqual(found["fix"], {"label": "Use opus (this space's default) and start",
                                        "body": {"verb": "stuck.model", "id": "c-9"}, "then": "house.retry"})

    def test_a_session_that_failed_to_start(self):
        found = stuckcards.read(self.cfg, self.card("house failed to start: claude --bg printed no session id",
                                                    stage="assigned"))
        self.assertEqual(found["kind"], "start-failed")
        self.assertEqual(found["what"], "No session started for c-9: claude --bg printed no session id.")
        self.assertEqual(found["fix"], {"label": "Try again", "body": {"verb": "house.retry", "id": "c-9"}})

    def test_a_landing_whose_tests_were_red(self):
        found = stuckcards.read(self.cfg, self.card(TESTS))
        self.assertEqual(found["kind"], "land-tests")
        self.assertEqual(found["what"], "The merged result failed `npm test`: 2 failed. Nothing landed.")
        self.assertEqual(found["fix"]["label"], "Send back with the failures")
        self.assertEqual(found["fix"]["body"], {"verb": "sendback", "id": "c-9", "reason": TESTS})

    def test_a_landing_onto_keels_own_copy_with_changes_never_committed(self):
        (self.repo / "README").write_text("changed\n")
        (self.repo / "package.json").write_text("{}\n")
        sh(self.repo, "git", "add", "package.json")
        reason = f"outcome not merged: {self.repo} has uncommitted changes on main; commit or stash them, then approve again"
        found = stuckcards.read(self.cfg, self.card(reason))
        self.assertEqual(found["kind"], "land-dirty")
        self.assertEqual(found["what"], "The folder Shipyard lands into has changes that were never committed: "
                                        "README, package.json. Shipyard will not merge over them.")
        self.assertEqual(found["fix"], {"label": "Set them aside and land", "body": {"verb": "land.aside", "id": "c-9"},
                                        "then": "land", "expect": reason})

    def test_a_landing_onto_an_attached_folder_gives_the_two_commands(self):
        (self.other / "README").write_text("changed\n")
        reason = f"outcome not merged: {self.other} has uncommitted changes on main; commit or stash them, then approve again"
        found = stuckcards.read(self.cfg, self.card(reason, repo="mine"))
        self.assertEqual(found["kind"], "land-dirty")
        self.assertNotIn("fix", found)
        self.assertEqual(found["commands"], [f"git -C {self.other} stash push", f"git -C {self.other} stash pop"])
        self.assertIn("your own folder", found["said"])

    def test_a_stale_lock(self):
        reason = ("outcome not merged: git merge --ff-only --quiet abc: fatal: Unable to create "
                  f"'{self.repo}/.git/index.lock': File exists.")
        found = stuckcards.read(self.cfg, self.card(reason))
        self.assertEqual(found["kind"], "land-lock")
        self.assertEqual(found["what"], "The merge did not go through: a git lock file was left behind in the folder Shipyard lands into.")
        self.assertEqual(found["fix"], {"label": "Remove the stale lock and land", "body": {"verb": "land.unlock", "id": "c-9"},
                                        "then": "land", "expect": reason})

    def test_git_not_knowing_who_you_are(self):
        found = stuckcards.read(self.cfg, self.card("outcome not merged: git merge x: fatal: empty ident name (for <a@b>) not allowed"))
        self.assertEqual(found["kind"], "land-identity")
        self.assertEqual(found["fix"], {"label": "Set your name and email", "step": "prerequisites"})

    def test_anything_else_git_said(self):
        found = stuckcards.read(self.cfg, self.card("outcome not merged: git rev-parse main: fatal: bad revision 'main'"))
        self.assertEqual(found["kind"], "land-other")
        self.assertEqual(found["what"], "The merge did not go through: git rev-parse main: fatal: bad revision 'main'.")
        self.assertNotIn("fix", found)


class FixTest(Case):
    def setUp(self):
        super().setUp()
        self.board = open_board(self.cfg).__enter__()
        self.addCleanup(self.board.close)

    def blocked(self, reason, repo="api", model="opus"):
        card = self.board.create("work", "A thing", repo=repo, actor="human", model=model)
        self.board.block(card, reason, "drain")
        return card

    def test_the_default_model_is_set_on_a_card_that_names_none(self):
        card = self.blocked("no model on c-1, and a house never runs on the account's default. Name one.")
        self.board.conn.execute("UPDATE cards SET model = NULL WHERE id = ?", (card,))
        self.board.conn.commit()
        done = stuckcards.set_model(self.cfg, self.board, card)
        self.assertEqual((done["model"], self.board.get(card)["model"]), ("opus", "opus"))

    def test_it_is_refused_on_any_other_card(self):
        card = self.blocked("Which heading did you mean?")
        with self.assertRaisesRegex(stuckcards.Refused, "not waiting on a model"):
            stuckcards.set_model(self.cfg, self.board, card)

    def test_set_aside_stashes_what_was_never_committed_in_keels_copy(self):
        (self.repo / "README").write_text("changed\n")
        card = self.blocked(f"outcome not merged: {self.repo} has uncommitted changes on main; commit or stash them, then approve again")
        done = stuckcards.set_aside(self.cfg, self.board, card)
        self.assertEqual(sh(self.repo, "git", "status", "--porcelain", "--untracked-files=no"), "")
        self.assertIn("keel: set aside before landing", sh(self.repo, "git", "stash", "list"))
        self.assertIn("git stash pop", done["note"])

    def test_set_aside_never_touches_a_folder_of_the_users_own(self):
        (self.other / "README").write_text("changed\n")
        card = self.blocked(f"outcome not merged: {self.other} has uncommitted changes on main; commit or stash them", repo="mine")
        with self.assertRaisesRegex(stuckcards.Refused, "your own folder"):
            stuckcards.set_aside(self.cfg, self.board, card)
        self.assertNotEqual(sh(self.other, "git", "status", "--porcelain"), "")

    def locked(self, age: float):
        """A card held by a lock file in Keel's copy that was last written `age` seconds ago."""
        lock = self.repo / ".git" / "index.lock"
        lock.write_text("")
        at = lock.stat().st_mtime - age
        os.utime(lock, (at, at))
        return lock, self.blocked(f"outcome not merged: fatal: Unable to create '{lock}': File exists.")

    def test_the_stale_lock_is_removed_from_keels_copy(self):
        lock, card = self.locked(3600)
        done = actions.act(self.cfg, self.board, {"verb": "land.unlock", "id": card})
        self.assertFalse(lock.exists())
        self.assertEqual(done["note"], "the stale lock is removed")

    def test_a_lock_a_git_may_still_hold_is_left_and_the_tap_says_to_wait(self):
        """Keel's copy has more writers than it had (the fetch, the push's merge, a branch
        switch): a lock younger than 30 seconds may be a live git's (review F14)."""
        lock, card = self.locked(0)
        with self.assertRaisesRegex(actions.ActionError, "A git command may still be running there. Wait a moment"):
            actions.act(self.cfg, self.board, {"verb": "land.unlock", "id": card})
        self.assertTrue(lock.exists())

    def test_each_fix_refuses_a_card_it_is_not_for_through_the_pages_verb(self):
        card = self.blocked("Which heading did you mean?")
        for verb, said in (("stuck.model", "not waiting on a model"), ("land.aside", "not held by changes"),
                           ("land.unlock", "not held by a git lock file")):
            with self.subTest(verb), self.assertRaisesRegex(actions.ActionError, said):
                actions.act(self.cfg, self.board, {"verb": verb, "id": card})
        self.assertNotIn("ship.inline", actions.SETUP_TABLE, "Keel moves no branch for a rewritten pull request (c-653)")


class FakeManager:
    """A service manager that answers as launchd does and runs nothing."""

    def __init__(self, home: Path, loaded: bool, installed: bool = True, ok: bool = True):
        self.home, self.installed_dir = home, home / "LaunchAgents"
        self.loaded, self.ok, self.calls = loaded, ok, []
        if installed:
            self.installed_dir.mkdir(parents=True)
            (self.installed_dir / "dev.shipyard.drain.plist").write_text("<plist/>")

    def files(self, svc):
        return {f"{svc.label}.plist": b"<plist/>"}

    def state(self, label, scheduled=False):
        return self.loaded, None

    def restart(self, label):
        self.calls.append(("restart", label))
        return (True, "ok") if self.ok else (False, "Could not find service")

    def start(self, svc):
        self.calls.append(("start", svc.label))
        if self.loaded:     # launchd's complaint about a job that is already bootstrapped
            return False, "Bootstrap failed: 5: Input/output error"
        return (True, "ok") if self.ok else (False, "Bootstrap failed: 5: Input/output error")


class ServicesTest(Case):
    def setUp(self):
        super().setUp()
        self.board = open_board(self.cfg).__enter__()
        self.addCleanup(self.board.close)
        other = mock.patch("keel.drainprobe.refusal", return_value=None)    # never asks this machine's processes
        self.other_drain = other.start()
        self.addCleanup(other.stop)

    def restart(self, manager):
        with mock.patch("keel.service.Manager", return_value=manager):
            return actions.act(self.cfg, self.board, {"verb": "services.restart"})

    def test_a_drain_that_is_loaded_but_hung_is_really_restarted(self):
        """`start` on a loaded job is a launchd error and restarts nothing (review F8)."""
        manager = FakeManager(self.dir / "home", loaded=True)
        done = self.restart(manager)
        self.assertEqual(manager.calls, [("restart", "dev.shipyard.drain")])
        self.assertEqual(done["note"], "restarted: sessions start and work lands again in a moment")

    def test_a_drain_that_is_installed_and_stopped_is_started(self):
        manager = FakeManager(self.dir / "home", loaded=False)
        done = self.restart(manager)
        self.assertEqual(manager.calls, [("start", "dev.shipyard.drain")])
        self.assertEqual(done["note"], "started: sessions start and work lands again in a moment")

    def test_a_drain_that_was_never_installed_is_refused_and_nothing_is_asked(self):
        manager = FakeManager(self.dir / "home", loaded=False, installed=False)
        with self.assertRaisesRegex(actions.ActionError, "could not be restarted from here: its service is not "
                                                         "installed on this computer"):
            self.restart(manager)
        self.assertEqual(manager.calls, [])

    def test_a_restart_the_manager_refuses_says_what_it_said(self):
        manager = FakeManager(self.dir / "home", loaded=True, ok=False)
        with self.assertRaisesRegex(actions.ActionError, "could not be restarted from here: Could not find service"):
            self.restart(manager)

    def test_another_drain_on_this_computer_is_never_doubled(self):
        self.other_drain.return_value = "another Shipyard drain runs as this user on this machine"
        manager = FakeManager(self.dir / "home", loaded=False)
        with self.assertRaisesRegex(actions.ActionError, "another Shipyard drain runs"):
            self.restart(manager)
        self.assertEqual(manager.calls, [])


class ConfigKeyTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        readiness.forget()
        self.addCleanup(readiness.forget)
        self.home = Path(tmp.name).resolve() / "install"
        self.assertEqual(init(self.home), 0)
        self.path = self.home / "config.toml"
        text = self.path.read_text()
        self.assertIn("[keel]\n", text)
        self.assertIn("review_asks = 2", text)
        text = text.replace("review_asks = 2", "reveiw_asks = 3", 1)      # the typo, in place of the real line
        self.path.write_text(text.replace("[keel]\n", "[keel]\nzzz_nothing_like_it = 1\n", 1))

    def cfg(self):
        return config_module.load(self.path, ensure=False)

    def test_an_unknown_key_is_read_with_what_it_is_near(self):
        found = {one["key"]: one for one in stuckcards.unknown_keys(self.cfg())}
        self.assertEqual(found["reveiw_asks"]["table"], "keel")
        self.assertEqual(found["reveiw_asks"]["near"], "review_asks")
        self.assertEqual(found["reveiw_asks"]["what"], "config.toml has a setting Shipyard does not know: `[keel] reveiw_asks`. "
                                                     "It was ignored and the default is in use.")
        self.assertIsNone(found["zzz_nothing_like_it"]["near"])

    def test_remove_takes_the_line_out(self):
        stuckcards.remove_key(self.cfg(), "keel", "zzz_nothing_like_it")
        self.assertNotIn("zzz_nothing_like_it", self.path.read_text())
        self.assertEqual([one["key"] for one in stuckcards.unknown_keys(self.cfg())], ["reveiw_asks"])

    def test_rename_keeps_the_value_under_the_name_keel_knows(self):
        stuckcards.rename_key(self.cfg(), "keel", "reveiw_asks", "review_asks")
        cfg = self.cfg()
        self.assertEqual(cfg.review_asks, 3)
        self.assertNotIn("reveiw_asks", self.path.read_text())

    def test_a_key_keel_knows_is_never_removed_or_renamed_this_way(self):
        """Through the page's verbs, which are the only way a page reaches them."""
        cfg = self.cfg()
        before = self.path.read_text()
        with open_board(cfg) as board:
            with self.assertRaisesRegex(actions.ActionError, "is a setting Shipyard knows"):
                actions.act(cfg, board, {"verb": "setup.config.remove", "table": "keel", "key": "houses_max"})
            with self.assertRaisesRegex(actions.ActionError, "is not a setting of"):
                actions.act(cfg, board, {"verb": "setup.config.rename", "table": "keel", "key": "reveiw_asks",
                                         "to": "nothing_real"})
        self.assertEqual(self.path.read_text(), before)
        self.assertIn("setup.config.remove", onboarding.CONFIG_VERBS)
        self.assertIn("setup.config.rename", onboarding.CONFIG_VERBS)


if __name__ == "__main__":
    unittest.main()
