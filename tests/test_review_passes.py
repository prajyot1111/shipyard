"""Review passes: the open pass is verified first, and the stamp holds a head per worktree
(c-581, slice S3 of c-578, r-28 items 3 and 5).

On c-272 (2026-09-28) the house opened review pass 6, then ran `prep --since` and the
verifier. The verifier was recorded as a fix check against pass 5, the stamp moved to a head
nobody had verified, `keel-review answer` refused every r6 id, and `kb stage review` read
pass 5 and let the card through. On the same two-repo card the stamp tracked only the api
worktree while the webapp head moved.
"""

import json
from unittest import mock

from keel.board import Refused
from keel.review import agents, gate, prep, stagecheck, stamp
from tests.helpers import make_repo
from tests.test_review_delta import MEDIUM, DeltaCase
from tests.test_review_gate import GIT, answer, sh

KEPT = answer([{"id": "r2.F1", "verify": "kept", "reason": "it holds"}])


def stage_check(board, cfg, card_id):
    """`kb stage review`'s check on the house's machine, the base check aside."""
    (cfg.card_dir(card_id) / "context.md").write_text("# c\n\n## Risk\n\nhigh: r2.F1 left for him\n")
    with mock.patch.object(stagecheck, "base_check"):
        stagecheck.check(board.get(card_id), cfg.card_dir(card_id))


class OpenPassTest(DeltaCase):
    def open_second_pass(self):
        """Pass 1 closed with r1.F1 fixed; pass 2 opened by the reviewer, not yet verified."""
        card_id, worktree, card_dir, reviewed = self.reviewed_with(MEDIUM)
        self.board.set_fields(card_id, {"options": {"worktree": str(worktree)}}, "drain")
        head = self.fix(worktree)
        prep.prepare(card_dir, "main", [worktree])
        self.finished(card_id, worktree, agents.REVIEWER, answer([dict(MEDIUM, id="F1")]), trip_rounds=1)
        return card_id, worktree, card_dir, reviewed, head

    def test_the_c272_sequence_verifies_the_open_pass(self):
        card_id, worktree, card_dir, reviewed, head = self.open_second_pass()
        prep.prepare(card_dir, "main", [worktree], since=reviewed)
        self.finished(card_id, worktree, agents.VERIFIER, KEPT, trip_rounds=1)
        rounds = stamp.read_rounds(card_dir)
        self.assertTrue(rounds[-1]["complete"], "the verifier closes the open pass")
        self.assertEqual(rounds[-1]["findings"][0]["verify"], "kept")
        self.assertEqual(rounds[0].get("deltas") or [], [], "no fix check lands on pass 1")
        self.assertEqual(stamp.read_stamp(self.cfg, card_id)["round"], 2)
        self.assertEqual(self.stamped_head(card_id), head)
        prep.answer(card_dir, "r2.F1", "declined", "the plan keeps it")
        stage_check(self.board, self.cfg, card_id)

    def test_answer_and_stage_review_refuse_an_open_pass_with_its_step(self):
        card_id, worktree, card_dir, _, _ = self.open_second_pass()
        with self.assertRaises(prep.PrepError) as caught:
            prep.answer(card_dir, "r2.F1", "fixed", "")
        self.assertIn("review pass 2 is open", str(caught.exception))
        self.assertIn(agents.VERIFIER, str(caught.exception))
        with self.assertRaises(Refused) as refused:
            stage_check(self.board, self.cfg, card_id)
        self.assertIn("review pass 2 is open", str(refused.exception))

    def test_a_fix_check_on_a_closed_pass_still_moves_the_stamp(self):
        card_id, worktree, card_dir, reviewed = self.reviewed_with(MEDIUM)
        head = self.fix(worktree)
        self.delta(card_id, worktree, card_dir, reviewed,
                   answer([{"id": "r1.F1", "fixed": True}]))
        self.assertEqual(self.stamped_head(card_id), head)
        self.assertEqual(len(stamp.read_rounds(card_dir)[0]["deltas"]), 1)

    def test_an_unparsed_newest_pass_takes_no_fix_check(self):
        card_id, worktree, card_dir, reviewed = self.reviewed_with(MEDIUM)
        self.fix(worktree)
        prep.prepare(card_dir, "main", [worktree])
        self.finished(card_id, worktree, agents.REVIEWER, "Looks fine.", trip_rounds=1)
        self.delta(card_id, worktree, card_dir, reviewed, answer([{"id": "r1.F1", "fixed": True}]))
        self.assertEqual(self.stamped_head(card_id), reviewed)
        self.assertEqual(stamp.read_rounds(card_dir)[0].get("deltas") or [], [])
        with self.assertRaises(prep.PrepError) as caught:
            prep.answer(card_dir, "r1.F1", "fixed", "")
        self.assertIn(agents.REVIEWER, str(caught.exception))


class HeadsCase(DeltaCase):
    def at_review(self, repo="keel"):
        card_id, worktree = super().at_review(repo)
        self.board.set_fields(card_id, {"options": {"worktree": str(worktree)}}, "drain")
        return card_id, worktree

    def two_worktrees(self):
        card_id, worktree = self.at_review()
        other_repo = make_repo(self.dir / "other")
        other = self.cfg.worktrees_dir / f"{card_id}-other"
        sh(other_repo, "git", "worktree", "add", "-q", "-b", f"keel/{card_id}", str(other))
        (other / "side.txt").write_text("the other half\n")
        sh(other, *GIT, "add", "side.txt")
        sh(other, *GIT, "commit", "-q", "-m", "the other half")
        self.board.set_fields(card_id, {"options": {"worktrees": {"other": str(other)}}}, "drain")
        self.other_repo = other_repo
        return card_id, worktree, other, self.cfg.card_dir(card_id)

    def roots(self, *trees):
        return [str(tree.resolve()) for tree in trees]

    def covered(self, card_id, worktree):
        """The Stop hook does not send it back for the review (its record check may)."""
        said = (self.stop(card_id, worktree) or {}).get("reason", "")
        self.assertNotIn(agents.REVIEWER, said)
        self.assertEqual(self.board.get(card_id)["stage"], "review")

    def not_covered(self, card_id, worktree):
        self.assertIn(agents.REVIEWER, self.stop(card_id, worktree)["reason"])


class HeadsTest(HeadsCase):
    def test_a_two_worktree_stamp_names_both_heads(self):
        card_id, worktree, other, card_dir = self.two_worktrees()
        prep.prepare(card_dir, "main", [worktree, other])
        self.finished(card_id, worktree, agents.REVIEWER, answer([]))
        stamped = stamp.read_stamp(self.cfg, card_id)
        mine, theirs = self.roots(worktree, other)
        self.assertEqual(stamped["heads"], {mine: sh(worktree, "git", "rev-parse", "HEAD"),
                                            theirs: sh(other, "git", "rev-parse", "HEAD")})
        self.covered(card_id, worktree)

    def test_a_commit_in_the_second_repo_alone_uncovers_it(self):
        card_id, worktree, other, card_dir = self.two_worktrees()
        prep.prepare(card_dir, "main", [worktree, other])
        self.finished(card_id, worktree, agents.REVIEWER, answer([]))
        (other / "side.txt").write_text("changed after the review\n")
        sh(other, *GIT, "commit", "-q", "-am", "unreviewed")
        self.not_covered(card_id, worktree)

    def test_a_clean_rebase_of_the_second_repo_still_covers(self):
        card_id, worktree, other, card_dir = self.two_worktrees()
        prep.prepare(card_dir, "main", [worktree, other])
        self.finished(card_id, worktree, agents.REVIEWER, answer([]))
        (self.other_repo / "base.txt").write_text("main moves on\n")
        sh(self.other_repo, *GIT, "add", "base.txt")
        sh(self.other_repo, *GIT, "commit", "-q", "-m", "main moves on")
        sh(other, *GIT, "rebase", "-q", "main")
        self.covered(card_id, worktree)

    def test_a_commit_after_prep_is_not_stamped_as_reviewed(self):
        card_id, worktree = self.at_review()
        card_dir = self.cfg.card_dir(card_id)
        prep.prepare(card_dir, "main", [worktree])
        prepped = sh(worktree, "git", "rev-parse", "HEAD")
        self.fix(worktree)
        self.finished(card_id, worktree, agents.REVIEWER, answer([]))
        self.assertEqual(self.stamped_head(card_id), prepped)
        self.not_covered(card_id, worktree)

    def test_an_old_single_head_stamp_covers_its_one_repo(self):
        card_id, worktree = self.at_review()
        head = sh(worktree, "git", "rev-parse", "HEAD")
        self.cfg.card_dir(card_id).mkdir(parents=True, exist_ok=True)
        stamp.stamp_path(self.cfg, card_id).write_text(json.dumps(
            {"head": head, "round": 1, "base": "main", "patch_id": None}))
        self.covered(card_id, worktree)
        self.assertTrue(gate.covers(stamp.read_stamp(self.cfg, card_id),
                                    {self.roots(worktree)[0]: head}))

    def test_an_old_single_head_stamp_does_not_cover_a_second_repo(self):
        card_id, worktree, other, _ = self.two_worktrees()
        self.cfg.card_dir(card_id).mkdir(parents=True, exist_ok=True)
        stamp.stamp_path(self.cfg, card_id).write_text(json.dumps(
            {"head": sh(worktree, "git", "rev-parse", "HEAD"), "round": 1, "base": "main"}))
        self.not_covered(card_id, worktree)

    def test_a_pass_opened_before_the_upgrade_still_covers_its_one_repo(self):
        """A pass recorded by the old code (one `head`, no `heads`), verified by the new."""
        card_id, worktree = self.at_review()
        card_dir = self.cfg.card_dir(card_id)
        prep.prepare(card_dir, "main", [worktree])
        self.finished(card_id, worktree, agents.REVIEWER, answer([MEDIUM]))
        rounds = stamp.read_rounds(card_dir)
        for key in ("heads", "patch_ids", "bases"):
            rounds[-1].pop(key)
        stamp.save_rounds(card_dir, rounds)
        self.finished(card_id, worktree, agents.VERIFIER,
                      answer([{"id": "r1.F1", "verify": "kept", "reason": "it holds"}]))
        self.assertEqual(stamp.read_stamp(self.cfg, card_id)["heads"], {})
        self.covered(card_id, worktree)

    def test_a_two_worktree_fix_check_moves_both_heads(self):
        card_id, worktree, other, card_dir = self.two_worktrees()
        prep.prepare(card_dir, "main", [worktree, other])
        self.finished(card_id, worktree, agents.REVIEWER, answer([MEDIUM]))
        self.finished(card_id, worktree, agents.VERIFIER,
                      answer([{"id": "r1.F1", "verify": "kept", "reason": "it holds"}]))
        prep.answer(card_dir, "r1.F1", "fixed", "")
        (other / "side.txt").write_text("the other half, guarded\n")
        sh(other, *GIT, "commit", "-q", "-am", "fix r1.F1")
        self.not_covered(card_id, worktree)
        self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="b @ 1")
        prep.prepare(card_dir, "main", [worktree, other], since=prep.FROM_STAMP)
        self.finished(card_id, worktree, agents.VERIFIER, answer([{"id": "r1.F1", "fixed": True}]),
                      trip_rounds=1)
        mine, theirs = self.roots(worktree, other)
        self.assertEqual(stamp.read_stamp(self.cfg, card_id)["heads"],
                         {mine: sh(worktree, "git", "rev-parse", "HEAD"),
                          theirs: sh(other, "git", "rev-parse", "HEAD")})
        self.covered(card_id, worktree)

    def test_a_bare_since_takes_each_worktree_s_head_from_the_stamp(self):
        card_id, worktree, other, card_dir = self.two_worktrees()
        prep.prepare(card_dir, "main", [worktree, other])
        self.finished(card_id, worktree, agents.REVIEWER, answer([]))
        mine, theirs = self.roots(worktree, other)
        before = stamp.read_stamp(self.cfg, card_id)["heads"]
        (other / "side.txt").write_text("a fix\n")
        sh(other, *GIT, "commit", "-q", "-am", "a fix")
        prep.prepare(card_dir, "main", [worktree, other], since=prep.FROM_STAMP)
        prepped = json.loads((card_dir / stamp.PREP_FILE).read_text())
        self.assertEqual(prepped["sinces"], before)
        since = (card_dir / prep.SINCE_FILE).read_text()
        self.assertIn("+a fix", since)
        self.assertIn(theirs, since)
        self.assertNotIn(f"({mine},", since)

    def test_a_given_sha_is_used_where_it_resolves_and_the_stamp_elsewhere(self):
        card_id, worktree, other, card_dir = self.two_worktrees()
        prep.prepare(card_dir, "main", [worktree, other])
        self.finished(card_id, worktree, agents.REVIEWER, answer([]))
        mine, theirs = self.roots(worktree, other)
        first = sh(worktree, "git", "rev-parse", "HEAD")     # a commit only this repo has
        prep.prepare(card_dir, "main", [worktree, other], since=first)
        sinces = json.loads((card_dir / stamp.PREP_FILE).read_text())["sinces"]
        self.assertEqual(sinces[mine], first)
        self.assertEqual(sinces[theirs], stamp.read_stamp(self.cfg, card_id)["heads"][theirs])

    def test_a_since_with_no_reviewed_head_is_refused(self):
        card_id, worktree, other, card_dir = self.two_worktrees()
        with self.assertRaises(prep.PrepError) as caught:
            prep.prepare(card_dir, "main", [worktree, other], since=prep.FROM_STAMP)
        self.assertIn("full prep", str(caught.exception))

    def test_the_cli_takes_a_bare_since(self):
        args = prep.parser().parse_args(["prep", "--dir", "d", "--base", "main", "--since"])
        self.assertEqual(args.since, prep.FROM_STAMP)


class StageHeadsTest(HeadsCase):
    def stage_check(self, card_id):
        stage_check(self.board, self.cfg, card_id)

    def test_stage_review_refuses_a_stamp_missing_a_head(self):
        card_id, worktree, other, card_dir = self.two_worktrees()
        prep.prepare(card_dir, "main", [worktree])
        self.finished(card_id, worktree, agents.REVIEWER, answer([]))
        with self.assertRaises(Refused) as caught:
            self.stage_check(card_id)
        said = str(caught.exception)
        self.assertIn("has no head for " + self.roots(other)[0], said)
        self.assertIn(f"--worktree {self.roots(other)[0]}", said)
        prep.prepare(card_dir, "main", [worktree, other])
        self.finished(card_id, worktree, agents.REVIEWER, answer([]))
        self.stage_check(card_id)

    def test_stage_review_refuses_a_prepared_card_with_no_stamp(self):
        card_id, worktree = self.at_review()
        prep.prepare(self.cfg.card_dir(card_id), "main", [worktree])
        with self.assertRaises(Refused) as caught:
            self.stage_check(card_id)
        self.assertIn("there is no review stamp", str(caught.exception))
