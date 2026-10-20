"""The board list, grouped by card, and one search across it (C5, 2026-09-23)."""

from keel import boardlist, boards
from tests import test_serve as deck_tests


class ListCase(deck_tests.ServerCase):
    def setUp(self):
        super().setUp()
        self.work = self.board.create("personal", "The drain pass", repo="keel", actor="human",
                                      options={"tracker_ref": "st-4242"})
        boards.push(self.cfg, 'board "How the drain claims"\n'
                              'node card box "A startable card"\n'
                              'node drain server "the drain" "one pass a minute"\n'
                              'note drain "It reconciles against the harness first."\n'
                              'table card "Limits"\ncols Limit | Value\nrow houses_max | 3',
                    card=self.work)
        boards.push(self.cfg, 'board "The memory tier system"\nnode index file "MEMORY.md index"',
                    talker=True, actor="talker")


class ListingTest(ListCase):
    def test_every_row_carries_its_cards_title_and_story(self):
        rows = boardlist.listing(self.cfg)["rows"]
        house = next(r for r in rows if (r["source"] or {}).get("card") == self.work)
        self.assertEqual(house["card"]["title"], "The drain pass")
        self.assertEqual(house["card"]["story"], "st-4242")
        harbor = next(r for r in rows if r["source"]["kind"] == "talker")
        self.assertIsNone(harbor["card"])
        self.assertEqual(harbor["topic"], boards.topic_key("The memory tier system"))

    def test_a_review_card_s_board_says_so_and_no_other_does(self):
        """FC-4: the deck hides a review card's boards from its list until he includes them;
        the row says which they are."""
        review = self.board.create("work", "Review: tidy the loader", repo="api", actor="drain",
                                   options={"kind": "review", "review_key": "api:4150"})
        boards.push(self.cfg, 'board "The loader\'s code path"\nnode a box "loader"', card=review)
        rows = boardlist.listing(self.cfg)["rows"]
        by_card = {(r["source"] or {}).get("card"): r for r in rows if (r["source"] or {}).get("card")}
        self.assertTrue(by_card[review]["card"]["review"])
        self.assertFalse(by_card[self.work]["card"]["review"])

    def test_a_done_or_archived_card_s_board_says_so_and_a_live_one_does_not(self):
        """c-562: the deck hides a finished card's boards until Include done; the row says
        which they are, whether the card reached done or was archived."""
        done = self.board.create("personal", "Shipped last week", actor="human")
        gone = self.board.create("personal", "Put away", actor="human", options={"archived": True})
        self.board.conn.execute("UPDATE cards SET stage = 'done' WHERE id = ?", (done,))
        self.board.conn.commit()
        for card in (done, gone):
            boards.push(self.cfg, f'board "Board of {card}"\nnode a box "a"', card=card)
        rows = boardlist.listing(self.cfg)["rows"]
        by_card = {(r["source"] or {}).get("card"): r for r in rows if (r["source"] or {}).get("card")}
        self.assertTrue(by_card[done]["card"]["done"])
        self.assertTrue(by_card[gone]["card"]["done"])
        self.assertFalse(by_card[self.work]["card"]["done"])

    def search(self, words):
        return boardlist.listing(self.cfg, words)["rows"]

    def test_a_node_label_hit_names_the_node_so_the_page_can_light_it(self):
        rows = self.search("the drain")
        self.assertEqual([r["title"] for r in rows], ["How the drain claims"])
        self.assertEqual(rows[0]["hit"]["node"], "drain")
        self.assertIn("drain", rows[0]["hit"]["snippet"])

    def test_attachment_text_is_searched_and_lands_on_its_node(self):
        rows = self.search("reconciles harness")
        self.assertEqual(rows[0]["hit"]["field"], "attachment")
        self.assertEqual(rows[0]["hit"]["node"], "drain")
        self.assertEqual(self.search("houses_max")[0]["hit"]["node"], "card")

    def test_the_card_its_title_and_its_story_are_searched(self):
        self.assertEqual(len(self.search("st-4242")), 1)
        self.assertEqual(self.search("st-4242")[0]["hit"]["field"], "story")
        self.assertEqual(len(self.search(self.work)), 1)
        self.assertEqual(self.search("drain pass")[0]["title"], "How the drain claims")

    def test_every_word_must_be_somewhere_on_the_board(self):
        self.assertEqual(self.search("memory drain"), [])
        self.assertEqual([r["title"] for r in self.search("memory")],
                         ["The memory tier system"])


class RouteTest(ListCase):
    def test_the_route_answers_the_list_and_the_search(self):
        whole = self.get_json("/api/boards")
        self.assertEqual(len(whole["rows"]), 2)
        found = self.get_json("/api/boards?q=reconciles")
        self.assertEqual([r["hit"]["node"] for r in found["rows"]], ["drain"])


import json                                                              # noqa: E402
import re                                                                # noqa: E402
import shutil                                                            # noqa: E402
import subprocess                                                        # noqa: E402
import unittest                                                          # noqa: E402
from pathlib import Path                                                 # noqa: E402

ROOT = Path(__file__).resolve().parent.parent



