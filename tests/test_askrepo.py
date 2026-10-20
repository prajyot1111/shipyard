"""An escalation's filed card names its repo, settled at raise and shown on the ask (c-550, r-21).

c-541 was filed from ask a-15, which named no --card, so it landed with no repo, started as
an errand and blocked. These hold the three ways a raise settles the repo (stated, from its
card, refused), the check against the personal space, the explicit errand, the old-shape
option still filing from its card, and every surface saying where it builds.
"""

import json
import tempfile
import unittest
from pathlib import Path

from keel import asks, deckdigest, requests
from keel.board import Board, Refused

TWO = ["Do it|file the card", "No|nothing"]


def refuse_unlisted(repo):
    if repo not in ("keel", "harbor"):
        raise Refused(f"{repo} is not a repo the personal space can open")


class AskRepoTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.board = Board(Path(self.dir.name) / "board.db")

    def tearDown(self):
        self.board.close()
        self.dir.cleanup()

    def raise_(self, card=None, file_repo=None, check=refuse_unlisted):
        return asks.raise_ask(self.board, "bosun", "escalation", "Should X?", "because",
                              TWO, card=card, files="A|Fix X|the brief",
                              file_repo=file_repo, check_repo=check)

    def filed(self, row):
        return self.board.get(asks.answer(self.board, row["id"], "human", "A")["filed_as"])

    def source(self, repo):
        return self.board.create("personal", "the card it is about", repo=repo, actor="human")

    def test_no_card_and_no_repo_is_refused(self):
        with self.assertRaisesRegex(Refused, "--file-repo <key>"):
            self.raise_()
        self.assertEqual(asks.listing(self.board), [])

    def test_a_stated_repo_files_there(self):
        card = self.filed(self.raise_(file_repo="keel"))
        self.assertEqual((card["space"], card["repo"]), ("personal", "keel"))

    def test_a_card_with_a_repo_gives_it(self):
        about = self.source("keel")
        row = self.raise_(card=about)
        self.assertEqual(row["options"][0]["files"]["repo_from"], about)
        card = self.filed(row)
        self.assertEqual((card["repo"], card["from"]), ("keel", about))

    def test_a_stated_repo_wins_over_the_card(self):
        card = self.filed(self.raise_(card=self.source("keel"), file_repo="harbor"))
        self.assertEqual(card["repo"], "harbor")

    def test_a_card_with_no_repo_and_nothing_stated_is_refused(self):
        with self.assertRaisesRegex(Refused, "none for an errand"):
            self.raise_(card=self.source(None))

    def test_an_unlisted_repo_is_refused_before_the_ask_exists(self):
        with self.assertRaisesRegex(Refused, "can open"):
            self.raise_(file_repo="nowhere")
        with self.assertRaisesRegex(Refused, "can open"):
            self.raise_(card=self.board.create("personal", "odd", repo="nowhere", actor="human"))
        self.assertEqual(asks.listing(self.board), [])

    def test_none_is_an_errand_even_when_its_card_has_a_repo(self):
        about = self.source("keel")
        card = self.filed(self.raise_(card=about, file_repo="none"))
        self.assertIsNone(card["repo"])
        self.assertEqual(card["from"], about)
        self.assertEqual(card["options"]["provenance"]["repo"], "stated")

    def test_only_an_escalation_takes_a_file_repo(self):
        with self.assertRaisesRegex(Refused, "this is a decision"):
            asks.raise_ask(self.board, "bosun", "decision", "Q?", "w", TWO, file_repo="keel")

    def test_an_ask_raised_before_c550_still_files_from_its_card(self):
        about = self.source("keel")
        row = self.raise_(card=about)
        options = row["options"]
        for key in ("repo", "repo_from"):
            del options[0]["files"][key]
        self.board.conn.execute("UPDATE asks SET options = ? WHERE id = ?",
                                (json.dumps(options), row["id"]))
        self.board.conn.commit()
        self.assertIn("repo from its card", asks.row_line(asks.get(self.board, row["id"])))
        self.assertEqual(self.filed(row)["repo"], "keel")

    def test_a_file_kind_files_a_card_marked_with_it(self):
        """c-553: a research card Bosun raises arrives marked, set at create by his answer."""
        row = asks.raise_ask(self.board, "bosun", "escalation", "Should X?", "because", TWO,
                             files="A|Look into X|findings only", file_repo="none",
                             file_kind="research", check_repo=refuse_unlisted)
        self.assertEqual(row["options"][0]["files"]["kind"], "research")
        self.assertIn("marked research", asks.row_line(asks.get(self.board, row["id"])))
        self.assertEqual(self.filed(row)["options"]["kind"], "research")

    def test_no_file_kind_files_an_unmarked_card(self):
        self.assertNotIn("kind", self.filed(self.raise_(file_repo="keel"))["options"])

    def test_an_unknown_file_kind_or_one_on_a_decision_is_refused(self):
        with self.assertRaisesRegex(Refused, "--file-kind is research"):
            asks.raise_ask(self.board, "bosun", "escalation", "Q?", "w", TWO,
                           files="A|t|b", file_repo="none", file_kind="feature")
        with self.assertRaisesRegex(Refused, "this is a decision"):
            asks.raise_ask(self.board, "bosun", "decision", "Q?", "w", TWO, file_kind="research")
        self.assertEqual(asks.listing(self.board), [])


class SaidTest(unittest.TestCase):
    """Where it builds, on every surface he reads the ask: kb console asks and show, the
    voice's digest line, and the wire that carries --file-repo from the Mac."""

    def option(self, **files):
        return {"letter": "B", "label": "File it", "does": "files it",
                "files": dict(title="Fix X", brief="b", **files)}

    def row(self, option):
        return {"id": "a-9", "kind": "escalation", "state": "open", "card": None,
                "question": "Should X?", "why": "w",
                "options": [{"letter": "A", "label": "Not yet", "does": "nothing"}, option]}


    def test_the_wire_carries_file_repo(self):
        argv = requests.argv({"sub": "raise", "file": "A|t|b", "file_repo": "keel"})
        self.assertIn("--file-repo=keel", argv)

    def test_the_wire_carries_file_kind(self):
        argv = requests.argv({"sub": "raise", "file": "A|t|b", "file_kind": "research"})
        self.assertIn("--file-kind=research", argv)


if __name__ == "__main__":
    unittest.main()
