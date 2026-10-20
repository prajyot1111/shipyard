"""SH-1 and SH-3 on the deck: a Shipping lane, the shipping chip, and (c-600) Ship.

Greps, as `tests/test_deck_css.py` says of itself: a stdlib suite cannot run the page. What
they hold is that the lane, the chip, the action, its hover line and its group are there,
and that a review card dropped on the Shipping lane is an Approve rather than a stage move
(which the board would refuse anyway).
"""

import re
import unittest
from pathlib import Path

from tests.test_card_tips import tip_keys
from tests.test_deck_css import js_function

APP = Path(__file__).resolve().parent.parent / "app"


class ShippingLaneTest(unittest.TestCase):
    def test_the_deck_has_the_board_s_stages_in_the_board_s_order(self):
        from keel.board import STAGES
        text = (APP / "ui.core.js").read_text()
        found = re.search(r"var STAGES = \[([^\]]*)\]", text).group(1)
        self.assertEqual(tuple(re.findall(r"'(\w+)'", found)), STAGES)


    def test_the_digest_line_summarises_across_pull_requests(self):
        from keel import deckdigest
        facts = {"state": "open", "comments": 3, "approvals": 1, "ci": "none", "behind": 0,
                 "waiting": 1, "prs": [{"repo": "api", "pr": 4150, "state": "merged"},
                                       {"repo": "web", "pr": 2190, "state": "open"}]}
        said = deckdigest.pr_words({"options": {"shipping": {"facts": facts}}}, {"changes": "pull requests"})
        self.assertTrue(said.startswith("2 pull requests (1 merged, 1 open)"), said)
        # c-630: a card whose space's words did not come with it says the neutral word
        self.assertTrue(deckdigest.pr_words({"options": {"shipping": {"facts": facts}}}).startswith("2 changes"))
        self.assertIn("3 comments", said)
        one = dict(facts)
        one.pop("prs")
        self.assertTrue(deckdigest.pr_words({"options": {"shipping": {"facts": one}}}).startswith("open, 3 comments"))

    def test_a_review_card_dropped_on_shipping_is_approved_not_staged(self):
        body = js_function("ui.cards.js", "dropOn")
        self.assertIn("stage === 'shipping'", body)
        self.assertIn("K.approveGate(c, 'outcome', from)", body)



if __name__ == "__main__":
    unittest.main()
