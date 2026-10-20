"""SH-1: the `shipping` stage on the board (lane SHIP, 2026-09-24).

Approve outcome on a work card whose publish says the pull request is ready moves the card
to `shipping`, not `done`: it reaches done when the pull request merges. A card whose
publish says nothing of the kind (a personal merge, a research card, a tracking card)
still goes to done. Only the drain and he move a card into or out of shipping, and out of it
only to done (c-600: its house answers review AT shipping); a house never moves it, and never
writes the watcher's record (`options.shipping`).
"""

import json

from keel.board import SHIPPING_OPTION, Refused
from tests.helpers import BoardCase

READY = {"pr": 12, "url": "https://example.invalid/pr/12", "shipping": True}


class ShippingStageCase(BoardCase):
    def shipping(self) -> str:
        card_id = self.at_review()
        self.board.approve(card_id, "outcome", "human", publish=lambda c: READY)
        return card_id


class ApproveToShippingTest(ShippingStageCase):
    def test_a_publish_that_says_shipping_moves_the_card_to_shipping_not_done(self):
        card_id = self.shipping()
        card = self.board.get(card_id)
        self.assertEqual(card["stage"], "shipping")
        event = self.board.events(card_id)[-1]
        self.assertEqual((event["kind"], event["data"]["to"]), ("approve", "shipping"))
        self.assertEqual(card["options"][SHIPPING_OPTION]["round"], 0)
        self.assertIn("since", card["options"][SHIPPING_OPTION])

    def test_the_answer_may_come_as_the_adapter_s_json_text(self):
        card_id = self.at_review()
        self.board.approve(card_id, "outcome", "human", publish=lambda c: json.dumps(READY))
        self.assertEqual(self.board.get(card_id)["stage"], "shipping")

    def test_a_publish_that_does_not_say_shipping_still_moves_to_done(self):
        for answer in (None, "merged main at abc123", {"published": "nothing", "kind": "research"},
                       json.dumps({"published": "nothing"}), "{not json"):
            card_id = self.at_review()
            self.board.approve(card_id, "outcome", "human", publish=lambda c, a=answer: a)
            self.assertEqual(self.board.get(card_id)["stage"], "done", answer)

    def test_a_card_at_shipping_is_not_at_a_gate_and_does_not_need_him(self):
        card = self.board.get(self.shipping())
        self.assertFalse(card["derived"]["outcome_gate"])
        self.assertFalse(card["derived"]["needs_you"])

    def test_the_approve_begins_the_record_and_keeps_no_state_of_an_old_decline(self):
        card_id = self.at_review()
        self.board.set_fields(card_id, {"options": {SHIPPING_OPTION: {"since": "x", "round": 0, "state": "declined"}}}, "drain")
        self.board.approve(card_id, "outcome", "human", publish=lambda c: READY)
        self.assertNotIn("state", self.board.get(card_id)["options"][SHIPPING_OPTION])


class ShippingMovesTest(ShippingStageCase):
    def test_nothing_reaches_shipping_by_a_plain_stage_move_from_review(self):
        card_id = self.at_review()
        for actor in ("house", "drain", "human", "cli"):
            with self.assertRaisesRegex(Refused, "Approve outcome"):
                self.board.stage(card_id, "shipping", actor)

    def test_the_drain_and_he_move_a_shipping_card_on_and_a_house_does_not(self):
        card_id = self.shipping()
        for actor in ("house", "cli", "hook", "voice"):
            for stage in ("done", "building", "review"):
                with self.assertRaisesRegex(Refused, "shipping"):
                    self.board.stage(card_id, stage, actor)

    def test_nothing_sends_a_shipping_card_back_to_building_or_review(self):
        card_id = self.shipping()
        for actor in ("drain", "human"):
            for stage in ("building", "review"):
                with self.assertRaisesRegex(Refused, "goes on to done"):
                    self.board.stage(card_id, stage, actor)


    def test_he_may_close_a_shipping_card_himself(self):
        card_id = self.shipping()
        self.assertEqual(self.board.stage(card_id, "done", "human")["stage"], "done")

    def test_a_shipping_card_goes_nowhere_but_done(self):
        card_id = self.shipping()
        for stage in ("inbox", "assigned", "planning"):
            with self.assertRaisesRegex(Refused, "shipping"):
                self.board.stage(card_id, stage, "drain")

    def test_the_one_time_sync_may_bring_a_done_card_back_to_shipping(self):
        card_id = self.at_review()
        self.board.approve(card_id, "outcome", "human", publish=lambda c: {"pr": 3})
        self.assertEqual(self.board.get(card_id)["stage"], "done")
        with self.assertRaisesRegex(Refused, "shipping"):
            self.board.stage(card_id, "shipping", "house")
        self.assertEqual(self.board.stage(card_id, "shipping", "drain")["stage"], "shipping")

    def test_a_card_at_shipping_counts_as_finished_for_a_sibling_waiting_on_it(self):
        parent = self.card(title="big")
        first = self.board.create("personal", "first", parent=parent, repo="keel")
        second = self.board.create("personal", "second", parent=parent, repo="keel", after=first)
        self.board.stage(first, "assigned", "human")
        self.board.stage(first, "building", "drain")
        self.board.stage(first, "review", "house", plan_ref="p", output_ref="o")
        self.board.approve(first, "outcome", "human", publish=lambda c: READY)
        self.board.stage(second, "assigned", "human")
        self.assertTrue(self.board.get(second)["derived"]["startable"])


class SyncMoveTest(ShippingStageCase):
    """SH-11: the shipping sync brings a card whose pull requests are all open and ready to
    shipping from done OR from review, with a fresh watcher's record, as the drain's move."""

    def test_review_goes_to_shipping_only_through_the_sync_s_move(self):
        card_id = self.at_review()
        with self.assertRaisesRegex(Refused, "shipping"):
            self.board.stage(card_id, "shipping", "drain")
        card = self.board.ship_from_sync(card_id, "drain", note="its pull requests are ready")
        self.assertEqual(card["stage"], "shipping")
        self.assertEqual(card["options"][SHIPPING_OPTION]["round"], 0)
        self.assertTrue(card["options"][SHIPPING_OPTION]["synced"])
        event = self.board.events(card_id)[-1]
        self.assertEqual((event["kind"], event["actor"], event["text"]),
                         ("stage", "drain", "its pull requests are ready"))
        self.assertTrue(event["data"]["sync"])
        self.assertEqual(event["data"]["from"], "review")

    def test_done_goes_too_and_nothing_else_does(self):
        card_id = self.at_review()
        self.board.approve(card_id, "outcome", "human", publish=lambda c: {"pr": 3})
        self.assertEqual(self.board.ship_from_sync(card_id, "drain", note="n")["stage"], "shipping")
        building = self.card(title="still building")
        self.board.stage(building, "assigned", "human")
        self.board.stage(building, "building", "drain")
        with self.assertRaisesRegex(Refused, "done or review"):
            self.board.ship_from_sync(building, "drain", note="n")

    def test_only_the_drain_or_he_and_never_a_round_at_his_gate(self):
        card_id = self.at_review()
        with self.assertRaisesRegex(Refused, "drain"):
            self.board.ship_from_sync(card_id, "house", note="n")
        self.board.set_fields(card_id, {"options": {SHIPPING_OPTION: {"round": 1, "batch": []}}}, "drain")
        with self.assertRaisesRegex(Refused, "round"):
            self.board.ship_from_sync(card_id, "drain", note="n")
        self.assertEqual(self.board.get(card_id)["stage"], "review")


class ShippingRecordTest(ShippingStageCase):
    def test_only_the_drain_and_he_write_the_watcher_s_record(self):
        card_id = self.shipping()
        for actor in ("house", "cli", "hook", "voice"):
            with self.assertRaisesRegex(Refused, SHIPPING_OPTION):
                self.board.set_fields(card_id, {"options": {SHIPPING_OPTION: {"posted": {"c1": "x"}}}}, actor)

    def test_no_card_is_filed_carrying_the_record(self):
        with self.assertRaisesRegex(Refused, SHIPPING_OPTION):
            self.board.create("work", "sneaky", options={SHIPPING_OPTION: {"round": 3}})
