"""The shipped `keel.toml`, read as the live engine reads it.

`tests/helpers.py` builds a scratch `Config` by hand, so nothing else here ever loads the
real file. These are the facts cutover step 8 turned on, and they are worth a test because
each is one line of TOML away from silently pointing at the old tree again.

The paths in the file are absolute (`~/keel/...`), like `state_dir` and `adapters_dir`
beside them, so a worktree shares the one live segments tree rather than fetching into a
data-less copy of it. That is why nothing here compares against this checkout's own
directory: from a worktree the two are legitimately different.
"""

import dataclasses
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import adapters
from keel import config as config_module
from tests.helpers import make_repo

ROOT = Path(__file__).resolve().parent.parent


class ShippedConfigTest(unittest.TestCase):
    def setUp(self):
        # The shipped example (c-722 landing B): no one's own keel.toml is tracked any more.
        self.cfg = config_module.load(ROOT / "etc" / "shipyard.example.toml", ensure=False)

    def test_segments_dir_is_the_checkouts_own_tree(self):
        """Step 8 flipped it from the old system's tree to `segments/` in the Keel
        checkout, which is the directory beside `state/`."""
        self.assertEqual(self.cfg.segments_dir, self.cfg.state_dir.parent / "segments")

    def test_the_voice_table_carries_all_three_of_the_page_s_defaults(self):
        """The shipped values, read as the engine reads them. Each is one line of TOML
        away from being dropped, and a dropped one is a page default that silently falls
        back to whatever `harbor_voice/config.py` happens to say."""
        self.assertEqual(self.cfg.voice_port, 4390)
        self.assertEqual(self.cfg.voice_space_default, "personal")
        self.assertEqual(self.cfg.voice_mode_default, "capture")
        # V7: his default stays Google, the voice he chose from rendered samples.
        self.assertEqual(self.cfg.voice_engine_default, "google")

    def test_the_segment_roots_collapse_to_one(self):
        """`segment_roots` is the repo's own `segments/` then `segments_dir`. Those are now
        the same tree, and the de-duplication in `Config.segment_roots` is what makes the
        deck look in one place. Read with the root the config names, which is the live
        engine's case; from a worktree `ROOT` is the worktree and they differ on purpose."""
        live = dataclasses.replace(self.cfg, root=self.cfg.segments_dir.parent)
        self.assertEqual(live.segment_roots, [self.cfg.segments_dir.resolve()])

    def test_the_fetch_locks_live_under_state(self):
        """They used to be the old system's ledger directory, which is what made two
        engines locking the same segment safe. Only one engine locks now, and `state/` is
        where everything Keel writes belongs."""
        self.assertEqual(self.cfg.fetch_locks.parent, self.cfg.state_dir)

    def test_every_segment_in_the_tree_is_reachable_from_the_one_root(self):
        """The tree is THIS checkout's `segments/`, not `segments_dir`'s. `keel.toml` says
        `~/keel/segments`, so reading that listed the live checkout while testing a
        worktree's config, and under the suite's throwaway HOME there is nothing there at
        all (tests/fence.py). `segment_dir` reads the disk, so it needs a real tree: the
        shipped config as it would be on a machine whose checkout is this one."""
        live = dataclasses.replace(self.cfg, root=ROOT, segments_dir=ROOT / "segments")
        names = sorted(path.name for path in (ROOT / "segments").iterdir()
                       if path.is_dir() and not path.name.startswith("."))
        for name in names:
            self.assertEqual(live.segment_dir(name), (ROOT / "segments" / name).resolve())
        self.assertIn("voice", names)


class ProjectsDirTest(unittest.TestCase):
    """`projects_dir`: optional, per space, and the one rule that says which names it
    answers to. A space without one can open no project at all."""

    def load(self, body: str) -> config_module.Config:
        path = Path(self.dir) / "keel.toml"
        path.write_text(body)
        return config_module.load(path, ensure=False)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.base = ('[keel]\nstate_dir = "%s/state"\n[spaces.personal]\n'
                     'config_dir = "~/nowhere"\n' % self.dir)

    def test_it_parses_and_expands_the_home_directory(self):
        cfg = self.load(self.base + 'projects_dir = "~/projects"\n')
        self.assertEqual(cfg.spaces["personal"].projects_dir, Path.home() / "projects")

    def test_a_space_without_it_has_none(self):
        self.assertIsNone(self.load(self.base).spaces["personal"].projects_dir)

    def test_a_listed_repo_wins_and_a_plain_name_becomes_a_project(self):
        cfg = self.load(self.base + 'projects_dir = "~/projects"\n'
                        '[spaces.personal.repos]\nkeel = "~/keel"\n')
        space = cfg.spaces["personal"]
        self.assertEqual(space.repo_path("keel"), Path.home() / "keel")
        self.assertEqual(space.repo_path("smoke"), Path.home() / "projects" / "smoke")

    def test_a_name_that_is_not_a_plain_directory_name_answers_to_nothing(self):
        space = self.load(self.base + 'projects_dir = "~/projects"\n').spaces["personal"]
        for name in ("../escape", "a/b", "..", ".hidden", "Name", ""):
            self.assertIsNone(space.repo_path(name), name)

    def test_a_space_with_no_projects_dir_refuses_a_new_project_card(self):
        space = self.load(self.base).spaces["personal"]
        card = {"id": "c-1", "repo": "smoke", "options": {"new_project": True}}
        with self.assertRaises(adapters.AdapterError) as caught:
            adapters.repo_for(space, "smoke", card)
        self.assertIn("no projects directory to open one in", str(caught.exception))

    def test_projects_lists_every_git_repo_directly_under_it(self):
        root = Path(self.dir) / "projects"
        make_repo(root / "one")
        make_repo(root / "two")
        (root / "plain").mkdir()
        space = self.load(self.base + 'projects_dir = "%s"\n' % root).spaces["personal"]
        self.assertEqual(space.projects(), ["one", "two"])

    def test_projects_is_empty_when_the_directory_is_not_there_yet(self):
        space = self.load(self.base + 'projects_dir = "%s/nope"\n' % self.dir).spaces["personal"]
        self.assertEqual(space.projects(), [])


if __name__ == "__main__":
    unittest.main()


class AllowTest(unittest.TestCase):
    """c-769: a space's `allow` list, which only the space's own table may name."""

    def load(self, body: str = "") -> config_module.Config:
        path = self.dir / "keel.toml"
        path.write_text('[keel]\nstate_dir = "%s/state"\n[spaces.personal]\n'
                        'config_dir = "~/nowhere"\n' % self.dir + body)
        with mock.patch.dict(os.environ, {"KEEL_HOME": str(self.dir)}):
            return config_module.load(path, ensure=False)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_a_space_reads_its_allow_list_beside_its_deny_list(self):
        cfg = self.load('deny = ["mcp__one"]\nallow = ["Bash(make check)"]\n')
        space = cfg.spaces["personal"]
        self.assertEqual((space.deny, space.allow, cfg.warnings), (["mcp__one"], ["Bash(make check)"], []))
        self.assertEqual(self.load().spaces["personal"].allow, [])

    def test_anything_but_a_list_of_rules_warns_and_allows_nothing(self):
        for said in ('"Bash(make check)"', '["Bash(make check)", ""]', "[1]"):
            with self.subTest(allow=said):
                cfg = self.load(f"allow = {said}\n")
                self.assertEqual(cfg.spaces["personal"].allow, [])
                self.assertEqual(len(cfg.warnings), 1)

    def test_a_pack_s_space_defaults_never_allow(self):
        pack = self.dir / "packs" / "mine"
        pack.mkdir(parents=True)
        (pack / "pack.toml").write_text('name = "mine"\nversion = "1"\ndescription = "d"\n'
                                        '[space]\nallow = ["Bash(make check)"]\n')
        cfg = self.load('pack = "mine"\n')
        self.assertEqual(cfg.spaces["personal"].allow, [])
        self.assertEqual(len(cfg.warnings), 1)
        self.assertIn("the pack mine's [space] (for [spaces.personal]) allow", cfg.warnings[0])
        own = self.load('pack = "mine"\nallow = ["Bash(make lint)"]\n')
        self.assertEqual(own.spaces["personal"].allow, ["Bash(make lint)"])


class ModelTest(unittest.TestCase):
    """B1 and B2 (the overnight clearance): the house model per space, Keel's own turns in
    `[models]`, and a name nobody knows refused when the file is read rather than at the
    first launch that hands it to `claude`."""

    def load(self, body: str) -> config_module.Config:
        path = Path(self.tmp.name) / "keel.toml"
        path.write_text(body)
        return config_module.load(path, ensure=False)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = ('[keel]\nstate_dir = "%s/state"\n[spaces.personal]\n'
                     'config_dir = "~/nowhere"\n' % self.tmp.name)


    def test_a_space_that_names_no_model_leaves_it_to_keel(self):
        self.assertIsNone(self.load(self.base).spaces["personal"].model)

    def test_an_unknown_space_model_is_warned_about_when_the_file_is_read(self):
        """c-633: a typo never keeps the deck from starting. It is a warning naming the key
        and the value, and the space falls back to its default (Keel's model)."""
        cfg = self.load(self.base + 'model = "opsu"\n')
        self.assertIsNone(cfg.spaces["personal"].model)
        self.assertEqual(len(cfg.warnings), 1)
        self.assertIn("[spaces.personal] model = 'opsu' is not a model", cfg.warnings[0])


    def test_turn_models_default_without_the_table_and_refuse_a_stranger(self):
        self.assertEqual(self.load(self.base).turn_models, {"converse": "opus", "refine": "sonnet"})
        with self.assertRaisesRegex(config_module.ConfigError, "models"):
            self.load(self.base + '[models]\nnarrator = "opus"\n')
        with self.assertRaisesRegex(config_module.ConfigError, "opsu"):
            self.load(self.base + '[models]\nrefine = "opsu"\n')


    def test_a_recurring_card_naming_an_unknown_model_is_refused(self):
        body = (self.base + '[recurring.x]\nevery_days = 1\nspace = "personal"\n'
                'title = "t"\nmodel = "opsu"\n')
        with self.assertRaisesRegex(config_module.ConfigError, "opsu"):
            self.load(body)
