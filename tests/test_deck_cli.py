"""`keel deck` and the one reduction behind it (`keel.deckdigest`).

WHAT THESE DEFEND, and it is one sentence: what the deck SHOWS and what a Harbor can SAY
are the same set of facts. The night this was written they were not. The deck's state
document carried `providers.work.reviews` while the voice digest hard-coded an empty list,
so a question about the PR Review screen came back "that is on the work side and I cannot
reach it" with the rows sitting on loopback.

The HTTP read is patched everywhere below: a test may never depend on a deck being up, and
the one that exercises the fallback needs it to be down on purpose.

NO EMPLOYER VOCABULARY IN THE FIXTURES. `make test` greps every tracked file outside
`packs/work/` against `packs/work/drift-terms`, so the repos, keys and stories here are
invented ones.
"""

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from keel import cli, deckdigest
from tests.helpers import CliCase


def a_card(card_id, space, stage, title, updated, blocked="", needs_you=False,
           archived=False, plan_gate=False, review=None, repo=""):
    return {"id": card_id, "space": space, "stage": stage, "title": title, "repo": repo,
            "blocked_reason": blocked, "updated_at": updated, "topic": "",
            "derived": {"archived": archived, "needs_you": needs_you, "backlog": False,
                        "plan_gate": plan_gate, "outcome_gate": False, "review": review}}


def state_document():
    """A document shaped like `GET /api/state`, carrying the traps that were fallen into.

    The card bodies (`brief`) and the review bodies (`findings`) are here ON PURPOSE: the
    digest has to drop them, and a fixture with nothing to drop proves nothing.
    """
    cards = [
        a_card("c-001", "personal", "inbox", "rewire the porch light", "2026-09-18T01:00:00+05:30"),
        a_card("c-002", "personal", "building", "the deck redesign", "2026-09-17T09:00:00+05:30"),
        # Two review cards (lane RC): the Reviews list, and what a Harbor says about it.
        a_card("c-003", "work", "review", "widget list drops its second page", "2026-09-18T02:00:00+05:30",
               review="gate", repo="widgets"),
        a_card("c-004", "work", "inbox", "engine: retries never back off", "2026-09-16T02:00:00+05:30",
               review="waiting", repo="engine"),
        a_card("c-005", "work", "planning", "a gate nobody answered", "2026-09-18T02:10:00+05:30",
               needs_you=True, plan_gate=True),
        a_card("c-006", "personal", "done", "an archived one", "2026-09-10T02:00:00+05:30",
               archived=True),
        # A work card whose pull request is open (lane SHIP): its pull request's state is on
        # the card, `options.shipping.facts`, and that is how it reaches a Harbor (RT-1).
        a_card("c-007", "work", "shipping", "back off on the third retry", "2026-09-18T00:30:00+05:30",
               repo="engine"),
    ]
    cards[-1]["options"] = {"pr": 41, "shipping": {
        "round": 1, "pending": [{"kind": "comment", "handle": "c9", "text": "a body nobody should ever hear read out loud"}],
        "facts": {"state": "open", "comments": 3, "approvals": 1, "ci": "failed", "behind": 2, "waiting": 1}}}
    for card in cards:
        card["brief"] = "a body nobody should ever hear read out loud"
    return {
        "now": "2026-09-18T02:30:00+05:30",
        "cards": cards,
        "needs_you": ["c-005"],
        "backlog": [],
        "houses": ["c-002"],
        "running": ["c-002"],
        "drain": {"host": "here", "text": "drain: houses=1 reviews=0 started=1", "alive": True},
        "segments": [
            {"name": "daybook", "summary": {"tiles": [{"label": "New since last look", "value": "4"}]}},
            {"name": "ledger", "summary": {"tiles": []}},
        ],
        "spaces": {
            "personal": {"name": "personal", "topics": ["deck", "keel"],
                         "counts": {"cards": 3, "needs_you": 0, "backlog": 0}},
            "work": {"name": "work", "topics": ["widgets"],
                     "counts": {"cards": 3, "needs_you": 1, "backlog": 1}},
        },
        "providers": {
            "work": {
                "reviews": {"route": "reviews", "columns": ["detected", "inbox"], "hidden": 9,
                            "items": [
                                {"key": "review:a-101", "title": "widget list drops its second page",
                                 "repo": "widgets", "kanbanState": "inbox",
                                 "findings": "a body nobody should ever hear read out loud"},
                                {"key": "review:a-102", "title": "retries never back off",
                                 "repo": "engine", "kanbanState": "detected",
                                 "findings": "another body"},
                            ]},
                # THE RETIRED PULL REQUEST WATCH'S ROUTE (lane RETIRE, RT-1), as an older
                # deck or a stale push could still carry it: none of it may reach a Harbor.
                "prs": {"route": "prs", "columns": ["open", "behind"], "hidden": 1,
                        "items": [
                            {"pr": 42, "story": "t-22", "title": "a stale watcher row",
                             "repo": "widgets", "kanbanState": "behind"},
                        ]},
            }
        },
        "config": {"houses_max": 3},
    }


class FoldTest(unittest.TestCase):
    def setUp(self):
        self.doc = deckdigest.fold(state_document(), harbor_running=True)


    def test_both_spaces_cards_are_in_it_and_the_archived_one_is_not(self):
        spaces = {row["space"] for row in self.doc["cards"]}
        self.assertEqual(spaces, {"personal", "work"})
        self.assertNotIn("c-006", [row["id"] for row in self.doc["cards"]])

    def test_the_card_that_wants_him_is_first(self):
        # The cap is per space and the sample is what he would ask about, so the order is
        # the deck's own: what wants him, then what is moving, then what he touched last.
        self.assertEqual(self.doc["cards"][0]["id"], "c-005")
        self.assertEqual(self.doc["cards"][1]["id"], "c-002")

    def test_the_provider_routes_are_folded_per_space(self):
        # lane RC: the reviews are the review cards, never the old scanner's rows
        reviews = deckdigest.provider_rows(self.doc, "reviews", "work")
        self.assertEqual([row["id"] for row in reviews], ["c-003", "c-004"])
        self.assertEqual([row["state"] for row in reviews], ["gate", "waiting"])
        self.assertEqual(deckdigest.provider_rows(self.doc, "prs", "work"), [])
        self.assertEqual(deckdigest.provider_rows(self.doc, "reviews", "personal"), [])

    def test_a_shipping_card_carries_its_pull_request_s_state_and_no_body(self):
        """RT-1: the PRs page is gone, so a work pull request reaches a Harbor through its
        card: the watcher's facts, states and counts, never a comment."""
        row = next(row for row in self.doc["cards"] if row["id"] == "c-007")
        self.assertEqual(row["pr"], "open, 3 comments, 1 approval, checks failed, 2 behind, 1 waiting")
        self.assertNotIn("pr", next(row for row in self.doc["cards"] if row["id"] == "c-001"))

    def test_the_queue_marks_a_gate_as_something_only_his_hands_answer(self):
        row = self.doc["queue"][0]
        self.assertEqual((row["id"], row["kind"]), ("c-005", "approval"))
        self.assertTrue(row["by_hand"])

    def test_the_segments_carry_a_headline_and_survive_having_no_tiles(self):
        self.assertEqual(self.doc["segments"][0], {"name": "daybook",
                                                   "headline": "New since last look 4"})
        self.assertEqual(self.doc["segments"][1]["headline"], "")

    def test_the_topics_come_through_for_the_refine(self):
        self.assertEqual(self.doc["topics"], {"personal": ["deck", "keel"], "work": ["widgets"]})

    def test_a_document_it_cannot_read_folds_to_an_empty_one_rather_than_raising(self):
        # Fields the deck has always had can go missing (an older deck, a partial write);
        # every one of them reads as absent rather than as an exception in a turn.
        doc = deckdigest.fold({})
        self.assertEqual(doc["cards"], [])
        self.assertEqual(doc["counts"]["cards"], 0)


class DigestTest(unittest.TestCase):
    def setUp(self):
        self.doc = deckdigest.fold(state_document(), harbor_running=True)
        self.digest = deckdigest.build(self.doc)
        self.blob = deckdigest.as_json(self.doc)

    def test_no_body_reaches_it(self):
        self.assertNotIn("a body nobody should ever hear read out loud", self.blob)
        self.assertNotIn("another body", self.blob)

    def test_the_names_do_reach_it_which_is_what_repairs_a_garbled_transcript(self):
        self.assertIn("widget list drops its second page", self.blob)
        self.assertIn("c-003 | widget list drops its second page | widgets | gate", self.blob)
        self.assertNotIn("review:a-101", self.blob)      # the old scanner's row is not read
        self.assertNotIn("a stale watcher row", self.blob)   # nor the retired watcher's

    def test_there_is_no_pull_request_section_and_the_card_line_says_the_pr(self):
        self.assertNotIn("prs", self.digest)
        rows = self.digest["cards"]["work"]["rows"]
        self.assertIn("c-007 back off on the third retry (shipping, pr: open, 3 comments, 1 approval, "
                      "checks failed, 2 behind, 1 waiting)", rows)


    def test_each_space_carries_its_real_count_and_a_stage_tally(self):
        self.assertEqual(self.digest["cards"]["work"]["count"], 4)
        self.assertEqual(self.digest["cards"]["work"]["stages"],
                         {"inbox": 1, "planning": 1, "review": 1, "shipping": 1})
        self.assertEqual(self.digest["cards"]["work"]["needsYou"], 1)

    def test_a_capped_section_breaks_down_by_lane_over_every_row(self):
        # THE BREAKDOWN IS A COUNT TOO. The first live turn after this landed said "three
        # open and the rest behind" about thirteen pull requests: four were open and only
        # three survived the twelve row sample. The total was right, the breakdown was
        # not, which is the same failure one level down.
        self.assertEqual(self.digest["reviews"]["states"], {"gate": 1, "waiting": 1})
        state = state_document()
        state["cards"] += ([a_card(f"c-{300 + n}", "work", "inbox", f"r {n}", "2026-09-18T01:00:00+05:30",
                                   review="waiting") for n in range(20)]
                           + [a_card(f"c-{400 + n}", "work", "review", f"g {n}", "2026-09-18T01:00:00+05:30",
                                     review="gate") for n in range(5)])
        digest = deckdigest.build(deckdigest.fold(state))
        self.assertEqual(digest["reviews"]["states"], {"gate": 6, "waiting": 21})
        self.assertEqual(len(digest["reviews"]["rows"]), deckdigest.REVIEW_ROWS)

    def test_a_capped_section_still_counts_every_row(self):
        # THE ONE THING SPOKEN MOST OFTEN IS THE COUNT, so the cap may never reach it: a
        # digest that carried 12 of 28 reviews and said "28" is honest, one that said
        # "12" is the confident wrong answer this whole package refuses.
        state = state_document()
        state["cards"] += [a_card(f"c-{200 + n}", "work", "inbox", f"review {n}", "2026-09-18T01:00:00+05:30",
                                  review="waiting") for n in range(38)]
        digest = deckdigest.build(deckdigest.fold(state))
        self.assertEqual(digest["reviews"]["count"], 40)
        self.assertEqual(len(digest["reviews"]["rows"]), deckdigest.REVIEW_ROWS)

    def test_the_cards_sample_is_capped_per_space(self):
        state = state_document()
        state["cards"] = [a_card(f"c-{n:03d}", "personal", "inbox", f"card {n}",
                                 "2026-09-18T01:00:00+05:30") for n in range(60)]
        digest = deckdigest.build(deckdigest.fold(state))
        self.assertEqual(len(digest["cards"]["personal"]["rows"]), deckdigest.CARD_ROWS)
        self.assertEqual(digest["cards"]["personal"]["count"], 60)

    def test_it_stays_a_few_kilobytes(self):
        size, tokens = deckdigest.measure(self.doc)
        self.assertLess(size, 16000, f"{size} bytes; the live deck measured about 6,500")


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.doc = deckdigest.fold(state_document(), harbor_running=True)

    def test_a_section_prints_its_rows_and_its_count(self):
        text = deckdigest.render_section(self.doc, "reviews", "work")
        self.assertIn("c-003", text)
        self.assertIn("widget list drops its second page", text)
        self.assertTrue(text.endswith("2 reviews in work"), text)

    def test_a_section_prints_every_row_rather_than_the_digest_sample(self):
        state = state_document()
        state["cards"] = [a_card(f"c-{n:03d}", "personal", "inbox", f"card {n}",
                                 "2026-09-18T01:00:00+05:30") for n in range(60)]
        text = deckdigest.render_section(deckdigest.fold(state), "cards")
        self.assertTrue(text.endswith("60 cards"), text.splitlines()[-1])

    def test_a_space_filters_the_cards(self):
        text = deckdigest.render_section(self.doc, "cards", "work")
        self.assertIn("c-003", text)
        self.assertNotIn("c-001", text)

    def test_an_empty_section_says_so_rather_than_printing_a_bare_heading(self):
        self.assertEqual(deckdigest.render_section(self.doc, "reviews", "personal"),
                         "no reviews in personal")

    def test_an_unknown_section_is_refused(self):
        with self.assertRaises(ValueError):
            deckdigest.section_rows(self.doc, "usage")


class DeckVerbTest(CliCase):
    """`keel deck ...` end to end, with the loopback read patched."""

    def deck(self, *argv, state=None, down=False):
        out, err = io.StringIO(), io.StringIO()
        fetch = (mock.Mock(side_effect=OSError("connection refused")) if down
                 else mock.Mock(return_value=state if state is not None else state_document()))
        with mock.patch.object(deckdigest, "fetch_state", fetch), \
                mock.patch.object(cli, "talker_running", lambda config: True), \
                redirect_stdout(out), redirect_stderr(err):
            code = cli.keel_main(["deck", *argv])
        return code, out.getvalue().strip(), err.getvalue().strip()

    def test_the_overview_names_every_section_and_its_source(self):
        code, out, err = self.deck()
        self.assertEqual(code, 0, err)
        self.assertIn("source: deck", out)
        self.assertIn("reviews: 2", out)
        self.assertNotIn("prs:", out)
        self.assertIn("cards (work): 4", out)


    def test_a_section_renders_as_a_table(self):
        code, out, err = self.deck("reviews", "--space", "work")
        self.assertEqual(code, 0, err)
        self.assertIn("c-003", out)
        self.assertIn("2 reviews in work", out)

    def test_the_cards_table_says_a_shipping_card_s_pull_request(self):
        code, out, err = self.deck("cards", "--space", "work")
        self.assertEqual(code, 0, err)
        line = next(line for line in out.splitlines() if line.startswith("c-007"))
        self.assertIn("open, 3 comments, 1 approval", line)

    def test_json_prints_the_whole_state_document(self):
        code, out, err = self.deck("--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["cards"][0]["id"], "c-001")

    def test_digest_prints_the_same_reduction_a_voice_turn_carries(self):
        code, out, err = self.deck("--digest")
        self.assertEqual(code, 0, err)
        digest = json.loads(out)
        self.assertEqual(digest, deckdigest.build(deckdigest.fold(state_document(),
                                                                 harbor_running=True)))

    def test_an_unknown_space_is_refused_with_one_line(self):
        code, out, err = self.deck("cards", "--space", "nowhere")
        self.assertEqual(code, 1)
        self.assertIn("unknown space", err)

    def test_a_deck_that_does_not_answer_falls_back_and_says_so_on_stderr(self):
        # THE FALLBACK IS NOT SILENT. `deckstate.build` is the same builder the deck runs,
        # so the answer is still the board's; what changes is freshness, and the note is
        # what stops that difference being invisible.
        code, out, err = self.deck(down=True)
        self.assertEqual(code, 0, err)
        self.assertIn("nothing answered on http://127.0.0.1:", err)
        self.assertIn("source: board", out)


if __name__ == "__main__":
    unittest.main()
