"""The landing queue (E5, c-298, c-306 and R5): Approve outcome carried to the machine that
holds the worktree, and landed there by a worker of its own.

Two things change where a personal card's Approve outcome runs. A card whose house is on
ANOTHER machine lands there (its branch and its worktree are there), always: it used to be
merged here, find no branch, and be reported as "main moved". And with `[keel] merge_queue`
on (shipped off), a card here lands asynchronously too, so the tap returns at once instead
of holding the deck's request for a whole test suite, and the drain pre-runs the merged
tree at review. The tap is a `land` relay, the human's; the drain that owns the card takes
it and spawns `python3 -m keel.landing`, which holds the repo's lock, runs
`merging.publish`, and finishes the approve with `kb land` or blocks with the reason.
"""

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from keel import actions, authority, cli, drain, house, housejobs, landing, merging, views
from keel.board import Board, Refused
from tests import test_housejobs
from tests.helpers import SESSION, FakeHarness, FakeMachine, make_config


def sh(cwd, *args):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    sh(path, "git", "init", "-q", "-b", "main")
    sh(path, "git", "config", "user.email", "t@example.invalid")
    sh(path, "git", "config", "user.name", "t")
    (path / "README").write_text("hello\n")
    sh(path, "git", "add", "."); sh(path, "git", "commit", "-q", "-m", "first")
    return path


class LandingCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.repo = make_repo(self.dir / "repo")
        self.cfg = make_config(self.dir, repos={"keel": self.repo})
        self.cfg.host = "box"
        self.cfg.merge_queue = True        # the queue is dormant unless switched on
        self.board = Board(self.cfg.db_path, switches={"merge_queue"})
        self.addCleanup(self.board.close)
        self.fake = FakeHarness()
        self.fake.stops = []
        for module in (drain, house, landing):
            patch = mock.patch.object(module, "harness", self.fake)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(drain, "machine", FakeMachine())
        patch.start()
        self.addCleanup(patch.stop)
        self.spawned = []
        patch = mock.patch.object(landing, "spawn",
                                  side_effect=lambda cfg, card_id, *args: self.spawned.append((card_id, args)) or 4242)
        patch.start()
        self.addCleanup(patch.stop)
        self.card = self.at_review()

    def at_review(self, title="A thing", **create) -> str:
        card = self.board.create("personal", title, repo="keel", actor="human", **create)
        self.board.stage(card, "assigned", "human")
        self.board.claim(card, "box", "drain")
        self.board.stage(card, "building", "drain")
        self.board.set_session(card, SESSION, "drain", bg_id=SESSION[:8])
        worktree = self.cfg.worktrees_dir / card
        self.cfg.worktrees_dir.mkdir(parents=True, exist_ok=True)
        sh(self.repo, "git", "worktree", "add", "-q", "-b", f"keel/{card}", str(worktree))
        (worktree / f"{card}.txt").write_text("built\n")
        sh(worktree, "git", "add", "."); sh(worktree, "git", "commit", "-q", "-m", "the work")
        self.board.stage(card, "review", "house", plan_ref="plan.md", output_ref=f"keel/{card} @ abc")
        return card

    def head(self, card=None) -> str:
        return sh(self.repo, "git", "rev-parse", f"keel/{card or self.card}")

    def landed_state(self, relay_id: int, sha: str | None = None) -> None:
        self.board.set_fields(self.card, {"options": {"landing": {
            "state": "landed", "relay": relay_id, "sha": sha or self.head()}}}, "drain")

    def land(self, relay_id: int, actor: str = "drain", **kwargs):
        """`Board.land` as `kb land` calls it: the flag on and git as the verifier."""
        return self.board.land(self.card, relay_id, actor, merge_queue=True,
                               verify=lambda card, sha: merging.target_has(self.cfg, card, sha),
                               **kwargs)

    def merge_by_hand(self):
        """The branch really merged into main, so `target_has` agrees."""
        sh(self.repo, "git", "merge", "-q", "--no-ff", f"keel/{self.card}", "-m", "by hand")

    def relay_land(self, card=None, to="box") -> dict:
        self.board.relay(card or self.card, "land", "human", to, sha=self.head(card))
        return self.board.get(card or self.card)["derived"]["relays"][-1]


class DormantTest(LandingCase):
    """Round 3 safety net: with `merge_queue` off nothing is queued, a Mac-built card
    included, no drain carries a land relay, and `Board.land` refuses outright."""

    def setUp(self):
        super().setUp()
        self.cfg.merge_queue = False

    def test_no_card_is_routed_to_a_queue(self):
        self.assertIsNone(landing.route(self.cfg, self.board.get(self.card)))
        self.board.set_fields(self.card, {"options": {"claim": {"host": "mac", "at": "x"}}}, "drain")
        self.assertIsNone(landing.route(self.cfg, self.board.get(self.card)))

    def test_no_land_relay_can_be_written_whatever_the_caller(self):
        """Round 4 finding 3: the generic `relay` verb included."""
        off = Board(self.cfg.db_path)                      # a board with no switches on
        self.addCleanup(off.close)
        with self.assertRaises(Refused):
            off.relay(self.card, "land", "human", "box", sha=self.head())

    def test_a_manual_worker_does_nothing(self):
        """Round 4 finding 2: `python3 -m keel.landing` with the queue off."""
        relay = self.relay_land()
        self.board.carry(self.card, relay["id"], "drain")
        before = len(self.board.events(self.card))
        self.assertEqual(landing.run(self.cfg, self.board, self.card, relay=relay["id"]), 1)
        self.assertEqual(landing.land(self.cfg, self.board, self.board.get(self.card), relay["id"]), 1)
        self.assertEqual(len(self.board.events(self.card)), before)
        self.assertEqual(self.board.get(self.card)["stage"], "review")

    def test_board_land_refuses_and_no_drain_carries_or_announces_land(self):
        relay = self.relay_land()
        drain.once(self.cfg, board=self.board)
        self.assertEqual(self.spawned, [])
        self.assertNotIn("land", drain.carried_kinds(self.cfg))
        with self.assertRaises(Refused):
            self.board.land(self.card, relay["id"], "drain", merge_queue=False)


class RouteTest(LandingCase):

    def test_with_the_flag_on_a_card_here_is_queued_for_this_machine(self):
        self.cfg.merge_queue = True
        self.assertEqual(landing.route(self.cfg, self.board.get(self.card)), "box")

    def test_a_work_card_or_an_errand_is_never_queued(self):
        self.cfg.merge_queue = True
        errand = self.board.create("personal", "an errand", actor="human")
        self.assertIsNone(landing.route(self.cfg, self.board.get(errand)))
        work = self.board.create("work", "work", repo="api", actor="human")
        self.assertIsNone(landing.route(self.cfg, self.board.get(work)))


class BoardTest(LandingCase):
    def test_a_land_relay_is_the_human_s_and_only_at_review(self):
        with self.assertRaises(Refused):
            self.board.relay(self.card, "land", "drain", "box")
        other = self.board.create("personal", "inbox", repo="keel", actor="human")
        with self.assertRaises(Refused):
            self.board.relay(other, "land", "human", "box")

    def test_one_landing_at_a_time_per_card(self):
        self.relay_land()
        with self.assertRaises(Refused):
            self.board.relay(self.card, "land", "human", "box")

    def test_the_drain_finishes_the_approve_only_on_a_land_relay_it_took(self):
        relay = self.relay_land()
        with self.assertRaises(Refused):
            self.land(relay["id"], published="abc merged")
        self.board.carry(self.card, relay["id"], "drain")
        with self.assertRaises(Refused):
            self.land(relay["id"], "house", published="abc merged")
        self.landed_state(relay["id"])
        self.merge_by_hand()
        card = self.land(relay["id"], published="abc merged into main")
        self.assertEqual(card["stage"], "done")
        event = [e for e in self.board.events(self.card) if e["kind"] == "approve"][-1]
        self.assertEqual((event["data"]["gate"], event["data"]["relay"], event["data"]["published"]),
                         ("outcome", relay["id"], "abc merged into main"))


class OneRelayOneOutcomeTest(LandingCase):
    """Review finding 4: `kb land` passes the outcome gate only for the relay whose worker
    recorded a landed sha, never on a blocked card or a refused landing, never twice."""

    def taken(self) -> dict:
        relay = self.relay_land()
        self.board.carry(self.card, relay["id"], "drain")
        return relay

    def test_a_blocked_card_does_not_land(self):
        relay = self.taken()
        self.landed_state(relay["id"])
        self.board.block(self.card, "his block", "human")
        with self.assertRaises(Refused):
            self.land(relay["id"])

    def test_a_refused_landing_or_another_relay_s_sha_does_not_land(self):
        relay = self.taken()
        self.board.set_fields(self.card, {"options": {"landing": {
            "state": "refused", "relay": relay["id"], "why": "red"}}}, "drain")
        with self.assertRaises(Refused):
            self.land(relay["id"])
        self.landed_state(relay["id"] + 99)
        with self.assertRaises(Refused):
            self.land(relay["id"])
        self.assertEqual(self.board.get(self.card)["stage"], "review")

    def test_a_card_in_an_adapter_space_neither_lands_nor_is_queued(self):
        from argparse import Namespace
        from keel import cli
        work = self.board.create("work", "work", repo="api", actor="human")
        with self.assertRaises(Refused):
            cli.cmd_relay(self.board, Namespace(id=work, what="land", to="box", prompt=None,
                                                sha="abc", config=self.cfg), "human")
        with self.assertRaises(Refused):
            cli.cmd_land(self.board, Namespace(id=work, relay=1, published=None, config=self.cfg), "drain")


class FactsTest(LandingCase):
    """Round 3 finding 4: `Board.land` checks git, not only what the worker wrote."""

    def taken(self) -> dict:
        relay = self.relay_land()
        self.board.carry(self.card, relay["id"], "drain")
        return relay

    def test_a_landed_record_with_nothing_merged_does_not_land(self):
        relay = self.taken()
        self.landed_state(relay["id"])
        with self.assertRaises(Refused) as caught:
            self.land(relay["id"])
        self.assertIn("is not in main", str(caught.exception))
        self.assertEqual(self.board.get(self.card)["stage"], "review")

    def test_a_record_naming_another_sha_does_not_land(self):
        relay = self.taken()
        self.merge_by_hand()
        self.landed_state(relay["id"], sha=sh(self.repo, "git", "rev-parse", "main~1"))
        with self.assertRaises(Refused):
            self.land(relay["id"])

    def test_no_verifier_no_landing(self):
        relay = self.taken()
        self.merge_by_hand()
        self.landed_state(relay["id"])
        with self.assertRaises(Refused):
            self.board.land(self.card, relay["id"], "drain", merge_queue=True)

    def test_only_the_landing_worker_writes_options_landing(self):
        for actor in ("human", "house", "hook", "voice"):
            with self.assertRaises(Refused):
                self.board.set_fields(self.card, {"options": {"landing": {"state": "landed"}}}, actor)

    def test_leaving_review_cancels_a_landing_that_is_testing(self):
        relay = self.taken()
        self.board.set_fields(self.card, {"options": {"landing": {"state": "testing", "relay": relay["id"]}}}, "drain")
        self.board.stage(self.card, "building", "human", note="sent back")
        self.assertEqual(self.board.get(self.card)["options"]["landing"]["state"], "cancelled")


class TapTest(LandingCase):
    """The deck's Approve outcome, when the card is queued: one relay, and back at once."""

    def setUp(self):
        super().setUp()
        self.kb = []
        patch = mock.patch.object(actions, "run_kb", side_effect=self.fake_kb)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(actions, "run_keel", return_value="")
        self.keel = patch.start()
        self.addCleanup(patch.stop)

    def fake_kb(self, cfg, argv, **kwargs):
        self.kb.append(argv)
        if argv[0] == "relay":
            sha = argv[argv.index("--sha") + 1] if "--sha" in argv else None
            self.board.relay(argv[1], argv[2], "human", argv[argv.index("--to") + 1], sha=sha)
        return self.board.get(argv[1]) if len(argv) > 1 and argv[1].startswith("c-") else None

    def test_the_tap_returns_before_anything_is_merged_or_tested(self):
        self.cfg.merge_queue = True
        with mock.patch.object(merging, "publish") as publish:
            answer = actions.act(self.cfg, self.board, {"verb": "approve", "id": self.card,
                                                        "gate": "outcome", "said": "ship it"})
        publish.assert_not_called()
        self.assertEqual((answer["relayed"], answer["to"]), ("land", "box"))
        self.assertNotIn("approve", [argv[0] for argv in self.kb])
        self.assertIn(["note", self.card, "ship it"], self.kb)
        self.assertEqual(self.board.get(self.card)["stage"], "review")

    def test_a_repo_with_no_suite_is_said_to_land_untested(self):
        """c-621: the note promised a green suite to a repo with no [tests] entry."""
        self.cfg.repo_tests.clear()
        answer = actions.act(self.cfg, self.board, {"verb": "approve", "id": self.card, "gate": "outcome"})
        self.assertIn("lands untested", answer["note"])
        self.assertNotIn("green", answer["note"])

class CarryTest(LandingCase):
    """The drain that owns the card carries the relay by spawning the worker."""

    def test_a_land_relay_is_taken_and_handed_to_a_worker(self):
        relay = self.relay_land()
        drain.once(self.cfg, board=self.board)
        self.assertEqual(self.spawned, [(self.card, ("--relay", str(relay["id"])))])
        card = self.board.get(self.card)
        self.assertEqual(card["derived"]["relays"], [])
        self.assertEqual((card["options"]["landing"]["state"], card["options"]["landing"]["host"]),
                         ("testing", "box"))

    def test_one_landing_per_repo_at_a_time_the_second_waits(self):
        self.relay_land()
        second = self.at_review("Another")
        self.relay_land(second)
        drain.once(self.cfg, board=self.board)
        self.assertEqual([card for card, _ in self.spawned], [self.card])
        self.assertEqual(len(self.board.get(second)["derived"]["relays"]), 1, "left pending")

    def test_a_land_relay_for_a_card_no_longer_at_review_is_superseded(self):
        relay = self.relay_land()
        self.board.stage(self.card, "building", "human")
        drain.once(self.cfg, board=self.board)
        self.assertEqual(self.spawned, [])
        carried = [e for e in self.board.events(self.card) if e["kind"] == "carried"][-1]
        self.assertEqual((carried["data"]["relay"], carried["data"]["outcome"]), (relay["id"], "superseded"))

    def test_a_worker_that_died_is_answered_on_the_card(self):
        self.board.set_fields(self.card, {"options": {"landing": {
            "state": "testing", "host": "box", "pid": 999999, "at": "2026-09-23T00:00:00+00:00"}}}, "drain")
        with mock.patch.object(landing, "alive", return_value=False):
            landing.upkeep(self.cfg, self.board)
        card = self.board.get(self.card)
        self.assertEqual(card["options"]["landing"]["state"], "refused")
        self.assertIn("outcome not merged", card["blocked_reason"])


class WorkerTest(LandingCase):
    """`python3 -m keel.landing`, run in-process: the merge, the tests, the card's answer."""

    def taken(self) -> dict:
        relay = self.relay_land()
        self.board.carry(self.card, relay["id"], "drain")
        return relay

    def test_green_lands_the_card_and_ends_its_house(self):
        relay = self.taken()
        self.cfg.repo_tests["keel"] = f"test -f {self.card}.txt"
        self.fake.rows = [{"id": SESSION[:8], "sessionId": SESSION, "name": self.card,
                           "kind": "background", "status": "idle"}]
        self.assertEqual(landing.run(self.cfg, self.board, self.card, relay=relay["id"]), 0)
        card = self.board.get(self.card)
        self.assertEqual(card["stage"], "done")
        self.assertEqual(card["options"]["landing"]["state"], "landed")
        self.assertTrue((self.repo / f"{self.card}.txt").is_file())
        self.assertEqual(self.fake.stops, [SESSION[:8]], "the finished house is retired")

    def test_red_is_refused_and_blocked_with_main_untouched(self):
        relay = self.taken()
        head = sh(self.repo, "git", "rev-parse", "HEAD")
        self.cfg.repo_tests["keel"] = "echo nope; exit 1"
        self.assertEqual(landing.run(self.cfg, self.board, self.card, relay=relay["id"]), 1)
        card = self.board.get(self.card)
        self.assertEqual((card["stage"], card["options"]["landing"]["state"]), ("review", "refused"))
        self.assertIn("outcome not merged: tests failed", card["blocked_reason"])
        self.assertEqual(sh(self.repo, "git", "rev-parse", "HEAD"), head)

    def test_a_conflict_sends_the_house_to_merge_main_as_the_tap_does(self):
        relay = self.taken()
        (self.repo / f"{self.card}.txt").write_text("theirs\n")
        sh(self.repo, "git", "add", "."); sh(self.repo, "git", "commit", "-q", "-m", "conflicting")
        landing.run(self.cfg, self.board, self.card, relay=relay["id"])
        card = self.board.get(self.card)
        self.assertEqual(card["stage"], "building")
        self.assertIs(card["options"]["merging"], True)
        self.assertIn("merge", self.fake.resumes[-1]["prompt"].lower())


class WithdrawnApproveTest(LandingCase):
    """Review finding 1: the worker lands exactly what he approved, or nothing."""

    def taken(self) -> dict:
        relay = self.relay_land()
        self.board.carry(self.card, relay["id"], "drain")
        return relay

    def commit_on_branch(self, message="after the approve"):
        worktree = self.cfg.worktrees_dir / self.card
        (worktree / "later.txt").write_text(message + "\n")
        sh(worktree, "git", "add", "."); sh(worktree, "git", "commit", "-q", "-m", message)

    def test_send_back_then_a_commit_lands_nothing_and_leaves_the_house_alone(self):
        relay = self.taken()
        main = sh(self.repo, "git", "rev-parse", "main")
        self.board.stage(self.card, "building", "human", note="sent back")
        self.commit_on_branch()
        self.fake.rows = [{"id": SESSION[:8], "sessionId": SESSION, "name": self.card,
                           "kind": "background", "status": "busy"}]
        self.assertEqual(landing.run(self.cfg, self.board, self.card, relay=relay["id"]), 1)
        card = self.board.get(self.card)
        self.assertEqual((card["stage"], card["blocked_reason"]), ("building", None))
        self.assertEqual(card["options"]["landing"]["state"], "refused")
        self.assertEqual(sh(self.repo, "git", "rev-parse", "main"), main)
        self.assertTrue((self.cfg.worktrees_dir / self.card).is_dir())
        self.assertEqual(self.fake.stops, [])

    def test_commits_after_the_approve_are_refused_not_merged(self):
        relay = self.taken()
        main = sh(self.repo, "git", "rev-parse", "main")
        self.commit_on_branch()
        self.assertEqual(landing.run(self.cfg, self.board, self.card, relay=relay["id"]), 1)
        card = self.board.get(self.card)
        self.assertIn("moved since you approved", card["blocked_reason"])
        self.assertEqual(sh(self.repo, "git", "rev-parse", "main"), main)
        with self.assertRaises(Refused):
            self.land(relay["id"])

    def row(self, status="idle"):
        return {"id": SESSION[:8], "sessionId": SESSION, "name": self.card,
                "kind": "background", "status": status}

    def during_the_suite(self, act):
        """Run `act` after the merged tree is built and tested, before the fast-forward."""
        real = merging.build_and_test

        def build(*args, **kwargs):
            merged = real(*args, **kwargs)
            act()
            return merged
        return mock.patch.object(merging, "build_and_test", side_effect=build)


    def test_a_working_house_lands_nothing(self):
        relay = self.taken()
        main = sh(self.repo, "git", "rev-parse", "main")
        self.fake.rows = [self.row("busy")]
        self.assertEqual(landing.run(self.cfg, self.board, self.card, relay=relay["id"]), 1)
        self.assertEqual((sh(self.repo, "git", "rev-parse", "main"), self.fake.stops), (main, []))

    def test_a_house_that_comes_back_during_the_suite_stops_the_fast_forward(self):
        relay = self.taken()
        main = sh(self.repo, "git", "rev-parse", "main")
        with self.during_the_suite(lambda: self.fake.rows.append(self.row("busy"))):
            self.assertEqual(landing.run(self.cfg, self.board, self.card, relay=relay["id"]), 1)
        self.assertEqual(sh(self.repo, "git", "rev-parse", "main"), main)
        self.assertTrue((self.cfg.worktrees_dir / self.card).is_dir())

    def test_a_send_back_during_the_suite_cancels_the_landing(self):
        relay = self.taken()
        main = sh(self.repo, "git", "rev-parse", "main")
        with self.during_the_suite(lambda: self.board.stage(self.card, "building", "human")):
            self.assertEqual(landing.run(self.cfg, self.board, self.card, relay=relay["id"]), 1)
        self.assertEqual(sh(self.repo, "git", "rev-parse", "main"), main)
        self.assertEqual(self.board.get(self.card)["options"]["landing"]["state"], "refused")

    def test_a_send_back_and_return_to_review_in_between_still_withdraws_it(self):
        relay = self.taken()
        self.board.stage(self.card, "building", "human")
        self.board.stage(self.card, "review", "house", output_ref=f"keel/{self.card} @ x")
        self.assertEqual(landing.run(self.cfg, self.board, self.card, relay=relay["id"]), 1)
        self.assertNotEqual(self.board.get(self.card)["stage"], "done")

    def test_the_pinned_sha_is_merged_even_when_the_branch_moves_during_the_suite(self):
        relay = self.taken()
        pinned = self.head()
        with self.during_the_suite(self.commit_on_branch):
            self.assertEqual(landing.run(self.cfg, self.board, self.card, relay=relay["id"]), 0)
        later = self.head()
        self.assertNotEqual(later, pinned)
        self.assertEqual(subprocess.run(["git", "-C", str(self.repo), "merge-base", "--is-ancestor",
                                         pinned, "main"]).returncode, 0)
        self.assertNotEqual(subprocess.run(["git", "-C", str(self.repo), "merge-base", "--is-ancestor",
                                            later, "main"]).returncode, 0, "unapproved commit landed")
        notes = " ".join(e.get("text") or "" for e in self.board.events(self.card))
        self.assertIn("merged, but", notes, "a branch -d that fails is a note, not a refusal")

    def test_the_pinned_sha_is_merged_on_the_retry_too(self):
        relay = self.taken()
        pinned = self.head()
        calls = []

        def move_both():
            if not calls:
                calls.append(1)
                self.commit_on_branch("unapproved")
                sh(self.repo, "git", "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-q",
                   "--allow-empty", "-m", "main moved")
        with self.during_the_suite(move_both):
            self.assertEqual(landing.run(self.cfg, self.board, self.card, relay=relay["id"]), 0)
        self.assertNotEqual(subprocess.run(["git", "-C", str(self.repo), "merge-base", "--is-ancestor",
                                            self.head(), "main"]).returncode, 0)
        self.assertEqual(subprocess.run(["git", "-C", str(self.repo), "merge-base", "--is-ancestor",
                                         pinned, "main"]).returncode, 0)

    def test_a_house_that_comes_back_after_the_merge_keeps_its_worktree(self):
        relay = self.taken()
        real = merging.settle

        def settle(*args, **kwargs):
            done = real(*args, **kwargs)
            self.fake.rows.append(self.row("idle"))
            return done
        with mock.patch.object(merging, "settle", side_effect=settle):
            landing.run(self.cfg, self.board, self.card, relay=relay["id"])
        self.assertTrue((self.cfg.worktrees_dir / self.card).is_dir())
        self.assertIn(f"keel/{self.card}", sh(self.repo, "git", "branch", "--list"))

    def test_a_merge_that_landed_is_never_reported_as_not_merged(self):
        """NEW-a: the board refusing after the merge says it merged, and blocks for him."""
        relay = self.taken()
        with mock.patch.object(self.board, "land", side_effect=Refused("the board said no")):
            self.assertEqual(landing.run(self.cfg, self.board, self.card, relay=relay["id"]), 1)
        reason = self.board.get(self.card)["blocked_reason"]
        self.assertTrue(reason.startswith("merged into main at "), reason)
        self.assertIn("the board said no", reason)
        self.assertNotIn("not merged", reason)

    def test_anything_unexpected_is_an_answer_on_the_card_not_a_traceback(self):
        relay = self.taken()
        with mock.patch.object(merging, "land_card", side_effect=RuntimeError("disk on fire")):
            self.assertEqual(landing.run(self.cfg, self.board, self.card, relay=relay["id"]), 1)
        self.assertIn("disk on fire", self.board.get(self.card)["blocked_reason"])


class QueuedWorkerTest(LandingCase):
    """Review finding 5: a worker waiting on the repo's lock is alive and says so, and a
    card whose own worker or pre-run is running starts no second one."""

    def test_a_waiting_worker_has_written_its_pid_and_is_not_declared_dead(self):
        import threading
        relay = self.relay_land()
        self.board.carry(self.card, relay["id"], "drain")
        def worker():
            board = Board(self.cfg.db_path)        # its own connection, in its own thread
            try:
                landing.run(self.cfg, board, self.card, relay=relay["id"])
            finally:
                board.close()

        with landing.repo_lock(self.cfg, self.board.get(self.card)):
            thread = threading.Thread(target=worker)
            thread.start()
            for _ in range(100):
                if (self.board.get(self.card)["options"].get("landing") or {}).get("pid"):
                    break
                time.sleep(0.02)
            state = self.board.get(self.card)["options"]["landing"]
            self.assertEqual((state["state"], state["pid"]), ("testing", os.getpid()))
            landing.upkeep(self.cfg, self.board)
            self.assertEqual(self.board.get(self.card)["options"]["landing"]["state"], "testing")
        thread.join(timeout=60)
        self.assertEqual(self.board.get(self.card)["stage"], "done")

    def test_a_second_approve_while_the_worker_runs_is_refused(self):
        relay = self.relay_land()
        self.board.carry(self.card, relay["id"], "drain")
        self.board.set_fields(self.card, {"options": {"landing": {
            "state": "testing", "host": "box", "relay": relay["id"], "pid": os.getpid()}}}, "drain")
        with self.assertRaises(Refused):
            self.relay_land()

    def test_the_card_s_own_pre_run_holds_its_landing_back(self):
        self.board.set_fields(self.card, {"options": {"pretest": {
            "state": "running", "host": "box", "pid": os.getpid()}}}, "drain")
        self.relay_land()
        drain.once(self.cfg, board=self.board)
        self.assertEqual(self.spawned, [])
        self.assertEqual(len(self.board.get(self.card)["derived"]["relays"]), 1)


class PretestTest(LandingCase):
    """R5: with the flag on, the drain pre-runs the merged tree when a card reaches review
    and records the answer on the card, so the tap is not the first time it is known."""


    def test_a_card_at_review_is_pre_run_once_per_head(self):
        self.cfg.merge_queue = True
        landing.upkeep(self.cfg, self.board)
        self.assertEqual(self.spawned, [(self.card, ("--pretest",))])
        self.cfg.repo_tests["keel"] = "exit 0"
        self.assertEqual(landing.run(self.cfg, self.board, self.card, pretest=True), 0)
        record = self.board.get(self.card)["options"]["pretest"]
        self.assertEqual(record["result"], "green")
        self.spawned.clear()
        landing.upkeep(self.cfg, self.board)
        self.assertEqual(self.spawned, [], "the same heads are not pre-run twice")

    def test_a_restage_to_review_drops_the_last_outcome_s_pre_run_and_runs_it_again(self):
        """c-621: Approve showed the previous outcome's result after a re-stage."""
        landing.mark(self.board, self.card, {"state": "done", "result": "red", "said": "old"},
                     landing.PRETEST)
        self.board.stage(self.card, "building", "human")
        self.board.stage(self.card, "review", "house", output_ref=f"keel/{self.card} @ abc")
        self.assertNotIn("pretest", self.board.get(self.card)["options"])
        landing.upkeep(self.cfg, self.board)
        self.assertEqual(self.spawned, [(self.card, ("--pretest",))])



class LandingWordTest(LandingCase):
    """c-535 (r-12): a card whose approve is on record and landing is not waiting on him.
    c-533 sat 14 minutes under needs you while its merged tree was tested."""

    def test_a_pending_land_relay_reads_landing_and_leaves_needs_you(self):
        self.assertTrue(self.board.get(self.card)["derived"]["needs_you"], "the gate is his")
        self.relay_land()
        derived = self.board.get(self.card)["derived"]
        self.assertTrue(derived["landing"])
        self.assertFalse(derived["needs_you"])
        self.assertNotIn(self.card, [card["id"] for card in self.board.needs_you()])

    def test_a_worker_testing_reads_landing_and_a_refusal_is_his_again(self):
        relay = self.relay_land()
        self.board.carry(self.card, relay["id"], "drain")
        landing.mark(self.board, self.card, {"state": landing.TESTING, "host": "box", "relay": relay["id"]})
        card = self.board.get(self.card)
        self.assertEqual((card["derived"]["landing"], card["derived"]["needs_you"]), (True, False))
        self.assertIn("[landing]", cli.card_line(card))
        landing.refuse_clean(self.board, card, relay["id"], "tests failed")
        card = self.board.get(self.card)
        self.assertEqual((card["derived"]["landing"], card["derived"]["needs_you"]), (False, True))

    def test_an_open_ask_still_needs_him_while_it_lands(self):
        self.relay_land()
        with mock.patch.object(views, "open_ask", return_value={"id": "a-1"}):
            self.assertTrue(self.board.get(self.card)["derived"]["needs_you"])


class LeftoverJobTest(LandingCase):
    """c-535: `finish_house` refused on `status: busy`, which the harness also lists for an
    idle house with a background job still running (c-532's review session sat 46 minutes
    on a polling loop and blocked its landing). `state` says whether it is in a turn."""

    def taken(self) -> dict:
        relay = self.relay_land()
        self.board.carry(self.card, relay["id"], "drain")
        return relay

    def row(self, status, state=None):
        row = {"id": SESSION[:8], "sessionId": SESSION, "name": self.card,
               "kind": "background", "status": status, "pid": 4321}
        return dict(row, state=state) if state else row

    def ghost(self):
        """c-561's old session as 2.1.284 listed it on 2026-09-29: `state: working` and
        nothing else, no `status` and no `pid` (r-26)."""
        return {"id": SESSION[:8], "sessionId": SESSION, "name": self.card,
                "kind": "background", "startedAt": 0, "cwd": "/w", "state": "working"}

    def test_an_idle_house_with_a_leftover_job_is_stopped_and_it_lands(self):
        relay = self.taken()
        self.fake.rows = [self.row("busy", "done")]
        self.assertEqual(landing.run(self.cfg, self.board, self.card, relay=relay["id"]), 0)
        self.assertEqual(self.fake.stops, [SESSION[:8]])
        self.assertEqual(self.board.get(self.card)["stage"], "done")

    def test_the_leftover_job_itself_is_ended_and_said(self):
        """A real job, as c-532's polling loop was: a shell leading its own session, recorded
        in the harness's job record, ended by pid when the landing stops its house."""
        relay = self.taken()
        # The task's real start, read before the spawn and its wait: off Linux there are no
        # /proc start ticks, and the pid is proven by `ps -o lstart` sitting within seconds
        # of it (c-635).
        started = int(time.time() * 1000)
        pid = test_housejobs.spawn_job()
        self.addCleanup(lambda: [os.kill(m, 9) for m in housejobs.in_session(pid) or []])
        jobs = self.cfg.spaces["personal"].config_dir / "jobs" / SESSION[:8]
        jobs.mkdir(parents=True)
        (jobs / "state.json").write_text(json.dumps({
            "state": "idle", "inFlight": {"tasks": 1},
            "fan": [{"id": "t1", "kind": "shell", "label": "while pgrep -f x", "startedAt": started}]}))
        ticks = housejobs.start_ticks(pid)
        stop = self.fake.stop

        def claude_stop(bg_id, config_dir=None):
            stop(bg_id, config_dir)
            (jobs / "adopt.json").write_text(json.dumps({
                "writtenAtMs": int(time.time() * 1000),
                "shells": [{"taskId": "t1", "pid": pid, "startTimeTicks": ticks}]}))
        self.fake.stop = claude_stop
        self.fake.rows = [self.row("busy", "done")]
        self.assertEqual(landing.run(self.cfg, self.board, self.card, relay=relay["id"]), 0)
        self.assertFalse(housejobs.alive(pid), "the leftover job was ended")
        notes = " ".join(e["text"] or "" for e in self.board.events(self.card) if e["kind"] == "note")
        self.assertIn(f"ended its background job t1 (pid {pid})", notes)


    def test_a_row_listed_working_with_no_process_is_stopped_and_it_lands(self):
        """r-26: the ghost is not working (no process), so it is stopped and landed past,
        with a note naming it, even when the harness keeps listing it after the stop."""
        relay = self.taken()
        ghost = self.ghost()
        self.fake.rows = [ghost]
        self.fake.stop = lambda bg_id, config_dir=None: self.fake.stops.append(bg_id)
        self.assertEqual(landing.run(self.cfg, self.board, self.card, relay=relay["id"]), 0)
        self.assertEqual(self.fake.stops, [SESSION[:8]], "the stop is still asked")
        self.assertEqual(self.board.get(self.card)["stage"], "done")
        notes = " ".join(e["text"] or "" for e in self.board.events(self.card) if e["kind"] == "note")
        self.assertIn("with no process behind it; landed past it", notes)

    def test_a_restage_to_review_clears_the_landing_refusal(self):
        """c-575: blocked by a refused landing, it staged review again and stayed blocked."""
        relay = self.taken()
        self.fake.rows = [self.row("busy", "working")]
        landing.run(self.cfg, self.board, self.card, relay=relay["id"])
        self.assertTrue(self.board.get(self.card)["blocked_reason"])
        self.board.stage(self.card, "review", "house", output_ref=f"keel/{self.card} @ def")
        card = self.board.get(self.card)
        self.assertIsNone(card["blocked_reason"])
        self.assertEqual(self.board.events(self.card)[-1]["kind"], "unblock")

    def test_a_restage_leaves_any_other_block(self):
        self.board.block(self.card, landing.NOT_MERGED + "his own words", "house")
        self.board.stage(self.card, "review", "house", output_ref=f"keel/{self.card} @ def")
        self.assertEqual(self.board.get(self.card)["blocked_reason"], landing.NOT_MERGED + "his own words")


class BosunCardTest(LandingCase):
    """c-647: a card Bosun builds lands the branch its outcome names and no other, and a
    conflict is Bosun's to merge. The fixture's card carries a house's session and a house's
    worktree on `keel/<card>`, left by a start made before the card was Bosun's."""

    def setUp(self):
        super().setUp()
        self.board.close()
        self.board = Board(self.cfg.db_path, switches={"merge_queue", authority.BUILDER}, builds=["keel"])
        self.addCleanup(self.board.close)
        self.theirs = self.at_review("a house's", options={"worker": "house"})
        self.assertEqual([self.board.get(c)["derived"]["bosun"] for c in (self.card, self.theirs)], [True, False])

    def named(self, output_ref: str, card=None) -> str:
        self.board.set_fields(card or self.card, {"output_ref": output_ref}, "human")
        return merging.branch_placed(self.cfg, self.board.get(card or self.card))[3]

    def land(self, card: str) -> int:
        relay = self.relay_land(card)
        self.board.carry(card, relay["id"], "drain")
        return landing.run(self.cfg, self.board, card, relay=relay["id"])

    def test_a_conflict_resumes_no_house_and_the_card_says_bosun_merges_it(self):
        for card in (self.card, self.theirs):
            (self.repo / f"{card}.txt").write_text("theirs\n")
        sh(self.repo, "git", "add", "."); sh(self.repo, "git", "commit", "-q", "-m", "conflicting")
        self.land(self.card)
        card = self.board.get(self.card)
        self.assertEqual((card["stage"], card["blocked_reason"]), ("building", None))
        self.assertFalse(card["options"].get("merging"), "no word on the deck that a house is merging")
        self.assertEqual((self.fake.resumes, self.fake.starts, self.fake.stops), ([], [], []))
        moved = [e["text"] for e in self.board.events(self.card) if e["kind"] == "stage"][-1]
        self.assertIn(f"waiting for Bosun to merge main into keel/{self.card}", moved)
        self.land(self.theirs)                         # a house's card, as before
        house_card = self.board.get(self.theirs)
        self.assertEqual((house_card["stage"], house_card["options"]["merging"]), ("building", True))
        self.assertEqual(len(self.fake.resumes), 1)

    def test_only_a_branch_the_outcome_names_lands_and_a_house_s_card_keeps_its_worktree_s(self):
        sha = self.head()
        sh(self.repo, "git", "branch", "bosun/mine", sha)
        self.assertEqual(self.named("bosun/mine"), "bosun/mine")
        self.assertEqual(self.named(f"bosun/mine @ {sha}"), "bosun/mine")
        self.assertEqual(self.named(f"branch bosun/mine @ {sha}"), "bosun/mine")
        self.cfg.integration = {"keel": "next"}
        sh(self.repo, "git", "branch", "next")
        for unusable in (sha, "docs/plan.md", "the work is on my branch", f"main @ {sha}", "next",
                         str(self.dir / "plan.md"), "bosun/gone", "bosun/mine~0", "bosun/mine^0",
                         "bosun/mine@{0}", "main~0", "Main", "Next", f"MAIN @ {sha}"):
            with self.subTest(unusable):
                with self.assertRaises(merging.MergeRefused) as refused:
                    self.named(unusable)
                self.assertIn(f"`kb stage {self.card} review --output <branch>`", str(refused.exception))
        self.assertEqual(self.named("branch other @ 1", self.theirs), f"keel/{self.theirs}")
        self.board.set_fields(self.card, {"output_ref": "docs/plan.md", "options": {"kind": "research"}}, "human")
        self.assertTrue(merging.nothing_to_land(self.cfg, self.board.get(self.card)),
                        "a research card still closes with nothing to land")
        tree = self.cfg.worktrees_dir / self.card
        self.assertTrue(tree.is_dir(), "the house's leftover worktree")
        with mock.patch.object(merging.trust, "forget") as forgot:
            closed = merging.publish(self.cfg, self.board.get(self.card))
        self.assertEqual(closed["published"], "nothing")
        self.assertFalse(tree.exists(), "closed with nothing to land: the worktree goes")
        self.assertEqual([call.args[1] for call in forgot.call_args_list], [tree])
        self.assertTrue(self.head(), "and no branch is deleted on this path")

    def test_a_landing_names_the_house_branch_it_leaves_in_the_repo(self):
        sh(self.repo, "git", "branch", "bosun/mine", self.head())
        self.board.set_fields(self.card, {"output_ref": "bosun/mine"}, "human")
        self.assertEqual(self.land(self.card), 0)
        self.assertEqual(self.board.get(self.card)["stage"], "done")
        notes = [e["text"] for e in self.board.events(self.card) if e["kind"] == "note"]
        self.assertEqual(len([n for n in notes if f"keel/{self.card}" in n]), 1)
        self.assertTrue(self.head(), "the house's branch is kept")


if __name__ == "__main__":
    unittest.main()
