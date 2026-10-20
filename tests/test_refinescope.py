"""The capture refine's scope, by mechanism (review item 1) and `kb set --assumed`'s limits
(review item 2).

A refine turn runs with `KEEL_REFINE_CARD=<id>` in its environment. With it set, `kb` refuses
any mutating verb whose target is not that card, and refuses the verbs V11 says a refine may
never run (assign, stage, start, approve, unblock) outright, whatever the card. The words a
capture carries are his, and "block c-other" spoken into the microphone must not become a
block on another card.
"""

import json

from tests.test_cli import KbCase


class RefineScopeTest(KbCase):
    def setUp(self):
        super().setUp()
        self.mine = self.create()
        self.other = self.create()
        self.scope = {"KEEL_REFINE_CARD": self.mine}

    def refused(self, *argv):
        code, _, err = self.kb("--actor", "voice", *argv, env=self.scope)
        self.assertEqual(code, 1, f"{argv} was not refused")
        self.assertIn("refine", err)
        return err

    def test_block_and_unblock_of_another_card_are_refused(self):
        self.refused("block", self.other, "Which account?")
        self.kb("block", self.other, "his own block")
        self.refused("unblock", self.other)
        self.assertEqual(self.kb_json("show", self.other)["blocked_reason"], "his own block")

    def test_an_empty_scope_refuses_everything(self):
        """Round 2: set-and-empty is not "no scope", it is a scope nothing is inside."""
        for argv in (("note", self.mine, "x"), ("show", self.mine)):
            code, _, err = self.kb("--actor", "voice", *argv, env={"KEEL_REFINE_CARD": ""})
            self.assertEqual(code, 1, argv)
            self.assertIn("refine", err)

    def test_links_to_other_cards_are_refused_even_on_its_own(self):
        """Round 2: `set parent=`, `after=` and `from=` reach another card, and `split`
        makes this one a tracking card; Keel's own code creates split children instead."""
        for field in ("parent", "after", "from"):
            self.refused("set", self.mine, f"{field}={self.other}")
        self.refused("split", self.mine, "--slice", "a", "--slice", "b")
        self.refused("create", "--space", "personal", "--title", "x", "--from", self.mine,
                     "--parent", self.other)

    def test_the_card_tree_verbs_are_refused(self):
        """Round 3: main's card tree (c-302). Assigning, the queue and its order are his."""
        self.refused("tree", self.mine)
        self.refused("assign", self.mine)
        self.refused("next", self.mine)
        self.refused("queue")
        self.refused("set", self.mine, "rank=1")

    def test_its_own_card_may_be_tidied_noted_and_blocked(self):
        for argv in (("set", self.mine, "title=Tidy"), ("note", self.mine, "a line"),
                     ("block", self.mine, "Which account?")):
            code, _, err = self.kb("--actor", "voice", *argv, env=self.scope)
            self.assertEqual(code, 0, err)

    def test_the_v11_verbs_are_refused_even_on_its_own_card(self):
        self.kb("--actor", "voice", "block", self.mine, "q", env=self.scope)
        self.refused("unblock", self.mine)
        self.refused("stage", self.mine, "assigned")
        self.refused("approve", self.mine, "plan")
        self.refused("claim", self.mine)

    def test_another_card_cannot_be_set_noted_or_split(self):
        self.refused("set", self.other, "title=moved")
        self.refused("note", self.other, "x")
        self.refused("split", self.other, "--slice", "a", "--slice", "b")

    def test_create_only_as_a_recreate_of_its_own_card(self):
        self.refused("create", "--space", "work", "--title", "loose")
        code, _, err = self.kb("--actor", "voice", "create", "--space", "work", "--title",
                               "moved", "--from", self.mine, env=self.scope)
        self.assertEqual(code, 0, err)

    def test_reads_are_not_scoped(self):
        code, out, err = self.kb("show", self.other, "--json", env=self.scope)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["id"], self.other)


class AssumedLimitTest(KbCase):
    def test_voice_never_overwrites_a_stated_field_with_a_plain_set(self):
        """Round 2, item C: his words are protected from the voice actor too."""
        card = self.create("--repo", "keel")
        code, _, err = self.kb("--actor", "voice", "set", card, "repo=other")
        self.assertEqual(code, 1)
        self.assertIn("stated", err)
        self.assertEqual(self.kb_json("show", card)["repo"], "keel")
        code, _, err = self.kb("--actor", "voice", "set", card, "title=Tidy")
        self.assertEqual(code, 0, err)

    def test_create_assumed_is_the_voice_actors_only(self):
        code, _, err = self.kb("create", "--space", "personal", "--title", "t",
                               "--repo", "keel", "--assumed", "repo")
        self.assertEqual(code, 1)
        self.assertIn("assumed", err)
        code, _, err = self.kb("--actor", "voice", "create", "--space", "personal",
                               "--title", "t", "--repo", "keel", "--assumed", "repo")
        self.assertEqual(code, 0, err)

    def test_a_stated_field_is_never_relabelled_a_guess(self):
        card = self.create("--repo", "keel")
        code, _, err = self.kb("--actor", "voice", "set", card, "repo=other",
                               "--assumed", "repo", env={"KEEL_REFINE_CARD": card})
        self.assertEqual(code, 1)
        self.assertIn("stated", err)
        self.assertEqual(self.kb_json("show", card)["options"]["provenance"]["repo"], "stated")

    def test_only_the_refine_or_the_voice_actor_may_assume(self):
        card = self.create()
        code, _, err = self.kb("set", card, "repo=keel", "--assumed", "repo")
        self.assertEqual(code, 1)
        self.assertIn("assumed", err)
        code, _, err = self.kb("--actor", "voice", "set", card, "repo=keel", "--assumed", "repo")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.kb_json("show", card)["options"]["provenance"]["repo"], "assumed")
