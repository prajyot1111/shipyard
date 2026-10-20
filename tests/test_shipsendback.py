"""c-663: Send back at shipping. His own notes on a shipping card are one more item of the
card's batch, of a kind of its own (his), told to the card's own house whatever the two
automatic-handling switches say, judged like any item, and never posted anywhere.

The stand-ins are `tests/test_shipping.py`'s, with both switches off as shipped
(`tests/test_shipauto.py`'s `OffCase`).
"""

from argparse import Namespace
from datetime import timedelta
from unittest import mock

from keel import actions, cli, dropin, idleclose, shipauto, shipidle, shipreplies, shipsendback, shipwatch
from keel import config as config_module
from keel.board import Board, Refused, open_board
from tests.helpers import SESSION, write_toml
from tests.test_shipauto import LATER, OffCase
from tests.test_shipping import MON_10, comment, sight

WORDS = "Rename `CAP` to PAGE_SIZE {everywhere}.\nAnd say why it is 40 in the docstring."
SOON = MON_10 + timedelta(minutes=1)


class SendBackCase(OffCase):
    def setUp(self):
        super().setUp()
        for module in (shipidle, idleclose):
            patch = mock.patch.object(module, "harness", self.fake)
            patch.start()
            self.addCleanup(patch.stop)

    def sent(self, words=WORDS, **seen) -> None:
        """A live house, the looks that find what the code host shows, and his send-back."""
        self.arrive(**seen)
        self.board.send_back(self.card, "human", words)

    def rows(self) -> dict:
        card = self.board.get(self.card)
        return {row["handle"]: row for row in shipreplies.rows(card, self.board.events(self.card))}

    def asked(self) -> list[str]:
        return [ask["handle"] for ask in self.board.get(self.card)["options"].get("sendback") or []]

    def idle_step(self) -> None:
        """The drain's idle step, which closes a re-offer's house once its turn ended."""
        shipidle.upkeep(self.cfg, self.board, list(self.fake.rows), {"work"}, at=SOON)


class ToldTest(SendBackCase):
    def test_his_words_reach_the_house_on_the_next_pass_with_both_switches_off(self):
        self.sent(comments=[comment(11, MON_10)])
        self.assertEqual(self.board.get(self.card)["derived"]["ship_sendback"][0]["text"], WORDS, "it waits, said")
        self.assertEqual(self.upkeep(SOON)["told"], [self.card])
        self.assertEqual((self.handles("told"), self.handles("untold")), (["his-1"], ["c11"]),
                         "his own item goes; the reviewer's stays parked")
        self.assertEqual(self.shipped()["told"][0]["kind"], shipsendback.KIND)
        self.assertEqual((self.asked(), self.board.get(self.card)["stage"]), ([], "shipping"))
        prompt = self.told_prompt()
        self.assertIn(WORDS, prompt, "verbatim, braces and line breaks kept")
        self.assertNotIn("Why is the cap 40?", prompt)

    def test_several_send_backs_before_the_tell_are_several_items(self):
        self.sent()
        self.board.send_back(self.card, "human", "And drop the dead import.")
        self.upkeep(SOON)
        self.assertEqual(self.handles("told"), ["his-1", "his-2"])

    def test_a_send_back_while_the_house_is_in_its_turn_waits_for_the_turn_to_end(self):
        self.sent()
        self.live(status="busy")
        self.assertEqual((self.upkeep(SOON)["told"], self.handles("pending")), ([], ["his-1"]))
        self.live()
        self.assertEqual(self.upkeep(SOON + timedelta(seconds=30))["told"], [self.card])

    def test_an_ask_that_lands_while_the_drain_writes_its_record_is_not_dropped(self):
        self.sent()
        keep, landed = self.board.keep_shipping, []

        def meanwhile(*args, **kwargs):
            if not landed:
                landed.append(self.board.send_back(self.card, "human", "One more thing."))
            return keep(*args, **kwargs)
        with mock.patch.object(self.board, "keep_shipping", meanwhile):
            self.upkeep(SOON)
        self.assertEqual((self.handles("told"), self.asked()), (["his-1"], ["his-2"]))
        self.turn_ends()
        self.upkeep(SOON + timedelta(minutes=1))
        self.assertEqual(self.handles("told"), ["his-1", "his-2"])


class NeverPostedTest(SendBackCase):
    def told_and_judged(self):
        self.space_on("comments")
        self.sent(comments=[comment(11, MON_10)])
        self.later()
        self.verdict("c11", "not-valid", reply="It is the page size.")
        self.verdict("his-1", "valid", commits=[{"sha": "abc1234", "diff": "abc1234 Rename CAP\n"}],
                     reply="Renamed in three files.")

    def test_his_item_shows_as_his_row_and_ship_never_counts_or_posts_it(self):
        self.told_and_judged()
        card, events = self.board.get(self.card), self.board.events(self.card)
        mine = self.rows()["his-1"]
        self.assertEqual((mine["his"], mine["words"], mine["verdict"]["reply"]), (True, "", "Renamed in three files."))
        self.assertEqual([one["handle"] for one in shipreplies.kept(card, events)], ["c11"])
        self.assertEqual(shipreplies.summary(card, events)["to_post"], 1)
        self.board.ship(self.card, "human", lambda _card: {"sent": [{"handle": "c11", "text": "It is the page size."}]})
        self.assertFalse(shipwatch.open_told(self.shipped()), "nothing of his is ever waiting to be posted")

    def test_no_mark_of_his_makes_it_postable(self):
        self.told_and_judged()
        with self.assertRaises(Refused):
            self.board.mark(self.card, {"what": "answer", "doc": "shipping", "block": "replies",
                                        "row": "his-1", "choice": "post"}, "human")

    def test_a_reason_why_not_is_an_answer_with_no_commit_and_no_reply(self):
        self.sent()
        self.upkeep(SOON)
        self.verdict("his-1", "not-valid", why="PAGE_SIZE is taken by the pager; CAP stays")
        self.assertEqual(self.rows()["his-1"]["verdict"]["verdict"], "not-valid")


class HisAloneTest(SendBackCase):
    def test_only_he_sends_back_and_only_with_words_at_shipping(self):
        self.arrive()
        for actor in ("house", "bosun", "drain"):
            with self.assertRaises(Refused, msg=actor):
                self.board.send_back(self.card, actor, WORDS)
            with self.assertRaises(Refused, msg=f"{actor} writing the option"):
                self.board.set_fields(self.card, {"options": {"sendback": [{"handle": "his-9", "text": "x"}]}}, actor)
        with self.assertRaises(Refused):
            self.board.send_back(self.card, "human", "   ")
        self.board.stage(self.card, "done", "human")
        with self.assertRaises(Refused):
            self.board.send_back(self.card, "human", WORDS)


class OrdinaryItemTest(SendBackCase):
    """His item rides no hand-over mark: it is told, waits and is left unjudged exactly as an
    ordinary item of the batch is, so nothing about it can stop a house or block a card."""

    def test_a_turn_that_ends_with_his_item_unjudged_blocks_nothing_and_he_can_hand_it_over_again(self):
        self.sent()
        self.upkeep(SOON)
        self.assertNotIn("reoffer", self.shipped(), "no hand-over mark is written for it")
        self.assertNotIn("Keel stops this", self.told_prompt(), "the house is not told it will be stopped")
        self.turn_ends()
        self.assertFalse((self.board.get(self.card)["derived"]["ship_idle"] or {}).get("reoffer"),
                         "the deck does not say it closes now")
        self.idle_step()
        card = self.board.get(self.card)
        self.assertEqual((self.fake.stops, card["blocked_reason"]), ([], None))
        self.assertIsNone(self.rows()["his-1"]["verdict"], "told, not judged yet")
        self.assertEqual(self.hand()["his"], 1, "his hand-over counts it")
        self.board.reoffer(self.card, "human")
        self.assertEqual(self.later()["told"], [self.card])
        self.assertIn(WORDS, self.told_prompt())
        self.assertEqual(self.shipped()["told"][-1]["batch"], 2)

    def test_a_judged_item_s_turn_ends_and_the_next_send_back_is_told_at_once(self):
        self.sent()
        self.upkeep(SOON)
        self.verdict("his-1", "not-valid", why="PAGE_SIZE is taken by the pager; CAP stays")
        self.turn_ends()
        self.idle_step()
        self.board.send_back(self.card, "human", "One more thing.")
        self.upkeep(SOON + timedelta(minutes=1))
        self.assertEqual((self.handles("told"), self.fake.stops), (["his-1", "his-2"], []))

    def test_a_reviewer_s_comment_and_his_item_in_one_batch_end_their_turn_like_any_batch(self):
        self.space_on("comments")
        self.sent(comments=[comment(11, MON_10)])
        self.assertEqual(self.upkeep(SOON)["told"], [self.card])
        self.assertEqual(sorted(self.handles("told")), ["c11", "his-1"])
        self.turn_ends()
        self.idle_step()
        card = self.board.get(self.card)
        self.assertEqual((card["blocked_reason"], self.fake.stops), (None, []))
        hand = self.hand()
        self.assertEqual((hand["comments"], hand["his"]), (1, 1), "both are his to hand over again")

    def test_his_item_in_a_batch_he_re_offered_follows_the_re_offer_s_rules(self):
        self.sent(comments=[comment(11, MON_10)])
        self.live(status="busy")
        self.upkeep(SOON)                           # his-1 waits in the batch for the turn to end
        self.board.reoffer(self.card, "human")      # and he hands the parked comment over too
        self.live()
        self.later()
        self.assertEqual(sorted(self.handles("told")), ["c11", "his-1"])
        self.turn_ends()
        self.idle_step()
        self.assertEqual(self.fake.stops, [SESSION[:8]], "that batch is his re-offer")

    def test_a_re_offer_whose_items_were_judged_before_the_tell_leaves_his_item_an_ordinary_batch(self):
        self.space_on("comments")
        self.arrive(comments=[comment(11, MON_10)])
        self.later()                                        # batch 1: c11, an ordinary batch
        self.turn_ends()
        self.board.send_back(self.card, "human", WORDS)
        self.later(LATER + timedelta(minutes=1), slots=0)   # his-1 waits for a slot
        self.board.reoffer(self.card, "human")              # and c11, never judged, is offered again
        self.later(LATER + timedelta(minutes=2), slots=0)
        self.assertEqual(sorted(self.handles("pending")), ["c11", "his-1"])
        self.verdict("c11", "not-valid", reply="It is the page size.")
        self.assertEqual(self.later(LATER + timedelta(minutes=3))["told"], [self.card])
        self.assertEqual([item["handle"] for item in self.shipped()["told"] if item["batch"] == 2], ["his-1"])
        self.assertNotIn("Keel stops this", self.told_prompt())
        self.turn_ends()
        self.idle_step()
        self.assertEqual((self.fake.stops, self.board.get(self.card)["blocked_reason"]), ([], None))


class HeldTest(SendBackCase):
    """Review pass 4: a send-back never perturbs a re-offer, and what he sent says why it is
    not on its way whenever that is so."""

    def held(self) -> str:
        return self.board.get(self.card)["derived"]["ship_sendback"][0]["held"] or ""

    def reached(self, at) -> list[str]:
        result = self.later(at)
        return result["told"] + result["resumed"]

    def test_a_send_back_during_a_re_offer_s_turn_waits_and_the_re_offer_is_settled_as_ever(self):
        self.arrive(comments=[comment(11, MON_10)])         # parked: handling is off
        self.board.reoffer(self.card, "human")
        self.assertEqual(self.later()["told"], [self.card])  # batch 1: c11, his re-offer
        self.board.send_back(self.card, "human", WORDS)      # during its turn
        self.assertEqual(self.reached(LATER + timedelta(minutes=1)), [])
        self.assertEqual((self.asked(), self.handles("pending")), (["his-1"], []), "his ask stays on the card")
        self.assertIn("handed over", self.held())
        self.turn_ends()                                     # c11 left unjudged
        self.assertEqual(self.reached(LATER + timedelta(minutes=2)), [], "no batch is taken before the settle")
        self.idle_step()
        card = self.board.get(self.card)
        self.assertEqual(self.fake.stops, [SESSION[:8]], "the re-offer's close, as with no send-back")
        self.assertIn("c11", card["blocked_reason"] or "")
        self.assertNotIn("his-1", card["blocked_reason"])
        self.assertEqual(self.shipped()["reoffer"]["unjudged"], ["c11"])
        self.board.unblock(self.card, "human")
        self.assertEqual(self.reached(LATER + timedelta(minutes=3)), [self.card])
        self.assertEqual([item["handle"] for item in self.shipped()["told"] if item["batch"] == 2], ["his-1"])

    def re_offered_then_sent_back(self) -> None:
        """Batch 1 is his re-offer of a parked comment, told; he sends back during its turn."""
        self.arrive(comments=[comment(11, MON_10)])
        self.board.reoffer(self.card, "human")
        self.assertEqual(self.later()["told"], [self.card])
        self.board.send_back(self.card, "human", WORDS)
        self.at = LATER

    def passes(self, count=2) -> list[str]:
        """`count` drain passes a minute apart, the watcher and then the idle step: the cards
        a batch reached."""
        reached = []
        for _ in range(count):
            self.at += timedelta(minutes=1)
            reached += self.reached(self.at)
            self.idle_step()
        return reached

    def waits_on_the_re_offer(self) -> None:
        self.assertEqual(self.passes(), [], "no batch is taken")
        self.assertEqual((self.asked(), self.handles("pending"), self.shipped()["round"]), (["his-1"], [], 1))
        self.assertIn("handed over", self.held())
        self.assertEqual(self.fake.stops, [])

    def tap_resume(self):
        """His Resume as the deck sends it (`actions.act_resume`), never an event written by hand."""
        return actions.act(self.cfg, self.board, {"verb": "house.resume", "id": self.card})

    def test_a_re_offer_s_house_that_died_mid_turn_does_not_hold_his_ask(self):
        """c-666 review F2: with no Stop on the board that turn never reads as ended, and his
        ask waited until his Resume. The hold is "its house is on that batch": a session
        listed no more is on nothing. A listing that failed is never read as that."""
        self.re_offered_then_sent_back()
        self.fake.rows, self.fake.listing_fails = [], True
        self.waits_on_the_re_offer()
        self.fake.listing_fails = False
        self.assertEqual(self.passes(), [self.card], "his item resumes the house")
        self.assertEqual([item["handle"] for item in self.shipped()["told"] if item["batch"] == 2], ["his-1"])
        self.assertEqual(self.fake.stops, [])

    def test_a_listed_row_with_no_process_does_not_hold_his_ask_either(self):
        """c-666 review pass 2, F1: the harness can go on listing a dead session with no
        process behind it, and that house is on nothing."""
        self.re_offered_then_sent_back()
        self.fake.rows[0]["pid"] = None                      # and no Stop on the board
        self.assertEqual(self.passes(), [self.card])
        self.assertEqual([item["handle"] for item in self.shipped()["told"] if item["batch"] == 2], ["his-1"])
        self.assertEqual(self.fake.stops, [])

    def test_his_resume_of_a_house_open_in_his_terminal_is_refused_and_records_nothing(self):
        self.arrive()
        self.fake.rows[0]["kind"] = dropin.INTERACTIVE
        events = len(self.board.events(self.card))
        with self.assertRaises(actions.ActionError):
            self.tap_resume()
        self.assertEqual(len(self.board.events(self.card)), events)

    def test_a_send_back_to_a_house_he_stopped_says_so_and_goes_with_his_resume(self):
        self.arrive()
        self.fake.rows = []
        self.board.note(self.card, "session stopped from the deck", "human", mark="human-stop")
        self.board.send_back(self.card, "human", WORDS)
        self.assertEqual(self.reached(LATER), [])
        self.assertEqual(self.handles("pending"), ["his-1"])
        self.assertIn("Resume", self.held())
        self.board.record_event(self.card, "resume", "human")          # his Resume
        self.assertEqual(self.held(), "")
        self.assertEqual(self.reached(LATER + timedelta(minutes=1)), [self.card])

    def test_a_send_back_while_the_drain_is_paused_says_so_and_goes_once_it_runs(self):
        self.arrive()
        self.cfg.drain_paused = self.board.drain_paused = True
        self.board.send_back(self.card, "human", WORDS)
        self.assertEqual(self.reached(LATER), [])
        self.assertIn("paused", self.held())
        self.cfg.drain_paused = self.board.drain_paused = False
        self.assertEqual(self.held(), "")
        self.assertEqual(self.reached(LATER + timedelta(minutes=1)), [self.card])

    def test_an_ask_on_a_pull_request_declined_meanwhile_is_told_once_it_is_open_again(self):
        self.sent()
        self.see(sight(state="declined"))
        self.assertEqual(self.reached(LATER), [])
        self.assertEqual((self.asked(), self.handles("pending")), (["his-1"], []))
        self.assertIn("declined", self.held())
        self.see(sight())
        self.assertEqual(self.reached(LATER + timedelta(minutes=1)), [self.card])
        self.assertEqual(self.handles("told"), ["his-1"])

    def test_a_merge_the_drain_finds_says_which_send_backs_went_untold(self):
        self.sent()
        self.live(status="busy")
        self.upkeep(SOON)                                    # his-1 in the batch, untold
        self.board.send_back(self.card, "human", "One more thing.")
        self.see(sight(state="merged"))
        self.later()
        self.assertEqual(self.board.get(self.card)["stage"], "done")
        dropped = [event for event in self.board.events(self.card)
                   if (event.get("data") or {}).get("sendback_dropped")]
        self.assertEqual(dropped[-1]["data"]["sendback_dropped"], ["his-2", "his-1"])


class KeptTest(SendBackCase):
    """What keeps his words: the fill is once, a failed tell puts the item back, a block or
    an archive keeps the ask, and leaving shipping says what it dropped."""

    def test_a_pass_that_filled_the_item_and_never_took_the_ask_does_not_fill_it_twice(self):
        self.sent()
        self.live(status="busy")
        with mock.patch.object(self.board, "take_sendback"):       # the pass died before its take
            self.upkeep(SOON)
        self.assertEqual((self.handles("pending"), self.asked()), (["his-1"], ["his-1"]))
        self.upkeep(SOON + timedelta(seconds=30))
        self.assertEqual((self.handles("pending"), self.asked()), (["his-1"], []))

    def test_a_tell_that_fails_puts_his_item_back(self):
        self.arrive()
        self.board.set_fields(self.card, {"session_id": None}, "drain")
        self.fake.rows = []
        self.board.send_back(self.card, "human", WORDS)
        self.fake.fail = "claude would not start"
        self.upkeep(SOON)
        self.assertIn("claude would not start", self.board.get(self.card)["blocked_reason"])
        self.assertEqual((self.handles("pending"), self.handles("told")), (["his-1"], []))
        self.assertEqual(self.shipped()["pending"][0]["text"], WORDS)

    def test_a_block_and_an_archive_keep_the_ask_and_leaving_shipping_says_what_it_dropped(self):
        self.sent()
        self.board.block(self.card, "waiting on the pager", "human")
        self.board.set_fields(self.card, {"options": {"archived": True}}, "human")
        self.assertEqual(self.asked(), ["his-1"])
        held = self.board.get(self.card)["derived"]["ship_sendback"][0]["held"]
        self.assertTrue(held, "and the deck is told it is not on its way")
        self.board.set_fields(self.card, {"options": {"archived": None}}, "human")
        self.board.unblock(self.card, "human")
        self.assertIsNone(self.board.get(self.card)["derived"]["ship_sendback"][0]["held"])
        self.live(status="busy")
        self.upkeep(SOON)                                           # his-1 in the batch, untold
        self.board.send_back(self.card, "human", "One more thing.")
        self.board.stage(self.card, "done", "human")
        self.assertEqual(self.asked(), [])
        dropped = [event for event in self.board.events(self.card)
                   if (event.get("data") or {}).get("sendback_dropped")]
        self.assertEqual(dropped[-1]["data"]["sendback_dropped"], ["his-2", "his-1"])


class RefusedTest(SendBackCase):
    def refused(self, words=WORDS) -> str:
        with self.assertRaises(Refused) as caught:
            self.board.send_back(self.card, "human", words)
        return str(caught.exception)

    def test_a_blocked_an_archived_and_a_declined_card_and_words_too_long_are_refused(self):
        self.arrive()
        self.assertIn("longer", self.refused("x" * (shipsendback.WORDS_MAX + 1)))
        self.board.block(self.card, "waiting on the pager", "human")
        self.assertIn("blocked", self.refused())
        self.board.unblock(self.card, "human")
        self.board.set_fields(self.card, {"options": {"archived": True}}, "human")
        self.assertIn("archived", self.refused())
        self.board.set_fields(self.card, {"options": {"archived": None}}, "human")
        self.see(sight(state="declined"))
        self.later()
        self.assertIn("declined", self.refused())
        self.assertEqual(self.asked(), [])

    def test_the_option_is_not_his_to_write_by_hand_either(self):
        self.arrive()
        with self.assertRaises(Refused):
            self.board.set_fields(self.card, {"options": {"sendback": [{"handle": "his-9", "text": "x"}]}}, "human")

    def test_a_valid_verdict_on_his_item_names_its_commits(self):
        self.sent()
        self.upkeep(SOON)
        with self.assertRaises(Refused):
            self.verdict("his-1", "valid")
        self.assertIsNone(self.rows()["his-1"]["verdict"])


class VerbTest(SendBackCase):
    """`kb ship <id> sendback`: where its words come from, and the flags that are not its."""

    def ship(self, actor="human", **flags):
        args = Namespace(id=self.card, what=flags.pop("what", "sendback"), config=self.cfg,
                         **dict({"words": None, "words_file": None, "anyway": False, "rebase": False}, **flags))
        return cli.cmd_ship(self.board, args, actor)

    def test_the_words_come_from_the_flag_or_a_file(self):
        self.arrive()
        self.ship(words=WORDS)
        path = self.dir / "words.txt"
        path.write_text("From a file.\n")
        self.ship(words_file=str(path))
        self.assertEqual([ask["text"] for ask in self.board.get(self.card)["options"]["sendback"]],
                         [WORDS, "From a file."])

    def test_flags_that_are_not_its_and_words_given_twice_or_to_another_verb_are_refused(self):
        self.arrive()
        for flags in ({"words": WORDS, "anyway": True}, {"words": WORDS, "rebase": True},
                      {"words": WORDS, "words_file": "x.txt"}, {"words_file": str(self.dir / "none.txt")},
                      {"what": None, "words": WORDS}, {"what": "reoffer", "words": WORDS}, {}):
            with self.assertRaises(Refused, msg=str(flags)):
                self.ship(**flags)
        with self.assertRaises(Refused):
            self.ship(actor="house", words=WORDS)
        self.assertEqual(self.asked(), [])


class CadenceTest(SendBackCase):
    def test_only_his_kind_is_left_out_of_what_a_ship_has_yet_to_answer(self):
        """The look's cadence reads this: a rebase item told counts as it always did."""
        told = lambda kind: {"told": [{"kind": kind, "handle": kind}], "posted": {}}     # noqa: E731
        self.assertTrue(shipwatch.open_told(told("rebase")))
        self.assertTrue(shipwatch.open_told(told("comment")))
        self.assertFalse(shipwatch.open_told(told(shipsendback.KIND)))


class SwitchTest(SendBackCase):
    def test_his_kind_answers_to_neither_switch_by_itself(self):
        """With no hand-over mark to hold it in the batch: the kind alone is never parked."""
        waits = {"pending": [shipsendback.item_of({"handle": "his-1", "text": WORDS, "at": "x"})]}
        kept = shipauto.settle(waits, {"comments": False, "checks": False}, release=False)
        self.assertEqual((kept["pending"], kept.get("untold")), (waits["pending"], None))


class TapTest(SendBackCase):
    """His tap, through the real `bin/kb`, as the hand-over's is."""

    def config(self):
        return config_module.load(write_toml(self.dir))

    def opened(self) -> Board:
        return open_board(self.cfg)

    def test_the_deck_s_send_back_is_the_verb_run_as_him(self):
        self.arrive()
        said = actions.act(self.cfg, self.board, {"verb": "ship.sendback", "id": self.card, "words": WORDS})
        self.assertEqual(said["note"], shipsendback.SENT)
        ask = self.board.get(self.card)["options"]["sendback"][0]
        self.assertEqual((ask["by"], ask["text"]), ("human", WORDS))
        with self.assertRaises(actions.ActionError):
            actions.act(self.cfg, self.board, {"verb": "ship.sendback", "id": self.card, "words": ""})

    def test_the_board_the_deck_opens_knows_the_drain_is_paused(self):
        self.arrive()
        self.cfg.drain_paused = True
        board = open_board(self.cfg)
        self.addCleanup(board.close)
        board.send_back(self.card, "human", WORDS)
        self.assertIn("paused", board.get(self.card)["derived"]["ship_sendback"][0]["held"] or "")

    def test_a_body_with_a_caller_is_refused(self):
        self.arrive()
        with self.assertRaisesRegex(actions.ActionError, "one machine"):
            actions.act(self.cfg, self.board, {"verb": "ship.sendback", "id": self.card, "words": WORDS,
                                               "caller": {"actor": "house"}})
        self.assertEqual(self.asked(), [])


if __name__ == "__main__":
    import unittest
    unittest.main()
