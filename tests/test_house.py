"""house: the settings file, the brief composition, and launch/resume with a fake harness."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import adapters, briefnews, house, merging
from keel import harness as real_harness
from keel.board import Board, Refused
from tests.helpers import SESSION, FakeHarness, background_row, make_config, make_repo


class HouseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.repo = make_repo(self.dir / "repo")
        self.other = make_repo(self.dir / "other")
        self.cfg = make_config(self.dir, repos={"keel": self.repo, "other": self.other})
        self.board = Board(self.cfg.db_path)
        self.fake = FakeHarness()
        patch = mock.patch.object(house, "harness", self.fake)
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        self.board.close()
        self.tmp.cleanup()

    def assigned(self, repo="keel", autonomy="autonomous", space="personal", **kwargs) -> str:
        card_id = self.board.create(space, "Add keel doctor", brief="do it", repo=repo,
                                    autonomy=autonomy, **kwargs)
        self.board.stage(card_id, "assigned", "human")
        return card_id


class SettingsTest(HouseCase):
    def test_hooks_and_deny_match_the_layout(self):
        card_id = self.assigned()
        guard = self.dir / "guard.py"
        guard.write_text("# guard\n")
        with mock.patch.object(self.cfg, "stack_guard_hook", guard):
            path = house.settings_for(self.cfg, self.board.get(card_id))
        self.assertEqual(path, self.cfg.state_dir / "cards" / card_id / "settings.json")
        settings = json.loads(path.read_text())
        kb = house.board_prefix(self.cfg) + str(self.cfg.root / "bin" / "kb")
        self.assertTrue(kb.startswith("KEEL_HOME=/"), kb)
        hooks = settings["hooks"]
        self.assertEqual(hooks["Stop"][0]["hooks"][0]["command"], f"{kb} stop-check {card_id}")
        self.assertEqual(hooks["SessionEnd"][0]["hooks"][0]["command"],
                         f"{kb} event {card_id} --hook SessionEnd")
        notification = hooks["Notification"][0]
        self.assertEqual(notification["matcher"], "idle_prompt|permission_prompt")
        self.assertEqual(notification["hooks"][0]["command"], f"{kb} event {card_id} --hook Notification")
        self.assertEqual([group["matcher"] for group in hooks["PreToolUse"]], ["Bash", "mcp__docker__.*", "Bash"])
        self.assertEqual(hooks["PreToolUse"][0]["hooks"][0]["command"], f"python3 {guard}")
        self.assertEqual(hooks["PreToolUse"][2]["hooks"][0]["command"],
                         f"{house.board_prefix(self.cfg)}python3 {self.cfg.root / 'bin' / 'keel-house-guard'} {card_id}")
        self.assertEqual(settings["permissions"]["deny"],
                         ["mcp__claude_ai_Slack", "mcp__claude-in-chrome", *house.secret_deny(self.cfg),
                          "EnterWorktree", "ExitWorktree"])
        env = settings["env"]
        self.assertEqual((env["KEEL_CARD"], env["KEEL_HOME"]), (card_id, str(self.cfg.root)))
        self.assertTrue(env["PATH"].startswith(
            f"{self.cfg.root / 'etc' / 'house-bin'}:{self.cfg.root / 'bin'}:"))
        # c-553: a key a daemon carries from Bosun's launch never rides into a house
        self.assertEqual(env["KEEL_BOSUN"], "")

    def test_a_pack_with_a_guard_verb_is_named_on_the_house_guard_s_command_and_no_other_is(self):
        """c-689: the hook is handed the pack's `guard` and its tools; a space whose pack has
        none (the work pack, the sandbox pack, no pack) gets the command byte for byte."""
        from keel import packs
        plain = f"{house.board_prefix(self.cfg)}python3 {self.cfg.root / 'bin' / 'keel-house-guard'} "

        def command(card_id):
            with mock.patch.object(self.cfg, "stack_guard_hook", self.dir / "absent.py"), \
                    mock.patch.object(adapters, "extra_deny", return_value=[]):
                body = house.settings_body(self.cfg, self.board.get(card_id))
            return body["hooks"]["PreToolUse"][0]["hooks"][0]["command"]

        personal = self.assigned()
        self.assertEqual(command(personal), plain + personal)
        for name in ("work", "sandbox"):
            self.cfg.spaces["work"].adapter_dir = packs.PACKAGE / packs.PACKS / name
            card_id = self.assigned(space="work")
            self.assertEqual(command(card_id), plain + card_id, name)
        github = packs.PACKAGE / packs.PACKS / "github"
        self.cfg.spaces["work"].adapter_dir = github
        card_id = self.assigned(space="work")
        self.assertEqual(command(card_id), f"{plain}{card_id} {github / 'guard'} gh")

    def demo_pack(self, toml: str, guard_mode: int | None) -> None:
        pack = self.dir / "packs" / "demo"
        pack.mkdir(parents=True)
        (pack / "pack.toml").write_text(toml)
        if guard_mode is not None:
            (pack / "guard").write_text("#!/bin/sh\n")
            (pack / "guard").chmod(guard_mode)
        self.cfg.spaces["work"].adapter_dir = pack
        self.cfg.spaces["work"].adapter = "demo"

    def test_a_pack_that_declares_a_guard_and_does_not_load_blocks_the_card(self):
        """r3.F2: a house is never started without the guard its pack says it has."""
        manifest = 'name = "demo"\nversion = "1"\ndescription = "a pack for the test"\n'
        self.demo_pack(manifest + '[guard]\ntools = ["gh"]\n', 0o644)       # lost its executable bit
        card_id = self.assigned(space="work", repo=None)
        with self.assertRaises(adapters.AdapterError):
            house.launch(self.cfg, self.board, card_id)
        self.assertEqual(self.fake.starts, [])
        reason = self.board.get(card_id)["blocked_reason"]
        self.assertIn("house failed to start", reason)
        self.assertIn("declares a guard", reason)
        self.assertIn("no executable guard", reason)

    def test_a_guard_beside_a_pack_toml_that_does_not_parse_blocks_the_card_too(self):
        self.demo_pack('name = "demo"\nversion = \n', 0o755)
        with self.assertRaisesRegex(adapters.AdapterError, "declares a guard"):
            house.pack_guard(self.cfg, {"id": "c-1", "space": "work"})

    def test_a_pack_with_no_guard_and_a_fault_of_its_own_launches_as_it_did(self):
        for toml in ('name = "demo"\nversion = \n', 'name = "other"\nversion = "1"\ndescription = "x"\n'):
            with self.subTest(toml=toml):
                self.demo_pack(toml, None)
                self.assertEqual(house.pack_guard(self.cfg, {"id": "c-1", "space": "work"}), "")
                import shutil
                shutil.rmtree(self.dir / "packs")

    def test_the_installs_bosun_memory_is_denied_to_the_editing_tools_of_every_house(self):
        """c-722: Bosun's memory lives in the install, outside every worktree; a house changes
        it only through a card, never by writing the live file."""
        from keel import config as config_module
        self.assertEqual(house.memory_deny(self.cfg), [], "no install, nothing to deny")
        with mock.patch.object(config_module.Config, "install_home", new_callable=mock.PropertyMock,
                               return_value=Path("/i")):
            self.assertEqual(house.memory_deny(self.cfg), ["Edit(//i/memory/**)", "Bash(*/i/memory*)"])
            deny = house.settings_body(self.cfg, self.board.get(self.assigned()))["permissions"]["deny"]
        self.assertIn("Edit(//i/memory/**)", deny)   # r1.F2: the whole root, its .git too
        self.assertIn("Bash(*/i/memory*)", deny)

    def test_bosun_s_settings_file_is_denied_to_every_house(self):
        """It carries Bosun's key (c-553), as the shared key it is derived from does."""
        from keel import housetier
        path = housetier.bosun_settings_path(self.cfg)
        self.assertIn(f"Read(/{path})", house.secret_deny(self.cfg))
        self.assertIn(f"Bash(*{path.name}*)", house.secret_deny(self.cfg))

    def test_guard_hook_is_left_out_when_the_script_is_missing(self):
        """The machine's stack guard is optional; Keel's own house guard is not (c-534)."""
        card_id = self.assigned(space="work")
        with mock.patch.object(self.cfg, "stack_guard_hook", self.dir / "absent.py"):
            settings = json.loads(house.settings_for(self.cfg, self.board.get(card_id)).read_text())
        self.assertEqual([group["hooks"][0]["command"] for group in settings["hooks"]["PreToolUse"]],
                         [f"{house.board_prefix(self.cfg)}python3 {self.cfg.root / 'bin' / 'keel-house-guard'} {card_id}"])
        self.assertEqual(settings["permissions"]["deny"],
                         ["mcp__claude-in-chrome", *house.secret_deny(self.cfg),
                          "EnterWorktree", "ExitWorktree"])

    def test_a_confined_house_is_fenced_to_the_board_and_a_repo_card_is_not(self):
        """The errand's Bash is the board and nothing else; a repo card keeps its shell."""
        errand = self.assigned(repo=None)
        with mock.patch.object(self.cfg, "stack_guard_hook", self.dir / "absent.py"):
            settings = json.loads(house.settings_for(self.cfg, self.board.get(errand)).read_text())
        group = settings["hooks"]["PreToolUse"][0]
        self.assertEqual(group["matcher"], "Bash")
        self.assertEqual(group["hooks"][0]["command"],
                         f"python3 {self.cfg.root / 'bin' / 'keel-board-fence'} {errand}")
        with_repo = self.assigned()
        with mock.patch.object(self.cfg, "stack_guard_hook", self.dir / "absent.py"):
            plain = json.loads(house.settings_for(self.cfg, self.board.get(with_repo)).read_text())
        commands = [group["hooks"][0]["command"] for group in plain["hooks"]["PreToolUse"]]
        self.assertEqual(commands, [f"{house.board_prefix(self.cfg)}python3 {self.cfg.root / 'bin' / 'keel-house-guard'} {with_repo}"])

    def test_a_space_allow_list_reaches_an_open_shell_and_leaves_the_deny_list_alone(self):
        """c-769: a space's allow rules settle its own commands before the classifier is
        asked. None named, no key; a confined house, whose Bash is the board's, gets none."""
        card, errand = self.board.get(self.assigned()), self.board.get(self.assigned(repo=None))
        before = house.settings_body(self.cfg, card)
        self.assertNotIn("allow", before["permissions"])
        self.cfg.spaces["personal"].allow = ["Bash(make check)", "Bash(make check:*)"]
        after = house.settings_body(self.cfg, card)
        self.assertEqual(after["permissions"]["allow"], ["Bash(make check)", "Bash(make check:*)"])
        self.assertEqual(after["permissions"]["deny"], before["permissions"]["deny"])
        self.assertNotIn("allow", house.settings_body(self.cfg, errand)["permissions"])

    def test_a_changed_allow_list_makes_the_written_settings_stale(self):
        """c-769: the file a house runs under is rewritten when its space's allow list moves."""
        card = self.board.get(self.assigned())
        house.settings_for(self.cfg, card)
        self.assertTrue(house.settings_current(self.cfg, card))
        self.cfg.spaces["personal"].allow = ["Bash(make check)"]
        self.assertFalse(house.settings_current(self.cfg, card))

    def test_a_worker_with_no_bash_has_nothing_to_fence(self):
        card_id = self.assigned(repo=None, options={"tools": "Read,Write"})
        with mock.patch.object(self.cfg, "stack_guard_hook", self.dir / "absent.py"):
            settings = json.loads(house.settings_for(self.cfg, self.board.get(card_id)).read_text())
        self.assertNotIn("PreToolUse", settings["hooks"])

    def test_the_fence_joins_the_machine_guard_rather_than_replacing_it(self):
        card_id = self.assigned(repo=None)
        guard = self.dir / "guard.py"
        guard.write_text("# guard\n")
        with mock.patch.object(self.cfg, "stack_guard_hook", guard):
            settings = json.loads(house.settings_for(self.cfg, self.board.get(card_id)).read_text())
        groups = settings["hooks"]["PreToolUse"]
        self.assertEqual([group["matcher"] for group in groups], ["Bash", "mcp__docker__.*", "Bash"])
        self.assertIn("keel-board-fence", groups[-1]["hooks"][0]["command"])


class SecretDenyTest(HouseCase):
    """A house may not read his token (c-451): with it, its own `kb` is him."""

    def settings(self, card_id: str) -> dict:
        with mock.patch.object(self.cfg, "stack_guard_hook", self.dir / "absent.py"):
            return json.loads(house.settings_for(self.cfg, self.board.get(card_id)).read_text())

    def test_every_house_is_denied_the_human_token_by_read_and_by_bash(self):
        token = str(self.cfg.token_path)
        self.assertTrue(token.startswith("/"))
        for card_id in (self.assigned(), self.assigned(repo=None), self.assigned(space="work"),
                        self.assigned(repo=None, options={"tools": "Read,Write"})):
            deny = self.settings(card_id)["permissions"]["deny"]
            # DOUBLE leading slash (H6): a single one anchors at the settings file, and the
            # deny would match nothing and fail open.
            self.assertIn(f"Read(/{token})", deny)
            self.assertTrue(f"Read(/{token})".startswith("Read(//"))
            self.assertIn(f"Bash(*{token}*)", deny)
            self.assertIn("Bash(*human.token*)", deny)

    def test_the_voice_house_key_is_denied_the_same_way(self):
        from keel import housetier
        key = str(housetier.key_path(self.cfg))
        self.assertEqual(house.HOUSE_KEY_NAME, housetier.KEY_NAME)
        deny = self.settings(self.assigned())["permissions"]["deny"]
        self.assertIn(f"Read(/{key})", deny)
        self.assertIn("Bash(*house.key*)", deny)

    def test_the_rules_are_real_permission_rules(self):
        """Every rule is `Tool(pattern)` with the tool one Claude Code has."""
        for rule in house.secret_deny(self.cfg):
            tool, _, rest = rule.partition("(")
            self.assertIn(tool, ("Read", "Bash"), rule)
            self.assertTrue(rest.endswith(")") and len(rest) > 1, rule)


class RestrictedSettingsTest(HouseCase):
    """The two rules a house with no worktree needs: it may write its own record, and the
    directory its brief tells it to read stays one it only reads."""

    def settings(self, card_id: str) -> dict:
        with mock.patch.object(self.cfg, "stack_guard_hook", self.dir / "absent.py"):
            return json.loads(house.settings_for(self.cfg, self.board.get(card_id)).read_text())

    def test_every_house_runs_without_the_background_worktree_guard(self):
        """Claude Code refuses a background session's writes inside a git repo until it
        enters a worktree. A card directory is inside the Keel repo and a confined house
        has no worktree to enter, which is what blocked c-271 (2026-09-18); a repo house
        already runs in its own worktree, and in c-605's run it sat on EnterWorktree's
        permission prompt instead (work, personal and confined houses alike)."""
        for card_id in (self.assigned(repo=None), self.assigned(), self.assigned(space="work"),
                        self.assigned(space="work", repo=None)):
            settings = self.settings(card_id)
            self.assertEqual(settings["worktree"], {"bgIsolation": "none"}, card_id)
            deny = settings["permissions"]["deny"]
            self.assertIn("EnterWorktree", deny, card_id)
            self.assertIn("ExitWorktree", deny, card_id)

    def test_the_atlas_is_denied_to_the_editing_tools_of_a_restricted_house(self):
        """It is an `--add-dir` so the house can read it, and `--add-dir` grants writes, so
        the deny is what makes it read-only. The double leading slash is what makes the
        rule absolute: one slash anchors at the settings file instead."""
        deny = self.settings(self.assigned(repo=None))["permissions"]["deny"]
        atlas = self.cfg.root / "docs" / "atlas"
        secrets = house.secret_deny(self.cfg)
        self.assertEqual(deny[:4 + len(secrets)], ["mcp__claude_ai_Slack", "mcp__claude-in-chrome", *secrets,
                                                   "EnterWorktree", "ExitWorktree"])
        for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            self.assertIn(f"{tool}(/{atlas}/**)", deny)
        rest = deny[4 + len(secrets):]
        self.assertEqual(len(rest), 4)
        self.assertTrue(all(rule.count("(//") == 1 for rule in rest), deny)

    def test_a_repo_card_is_denied_nothing_extra(self):
        self.assertEqual(self.settings(self.assigned())["permissions"]["deny"],
                         ["mcp__claude_ai_Slack", "mcp__claude-in-chrome", *house.secret_deny(self.cfg),
                          "EnterWorktree", "ExitWorktree"])


class RestrictedPlacementTest(HouseCase):
    """What a confined house may open besides its own card directory."""

    def add_dirs(self, card_id: str) -> list[str]:
        return [str(path) for path in house.placement(self.cfg, self.board.get(card_id))["add_dirs"]]

    def test_the_atlas_is_open_to_every_confined_house(self):
        """Every brief tells a house to read `docs/atlas/`, and `--restricted` reaches the
        cwd and the add-dirs only, so without this the block names what it cannot open."""
        self.assertEqual(self.add_dirs(self.assigned(repo=None)),
                         [str(self.cfg.root / "docs" / "atlas")])

    def test_the_segment_its_brief_names_is_open_too(self):
        segment = self.cfg.segments_dir / "scratchseg"
        segment.mkdir(parents=True)
        card_id = self.assigned(repo=None, options={"segment": "scratchseg"})
        self.assertEqual(self.add_dirs(card_id)[0], str(segment.resolve()))

    def test_a_drop_opens_the_directory_it_belongs_in(self):
        inbox = self.dir / "seg" / "data" / "inbox"
        inbox.mkdir(parents=True)
        card_id = self.assigned(repo=None, options={"drop": str(inbox / "worker.json")})
        self.assertEqual(self.add_dirs(card_id)[0], str(inbox.resolve()))

    def test_the_cards_own_add_dirs_come_first_and_nothing_is_named_twice(self):
        segment = self.cfg.segments_dir / "scratchseg"
        (segment / "data" / "inbox").mkdir(parents=True)
        card_id = self.assigned(repo=None, options={
            "add_dirs": [str(segment)], "segment": "scratchseg", "drop": str(segment / "data" / "inbox" / "d.json")})
        self.assertEqual(self.add_dirs(card_id),
                         [str(segment.resolve()), str(segment.resolve() / "data" / "inbox"),
                          str(self.cfg.root / "docs" / "atlas")],
                         "one directory, one --add-dir, whatever spelling it arrived in")

    def test_a_directory_that_is_not_there_is_left_out(self):
        """`--add-dir` refuses a path that does not exist, and a refused flag is a house
        that never starts."""
        card_id = self.assigned(repo=None, options={"segment": "gone", "add_dirs": [str(self.dir / "nope")]})
        self.assertEqual(self.add_dirs(card_id), [str(self.cfg.root / "docs" / "atlas")])


class NewProjectTest(HouseCase):
    """A repo the config does not list: a project under the space's `projects_dir`."""

    def setUp(self):
        super().setUp()
        self.projects = self.dir / "projects"
        self.cfg.spaces["personal"].projects_dir = self.projects

    def card(self, repo: str, new_project: bool = False) -> dict:
        options = {"new_project": True} if new_project else {}
        return self.board.get(self.assigned(repo=repo, options=options))

    def git(self, repo: Path, *args: str) -> str:
        return adapters.git(repo, *args).strip()

    def test_a_missing_directory_with_the_option_is_scaffolded_and_used(self):
        card = self.card("smoke", new_project=True)
        paths = house.worktree_for(self.cfg, card)
        repo = self.projects / "smoke"
        self.assertTrue((repo / ".git").is_dir())
        self.assertEqual(self.git(repo, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertEqual(len(self.git(repo, "log", "--oneline").splitlines()), 1)
        self.assertIn(card["id"], (repo / "README.md").read_text())
        self.assertEqual(paths, [self.cfg.worktrees_dir / card["id"]])
        self.assertIn(card["id"], self.git(repo, "worktree", "list"))

    def test_a_missing_directory_without_the_option_is_refused(self):
        with self.assertRaises(adapters.AdapterError) as caught:
            house.worktree_for(self.cfg, self.card("smoke"))
        self.assertIn("--new-project smoke", str(caught.exception))
        self.assertFalse(self.projects.exists(), "a typo never scaffolds a project")

    def test_an_existing_git_directory_is_a_repo_like_any_other(self):
        make_repo(self.projects / "already")
        card = self.card("already", new_project=True)
        self.assertEqual(house.worktree_for(self.cfg, card), [self.cfg.worktrees_dir / card["id"]])
        self.assertEqual(len(self.git(self.projects / "already", "log", "--oneline").splitlines()), 1)

    def test_a_directory_that_is_not_a_repo_is_refused(self):
        (self.projects / "plain").mkdir(parents=True)
        with self.assertRaises(adapters.AdapterError) as caught:
            house.worktree_for(self.cfg, self.card("plain", new_project=True))
        self.assertIn("is not a git repository", str(caught.exception))

    def test_a_name_that_could_leave_the_projects_directory_is_refused(self):
        for name in ("../escape", "a/b", "..", ".hidden", "Name"):
            with self.assertRaises(adapters.AdapterError) as caught:
                house.worktree_for(self.cfg, self.card(name, new_project=True))
            self.assertIn("not a plain project name", str(caught.exception))
        self.assertFalse(self.projects.exists())


    def test_the_merge_flow_finds_a_discovered_project(self):
        """Approve outcome merges a personal card's branch, and a project's card is one."""
        card = self.card("smoke", new_project=True)
        worktree = house.worktree_for(self.cfg, card)[0]
        # a commit of its own: a branch that adds nothing closes with nothing landed (r-24)
        (Path(worktree) / "built.txt").write_text("built\n")
        for argv in (["add", "."], ["-c", "user.email=t@example.invalid", "-c", "user.name=t",
                                    "commit", "-q", "-m", "the work"]):
            subprocess.run(["git", "-C", str(worktree), *argv], check=True, capture_output=True)
        self.board.stage(card["id"], "building", "drain")
        self.board.stage(card["id"], "review", "house", plan_ref="p.md", output_ref="x")
        merged = merging.publish(self.cfg, self.board.get(card["id"]))
        self.assertIn("merged into main", merged)
        self.assertFalse((self.cfg.worktrees_dir / card["id"]).exists())


class BriefTest(HouseCase):
    def test_brief_is_contract_then_card_then_space(self):
        card_id = self.assigned(model="opus", options={"plan_style": "light"})
        text = house.brief_for(self.cfg, self.board.get(card_id))
        self.assertTrue(text.startswith("# You are the house for one card"))
        block_at, space_at = text.index("## The card"), text.index("# Personal space")
        self.assertLess(block_at, space_at)
        fenced = text[text.index("```json") + len("```json"):text.index("```", block_at + 20)]
        self.assertEqual(json.loads(fenced), {
            "id": card_id, "title": "Add keel doctor", "brief": "do it", "autonomy": "autonomous",
            "repo": "keel", "model": "opus", "stage": "assigned", "plan_ref": None,
            "options": {"plan_style": "light", "provenance": {
                "repo": "stated", "model": "stated", "autonomy": "stated",
                "topic": "keel_default"}}})
        card_dir = self.cfg.state_dir / "cards" / card_id
        self.assertEqual((card_dir / "brief.md").read_text(), text)
        context = (card_dir / "context.md").read_text()
        self.assertEqual(context.count("## "), 7)       # the six, and Risk for a repo card (HP-2)
        for heading in (*house.CONTEXT_SECTIONS, "Risk"):
            self.assertIn(f"## {heading}\n", context)

    def test_existing_context_is_kept(self):
        card_id = self.assigned()
        card_dir = self.cfg.card_dir(card_id)
        (card_dir / "context.md").write_text("## Where it stands\n\nhalf done\n")
        house.brief_for(self.cfg, self.board.get(card_id))
        self.assertIn("half done", (card_dir / "context.md").read_text())


class LaunchTest(HouseCase):
    def test_house_card_runs_in_its_worktree_and_is_staged_building(self):
        card_id = self.assigned(model="opus")
        result = house.launch(self.cfg, self.board, card_id)
        self.assertEqual(result["session_id"], SESSION)
        start = self.fake.starts[0]
        self.assertEqual(start["cwd"], self.cfg.worktrees_dir / card_id)
        self.assertTrue((start["cwd"] / ".git").exists())
        self.assertEqual(start["name"], card_id)
        self.assertEqual(start["config_dir"], self.cfg.spaces["personal"].config_dir)
        self.assertEqual(start["settings_path"], self.cfg.state_dir / "cards" / card_id / "settings.json")
        self.assertEqual((start["model"], start["add_dirs"], start["restricted"], start["tools"]),
                         ("opus", (), False, None))
        self.assertTrue(start["prompt"].startswith("# You are the house"))
        card = self.board.get(card_id)
        self.assertEqual((card["stage"], card["session_id"]), ("building", SESSION))
        kinds = [(e["kind"], e["actor"]) for e in self.board.events(card_id)][-2:]
        self.assertEqual(kinds, [("session", "drain"), ("stage", "drain")])
        self.assertEqual(self.board.events(card_id)[-2]["data"]["bg_id"], SESSION[:8])

    def test_launch_and_resume_record_the_app_link_with_the_session(self):
        card_id = self.assigned()
        with mock.patch.object(house, "APP_LINK_PAUSE", 0):
            house.launch(self.cfg, self.board, card_id)
        self.assertEqual(self.board.get(card_id)["options"]["app_link"], self.fake.app_link)
        session = [e for e in self.board.events(card_id) if e["kind"] == "session"][-1]
        self.assertEqual(session["data"]["app_link"], self.fake.app_link)
        self.fake.app_link = "https://claude.ai/code/session_01GGEoq2MZck2dB1c27j5Kvm"
        self.fake.resume_bg = lambda session_id, prompt, **kw: {"bg_id": "6d3575a7", "session_id": "6d3575a7-b4d3-4edb-aa15-fef8a9136367"}
        with mock.patch.object(house, "APP_LINK_PAUSE", 0):
            house.resume(self.cfg, self.board, card_id)
        self.assertEqual(self.board.get(card_id)["options"]["app_link"], self.fake.app_link)

    def kept_session_card(self) -> str:
        """A card on a session with no link on record (c-135, c-238: imported sessions)."""
        card_id = self.assigned()
        self.board.stage(card_id, "building", "drain")
        self.board.set_session(card_id, SESSION, "drain", bg_id=SESSION[:8])
        return card_id

    def test_a_resume_that_keeps_its_session_reads_no_link_and_is_recorded_whoever_resumed(self):
        """c-653 review (r1.F5, r1.F9, r2.F8): a read of the log at resume cost the pass
        seconds, missed more often than not, and once failed a resume Bosun made. The link
        of a kept session is his Open in Claude app's to fetch (`keel/openapp.py`)."""
        card_id = self.kept_session_card()
        for actor in ("drain", "bosun", "human"):
            house.resume(self.cfg, self.board, card_id, actor=actor)
        self.assertEqual(self.fake.links_asked, [])
        self.assertEqual([e["actor"] for e in self.board.events(card_id) if e["kind"] == "resume"],
                         ["drain", "bosun", "human"])

    def test_resume_stops_the_session_it_superseded_when_it_is_still_listed(self):
        card_id = self.assigned()
        with mock.patch.object(house, "APP_LINK_PAUSE", 0):
            house.launch(self.cfg, self.board, card_id)
        self.fake.rows = [{"name": card_id, "kind": "background", "sessionId": SESSION,
                           "id": SESSION[:8], "status": "idle", "state": "blocked", "pid": 51563}]
        self.fake.resume_bg = lambda session_id, prompt, **kw: {"bg_id": "d4db30e1", "session_id": "d4db30e1-f5d6-4498-83a6-9dd7a1c057d6"}
        with mock.patch.object(house, "APP_LINK_PAUSE", 0):
            house.resume(self.cfg, self.board, card_id)
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        self.assertEqual(self.board.get(card_id)["session_id"], "d4db30e1-f5d6-4498-83a6-9dd7a1c057d6")
        self.assertIn("superseded session", self.board.events(card_id)[-1]["text"])

    def test_resume_of_an_exited_session_stops_nothing(self):
        card_id = self.assigned()
        with mock.patch.object(house, "APP_LINK_PAUSE", 0):
            house.launch(self.cfg, self.board, card_id)
        self.fake.rows = []
        self.fake.resume_bg = lambda session_id, prompt, **kw: {"bg_id": "d4db30e1", "session_id": "d4db30e1-f5d6-4498-83a6-9dd7a1c057d6"}
        with mock.patch.object(house, "APP_LINK_PAUSE", 0):
            house.resume(self.cfg, self.board, card_id)
        self.assertEqual(getattr(self.fake, "stops", []), [])

    def test_a_failed_stop_of_the_superseded_session_is_noted_not_raised(self):
        card_id = self.assigned()
        with mock.patch.object(house, "APP_LINK_PAUSE", 0):
            house.launch(self.cfg, self.board, card_id)
        self.fake.rows = [{"name": card_id, "kind": "background", "sessionId": SESSION,
                           "id": SESSION[:8], "status": "idle", "state": "blocked", "pid": 1}]
        self.fake.stop_fails = True
        self.fake.resume_bg = lambda session_id, prompt, **kw: {"bg_id": "d4db30e1", "session_id": "d4db30e1-f5d6-4498-83a6-9dd7a1c057d6"}
        with mock.patch.object(house, "APP_LINK_PAUSE", 0):
            house.resume(self.cfg, self.board, card_id)
        self.assertIn("could not be stopped", self.board.events(card_id)[-1]["text"])

    def test_approving_the_outcome_retires_a_listed_house(self):
        card_id = self.assigned()
        with mock.patch.object(house, "APP_LINK_PAUSE", 0):
            house.launch(self.cfg, self.board, card_id)
        self.fake.rows = [{"name": card_id, "kind": "background", "sessionId": SESSION,
                           "id": SESSION[:8], "status": "idle", "state": "done", "pid": 35342}]
        self.assertTrue(house.retire_finished(self.cfg, self.board, self.board.get(card_id)))
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        last = self.board.events(card_id)[-1]
        self.assertEqual((last["actor"], last["text"]), ("human", f"finished house {SESSION[:8]} stopped"))
        self.fake.rows = []
        self.assertFalse(house.retire_finished(self.cfg, self.board, self.board.get(card_id)))


    def test_attended_card_is_staged_planning(self):
        card_id = self.assigned(autonomy="attended")
        house.launch(self.cfg, self.board, card_id)
        self.assertEqual(self.board.get(card_id)["stage"], "planning")

    def test_cross_repo_card_adds_the_other_worktrees(self):
        card_id = self.assigned(repo="keel,other")
        house.launch(self.cfg, self.board, card_id)
        start = self.fake.starts[0]
        self.assertEqual(start["cwd"], self.cfg.worktrees_dir / card_id)
        self.assertEqual(start["add_dirs"], (self.cfg.worktrees_dir / f"{card_id}-other",))

    def test_errand_is_restricted_in_its_card_dir(self):
        card_id = self.assigned(repo=None)
        house.launch(self.cfg, self.board, card_id)
        start = self.fake.starts[0]
        self.assertEqual(start["cwd"], self.cfg.state_dir / "cards" / card_id)
        self.assertEqual((start["restricted"], start["tools"]), (True, house.ERRAND_TOOLS))
        self.assertIn("Bash", house.ERRAND_TOOLS.split(","), "an errand reaches the board")
        for tool in ("WebSearch", "WebFetch"):
            self.assertIn(tool, start["tools"].split(","), "an errand reaches the web (c-291)")
        other = self.assigned(repo=None, options={"tools": "Read,Bash"})
        house.launch(self.cfg, self.board, other)
        self.assertEqual(self.fake.starts[1]["tools"], "Read,Bash")

    FORK = {"kind": "review", "review_key": "keel:12", "pr": 12, "review_fork": True}

    def test_a_review_card_of_the_team_s_own_code_starts_exactly_as_before(self):
        """c-730 r2.F1: a review card that is not a fork's (the work pack's, a GitHub one from
        the repository itself) reads its repo's settings and runs where it always ran."""
        card_id = self.assigned(options={"kind": "review", "review_key": "keel:12", "pr": 12})
        house.launch(self.cfg, self.board, card_id)
        start = self.fake.starts[0]
        self.assertEqual((start["setting_sources"], start["restricted"], start["tools"]), (None, False, None))
        self.assertEqual(start["cwd"], self.cfg.worktrees_dir / card_id)
        self.assertEqual(house.harness_flags(house.placement(self.cfg, self.board.get(card_id))),
                         {"add_dirs": (), "restricted": False, "tools": None, "setting_sources": None})

    def test_a_fork_s_review_house_reads_its_code_confined_and_never_runs_it(self):
        """c-730 r1.F1, r2.F3: a fork's code is a stranger's. Its house starts `--restricted` in
        the checkout, with the read tools, the review's agents and Bash behind the board fence
        (the board and Keel's review steps, nothing of the fork's), and `--setting-sources
        user`, so no project setting or hook of the fork loads."""
        card_id = self.assigned(options=dict(self.FORK))
        house.launch(self.cfg, self.board, card_id)
        start = self.fake.starts[0]
        self.assertEqual((start["setting_sources"], start["restricted"]), ("user", True))
        self.assertEqual(start["tools"], house.FORK_REVIEW_TOOLS)
        self.assertEqual(start["cwd"], self.cfg.worktrees_dir / card_id)
        self.assertIn(self.cfg.card_dir(card_id).resolve(), start["add_dirs"])
        settings = json.loads((self.cfg.card_dir(card_id) / "settings.json").read_text())
        fences = [hook["command"] for group in settings["hooks"]["PreToolUse"] for hook in group["hooks"]
                  if "keel-board-fence" in hook["command"]]
        self.assertEqual(fences, [f"python3 {house.fence_path(self.cfg)} {card_id} --review --card-dir "
                                  f"{self.cfg.card_dir(card_id)} --worktree {start['cwd']}"])
        build = self.assigned()
        house.launch(self.cfg, self.board, build)
        self.assertEqual((self.fake.starts[1]["setting_sources"], self.fake.starts[1]["restricted"]), (None, False))
        self.assertEqual(real_harness.session_flags("/s.json", model="opus", setting_sources="user")[-2:],
                         ["--setting-sources", "user"])
        self.assertNotIn("--setting-sources", real_harness.session_flags("/s.json", model="opus"))

    def test_a_fork_s_review_house_takes_no_allow_rule_of_its_space(self):
        """c-769: a fork's review card has a repo and is confined all the same, so the
        space's allow list, which could name a command of the checkout, is not its."""
        self.cfg.spaces["personal"].allow = ["Bash(make check)"]
        fork = self.board.get(self.assigned(options=dict(self.FORK)))
        self.assertTrue(house.is_fork_review(fork))
        self.assertNotIn("allow", house.settings_body(self.cfg, fork)["permissions"])

    def test_a_fork_s_review_house_resumes_and_takes_turns_under_the_same_flags(self):
        """r2.F2, r2.F4: every door into the house carries what its start did."""
        from keel import housetalk
        card_id = self.assigned(options=dict(self.FORK))
        house.launch(self.cfg, self.board, card_id)
        house.resume(self.cfg, self.board, card_id)
        call = self.fake.resumes[0]
        self.assertEqual((call["setting_sources"], call["restricted"], call["tools"]),
                         ("user", True, house.FORK_REVIEW_TOOLS))
        flags = housetalk.flags_of(housetalk.plan(self.cfg, self.board.get(card_id)))
        self.assertEqual((flags["setting_sources"], flags["restricted"], flags["tools"]),
                         ("user", True, house.FORK_REVIEW_TOOLS))

    def test_an_ask_card_keeps_its_worker_s_tools_and_gets_no_web_it_did_not_ask_for(self):
        card_id = self.assigned(repo=None, options={"tools": "Read,Write", "drop": "/x/w.json"})
        house.launch(self.cfg, self.board, card_id)
        self.assertEqual(self.fake.starts[0]["tools"], "Read,Write")


    def test_failed_start_blocks_the_card_and_leaves_it_assigned(self):
        card_id = self.assigned()
        self.fake.fail = "claude exited 1"
        with self.assertRaises(house.harness.HarnessError):
            house.launch(self.cfg, self.board, card_id)
        card = self.board.get(card_id)
        self.assertEqual(card["stage"], "assigned")
        self.assertIn("house failed to start: claude exited 1", card["blocked_reason"])
        # Keel's own mechanics, which Bosun may repair on any card (c-575, `keel/repair.py`).
        self.assertEqual(self.board.events(card_id)[-1]["data"], {"mechanics": True})
        self.assertTrue(card["derived"]["needs_you"])
        self.assertFalse(card["derived"]["startable"])

    def test_a_stage_the_house_already_moved_is_kept(self):
        card_id = self.assigned()
        self.fake.on_start = lambda name: self.board.stage(name, "planning", "house", plan_ref="p.md")
        house.launch(self.cfg, self.board, card_id)
        self.assertEqual(self.board.get(card_id)["stage"], "planning")


class ResumeTest(HouseCase):
    def test_resume_keeps_the_same_settings_file_and_records_the_event(self):
        card_id = self.assigned()
        house.launch(self.cfg, self.board, card_id)
        settings = self.cfg.state_dir / "cards" / card_id / "settings.json"
        before = settings.read_text()
        house.resume(self.cfg, self.board, card_id)
        call = self.fake.resumes[0]
        self.assertEqual(call["session_id"], SESSION)
        self.assertEqual(call["prompt"], "continue from where you stopped; the card is still at building")
        self.assertEqual(call["settings_path"], settings)
        self.assertEqual(settings.read_text(), before, "the same settings, rewritten from the same code")
        self.assertEqual(call["cwd"], self.cfg.worktrees_dir / card_id)
        self.assertEqual(call["name"], card_id)
        event = self.board.events(card_id)[-1]
        self.assertEqual((event["kind"], event["actor"]), ("resume", "drain"))
        self.assertEqual(event["data"]["session_id"], SESSION)
        self.assertEqual(self.board.get(card_id)["session_id"], SESSION)

    def test_resume_records_a_new_session_when_the_harness_made_a_copy(self):
        card_id = self.assigned()
        house.launch(self.cfg, self.board, card_id)
        copy = "9999aaaa-0000-4000-8000-000000000002"
        self.fake.resume_bg = lambda session_id, prompt, **kw: {"bg_id": copy[:8], "session_id": copy}
        house.resume(self.cfg, self.board, card_id, prompt="carry on")
        self.assertEqual(self.board.get(card_id)["session_id"], copy)
        self.assertEqual([e["kind"] for e in self.board.events(card_id)][-2:], ["resume", "session"])


class CardNewsTest(HouseCase):
    """c-533: a field changed after the house was briefed reaches its next resume, once."""

    def brief(self, card_id) -> str:
        return (self.cfg.state_dir / "cards" / card_id / "brief.md").read_text()

    def test_autonomy_set_after_start_reaches_the_next_resume_and_the_brief(self):
        card_id = self.assigned(autonomy="attended")
        house.launch(self.cfg, self.board, card_id)
        self.assertIn('"autonomy": "attended"', self.brief(card_id))
        self.board.set_fields(card_id, {"autonomy": "autonomous"}, "human")
        house.resume(self.cfg, self.board, card_id)
        prompt = self.fake.resumes[0]["prompt"]
        self.assertTrue(prompt.startswith("continue from where you stopped"))
        self.assertIn("autonomy: attended -> autonomous", prompt)
        self.assertIn("do not wait at the plan gate", prompt)
        self.assertIn('"autonomy": "autonomous"', self.brief(card_id))
        self.assertTrue(self.brief(card_id).startswith("# You are the house"), "the rest is kept")
        house.resume(self.cfg, self.board, card_id)
        self.assertEqual(self.fake.resumes[1]["prompt"],
                         "continue from where you stopped; the card is still at planning",
                         "said once")

    def test_model_and_base_are_named_and_bookkeeping_is_not(self):
        card_id = self.assigned(model="opus")
        house.launch(self.cfg, self.board, card_id)
        self.board.set_fields(card_id, {"model": "sonnet", "options": {"base": "release", "app_link": "x"}},
                              "human")
        house.resume(self.cfg, self.board, card_id, prompt="carry on")
        prompt = self.fake.resumes[0]["prompt"]
        self.assertIn("model: opus -> sonnet; options.base: none -> release", prompt)
        self.assertIn(briefnews.MODEL_HINT, prompt)
        self.assertNotIn("app_link", prompt)


    def test_a_failed_resume_leaves_the_news_for_the_next_one(self):
        card_id = self.assigned(autonomy="attended")
        house.launch(self.cfg, self.board, card_id)
        self.board.set_fields(card_id, {"autonomy": "autonomous"}, "human")

        def fail(session_id, prompt, **kwargs):
            self.assertIn("autonomy: attended -> autonomous", prompt)
            raise house.harness.HarnessError("no")
        self.fake.resume_bg = fail
        with self.assertRaises(house.harness.HarnessError):
            house.resume(self.cfg, self.board, card_id)
        self.assertIn('"autonomy": "attended"', self.brief(card_id))


class ResumeSettingsTest(HouseCase):
    def test_a_resume_rewrites_the_settings_so_a_new_hook_reaches_an_open_card(self):
        """An errand started before the board fence existed must not be resumed without
        it: the hooks are Keel's, not a snapshot of the day the house started."""
        card_id = self.assigned(repo=None)
        house.launch(self.cfg, self.board, card_id)
        settings = self.cfg.card_dir(card_id) / "settings.json"
        settings.write_text('{"hooks": {}}\n')
        house.resume(self.cfg, self.board, card_id)
        hooks = json.loads(settings.read_text())["hooks"]
        self.assertIn("keel-board-fence", hooks["PreToolUse"][-1]["hooks"][0]["command"])
        self.assertEqual(self.fake.resumes[-1]["settings_path"], settings)


class ConfinedBriefTest(HouseCase):
    """A brief may not promise what the tool set denies."""

    def test_a_house_with_no_bash_gets_the_drop_contract_and_no_board_command(self):
        card_id = self.assigned(repo=None, options={"tools": "Read,Write", "drop": "/x/w.json"})
        card = self.board.get(card_id)
        self.assertEqual(house.contract_path(self.cfg, card).name, "house-contract-drop.md")
        text = house.brief_for(self.cfg, card)
        self.assertTrue(text.startswith("# You are the house for one card, and your output is a file"))
        self.assertIn("/x/w.json", text)
        for promise in ("kb stage", "kb note", "kb block", "`kb ", "lavish-axi"):
            self.assertNotIn(promise, text, promise)


class ThemeAndEnvironmentTest(HouseCase):
    """The two things a house is given so it never has to remember them: its space's theme
    beside the card, and a PATH whose `open` opens nothing."""

    def test_the_brief_leaves_the_spaces_theme_beside_the_card(self):
        card_id = self.assigned(space="personal")
        house.brief_for(self.cfg, self.board.get(card_id))
        copied = self.cfg.card_dir(card_id) / "theme.css"
        self.assertTrue(copied.is_file(), "no theme.css beside the card")
        self.assertEqual(copied.read_text(), (self.cfg.root / "app" / "theme-personal.css").read_text())


    def test_a_palette_change_reaches_a_card_that_is_already_open(self):
        card_id = self.assigned()
        copied = self.cfg.card_dir(card_id) / "theme.css"
        copied.write_text("/* stale */\n")
        house.ensure_theme(self.cfg, self.board.get(card_id))
        self.assertNotIn("stale", copied.read_text())


    def test_the_house_is_given_its_card_dir_wherever_state_dir_is(self):
        """c-604: the brief said `$KEEL_HOME/state/cards/<id>`, wrong when `state_dir` is
        elsewhere (the sandbox), and houses that reset KEEL_HOME broke `kb` and `pr`."""
        env = house.env_for(self.cfg, "c-1")
        self.assertEqual(env["KEEL_CARD_DIR"], str(self.cfg.cards_dir / "c-1"))
        root = Path(__file__).resolve().parent.parent
        for path in [*root.glob("keel/**/*.py"), *root.glob("etc/*.md"), *root.glob("packs/*/*.py")]:
            self.assertNotIn("$KEEL_HOME/state", path.read_text(), f"{path}: a brief names $KEEL_CARD_DIR")


    def test_a_toml_of_its_own_reaches_the_houses_hooks(self):
        """A sandbox's houses run `$KEEL_HOME/bin/kb` in their hooks; without the toml they
        load the checkout's own and write to its board (c-570: a review stamp landed there)."""
        own = Path(self.tmp.name) / "sandbox" / "keel.toml"
        with mock.patch.object(self.cfg, "source", own), mock.patch.object(self.cfg, "scratch", False):
            self.assertEqual(house.env_for(self.cfg, "c-1")["KEEL_CONFIG"], str(own.resolve()))

    def test_the_checkouts_own_toml_and_a_scratch_config_pass_none(self):
        """A named toml is taken at its word, so handing a house the checkout's own would
        send a Keel worktree's `kb` to that checkout's board instead of its scratch one."""
        for source, scratch in ((self.cfg.root / "keel.toml", False), (Path(self.tmp.name) / "x.toml", True), (None, False)):
            with self.subTest(source=source, scratch=scratch), \
                    mock.patch.object(self.cfg, "source", source), mock.patch.object(self.cfg, "scratch", scratch):
                self.assertEqual(house.env_for(self.cfg, "c-1")["KEEL_CONFIG"], "",
                                 "emptied, so a daemon a sandbox started cannot hand its toml on")


class DoneResumeTest(HouseCase):
    def test_a_done_card_is_never_resumed(self):
        """It ran a real turn in the reaped worktree and recreated the directory (c-601,
        e2e bug 6)."""
        card_id = self.assigned(repo="")
        self.board.stage(card_id, "building", "drain")
        self.board.set_session(card_id, SESSION, "drain", bg_id=SESSION[:8])
        self.board.stage(card_id, "review", "house", plan_ref="p", output_ref="o")
        self.board.stage(card_id, "done", "human")
        with self.assertRaises(Refused) as caught:
            house.resume(self.cfg, self.board, card_id)
        self.assertIn("is done", str(caught.exception))
        self.assertEqual(self.fake.resumes, [])


class HookBoardTest(unittest.TestCase):
    """A hook runs with the harness daemon's environment, not the drain's: a sandbox
    house's hooks followed the daemon's `KEEL_URL` to the LIVE deck (c-601, e2e bug 1)."""

    def setUp(self):
        from keel import config as config_module
        from tests.helpers import write_toml
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = config_module.load(write_toml(self.dir))
        with Board(self.cfg.db_path) as board:
            self.card = board.create("personal", "Pinned", brief="b", repo="")

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_hook_reaches_its_own_board_whatever_the_daemon_inherited(self):
        import os
        stale = self.dir / "stale"
        stale.mkdir()
        (stale / "keel.toml").write_text("this is not toml [\n")
        daemon = dict(os.environ, KEEL_URL="http://127.0.0.1:9", KEEL_HOME=str(stale),
                      KEEL_CONFIG=str(stale / "keel.toml"))
        hooks = house.hooks_for(self.cfg, self.card)
        command = hooks["SessionEnd"][0]["hooks"][0]["command"]
        done = subprocess.run(["sh", "-c", command], env=daemon, input="{}", text=True,
                              capture_output=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        with Board(self.cfg.db_path) as board:
            kinds = [(e["kind"], e["text"]) for e in board.events(self.card)]
        self.assertTrue(any("SessionEnd" in (text or "") or kind == "hook" for kind, text in kinds), kinds)

class VoiceHoldTest(HouseCase):
    """A house voice is talking to is not the drain's, the deck's Resume button's, or a
    relayed tap's to move (card c-315, V4 guard 2)."""

    def held(self) -> str:
        card_id = self.assigned()
        self.board.stage(card_id, "building", "drain")
        self.board.set_session(card_id, SESSION, "drain", bg_id=SESSION[:8])
        self.board.hold_voice(card_id, 300, stopped=True)
        return card_id

    def test_a_resume_is_refused_while_voice_holds_the_card(self):
        card_id = self.held()
        with self.assertRaises(Refused) as caught:
            house.resume(self.cfg, self.board, card_id)
        self.assertIn("voice is talking", str(caught.exception))
        self.assertEqual(self.fake.resumes, [])

    def test_his_own_answer_at_a_gate_releases_the_hold_rather_than_being_refused_by_it(self):
        """He is plainly finished talking to the house if he is answering its gate."""
        card_id = self.held()
        house.resume(self.cfg, self.board, card_id, prompt="approved", force=True)
        self.assertEqual(len(self.fake.resumes), 1)
        self.assertIsNone(self.board.voice_hold_of(card_id))

    def test_wake_puts_a_stopped_session_back_with_no_prompt_and_keeps_its_id(self):
        card_id = self.held()
        result = house.wake(self.cfg, self.board, card_id)
        self.assertEqual(result["session_id"], SESSION)
        self.assertEqual(self.fake.wakes, [SESSION])
        self.assertEqual(self.fake.resumes, [], "a wake takes no turn, so it costs nothing")
        self.assertEqual(self.board.get(card_id)["session_id"], SESSION)

    def test_wake_does_nothing_when_the_session_is_already_listed(self):
        card_id = self.held()
        self.fake.rows = [background_row(card_id, SESSION)]
        self.assertIsNone(house.wake(self.cfg, self.board, card_id))

    def test_a_wake_that_mints_a_copy_is_recorded_like_the_resume_it_turned_out_to_be(self):
        """A build of `claude` that does not keep a session's saved options answers with a
        new id. The card follows the session it actually has."""
        card_id = self.held()
        self.fake.woken = "99999999-0000-4000-8000-000000000099"
        house.wake(self.cfg, self.board, card_id)
        self.assertEqual(self.board.get(card_id)["session_id"], self.fake.woken)


class NoModelTest(HouseCase):
    """B1: a card that still has no model (one filed before the resolver, or imported) is
    refused at launch and blocked with the reason, never started on the account default."""

    def nameless(self) -> str:
        card_id = self.board.insert_card({"space": "personal", "title": "old", "stage": "assigned",
                                          "autonomy": "autonomous", "repo": "keel"}, "import")
        self.assertIsNone(self.board.get(card_id)["model"])
        return card_id

    def test_a_start_is_refused_and_the_card_blocked(self):
        card_id = self.nameless()
        with self.assertRaises(house.NoModel):
            house.launch(self.cfg, self.board, card_id)
        self.assertEqual(self.fake.starts, [])
        card = self.board.get(card_id)
        self.assertIn("no model", card["blocked_reason"])
        self.assertIn("kb set", card["blocked_reason"])
        self.assertEqual(card["stage"], "assigned")


class SessionOriginTest(HouseCase):
    """B5: a house's session is declared to csr, the session index, as ground truth: one
    small file per session naming the card, written only where csr keeps its sidecars."""

    def sidecars(self):
        return self.cfg.home / ".claude" / "session-origin"

    def test_a_launch_writes_the_sidecar_naming_the_card(self):
        self.sidecars().mkdir(parents=True)
        card_id = self.assigned(topic="boards")
        house.launch(self.cfg, self.board, card_id)
        written = json.loads((self.sidecars() / f"{SESSION}.json").read_text())
        self.assertEqual(written, {"provenance": "house", "origin_ref": card_id, "topic": "boards"})

    def test_a_resume_that_mints_a_new_session_declares_that_one_too(self):
        self.sidecars().mkdir(parents=True)
        card_id = self.assigned()
        self.board.set_session(card_id, "11111111-0000-4000-8000-000000000009", "drain")
        self.fake.resume_bg = lambda session_id, prompt, **kwargs: {"bg_id": SESSION[:8],
                                                                    "session_id": SESSION}
        with mock.patch.object(house, "APP_LINK_PAUSE", 0):
            house.resume(self.cfg, self.board, card_id)
        written = json.loads((self.sidecars() / f"{SESSION}.json").read_text())
        self.assertEqual(written["origin_ref"], card_id)
        self.assertNotIn("topic", written)


    def test_a_sidecar_that_cannot_be_written_never_fails_the_launch(self):
        self.sidecars().mkdir(parents=True)
        (self.sidecars() / f"{SESSION}.json").mkdir()     # a directory where the file goes
        card_id = self.assigned()
        house.launch(self.cfg, self.board, card_id)
        self.assertEqual(self.board.get(card_id)["session_id"], SESSION)


class BusyResumeTest(HouseCase):
    """E1 (c-443): a resume never stops a BUSY session. `claude --resume --bg` with flags on
    a running session makes a copy, and the supersede rule would then stop the original
    mid-turn; so a house the listing says is busy is refused, with a reason the deck shows.
    An IDLE live session is still resumed and superseded, as designed."""

    def live(self, status: str) -> str:
        card_id = self.assigned()
        self.board.stage(card_id, "building", "drain")
        self.board.set_session(card_id, SESSION, "drain", bg_id=SESSION[:8])
        self.fake.rows = [background_row(card_id, SESSION, status=status)]
        self.fake.stops = []
        self.fake.resume_bg = lambda session_id, prompt, **kw: {
            "bg_id": "d4db30e1", "session_id": "d4db30e1-f5d6-4498-83a6-9dd7a1c057d6"}
        return card_id

    def test_a_busy_session_is_refused_and_nothing_is_started_or_stopped(self):
        card_id = self.live("busy")
        with self.assertRaises(house.Busy) as caught:
            house.resume(self.cfg, self.board, card_id)
        self.assertIsInstance(caught.exception, Refused)
        self.assertIn("working", str(caught.exception))
        self.assertEqual(self.board.get(card_id)["session_id"], SESSION)
        self.assertEqual(self.fake.stops, [])

    def test_his_gate_answer_does_not_override_a_busy_session_either(self):
        card_id = self.live("busy")
        with self.assertRaises(house.Busy):
            house.resume(self.cfg, self.board, card_id, prompt="approved", force=True)
        self.assertEqual(self.fake.stops, [])


    def test_resume_and_landing_ask_one_rule(self):
        """r-26: resume read `status`, landing read `state`. An idle house whose background
        job still runs (status busy, state done: c-535) is resumed, as landing stops it."""
        card_id = self.live("busy")
        self.fake.rows = [dict(self.fake.rows[0], state="done")]
        with mock.patch.object(house, "APP_LINK_PAUSE", 0):
            house.resume(self.cfg, self.board, card_id)
        self.assertEqual(self.fake.stops, [SESSION[:8]])

    def test_a_row_listed_working_with_no_process_is_not_working(self):
        card_id = self.live("busy")
        ghost = {k: v for k, v in self.fake.rows[0].items() if k not in ("pid", "status")}
        self.fake.rows = [ghost]
        with mock.patch.object(house, "APP_LINK_PAUSE", 0):
            house.resume(self.cfg, self.board, card_id)
        self.assertEqual(self.board.get(card_id)["session_id"],
                         "d4db30e1-f5d6-4498-83a6-9dd7a1c057d6")


class BusyBeforeHoldTest(HouseCase):
    """Review finding 9: a gate answer on a held house that is WORKING is refused before
    the hold is touched, so a refusal leaves the voice hold exactly as it was."""

    def test_the_hold_survives_a_busy_refusal(self):
        card_id = self.assigned()
        self.board.stage(card_id, "building", "drain")
        self.board.set_session(card_id, SESSION, "drain", bg_id=SESSION[:8])
        self.board.hold_voice(card_id, 300, stopped=True)
        self.fake.rows = [background_row(card_id, SESSION, status="busy")]
        with self.assertRaises(house.Busy):
            house.resume(self.cfg, self.board, card_id, prompt="approved", force=True)
        self.assertIsNotNone(self.board.voice_hold_of(card_id))
        self.assertNotIn("released it", " ".join(e.get("text") or "" for e in self.board.events(card_id)))


class TrustTest(HouseCase):
    """Claude Code 2.1.281 refuses `claude --bg` in a directory the config dir never trusted
    ("Workspace not trusted", c-452 on the box, 2026-09-24), so every start trusts its cwd
    in the space's `.claude.json` first."""

    def claude_json(self) -> Path:
        return self.cfg.spaces["personal"].config_dir / ".claude.json"

    def trusted(self) -> dict:
        try:
            return json.loads(self.claude_json().read_text()).get("projects", {})
        except FileNotFoundError:
            return {}

    def entry_at_start(self, cwd_of):
        seen = []
        self.fake.on_start = lambda name: seen.append(self.trusted().get(str(cwd_of())))
        return seen

    def test_an_errand_launch_trusts_its_card_dir_before_start_bg(self):
        card_id = self.assigned(repo=None)
        seen = self.entry_at_start(lambda: self.cfg.card_dir(card_id))
        house.launch(self.cfg, self.board, card_id)
        self.assertEqual(seen, [{"allowedTools": [], "mcpServers": {},
                                 "hasTrustDialogAccepted": True}])


    def test_an_unparseable_claude_json_blocks_the_launch_and_is_not_written_over(self):
        card_id = self.assigned(repo=None)
        self.claude_json().parent.mkdir(parents=True, exist_ok=True)
        self.claude_json().write_text('{"oauthAccount": {')
        with self.assertRaises(Exception):
            house.launch(self.cfg, self.board, card_id)
        self.assertEqual(self.fake.starts, [])
        self.assertEqual(self.claude_json().read_text(), '{"oauthAccount": {')
        reason = self.board.get(card_id)["blocked_reason"]
        self.assertIn("house failed to start", reason)
        self.assertIn("does not parse", reason)

    def test_a_resume_trusts_its_cwd_first(self):
        card_id = self.assigned(repo=None)
        house.launch(self.cfg, self.board, card_id)
        self.claude_json().unlink()
        seen = []
        real = self.fake.resume_bg
        self.fake.resume_bg = lambda sid, prompt, **kw: (
            seen.append(str(kw["cwd"]) in self.trusted()) or real(sid, prompt, **kw))
        house.resume(self.cfg, self.board, card_id)
        self.assertEqual(seen, [True])


    def test_approving_an_errand_forgets_its_card_dir(self):
        card_id = self.assigned(repo=None)
        house.launch(self.cfg, self.board, card_id)
        self.assertIn(str(self.cfg.card_dir(card_id)), self.trusted())
        house.retire_finished(self.cfg, self.board, self.board.get(card_id))
        self.assertNotIn(str(self.cfg.card_dir(card_id)), self.trusted())
