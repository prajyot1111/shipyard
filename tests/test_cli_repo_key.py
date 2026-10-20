"""`kb create --repo` and `kb set repo=` refuse a key the card's space cannot open (c-509,
2026-09-25): a house set `repo=skills`, a repo nobody had listed, the board
took it, and the card could never cut a worktree. A listed key, a comma list of listed
keys, and a project under the space's projects_dir still pass; clearing the repo passes."""

from tests.test_cli import KbCase


class RepoKeyTest(KbCase):
    def test_create_refuses_an_unknown_key_and_names_the_known_ones(self):
        code, _, err = self.kb("create", "--space", "personal", "--title", "t", "--repo", "nowhere")
        self.assertEqual(code, 1)
        self.assertIn("nowhere", err)
        self.assertIn("keel", err)

    def test_create_takes_a_listed_key(self):
        self.create("--repo", "keel")

    def test_set_refuses_an_unknown_key_and_takes_a_listed_one_or_none(self):
        card = self.create()
        code, _, err = self.kb("set", card, "repo=nowhere")
        self.assertEqual(code, 1)
        self.assertIn("kb repos", err)
        self.assertEqual(self.kb("set", card, "repo=keel")[0], 0)
        self.assertEqual(self.kb("set", card, "repo=")[0], 0)
