"""A research card's outcome IS the research (c-719): one file, `kind: research`, its own
light contract (Findings, What it means, What is next, Evidence), told to the house on the
personal side here and on the work side in its pack, and known on the deck by the card's
kind on either side."""

import json
import shutil
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from keel import authority, deckstate, house, planbrief, planformat, plangate, planlint, planroute
from keel.board import Refused
from keel.review import gate as review_gate
from tests.helpers import SESSION
from tests.test_serve import DeckCase, ServerCase

ROOT = Path(__file__).resolve().parent.parent


class SkeletonTest(unittest.TestCase):
    def test_a_research_card_starts_with_a_research_outcome(self):
        card = {"id": "c-1", "title": "What the costs come to", "options": {"kind": "research"}}
        text = planbrief.context_skeleton(card, True)
        doc = planformat.parse(text, "context.md")
        self.assertEqual(doc["kind"], "research")
        self.assertEqual([s["text"] for s in doc["sections"]],
                         list(planbrief.RESEARCH_SECTIONS))
        self.assertIn("no separate report file", text)
        found = planlint.lint(doc)["findings"]
        self.assertTrue(found and all(f["rule"] == "C26" for f in found))

    def test_any_other_card_starts_with_the_outcome_it_always_did(self):
        text = planbrief.context_skeleton({"id": "c-2", "title": "t", "options": {"kind": "feature"}}, True)
        self.assertEqual(planformat.parse(text, "context.md")["kind"], "outcome")
        for heading in planbrief.CONTEXT_SECTIONS:
            self.assertIn(f"## {heading}\n", text)


class BriefTest(unittest.TestCase):
    def test_the_brief_and_the_card_say_the_research_is_the_outcome(self):
        for text in (planbrief.plan_block(True), (ROOT / "docs" / "plan-format.md").read_text()):
            flat = " ".join(text.split())
            self.assertIn("kind: research", flat)
            self.assertIn("no separate report file", flat)

    def test_a_card_whose_brief_names_its_output_keeps_it(self):
        """r1.F5: context.md as the output is for research, plans and errands without one; a
        tier or flow proposal still stages with the file its brief names."""
        flat = " ".join((ROOT / "etc" / "space-personal.md").read_text().split())
        self.assertIn("A card whose own brief names its output file", flat)
        self.assertIn("stages with that file", flat)

    def test_the_personal_space_says_so(self):
        flat = " ".join((ROOT / "etc" / "space-personal.md").read_text().split())
        self.assertIn("kind: research", flat)
        self.assertIn("no separate report file", flat)


class DeckTest(ServerCase):
    def setUp(self):
        super().setUp()
        self.card = self.board.create("work", "what the costs come to", autonomy="autonomous", actor="human")
        self.board.set_fields(self.card, {"options": {"kind": "research"}}, "human")
        (self.cfg.card_dir(self.card) / "context.md").write_text(
            "---\nkind: research\n---\n# t\n\nThe agent costs a **third** of the pilot.\n\n## Findings\n\n"
            "| run | cost |\n|---|---|\n| r1 | 0.40 |\n\n## What it means\n\nx\n\n"
            "## What is next\n\ny\n\n## Evidence\n\n- [bill](https://example.com)\n")

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_outcome_pages_send_panel_says_done_from_the_real_payload(self):
        """r1.F9: drawn from the route's own answer, so `card.kind` reaching the page is held."""
        b = self.board
        plan = self.cfg.card_dir(self.card) / "plan.md"
        plan.write_text("---\nkind: plan\n---\n# p\n")
        b.stage(self.card, "assigned", "human")
        b.stage(self.card, "building", "house")
        b.stage(self.card, "review", "house", plan_ref=str(plan), output_ref="https://example.com/board/b-1")
        with mock.patch.object(deckstate, "adapter_links_of", return_value={}):
            body = self.get_json(f"/api/plan/{self.card}?doc=outcome")
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "outcome.json"
            data.write_text(json.dumps(body))
            done = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "research-send.js"), str(ROOT / "app"), str(data)],
                                  capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), {"ok": True})

    def test_the_outcome_page_knows_the_cards_kind(self):
        body = self.get_json(f"/api/plan/{self.card}?doc=outcome")
        self.assertEqual(body["card"]["kind"], "research")
        self.assertEqual(body["doc"]["kind"], "research")

    def test_the_pane_says_what_the_research_found_in_its_own_words(self):
        """Its lede, plain, never the Findings section's raw markdown (a table read as pipes)."""
        with mock.patch.object(deckstate, "adapter_links_of", return_value={}):
            detail = self.get_json(f"/api/card/{self.card}")
        self.assertEqual(detail["findings"], "The agent costs a third of the pilot.")


RESEARCH_RECORD = ("---\nkind: research\n---\n# t\n\nwhat it found\n\n## Findings\n\nf\n\n## What it means\n\nm\n\n"
                   "## What is next\n\nn\n\n## Evidence\n\n- [bill](https://example.com)\n")


class KindFollowsTheCardTest(DeckCase):
    """r1.F1: a card's record is held to the CARD's contract. `kind: research` (or `report`) on
    the context.md of a card that is not research is linted as the outcome it is, with its
    Risk and its boards when it ships, and the mismatch is named."""

    def shipping_card(self):
        card = self.board.create("personal", "a change", repo="keel", actor="human")
        self.board.set_fields(card, {"session_id": SESSION, "options": {review_gate.SESSION_OPTION: SESSION}}, "human")
        (self.cfg.card_dir(card) / "context.md").write_text(RESEARCH_RECORD)
        got = self.board.get(card)
        self.assertTrue(review_gate.started_with_pipeline(got))
        return got

    def test_stage_review_refuses_a_shipping_cards_record_that_says_research(self):
        card = self.shipping_card()
        result = plangate.lint_file(self.cfg.card_dir(card["id"]) / "context.md", card)
        lines = planlint.lines_of(result)
        self.assertFalse(result["ok"])
        self.assertTrue(any("is not a research card" in line for line in lines), lines)
        self.assertTrue(any(line.startswith("C27 error") for line in lines), lines)
        with self.assertRaises(Refused):
            plangate.refuse_on_findings(result, "record")
        for kind in ("report",):
            (self.cfg.card_dir(card["id"]) / "context.md").write_text(RESEARCH_RECORD.replace("kind: research", f"kind: {kind}"))
            self.assertFalse(plangate.lint_file(self.cfg.card_dir(card["id"]) / "context.md", card)["ok"])

    def test_the_approve_check_refuses_it_too(self):
        card = self.shipping_card()
        errors = authority.outcome_facts(self.cfg, card)["errors"]
        self.assertTrue(any("is not a research card" in e for e in errors), errors)

    def test_a_card_with_no_repo_may_write_a_research_outcome(self):
        """It ships no code: a personal errand or research card, which the deck reads as research."""
        card = self.board.create("personal", "an errand", actor="human")
        (self.cfg.card_dir(card) / "context.md").write_text(RESEARCH_RECORD)
        result = plangate.lint_file(self.cfg.card_dir(card) / "context.md", self.board.get(card))
        self.assertTrue(result["ok"], planlint.lines_of(result))
        self.assertEqual(result["kind"], "research")

    def test_a_card_with_a_repo_that_is_not_research_still_gets_the_outcome_contract(self):
        card = self.board.create("personal", "a change", repo="keel", actor="human")
        (self.cfg.card_dir(card) / "context.md").write_text(RESEARCH_RECORD.replace("kind: research", "kind: report"))
        result = plangate.lint_file(self.cfg.card_dir(card) / "context.md", self.board.get(card))
        self.assertEqual(result["kind"], "outcome")
        self.assertTrue(any("is not a research card" in line for line in planlint.lines_of(result)))

    def stage(self, card, stage, plan=None):
        args = types.SimpleNamespace(verb="stage", stage=stage, id=card, plan=plan, output=None, nothing_to_land=False)
        got = self.board.get(card)
        return plangate.check_stage(args, lambda: dict(got, events=self.board.events(card)), self.cfg.cards_dir)

    def test_r2_f2_a_plan_saying_research_is_refused_at_kb_stage_planning(self):
        card = self.board.create("personal", "a change", repo="keel", actor="human")
        plan = self.cfg.card_dir(card) / "plan.md"
        for kind in ("research", "report"):
            plan.write_text(RESEARCH_RECORD.replace("kind: research", f"kind: {kind}"))
            with self.assertRaises(Refused) as caught:
                self.stage(card, "planning", str(plan))
            self.assertIn("C2 error: the plan says", str(caught.exception))
        # and on the plan page, read as a plan
        self.board.set_fields(card, {"plan_ref": str(plan)}, "human")
        body = planroute.payload(self.cfg, self.board, card, "plan")
        self.assertEqual(body["doc"]["kind"], "plan")
        self.assertTrue(any(f["rule"] == "C2" and "the plan says" in f["text"] for f in body["lint"]["findings"]))

    def test_fix_check_a_plan_saying_any_kind_but_plan_is_refused_at_kb_stage_planning(self):
        card = self.board.create("personal", "a change", repo="keel", actor="human")
        plan = self.cfg.card_dir(card) / "plan.md"
        for kind in ("outcome", "pr", "review"):
            plan.write_text(RESEARCH_RECORD.replace("kind: research", f"kind: {kind}"))
            with self.subTest(kind=kind), self.assertRaises(Refused) as caught:
                self.stage(card, "planning", str(plan))
            self.assertIn("C2 error: the plan says", str(caught.exception))

    def test_fix_check_a_review_cards_record_stays_a_review_on_its_row(self):
        from keel import planfacts
        card = self.board.create("work", "a review", actor="human")
        self.board.set_fields(card, {"options": {"kind": "review", "review_key": "api:1"}}, "human")
        (self.cfg.card_dir(card) / "context.md").write_text("---\nkind: review\n---\n# r\n\nwhat it does\n")
        facts = planfacts.doc_facts(self.cfg, self.board.get(card))["outcome"]
        self.assertEqual(facts["kind"], "review")

    def test_r2_f3_a_record_saying_any_other_kind_is_an_outcome(self):
        card = self.shipping_card()
        record = self.cfg.card_dir(card["id"]) / "context.md"
        for kind in ("pr", "plan", "review"):
            record.write_text(RESEARCH_RECORD.replace("kind: research", f"kind: {kind}"))
            lines = planlint.lines_of(plangate.lint_file(record, card))
            with self.subTest(kind=kind):
                self.assertTrue(any(line.startswith("C26 error: the record says") for line in lines), lines)
                self.assertTrue(any(line.startswith("C27 error") for line in lines), lines)

    def test_r2_f3_a_review_cards_record_keeps_its_review_kind(self):
        card = self.board.create("work", "a review", actor="human")
        self.board.set_fields(card, {"options": {"kind": "review"}}, "human")
        record = self.cfg.card_dir(card) / "context.md"
        record.write_text("---\nkind: review\n---\n# r\n\nwhat it does\n")
        result = plangate.lint_file(record, self.board.get(card))
        self.assertEqual(result["kind"], "review")
        self.assertFalse(any("the record says" in f["text"] for f in result["findings"]))

    def test_r2_f8_an_unclosed_comment_in_a_record_is_an_error(self):
        card = self.board.create("personal", "an errand", actor="human")
        record = self.cfg.card_dir(card) / "context.md"
        record.write_text(RESEARCH_RECORD.replace("## Findings", "<!-- never closed\n\n## Findings"))
        result = plangate.lint_file(record, self.board.get(card))
        self.assertFalse(result["ok"])
        self.assertTrue(any("never closes" in f["text"] and f["level"] == "error" for f in result["findings"]))
        other = planlint.lint(planformat.parse(RESEARCH_RECORD.replace("## Findings", "<!-- x\n\n## Findings"), "report.md"))
        self.assertTrue(any("never closes" in f["text"] and f["level"] == "warning" for f in other["findings"]))

    def test_r2_f10_the_rows_facts_hold_the_record_to_the_cards_contract(self):
        from keel import planfacts
        card = self.shipping_card()
        facts = planfacts.doc_facts(self.cfg, card)["outcome"]
        self.assertEqual(facts["kind"], "outcome")
        self.assertFalse(facts["ok"])

    def test_a_research_cards_record_keeps_its_light_contract(self):
        card = self.board.create("work", "costs", actor="human")
        self.board.set_fields(card, {"options": {"kind": "research"}}, "human")
        (self.cfg.card_dir(card) / "context.md").write_text(RESEARCH_RECORD)
        result = plangate.lint_file(self.cfg.card_dir(card) / "context.md", self.board.get(card))
        self.assertTrue(result["ok"], planlint.lines_of(result))

    def test_the_outcome_page_holds_it_to_the_cards_contract(self):
        card = self.shipping_card()
        body = planroute.payload(self.cfg, self.board, card["id"], "outcome")
        self.assertEqual(body["doc"]["kind"], "outcome")
        self.assertFalse(body["lint"]["ok"])
        self.assertTrue(any("is not a research card" in f["text"] for f in body["lint"]["findings"]))


if __name__ == "__main__":
    unittest.main()
