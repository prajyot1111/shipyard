"""A Keel card on his personal board (c-592, `keel/bosuncards.py`): who filed it, read from
its create event; Bosun's state, with next against live from git (the deploy asks only for a
repo not checked out here); and whether his board shows it. docs/atlas/96-bosun.md, "Keel
cards on his board"."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import asks, bosuncards, builder, deckstate, deploy, deployask
from keel.board import Board
from tests.helpers import make_config, make_repo, superuser_builder


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@x", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


class KeelCardCase(unittest.TestCase):
    """No checkout of the keel repo on this machine: next against live falls back to the
    deploy asks."""
    checkout = False

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        bosuncards._carried.clear()
        self.repo = make_repo(root / "keel") if self.checkout else None
        self.cfg = make_config(root, repos={"keel": root / "keel", "notes": root / "notes"})
        superuser_builder(self.cfg).builder["repos"] = ["keel", "notes"]
        self.cfg.integration = {"keel": "next"}
        self.board = Board(self.cfg.db_path, switches=self.cfg.switches, integrated=self.cfg.integrated,
                           builds=builder.repos(self.cfg))
        self.addCleanup(self.board.close)

    def card(self, actor="human", repo="keel", autonomy="autonomous", stage="assigned"):
        cid = self.board.create("personal", f"a card {actor} filed", actor=actor, repo=repo, autonomy=autonomy)
        if stage != "inbox":
            self.board.stage(cid, "assigned", "human")
        return cid

    def done(self, cid, at="2026-09-29T10:00:00+00:00"):
        self.board.stage(cid, "building", "bosun")
        with mock.patch.object(self.board, "now", return_value=at):
            self.board.stage(cid, "done", "bosun", note="landed on next as 20eace7")

    def deploy(self, cards, at="2026-09-29T11:00:00+00:00", deployed=False):
        found = {"repo": "keel", "space": "personal", "target": "next", "trunk": "main",
                 "sha": "a" * 40, "cards": cards}
        with mock.patch.object(self.board, "now", return_value=at):
            row = deployask.raise_deploy(self.board, found)
        if deployed:
            asks.answer(self.board, row["id"], "human", "A")
            deployask.record(self.board, row["id"], deployask.DEPLOYED, "main moved", sha="a" * 40)
        return row

    def keel(self, cid=None):
        with mock.patch.object(deckstate.harness, "agents_across", return_value=[]):
            doc = deckstate.build(self.cfg, self.board, rows=[])
        views = {view["id"]: view for view in doc["cards"]}
        return views if cid is None else views[cid]["derived"].get("keel_card")


class WhoFiledItTest(KeelCardCase):
    def test_the_filer_is_the_create_events_actor(self):
        his, voiced, bosuns = self.card("human"), self.card("voice"), self.card("bosun")
        self.assertEqual(self.keel(his)["filed_by"], "him")
        self.assertEqual(self.keel(voiced)["filed_by"], "him", "voice and the talker are him")
        self.assertEqual(self.keel(bosuns)["filed_by"], "bosun")

    def test_only_the_actors_that_are_him_count_as_his(self):
        talked = self.card("talker")
        self.assertEqual(self.keel(talked)["filed_by"], "him")
        for actor in ("house", "drain", "cli", "doctor"):
            cid = self.card(actor)
            self.assertEqual(self.keel(cid)["filed_by"], "bosun", actor)
            self.assertFalse(self.keel(cid)["shown"], f"{actor}'s card shows only while it needs him")

    def test_only_a_card_bosun_builds_is_labelled(self):
        errand = self.card(repo=None)
        self.assertIsNone(self.keel(errand), "a personal card with no repo is a house's")
        self.assertIsNone(self.board.get(errand)["derived"].get("keel_card"), "the board itself keeps nothing")


class GitCase(KeelCardCase):
    """The keel repo checked out here, with `next` beside `main`: git decides."""
    checkout = True

    def setUp(self):
        super().setUp()
        git(self.repo, "branch", "next")

    def land(self, cid, subject=None):
        """A card's landing merge on next, as `merging.publish` writes it."""
        git(self.repo, "checkout", "-q", "-b", f"keel/{cid}-x", "next")
        (self.repo / f"{cid}.txt").write_text(cid + "\n")
        git(self.repo, "add", "."); git(self.repo, "commit", "-q", "-m", "the work")
        git(self.repo, "checkout", "-q", "next")
        git(self.repo, "merge", "-q", "--no-ff", "-m", subject or f"Merge keel/{cid}-x: a card ({cid})",
            f"keel/{cid}-x")
        git(self.repo, "checkout", "-q", "main")

    def deploy_next(self):
        git(self.repo, "merge", "-q", "--ff-only", "next")


class OnNextFromGitTest(GitCase):
    def test_a_landing_on_next_is_next_until_main_has_it(self):
        cid = self.card()
        self.done(cid)
        self.land(cid)
        self.assertEqual(self.keel(cid)["state"], "next")
        self.assertTrue(self.keel(cid)["shown"])
        self.deploy_next()
        self.assertEqual(self.keel(cid)["state"], "live")
        self.assertFalse(self.keel(cid)["shown"])

    def test_the_deploy_asks_say_nothing_when_git_can(self):
        never, carried = self.card(), self.card()
        self.done(never)
        self.done(carried)
        self.land(carried)
        self.deploy([carried, never], at="2026-09-29T11:00:00+00:00", deployed=True)
        self.assertEqual(self.keel(never)["state"], "live", "not on next: it never landed there")
        self.assertEqual(self.keel(carried)["state"], "next", "main has not moved, whatever the ask says")

    def test_a_merge_subject_without_the_card_is_live(self):
        cid = self.card()
        self.done(cid)
        self.land(cid, subject="Merge a branch")
        self.deploy(["c-900"], at="2026-09-29T12:00:00+00:00")
        self.assertEqual(self.keel(cid)["state"], "live")

    def test_the_log_is_read_once_per_pair_of_shas(self):
        cid = self.card()
        self.done(cid)
        self.land(cid)
        with mock.patch.object(deploy, "carried", wraps=deploy.carried) as read:
            self.keel()
            self.keel()
            self.assertEqual(read.call_count, 1)
            self.deploy_next()
            self.keel()
            self.assertEqual(read.call_count, 2, "main moved: a new key")


class BosunsStateTest(KeelCardCase):
    def test_queued_building_and_his_plan_gate(self):
        queued = self.card()
        building = self.card()
        self.board.stage(building, "building", "bosun")
        planned = self.card(autonomy="attended")
        self.board.stage(planned, "planning", "bosun", plan_ref=str(self.cfg.state_dir / "plan.md"))
        self.assertEqual(self.keel(queued)["state"], "queued")
        self.assertEqual(self.keel(building)["state"], "building")
        self.assertEqual(self.keel(planned)["state"], "plan")

    def test_done_is_on_next_until_a_deploy_carries_it_live(self):
        cid = self.card()
        self.done(cid)
        self.assertEqual(self.keel(cid)["state"], "next", "no deploy ask yet")
        row = self.deploy([cid])
        self.assertEqual(self.keel(cid)["state"], "next", "in the open deploy ask")
        asks.answer(self.board, row["id"], "human", "A")
        deployask.record(self.board, row["id"], deployask.DEPLOYING, "the suite runs")
        self.assertEqual(self.keel(cid)["state"], "next", "deploying is not live")
        deployask.record(self.board, row["id"], deployask.DEPLOYED, "main moved", sha="a" * 40)
        self.assertEqual(self.keel(cid)["state"], "live")

    def test_a_card_no_ask_carries_goes_by_when_it_was_done(self):
        old, fresh = self.card(), self.card()
        self.done(old, at="2026-09-28T10:00:00+00:00")
        self.deploy(["c-900"], at="2026-09-29T09:00:00+00:00", deployed=True)
        withdrawn = self.deploy(["c-901"], at="2026-09-29T09:30:00+00:00")
        deployask.withdraw(self.board, withdrawn, "main caught up")
        self.done(fresh, at="2026-09-29T09:15:00+00:00")
        self.assertEqual(self.keel(old)["state"], "live", "done before the newest deploy ask")
        self.assertEqual(self.keel(fresh)["state"], "next", "landed after it; a withdrawn ask says nothing")

    def test_a_repo_with_no_integration_branch_is_live_when_done(self):
        cid = self.card(repo="notes")
        self.done(cid)
        self.assertEqual(self.keel(cid)["state"], "live")


class HisBoardShowsItTest(KeelCardCase):
    def test_his_card_shows_until_it_is_live(self):
        cid = self.card("human")
        self.assertTrue(self.keel(cid)["shown"])
        self.done(cid)
        self.assertTrue(self.keel(cid)["shown"], "on next, not live")
        self.deploy([cid], deployed=True)
        self.assertFalse(self.keel(cid)["shown"])

    def test_bosuns_card_shows_only_while_it_needs_him(self):
        cid = self.card("bosun")
        self.assertFalse(self.keel(cid)["shown"], "autonomous and queued: the Bosun page's")
        asks.raise_ask(self.board, "bosun", "decision", "Split it?", "it is big", ["Yes|splits", "No|keeps"], card=cid)
        self.assertTrue(self.keel(cid)["shown"], "an open ask about it needs him")

    def test_bosuns_attended_card_shows_at_his_plan_gate(self):
        cid = self.card("bosun", autonomy="attended")
        self.assertFalse(self.keel(cid)["shown"])
        self.board.stage(cid, "planning", "bosun", plan_ref=str(self.cfg.state_dir / "plan.md"))
        self.assertTrue(self.keel(cid)["shown"])

    def test_his_card_on_next_travels_in_the_live_part(self):
        cid = self.card("human")
        self.done(cid)
        view = self.keel()[cid]
        self.assertFalse(deckstate.in_done_part(view), "his board shows it without Include done")
        self.deploy([cid], deployed=True)
        self.assertTrue(deckstate.in_done_part(self.keel()[cid]))


class PlacesTest(KeelCardCase):
    def test_a_withdrawn_ask_says_nothing_and_the_newest_decides(self):
        self.assertEqual(deployask.places(self.board), ({}, {}))
        old = self.deploy(["c-1"], at="2026-09-29T08:00:00+00:00")
        deployask.withdraw(self.board, old, "next moved")
        self.deploy(["c-1", "c-2"], at="2026-09-29T09:00:00+00:00", deployed=True)
        self.deploy(["c-3"], at="2026-09-29T10:00:00+00:00")
        places, newest = deployask.places(self.board)
        self.assertEqual(places, {"c-1": "live", "c-2": "live", "c-3": "next"})
        self.assertEqual(newest, {"keel": "2026-09-29T10:00:00+00:00"})

    def test_state_and_shown_are_pure(self):
        card = {"id": "c-1", "stage": "done", "derived": {"needs_you": False}}
        self.assertEqual(bosuncards.state(card, "next"), "next")
        self.assertTrue(bosuncards.shown({"needs_you": True}, "bosun", "live"))
        self.assertFalse(bosuncards.shown({}, "him", "live"))


if __name__ == "__main__":
    unittest.main()
