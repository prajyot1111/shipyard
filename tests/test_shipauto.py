"""c-655: automatic handling at shipping is two switches, both off by default, and his
hand-over is a tap on the card.

His word (2026-10-05): a new review comment and a failing check each go to the card's house
by themselves only where the space, or the card over it, says so. Off, the watcher still
collects them on the card (`options.shipping.untold`), tells nobody, and his hand-over (the
deck's `ship.handover`, which is `kb ship <id> reoffer` as him) gives them to the house.

The stand-ins are `tests/test_shipping.py`'s: its adapter, its harness, its invented pull
request. `ShippingCase` runs with both switches on; here they start off, as shipped.
"""

import os
from datetime import timedelta

from keel import actions, settings, shipauto, shipping, shipreoffer, shipupgrade
from keel import config as config_module
from keel.board import SHIPPING_OPTION, Board, Refused, open_board
from tests.helpers import SESSION, write_toml
from tests.test_shipping import MON_10, ShippingCase, comment, sight

FAILED = {"state": "failed", "name": "unit tests", "url": "https://example.invalid/ci/1",
          "at": MON_10.isoformat()}
LATER = MON_10 + timedelta(minutes=40)        # past the quiet window and its cap


class OffCase(ShippingCase):
    AUTO = False

    def arrive(self, **seen):
        """The baseline look, then what the code host shows at MON_10, seen on the next."""
        self.live()
        self.upkeep(MON_10 - timedelta(minutes=30))
        self.see(sight(**seen))
        shipping.LAST_POLLED.clear()
        return self.upkeep(MON_10)

    def later(self, at=LATER, slots: int = 1) -> dict:
        shipping.LAST_POLLED.clear()
        return self.upkeep(at, slots=slots)

    def handles(self, key: str) -> list[str]:
        return [item["handle"] for item in self.shipped().get(key) or []]

    def woken(self) -> tuple:
        return (getattr(self.fake, "relays", []), self.fake.starts, self.fake.resumes)

    def card_switch(self, kind: str, value) -> None:
        self.board.set_fields(self.card, {"options": {shipauto.KEYS[kind]: value}}, "human")

    def space_on(self, *kinds) -> None:
        for kind in kinds:
            setattr(self.cfg.spaces["work"], shipauto.KEYS[kind], True)

    def turn_ends(self) -> None:
        """The house's turn on the batch it was told ends (its Stop hook)."""
        self.board.record_hook(self.card, "Stop", {"session_id": SESSION})

    def every_prompt(self) -> str:
        """Every batch's words (two told in one second do not sort by age)."""
        return "\n".join(path.read_text() for path in (self.cfg.card_dir(self.card) / "told").iterdir())

    def hand(self) -> dict:
        """What the deck's button and lines count (`derived.ship_handover`)."""
        return self.board.get(self.card)["derived"]["ship_handover"]

    def ask(self) -> None:
        self.board.reoffer(self.card, "human")

    def words(self) -> str:
        """The spoken digest's words for the card, which read what the list's chip reads."""
        from keel import deckdigest
        return deckdigest.pr_words(self.board.get(self.card))


class DefaultTest(OffCase):
    """r1.F6: off is the DEFAULT, read from a config that names neither key."""

    def config(self):
        return config_module.load(write_toml(self.dir))

    def opened(self) -> Board:
        return open_board(self.cfg)

    def test_a_config_that_names_neither_key_tells_nothing_and_the_card_says_off(self):
        work = self.cfg.spaces["work"]
        self.assertIs(settings.default("space", "ship_auto_comments"), False)
        self.assertIs(settings.default("space", "ship_auto_checks"), False)
        self.assertEqual((work.ship_auto_comments, work.ship_auto_checks), (False, False))
        self.arrive(comments=[comment(11, MON_10)], ci=FAILED)
        result = self.later()
        self.assertEqual((result["told"], result["resumed"], self.woken()), ([], [], ([], [], [])))
        self.assertEqual(self.board.get(self.card)["derived"]["ship_auto"],
                         {"comments": {"on": False, "by": "space"}, "checks": {"on": False, "by": "space"}})


class CollectedNotToldTest(OffCase):
    def test_off_collects_every_new_item_and_tells_the_house_nothing(self):
        self.arrive(comments=[comment(11, MON_10)], ci=FAILED,
                    reviews=[{"author": "Bo Example", "state": "changes_requested", "at": MON_10.isoformat()}])
        result = self.later()
        self.assertEqual((result["told"], result["resumed"]), ([], []))
        self.assertEqual(self.woken(), ([], [], []), "no tell, no start, no resume")
        self.assertEqual(sorted(self.handles("untold")), ["c11", "ci", "review-bo-example"])
        self.assertEqual((self.handles("pending"), self.handles("told")), ([], []))
        self.assertIsNone(shipping.shipwatch.due(self.shipped(), LATER), "nothing is ever due")

    def test_a_merge_is_still_seen_with_both_off(self):
        self.arrive(comments=[comment(11, MON_10)])
        self.see(sight(comments=[comment(11, MON_10)], state="merged"))
        self.assertEqual(self.later()["merged"], 1)
        self.assertEqual(self.board.get(self.card)["stage"], "done")

    def test_a_check_that_passes_again_is_taken_back_from_the_untold_items(self):
        self.arrive(ci=FAILED)
        self.assertEqual(self.handles("untold"), ["ci"])
        self.see(sight(ci={"state": "passed"}))
        self.later(MON_10 + timedelta(minutes=3))
        self.assertNotIn("untold", self.shipped())

    def test_one_kind_on_tells_only_that_kind(self):
        self.cfg.spaces["work"].ship_auto_comments = True
        self.arrive(comments=[comment(11, MON_10)], ci=FAILED)
        self.assertEqual(self.later()["told"], [self.card])
        self.assertEqual((self.handles("told"), self.handles("untold")), (["c11"], ["ci"]))
        self.assertNotIn("unit tests failed", self.told_prompt())

    def test_a_kind_turned_on_later_tells_what_waited(self):
        self.arrive(comments=[comment(11, MON_10)], ci=FAILED)
        self.later()
        self.card_switch("comments", True)
        self.assertEqual(self.later(LATER + timedelta(minutes=3))["told"], [self.card])
        self.assertEqual((self.handles("told"), self.handles("untold")), (["c11"], ["ci"]))

    def test_the_card_s_own_switch_beats_its_space_s_both_ways(self):
        self.cfg.spaces["work"].ship_auto_comments = self.cfg.spaces["work"].ship_auto_checks = True
        self.card_switch("comments", False)
        self.arrive(comments=[comment(11, MON_10)])
        self.assertEqual(self.later()["told"], [])
        self.assertEqual(self.handles("untold"), ["c11"])
        self.card_switch("comments", None)          # back to the space's, which is on
        self.assertEqual(self.later(LATER + timedelta(minutes=3))["told"], [self.card])

    def test_a_kind_turned_off_takes_its_waiting_items_out_of_the_batch_at_once(self):
        self.cfg.spaces["work"].ship_auto_comments = True
        self.arrive(comments=[comment(11, MON_10)])
        self.assertEqual(self.handles("pending"), ["c11"])
        self.card_switch("comments", False)
        result = self.upkeep(MON_10 + timedelta(minutes=1))       # no look is due yet
        self.assertEqual((result["polled"], self.handles("pending"), self.handles("untold")), (0, [], ["c11"]))

    def test_only_he_sets_a_card_s_switch_and_only_to_a_bool(self):
        for actor in ("house", "bosun", "drain"):
            with self.assertRaises(Refused):
                self.board.set_fields(self.card, {"options": {shipauto.KEYS["checks"]: True}}, actor)
        with self.assertRaises(Refused):
            self.card_switch("checks", "yes")


class StatefulTest(OffCase):
    """r1.F5: the paths that keep state across passes, through the drain's own pass."""

    def test_a_kind_turned_on_is_looked_at_within_two_minutes_by_its_own_cadence(self):
        self.arrive(comments=[comment(11, MON_10)])
        self.card_switch("comments", True)
        self.assertEqual(self.upkeep(MON_10 + timedelta(minutes=1))["polled"], 0)
        self.assertEqual(self.upkeep(MON_10 + timedelta(minutes=2))["polled"], 1, "3 minutes, but for what waits to be freed")
        self.assertEqual((self.handles("pending"), self.handles("untold")), (["c11"], []))
        self.assertEqual(self.upkeep(MON_10 + timedelta(minutes=5))["told"], [self.card])

    def test_a_hand_over_waiting_for_a_slot_stays_in_the_batch_while_the_kinds_are_off(self):
        self.arrive(comments=[comment(11, MON_10)], ci=FAILED)
        self.ask()
        for minute in (1, 2):
            self.assertEqual(self.upkeep(MON_10 + timedelta(minutes=minute), slots=0)["told"], [])
            self.assertEqual((sorted(self.handles("pending")), self.handles("untold")), (["c11", "ci"], []))
        self.assertEqual(self.upkeep(MON_10 + timedelta(minutes=3), slots=1)["told"], [self.card])
        self.assertEqual(sorted(self.handles("told")), ["c11", "ci"])

    def test_a_check_that_fails_passes_and_fails_again_while_off_waits_once_and_is_never_told(self):
        self.arrive(ci=FAILED)
        self.see(sight(ci={"state": "passed"}))
        self.later(MON_10 + timedelta(minutes=3))
        self.assertEqual(self.handles("untold"), [])
        self.see(sight(ci=dict(FAILED, at=(MON_10 + timedelta(minutes=6)).isoformat())))
        self.later(MON_10 + timedelta(minutes=6))
        self.assertEqual(self.handles("untold"), ["ci"])
        self.assertEqual((self.later()["told"], self.handles("told"), self.woken()), ([], [], ([], [], [])))

    def test_a_comment_edited_after_it_was_judged_is_handed_over_as_new(self):
        first = dict(comment(11, MON_10), updated=MON_10.isoformat())
        self.space_on("comments")
        self.arrive(comments=[first])
        self.assertEqual(self.later()["told"], [self.card])
        self.verdict("c11", "not-valid", reply="No: it is the documented cap.")
        self.turn_ends()
        self.card_switch("comments", False)
        edited = dict(first, text="Then say so in the name.", updated=(LATER + timedelta(minutes=5)).isoformat())
        self.see(sight(comments=[edited]))
        self.later(LATER + timedelta(minutes=6))
        self.assertEqual((self.handles("untold"), self.hand()["comments"]), (["c11"], 1))
        self.ask()
        self.assertEqual(self.later(LATER + timedelta(minutes=7))["told"], [self.card], "not dropped as judged")
        self.assertEqual([(i["handle"], i["batch"]) for i in self.shipped()["told"]], [("c11", 2)])
        self.assertIn("Then say so in the name.", self.every_prompt())

    def test_a_told_check_never_judged_is_counted_and_handed_over_while_it_still_fails(self):
        """r1.F1: the count and the fill agree."""
        self.space_on("checks")
        self.arrive(ci=FAILED)
        self.assertEqual(self.later()["told"], [self.card])
        self.turn_ends()
        self.assertEqual(self.hand()["checks"], 1)
        self.ask()
        self.assertEqual(self.later(LATER + timedelta(minutes=1))["told"], [self.card])
        self.assertEqual([(i["handle"], i["batch"]) for i in self.shipped()["told"]], [("ci", 2)])
        self.assertIn("unit tests failed", self.told_prompt())

    def test_a_told_check_that_passes_again_is_neither_counted_nor_handed_over(self):
        self.space_on("checks")
        self.arrive(ci=FAILED)
        self.later()
        self.turn_ends()
        self.see(sight(ci={"state": "passed"}))
        self.later(LATER + timedelta(minutes=5))
        self.assertEqual(self.hand()["checks"], 0)
        with self.assertRaisesRegex(Refused, shipreoffer.NOTHING):
            self.ask()

    def test_an_untold_review_the_reviewer_withdrew_is_not_told_when_the_kind_is_turned_on(self):
        """r1.F2: what waits untold is held to the code host on every look."""
        asks = {"author": "Bo Example", "state": "changes_requested", "at": MON_10.isoformat()}
        self.arrive(reviews=[asks])
        self.assertEqual((self.handles("untold"), self.hand()["comments"]), (["review-bo-example"], 1))
        self.see(sight(reviews=[dict(asks, state="approved", at=(MON_10 + timedelta(minutes=9)).isoformat())]))
        self.card_switch("comments", True)
        result = self.later()
        self.assertEqual((result["told"], self.woken()), ([], ([], [], [])))
        self.assertEqual((self.handles("untold"), self.handles("pending"), self.hand()["comments"]), ([], [], 0))
        self.assertNotIn("urgent", self.shipped())
        notes = [e["text"] for e in self.board.events(self.card) if e["kind"] == "note" and "review-bo-example" in (e["text"] or "")]
        self.assertEqual(len(notes), 1, "said once, on the card")

    def test_a_told_comment_never_judged_and_gone_from_the_host_is_not_counted(self):
        """r1.D1: the count is what the ask would accept, by one rule."""
        self.space_on("comments")
        self.arrive(comments=[comment(11, MON_10)])
        self.assertEqual(self.later()["told"], [self.card])
        self.turn_ends()
        self.assertEqual(self.hand()["comments"], 1, "told, never judged, still on the host")
        self.see(sight())
        self.later(LATER + timedelta(minutes=5))
        self.assertEqual(self.hand()["comments"], 0, "no button")
        with self.assertRaisesRegex(Refused, shipreoffer.NOTHING):
            self.ask()

    def test_what_a_hand_over_put_back_in_the_batch_is_not_counted_while_it_waits_for_a_slot(self):
        """r1.D4: told, never judged, handed over again, and waiting in the batch."""
        self.space_on("comments")
        self.arrive(comments=[comment(11, MON_10)])
        self.assertEqual(self.later()["told"], [self.card])
        self.turn_ends()
        self.assertEqual(self.hand()["comments"], 1)
        self.ask()
        self.assertEqual(self.later(LATER + timedelta(minutes=1), slots=0)["told"], [], "filled, no slot")
        self.assertEqual(self.handles("pending"), ["c11"])
        hand = self.hand()
        self.assertEqual((hand["comments"], hand["checks"], hand["asked"]), (0, 0, False), "no button, no chip")
        self.assertNotIn("not handed over", self.words())
        with self.assertRaisesRegex(Refused, shipreoffer.NOTHING):
            self.ask()

    def test_a_declined_card_has_nothing_to_hand_over_anywhere(self):
        """r1.D5: it stays at shipping, and the list says no count the page and the verb refuse."""
        self.arrive(comments=[comment(11, MON_10)], ci=FAILED)
        self.assertEqual(self.hand()["comments"], 1)
        self.see(sight(comments=[comment(11, MON_10)], ci=FAILED, state="declined"))
        self.assertEqual(self.later()["declined"], 1)
        self.assertEqual(self.board.get(self.card)["stage"], "shipping")
        self.assertIsNone(self.hand())
        self.assertNotIn("not handed over", self.words())
        with self.assertRaisesRegex(Refused, "declined"):
            self.ask()

    def test_an_untold_comment_deleted_on_the_host_stops_waiting_and_a_tap_is_refused(self):
        self.arrive(comments=[comment(11, MON_10)])
        self.see(sight())
        self.later(MON_10 + timedelta(minutes=12))
        self.assertEqual((self.handles("untold"), self.hand()["comments"]), ([], 0))
        with self.assertRaisesRegex(Refused, shipreoffer.NOTHING):
            self.ask()


class ListTest(OffCase):
    """What the cards list shows: the number the hand-over would give the house
    (`derived.ship_handover`, which the chip and the spoken digest both read), in words
    that are not the batch's "waiting", and nothing once he has asked."""

    def test_the_list_counts_what_the_button_would_hand_over_until_he_asks(self):
        from tests.test_deck_css import js_function
        self.arrive(comments=[comment(11, MON_10), comment(12, MON_10, "And the name?")], ci=FAILED)
        self.assertEqual(self.shipped()["facts"]["waiting"], 0)
        self.assertIn("3 not handed over", self.words())
        self.assertNotIn("waiting", self.words())
        chip = js_function("ui.cards.js", "shipWord")
        self.assertIn("ship_handover", chip, "the chip reads the derived count, as the button does")
        self.assertNotIn("untold", chip)
        self.ask()
        self.assertNotIn("not handed over", self.words(), "handed over, waiting for the drain")

    def test_comments_from_before_the_card_shipped_are_counted_on_the_list_too(self):
        old = MON_10 - timedelta(days=1)
        self.see(sight(comments=[comment(1, old), comment(2, old, "Rename it")]))
        self.upkeep(MON_10 - timedelta(minutes=30))        # the baseline: seen, never told, not untold
        self.assertEqual((self.handles("untold"), self.hand()["comments"]), ([], 2))
        self.assertIn("2 not handed over", self.words())


class KeptTest(OffCase):
    def test_the_untold_items_survive_the_writes_of_the_whole_record(self):
        self.arrive(comments=[comment(11, MON_10)])
        card = self.board.get(self.card)
        old = dict(card, options=dict(card["options"], shipping=dict(self.shipped(), batch=[], round=1)))
        self.assertEqual([i["handle"] for i in shipupgrade.carried(old)["untold"]], ["c11"], "keel-shipping-upgrade")
        self.board.stage(self.card, "done", "human")
        self.board.ship_from_sync(self.card, "drain", note="ready again")
        self.assertEqual(self.handles("untold"), ["c11"], "the sync's fresh record")
        self.later()
        self.assertEqual((self.handles("untold"), self.handles("told")), (["c11"], []), "and the first look after it")


class HandOverTest(OffCase):
    """His tap, through the real `bin/kb` (r1.F4): the deck's `run_kb` runs the command as him,
    with his token, against this test's own config file and board."""

    def config(self):
        return config_module.load(write_toml(self.dir))

    def opened(self) -> Board:
        return open_board(self.cfg)

    def tap(self, **more) -> dict:
        # the fence took KEEL_* out of the environment; the deck names the config itself
        self.assertNotIn("KEEL_CONFIG", os.environ)
        return actions.act(self.cfg, self.board, {"verb": "ship.handover", "id": self.card, **more})

    def refused(self, **more) -> str:
        with self.assertRaises(actions.ActionError) as caught:
            self.tap(**more)
        return str(caught.exception)

    def test_his_tap_hands_the_waiting_comment_and_the_failing_check_to_the_house(self):
        self.arrive(comments=[comment(11, MON_10)], ci=FAILED)
        self.assertEqual(self.tap()["note"], shipauto.HANDED)
        asked = self.board.get(self.card)["options"]["reoffer"]
        self.assertEqual((asked["by"], asked["rebase"]), ("human", False), "kb ran as him, by his token")
        self.assertTrue(self.hand()["asked"])
        self.assertEqual(self.refused(), shipauto.ALREADY)
        self.assertEqual(self.upkeep(MON_10 + timedelta(minutes=1))["told"], [self.card], "told at once")
        self.assertEqual(sorted(self.handles("told")), ["c11", "ci"])
        self.assertNotIn("untold", self.shipped())
        for words in ("Why is the cap 40?", "unit tests failed"):
            self.assertIn(words, self.told_prompt())

    def test_the_base_is_asked_with_the_same_tap(self):
        self.arrive()
        self.assertEqual(self.tap(rebase=True)["note"], shipauto.HANDED_BASE)
        self.assertTrue(self.board.get(self.card)["options"]["reoffer"]["rebase"])

    def test_the_tap_is_his_and_nobody_else_s(self):
        with self.assertRaisesRegex(actions.ActionError, "one machine"):
            actions.act(self.cfg, self.board, {"verb": "ship.handover", "id": self.card, "caller": {"actor": "house"}})
        for actor in ("house", "bosun", "drain"):
            with self.assertRaises(Refused):
                self.board.reoffer(self.card, actor)

    def test_a_tap_with_nothing_to_hand_over_says_so_in_the_deck_s_words(self):
        self.arrive()
        self.assertEqual(self.refused(), shipauto.NOTHING)

    def test_a_tap_while_the_house_is_on_its_batch_says_so_without_the_command_s_name(self):
        self.space_on("comments")
        self.arrive(comments=[comment(11, MON_10)])
        self.assertEqual(self.later()["told"], [self.card])       # its turn on batch 1 has not ended
        self.assertEqual(self.refused(), f"{self.card}: {shipreoffer.still_on(1, 1)}")
        self.assertEqual(self.hand()["busy"], 1)

    def test_the_card_says_what_waits_and_which_kinds_are_on(self):
        self.arrive(comments=[comment(11, MON_10), comment(12, MON_10, "And the name?")], ci=FAILED)
        self.card_switch("checks", True)
        derived = self.board.get(self.card)["derived"]
        self.assertEqual(derived["ship_auto"], {"comments": {"on": False, "by": "space"},
                                                "checks": {"on": True, "by": "card"}})
        hand = derived["ship_handover"]
        self.assertEqual((hand["comments"], hand["checks"], hand["base"], hand["asked"]), (2, 1, False, False))


if __name__ == "__main__":
    import unittest
    unittest.main()
