"""`keel/configpath.py`: which toml a process reads, and the toml a child or a service is
handed (c-711). Every expected path is written out, not computed the way the code does."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import configpath


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(os.path.realpath(tmp.name))
        self.root = self.dir / "checkout"
        self.root.mkdir()
        (self.root / "keel.toml").write_text("")
        self.install = self.dir / "install"
        self.install.mkdir()
        (self.install / "config.toml").write_text("")


class ConfigPathTest(Case):
    def test_the_roots_own_file_when_nothing_is_named(self):
        self.assertEqual(configpath.config_path(self.root, {}), self.root / "keel.toml")
        (self.root / "config.toml").write_text("")
        self.assertEqual(configpath.config_path(self.root, {}), self.root / "config.toml")

    def test_a_checkout_with_neither_reads_the_shipped_example(self):
        """c-722 landing B: no one's `keel.toml` is tracked any more, so a clone or a worktree
        with no config of its own reads `etc/shipyard.example.toml`, whose state is anchored
        to a home and so is a scratch board, never another checkout's."""
        (self.root / "keel.toml").unlink()
        self.assertEqual(configpath.config_path(self.root, {}), self.root / "etc" / "shipyard.example.toml")
        self.assertIsNone(configpath.named(self.root / "etc" / "shipyard.example.toml", self.root),
                          "the root's own, so never handed to a child")

    def test_the_example_is_refused_outside_a_house_worktree_and_a_test(self):
        """r1.F5: a live checkout whose own config has gone must not run quietly on the
        example's defaults (an unpaused drain on a board of its own). The example is a
        house worktree's (its `.git` is a file, or the house's `KEEL_CARD` is set) and a
        test's (the fence's log variable); anywhere else the load refuses, naming KEEL_CONFIG."""
        from keel import config as config_module
        from tests import fence
        self.assertIn(fence.LOG_VAR, config_module.WORKTREE_MARKS, "the fence's own variable")
        (self.root / "keel.toml").unlink()
        (self.root / "etc").mkdir()
        shutil.copy(Path(config_module.__file__).resolve().parent.parent / "etc" / "shipyard.example.toml",
                    self.root / "etc" / "shipyard.example.toml")
        (self.root / ".git").mkdir()
        bare = {key: value for key, value in os.environ.items()
                if key not in (fence.LOG_VAR, "KEEL_CARD", "KEEL_CONFIG")}
        with mock.patch.dict(os.environ, {**bare, "KEEL_HOME": str(self.root)}, clear=True):
            with self.assertRaisesRegex(config_module.ConfigError, "KEEL_CONFIG"):
                config_module.load(ensure=False)
            with mock.patch.dict(os.environ, {"KEEL_CARD": "c-1"}):
                self.assertTrue(config_module.load(ensure=False).scratch)
            with mock.patch.dict(os.environ, {fence.LOG_VAR: "x"}):
                self.assertTrue(config_module.load(ensure=False).scratch)
            (self.root / ".git").rmdir()
            (self.root / ".git").write_text("gitdir: elsewhere\n")       # a git worktree
            cfg = config_module.load(ensure=False)
        self.assertTrue(cfg.scratch)
        self.assertEqual(Path(cfg.source).resolve(), (self.root / "etc" / "shipyard.example.toml").resolve())

    def test_an_empty_name_reads_as_unset(self):
        """A house's settings empty the variable rather than leave it out (`house.env_for`)."""
        self.assertEqual(configpath.config_path(self.root, {"KEEL_CONFIG": ""}),
                         self.root / "keel.toml")

    def test_a_named_file_wins_over_the_roots_own(self):
        (self.root / "config.toml").write_text("")
        named = str(self.install / "config.toml")
        self.assertEqual(configpath.config_path(self.root, {"KEEL_CONFIG": named}),
                         self.install / "config.toml")

    def test_a_tilde_is_the_home(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.install)}):
            found = configpath.config_path(self.root, {"KEEL_CONFIG": "~/config.toml"})
        self.assertEqual(found, self.install / "config.toml")

    def test_a_relative_name_is_from_where_the_process_stands(self):
        before = os.getcwd()
        self.addCleanup(os.chdir, before)
        os.chdir(self.install)
        self.assertEqual(configpath.config_path(self.root, {"KEEL_CONFIG": "config.toml"}),
                         self.install / "config.toml")

    def test_a_link_to_a_config_is_the_file_it_points_at(self):
        link = self.dir / "link.toml"
        link.symlink_to(self.install / "config.toml")
        self.assertEqual(configpath.config_path(self.root, {"KEEL_CONFIG": str(link)}),
                         self.install / "config.toml")

    def test_the_process_environment_is_the_default(self):
        with mock.patch.dict(os.environ, {"KEEL_CONFIG": str(self.install / "config.toml")}):
            self.assertEqual(configpath.config_path(self.root), self.install / "config.toml")


class NamedTest(Case):
    def test_an_installs_config_is_named(self):
        self.assertEqual(configpath.named(self.install / "config.toml", self.root),
                         str(self.install / "config.toml"))

    def test_the_roots_own_files_are_never_named(self):
        for own in ("keel.toml", "config.toml"):
            self.assertIsNone(configpath.named(self.root / own, self.root), own)

    def test_no_source_and_a_scratch_config_name_nothing(self):
        self.assertIsNone(configpath.named(None, self.root))
        self.assertIsNone(configpath.named(self.install / "config.toml", self.root, scratch=True))

    def test_a_root_reached_through_a_link_still_knows_its_own_file(self):
        """A worktree must keep its scratch board however its path was spelled."""
        link = self.dir / "linked-checkout"
        link.symlink_to(self.root)
        self.assertIsNone(configpath.named(link / "keel.toml", self.root))
        self.assertIsNone(configpath.named(self.root / "keel.toml", link))

    def test_a_named_link_is_handed_over_as_the_file_it_points_at(self):
        link = self.dir / "link.toml"
        link.symlink_to(self.install / "config.toml")
        self.assertEqual(configpath.named(link, self.root), str(self.install / "config.toml"))
