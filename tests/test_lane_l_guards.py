"""The markers only Keel's own paths write, and the kind only he changes (lane L, round 3).

`options.publishing` (his Approve outcome in flight), `options.landing` and
`options.rotate` are records a card never carries because someone typed them: no create,
split or row insert may bring one in, by any actor. `options.kind` decides a work house's
fence (a research card cannot push), so only he changes it after create.
"""

import json
import tempfile
import unittest
from pathlib import Path

from keel.board import Board, Refused
from tests import test_cli

RESERVED = ("publishing", "landing", "rotate")


class ReservedOptionsTest(test_cli.KbCase):

    def test_no_reserved_marker_through_create_by_any_actor(self):
        self.kb("list")                        # the first kb writes his token
        for key in RESERVED:
            for env in ({}, {"KEEL_TOKEN": self.token}):
                code, _, err = self.kb("create", "--space", "work", "--title", "x",
                                       "--option", f'{key}={{"state":"testing"}}', env=env)
                self.assertEqual(code, 1, (key, env))
                self.assertIn(f"options.{key}", err)
        self.assertEqual(self.kb_json("list"), [])


class ReservedOnTheBoardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.board = Board(Path(self.tmp.name) / "board.db")
        self.parent = self.board.create("work", "the parent", actor="human")

    def tearDown(self):
        self.board.close()
        self.tmp.cleanup()

    def test_split_and_insert_refuse_every_reserved_marker(self):
        for key in RESERVED:
            for actor in ("human", "drain", "house", "cli"):
                with self.assertRaisesRegex(Refused, f"options.{key}"):
                    self.board.split(self.parent, [{"title": "a", "options": {key: {"x": 1}}}], actor)
                with self.assertRaisesRegex(Refused, f"options.{key}"):
                    self.board.insert_card({"space": "work", "title": "t", "stage": "inbox",
                                            "autonomy": "autonomous", "options": {key: {"x": 1}}},
                                           actor)
        self.assertEqual(self.board.children(self.parent), [])

    def test_his_kind_only_after_create(self):
        card = self.board.create("work", "look", actor="cli", options={"kind": "research"})
        for actor in ("house", "cli", "drain", "voice", "fetch", "hook"):
            with self.assertRaisesRegex(Refused, "options.kind", msg=actor):
                self.board.set_fields(card, {"options": {"kind": "feature"}}, actor)
        self.board.set_fields(card, {"options": {"kind": "feature"}}, "human")
        self.assertEqual(self.board.get(card)["options"]["kind"], "feature")

    def test_any_stage_move_clears_the_marker(self):
        card = self.board.create("work", "c", actor="human")
        self.board.stage(card, "assigned", "human")
        self.board.stage(card, "building", "drain")
        self.board.stage(card, "review", "house", plan_ref="p", output_ref="o")
        self.board.mark_publishing(card, "human")
        self.board.stage(card, "building", "human")
        self.assertNotIn("publishing", self.board.get(card)["options"])

    def test_the_nonce_is_never_stored_or_shown(self):
        card = self.board.create("work", "c", actor="human")
        self.board.stage(card, "assigned", "human")
        self.board.stage(card, "building", "drain")
        self.board.stage(card, "review", "house", plan_ref="p", output_ref="o")
        nonce = self.board.mark_publishing(card, "human")
        shown = json.dumps(dict(self.board.get(card), events=self.board.events(card)))
        self.assertNotIn(nonce, shown)
        raw = self.board.conn.execute("SELECT options FROM cards WHERE id = ?", (card,)).fetchone()[0]
        self.assertNotIn(nonce, raw)
        self.assertIn("digest", self.board.get(card)["options"]["publishing"])


class KindThroughKbTest(test_cli.KbCase):
    def test_kind_through_kb_needs_his_token(self):
        code, out, err = self.kb("create", "--space", "work", "--title", "x",
                                 "--option", "kind=research")
        self.assertEqual(code, 0, err)
        card = out
        for env in ({}, {"KEEL_CARD": card}, {"KEEL_TOKEN": "wrong"}):
            code, _, err = self.kb("set", card, "options.kind=feature", env=env)
            self.assertEqual(code, 1, env)
            self.assertIn("options.kind", err)
        code, _, err = self.kb("set", card, "options.kind=feature", env={"KEEL_TOKEN": self.token})
        self.assertEqual(code, 0, err)
        self.assertEqual(self.kb_json("show", card)["options"]["kind"], "feature")


if __name__ == "__main__":
    unittest.main()
