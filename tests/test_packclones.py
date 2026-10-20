"""A shared pack plugs into an install (c-740, `keel/packclones.py`): a pack that is its own
clone inside the install's packs folder is found as any pack there, the packs repo ignores
it, its update moves the drain's restart check, a clone under the wrong folder name is one
problem line beside every other pack, Bosun builds it from a clone of its own and its landing
goes to the pack's repo, and the checks that read a pack's suite and its terms read a cloned
pack's exactly as a tracked one's. One test per promise, on a scratch install."""

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import actions, builder, configedit, drain, merging, onboarding, packclones, packs, packsetup, readiness
from keel.board import open_board
from keel import config as config_module
from tests import installdrift, packsuites, publiccheck
from tests.helpers import no_real_tools
from tests.test_installer import init

PACK = 'name = "{name}"\nversion = "1"\ndescription = "a team\'s pack"\n'
WORD = "zorblaxian"


def git(repo: Path, *argv: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *argv],
                          capture_output=True, text=True, check=True).stdout.strip()


class ClonedPackCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        no_real_tools(self)
        self.base = Path(tmp.name).resolve()
        self.home = self.base / "install"
        self.assertEqual(init(self.home), 0)
        os.environ["KEEL_CONFIG"] = str(self.home / "config.toml")
        packs.forget()
        self.addCleanup(packs.forget)
        self.packs = self.home / "packs"

    def cfg(self):
        return config_module.load(self.home / "config.toml", ensure=False)

    def shared(self, name: str = "team") -> Path:
        """The repo a team keeps its pack in: one commit, the pack at its root."""
        origin = self.base / f"{name}-origin"
        subprocess.run(["git", "init", "-q", "-b", "main", str(origin)], check=True)
        (origin / "pack.toml").write_text(PACK.format(name=name))
        (origin / "drift-terms").write_text(f"{WORD}\n")
        (origin / "tests").mkdir()
        (origin / "tests" / "test_it.py").write_text("")
        git(origin, "add", "-A")
        git(origin, "commit", "-q", "-m", "the pack")
        return origin

    def clone(self, name: str = "team", folder: str | None = None) -> Path:
        """What the page's one line does: the shared pack cloned into the packs folder."""
        target = self.packs / (folder or name)
        subprocess.run(["git", "clone", "-q", str(self.shared(name)), str(target)], check=True)
        return target


class FoundAndIgnoredTest(ClonedPackCase):
    def test_a_cloned_pack_is_found_and_loads_as_any_pack_there(self):
        clone = self.clone()
        rows, problem = packsetup.rows(self.cfg())
        self.assertIsNone(problem)
        self.assertIn("team", [row["name"] for row in rows])
        self.assertEqual(packs.find("team", packs.PACKAGE).path, clone)

    def test_its_row_says_it_was_found_in_the_installs_folder(self):
        """c-758: the choice step lists a connection found in the install's own folder first,
        marked as found there; one Shipyard ships names no folder."""
        clone = self.clone()
        rows = {row["name"]: row for row in packsetup.rows(self.cfg())[0]}
        self.assertEqual(rows["team"]["folder"], str(clone))
        self.assertIsNone(rows["github"]["folder"])

    def test_the_packs_repo_ignores_it_so_its_status_stays_clean(self):
        self.clone()
        self.assertIn("team/", git(self.packs, "status", "--porcelain"), "untracked until Keel sees it")
        self.assertTrue(packclones.reconcile(self.cfg()))
        self.assertEqual(git(self.packs, "status", "--porcelain"), "")
        self.assertFalse(packclones.reconcile(self.cfg()), "a second look writes nothing")

    def test_the_setup_report_is_one_place_keel_sees_it(self):
        self.clone()
        onboarding.report(self.cfg())
        self.assertEqual(git(self.packs, "status", "--porcelain"), "")

    def test_the_block_follows_the_clones_and_keeps_the_users_own_lines(self):
        exclude = self.packs / ".git" / "info" / "exclude"
        exclude.parent.mkdir(exist_ok=True)
        exclude.write_text("my-notes.txt\n")
        self.clone()
        packclones.reconcile(self.cfg())
        self.clone("other")
        packclones.reconcile(self.cfg())
        text = exclude.read_text()
        self.assertEqual(text.count(packclones.BEGIN), 1)
        self.assertIn("my-notes.txt\n", text)
        self.assertIn("/other/\n", text)
        self.assertIn("/team/\n", text)

    def test_the_block_goes_when_the_last_clone_goes(self):
        """r1.F4: the block follows the clones down to none, and the user's lines stay."""
        exclude = self.packs / ".git" / "info" / "exclude"
        exclude.parent.mkdir(exist_ok=True)
        exclude.write_text("my-notes.txt\n")
        clone = self.clone()
        packclones.reconcile(self.cfg())
        shutil.rmtree(clone)
        self.assertTrue(packclones.reconcile(self.cfg()))
        self.assertEqual(exclude.read_text(), "my-notes.txt\n")
        self.assertFalse(packclones.reconcile(self.cfg()), "and nothing is written after")

    def test_a_plain_folder_and_a_linked_folder_are_not_clones(self):
        """A pack with no repo of its own, and a link to one: neither is read as a clone
        (`StillTrackedTest` holds the folder the packs repo tracks, r1.F3)."""
        (self.packs / "mine").mkdir()
        (self.packs / "mine" / "pack.toml").write_text(PACK.format(name="mine"))
        outside = self.base / "outside"
        subprocess.run(["git", "clone", "-q", str(self.shared("linked")), str(outside)], check=True)
        os.symlink(outside, self.packs / "linked")
        self.assertEqual(packclones.found(self.packs), {})
        self.assertFalse(packclones.reconcile(self.cfg()))


class FirstCommitTest(unittest.TestCase):
    def test_a_clone_there_before_the_packs_repo_is_made_is_never_committed_into_it(self):
        """r1.F7: init writes the ignore block before the packs repo's first add and commit."""
        with tempfile.TemporaryDirectory() as scratch, mock.patch.dict(os.environ):
            base = Path(scratch).resolve()
            origin, home = base / "origin", base / "install"
            subprocess.run(["git", "init", "-q", "-b", "main", str(origin)], check=True)
            (origin / "pack.toml").write_text(PACK.format(name="team"))
            git(origin, "add", "-A")
            git(origin, "commit", "-q", "-m", "the pack")
            (home / "packs").mkdir(parents=True)
            subprocess.run(["git", "clone", "-q", str(origin), str(home / "packs" / "team")], check=True)
            self.assertEqual(init(home), 0)
            self.assertEqual(git(home / "packs", "ls-files", "--stage", "--", "team"), "", "not tracked")
            self.assertEqual(git(home / "packs", "status", "--porcelain"), "")
            self.assertEqual(list(packclones.found(home / "packs")), ["team"])


class StillTrackedTest(ClonedPackCase):
    """r1.F3: a folder the packs repo still tracks paths under is not a clone, whatever
    `.git` it has: the ignore line would do nothing, and two repos could land its files."""

    def setUp(self):
        super().setUp()
        self.mine = self.packs / "mine"
        self.mine.mkdir()
        (self.mine / "pack.toml").write_text(PACK.format(name="mine"))
        git(self.packs, "add", "-A")
        git(self.packs, "commit", "-q", "-m", "mine, tracked here")
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.mine)], check=True)

    def test_it_is_no_clone_gets_no_ignore_line_and_is_no_repo_of_its_own(self):
        self.assertEqual(packclones.found(self.packs), {})
        self.assertEqual(packclones.tracked(self.packs), ["mine"])
        self.assertFalse(packclones.reconcile(self.cfg()))
        self.assertNotIn("pack-mine", builder.own_repos(self.home))
        self.assertFalse(builder.is_own(self.home, self.mine))

    def test_the_packs_panel_says_so_in_one_line_with_the_command_that_stops_it(self):
        rows, problem = packsetup.rows(self.cfg())
        self.assertIn("mine", [row["name"] for row in rows], "it still lists, as the tracked pack it is")
        self.assertEqual(len(problem.splitlines()), 1)
        self.assertIn("still tracks mine", problem)
        self.assertIn(f"git -C {self.packs} rm -r --cached mine", problem)
        self.assertIn("commit", problem)

    def test_one_listing_asks_the_packs_repo_what_it_tracks_once(self):
        """Fix check D3: the lines are said in two words (pack, connection), from one reading."""
        cfg = self.cfg()
        with mock.patch.object(packclones, "tracked", wraps=packclones.tracked) as asked:
            listed = packsetup.listing(cfg)
        self.assertEqual(asked.call_count, 1)
        self.assertIn("is not read as a pack with a repo", listed["problem"])
        self.assertIn("is not read as a connection with a repo", listed["said"])
        self.assertIs(listed["install"], True)

    def test_once_the_packs_repo_stops_tracking_it_it_is_a_clone(self):
        git(self.packs, "rm", "-r", "-q", "--cached", "mine")
        git(self.packs, "commit", "-q", "-m", "mine leaves")
        self.assertEqual(list(packclones.found(self.packs)), ["mine"])
        self.assertIsNone(packsetup.rows(self.cfg())[1])


class RestartCheckTest(ClonedPackCase):
    def test_an_update_of_a_cloned_pack_moves_the_drains_restart_check(self):
        clone = self.clone()
        cfg = self.cfg()
        started = drain.packs_head(cfg)
        self.assertFalse(drain.packs_moved(cfg, started))
        git(clone, "commit", "-q", "--allow-empty", "-m", "pulled")
        self.assertTrue(drain.packs_moved(cfg, started))

    def test_the_packs_repo_itself_still_moves_it(self):
        cfg = self.cfg()
        started = drain.packs_head(cfg)
        git(self.packs, "commit", "-q", "--allow-empty", "-m", "landed")
        self.assertTrue(drain.packs_moved(cfg, started))

    def test_a_pack_cloned_since_the_start_moves_it(self):
        cfg = self.cfg()
        started = drain.packs_head(cfg)
        self.clone()
        self.assertTrue(drain.packs_moved(cfg, started))

    def test_a_clone_with_no_head_yet_is_not_counted_until_it_has_one(self):
        """r1.F6: a clone seen mid-clone restarts nothing, and its first head restarts once;
        counted with no head, a later `git pull` could never move the check."""
        cfg = self.cfg()
        started = drain.packs_head(cfg)
        unborn = self.packs / "team"
        subprocess.run(["git", "init", "-q", "-b", "main", str(unborn)], check=True)
        self.assertFalse(drain.packs_moved(cfg, started), "no head yet: not counted")
        started = drain.packs_head(cfg)             # a drain that started while it had none
        git(unborn, "commit", "-q", "--allow-empty", "-m", "its first head")
        self.assertTrue(drain.packs_moved(cfg, started))
        started = drain.packs_head(cfg)
        self.assertFalse(drain.packs_moved(cfg, started), "once")
        git(unborn, "commit", "-q", "--allow-empty", "-m", "pulled")
        self.assertTrue(drain.packs_moved(cfg, started))

    def test_a_cloned_pack_that_is_gone_moves_it(self):
        clone = self.clone()
        cfg = self.cfg()
        started = drain.packs_head(cfg)
        shutil.rmtree(clone)
        self.assertTrue(drain.packs_moved(cfg, started))

    def test_a_head_that_cannot_be_read_is_unknown_and_unknown_is_not_moved(self):
        self.clone()
        cfg = self.cfg()
        started = drain.packs_head(cfg)
        with mock.patch.object(merging, "code_head", return_value=None):
            self.assertFalse(drain.packs_moved(cfg, started))


class WrongFolderTest(ClonedPackCase):
    def test_a_clone_under_another_name_is_one_problem_line_and_the_rest_still_list(self):
        self.clone()
        wrong = self.clone("shared", folder="shared-pack")
        rows, problem = packsetup.rows(self.cfg())
        names = [row["name"] for row in rows]
        self.assertIn("team", names)
        self.assertIn("github", names)
        self.assertNotIn("shared", names)
        self.assertEqual(len(problem.splitlines()), 1)
        self.assertIn(str(wrong), problem, "what the folder is")
        self.assertIn(str(self.packs / "shared"), problem, "what it should be called")

    def test_a_name_that_is_no_pack_name_has_its_own_one_line(self):
        """r1.F8: the name is whatever the file says, so it is never put in the line as it is."""
        wrong = self.clone("odd")
        (wrong / "pack.toml").write_text(PACK.format(name="two\\nlines\\rhere"))
        rows, problem = packsetup.rows(self.cfg())
        self.assertIn("github", [row["name"] for row in rows])
        self.assertEqual(len(problem.splitlines()), 1, problem)
        self.assertNotIn("lines", problem)
        self.assertIn(str(wrong), problem)
        self.assertIn("lower case letters, digits, - and _", problem)

    def test_the_report_gives_the_packs_folder_as_a_shell_reads_it(self):
        """r1.F8: the page's line is copied into a shell, so a space in the path is quoted."""
        self.assertEqual(onboarding.report(self.cfg())["packs_folder"], str(self.packs))
        spaced = self.base / "my install"
        self.assertEqual(init(spaced), 0)
        cfg = config_module.load(spaced / "config.toml", ensure=False)
        self.assertEqual(packsetup.packs_folder(cfg), f"'{spaced / 'packs'}'")

    def test_a_pack_that_does_not_load_for_another_reason_still_empties_the_list(self):
        self.clone()
        (self.packs / "team" / "pack.toml").write_text("name = \n")
        rows, problem = packsetup.rows(self.cfg())
        self.assertEqual(rows, [])
        self.assertIn("team", problem)

    def test_the_report_says_the_problem_in_each_pages_word_and_whether_it_is_the_installs_folder(self):
        """c-758 r1.F7, F13: the Setup view says pack and the first run says connection, of the
        same folder; and only a problem about a folder of the install's own packs folder is
        marked as one, so the first run opens the shared choice for that and nothing else."""
        wrong = self.clone("shared", folder="shared-pack")
        report = onboarding.report(self.cfg())
        self.assertEqual(report["packs_error"], f"The folder {wrong} holds the pack shared: rename it to "
                                                f"{self.packs / 'shared'}, then Look again.")
        self.assertEqual(report["connections_error"], f"The folder {wrong} holds the connection shared: rename it "
                                                      f"to {self.packs / 'shared'}, then Look again.")
        self.assertIs(report["packs_error_install"], True)
        shutil.rmtree(wrong)
        self.assertIs(onboarding.report(self.cfg())["packs_error_install"], False, "nothing wrong")
        self.clone()
        (self.packs / "team" / "pack.toml").write_text("name = \n")
        broken = onboarding.report(self.cfg())
        self.assertIn("team", broken["connections_error"])
        self.assertIs(broken["packs_error_install"], False, "a pack that does not load names no folder")


class BuilderTest(ClonedPackCase):
    def test_a_cloned_pack_is_the_installs_own_repo_under_a_key_of_its_own(self):
        clone = self.clone()
        self.assertEqual(builder.own_repos(self.home)["pack-team"], clone)
        self.assertTrue(builder.is_own(self.home, clone))
        self.assertFalse(builder.is_own(self.home, self.packs / "github"))

    def test_init_lists_it_and_makes_bosun_a_clone_of_it(self):
        clone = self.clone()
        self.assertEqual(init(self.home), 0)
        cfg = self.cfg()
        self.assertEqual(cfg.spaces["personal"].repos["pack-team"], clone)
        self.assertIn("pack-team", builder.repos(cfg))
        self.assertEqual(git(self.home / "builder" / "pack-team", "remote", "get-url", "origin"), str(clone))
        self.assertTrue(onboarding.fresh(cfg), "it is not one of the user's repos")
        self.assertNotIn("pack-team", readiness.repos_row(cfg, cfg.spaces["personal"])["why"])

    def test_a_users_repo_that_already_has_the_key_keeps_it(self):
        """r1.F4: no listing is written over it, no builder clone is made from the pack, and
        the tap says why."""
        theirs = self.base / "theirs"
        subprocess.run(["git", "init", "-q", "-b", "main", str(theirs)], check=True)
        git(theirs, "commit", "-q", "--allow-empty", "-m", "theirs")
        path = self.home / "config.toml"
        path.write_text(configedit.set_entry(path.read_text(), "spaces.personal.repos", "pack-team", str(theirs)))
        self.clone()
        self.assertEqual(init(self.home), 0)
        cfg = self.cfg()
        self.assertEqual(cfg.spaces["personal"].repos["pack-team"], theirs)
        self.assertNotIn("pack-team", builder.repos(cfg))
        self.assertFalse((self.home / "builder" / "pack-team").exists())
        with self.assertRaisesRegex(actions.ActionError, "already called pack-team"):
            self.build()

    def test_a_clone_under_another_name_than_its_packs_is_no_repo_of_its_own(self):
        """r1.F5: the page asks for a rename, and a listing made before it would outlive it."""
        self.clone("shared", folder="shared-pack")
        self.assertEqual(packclones.own(self.home), {})
        self.assertEqual(init(self.home), 0)
        self.assertNotIn("pack-shared-pack", self.cfg().spaces["personal"].repos)

    def test_a_listed_pack_whose_clone_is_gone_is_taken_out_where_it_was_put_in(self):
        """r1.F5: a listing that points at a folder that is no clone any more reads as one of
        the user's repos; init takes it out, and keeps Bosun's clone of it on disk."""
        clone = self.clone()
        self.assertEqual(init(self.home), 0)
        self.assertIn("pack-team", builder.repos(self.cfg()))
        shutil.rmtree(clone)
        self.assertEqual(init(self.home), 0)
        cfg = self.cfg()
        self.assertNotIn("pack-team", cfg.spaces["personal"].repos)
        self.assertNotIn("pack-team", builder.repos(cfg))
        self.assertEqual(set(cfg.spaces["personal"].repos), {"packs", "memory"})
        self.assertTrue(onboarding.fresh(cfg))
        self.assertTrue((self.home / "builder" / "pack-team" / ".git").is_dir(), "nothing is deleted")

    # ----- r1.F1: the page's own flow finishes the job, by one tap on the pack's row -----

    def row(self, name: str = "team") -> dict:
        return next(row for row in packsetup.rows(self.cfg())[0] if row["name"] == name)

    def build(self, name: str = "team") -> dict:
        cfg = self.cfg()
        with open_board(cfg) as board:
            return actions.act(cfg, board, {"verb": "setup.pack.build", "pack": name})

    def test_a_cloned_packs_row_says_whether_bosun_builds_it(self):
        self.clone()
        self.assertEqual(self.row()["own_repo"], {"key": "pack-team", "built": False})
        self.assertIsNone(self.row("github")["own_repo"])

    def test_one_tap_lists_it_for_bosun_and_makes_bosuns_clone(self):
        clone = self.clone()
        self.assertIn("setup.pack.build", onboarding.CONFIG_VERBS)
        self.build()
        cfg = self.cfg()
        self.assertEqual(cfg.spaces["personal"].repos["pack-team"], clone)
        self.assertIn("pack-team", builder.repos(cfg))
        self.assertEqual(git(self.home / "builder" / "pack-team", "remote", "get-url", "origin"), str(clone))
        self.assertEqual(self.row()["own_repo"], {"key": "pack-team", "built": True})

    def test_the_tap_puts_back_a_pack_that_was_taken_out_of_the_builders_repos(self):
        self.clone()
        self.build()
        path = self.home / "config.toml"
        path.write_text(configedit.set_entry(path.read_text(), "builder", "repos", ["packs", "memory"]))
        self.assertEqual(self.row()["own_repo"]["built"], False)
        self.build()
        self.assertIn("pack-team", builder.repos(self.cfg()))

    def test_the_tap_is_refused_for_a_pack_with_no_repo_of_its_own(self):
        with self.assertRaisesRegex(actions.ActionError, "no repo of its own"):
            self.build("github")

    def test_the_tap_is_refused_where_bosun_is_not_the_installs_builder(self):
        """r2.F3: the verb refuses, not only the page: nothing is listed and no success said."""
        self.clone()
        path = self.home / "config.toml"
        path.write_text(configedit.set_entry(path.read_text(), "keel", "bosun_builder", False))
        before = path.read_text()
        self.assertFalse(builder.in_app(self.cfg()))
        with self.assertRaisesRegex(actions.ActionError, "Bosun is not this install's builder"):
            self.build()
        self.assertEqual(path.read_text(), before)

    # ----- r2.F1: a stale listing leaves no key behind in [builder] repos -----

    def test_two_clones_gone_at_once_both_leave_the_builders_repos(self):
        one, two = self.clone(), self.clone("other")
        self.assertEqual(init(self.home), 0)
        self.assertLessEqual({"pack-team", "pack-other"}, builder.repos(self.cfg()))
        shutil.rmtree(one)
        shutil.rmtree(two)
        self.assertEqual(init(self.home), 0)
        cfg = self.cfg()
        self.assertEqual(set(cfg.spaces["personal"].repos), {"packs", "memory"})
        self.assertEqual(builder.repos(cfg), {"packs", "memory"})

    def test_the_tap_after_a_built_clone_is_renamed_does_not_write_the_old_key_back(self):
        clone = self.clone()
        self.build()
        clone.rename(self.packs / "crew")
        (self.packs / "crew" / "pack.toml").write_text(PACK.format(name="crew"))
        packs.forget()
        self.build("crew")
        cfg = self.cfg()
        self.assertEqual(set(cfg.spaces["personal"].repos), {"packs", "memory", "pack-crew"})
        self.assertEqual(builder.repos(cfg), {"packs", "memory", "pack-crew"})

    def test_a_pack_key_the_builder_names_with_no_listing_is_dropped(self):
        path = self.home / "config.toml"
        path.write_text(configedit.set_entry(path.read_text(), "builder", "repos", ["packs", "memory", "pack-ghost"]))
        self.assertEqual(init(self.home), 0)
        self.assertEqual(builder.repos(self.cfg()), {"packs", "memory"})

    def test_an_approved_change_lands_in_the_packs_own_repo_and_is_not_pushed(self):
        clone = self.clone()
        self.assertEqual(init(self.home), 0)
        cfg = self.cfg()
        packclones.reconcile(cfg)
        built = self.home / "builder" / "pack-team"
        git(built, "checkout", "-q", "-b", "bosun/c-001-rule")
        (built / "rule.md").write_text("a rule\n")
        git(built, "add", "-A")
        git(built, "commit", "-q", "-m", "a rule")
        installs, shared = git(self.packs, "rev-parse", "HEAD"), git(self.base / "team-origin", "rev-parse", "HEAD")
        card = {"id": "c-001", "space": "personal", "repo": "pack-team", "title": "a rule",
                "output_ref": "bosun/c-001-rule", "options": {}}
        landed = merging.land_card(cfg, card)
        self.assertIn("not pushed", landed["published"])
        self.assertTrue((clone / "rule.md").is_file(), "the pack's own tree moved")
        self.assertEqual(git(self.packs, "rev-parse", "HEAD"), installs, "never the install's packs repo")
        self.assertEqual(git(self.packs, "status", "--porcelain"), "")
        self.assertEqual(git(self.base / "team-origin", "rev-parse", "HEAD"), shared, "nothing was pushed")


class LandingGuardTest(ClonedPackCase):
    """r1.F2: the ignore line took away git's own refusal to write over the clone's files,
    so the landing refuses instead, and its fast-forward never writes over an ignored file."""

    def test_a_packs_landing_that_touches_a_cloned_packs_folder_is_refused(self):
        clone = self.clone()
        cfg = self.cfg()
        packclones.reconcile(cfg)
        (clone / "pack.toml").write_text(PACK.format(name="team") + "# an edit not committed yet\n")
        built = self.home / "builder" / "packs"
        git(built, "checkout", "-q", "-b", "bosun/c-002-team")
        (built / "team").mkdir()
        (built / "team" / "pack.toml").write_text("written from the packs repo\n")
        (built / "team" / "x").write_text("x\n")
        git(built, "add", "-A")
        git(built, "commit", "-q", "-m", "team, from the wrong repo")
        before = git(self.packs, "rev-parse", "HEAD")
        card = {"id": "c-002", "space": "personal", "repo": "packs", "title": "team",
                "output_ref": "bosun/c-002-team", "options": {}}
        with self.assertRaises(merging.MergeRefused) as caught:
            merging.land_card(cfg, card)
        self.assertIn("pack-team", str(caught.exception), "the repo to use")
        self.assertIn("an edit not committed yet", (clone / "pack.toml").read_text())
        self.assertFalse((clone / "x").exists())
        self.assertEqual(git(self.packs, "rev-parse", "HEAD"), before)

    def test_a_folder_named_in_another_case_is_the_same_folder(self):
        """r2.F4: on a disk that folds case, `Team/x` is written into the clone `team`."""
        clone = self.clone()
        cfg = self.cfg()
        packclones.reconcile(cfg)
        built = self.home / "builder" / "packs"
        git(built, "checkout", "-q", "-b", "bosun/c-004-team")
        (built / "Team").mkdir()
        (built / "Team" / "x").write_text("x\n")
        git(built, "add", "-A")
        git(built, "commit", "-q", "-m", "Team, in another case")
        card = {"id": "c-004", "space": "personal", "repo": "packs", "title": "team",
                "output_ref": "bosun/c-004-team", "options": {}}
        with self.assertRaisesRegex(merging.MergeRefused, "pack-team"):
            merging.land_card(cfg, card)
        self.assertFalse((clone / "x").exists())

    def test_a_folder_the_packs_repo_tracks_in_another_case_is_still_tracked(self):
        """r2.F4: the index holds `Mine/...`, the folder with its own repo is `mine`."""
        mine = self.packs / "mine"
        subprocess.run(["git", "init", "-q", "-b", "main", str(mine)], check=True)
        (mine / "pack.toml").write_text(PACK.format(name="mine"))
        blob = git(self.packs, "hash-object", "-w", str(mine / "pack.toml"))
        git(self.packs, "update-index", "--add", "--cacheinfo", f"100644,{blob},Mine/pack.toml")
        self.assertEqual(packclones.tracked(self.packs), ["mine"])
        self.assertEqual(packclones.found(self.packs), {})

    # ----- r2.D1: the early checks read what the merge would write, not the branch's tip -----

    def behind(self, card_id: str, *untrack: str) -> dict:
        """A card whose branch in the packs builder clone was cut while the packs repo still
        tracked `untrack`, and changes none of it; the packs repo has since stopped."""
        built = self.home / "builder" / "packs"
        git(self.packs, "add", "-A")
        git(self.packs, "commit", "-q", "-m", "tracked for now")
        git(built, "pull", "-q")
        branch = f"bosun/{card_id}-other"
        git(built, "checkout", "-q", "-b", branch)
        (built / "other.txt").write_text("unrelated\n")
        git(built, "add", "-A")
        git(built, "commit", "-q", "-m", "unrelated")
        git(self.packs, "rm", "-r", "-q", "--cached", *untrack)
        git(self.packs, "commit", "-q", "-m", "no longer tracked here")
        return {"id": card_id, "space": "personal", "repo": "packs", "title": "other",
                "output_ref": branch, "options": {}}

    def test_a_branch_behind_a_trunk_that_untracked_and_ignored_a_file_still_lands(self):
        (self.packs / "gen.txt").write_text("generated\n")
        card = self.behind("c-005", "gen.txt")
        (self.packs / ".git" / "info" / "exclude").write_text("gen.txt\n")
        merging.land_card(self.cfg(), card)
        self.assertTrue((self.packs / "other.txt").is_file())
        self.assertEqual((self.packs / "gen.txt").read_text(), "generated\n")
        self.assertEqual(git(self.packs, "ls-files", "--", "gen.txt"), "", "and it stays untracked")

    def test_a_packs_branch_cut_before_the_pack_left_lands_when_it_leaves_the_folder_alone(self):
        mine = self.packs / "mine"
        mine.mkdir()
        (mine / "pack.toml").write_text(PACK.format(name="mine"))
        card = self.behind("c-006", "mine")
        subprocess.run(["git", "init", "-q", "-b", "main", str(mine)], check=True)
        cfg = self.cfg()
        packclones.reconcile(cfg)
        self.assertEqual(list(packclones.found(self.packs)), ["mine"])
        merging.land_card(cfg, card)
        self.assertTrue((self.packs / "other.txt").is_file())
        self.assertEqual(git(self.packs, "ls-files", "--", "mine"), "", "the pack stays out of the packs repo")

    def test_a_file_renamed_onto_an_ignored_path_is_named_too(self):
        """r2.D2: a rename is an add at its new path; rename detection hid it from the words."""
        repo = self.base / "repo"
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        (repo / "a.txt").write_text("the same twenty lines\n" * 20)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "one")
        base = git(repo, "rev-parse", "HEAD")
        git(repo, "checkout", "-q", "-b", "card")
        git(repo, "mv", "a.txt", "notes.txt")
        git(repo, "commit", "-q", "-m", "renamed")
        merged = git(repo, "rev-parse", "HEAD")
        git(repo, "checkout", "-q", "main")
        (repo / ".git" / "info" / "exclude").write_text("notes.txt\n")
        (repo / "notes.txt").write_text("mine\n")
        with self.assertRaisesRegex(merging.MergeRefused, "ignored files this change would write over: notes.txt"):
            merging.settle(repo, "main", base, merged)
        self.assertEqual((repo / "notes.txt").read_text(), "mine\n")

    # ----- r2.D3: a path that is exactly the folder's name, an embedded repo entry -----

    def test_a_folder_the_packs_repo_holds_as_an_embedded_repo_entry_is_tracked(self):
        clone = self.clone()
        head = git(clone, "rev-parse", "HEAD")
        git(self.packs, "update-index", "--add", "--cacheinfo", f"160000,{head},team")
        self.assertEqual(packclones.tracked(self.packs), ["team"])
        self.assertEqual(packclones.found(self.packs), {})

    def test_a_landing_that_adds_the_folder_as_an_embedded_repo_entry_is_refused(self):
        clone = self.clone()
        cfg = self.cfg()
        packclones.reconcile(cfg)
        built = self.home / "builder" / "packs"
        git(built, "checkout", "-q", "-b", "bosun/c-007-link")
        git(built, "update-index", "--add", "--cacheinfo", f"160000,{git(clone, 'rev-parse', 'HEAD')},team")
        git(built, "commit", "-q", "-m", "team as an embedded repo")
        card = {"id": "c-007", "space": "personal", "repo": "packs", "title": "link",
                "output_ref": "bosun/c-007-link", "options": {}}
        with self.assertRaisesRegex(merging.MergeRefused, "pack-team"):
            merging.land_card(cfg, card)
        self.assertEqual(git(self.packs, "ls-files", "--", "team"), "")

    def test_the_fast_forward_never_writes_over_an_ignored_file(self):
        repo = self.base / "repo"
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        git(repo, "commit", "-q", "--allow-empty", "-m", "one")
        base = git(repo, "rev-parse", "HEAD")
        git(repo, "checkout", "-q", "-b", "card")
        (repo / "notes.txt").write_text("theirs\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "notes")
        merged = git(repo, "rev-parse", "HEAD")
        git(repo, "checkout", "-q", "main")
        (repo / ".git" / "info" / "exclude").write_text("notes.txt\n")
        (repo / "notes.txt").write_text("mine\n")
        with self.assertRaises(merging.MergeRefused) as caught:
            merging.settle(repo, "main", base, merged)
        self.assertEqual((repo / "notes.txt").read_text(), "mine\n")
        self.assertEqual(git(repo, "rev-parse", "HEAD"), base)
        said = str(caught.exception)            # r2.F2: in plain words, never git's own
        self.assertIn(f"{repo} holds ignored files this change would write over: notes.txt", said)
        self.assertIn("Nothing was merged", said)
        self.assertIn("Move or delete them there, then approve again", said)
        self.assertNotIn("untracked", said)

    def test_it_is_said_before_the_suite_is_paid_for(self):
        """r2.F2: a landing on the checkout's own branch is refused before anything is built."""
        cfg = self.cfg()
        (self.packs / ".git" / "info" / "exclude").write_text("notes.txt\n")
        (self.packs / "notes.txt").write_text("mine\n")
        built = self.home / "builder" / "packs"
        git(built, "checkout", "-q", "-b", "bosun/c-003-notes")
        (built / "notes.txt").write_text("theirs\n")
        git(built, "add", "-A")
        git(built, "commit", "-q", "-m", "notes")
        card = {"id": "c-003", "space": "personal", "repo": "packs", "title": "notes",
                "output_ref": "bosun/c-003-notes", "options": {}}
        with mock.patch.object(merging, "build_and_test") as suite, \
                self.assertRaisesRegex(merging.MergeRefused, "ignored files this change would write over: notes.txt"):
            merging.land_card(cfg, card)
        suite.assert_not_called()
        self.assertEqual((self.packs / "notes.txt").read_text(), "mine\n")


class ChecksReadItUnchangedTest(ClonedPackCase):
    """The checks that read `<install>/packs/*` read a cloned pack's suite and terms as a
    tracked pack's: they list the folder, and a clone is a folder."""

    def setUp(self):
        super().setUp()
        self.clone()
        packclones.reconcile(self.cfg())
        self.tree = self.base / "tree"
        (self.tree / "keel").mkdir(parents=True)
        (self.tree / "keel" / "leak.py").write_text(f"NAME = '{WORD}'\n")
        subprocess.run(["git", "init", "-q", str(self.tree)], check=True)
        self.named = str(self.home / "config.toml")

    def test_its_suite_is_one_of_the_pack_suites(self):
        self.assertIn(self.packs / "team" / "tests", packsuites.suites(self.tree, self.named))

    def test_its_drift_terms_still_fail_the_tree(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = installdrift.main(self.tree, {"KEEL_CONFIG": self.named})
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn("keel/leak.py: 1 hit", out.getvalue())

    def test_the_public_check_knows_its_terms(self):
        names = publiccheck.install_names(self.home, self.tree, git=lambda root, key: "",
                                          home=lambda: self.base, hostname=lambda: "localhost")
        self.assertIn(WORD, names.terms)


if __name__ == "__main__":
    unittest.main()
