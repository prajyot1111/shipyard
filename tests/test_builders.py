"""Bosun's builder (c-619, c-621, `keel/builder.py`): on an install one builder, running as
the user in auto mode or in bypass, kept out of the live checkouts by one hook, using the
board through `kb` as Bosun, and landing nothing without the user's tap; no superuser. The
superuser is the legacy builder, which does not start until its fence is decided (c-648). One
test per promise, through its public seam."""

import json
import os
import pwd
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from keel import actions, adapters, authority, bosuntalk, builder, cli, console, consoletaps, harness, house, housetier, installer, landing, merging, receipt, repolayout
from keel import config as config_module
from keel.board import Board, Refused
from tests.helpers import ROOT, SESSION, FakeHarness, make_config

FAKE_USER = pwd.struct_passwd(("bosun", "x", 1002, 1002, "", "/home/bosun", "/bin/bash"))
GUARD = ROOT / "bin" / "keel-builder-guard"


def git(repo: Path, *argv: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *argv],
                          capture_output=True, text=True, check=True).stdout.strip()


def install_config(home: Path):
    """An install's config, as `shipyard init` leaves it: its packs repo, Bosun's clone of it,
    the install's key, and builder mode on (auto, the default)."""
    packs = home / "packs"
    packs.mkdir(parents=True)
    git(packs, "init", "-q", "-b", "main")
    git(packs, "commit", "-q", "--allow-empty", "-m", "init")
    subprocess.run(["git", "clone", "-q", str(packs), str(home / "builder" / "packs")], check=True)
    cfg = make_config(home, repos={"packs": packs})
    cfg.source, cfg.bosun_builder, cfg.builder = home / "config.toml", True, {}
    housetier.mint_shared(cfg)
    example = (ROOT / installer.EXAMPLE).read_text()     # what kb reads
    ports = {"serve_port": 8999, "lavish_port": 4998, "voice_port": 4997}
    cfg.source.write_text(installer.render_config(example, home, ports, "test"))
    return cfg


def guard(roots: list[Path], payload) -> int:
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(GUARD), *map(str, roots)], input=stdin,
                          capture_output=True, text=True).returncode


class InAppTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve() / "install"
        self.cfg = install_config(self.home)

    def test_it_runs_as_the_user_in_auto_mode_with_one_hook_and_no_fence(self):
        made = console.settings(self.cfg)
        self.assertEqual(console.permission_mode(self.cfg), "auto")
        self.assertEqual(console.cwd(self.cfg), self.home / "builder")
        self.assertEqual(made["crossSessionInbound"], "accept")      # the drain's wake reaches it
        self.assertNotIn("sandbox", made)
        self.assertEqual(made["env"]["KEEL_CONFIG"], str(self.cfg.source))
        hook = made["hooks"]["PreToolUse"][0]
        self.assertEqual(hook["matcher"], "Edit|Write|MultiEdit|NotebookEdit|Bash")
        self.assertIn("keel-builder-guard", hook["hooks"][0]["command"])
        self.assertIn(str(ROOT), hook["hooks"][0]["command"], "the live code is guarded")
        deny = made["permissions"]["deny"]
        for rule in (f"Read(/{self.home}/credentials/**)", f"Read(/{Path.home()}/.ssh/**)",
                     "Bash(*git*push*--force*)", "Bash(*git*push* main*)"):
            self.assertIn(rule, deny)
        self.assertFalse([rule for rule in deny if str(self.home / "builder") in rule], "its clones are its own")
        allow = made["permissions"]["allow"]
        for rule in ("Bash(kb create:*)", "Bash(kb split:*)", "Bash(keel board push:*)"):
            self.assertIn(rule, allow)
        auto = made["autoMode"]
        self.assertEqual((auto["soft_deny"], auto["allow"][0], auto["hard_deny"][0]),
                         (["$defaults"], "$defaults", "$defaults"))
        said = " ".join(auto["hard_deny"])
        for words in ("force-pushing", "live checkout", "credentials", str(ROOT)):
            self.assertIn(words, said)
        # c-678: auto mode is the Guide builder, which installs nothing and changes no setting
        self.assertIn("Installing software on this computer", said)

    def test_the_guard_keeps_bosun_out_of_every_repo_the_install_copied(self):
        """c-678: Bosun reads the user's repos to draft their CLAUDE.md, and never edits them.
        A repo in the install's layout is a live checkout to the guard, whatever its space."""
        repo = self.home / "spaces" / "work" / "api" / "repo"
        elsewhere = self.home.parent / "mine"
        self.cfg.spaces["work"].repos = {"api": repo, "mine": elsewhere}
        guarded = builder.live_checkouts(self.cfg)
        self.assertIn(repo, guarded)
        self.assertNotIn(elsewhere, guarded, "a checkout outside the layout is its space's own business")

    def test_the_superbuilder_runs_in_bypass_and_an_unknown_mode_is_refused(self):
        self.cfg.builder = {"mode": "bypass"}
        self.assertEqual(console.permission_mode(self.cfg), "bypassPermissions")
        self.assertEqual(builder.status(self.cfg)["label"], "Builder, bypass")
        made = console.settings(self.cfg)
        self.assertIn("keel-builder-guard", made["hooks"]["PreToolUse"][0]["hooks"][0]["command"])
        self.assertIsNone(builder.refusal(self.cfg))
        self.cfg.builder = {"mode": "yolo"}
        self.assertIn("[builder] mode is 'yolo'", builder.refusal(self.cfg))

    def test_a_tap_launches_with_the_mode_on_disk(self):
        """His Mac, 2026-10-03: he set mode = "bypass" in config.toml and tapped Restart; the
        deck launched Bosun with the config it read at its own start (auto), and Bosun's
        process, a daemon spare made by the old launch, still carried KEEL_URL to the
        removed door, so every kb failed."""
        text = self.cfg.source.read_text().replace('# mode = "auto"', 'mode = "bypass"', 1)
        self.cfg.source.write_text(text)
        launched = {}
        fake = lambda *a, **k: (launched.update(k), {"bg_id": "b", "session_id": "s"})[1]
        with mock.patch.object(harness, "start_bg", fake):
            consoletaps.tap(self.cfg, "start")
        self.assertEqual(launched["permission_mode"], "bypassPermissions")
        made = json.loads(Path(launched["settings_path"]).read_text())
        self.assertEqual(made["env"]["KEEL_CONFIG"], str(self.cfg.source))

    def test_an_install_has_no_superuser(self):
        self.cfg.builder = dict(self.cfg.builder, superuser=True)
        self.assertNotIn(authority.SUPERUSER, self.cfg.switches)
        with self.assertRaisesRegex(console.ConsoleError, "an install has one builder.*mode = \"bypass\""):
            consoletaps.launch(self.cfg, None)

    def test_its_kb_reaches_the_board_as_bosun_and_the_board_scopes_it(self):
        """No door: its `kb` opens the install's board itself, with Bosun's key, and the
        board's own rules hold it to its repos and its own cards."""
        env = dict(os.environ, KEEL_CONFIG=str(self.cfg.source), KEEL_CARD="",
                   **{console.BOSUN_ENV: console.key_of(self.cfg)})
        env.pop("KEEL_URL", None)

        def kb(*argv):
            return subprocess.run([str(ROOT / "bin" / "kb"), *argv], env=env, capture_output=True, text=True)
        made = kb("create", "--space", "personal", "--title", "a pack", "--repo", "packs", "--json")
        self.assertEqual(made.returncode, 0, made.stderr)
        card = json.loads(made.stdout)["id"]
        self.assertEqual(kb("split", card, "--slice", "S1|first", "--slice", "S2|second|S1").returncode, 0)
        board = Board(self.cfg.db_path, switches=self.cfg.switches, builds=builder.repos(self.cfg))
        self.addCleanup(board.close)
        self.assertEqual(board.events(card)[0]["actor"], authority.BOSUN)
        self.assertEqual(len(board.conn.execute("SELECT id FROM cards WHERE parent = ?", (card,)).fetchall()), 2)
        refused = kb("create", "--space", "personal", "--title", "x", "--repo", "app")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("only on packs", refused.stderr)

    def test_approve_lands_a_keel_card_on_next_and_never_main(self):
        live = self.home.parent / "keel-live"
        live.mkdir()
        git(live, "init", "-q", "-b", "main")
        git(live, "commit", "-q", "--allow-empty", "-m", "init")
        git(live, "branch", "next")
        self.cfg.spaces["personal"].repos["keel"] = live
        self.cfg.builder = dict(self.cfg.builder, repos=["packs", "keel"])
        self.cfg.integration = {"keel": "next"}
        self.assertEqual(builder.ensure_clones(self.cfg), ["keel"])
        clone = self.home / "builder" / "keel"
        git(clone, "checkout", "-q", "-b", "bosun/c-002-fix", "origin/next")
        (clone / "fix.txt").write_text("fixed\n")
        git(clone, "add", "-A")
        git(clone, "commit", "-q", "-m", "fix")
        card = {"id": "c-002", "space": "personal", "repo": "keel", "title": "fix",
                "output_ref": "bosun/c-002-fix", "options": {}}
        main = git(live, "rev-parse", "main")
        with self.assertRaisesRegex(merging.MergeRefused, "Approve outcome"):
            merging.branch_placed(self.cfg, card)            # nothing reads it before his tap
        self.assertEqual(git(live, "for-each-ref", "refs/builder"), "")
        landed = merging.land_card(self.cfg, card)          # his Approve outcome
        self.assertEqual(landed["target"], "next")
        self.assertEqual(git(live, "show", "next:fix.txt"), "fixed")
        self.assertEqual(git(live, "rev-parse", "main"), main, "main moves only by his deploy")
        self.assertEqual(git(live, "branch", "--list", "bosun/*"), "", "no live branch written")

    def test_a_voice_held_bosun_turn_runs_as_the_builder(self):
        board = mock.Mock(bosun_hold=mock.Mock(return_value=True))
        made = bosuntalk.door_plan(self.cfg, board)
        self.assertEqual((made["cwd"], made["permission_mode"]), (str(self.home / "builder"), "auto"))
        self.assertIn("autoMode", json.loads(Path(made["settings_path"]).read_text()))

    def test_the_board_refuses_it_a_landing_tested_and_another_repo(self):
        board = Board(self.cfg.db_path, switches=self.cfg.switches, builds=builder.repos(self.cfg))
        self.addCleanup(board.close)
        with self.assertRaisesRegex(Refused, "only on packs"):
            board.create("personal", "x", repo="keel", actor=authority.BOSUN)
        card = board.create("personal", "a pack", repo="packs", actor=authority.BOSUN, autonomy="autonomous")
        with self.assertRaisesRegex(Refused, "landing is the user's tap"):
            authority.gate_approval(board.get(card), "outcome", {}, "checked", board.builder,
                                    superuser=board.superuser)
        with self.assertRaisesRegex(Refused, "superuser builder's"):
            cli.cmd_tested(board, types.SimpleNamespace(), authority.BOSUN)

    def test_in_bypass_it_passes_its_own_cards_gates_and_no_one_elses(self):
        """His call, 2026-10-03: the superbuilder does not stop to ask. Its own personal cards'
        plan and outcome gates are its to pass; the outcome still only onto an integration
        branch, checked clean and reviewed; another repo's card, and auto mode, stay his."""
        facts = {"integration": "next", "trunk": "main", "errors": [], "reviewed": True, "sha": "abc123"}

        def board_in(mode):
            self.cfg.builder, self.cfg.merge_queue = {"mode": mode}, True
            board = Board(self.cfg.db_path, switches=self.cfg.switches, builds=builder.repos(self.cfg))
            self.addCleanup(board.close)
            return board

        def at_plan(board, repo="packs"):
            card = board.create("personal", "a pack", repo=repo, actor="human", autonomy="attended")
            board.stage(card, "planning", "drain", plan_ref="plan.md")
            return card
        auto = board_in("auto")
        card = at_plan(auto)
        with self.assertRaisesRegex(Refused, "plan gate is his"):
            auto.approve(card, "plan", authority.BOSUN, bosun={"checked": "read it", "facts": None})
        bypass = board_in("bypass")
        self.assertTrue(bypass.bypass)
        self.assertFalse(bypass.superuser, "bypass widens no scope")
        card = at_plan(bypass)
        with self.assertRaisesRegex(Refused, "says what it checked"):
            bypass.approve(card, "plan", authority.BOSUN, bosun={"checked": "", "facts": None})
        self.assertEqual(bypass.approve(card, "plan", authority.BOSUN,
                                        bosun={"checked": "read it", "facts": None})["stage"], "building")
        bypass.stage(card, "review", authority.BOSUN, output_ref="bosun/c-x")
        bypass.approve(card, "outcome", authority.BOSUN, bosun={"checked": "tests", "facts": facts, "to": "mac"})
        approvals = [(e.get("data") or {}).get("approval") for e in bypass.events(card)]
        self.assertEqual({a["lands_on"] for a in approvals if a and a.get("gate") == "outcome"}, {"next"})
        with self.assertRaisesRegex(Refused, "lands on|live"):
            other = at_plan(bypass)
            bypass.approve(other, "plan", authority.BOSUN, bosun={"checked": "x", "facts": None})
            bypass.stage(other, "review", authority.BOSUN, output_ref="bosun/c-y")
            bypass.approve(other, "outcome", authority.BOSUN,
                           bosun={"checked": "x", "facts": dict(facts, integration=None), "to": "mac"})
        theirs = at_plan(bypass, repo="app")
        with self.assertRaisesRegex(Refused, "not a card the builder builds"):
            bypass.approve(theirs, "plan", authority.BOSUN, bosun={"checked": "x", "facts": None})

    def test_bosun_builds_only_its_repos_and_a_house_the_rest(self):
        board = Board(self.cfg.db_path, switches=self.cfg.switches, builds=builder.repos(self.cfg))
        self.addCleanup(board.close)
        ours = board.create("personal", "a pack", repo="packs", actor="human", autonomy="autonomous")
        theirs = board.create("personal", "an app", repo="app", actor="human", autonomy="autonomous")
        for card in (ours, theirs):
            board.stage(card, "assigned", "human")
        derived = {card: board.get(card)["derived"] for card in (ours, theirs)}
        self.assertEqual((derived[ours]["bosun"], derived[ours]["startable"]), (True, False))
        self.assertEqual((derived[theirs]["bosun"], derived[theirs]["startable"]), (False, True))

    def test_a_builder_card_at_review_is_never_pre_run_or_fetched(self):
        clone = self.home / "builder" / "packs"
        git(clone, "checkout", "-q", "-b", "bosun/c-001-mine")
        git(clone, "commit", "-q", "--allow-empty", "-m", "mine")
        self.cfg.merge_queue = True
        board = Board(self.cfg.db_path, switches=self.cfg.switches, builds=builder.repos(self.cfg))
        self.addCleanup(board.close)
        card = board.create("personal", "a pack", repo="packs", actor=authority.BOSUN, autonomy="autonomous")
        board.set_fields(card, {"plan_ref": "p", "output_ref": "bosun/c-001-mine"}, "human")
        with board.tx():
            board.conn.execute("UPDATE cards SET stage = 'review' WHERE id = ?", (card,))
        with mock.patch.object(landing, "spawn") as spawned:
            self.assertFalse(landing.pre_run_one(self.cfg, board))
        spawned.assert_not_called()
        self.assertIsNone(landing.heads(self.cfg, board.get(card)))
        self.assertEqual(git(self.home / "packs", "for-each-ref", "refs/builder"), "", "nothing fetched")

    def test_approve_outcome_fetches_its_branch_from_the_clone_and_lands_it(self):
        clone = self.home / "builder" / "packs"
        git(clone, "checkout", "-q", "-b", "bosun/c-001-mine")
        (clone / "mine").mkdir()
        (clone / "mine" / "pack.toml").write_text('name = "mine"\n')
        git(clone, "add", "-A")
        git(clone, "commit", "-q", "-m", "mine")
        card = {"id": "c-001", "space": "personal", "repo": "packs", "title": "mine",
                "output_ref": "bosun/c-001-mine", "options": {}}
        landed = merging.land_card(self.cfg, card)
        self.assertEqual(landed["target"], "main")
        self.assertTrue((self.home / "packs" / "mine" / "pack.toml").is_file(), "the working tree moved")
        self.assertEqual(git(self.home / "packs", "branch", "--list", "bosun/*"), "", "no live branch written")
        before = git(self.home / "packs", "rev-parse", "main")
        self.assertIsNone(merging.land_card(self.cfg, dict(card, output_ref="main")), "never the trunk")
        self.assertEqual(git(self.home / "packs", "rev-parse", "main"), before)

    def test_a_leftover_house_worktree_never_names_the_branch_bosun_s_card_lands(self):
        """c-647: a house started by accident left its worktree on a branch of its own; the
        card's outcome names Bosun's branch, and that is the one fetched and landed."""
        clone, live = self.home / "builder" / "packs", self.home / "packs"
        git(clone, "checkout", "-q", "-b", "bosun/c-001-mine")
        (clone / "mine.toml").write_text('name = "mine"\n')
        git(clone, "add", "-A")
        git(clone, "commit", "-q", "-m", "mine")
        board = Board(self.cfg.db_path, switches=self.cfg.switches, builds=builder.repos(self.cfg))
        self.addCleanup(board.close)
        card_id = board.create("personal", "a pack", repo="packs", actor=authority.BOSUN, autonomy="autonomous")
        board.set_fields(card_id, {"output_ref": "bosun/c-001-mine"}, "human")
        card = board.get(card_id)
        self.assertTrue(card["derived"]["bosun"])
        tree = repolayout.card_tree(self.cfg, card)
        git(live, "worktree", "add", "-q", "-b", f"keel/{card_id}-house", str(tree))
        sha = git(clone, "rev-parse", "HEAD")
        for unusable in (sha, f"keel/{card_id}-house", "bosun/c-001-mine~0", "bosun/c-001-mine^0",
                         "bosun/c-001-mine@{0}", "Main", f"MAIN @ {sha}"):
            with self.subTest(unusable), self.assertRaisesRegex(merging.MergeRefused, "--output <branch>"):
                merging.land_card(self.cfg, dict(card, output_ref=unusable))    # not a branch of the clone
        for named in (f"bosun/c-001-mine @ {sha}", f"branch bosun/c-001-mine @ {sha}"):
            found = merging.branch_placed(self.cfg, dict(card, output_ref=named), fetch=True)
            self.assertEqual(found[3], "refs/builder/bosun/c-001-mine")
        landed = merging.land_card(self.cfg, dict(card, output_ref=f"bosun/c-001-mine @ {sha}"))
        self.assertEqual(landed["target"], "main")
        self.assertTrue((live / "mine.toml").is_file(), "Bosun's branch landed")

    def builder_board(self, *switches) -> Board:
        board = Board(self.cfg.db_path, switches={*self.cfg.switches, *switches}, builds=builder.repos(self.cfg))
        self.addCleanup(board.close)
        return board

    def test_a_card_closed_unlanded_on_the_read_only_refusal_keeps_its_worktree(self):
        """c-647: only an outcome that names no branch gives up a leftover worktree. With a
        clone the branch is not read before the tap, and that refusal removes nothing."""
        live = self.home / "packs"
        board = self.builder_board()
        card_id = board.create("personal", "a pack", repo="packs", actor=authority.BOSUN, autonomy="autonomous")
        board.set_fields(card_id, {"output_ref": "bosun/c-001-mine"}, "human")
        card = board.get(card_id)
        tree = repolayout.card_tree(self.cfg, card)
        git(live, "worktree", "add", "-q", "-b", f"keel/{card_id}-house", str(tree))
        (tree / "uncommitted.toml").write_text('name = "not yet"\n')
        with self.assertRaisesRegex(merging.MergeRefused, "read only when"):
            merging.branch_placed(self.cfg, card)
        self.assertEqual(merging.close_unlanded(self.cfg, card), [])
        self.assertTrue((tree / "uncommitted.toml").is_file(), "the worktree and what is in it stay")

    def test_a_branch_checked_out_in_a_worktree_of_the_clone_lands(self):
        clone, live = self.home / "builder" / "packs", self.home / "packs"
        tree = self.home / "builder" / "packs-c-001"
        git(clone, "worktree", "add", "-q", "-b", "bosun/c-001-tree", str(tree))
        (tree / "tree.toml").write_text('name = "tree"\n')
        git(tree, "add", "-A")
        git(tree, "commit", "-q", "-m", "in a worktree")
        board = self.builder_board()
        card_id = board.create("personal", "a pack", repo="packs", actor=authority.BOSUN, autonomy="autonomous")
        board.set_fields(card_id, {"output_ref": "bosun/c-001-tree"}, "human")
        merging.land_card(self.cfg, board.get(card_id))
        self.assertTrue((live / "tree.toml").is_file())

    def test_a_house_s_card_on_a_builder_repo_lands_its_worktree_s_branch_from_the_live_repo(self):
        """c-647 F2: the clone is Bosun's; a card he gave a house never reads it."""
        live = self.home / "packs"
        self.cfg.merge_queue = True
        board = self.builder_board()
        card_id = board.create("personal", "a pack", repo="packs", actor="human", autonomy="autonomous",
                               options={"worker": "house"})
        card = board.get(card_id)
        self.assertFalse(card["derived"]["bosun"])
        tree = repolayout.card_tree(self.cfg, card)
        git(live, "worktree", "add", "-q", "-b", f"keel/{card_id}-house", str(tree))
        (tree / "house.toml").write_text('name = "house"\n')
        git(tree, "add", "-A")
        git(tree, "commit", "-q", "-m", "the house's")
        self.assertEqual(merging.branch_placed(self.cfg, card)[3], f"keel/{card_id}-house", "read with no tap")
        self.assertIsNotNone(landing.heads(self.cfg, card), "and pre-run like any house's card")
        merging.land_card(self.cfg, card)
        self.assertTrue((live / "house.toml").is_file())
        self.assertEqual(git(live, "for-each-ref", "refs/builder"), "", "nothing fetched from the clone")

    def test_a_conflict_on_a_branch_from_the_clone_waits_on_bosun_and_resumes_no_house(self):
        clone, live = self.home / "builder" / "packs", self.home / "packs"
        git(clone, "checkout", "-q", "-b", "bosun/c-001-mine")
        (clone / "same.toml").write_text('name = "mine"\n')
        git(clone, "add", "-A")
        git(clone, "commit", "-q", "-m", "mine")
        (live / "same.toml").write_text('name = "theirs"\n')
        git(live, "add", "-A")
        git(live, "commit", "-q", "-m", "theirs")
        self.cfg.merge_queue = True
        fake = FakeHarness()
        for module in (landing, house):
            patch = mock.patch.object(module, "harness", fake)
            patch.start()
            self.addCleanup(patch.stop)
        board = self.builder_board("merge_queue")
        card_id = board.create("personal", "a pack", repo="packs", actor=authority.BOSUN, autonomy="autonomous")
        board.set_fields(card_id, {"plan_ref": "p", "output_ref": "bosun/c-001-mine"}, "human")
        board.set_session(card_id, SESSION, "drain", bg_id=SESSION[:8])      # a house's leftover
        with board.tx():
            board.conn.execute("UPDATE cards SET stage = 'review' WHERE id = ?", (card_id,))
        board.relay(card_id, "land", "human", self.cfg.host, sha=git(clone, "rev-parse", "HEAD"))
        relay = board.get(card_id)["derived"]["relays"][-1]["id"]
        board.carry(card_id, relay, "drain")
        self.assertEqual(landing.run(self.cfg, board, card_id, relay=relay), 1)
        card = board.get(card_id)
        self.assertEqual((card["stage"], fake.resumes, fake.starts), ("building", [], []))
        events = board.events(card_id)
        moved = [e["text"] for e in events if e["kind"] == "stage"][-1]
        now = receipt.receipt(self.cfg, card, events, "outcome")["now"]
        for said in (moved, now):
            self.assertIn("waiting for Bosun to merge main into bosun/c-001-mine", said)
            self.assertNotIn("refs/builder", said)
        self.assertNotIn("house", now)




class GuardTest(unittest.TestCase):
    """Never edit a live checkout (`keel/builderguard.py`): the editing tools by path, failing
    closed; Bash a speed bump over its commands, following cd and git -C."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.live, self.clone = root / "keel", root / "install" / "builder" / "keel"
        for path in (self.live, self.clone):
            path.mkdir(parents=True)
        (self.clone / "out").symlink_to(self.live)          # a link from its clone to the live code

    def edit(self, path, tool="Write") -> int:
        return guard([self.live], {"tool_name": tool, "tool_input": {"file_path": str(path)},
                                   "cwd": str(self.clone)})

    def bash(self, line: str, cwd=None) -> int:
        return guard([self.live], {"tool_name": "Bash", "tool_input": {"command": line},
                                   "cwd": str(cwd or self.clone)})

    def test_an_edit_in_a_live_checkout_is_refused_and_its_clone_is_its_own(self):
        self.assertEqual(self.edit(self.clone / "keel" / "builder.py"), 0)
        self.assertEqual(self.edit(Path.home() / "notes.txt"), 0, "only the live checkouts are fenced")
        self.assertEqual(self.edit("rel.py", "Edit"), 0, "relative to its cwd in the clone")
        for path in (self.live / "keel" / "builder.py", self.clone / "out" / "x.py"):
            self.assertEqual(self.edit(path), 2, path)
        for refused in ("garbage", "{}", json.dumps({"tool_name": "Write", "tool_input": {}})):
            self.assertEqual(guard([self.live], refused), 2, refused)

    def test_bash_may_read_a_live_checkout_but_not_write_or_move_it(self):
        for line in (f"cd {self.live} && grep -rn foo keel | head", f"git -C {self.live} log --oneline -3",
                     f"cat {self.live}/keel/builder.py > /tmp/x", f"cp {self.live}/a.py {self.clone}/a.py",
                     "git commit -am x", f"git -C {self.live} branch --list"):
            self.assertEqual(self.bash(line), 0, line)
        for line in (f"cd {self.live} && git checkout -b x", f"git -C {self.live} reset --hard",
                     f"echo x > {self.live}/a.py", f"rm -rf {self.live}/keel", f"sed -i '' s/a/b/ {self.live}/a.py",
                     f"cp a.py {self.live}/a.py", f"git -C {self.live} branch -D next",
                     f"cd {self.clone}/out && git commit -am x"):
            self.assertEqual(self.bash(line), 2, line)
        self.assertEqual(self.bash("git stash", cwd=self.live), 2, "run from inside the live checkout")


class SuperuserTest(unittest.TestCase):
    def test_a_superuser_configs_settings_and_board_scope(self):
        """What a checkout's own config's `[builder] superuser` still decides (c-619): the
        session's settings in bypass, with its peer wake and no sandbox, the board's switch,
        and every personal repo card as Bosun's. No one's config is tracked since c-722, so
        the shipped example is read with the switch and the `[console]` keys written here.
        It does not start (the test below)."""
        bypass = '[console]\nhost = "mac"\npermission_mode = "bypassPermissions"\n'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keel.toml"
            example = (ROOT / "etc" / "shipyard.example.toml").read_text()
            path.write_text(example.replace("superuser = false\n", "superuser = true\n", 1) + bypass)
            cfg = config_module.load(path, ensure=False)
        with mock.patch.object(authority, "bosun_key", return_value="k"):
            made = console.settings(cfg)
        self.assertEqual((builder.mode(cfg), console.permission_mode(cfg)), ("superuser", "bypassPermissions"))
        self.assertEqual(made["crossSessionInbound"], "accept")
        self.assertNotIn("sandbox", made)
        self.assertNotIn("autoMode", made)
        self.assertIn(authority.SUPERUSER, cfg.switches)
        with tempfile.TemporaryDirectory() as tmp:      # every personal repo card, as before
            board = Board(Path(tmp) / "b.db", switches=cfg.switches, builds=builder.repos(cfg))
            self.addCleanup(board.close)
            for repo in ("keel", "harbor", "a-new-project"):
                self.assertTrue(board.get(board.create("personal", repo, repo=repo, actor="human"))["derived"]["bosun"])

    def test_the_superuser_does_not_start_until_its_fence_is_decided(self):
        """Its fence was Bosun as its own Unix user, retired in c-648: Start is refused in
        one line, and the readiness row says the same."""
        from keel import readiness
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(Path(tmp))
            cfg.bosun_builder, cfg.builder = True, {"superuser": True}
            with self.assertRaisesRegex(console.ConsoleError, "does not start since c-648"):
                consoletaps.launch(cfg, None)
            row = readiness.builder_row(cfg)
        self.assertEqual((row["ready"], row["why"]), (False, builder.SUPERUSER_UNFENCED))

    def test_a_config_dir_another_user_owns_refuses_the_start(self):
        """c-648: the harness would run that dir's `claude` as its owner through sudo, while
        Bosun's settings and key are this user's. On an install with a repo still to clone,
        the Start is refused before a clone is made or a settings file written, and the
        doctor and the readiness row say why, with builder mode off too."""
        from keel import doctor, readiness
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve() / "install"
            cfg = install_config(home)
            other = home / "other"
            other.mkdir()
            git(other, "init", "-q", "-b", "main")
            git(other, "commit", "-q", "--allow-empty", "-m", "init")
            cfg.spaces["personal"].repos["other"] = other
            cfg.builder = {"repos": ["packs", "other"]}
            self.assertEqual(builder.to_clone(cfg), ["other"], "Start would clone it")
            mine = home / "mine"
            mine.mkdir()
            cfg.spaces["personal"].config_dir = mine
            self.assertIsNone(console.other_owner(cfg), "a directory this user owns")
            with mock.patch.object(console, "owner_of", return_value=FAKE_USER):
                with self.assertRaisesRegex(console.ConsoleError, "belongs to the Unix user bosun"):
                    consoletaps.launch(cfg, None)
                self.assertFalse((home / "builder" / "other").exists(), "no clone was made")
                self.assertFalse(console.settings_path(cfg).exists(), "no settings were written")
                cfg.bosun_builder = False
                row, said = readiness.builder_row(cfg), doctor.bosun_owner(cfg)
            self.assertIsNone(doctor.bosun_owner(cfg))
        self.assertIn("belongs to the Unix user bosun", said)
        self.assertEqual((row["ready"], row["why"]), (False, said))

    def test_bosun_starts_only_with_a_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(Path(tmp))        # builder mode off: nothing else refuses it
            with self.assertRaisesRegex(console.ConsoleError, "no shared key"):
                consoletaps.launch(cfg, None)


OUTCOME = """---
kind: outcome
card: {card}
title: A slice
repo: keel
---
# {card} A slice

Built and green: the slice is on its branch, in `{ref}`.

## Where it stands

- Built.

## What is next

- Its gate.

## Why this shape

- It is small.

## Open questions

- None.

## Evidence

```shell | the suite, green
make test
```

## Risk

Low: one file.
"""


class SuperbuilderLandsTest(unittest.TestCase):
    """His Mac, 2026-10-04: Bosun in bypass built a stack of slices in its clone and could land
    none of them. Its own approval read the branch without fetching it ("read only when the
    user's Approve outcome lands it"), the lint read the outcome at main, where the slice's
    files are not, and Bosun's session could write no review stamp at all. Now the branch is
    fetched for its approval, and ONE review of a stack's top covers every slice under it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve() / "install"
        self.cfg = install_config(self.home)
        self.live = self.home.parent / "keel-live"
        self.live.mkdir()
        git(self.live, "init", "-q", "-b", "main")
        git(self.live, "commit", "-q", "--allow-empty", "-m", "init")
        git(self.live, "branch", "next")
        self.cfg.spaces["personal"].repos["keel"] = self.live
        self.cfg.builder = {"mode": "bypass", "repos": ["packs", "keel"]}
        self.cfg.integration, self.cfg.merge_queue = {"keel": "next"}, True
        builder.ensure_clones(self.cfg)
        self.clone = self.home / "builder" / "keel"
        self.board = Board(self.cfg.db_path, switches=self.cfg.switches, integrated=self.cfg.integrated,
                           builds=builder.repos(self.cfg))
        self.addCleanup(self.board.close)

    def slice(self, branch: str, start: str, name: str) -> str:
        """A commit adding `name` on `branch` in Bosun's clone, and its card at review."""
        git(self.clone, "checkout", "-q", "-b", branch, start)
        (self.clone / name).write_text("one\ntwo\nthree\n")
        git(self.clone, "add", "-A")
        git(self.clone, "commit", "-q", "-m", name)
        card = self.board.create("personal", name, repo="keel", actor=authority.BOSUN, autonomy="autonomous")
        self.board.stage(card, "review", authority.BOSUN, plan_ref="plan.md", output_ref=branch)
        card_dir = self.cfg.cards_dir / card
        card_dir.mkdir(parents=True, exist_ok=True)
        (card_dir / "context.md").write_text(OUTCOME.format(card=card, ref=f"{name}:2"))
        return card

    def review(self, card: str) -> None:
        """Bosun's review of `card` from its clone: prep, then the reviewer finishing clean,
        recorded by its session's own hook (`--bosun`), which finds the card in the prompt."""
        from keel.review import agents, prep, stamp
        card_dir = self.cfg.cards_dir / card
        git(self.clone, "checkout", "-q", self.board.get(card)["output_ref"])
        prep.prepare(card_dir, "next", [self.clone])
        transcript = card_dir.parent / f"agent-{card}.jsonl"
        said = {"type": "user", "message": {"role": "user", "content": f"diff {card_dir}/review.diff"}}
        transcript.write_text(json.dumps(said) + "\n")
        payload = {"agent_type": agents.REVIEWER, "hook_event_name": "SubagentStop",
                   "cwd": str(self.home / "builder"), "session_id": "s",
                   "agent_transcript_path": str(transcript), "last_assistant_message": "[]"}
        found, payload = stamp.bosun_review(self.cfg, payload, self.board)
        self.assertEqual(found, card)
        self.assertIsNotNone(stamp.stamp(self.cfg, found, payload, board=self.board))

    def refusal(self, card: str):
        return authority.outcome_refusal(authority.outcome_facts(self.cfg, self.board.get(card)))

    def test_one_review_of_the_stack_top_lands_every_slice_on_next(self):
        first = self.slice("bosun/s1-a", "origin/next", "a.py")
        second = self.slice("bosun/s2-b", "bosun/s1-a", "b.py")
        self.assertIn("no review stamp covers", self.refusal(first), "fetched and linted: only the review is missing")
        self.assertEqual(git(self.live, "for-each-ref", "--format=%(refname)", "refs/builder"),
                         "refs/builder/bosun/s1-a")
        self.review(second)                               # one pass, at the top of the stack
        self.assertIsNone(self.refusal(second))
        self.assertIsNone(self.refusal(first), "the stack's review covers the slice under it")
        args = types.SimpleNamespace(config=self.cfg, id=first, gate="outcome", checked="suite, review")
        cli.bosun_gate(self.board, args, authority.BOSUN)  # what `kb approve` checks it against
        self.board.approve(first, "outcome", authority.BOSUN, bosun=cli.bosun_gate(self.board, args, authority.BOSUN))
        relay = [e for e in self.board.events(first) if e["kind"] == "relay"][-1]
        self.board.carry(first, relay["id"], "drain")
        main = git(self.live, "rev-parse", "main")
        with mock.patch.object(landing, "finish_house", return_value=None), \
                mock.patch.object(landing, "listed", return_value=None):
            self.assertEqual(landing.land(self.cfg, self.board, self.board.get(first), relay["id"]), 0)
        self.assertEqual(self.board.get(first)["stage"], "done")
        self.assertEqual(git(self.live, "show", "next:a.py").splitlines()[1], "two")
        self.assertEqual(git(self.live, "rev-parse", "main"), main, "main moves only by his deploy")
        self.assertIsNone(self.refusal(second), "still covered once the slice under it landed")

    def landed_under_another(self, branch: str) -> str:
        """`branch`'s code is on `next` by another card's landing, which dropped the fetched
        ref as a landing does: `next`'s head."""
        git(self.live, "fetch", "-q", str(self.clone), f"+refs/heads/{branch}:refs/builder/{branch}")
        git(self.live, "branch", "-f", "next", f"refs/builder/{branch}")
        git(self.live, "update-ref", "-d", f"refs/builder/{branch}")
        return git(self.live, "rev-parse", "next")

    def built_refs(self) -> str:
        return git(self.live, "for-each-ref", "--format=%(refname)", "refs/builder")

    def kb(self, cfg, argv, **rest):
        """`actions.run_kb` without the process: `kb approve` as the user, on this board."""
        self.assertEqual(argv[0], "approve", "the tap asks kb for nothing else")
        self.board.approve(argv[1], argv[2], "human", publish=adapters.publisher(cfg, "personal"))
        return self.board.get(argv[1])

    def test_a_slice_that_landed_under_the_stacks_top_closes_by_the_users_tap(self):     # c-773
        """c-771's code landed inside c-772's landing. The tap on c-771 was routed to the
        landing queue (its branch unread before the fetch) and then refused: "has no branch
        to land". The tap reads the branch as it lands it, finds nothing, and closes."""
        first = self.slice("bosun/s1-a", "origin/next", "a.py")
        landed = self.landed_under_another("bosun/s1-a")
        card = self.board.get(first)
        self.assertFalse(merging.nothing_to_land(self.cfg, card), "unread before the tap: not nothing")
        self.assertEqual(landing.route(self.cfg, card), self.cfg.host, "a read routes it, as before")
        with mock.patch.object(actions, "run_kb", side_effect=self.kb):
            done = actions.act_approve(self.cfg, self.board, {"verb": "approve", "id": first, "gate": "outcome"})
        self.assertEqual(done["stage"], "done")
        self.assertEqual(self.board.get(first)["stage"], "done")
        events = self.board.events(first)
        self.assertEqual([e for e in events if e["kind"] == "relay"], [], "no land relay: it closed in the tap")
        approve = [e for e in events if e["kind"] == "approve"][-1]
        self.assertTrue(approve["text"].startswith(merging.NOTHING_TO_LAND), approve["text"])
        self.assertEqual(git(self.live, "rev-parse", "next"), landed, "nothing merged")
        self.assertEqual(self.built_refs(), "", "the ref the tap fetched goes with the close")
        self.assertTrue(git(self.clone, "rev-parse", "bosun/s1-a"), "Bosun's clone keeps its branch")

    def test_the_close_drops_another_cards_landed_ref_and_a_leftover_worktree(self):     # c-773 F2
        """The branch a card names may be the stack top's, landed by that card: its fetched
        ref goes all the same, with a worktree a house left at the card's path. A ref of
        another card that `next` does not hold is none of this close's."""
        first = self.slice("bosun/s1-a", "origin/next", "a.py")
        second = self.slice("bosun/s2-b", "bosun/s1-a", "b.py")
        apart = self.slice("bosun/s3-c", "origin/next", "c.py")
        landed = self.landed_under_another("bosun/s2-b")
        git(self.live, "fetch", "-q", str(self.clone), "+refs/heads/bosun/s3-c:refs/builder/bosun/s3-c")
        self.board.set_fields(first, {"output_ref": "bosun/s2-b"}, "human")      # one branch for the stack
        tree = repolayout.card_tree(self.cfg, self.board.get(first))
        git(self.live, "worktree", "add", "-q", "-b", f"keel/{first}-house", str(tree))
        closed = self.board.approve(first, "outcome", "human", publish=adapters.publisher(self.cfg, "personal"))
        self.assertEqual(closed["stage"], "done")
        self.assertFalse(tree.exists(), "the house's leftover worktree goes")
        self.assertEqual(self.built_refs(), "refs/builder/bosun/s3-c", "only the ref next holds was dropped")
        self.assertEqual(git(self.live, "rev-parse", "next"), landed)
        self.assertTrue(git(self.live, "rev-parse", f"keel/{first}-house"), "no branch of the live repo is deleted")
        self.assertEqual(self.board.get(second)["stage"], "review")
        self.assertEqual(self.board.get(apart)["stage"], "review")

    def test_with_its_clone_gone_the_close_keeps_the_live_repos_own_branch(self):     # c-773 fix check
        """No clone: the branch read is `refs/heads/<name>` of the live repo itself, not a ref
        the tap fetched, and a nothing-to-land close deletes no branch of the live repo."""
        import shutil
        first = self.slice("bosun/s1-a", "origin/next", "a.py")
        git(self.live, "fetch", "-q", str(self.clone), "+refs/heads/bosun/s1-a:refs/heads/bosun/s1-a")
        git(self.live, "branch", "-f", "next", "bosun/s1-a")
        shutil.rmtree(self.clone)
        closed = self.board.approve(first, "outcome", "human", publish=adapters.publisher(self.cfg, "personal"))
        self.assertEqual(closed["stage"], "done")
        self.assertTrue(git(self.live, "rev-parse", "refs/heads/bosun/s1-a"), "the live repo's branch stays")

    def unread(self, breaks, reason: str) -> None:
        """c-773 F3. Unreadable is not "nothing": the tap routes the card to the landing,
        `kb approve` refuses with the reason, and the card stays at review."""
        first = self.slice("bosun/s1-a", "origin/next", "a.py")
        landed = self.landed_under_another("bosun/s1-a")
        breaks()
        card = self.board.get(first)
        self.assertEqual(landing.route(self.cfg, card, tap=True), self.cfg.host)
        with self.assertRaisesRegex(merging.MergeRefused, reason):
            merging.publish(self.cfg, card)
        with self.assertRaisesRegex(merging.MergeRefused, reason):
            self.board.approve(first, "outcome", "human", publish=adapters.publisher(self.cfg, "personal"))
        self.assertEqual(self.board.get(first)["stage"], "review")
        self.assertEqual(git(self.live, "rev-parse", "next"), landed)

    def test_a_branch_gone_from_the_clone_takes_the_landing_path_and_closes_nothing(self):
        def gone():
            git(self.clone, "checkout", "-q", "--detach")
            git(self.clone, "branch", "-q", "-D", "bosun/s1-a")
        self.unread(gone, "--output <branch>")

    def test_a_clone_that_is_a_link_takes_the_landing_path_and_closes_nothing(self):
        def linked():
            real = self.home / "elsewhere"
            self.clone.rename(real)
            self.clone.symlink_to(real)
        self.unread(linked, "is not a real clone")
        self.assertEqual(self.built_refs(), "", "nothing is fetched from it")

    def test_unrelated_work_and_a_commit_after_the_review_are_not_covered(self):
        first = self.slice("bosun/s1-a", "origin/next", "a.py")
        apart = self.slice("bosun/s3-c", "origin/next", "c.py")
        self.review(first)
        self.assertIn("no review stamp covers", self.refusal(apart), "a branch off next needs its own pass")
        git(self.clone, "checkout", "-q", "bosun/s1-a")
        (self.clone / "late.py").write_text("late\n")
        git(self.clone, "add", "-A")
        git(self.clone, "commit", "-q", "-m", "late")
        self.assertIn("no review stamp covers", self.refusal(first), "a commit after the review")

    def test_in_auto_mode_its_approval_still_reads_nothing_before_the_users_tap(self):
        self.cfg.builder = dict(self.cfg.builder, mode="auto")
        first = self.slice("bosun/s1-a", "origin/next", "a.py")
        facts = authority.outcome_facts(self.cfg, self.board.get(first))
        self.assertIn("read only when the user's Approve outcome", " ".join(facts["errors"]))
        self.assertEqual(git(self.live, "for-each-ref", "refs/builder"), "", "nothing fetched")

    def test_its_session_has_the_review_agents_and_their_hook(self):
        made = console.settings(self.cfg)
        matchers = [group["matcher"] for group in made["hooks"]["SubagentStop"]]
        self.assertEqual(matchers, ["keel-reviewer", "keel-verifier"])
        self.assertIn("keel-review-stamp --bosun", made["hooks"]["SubagentStop"][0]["hooks"][0]["command"])
        launched = {}
        fake = lambda *a, **k: (launched.update(k), {"bg_id": "b", "session_id": "s"})[1]
        with mock.patch.object(harness, "start_bg", fake), mock.patch.object(builder, "refusal", return_value=None):
            consoletaps.launch(self.cfg, None)
        self.assertIn("keel-reviewer", json.loads(launched["agents"]))

    def test_a_review_naming_two_cards_or_another_repos_card_is_not_stamped(self):
        from keel.review import stamp
        first = self.slice("bosun/s1-a", "origin/next", "a.py")
        second = self.slice("bosun/s2-b", "bosun/s1-a", "b.py")
        transcript = self.cfg.cards_dir / "agent.jsonl"
        both = f"{self.cfg.cards_dir}/{first}/review.diff and {self.cfg.cards_dir}/{second}/review.diff"
        transcript.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": both}}) + "\n")
        self.assertIsNone(stamp.bosun_review(self.cfg, {"agent_transcript_path": str(transcript)}, self.board)[0])
        house = self.board.create("personal", "an app", repo="app", actor="human", autonomy="autonomous")
        transcript.write_text(json.dumps({"type": "user", "message": {"role": "user",
                              "content": f"{self.cfg.cards_dir}/{house}/review.diff"}}) + "\n")
        self.assertIsNone(stamp.bosun_review(self.cfg, {"agent_transcript_path": str(transcript)}, self.board)[0])


if __name__ == "__main__":
    unittest.main()
