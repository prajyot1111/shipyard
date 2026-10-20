"""Deleting a board (lane BD, 2026-09-24): "I need an option to delete boards too."

A delete MOVES the board under `state/boards/.trash/`, so every reader that lists or opens a
board stops seeing it without being told; he can restore it for 30 days, and the drain's
upkeep purges it after that. A house may delete only its own card's boards, Harbor only its
own talker boards, and every other board is his alone.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from keel import actions, boardlist, boards, boardtrash, boarduses, drain, planlint, plangate
from keel import planformat, planroute
from keel.board import Board
from keel.config import human_token
from tests.helpers import make_config

SCRIPT = 'board "The drain"\nnode a box "A card"\nnode b server "The drain"\nedge a -> b\nstep a "It is claimed"\n'


class TrashCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = make_config(Path(self.tmp.name))
        self.cfg.serve_port = 8791
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        self.card = self.board.create("personal", "the blackboard", repo="keel", actor="human")
        self.other = self.board.create("personal", "another card", repo="keel", actor="human")
        self.house = {"actor": "house", "card": self.card}
        self.stranger = {"actor": "house", "card": self.other}
        self.talker = {"actor": "talker", "card": None}
        self.human = {"actor": "human", "card": None}

    def card_board(self, card=None, text=SCRIPT, new=False):
        card = card or self.card
        return boards.push(self.cfg, text, card=card, caller={"actor": "house", "card": card},
                           actor="house", new=new)["board"]

    def talker_board(self, text=SCRIPT):
        return boards.push(self.cfg, text, talker=True, caller=self.talker, actor="talker")["board"]

    def delete(self, board_id, caller):
        return boardtrash.delete(self.cfg, [board_id], caller)


class WhoMayDeleteTest(TrashCase):
    def test_a_house_deletes_its_own_cards_board(self):
        mine = self.card_board()
        result = self.delete(mine, self.house)
        self.assertEqual([row["id"] for row in result["deleted"]], [mine])
        self.assertIsNotNone(boardtrash.trashed_record(self.cfg, mine))

    def test_a_house_is_refused_another_cards_board(self):
        theirs = self.card_board(self.other)
        with self.assertRaises(boards.BoardError) as caught:
            self.delete(theirs, self.house)
        self.assertIn(self.other, str(caught.exception))
        self.assertIsNone(boardtrash.trashed_record(self.cfg, theirs))
        self.assertTrue(boards.read_record(self.cfg, theirs))

    def test_a_house_is_refused_the_talkers_board(self):
        harbor = self.talker_board()
        with self.assertRaises(boards.BoardError):
            self.delete(harbor, self.house)

    def test_harbor_deletes_its_own_talker_board(self):
        harbor = self.talker_board()
        self.assertEqual(self.delete(harbor, self.talker)["deleted"][0]["id"], harbor)

    def test_harbor_is_refused_a_cards_board(self):
        mine = self.card_board()
        with self.assertRaises(boards.BoardError) as caught:
            self.delete(mine, self.talker)
        self.assertIn("talker", str(caught.exception))

    def test_he_deletes_any_board(self):
        ids = [self.card_board(), self.card_board(self.other), self.talker_board()]
        result = boardtrash.delete(self.cfg, ids, self.human)
        self.assertEqual(sorted(row["id"] for row in result["deleted"]), sorted(ids))
        self.assertEqual(boards.listing(self.cfg), [])

    def test_anyone_else_is_refused_the_way_a_human_only_verb_is(self):
        """A terminal with no house, no talker and no token is not him: deleting another
        source's board is gated exactly as `--actor human` is."""
        mine = self.card_board()
        for caller in ({"actor": "cli", "card": None}, {"actor": "drain", "card": None}, None):
            with self.assertRaises(boards.BoardError) as caught:
                self.delete(mine, caller)
            self.assertIn("KEEL_TOKEN", str(caught.exception))

    def test_a_stack_is_refused_whole_when_one_board_is_not_the_callers(self):
        mine, theirs = self.card_board(), self.card_board(self.other)
        with self.assertRaises(boards.BoardError):
            boardtrash.delete(self.cfg, [mine, theirs], self.house)
        self.assertEqual({row["id"] for row in boards.listing(self.cfg)}, {mine, theirs})

    def test_the_local_caller_is_him_only_with_the_token(self):
        saved = {name: os.environ.get(name) for name in ("KEEL_CARD", "KEEL_TALKER", "KEEL_TOKEN")}
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in saved.items()])
        for name in saved:
            os.environ.pop(name, None)
        self.assertEqual(boardtrash.local_caller(self.cfg)["actor"], "cli")
        os.environ["KEEL_TOKEN"] = human_token(self.cfg.token_path)
        self.assertEqual(boardtrash.local_caller(self.cfg)["actor"], "human")
        os.environ["KEEL_CARD"] = self.card
        self.assertEqual(boardtrash.local_caller(self.cfg), {"actor": "house", "card": self.card})


class TheDeleteEventTest(TrashCase):
    def test_the_record_names_who_deleted_it_and_when(self):
        for caller, who in ((self.house, self.card), (self.human, "you")):
            board_id = self.card_board(new=True)
            self.delete(board_id, caller)
            deleted = boardtrash.trashed_record(self.cfg, board_id)["deleted"]
            self.assertEqual(deleted["by"], who)
            self.assertEqual(deleted["actor"], caller["actor"])
            self.assertLess(boards.seconds_since(deleted["at"]), 60)
        harbor = self.talker_board()
        self.delete(harbor, self.talker)
        self.assertEqual(boardtrash.trashed_record(self.cfg, harbor)["deleted"]["by"], "the talker")


class DeleteHidesEverywhereTest(TrashCase):
    def setUp(self):
        super().setUp()
        self.gone = self.card_board()
        self.kept = self.card_board(new=True, text='board "The deck"\nnode d server "The deck"\n')
        self.delete(self.gone, self.human)

    def test_the_list_and_the_verbs_list(self):
        self.assertEqual([row["id"] for row in boards.listing(self.cfg)], [self.kept])
        self.assertEqual([row["id"] for row in boardlist.listing(self.cfg)["rows"]], [self.kept])

    def test_search_both_ways(self):
        self.assertEqual(boards.find(self.cfg, "drain"), [])
        self.assertEqual(boardlist.listing(self.cfg, "drain")["rows"], [])

    def test_a_cards_boards_which_is_what_its_stack_is_drawn_from(self):
        block = boards.card_board(self.cfg, self.card)
        self.assertEqual([row["id"] for row in block["boards"]], [self.kept])
        self.assertEqual(block["count"], 1)

    def test_reading_it_says_it_is_in_the_trash(self):
        for read in (lambda: boards.read_record(self.cfg, self.gone),
                     lambda: boards.show(self.cfg, self.gone),
                     lambda: boards.api_board(self.cfg, self.gone)):
            with self.assertRaises(boards.BoardError) as caught:
                read()
            self.assertIn(boards.DELETED_MARK, str(caught.exception))

    def test_a_push_does_not_land_on_it(self):
        result = boards.push(self.cfg, 'node z box "Z"', card=self.card, caller=self.house)
        self.assertEqual(result["board"], self.kept)

    def test_the_trash_lists_it_with_who_and_when_it_is_purged(self):
        rows = boardtrash.trashed(self.cfg)
        self.assertEqual([row["id"] for row in rows], [self.gone])
        self.assertEqual(rows[0]["deleted"]["by"], "you")
        self.assertIn("purge_at", rows[0])
        listed = boardlist.listing(self.cfg, deleted=True)["rows"]
        self.assertEqual([row["id"] for row in listed], [self.gone])
        self.assertEqual(listed[0]["card"]["title"], "the blackboard")

    def test_an_id_is_never_minted_twice(self):
        fresh = boards.push(self.cfg, 'node q box "Q"', card=self.other,
                            caller=self.stranger)["board"]
        self.assertNotIn(fresh, (self.gone, self.kept))


class TheLiveBoardTest(TrashCase):
    def test_deleting_the_live_board_clears_it_as_live(self):
        older = self.card_board()
        live = self.card_board(new=True, text='board "Second"\nnode s box "S"\n')
        self.assertEqual(boards.live_record(self.cfg, {"kind": "card", "card": self.card})["id"], live)
        result = self.delete(live, self.house)
        self.assertTrue(result["deleted"][0]["live_cleared"])
        now_live = boards.live_record(self.cfg, {"kind": "card", "card": self.card})
        self.assertEqual(now_live["id"], older)
        self.assertNotIn(live, [row["id"] for row in boards.listing(self.cfg) if row["live"]])

    def test_deleting_the_only_board_leaves_the_card_with_none(self):
        only = self.card_board()
        self.delete(only, self.house)
        self.assertIsNone(boards.live_record(self.cfg, {"kind": "card", "card": self.card}))
        self.assertIsNone(boards.card_board(self.cfg, self.card))
        fresh = boards.push(self.cfg, 'node n box "N"', card=self.card, caller=self.house)["board"]
        self.assertNotEqual(fresh, only)


class RestoreTest(TrashCase):
    def test_restore_brings_it_back_everywhere(self):
        board_id = self.card_board()
        self.delete(board_id, self.house)
        row = boardtrash.restore(self.cfg, board_id, self.human)
        self.assertEqual(row["id"], board_id)
        self.assertEqual([r["id"] for r in boards.listing(self.cfg)], [board_id])
        self.assertTrue(boards.find(self.cfg, "drain"))
        self.assertEqual(boardtrash.trashed(self.cfg), [])
        record = boards.read_record(self.cfg, board_id)
        self.assertNotIn("deleted", record)
        self.assertEqual(record["restored"]["by"], "you")
        self.assertTrue(boards.ops_lines(self.cfg, board_id))

    def test_only_he_restores(self):
        board_id = self.card_board()
        self.delete(board_id, self.house)
        for caller in (self.house, self.talker, {"actor": "cli", "card": None}):
            with self.assertRaises(boards.BoardError):
                boardtrash.restore(self.cfg, board_id, caller)
        self.assertIsNotNone(boardtrash.trashed_record(self.cfg, board_id))

    def test_restoring_a_board_that_is_not_in_the_trash_says_so(self):
        board_id = self.card_board()
        with self.assertRaises(boards.BoardError) as caught:
            boardtrash.restore(self.cfg, board_id, self.human)
        self.assertIn("not in the trash", str(caught.exception))


class PurgeTest(TrashCase):
    def age(self, board_id, days):
        path = boardtrash.trash_dir(self.cfg, board_id) / boards.BOARD_FILE
        record = json.loads(path.read_text())
        then = time.time() - days * 86400
        from datetime import datetime, timezone
        record["deleted"]["at"] = datetime.fromtimestamp(then, timezone.utc).isoformat()
        path.write_text(json.dumps(record))

    def test_purged_after_thirty_days_and_not_before(self):
        young, old = self.card_board(), self.card_board(new=True, text='board "Old"\nnode o box "O"\n')
        boardtrash.delete(self.cfg, [young, old], self.human)
        self.age(young, 29)
        self.age(old, 31)
        self.assertEqual(boardtrash.purge(self.cfg), [old])
        self.assertIsNotNone(boardtrash.trashed_record(self.cfg, young))
        self.assertIsNone(boardtrash.trashed_record(self.cfg, old))
        self.assertFalse(boardtrash.trash_dir(self.cfg, old).exists())
        with self.assertRaises(boards.BoardError):
            boardtrash.restore(self.cfg, old, self.human)

    def test_a_purged_id_is_not_minted_again(self):
        only = self.card_board()
        self.delete(only, self.human)
        self.age(only, 40)
        boardtrash.purge(self.cfg)
        fresh = self.card_board()
        self.assertNotEqual(fresh, only)

    def test_the_drains_upkeep_is_what_purges(self):
        board_id = self.card_board()
        self.delete(board_id, self.human)
        self.age(board_id, 31)
        drain.board_trash_upkeep(self.cfg)
        self.assertIsNone(boardtrash.trashed_record(self.cfg, board_id))

    def test_no_request_purges(self):
        """The delete, the list and the restore never purge: only the upkeep does."""
        board_id = self.card_board()
        self.delete(board_id, self.human)
        self.age(board_id, 31)
        boardtrash.trashed(self.cfg)
        boardlist.listing(self.cfg, deleted=True)
        self.delete(self.card_board(new=True, text='board "X"\nnode x box "X"\n'), self.human)
        self.assertIsNotNone(boardtrash.trashed_record(self.cfg, board_id))


PLAN = """# The plan

A plan that embeds a board.

```board The flow
{ref}
```
"""


class EmbedsTest(TrashCase):
    def setUp(self):
        super().setUp()
        self.board_id = self.card_board()
        self.plan = self.cfg.card_dir(self.card) / "plan.md"
        self.plan.write_text(PLAN.format(ref=self.board_id))
        self.board.stage(self.card, "assigned", "human")
        self.board.stage(self.card, "planning", "house", plan_ref=str(self.plan))
        (self.cfg.card_dir(self.other) / "context.md").write_text(PLAN.format(ref=self.board_id))

    def test_the_confirm_lists_the_documents_that_embed_it(self):
        found = boarduses.uses(self.cfg, self.board, [self.board_id])["uses"][self.board_id]
        self.assertEqual({(use["card"], use["doc"]) for use in found},
                         {(self.card, "plan"), (self.other, "outcome")})
        self.assertEqual({use["title"] for use in found}, {"the blackboard", "another card"})
        self.assertEqual(boarduses.uses(self.cfg, self.board, ["b-099"])["uses"]["b-099"], [])

    def test_an_embed_of_a_deleted_board_is_a_placeholder_not_an_error(self):
        self.delete(self.board_id, self.human)
        doc = planformat.parse(self.plan.read_text(), "plan.md")
        planroute.decorate(self.cfg, doc, self.plan.parent)
        block = next(b for b in planformat.all_blocks(doc["blocks"]) if b["type"] == "board")
        self.assertNotIn("missing", block)
        self.assertEqual(block["deleted"]["by"], "you")
        self.assertEqual(block["deleted"]["id"], self.board_id)

    def test_the_lint_warns_and_does_not_error(self):
        self.delete(self.board_id, self.human)
        doc = planformat.parse(self.plan.read_text(), "plan.md")
        found = planlint.board_ref_rules(doc, plangate.board_resolver(self.cfg))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["level"], "warn")
        self.assertIn("trash", found[0]["text"])

    def test_an_id_that_never_existed_is_still_an_error(self):
        doc = planformat.parse(PLAN.format(ref="b-077"), "plan.md")
        found = planlint.board_ref_rules(doc, plangate.board_resolver(self.cfg))
        self.assertEqual(found[0]["level"], "error")


class OverTheActionTableTest(TrashCase):
    def act(self, body):
        return actions.act(self.cfg, self.board, body)

    def test_the_decks_tap_is_him_and_deletes_a_stack(self):
        ids = [self.card_board(), self.card_board(new=True, text='board "B"\nnode b box "B"\n')]
        result = self.act({"verb": "board.delete", "ids": ids})
        self.assertEqual(len(result["deleted"]), 2)
        self.assertEqual(self.act({"verb": "board.list", "deleted": True})[0]["id"] in ids, True)
        self.assertEqual(self.act({"verb": "board.restore", "id": ids[0]})["id"], ids[0])

class BackupTest(unittest.TestCase):
    def test_the_trash_is_in_the_keel_set_until_it_is_purged(self):
        """BD-4: `bin/keel-backup` scans `state/` and excludes `state/boards/.attached` by
        path; the trash is not excluded, so a deleted board is backed up until purged."""
        script = (Path(__file__).resolve().parent.parent / "bin" / "keel-backup").read_text()
        self.assertIn("state/boards/.attached", script)
        self.assertNotIn("state/boards/.trash'", script)
        self.assertIn("state/boards/.trash/", script, "the script says the trash is IN")


if __name__ == "__main__":
    unittest.main()


class CliTest(TrashCase):
    """`keel board delete` and `restore` end to end, as a house and as him run them."""

    def run_keel(self, argv, **env_extra):
        import subprocess
        root = Path(__file__).resolve().parent.parent
        toml = Path(self.tmp.name) / "keel.toml"
        toml.write_text("[keel]\n"
                        f'state_dir = "{self.cfg.state_dir}"\n'
                        f'segments_dir = "{self.cfg.segments_dir}"\n'
                        f'adapters_dir = "{self.cfg.adapters_dir}"\n'
                        "serve_port = 8791\n"
                        "[spaces.personal]\n"
                        f'config_dir = "{Path(self.tmp.name) / "cfg-personal"}"\n')
        env = dict(os.environ, KEEL_HOME=str(root), KEEL_CONFIG=str(toml), **env_extra)
        for name in ("KEEL_URL", "KEEL_CARD", "KEEL_TALKER", "KEEL_TOKEN"):
            if name not in env_extra:
                env.pop(name, None)
        return subprocess.run([str(root / "bin" / "keel"), "board", *argv], capture_output=True,
                              text=True, env=env, timeout=60)

    def test_a_house_deletes_its_own_and_he_restores(self):
        mine, theirs = self.card_board(), self.card_board(self.other)
        refused = self.run_keel(["delete", theirs], KEEL_CARD=self.card)
        self.assertEqual(refused.returncode, 1)
        self.assertIn(self.other, refused.stderr)
        done = self.run_keel(["delete", mine], KEEL_CARD=self.card)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("in the trash", done.stdout)
        listed = self.run_keel(["list", "--deleted"])
        self.assertIn(mine, listed.stdout)
        self.assertIn(f"deleted by {self.card}", listed.stdout)
        self.assertEqual(self.run_keel(["restore", mine]).returncode, 1, "a bare terminal is not him")
        back = self.run_keel(["restore", mine], KEEL_TOKEN=human_token(self.cfg.token_path))
        self.assertEqual(back.returncode, 0, back.stderr)
        self.assertIn(mine, self.run_keel(["list"]).stdout)
