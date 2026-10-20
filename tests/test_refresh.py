"""What a move of main refreshes, and the stamps the long-lived pieces check (c-538, r-14)."""

import tempfile
import unittest
from pathlib import Path

from keel import memoryroot, refresh
from tests.test_merging import make_repo, sh


class StampTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = make_repo(Path(tmp.name) / "repo")
        (self.repo / "talker" / "memory").mkdir(parents=True)
        (self.repo / "talker" / "memory" / "a.md").write_text("a\n")
        sh(self.repo, "git", "add", ".")
        sh(self.repo, "git", "commit", "-q", "-m", "memory")

    def commit(self, name, text):
        (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / name).write_text(text)
        sh(self.repo, "git", "add", ".")
        sh(self.repo, "git", "commit", "-q", "-m", name)

    def test_a_committed_memory_change_moves_the_memory_stamp_only(self):
        memory = refresh.stamp(self.repo, refresh.MEMORY_PATHS)
        gateway = refresh.stamp(self.repo, refresh.GATEWAY_PATHS)
        self.commit("talker/memory/b.md", "b\n")
        self.assertNotEqual(refresh.stamp(self.repo, refresh.MEMORY_PATHS), memory)
        self.assertEqual(refresh.stamp(self.repo, refresh.GATEWAY_PATHS), gateway)

    def test_an_uncommitted_memory_write_moves_nothing(self):
        """Harbor writes its own memory as it talks; only a commit to main is a change."""
        memory = refresh.stamp(self.repo, refresh.MEMORY_PATHS)
        (self.repo / "talker" / "memory" / "a.md").write_text("Harbor saved this\n")
        self.assertEqual(refresh.stamp(self.repo, refresh.MEMORY_PATHS), memory)

    def test_a_voice_change_moves_the_gateway_stamp(self):
        gateway = refresh.stamp(self.repo, refresh.GATEWAY_PATHS)
        self.commit("voice/harbor_voice/x.py", "x\n")
        self.assertNotEqual(refresh.stamp(self.repo, refresh.GATEWAY_PATHS), gateway)

    def test_the_keel_modules_the_gateway_imports_move_its_stamp_too(self):
        """c-711: the gateway reads which toml to load from `keel/configpath.py` once, at
        import, and builds every child's environment with `keel/childenv.py`; a deploy that
        changes either must restart it, or it and its `kb` would run two versions of a rule."""
        for name in ("keel/configpath.py", "keel/childenv.py"):
            self.assertIn(name, refresh.GATEWAY_PATHS)
            gateway = refresh.stamp(self.repo, refresh.GATEWAY_PATHS)
            self.commit(name, "x\n")
            self.assertNotEqual(refresh.stamp(self.repo, refresh.GATEWAY_PATHS), gateway, name)
            self.assertIn(refresh.GATEWAY, refresh.effects([name]))

    def test_no_checkout_is_unknown(self):
        self.assertIsNone(refresh.stamp(self.repo / "missing", refresh.MEMORY_PATHS))


class InstallMemoryStampTest(unittest.TestCase):
    """c-722: the talker's memory lives in the install's memory repo; its commits move the
    stamp, and the checkout's old copy no longer does."""

    setUp_checkout = StampTest.setUp
    commit = StampTest.commit

    def setUp(self):
        self.setUp_checkout()
        self.install = self.repo.parent / "install"
        self.memory = make_repo(self.install / "memory")
        (self.memory / "talker").mkdir()
        (self.memory / "talker" / "MEMORY.md").write_text("index\n")
        sh(self.memory, "git", "add", ".")
        sh(self.memory, "git", "commit", "-q", "-m", "seeded")

    def test_the_installs_commits_move_it_and_its_own_writes_do_not(self):
        memory = refresh.memory_stamp(self.repo, self.install)
        self.assertIsNotNone(memory)
        self.commit("talker/memory/b.md", "the checkout's old copy\n")
        self.assertEqual(refresh.memory_stamp(self.repo, self.install), memory)
        (self.memory / "talker" / "MEMORY.md").write_text("the talker saved this\n")
        self.assertEqual(refresh.memory_stamp(self.repo, self.install), memory)
        sh(self.memory, "git", "commit", "-qam", "a reviewed change")
        self.assertNotEqual(refresh.memory_stamp(self.repo, self.install), memory)

    def test_the_shipped_rulebook_moves_it_only_while_the_install_has_none_of_its_own(self):
        """c-722 landing B: the rulebook lives beside the memory; an install seeded before it
        shipped reads the code's template, whose commits move the stamp until it has its own."""
        memoryroot.write_seeded(self.install, {"templates/memory/talker/MEMORY.md": "x"})   # init seeded it
        memory = refresh.memory_stamp(self.repo, self.install)
        self.commit("templates/memory/talker/CLAUDE.md", "the shipped rules\n")
        moved = refresh.memory_stamp(self.repo, self.install)
        self.assertNotEqual(moved, memory)
        (self.memory / "talker" / "CLAUDE.md").write_text("the user's own rules\n")
        sh(self.memory, "git", "add", ".")
        sh(self.memory, "git", "commit", "-q", "-m", "own rules")
        own = refresh.memory_stamp(self.repo, self.install)
        self.assertNotEqual(own, moved)
        self.commit("templates/memory/talker/CLAUDE.md", "the shipped rules, again\n")
        self.assertEqual(refresh.memory_stamp(self.repo, self.install), own)

    def test_an_owners_memory_not_seeded_from_the_template_is_not_moved_by_it(self):
        """c-726 r1.F5: the stamp's rulebook half follows `talker.Paths.rules_src`: a memory
        not seeded from the template links no template rulebook, so a template commit rotates
        nothing; a rulebook of its own, even before it is committed, takes the template out."""
        memory = refresh.memory_stamp(self.repo, self.install)
        self.commit("templates/memory/talker/CLAUDE.md", "the shipped rules\n")
        self.assertEqual(refresh.memory_stamp(self.repo, self.install), memory)
        memoryroot.write_seeded(self.install, {"templates/memory/talker/MEMORY.md": "x"})
        seeded = refresh.memory_stamp(self.repo, self.install)
        self.assertNotEqual(seeded, memory)
        (self.memory / "talker" / "CLAUDE.md").write_text("the user's own rules\n")
        # r2.F5: written and not yet committed, the own rulebook is what the talker links
        # (`rules_src` reads the disk), so the template leaves the stamp at once.
        own = refresh.memory_stamp(self.repo, self.install)
        self.assertEqual(own, memory, "the memory alone, the template left out")
        self.commit("templates/memory/talker/CLAUDE.md", "the shipped rules, again\n")
        self.assertEqual(refresh.memory_stamp(self.repo, self.install), own, "a template commit moves nothing")

    def test_the_old_rulebook_in_the_checkout_moves_nothing(self):
        memory = refresh.memory_stamp(self.repo, self.install)
        self.commit("spaces/harbor/.claude/CLAUDE.md", "rules\n")
        self.assertEqual(refresh.memory_stamp(self.repo, self.install), memory)

    def test_an_install_without_memory_reads_the_checkouts(self):
        self.assertEqual(refresh.memory_stamp(self.repo, self.repo.parent / "elsewhere"),
                         refresh.stamp(self.repo, refresh.MEMORY_PATHS))
        self.assertEqual(refresh.memory_stamp(self.repo, None), refresh.stamp(self.repo, refresh.MEMORY_PATHS))


class EffectsTest(unittest.TestCase):
    def test_what_each_path_refreshes(self):
        self.assertEqual(refresh.effects([]), [])
        self.assertEqual(refresh.effects(["keel/drain.py"]), [refresh.ENGINE])
        self.assertEqual(refresh.effects(["voice/harbor_voice/server.py"]),
                         [refresh.ENGINE, refresh.GATEWAY])
        self.assertEqual(refresh.effects(["bin/keel-voice-gateway"]), [refresh.ENGINE, refresh.GATEWAY])
        self.assertEqual(refresh.effects(["templates/memory/talker/CLAUDE.md"]),
                         [refresh.ENGINE, refresh.MEMORY])
        self.assertEqual(refresh.effects(["talker/memory/x.md", "voice/a.py"]),
                         [refresh.ENGINE, refresh.GATEWAY, refresh.MEMORY])

    def test_a_neighbour_of_a_path_is_not_it(self):
        self.assertEqual(refresh.effects(["voicex/a.py", "talker/memoryx.md"]), [refresh.ENGINE])


if __name__ == "__main__":
    unittest.main()
