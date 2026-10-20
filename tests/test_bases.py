"""Which branches work starts from (c-732): a space's bases, asked on How work ships, kept in the
install's config, offered on every space's card form, and read by both drafts. A card that
names a base is cut from it and lands on it in a space with no pack, as a pack's card already
does. On a real scratch install from `shipyard init` with a team remote that has main and
staging; no session is started."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import actions, adapters, bases, cardspec, firstrun, firstrunsteps, flowcards, merging, packdraft, readiness
from keel import config as config_module
from keel.board import open_board
from tests.helpers import no_real_tools
from tests.test_installer import init

ROOT = Path(__file__).resolve().parent.parent


def git(repo: Path, *argv: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@x", *argv],
                          capture_output=True, text=True, check=True).stdout.strip()


def team_remote(where: Path) -> Path:
    """A bare remote with main, and staging one commit ahead of it (STAGING.md)."""
    seed = where / "seed"
    seed.mkdir(parents=True)
    git(seed, "init", "-q", "-b", "main")
    (seed / "README.md").write_text("shop\n")
    git(seed, "add", "README.md")
    git(seed, "commit", "-qm", "first")
    git(seed, "checkout", "-qb", "staging")
    (seed / "STAGING.md").write_text("staging only\n")
    git(seed, "add", "STAGING.md")
    git(seed, "commit", "-qm", "on staging")
    git(seed, "checkout", "-q", "main")
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(where / "remote.git")], check=True)
    return where / "remote.git"


class Install(unittest.TestCase):
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
        self.dir = Path(tmp.name).resolve()
        self.home = self.dir / "install"
        self.assertEqual(init(self.home), 0)

    def cfg(self):
        return config_module.load(self.home / "config.toml", ensure=False)

    def act(self, body):
        cfg = self.cfg()
        with open_board(cfg) as board:
            return actions.act(cfg, board, body)

    def save_bases(self, space, names):
        self.act({"verb": "setup.settings.save",
                  "changes": [{"table": "space", "space": space, "key": "bases", "value": names}]})

    def with_team(self):
        self.act({"verb": "setup.repo.add", "space": "team", "url": str(team_remote(self.dir)), "key": "shop"})
        return self.cfg().spaces["team"].repos["shop"]


class SettingTest(Install):
    def test_the_bases_are_kept_in_the_installs_config(self):
        self.save_bases("personal", ["main", "staging"])
        self.assertEqual(self.cfg().spaces["personal"].bases, ("main", "staging"))
        self.assertIn('bases = ["main", "staging"]', (self.home / "config.toml").read_text())

    def test_a_name_git_cannot_take_is_refused_on_save(self):
        with self.assertRaises(Exception) as raised:
            self.save_bases("personal", ["main", "my staging"])
        self.assertIn("my staging", str(raised.exception))

    def test_one_branch_name_rule_git_s_own(self):
        """r1.F12: `git check-ref-format --branch`, for the setting, at create and at the cut."""
        for name in ("-x", ".hidden", "main~1", "@{-1}"):
            with self.subTest(name=name), self.assertRaises(Exception):
                self.save_bases("personal", ["main", name])
        self.assertIsNone(bases.branch_problem("release/1.2"))

    def test_only_the_bases_list_is_normalised(self):
        """r1.F13: the bases drop blanks and spaces round a name; other lists stay as given."""
        from keel import settings
        found = {setting.key: setting for setting in settings.of("space")}
        self.assertEqual(settings.parse(found["bases"], [" main ", ""]), ("main",))
        self.assertEqual(settings.parse(found["confirm"], [" repo", ""]), (" repo", ""))


class MixedSpaceTest(Install):
    """r2.F4: in a space where only some repos land on an integration branch, the Base branch
    row is for the others only, and the drafts leave the integrated ones out."""

    def setUp(self):
        super().setUp()
        self.act({"verb": "setup.repo.add", "space": "team", "url": str(team_remote(self.dir)), "key": "shop"})
        self.act({"verb": "setup.repo.add", "space": "team", "url": str(self.dir / "remote.git"), "key": "keelish"})
        path = self.home / "config.toml"
        path.write_text(path.read_text().replace("[integration]\n", '[integration]\nkeelish = "next"\n', 1))
        self.save_bases("team", ["main", "release"])

    def test_the_row_is_for_the_repos_without_an_integration_branch(self):
        from keel import deckstate
        cfg = self.cfg()
        row = [r for r in deckstate.options_for(cfg.spaces["team"], cfg) if r["key"] == "base"][0]
        self.assertEqual(row["repos"], ["shop"])

    def test_how_work_ships_offers_bases_for_the_repos_that_take_one(self):
        cfg = self.cfg()
        with open_board(cfg) as board:
            step = [s for s in firstrun.report(cfg, board)["steps"] if s["id"] == "defaults"][0]
        self.assertEqual((step["bases"]["team"]["bases"], step["bases"]["team"]["suggested"],
                          step["bases"]["team"]["integration"]), (["main", "release"], "main", None))

    def test_the_drafts_leave_the_integrated_repos_out(self):
        said = bases.said(self.cfg(), "team")
        self.assertIn("main, release", said)
        self.assertIn("keelish lands on its integration branch", said)


class TypedBaseTest(Install):
    """r1.F12: a base typed on the card form is checked by the same rule at create and at the cut."""

    def test_a_base_git_would_read_as_a_revision_is_refused_at_create(self):
        from keel.board import Refused
        self.with_team()
        cfg = self.cfg()
        with open_board(cfg) as board, self.assertRaises(Refused) as refused:
            board.create("team", "x", repo="shop", options={"base": "main~1"}, actor="human")
        self.assertIn("main~1", str(refused.exception))

    def test_and_at_the_cut(self):
        self.with_team()
        cfg = self.cfg()
        with open_board(cfg) as board:
            card = board.get(board.create("team", "x", repo="shop", actor="human"))
        card = dict(card, options=dict(card["options"], base="staging~1"))      # resolves, as a revision
        with self.assertRaises(adapters.AdapterError) as refused:
            adapters.worktree(cfg, card)
        self.assertIn("staging~1", str(refused.exception))


class FormTest(Install):
    def test_every_space_with_bases_offers_them_as_a_select_with_no_default(self):
        """r1.F5, F7: empty is the repo's own rule, so a card that picks none behaves as before."""
        self.save_bases("personal", ["main", "staging"])
        rows = {row["key"]: row for row in cardspec.sheet(self.cfg().spaces["personal"])}
        self.assertEqual(rows["base"]["type"], "select")
        self.assertEqual(rows["base"]["options"], ["", "main", "staging"])
        self.assertEqual(rows["base"]["default"], "")
        self.assertEqual(rows["base"]["blank"], "the repo's usual branch")
        self.assertEqual(rows["base"]["stored"], "options")

    def test_a_space_that_names_none_has_no_base_row(self):
        rows = {row["key"] for row in cardspec.sheet(self.cfg().spaces["personal"])}
        self.assertNotIn("base", rows)

    def test_a_packs_own_base_field_is_kept_as_it_is(self):
        space = self.cfg().spaces["personal"]
        own = {"key": "base", "label": "Base branch", "type": "select", "stored": "options",
               "options": ["release", "trunk"], "default": "release", "custom": True}
        pack = self.dir / "pack"
        pack.mkdir()
        (pack / "options.json").write_text(__import__("json").dumps([own]))
        space.adapter_dir = pack
        space.bases = ("main",)
        self.assertEqual([row for row in cardspec.sheet(space) if row["key"] == "base"], [own])
        self.assertEqual(bases.of(space), ["release", "trunk"],
                         "the pack's own list is the space's bases for the drafts too")

    def test_a_packs_free_text_field_takes_the_spaces_bases_as_its_choices(self):
        """c-734 (12): the box test's drafted pack declared Base branch as free text, and the
        space's saved bases were not offered. A pack's own select stays as declared (above);
        its free-text field becomes a select of the space's bases that still takes a typed
        branch, keeping the pack's own label, help and placeholder. With no bases saved it is
        kept as the pack declares it, and How work ships asks for the bases."""
        import json
        space = self.cfg().spaces["personal"]
        space.adapter_dir = ROOT / "packs" / "github"
        own = [row for row in json.loads((ROOT / "packs" / "github" / "options.json").read_text()) if row["key"] == "base"]
        self.assertEqual([row for row in cardspec.sheet(space) if row["key"] == "base"], own, "no bases: as declared")
        space.bases = ("main", "release")
        row = [row for row in cardspec.sheet(space) if row["key"] == "base"][0]
        self.assertEqual((row["type"], row["options"], row["typed"], row["default"]), ("select", ["", "main", "release"], True, ""))
        self.assertEqual((row["label"], row["help"], row["stored"], row["blank"]),
                         (own[0]["label"], own[0]["help"], own[0]["stored"], own[0]["placeholder"]))
        found = firstrunsteps.bases_of(self.cfg(), space)
        self.assertFalse(found["pack"], "the page asks for the bases, which the field then offers")
        self.assertEqual(found["bases"], ["main", "release"])

    def test_only_the_spaces_own_row_may_be_typed_into(self):
        """r1.F2: `typed` is the row bases.row makes; a pack's `custom` select keeps its old meaning."""
        self.save_bases("personal", ["main", "release"])
        row = [row for row in cardspec.sheet(self.cfg().spaces["personal"]) if row["key"] == "base"][0]
        self.assertTrue(row["typed"])
        self.assertNotIn("custom", row)


class DraftsTest(Install):
    def test_the_flow_draft_and_the_provider_draft_read_the_same_list(self):
        self.save_bases("personal", ["main", "staging"])
        flow = self.act({"verb": "setup.flow.draft", "space": "personal"})["card"]
        cfg = self.cfg()
        with open_board(cfg) as board:
            flow_brief = board.get(flow)["brief"]
        said = bases.said(cfg, "personal")
        self.assertIn("main, staging", said)
        self.assertIn(said, flow_brief)
        with mock.patch.object(packdraft.builder, "in_app", return_value=True), \
             mock.patch.object(packdraft.builder, "repos", return_value=["packs"]):
            cfg = self.cfg()
            with open_board(cfg) as board:
                card = packdraft.draft_connection(cfg, board, "personal", "We use Gitea.")["card"]
                self.assertIn(said, board.get(card)["brief"])

    def test_the_flow_draft_asks_the_pages_questions_one_at_a_time(self):
        flow = self.act({"verb": "setup.flow.draft", "space": "personal"})["card"]
        cfg = self.cfg()
        with open_board(cfg) as board:
            brief = board.get(flow)["brief"]
        for ask in bases.ASKS:
            self.assertIn(ask["ask"], brief)
        self.assertIn("one question at a time", brief)
        self.assertIn("ask it back", brief)

    def test_how_work_ships_carries_the_asks_and_each_spaces_bases(self):
        self.with_team()
        self.save_bases("team", ["main", "staging"])
        cfg = self.cfg()
        with open_board(cfg) as board:
            step = [s for s in firstrun.report(cfg, board)["steps"] if s["id"] == "defaults"][0]
        self.assertEqual([a["id"] for a in step["asks"]], [a["id"] for a in bases.ASKS])
        self.assertEqual(step["bases"]["team"], {"bases": ["main", "staging"], "suggested": "main", "pack": False,
                                                "listed": False, "integration": None})


class Cards(Install):
    """A card on the team space's shop repo, and its work committed in the worktree it is cut in."""

    def card(self, card_id, base=None):
        cfg = self.cfg()
        with open_board(cfg) as board:
            made = board.create("team", f"Work on {base or 'the default'}", brief="", repo="shop",
                                options={"base": base} if base else {}, actor="human")
            return board.get(made)

    def build(self, card, name):
        tree = adapters.worktree(self.cfg(), card)[0]
        (tree / name).write_text("built\n")
        git(tree, "add", name)
        git(tree, "commit", "-qm", f"the work of {card['id']}")
        return tree


class CutAndLandTest(Cards):
    """The Proof's first part: two bases, a card on each, each cut from and landing on its own."""

    def test_a_card_on_staging_is_cut_from_staging_and_lands_on_it(self):
        repo = self.with_team()
        self.save_bases("team", ["main", "staging"])
        card = self.card("c-1", "staging")
        tree = self.build(card, "on-staging.txt")
        self.assertTrue((tree / "STAGING.md").is_file(), "cut from staging")
        main_before = git(repo, "rev-parse", "main")
        said = merging.publish(self.cfg(), card)
        self.assertIn("merged into staging", said)
        self.assertEqual(git(repo, "rev-parse", "main"), main_before, "main is untouched")
        self.assertIn("on-staging.txt", git(repo, "ls-tree", "--name-only", "staging"))
        self.assertEqual(git(repo, "branch", "--show-current"), "main", "the copy's checkout stays on main")

    def test_the_deck_state_carries_a_base_that_applies(self):
        from keel import deckstate
        self.with_team()
        self.save_bases("team", ["main", "staging"])
        self.assertEqual(deckstate.base_of(self.cfg(), self.card("c-1", "staging")), "staging")

    def test_a_card_on_main_is_cut_from_main_and_lands_on_it(self):
        repo = self.with_team()
        self.save_bases("team", ["main", "staging"])
        card = self.card("c-1", "main")
        tree = self.build(card, "on-main.txt")
        self.assertFalse((tree / "STAGING.md").exists(), "cut from main")
        staging_before = git(repo, "rev-parse", "refs/remotes/origin/staging")
        self.assertIn("merged into main", merging.publish(self.cfg(), card))
        self.assertIn("on-main.txt", git(repo, "ls-tree", "--name-only", "main"))
        self.assertEqual(git(repo, "rev-parse", "refs/remotes/origin/staging"), staging_before)

    def test_the_drafts_say_where_a_card_naming_none_goes(self):
        """r2.F2: no default, so the drafts say the repo's usual branch, not the first base."""
        self.with_team()
        self.save_bases("team", ["main", "staging"])
        said = bases.said(self.cfg(), "team")
        self.assertIn("A card that names none starts from, and lands on, its repo's usual branch", said)
        self.assertNotIn("unless the card names another", said)
        from keel import settings
        help_ = {s.key: s for s in settings.of("space")}["bases"].help
        self.assertIn("its repo's usual branch", help_)
        self.assertNotIn("The first is a new card's", help_)

    def test_a_card_that_names_no_base_is_cut_and_landed_as_before(self):
        repo = self.with_team()
        self.save_bases("team", ["main", "staging"])
        card = self.card("c-1")
        tree = self.build(card, "plain.txt")
        self.assertFalse((tree / "STAGING.md").exists())
        self.assertIn("merged into main", merging.publish(self.cfg(), card))
        self.assertIn("plain.txt", git(repo, "ls-tree", "--name-only", "main"))

    def test_a_base_the_repo_does_not_have_refuses_the_cut_by_name(self):
        """r1.F7: in plain words, naming the branch and the repo."""
        self.with_team()
        card = self.card("c-1", "release")
        with self.assertRaises(adapters.AdapterError) as refused:
            adapters.worktree(self.cfg(), card)
        self.assertTrue(str(refused.exception).startswith("shop has no branch called release"), str(refused.exception))

    def test_an_empty_base_from_the_form_is_the_repos_own_rule(self):
        repo = self.with_team()
        self.save_bases("team", ["main", "staging"])
        card = self.card("c-1", "")
        tree = self.build(card, "plain.txt")
        self.assertFalse((tree / "STAGING.md").exists())
        self.assertIn("merged into main", merging.publish(self.cfg(), card))
        self.assertIn("plain.txt", git(repo, "ls-tree", "--name-only", "main"))


class FetchFirstTest(Cards):
    """r1.F9, F10, F14: fetch before work moves the card's own base up to the remote's, never one
    a working tree has out, and whatever happened to the trunk."""

    def setUp(self):
        super().setUp()
        self.repo = self.with_team()
        git(self.repo, "branch", "staging", "refs/remotes/origin/staging")     # the copy's own branch of the base
        self.seed = self.dir / "seed"

    def remote_moves(self, branch, name):
        """A teammate's commit on the remote's `branch`."""
        git(self.seed, "checkout", "-q", branch)
        (self.seed / name).write_text("theirs\n")
        git(self.seed, "add", name)
        git(self.seed, "commit", "-qm", f"theirs on {branch}")
        git(self.seed, "push", "-q", str(self.dir / "remote.git"), branch)
        git(self.seed, "checkout", "-q", "main")

    def first(self, base="staging"):
        from keel import landpush
        cfg = self.cfg()
        return landpush.fetch_first(cfg, cfg.spaces["team"], "shop", base)

    def test_a_base_strictly_behind_is_moved_up(self):
        self.remote_moves("staging", "late.txt")
        self.assertIsNone(self.first())
        self.assertEqual(git(self.repo, "rev-parse", "staging"), git(self.repo, "rev-parse", "refs/remotes/origin/staging"))
        self.assertIn("late.txt", git(self.repo, "ls-tree", "--name-only", "staging"))

    def test_a_level_base_says_nothing(self):
        self.assertIsNone(self.first())

    def test_a_diverged_base_is_said_and_left(self):
        mine = git(self.repo, "commit-tree", "staging^{tree}", "-p", "staging", "-m", "mine on staging")
        git(self.repo, "branch", "-f", "staging", mine)
        self.remote_moves("staging", "late.txt")
        said = self.first()
        self.assertIn("have each moved", said)
        self.assertEqual(git(self.repo, "rev-parse", "staging"), mine)

    def test_a_base_a_working_tree_has_out_is_never_moved(self):
        """r1.F9: the user's own linked worktree on the base."""
        git(self.repo, "worktree", "add", "-q", str(self.dir / "theirs"), "staging")
        self.remote_moves("staging", "late.txt")
        before = git(self.repo, "rev-parse", "staging")
        said = self.first("staging")
        self.assertIn("staging is checked out in", said)
        self.assertEqual(git(self.repo, "rev-parse", "staging"), before)

    def test_the_base_moves_whatever_happened_to_the_trunk(self):
        """r1.F10: the trunk diverged, the base is still moved, and both are said."""
        (self.repo / "local.txt").write_text("mine\n")
        git(self.repo, "add", "local.txt")
        git(self.repo, "commit", "-qm", "mine on main")
        self.remote_moves("main", "theirs-main.txt")
        self.remote_moves("staging", "late.txt")
        said = self.first("staging")
        self.assertIn("main on this computer", said)
        self.assertEqual(git(self.repo, "rev-parse", "staging"), git(self.repo, "rev-parse", "refs/remotes/origin/staging"))

    def test_a_landing_never_moves_a_base_a_working_tree_has_out(self):
        """r1.F9: refused, and said, rather than moved under the user's working tree."""
        self.save_bases("team", ["main", "staging"])
        card = self.card("c-1", "staging")
        self.build(card, "work.txt")
        git(self.repo, "worktree", "add", "-q", str(self.dir / "theirs"), "staging")
        before = git(self.repo, "rev-parse", "staging")
        with self.assertRaises(merging.MergeRefused) as refused:
            merging.publish(self.cfg(), card)
        self.assertIn("staging is checked out in", str(refused.exception))
        self.assertEqual(git(self.repo, "rev-parse", "staging"), before)


class IntegrationTest(Cards):
    """r1.F4, F5, F8: a repo whose cards land on an integration branch (Keel's `next`) never takes
    a card's own base: it is refused at create and at set, and a card that names one anyway (a
    card written before the refusal, say) is cut and landed by the integration rule."""

    def setUp(self):
        super().setUp()
        self.repo = self.with_team()
        path = self.home / "config.toml"
        path.write_text(path.read_text().replace("[integration]\n", '[integration]\nshop = "next"\n', 1))

    def named(self, base):
        """A card filed with no base, holding `base` in memory as if it had been written so."""
        card = self.card("c-1")
        return dict(card, options=dict(card["options"], base=base))

    def test_a_base_on_an_integration_repo_is_refused_at_create(self):
        from keel.board import Refused
        with self.assertRaises(Refused) as refused:
            self.card("c-1", "main")
        self.assertIn("integration branch", str(refused.exception))

    def test_and_at_set(self):
        from keel.board import Refused
        card = self.card("c-1")
        cfg = self.cfg()
        with open_board(cfg) as board, self.assertRaises(Refused):
            board.set_fields(card["id"], {"options": {"base": "main"}}, "human")

    def test_a_card_naming_a_base_anyway_lands_on_the_integration_branch_with_the_trunk_in(self):
        card = self.named("main")
        self.build(card, "work.txt")
        main_before = git(self.repo, "rev-parse", "main")
        self.assertIn("merged into next", merging.publish(self.cfg(), card))
        self.assertEqual(git(self.repo, "rev-parse", "main"), main_before, "main moves only on a deploy")
        git(self.repo, "merge-base", "--is-ancestor", "main", "next")      # raises when next lacks main

    def test_a_card_naming_the_integration_branch_itself_takes_the_integration_path(self):
        card = self.named("next")
        self.build(card, "work.txt")
        self.assertIn("merged into next", merging.publish(self.cfg(), card), "next is created at the trunk")

    def test_it_is_cut_by_the_integration_rule_not_from_its_base(self):
        tree = adapters.worktree(self.cfg(), self.named("staging"))[0]
        self.assertFalse((tree / "STAGING.md").exists(), "cut from the trunk while next has nothing, never staging")

    def test_bosuns_outcome_facts_name_the_branch_it_lands_on(self):
        from keel import authority
        card = self.named("main")
        self.build(card, "work.txt")
        cfg = self.cfg()
        self.assertEqual(merging.placed(cfg, card)[4], "next")
        # r2.F6: what Bosun pins is this card's own branch head, read where it lands
        branch = git(adapters.worktree(cfg, card)[0], "branch", "--show-current")
        self.assertEqual(authority.outcome_facts(cfg, card)["sha"], git(self.repo, "rev-parse", branch))

    def test_a_slice_naming_a_base_is_refused_as_create_refuses_it(self):
        """r2.F1: a split cannot carry a base onto an integrated repo."""
        from keel.board import Refused
        card = self.card("c-1")
        cfg = self.cfg()
        with open_board(cfg) as board, self.assertRaises(Refused) as refused:
            board.split(card["id"], [{"title": "a slice", "options": {"base": "main"}}], "human")
        self.assertIn("integration branch", str(refused.exception))

    def test_the_stage_check_takes_next_as_the_base_whatever_the_card_holds(self):
        """r2.F1: a card holding base=main is checked against next, where it lands."""
        from keel.board import Refused
        from keel.review import stagecheck
        card = self.named("main")
        tree = self.build(card, "work.txt")
        ahead = git(self.repo, "commit-tree", "main^{tree}", "-p", "main", "-m", "landed on next")
        git(self.repo, "branch", "next", ahead)
        with self.assertRaises(Refused) as refused:
            stagecheck.base_check(card, tree, integration="next", remote="origin")
        self.assertIn("next", str(refused.exception))

    def review_base(self, card, tree):
        """The base `keel check` prepares the review against (`fixcheck.run`)."""
        from keel import fixcheck
        seen = []
        with mock.patch.object(fixcheck, "plan", return_value=("full", "")), \
             mock.patch.object(fixcheck.prep, "prepare", side_effect=lambda dir_, base, *a, **k: seen.append(base) or {"diff": "d"}):
            fixcheck.run(self.cfg(), card, tree)
        return seen

    def test_the_review_diff_is_taken_against_next_whatever_the_card_holds(self):
        """r2.F1: fixcheck reads the card's base by the integration rule."""
        card = self.named("main")
        tree = self.build(card, "work.txt")
        git(self.repo, "branch", "next", "main")
        self.assertEqual(self.review_base(card, tree), ["next"])

    def test_before_next_exists_a_card_naming_no_base_reviews_against_the_stamps_base(self):
        """Fix check 1: a configured integration branch that is not there yet is never the base."""
        card = self.card("c-1")
        tree = self.build(card, "work.txt")
        self.assertEqual(self.review_base(card, tree), ["HEAD"], "no stamp yet: HEAD, as before")

    def test_before_next_exists_a_card_holding_a_base_reviews_against_the_trunk(self):
        card = self.named("staging")
        tree = self.build(card, "work.txt")
        self.assertEqual(self.review_base(card, tree), ["main"])

    def test_before_next_exists_the_stage_check_takes_the_trunk_not_the_option(self):
        """Fix check 2: the caller hands the base that applies, so the raw option is never read.
        Through `kb stage review`'s own checks (`plangate.contract_checks`, c-733), so a plan
        gate that stopped handing the card's base in fails here."""
        args = self.stage_review(*self.staged())
        self.assertFalse(getattr(args, "nothing_to_land", False), "the stage check was not skipped")

    def test_the_same_gate_reading_the_raw_option_is_refused(self):
        """c-733 r1.F5, r2.F5, the control: the same card through the same gate, with the base
        read as the raw option (`staging`), is behind its base. So the gate above reaches the
        base check, and passes it only for the base it hands in."""
        from keel.board import Refused
        staged = self.staged()
        raw = lambda _cfg, card: (card.get("options") or {}).get("base")   # noqa: E731
        with mock.patch.object(merging, "card_base", side_effect=raw), \
             self.assertRaises(Refused) as refused:
            self.stage_review(*staged)
        self.assertIn("is behind its base", str(refused.exception))
        self.assertIn("origin/staging", str(refused.exception))

    def stage_review(self, card, card_dir):
        """`kb stage review`'s checks on a staged card; the args they were handed."""
        import argparse
        from keel import plangate
        args = argparse.Namespace(verb="stage", stage="review", id=card["id"], plan=None)
        plangate.contract_checks(args, lambda: card, card_dir.parent, None, self.cfg())
        return args

    def staged(self):
        """A card holding base=staging, built, prepared and stamped as the review step
        leaves it, with its session started with the pipeline: one the stage check holds."""
        import json
        from keel.review import stamp
        card = self.named("staging")             # origin/staging holds a commit the card lacks
        tree = self.build(card, "work.txt")
        card = dict(card, session_id="s-1", options=dict(card["options"], review_session="s-1", worktree=str(tree)))
        card_dir = self.dir / "cards" / card["id"]
        card_dir.mkdir(parents=True)
        (card_dir / stamp.PREP_FILE).write_text("{}")                 # the review step has run
        (card_dir / stamp.STAMP_FILE).write_text(json.dumps({"heads": {str(tree.resolve()): git(tree, "rev-parse", "HEAD")}, "round": 1}))
        return card, card_dir

    def test_a_resumed_house_is_told_it_merges_into_next(self):
        """r2.F1: the brief of a house started afresh reads the base by the integration rule."""
        from keel import prompts
        card = dict(self.named("main"), stage="building")
        card["options"]["branch"] = "shipyard/c-1-x"
        said = prompts.afresh(card, self.cfg().card_dir(card["id"]), "go on", "s-1", cfg=self.cfg())
        self.assertIn("which merges into `next`", said)

    def test_the_deck_state_carries_the_base_that_applies(self):
        """The deck's move buttons read the base the server says applies, not the option."""
        from keel import deckstate
        self.assertEqual(deckstate.base_of(self.cfg(), self.named("main")), "")

    def test_a_move_for_main_is_not_offered_to_it(self):
        """r2.F1: flows.based reads the card's base by the integration rule where cfg is at hand."""
        from keel import flows
        move = flows.Move(id="early", label="Early", source="card", target="base", by="you", bases=("main",))
        self.assertFalse(flows.based(move, self.named("main"), self.cfg()))
        self.assertTrue(flows.based(move, self.named("main")), "without cfg it reads the option, as before")

    def test_saving_bases_for_a_space_whose_repos_are_all_integrated_is_refused(self):
        """r2.F4"""
        with self.assertRaises(Exception) as refused:
            self.save_bases("team", ["main", "release"])
        self.assertIn("integration branch", str(refused.exception))

    def test_how_work_ships_offers_no_bases_for_it_and_names_where_cards_land(self):
        cfg = self.cfg()
        with open_board(cfg) as board:
            step = [s for s in firstrun.report(cfg, board)["steps"] if s["id"] == "defaults"][0]
        self.assertEqual(step["bases"]["team"], {"bases": [], "suggested": "next", "pack": False, "listed": False,
                                                "integration": "next"})


if __name__ == "__main__":
    unittest.main()
