"""A card's review comments page (c-643, keel/commentsroute.py, app/ui.comments.js): the
route on the plan page's shell, its rounds read from the board (the told items, the house's
verdicts, his marks), a cut comment read whole from the card's `comments/`, the header's
switch, and the page drawn under node with the pane's own rows and Ship."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from keel import commentsroute, planroute, shipwatch
from keel.board import SHIPPING_OPTION, Board
from tests.helpers import SESSION, make_config

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "comments-page.js"


class CommentsRouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = make_config(Path(self.tmp.name))
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)

    def shipping(self, told):
        card_id = self.board.create("work", "Tidy", repo="api", actor="human", options={"pr": 4})
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        self.board.set_session(card_id, SESSION, "drain", bg_id=SESSION[:8])
        self.board.stage(card_id, "review", "house", plan_ref="p", output_ref="o")
        self.board.approve(card_id, "outcome", "human", publish=lambda c: {"shipping": True})
        shipped = dict(self.board.get(card_id)["options"][SHIPPING_OPTION], told=told, round=2)
        self.board.set_fields(card_id, {"options": {SHIPPING_OPTION: shipped}}, "drain")
        return card_id

    def test_the_route_is_the_plan_pages(self):
        self.assertTrue(planroute.PLAN_PAGE.match("/comments/c-12"))
        self.assertEqual(commentsroute.COMMENTS_API.match("/api/comments/c-12").group(1), "c-12")

    def test_rows_are_grouped_by_round_newest_first_with_verdicts_and_counts(self):
        card_id = self.shipping([
            {"handle": "c11", "kind": "comment", "author": "Ana", "text": "Why 40?", "batch": 1,
             "told_at": "2026-10-04T10:00:00+05:30"},
            {"handle": "c12", "kind": "comment", "author": "Bo", "text": "Use a dict", "batch": 2,
             "told_at": "2026-10-04T11:00:00+05:30"},
            {"handle": "ci", "kind": "ci", "name": "unit tests", "batch": 2, "told_at": "2026-10-04T11:00:00+05:30"}])
        self.board.verdict(card_id, {"handle": "c11", "verdict": "not-valid", "why": "the host pages at 40",
                                     "reply": "It is the page size."}, "house", card_id)
        status, body = commentsroute.payload(self.cfg, self.board, self.board.get(card_id), ["plan"])
        self.assertEqual(status, 200)
        self.assertEqual([r["round"] for r in body["rounds"]], [2, 1])
        self.assertEqual([row["handle"] for row in body["rounds"][0]["rows"]], ["c12", "ci"])
        self.assertEqual(body["rounds"][1]["rows"][0]["verdict"]["reply"], "It is the page size.")
        self.assertEqual(body["shipping"]["summary"]["to_post"], 1, "Ship's confirm reads the same")
        self.assertEqual(body["card"]["options"]["shipping"]["told"], [{"handle": "c11"}, {"handle": "c12"}, {"handle": "ci"}])
        self.assertIsNone(body["why"])

    def test_a_cut_comment_is_read_whole_from_the_cards_comments(self):
        whole = "x" * (shipwatch.TEXT_MAX + 50)
        item = shipwatch.comment_item({"id": 21, "author": "Ana", "text": whole}, shipwatch.parse("2026-10-04T10:00:00+05:30"))
        self.assertIn("[cut:", item["text"])
        card_id = self.shipping([dict(item, batch=1, told_at="2026-10-04T10:00:00+05:30")])
        card = self.board.get(card_id)
        row = commentsroute.payload(self.cfg, self.board, card, [])[1]["rounds"][0]["rows"][0]
        self.assertEqual((row["whole"], row["cut"], row["text"]), (False, "here", item["text"]),
                         "not kept on this machine: the cut text, said")
        folder = self.cfg.card_dir(card_id) / shipwatch.COMMENTS_DIR
        folder.mkdir(parents=True)
        name = shipwatch.comment_file("c21")
        (folder / name).write_text(f"# c21\n\nAna at 2026-10-04 on `a.py:4`\n\n{whole}\n")
        row = commentsroute.payload(self.cfg, self.board, card, [])[1]["rounds"][0]["rows"][0]
        self.assertEqual((row["whole"], row["text"]), (True, whole))
        # r1.F7: edited on the host since it was told, the watcher rewrote the file: the told text stays
        (folder / name).write_text(f"# c21\n\nAna at 2026-10-04\n\nsomething else entirely {whole}\n")
        row = commentsroute.payload(self.cfg, self.board, card, [])[1]["rounds"][0]["rows"][0]
        self.assertEqual((row["whole"], row["cut"], row["text"]), (False, "edited", item["text"]))

    def test_the_page_is_told_the_house_is_in_a_turn_from_the_deck_s_own_listing(self):
        """c-653: Ship is drawn only where it can go, and this page has no listing of its
        own; the route hands it the deck's kept one, never a harness call per read."""
        card = self.board.get(self.shipping([]))
        busy = {"sessionId": SESSION, "id": SESSION[:8], "kind": "background", "status": "busy", "state": "working", "pid": 1}
        idle = dict(busy, status="idle", state="done")
        house_of = lambda rows: commentsroute.payload(self.cfg, self.board, card, [], rows=rows)[1]["card"]["house"]  # noqa: E731
        self.assertEqual(house_of([busy]), {"working": True})
        self.assertIsNone(house_of([idle]))
        self.assertIsNone(house_of(None), "no listing: drawn as idle, and the backend still holds")
        self.assertIsNone(commentsroute.in_turn(dict(card, stage="done"), [busy]))

    def test_a_re_read_leaves_the_headers_pages_to_the_page(self):
        """r1.F6: `docs` None is answered as None, so the plan is not read on every event."""
        card = self.board.get(self.shipping([]))
        self.assertIsNone(commentsroute.payload(self.cfg, self.board, card, None)[1]["docs"])

    def test_a_card_never_told_anything_has_no_comments_page(self):
        card_id = self.board.create("work", "Fresh", repo="api", actor="human")
        card = self.board.get(card_id)
        self.assertFalse(commentsroute.offered(card))
        body = commentsroute.payload(self.cfg, self.board, card, ["plan"])[1]
        self.assertEqual(body["rounds"], [])
        self.assertIn("no review to answer yet", body["why"])
        self.assertNotIn("comments", planroute.more_pages(self.cfg, card))

    def test_the_header_lists_comments_at_shipping(self):
        card = self.board.get(self.shipping([]))
        self.assertTrue(commentsroute.offered(card), "at shipping, before any review")
        self.assertIn("comments", planroute.more_pages(self.cfg, card))

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_page_draws_each_round_and_its_controls_send_the_panes_marks(self):
        card_id = self.shipping([
            {"handle": "c11", "kind": "comment", "author": "Ana", "path": "a.py", "line": 4, "text": "Why 40?",
             "batch": 1, "told_at": "2026-10-04T10:00:00+05:30"},
            {"handle": "c12", "kind": "comment", "author": "Bo", "text": "Use a dict", "batch": 2,
             "told_at": "2026-10-04T11:00:00+05:30"},
            {"handle": "c13", "kind": "comment", "author": "Cy", "text": "Typo in the log line", "batch": 1,
             "told_at": "2026-10-04T10:00:00+05:30"}])
        self.board.verdict(card_id, {"handle": "c11", "verdict": "not-valid", "why": "the host pages at 40",
                                     "summary": "why the cap", "reply": "It is the page size."}, "house", card_id)
        self.board.verdict(card_id, {"handle": "c13", "verdict": "not-valid", "why": "it is spelled so upstream",
                                     "reply": "Upstream spells it so."}, "house", card_id)
        shipped = dict(self.board.get(card_id)["options"][SHIPPING_OPTION], posted={"c13": "d"})
        self.board.set_fields(card_id, {"options": {SHIPPING_OPTION: shipped}}, "drain")
        payload = commentsroute.payload(self.cfg, self.board, self.board.get(card_id), ["plan", "outcome", "comments"])[1]
        # a commit as `kb verdict` records one, with its diff (the board reads it from the clone)
        payload["rounds"][0]["rows"][0]["verdict"] = {"verdict": "valid", "why": "lookups", "summary": "use a dict",
                                                       "reply": "", "commits": [{"sha": "abc1234def",
                                                                                 "diff": "abc1234 Use a dict for the lookups\n+x = {}"}]}
        payload["card"]["options"]["shipping"]["local"] = {"ahead": 1}
        # c-655: both kinds off (the default, as the route read them) and three comments waiting
        self.assertEqual(payload["card"]["derived"]["ship_auto"]["comments"], {"on": False, "by": "space"})
        payload["card"]["derived"]["ship_handover"].update(comments=3, checks=0)
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "comments.json"
            data.write_text(json.dumps(payload))
            done = subprocess.run(["node", str(FIXTURE), str(ROOT / "app"), str(data)], capture_output=True,
                                  text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout)
        self.assertEqual(out, {"ok": True}, out)


if __name__ == "__main__":
    unittest.main()
