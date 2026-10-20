"""A card's plan_ref is stored absolute, and an old relative one still reads (c-574).

Seen on c-573: a house staged `--plan state/cards/c-573/plan.md` from the Keel checkout,
the board stored it as typed, and the deck showed the card as having no plan, because
`artifacts.allowed` serves only an absolute path.
"""

import dataclasses
import os
from pathlib import Path
from unittest import mock

from keel import artifacts, config as config_module, deckstate
from keel.board import Board
from tests.helpers import make_config
from tests.test_cli import KbCase


class InDir:
    """Run a block with the process cwd at `path`, as a house's shell would be."""

    def __init__(self, path: Path):
        self.path, self.saved = path, None

    def __enter__(self):
        self.saved = os.getcwd()
        self.path.mkdir(parents=True, exist_ok=True)
        os.chdir(self.path)

    def __exit__(self, *exc):
        os.chdir(self.saved)


class StoredAbsoluteTest(KbCase):
    def setUp(self):
        super().setUp()
        self.card = self.create()
        self.plan = self.dir / "state" / "cards" / self.card / "plan.md"
        self.plan.parent.mkdir(parents=True, exist_ok=True)
        self.plan.write_text("# plan\n")

    def stored(self) -> str:
        return self.kb_json("show", self.card)["plan_ref"]

    def test_a_relative_plan_from_the_checkout_shows_on_the_deck_from_anywhere(self):
        with InDir(self.dir):
            code, _, err = self.kb("stage", self.card, "planning", "--plan", f"state/cards/{self.card}/plan.md")
        self.assertEqual(code, 0, err)
        with InDir(self.dir / "elsewhere"):
            cfg = config_module.load(None, ensure=False)
            card = self.kb_json("show", self.card)
            self.assertIsNotNone(deckstate.links_for(cfg, card)["plan"], card["plan_ref"])
        self.assertEqual(Path(self.stored()), self.plan.resolve())

    def test_a_bare_name_from_another_cwd_is_found_in_the_cards_own_directory(self):
        with InDir(self.dir / "elsewhere"):
            code, _, err = self.kb("stage", self.card, "planning", "--plan", "plan.md")
        self.assertEqual(code, 0, err)
        self.assertEqual(Path(self.stored()), self.plan.resolve())

    def test_the_callers_cwd_wins_over_the_card_directory(self):
        mine = self.dir / "work" / "plan.md"
        mine.parent.mkdir()
        mine.write_text("# mine\n")
        with InDir(mine.parent):
            code, _, err = self.kb("set", self.card, "plan_ref=plan.md")
        self.assertEqual(code, 0, err)
        self.assertEqual(Path(self.stored()), mine.resolve())

    def test_a_relative_ref_that_names_no_file_is_refused_and_nothing_is_stored(self):
        with InDir(self.dir / "elsewhere"):
            code, _, err = self.kb("stage", self.card, "planning", "--plan", "nowhere/other.md")
        self.assertEqual(code, 1)
        self.assertIn("no plan file at nowhere/other.md", err)
        self.assertIsNone(self.stored())

    def test_a_plan_in_the_callers_worktree_is_passed_over_for_the_card_directory(self):
        worktree = self.dir / "state" / "worktrees" / self.card
        worktree.mkdir(parents=True)
        (worktree / "plan.md").write_text("# reaped with the worktree\n")
        with InDir(worktree):
            code, _, err = self.kb("stage", self.card, "planning", "--plan", "plan.md")
        self.assertEqual(code, 0, err)
        self.assertEqual(Path(self.stored()), self.plan.resolve())
        (worktree / "only-here.md").write_text("# nowhere else\n")
        with InDir(worktree):
            code, _, err = self.kb("set", self.card, "plan_ref=only-here.md")
        self.assertEqual(code, 1)
        self.assertIn("outside a worktree", err)

    def test_an_absolute_ref_and_a_url_are_stored_as_given(self):
        for value in ("/somewhere/not/yet/plan.md", "https://example.invalid/plan"):
            code, _, err = self.kb("set", self.card, f"plan_ref={value}")
            self.assertEqual(code, 0, err)
            self.assertEqual(self.stored(), value)


class RelativeRefReadTest(KbCase):
    """A ref stored relative before c-574 resolves against the Keel home, not the cwd."""

    def test_an_old_relative_ref_is_served_read_and_stamped(self):
        cfg = dataclasses.replace(make_config(self.dir), root=self.dir)
        plan = cfg.cards_dir / "c-001" / "plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("# plan\n")
        ref = "state/cards/c-001/plan.md"
        with InDir(self.dir / "elsewhere"):
            self.assertIsNotNone(artifacts.url(cfg, ref))
            self.assertEqual(artifacts.local_path(ref, cfg.root), plan)
            from keel import planroute
            self.assertIsNone(planroute.source(cfg, {"id": "c-001", "plan_ref": ref}, "plan")[3])
            self.assertNotEqual(planroute.plan_stamp(cfg, {"plan_ref": ref}), "0")
            from keel import planfacts
            self.assertEqual(planfacts.paths_of(cfg, {"id": "c-001", "plan_ref": ref})["plan"], plan)
            self.assertEqual(planroute.local_plan(cfg, {"plan_ref": ref}), plan)

    def test_the_installer_keeps_an_old_plan_named_by_a_relative_ref(self):
        from keel import planinstall
        card_dir = self.dir / "state" / "cards" / "c-001"
        card_dir.mkdir(parents=True)
        (card_dir / "plan.md").write_text("# old\n")
        work = {"card": {"plan_ref": "state/cards/c-001/plan.md"}, "card_dir": card_dir}
        with InDir(self.dir / "elsewhere"), mock.patch.object(
                planinstall.config_module, "repo_root", return_value=self.dir):
            self.assertEqual(planinstall.old_of(work, "plan"), card_dir / "plan.md")
