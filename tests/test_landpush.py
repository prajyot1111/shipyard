"""Fetch before work and a Push after a landing, for a space with no pack (keel/landpush.py,
c-678). On a temp config laid out as an install's: a bare repo in the temp directory stands
for the repo's home address, Keel's copy is a clone of it, and a second clone is a teammate.
No real remote is reached, nothing is ever forced, and nothing outside the temp directory
is run."""

import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from keel import actions, adapters, house, landpush, settings, tierrecord
from keel.board import Refused, open_board
from keel.config import Space
from tests.helpers import make_config, make_repo

BEHIND = "origin has commits this computer has not seen, so the push was refused."
FILE = "# api\n\n## Prepare and test\n- Run the tests: `test ! -f bad.txt`\n"


def sh(cwd, *args):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


def commit(repo, name, text="x\n"):
    (repo / name).write_text(text)
    sh(repo, "git", "add", name)
    sh(repo, "git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", f"add {name}")
    return sh(repo, "git", "rev-parse", "HEAD")


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        self.origin = self.dir / "origin.git"
        sh(self.dir, "git", "clone", "-q", "--bare", str(make_repo(self.dir / "seed")), str(self.origin))
        self.home = self.dir / "spaces" / "work" / "api"
        self.home.mkdir(parents=True)
        self.repo = self.home / "repo"
        sh(self.dir, "git", "clone", "-q", str(self.origin), str(self.repo))
        # the temp copy's own identity, for the merge commit a fetch may have to make
        sh(self.repo, "git", "config", "user.name", "t")
        sh(self.repo, "git", "config", "user.email", "t@example.invalid")
        self.mate = self.dir / "mate"
        sh(self.dir, "git", "clone", "-q", str(self.origin), str(self.mate))
        self.cfg = make_config(self.dir, repos={"keel": make_repo(self.dir / "elsewhere")})
        self.cfg.source = self.dir / "config.toml"
        # both switches on, as the first run writes them for the space it makes (review F1)
        self.space = Space(name="work", config_dir=self.dir / "cfg-work", repos={"api": self.repo},
                           contract=None, adapter=None, house_review=False,
                           fetch_before_work=True, offer_push=True)
        self.cfg.spaces["work"] = self.space
        (self.home / "CLAUDE.md").write_text("# api\n")
        self.card = {"id": "c-1", "space": "work", "repo": "api", "title": "A thing", "options": {}}

    def teammate(self, name="theirs.txt", text="x\n"):
        sha = commit(self.mate, name, text)
        sh(self.mate, "git", "push", "-q", "origin", "main")
        return sha

    def landed(self, name="mine.txt", text="x\n"):
        """A done card whose work is merged into main in Keel's copy, as a landing records it."""
        sha = commit(self.repo, name, text)
        return dict(self.card, stage="done", options={"landing": {
            "state": "landed", "sha": sha, "merge": sha,
            "published": f"{sha[:7]} merged into main locally, not pushed"}})

    def at_origin(self, sha):
        return subprocess.run(["git", "-C", str(self.origin), "merge-base", "--is-ancestor", sha, "main"]).returncode == 0

    def origin_head(self):
        return sh(self.origin, "git", "rev-parse", "main")


class FetchFirstTest(Case):
    def test_a_new_card_builds_on_what_the_team_has(self):
        self.teammate()
        [tree] = adapters.worktree(self.cfg, self.card)
        self.assertTrue((tree / "theirs.txt").is_file(), "the copy was fetched and moved before the worktree was cut")
        self.assertTrue((self.repo / "theirs.txt").is_file())

    def test_the_switch_off_fetches_nothing(self):
        self.space.fetch_before_work = False
        self.teammate()
        [tree] = adapters.worktree(self.cfg, self.card)
        self.assertFalse((tree / "theirs.txt").exists())

    def test_a_fetch_that_fails_never_refuses_the_card(self):
        self.origin.rename(self.dir / "gone.git")
        said = landpush.fetch_first(self.cfg, self.space, "api")
        self.assertIn("could not fetch api from origin", said)
        [tree] = adapters.worktree(self.cfg, self.card)
        self.assertTrue(tree.is_dir())

    def test_what_the_fetch_could_not_do_is_said_on_the_card_and_in_the_brief(self):
        """The page promises the card builds on what the team has; where it does not, the card
        and the session are told (review F6)."""
        self.origin.rename(self.dir / "gone.git")
        with open_board(self.cfg) as board:
            card = board.create("work", "A thing", repo="api", actor="human", model="opus")
            adapters.worktree(self.cfg, board.get(card))
            said = [event["text"] for event in board.events(card) if event["kind"] == "note"]
            block = house.cut_block(self.cfg, board.get(card))
        self.assertEqual(len(said), 1)
        self.assertIn("could not fetch api from origin before the card started, so it builds on what this "
                      "computer has", said[0])
        self.assertIn(said[0], block)
        self.assertIn("### When this worktree was cut", block)

    def test_a_card_that_was_cut_level_with_the_remote_has_nothing_said(self):
        with open_board(self.cfg) as board:
            card = board.create("work", "A thing", repo="api", actor="human", model="opus")
            adapters.worktree(self.cfg, board.get(card))
            self.assertEqual([event for event in board.events(card) if event["kind"] == "note"], [])
            self.assertIsNone(house.cut_block(self.cfg, board.get(card)))

    def test_the_fetch_before_a_cut_has_a_short_clock_of_its_own(self):
        """It runs in whoever cuts the worktree, so it does not get the push's two minutes."""
        self.assertLessEqual(landpush.FETCH_FIRST_SECONDS, 30)
        asked = []
        real = subprocess.run

        def run(argv, **rest):
            asked.append((list(argv), rest.get("timeout")))
            return real(argv, **rest)
        with mock.patch.object(landpush.subprocess, "run", run):
            landpush.fetch_first(self.cfg, self.space, "api")
        fetches = [timeout for argv, timeout in asked if "fetch" in argv]
        self.assertEqual(fetches, [landpush.FETCH_FIRST_SECONDS])

    def test_a_copy_that_has_moved_too_is_left_where_it_is(self):
        mine = commit(self.repo, "mine.txt")
        self.teammate()
        said = landpush.fetch_first(self.cfg, self.space, "api")
        self.assertIn("have each moved", said)
        self.assertEqual(sh(self.repo, "git", "rev-parse", "HEAD"), mine)

    def test_a_repo_the_install_did_not_copy_is_never_fetched(self):
        self.assertIsNone(landpush.applies(self.cfg, "personal", "keel"))
        self.assertIsNone(landpush.fetch_first(self.cfg, self.cfg.spaces["personal"], "keel"))

    def test_a_space_with_a_pack_is_its_packs_business(self):
        self.space.adapter_dir = self.dir / "pack"
        self.assertIsNone(landpush.applies(self.cfg, "work", "api"))

    def test_a_space_whose_config_names_neither_switch_fetches_and_offers_nothing(self):
        """A finished install does not change by itself (review F1): both are off unless set."""
        plain = Space(name="work", config_dir=self.dir / "cfg-work", repos={"api": self.repo},
                      contract=None, adapter=None, house_review=False)
        self.cfg.spaces["work"] = plain
        sha = self.teammate()
        self.assertIsNone(landpush.fetch_first(self.cfg, plain, "api"))
        self.assertNotEqual(sh(self.repo, "git", "rev-parse", "HEAD"), sha, "nothing was fetched")
        self.assertIsNone(landpush.offer(self.cfg, self.landed()))
        self.assertEqual((landpush.panel(self.cfg)["work"]["fetch"], landpush.panel(self.cfg)["work"]["push"]),
                         (False, False))


class OfferTest(Case):
    def test_a_landed_card_offers_the_push_until_origin_has_it(self):
        card = self.landed()
        offer = landpush.offer(self.cfg, card)
        self.assertEqual((offer["branch"], offer["remote"], offer["pushed"]), ("main", "origin", False))
        self.assertEqual(offer["said"], "Merged into main on this computer.")
        landpush.push(self.cfg, card)
        self.assertTrue(landpush.offer(self.cfg, card)["pushed"])

    def test_nothing_is_offered_where_it_does_not_apply(self):
        card = self.landed()
        self.assertIsNone(landpush.offer(self.cfg, dict(card, stage="review")), "not landed yet")
        self.assertIsNone(landpush.offer(self.cfg, dict(card, options={})), "no landing record")
        self.space.offer_push = False
        self.assertIsNone(landpush.offer(self.cfg, card), "the space's switch is off")
        self.space.offer_push = True
        self.space.adapter_dir = self.dir / "pack"
        self.assertIsNone(landpush.offer(self.cfg, card), "a pack publishes its own way")


class PushTest(Case):
    def test_the_push_puts_the_landing_at_origin(self):
        card = self.landed()
        done = landpush.push(self.cfg, card)
        self.assertTrue(self.at_origin(card["options"]["landing"]["sha"]))
        self.assertEqual(done["note"], "main is pushed to origin")

    def test_origin_ahead_refuses_the_push_and_nothing_is_forced(self):
        card = self.landed()
        theirs = self.teammate()
        with self.assertRaises(landpush.PushRefused) as caught:
            landpush.push(self.cfg, card)
        self.assertEqual(str(caught.exception), BEHIND)
        self.assertEqual(caught.exception.detail, {"kind": "behind"})
        self.assertEqual(self.origin_head(), theirs, "origin is exactly where the teammate left it")

    def test_with_fetch_origins_commits_are_merged_in_and_pushed(self):
        card = self.landed()
        theirs = self.teammate()
        landpush.push(self.cfg, card, fetch=True)
        self.assertTrue(self.at_origin(card["options"]["landing"]["sha"]))
        self.assertTrue(self.at_origin(theirs))
        self.assertTrue((self.repo / "theirs.txt").is_file() and (self.repo / "mine.txt").is_file())

    def test_commits_that_disagree_are_not_merged_and_nothing_is_pushed(self):
        card = self.landed("same.txt", "mine\n")
        theirs = self.teammate("same.txt", "theirs\n")
        head = sh(self.repo, "git", "rev-parse", "HEAD")
        with self.assertRaisesRegex(landpush.PushRefused, "change the same lines"):
            landpush.push(self.cfg, card, fetch=True)
        self.assertEqual(self.origin_head(), theirs)
        self.assertEqual(sh(self.repo, "git", "rev-parse", "HEAD"), head, "Keel's copy is where it was")
        self.assertEqual(sh(self.repo, "git", "status", "--porcelain", "--untracked-files=no"), "")

    def test_the_merged_tree_is_tested_before_it_is_pushed(self):
        (self.home / "CLAUDE.md").write_text(FILE)
        with open_board(self.cfg) as board:         # saved by the user: only that text runs (F3)
            tierrecord.saved(board, self.home / "CLAUDE.md", FILE)
        card = self.landed()
        theirs = self.teammate("bad.txt")
        head = sh(self.repo, "git", "rev-parse", "HEAD")
        with self.assertRaisesRegex(landpush.PushRefused, "tests failed with origin's commits merged in"):
            landpush.push(self.cfg, card, fetch=True)
        self.assertEqual(self.origin_head(), theirs)
        self.assertEqual(sh(self.repo, "git", "rev-parse", "HEAD"), head)

    def test_a_card_with_nothing_to_push_is_refused(self):
        with self.assertRaisesRegex(landpush.PushRefused, "c-1 has nothing to push"):
            landpush.push(self.cfg, dict(self.card, stage="review"))


class WorkerTest(Case):
    """The push that has to bring in the team's commits runs in a worker of its own (review
    F10): the verb marks the card and returns, the worker answers on the card."""

    def setUp(self):
        super().setUp()
        self.board = open_board(self.cfg).__enter__()
        self.addCleanup(self.board.close)
        self.spawned, self.taps = [], []

        def spawned(cfg, card, tap):
            self.spawned.append(card)
            self.taps.append(tap)
            return 4242
        spawn = mock.patch.object(landpush, "spawn", side_effect=spawned)
        spawn.start()
        self.addCleanup(spawn.stop)

    def worker(self, card) -> int:
        """The worker as the tap started it: with the id of the event that tap left."""
        return landpush.work(self.cfg, self.board, card, self.taps[-1])

    def whole(self, card):
        """Everything a worker could change: the card, its events, both heads."""
        return (self.board.get(card), [dict(event) for event in self.board.events(card)],
                self.origin_head(), sh(self.repo, "git", "rev-parse", "HEAD"))

    def on_board(self, name="mine.txt", text="x\n") -> str:
        """A done card on the board whose work is merged into main in Keel's copy."""
        landing = self.landed(name, text)["options"]["landing"]
        card = self.board.create("work", "A thing", repo="api", actor="human", model="opus")
        self.board.set_fields(card, {"options": {"landing": landing}}, "drain")
        self.board.conn.execute("UPDATE cards SET stage = 'done' WHERE id = ?", (card,))
        self.board.conn.commit()
        return card

    def act(self, card, **more):
        return actions.act(self.cfg, self.board, dict({"verb": "land.push", "id": card}, **more))

    def push_state(self, card):
        return (self.board.get(card)["options"].get("push") or {})

    def test_the_verb_marks_the_card_and_returns_before_anything_is_fetched_or_tested(self):
        card = self.on_board()
        theirs = self.teammate()
        head = sh(self.repo, "git", "rev-parse", "HEAD")
        done = self.act(card, fetch=True)
        self.assertEqual(done["push"], "testing")
        self.assertEqual(self.spawned, [card], "one worker, for this card")
        self.assertEqual(self.push_state(card)["state"], "testing")
        self.assertEqual(sh(self.repo, "git", "rev-parse", "HEAD"), head, "nothing was merged in the handler")
        self.assertFalse(self.at_origin(head))
        self.assertEqual(self.origin_head(), theirs)

    def test_the_worker_fetches_merges_tests_and_pushes_and_says_so_on_the_card(self):
        card = self.on_board()
        theirs = self.teammate()
        self.act(card, fetch=True)
        self.assertEqual(self.worker(card), 0)
        self.assertTrue(self.at_origin(theirs))
        self.assertTrue((self.repo / "theirs.txt").is_file() and (self.repo / "mine.txt").is_file())
        self.assertEqual(self.push_state(card)["state"], "pushed")
        self.assertIn("main is pushed to origin", [event["text"] for event in self.board.events(card)][-1])
        offer = landpush.offer(self.cfg, self.board.get(card))
        self.assertEqual((offer["pushed"], offer["testing"], offer["refused"]), (True, False, None))

    def test_a_worker_whose_tests_fail_leaves_the_refusal_on_the_card_and_pushes_nothing(self):
        (self.home / "CLAUDE.md").write_text(FILE)
        tierrecord.saved(self.board, self.home / "CLAUDE.md", FILE)
        card = self.on_board()
        theirs = self.teammate("bad.txt")
        head = sh(self.repo, "git", "rev-parse", "HEAD")
        self.act(card, fetch=True)
        self.assertEqual(self.worker(card), 1)
        self.assertEqual((self.origin_head(), sh(self.repo, "git", "rev-parse", "HEAD")), (theirs, head))
        state = self.push_state(card)
        self.assertEqual((state["state"], state["kind"]), ("refused", "tests"))
        offer = landpush.offer(self.cfg, self.board.get(card))
        self.assertFalse(offer["testing"])
        self.assertEqual(offer["refused"]["kind"], "tests")
        self.assertIn("tests failed with origin's commits merged in", offer["refused"]["error"])
        self.assertIn("the push did not happen", [event["text"] for event in self.board.events(card)][-1])

    def test_a_push_that_must_merge_is_refused_while_the_repo_file_stands_changed(self):
        """As a landing is: Keel cannot know what to test on the merged tree."""
        (self.home / "CLAUDE.md").write_text(FILE)
        tierrecord.saved(self.board, self.home / "CLAUDE.md", FILE)
        card = self.on_board()
        theirs = self.teammate()
        (self.home / "CLAUDE.md").write_text(FILE + "- Lint: `true`\n")
        self.act(card, fetch=True)
        self.assertEqual(self.worker(card), 1)
        self.assertEqual(self.origin_head(), theirs)
        self.assertEqual(self.push_state(card)["why"],
                         "api's CLAUDE.md changed since it was adopted or saved, and Shipyard takes this repo's test "
                         "command from that file, so nothing was merged or pushed. Adopt or save the file again "
                         "(Setup, the api repo's file), then push.")

    def test_the_tests_are_told_the_commit_the_merge_was_built_on(self):
        """`{base}` in a test command was left as the literal text."""
        self.cfg.repo_tests["api"] = "git cat-file -e {base}"
        card = self.on_board()
        theirs = self.teammate()
        self.act(card, fetch=True)
        self.assertEqual(self.worker(card), 0, self.push_state(card))
        self.assertTrue(self.at_origin(theirs))

    def test_a_worker_nobody_tapped_for_pushes_nothing_and_changes_nothing(self):
        """`python3 -m keel.landpush <card>` pushed for whoever ran it (review r2.F2)."""
        card = self.on_board()
        self.teammate()
        other = self.on_board("other.txt")
        with self.board.tx():
            theirs = self.board.record_event(other, "note", "human", text="asked", data={"push": "asked"})
            house = self.board.record_event(card, "note", "house", text="asked", data={"push": "asked"})
            plain = self.board.record_event(card, "note", "human", text="a note of the user's")
        before = self.whole(card)
        for tap in (None, 0, 999999, "x", theirs, house, plain):
            with self.subTest(tap=tap):
                self.assertEqual(landpush.work(self.cfg, self.board, card, tap), 1)
                self.assertEqual(self.whole(card), before)
        # with the mark itself naming each event, so the PROOF query is what decides (fix
        # check r2.D5): another card's event, a house's note, a plain note of the user's
        for name, tap in (("another card's", theirs), ("a house's", house), ("a plain note", plain), ("none", 999999)):
            with self.subTest(mark=name):
                landpush.mark(self.board, card, {"state": "testing", "host": self.cfg.host, "tap": tap})
                marked = self.whole(card)
                self.assertFalse(landpush.asked(self.cfg, self.board, self.board.get(card), tap))
                self.assertEqual(landpush.work(self.cfg, self.board, card, tap), 1)
                self.assertEqual(self.whole(card), marked)
        self.board.set_fields(card, {"options": {"push": None}}, "drain")
        before = self.whole(card)
        # the command itself, on this test's config: never the machine's own
        with mock.patch.object(landpush.config_module, "load", return_value=self.cfg):
            self.assertEqual(landpush.main([card]), 1, "with no tap named")
            self.assertEqual(landpush.main([card, "--tap", str(theirs)]), 1, "with another card's tap")
        self.assertEqual(self.whole(card), before)

    def test_the_tap_leaves_the_users_own_event_and_the_worker_is_handed_its_id(self):
        card = self.on_board()
        self.teammate()
        self.act(card, fetch=True)
        event = [event for event in self.board.events(card) if event["id"] == self.taps[-1]]
        self.assertEqual([(found["kind"], found["actor"]) for found in event], [("note", "human")])
        self.assertEqual(self.push_state(card)["tap"], self.taps[-1])

    def test_a_tap_is_good_for_one_worker(self):
        """The worker writes its pid as it takes the tap, and a mark with a pid is taken."""
        card = self.on_board()
        theirs = self.teammate()
        self.act(card, fetch=True)
        landpush.mark(self.board, card, dict(self.push_state(card), pid=os.getpid()))
        before = self.whole(card)
        self.assertEqual(self.worker(card), 1)
        self.assertEqual(self.whole(card), before)
        self.assertEqual(self.origin_head(), theirs)

    def test_two_workers_cannot_both_take_one_tap(self):
        """The read of the mark and the write of the pid were two steps (fix check r2.D5)."""
        card = self.on_board()
        theirs = self.teammate()
        self.act(card, fetch=True)
        tap = self.taps[-1]
        self.assertTrue(landpush.take(self.cfg, self.board, card, tap, 111))
        self.assertFalse(landpush.take(self.cfg, self.board, card, tap, 222), "the mark is taken")
        self.assertEqual(self.push_state(card)["pid"], 111)
        # a second worker that read the mark before the first wrote its pid
        with mock.patch.object(landpush, "asked", return_value=True):
            self.assertEqual(self.worker(card), 1)
        self.assertEqual((self.push_state(card)["pid"], self.origin_head()), (111, theirs))

    def test_a_tap_nobody_took_in_a_minute_is_no_longer_taken(self):
        card = self.on_board()
        theirs = self.teammate()
        self.act(card, fetch=True)
        # two minutes: past the one-minute rule and well short of the five a dead worker is
        # given, so only the minute rule can make the assertions below pass
        ago = (datetime.now().astimezone() - timedelta(minutes=2)).isoformat(timespec="seconds")
        state = dict(self.push_state(card), at=ago)
        self.board.conn.execute("UPDATE cards SET options = json_set(options, '$.push', json(?)) WHERE id = ?",
                                (json.dumps(state), card))
        self.board.conn.commit()
        self.assertFalse(landpush.asked(self.cfg, self.board, self.board.get(card), self.taps[-1]))
        self.assertEqual(self.worker(card), 1)
        self.assertEqual(self.origin_head(), theirs)
        offer = landpush.offer(self.cfg, self.board.get(card))
        self.assertFalse(offer["testing"], "and the card does not say testing for a worker that never came")

    def test_a_tap_that_was_answered_starts_no_second_worker(self):
        card = self.on_board()
        self.teammate()
        self.act(card, fetch=True)
        self.assertEqual(self.worker(card), 0)
        before = self.whole(card)
        self.assertEqual(self.worker(card), 1)
        self.assertEqual(self.whole(card), before)

    def test_a_card_the_worker_cannot_read_ends_it_without_a_crash(self):
        self.assertEqual(landpush.work(self.cfg, self.board, "c-9999", 1), 1)

    def test_a_worker_stopped_by_anything_answers_on_the_card(self):
        card = self.on_board()
        self.teammate()
        self.act(card, fetch=True)
        with mock.patch.object(landpush, "push", side_effect=RuntimeError("the disk went away")):
            self.assertEqual(self.worker(card), 1)
        state = self.push_state(card)
        self.assertEqual((state["state"], state["why"]), ("refused", "the push stopped: RuntimeError: the disk went away"))

    def test_a_plain_push_is_refused_while_a_worker_is_testing(self):
        """It wrote `refused` or `pushed` over the worker's mark, and a second worker could
        then be started beside the first (review r2.F10)."""
        card = self.on_board()
        theirs = self.teammate()
        self.act(card, fetch=True)
        landpush.mark(self.board, card, dict(self.push_state(card), pid=os.getpid(),
                                             started=landpush.born(os.getpid())))
        before = self.push_state(card)
        with self.assertRaisesRegex(actions.ActionError, "is already being tested"):
            self.act(card)
        self.assertEqual(self.push_state(card), before)
        self.assertEqual(self.origin_head(), theirs)

    def test_a_pid_that_another_process_took_is_not_the_worker(self):
        """`os.kill(pid, 0)` says yes for whatever process has the number now."""
        card = self.on_board()
        self.teammate()
        self.act(card, fetch=True)
        mine = landpush.born(os.getpid())
        self.assertIsNotNone(mine, "the system says when this process started")
        landpush.mark(self.board, card, dict(self.push_state(card), pid=os.getpid(), started=mine))
        self.assertTrue(landpush.offer(self.cfg, self.board.get(card))["testing"], "the worker itself")
        landpush.mark(self.board, card, dict(self.push_state(card), pid=os.getpid(), started=mine - 3600))
        offer = landpush.offer(self.cfg, self.board.get(card))
        self.assertFalse(offer["testing"], "a process that started after the worker did is not it")
        self.assertEqual(offer["refused"]["kind"], "failed")
        self.assertEqual(self.act(card, fetch=True)["push"], "testing", "and it can be started again")

    def test_a_worker_that_died_is_not_shown_as_testing_for_ever(self):
        card = self.on_board()
        self.teammate()
        self.act(card, fetch=True)
        gone = subprocess.Popen(["true"])
        gone.wait()                                     # a pid that is certainly no longer running
        landpush.mark(self.board, card, {"state": "testing", "host": self.cfg.host, "pid": gone.pid})
        offer = landpush.offer(self.cfg, self.board.get(card))
        self.assertFalse(offer["testing"])
        self.assertEqual(offer["refused"], {"error": "The push stopped before it finished, and nothing says why. "
                                                     "Try again.", "kind": "failed", "fetch": True})
        self.assertEqual(self.act(card, fetch=True)["push"], "testing", "and it can be started again")

    def test_a_push_being_tested_is_not_started_twice(self):
        card = self.on_board()
        self.teammate()
        self.act(card, fetch=True)
        landpush.mark(self.board, card, {"state": "testing", "host": self.cfg.host, "pid": os.getpid()})
        with self.assertRaisesRegex(actions.ActionError, "is already being tested"):
            self.act(card, fetch=True)
        self.assertEqual(self.spawned, [card])

    def test_a_plain_push_stays_in_the_tap_and_a_refusal_is_kept_on_the_card(self):
        card = self.on_board()
        self.teammate()
        with self.assertRaises(actions.ActionError) as refused:
            self.act(card)
        self.assertEqual((str(refused.exception), refused.exception.detail), (BEHIND, {"kind": "behind"}))
        self.assertEqual(self.spawned, [])
        offer = landpush.offer(self.cfg, self.board.get(card))
        self.assertEqual(offer["refused"], {"error": BEHIND, "kind": "behind", "fetch": False})

    def test_each_verb_refuses_through_the_page(self):
        review = self.board.create("work", "Another", repo="api", actor="human", model="opus")
        with self.assertRaisesRegex(actions.ActionError, "has nothing to push"):
            self.act(review)
        with self.assertRaisesRegex(actions.ActionError, "has nothing to push"):
            self.act(review, fetch=True)
        with self.assertRaisesRegex(actions.ActionError, "there is no space 'nowhere'"):
            actions.act(self.cfg, self.board, {"verb": "land.push.check", "space": "nowhere"})
        self.assertEqual(self.spawned, [])

    def test_a_session_may_not_write_the_push_mark(self):
        card = self.on_board()
        with self.assertRaisesRegex(Refused, "options.push is the drain's"):
            self.board.set_fields(card, {"options": {"push": {"state": "pushed"}}}, "house")


class NoPushTest(Case):
    """c-729, point 17: Keel's copy lands by the merge here, and its one push is the Push
    after a landing. A house pushed the card's branch by hand on the stranger run, so the copy
    itself cannot be pushed to: its remote's push address is one git cannot reach
    (`landpush.NO_PUSH`), set when the copy is made and when a card is next cut in it, and
    the Push sends the landed branch by the remote's own address."""

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)

    def branches(self):
        return sorted(sh(self.origin, "git", "for-each-ref", "--format=%(refname:short)", "refs/heads").split())

    def test_a_worktree_of_the_copy_cannot_push_to_origin_however_it_is_written(self):
        [tree] = adapters.worktree(self.cfg, self.card)
        commit(tree, "work.txt")
        branch = sh(tree, "git", "rev-parse", "--abbrev-ref", "HEAD")
        for args in (("push", "origin", branch), ("push", "-u", "origin", "HEAD"),
                     ("push", "origin", f"HEAD:{branch}"), ("push", "--all", "origin")):
            with self.subTest(args=args):
                self.assertNotEqual(self.git(tree, *args).returncode, 0)
                self.assertNotEqual(self.git(self.repo, *args).returncode, 0, "nor from the copy itself")
        self.assertEqual(self.branches(), ["main"], "nothing reached origin")
        self.assertEqual(self.git(self.repo, "fetch", "-q", "origin").returncode, 0, "fetching still works")

    def test_push_sends_main_to_origin_and_nothing_else(self):
        [tree] = adapters.worktree(self.cfg, self.card)
        commit(tree, "work.txt")
        card = self.landed()
        done = landpush.push(self.cfg, card)
        self.assertEqual(done["note"], "main is pushed to origin")
        self.assertTrue(self.at_origin(card["options"]["landing"]["sha"]))
        self.assertEqual(self.branches(), ["main"], "only main, never the card's branch")
        self.assertEqual(landpush.offer(self.cfg, card)["pushed"], True, "the copy knows origin has it")
        [row] = landpush.check(self.cfg, "work")
        self.assertTrue(row["ok"], row)

    def test_a_copy_from_before_is_fenced_when_a_card_is_next_cut(self):
        self.assertEqual(self.git(self.repo, "push", "-q", "origin", "main").returncode, 0)
        adapters.worktree(self.cfg, self.card)
        self.assertEqual(sh(self.repo, "git", "config", "--get-all", "remote.origin.pushurl"), landpush.NO_PUSH)
        self.assertNotEqual(self.git(self.repo, "push", "-q", "origin", "main").returncode, 0)

    def test_a_folder_the_user_attached_pushes_as_before(self):
        self.space.repos["live"] = self.mate
        card = dict(self.card, id="c-2", repo="live")
        [tree] = adapters.worktree(self.cfg, card)
        commit(tree, "theirs-too.txt")
        branch = sh(tree, "git", "rev-parse", "--abbrev-ref", "HEAD")
        self.assertEqual(self.git(tree, "push", "-q", "origin", branch).returncode, 0)
        self.assertIn(branch, self.branches())
        self.assertNotEqual(self.git(self.mate, "config", "--get", "remote.origin.pushurl").returncode, 0)

    def test_a_space_that_turns_a_pack_on_can_push_from_its_copy_again(self):
        adapters.worktree(self.cfg, self.card)
        self.space.adapter_dir = self.dir / "pack"
        landpush.fence(self.cfg, "work", "api")
        self.assertNotEqual(self.git(self.repo, "config", "--get", "remote.origin.pushurl").returncode, 0)

    def pushurls(self):
        return self.git(self.repo, "config", "--get-all", "remote.origin.pushurl").stdout.split()

    def test_a_push_address_the_user_set_is_kept_through_fence_and_unfence_and_push_uses_it(self):
        """fix check 1: the copy's own push address (an ssh one beside an https fetch, say) is
        saved, not lost; the Push goes to it; and a pack turned on puts it back."""
        mirror = self.dir / "push-here.git"
        sh(self.dir, "git", "clone", "-q", "--bare", str(self.origin), str(mirror))
        sh(self.repo, "git", "config", "remote.origin.pushurl", str(mirror))
        adapters.worktree(self.cfg, self.card)
        self.assertEqual(self.pushurls(), [landpush.NO_PUSH])
        card = self.landed()
        landpush.push(self.cfg, card)
        sha = card["options"]["landing"]["sha"]
        self.assertEqual(sh(mirror, "git", "rev-parse", "main"), sha, "the Push used the user's push address")
        self.assertFalse(self.at_origin(sha), "not the fetch address")
        self.space.adapter_dir = self.dir / "pack"
        landpush.fence(self.cfg, "work", "api")
        self.assertEqual(self.pushurls(), [str(mirror)], "put back as it was")

    def test_a_push_address_with_a_space_is_kept_whole(self):
        """A folder name with a space ('My Repos') is one address, saved, used and put back whole."""
        mirror = self.dir / "My Repos" / "push here.git"
        mirror.parent.mkdir()
        sh(self.dir, "git", "clone", "-q", "--bare", str(self.origin), str(mirror))
        sh(self.repo, "git", "config", "remote.origin.pushurl", str(mirror))
        adapters.worktree(self.cfg, self.card)
        self.assertEqual(self.git(self.repo, "config", "--get-all", "remote.origin.shipyardPushurl").stdout.splitlines(),
                         [str(mirror)])
        card = self.landed()
        landpush.push(self.cfg, card)
        self.assertEqual(sh(mirror, "git", "rev-parse", "main"), card["options"]["landing"]["sha"])
        self.space.adapter_dir = self.dir / "pack"
        landpush.fence(self.cfg, "work", "api")
        self.assertEqual(self.git(self.repo, "config", "--get-all", "remote.origin.pushurl").stdout.splitlines(),
                         [str(mirror)])

    def test_a_pack_added_by_hand_is_followed_at_the_next_cut_and_its_push_works(self):
        """fix check 2: every cut reconciles the copy with its space, whatever changed the
        config: a pack line written by hand takes the fence off, and the pack's push goes."""
        adapters.worktree(self.cfg, self.card)
        self.assertEqual(self.pushurls(), [landpush.NO_PUSH])
        pack = self.dir / "pack"
        pack.mkdir()
        trees = self.dir / "pack-trees"
        cut = pack / "worktree"
        cut.write_text(f"#!/bin/sh\ngit -C {self.repo} worktree add -q -b pack/$1 {trees}/$1 main >/dev/null 2>&1 "
                       f"&& echo {trees}/$1\n")
        cut.chmod(0o755)
        self.space.adapter_dir = pack
        card = dict(self.card, id="c-2")
        [tree] = adapters.worktree(self.cfg, card)
        self.assertEqual(self.pushurls(), [])
        commit(tree, "packed.txt")
        self.assertEqual(self.git(tree, "push", "-q", "origin", "pack/c-2").returncode, 0)
        self.assertIn("pack/c-2", self.branches())


class CanPushTest(Case):
    def test_each_copied_repo_says_whether_this_computer_can_push(self):
        [row] = landpush.check(self.cfg, "work")
        self.assertEqual((row["key"], row["ok"]), ("api", True))
        self.origin.rename(self.dir / "gone.git")
        [row] = landpush.check(self.cfg, "work")
        self.assertFalse(row["ok"])
        self.assertIn("git could not reach origin", row["why"])

    def test_the_panel_names_each_repos_host(self):
        sh(self.repo, "git", "remote", "set-url", "origin", "git@github.com:maya-okafor/api.git")
        panel = landpush.panel(self.cfg)
        self.assertEqual(panel["work"]["repos"], [{"key": "api", "host": "github.com", "branch": "main"}])
        self.assertEqual((panel["work"]["remote"], panel["work"]["fetch"], panel["work"]["push"]), ("origin", True, True))


if __name__ == "__main__":
    unittest.main()
