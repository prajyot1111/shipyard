"""One viewer for a card's pages (c-644): the context page for a `context.md` that is not in
the plan format, the tabs that switch every page to the others in one order, and the flow's
moves on the page in the groups the flow names. End to end on a free port for the routes;
the page drawn under node on the real plan shell (`tests/fixtures/viewer.js`)."""

import json
import shutil
import subprocess
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from keel import flows, planroute
from tests.helpers import SESSION
from tests.test_serve import ServerCase

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "viewer.js"
PLAN = (Path(__file__).parent / "fixtures" / "plan-sample.md").read_text()
RECORD = "# Where it stands\n\nThe export retries now.\n\n- with backoff\n- with jitter\n"


class ViewerTest(ServerCase):
    def setUp(self):
        super().setUp()
        b = self.board
        self.card = b.create("personal", "a card with a record", autonomy="attended", actor="human")
        self.plan = self.cfg.card_dir(self.card) / "plan.md"
        self.plan.write_text(PLAN)
        b.stage(self.card, "assigned", "human")
        b.stage(self.card, "planning", "house", plan_ref=str(self.plan))
        (self.cfg.card_dir(self.card) / "context.md").write_text(RECORD)

    def test_the_context_page_is_on_the_shell(self):
        self.assertTrue(planroute.PLAN_PAGE.match("/context/c-12"))
        request = urllib.request.Request(self.base + "/context/" + self.card)
        with urllib.request.urlopen(request, timeout=10) as response:
            self.assertIn(b"ui.plan.js", response.read())

    def test_a_record_not_in_the_plan_format_is_the_context_page_with_no_gate(self):
        self.assertEqual(planroute.format_docs(self.cfg, self.board.get(self.card)), ["plan", "context"])
        status, _, raw = self.fetch(f"/api/plan/{self.card}?doc=context")
        self.assertEqual(status, 200, raw)
        body = json.loads(raw)
        self.assertEqual((body["doc_name"], body["gate"], body["answerable"], body["receipt"]),
                         ("context", None, False, None))
        self.assertIn("The export retries now.", json.dumps(body["doc"]))
        self.assertEqual(body["docs"], ["plan", "context"])

    def test_a_record_in_the_plan_format_is_the_outcome_not_the_context(self):
        (self.cfg.card_dir(self.card) / "context.md").write_text("---\nkind: outcome\n---\n# t\n\n## Where it stands\n\nx\n")
        self.assertEqual(planroute.format_docs(self.cfg, self.board.get(self.card)), ["plan", "outcome"])

    def test_the_moves_are_his_at_the_cards_stage_with_their_groups(self):
        flow_text = ('''
name = "Ours"
description = "d"
[[branch]]
id = "card"
label = "card"
kind = "card"
[[branch]]
id = "dev"
label = "dev"
kind = "environment"
[[move]]
id = "to-dev"
label = "Merge to dev review"
from = "card"
to = "dev"
by = "you"
stages = ["planning"]
group = "Try it live"
prompt = "merge it"
[[move]]
id = "tidy"
label = "Tidy"
from = "card"
to = "dev"
by = "you"
stages = ["planning"]
prompt = "tidy it"
''')
        # the space's own flow file, read as the deck reads it (r1.F10: no mock of flows.of);
        # this test's config is a checkout's, so it is given an install's space directories
        home = Path(self.cfg.state_dir).parent / "install"
        patch = mock.patch.object(type(self.cfg), "install_home", new_callable=mock.PropertyMock, return_value=home)
        patch.start()
        self.addCleanup(patch.stop)
        path = flows.space_file(self.cfg, "personal")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(flow_text)
        card = self.board.get(self.card)
        self.assertEqual(planroute.moves_of(self.cfg, card), [], "no session, no house to tell")
        card = dict(card, session_id=SESSION)
        self.assertEqual([(m["id"], m["group"]) for m in planroute.moves_of(self.cfg, card)],
                         [("to-dev", "Try it live"), ("tidy", "Flow")])
        # r1.F4: an edited flow moves the plan answer's tag, so the page never keeps old moves
        before = planroute.flow_stamp(self.cfg, card)
        import os
        os.utime(path, ns=(1, 1))
        self.assertNotEqual(planroute.flow_stamp(self.cfg, card), before)

    def test_a_formatted_record_asked_as_context_is_sent_to_the_outcome(self):
        """r1.F1: a done card's links say no format (they are read at live stages only), so
        View context opens /context; the server says it is the Outcome page."""
        (self.cfg.card_dir(self.card) / "context.md").write_text("---\nkind: outcome\n---\n# t\n\n## Where it stands\n\nx\n")
        status, _, raw = self.fetch(f"/api/plan/{self.card}?doc=context")
        self.assertEqual(json.loads(raw)["redirect"], "outcome")

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_page_follows_the_redirect_to_the_outcome(self):
        """r2.F3: the client half: the context page replaces itself with the outcome's, which
        it reads fresh."""
        (self.cfg.card_dir(self.card) / "context.md").write_text("---\nkind: outcome\n---\n# t\n\n## Where it stands\n\nx\n")
        status, _, raw = self.fetch(f"/api/plan/{self.card}?doc=outcome")
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "outcome.json"
            data.write_text(raw.decode() if isinstance(raw, bytes) else raw)
            done = subprocess.run(["node", str(ROOT / "tests" / "fixtures" / "viewer-redirect.js"), str(ROOT / "app"), str(data)],
                                  capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), {"ok": True})

    def test_the_tabs_order_is_one_in_both_places(self):
        """r2.F6: `planroute.PAGES` and the page's `TAB_ORDER` are one order."""
        source = (ROOT / "app" / "ui.plan.js").read_text()
        line = [one for one in source.splitlines() if "var TAB_ORDER = " in one][0]
        self.assertEqual(tuple(json.loads(line.split("=", 1)[1].strip().rstrip(";").replace("'", '"'))), planroute.PAGES)
        self.assertEqual(planroute.in_order(["ci", "comments", "plan"]), ["plan", "comments", "ci"])

    def test_a_plain_record_carries_no_contract_findings(self):
        """r1.F5: the context page is read, not held to the outcome's contract."""
        status, _, raw = self.fetch(f"/api/plan/{self.card}?doc=context")
        lint = json.loads(raw)["lint"]
        self.assertEqual((lint["ok"], lint["findings"]), (True, []))

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_viewer_draws_its_tabs_its_context_and_its_moves(self):
        status, _, raw = self.fetch(f"/api/plan/{self.card}?doc=context")
        body = json.loads(raw)
        body["docs"] = ["plan", "context", "comments", "ci"]
        body["moves"] = [{"id": "to-dev", "label": "Merge to dev review", "group": "Try it live", "about": ""},
                         {"id": "redo", "label": "Rebuild the preview", "group": "Try it live", "about": ""},
                         {"id": "early", "label": "Early merge to master", "group": "Early to master", "about": ""}]
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "context.json"
            data.write_text(json.dumps(body))
            done = subprocess.run(["node", str(FIXTURE), str(ROOT / "app"), str(data)], capture_output=True,
                                  text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), {"ok": True})


if __name__ == "__main__":
    unittest.main()
