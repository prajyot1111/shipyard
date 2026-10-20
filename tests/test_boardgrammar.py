"""One grammar version (C4 of the overnight clearance, c-425).

A house started before a grammar change drew the OLD grammar: c-302's house, spawned
2026-09-19, wrote `step "<text>"` and `frame` lines two days after both had gone, and 21 of
27 of b-003's lines were refused. The grammar reached a house through three hand-kept
copies (the contract, the talker's memory, the Atlas) and nothing said which version any of
them was. So the card is generated from the parser's own tables, every copy embeds it and is
checked here, the version rides on a conversation's first sentence, and the previous
grammar is translated rather than refused.
"""

import tempfile
import unittest
from pathlib import Path

from keel import boardfiles, boardgrammar, boards, prompts
from keel.board import Board
from tests.helpers import make_config

ROOT = Path(__file__).resolve().parent.parent

# The previous grammar, as a house carrying it writes it: b-003's shape.
PREVIOUS = """\
board "How a card moves"
frame graph "The pass"
node card box "A card"
node drain server "The drain"
edge card -> drain "claimed"
frame steps "In order"
step "The drain claims the card"
step "It starts a house"
frame note "Why"
text "Nothing automatic ends a live session."
frame table "Limits"
cols Limit | Value
row houses_max | 3
path "probe.py" size "2 KB" from house
"""


class CardTest(unittest.TestCase):
    def test_the_card_is_built_from_the_parsers_own_tables(self):
        card = boardgrammar.grammar_card()
        self.assertIn(f"v{boardgrammar.GRAMMAR_VERSION}", card)
        for op in boards.OPS:
            self.assertRegex(card, rf"(?m)^{op}\b", f"{op} is not on the card")
        for icon in boards.ICONS:
            self.assertIn(icon, card)
        self.assertIn("|".join(boards.MARKS), card)
        self.assertIn(str(boards.MAX_NODES), card)
        for retired in boards.RETIRED:
            self.assertIn(retired, card)


    def test_every_op_has_a_signature_on_the_card(self):
        self.assertEqual(set(boardgrammar.SIGNATURES), set(boards.OPS))

    def test_every_copy_embeds_the_current_card(self):
        """The places that used to copy the grammar by hand now embed the generated card (the
        house's brief generates it, c-603), and a copy that has drifted fails here with the command that rewrites it."""
        card = boardgrammar.grammar_card()
        for path in boardgrammar.copies():
            relative = path
            text = path.read_text()
            embedded = boardgrammar.embedded(text)
            self.assertIsNotNone(embedded, f"{relative} has no ```{boardgrammar.FENCE_LANG} block")
            self.assertEqual(embedded, card,
                             f"{relative} is stale: run python3 -m keel.boardgrammar --write")

    def test_the_talkers_copy_moves_with_its_memory(self):
        """c-722: the talker's drawing entry is the install's once the install holds the
        talker's memory, the checkout's until then, and none where neither has it."""
        with tempfile.TemporaryDirectory() as tmp:
            code, install = Path(tmp) / "code", Path(tmp) / "install"
            (code / "docs" / "atlas").mkdir(parents=True)
            (code / "talker" / "memory").mkdir(parents=True)
            for name in ("MEMORY.md", boardgrammar.TALKER_COPY):
                (code / "talker" / "memory" / name).write_text("x\n")
            self.assertEqual(boardgrammar.copies(code, install)[-1],
                             code / "talker" / "memory" / boardgrammar.TALKER_COPY)
            (install / "memory" / "talker").mkdir(parents=True)
            for name in ("MEMORY.md", boardgrammar.TALKER_COPY):
                (install / "memory" / "talker" / name).write_text("x\n")
            self.assertEqual(boardgrammar.copies(code, install)[-1],
                             install / "memory" / "talker" / boardgrammar.TALKER_COPY)
            (install / "memory" / "talker" / boardgrammar.TALKER_COPY).unlink()
            self.assertEqual(boardgrammar.copies(code, install), [code / c for c in boardgrammar.COPIES])

    def test_write_rewrites_a_stale_copy_and_leaves_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "copy.md"
            path.write_text(f"before\n\n```{boardgrammar.FENCE_LANG}\nold card\n```\n\nafter\n")
            self.assertTrue(boardgrammar.write_copy(path))
            text = path.read_text()
            self.assertEqual(boardgrammar.embedded(text), boardgrammar.grammar_card())
            self.assertTrue(text.startswith("before\n") and text.endswith("after\n"))
            self.assertFalse(boardgrammar.write_copy(path), "a current copy is left alone")


class TranslateTest(unittest.TestCase):
    """The previous grammar, translated line by line instead of refused."""

    def test_a_bare_step_and_note_hang_on_the_board(self):
        self.assertEqual(boardgrammar.translate('step "It starts"')["line"],
                         'step board "It starts"')
        self.assertEqual(boardgrammar.translate('note "Why"')["line"], 'note board "Why"')
        self.assertEqual(boardgrammar.translate('text "Why"')["line"], 'note board "Why"')

    def test_a_frame_line_is_dropped_with_its_reason(self):
        dropped = boardgrammar.translate('frame graph "The pass"')
        self.assertIsNone(dropped["line"])
        self.assertIn("frames are gone", dropped["why"])
        self.assertIn("previous grammar", dropped["why"])

    def test_a_table_or_code_frame_opens_that_attachment_on_the_board(self):
        self.assertEqual(boardgrammar.translate('frame table "Limits"')["line"],
                         'table board "Limits"')
        self.assertEqual(boardgrammar.translate('frame code "The fix"')["line"],
                         'code board "The fix"')

    def test_a_bare_path_hangs_on_the_board(self):
        self.assertEqual(boardgrammar.translate('path "probe.py" size "2 KB" from house')["line"],
                         'path board "probe.py" size "2 KB" from house')

    def test_a_line_that_is_simply_wrong_is_not_translated(self):
        self.assertIsNone(boardgrammar.translate("draw a picture"))
        self.assertIsNone(boardgrammar.translate('node a'))


class PushCase(unittest.TestCase):
    """A card on a scratch board to push to; no tests of its own."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = make_config(Path(self.tmp.name))
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        self.card = self.board.create("personal", "a card", repo="keel", actor="human")


class TranslatedPushTest(PushCase):
    def test_the_previous_grammar_lands_instead_of_being_refused(self):
        """Red before C4: the steps, the note and the table rows were all refused."""
        body = PREVIOUS.replace('path "probe.py" size "2 KB" from house\n', "")
        result = boards.push(self.cfg, body, card=self.card)
        model = boards.build(boards.ops_lines(self.cfg, result["board"]))
        kinds = [a["kind"] for a in model["attachments"]]
        self.assertEqual(kinds.count("step"), 2)
        self.assertEqual(kinds.count("note"), 1)
        self.assertEqual(kinds.count("table"), 1)
        self.assertEqual(model["attachments"][-1]["rows"], [["houses_max", "3"]])
        self.assertEqual(result["skipped"], 3, "the three bare frames are dropped")
        self.assertGreaterEqual(result["translated"], 7)
        skipped = (boards.board_dir(self.cfg, result["board"]) / boards.SKIPPED_FILE).read_text()
        self.assertIn("previous grammar", skipped)

    def test_the_log_holds_the_translated_lines_so_the_deck_reads_them(self):
        result = boards.push(self.cfg, 'node a box "a"\nstep "one"', card=self.card)
        self.assertIn('step board "one"', boards.ops_lines(self.cfg, result["board"]))


class RealB003Test(PushCase):
    """The translator against b-003's REAL skipped log (21 lines), as the box kept it."""

    LINES = (ROOT / "tests" / "fixtures" / "b003-skipped.txt").read_text().splitlines()


    def test_b003s_refused_lines_land_through_the_translator(self):
        """21 of 21 were refused on the box. Now every bare step lands on the board, the
        three whole frame lines are dropped with a row naming the old grammar, and the one
        line the log cut at 170 characters (an unclosed quote) is not guessed at: the
        translator leaves it, and the current grammar's own refusal stands."""
        result = boards.push(self.cfg, "\n".join(self.LINES), card=self.card)
        model = boards.build(boards.ops_lines(self.cfg, result["board"]))
        steps = [a for a in model["attachments"] if a["kind"] == "step"]
        self.assertEqual(len(steps), 17)
        self.assertTrue(all(a["at"] == "board" for a in steps))
        self.assertEqual(steps[0]["text"], "Tap Assign tree on Move my blog")
        self.assertEqual(result["skipped"], 4)
        skipped = (boards.board_dir(self.cfg, result["board"]) / boards.SKIPPED_FILE).read_text()
        self.assertEqual(skipped.count("previous grammar"), 3)
        cut = [row for row in skipped.splitlines() if row.endswith("with five slice")]
        self.assertEqual(len(cut), 1)
        self.assertNotIn("previous grammar", cut[0])


class PathTranslationTest(PushCase):
    """F5 of the lane C review: a translated v1 `path` still carries its file (B12)."""

    def test_path_ops_reads_a_v1_path_through_the_translator(self):
        self.assertEqual(boards.path_ops('path "probe.py" size "2 KB" from house'), ["probe.py"])

    def test_the_v1_path_is_carried_and_downloadable(self):
        target = self.cfg.card_dir(self.card) / "probe.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("print(1)\n")
        source = {"kind": "card", "card": self.card}
        body = f'path "{target}" size "1 KB" from house'
        carried = []
        boards.carry(self.cfg, source, body,
                     attach=lambda path, blob: carried.append(path) or boardfiles.attach(
                         self.cfg, source, path, blob))
        self.assertEqual(carried, [str(target)])
        result = boards.push(self.cfg, body, card=self.card)
        self.assertEqual(result["files"], 1, result)


class FramingTest(unittest.TestCase):
    def test_the_first_sentence_carries_the_card(self):
        self.assertIn(boardgrammar.grammar_card(), prompts.converse("draw it"))

    def test_a_later_sentence_carries_it_only_when_asked(self):
        self.assertNotIn(boardgrammar.grammar_card(), prompts.converse_more("and now"))
        self.assertIn(boardgrammar.grammar_card(),
                      prompts.converse_more("and now", grammar=True))


if __name__ == "__main__":
    unittest.main()
