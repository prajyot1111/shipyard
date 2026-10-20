"""Another provider: Bosun drafts a connection (keel/packdraft.py, keel/scaffold.py, c-678).
The page's verb files one card for the builder, in the pattern of Import my Claude setup,
with the user's words and the way to a checked starting point (`keel new pack --into`); the
report says how that card stands. On a real scratch install from `shipyard init`; no
session is started."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import actions, firstrunsteps, onboarding, packdraft, packs, readiness, scaffold
from keel import config as config_module
from keel.board import open_board
from tests.helpers import no_real_tools
from tests.test_installer import init

ROOT = Path(__file__).resolve().parent.parent
WORDS = "We use Gitea at git.example.org. A teammate reviews each pull request and merges it."


class DraftCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        no_real_tools(self)
        readiness.forget()
        self.addCleanup(readiness.forget)
        for name, value in (("keel.prereqs.gather", []), ("keel.readiness.serve_status", {"missing": True})):
            fake = mock.patch(name, return_value=value)
            fake.start()
            self.addCleanup(fake.stop)
        self.home = Path(tmp.name).resolve() / "install"
        self.assertEqual(init(self.home), 0)

    def cfg(self):
        return config_module.load(self.home / "config.toml", ensure=False)

    def act(self, body):
        cfg = self.cfg()
        with open_board(cfg) as board:
            return actions.act(cfg, board, body)

    def card(self, card_id):
        cfg = self.cfg()
        with open_board(cfg) as board:
            return board.get(card_id)


class DraftTest(DraftCase):
    def test_the_tap_files_one_card_for_the_builder_with_the_users_words(self):
        done = self.act({"verb": "setup.pack.draft", "space": "personal", "words": WORDS})
        found = self.card(done["card"])
        self.assertEqual((found["space"], found["repo"], found["stage"]), ("personal", "packs", "assigned"))
        self.assertEqual(found["title"], packdraft.CONNECTION_TITLE)
        self.assertEqual(found["autonomy"], "attended", "the user reads its plan before it builds")
        self.assertIn(WORDS, found["brief"])
        self.assertIn("keel new pack <name> --kit --into", found["brief"])
        self.assertNotIn("copy of the sandbox pack", found["brief"])
        self.assertIn(f"bosun/{done['card']}-connection", found["brief"])
        self.assertIn("docs/atlas/62-packs.md", found["brief"])
        self.assertIn("for the personal space", found["brief"])

    def test_the_brief_starts_from_the_kit_and_is_done_when_the_pack_check_is_green(self):
        """c-735: Bosun writes only what is the host's own (its layer, its stand-in, its
        sentences) on the pack kit, never a copy of another pack, and the draft is done once
        `keel pack check` passes."""
        done = self.act({"verb": "setup.pack.draft", "space": "personal", "words": WORDS})
        brief = self.card(done["card"])["brief"]
        for said in ("keel new pack <name> --kit --into", "the host layer", "its stand-in", "its sentences",
                     "Never copy another pack", "keel pack check <your pack>", "is green"):
            self.assertIn(said, brief)

    def test_the_brief_says_whether_the_pack_should_review_pull_requests_too(self):
        """c-730: the draft choice asks; a yes has Bosun build the review verb in the GitHub pack's
        pattern, and anything else has it leave review scanning out."""
        yes = self.act({"verb": "setup.pack.draft", "space": "personal", "words": WORDS, "reviews": True})
        brief = self.card(yes["card"])["brief"]
        self.assertIn(packdraft.REVIEWS_YES.splitlines()[0], brief)
        for said in ("`review scan`", "`reviews = true`", "packs/github", "review_scan = false"):
            self.assertIn(said, brief)
        cfg = self.cfg()
        with open_board(cfg) as board:
            board.conn.execute("UPDATE cards SET stage = 'done' WHERE id = ?", (yes["card"],))
            board.conn.commit()
        no = self.act({"verb": "setup.pack.draft", "space": "personal", "words": WORDS})
        brief = self.card(no["card"])["brief"]
        self.assertIn("The user did not ask for review requests", brief)
        self.assertNotIn("`review scan`", brief)

    def test_it_needs_the_users_words(self):
        with self.assertRaisesRegex(actions.ActionError, "Which code host, and what should Shipyard do there"):
            self.act({"verb": "setup.pack.draft", "space": "personal", "words": "  "})

    def test_one_draft_at_a_time(self):
        card = self.act({"verb": "setup.pack.draft", "space": "personal", "words": WORDS})["card"]
        with self.assertRaisesRegex(actions.ActionError, f"{card} is already drafting a connection"):
            self.act({"verb": "setup.pack.draft", "space": "personal", "words": WORDS})

    def test_it_is_refused_for_a_space_that_is_not_there(self):
        with self.assertRaisesRegex(actions.ActionError, "there is no space"):
            self.act({"verb": "setup.pack.draft", "space": "nowhere", "words": WORDS})

    def test_the_report_says_how_the_draft_stands(self):
        self.assertEqual(onboarding.report(self.cfg())["builder"]["connection"],
                         {"open": None, "done": None, "pack": None, "space": None})
        card = self.act({"verb": "setup.pack.draft", "space": "personal", "words": WORDS})["card"]
        found = onboarding.report(self.cfg())["builder"]["connection"]
        self.assertEqual(found, {"open": {"card": card, "stage": "assigned", "waiting": False, "gate": None, "told": False,
                                          "space": "personal"},
                                 "done": None, "pack": None, "space": None})
        cfg = self.cfg()
        with open_board(cfg) as board:
            board.conn.execute("UPDATE cards SET stage = 'done' WHERE id = ?", (card,))
            board.conn.commit()
        # c-734: a done draft with no landing read names no pack; r2.F4: it names the space it
        # was drafted for, so the page offers its pack there only
        self.assertEqual(onboarding.report(self.cfg())["builder"]["connection"],
                         {"open": None, "done": card, "pack": None, "space": "personal"})

    def test_the_draft_card_records_the_space_it_is_for(self):
        """r2.F4: filed in personal whatever space it is for, so the target is recorded on it."""
        from keel import packdraft
        self.act({"verb": "setup.space.add", "space": "team"})
        card = self.act({"verb": "setup.pack.draft", "space": "team", "words": WORDS})["card"]
        with open_board(self.cfg()) as board:
            made = board.get(card)
        self.assertEqual(made["space"], "personal")
        self.assertEqual(made["options"].get(packdraft.TARGET_OPTION), "team")

    def test_a_draft_card_is_not_the_users_first_card(self):
        from keel import firstrun
        self.act({"verb": "setup.pack.draft", "space": "personal", "words": WORDS})
        cfg = self.cfg()
        with open_board(cfg) as board:
            step = next(s for s in firstrun.report(cfg, board)["steps"] if s["id"] == "first-card")
        self.assertNotIn("card", step)


PACK = 'name = "{name}"\nversion = "1"\ndescription = "a drafted connection"\n\n[provides]\nconfig_example = "config.example.toml"\n'
EXAMPLE = '[spaces.work]\npack = "{name}"\nconfig_dir = "~/.claude"\n'


def git(repo: Path, *argv: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *argv],
                          capture_output=True, text=True, check=True).stdout.strip()


class ChoiceStepTest(DraftCase):
    """Where finished work goes while a connection draft stands (c-758, `firstrunsteps.draft_waiting`):
    the two states that hold the step, and every way it is let go again."""

    def setUp(self):
        super().setUp()
        # a draft lands in the install's own packs folder, which is read through KEEL_CONFIG
        os.environ["KEEL_CONFIG"] = str(self.home / "config.toml")
        packs.forget()
        self.addCleanup(packs.forget)

    def choice_step(self):
        from keel import firstrun
        cfg = self.cfg()
        readiness.forget()
        with open_board(cfg) as board:
            return next(s for s in firstrun.report(cfg, board)["steps"] if s["id"] == "integrations")

    def draft(self, space="personal"):
        return self.act({"verb": "setup.pack.draft", "space": space, "words": WORDS})["card"]

    def landed(self, card, name="forge"):
        """The draft landed as a landing lands it: its pack added to the install's packs repo by
        a merge, the card done, and the merge recorded as the card's landing."""
        repo = self.home / "packs"
        main = git(repo, "branch", "--show-current")
        git(repo, "checkout", "-q", "-b", f"draft-{name}")
        (repo / name).mkdir()
        (repo / name / "pack.toml").write_text(PACK.format(name=name))
        (repo / name / "config.example.toml").write_text(EXAMPLE.format(name=name))
        git(repo, "add", name)
        git(repo, "commit", "-q", "-m", f"{name}: a drafted connection")
        git(repo, "checkout", "-q", main)
        git(repo, "merge", "-q", "--no-ff", "-m", "the draft lands", f"draft-{name}")
        with open_board(self.cfg()) as board:
            board.stage(card, "building", "drain")
            board.stage(card, "review", "house", plan_ref="plan.md", output_ref="out.md")
            board.stage(card, "done", "drain")
            board.set_fields(card, {"options": {"landing": {"merge": git(repo, "rev-parse", "HEAD")}}}, "drain")
        return name

    def test_a_draft_in_progress_keeps_the_step_open_and_names_skip(self):
        self.assertIsNone(self.choice_step()["done"], "nothing to check while work stays on this computer")
        card = self.draft()
        step = self.choice_step()
        self.assertIs(step["done"], False)
        self.assertEqual(step["why"], f"Bosun is drafting a connection for personal ({card}); until it has landed "
                                      f"and you turn it on, work is merged on this computer: skip this step to "
                                      f"carry on meanwhile")

    def test_a_landed_draft_that_is_not_turned_on_does_not_read_as_done(self):
        card = self.draft()
        self.landed(card)
        step = self.choice_step()
        self.assertIs(step["done"], False)
        self.assertEqual(step["why"], f"the connection Bosun drafted (forge, {card}) has landed and is not turned on "
                                      f"for personal: turn it on, or skip this step to keep work on this computer")

    def test_a_draft_for_a_space_already_on_a_connection_holds_nothing_open_or_landed(self):
        self.act({"verb": "setup.pack.on", "pack": "sandbox", "space": "personal"})
        card = self.draft()
        self.assertNotIn("drafting", self.choice_step()["why"])
        self.landed(card)
        self.assertNotIn("drafted", self.choice_step()["why"])

    def test_a_landed_draft_that_names_no_space_holds_nothing(self):
        card = self.draft()
        with open_board(self.cfg()) as board:
            board.set_fields(card, {"options": {packdraft.TARGET_OPTION: ""}}, "him")
        self.landed(card)
        self.assertIsNone(self.choice_step()["done"])

    def test_a_draft_for_a_space_that_is_gone_holds_nothing(self):
        card = self.draft()
        with open_board(self.cfg()) as board:
            board.set_fields(card, {"options": {packdraft.TARGET_OPTION: "gone"}}, "him")
        self.assertIsNone(self.choice_step()["done"], "open")
        self.landed(card)
        self.assertIsNone(self.choice_step()["done"], "landed")

    def test_a_landed_draft_whose_connection_no_longer_loads_holds_nothing(self):
        card = self.draft()
        name = self.landed(card)
        shutil.rmtree(self.home / "packs" / name)
        self.assertIsNone(self.choice_step()["done"])

    def test_an_archived_draft_card_holds_nothing(self):
        card = self.draft()
        with open_board(self.cfg()) as board:
            board.set_fields(card, {"options": {"archived": True}}, "him")
        self.assertIsNone(self.choice_step()["done"])

    def test_an_open_draft_does_not_hide_another_spaces_failing_checks(self):
        """The draft is for team; personal is on a connection that is not ready: both are said."""
        plain = self.home / "packs" / "plain"
        plain.mkdir()
        (plain / "pack.toml").write_text(PACK.format(name="plain"))
        (plain / "config.example.toml").write_text(EXAMPLE.format(name="plain"))
        self.act({"verb": "setup.space.add", "space": "team"})
        self.act({"verb": "setup.pack.on", "pack": "plain", "space": "personal"})
        before = self.choice_step()
        self.assertIs(before["done"], False, before["why"])
        card = self.draft("team")
        step = self.choice_step()
        self.assertIs(step["done"], False)
        self.assertIn(f"Bosun is drafting a connection for team ({card})", step["why"])
        self.assertIn(before["why"], step["why"])

    def test_a_landed_draft_still_holds_the_step_while_another_draft_is_open_for_a_space_on_a_connection(self):
        """r2.F3: the open draft holds nothing (its space is on a connection), so it does not
        let the landed one go: the page still says the step is not done."""
        self.act({"verb": "setup.space.add", "space": "team"})
        card = self.draft("team")
        self.landed(card)
        self.act({"verb": "setup.pack.on", "pack": "sandbox", "space": "personal"})
        self.draft("personal")
        step = self.choice_step()
        self.assertIs(step["done"], False, step["why"])
        self.assertIn(f"the connection Bosun drafted (forge, {card}) has landed and is not turned on for team",
                      step["why"])

    def test_keeping_work_on_this_computer_works_while_no_connection_is_listed(self):
        """r2.F1: one connection that does not load empties the list, so the connection a space
        is on is not drawn, with no Turn off. The step then names the Keep work button, so
        that tap (`setup.pack.off`) must go through in that state."""
        for name in ("plain", "other"):
            folder = self.home / "packs" / name
            folder.mkdir()
            (folder / "pack.toml").write_text(PACK.format(name=name))
            (folder / "config.example.toml").write_text(EXAMPLE.format(name=name))
        self.act({"verb": "setup.pack.on", "pack": "plain", "space": "personal"})
        (self.home / "packs" / "other" / "pack.toml").write_text("name = \n")
        packs.forget()
        readiness.forget()
        cfg = self.cfg()
        report = onboarding.report(cfg)
        self.assertEqual(report["packs"], [], "no connection is listed while one does not load")
        self.assertTrue(report["connections_error"])
        self.assertEqual(cfg.spaces["personal"].adapter, "plain")
        done = self.act({"verb": "setup.pack.off", "space": "personal"})
        self.assertIn("stays on this computer now", done["note"])
        self.assertIsNone(self.cfg().spaces["personal"].adapter)

    def test_a_space_whose_own_connection_does_not_load_is_a_config_that_does_not_load(self):
        """r2.F1, the other half: when the broken connection is the one the space is on, the
        config itself is refused, so the step is never drawn in that state and promises nothing."""
        plain = self.home / "packs" / "plain"
        plain.mkdir()
        (plain / "pack.toml").write_text(PACK.format(name="plain"))
        (plain / "config.example.toml").write_text(EXAMPLE.format(name="plain"))
        self.act({"verb": "setup.pack.on", "pack": "plain", "space": "personal"})
        (plain / "pack.toml").write_text("name = \n")
        packs.forget()
        with self.assertRaises(config_module.ConfigError):
            self.cfg()

    def test_a_second_state_build_with_a_landed_draft_starts_no_process(self):
        """r1.F9: the state is built on every poll, so the landed draft's connection is read once
        and kept; the next build asks git nothing and scans no card but the drafts."""
        card = self.draft()
        self.landed(card)
        cfg = self.cfg()
        readiness.forget()
        with open_board(cfg) as board:
            ready = readiness.build(cfg)
            first = firstrunsteps.integrations_state(cfg, ready, board)
            with mock.patch("subprocess.run", side_effect=AssertionError("a process was started")), \
                    mock.patch.object(board, "list_cards", side_effect=AssertionError("the whole board was scanned")):
                second = firstrunsteps.integrations_state(cfg, ready, board)
        self.assertEqual(first, second)
        self.assertIn("has landed and is not turned on", second[1])

    def clock(self, at: float):
        """`readiness` reading the time as `at` says: a stand-in for its `time` alone."""
        return mock.patch.object(readiness, "time", mock.Mock(monotonic=lambda: at))

    def test_a_failed_read_of_the_landed_drafts_connection_is_kept_only_briefly(self):
        """Fix check D2, bounded: git could not say what the landing added. That is kept for
        `RETRY_SECONDS`, not `KEEP_SECONDS`: a passing failure heals within half a minute, and
        one that never passes costs one process per half minute, not one per state build."""
        from keel import merging
        card = self.draft()
        self.landed(card)
        cfg = self.cfg()
        readiness.forget()
        refused = merging.MergeRefused("the repo is locked")
        with open_board(cfg) as board:
            with mock.patch.object(merging, "git", side_effect=refused) as asked:
                with self.clock(1000.0):
                    self.assertIsNone(packdraft.standing(board, cfg)["pack"])
                with self.clock(1000.0 + readiness.RETRY_SECONDS - 1):
                    self.assertIsNone(packdraft.standing(board, cfg)["pack"])
                self.assertEqual(asked.call_count, 1, "inside the short window the failure is not asked again")
                with self.clock(1000.0 + readiness.RETRY_SECONDS + 1):
                    self.assertIsNone(packdraft.standing(board, cfg)["pack"])
                self.assertEqual(asked.call_count, 2, "after it, git is asked again")
            # git answers again: the step holds within the short window's end, long before KEEP_SECONDS
            with self.clock(1000.0 + 2 * readiness.RETRY_SECONDS + 2):
                ready = readiness.build(cfg)
                after = firstrunsteps.integrations_state(cfg, ready, board)
        self.assertLess(readiness.RETRY_SECONDS, readiness.KEEP_SECONDS)
        self.assertIs(after[0], False)
        self.assertIn("has landed and is not turned on", after[1])

    def test_a_real_answer_is_kept_the_full_time_even_when_it_is_none(self):
        """A landing that added no pack is an answer (r1.F9): kept for `KEEP_SECONDS`, past the
        short window a failed read gets."""
        card = self.draft()
        self.landed(card)
        cfg = self.cfg()
        readiness.forget()
        with open_board(cfg) as board:
            with mock.patch.object(packdraft, "added_pack", return_value=None) as read:
                for at in (0, readiness.RETRY_SECONDS + 1, readiness.KEEP_SECONDS - 1):
                    with self.clock(1000.0 + at):
                        self.assertIsNone(packdraft.standing(board, cfg)["pack"])
                self.assertEqual(read.call_count, 1)
                with self.clock(1000.0 + readiness.KEEP_SECONDS + 1):
                    packdraft.standing(board, cfg)
                self.assertEqual(read.call_count, 2)


class IntoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "code"
        shutil.copytree(ROOT / "packs" / "sandbox", self.root / "packs" / "sandbox",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        self.clone = Path(self.tmp.name) / "builder" / "packs"
        self.clone.mkdir(parents=True)

    def args(self, *argv):
        return scaffold.build_parser().parse_args(list(argv))

    def never(self):
        raise AssertionError("the config was read")

    def test_into_writes_the_pack_where_the_builder_says(self):
        written = scaffold.run(self.args("pack", "forge", "--into", str(self.clone)), self.never, self.root)
        self.assertTrue((self.clone / "forge" / "pack.toml").is_file())
        self.assertTrue(all(str(path).startswith(str(self.clone / "forge")) for path in written))
        self.assertFalse((self.root / "packs" / "forge").exists())

    def test_into_is_a_packs_alone_and_never_with_install(self):
        with self.assertRaisesRegex(scaffold.Refused, "--into is for a pack"):
            scaffold.run(self.args("view", "demo", "--into", str(self.clone)), self.never, self.root)
        with self.assertRaisesRegex(scaffold.Refused, "one of --into and --install"):
            scaffold.run(self.args("pack", "forge", "--into", str(self.clone), "--install"), self.never, self.root)

    def test_into_a_folder_that_is_not_there_is_refused(self):
        with self.assertRaisesRegex(scaffold.Refused, "is not a folder"):
            scaffold.run(self.args("pack", "forge", "--into", str(self.clone / "nowhere")), self.never, self.root)


if __name__ == "__main__":
    unittest.main()
