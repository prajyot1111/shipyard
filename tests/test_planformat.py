"""The plan format's parser: markdown plus the closed set of fenced blocks, into one document.

What is held here is what the renderer and the lint both rest on: every block comes back
typed and with a stable id, a bad block says what is wrong with it instead of taking the
plan down, and nothing the house wrote comes out as markup.
"""

import json
import unittest
from pathlib import Path

from keel import planformat, planinline, planmermaid

SAMPLE = (Path(__file__).parent / "fixtures" / "plan-sample.md").read_text()


def of_type(doc, kind):
    return [b for b in planformat.all_blocks(doc["blocks"]) if b["type"] == kind]


class DocumentTest(unittest.TestCase):
    def setUp(self):
        self.doc = planformat.parse(SAMPLE)

    def test_frontmatter_and_title(self):
        self.assertEqual(self.doc["kind"], "plan")
        self.assertEqual(self.doc["meta"]["card"], "c-900")
        self.assertEqual(self.doc["title"], "Answers live on the card")
        self.assertTrue(self.doc["format"])

    def test_a_markdown_comment_is_the_authors_alone(self):
        """c-719: `<!-- ... -->`, one line or several, is never a block the page draws."""
        doc = planformat.parse("---\nkind: outcome\n---\n# t\n\n<!-- a note to the house,\nover two lines -->\n\n"
                               "## Where it stands\n\nDone. <!-- not this one: it is inside a paragraph -->\n", "context.md")
        self.assertNotIn("note to the house", json.dumps(doc["blocks"]))
        self.assertIn("inside a paragraph", json.dumps(doc["blocks"]))

    def test_r1_f4_text_after_a_comment_is_kept_and_an_unclosed_one_is_drawn(self):
        doc = planformat.parse("---\nkind: outcome\n---\n# t\n\n## Where it stands\n\n"
                               "<!-- a note --> kept words\n", "context.md")
        self.assertIn("kept words", json.dumps(doc["blocks"]))
        self.assertNotIn("a note", json.dumps(doc["blocks"]))
        open_ = planformat.parse("---\nkind: outcome\n---\n# t\n\n<!-- never closed\n\n"
                                 "## Where it stands\n\nDone.\n", "context.md")
        self.assertIn("never closed", json.dumps(open_["blocks"]))
        self.assertIn("stands", [s["name"] for s in open_["sections"]])
        from keel import planlint
        warned = [f for f in planlint.lint(open_)["findings"] if "never closes" in f["text"]]
        self.assertEqual([f["level"] for f in warned], ["warning"])

    def test_r1_f4_the_panes_sections_read_what_the_page_reads(self):
        from keel import deckstate
        text = "## Where it stands\n\n<!-- for the house -->\nDone, and tested.\n\n## PR body\n\n<!-- x -->\nBody.\n"
        self.assertEqual(deckstate.section(text, "Where it stands"), "Done, and tested.")
        self.assertEqual(deckstate.pr_body(text), "Body.")
        self.assertEqual(planformat.strip_comments("a\n```\n<!-- code -->\n```\n"), "a\n```\n<!-- code -->\n```\n")

    def test_a_quoted_frontmatter_value_is_its_words(self):
        doc = planformat.parse('---\ntitle: "Quoted, as YAML writes it"\nkind: plan\n---\n')
        self.assertEqual(doc["title"], "Quoted, as YAML writes it")

    def test_the_named_sections_in_order(self):
        names = [s["name"] for s in self.doc["sections"]]
        self.assertEqual(names, ["goal", "now", "target", "proposal", "decisions", "risks",
                                 "steps", "proof", "out", "questions"])

    def test_the_summary_is_the_first_paragraph(self):
        self.assertIn("He is deciding", planinline.plain(self.doc["summary"]))

    def test_every_block_has_a_unique_id(self):
        ids = [b["id"] for b in planformat.all_blocks(self.doc["blocks"])]
        self.assertEqual(len(ids), len(set(ids)), ids)

    def test_ids_are_stable_across_an_edit_elsewhere(self):
        edited = SAMPLE.replace("Slides.", "Slides, and the deck export.")
        again = planformat.parse(edited)
        self.assertEqual([b["id"] for b in self.doc["blocks"]], [b["id"] for b in again["blocks"]])

    def test_a_decision_is_data(self):
        (store,) = of_type(self.doc, "decision")
        self.assertEqual(store["id"], "store")
        self.assertEqual([o["id"] for o in store["options"]], ["card", "file"])
        self.assertEqual(store["rec"], "card")
        self.assertIn("cost", store["options"][0])
        self.assertNotIn("problems", store)

    def test_a_batch_carries_rows_with_their_recommendation(self):
        (triage,) = of_type(self.doc, "batch")
        self.assertEqual(triage["choices"], ["fix", "defer", "drop"])
        self.assertEqual([(r["id"], r["rec"]) for r in triage["rows"]], [("f1", "fix"), ("f2", "drop")])

    def test_a_batch_row_id_may_hold_a_dot_and_other_blocks_keep_their_keys(self):
        """c-580: a two-repo card's replies are keyed `<repo>.c<n>`, `<repo>.ci` and
        `<repo>.review-<who>`; before, each such row was refused and so never posted."""
        doc = planformat.parse("# t\n\n```batch replies-1\nq: What to send\nchoices: post, edit, drop\n"
                               "c11: It is the page size | post | answers it\n"
                               "web.c21: Renamed | post | answers it\n"
                               "web.ci: A flaky build | drop | nothing to say\n"
                               "web.review-ana-example: Done | post | answers it\n"
                               f"web.review-{'x' * 30}: Thanks | post | the longest slug\n"
                               "WebApp.c7: Kept as written | post | its repo routes it\n```\n\n"
                               "```decision d1\nq: Which?\nq.x: not a key\n"
                               "option a: A\n  cost: none\noption b: B\n  cost: none\nrec: a\nbecause: yes\n```\n")
        (replies,) = of_type(doc, "batch")
        self.assertEqual([r["id"] for r in replies["rows"]],
                         ["c11", "web.c21", "web.ci", "web.review-ana-example",
                          f"web.review-{'x' * 30}", "WebApp.c7"])
        self.assertNotIn("problems", replies)
        (decision,) = of_type(doc, "decision")
        self.assertIn("a decision does not know the line 'q.x: not a key'", decision["problems"])

    def test_the_counts_the_deck_shows(self):
        self.assertEqual(self.doc["counts"]["decisions"], 3)
        self.assertEqual(self.doc["counts"]["questions"], 2)
        self.assertEqual(self.doc["counts"]["diagrams"], 2)

    def test_open_questions_carry_their_recommendation(self):
        (qs,) = of_type(self.doc, "questions")
        self.assertIn("rec", qs["items"][0])
        self.assertNotIn("rec", qs["items"][1])

    def test_the_table_keeps_its_caption_and_chips(self):
        (table,) = of_type(self.doc, "table")
        self.assertIn("which file changes", planinline.plain(table["caption"]))
        self.assertEqual(table["rows"][0][2]["chip"], "ok")
        self.assertEqual(table["rows"][1][2]["chip"], "warn")

    def test_callout_steps_checklist_compare_code(self):
        (callout,) = of_type(self.doc, "callout")
        self.assertEqual(callout["tone"], "settled")
        (steps,) = of_type(self.doc, "steps")
        self.assertEqual([i["state"] for i in steps["items"]], ["done", "doing", "todo"])
        (check,) = of_type(self.doc, "checklist")
        self.assertEqual([i["done"] for i in check["items"]], [True, False])
        (compare,) = of_type(self.doc, "compare")
        self.assertEqual((compare["left"], compare["right"], len(compare["rows"])), ("Today", "After", 2))
        (code,) = of_type(self.doc, "code")
        self.assertEqual(code["path"], "keel/planstate.py:40-52")
        self.assertIn("why", code)

    def test_mermaid_becomes_board_ops(self):
        (diagram,) = of_type(self.doc, "diagram")
        self.assertEqual(diagram["kind"], "flowchart")
        self.assertIn('node db database "board.db"', diagram["ops"])
        self.assertTrue(any(line.startswith("edge phone -> deck") for line in diagram["ops"]))

    def test_nothing_is_markup(self):
        """A script in a plan comes out as words, never as a tag the page would parse."""
        doc = planformat.parse("# t\n\n<script>alert(1)</script> and **<b>x</b>**\n")
        text = json.dumps(doc)
        self.assertNotIn('"html"', text)
        (para,) = of_type(doc, "paragraph")
        self.assertEqual(para["text"][0], {"t": "text", "v": "<script>alert(1)</script> and "})

    def test_a_context_record_is_an_outcome(self):
        doc = planformat.parse("## Where it stands\n\nx\n\n## Evidence\n\n- y\n", "context.md")
        self.assertEqual(doc["kind"], "outcome")
        self.assertEqual([s["name"] for s in doc["sections"]], ["stands", "evidence"])


class BlockProblemsTest(unittest.TestCase):
    def test_a_decision_without_costs_says_so_and_still_renders(self):
        doc = planformat.parse("```decision d1\nq: which\noption a: A\noption b: B\nrec: a\n```\n")
        (block,) = of_type(doc, "decision")
        self.assertEqual(len(block["options"]), 2)
        self.assertTrue(any("cost" in p for p in block["problems"]))
        self.assertTrue(any("because" in p for p in block["problems"]))

    def test_a_decision_that_recommends_nothing(self):
        doc = planformat.parse("```decision d1\nq: which\noption a: A\n  cost: x\noption b: B\n  cost: y\n```\n")
        (block,) = of_type(doc, "decision")
        self.assertTrue(any("no recommendation" in p for p in block["problems"]))

    def test_one_option_is_not_a_decision(self):
        doc = planformat.parse("```decision d1\nq: which\noption a: A\n  cost: x\nrec: a\nbecause: z\n```\n")
        self.assertTrue(any("at least two" in p["text"] for p in doc["problems"]))

    def test_an_unclosed_fence_is_a_problem_not_a_crash(self):
        doc = planformat.parse("```decision d1\nq: which\n")
        self.assertTrue(any("never closes" in p["text"] for p in doc["problems"]))

    def test_a_board_by_id_is_an_embed(self):
        doc = planformat.parse("```board The flow\nb-12\n```\n")
        (block,) = of_type(doc, "board")
        self.assertEqual(block["ref"], "b-012", "the id as the store spells it")

    def test_inline_board_ops_are_checked_by_the_boards_own_parser(self):
        doc = planformat.parse('```board\nnode a box "A"\nframe x\n```\n')
        (block,) = of_type(doc, "diagram")
        self.assertTrue(any("frames are gone" in p for p in block["problems"]))

    def test_images_keep_their_frame_hint(self):
        doc = planformat.parse("![the pane](assets/a.png){phone}\n![desk](assets/b.png)\n")
        (images,) = of_type(doc, "images")
        self.assertEqual([i["frame"] for i in images["items"]], ["phone", "desktop"])


class InlineTest(unittest.TestCase):
    def test_references_are_lifted(self):
        # c-630: the ticket and change refs are the card's space's (`terms.refs`)
        refs = planinline.ref_regex(ticket=r"st-\d+", change=r"PR #\d+")
        items = planinline.spans("see c-287 and st-36530, PR #12, and keel/serve.py:40-52 today", refs)
        kinds = [(s["t"], s.get("kind")) for s in items if s["t"] == "ref"]
        self.assertEqual(kinds, [("ref", "card"), ("ref", "ticket"), ("ref", "change"), ("ref", "path")])
        self.assertEqual([s.get("n") for s in items if s.get("kind") == "change"], [12])
        path = [s for s in items if s.get("kind") == "path"][0]
        self.assertEqual((path["path"], path["start"], path["end"]), ("keel/serve.py", 40, 52))

    def test_a_code_span_that_is_a_path_line_is_a_ref(self):
        (span,) = planinline.spans("`keel/board.py:12`")
        self.assertEqual((span["t"], span["kind"], span["code"]), ("ref", "path", True))

    def test_a_time_is_not_a_path(self):
        self.assertFalse(any(s["t"] == "ref" for s in planinline.spans("at 12:30 and 09:00")))

    def test_marks(self):
        items = planinline.spans("**bold `x`** and *em* and [a](https://example.org) and `code`")
        self.assertEqual([s["t"] for s in items if s["t"] != "text"], ["strong", "em", "link", "code"])


class MermaidTest(unittest.TestCase):
    def test_sequence_numbers_the_messages_as_steps(self):
        out = planmermaid.translate("sequenceDiagram\nactor P as User\nP->>Deck: taps Approve\nDeck-->>P: resumed\nloop x\nend\n")
        self.assertEqual(out["kind"], "sequence")
        self.assertIn('node P user "User"', out["ops"])
        self.assertIn('step P "1. taps Approve"', out["ops"])
        self.assertEqual(out["problems"], [])

    def test_state_start_and_end(self):
        out = planmermaid.translate("stateDiagram-v2\n[*] --> planning\nplanning --> building : approve\nbuilding --> [*]\n")
        self.assertIn('edge planning -> building "approve"', out["ops"])
        self.assertIn('node start zap "start"', out["ops"])
        self.assertIn('node end box "end"', out["ops"])

    def test_subgraph_is_a_group_and_the_ops_parse(self):
        from keel import boards
        out = planmermaid.translate("flowchart TD\nsubgraph box [The box]\na[Deck] --> b[(Board)]\nend\nc & a --> b\nclassDef x fill:#fff\n")
        self.assertTrue(out["ops"][0].startswith("group g_"))
        model = boards.new_model()
        for line in out["ops"]:
            op = boards.parse_line(line)
            if op:
                boards.apply_op(model, op)
        self.assertEqual(len(model["nodes"]), 3)
        self.assertEqual(len(model["edges"]), 3)

    def test_other_kinds_are_refused_by_name(self):
        out = planmermaid.translate("gantt\ntitle x\n")
        self.assertTrue(out["problems"] and "three kinds" in out["problems"][0])

    def test_the_node_cap(self):
        text = "flowchart LR\n" + "\n".join(f"n{i} --> n{i + 1}" for i in range(13))
        self.assertTrue(any("split it" in p for p in planmermaid.translate(text)["problems"]))


if __name__ == "__main__":
    unittest.main()
