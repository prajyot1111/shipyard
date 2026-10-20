"""What the keel set leaves out of a card's folder (c-752): its `scratch` folder, whole.

The scope is `keel_find` in `bin/keel-backup`. It is asked here the way a restore asks it:
the real `snapshot` run is made over a scratch install, the snapshot is restored into an
empty directory, and the test reads what came back. The fixture is the slim tests' own
(`tests/backupslimcase.py`): a scratch store, scratch keys and a scratch backup home.
"""

import unittest

from tests.backupslimcase import GPG, SlimCase

CARD = "state/cards/c-9"
# Plain copies of a repo's source, with no `.git` anywhere: what c-512's scratch held.
THROWAWAY = {
    f"{CARD}/scratch/copy-1/src/app.js": b"console.log(1)\n",
    f"{CARD}/scratch/copy-1/package.json": b"{}\n",
    f"{CARD}/scratch/notes.md": b"a house's working notes\n",
}
THE_CARDS_OWN = {
    f"{CARD}/plan.md": b"the plan\n",
    f"{CARD}/out/report.md": b"what the card found\n",
    f"{CARD}/out/scratch/kept.md": b"a deeper folder of that name is the card's own\n",
    # A second card, with a FILE of that name: the rule names a folder, and a file is the card's.
    "state/cards/c-10/scratch": b"a file a card happens to call scratch\n",
}


@unittest.skipUnless(GPG, "gpg is not installed")
class CardScratchTest(SlimCase):
    def restored(self) -> set:
        """Every file a snapshot of the live tree brings back, by relative path."""
        took = self.tool("snapshot")
        self.assertEqual(took.returncode, 0, took.stdout + took.stderr)
        into = self.root / "restored"
        done = self.tool("restore", "--set", "keel", "--into", str(into))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return {str(p.relative_to(into)) for p in into.rglob("*") if p.is_file()}

    def test_a_cards_scratch_folder_is_left_out_whole_and_the_cards_own_files_stay(self):
        self.old_tree(self.live)
        self.write_tree(self.live, THROWAWAY | THE_CARDS_OWN, [f"{CARD}/scratch/empty"])
        back = self.restored()
        self.assertEqual(sorted(back & set(THROWAWAY)), [], "plain files in scratch, no .git anywhere")
        self.assertFalse((self.root / "restored" / CARD / "scratch").exists(), "nor the folder itself")
        self.assertLessEqual(set(THE_CARDS_OWN), back)


if __name__ == "__main__":
    unittest.main()
