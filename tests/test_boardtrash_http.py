"""Deleting a board through the deck itself (lane BD): the routes the page reads, and the
action it sends, on a real server on a free port."""

import json
import urllib.parse

from keel import boards, planlint
from tests.test_serve import ServerCase

PLAN = """# The plan

A plan that embeds a board.

```board The flow
{ref}
```
"""


class DeckDeleteTest(ServerCase):
    def setUp(self):
        super().setUp()
        self.card = self.board.create("personal", "the blackboard", actor="human")
        self.board_id = boards.push(self.cfg, 'board "The drain"\nnode a box "A"\n',
                                    card=self.card)["board"]
        self.plan = self.cfg.card_dir(self.card) / "plan.md"
        self.plan.write_text(PLAN.format(ref=self.board_id))
        self.board.stage(self.card, "assigned", "human")
        self.board.stage(self.card, "planning", "house", plan_ref=str(self.plan))

    def post_action(self, body, page=True):
        status, _, raw = self.fetch("/api/action", json.dumps(body).encode(), "POST", page=page)
        return status, json.loads(raw)

    def delete(self):
        status, reply = self.post_action({"verb": "board.delete", "id": self.board_id})
        self.assertEqual(status, 200, reply)
        return reply

    def test_the_confirm_asks_which_documents_embed_it(self):
        uses = self.get_json("/api/boards/uses?ids=" + urllib.parse.quote(self.board_id + ",b-999"))
        self.assertEqual(uses["uses"][self.board_id][0]["card"], self.card)
        self.assertEqual(uses["uses"][self.board_id][0]["doc"], "plan")
        self.assertEqual(uses["uses"]["b-999"], [])

    def test_the_page_deletes_and_the_board_is_gone_from_the_list(self):
        reply = self.delete()
        self.assertEqual(reply["result"]["deleted"][0]["id"], self.board_id)
        self.assertEqual(self.get_json("/api/boards")["rows"], [])
        trash = self.get_json("/api/boards?deleted=1")["rows"]
        self.assertEqual([row["id"] for row in trash], [self.board_id])
        self.assertEqual(trash[0]["deleted"]["by"], "you")

    def test_a_deleted_board_is_gone_not_missing(self):
        self.delete()
        status, _, raw = self.fetch("/api/board/" + self.board_id)
        self.assertEqual(status, 410)
        body = json.loads(raw)
        self.assertEqual(body["deleted"]["by"], "you")
        self.assertIn(boards.DELETED_MARK, body["error"])
        status, _, raw = self.fetch("/api/board/b-404")
        self.assertEqual(status, 404)

    def test_a_tap_without_the_pages_proof_is_refused(self):
        status, _ = self.post_action({"verb": "board.delete", "id": self.board_id}, page=False)
        self.assertEqual(status, 403)
        self.assertEqual(len(self.get_json("/api/boards")["rows"]), 1)

    def test_the_plan_page_shows_a_placeholder_and_the_lint_passes(self):
        self.delete()
        doc = self.get_json("/api/plan/" + self.card)
        block = [b for b in doc["doc"]["blocks"] if b.get("type") == "board"][0]
        self.assertEqual(block["deleted"]["id"], self.board_id)
        self.assertNotIn("missing", block)
        levels = [f["level"] for f in doc["lint"]["findings"] if f["rule"] == "C4" and self.board_id in f["text"]]
        self.assertEqual(levels, ["warn"])

    def test_restore_from_the_page_brings_it_back(self):
        self.delete()
        status, reply = self.post_action({"verb": "board.restore", "id": self.board_id})
        self.assertEqual(status, 200, reply)
        self.assertEqual(self.get_json("/api/board/" + self.board_id)["id"], self.board_id)

    def test_a_delete_or_a_restore_moves_the_plan_pages_tag(self):
        """The plan page asks with If-None-Match; its tag is the card's revision and the
        plan file's stamp, neither of which a delete touches, so the trash's own stamp is in
        it too, or Restore on the page would be answered 304 with the placeholder still up."""
        import urllib.request
        def tag():
            with urllib.request.urlopen(self.base + "/api/plan/" + self.card, timeout=10) as r:
                return r.headers["ETag"]
        before = tag()
        self.delete()
        deleted = tag()
        self.assertNotEqual(before, deleted)
        self.post_action({"verb": "board.restore", "id": self.board_id})
        self.assertNotEqual(deleted, tag())

