"""The plan page's door, end to end on a free port: the shell under `/plan/<id>`, the one
answer `/api/plan/<id>` carries, his marks through `/api/action` as the page sends them,
`plan.send` composing the round into Send back's reason, and the stream naming the plan
FILE when a house rewrites it.
"""

import json
import time
import urllib.request
from pathlib import Path

from keel import boards
from tests.test_serve import ServerCase

SAMPLE = (Path(__file__).parent / "fixtures" / "plan-sample.md").read_text().replace(
    "Does the outcome use the same page?", "Does the outcome use the same page? Recommend: yes.")


class PlanRouteTest(ServerCase):
    def setUp(self):
        super().setUp()
        b = self.board
        self.card = b.create("personal", "answers live on the card", autonomy="attended", actor="human")
        self.plan = self.cfg.card_dir(self.card) / "plan.md"
        self.plan.write_text(SAMPLE)
        b.stage(self.card, "assigned", "human")
        b.stage(self.card, "planning", "house", plan_ref=str(self.plan))
        # the sample embeds b-1 by id; the house pushed it (P2-7)
        boards.push(self.cfg, 'node a box "A"', card=self.card)

    def post_action(self, body, page=True):
        status, _, raw = self.fetch("/api/action", json.dumps(body).encode(), "POST", page=page)
        return status, json.loads(raw)

    def test_plan_and_outcome_are_pages_of_their_own(self):
        """P2-5: a standalone page per document, not the deck's shell: no rail, no header,
        no dock, no deck boot, and the page's cookie on it so its POSTs are his."""
        for path in ("/plan/" + self.card, "/outcome/" + self.card, "/plan/" + self.card + "/"):
            request = urllib.request.Request(self.base + path)
            with urllib.request.urlopen(request, timeout=10) as response:
                body, cookie = response.read(), response.headers.get("Set-Cookie") or ""
                self.assertIn("text/html", response.headers["Content-Type"])
            self.assertIn(b"ui.plan.js", body, path)
            self.assertIn(b"ui.planpage.js", body, path)
            for deck_only in (b'id="rail"', b'id="dock"', b'id="header"', b'src="/ui.js"', b"ui.cards.js"):
                self.assertNotIn(deck_only, body, (path, deck_only))
            self.assertIn("keel_deck_", cookie, path)


    def test_one_answer_carries_the_document_the_lint_and_the_round(self):
        doc = self.get_json("/api/plan/" + self.card)
        self.assertEqual(doc["gate"], "plan")
        self.assertEqual(doc["doc"]["counts"]["decisions"], 3)
        self.assertTrue(doc["lint"]["ok"], doc["lint"]["findings"])
        self.assertEqual(doc["round"]["changed"], 0)
        self.assertGreater(doc["cost"]["bytes"], 1000)
        self.assertNotIn("<script", json.dumps(doc))

    def test_an_embedded_id_that_does_not_resolve_is_a_finding_on_the_page(self):
        self.plan.write_text(SAMPLE.replace("\nb-1\n", "\nb-77\n"))
        doc = self.get_json("/api/plan/" + self.card)
        self.assertFalse(doc["lint"]["ok"])
        self.assertIn("`b-077` does not resolve", json.dumps(doc["lint"]["findings"]))

    def test_a_plan_longer_than_the_pane_preview_is_rendered_whole(self):
        """The pane's preview of a plan is cut at 20000 characters (`deckstate.PLAN_TEXT_MAX`); the
        plan page must read the whole file, or a long plan loses its last sections and the
        lint calls them missing (found on the c-272 stand-in, 20.6 KB)."""
        filler = "\n".join(f"- padding line {i} that makes the plan long" for i in range(600))
        self.plan.write_text(SAMPLE.replace("## Decisions", "## Detail\n\n" + filler + "\n\n## Decisions"))
        doc = self.get_json("/api/plan/" + self.card)
        self.assertGreater(doc["cost"]["bytes"], 20000)
        self.assertIn("out", [s["name"] for s in doc["doc"]["sections"]])
        self.assertTrue(doc["lint"]["ok"], doc["lint"]["findings"])

    def test_a_current_page_is_a_304_and_a_rewritten_plan_is_not(self):
        request = urllib.request.Request(self.base + "/api/plan/" + self.card)
        with urllib.request.urlopen(request, timeout=10) as response:
            tag = response.headers["ETag"]
        request.add_header("If-None-Match", tag)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=10)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 304)
        time.sleep(0.01)
        self.plan.write_text(SAMPLE.replace("Slides.", "Slides, and exports."))
        with urllib.request.urlopen(request, timeout=10) as response:
            self.assertEqual(response.status, 200)

    def test_a_mark_needs_the_page(self):
        status, answer = self.post_action({"verb": "mark", "id": self.card,
                                           "data": {"what": "comment", "text": "x"}}, page=False)
        self.assertEqual(status, 403, answer)

    def test_marks_then_send_back_carries_his_round_as_the_reason(self):
        for data in ({"what": "answer", "block": "store", "option": "file", "other": "keep it simple"},
                     {"what": "answer", "block": "triage", "row": "f2", "choice": "defer"},
                     {"what": "comment", "block": "risks.list1", "quote": "an old deck",
                      "text": "which deck is old?"}):
            status, answer = self.post_action({"verb": "mark", "id": self.card, "data": data})
            self.assertEqual(status, 200, answer)
        doc = self.get_json("/api/plan/" + self.card)
        self.assertEqual(doc["round"], {"decisions": 3, "changed": 2, "notes": 1, "replies": 0})
        status, answer = self.post_action({"verb": "plan.send", "id": self.card, "mode": "sendback"})
        self.assertEqual(status, 200, answer)
        text = answer["result"]["composed"]
        self.assertIn("THE USER CHOSE file", text)
        self.assertIn('The user wrote: "which deck is old?"', text)
        notes = [e["text"] for e in self.board.events(self.card) if e["kind"] == "note"]
        self.assertTrue(any("THE USER CHOSE file" in n for n in notes), notes)
        after = self.get_json("/api/plan/" + self.card)
        self.assertEqual(after["round"]["notes"], 0)
        self.assertEqual(after["state"]["answered"], ["store", "triage"])

    def test_an_approved_plan_carries_its_receipt_and_takes_no_second_answer(self):
        """c-537: after Approve the page draws a receipt, not the buttons, and a second
        send (a stale tab) is refused by the server too."""
        before = self.get_json("/api/plan/" + self.card)
        self.assertIsNone(before["receipt"])
        self.assertTrue(before["answerable"])
        status, answer = self.post_action({"verb": "plan.send", "id": self.card, "mode": "approve"})
        self.assertEqual(status, 200, answer)
        after = self.get_json("/api/plan/" + self.card)
        self.assertFalse(after["answerable"])
        self.assertEqual((after["receipt"]["said"], after["receipt"]["now"]),
                         ("Approved by you", "building, with no house session to resume"))
        status, answer = self.post_action({"verb": "plan.send", "id": self.card, "mode": "sendback"})
        self.assertEqual(status, 409, answer)
        detail = self.get_json("/api/card/" + self.card)
        self.assertEqual(detail["receipt"]["said"], "Approved by you")

    def test_send_is_refused_with_no_gate_and_without_the_page(self):
        status, _ = self.post_action({"verb": "plan.send", "id": self.card, "mode": "approve"}, page=False)
        self.assertEqual(status, 403)
        status, answer = self.post_action({"verb": "plan.send", "id": self.review, "mode": "approve"})
        self.assertEqual(status, 409, answer)

    def test_the_stream_names_the_plan_file_when_it_is_rewritten(self):
        request = urllib.request.Request(self.base + "/api/events?plan=" + self.card)
        with urllib.request.urlopen(request, timeout=10) as stream:
            time.sleep(0.3)
            self.plan.write_text(SAMPLE + "\n")
            deadline = time.monotonic() + 5
            seen = []
            while time.monotonic() < deadline:
                line = stream.readline().decode().strip()
                if line.startswith("data: "):
                    seen.append(line[6:])
                    if line[6:].startswith("plan " + self.card):
                        break
        self.assertTrue(any(s.startswith("plan " + self.card) for s in seen), seen)


    def test_a_reply_written_by_another_process_names_the_plan_card(self):
        """c-579: a house's `kb reply` writes the board from its own process, so the deck
        made no write of its own and used to say only `state`, which the plan page drops.
        The answer then showed only on reload. The stream names the card now."""
        ask = self.board.mark(self.card, {"what": "ask", "doc": "plan", "text": "why?"}, "human")
        request = urllib.request.Request(self.base + "/api/events?plan=" + self.card)
        with urllib.request.urlopen(request, timeout=6) as stream:
            time.sleep(0.3)
            self.board.reply(self.card, ask, "because", "house", self.card)
            deadline = time.monotonic() + 5
            seen = []
            while time.monotonic() < deadline:
                try:
                    line = stream.readline().decode().strip()
                except TimeoutError:
                    break
                if line.startswith("data: "):
                    seen.append(line[6:])
                    if line[6:].startswith("card " + self.card + " "):
                        break
        self.assertTrue(any(s.startswith("card " + self.card + " ") for s in seen), seen)

class ColdLoadTest(ServerCase):
    """What a phone pays to open a plan cold: measured at 2.1 MB and a 1.9 s first readable
    paint on a shaped 10 Mbit/s link, because the shell carried ELK (1.6 MB) as a deferred
    script, which holds DOMContentLoaded, and nothing was compressed."""


    def test_an_app_file_is_gzipped_for_a_client_that_asks(self):
        import gzip
        request = urllib.request.Request(self.base + "/ui.core.js", headers={"Accept-Encoding": "gzip"})
        with urllib.request.urlopen(request, timeout=10) as response:
            self.assertEqual(response.headers.get("Content-Encoding"), "gzip")
            body = gzip.decompress(response.read())
        self.assertEqual(body, (Path(__file__).resolve().parent.parent / "app" / "ui.core.js").read_bytes())
        with urllib.request.urlopen(self.base + "/ui.core.js", timeout=10) as response:
            self.assertIsNone(response.headers.get("Content-Encoding"))
