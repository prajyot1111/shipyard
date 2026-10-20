"""The blackboard: the grammar, the one model it folds into, the store, the index, the verb.

Four things are held here that nothing else would catch:

1. **The two parsers agree.** `keel/boards.py` decides what may be written and
   `app/ui.board.js` parses the same lines to draw them. Both are run over
   `tests/fixtures/board-lines.txt`, and the deck's half also has its vocabulary compared
   name by name against Python's, so an op or an icon added to one side alone fails here
   rather than on his phone. The node run is skipped where there is no node; the
   vocabulary comparison is a source read and always runs.
2. **A bad line costs one line.** Every refusal is a SKIP with a reason, never a failed
   push, because a house that got one line wrong still drew the rest.
3. **A board is ONE model.** One diagram with attachments hanging off its nodes, no
   frames, twelve nodes at most, and a second picture is `board new` and therefore a
   second board.
4. **The store is a record.** Ops are append-only, ids are minted like a card's, the live
   board is the newest one that is not closed, a house may only draw on its own card, and
   the same push said twice inside ten seconds lands once.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from keel import actions, boards
from keel.board import Board
from tests.helpers import make_config

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "board-lines.txt"
BOARD_JS = ROOT / "app" / "ui.board.js"

SCRIPT = """board "How Keel is laid out"
group box "The box (Oracle VPS)"
node phone phone "His phone"
node deck server "keel serve" in box "deck and board"
edge phone -> deck "speech, tailnet"
mark deck accent
note board "One diagram, seen three ways."
step board "You stop talking, the detector waits 2.5 s"
step deck "The sentence goes to the house that is held for you"
"""


def rows() -> list[tuple[str, str]]:
    """(verdict, line) for every row of the fixture, comments and blanks dropped."""
    out = []
    for raw in FIXTURE.read_text().splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        verdict, _, line = raw.partition("\t")
        out.append((verdict, line))
    return out


class GrammarTest(unittest.TestCase):
    def test_every_fixture_row_parses_as_the_fixture_says(self):
        for verdict, line in rows():
            with self.subTest(line=line):
                if verdict == "OK":
                    boards.parse_line(line)          # a blank or a comment returns None
                else:
                    with self.assertRaises(boards.BadLine):
                        boards.parse_line(line)

    def test_a_refusal_says_why_in_one_line_without_an_em_dash(self):
        for verdict, line in rows():
            if verdict != "BAD":
                continue
            with self.subTest(line=line):
                try:
                    boards.parse_line(line)
                except boards.BadLine as why:
                    reason = str(why)
                self.assertTrue(reason.strip(), "a skipped line carries a reason")
                self.assertEqual(len(reason.splitlines()), 1, "the reason is one line")
                self.assertNotIn(chr(0x2014), reason)

    def test_a_retired_op_is_answered_by_name_rather_than_as_an_unknown_one(self):
        """A house or a talker carrying the old grammar is told what to write instead, on
        the line it got wrong, which is the whole value of a skip reason."""
        with self.assertRaises(boards.BadLine) as caught:
            boards.parse_line('frame graph "The machines"')
        self.assertIn("frames are gone", str(caught.exception))
        self.assertIn("board new", str(caught.exception))
        with self.assertRaises(boards.BadLine) as caught:
            boards.parse_line('text "a paragraph"')
        self.assertIn("note <node|board>", str(caught.exception))

    def test_an_unknown_icon_falls_back_to_box_rather_than_refusing_the_node(self):
        op = boards.parse_line('node odd wombat "a node"')
        self.assertEqual(op["icon"], boards.FALLBACK_ICON)
        self.assertEqual(boards.parse_line('node m laptop "a node"')["icon"], "laptop")

    def test_the_three_arrows_are_the_only_ones(self):
        self.assertEqual(boards.parse_line("edge a -> b")["arrow"], "to")
        self.assertEqual(boards.parse_line("edge a <-> b")["arrow"], "both")
        self.assertEqual(boards.parse_line("edge a -- b")["arrow"], "none")

    def test_an_attachment_names_where_it_hangs_and_board_wins(self):
        self.assertEqual(boards.parse_line('note board "x"')["at"], "board")
        self.assertEqual(boards.parse_line('note deck "x"')["at"], "deck")
        self.assertEqual(boards.parse_line('path board "p" size "2 KB" from house')["at"],
                         "board")

    def test_the_string_caps_are_the_servers(self):
        long = "x" * (boards.MAX_TEXT + 1)
        with self.assertRaises(boards.BadLine):
            boards.parse_line(f'step board "{long}"')
        with self.assertRaises(boards.BadLine):
            boards.parse_line(f'node {"n" * (boards.MAX_NAME + 1)} laptop "fine"')
        with self.assertRaises(boards.BadLine):
            boards.parse_line("cols " + " | ".join(str(n) for n in range(boards.MAX_CELLS + 1)))


class ModelTest(unittest.TestCase):
    """What a line MEANS, which can only be judged against the board it lands on."""

    def fold(self, text: str) -> tuple[dict, list[str]]:
        model, skipped = boards.new_model(), []
        for raw in text.splitlines():
            try:
                op = boards.parse_line(raw)
            except boards.BadLine as why:
                skipped.append(str(why))
                continue
            if op is None:
                continue
            try:
                boards.apply_op(model, op)
            except boards.BadLine as why:
                skipped.append(str(why))
        return model, skipped

    def test_a_script_builds_one_diagram_with_its_attachments(self):
        model, skipped = self.fold(SCRIPT)
        self.assertEqual(skipped, [])
        self.assertEqual(model["title"], "How Keel is laid out")
        self.assertEqual([n["id"] for n in model["nodes"]], ["phone", "deck"])
        self.assertEqual(model["nodes"][1]["group"], "box")
        self.assertEqual(model["nodes"][1]["mark"], "accent")
        self.assertEqual(model["edges"][0]["label"], "speech, tailnet")
        self.assertEqual([(a["kind"], a["at"]) for a in model["attachments"]],
                         [("note", "board"), ("step", "board"), ("step", "deck")])

    def test_steps_are_ordered_by_push_order_across_the_whole_board(self):
        model, _ = self.fold('node a box "a"\nnode b box "b"\n'
                             'step a "first"\nstep board "second"\nstep b "third"')
        steps = [a["text"] for a in model["attachments"] if a["kind"] == "step"]
        self.assertEqual(steps, ["first", "second", "third"])
        self.assertEqual([a["n"] for a in model["attachments"]], [1, 2, 3])

    def test_an_attachment_on_a_node_nobody_declared_is_skipped(self):
        model, skipped = self.fold('node a box "a"\nnote ghost "no such node"')
        self.assertEqual(len(skipped), 1)
        self.assertIn("no node called 'ghost'", skipped[0])
        self.assertEqual(model["attachments"], [])

    def test_a_table_and_a_snippet_continue_the_attachment_they_opened(self):
        model, skipped = self.fold('node a box "a"\ntable a "costs"\ncols One | Two\n'
                                   'row 1 | 2\ncode board "the call"\nlang python\n'
                                   'line "def f():"')
        self.assertEqual(skipped, [])
        table, block = model["attachments"]
        self.assertEqual((table["cols"], table["rows"]), (["One", "Two"], [["1", "2"]]))
        self.assertEqual((block["lang"], block["lines"]), ("python", ["def f():"]))

    def test_a_row_or_a_line_with_nothing_open_is_skipped_with_its_reason(self):
        _, skipped = self.fold("row a | b\nline \"x\"")
        self.assertEqual(len(skipped), 2)
        self.assertIn("continues a table", skipped[0])
        self.assertIn("continues a snippet", skipped[1])

    def test_a_table_row_before_its_cols_is_skipped(self):
        _, skipped = self.fold('table board "t"\nrow a | b\ncols A | B\nrow a | b')
        self.assertEqual(len(skipped), 1)
        self.assertIn("`cols` line", skipped[0])

    def test_the_node_cap_is_the_boards_and_the_thirteenth_says_to_start_another(self):
        lines = [f'node n{i} box "node {i}"' for i in range(boards.MAX_NODES + 3)]
        model, skipped = self.fold("\n".join(lines))
        self.assertEqual(len(model["nodes"]), boards.MAX_NODES)
        self.assertEqual(len(skipped), 3)
        self.assertIn(f"at most {boards.MAX_NODES} nodes", skipped[0])
        self.assertIn("board new", skipped[0])

    def test_re_declaring_a_node_updates_its_label_and_keeps_its_mark(self):
        model, skipped = self.fold('node a laptop "first"\nmark a warn\nnode a server "second"')
        self.assertEqual(skipped, [])
        node = model["nodes"][0]
        self.assertEqual((node["label"], node["icon"], node["mark"]), ("second", "server", "warn"))
        self.assertEqual(len(model["nodes"]), 1)

    def test_an_edge_or_a_mark_naming_a_node_nobody_declared_is_skipped(self):
        _, skipped = self.fold('node a laptop "a"\nedge a -> ghost\nmark ghost good')
        self.assertEqual(len(skipped), 2)
        self.assertIn("declare it before the edge", skipped[0])

    def test_a_node_naming_an_undeclared_group_is_skipped(self):
        _, skipped = self.fold('node a laptop "a" in nowhere')
        self.assertIn("no group called", skipped[0])

    def test_normalising_makes_two_readings_of_one_block_one_sequence(self):
        """The b-003 comparison. The stream's reading of a block carried a trailing fence
        mark and the finished text's did not, so the raw bodies differed and the same ops
        were drawn twice."""
        streamed = 'node a box "a"\nstep a "one"\n```'
        finished = '\nnode  a  box "a"\n\nstep a "one"\n'
        self.assertEqual(boards.normalise(streamed), boards.normalise(finished))
        self.assertEqual(boards.signature(streamed), boards.signature(finished))
        self.assertNotEqual(boards.signature(streamed), boards.signature('node b box "b"'))


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.cfg.serve_port = 8791
        self.board = Board(self.cfg.db_path)
        self.card = self.board.create("personal", "the blackboard", repo="keel", actor="human")
        self.addCleanup(self.board.close)
        self.addCleanup(self.tmp.cleanup)

    def push(self, text=SCRIPT, **kwargs):
        kwargs.setdefault("card", self.card)
        return boards.push(self.cfg, text, **kwargs)

    def close(self, board_id, **kwargs):
        return boards.close(self.cfg, board_id, **kwargs)


class RedrawTest(StoreCase):
    """c-604: an outcome redraws a plan board at the built head. Appending to it drew the
    plan's edges and steps and the build's side by side; a push that names its board
    replaces what it shows, under the same id, with the plan's lines kept in its log."""

    PLAN = 'board "Flow"\nnode a box "a"\nnode b box "b"\nedge a -> b "plan"\nstep a "plan step"'
    BUILT = 'board "Flow"\nnode a box "a"\nnode c box "c"\nedge a -> c "built"\nstep c "built step"'

    def redrawn(self):
        first = self.push(self.PLAN)
        self.push('board new "Other"\nnode z box "z"')        # the plan board is not the live one
        return first, self.push(self.BUILT, board_id=first["board"])

    def test_a_push_naming_its_board_replaces_what_it_shows(self):
        first, result = self.redrawn()
        self.assertEqual(result["board"], first["board"])
        model = boards.build(boards.ops_lines(self.cfg, first["board"]))
        self.assertEqual([n["id"] for n in model["nodes"]], ["a", "c"])
        self.assertEqual([e["label"] for e in model["edges"]], ["built"])
        self.assertEqual([a["text"] for a in model["attachments"]], ["built step"])
        self.assertEqual(boards.read_record(self.cfg, first["board"])["nodes"], 2)

    def test_the_plans_lines_stay_in_the_log_and_the_redraw_counts_as_a_push(self):
        first, _ = self.redrawn()
        ops = boards.ops_lines(self.cfg, first["board"])
        self.assertIn('edge a -> b "plan"', ops)
        self.assertEqual(len([o for o in ops if o.startswith(boards.REDRAW_MARK)]), 1)
        record = boards.read_record(self.cfg, first["board"])
        self.assertEqual(boards.pushed_at(record), record["last_push"]["at"])

    def test_only_the_sources_own_open_board_is_redrawn(self):
        first = self.push(self.PLAN)
        other = self.board.create("personal", "another", repo="keel", actor="human")
        with self.assertRaises(boards.BoardError):
            boards.push(self.cfg, self.BUILT, card=other, board_id=first["board"])
        with self.assertRaises(boards.BoardError):
            self.push(self.BUILT, board_id=first["board"], new=True)

    def test_a_redraw_that_draws_nothing_leaves_the_picture(self):
        first = self.push(self.PLAN)
        self.push("draw a picture", board_id=first["board"])
        model = boards.build(boards.ops_lines(self.cfg, first["board"]))
        self.assertEqual([n["id"] for n in model["nodes"]], ["a", "b"])

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_deck_folds_a_redraw_the_way_the_server_does(self):
        first, _ = self.redrawn()
        lines = boards.ops_lines(self.cfg, first["board"])
        path = self.dir / "lines.json"
        path.write_text(json.dumps(lines))
        result = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "board-model.js"),
                                 str(BOARD_JS), str(path)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        said = json.loads(result.stdout)
        self.assertEqual(said["nodes"], ["a", "c"])
        self.assertEqual(said["steps"], ["built step"])


class PinnedToTheApprovalTest(StoreCase):
    """c-604 review: a redraw must not change what the APPROVED plan page shows. Its embed is
    the board as it stood at the approval (derived from the log's own stamped markers), and
    the outcome's embed is the board now, with the plan's picture to compare with."""

    PLAN, BUILT = RedrawTest.PLAN, RedrawTest.BUILT

    def approved_between(self):
        first = self.push(self.PLAN)
        ops = boards.ops_lines(self.cfg, first["board"])
        at = ops[0].split()[3]                  # the plan's push, then his approval after it
        from datetime import datetime, timedelta
        approved = (datetime.fromisoformat(at) + timedelta(microseconds=1)).isoformat()
        time.sleep(0.01)
        self.push(self.BUILT, board_id=first["board"])
        return first["board"], approved, len(ops)

    def embed(self, kind, ref, approved):
        from keel import planroute
        doc = {"kind": kind, "blocks": [{"type": "board", "ref": ref}]}
        planroute.decorate(self.cfg, doc, None, approved)
        return doc["blocks"][0]

    def test_the_plan_shows_the_board_as_approved_and_links_it_so(self):
        ref, approved, planned = self.approved_between()
        block = self.embed("plan", ref, approved)
        self.assertEqual(block["upto"], planned)
        self.assertNotIn(boards.REDRAW_MARK.strip(), " ".join(block["ops"]))
        self.assertEqual([n["id"] for n in boards.build(block["ops"])["nodes"]], ["a", "b"])

    def test_the_outcome_shows_the_board_now_and_offers_the_plans(self):
        ref, approved, planned = self.approved_between()
        block = self.embed("outcome", ref, approved)
        self.assertEqual([n["id"] for n in boards.build(block["ops"])["nodes"]], ["a", "c"])
        self.assertEqual(block["planned_upto"], planned)
        self.assertNotIn("upto", block)

    def test_an_unapproved_plan_is_live(self):
        ref, _, _ = self.approved_between()
        self.assertNotIn("upto", self.embed("plan", ref, None))


class GroupAndNodeShareNoIdTest(StoreCase):
    """c-602: a node in a group of its own name hung the page (its drawing walked the node as
    its own parent). The push skips the clashing line, in either order, with the reason."""

    def test_a_node_named_like_a_group_is_skipped_with_the_reason(self):
        result = self.push('group lint "the lint"\nnode lint box "A" in lint\nnode rules box "B" in lint')
        self.assertEqual((result["nodes"], result["skipped"]), (1, 1))
        self.assertIn("may not share one", result["reasons"][0])
        self.assertIn("a group is already called 'lint'", result["reasons"][0])

    def test_a_group_named_like_a_node_is_skipped_too(self):
        result = self.push('node lint box "A"\ngroup lint "the lint"')
        self.assertEqual(result["skipped"], 1)
        self.assertIn("a node is already called 'lint'", result["reasons"][0])


class StoreTest(StoreCase):
    def test_a_push_creates_the_board_its_files_and_one_push_marker(self):
        result = self.push()
        self.assertEqual(result["board"], "b-001")
        self.assertEqual((result["nodes"], result["attachments"]), (2, 3))
        self.assertEqual(result["skipped"], 0)
        directory = boards.board_dir(self.cfg, "b-001")
        ops = (directory / boards.OPS_FILE).read_text().splitlines()
        self.assertTrue(ops[0].startswith(boards.PUSH_MARK), ops[:3])
        self.assertIn("cli", ops[0], "the marker says who drew")
        self.assertEqual(len([line for line in ops if line.startswith(boards.PUSH_MARK)]), 1)
        record = json.loads((directory / boards.BOARD_FILE).read_text())
        self.assertEqual(record["title"], "How Keel is laid out")
        self.assertEqual(record["source"], {"kind": "card", "card": self.card})
        self.assertEqual((record["nodes"], record["attachments"]), (2, 3))
        self.assertIn("His phone", record["labels"])

    def test_the_url_it_hands_back_is_the_board_itself(self):
        """A board is one page with three views now, so there is no frame to deep link to."""
        self.assertEqual(self.push()["url"], "http://127.0.0.1:8791/board/b-001")

    def test_a_second_push_appends_to_the_same_live_board(self):
        self.push()
        result = self.push('node extra box "one more"')
        self.assertEqual(result["board"], "b-001")
        self.assertEqual(result["nodes"], 3)
        self.assertEqual(boards.api_board(self.cfg, "b-001")["nodes"], 3)
        ops = boards.ops_lines(self.cfg, "b-001")
        self.assertEqual(len([line for line in ops if line.startswith(boards.PUSH_MARK)]), 2)

    def test_a_push_continues_the_one_diagram_rather_than_starting_a_picture(self):
        self.push('node a laptop "a"')
        self.push('node b server "b"\nedge a -> b')
        model = boards.build(boards.ops_lines(self.cfg, "b-001"))
        self.assertEqual([n["id"] for n in model["nodes"]], ["a", "b"])
        self.assertEqual(len(model["edges"]), 1)

    def test_a_bad_line_is_skipped_with_its_reason_and_the_rest_still_lands(self):
        result = self.push('node a laptop "a"\ndraw a picture\nmark a good')
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["nodes"], 1)
        skipped = (boards.board_dir(self.cfg, "b-001") / boards.SKIPPED_FILE).read_text()
        self.assertIn("draw a picture", skipped)
        self.assertIn("is not an op", skipped)
        model = boards.build(boards.ops_lines(self.cfg, "b-001"))
        self.assertEqual(model["nodes"][0]["mark"], "good")

    def test_a_push_of_nothing_but_bad_lines_still_answers_rather_than_failing(self):
        result = self.push("draw a picture\nrender it nicely")
        self.assertEqual((result["skipped"], result["nodes"]), (2, 0))

    def test_the_title_falls_back_to_the_first_label_then_to_the_card(self):
        self.push('group box "The machines"\nnode a laptop "a" in box')
        self.assertEqual(boards.read_record(self.cfg, "b-001")["title"], "The machines")
        second = self.board.create("personal", "another card", actor="human")
        boards.push(self.cfg, 'node n box "a node"', card=second,
                    card_title=boards.card_title(self.cfg, second))
        self.assertEqual(boards.read_record(self.cfg, "b-002")["title"], "a node")

    def test_a_title_given_on_the_verb_wins(self):
        self.push(title="What he asked for")
        self.assertEqual(boards.read_record(self.cfg, "b-001")["title"], "What he asked for")

    def test_ids_are_minted_like_a_cards(self):
        self.push()
        boards.push(self.cfg, SCRIPT, talker=True)
        self.assertEqual(sorted(r["id"] for r in boards.records(self.cfg)), ["b-001", "b-002"])

    def test_a_push_names_exactly_one_source(self):
        with self.assertRaises(boards.BoardError):
            boards.push(self.cfg, SCRIPT)
        with self.assertRaises(boards.BoardError):
            boards.push(self.cfg, SCRIPT, card=self.card, talker=True)

    def test_a_push_longer_than_the_cap_is_refused_whole(self):
        with self.assertRaises(boards.BoardError):
            self.push("\n".join(['step board "x"'] * (boards.MAX_PUSH_LINES + 1)))


class SecondBoardTest(StoreCase):
    """`board new "<title>"`: the second thing that does not fit with the first.

    His words: "if I ask for a second thing that doesn't fit with the first but still
    belongs to the house, it can be another board, not a frame".
    """

    def test_board_new_mid_push_starts_a_second_board_for_the_same_source(self):
        result = self.push('node a laptop "the first picture"\n'
                           'board new "The second picture"\n'
                           'node b server "the second picture"\nstep b "and its step"')
        self.assertEqual(result["board"], "b-002", "the result names the live board")
        self.assertEqual(result["boards"], ["b-001", "b-002"])
        first = boards.build(boards.ops_lines(self.cfg, "b-001"))
        second = boards.build(boards.ops_lines(self.cfg, "b-002"))
        self.assertEqual([n["id"] for n in first["nodes"]], ["a"])
        self.assertEqual([n["id"] for n in second["nodes"]], ["b"])
        self.assertEqual(boards.read_record(self.cfg, "b-002")["title"], "The second picture")
        self.assertEqual(boards.read_record(self.cfg, "b-002")["source"],
                         {"kind": "card", "card": self.card})

    def test_the_report_counts_every_board_the_push_touched(self):
        """C1: the pen builds what he hears from `accepted` and `skipped`, so a push that
        refused lines on its FIRST board and drew cleanly on its second must not report
        the second board's clean count alone."""
        result = self.push('node a laptop "a"\nframe old "x"\nnote nowhere "y"\n'
                           'board new "The second picture"\nnode b server "b"')
        self.assertEqual(result["board"], "b-002")
        self.assertEqual(result["skipped"], 2, result)
        self.assertEqual(result["accepted"], 3, result)
        self.assertEqual(len(result["reasons"]), 2)

    def test_the_second_board_is_the_live_one_so_the_next_push_continues_it(self):
        self.push('node a laptop "one"\nboard new "Two"\nnode b server "two"')
        self.assertEqual(self.push('node c box "three"')["board"], "b-002")

    def test_board_new_on_an_untouched_board_names_it_rather_than_leaving_a_blank(self):
        """A talker whose every push opens with `board new` would otherwise collect empty
        boards, one per push."""
        result = self.push('board new "The only picture"\nnode a laptop "a"')
        self.assertEqual(result["boards"], ["b-001"])
        self.assertEqual(boards.read_record(self.cfg, "b-001")["title"], "The only picture")
        self.assertEqual(len(boards.records(self.cfg)), 1)

    def test_a_second_board_is_how_a_thirteenth_node_gets_drawn(self):
        lines = [f'node n{i} box "node {i}"' for i in range(boards.MAX_NODES)]
        lines += ['board new "The rest of it"', 'node more box "the thirteenth"']
        result = self.push("\n".join(lines))
        self.assertEqual(result["skipped"], 0, result["reasons"])
        self.assertEqual(boards.read_record(self.cfg, "b-001")["nodes"], boards.MAX_NODES)
        self.assertEqual(boards.read_record(self.cfg, "b-002")["nodes"], 1)


class TheTitleIsTheTopicTest(StoreCase):
    """A `board` line whose title is not this board's title STARTS ANOTHER BOARD.

    THE CASE, from the box on 2026-09-21. Harbor was asked to explain how input becomes a
    diagram. It wrote a fence opening `board "How drawing on the board works"`, and the push
    appended to its LIVE board, b-001, which was "The memory tier system" and already held
    nine nodes. So the memory board was renamed to the drawing board, the drawing board's
    own nodes ran into the twelve node cap three nodes in, and then every attachment on the
    five nodes that had been dropped was refused in turn: 25 skipped lines, all of them
    `no node called 'meaning' on this board`. Two boards' worth of thinking in one, under
    the wrong name, most of it missing.

    Nothing about that push was ill-formed. It said what it was about, in the one op that
    exists for saying so, and the store read it as a rename. The title is the TOPIC now.
    """

    NINE = "\n".join(['board "The memory tier system"'] +
                      [f'node n{i} box "node {i}"' for i in range(9)])
    DRAWING = "\n".join(['board "How drawing on the board works"'] +
                         [f'node d{i} box "drawing {i}"' for i in range(8)] +
                         ['note d0 "the ops are read, not run"',
                          'step d1 "he says it, and the words reach the house"',
                          'table d2 "what each op costs"', 'cols Op | Lines', 'row node | 1'])

    def test_harbors_own_shape_lands_as_a_second_board_with_all_of_it(self):
        self.push(self.NINE, talker=True, card=None, actor="talker")
        self.was = boards.read_record(self.cfg, "b-001")["updated"]
        result = self.push(self.DRAWING, talker=True, card=None, actor="talker")

        self.assertEqual(result["board"], "b-002", "it appended to the memory board again")
        self.assertEqual(result["boards"], ["b-002"],
                         "it counted the board it did not draw on")
        self.assertEqual(result["skipped"], 0, result["reasons"])
        self.assertEqual(result["nodes"], 8, "the board ran out of room for its own nodes")
        self.assertEqual(result["attachments"], 3)

        first = boards.read_record(self.cfg, "b-001")
        self.assertEqual(first["title"], "The memory tier system", "the first board was renamed")
        self.assertEqual(first["nodes"], 9, "the second topic landed on the first board")
        self.assertEqual(first["updated"], self.was, "a board it never drew on was touched")
        second = boards.read_record(self.cfg, "b-002")
        self.assertEqual(second["title"], "How drawing on the board works")
        self.assertEqual(second["source"], {"kind": "talker", "card": None})
        model = boards.build(boards.ops_lines(self.cfg, "b-002"))
        self.assertEqual([n["id"] for n in model["nodes"]], [f"d{i}" for i in range(8)])
        self.assertEqual([(a["kind"], a["at"]) for a in model["attachments"]],
                         [("note", "d0"), ("step", "d1"), ("table", "d2")])
        self.assertEqual(model["attachments"][2]["rows"], [["node", "1"]])

    def test_the_new_board_names_itself_in_its_own_log(self):
        """A board's log says what the board is called, so replaying it is enough."""
        self.push(self.NINE, talker=True, card=None, actor="talker")
        self.push(self.DRAWING, talker=True, card=None, actor="talker")
        lines = [line for line in boards.ops_lines(self.cfg, "b-002") if not line.startswith("#")]
        self.assertEqual(lines[0], 'board "How drawing on the board works"')
        self.assertEqual(boards.build(lines)["title"], "How drawing on the board works")

    def test_the_same_title_continues_the_board_it_names(self):
        self.push(self.NINE, talker=True, card=None, actor="talker")
        result = self.push('board "The memory tier system"\nnode more box "one more"',
                           talker=True, card=None, actor="talker")
        self.assertEqual(result["board"], "b-001")
        self.assertEqual(result["nodes"], 10)
        self.assertEqual(len(boards.records(self.cfg)), 1)

    def test_the_same_topic_survives_case_punctuation_and_whitespace(self):
        """He is not typing it: a model writes the title again from memory, and "the
        memory-tier system." is the same topic as "The memory tier system"."""
        self.push(self.NINE, talker=True, card=None, actor="talker")
        for said in ('board "the memory tier system"',
                     'board "The  memory   tier system"',
                     'board "The memory-tier system."',
                     'board "THE MEMORY TIER SYSTEM"'):
            with self.subTest(said=said):
                result = self.push(f'{said}\nnote board "still the same topic"',
                                   talker=True, card=None, actor="talker")
                self.assertEqual(result["board"], "b-001", said)
        self.assertEqual(len(boards.records(self.cfg)), 1)

    def test_a_push_with_no_board_line_continues_the_live_board(self):
        self.push(self.NINE, talker=True, card=None, actor="talker")
        result = self.push('node more box "one more"', talker=True, card=None, actor="talker")
        self.assertEqual(result["board"], "b-001")
        self.assertEqual(boards.read_record(self.cfg, "b-001")["title"], "The memory tier system")

    def test_renaming_is_its_own_op_now(self):
        self.push(self.NINE, talker=True, card=None, actor="talker")
        result = self.push('board rename "The memory tiers, properly"\n'
                           'note board "same board, better name"',
                           talker=True, card=None, actor="talker")
        self.assertEqual(result["board"], "b-001")
        self.assertEqual(len(boards.records(self.cfg)), 1)
        self.assertEqual(boards.read_record(self.cfg, "b-001")["title"],
                         "The memory tiers, properly")

    def test_a_renamed_board_is_then_continued_by_its_new_name(self):
        self.push(self.NINE, talker=True, card=None, actor="talker")
        self.push('board rename "The memory tiers, properly"', talker=True, card=None,
                  actor="talker")
        result = self.push('board "The memory tiers, properly"\nnote board "still here"',
                           talker=True, card=None, actor="talker")
        self.assertEqual(result["board"], "b-001")

    def test_board_new_still_forces_a_second_board_under_the_same_title(self):
        """The explicit form says "another one about this", which a title cannot."""
        self.push(self.NINE, talker=True, card=None, actor="talker")
        result = self.push('board new "The memory tier system"\nnode a box "a"',
                           talker=True, card=None, actor="talker")
        self.assertEqual(result["board"], "b-002")
        self.assertEqual(boards.read_record(self.cfg, "b-002")["title"], "The memory tier system")

    def test_a_title_on_a_board_nothing_has_been_drawn_on_names_it(self):
        """The first push of all, and a fresh board made by `board new`: there is nothing
        to start a second board away from."""
        result = self.push('board "The first thing"\nnode a box "a"', talker=True, card=None)
        self.assertEqual(result["boards"], ["b-001"])
        self.assertEqual(boards.read_record(self.cfg, "b-001")["title"], "The first thing")


class ACardHasAsManyBoardsAsItHasPicturesTest(StoreCase):
    """The title rule is the SOURCE'S, not Harbor's: a house splits on a new topic too.

    His words: "a user flow diagram and then a database schema diagram both belong to the
    same story but are different, and the node cap would hamper cramming them into one".
    One topic per board, as many boards per card as the card has pictures, and all of them
    are listed under that card.
    """

    def house(self):
        return {"actor": "house", "card": self.card}

    def test_a_house_pushing_a_new_topic_gets_a_second_board_on_its_own_card(self):
        self.push('board "The user flow"\nnode land box "he lands"\nnode pick box "he picks"\n'
                  'edge land -> pick', caller=self.house(), actor="house")
        result = self.push('board "The database schema"\nnode cards box "cards"\n'
                           'node events box "events"\nedge cards -> events "one to many"\n'
                           'note cards "the only table that is ever written by hand"',
                           caller=self.house(), actor="house")
        self.assertEqual(result["boards"], ["b-002"])
        self.assertEqual(result["nodes"], 2)
        self.assertEqual(result["skipped"], 0, result["reasons"])
        for board_id, name, nodes in (("b-001", "The user flow", 2),
                                      ("b-002", "The database schema", 2)):
            record = boards.read_record(self.cfg, board_id)
            self.assertEqual(record["title"], name)
            self.assertEqual(record["nodes"], nodes)
            self.assertEqual(record["source"], {"kind": "card", "card": self.card},
                             "the second picture left the card")
            self.assertEqual(record["actor"], "house")

    def test_both_are_listed_under_that_card_newest_first_with_the_live_one_marked(self):
        self.push('board "The user flow"\nnode land box "he lands"', caller=self.house())
        self.push('board "The database schema"\nnode cards box "cards"', caller=self.house())
        rows = boards.listing(self.cfg, card=self.card)
        self.assertEqual([row["id"] for row in rows], ["b-002", "b-001"])
        self.assertEqual([row["title"] for row in rows],
                         ["The database schema", "The user flow"])
        self.assertEqual([row["live"] for row in rows], [True, False],
                         "a card has one LIVE board and keeps the rest")

    def test_the_cards_pane_carries_every_one_of_them_and_not_only_the_live_one(self):
        self.push('board "The user flow"\nnode land box "he lands"', caller=self.house())
        self.push('board "The database schema"\nnode cards box "cards"', caller=self.house())
        shown = boards.card_board(self.cfg, self.card)
        self.assertEqual(shown["count"], 2)
        self.assertEqual(shown["id"], "b-002", "the block still leads with the live board")
        self.assertEqual([row["id"] for row in shown["boards"]], ["b-002", "b-001"])
        self.assertEqual([row["title"] for row in shown["boards"]],
                         ["The database schema", "The user flow"])
        self.assertTrue(shown["boards"][0]["live"])

    def test_a_house_still_cannot_put_its_second_picture_on_another_source(self):
        """Splitting is per SOURCE. A new topic makes another of the caller's own boards."""
        boards.push(self.cfg, 'board "Harbor\'s own"\nnode a box "a"', talker=True,
                    actor="talker", caller=TALKER)
        with self.assertRaises(boards.BoardError):
            boards.push(self.cfg, 'board "Something else"\nnode b box "b"', talker=True,
                        caller=self.house())


class AtomicNodeCapTest(StoreCase):
    """A push that will not fit draws NOTHING.

    The cap used to refuse the thirteenth node and carry on, which is right for a line that
    is merely wrong and wrong for one that means the board is full: what followed was every
    attachment hanging on a node that had been dropped, refused one by one. Harbor's push
    left 25 such lines in the skipped log. Half a diagram under the wrong name is worse than
    a refusal he can act on.
    """

    def full(self):
        return "\n".join(['board "A full board"'] +
                          [f'node n{i} box "node {i}"' for i in range(boards.MAX_NODES)])

    def test_a_push_past_the_cap_is_refused_whole_and_names_board_new(self):
        self.push(self.full(), talker=True, card=None)
        before = boards.ops_lines(self.cfg, "b-001")
        with self.assertRaises(boards.BoardError) as caught:
            self.push('board "A full board"\nnode extra box "the thirteenth"\n'
                      'note extra "and what hangs on it"', talker=True, card=None)
        said = str(caught.exception)
        self.assertIn(str(boards.MAX_NODES), said)
        self.assertIn("board new", said)
        self.assertEqual(len(said.splitlines()), 1, said)
        self.assertEqual(boards.ops_lines(self.cfg, "b-001"), before, "it drew half of it")
        self.assertEqual(boards.read_record(self.cfg, "b-001")["nodes"], boards.MAX_NODES)

    def test_nothing_at_all_is_written_not_even_the_lines_that_fitted(self):
        self.push(self.full(), talker=True, card=None)
        before = boards.ops_lines(self.cfg, "b-001")
        skipped = boards.board_dir(self.cfg, "b-001") / boards.SKIPPED_FILE
        was = skipped.read_text() if skipped.exists() else ""
        with self.assertRaises(boards.BoardError):
            self.push('note board "this one would have fitted"\n'
                      'node extra box "this one would not"', talker=True, card=None)
        self.assertEqual(boards.ops_lines(self.cfg, "b-001"), before)
        self.assertEqual(skipped.read_text() if skipped.exists() else "", was,
                         "a refused push still wrote to the skipped log")

    def test_the_refusal_counts_the_whole_push_rather_than_one_line(self):
        """Nine on the board and five in the push is over, even though no single line is."""
        self.push("\n".join(['board "Nine"'] + [f'node n{i} box "{i}"' for i in range(9)]),
                  talker=True, card=None)
        with self.assertRaises(boards.BoardError):
            self.push("\n".join(['board "Nine"'] + [f'node m{i} box "{i}"' for i in range(5)]),
                      talker=True, card=None)
        self.assertEqual(boards.read_record(self.cfg, "b-001")["nodes"], 9)

    def test_board_new_inside_the_push_is_what_makes_it_fit(self):
        """The reason names the way out, and the way out works."""
        self.push(self.full(), talker=True, card=None)
        result = self.push('board new "The rest of it"\nnode extra box "the thirteenth"\n'
                           'note extra "and what hangs on it"', talker=True, card=None)
        self.assertEqual(result["board"], "b-002")
        self.assertEqual((result["nodes"], result["attachments"]), (1, 1))

    def test_a_new_title_is_the_other_way_out_and_needs_no_cap_at_all(self):
        """Harbor's own push: a different topic starts its own board, so the cap it would
        have hit on the old board is never reached."""
        self.push(self.full(), talker=True, card=None)
        result = self.push('board "Something else entirely"\nnode extra box "the first"',
                           talker=True, card=None)
        self.assertEqual(result["board"], "b-002")
        self.assertEqual(result["nodes"], 1)

    def test_re_declaring_a_node_on_a_full_board_is_not_a_thirteenth(self):
        self.push(self.full(), talker=True, card=None)
        result = self.push('node n0 server "the same node, corrected"', talker=True, card=None)
        self.assertEqual(result["board"], "b-001")
        self.assertEqual(result["nodes"], boards.MAX_NODES)


class PushNewTest(StoreCase):
    """`keel board push --new` (P4-3): a fresh board even when one is live, and every
    `board` line in that push starts another, so a house's N boards cost N pushes (or one).

    The board that was live stays OPEN, as it does after `board new` (B3, B6): nothing he
    did not ask to close is closed, and the newest board is the live one."""

    def test_new_starts_a_fresh_board_while_one_is_live_and_closes_nothing(self):
        self.push('node a laptop "the first flow"')
        result = self.push('node b server "the second flow"', new=True)
        self.assertEqual(result["board"], "b-002")
        self.assertEqual(result["boards"], ["b-002"])
        first = boards.read_record(self.cfg, "b-001")
        self.assertIsNone(first["closed"], "the old live board is left open")
        self.assertEqual(first["nodes"], 1, "and nothing was drawn on it")
        self.assertEqual(self.push('node c box "more"')["board"], "b-002",
                         "the fresh board is the live one after it")

    def test_new_names_the_fresh_board_by_its_first_board_line(self):
        self.push('board "The first flow"\nnode a laptop "the first flow"')
        result = self.push('board "The first flow"\nnode b server "a fresh one"', new=True)
        self.assertEqual(result["boards"], ["b-002"],
                         "the same title as the live board still starts a fresh one")
        self.assertEqual(boards.read_record(self.cfg, "b-002")["title"], "The first flow")

    def test_every_board_line_in_a_new_push_is_a_board_of_its_own(self):
        """Three flows in one file: one call, three boards, the last one live."""
        text = ('board "Flow one"\nnode a laptop "a"\n'
                'board "Flow two"\nnode b server "b"\n'
                'board "Flow three"\nnode c box "c"\nnote c "hangs on c"')
        result = self.push(text, new=True)
        self.assertEqual(result["boards"], ["b-001", "b-002", "b-003"])
        titles = [boards.read_record(self.cfg, b)["title"] for b in result["boards"]]
        self.assertEqual(titles, ["Flow one", "Flow two", "Flow three"])
        self.assertEqual([boards.read_record(self.cfg, b)["nodes"] for b in result["boards"]],
                         [1, 1, 1])
        self.assertEqual(result["accepted"], 7, result)

    def test_rename_inside_a_new_push_renames_rather_than_splitting(self):
        result = self.push('board "Flow one"\nnode a laptop "a"\nboard rename "Flow 1"', new=True)
        self.assertEqual(result["boards"], ["b-001"])
        self.assertEqual(boards.read_record(self.cfg, "b-001")["title"], "Flow 1")

    def test_new_travels_through_the_action_verb(self):
        self.push('node a laptop "the first flow"')
        result = actions.act(self.cfg, self.board, {"verb": "board.push", "card": self.card,
                                                     "ops": 'node b server "b"', "new": True})
        self.assertEqual(result["board"], "b-002")


class DuplicateTest(StoreCase):
    """The same push, from the same caller, inside ten seconds, lands once.

    b-003 (c-302) is the case: one `board` fence in a spoken answer, read by the stream as
    it closed and again off the finished text, and drawn twice 6 ms apart. The pen holds the
    first half of this rule; the store holds this half, because a cap only the pen holds is
    one another door gets past.
    """

    def test_the_same_ops_from_the_same_caller_land_once_and_answer_ok(self):
        first = self.push(actor="house", caller={"actor": "house", "card": self.card})
        again = self.push(actor="house", caller={"actor": "house", "card": self.card})
        self.assertFalse(first["duplicate"])
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["board"], "b-001")
        self.assertEqual(boards.read_record(self.cfg, "b-001")["nodes"], 2)
        model = boards.build(boards.ops_lines(self.cfg, "b-001"))
        self.assertEqual(len([a for a in model["attachments"] if a["kind"] == "step"]), 2)

    def test_the_second_reading_is_accounted_for_in_the_skipped_log(self):
        self.push(actor="house", caller={"actor": "house", "card": self.card})
        self.push(actor="house", caller={"actor": "house", "card": self.card})
        skipped = (boards.board_dir(self.cfg, "b-001") / boards.SKIPPED_FILE).read_text()
        self.assertIn("\tdup\t", skipped)
        self.assertIn("house", skipped)

    def test_whitespace_and_a_stray_fence_mark_do_not_make_it_a_different_push(self):
        self.push('node a box "a"\nstep a "one"')
        again = self.push('```\nnode  a   box "a"\n\nstep a "one"\n```')
        self.assertTrue(again["duplicate"])

    def test_a_different_caller_or_different_ops_are_not_a_duplicate(self):
        self.push('node a box "a"', actor="house", caller={"actor": "house", "card": self.card})
        self.assertFalse(self.push('node a box "a"', actor="human")["duplicate"])
        self.assertFalse(self.push('node b box "b"', actor="human")["duplicate"])

    def test_the_window_is_ten_seconds_and_not_forever(self):
        self.push('node a box "a"')
        record = boards.read_record(self.cfg, "b-001")
        stale = dict(record["last_push"])
        self.assertTrue(boards.dup_of(record, stale["sig"], "cli"))
        record["last_push"] = dict(stale, at="2020-01-01T00:00:00.000000+00:00")
        self.assertFalse(boards.dup_of(record, stale["sig"], "cli"))
        self.assertLessEqual(boards.DUP_SECONDS, 10)


class HouseTest(StoreCase):
    """A house draws on its own card's board and nothing else. `KEEL_CARD` is the fact it
    cannot restate: the harness sets it, and it says which house this is."""

    def test_a_house_may_push_to_its_own_card(self):
        result = self.push(caller={"actor": "house", "card": self.card}, actor="house")
        self.assertEqual(result["board"], "b-001")
        self.assertEqual(boards.read_record(self.cfg, "b-001")["actor"], "house")

    def test_a_house_may_not_push_to_another_card_or_to_the_talkers_board(self):
        with self.assertRaises(boards.BoardError) as caught:
            self.push(caller={"actor": "house", "card": "c-999"})
        self.assertIn("c-999", str(caught.exception))
        with self.assertRaises(boards.BoardError):
            boards.push(self.cfg, SCRIPT, talker=True,
                        caller={"actor": "house", "card": self.card})

    def test_the_talkers_board_is_linked_to_no_card(self):
        boards.push(self.cfg, SCRIPT, talker=True, actor="talker")
        record = boards.read_record(self.cfg, "b-001")
        self.assertEqual(record["source"], {"kind": "talker", "card": None})
        self.assertEqual(record["actor"], "talker")


HOUSE = {"actor": "house", "card": "c-001"}
STRANGER = {"actor": "house", "card": "c-999"}
TALKER = {"actor": "talker", "card": None}
HUMAN = {"actor": "human", "card": None}


class OwnershipTest(StoreCase):
    """Who may CHANGE a board, which is not the same question as who may read one.

    `push` has always been held to the caller's own card. `open`, `new --from` and `close`
    change a board just as much: reopening one makes it the source's live board again, so
    the next push lands there, and closing one ends a sitting that was not the caller's.
    A house scoped to c-999 could do all three to the talker's board and to any other
    card's, locally and over HTTP, and its fork became the OTHER source's live board while
    being stamped as the house's. Every verb that writes takes the caller now.
    """

    def seed_talker(self):
        boards.push(self.cfg, SCRIPT, talker=True, actor="talker", caller=TALKER)
        return "b-001"

    def test_a_house_cannot_open_or_close_the_talkers_board(self):
        self.seed_talker()
        for act in (lambda: boards.reopen(self.cfg, "b-001", caller=STRANGER),
                    lambda: boards.close(self.cfg, "b-001", caller=STRANGER)):
            with self.assertRaises(boards.BoardError) as caught:
                act()
            self.assertIn("c-999", str(caught.exception))
        self.assertIsNone(boards.read_record(self.cfg, "b-001")["closed"])

    def test_a_house_cannot_open_or_close_another_cards_board(self):
        self.push(caller=HOUSE)
        for act in (lambda: boards.reopen(self.cfg, "b-001", caller=STRANGER),
                    lambda: boards.close(self.cfg, "b-001", caller=STRANGER)):
            with self.assertRaises(boards.BoardError):
                act()

    def test_the_talker_cannot_change_a_cards_board(self):
        self.push(caller=HOUSE)
        with self.assertRaises(boards.BoardError) as caught:
            boards.close(self.cfg, "b-001", caller=TALKER)
        self.assertIn("talker", str(caught.exception))

    def test_he_may_change_any_board(self):
        self.seed_talker()
        self.assertTrue(boards.close(self.cfg, "b-001", caller=HUMAN)["closed"])
        self.assertTrue(boards.reopen(self.cfg, "b-001", caller=HUMAN)["live"])
        self.assertEqual(boards.copy_to_new(self.cfg, "b-001", caller=HUMAN)["id"], "b-002")

    def test_a_fork_is_always_the_callers_own_source_never_the_originals(self):
        """A house may COPY a shape it can see; what it may not do is make a board on
        somebody else's source. So the copy lands on the caller's own card."""
        self.seed_talker()
        row = boards.copy_to_new(self.cfg, "b-001", caller=HOUSE)
        self.assertEqual(row["source"], {"kind": "card", "card": self.card})
        self.assertTrue(row["live"])
        self.assertTrue(boards.read_record(self.cfg, "b-001")["closed"] is None)
        self.assertTrue(boards.row_of(self.cfg, boards.read_record(self.cfg, "b-001"))["live"],
                        "the talker's own board is still the talker's live board")

    def test_his_own_fork_keeps_the_boards_source(self):
        self.seed_talker()
        self.assertEqual(boards.copy_to_new(self.cfg, "b-001", caller=HUMAN)["source"],
                         {"kind": "talker", "card": None})

    def test_reading_is_open_to_anyone(self):
        self.seed_talker()
        self.assertTrue(boards.show(self.cfg, "b-001")["ops"])
        self.assertEqual(len(boards.listing(self.cfg)), 1)


class ConcurrencyTest(StoreCase):
    """Two pushes at once. The store is read, changed and rewritten whole, so without a
    lock two of them mint the same `b-<n>` and the second's `board.json` is written from a
    snapshot taken before the first appended to `ops.log`."""

    def push_many(self, calls):
        import threading
        errors = []

        def run(fn):
            try:
                fn()
            except Exception as error:  # noqa: BLE001 - reported, not swallowed
                errors.append(error)

        threads = [threading.Thread(target=run, args=(fn,)) for fn in calls]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(errors, [])

    def test_two_pushes_to_two_fresh_sources_mint_two_ids(self):
        second = self.board.create("personal", "another card", actor="human")
        self.push_many([lambda: boards.push(self.cfg, SCRIPT, card=self.card),
                        lambda: boards.push(self.cfg, SCRIPT, card=second)] * 3)
        ids = sorted(record["id"] for record in boards.records(self.cfg))
        self.assertEqual(ids, ["b-001", "b-002"], "one board per source, no id minted twice")

    def test_concurrent_pushes_to_one_board_keep_the_record_and_the_log_in_step(self):
        """Six DIFFERENT pushes, because six identical ones are one push said six times and
        the duplicate rule is what answers those."""
        self.push(caller=HOUSE)
        self.push_many([(lambda n=n: boards.push(self.cfg, f'step board "step {n}"',
                                                 card=self.card)) for n in range(6)])
        lines = boards.ops_lines(self.cfg, "b-001")
        markers = [line for line in lines if line.startswith(boards.PUSH_MARK)]
        record = boards.read_record(self.cfg, "b-001")
        self.assertEqual(len(markers), 7, "one marker per push that wrote")
        model = boards.build(lines)
        self.assertEqual(record["attachments"], len(model["attachments"]),
                         "board.json counts the attachments ops.log actually holds")
        self.assertEqual(record["attachments"], 9)


class IndexTest(StoreCase):
    def seed(self):
        self.push('board "The memory system"\ngroup all "Always injected"\n'
                  'node idx file "MEMORY.md index" in all\n'
                  'note idx "the index line is the trigger"')
        boards.push(self.cfg, 'board "The drain pools"\nnode card box "a card"\n'
                              'step card "A card starts in Inbox"', talker=True)

    def test_list_is_newest_first_and_says_which_board_is_live(self):
        self.seed()
        rows = boards.listing(self.cfg)
        self.assertEqual([row["id"] for row in rows], ["b-002", "b-001"])
        self.assertTrue(all(row["live"] for row in rows), "each source has one live board")
        self.assertEqual(rows[0]["source"]["kind"], "talker")
        self.assertEqual(rows[1]["nodes"], 1)
        self.assertEqual(rows[1]["attachments"], 1)

    def test_list_can_be_narrowed_to_one_cards_boards(self):
        self.seed()
        rows = boards.listing(self.cfg, card=self.card)
        self.assertEqual([row["id"] for row in rows], ["b-001"])

    def test_find_scores_the_title_the_summary_the_labels_and_what_is_attached(self):
        self.seed()
        found = boards.find(self.cfg, "memory system")
        self.assertEqual(found[0]["id"], "b-001")
        self.assertGreater(found[0]["score"], 0)
        self.assertEqual([row["id"] for row in boards.find(self.cfg, "starts in Inbox")], ["b-002"],
                         "a step's words are searchable")
        self.assertEqual([row["id"] for row in boards.find(self.cfg, "MEMORY.md")], ["b-001"],
                         "a node label is searchable")
        self.assertEqual(boards.find(self.cfg, "nothing at all here"), [])

    def test_find_needs_something_to_look_for(self):
        with self.assertRaises(boards.BoardError):
            boards.find(self.cfg, "   ")

    def test_close_writes_the_labels_as_the_summary_and_ends_the_live_board(self):
        self.push()
        row = boards.close(self.cfg, "b-001")
        self.assertIn("His phone", row["summary"])
        self.assertTrue(row["closed"])
        self.assertFalse(row["live"])
        self.assertIsNone(boards.live_record(self.cfg, {"kind": "card", "card": self.card}))

    def test_close_takes_a_summary_of_his_own(self):
        self.push()
        self.assertEqual(boards.close(self.cfg, "b-001", "the VPS talk")["summary"], "the VPS talk")

    def test_a_push_after_a_close_starts_a_new_board(self):
        self.push()
        boards.close(self.cfg, "b-001")
        self.assertEqual(self.push()["board"], "b-002")

    def test_open_makes_a_closed_board_live_again_so_a_push_continues_it(self):
        self.push()
        boards.close(self.cfg, "b-001")
        self.push('node other box "a second sitting"')     # b-002
        self.assertTrue(boards.reopen(self.cfg, "b-001")["live"])
        self.assertEqual(self.push('note board "back on the first"')["board"], "b-001")

    def test_new_from_copies_the_ops_into_a_new_live_board(self):
        self.push()
        row = boards.copy_to_new(self.cfg, "b-001")
        self.assertEqual(row["id"], "b-002")
        self.assertEqual((row["nodes"], row["attachments"]), (2, 3))
        self.assertTrue(row["title"].endswith("(copy)"))
        self.assertEqual(boards.ops_lines(self.cfg, "b-002"), boards.ops_lines(self.cfg, "b-001"))
        self.assertEqual(self.push('note board "x"')["board"], "b-002")

    def test_show_prints_the_ops(self):
        self.push()
        self.assertIn('node phone phone "His phone"', boards.show(self.cfg, "b-001")["ops"])

    def test_an_id_that_is_not_one_is_refused_rather_than_becoming_a_path(self):
        for bad in ("../../etc", "b-1/../..", "", "board"):
            with self.assertRaises(boards.BoardError):
                boards.read_record(self.cfg, bad)


class LiveChannelTest(StoreCase):
    """The deck asks for what came after the last line it holds, and appends that."""

    def test_since_returns_only_what_arrived_after_it(self):
        self.push()
        whole = boards.api_board(self.cfg, "b-001")
        self.assertEqual(whole["since"], 0)
        self.assertEqual(len(whole["lines"]), whole["next"])
        self.push('note board "one more"')
        more = boards.api_board(self.cfg, "b-001", since=whole["next"])
        self.assertEqual([line for line in more["lines"] if not line.startswith("#")],
                         ['note board "one more"'])
        self.assertEqual(more["attachments"], 4)

    def test_a_cursor_past_the_end_or_below_zero_is_clamped(self):
        self.push()
        self.assertEqual(boards.api_board(self.cfg, "b-001", since=9999)["lines"], [])
        self.assertTrue(boards.api_board(self.cfg, "b-001", since=-5)["lines"])

    def test_a_card_carries_its_newest_board_and_how_many_it_has(self):
        self.assertIsNone(boards.card_board(self.cfg, self.card))
        self.push()
        boards.close(self.cfg, "b-001")
        self.push('node other box "x"')
        shown = boards.card_board(self.cfg, self.card)
        self.assertEqual((shown["id"], shown["count"]), ("b-002", 2))


class VerbTest(StoreCase):
    """`board.push` and friends through the deck's action table, the way a remote `keel
    board` sends them: the caller decides the actor, and a house is held to its own card."""

    def act(self, body):
        return actions.act(self.cfg, self.board, body)

    def test_a_push_through_the_action_verb_lands_on_the_store(self):
        result = self.act({"verb": "board.push", "ops": SCRIPT, "card": self.card})
        self.assertEqual(result["nodes"], 2)
        self.assertEqual(boards.read_record(self.cfg, "b-001")["actor"], "human")

    def test_every_board_verb_is_reachable_and_refuses_with_one_line(self):
        self.act({"verb": "board.push", "ops": SCRIPT, "card": self.card})
        self.assertEqual(self.act({"verb": "board.list"})[0]["id"], "b-001")
        self.assertEqual(self.act({"verb": "board.find", "text": "phone"})[0]["id"], "b-001")
        self.assertIn('node phone phone "His phone"', self.act({"verb": "board.show", "id": "b-001"})["ops"])
        self.assertEqual(self.act({"verb": "board.close", "id": "b-001"})["closed"] is None, False)
        self.assertTrue(self.act({"verb": "board.open", "id": "b-001"})["live"])
        self.assertEqual(self.act({"verb": "board.new", "from": "b-001"})["id"], "b-002")
        with self.assertRaises(actions.ActionError):
            self.act({"verb": "board.show", "id": "b-404"})

    def test_the_verbs_are_in_the_action_table_the_atlas_is_checked_against(self):
        self.assertEqual(set(actions.BOARD_VERBS),
                         {"board.push", "board.list", "board.find",
                          "board.show", "board.open", "board.new", "board.close",
                          "board.delete", "board.restore"})


class CliTest(StoreCase):
    """`keel board` end to end, as a house on this machine runs it."""

    def run_keel(self, argv, stdin=""):
        env = dict(os.environ, KEEL_HOME=str(ROOT))
        env.pop("KEEL_URL", None)
        env["KEEL_CONFIG"] = str(self.write_toml())
        return subprocess.run([str(ROOT / "bin" / "keel"), "board", *argv], input=stdin,
                              capture_output=True, text=True, env=env, timeout=60)

    def write_toml(self) -> Path:
        path = self.dir / "keel.toml"
        path.write_text("[keel]\n"
                        f'state_dir = "{self.cfg.state_dir}"\n'
                        f'segments_dir = "{self.cfg.segments_dir}"\n'
                        f'adapters_dir = "{self.cfg.adapters_dir}"\n'
                        "serve_port = 8791\n"
                        "[spaces.personal]\n"
                        f'config_dir = "{self.dir / "cfg-personal"}"\n')
        return path

    def test_push_on_stdin_prints_the_id_the_counts_and_the_link(self):
        result = self.run_keel(["push", "--card", self.card], stdin=SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("b-001", result.stdout)
        self.assertIn("2 nodes", result.stdout)
        self.assertIn("3 attachments", result.stdout)
        self.assertIn("/board/b-001", result.stdout)

    def test_push_from_a_file_is_what_a_confined_house_and_the_talker_use(self):
        ops = self.dir / "ops.txt"
        ops.write_text(SCRIPT)
        result = self.run_keel(["push", "--card", self.card, "--file", str(ops), "--json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["nodes"], 2)

    def test_a_refusal_is_one_line_on_stderr_and_exit_one(self):
        result = self.run_keel(["show", "b-404"])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(result.stderr.strip().splitlines()), 1, result.stderr)
        self.assertTrue(result.stderr.startswith("keel board: "))


    def test_find_and_list_print_a_row_each(self):
        self.run_keel(["push", "--card", self.card], stdin=SCRIPT)
        listed = self.run_keel(["list"])
        self.assertIn("b-001", listed.stdout)
        self.assertIn("How Keel is laid out", listed.stdout)
        found = self.run_keel(["find", "phone"])
        self.assertIn("b-001", found.stdout)
        self.assertIn("no boards", self.run_keel(["list", "--card", "c-999"]).stdout)


class ExampleBoardTest(unittest.TestCase):
    """The worked example in the docs parses clean, so what the docs show is what draws.

    `tests/fixtures/example.board` is the shape a board should have: ONE diagram with its
    places as groups, and the notes, steps and table hanging on the nodes they are about
    rather than standing as pictures of their own.
    """

    def test_the_example_board_parses_and_folds_without_one_skip(self):
        text = (ROOT / "tests" / "fixtures" / "example.board").read_text()
        model, skipped = boards.new_model(), []
        for raw in text.splitlines():
            try:
                op = boards.parse_line(raw)
                if op is not None:
                    boards.apply_op(model, op)
            except boards.BadLine as why:
                skipped.append(f"{why}: {raw}")
        self.assertEqual(skipped, [], "the example board does not draw clean")
        self.assertLessEqual(len(model["nodes"]), boards.MAX_NODES)
        self.assertGreaterEqual(len(model["groups"]), 2)
        self.assertTrue(any(a["kind"] == "step" for a in model["attachments"]))
        self.assertTrue(any(a["kind"] == "table" for a in model["attachments"]))
        self.assertTrue(any(a["kind"] == "note" for a in model["attachments"]))
        self.assertTrue(any(a["at"] != "board" for a in model["attachments"]),
                        "everything hangs on the board, so nothing hangs on a node")
        self.assertNotIn("frame ", text, "the example still speaks the old grammar")


class DeckParserTest(unittest.TestCase):
    """The deck's own parser, against the same fixture and the same vocabulary.

    The vocabulary comparison is a source read, so it runs everywhere: an op, an icon, a
    mark or an arrow added on one side alone fails here. The fixture run needs node, which
    the box has and a bare CI box might not, so it is skipped rather than faked.
    """

    def names(self, constant: str) -> list[str]:
        match = re.search(r"var " + constant + r"\s*=\s*\[(.*?)\]", BOARD_JS.read_text(), re.S)
        self.assertIsNotNone(match, f"{constant} is not declared in app/ui.board.js")
        return re.findall(r"'([^']+)'", match.group(1))

    def test_the_two_sides_name_the_same_ops_kinds_icons_marks_and_arrows(self):
        self.assertEqual(self.names("OPS"), list(boards.OPS))
        self.assertEqual(self.names("ATTACH_KINDS"), list(boards.ATTACH_KINDS))
        self.assertEqual(self.names("MARKS"), list(boards.MARKS))
        self.assertEqual(self.names("BOARD_MODES"), list(boards.BOARD_MODES))
        self.assertEqual(sorted(self.names("ICON_NAMES")), sorted(boards.ICONS))
        self.assertEqual(sorted(self.names("ARROWS")), sorted(boards.ARROWS))


    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_decks_parser_agrees_with_the_server_over_the_fixture(self):
        harness = ROOT / "tests" / "fixtures" / "board-parse.js"
        result = subprocess.run(["node", str(harness), str(BOARD_JS), str(FIXTURE)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        answers = json.loads(result.stdout)
        expected = [verdict for verdict, _ in rows()]
        self.assertEqual(len(answers), len(expected))
        for (verdict, line), said in zip(rows(), answers):
            with self.subTest(line=line):
                self.assertEqual(said, verdict, f"the deck parsed {line!r} as {said}")

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_decks_model_folds_a_board_the_way_the_servers_does(self):
        """One model, one set of attachments, in one order: the two halves have to agree
        about what hangs where, or the outline shows what the record does not say."""
        harness = ROOT / "tests" / "fixtures" / "board-model.js"
        result = subprocess.run(["node", str(harness), str(BOARD_JS)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        said = json.loads(result.stdout)
        model = boards.build(said["lines"])
        self.assertEqual(said["nodes"], [n["id"] for n in model["nodes"]])
        self.assertEqual(said["groups"], [g["id"] for g in model["groups"]])
        self.assertEqual([tuple(pair) for pair in said["attachments"]],
                         [(a["kind"], a["at"]) for a in model["attachments"]])
        self.assertEqual(said["steps"],
                         [a["text"] for a in model["attachments"] if a["kind"] == "step"])

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_a_label_too_long_for_its_node_is_cut_to_fit_rather_than_painted_past_it(self):
        """A node box is sized to its own text and then CLAMPED, so a long label used to be
        painted across the diagram (`state/cards/c-001/board-files` on a 184px box). The cut
        is the arithmetic half of that, so it is a pure function and this runs it."""
        harness = ROOT / "tests" / "fixtures" / "board-fit.js"
        result = subprocess.run(["node", str(harness), str(BOARD_JS)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True}, result.stdout)

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_zoom_clamp_holds_the_band_the_stage_may_be_scaled_to(self):
        harness = ROOT / "tests" / "fixtures" / "board-zoom.js"
        result = subprocess.run(["node", str(harness), str(BOARD_JS)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True}, result.stdout)


if __name__ == "__main__":
    unittest.main()
