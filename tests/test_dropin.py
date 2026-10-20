"""Drop in (E2, c-443): the one command that puts him in a card's house from the desk.

Probed 2026-09-23 on Claude Code 2.1.280 (`tests/fixtures/harness/README.md`): a turn typed
through `claude attach <id>` lands in the SAME session (same pid, same session id, one
transcript), so a LIVE house gets `attach`, never `--resume`, which on a running session
starts a copy. An exited house is resumed as before. A house on a machine the desk reaches
by ssh (`[hosts.<name>] ssh`) gets the command wrapped for that machine.
"""

import shlex
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import actions, dropin
from keel.board import Board
from tests.helpers import SESSION, FakeHarness, background_row, make_config


class DropinCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.cfg.host = "box"
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        self.fake = FakeHarness()
        for module in (dropin, actions):
            patch = mock.patch.object(module, "harness", self.fake)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(actions.subprocess, "run")      # the `kb note`
        self.kb = patch.start()
        self.kb.return_value = mock.Mock(returncode=0, stdout="null", stderr="")
        self.addCleanup(patch.stop)
        self.card = self.board.create("personal", "an errand", actor="human")
        self.board.stage(self.card, "assigned", "human")
        self.board.stage(self.card, "building", "drain")
        self.config_dir = self.cfg.spaces["personal"].config_dir

    def session(self):
        self.board.set_session(self.card, SESSION, "drain", bg_id=SESSION[:8])

    def facts(self):
        return dropin.facts(self.cfg, self.board.get(self.card))


class CommandShapeTest(DropinCase):
    def test_a_live_house_is_attached_to_never_resumed(self):
        self.session()
        self.fake.rows = [background_row(self.card, SESSION, status="busy")]
        facts = self.facts()
        self.assertEqual(facts["command"],
                         f"CLAUDE_CONFIG_DIR={shlex.quote(str(self.config_dir))} claude attach {SESSION[:8]}")
        self.assertNotIn("--resume", facts["command"])
        self.assertEqual((facts["how"], facts["status"]), ("attach", "busy"))

    def test_an_idle_live_house_is_attached_to_as_well(self):
        self.session()
        self.fake.rows = [background_row(self.card, SESSION, status="idle")]
        self.assertIn(f"attach {SESSION[:8]}", self.facts()["command"])

    def test_an_exited_house_is_resumed_in_its_own_directory(self):
        self.session()
        facts = self.facts()
        cwd = self.cfg.card_dir(self.card)
        self.assertEqual(facts["command"], f"cd {shlex.quote(str(cwd))} && CLAUDE_CONFIG_DIR="
                                           f"{shlex.quote(str(self.config_dir))} claude --resume {SESSION}")
        self.assertEqual(facts["how"], "resume")

    def test_a_card_with_no_session_opens_a_fresh_one_there(self):
        facts = self.facts()
        self.assertTrue(facts["command"].endswith(" claude"))
        self.assertEqual(facts["how"], "new")


class NoWorktreeIsMadeTest(DropinCase):
    def test_an_exited_house_whose_worktree_is_gone_is_refused_and_nothing_is_created(self):
        """Review finding 7: Drop in used `house.placement`, which recreates a worktree."""
        card = self.board.create("personal", "a repo card", repo="keel", actor="human")
        self.board.set_session(card, SESSION, "drain", bg_id=SESSION[:8])
        with self.assertRaises(dropin.NoPlace):
            dropin.facts(self.cfg, self.board.get(card))
        self.assertFalse((self.cfg.worktrees_dir / card).exists())

    def test_a_live_house_is_attached_to_even_with_no_directory_here(self):
        card = self.board.create("personal", "a repo card", repo="keel", actor="human")
        self.board.set_session(card, SESSION, "drain", bg_id=SESSION[:8])
        self.fake.rows = [background_row(card, SESSION, status="busy")]
        self.assertEqual(dropin.facts(self.cfg, self.board.get(card))["how"], "attach")
        self.assertFalse((self.cfg.worktrees_dir / card).exists())


