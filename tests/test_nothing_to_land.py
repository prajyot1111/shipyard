"""Approve outcome on a card with nothing to land (r-24): a research card, or one whose branch
adds no commit its target lacks, closes as done with a note, and nothing queues a land
relay, pre-runs the merged tree, merges or runs a suite for it. c-542 was the case: a
findings-only card whose approve queued a land relay and a merged-tree `make test`.
"""

import unittest
from unittest import mock

from keel import actions, adapters, authority, landing, merging
from keel.board import Refused
from tests.test_landing import LandingCase, sh


class NothingToLandCase(LandingCase):
    def research(self, card=None):
        self.board.set_fields(card or self.card, {"options": {"kind": "research"}}, "human")

    def main_head(self) -> str:
        return sh(self.repo, "git", "rev-parse", "main")


class RouteAndPretestTest(NothingToLandCase):
    def test_a_research_card_is_never_queued_or_pre_run(self):
        self.research()
        card = self.board.get(self.card)
        self.assertTrue(merging.nothing_to_land(self.cfg, card))
        self.assertIsNone(landing.route(self.cfg, card))
        self.assertFalse(landing.pre_run_one(self.cfg, self.board))
        self.assertEqual(self.spawned, [])

    def test_a_branch_already_in_its_target_is_never_queued_or_pre_run(self):
        self.merge_by_hand()
        card = self.board.get(self.card)
        self.assertTrue(merging.nothing_to_land(self.cfg, card))
        self.assertIsNone(landing.route(self.cfg, card))
        self.assertFalse(landing.pre_run_one(self.cfg, self.board))

    def test_a_card_with_commits_of_its_own_still_lands_through_the_queue(self):
        card = self.board.get(self.card)
        self.assertFalse(merging.nothing_to_land(self.cfg, card))
        self.assertEqual(landing.route(self.cfg, card), "box")
        self.assertTrue(landing.pre_run_one(self.cfg, self.board))


class TapTest(NothingToLandCase):
    def approve(self):
        publish = adapters.publisher(self.cfg, "personal")
        return self.board.approve(self.card, "outcome", "human", publish=publish)

    def test_the_tap_closes_a_research_card_with_the_note_and_merges_nothing(self):
        self.research()
        before = self.main_head()
        self.cfg.repo_tests["keel"] = "false"        # a suite that ran would refuse
        card = self.approve()
        self.assertEqual(card["stage"], "done")
        self.assertEqual(self.main_head(), before, "nothing merged")
        approve = [e for e in self.board.events(self.card) if e["kind"] == "approve"][-1]
        self.assertTrue(approve["text"].startswith(merging.NOTHING_TO_LAND), approve["text"])
        self.assertEqual(approve["data"]["published"]["published"], "nothing")

    def branches(self) -> list[str]:
        return sh(self.repo, "git", "branch", "--format=%(refname:short)").split()

    def test_a_research_card_gives_up_its_worktree_and_keeps_a_branch_with_commits(self):
        """Review F4: a close with nothing landed cleans up as a landed one does."""
        self.research()
        card = self.approve()
        self.assertFalse((self.cfg.worktrees_dir / self.card).exists())
        self.assertIn(f"keel/{self.card}", self.branches(), "its commits are not in main")
        approve = [e for e in self.board.events(card["id"]) if e["kind"] == "approve"][-1]
        self.assertIn("so it was kept", approve["text"])

    def test_the_tap_closes_a_branch_already_in_its_target(self):
        self.merge_by_hand()
        self.cfg.repo_tests["keel"] = "false"
        self.assertEqual(self.approve()["stage"], "done")
        self.assertFalse((self.cfg.worktrees_dir / self.card).exists())
        self.assertNotIn(f"keel/{self.card}", self.branches(), "main already holds it")

    def test_the_deck_s_approve_asks_kb_to_approve_and_writes_no_relay(self):
        self.research()
        argvs = []
        with mock.patch.object(actions, "run_kb",
                               side_effect=lambda cfg, argv, **kw: argvs.append(argv) or {}), \
                mock.patch.object(actions, "run_keel", return_value=""):
            actions.act(self.cfg, self.board, {"verb": "approve", "id": self.card,
                                               "gate": "outcome"})
        self.assertEqual([argv[0] for argv in argvs], ["approve"])
        self.assertEqual(self.board.get(self.card)["derived"].get("relays") or [], [])


class QueuedBeforeTest(NothingToLandCase):
    def test_a_relay_whose_branch_turned_out_empty_closes_as_done_not_blocked(self):
        relay = self.relay_land()
        self.board.carry(self.card, relay["id"], "drain")
        self.merge_by_hand()
        self.cfg.repo_tests["keel"] = "false"
        self.assertEqual(landing.run(self.cfg, self.board, self.card, relay=relay["id"]), 0)
        card = self.board.get(self.card)
        self.assertEqual(card["stage"], "done")
        self.assertIsNone(card["blocked_reason"])
        notes = [e["text"] for e in self.board.events(self.card) if e["kind"] == "note"]
        self.assertIn(merging.NOTHING_TO_LAND, notes)


class BosunTest(NothingToLandCase):
    def assert_refused_with_no_relay(self):
        card = self.board.get(self.card)
        facts = authority.outcome_facts(self.cfg, card)
        self.assertTrue(any(merging.NOTHING_TO_LAND in error for error in facts["errors"]),
                        facts["errors"])
        self.assertIn("goes to him", authority.outcome_refusal(dict(facts, integration="next",
                                                                     trunk="main")))
        with self.assertRaises(Refused):
            self.board.approve(self.card, "outcome", authority.BOSUN,
                               bosun={"checked": "read it", "to": "box", "facts": facts})
        after = self.board.get(self.card)
        self.assertEqual(after["stage"], "review")
        self.assertEqual(after["derived"].get("relays") or [], [])

    def test_bosun_s_approve_of_a_research_card_is_refused_and_queues_nothing(self):
        self.research()
        self.assert_refused_with_no_relay()


if __name__ == "__main__":
    unittest.main()
