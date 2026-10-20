"""c-666: a re-offered batch is settled even when another batch is due right behind it.

The watcher runs before the idle step in a pass, so a batch due on the pass after a
re-offered batch's turn ended was told first, `round` moved past the hand-over mark, and
the idle step never settled that re-offer: no close, no count of what was left unjudged,
no block. Now the watcher, about to tell a batch behind such a re-offer, settles it first,
in that pass, with the idle step's own function on a strict listing: the house closed or
gone exactly as the idle step does it; a listing that failed settles and tells nothing; a
close refused for a reason ends the re-offer with a note, and neither a stop nor a block.
Nothing is carried from one pass to the next.

Every test here is a drain pass as the drain makes it: the watcher (`shipping.upkeep`),
then the idle step (`shipidle.upkeep`), each with the pass's skip set where one is given.
A house that is not idle is said by the fake listing's own row, or by the harness's own
job record in the space's config dir.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from keel import drain, dropin, harness, house, shipidle, shipping, tellhouse
from tests.helpers import SESSION, background_row
from tests.test_shipauto import LATER
from tests.test_shipping import MON_10, comment, sight
from tests.test_shipsendback import WORDS, SendBackCase

# What the card says when a re-offer is ended with its house not closed, by the reason.
NOT_CLOSED = ("the house's turn on re-offered batch 1 ended and the house was not closed as idle: {fact}. "
              "1 of 1 item of that batch has no verdict yet (c11); the house may still be judging it. "
              "Nothing was stopped and the card is not blocked")
A_JOB = NOT_CLOSED.format(fact="a background job of its own is still running")
A_TERMINAL = NOT_CLOSED.format(fact="it is open in your terminal")
STOP_FAILED = ("Shipyard could not stop this idle house (claude stop failed) and keeps trying. Its re-offered "
               "batch is settled once the stop goes through; the review items waiting behind it are told "
               "after that, or after your unblock if that batch left items unjudged")

# The note as the release before c-699 wrote it, verbatim from origin/next's
# keel/shipidle.py (`STOP_FAILED_NOTE`, the same why): a card may still hold it (r2.F5).
EARLIER_STOP_FAILED = ("Keel could not stop this idle house (claude stop failed) and keeps trying. Its "
                       "re-offered batch is settled once the stop goes through; the review items waiting "
                       "behind it are told after that, or after your unblock if that batch left items "
                       "unjudged")


class SettleCase(SendBackCase):
    def re_offered(self) -> None:
        """Batch 1 is the owner's re-offer of a parked comment (c11), told to a live house."""
        self.arrive(comments=[comment(11, MON_10)])
        self.board.reoffer(self.card, "human")
        self.assertEqual(self.later()["told"], [self.card])
        self.at = LATER

    def a_reviewer_writes(self, busy=True) -> None:
        """A reviewer's new comment (c12), found while the house is in its turn on batch 1,
        with comments handled automatically: its quiet window is over on the next pass."""
        self.space_on("comments")
        if busy:
            self.live(status="busy")
        self.see(sight(comments=[comment(11, MON_10), comment(12, self.at)]))
        self.assertEqual(self.reached(), [], "the comment waits")
        self.assertEqual(self.handles("pending"), ["c12"])
        self.at += timedelta(minutes=10)

    def watch(self, slots=1, skip=frozenset()) -> list[str]:
        """The watcher's step of one pass: the cards a batch reached."""
        self.at += timedelta(minutes=1)
        shipping.LAST_POLLED.clear()
        self.listed = list(self.fake.rows)       # the pass's one listing, taken before its steps
        more = {"skip": skip} if skip else {}
        result = shipping.upkeep(self.cfg, self.board, {"work"}, slots=slots, at=self.at, **more)
        self.closed = set(result.get("closed") or ())
        return result["told"] + result["resumed"]

    def idle(self, skip=frozenset(), at=None) -> None:
        """The idle step of the same pass, over the pass's listing, skipping what the drain
        skips: its own set, and the houses the watcher closed on this pass."""
        shipidle.upkeep(self.cfg, self.board, self.listed, {"work"}, set(skip) | self.closed, at=at or self.at)

    def reached(self, slots=1) -> list[str]:
        """One drain pass, the watcher and then the idle step: the cards a batch reached."""
        reached = self.watch(slots)
        self.idle()
        return reached

    def idle_adds_nothing(self) -> None:
        """The idle step of the pass whose watcher settled the re-offer finds it settled."""
        before = (len(self.board.events(self.card)), list(self.fake.stops))
        self.idle()
        self.assertEqual((len(self.board.events(self.card)), self.fake.stops), before)

    def mark(self) -> dict:
        return self.shipped()["reoffer"]

    def batch(self, number: int) -> list[str]:
        return sorted(item["handle"] for item in self.shipped()["told"] if item["batch"] == number)

    def notes(self) -> list[str]:
        return [event["text"] or "" for event in self.board.events(self.card) if event["kind"] == "note"]

    def blocked(self) -> str:
        return self.board.get(self.card)["blocked_reason"] or ""

    def a_job_of_its_own(self) -> None:
        """The listing's shape for a house idle with a background job running (busy by
        status, done by state), and the harness's own record of that job."""
        self.job = Path(self.cfg.spaces["work"].config_dir) / "jobs" / SESSION[:8] / "state.json"
        self.job.parent.mkdir(parents=True, exist_ok=True)
        self.job.write_text(json.dumps({
            "inFlight": {"tasks": 1}, "fan": [{"id": "bs6e3ga2f", "kind": "shell", "startedAt": 1790413540697,
                                               "label": "make test"}]}))
        self.fake.rows = [dict(background_row(self.card, SESSION), status="busy", state="done")]

    def open(self) -> None:
        """The re-offer is as it was: nothing on its mark, nothing said, nothing told."""
        mark = self.mark()
        self.assertEqual((mark.get("closed_at"), mark.get("done_at"), self.shipped()["round"]), (None, None, 1))
        self.assertEqual(self.blocked(), "")

    def listings(self, second):
        """The fake's listing, answering the pass's SECOND ask (the close's own, under the
        card's lock) with `second`."""
        agents, asked = self.fake.agents, []

        def answer(config_dir=None, all_sessions=False, strict=False):
            asked.append(strict)
            return second(strict) if len(asked) == 2 else agents(config_dir, all_sessions, strict)
        return mock.patch.object(self.fake, "agents", side_effect=answer)

    def unsettled(self) -> None:
        mark = self.mark()
        self.assertEqual((mark.get("closed_at"), mark.get("done_at"), self.shipped()["round"]), (None, None, 1))
        self.assertEqual((self.fake.stops, self.blocked()), ([], ""))

    def ended_by_note(self, said: str) -> None:
        """The re-offer is over with this one note; nothing was stopped, nothing blocked,
        and no field waits for a later pass."""
        mark = self.mark()
        self.assertTrue(mark.get("done_at"))
        self.assertEqual((mark.get("closed_at"), self.fake.stops, self.blocked()), (None, [], ""))
        self.assertEqual(sorted(set(mark) & {"unjudged", "deferred"}), [], "the note carries it, not the mark")
        self.assertEqual(self.notes().count(said), 1)


class IdleHouseTest(SettleCase):
    def test_a_batch_due_on_the_pass_after_the_turn_ended_does_not_skip_the_settlement(self):
        """The bug: the newer batch was told first, and the re-offer was never settled."""
        self.re_offered()
        self.a_reviewer_writes()
        self.turn_ends()                                     # c11 left unjudged
        self.live()
        self.assertEqual(self.watch(), [], "settled first, by the watcher itself")
        self.assertEqual(self.fake.stops, [SESSION[:8]], "the idle house is closed, as with nothing due")
        self.assertIn("c11", self.blocked())
        self.assertEqual((self.mark()["unjudged"], self.shipped()["round"]), (["c11"], 1))
        self.idle_adds_nothing()
        self.assertEqual(self.reached(), [], "blocked for the owner: nothing is told until the unblock")
        self.board.unblock(self.card, "human")
        self.assertEqual(self.reached(), [self.card])
        self.assertEqual((self.batch(2), self.fake.stops), (["c12"], [SESSION[:8]]))

    def test_with_every_item_judged_the_house_is_closed_and_the_next_pass_resumes_it(self):
        self.re_offered()
        self.a_reviewer_writes()
        self.verdict("c11", "not-valid", reply="It is the page size.")
        self.turn_ends()
        self.live()
        self.assertEqual(self.watch(), [], "a house closed on this pass is told nothing on it")
        self.assertEqual((self.fake.stops, self.blocked()), ([SESSION[:8]], ""))
        self.assertTrue(self.mark().get("closed_at"))
        self.idle_adds_nothing()
        self.assertEqual(self.reached(), [self.card])
        self.assertEqual((self.batch(2), self.fake.stops), (["c12"], [SESSION[:8]]))

    def test_a_pass_that_could_not_settle_leaves_nothing_behind_for_a_later_one(self):
        """Review F1: a stamp kept from a pass that could not settle made a later pass, with
        the house idle, end the re-offer by note before the idle step could close it."""
        self.re_offered()
        self.a_reviewer_writes()
        self.turn_ends()                                     # c11 left unjudged
        self.fake.rows, self.fake.listing_fails = [], True
        self.assertEqual(self.reached(), [])
        self.unsettled()
        self.fake.listing_fails = False
        self.live()
        self.assertEqual(self.reached(), [])
        self.assertEqual(self.fake.stops, [SESSION[:8]], "idle now: closed, as the idle step closes it")
        self.assertIn("c11", self.blocked())

    def test_a_house_with_a_job_at_its_stop_that_idles_before_a_batch_is_due_is_closed_and_blocked(self):
        """Review F6: nothing was due while the job ran, so nothing ended the re-offer then."""
        self.re_offered()
        self.turn_ends()                                     # c11 left unjudged
        self.a_job_of_its_own()
        self.assertEqual(self.reached(), [])
        self.a_reviewer_writes(busy=False)                   # seen while the job still runs
        self.unsettled()
        self.job.unlink()
        self.live()
        self.assertEqual(self.reached(), [])
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        self.assertIn("c11", self.blocked())

    def test_a_card_the_pass_already_acted_on_waits_for_the_next_pass(self):
        """The drain's skip set: the idle step leaves such a card alone, and so does this."""
        self.re_offered()
        self.a_reviewer_writes()
        self.turn_ends()
        self.live()
        self.assertEqual(self.watch(skip={self.card}), [])
        self.idle(skip={self.card})
        self.unsettled()
        self.assertEqual(self.handles("pending"), ["c12"])
        self.assertEqual(self.reached(), [])
        self.assertEqual(self.fake.stops, [SESSION[:8]])

    def test_a_send_back_that_lands_while_the_house_is_closed_is_told_after_the_unblock(self):
        self.re_offered()
        self.a_reviewer_writes()
        self.turn_ends()                                     # c11 left unjudged
        self.live()
        stop = self.fake.stop

        def sent_meanwhile(bg_id, config_dir=None):
            self.board.send_back(self.card, "human", WORDS)
            return stop(bg_id, config_dir)
        with mock.patch.object(self.fake, "stop", side_effect=sent_meanwhile):
            self.assertEqual(self.reached(), [])
        self.assertIn("c11", self.blocked())
        self.board.unblock(self.card, "human")
        self.assertEqual(self.reached() + self.reached(), [self.card])
        self.assertEqual(self.batch(2), ["c12", "his-1"])


class GoneHouseTest(SettleCase):
    def test_a_house_that_exited_with_a_batch_due_is_handed_to_the_owner_as_ever(self):
        self.re_offered()
        self.a_reviewer_writes()
        self.board.record_hook(self.card, "SessionEnd", {"session_id": SESSION})
        self.fake.rows = []
        self.assertEqual(self.watch(), [])
        self.assertTrue(self.mark().get("done_at"))
        self.assertEqual((self.mark()["unjudged"], self.fake.stops), (["c11"], []))
        self.assertIn("c11", self.blocked())
        self.idle_adds_nothing()
        self.board.unblock(self.card, "human")
        self.assertEqual(self.reached(), [self.card])
        self.assertEqual(self.batch(2), ["c12"])

    def test_a_listing_that_failed_settles_nothing_and_tells_nothing_until_it_answers(self):
        """Review F3: a failed listing read as "no session" told the batch to a house
        nothing could see."""
        self.re_offered()
        self.a_reviewer_writes()
        self.turn_ends()
        self.fake.rows, self.fake.listing_fails = [], True
        self.assertEqual(self.reached() + self.reached(), [])
        self.unsettled()
        self.assertEqual(self.handles("pending"), ["c12"], "nothing is lost")
        self.fake.listing_fails = False                      # and its session is listed no more
        self.assertEqual(self.reached(), [])
        self.assertEqual((self.mark()["unjudged"], self.fake.stops), (["c11"], []))
        self.assertIn("c11", self.blocked())

    def test_a_listed_row_with_no_process_is_a_house_that_is_gone(self):
        """Review F2: nothing can still be judging in a house that is not running, so what
        it left is counted and blocked for the owner, as for a session listed no more."""
        self.re_offered()
        self.a_reviewer_writes()
        self.turn_ends()                                     # c11 left unjudged
        self.fake.rows = [dict(background_row(self.card, SESSION), pid=None)]
        self.assertEqual(self.reached(), [])
        self.assertTrue(self.mark().get("done_at"))
        self.assertEqual((self.mark().get("unjudged"), self.fake.stops), (["c11"], []))
        self.assertIn("c11", self.blocked())
        self.assertIn("no longer running", self.blocked())
        self.board.unblock(self.card, "human")
        self.assertEqual(self.reached(), [self.card])
        self.assertEqual(self.batch(2), ["c12"])

    def no_process(self) -> list[dict]:
        return [dict(background_row(self.card, SESSION), pid=None)]

    def test_a_row_that_loses_its_process_between_the_two_listings_is_gone_too(self):
        """Review pass 3, F4: the watcher's listing showed a live house, the close's own
        (under the card's lock) shows the row with no process."""
        self.re_offered()
        self.a_reviewer_writes()
        self.turn_ends()                                     # c11 left unjudged
        self.live()

        def dead(_strict):
            self.fake.rows = self.no_process()
            return self.fake.rows
        with self.listings(dead):
            self.assertEqual(self.watch(), [])
        self.assertTrue(self.mark().get("done_at"))
        self.assertEqual((self.mark().get("unjudged"), self.fake.stops), (["c11"], []))
        self.assertIn("no longer running", self.blocked())

    def test_the_gone_settlement_waits_for_the_card_s_lock(self):
        """Review pass 3, F3: the owner's Resume of that house holds the card's lock while
        it starts the session, and records its turn only after. Nothing is written
        beside it; the pass waits, and never blocks on the lock."""
        self.re_offered()
        self.a_reviewer_writes()
        self.turn_ends()
        self.fake.rows = self.no_process()
        with house.card_lock(self.cfg, self.card):
            self.assertEqual(self.watch(), [])
            self.open()
        self.assertEqual(self.handles("pending"), ["c12"])
        self.assertEqual(self.reached(), [])
        self.assertIn("c11", self.blocked())

    def test_a_resume_recorded_before_the_gone_settlement_writes_is_not_blocked_over(self):
        """The same race, seen from the board: by the time the lock is free the resume is
        on record, the re-offer's turn reads over, and nothing of "gone" is written."""
        self.re_offered()
        self.a_reviewer_writes()
        self.turn_ends()
        self.fake.rows = self.no_process()
        agents, resumed = self.fake.agents, []

        def resumed_meanwhile(config_dir=None, all_sessions=False, strict=False):
            if strict and not resumed:
                resumed.append(self.board.record_resume(self.card, "human", "Carry on.",
                                                        {"session_id": SESSION}))
            return agents(config_dir, all_sessions, strict)
        with mock.patch.object(self.fake, "agents", side_effect=resumed_meanwhile):
            self.watch()
        self.assertEqual((self.blocked(), self.mark().get("unjudged"), self.fake.stops), ("", None, []))

    def test_a_house_killed_mid_turn_is_resumed_with_the_due_batch_at_once(self):
        """No Stop on the board, so that turn never reads as ended: the batch does not wait."""
        self.re_offered()
        self.a_reviewer_writes()
        self.fake.rows = []
        self.assertEqual(self.reached(), [self.card])
        self.assertEqual((self.batch(2), self.fake.stops, self.blocked()), (["c12"], [], ""))


class NotIdleTest(SettleCase):
    """The idle close is refused for a reason, so the re-offer is ended with a note giving
    it: never a stop, never a block, and the batch is told on that same pass."""

    def test_a_house_holding_a_job_of_its_own_is_told_at_once_with_a_note(self):
        self.re_offered()
        self.a_reviewer_writes()
        self.turn_ends()                                     # c11 left unjudged
        self.a_job_of_its_own()
        self.assertEqual(self.watch(), [self.card])
        self.ended_by_note(A_JOB)
        self.assertEqual(self.batch(2), ["c12"])
        self.idle_adds_nothing()
        self.job.unlink()                                    # the job ends, and the house idles
        self.live()
        self.assertEqual(self.reached(), [])
        self.assertEqual((self.fake.stops, self.blocked()), ([], ""), "an ordinary house now: the two-hour rule")

    def test_with_every_item_judged_nothing_is_said_of_the_re_offer(self):
        self.re_offered()
        self.a_reviewer_writes()
        self.verdict("c11", "not-valid", reply="It is the page size.")
        self.turn_ends()
        self.a_job_of_its_own()
        said = len(self.notes())
        self.assertEqual(self.reached(), [self.card])
        self.assertTrue(self.mark().get("done_at"))
        self.assertEqual(len(self.notes()), said + 1, "the one note is the newer batch's own")
        self.assertEqual((self.fake.stops, self.blocked()), ([], ""))

    def test_no_slot_and_a_paused_drain_settle_nothing_tell_nothing_and_lose_nothing(self):
        self.re_offered()
        self.board.send_back(self.card, "human", WORDS)
        self.a_reviewer_writes()
        self.turn_ends()
        self.a_job_of_its_own()
        self.assertEqual(self.reached(slots=0), [])
        self.cfg.drain_paused = True
        self.assertEqual(self.reached(), [])
        self.unsettled()
        self.assertEqual((self.asked(), self.handles("pending")), (["his-1"], ["c12"]))
        self.cfg.drain_paused = False
        self.assertEqual(self.reached(), [self.card])
        self.assertEqual(self.batch(2), ["c12", "his-1"])

    def test_a_re_offer_that_lands_mid_pass_is_kept_and_its_fresh_mark_carries_nothing_over(self):
        self.re_offered()
        self.a_reviewer_writes()
        self.turn_ends()                                     # c11 left unjudged
        self.a_job_of_its_own()
        mark_reoffer = self.board.mark_reoffer

        def asked_meanwhile(*args, **kwargs):
            self.board.reoffer(self.card, "human")
            return mark_reoffer(*args, **kwargs)
        with mock.patch.object(self.board, "mark_reoffer", side_effect=asked_meanwhile):
            self.assertEqual(self.reached(), [self.card])
        self.assertIn("reoffer", self.board.get(self.card)["options"], "his ask is still on the card")
        self.assertEqual(self.batch(2), ["c12"])
        self.assertEqual(self.reached(), [self.card])
        self.assertEqual(self.batch(3), ["c11"])
        self.assertEqual(sorted(set(self.mark()) & {"done_at", "closed_at", "unjudged", "deferred"}), [])
        self.assertEqual(self.mark()["batch"], 3)

    def test_a_house_open_in_a_terminal_says_once_that_the_batch_waits_for_it(self):
        """Review F5: the owner's ask no longer waits on the re-offer, but nothing is told
        into a terminal by anyone (`house.InTerminal`), and that wait was silent."""
        self.re_offered()
        self.board.send_back(self.card, "human", WORDS)
        self.turn_ends()                                     # c11 left unjudged
        self.fake.rows[0]["kind"] = dropin.INTERACTIVE
        self.assertEqual(self.reached() + self.reached() + self.reached(), [])
        self.ended_by_note(A_TERMINAL)
        self.assertEqual((self.asked(), self.handles("pending")), ([], ["his-1"]), "his ask is in the batch")
        self.assertEqual(self.notes().count(shipping.IN_TERMINAL_NOTE), 1, "said once, not every pass")
        self.fake.rows = []                                  # the owner quit it there
        self.assertEqual(self.reached(), [self.card])
        self.assertEqual((self.batch(2), self.fake.stops), (["his-1"], []))



class RefusedCloseTest(SettleCase):
    """Review F2 and F5: what the early settlement does is decided by the KIND of the
    close's refusal, never by its words."""

    def due_with_the_turn_ended(self) -> None:
        self.re_offered()
        self.a_reviewer_writes()
        self.turn_ends()                                     # c11 left unjudged
        self.live()

    def test_a_failed_stop_said_under_the_engines_earlier_name_is_not_said_again(self):
        """c-699 review F9: the note is said once by comparing it with what the card holds,
        and a card may hold it as the earlier release worded it."""
        self.due_with_the_turn_ended()
        earlier = EARLIER_STOP_FAILED
        self.assertNotEqual(earlier, STOP_FAILED)
        self.board.note(self.card, earlier, "drain")
        self.fake.stop_fails = True
        self.assertEqual(self.reached() + self.reached(), [])
        self.assertEqual((self.notes().count(earlier), self.notes().count(STOP_FAILED)), (1, 0))

    def test_a_stop_that_fails_settles_nothing_and_is_tried_again(self):
        self.due_with_the_turn_ended()
        said = len(self.notes())
        self.fake.stop_fails = True
        self.assertEqual(self.reached() + self.reached(), [])
        self.open()
        self.assertEqual(self.notes().count(STOP_FAILED), 1, "said on the card, once")
        self.assertNotIn("told once the stop", shipidle.STOP_FAILED_NOTE, "no tell is promised: c11 is unjudged, so it blocks")
        self.assertEqual((len(self.notes()), self.handles("pending")), (said + 1, ["c12"]))
        self.fake.stop_fails, self.fake.stops = False, []
        self.assertEqual(self.reached(), [])
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        self.assertIn("c11", self.blocked())

    def test_a_house_that_starts_working_between_the_two_listings_is_left_to_its_turn(self):
        self.due_with_the_turn_ended()
        said = len(self.notes())
        busy = [background_row(self.card, SESSION, status="busy")]

        def working(_strict):
            self.fake.rows = busy
            return busy
        with self.listings(working):
            self.assertEqual(self.reached(), [], "the batch waits for that turn, as any batch")
        self.open()
        self.assertEqual((self.fake.stops, len(self.notes()), self.handles("pending")), ([], said, ["c12"]))
        self.turn_ends()
        self.live()
        self.assertEqual(self.reached(), [])
        self.assertEqual(self.fake.stops, [SESSION[:8]], "that turn over, the re-offer is settled as ever")

    def test_a_listing_that_fails_inside_the_close_settles_nothing(self):
        self.due_with_the_turn_ended()

        def failed(strict):
            if strict:
                raise harness.HarnessError("claude agents exited 1")
            return []
        with self.listings(failed):
            self.assertEqual(self.watch(), [])
        self.open()
        self.assertEqual((self.fake.stops, self.handles("pending")), ([], ["c12"]))

    def test_a_refusal_the_plan_does_not_name_writes_nothing_and_holds_nothing(self):
        """A message on its way to the house: the mark is left as it is, and the batch goes
        on to `deliver`, which does with it what it does on a card with no re-offer."""
        self.due_with_the_turn_ended()
        said = len(self.notes())
        tellhouse.mark_telling(self.cfg, self.card)
        self.assertEqual(self.watch(), [self.card])
        mark = self.mark()
        self.assertEqual((mark.get("closed_at"), mark.get("done_at"), self.fake.stops, self.blocked()),
                         (None, None, [], ""))
        self.assertEqual((self.batch(2), len(self.notes())), (["c12"], said + 1))


class OnePassTest(SettleCase):
    def closed_as_idle(self) -> int:
        return len([event for event in self.board.events(self.card)
                    if event["kind"] == "note" and (event.get("data") or {}).get("stop") == "idle"])

    def test_a_house_the_watcher_closed_is_not_closed_again_by_the_two_hour_rule(self):
        """Review F3: the idle step reads the pass's own listing, taken before the watcher's
        stop, and the harness can go on listing a stopped session for a moment."""
        self.re_offered()
        self.a_reviewer_writes()
        self.verdict("c11", "not-valid", reply="It is the page size.")
        self.turn_ends()
        self.live()
        notes = self.closed_as_idle()

        def still_listed(bg_id, config_dir=None):
            self.fake.stops.append(bg_id)
        with mock.patch.object(self.fake, "stop", side_effect=still_listed):
            self.assertEqual(self.watch(), [])
            # by the board's clock that turn ended over two hours before this idle step
            self.idle(at=datetime.now(timezone.utc) + timedelta(hours=3))
        self.assertEqual((self.fake.stops, self.closed_as_idle()), ([SESSION[:8]], notes + 1))

    def test_one_drain_pass_stops_a_re_offered_house_once(self):
        """Review pass 3, F2: the same, through `drain.once`, which is where the watcher's
        closed houses join the idle step's skips."""
        self.re_offered()
        self.a_reviewer_writes()
        self.verdict("c11", "not-valid", reply="It is the page size.")
        self.turn_ends()
        self.live()
        notes = self.closed_as_idle()

        def still_listed(bg_id, config_dir=None):
            self.fake.stops.append(bg_id)
        late = datetime.now(timezone.utc) + timedelta(hours=3)
        with mock.patch.object(self.fake, "stop", side_effect=still_listed), \
                mock.patch.object(shipping, "now", return_value=self.at + timedelta(minutes=1)), \
                mock.patch.object(shipidle, "now", return_value=late):
            drain.once(self.cfg, board=self.board)
        self.assertEqual((self.fake.stops, self.closed_as_idle()), ([SESSION[:8]], notes + 1))

    def test_a_card_skipped_on_two_passes_running_is_settled_on_the_first_that_does_not(self):
        self.re_offered()
        self.a_reviewer_writes()
        self.turn_ends()
        self.live()
        for _ in range(2):
            self.assertEqual(self.watch(skip={self.card}), [])
            self.idle(skip={self.card})
            self.open()
        self.assertEqual(self.handles("pending"), ["c12"])
        self.assertEqual(self.reached(), [])
        self.assertEqual(self.fake.stops, [SESSION[:8]])

    def test_the_drain_hands_the_watcher_its_skips_and_takes_back_what_it_closed(self):
        self.re_offered()
        self.a_reviewer_writes()
        self.turn_ends()
        self.live()
        live, gate = {drain.HOUSE_SLOT: 0}, drain.MemoryGate(self.cfg)
        self.at += timedelta(minutes=1)
        with mock.patch.object(shipping, "now", return_value=self.at):
            closed = set()
            self.assertEqual(drain.ship_upkeep(self.cfg, self.board, {"work"}, live, gate, {self.card}, closed), 0)
            self.open()
            self.assertEqual((self.fake.stops, closed), ([], set()), "a skipped card is left alone")
            self.assertEqual(drain.ship_upkeep(self.cfg, self.board, {"work"}, live, gate, set(), closed), 0)
        self.assertEqual((self.fake.stops, closed), ([SESSION[:8]], {self.card}))


if __name__ == "__main__":
    import unittest
    unittest.main()
