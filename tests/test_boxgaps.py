"""What the box test that finished the second stranger run found (c-734, points 11, 13 and 14).

(11) A review card's worktree (`spaces/work/<repo>/trees/c-003`, detached) was never removed
once the card was done: only a shipping card's merge reaped (`shipping.reap`). Now the review
fetcher's pass reaps the tree the pack recorded, by git, never under a live session, once a
round (`keel/reviewreap.py`). (13) A house committed `__pycache__`: a copy's own
`info/exclude` carries the build output it does not track (`keel/buildout.py`). (14) The
Reviews gear read `scan_asked` true for a moment after the scan filed its card: the deck keeps
a provider reading for 30 seconds, and a change to the scan file makes it stale."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import buildout, deckstate, readings, reviewcards, reviewreap, reviewsettings
from keel.board import open_board
from tests.helpers import SESSION, background_row, make_config


def team():
    """A real install with a team remote (main, and staging ahead of it), as test_bases has it."""
    from tests.test_bases import Cards
    case = Cards("run")
    case.setUp()
    return case


class ReviewCase(unittest.TestCase):
    """The review tree is cut where a pack records it (`options.worktree`, detached at the pull
    request's head); a worktree of the user's has the pull request's branch out in the same repo."""

    def setUp(self):
        from tests.test_bases import git
        self.git = git
        self.case = team()
        self.addCleanup(self.case.doCleanups)
        self.repo = self.case.with_team()
        self.cfg = self.case.cfg()
        git(self.repo, "branch", "staging", "refs/remotes/origin/staging")
        self.mine = self.case.dir / "mine-staging"
        git(self.repo, "worktree", "add", "-q", str(self.mine), "staging")        # the user's own
        with open_board(self.cfg) as board:
            self.card = board.create("team", "Review: a change", brief="", repo="shop", actor="human",
                                     options={reviewcards.KEY_OPTION: "shop:7", "branch": "staging", "slot": "review"})
        self.tree = self.tree_path()
        self.cut()
        self.set({"worktree": str(self.tree)})
        self.done()

    def cut(self):
        self.git(self.repo, "worktree", "add", "-q", "--detach", str(self.tree), "refs/remotes/origin/staging")

    def set(self, options):
        with open_board(self.cfg) as board:
            board.set_fields(self.card, {"options": options}, "drain")

    def done(self):
        with open_board(self.cfg) as board:
            board.conn.execute("UPDATE cards SET stage = 'done', updated_at = ? WHERE id = ?", (board.now(), self.card))
            board.conn.commit()

    def reap(self, rows=()):
        with open_board(self.cfg) as board, mock.patch.object(reviewreap.harness, "agents", return_value=list(rows)):
            return reviewreap.reap(self.cfg, board, "team")

    def notes(self):
        with open_board(self.cfg) as board:
            return [e["text"] for e in board.events(self.card) if e["kind"] == "note"]

    def tree_path(self):
        """Where Keel's own layout cuts: `spaces/<space>/<key>/trees/<name>`."""
        return self.repo.parent / "trees" / "review-shop-7"


class ReapReviewedTest(ReviewCase):
    def test_the_recorded_tree_is_reaped_once_and_the_users_worktree_on_its_branch_stays(self):
        self.assertEqual(self.reap(), [self.card])
        self.assertFalse(self.tree.exists())
        self.assertTrue((self.mine / ".git").exists(), "a worktree of the user's on the pull request's branch stays")
        self.assertIn(f"worktree reaped: {self.tree}", self.notes())
        self.assertEqual(self.reap(), [], "once a round")

    def test_a_re_reviewed_cards_new_tree_is_reaped_too(self):
        self.reap()
        self.cut()
        self.set({"review_round": 2})
        self.done()
        self.assertEqual(self.reap(), [self.card])
        self.assertFalse(self.tree.exists())

    def test_a_card_whose_session_is_listed_is_left_until_it_is_not(self):
        with open_board(self.cfg) as board:
            board.set_session(self.card, SESSION, "drain", bg_id=SESSION[:8])
        live = background_row(self.card, SESSION, status="idle")
        self.assertEqual(self.reap([live]), [])
        self.assertTrue(self.tree.exists(), "an idle house still listed keeps its tree")
        self.assertEqual(self.reap(), [self.card])
        self.assertFalse(self.tree.exists())

    def test_a_tree_any_listed_session_runs_in_is_left(self):
        other = dict(background_row("c-99", "f" * 36), cwd=str(self.tree / "src"))
        self.assertEqual(self.reap([other]), [])
        self.assertTrue(self.tree.exists())

    def test_a_card_under_a_voice_hold_is_left(self):
        self.set({"voice_hold": {"until": "2999-01-01T00:00:00+00:00"}})
        self.assertEqual(self.reap(), [])
        self.assertTrue(self.tree.exists(), "the user is talking to it: its tree stays")
        self.set({"voice_hold": None})
        self.assertEqual(self.reap(), [self.card], "reaped once the hold is gone")

    def test_a_card_under_a_dropin_hold_is_left(self):
        self.set({"dropin_hold": {"seen": True}})
        self.assertEqual(self.reap(), [])
        self.assertTrue(self.tree.exists(), "the user dropped into its session: its tree stays")

    def test_a_tree_a_session_of_another_space_runs_in_is_left(self):
        """Every config dir's sessions are read, as a pass reads them, not only the review
        space's: a session the user runs from another space may sit in the tree."""
        import dataclasses
        other = next(name for name in self.cfg.spaces if name != "team")
        theirs = self.case.dir / "cfg-other"         # its own config dir, as an owner's space has
        self.cfg.spaces[other] = dataclasses.replace(self.cfg.spaces[other], config_dir=theirs)
        inside = dict(background_row("c-99", "f" * 36), cwd=str(self.tree))

        def listing(config_dir, strict=False):
            return [inside] if str(config_dir) == str(theirs) else []

        with open_board(self.cfg) as board, \
                mock.patch.object(reviewreap.harness, "agents", side_effect=listing):
            self.assertEqual(reviewreap.reap(self.cfg, board, "team"), [])
        self.assertTrue(self.tree.exists())

    def test_a_listing_that_fails_reaps_nothing(self):
        with open_board(self.cfg) as board, \
                mock.patch.object(reviewreap.harness, "agents", side_effect=reviewreap.harness.HarnessError("no")):
            self.assertEqual(reviewreap.reap(self.cfg, board, "team"), [])
        self.assertTrue(self.tree.exists())

    def test_a_tree_with_changes_is_kept_and_said_once(self):
        (self.tree / "README.md").write_text("changed\n")
        self.assertEqual(self.reap(), [self.card])
        self.assertTrue(self.tree.exists())
        self.assertTrue(any(note.startswith("worktree kept, ") for note in self.notes()))
        self.assertEqual(self.reap(), [])

    def test_only_a_recorded_path_is_reaped(self):
        self.set({"worktree": None})
        self.assertEqual(self.reap(), [], "nothing recorded: nothing is reaped")
        self.assertEqual(self.reap(), [])
        self.assertTrue(self.tree.exists(), "no recorded path: nothing is guessed")
        self.assertEqual(self.notes(), [reviewreap.NO_TREE], "said once, so it is read once")

    def test_a_recorded_tree_already_gone_gets_its_own_plain_note_once(self):
        self.git(self.repo, "worktree", "remove", str(self.tree))
        self.assertEqual(self.reap(), [])
        self.assertEqual(self.reap(), [])
        self.assertEqual(self.notes(), [reviewreap.NO_TREE], "not NOT_OURS: there is nothing to reap")

    def test_a_card_that_is_not_done_or_not_a_review_keeps_its_tree(self):
        with open_board(self.cfg) as board:
            board.conn.execute("UPDATE cards SET stage = 'building' WHERE id = ?", (self.card,))
            board.conn.commit()
        self.assertEqual(self.reap(), [])
        self.assertTrue(self.tree.exists())


class WhoReapsTest(ReviewCase):
    """r2: Keel reaps with plain git only a tree its own layout cut; a tree a pack keeps in a
    home of its own is the pack's, and only a pack declaring `review_reap` is asked."""

    def tree_path(self):
        """A pack's own tree home, outside the install's layout (as the owner's work pack has)."""
        return self.case.dir / "wt-home" / "review-shop-7"

    def layout_tree(self):
        tree = self.repo.parent / "trees" / self.card
        self.git(self.repo, "worktree", "add", "-q", "--detach", str(tree), "refs/remotes/origin/staging")
        self.set({"worktree": str(tree)})
        return tree

    def test_a_tree_inside_the_layout_is_reaped_with_git(self):
        tree = self.layout_tree()
        with mock.patch.object(reviewreap.adapters, "run") as pack:
            self.assertEqual(self.reap(), [self.card])
        self.assertFalse(tree.exists())
        pack.assert_not_called()

    def test_a_tree_outside_the_layout_with_no_capability_is_left_alone(self):
        with mock.patch.object(reviewreap.adapters, "run") as pack, \
                mock.patch.object(reviewreap.harness, "agents") as listed:
            self.assertEqual(self.reap(), [])
            self.assertEqual(self.reap(), [])
        self.assertTrue(self.tree.exists(), "the owner's work pack keeps its review trees: untouched")
        pack.assert_not_called()
        listed.assert_not_called()
        self.assertEqual(self.notes(), [reviewreap.NOT_OURS], "said once for its round, then not read again")

    def test_with_the_capability_the_pack_verb_is_called_with_that_card(self):
        answer = '{"removed": ["%s"], "kept": []}' % self.tree
        with mock.patch.object(reviewreap, "pack_reaps", return_value=True), \
                mock.patch.object(reviewreap.adapters, "run", return_value=answer) as pack:
            self.assertEqual(self.reap(), [self.card])
        self.assertEqual(pack.call_args.args[1:4], ("ship", self.card, "reap"))
        self.assertTrue(self.tree.exists(), "Keel itself removes nothing outside its layout")
        self.assertIn(f"worktree reaped: {self.tree}", self.notes())

    def test_a_pack_toml_that_cannot_be_read_writes_nothing_and_is_asked_again(self):
        from keel import packs
        with mock.patch.object(reviewreap.packs, "at", side_effect=packs.PackError("unreadable")), \
                mock.patch.object(reviewreap.adapters, "run") as pack:
            self.assertEqual(self.reap(), [])
        pack.assert_not_called()
        self.assertTrue(self.tree.exists())
        self.assertEqual(self.notes(), [], "unknown is not a no: nothing written")
        self.assertEqual(self.reap(), [], "readable again, and it declares no review_reap")
        self.assertEqual(self.notes(), [reviewreap.NOT_OURS], "the next pass read it again")

    def test_the_capability_is_a_pack_toml_claim(self):
        from keel import packs
        self.assertIn("review_reap", packs.CAPABILITY_KEYS)
        self.assertEqual(packs.NEEDS["review_reap"], ("ship",))


class AskedAgainLaterTest(ReviewCase):
    """c-743: a pack keeping a review tree for a passing reason answers `later: true`, and a
    reap command that fails is read the same way: no reaped mark, asked again on a later pass."""

    AT = "2026-03-02T09:00:00+00:00"

    def setUp(self):
        from keel.board import Board
        for patch in (mock.patch.object(Board, "now", return_value=self.AT),      # the board's clock, pinned
                      mock.patch.dict(reviewreap.ASKED, clear=True)):
            started = patch.start()
            self.addCleanup(patch.stop)
            self.clock = self.clock if hasattr(self, "clock") else started
        super().setUp()
        self.keeps_its_trees()

    def keeps_its_trees(self):
        """The space on a pack of its own that declares `review_reap` in its `pack.toml`, so the
        real capability read runs (r2.F4); its `ship` is answered by `self.pack`."""
        import dataclasses
        pack = self.case.dir / "keeps"
        pack.mkdir()
        (pack / "pack.toml").write_text('name = "keeps"\nversion = "1"\ndescription = "Keeps its review trees."\n'
                                        '\n[capabilities]\nreview_reap = true\n')
        (pack / "ship").write_text("#!/bin/sh\nexit 1\n")
        (pack / "ship").chmod(0o755)
        self.cfg.spaces["team"] = dataclasses.replace(self.cfg.spaces["team"], adapter="keeps", adapter_dir=pack)

    def at(self, minutes=0, days=0):
        """Move the board's pinned clock to that long after `AT`."""
        from datetime import datetime, timedelta
        self.clock.return_value = (datetime.fromisoformat(self.AT) + timedelta(days=days, minutes=minutes)).isoformat()

    def tree_path(self):
        return self.case.dir / "wt-home" / "review-shop-7"       # the pack's own tree home

    def later(self, card_id):
        return json.dumps({"removed": [], "later": True,
                           "kept": [{"path": f"/wt/{card_id}", "why": "a session is live in it"}]})

    def gone(self, card_id):
        return json.dumps({"removed": [f"/wt/{card_id}"], "kept": []})

    def pack(self, answers):
        """The pack's `ship <id> reap`, answering per card: a string, or an error to raise."""
        def run(space, verb, card_id, *args, **kwargs):
            answer = answers[card_id](card_id) if callable(answers[card_id]) else answers[card_id]
            if isinstance(answer, Exception):
                raise answer
            return answer
        return mock.patch.object(reviewreap.adapters, "run", side_effect=run)

    def newer(self, count):
        """`count` more done review cards of the space, each updated after `self.card`."""
        made = []
        with open_board(self.cfg) as board:
            for index in range(count):
                made.append(board.create(
                    "team", f"Review: another {index}", brief="", repo="shop", actor="human",
                    options={reviewcards.KEY_OPTION: f"shop:{index + 20}", "worktree": str(self.tree)}))
                board.conn.execute("UPDATE cards SET stage = 'done', updated_at = ? WHERE id = ?",
                                   (f"2026-03-02T10:0{index}:00+00:00", made[-1]))
            board.conn.commit()
        return made

    def marks(self):
        with open_board(self.cfg) as board:
            return [e["data"] for e in board.events(self.card) if reviewreap.REAPED in (e["data"] or {})]

    def test_a_pack_answering_later_is_asked_again_and_has_no_reaped_mark(self):
        with self.pack({self.card: self.later}) as pack:
            self.assertEqual(self.reap(), [])
            self.assertEqual(self.reap(), [])
        self.assertEqual(pack.call_count, 2, "asked again on the next pass")
        self.assertEqual(self.marks(), [], "no reaped mark while the pack says later")
        with self.pack({self.card: self.gone}):
            self.assertEqual(self.reap(), [self.card])
        self.assertEqual(self.marks(), [{reviewreap.REAPED: 1}])

    def test_a_reap_command_that_fails_is_asked_again_and_has_no_reaped_mark(self):
        failed = reviewreap.adapters.AdapterError("work/ship c-1 did not finish in 300 s and was stopped")
        with self.pack({self.card: failed}) as pack:
            self.assertEqual(self.reap(), [])
            self.assertEqual(self.reap(), [])
        self.assertEqual(pack.call_count, 2)
        self.assertEqual(self.marks(), [])
        notes = self.notes()
        self.assertEqual(len(notes), 1, "why it waits is said once for a failed command too")
        self.assertIn("did not finish in 300 s", notes[0])

    def test_a_re_reviews_round_that_waits_too_is_said_again(self):
        with self.pack({self.card: self.later}):
            self.reap()
            self.set({"review_round": 2})
            self.done()
            self.reap()
            self.reap()
        with open_board(self.cfg) as board:
            said = [e["data"] for e in board.events(self.card) if reviewreap.LATER in (e["data"] or {})]
        self.assertEqual(said, [{reviewreap.LATER: 1}, {reviewreap.LATER: 2}], "once a round")
        self.assertEqual(self.marks(), [])

    def test_a_tree_of_keels_goes_while_the_packs_waits(self):
        """One card, two trees: Keel's own layout cut one, the pack keeps the other."""
        ours = self.repo.parent / "trees" / self.card
        self.git(self.repo, "worktree", "add", "-q", "--detach", str(ours), "refs/remotes/origin/staging")
        self.set({"worktree": str(ours), "worktrees": {"shop": str(self.tree)}})
        with self.pack({self.card: self.later}) as pack:
            self.assertEqual(self.reap(), [])
            self.assertEqual(self.reap(), [])
        self.assertFalse(ours.exists(), "Keel's own tree went on the first pass")
        self.assertEqual(pack.call_count, 2, "and the pack is asked again for its own")
        self.assertEqual(self.marks(), [])
        notes = self.notes()
        self.assertEqual(len(notes), 1, notes)
        self.assertIn(f"worktree reaped: {ours}", notes[0])
        self.assertIn(reviewreap.ASKED_AGAIN, notes[0])
        with self.pack({self.card: self.gone}):
            self.assertEqual(self.reap(), [self.card])
        self.assertEqual(self.marks(), [{reviewreap.REAPED: 1}])

    def test_a_waiting_card_under_a_hold_is_not_asked(self):
        with self.pack({self.card: self.later}) as pack:
            self.reap()
            self.set({"dropin_hold": {"seen": True}})
            self.assertEqual(self.reap(), [])
        self.assertEqual(pack.call_count, 1, "the user is on it: its pack is asked once the hold is gone")

    def test_an_answer_that_is_not_an_object_is_a_failed_command(self):
        with self.pack({self.card: "[]"}) as pack:
            self.assertEqual(self.reap(), [])
            self.assertEqual(self.reap(), [])
        self.assertEqual(pack.call_count, 2)
        self.assertEqual(self.marks(), [])

    def test_an_answer_whose_entries_are_malformed_is_a_failed_command(self):
        """r1.F5: a `kept` entry that is no object, or a `removed` that is no list of strings."""
        for answer in ('{"kept": ["/wt/x"]}', '{"removed": "/wt/x"}', '{"removed": [7]}', '{"kept": {"path": "/wt/x"}}'):
            with self.subTest(answer=answer), self.pack({self.card: answer}):
                self.assertEqual(self.reap(), [])
        self.assertEqual(self.marks(), [])
        self.assertEqual(len(self.notes()), 1, "said once, as any failed command")
        self.assertIn("the pack's reap failed", self.notes()[0])

    def test_a_pass_runs_at_most_reaps_max_pack_commands_whatever_they_answer(self):
        """r1.F3: one budget a pass, so the worst case is the one before c-743."""
        waiting = self.newer(reviewreap.REAPS_MAX + 2)
        answers = dict({card: self.later for card in waiting}, **{self.card: self.gone})
        with self.pack(answers) as pack:
            self.assertEqual(self.reap(), [])
            self.assertEqual(pack.call_count, reviewreap.REAPS_MAX)

    def test_cards_answering_later_are_asked_after_the_ones_not_asked_yet(self):
        waiting = self.newer(reviewreap.REAPS_MAX)
        answers = dict({card: self.later for card in waiting}, **{self.card: self.gone})
        with self.pack(answers):
            self.assertEqual(self.reap(), [], "the pass's commands went to the cards ahead of it")
            self.assertEqual(self.reap(), [self.card], "they wait now, so it is asked first")

    def test_cards_whose_command_failed_are_asked_after_the_ones_not_asked_yet(self):
        failing = self.newer(reviewreap.REAPS_MAX)
        answers = dict({card: reviewreap.adapters.AdapterError("no") for card in failing}, **{self.card: self.gone})
        with self.pack(answers) as pack:
            self.assertEqual(self.reap(), [])
            self.assertEqual(pack.call_count, reviewreap.REAPS_MAX)
            self.assertEqual(self.reap(), [self.card], "the waiting cards went to the back")

    def test_a_waiting_card_behind_always_failing_ones_is_asked_within_two_passes(self):
        """r1.F1: the waiting cards take turns, least recently asked first."""
        failing = self.newer(reviewreap.REAPS_MAX)
        answers = dict({card: reviewreap.adapters.AdapterError("no") for card in failing}, **{self.card: self.later})
        with self.pack(answers):
            for minute in (0, 1):                       # every card has been asked, and waits
                self.at(minutes=minute)
                self.assertEqual(self.reap(), [])
            answers[self.card] = self.gone
            reaped = []
            for minute in (2, 3):
                self.at(minutes=minute)
                reaped += self.reap()
        self.assertEqual(reaped, [self.card])

    def test_held_waiting_cards_do_not_keep_another_waiting_card_from_its_turn(self):
        """r2.F1: a waiting card Keel skips as live runs nothing, so it takes no slot, and it
        goes to the back like one that was asked."""
        ahead = self.newer(reviewreap.REAPS_MAX)
        answers = dict({card: self.later for card in ahead}, **{self.card: self.later})
        with self.pack(answers):
            for minute in (0, 1):                       # every card has been asked, and waits
                self.at(minutes=minute)
                self.assertEqual(self.reap(), [])
            with open_board(self.cfg) as board:
                for card in ahead:
                    board.set_fields(card, {"options": {"dropin_hold": {"seen": True}}}, "drain")
            answers[self.card] = self.gone
            reaped = []
            for minute in (2, 3):
                self.at(minutes=minute)
                reaped += self.reap()
        self.assertEqual(reaped, [self.card])

    def test_after_a_drain_restart_every_waiting_card_is_asked_within_two_passes(self):
        """r2.F4: the board holds the waiting notes, and the process's memory starts empty."""
        cards = self.newer(reviewreap.REAPS_MAX) + [self.card]
        asked = []

        def later(card_id):
            asked.append(card_id)
            return self.later(card_id)

        with self.pack({card: later for card in cards}):
            for minute in (0, 1):                       # every card has been asked, and waits
                self.at(minutes=minute)
                self.reap()
            reviewreap.ASKED.clear()                    # the drain restarted
            del asked[:]
            for minute in (2, 3):
                self.at(minutes=minute)
                self.reap()
        self.assertEqual(set(asked), set(cards))
        self.assertLessEqual(len(asked), 2 * reviewreap.REAPS_MAX)

    def test_more_recent_cards_than_a_pass_reads_do_not_hide_a_waiting_one(self):
        """r2.F3: the waiting rounds are read by their own query, with their own limit."""
        with self.pack({self.card: self.later}):
            self.reap()
        answers = dict({card: self.gone for card in self.newer(3)}, **{self.card: self.gone})
        with self.pack(answers), mock.patch.object(reviewreap, "CANDIDATES_MAX", 2):
            self.assertIn(self.card, self.reap())

    def test_the_waiting_rounds_are_found_through_their_notes_index(self):
        """r2.F2: from the events side, so a card past the recent days costs no subquery."""
        with open_board(self.cfg) as board:
            plan = board.conn.execute("EXPLAIN QUERY PLAN " + reviewreap.WAITING, ("team", 9)).fetchall()
        self.assertIn("events_reap_later", " ".join(str(tuple(row)) for row in plan))
        self.assertIn("AND updated_at >= ? AND", reviewreap.CANDIDATES, "the plain recency cut")

    def test_an_old_card_that_never_waited_is_not_asked(self):
        self.at(days=reviewreap.RECENT_DAYS + 6)
        with self.pack({self.card: self.gone}) as pack:
            self.assertEqual(self.reap(), [])
        pack.assert_not_called()

    def test_a_waiting_round_is_still_asked_after_the_recent_days(self):
        """r1.F2: its note promised another ask, so the recency cut does not drop it."""
        with self.pack({self.card: self.later}) as pack:
            self.reap()
            self.at(days=reviewreap.RECENT_DAYS + 6)
            self.reap()
        self.assertEqual(pack.call_count, 2)

    def test_why_a_tree_waits_is_said_on_the_card_once(self):
        with self.pack({self.card: self.later}):
            for _ in range(3):
                self.reap()
        notes = self.notes()
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("a session is live in it", notes[0])
        self.assertIn("asked again", notes[0])


class ScanAskedTest(unittest.TestCase):
    def test_once_the_scan_ran_the_gear_reads_scan_asked_false(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = make_config(Path(tmp.name).resolve())
        space = cfg.spaces["work"]
        kept = readings.Kept(30.0)
        self.addCleanup(kept.close)
        reviewsettings.ask_scan(cfg, "work")
        said = lambda space, strict=False: {"reviews": {"settings": {   # noqa: E731 - the pack's provider
            "scan_asked": "asked" in reviewsettings.scan_state(cfg, "work")}}}
        with mock.patch.object(deckstate.adapters, "providers_for", side_effect=said):
            read = lambda: deckstate.space_providers(cfg, space, kept)["reviews"]["settings"]["scan_asked"]  # noqa: E731
            self.assertTrue(read())
            reviewsettings.scanned(cfg, "work", reviewcards.now())
            read()                                   # answers the held reading, and reads again now
            for worker in list(kept.threads):
                worker.join(5)
            self.assertFalse(read(), "the gear stops saying Scanning once the scan has run")


class BuildOutputTest(unittest.TestCase):
    """(13) The box test's house committed `__pycache__/*.pyc` and took it out in a second
    commit. A copy the install made ignores the build output of the common toolchains in its
    own `info/exclude`, set at the copy and at every cut, so a house's `git add -A` leaves it."""

    def setUp(self):
        from tests.test_bases import git
        self.git = git
        self.case = team()
        self.addCleanup(self.case.doCleanups)
        self.repo = self.case.with_team()

    def exclude(self):
        return (self.repo / ".git" / "info" / "exclude").read_text()

    def test_a_house_add_all_leaves_build_output_out(self):
        card = self.case.card("c-1")
        tree = self.case.build(card, "work.py")
        for junk in ("__pycache__/work.cpython-314.pyc", ".pytest_cache/v/x", "node_modules/a/index.js"):
            (tree / junk).parent.mkdir(parents=True, exist_ok=True)
            (tree / junk).write_text("built\n")
        self.git(tree, "add", "-A")
        self.assertEqual(self.git(tree, "diff", "--cached", "--name-only"), "", "nothing of it was added")

    def test_a_pattern_the_repo_tracks_is_left_out_of_the_block(self):
        """r1.F11: a repo that vendors node_modules on purpose keeps adding it."""
        (self.repo / "node_modules" / "dep").mkdir(parents=True)
        (self.repo / "node_modules" / "dep" / "index.js").write_text("vendored\n")
        self.git(self.repo, "add", "-f", "node_modules")
        self.git(self.repo, "commit", "-qm", "vendor a dependency")
        buildout.ensure(self.repo)
        block = self.exclude().partition(buildout.BEGIN)[2]
        self.assertNotIn("node_modules/", block)
        self.assertIn("__pycache__/", block)

    def test_the_teams_gitignore_and_the_users_own_lines_are_kept_and_a_stale_block_replaced_once(self):
        """r1.F12."""
        (self.repo / ".gitignore").write_text("dist/\n")
        before = (self.repo / ".gitignore").read_bytes()
        path = self.repo / ".git" / "info" / "exclude"
        path.write_text("my-notes.txt\n" + buildout.BEGIN + "\nold-pattern/\n" + buildout.END + "\nsecrets.env\n")
        self.case.build(self.case.card("c-1"), "x.txt")      # a cut reconciles
        text = self.exclude()
        self.assertEqual(text.count(buildout.BEGIN), 1)
        self.assertNotIn("old-pattern/", text)
        self.assertIn("my-notes.txt", text)
        self.assertIn("secrets.env", text)
        self.assertEqual((self.repo / ".gitignore").read_bytes(), before, "the team's file is never written")
        self.assertFalse(buildout.ensure(self.repo), "a second reconcile writes nothing")

    def test_an_attached_checkout_is_never_touched(self):
        from tests.test_bases import team_remote
        theirs = self.case.dir / "mine"
        self.git(self.case.dir, "clone", "-q", str(team_remote(self.case.dir / "t")), str(theirs))
        before = (theirs / ".git" / "info" / "exclude").read_text()
        self.case.act({"verb": "setup.repo.attach", "space": "team", "key": "mine", "path": str(theirs)})
        self.assertFalse(buildout.reconcile(self.case.cfg(), "team", "mine"))
        self.assertEqual((theirs / ".git" / "info" / "exclude").read_text(), before)


if __name__ == "__main__":
    unittest.main()
