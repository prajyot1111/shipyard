"""The receipt a gate leaves once it is answered (c-537, `keel/receipt.py`).

After Approve on the plan page nothing said what happened, and the buttons came back once
the command went through: an outcome approve leaves the card at review while it lands. The
receipt says who answered and when, from the card's events, and what is happening now, from
the card's own state; `answerable` is what keeps the buttons away after an answer, except
for the one answer that offers Approve again, a refused landing.
"""

import tempfile
import unittest
from pathlib import Path

from keel import actions, authority, landing, merging, planactions, receipt
from keel.board import Board
from tests.helpers import make_config

SHA = "c45247b0c9bf1e72992c26d2ebb949c8348c2ce1"
MERGE = "346cb8b68bad697ed57bc0f06881e8612c980782"


class ReceiptCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = make_config(Path(self.tmp.name), repos={"keel": Path(self.tmp.name) / "repo"})
        self.cfg.merge_queue = True
        self.board = Board(self.cfg.db_path, switches={"merge_queue"})
        self.addCleanup(self.board.close)
        self.card = self.board.create("personal", "a card", autonomy="attended", repo="keel", actor="human")
        self.board.stage(self.card, "assigned", "human")
        self.board.stage(self.card, "planning", "house", plan_ref=str(self.cfg.card_dir(self.card) / "plan.md"))
        self.board.set_fields(self.card, {"session_id": "s-1"}, "house")

    def got(self, doc):
        card = self.board.get(self.card)
        found = receipt.receipt(self.cfg, card, self.board.events(self.card), doc)
        return found, receipt.answerable(card, found, doc or "plan")

    def at_review(self):
        self.board.approve(self.card, "plan", "human")
        self.board.stage(self.card, "review", "house", output_ref="keel/c-1 @ abc")

    def landing(self, **state):
        self.board.set_fields(self.card, {"options": {"landing": state}}, "drain")

    def land_relay(self, actor="human"):
        self.board.relay(self.card, "land", actor, "box", sha=SHA)
        return max(e["id"] for e in self.board.events(self.card) if e["kind"] == "relay")


class PlanGate(ReceiptCase):
    def test_an_open_gate_has_no_receipt_and_takes_an_answer(self):
        found, open_ = self.got("plan")
        self.assertIsNone(found)
        self.assertTrue(open_)

    def test_an_approved_plan_says_who_when_and_that_the_house_builds(self):
        self.board.approve(self.card, "plan", "human")
        found, open_ = self.got("plan")
        self.assertEqual(found["said"], "Approved by you")
        self.assertEqual(found["now"], "house resumed, building")
        self.assertEqual(found["gate"], "plan")
        self.assertFalse(open_)

    def test_an_approve_held_for_a_working_house_says_so_until_it_is_carried(self):
        """c-604: the receipt said "house resumed" while the tap waited for the turn to end."""
        self.board.approve(self.card, "plan", "human", relay={"to": "box", "prompt": "go"})
        found, _ = self.got("plan")
        self.assertEqual(found["now"], "house resumed, building",
                         "c-604 review: a tap on an idle (or remote) house is not said held")
        self.board.relay(self.card, "resume", "human", "box", prompt="go", gate=True, held=True)
        found, _ = self.got("plan")
        self.assertEqual(found["now"], "held until the house's turn ends, then building")
        for relay in self.board.pending_relays(self.card):
            self.board.carry(self.card, relay["id"], "drain")
        found, _ = self.got("plan")
        self.assertEqual(found["now"], "house resumed, building")

    def test_the_page_mark_after_an_approve_is_the_same_answer(self):
        self.board.approve(self.card, "plan", "human")
        approved_at = self.board.events(self.card)[-1]["at"]
        self.board.record_event(self.card, "mark", "human", data={"what": "sent", "doc": "plan", "mode": "approve"})
        found, _ = self.got("plan")
        self.assertEqual((found["mode"], found["at"]), ("approve", approved_at))

    def test_a_send_back_leaves_it_at_planning_but_answered_until_the_house_restages(self):
        self.board.record_event(self.card, "mark", "human", data={"what": "sent", "doc": "plan", "mode": "sendback"})
        found, open_ = self.got("plan")
        self.assertEqual(found["said"], "Sent back by you")
        self.assertEqual(found["now"], "house resumed, revising the plan")
        self.assertFalse(open_)
        self.board.stage(self.card, "planning", "house", plan_ref=str(self.cfg.card_dir(self.card) / "plan.md"))
        found, open_ = self.got("plan")
        self.assertIsNone(found)
        self.assertTrue(open_)

    def test_a_plan_revised_in_place_opens_the_gate_again_when_the_house_ends_its_turn(self):
        """The real Send back flow (`prompts.sendback_plan`): the house revises the file in
        place, moves no stage, and ends its turn; its Stop hook gives him the buttons back."""
        self.board.record_event(self.card, "hook", "hook", data={"hook": "Stop", "session_id": "s-1"})
        self.board.record_event(self.card, "mark", "human", data={"what": "sent", "doc": "plan", "mode": "sendback"})
        self.board.record_event(self.card, "hook", "hook", data={"hook": "Notification", "session_id": "s-1"})
        self.assertFalse(self.got("plan")[1])          # still revising
        self.board.record_event(self.card, "hook", "hook", data={"hook": "Stop", "session_id": "s-1"})
        found, open_ = self.got("plan")
        self.assertIsNone(found)
        self.assertTrue(open_)

    def test_a_superseded_session_s_stop_does_not_reopen_it_but_a_session_end_does(self):
        self.board.record_event(self.card, "mark", "human", data={"what": "sent", "doc": "plan", "mode": "sendback"})
        self.board.record_event(self.card, "hook", "hook", data={"hook": "Stop", "session_id": "the-old-one"})
        self.assertFalse(self.got("plan")[1])
        self.board.record_event(self.card, "hook", "hook", data={"hook": "SessionEnd", "session_id": "s-1"})
        self.assertTrue(self.got("plan")[1])

    def test_the_plan_page_shows_what_followed_once_the_outcome_is_answered(self):
        self.at_review()
        relay = self.land_relay()
        self.board.carry(self.card, relay, "drain")
        self.landing(state="testing", host="box", relay=relay, pid=1)
        found, _ = self.got("plan")
        self.assertEqual((found["gate"], found["now"], found["link"]),
                         ("plan", "landing, testing the merged tree on box", "outcome"))

    def test_with_no_house_session_it_does_not_say_resumed(self):
        self.board.set_fields(self.card, {"session_id": None}, "house")
        self.board.approve(self.card, "plan", "human")
        self.assertEqual(self.got("plan")[0]["now"], "building, with no house session to resume")

    def test_a_blocked_build_says_so(self):
        self.board.approve(self.card, "plan", "human")
        self.board.block(self.card, "needs a key\nmore", "house")
        found, _ = self.got("plan")
        self.assertEqual((found["now"], found["tone"]), ("blocked: needs a key", "warn"))

    def test_the_outcome_page_does_not_take_the_plan_s_answer(self):
        self.board.approve(self.card, "plan", "human")
        found, open_ = self.got("outcome")
        self.assertIsNone(found)
        self.assertFalse(open_)       # no outcome gate open either

    def test_a_voice_and_a_bosun_answer_are_named(self):
        self.board.record_event(self.card, "approve", "voice", data={"gate": "plan"})
        self.assertEqual(self.got("plan")[0]["said"], "Approved by you, by voice")
        self.board.record_event(self.card, "approve", "bosun", data={"gate": "plan"})
        self.assertEqual(self.got("plan")[0]["said"], "Approved by Bosun")


class OutcomeGate(ReceiptCase):
    def test_at_review_with_no_answer_it_is_open(self):
        self.at_review()
        found, open_ = self.got("outcome")
        self.assertIsNone(found)
        self.assertTrue(open_)

    def test_a_queued_approve_is_landing_and_closed(self):
        self.at_review()
        self.land_relay()
        found, open_ = self.got("outcome")
        self.assertEqual(found["said"], "Approved by you")
        self.assertEqual(found["now"], "landing, queued for box")
        self.assertFalse(open_)

    def test_a_running_landing_names_its_machine(self):
        self.at_review()
        relay = self.land_relay()
        self.board.carry(self.card, relay, "drain")
        self.landing(state="testing", host="box", relay=relay, pid=1)
        found, open_ = self.got("outcome")
        self.assertEqual(found["now"], "landing, testing the merged tree on box")
        self.assertFalse(open_)

    def test_landed_on_the_integration_branch_goes_live_with_the_next_deploy(self):
        self.cfg.integration = {"keel": "next"}
        self.at_review()
        relay = self.land_relay()
        self.board.carry(self.card, relay, "drain")
        self.landing(state="landed", host="box", relay=relay, sha=SHA, merge=MERGE,
                     published="346cb8b merged into next")
        self.board.land(self.card, relay, "drain", published="346cb8b merged into next", merge_queue=True,
                        verify=lambda found, sha: None)
        found, open_ = self.got("outcome")
        self.assertEqual(found["now"], "landed on next at 346cb8b, goes live with the next deploy")
        self.assertEqual(found["tone"], "good")
        self.assertEqual(found["said"], "Approved by you")      # the drain's approve is not the answer
        self.assertFalse(open_)

    def test_a_refused_landing_names_the_failures_links_the_log_and_offers_approve_again(self):
        self.at_review()
        relay = self.land_relay()
        self.board.carry(self.card, relay, "drain")
        log = self.cfg.card_dir(self.card) / receipt.SUITE_LOG
        log.write_text("FAIL: test_x\n")
        why = f"tests failed on the merged tree; failed: tests.test_x; the whole output is in {log}"
        self.landing(state="refused", relay=relay, why=why)
        self.board.block(self.card, receipt.NOT_MERGED + why, "drain")
        found, open_ = self.got("outcome")
        self.assertEqual(found["now"], "refused: tests failed on the merged tree; failed: tests.test_x")
        self.assertEqual(found["tone"], "crit")
        self.assertTrue(found["log"].startswith("/api/artifact/"), found["log"])
        self.assertTrue(found["again"])
        self.assertTrue(open_)
        self.assertEqual(receipt.refused_block(self.board.get(self.card)), receipt.NOT_MERGED + why)

    def test_a_refusal_that_ran_no_suite_links_no_older_log(self):
        self.at_review()
        relay = self.land_relay()
        (self.cfg.card_dir(self.card) / receipt.SUITE_LOG).write_text("old run\n")
        self.landing(state="refused", relay=relay, why="the card's house is working")
        self.board.block(self.card, receipt.NOT_MERGED + "the card's house is working", "drain")
        found, _ = self.got("outcome")
        self.assertIsNone(found["log"])

    def test_a_second_approve_after_a_refusal_is_landing_again_not_refused(self):
        self.at_review()
        first = self.land_relay()
        self.board.carry(self.card, first, "drain")
        self.landing(state="refused", relay=first, why="red")
        self.land_relay()
        found, open_ = self.got("outcome")
        self.assertEqual(found["now"], "landing, queued for box")
        self.assertFalse(open_)

    def test_bosun_s_checked_approval_is_named_as_bosun_s(self):
        self.at_review()
        self.board.record_event(self.card, "relay", "bosun", text="land", data={"what": "land", "to": "box"})
        self.assertEqual(self.got("outcome")[0]["said"], "Approved by Bosun")

    def test_a_send_back_from_the_deck_is_his_move_back_to_building(self):
        self.at_review()
        self.board.stage(self.card, "building", "human", note="sent back from the deck")
        found, _ = self.got("outcome")
        self.assertEqual((found["said"], found["now"]), ("Sent back by you", "house resumed, revising the work"))

    def test_the_tap_s_merge_conflict_move_is_not_a_send_back(self):
        """`actions.merge_conflict` moves the card to building as the deck after an approve
        whose merge conflicted: he approved, he did not send it back."""
        self.at_review()
        self.board.stage(self.card, "building", "human", note="next moved; the house merges it first")
        self.assertIsNone(self.got("outcome")[0])

    def test_a_conflict_on_a_card_bosun_builds_waits_on_bosun_by_name(self):
        """c-647: the line is Bosun's, with the branch as it was staged; no house is in it."""
        self.board.close()
        self.board = Board(self.cfg.db_path, switches={"merge_queue", authority.BUILDER}, builds=["keel"])
        self.addCleanup(self.board.close)
        self.at_review()
        relay = self.land_relay()
        why = merging.CONFLICT.format(target="next", branch="refs/builder/bosun/c-1-x")
        landing.refused_here(self.cfg, self.board, self.board.get(self.card), why, relay)
        now = self.got("outcome")[0]["now"]
        self.assertEqual(now, "refused: merge conflict: next moved past bosun/c-1-x and the two disagree; "
                              "waiting for Bosun to merge next into bosun/c-1-x and stage review again")
        self.assertNotIn("house", now)

    def test_a_land_relay_a_drain_superseded_is_no_answer(self):
        self.at_review()
        relay = self.land_relay()
        self.board.carry(self.card, relay, "drain", outcome="superseded", why="switched off")
        found, open_ = self.got("outcome")
        self.assertIsNone(found)
        self.assertTrue(open_)

    def test_the_tap_s_own_landing_says_where_it_landed(self):
        self.cfg.integration = {"keel": "next"}
        self.at_review()
        self.board.record_event(self.card, "approve", "human",
                                data={"gate": "outcome", "published": "8ecbea2 merged into next"})
        self.board.conn.execute("UPDATE cards SET stage = 'done' WHERE id = ?", (self.card,))
        found, _ = self.got("outcome")
        self.assertEqual(found["now"], "landed on next at 8ecbea2, goes live with the next deploy")

    def test_the_receipt_says_the_landing_was_not_pushed(self):
        """c-665: a local landing never reads as shipped."""
        self.at_review()
        self.board.conn.execute("UPDATE cards SET stage = 'done' WHERE id = ?", (self.card,))
        self.board.record_event(self.card, "approve", "human", data={
            "gate": "outcome", "published": "8ecbea2 merged into main locally, not pushed"})
        self.assertEqual(self.got("outcome")[0]["now"], "landed on main at 8ecbea2, not pushed")

    def test_the_stage_hook_s_bounce_is_not_an_answer(self):
        self.at_review()
        self.board.stage(self.card, "building", "hook")
        self.board.stage(self.card, "review", "house", output_ref="keel/c-1 @ abc")
        found, open_ = self.got("outcome")
        self.assertIsNone(found)
        self.assertTrue(open_)


class PlanSend(ReceiptCase):
    """`plan.send` holds the same line on the server: a stale tab cannot answer twice, and
    Approve again after a refused landing clears that refusal's block, and only it."""

    def send(self, mode="approve", doc="plan", fails=False):
        self.calls = []

        def run_kb(cfg, argv):
            self.calls.append(argv)
            if argv[0] == "unblock":
                self.board.unblock(argv[1], "human", expect=argv[3])
            if argv[0] == "block":
                self.board.block(argv[1], argv[2], "human")

        def approve(cfg, board, body):
            self.calls.append(["approve", body["gate"]])
            if getattr(self, "relay_first", False):
                self.board.relay(self.card, "land", "human", "box", sha=SHA)
            if fails:
                raise actions.ActionError("the landing relay was refused")
            return {}
        return planactions.send(self.cfg, self.board, {"id": self.card, "mode": mode, "doc": doc},
                                approve=approve, sendback=lambda *a: {}, run_kb=run_kb,
                                gate_of=actions.gate_of)

    def test_a_second_send_at_an_answered_gate_is_refused(self):
        self.at_review()
        self.land_relay()
        with self.assertRaises(planactions.SendError) as caught:
            self.send(doc="outcome")
        self.assertIn("answered already: approved by you, landing", str(caught.exception))

    def test_approve_again_clears_the_refusal_s_block_then_approves(self):
        self.at_review()
        relay = self.land_relay()
        self.board.carry(self.card, relay, "drain")
        self.landing(state="refused", relay=relay, why="red")
        self.board.block(self.card, receipt.NOT_MERGED + "red", "drain")
        self.send(doc="outcome")
        self.assertEqual(self.calls[0], ["unblock", self.card, "--expect", receipt.NOT_MERGED + "red"])
        self.assertEqual(self.calls[1], ["approve", "outcome"])
        self.assertIsNone(self.board.get(self.card)["blocked_reason"])

    def test_an_approve_that_fails_after_the_unblock_puts_the_refusal_back(self):
        self.at_review()
        relay = self.land_relay()
        self.board.carry(self.card, relay, "drain")
        self.landing(state="refused", relay=relay, why="red")
        self.board.block(self.card, receipt.NOT_MERGED + "red", "drain")
        with self.assertRaises(actions.ActionError):
            self.send(doc="outcome", fails=True)
        self.assertEqual(self.board.get(self.card)["blocked_reason"], receipt.NOT_MERGED + "red")

    def test_an_approve_that_took_effect_before_failing_is_not_re_blocked(self):
        """The land relay was written, then its note failed: a block now would cancel a
        landing he asked for."""
        self.at_review()
        relay = self.land_relay()
        self.board.carry(self.card, relay, "drain")
        self.landing(state="refused", relay=relay, why="red")
        self.board.block(self.card, receipt.NOT_MERGED + "red", "drain")
        self.relay_first = True
        with self.assertRaises(actions.ActionError):
            self.send(doc="outcome", fails=True)
        self.assertIsNone(self.board.get(self.card)["blocked_reason"])

    def test_another_block_is_never_cleared_by_it(self):
        self.at_review()
        relay = self.land_relay()
        self.board.carry(self.card, relay, "drain")
        self.landing(state="refused", relay=relay, why="red")
        self.board.block(self.card, "he blocked it himself", "human")
        self.send(doc="outcome")
        self.assertEqual(self.calls[0], ["approve", "outcome"])     # the approve then refuses a blocked card


class Inspector(ReceiptCase):
    def test_it_takes_the_newest_answer_of_either_gate(self):
        self.at_review()
        self.assertEqual(self.got(None)[0]["gate"], "plan")
        self.assertEqual(self.got(None)[0]["now"], "built: the outcome waits for you")
        self.land_relay()
        self.assertEqual(self.got(None)[0]["gate"], "outcome")

    def test_a_card_nobody_answered_has_none(self):
        self.assertIsNone(self.got(None)[0])


class PublishedLineTest(unittest.TestCase):
    """At done the receipt printed the adapter's answer as raw JSON (c-601, e2e bug 11)."""

    def test_a_published_record_reads_as_a_sentence(self):
        import json
        record = json.dumps({"posted": ["a", "b", "c"], "pr": 1, "pushed": "0123456789abcdef", "round": 1})
        line = receipt.tap_landed(None, {}, {"kind": "approve", "published": record})
        self.assertEqual(line, "published: pull request #1, pushed 0123456789, 3 replies posted")
        self.assertNotIn("{", line)


if __name__ == "__main__":
    unittest.main()
