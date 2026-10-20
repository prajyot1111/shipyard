"""The first run (keel/firstrun.py, c-632): the core steps in the approved order (c-677) on a
fresh install, done read from readiness and never stored, a skip and Finish the only things written, an
install that predates the stepper never sent to Start, and a pack's own step placed after
Where finished work goes. All on a real scratch install from `shipyard init`."""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from keel import actions, deckstate, firstrun, login, onboarding, packsetup, readiness, settings
from keel import config as config_module
from keel.board import open_board
from tests.helpers import no_real_tools
from tests.test_installer import init
from tests.test_readiness import MISSING, fake_tailscale

CORE = ["choose-builder", "prerequisites", "login", "builder", "repos", "memory", "rules", "integrations",
        "defaults", "browser", "backup", "first-card", "set-up"]
TITLES = ["Choose your builder", "Check this computer", "Sign in to Claude", "Meet Bosun", "Add your repos",
          "How Shipyard remembers", "Set up your repos with Bosun", "Where finished work goes", "How work ships",
          "A browser for sessions", "Back up", "Your first card", "You are set up"]


class FirstRunTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        no_real_tools(self)
        readiness.forget()
        self.addCleanup(readiness.forget)
        gather = mock.patch("keel.prereqs.gather", return_value=[])
        self.gather = gather.start()
        self.addCleanup(gather.stop)
        self.home = Path(tmp.name).resolve() / "install"
        self.assertEqual(init(self.home), 0)
        fake_tailscale(self.home.parent / "bin", "{}")
        self.logged_in()

    def cfg(self):
        return config_module.load(self.home / "config.toml", ensure=False)

    def logged_in(self, state=login.GOOD):
        login.record(self.cfg(), "personal", {"state": state, "why": ""}, login.now())

    def report(self, cfg=None):
        cfg = cfg or self.cfg()
        readiness.forget()
        with open_board(cfg) as board:
            return firstrun.report(cfg, board)

    def step(self, report, step):
        return next(s for s in report["steps"] if s["id"] == step)

    def test_the_sign_in_step_promises_only_what_keel_does(self):
        """It said Keel tells you two days before the sign-in runs out; Keel holds no date for
        that and learns it from a session that failed (c-678 review r2.F7)."""
        said = firstrun.BY_ID["login"].about
        self.assertNotIn("two days", said)
        self.assertIn("When it runs out, Shipyard says so on every page with the way to sign in again.", said)

    def act(self, verb, **body):
        cfg = self.cfg()
        with open_board(cfg) as board:
            return actions.act(cfg, board, {"verb": verb, **body})

    def stored(self):
        return json.loads((self.home / "state" / firstrun.FILE).read_text())

    def bare(self) -> Path:
        work, origin = self.home.parent / "work", self.home.parent / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        subprocess.run(["git", "init", "-q", str(work)], check=True)
        (work / "README").write_text("hello\n")
        for argv in (["add", "."], ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "one"],
                     ["push", "-q", str(origin), "HEAD:main"]):
            subprocess.run(["git", "-C", str(work), *argv], check=True)
        return origin

    def test_a_fresh_install_reports_the_core_steps_in_the_approved_order_and_opens_start(self):
        report = self.report()
        self.assertEqual([s["id"] for s in report["steps"]], CORE)
        self.assertEqual([s["title"] for s in report["steps"]], TITLES)
        self.assertEqual([s["id"] for s in report["steps"] if s["required"]], ["prerequisites", "login"])
        self.assertEqual([s["id"] for s in report["steps"] if s["optional"]], ["browser"])
        self.assertTrue(self.step(report, "prerequisites")["done"])
        self.assertIsNone(self.step(report, "defaults")["done"])
        self.assertEqual((report["finished"], report["redirect"]), (None, True))
        self.assertEqual(self.stored(), {"skipped": {}, "finished": None})

    def test_the_checks_and_the_login_are_a_step_each(self):
        """c-677: what was one Prerequisites step is Check this computer, then Sign in to
        Claude; each follows its own readiness row."""
        self.gather.return_value = [MISSING]
        report = self.report()
        self.assertEqual(self.step(report, "prerequisites")["why"], "git: not found")
        self.assertTrue(self.step(report, "login")["done"])
        self.gather.return_value = []
        self.logged_in(login.EXPIRED)
        report = self.report()
        self.assertTrue(self.step(report, "prerequisites")["done"])
        self.assertFalse(self.step(report, "login")["done"])
        self.assertEqual(self.step(report, "login")["why"], "Shipyard is not signed in to Claude yet")
        self.assertTrue(report["redirect"])
        self.logged_in()
        self.assertTrue(self.step(self.report(), "login")["done"])

    def test_the_steps_from_meet_bosun_on_say_so(self):
        """c-677: the header line is for the steps from Meet Bosun on, a pack's own step
        following the place it is put. (A failed check's third part is not tied to the step:
        the deck draws it wherever Bosun's session can run, which is the builder row ready,
        the login row ready (one that could not be checked counts; an expired or missing one
        does not) and no required machine check failing.)"""
        onboarding.add_space(self.cfg(), "work")
        packsetup.pack_on(self.cfg(), "sandbox", "work")
        flags = {s["id"]: s["bosun"] for s in self.report()["steps"]}
        self.assertEqual([step for step in flags if not flags[step]], ["choose-builder", "prerequisites", "login"])
        self.assertTrue(flags["builder"] and flags["sandbox:try"] and flags["set-up"])

    def test_choose_your_builder_waits_for_a_pick_and_reads_it_from_the_config(self):
        """c-678: neither form is preselected. A new install's config names no `[builder]
        mode`, so the step is open until one is written; Full is bypass, Guide is auto."""
        step = self.step(self.report(), "choose-builder")
        self.assertEqual((step["done"], step["choice"], step["required"]), (False, None, False))
        self.assertEqual(step["why"], "no builder is chosen yet")
        settings.save(self.cfg(), [{"table": "builder", "key": "mode", "value": "bypass"}])
        step = self.step(self.report(), "choose-builder")
        self.assertEqual((step["done"], step["choice"], step["why"]), (True, "full", "Full builder"))
        settings.save(self.cfg(), [{"table": "builder", "key": "mode", "value": "auto"}])
        step = self.step(self.report(), "choose-builder")
        self.assertEqual((step["done"], step["choice"], step["why"]), (True, "guide", "Guide builder"))
        settings.save(self.cfg(), [{"table": "keel", "key": "bosun_builder", "value": False}])
        step = self.step(self.report(), "choose-builder")
        self.assertEqual((step["done"], step["choice"]), (False, None))
        self.assertIn("builder mode is off", step["why"])

    def test_full_builder_is_the_acceptance_of_bypass_mode_and_guide_takes_it_back(self):
        """c-729: the page already explains the risk, so choosing Full records Claude Code's
        own acceptance of bypass mode in the install's Claude folder (its user settings,
        where a background session reads it); Guide, or builder mode off, removes it. Every
        other key of that file stays as it was."""
        written = self.home / "claude" / "settings.json"
        written.write_text(json.dumps({"theme": "dark"}))

        def held():
            return json.loads(written.read_text())
        settings.save(self.cfg(), [{"table": "builder", "key": "mode", "value": "auto"}])
        self.assertEqual(held(), {"theme": "dark"})
        settings.save(self.cfg(), [{"table": "builder", "key": "mode", "value": "bypass"}])
        self.assertEqual(held(), {"theme": "dark", "skipDangerousModePermissionPrompt": True})
        settings.save(self.cfg(), [{"table": "builder", "key": "mode", "value": "auto"}])
        self.assertEqual(held(), {"theme": "dark"})
        settings.save(self.cfg(), [{"table": "builder", "key": "mode", "value": "bypass"}])
        settings.save(self.cfg(), [{"table": "keel", "key": "bosun_builder", "value": False}])
        self.assertEqual(held(), {"theme": "dark"})

    def test_a_claude_folder_the_install_does_not_own_is_never_touched(self):
        """c-729 r1.F1: the acceptance is written only into a Claude folder inside the install.
        A personal space pointed at a folder outside it (the user's own ~/.claude) keeps that
        folder's settings byte for byte, and a settings.json that is a link stays a link."""
        outside = self.home.parent / "own-claude"
        outside.mkdir()
        mine = outside / "settings.json"
        mine.write_text('{"skipDangerousModePermissionPrompt": true, "theme": "light"}\n')
        before = mine.read_bytes()
        text = (self.home / "config.toml").read_text()
        (self.home / "config.toml").write_text(text.replace(str(self.home / "claude"), str(outside), 1))
        self.assertEqual(self.cfg().spaces["personal"].config_dir, outside)
        for mode in ("auto", "bypass", "auto"):
            settings.save(self.cfg(), [{"table": "builder", "key": "mode", "value": mode}])
            self.assertEqual(mine.read_bytes(), before, mode)
        (self.home / "config.toml").write_text(text)
        target = self.home.parent / "dotfiles-settings.json"
        target.write_text("{}\n")
        link = self.home / "claude" / "settings.json"
        link.unlink(missing_ok=True)
        link.symlink_to(target)
        settings.save(self.cfg(), [{"table": "builder", "key": "mode", "value": "bypass"}])
        self.assertTrue(link.is_symlink(), "a linked settings.json is never replaced by a plain file")
        self.assertEqual(target.read_text(), "{}\n")

    def test_choose_your_builder_has_no_skip_and_never_sends_a_finished_install_to_start(self):
        """c-678: the design gives step 0 no Skip. It is not a required step all the same: a
        finished install whose config names no mode is not sent back to Start by it."""
        with self.assertRaisesRegex(actions.ActionError, "Choose your builder cannot be skipped"):
            self.act("firstrun.skip", step="choose-builder")
        step = self.step(self.report(), "choose-builder")
        self.assertEqual((step["skip"], step["required"]), (False, False))
        self.assertTrue(self.step(self.report(), "repos")["skip"])
        self.act("firstrun.finish")
        report = self.report()
        self.assertFalse(self.step(report, "choose-builder")["done"])
        self.assertFalse(report["redirect"])

    def test_meet_bosun_is_done_once_bosun_runs_and_has_the_users_first_message(self):
        """c-678: the builder ready, Bosun's session up, and a message of the user's in it."""
        from keel import bosunhello, console
        bosunhello.forget()
        self.addCleanup(bosunhello.forget)
        self.addCleanup(console.forget_view)
        console.forget_view()
        step = self.step(self.report(), "builder")
        self.assertEqual((step["done"], step["running"], step["hello"]), (False, False, False))
        self.assertEqual(step["why"], "Bosun is not running yet")
        cfg = self.cfg()
        console.write_state(cfg, {"session_id": "s-1", "bg_id": "b-1"})
        row = {"id": "b-1", "sessionId": "s-1", "pid": 7, "status": "idle"}
        with mock.patch("keel.harness.agents", return_value=[row]), \
                mock.patch("keel.harness.find", return_value=row):
            console.forget_view()
            step = self.step(self.report(), "builder")
            self.assertEqual((step["done"], step["running"], step["hello"]), (False, True, False))
            self.assertEqual(step["why"], "Bosun is running: say hello in its session")
            # a session Shipyard cannot see into is said so, and is not asked for a hello again (F20)
            with mock.patch.object(bosunhello, "hidden", return_value=True):
                step = self.step(self.report(), "builder")
            self.assertEqual((step["done"], step.get("sure"), step["hidden"]), (True, False, True))
            self.assertEqual(step["why"], "Bosun is running. Shipyard cannot see into its session from here, so it "
                                          "cannot tell whether you have said hello")
            path = console.config_dir(cfg) / "projects" / "x" / "s-1.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": "hello"}}) + "\n")
            step = self.step(self.report(), "builder")
        self.assertEqual((step["done"], step["running"], step["hello"]), (True, True, True))

    def test_building_the_report_runs_neither_node_nor_the_harness(self):
        """The fence does not cover them (review F18), so the base stands in for both: a
        report built in a test asks no real `node` for its version and no real `claude` for
        its sessions."""
        ran = []
        real = subprocess.run

        def spy(argv, *args, **rest):
            ran.append(Path(str(argv[0] if isinstance(argv, (list, tuple)) else argv).split()[0]).name)
            return real(argv, *args, **rest)
        with mock.patch("subprocess.run", spy):
            self.report()
            cfg = self.cfg()
            with open_board(cfg) as board:
                deckstate.build(cfg, board, rows=[])
        self.assertEqual(sorted({"node", "claude"} & set(ran)), [], ran)

    def heavy(self):
        """The step readings that cost something on every state build (review F11)."""
        return {name: mock.patch(name, return_value=value) for name, value in (
            ("keel.tierdrafts.every", []), ("keel.bosunhello.said", False),
            ("keel.browserinstall.status", {"state": "waiting", "percent": 0, "received_mb": 0, "of_mb": 400, "said": ""}),
            ("keel.browserinstall.probe", {"ok": True, "said": "v22.0.0"}),
            ("keel.backupsetup.status", {"on": False, "suggested": "/x"}))}

    def test_a_finished_installs_state_reads_no_step_unless_start_asks(self):
        self.act("firstrun.finish")
        cfg = self.cfg()
        readiness.forget()
        patches = self.heavy()
        with open_board(cfg) as board:
            mocks = {name: patch.start() for name, patch in patches.items()}
            self.addCleanup(mock.patch.stopall)
            light = firstrun.report(cfg, board, steps=False)
            self.assertEqual([name for name, fake in mocks.items() if fake.called], [], "nothing slow was read")
            self.assertTrue(light["finished"])
            self.assertFalse(light["redirect"])
            self.assertEqual({step["id"]: step["done"] for step in light["steps"] if step["required"]},
                             {"prerequisites": True, "login": True}, "what a redirect is decided on is still read")
            self.assertTrue(all(step["light"] and step["done"] is None for step in light["steps"] if not step["required"]))
            full = firstrun.report(cfg, board)
            self.assertFalse(any(step.get("light") for step in full["steps"]))
            self.assertTrue(mocks["keel.tierdrafts.every"].called and mocks["keel.browserinstall.status"].called)

    def test_an_install_that_is_not_finished_reads_every_step_whoever_asks(self):
        cfg = self.cfg()
        with open_board(cfg) as board:
            report = firstrun.report(cfg, board, steps=False)
        self.assertFalse(any(step.get("light") for step in report["steps"]))
        self.assertEqual(self.step(report, "builder")["why"], "Bosun is not running yet")

    def test_the_state_says_whether_it_carries_the_steps(self):
        cfg = self.cfg()
        with open_board(cfg) as board:
            self.assertIs(deckstate.build(cfg, board, rows=[])["scope"]["steps"], True, "a machine reader's whole state")
            self.assertIs(deckstate.build(cfg, board, rows=[], scope="deck", steps=False)["scope"]["steps"], True,
                          "not finished: every step is read whoever asks")
        self.act("firstrun.finish")
        with open_board(cfg) as board:
            self.assertIs(deckstate.build(cfg, board, rows=[], scope="deck", steps=False)["scope"]["steps"], False)
            self.assertIs(deckstate.build(cfg, board, rows=[], scope="deck", steps=True)["scope"]["steps"], True)

    def test_the_meet_bosun_screen_is_told_the_form_and_whether_the_workspace_is_there(self):
        shown = firstrun.panels(self.cfg())["bosun"]
        self.assertEqual((shown["on"], shown["form"], shown["workspace"], shown["missing"]), (True, None, True, []))
        settings.save(self.cfg(), [{"table": "builder", "key": "mode", "value": "bypass"}])
        self.assertEqual(firstrun.panels(self.cfg())["bosun"]["form"], "full")
        shutil.rmtree(self.home / "builder" / "packs")
        shutil.rmtree(self.home / "packs")
        shown = firstrun.panels(self.cfg())["bosun"]
        self.assertEqual((shown["workspace"], shown["missing"]), (False, ["packs"]))
        self.assertIn("no clone of packs", shown["refusal"])

    def test_a_finished_install_is_not_reopened_or_rewritten_by_the_new_order(self):
        """c-677: an install set up before the order changed keeps its Finish and its skips,
        a skip of a step that is gone is left where it is, and nothing is written."""
        # `spaces` and `phone` are steps that are gone (c-677, c-678); `browser` is one that is there
        kept = {"skipped": {"spaces": "2026-09-20T10:00:00+00:00", "phone": "2026-09-20T10:00:00+00:00",
                            "browser": "2026-09-20T10:00:00+00:00"},
                "finished": "2026-09-20T10:05:00+00:00", "reason": firstrun.EXISTING}
        path = self.home / "state" / firstrun.FILE
        path.write_text(json.dumps(kept, indent=2) + "\n")
        before = path.read_bytes()
        report = self.report()
        self.assertEqual((report["finished"], report["reason"], report["redirect"]),
                         (kept["finished"], firstrun.EXISTING, False))
        self.assertEqual([s["id"] for s in report["steps"] if s["skipped"]], ["browser"])
        self.assertFalse(report["untouched"])
        # it is sent to Start again only as it was before: when a required step stops being met
        self.logged_in(login.EXPIRED)
        self.assertTrue(self.report()["redirect"], "an expired login opens Start, as it did")
        self.logged_in()
        self.assertFalse(self.report()["redirect"])
        self.gather.return_value = [MISSING]
        self.assertTrue(self.report()["redirect"], "a missing required check opens Start, as it did")
        self.assertEqual(path.read_bytes(), before)

    def test_an_install_nobody_has_acted_on_says_so_until_a_step_is_taken(self):
        """c-677 review F2: Choose your builder reads done on a fresh install (builder mode
        ships on), so the deck needs to know that the user has not been through the steps
        yet. Nothing is stored for it: no skip, no Finish, and no step after Meet Bosun done."""
        self.assertTrue(self.report()["untouched"])
        self.act("firstrun.skip", step="repos")
        self.assertFalse(self.report()["untouched"], "a skip is the user's")
        self.act("firstrun.unskip", step="repos")
        self.assertTrue(self.report()["untouched"])
        onboarding.clone_repo(self.cfg(), "personal", "api", str(self.bare()))
        self.assertFalse(self.report()["untouched"], "a repo is the user's")
        self.assertEqual(self.stored(), {"skipped": {}, "finished": None})

    def test_a_builder_mode_chosen_on_the_first_step_does_not_end_untouched(self):
        """c-677: a Save on Choose your builder is not a move off it. Were `untouched` to end
        there, the next state would take the screen off step 0 with no tap."""
        self.assertTrue(self.report()["untouched"])
        settings.save(self.cfg(), [{"table": "builder", "key": "mode", "value": "bypass"}])
        report = self.report()
        self.assertEqual(self.step(report, "choose-builder")["why"], "Full builder")
        self.assertTrue(report["untouched"])

    def test_a_login_that_could_not_be_checked_does_not_block_and_does_not_read_as_working(self):
        """c-677 review F3: the step's sentence is the readiness row's own, so the list and
        the screen say one thing."""
        login.record(self.cfg(), "personal", {"state": login.UNKNOWN, "why": "exit 2: x"}, login.now())
        report = self.report()
        step = self.step(report, "login")
        self.assertTrue(step["done"])
        self.assertEqual(step["why"], "the install's Claude login could not be checked last time "
                                      "(exit 2: x); houses try it as they run")
        self.assertIs(step["sure"], False, "done for Next and Finish, and said as not confirmed")
        self.act("firstrun.finish")
        report = self.report()
        self.assertTrue(report["finished"], "Finish does not wait for a login that could not be checked")
        self.assertFalse(report["redirect"], "and a finished install is not sent back to Start for it")
        self.logged_in()
        step = self.step(self.report(), "login")
        self.assertEqual(step["why"], "the install's Claude login works")
        self.assertNotIn("sure", step)

    def test_the_attach_line_copies_as_a_command_from_a_path_with_a_space(self):
        """c-677 review F6: the first run shows the line with Copy, so it is quoted."""
        from keel import deckstate
        home = self.home.parent / "my install"
        self.assertEqual(init(home), 0)
        cfg = config_module.load(home / "config.toml", ensure=False)
        self.assertEqual(deckstate.attach_line(cfg), f"'{home}/bin/keel' console attach")
        self.assertEqual(deckstate.attach_line(self.cfg()), f"{self.home}/bin/keel console attach")

    def test_how_keel_remembers_is_read_only_and_says_where_each_file_lives(self):
        """c-678: the memory page has nothing to check and no Skip, and its screen is told
        the real paths: each space's file, each cloned repo's, the rules, Bosun's memory."""
        step = self.step(self.report(), "memory")
        self.assertEqual((step["done"], step["skip"], step["required"], step["bosun"]), (None, False, False, True))
        with self.assertRaisesRegex(actions.ActionError, "How Shipyard remembers cannot be skipped"):
            self.act("firstrun.skip", step="memory")
        onboarding.add_space(self.cfg(), "work")
        onboarding.clone_repo(self.cfg(), "work", "api", str(self.bare()))
        cfg = self.cfg()
        shown = firstrun.panels(cfg)["memory"]
        self.assertEqual(shown["spaces"], [{"name": "work", "tier": str(self.home / "spaces" / "work" / "CLAUDE.md"),
                                            "repos": [{"key": "api", "tier": str(self.home / "spaces" / "work" / "api" / "CLAUDE.md")}]}])
        self.assertEqual(shown["rules"], str(cfg.root / "etc" / "house-contract.md"))
        self.assertEqual(shown["layout"], str(self.home / "spaces"))
        # c-722: Bosun's memory is the install's once it holds one
        (self.home / "memory" / "bosun").mkdir(parents=True, exist_ok=True)
        (self.home / "memory" / "bosun" / "MEMORY.md").write_text("index\n")
        self.assertEqual(firstrun.panels(cfg)["memory"]["bosun"], str(self.home / "memory" / "bosun"))

    def test_a_step_with_nothing_to_check_is_done_once_the_user_has_been_through_it(self):
        """c-729: How Shipyard remembers, How work ships, and Where finished work goes while
        its default stands have nothing to check, so they never read done; going on past one
        (Next, Keep this) records it as seen, and from then on it is done, with why."""
        with open_board(self.cfg()) as board:
            for step in ("memory", "defaults", "integrations"):
                self.assertIsNone(self.step(self.report(), step)["done"], step)
                answer = actions.act(self.cfg(), board, {"verb": "firstrun.seen", "step": step})
                self.assertEqual(answer["seen"], step)
            with self.assertRaisesRegex(actions.ActionError, "has its own check"):
                actions.act(self.cfg(), board, {"verb": "firstrun.seen", "step": "repos"})
        report = self.report()
        said = {step: (self.step(report, step)["done"], self.step(report, step)["why"]) for step in ("memory", "defaults", "integrations")}
        self.assertEqual(said, {"memory": (True, "you have read how Shipyard remembers"),
                                "defaults": (True, "you kept the usual path"),
                                "integrations": (True, firstrun.LOCAL)})
        self.assertTrue(self.step(report, "defaults")["seen"])
        self.assertFalse(report["untouched"], "a step the user has been through is acted on")
        self.assertEqual(json.loads((self.home / "state" / "firstrun.json").read_text())["seen"].keys(),
                         {"memory", "defaults", "integrations"})

    def test_add_your_repos_is_done_once_any_space_has_a_repo(self):
        """c-678: the user's repos go in their own space, so personal having none (its own
        packs repo does not count) holds nothing up."""
        step = self.step(self.report(), "repos")
        self.assertEqual((step["done"], step["why"]), (False, "no repo is added yet"))
        onboarding.add_space(self.cfg(), "work")
        onboarding.clone_repo(self.cfg(), "work", "api", str(self.bare()))
        step = self.step(self.report(), "repos")
        self.assertEqual((step["done"], step["why"]), (True, "1 repo: api"))

    def test_skip_is_refused_for_prerequisites_and_stored_for_repos(self):
        with self.assertRaisesRegex(actions.ActionError, "Check this computer cannot be skipped"):
            self.act("firstrun.skip", step="prerequisites")
        with self.assertRaisesRegex(actions.ActionError, "no first-run step 'lunch'"):
            self.act("firstrun.skip", step="lunch")
        with self.assertRaisesRegex(actions.ActionError, "Sign in to Claude cannot be skipped"):
            self.act("firstrun.skip", step="login")
        self.act("firstrun.skip", step="repos")
        self.assertEqual(set(self.stored()["skipped"]), {"repos"})
        repos = self.step(self.report(), "repos")
        self.assertTrue(repos["skipped"])
        self.assertFalse(repos["done"])
        self.act("firstrun.unskip", step="repos")
        self.assertEqual(self.stored()["skipped"], {})

    def test_a_skip_racing_the_first_state_read_is_kept(self):
        """A GET /api/state on a fresh install writes the first record; a Skip at that moment
        used to read no file too, and its skip was then overwritten (c-628 review r1.F8)."""
        cfg = self.cfg()
        firstrun.path_of(cfg).unlink(missing_ok=True)
        inside, go = threading.Event(), threading.Event()
        fresh = onboarding.fresh

        def slow_fresh(config):         # only the state read's first write is held
            if not inside.is_set():
                inside.set()
                go.wait(5)
            return fresh(config)
        with mock.patch.object(firstrun.onboarding, "fresh", side_effect=slow_fresh):
            reader = threading.Thread(target=firstrun.stored, args=(cfg,))
            reader.start()
            self.assertTrue(inside.wait(5))
            skipper = threading.Thread(target=firstrun.skip, args=(cfg, "repos"))
            skipper.start()
            skipper.join(0.3)
            go.set()
            reader.join(5)
            skipper.join(5)
        self.assertEqual(set(self.stored()["skipped"]), {"repos"})

    def test_a_clone_turns_repos_done_with_nothing_stored(self):
        self.report()
        onboarding.clone_repo(self.cfg(), "personal", "api", str(self.bare()))
        report = self.report()
        self.assertTrue(self.step(report, "repos")["done"])
        self.assertEqual(self.stored(), {"skipped": {}, "finished": None})
        self.assertEqual(self.step(report, "rules")["why"], "api/CLAUDE.md is not adopted yet")

    def test_finish_is_refused_while_prerequisites_miss_and_stored_once_they_pass(self):
        self.gather.return_value = [MISSING]
        with self.assertRaisesRegex(actions.ActionError, "Finish waits for Check this computer"):
            self.act("firstrun.finish")
        self.assertIsNone(self.stored()["finished"])
        self.gather.return_value = []
        readiness.forget()
        self.act("firstrun.finish")
        report = self.report()
        self.assertTrue(report["finished"])
        self.assertFalse(report["redirect"])
        self.gather.return_value = [MISSING]
        self.assertTrue(self.report()["redirect"], "missing prerequisites open Start even after Finish")
        self.gather.return_value = []
        self.act("firstrun.reopen")
        self.assertTrue(self.report()["redirect"])

    def test_an_install_with_a_listed_repo_and_no_file_reads_finished(self):
        onboarding.clone_repo(self.cfg(), "personal", "api", str(self.bare()))
        self.assertFalse((self.home / "state" / firstrun.FILE).exists())
        report = self.report()
        self.assertEqual(report["reason"], firstrun.EXISTING)
        self.assertTrue(report["finished"])
        self.assertFalse(report["redirect"])

    def test_a_config_that_is_not_an_install_never_redirects_or_writes(self):
        other = self.home / "other.toml"
        shutil.copy(self.home / "config.toml", other)
        report = self.report(config_module.load(other, ensure=False))
        self.assertEqual((report["install"], report["redirect"]), (False, False))
        self.assertFalse((self.home / "state" / firstrun.FILE).exists())

    def test_the_sandbox_packs_step_follows_integrations_and_is_done_once_its_check_passes(self):
        onboarding.add_space(self.cfg(), "work")
        packsetup.pack_on(self.cfg(), "sandbox", "work")
        report = self.report()
        ids = [s["id"] for s in report["steps"]]
        self.assertEqual(ids[ids.index("integrations") + 1], "sandbox:try")
        self.assertTrue(self.step(report, "sandbox:try")["done"])
        failing = [{"name": "git", "kind": "command", "ok": False, "why": "not on PATH", "for": []}]
        with mock.patch("keel.packs.checks", return_value=failing):
            self.assertEqual(self.step(self.report(), "sandbox:try")["why"], "git is not set up: not on PATH")
        self.act("firstrun.skip", step="sandbox:try")
        self.assertIn("sandbox:try", self.stored()["skipped"])
        panel = onboarding.report(self.cfg())["start"]["pack_steps"]["sandbox:try"]
        self.assertIn("The sandbox needs no account", panel["text"])

    def test_a_pack_that_reads_no_builds_can_finish_integrations(self):
        """c-642 r2.F1: `ci` counts only where a pack declares it, so the sandbox finishes."""
        onboarding.add_space(self.cfg(), "work")
        packsetup.pack_on(self.cfg(), "sandbox", "work")
        packsetup.pack_on(self.cfg(), "sandbox", "personal")
        cfg = self.cfg()
        self.assertEqual(readiness.wanted(cfg.spaces["work"]), ("tracker", "codehost", "reviews"))
        step = self.step(self.report(), "integrations")
        self.assertNotIn("CI builds", step["why"])
        self.assertTrue(step["done"], step["why"])

    def test_first_card_counts_a_card_he_filed_once_it_reaches_review(self):
        cfg = self.cfg()

        def at(board, card, stage):          # the stage alone; the gates are not what is tested
            with board.tx():
                board.conn.execute("UPDATE cards SET stage = ? WHERE id = ?", (stage, card))
        with open_board(cfg) as board:
            tier = board.create("personal", "Propose the personal tier", options={"tier_proposal": "personal"},
                                actor="human")
            at(board, tier, "review")
            board.create("personal", "a review card the drain filed", actor="drain")
            mine = board.create("personal", "a first card", actor="human")
            at(board, mine, "building")
        step = self.step(self.report(), "first-card")
        self.assertFalse(step["done"])
        self.assertEqual((step["card"]["id"], step["card"]["stage"]), (mine, "building"))
        with open_board(cfg) as board:
            at(board, mine, "review")
        self.assertTrue(self.step(self.report(), "first-card")["done"])

    def test_check_again_probes_the_login_and_reads_again(self):
        with mock.patch("keel.login.probe", return_value={"state": login.EXPIRED, "why": "Not logged in"}):
            answer = self.act("firstrun.login.check")
        self.assertIn("does not work", answer["note"])
        self.assertFalse(self.step(self.report(), "login")["done"])

    def test_the_sign_in_step_carries_its_command_and_whether_a_sign_in_was_seen(self):
        """c-678: the guided sign-in. The page shows one command to paste, and watches for the
        sign-in file in the install's own Claude folder: the state says whether it is there."""
        claude = self.home / "claude"
        shown = firstrun.panels(self.cfg())["login"]
        self.assertTrue(shown["command"].startswith(f"CLAUDE_CONFIG_DIR={claude} "), shown["command"])
        self.assertTrue(shown["command"].endswith(" auth login"), shown["command"])
        step = self.step(self.report(), "login")
        self.assertEqual((step["seen"], step["stamp"]), (False, None))
        claude.mkdir(parents=True, exist_ok=True)
        (claude / login.CREDENTIALS).write_text("{}")
        os.utime(claude / login.CREDENTIALS, (1_700_000_000, 1_700_000_000))
        step = self.step(self.report(), "login")
        self.assertEqual((step["seen"], step["stamp"]), (True, 1_700_000_000))

    def test_check_again_probes_the_space_it_is_asked_for(self):
        """c-678: the sign-in banner is per space, so its Check again names the space; the
        step's names none and probes the install's own."""
        asked = []

        def probe(config_dir):
            asked.append(Path(config_dir))
            return {"state": login.GOOD, "why": ""}
        cfg = self.cfg()
        with mock.patch("keel.login.probe", side_effect=probe):
            self.act("firstrun.login.check", space="personal")
            with self.assertRaisesRegex(actions.ActionError, "no space 'nowhere'"):
                self.act("firstrun.login.check", space="nowhere")
        self.assertEqual(asked, [cfg.spaces["personal"].config_dir])

    def test_saving_the_git_name_and_email_writes_gits_global_setting_and_reads_again(self):
        """c-679: the page's two fields. git's global file is a temp file here."""
        from keel import prereqs
        file = self.home.parent / "gitconfig"
        os.environ.update(GIT_CONFIG_GLOBAL=str(file), GIT_CONFIG_NOSYSTEM="1")
        self.gather.side_effect = lambda *features: [prereqs.identity_check()]
        step = self.step(self.report(), "prerequisites")
        self.assertEqual((step["done"], step["why"]),
                         (False, "Your name and email for git: Git on this computer has no name and email set. "
                                 "When work lands, git records who merged it"))
        with self.assertRaisesRegex(actions.ActionError, "git needs your email"):
            self.act("firstrun.identity.save", name="Maya Okafor", email="")
        self.assertFalse(file.exists())
        answer = self.act("firstrun.identity.save", name="Maya Okafor", email="maya@example.com")
        self.assertEqual(answer["note"], "git will record your merges as Maya Okafor <maya@example.com>")
        self.assertIn("maya@example.com", file.read_text())
        with open_board(self.cfg()) as board:        # the kept reading was dropped: no forget here
            self.assertTrue(self.step(firstrun.report(self.cfg(), board), "prerequisites")["done"])
        before = file.read_text()
        with self.assertRaisesRegex(actions.ActionError, "git already has a name and email"):
            self.act("firstrun.identity.save", name="Someone Else", email="else@example.com")
        self.assertEqual(file.read_text(), before)

    def test_the_core_ids_are_the_ones_a_pack_may_follow(self):
        from keel import packs
        self.assertEqual(firstrun.CORE, packs.SETUP_AFTER)
        self.assertEqual(set(firstrun.STATE), set(firstrun.CORE), "a step is an entry in STEPS and one in STATE")
        self.assertEqual(set(readiness.STEPS.values()) - {None}, set(firstrun.CORE) - {"choose-builder", "memory", "defaults", "first-card"})


if __name__ == "__main__":
    unittest.main()
