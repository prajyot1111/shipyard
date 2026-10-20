"""`keel/configedit.py` (c-618): a change to an install's config touches only its own table,
keeps the old file as a backup, and is refused when the file moved since it was read."""

import tempfile
import unittest
from pathlib import Path

from keel import configedit

CONFIG = """# his own words at the top
[keel]
houses_max = 3   # kept, comment and all

[spaces.personal]
config_dir = "claude"

[spaces.personal.repos]
# a repo a card may name
keel = "/code/keel"

# leads into the next table
[tests]
keel = "make test"
"""


class ConfigEditTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / "config.toml"
        self.path.write_text(CONFIG)
        self.path.chmod(0o600)

    def test_adding_a_repo_changes_only_its_table_and_keeps_a_backup(self):
        new = configedit.set_entry(CONFIG, "spaces.personal.repos", "api", "/code/api")
        kept = configedit.write(self.path, CONFIG, new, self.dir / "backups", lambda path: None)
        self.assertEqual(self.path.read_text(),
                         CONFIG.replace('keel = "/code/keel"\n', 'keel = "/code/keel"\napi = "/code/api"\n'))
        self.assertEqual(kept.read_text(), CONFIG)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_a_file_changed_since_it_was_read_is_not_written(self):
        new = configedit.set_entry(CONFIG, "spaces.personal.repos", "api", "/code/api")
        self.path.write_text(CONFIG + "\n# his edit meanwhile\n")
        with self.assertRaises(configedit.EditError):
            configedit.write(self.path, CONFIG, new, self.dir / "backups", lambda path: None)
        self.assertIn("his edit meanwhile", self.path.read_text())
        self.assertFalse((self.dir / "backups").exists())


if __name__ == "__main__":
    unittest.main()
