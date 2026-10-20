"""One full review per gate trip, and a delta check for the fixes (RD-1, 2026-09-25).

c-512 ran ten review rounds in one afternoon: every commit after a review was a new change
to review in full, each fresh reviewer found a few more low findings, the house fixed them,
committed, and went round again; and a resumed session with the same HEAD had to review
again because the stamp was the session's. His call: review like the old pipeline did,
once, and check the fixes.

- The stamp follows the CODE: the same HEAD, or the same change on a newer base, is
  reviewed whatever session asks.
- After a complete round, the house fixes what survived (or declines it), runs
  a bare `keel-review prep --since` (the reviewed heads, from the stamp), and calls ONLY the verifier on the delta:
  it says of each finding answered fixed whether it is, and names a regression the delta
  brought into the lines it touched. All fixed, and no high or critical regression: the
  stamp moves to the new HEAD. A low or medium regression becomes a finding to answer.
- A second FULL review is earned, not routine: never by the size of the fixes (2026-09-26),
  or one that fixes a high or critical finding, is not stamped by the delta check until the
  trip has had `FULL_ROUNDS_MAX` full rounds; after that the delta check always suffices,
  and what is still open goes to his gate in the outcome.
"""

import json
import subprocess
from unittest import mock

from keel.review import agents, prep, stamp
from tests.test_review_gate import GIT, HIGH, SESSION, StopHookCase, answer, sh

MEDIUM = dict(HIGH, severity="medium", claim="a guard is missing")


class DeltaCase(StopHookCase):
    full_max = stamp.FULL_ROUNDS_MAX

    def finished(self, card_id, worktree, agent, said, session=None, trip_rounds=0):
        return stamp.stamp(self.cfg, card_id, {
            "hook_event_name": "SubagentStop", "agent_type": agent, "cwd": str(worktree),
            "session_id": session or "d16f5891-new-session", "last_assistant_message": said},
            trip_rounds=trip_rounds, board=self.board, full_max=self.full_max)

    def reviewed_with(self, finding):
        card_id, worktree = self.at_review()
        card_dir = self.cfg.card_dir(card_id)
        prep.prepare(card_dir, "main", [worktree])
        self.finished(card_id, worktree, agents.REVIEWER, answer([finding]))
        self.finished(card_id, worktree, agents.VERIFIER,
                      answer([{"id": "r1.F1", "verify": "kept", "reason": "it holds"}]))
        reviewed = sh(worktree, "git", "rev-parse", "HEAD")
        prep.answer(card_dir, "r1.F1", "fixed", "")
        return card_id, worktree, card_dir, reviewed

    def fix(self, worktree, lines=1):
        (worktree / "thing.txt").write_text("the thing, guarded\n" + "".join(f"more {n}\n" for n in range(lines - 1)))
        sh(worktree, *GIT, "commit", "-q", "-am", "fix r1.F1")
        return sh(worktree, "git", "rev-parse", "HEAD")

    def delta(self, card_id, worktree, card_dir, reviewed, said, trip_rounds=1):
        prep.prepare(card_dir, "main", [worktree], since=reviewed)
        return self.finished(card_id, worktree, agents.VERIFIER, said, trip_rounds=trip_rounds)

    def stamped_head(self, card_id):
        return stamp.read_stamp(self.cfg, card_id).get("head")


class SessionTest(DeltaCase):
    def test_a_new_session_on_the_same_head_needs_no_second_review(self):
        card_id, worktree = self.at_review()
        self.finished(card_id, worktree, agents.REVIEWER, answer([]), session="an-older-session")
        self.assertNotIn(agents.REVIEWER, (self.stop(card_id, worktree) or {}).get("reason", ""))
        self.assertEqual(self.board.get(card_id)["stage"], "review")


class DeltaTest(DeltaCase):
    def test_a_fix_the_verifier_confirms_moves_the_stamp_without_a_second_review(self):
        card_id, worktree, card_dir, reviewed = self.reviewed_with(MEDIUM)
        head = self.fix(worktree)
        self.assertEqual(self.stop(card_id, worktree)["decision"], "block")
        self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="b @ 1")
        self.delta(card_id, worktree, card_dir, reviewed, answer([{"id": "r1.F1", "fixed": True, "reason": "guarded now"}]))
        self.assertEqual(self.stamped_head(card_id), head)
        self.assertNotIn(agents.REVIEWER, (self.stop(card_id, worktree) or {}).get("reason", ""))
        rounds = stamp.read_rounds(card_dir)
        self.assertEqual(len(rounds), 1, "no second review round")
        self.assertTrue(rounds[0]["deltas"][-1]["ok"])

    def test_a_fix_the_verifier_does_not_confirm_is_not_stamped(self):
        card_id, worktree, card_dir, reviewed = self.reviewed_with(MEDIUM)
        self.fix(worktree)
        self.delta(card_id, worktree, card_dir, reviewed, answer([{"id": "r1.F1", "fixed": False, "reason": "still unguarded"}]))
        self.assertEqual(self.stamped_head(card_id), reviewed)
        self.assertFalse(stamp.read_rounds(card_dir)[0]["deltas"][-1]["ok"])

    def test_a_low_regression_becomes_a_finding_to_answer_and_does_not_hold_the_stamp(self):
        card_id, worktree, card_dir, reviewed = self.reviewed_with(MEDIUM)
        head = self.fix(worktree)
        self.delta(card_id, worktree, card_dir, reviewed, answer([
            {"id": "r1.F1", "fixed": True, "reason": "guarded"},
            {"regression": True, "severity": "low", "path": "thing.txt", "line": 1,
             "claim": "a trailing comma", "evidence": "thing.txt:1"}]))
        self.assertEqual(self.stamped_head(card_id), head)
        ids = [one["id"] for one in stamp.read_rounds(card_dir)[0]["findings"]]
        self.assertIn("r1.D1", ids)

    def test_a_high_regression_holds_the_stamp(self):
        card_id, worktree, card_dir, reviewed = self.reviewed_with(MEDIUM)
        self.fix(worktree)
        self.delta(card_id, worktree, card_dir, reviewed, answer([
            {"id": "r1.F1", "fixed": True, "reason": "guarded"},
            {"regression": True, "severity": "high", "path": "thing.txt", "line": 1,
             "claim": "the thing is gone", "evidence": "thing.txt:1"}]))
        self.assertEqual(self.stamped_head(card_id), reviewed)


class EarnedTest(DeltaCase):
    def test_a_large_delta_of_medium_fixes_is_checked_not_reviewed_again(self):
        """2026-09-26, his call: the size of the fixes no longer earns a second full review
        (c-530's second round was earned by 300+ lines of fixes to medium and low findings)."""
        card_id, worktree, card_dir, reviewed = self.reviewed_with(MEDIUM)
        head = self.fix(worktree, lines=500)
        self.delta(card_id, worktree, card_dir, reviewed,
                   answer([{"id": "r1.F1", "fixed": True, "reason": "guarded"}]), trip_rounds=1)
        self.assertEqual(self.stamped_head(card_id), head)

    def test_a_fixed_high_needs_a_full_review_until_the_trip_has_had_two(self):
        card_id, worktree, card_dir, reviewed = self.reviewed_with(HIGH)
        head = self.fix(worktree)
        fixed = answer([{"id": "r1.F1", "fixed": True, "reason": "made"}])
        self.delta(card_id, worktree, card_dir, reviewed, fixed, trip_rounds=1)
        self.assertEqual(self.stamped_head(card_id), reviewed)
        self.assertIn("full review", stamp.read_rounds(card_dir)[0]["deltas"][-1]["why"])
        self.delta(card_id, worktree, card_dir, reviewed, fixed, trip_rounds=stamp.FULL_ROUNDS_MAX)
        self.assertEqual(self.stamped_head(card_id), head)

    def test_fixing_a_high_finding_needs_a_full_review_first(self):
        card_id, worktree, card_dir, reviewed = self.reviewed_with(HIGH)
        self.fix(worktree)
        self.delta(card_id, worktree, card_dir, reviewed, answer([{"id": "r1.F1", "fixed": True, "reason": "made"}]))
        self.assertEqual(self.stamped_head(card_id), reviewed)


class OneFullPassTest(DeltaCase):
    """c-597: a space whose `review_full_rounds` is 1 (work) has one full review pass per trip
    and then a fix check: a fixed high finding is confirmed by the verifier, never earned."""

    full_max = 1

    def test_a_fixed_high_is_confirmed_by_the_fix_check(self):
        card_id, worktree, card_dir, reviewed = self.reviewed_with(HIGH)
        head = self.fix(worktree)
        self.delta(card_id, worktree, card_dir, reviewed,
                   answer([{"id": "r1.F1", "fixed": True, "reason": "made"}]), trip_rounds=1)
        self.assertEqual(self.stamped_head(card_id), head)
        last = stamp.read_rounds(card_dir)[0]["deltas"][-1]
        self.assertEqual((last["ok"], last["earned"]), (True, False))
        self.assertEqual(len(stamp.read_rounds(card_dir)), 1, "no second full pass")
        self.assertIsNone(self.board.get(card_id)["blocked_reason"])

    def test_an_unconfirmed_fix_still_holds_the_stamp(self):
        card_id, worktree, card_dir, reviewed = self.reviewed_with(HIGH)
        self.fix(worktree)
        self.delta(card_id, worktree, card_dir, reviewed,
                   answer([{"id": "r1.F1", "fixed": False, "reason": "still missing"}]), trip_rounds=1)
        self.assertEqual(self.stamped_head(card_id), reviewed)

    def test_the_limit_is_the_card_s_space_s(self):
        self.cfg.spaces["work"].review_full_rounds = 1
        self.assertEqual(stamp.full_rounds_max(self.cfg, "work"), 1)
        self.assertEqual(stamp.full_rounds_max(self.cfg, "personal"), stamp.FULL_ROUNDS_MAX)
        self.assertEqual(stamp.full_rounds_max(self.cfg, None), stamp.FULL_ROUNDS_MAX)
        card_id = self.card()
        self.assertEqual(stamp.space_of(card_id, self.board), "personal")
        self.assertIsNone(stamp.space_of(card_id, None))


class EarnedLoopTest(DeltaCase):
    """c-522, 2026-09-26: after its first full review the house asked for a delta check six
    times, each refused with "a full review is earned" (324 to 424 lines, 1 of 2 full rounds),
    because the Stop hook's refusal kept saying `prep --since` and the verifier. The refusal
    now names the full review, and a second one at the same full-round count blocks the card."""

    def refused_large(self, trip_rounds=1):
        card_id, worktree, card_dir, reviewed = self.reviewed_with(HIGH)
        self.fix(worktree)
        fixed = answer([{"id": "r1.F1", "fixed": True, "reason": "guarded"}])
        self.delta(card_id, worktree, card_dir, reviewed, fixed, trip_rounds=trip_rounds)
        return card_id, worktree, card_dir, reviewed, fixed

    def test_the_refusal_names_a_full_prep_and_the_reviewer(self):
        card_id, _, card_dir, _, _ = self.refused_large()
        why = stamp.read_rounds(card_dir)[0]["deltas"][-1]["why"]
        self.assertIn(agents.REVIEWER, why)
        self.assertIn("WITHOUT --since", why)
        self.assertIn(f"**refused**, {why}", (card_dir / stamp.REVIEW_FILE).read_text())
        self.assertIsNone(self.board.get(card_id).get("blocked_reason"), "one refusal never blocks")

    def test_the_stop_hook_names_the_full_review_after_an_earned_refusal(self):
        card_id, worktree, _, _, _ = self.refused_large()
        reason = self.stop(card_id, worktree)["reason"]
        self.assertIn("full review is earned", reason)
        self.assertIn(agents.REVIEWER, reason)
        self.assertIn("WITHOUT --since", reason)
        self.assertNotIn("have ONLY", reason)

    def test_once_the_reviewer_has_started_a_round_the_stop_hook_stops_naming_it(self):
        card_id, worktree, _, _, _ = self.refused_large()
        self.finished(card_id, worktree, agents.REVIEWER, answer([MEDIUM]), session=SESSION)  # round 2, open
        reason = self.stop(card_id, worktree)["reason"]
        self.assertNotIn("full review is earned", reason)
        self.assertIn(f"call {agents.VERIFIER} on its findings, not a fix check", reason)
        self.assertNotIn("prep --since", reason)

    def test_an_open_round_of_an_earlier_session_asks_for_the_reviewer_again(self):
        card_id, worktree, _, _, _ = self.refused_large()
        self.finished(card_id, worktree, agents.REVIEWER, answer([MEDIUM]), session="an-older-session")
        reason = self.stop(card_id, worktree)["reason"]
        self.assertIn(f"call {agents.REVIEWER} again for a new pass", reason)
        self.assertNotIn(agents.VERIFIER + " on its findings", reason)

    def test_two_refusals_at_one_full_round_count_block_the_card(self):
        card_id, worktree, card_dir, reviewed, fixed = self.refused_large()
        (worktree / "more.txt").write_text("another fix\n")
        sh(worktree, *GIT, "add", "more.txt")
        sh(worktree, *GIT, "commit", "-q", "-m", "fix more")
        self.delta(card_id, worktree, card_dir, reviewed, fixed, trip_rounds=1)
        card = self.board.get(card_id)
        self.assertIn(agents.REVIEWER, card["blocked_reason"])
        self.assertIn("WITHOUT --since", card["blocked_reason"])
        self.assertEqual(self.stamped_head(card_id), reviewed)
        blocks = [e for e in self.board.events(card_id, last=0) if e.get("kind") == "block"]
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].get("data"), {"limit": "review"})

    def test_a_smaller_delta_from_a_newer_since_is_still_refused_and_blocks(self):
        card_id, worktree, card_dir, reviewed, fixed = self.refused_large()
        newer = sh(worktree, "git", "rev-parse", "HEAD")
        (worktree / "more.txt").write_text("a small fix\n")
        sh(worktree, *GIT, "add", "more.txt")
        sh(worktree, *GIT, "commit", "-q", "-m", "fix a little")
        self.delta(card_id, worktree, card_dir, newer, fixed, trip_rounds=1)
        self.assertEqual(self.stamped_head(card_id), reviewed)
        self.assertIn("full review is earned", stamp.read_rounds(card_dir)[0]["deltas"][-1]["why"])
        self.assertIn(agents.REVIEWER, self.board.get(card_id)["blocked_reason"])

    def test_a_second_refusal_for_a_fixed_high_finding_blocks(self):
        card_id, worktree, card_dir, reviewed = self.reviewed_with(HIGH)
        self.fix(worktree)
        fixed = answer([{"id": "r1.F1", "fixed": True, "reason": "made"}])
        self.delta(card_id, worktree, card_dir, reviewed, fixed, trip_rounds=1)
        self.assertIsNone(self.board.get(card_id).get("blocked_reason"))
        self.delta(card_id, worktree, card_dir, reviewed, fixed, trip_rounds=1)
        self.assertIn("high or critical", self.board.get(card_id)["blocked_reason"])

    def test_a_card_already_blocked_keeps_its_reason(self):
        card_id, worktree, card_dir, reviewed, fixed = self.refused_large()
        self.board.block(card_id, "his own reason", "human")
        self.delta(card_id, worktree, card_dir, reviewed, fixed, trip_rounds=1)
        self.assertEqual(self.board.get(card_id)["blocked_reason"], "his own reason")
        blocks = [e for e in self.board.events(card_id, last=0) if e.get("kind") == "block"]
        self.assertEqual(len(blocks), 1)

    def test_with_no_board_a_repeat_is_recorded_and_nothing_fails(self):
        card_id, worktree, card_dir, reviewed, fixed = self.refused_large()
        prep.prepare(card_dir, "main", [worktree], since=reviewed)
        stamp.stamp(self.cfg, card_id, {
            "hook_event_name": "SubagentStop", "agent_type": agents.VERIFIER, "cwd": str(worktree),
            "session_id": "s", "last_assistant_message": fixed}, trip_rounds=1, board=None)
        self.assertTrue(stamp.read_rounds(card_dir)[0]["deltas"][-1]["repeat"])
        self.assertIsNone(self.board.get(card_id).get("blocked_reason"))

    def test_the_hook_binary_counts_the_trip_and_blocks_on_its_own_board(self):
        card_id, worktree, card_dir, reviewed = self.reviewed_with(HIGH)
        self.fix(worktree)
        prep.prepare(card_dir, "main", [worktree], since=reviewed)
        payload = json.dumps({"hook_event_name": "SubagentStop", "agent_type": agents.VERIFIER,
                              "cwd": str(worktree), "session_id": "s", "last_assistant_message":
                              answer([{"id": "r1.F1", "fixed": True, "reason": "guarded"}])})
        for _ in range(2):
            with mock.patch("keel.config.load", return_value=self.cfg), \
                    mock.patch("sys.stdin", mock.Mock(read=lambda: payload)):
                self.assertEqual(stamp.stamp_main([card_id]), 0)
        deltas = stamp.read_rounds(card_dir)[0]["deltas"]
        self.assertEqual([one["full_rounds"] for one in deltas], [1, 1])
        self.assertIn(agents.REVIEWER, self.board.get(card_id)["blocked_reason"])

    def test_refusals_at_different_full_round_counts_do_not_block(self):
        card_id, worktree, card_dir, reviewed, fixed = self.refused_large(trip_rounds=0)
        self.delta(card_id, worktree, card_dir, reviewed, fixed, trip_rounds=1)
        self.assertIsNone(self.board.get(card_id).get("blocked_reason"))

    def test_a_refusal_recorded_before_the_count_was_kept_never_counts(self):
        card_id, worktree, card_dir, reviewed, fixed = self.refused_large()
        rounds = stamp.read_rounds(card_dir)
        for record in rounds[0]["deltas"]:
            record.pop("full_rounds", None)
        stamp.save_rounds(card_dir, rounds)
        self.delta(card_id, worktree, card_dir, reviewed, fixed, trip_rounds=1)
        self.assertIsNone(self.board.get(card_id).get("blocked_reason"))


class LimitClearsTest(DeltaCase):
    """r-16, c-538: c-524 was blocked `review-limit` at 18:23, ran the earned full review at
    18:34 to 18:36, and still read blocked while building until Bosun unblocked it. The hook
    that set the mark clears it when the round it asked for writes the stamp: only that
    mark, and only while the card is still blocked with it."""

    def looped(self):
        card_id, worktree, card_dir, reviewed = self.reviewed_with(HIGH)
        self.fix(worktree)
        fixed = answer([{"id": "r1.F1", "fixed": True, "reason": "guarded"}])
        self.delta(card_id, worktree, card_dir, reviewed, fixed, trip_rounds=1)
        self.delta(card_id, worktree, card_dir, reviewed, fixed, trip_rounds=1)
        self.assertIn("full review is earned", self.board.get(card_id)["blocked_reason"])
        return card_id, worktree, card_dir

    def full_round(self, card_id, worktree, card_dir, found=()):
        prep.prepare(card_dir, "main", [worktree])
        return self.finished(card_id, worktree, agents.REVIEWER, answer(list(found)), trip_rounds=1)

    def test_the_earned_full_round_clears_its_own_block(self):
        card_id, worktree, card_dir = self.looped()
        self.assertIsNotNone(self.full_round(card_id, worktree, card_dir))
        self.assertIsNone(self.board.get(card_id).get("blocked_reason"))
        self.assertEqual(self.stamped_head(card_id), sh(worktree, "git", "rev-parse", "HEAD"))
        unblocks = [e for e in self.board.events(card_id, last=0) if e.get("kind") == "unblock"]
        self.assertEqual([e["actor"] for e in unblocks], ["hook"])

    def test_a_round_still_open_leaves_the_block(self):
        card_id, worktree, card_dir = self.looped()
        self.assertIsNone(self.full_round(card_id, worktree, card_dir, found=[MEDIUM]))
        self.assertIn("full review is earned", self.board.get(card_id)["blocked_reason"])
        self.finished(card_id, worktree, agents.VERIFIER,
                      answer([{"id": "r2.F1", "verify": "kept", "reason": "it holds"}]))
        self.assertIsNone(self.board.get(card_id).get("blocked_reason"))

    def test_another_block_is_never_cleared(self):
        card_id, worktree, card_dir = self.looped()
        self.board.block(card_id, "his own reason", "human")
        self.full_round(card_id, worktree, card_dir)
        self.assertEqual(self.board.get(card_id)["blocked_reason"], "his own reason")

    def test_a_card_blocked_for_anything_else_is_left_alone(self):
        card_id, worktree = self.at_review()
        self.board.block(card_id, "waiting on his answer", "house")
        self.full_round(card_id, worktree, self.cfg.card_dir(card_id))
        self.assertEqual(self.board.get(card_id)["blocked_reason"], "waiting on his answer")

    def test_the_stop_hook_s_own_limit_clears_too(self):
        card_id, worktree = self.at_review()
        self.board.block(card_id, "the review step still has no stamp for HEAD after 2 asks: x",
                         "hook", mark="review-limit")
        self.full_round(card_id, worktree, self.cfg.card_dir(card_id))
        self.assertIsNone(self.board.get(card_id).get("blocked_reason"))

    def test_with_no_board_nothing_fails(self):
        card_id, worktree, card_dir = self.looped()
        prep.prepare(card_dir, "main", [worktree])
        self.assertIsNotNone(stamp.stamp(self.cfg, card_id, {
            "hook_event_name": "SubagentStop", "agent_type": agents.REVIEWER, "cwd": str(worktree),
            "session_id": "s", "last_assistant_message": answer([])}, trip_rounds=1, board=None))


class AnswerRoundTest(DeltaCase):
    """c-512, 2026-09-25: after pass 8, six started passes never closed, and `keel-review
    answer` refused r8's ids while `kb stage review` wanted them answered. Since c-581 both
    read the NEWEST pass and refuse an open one with its step, so the two always agree and
    an open pass is finished rather than hidden (c-272 hid one behind an older closed pass)."""

    def test_answer_names_the_step_an_open_pass_needs(self):
        card_id, worktree, card_dir, reviewed = self.reviewed_with(MEDIUM)
        self.finished(card_id, worktree, agents.REVIEWER, "no schema here")        # pass 2, unparsed
        with self.assertRaises(prep.PrepError) as caught:
            prep.answer(card_dir, "r1.F1", "declined", "not worth it")
        self.assertIn(f"call {agents.REVIEWER} again", str(caught.exception))
        self.finished(card_id, worktree, agents.REVIEWER, answer([dict(MEDIUM, id="F1")]))  # pass 3, open
        with self.assertRaises(prep.PrepError) as caught:
            prep.answer(card_dir, "r3.F1", "fixed", "")
        self.assertIn(f"call {agents.VERIFIER}", str(caught.exception))
        self.finished(card_id, worktree, agents.VERIFIER,
                      answer([{"id": "r3.F1", "verify": "kept", "reason": "it holds"}]))
        prep.answer(card_dir, "r3.F1", "declined", "not worth it")
        self.assertEqual(stamp.read_answers(card_dir)["r3.F1"]["did"], "declined")


class PrepSinceTest(DeltaCase):
    def test_prep_since_records_what_the_delta_is_measured_from(self):
        card_id, worktree, card_dir, reviewed = self.reviewed_with(MEDIUM)
        self.fix(worktree)
        prep.prepare(card_dir, "main", [worktree], since=reviewed)
        self.assertEqual(stamp.read_json(card_dir / stamp.PREP_FILE, {})["since"], reviewed)
        prep.prepare(card_dir, "main", [worktree])
        self.assertNotIn("since", stamp.read_json(card_dir / stamp.PREP_FILE, {}))


if __name__ == "__main__":
    import unittest
    unittest.main()
