"""A card's CI page (c-642, keel/ciroute.py, app/ui.ci.js): the route on the plan page's
shell, its data from the space's pack, the readiness sentence where the pack provides no
`ci`, the plan page's header listing it, and the page drawn under node. On a scratch install
whose space runs a pack that declares `ci`, with the pack's verb faked at its edge."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import adapters, ciroute, packsetup, planroute, readiness
from keel import config as config_module
from keel.board import open_board
from tests.test_installer import init
from tests.test_readiness import fake_tailscale

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "ci-page.js"
SHELL = ROOT / "tests" / "fixtures" / "ci-shell.js"
SIGHT = {"card": "c-001", "story": "st-7",
         "checks": [{"repo": "api", "pr": 4, "url": "https://host/pr/4", "head": "aaa",
                     "statuses": [{"name": "Pipeline", "state": "SUCCESSFUL", "url": "https://host/s", "updated": None}]}],
         "builds": [{"repo": "api", "branch": "trial", "number": 12, "url": "https://ci/12/", "result": "FAILURE",
                     "building": False, "started": 1790581326196, "duration": 120000,
                     "matched": {"commits": 2, "ref": "st-7"},
                     "stages": [{"id": "1", "name": "Sanity checks", "status": "SUCCESS", "ms": 5},
                                {"id": "2", "name": "Testing", "status": "FAILED", "ms": 9}],
                     "failed_stage": {"id": "2", "name": "Testing", "status": "FAILED", "ms": 9},
                     "log": ["$ py.test", "1 failed, 9 passed"]}],
         "notes": ["one thing could not be read"]}


class CiRouteTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        readiness.forget()
        self.addCleanup(readiness.forget)
        self.home = Path(tmp.name).resolve() / "install"
        self.assertEqual(init(self.home), 0)
        fake_tailscale(self.home.parent / "bin", "{}")
        self.cfg = config_module.load(self.home / "config.toml", ensure=False)

    def on_work_pack(self):
        """A pack that declares `ci`, in the install's own packs (c-722: written here, so
        no pack of anyone's own is needed); its verb is faked at its edge."""
        pack = self.home / "packs" / "builds"
        pack.mkdir(parents=True, exist_ok=True)
        (pack / "pack.toml").write_text('name = "builds"\nversion = "1"\ndescription = "a pack with CI"\n'
                                        '[capabilities]\nci = true\n'
                                        '[provides]\nconfig_example = "config.example.toml"\n')
        (pack / "config.example.toml").write_text('[spaces.personal]\npack = "builds"\n')
        (pack / "ci").write_text("#!/bin/sh\n")
        (pack / "ci").chmod(0o755)
        os.environ["KEEL_CONFIG"] = str(self.home / "config.toml")     # how the install's packs are found
        packsetup.pack_on(self.cfg, "builds", "personal")
        readiness.forget()
        self.cfg = config_module.load(self.home / "config.toml", ensure=False)

    def card(self, repo="api", stage="review"):
        plan = self.home / "plan.md"
        plan.write_text("---\nkind: plan\n---\n# t\n")
        with open_board(self.cfg) as board:
            cid = board.create("personal", "a card", actor="human", repo=repo or None)
            board.conn.execute("UPDATE cards SET stage = ?, plan_ref = ? WHERE id = ?", (stage, str(plan), cid))
            board.conn.commit()
            folder = self.cfg.card_dir(cid)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "context.md").write_text("---\nkind: outcome\n---\n# t\n")
            return board.get(cid)

    def test_the_route_is_the_plan_pages_and_its_data_has_its_own(self):
        self.assertTrue(planroute.PLAN_PAGE.match("/ci/c-12"))
        self.assertEqual(ciroute.CI_API.match("/api/ci/c-12").group(1), "c-12")

    def test_a_space_without_ci_says_why_and_the_pack_is_never_run(self):
        card = self.card()
        with mock.patch.object(adapters, "run") as run:
            status, body = ciroute.payload(self.cfg, card)
        run.assert_not_called()
        self.assertEqual((status, body["ci"]), (200, None))
        self.assertEqual(body["why"], readiness.refusal(self.cfg, self.cfg.spaces["personal"], "ci"))
        self.assertFalse(ciroute.offered(self.cfg, card))
        self.assertNotIn("ci", body["docs"])

    def test_a_space_on_a_pack_with_ci_runs_its_verb_and_links_the_cards_pages(self):
        self.on_work_pack()
        card = self.card()
        ready = {"ci": {"ready": True, "why": "", "step": None}}
        with mock.patch.object(adapters, "run", return_value=json.dumps(SIGHT)) as run, \
                mock.patch.object(readiness, "capability_rows", return_value=ready):
            status, body = ciroute.payload(self.cfg, card)
            self.assertTrue(ciroute.offered(self.cfg, card))
        self.assertEqual(run.call_args.args[1:3], ("ci", card["id"]))
        self.assertEqual((status, body["ci"], body["why"]), (200, SIGHT, None))
        self.assertEqual(body["docs"], ["plan", "outcome", "ci"])
        self.assertEqual(body["card"]["terms"]["change"], "pull request")

    def test_the_link_shows_only_where_the_panes_button_does_but_the_page_still_runs(self):
        """r1.F8: the header's CI link reads the same readiness row as the pane's CI button,
        so a token that is not set up hides both; the page, opened, still runs the verb and
        says its own words (decision `refusal-basis`)."""
        self.on_work_pack()
        card = self.card()
        unset = {"ci": {"ready": False, "why": "CI token is not set up", "step": None}}
        with mock.patch.object(readiness, "capability_rows", return_value=unset), \
                mock.patch.object(adapters, "run", return_value=json.dumps(SIGHT)) as run:
            self.assertFalse(ciroute.offered(self.cfg, card))
            status, body = ciroute.payload(self.cfg, card)
        run.assert_called_once()
        self.assertEqual(body["ci"], SIGHT)
        self.assertNotIn("ci", body["docs"])

    def test_a_card_with_no_repo_has_no_ci_and_a_failing_verb_is_said(self):
        self.on_work_pack()
        self.assertEqual(ciroute.payload(self.cfg, self.card(repo=None))[1]["ci"], None)
        with mock.patch.object(adapters, "run", side_effect=adapters.AdapterError("ci exited 1: no token")):
            body = ciroute.payload(self.cfg, self.card())[1]
        self.assertIn("the CI read failed: ci exited 1: no token", body["why"])

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_the_page_draws_the_checks_the_builds_their_stages_and_the_failed_log(self):
        payload = {"card": {"id": "c-001", "title": "a card", "space": "personal", "stage": "review", "repo": "api",
                            "terms": {"change": "pull request", "Change": "Pull request", "ticket": "story"}},
                   "docs": ["plan", "outcome", "ci"], "at": "2026-10-04T12:00:00+05:30", "ci": SIGHT, "why": None}
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "ci.json"
            data.write_text(json.dumps(payload))
            done = subprocess.run(["node", str(FIXTURE), str(ROOT / "app"), str(data)], capture_output=True,
                                  text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout)
        self.assertEqual(out["fetched"], ["/api/ci/c-001"])
        self.assertEqual(out["links"], {"card": "c-001", "docs": ["plan", "outcome", "ci"], "current": "ci"})
        self.assertEqual(out["checks"], 1)
        self.assertEqual(out["builds"], ["build-api-trial-12"])
        self.assertEqual(out["stages"], [["Sanity checks", "ci-stage ok"], ["Testing", "ci-stage bad"]])
        self.assertEqual(out["log"], "$ py.test\n1 failed, 9 passed")
        self.assertIn("carries 2 of the card's commits, names st-7", out["why"])
        self.assertIn("Pull request checks", out["headings"])
        self.assertTrue(out["refreshed"], "Refresh reads it again")

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine")
    def test_on_the_real_shell_a_board_event_never_rereads_and_a_failed_refresh_keeps_the_page(self):
        """r1.F1, F2, F4, F11, F14: the plan modules and ui.ci.js loaded whole, fetch counted."""
        sight = dict(SIGHT, checks=[dict(SIGHT["checks"][0], statuses=[
            {"name": "a", "state": "FAILED", "url": None, "updated": None},
            {"name": "b", "state": "INPROGRESS", "url": None, "updated": None},
            {"name": "c", "state": "SUCCESSFUL", "url": None, "updated": None}])])
        payload = {"card": {"id": "c-001", "title": "a card", "space": "personal", "stage": "review", "repo": "api",
                            "terms": {"change": "pull request", "Change": "Pull request", "ticket": "story"}},
                   "docs": ["plan", "outcome", "ci"], "at": "2026-10-04T12:00:00+05:30", "ci": sight, "why": None}
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "ci.json"
            data.write_text(json.dumps(payload))
            done = subprocess.run(["node", str(SHELL), str(ROOT / "app"), str(data)], capture_output=True,
                                  text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), {"ok": True})


if __name__ == "__main__":
    unittest.main()
