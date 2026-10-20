"""ending: the turn-end half of the Stop hook. The record at the outcome gate is checked
once and once only, a background task still means wait, and a discussion flag is cleared
when the turn that held it ends."""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import briefnews, ending
from keel.board import Board
from tests.helpers import make_config, own_options

FULL = """\
## Where it stands

The rename is in and the suite is green.

## What is next

The human's tap on the outcome gate.

## Why this shape

One helper, because both callers need it.

## Open questions

None left.

## Evidence

![the deck at 1440](assets/deck-1440.png)

## PR body

The body.
"""

TEMPLATE = "".join(f"## {heading}\n\n" for heading in ending.RECORD_SECTIONS)


class RecordReadingTest(unittest.TestCase):
    def test_a_finished_record_has_no_gaps(self):
        self.assertEqual(ending.record_gaps(FULL), [])

    def test_the_template_is_five_gaps_in_the_record_s_own_order(self):
        gaps = ending.record_gaps(TEMPLATE)
        self.assertEqual(len(gaps), 5)
        self.assertTrue(gaps[0].startswith("Where it stands"))
        self.assertIn(ending.EVIDENCE_GAP, gaps)

    def test_a_missing_section_and_a_placeholder_both_count(self):
        text = FULL.replace("## Open questions\n\nNone left.\n", "").replace("None left.", "TBD")
        gaps = ending.record_gaps(text)
        self.assertEqual(gaps, ["Open questions is missing"])
        self.assertEqual(ending.record_gaps(FULL.replace("None left.", "_TBD_")),
                         ["Open questions is empty"])

    def test_none_is_a_real_answer_to_open_questions_not_a_placeholder(self):
        self.assertEqual(ending.record_gaps(FULL.replace("None left.", "None")), [])
        self.assertEqual(ending.record_gaps(FULL.replace("None left.", "todo")),
                         ["Open questions is empty"])

    def test_evidence_counts_a_path_a_link_or_a_url_but_not_bare_prose(self):
        def evidence(body):
            return ending.record_gaps(FULL.replace("![the deck at 1440](assets/deck-1440.png)", body))
        self.assertEqual(evidence("See `state/cards/c-1/assets/shot.png`."), [])
        self.assertEqual(evidence("The draft pull request https://x.test/pr/1 is the evidence."), [])
        self.assertEqual(evidence("[the run](../logs/run.txt)"), [])
        self.assertEqual(evidence("I tested it by hand and it worked well."), [ending.EVIDENCE_GAP])


class HookCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.board.close)

    def at_review(self, context: str | None = TEMPLATE) -> str:
        card_id = self.board.create("personal", "a card", repo="keel")
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        if context is not None:
            (self.cfg.card_dir(card_id) / "context.md").write_text(context)
        self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="o.md")
        return card_id

    def check(self, card_id, payload=None):
        return ending.check(self.cfg, self.board, card_id, payload or {"hook_event_name": "Stop"})


class VoiceHoldTest(HookCase):
    """Guard 3's other half: neither rule here is about a sentence he is waiting to hear."""

    def test_a_held_card_is_left_alone_at_the_outcome_gate(self):
        card_id = self.at_review()
        self.board.hold_voice(card_id, 300, stopped=True)
        self.assertIsNone(self.check(card_id))
        self.assertNotIn(ending.NUDGE_OPTION, self.board.get(card_id)["options"])
        self.board.release_voice(card_id)
        self.assertEqual(self.check(card_id)["decision"], "block",
                         "the record nudge is only deferred, never skipped")


class RecordNudgeTest(HookCase):
    def test_a_blank_evidence_section_is_blocked_once_with_the_section_named(self):
        card_id = self.at_review(FULL.replace("![the deck at 1440](assets/deck-1440.png)\n", ""))
        decision = self.check(card_id)
        self.assertEqual(decision["decision"], "block")
        self.assertIn(ending.EVIDENCE_GAP, decision["reason"])
        self.assertIn("context.md", decision["reason"])
        self.assertTrue(self.board.get(card_id)["options"][ending.NUDGE_OPTION])
        note = self.board.events(card_id)[-1]
        self.assertEqual((note["kind"], note["actor"]), ("note", "hook"))
        self.assertIsNone(self.check(card_id), "the second Stop is never blocked again")

    def test_a_card_blocked_before_the_stop_still_gets_its_record_nudge(self):
        """The review gate hands a card to him only when IT blocked it this Stop; a card
        that was blocked already is nudged for its record as before."""
        card_id = self.at_review(FULL.replace("![the deck at 1440](assets/deck-1440.png)\n", ""))
        self.board.block(card_id, "outcome not merged: tests failed", "human")
        self.assertEqual(self.check(card_id)["decision"], "block")

    def test_evidence_without_an_artifact_names_the_screenshot_it_wants(self):
        card_id = self.at_review(FULL.replace("![the deck at 1440](assets/deck-1440.png)",
                                              "I ran it and watched it work."))
        reason = self.check(card_id)["reason"]
        self.assertIn("Evidence has no screenshot or artifact", reason)
        self.assertIn("![what it shows](assets/<file>)", reason)

    def test_a_finished_record_is_not_nudged_and_leaves_no_mark(self):
        card_id = self.at_review(FULL)
        self.assertIsNone(self.check(card_id))
        self.assertEqual(own_options(self.board.get(card_id)), {})

    def test_a_card_that_is_not_at_the_outcome_gate_is_left_alone(self):
        card_id = self.board.create("personal", "building away", repo="keel")
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        (self.cfg.card_dir(card_id) / "context.md").write_text(TEMPLATE)
        self.assertIsNone(self.check(card_id))

    def test_a_stop_with_a_running_background_task_is_a_wait_not_a_stop(self):
        card_id = self.at_review(TEMPLATE)
        payload = {"background_tasks": [{"id": "x", "type": "subagent", "status": "running"}]}
        self.assertIsNone(self.check(card_id, payload))
        self.assertEqual(own_options(self.board.get(card_id)), {})
        self.assertEqual(self.check(card_id)["decision"], "block")

    def test_a_card_with_no_context_file_at_all_is_nudged_for_every_section(self):
        card_id = self.at_review(context=None)
        reason = self.check(card_id)["reason"]
        for heading in ending.RECORD_SECTIONS[:-1]:
            self.assertIn(f"{heading} is missing", reason)

    def test_an_ask_card_is_exempt_because_its_record_is_the_drop(self):
        """`kb stop-check` filed it from the drop, and its house has no shell to answer
        a record nudge with."""
        card_id = self.at_review(context=None)
        self.board.set_fields(card_id, {"options": {"drop": "/tmp/worker.json"}}, "fetch")
        self.assertIsNone(self.check(card_id))
        self.assertNotIn(ending.NUDGE_OPTION, self.board.get(card_id)["options"])


class DiscussionFlagTest(HookCase):
    def test_the_flag_is_cleared_when_the_turn_that_held_it_ends(self):
        card_id = self.board.create("personal", "talking", repo="keel",
                                    options={ending.DISCUSSION_OPTION: True})
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "planning", "drain", plan_ref="plan.html")
        self.assertIsNone(self.check(card_id))
        self.assertFalse(self.board.get(card_id)["options"][ending.DISCUSSION_OPTION])
        self.assertEqual(self.board.events(card_id)[-1]["kind"], "set")

    def test_a_card_that_was_not_talking_is_not_written_to(self):
        card_id = self.board.create("personal", "quiet", repo="keel")
        before = self.board.get(card_id)["updated_at"]
        self.assertIsNone(self.check(card_id))
        self.assertEqual(self.board.get(card_id)["updated_at"], before)

    def test_a_discussion_that_ends_at_review_is_cleared_and_the_record_still_checked(self):
        card_id = self.at_review(TEMPLATE)
        self.board.set_fields(card_id, {"options": {ending.DISCUSSION_OPTION: True}}, "human")
        decision = self.check(card_id)
        options = self.board.get(card_id)["options"]
        self.assertFalse(options[ending.DISCUSSION_OPTION])
        self.assertTrue(options[ending.NUDGE_OPTION])
        self.assertEqual(decision["decision"], "block")


class CardNewsTest(HookCase):
    """c-533: a briefed field changed after the start reaches the live house at its turn end,
    once, and never on a turn it would not change."""

    def briefed(self, autonomy="attended", stage="planning") -> str:
        card_id = self.board.create("personal", "a card", repo="keel", autonomy=autonomy)
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, stage, "drain")
        brief = "# You are the house\n\n" + briefnews.card_block(self.board.get(card_id)) + "\n\n# Space\n"
        (self.cfg.card_dir(card_id) / "brief.md").write_text(brief)
        return card_id

    def test_autonomy_set_after_start_sends_the_planning_house_back_once(self):
        card_id = self.briefed()
        self.assertIsNone(self.check(card_id), "nothing changed, nothing said")
        self.board.set_fields(card_id, {"autonomy": "autonomous"}, "human")
        decision = self.check(card_id)
        self.assertEqual(decision["decision"], "block")
        self.assertIn("autonomy: attended -> autonomous", decision["reason"])
        brief = (self.cfg.card_dir(card_id) / "brief.md").read_text()
        self.assertIn('"autonomy": "autonomous"', brief)
        self.assertTrue(brief.endswith("# Space\n"), "the rest of the brief is kept")
        self.assertIn("told the house", self.board.events(card_id)[-1]["text"])
        self.assertIsNone(self.check(card_id), "said once")

    def test_news_waits_on_a_voice_hold_and_a_background_task(self):
        card_id = self.briefed(stage="building")
        self.board.set_fields(card_id, {"model": "sonnet"}, "human")
        self.assertIsNone(self.check(card_id, {"hook_event_name": "Stop",
                                               "background_tasks": [{"status": "running"}]}))
        self.board.hold_voice(card_id, 300, stopped=True)
        self.assertIsNone(self.check(card_id))
        self.board.release_voice(card_id)
        self.assertIn("model: opus -> sonnet", self.check(card_id)["reason"])

    def test_a_blocked_card_keeps_its_news_for_the_resume(self):
        card_id = self.briefed(stage="building")
        self.board.set_fields(card_id, {"title": "a new title"}, "human")
        self.board.block(card_id, "needs him", "house")
        self.assertIsNone(self.check(card_id))
        self.assertIn('"title": "a card"', (self.cfg.card_dir(card_id) / "brief.md").read_text())

    def test_a_field_the_house_set_itself_is_not_news(self):
        card_id = self.briefed(stage="building")
        self.board.set_fields(card_id, {"title": "the redirected title"}, "house")
        self.assertIsNone(self.check(card_id))
        self.board.set_fields(card_id, {"title": "his title"}, "human")
        self.assertIn("title: a card -> his title", self.check(card_id)["reason"])

    def test_a_failed_note_leaves_the_news_pending(self):
        card_id = self.briefed()
        self.board.set_fields(card_id, {"autonomy": "autonomous"}, "human")
        with mock.patch.object(self.board, "note", side_effect=OSError("board gone")):
            with self.assertRaises(OSError):
                self.check(card_id)
        self.assertIn('"autonomy": "attended"', (self.cfg.card_dir(card_id) / "brief.md").read_text())
        self.assertIn("autonomy: attended -> autonomous", self.check(card_id)["reason"])

    def test_a_card_with_no_brief_block_is_left_alone(self):
        card_id = self.briefed(stage="building")
        (self.cfg.card_dir(card_id) / "brief.md").write_text("an old brief\n")
        self.board.set_fields(card_id, {"title": "a new title"}, "human")
        self.assertIsNone(self.check(card_id))


class MainTest(HookCase):
    def run_main(self, argv, payload="{}"):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(payload)), \
             mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err), \
             mock.patch.object(ending.config_module, "load", return_value=self.cfg):
            code = ending.main(argv)
        return code, out.getvalue().strip(), err.getvalue().strip()

    def test_the_hook_prints_the_decision_and_always_exits_zero(self):
        card_id = self.at_review(TEMPLATE)
        code, out, err = self.run_main([card_id])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Evidence", json.loads(out)["reason"])
        self.assertEqual(self.run_main([card_id])[1], "", "the mark holds across processes")

    def test_a_broken_call_says_so_on_stderr_and_still_exits_zero(self):
        code, out, err = self.run_main(["c-999"])
        self.assertEqual((code, out), (0, ""))
        self.assertIn("no card c-999", err)
        self.assertEqual(self.run_main([])[0], 0)

    def test_unparsable_stdin_is_an_empty_payload_not_a_crash(self):
        card_id = self.at_review(TEMPLATE)
        code, out, _ = self.run_main([card_id], payload="not json at all")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["decision"], "block")


if __name__ == "__main__":
    unittest.main()


class MergingFlagTest(HookCase):
    """`options.merging` (the house was sent to merge main) clears at review, not at building."""

    def test_clears_when_the_house_is_back_at_review(self):
        card_id = self.at_review(context=None)
        self.board.set_fields(card_id, {"options": {ending.MERGING_OPTION: True}}, "serve")
        self.check(card_id)
        self.assertFalse(self.board.get(card_id)["options"].get(ending.MERGING_OPTION))

    def test_stays_while_still_building(self):
        card_id = self.board.create("personal", "a card", repo="keel")
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        self.board.set_fields(card_id, {"options": {ending.MERGING_OPTION: True}}, "serve")
        self.check(card_id)
        self.assertTrue(self.board.get(card_id)["options"].get(ending.MERGING_OPTION))

