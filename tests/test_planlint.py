"""The contract lint: each enforceable rule refuses the plan that breaks it, by name.

The rules that failed in practice were C4 (show the flow), C11 and C12 (put each doubt to
him as a question with options and a recommendation): c-208's plan named a recommendation
three times in prose and offered nothing to tap. Each has a red case here.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from keel import boards, plangate, planlint
from tests.helpers import make_config

# The fixture leaves its last question unanswered on purpose (the parser test reads that);
# here every question carries a recommendation, as the contract asks.
SAMPLE = (Path(__file__).parent / "fixtures" / "plan-sample.md").read_text().replace(
    "Does the outcome use the same page?", "Does the outcome use the same page? Recommend: yes.")


def resolve_all(path, start, end):
    return None


def rules(result, level="error"):
    return sorted({f["rule"] for f in result["findings"] if f["level"] == level})


class PlanLintTest(unittest.TestCase):
    def test_the_sample_passes(self):
        result = planlint.lint_text(SAMPLE, repo_card=True, resolve=resolve_all)
        self.assertTrue(result["ok"], planlint.lines_of(result))

    def test_c208_prose_recommendation_with_nothing_to_tap(self):
        text = SAMPLE.split("## Decisions")[0] + (
            "## Decisions\n\nI recommend the card, three times over.\n\n"
            "## Risks\n\n- x\n\n## Steps\n\n- a\n\n## Proof\n\n- b\n\n## Out of scope\n\n- c\n")
        result = planlint.lint_text(text, repo_card=True, resolve=resolve_all)
        self.assertFalse(result["ok"])
        self.assertIn("C11", rules(result))

    def test_decisions_none_with_a_reason_is_the_escape(self):
        text = SAMPLE.split("## Decisions")[0] + (
            "## Decisions\n\nNone: the card said exactly what to build.\n\n"
            "## Risks\n\n- x\n\n## Steps\n\n- a\n\n## Proof\n\n- b\n\n## Out of scope\n\n- c\n")
        result = planlint.lint_text(text, repo_card=True, resolve=resolve_all)
        self.assertNotIn("C11", rules(result))

    def test_c4_a_repo_card_with_no_flow(self):
        text = SAMPLE.replace("```mermaid", "```text").replace("```board The round, as the house pushed it\nb-1\n```\n", "")
        self.assertIn("C4", rules(planlint.lint_text(text, repo_card=True, resolve=resolve_all)))
        self.assertNotIn("C4", rules(planlint.lint_text(text, repo_card=False, resolve=resolve_all)))

    # P2-7: a real flow is a board the house pushes and embeds BY ID, so the board page
    # lists it under the card and one fix shows in both places.
    def without_board(self):
        text = SAMPLE.replace("```board The round, as the house pushed it\nb-1\n```\n", "")
        self.assertNotIn("b-1", text)
        return text

    def test_c4_mermaid_alone_is_a_finding_with_the_push_command(self):
        result = planlint.lint_text(self.without_board(), repo_card=True, resolve=resolve_all, card_id="c-900")
        c4 = [f for f in result["findings"] if f["rule"] == "C4"]
        self.assertEqual([f["level"] for f in c4], ["error"])
        self.assertIn("keel board push --card c-900", c4[0]["text"])
        self.assertIn("by id", c4[0]["text"])

    def test_c4_inline_board_ops_alone_are_a_finding_too(self):
        text = self.without_board().replace(
            "```mermaid The tap, end to end\nflowchart LR\n  phone([His phone]) -->|tap| deck[The deck]\n"
            "  deck --> db[(board.db)]\n  deck -. resume .-> house[The house]\n```",
            '```board The tap\nnode a phone "His phone"\nnode b server "The deck"\nedge a -> b\n```')
        self.assertIn('node a phone', text)
        self.assertIn("C4", rules(planlint.lint_text(text, repo_card=True, resolve=resolve_all)))

    def test_c4_a_board_embedded_by_id_satisfies_it(self):
        result = planlint.lint_text(SAMPLE, repo_card=True, resolve=resolve_all,
                                    board_of=lambda ref: None)
        self.assertNotIn("C4", rules(result))

    def test_c4_an_id_that_does_not_resolve_is_an_error_on_any_card(self):
        missing = lambda ref: f"no board called {ref}"
        for repo_card in (True, False):
            result = planlint.lint_text(SAMPLE, repo_card=repo_card, resolve=resolve_all, board_of=missing)
            c4 = [f for f in result["findings"] if f["rule"] == "C4"]
            self.assertEqual(len(c4), 1, c4)
            self.assertIn("`b-001` does not resolve", c4[0]["text"])
            self.assertEqual(c4[0]["level"], "error")
            self.assertIsNotNone(c4[0]["block"])

    def test_the_gate_resolves_ids_against_the_boards_here(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(Path(tmp))
            path = Path(tmp) / "plan.md"
            path.write_text(SAMPLE)
            card = {"id": "c-900", "repo": "keel"}
            result = plangate.lint_file(path, card, root=tmp, board_of=plangate.board_resolver(cfg))
            self.assertIn("`b-001` does not resolve", " ".join(planlint.lines_of(result)))
            boards.push(cfg, 'node a box "A"', card="c-900")
            result = plangate.lint_file(path, card, root=tmp, board_of=plangate.board_resolver(cfg))
            self.assertNotIn("C4", [f["rule"] for f in result["findings"]])

    def test_c12_a_question_with_no_recommendation(self):
        self.assertIn("C12", rules(planlint.lint_text(
            SAMPLE.replace("Recommend: yes, and say so on the card.", "?"), resolve=resolve_all)))

    def test_c11_c12_block_problems_refuse(self):
        text = SAMPLE.replace("  cost: a new event kind\n", "").replace("because: the board is the only state\n", "")
        result = planlint.lint_text(text, repo_card=True, resolve=resolve_all)
        self.assertIn("C11", rules(result))
        self.assertIn("C12", rules(result))

    def test_c1_no_summary(self):
        text = SAMPLE.replace("He is deciding where plan answers are stored and whether the deck sends them in one tap. Two decisions, one risk worth reading.\n", "")
        self.assertIn("C1", rules(planlint.lint_text(text, resolve=resolve_all)))

    def test_c2_missing_and_out_of_order(self):
        missing = SAMPLE.replace("## Goal\n", "## Background\n")
        self.assertIn("C2", rules(planlint.lint_text(missing, resolve=resolve_all)))
        swapped = SAMPLE.replace("## Risks", "## Riskz").replace("## Out of scope", "## Risks\n\n- y\n\n## Out of scope")
        self.assertIn("C2", rules(planlint.lint_text(swapped, resolve=resolve_all)))

    def test_c17_risks_none_needs_a_reason(self):
        bare = SAMPLE.replace("- **Risk:** an old deck reads an unknown event kind. **Mitigation:** the kind is added in one place.", "None.")
        self.assertIn("C17", rules(planlint.lint_text(bare, resolve=resolve_all)))
        reasoned = bare.replace("None.", "None: nothing here changes a running process.")
        self.assertNotIn("C17", rules(planlint.lint_text(reasoned, resolve=resolve_all)))

    def test_c18_a_repo_card_says_how_it_is_proved(self):
        text = SAMPLE.replace("## Proof", "## Also")
        self.assertIn("C18", rules(planlint.lint_text(text, repo_card=True, resolve=resolve_all)))

    def test_c8_code_names_its_file_and_why(self):
        text = SAMPLE.replace("```python keel/planstate.py:40-52 | where the prompt is composed", "```python")
        self.assertIn("C8", rules(planlint.lint_text(text, resolve=resolve_all)))

    def test_c20_a_table_without_its_line(self):
        text = SAMPLE.replace("Rows say which file changes and why:\n\n", "")
        self.assertIn("C20", rules(planlint.lint_text(text, resolve=resolve_all)))

    def test_c24_no_em_dashes(self):
        text = SAMPLE.replace("Two decisions,", "Two decisions " + chr(0x2014))
        self.assertIn("C24", rules(planlint.lint_text(text, resolve=resolve_all)))

    def test_c16_an_answered_decision_left_open(self):
        result = planlint.lint_text(SAMPLE, resolve=resolve_all, answered=["store"])
        self.assertIn("C16", rules(result))

    def test_c7_refs_resolve_at_head_of_a_real_checkout(self):
        with tempfile.TemporaryDirectory() as root:
            run = lambda *a: subprocess.run(["git", "-C", root, *a], check=True, capture_output=True)
            run("init", "-q", "-b", "main")
            Path(root, "keel").mkdir()
            Path(root, "keel", "prompts.py").write_text("\n".join(f"line {i}" for i in range(20)) + "\n")
            run("add", ".")
            run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
            result = planlint.lint_text(SAMPLE, resolve=planlint.GitResolver(Path(root)))
            texts = [f["text"] for f in result["findings"] if f["rule"] == "C7"]
            # prompts.py:12 exists; the code block's planstate.py:40-52 does not
            self.assertEqual(len(texts), 1, texts)
            self.assertIn("planstate.py:40-52", texts[0])
            self.assertIn("no such file", texts[0])
            self.assertEqual(planlint.GitResolver(Path(root))("keel/prompts.py", 19, 21), "it has 20 lines")


class OutcomeLintTest(unittest.TestCase):
    RECORD = ("## Where it stands\n\nBuilt.\n\n## What is next\n\nApprove.\n\n## Why this shape\n\n"
              "One store.\n\n## Open questions\n\n- None.\n\n## Evidence\n\n![the pane](assets/a.png){phone}\n")

    def test_a_whole_record_passes(self):
        result = planlint.lint_text(self.RECORD, "context.md")
        self.assertTrue(result["ok"], planlint.lines_of(result))

    def test_c26_evidence_that_names_no_artifact(self):
        text = self.RECORD.replace("![the pane](assets/a.png){phone}", "It works.")
        self.assertIn("C26", rules(planlint.lint_text(text, "context.md")))

    def test_c26_a_missing_section(self):
        text = self.RECORD.replace("## Why this shape\n\nOne store.\n\n", "")
        self.assertIn("C26", rules(planlint.lint_text(text, "context.md")))


class ResearchLintTest(unittest.TestCase):
    """c-719: a research outcome IS the research, held to a light contract of its own; a
    report (`kind: report`) is held to the same one, never to a plan's."""
    RESEARCH = ("---\nkind: research\ncard: c-1\n---\n# c-1 What the costs come to\n\n"
                "## Findings\n\nThe agent costs a third of the pilot.\n\n"
                "## What it means\n\nIt pays for itself in a month.\n\n"
                "## What is next\n\nRun it on one more site.\n\n"
                "## Evidence\n\n- [the bill](https://example.com/bill)\n")

    def test_a_whole_research_outcome_passes_with_no_frame_of_five(self):
        result = planlint.lint_text(self.RESEARCH, "context.md")
        self.assertEqual(result["kind"], "research")
        self.assertTrue(result["ok"], planlint.lines_of(result))

    def test_a_research_outcome_names_each_missing_section(self):
        text = self.RESEARCH.replace("## What it means\n\nIt pays for itself in a month.\n\n", "")
        lines = planlint.lines_of(planlint.lint_text(text, "context.md"))
        self.assertEqual(lines, ["C26 error: the record has no `## What it means` section"])
        empty = self.RESEARCH.replace("The agent costs a third of the pilot.\n\n", "")
        self.assertIn("C26 error: `## Findings` is empty", planlint.lines_of(planlint.lint_text(empty, "context.md")))

    def test_a_report_has_the_same_light_contract_and_not_a_plans(self):
        text = self.RESEARCH.replace("kind: research", "kind: report")
        result = planlint.lint_text(text, "report.md")
        self.assertEqual(result["kind"], "report")
        self.assertTrue(result["ok"], planlint.lines_of(result))
        bare = planlint.lint_text("---\nkind: report\n---\n# r\n\nwords\n", "report.md")
        self.assertNotIn("C2", rules(bare))
        self.assertIn("C26", rules(bare))

    def test_an_outcome_still_lints_as_it_did(self):
        result = planlint.lint_text(OutcomeLintTest.RECORD, "context.md")
        self.assertTrue(result["ok"], planlint.lines_of(result))
        research_shaped = planlint.lint_text("---\nkind: outcome\n---\n" + self.RESEARCH.split("---\n", 2)[2], "context.md")
        self.assertIn("C26 error: the record has no `## Where it stands` section", planlint.lines_of(research_shaped))


if __name__ == "__main__":
    unittest.main()
