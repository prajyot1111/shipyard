"""SH-11: the shipping sync's move travels as `kb stage <id> shipping --sync`, so a sync run
on the machine that holds the work houses moves a card on the board wherever the board is.

Locally the flag is `Board.ship_from_sync` (from done or review, a fresh watcher's record,
the event marked `sync`); over the wire it is one more field of the stage body, which the
deck turns back into the same argv, and `RemoteBoard.ship_from_sync` sends it.
"""


from keel import actions
from keel.board import SHIPPING_OPTION
from tests.test_cli import KbCase


class StageSyncVerbTest(KbCase):
    def at_review(self) -> str:
        code, out, err = self.kb("create", "--space", "work", "--title", "t", "--repo", "api",
                                 "--model", "opus")
        self.assertEqual(code, 0, err)
        card_id = out
        code, _, err = self.kb("--actor", "human", "stage", card_id, "assigned", env={"KEEL_TOKEN": self.token})
        self.assertEqual(code, 0, err)
        self.assertEqual(self.kb("--actor", "drain", "stage", card_id, "building")[0], 0)
        code, _, err = self.kb("--actor", "house", "stage", card_id, "review", "--plan", "/plans/p", "--output", "o")
        self.assertEqual(code, 0, err)
        return card_id

    def test_kb_stage_sync_moves_review_to_shipping_and_a_plain_stage_is_refused(self):
        card_id = self.at_review()
        code, _, err = self.kb("--actor", "drain", "stage", card_id, "shipping")
        self.assertNotEqual(code, 0)
        card = self.kb_json("--actor", "drain", "stage", card_id, "shipping", "--sync", "--note", "ready")
        self.assertEqual(card["stage"], "shipping")
        self.assertTrue(card["options"][SHIPPING_OPTION]["synced"])

    def test_sync_is_only_a_move_to_shipping(self):
        card_id = self.at_review()
        code, _, err = self.kb("--actor", "drain", "stage", card_id, "done", "--sync")
        self.assertNotEqual(code, 0)
        self.assertIn("--sync", err)


class ReofferVerbTest(KbCase):
    """c-651: `kb ship <id> reoffer [--rebase]` is his ask for a card at shipping; anywhere
    else, or from a house, it is refused with the reason."""

    def test_reoffer_is_asked_only_at_shipping_and_never_by_a_house(self):
        card_id = StageSyncVerbTest.at_review(self)
        code, _, err = self.kb("ship", card_id, "reoffer", env={"KEEL_TOKEN": self.token})
        self.assertNotEqual(code, 0)
        self.assertIn("a re-offer is for a card at shipping", err)
        self.kb_json("--actor", "drain", "stage", card_id, "shipping", "--sync", "--note", "ready")
        code, _, err = self.kb("ship", card_id, "reoffer", env={"KEEL_CARD": card_id})
        self.assertNotEqual(code, 0, "a house does not ask for its own batch")
        code, _, err = self.kb("ship", card_id, "--rebase", env={"KEEL_TOKEN": self.token})
        self.assertNotEqual(code, 0, "--rebase without reoffer is not a Ship")
        self.assertIn("--rebase goes with reoffer", err)
        code, _, err = self.kb("ship", card_id, "reoffer", "--anyway", env={"KEEL_TOKEN": self.token})
        self.assertNotEqual(code, 0, "--anyway is Ship's")
        self.assertIn("--anyway is Ship's", err)
        card = self.kb_json("ship", card_id, "reoffer", "--rebase", env={"KEEL_TOKEN": self.token})
        self.assertIs(card["options"]["reoffer"]["rebase"], True)


class ArgvTest(KbCase):
    def test_the_deck_turns_sync_back_into_the_flag(self):
        body = {"verb": "stage", "id": "c-001", "stage": "shipping", "note": "ready", "sync": True}
        self.assertEqual(actions.kb_argv(body), ["stage", "c-001", "shipping", "--note", "ready", "--sync"])

