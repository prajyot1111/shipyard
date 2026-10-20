"""trust: a house's cwd recorded as trusted in its space's `.claude.json`, and forgotten when
the directory is gone for good (Claude Code 2.1.281 refuses `--bg` in an untrusted cwd)."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from unittest import mock

from keel import trust

ENTRY = {"allowedTools": [], "mcpServers": {}, "hasTrustDialogAccepted": True}


class TrustCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name).resolve()
        self.config_dir = self.dir / "cfg"
        self.config_dir.mkdir()
        self.file = self.config_dir / ".claude.json"
        self.state = self.dir / "state"
        self.cwd = self.state / "cards" / "c-452"
        self.cwd.mkdir(parents=True)

    def data(self) -> dict:
        return json.loads(self.file.read_text())


class GrantTest(TrustCase):
    def test_a_fresh_config_dir_gets_the_entry(self):
        self.assertTrue(trust.grant(self.config_dir, self.cwd))
        self.assertEqual(self.data()["projects"][str(self.cwd)], ENTRY)
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)

    def test_the_login_and_other_projects_are_kept(self):
        self.file.write_text(json.dumps({"oauthAccount": {"email": "x"},
                                         "projects": {"/elsewhere": {"lastCost": 1}}}))
        trust.grant(self.config_dir, self.cwd)
        data = self.data()
        self.assertEqual(data["oauthAccount"], {"email": "x"})
        self.assertEqual(data["projects"]["/elsewhere"], {"lastCost": 1})

    def test_an_existing_entry_is_merged_not_replaced(self):
        self.file.write_text(json.dumps({"projects": {str(self.cwd): {
            "allowedTools": ["Bash"], "lastCost": 2, "hasTrustDialogAccepted": False}}}))
        self.assertTrue(trust.grant(self.config_dir, self.cwd))
        entry = self.data()["projects"][str(self.cwd)]
        self.assertEqual(entry, {"allowedTools": ["Bash"], "lastCost": 2, "mcpServers": {},
                                 "hasTrustDialogAccepted": True})

    def test_an_already_trusted_cwd_is_not_rewritten(self):
        trust.grant(self.config_dir, self.cwd)
        before = self.file.stat().st_mtime_ns
        self.assertFalse(trust.grant(self.config_dir, self.cwd))
        self.assertEqual(self.file.stat().st_mtime_ns, before)

    def test_a_symlinked_cwd_is_trusted_under_both_spellings(self):
        link = self.dir / "link"
        link.symlink_to(self.state, target_is_directory=True)
        trust.grant(self.config_dir, link / "cards" / "c-452")
        projects = self.data()["projects"]
        self.assertIn(str(link / "cards" / "c-452"), projects)
        self.assertIn(str(self.cwd), projects)

    def test_a_file_that_does_not_parse_is_refused_and_left_alone(self):
        self.file.write_text('{"oauthAccount": ')
        with self.assertRaises(trust.Untrusted) as caught:
            trust.grant(self.config_dir, self.cwd)
        self.assertIn("does not parse", str(caught.exception))
        self.assertIn(str(self.cwd), str(caught.exception))
        self.assertEqual(self.file.read_text(), '{"oauthAccount": ')

    def test_a_projects_value_that_is_not_an_object_is_refused(self):
        self.file.write_text(json.dumps({"projects": []}))
        with self.assertRaises(trust.Untrusted):
            trust.grant(self.config_dir, self.cwd)
        self.assertEqual(self.data(), {"projects": []})


class ForgetTest(TrustCase):
    def test_a_directory_under_the_state_dir_is_forgotten(self):
        self.file.write_text(json.dumps({"projects": {"/elsewhere": ENTRY}}))
        trust.grant(self.config_dir, self.cwd)
        self.assertTrue(trust.forget(self.config_dir, self.cwd, self.state))
        self.assertEqual(self.data()["projects"], {"/elsewhere": ENTRY})

    def test_an_entry_outside_the_state_dir_is_never_removed(self):
        outside = self.dir / "workspace" / "cloud-worktrees" / "x"
        outside.mkdir(parents=True)
        trust.grant(self.config_dir, outside)
        self.assertFalse(trust.forget(self.config_dir, outside, self.state))
        self.assertIn(str(outside), self.data()["projects"])

    def test_the_state_dir_itself_is_not_one_of_its_houses(self):
        trust.grant(self.config_dir, self.state)
        self.assertFalse(trust.forget(self.config_dir, self.state, self.state))

    def test_forgetting_what_is_not_there_writes_nothing(self):
        self.assertFalse(trust.forget(self.config_dir, self.cwd, self.state))
        self.assertFalse(self.file.exists())

    def test_a_file_that_does_not_parse_is_left_alone_and_not_raised(self):
        self.file.write_text("{")
        self.assertFalse(trust.forget(self.config_dir, self.cwd, self.state))
        self.assertEqual(self.file.read_text(), "{")


if __name__ == "__main__":
    unittest.main()


class DefaultConfigDirTest(TrustCase):
    """claude reads `~/.claude.json` when CLAUDE_CONFIG_DIR is unset, which is how Keel
    reaches the default `~/.claude` (`harness.point_env`); only a dir named by the variable
    has its own `<dir>/.claude.json` (c-601, e2e bug 3)."""

    def setUp(self):
        super().setUp()
        self.home = self.dir / "home"
        (self.home / ".claude").mkdir(parents=True)
        patch = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_default_dir_is_trusted_in_the_homes_claude_json(self):
        trust.grant(self.home / ".claude", self.cwd)
        data = json.loads((self.home / ".claude.json").read_text())
        self.assertTrue(data["projects"][str(self.cwd)]["hasTrustDialogAccepted"])
        self.assertFalse((self.home / ".claude" / ".claude.json").exists())
        self.assertTrue(trust.forget("~/.claude", self.cwd, self.state))
        self.assertNotIn(str(self.cwd), json.loads((self.home / ".claude.json").read_text())["projects"])

    def test_a_named_dir_keeps_its_own_file(self):
        self.assertEqual(trust.file_of(self.config_dir), self.config_dir / ".claude.json")
        self.assertEqual(trust.file_of("~/.claude"), self.home / ".claude.json")


class RaceTest(TrustCase):
    def test_the_write_lands_on_the_file_as_it_is_just_before_it(self):
        """A live claude writes `~/.claude.json` too (c-601 review): what it wrote between
        Keel's first read and the write is kept."""
        from keel import claudejson
        real = claudejson.read
        reads = []

        def read(path):
            reads.append(path)
            if len(reads) == 2:      # claude wrote between the two reads
                path.write_text(json.dumps({"numStartups": 7}))
            return real(path)
        with mock.patch.object(claudejson, "read", read):
            self.assertTrue(trust.grant(self.config_dir, self.cwd))
        data = self.data()
        self.assertEqual(data["numStartups"], 7)
        self.assertTrue(data["projects"][str(self.cwd)]["hasTrustDialogAccepted"])
