"""Twins (2026-09-25, reshaped by c-559 on 2026-09-27, `keel/review/twins.py`): a story's
change raised on two bases of one repo is reviewed ONCE, on the member the adapter says the
twin follows (`twin_of`); the twin stays a member, gets no finding and no verdict, is named in
the orientation, and his Approve gives it one pointer comment and the same verdict.

Every pull request, story and repo here is invented.
"""

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from keel import adapters, planformat, planreview, reviewfeature
from keel.board import Board
from keel.review import ledger, prep, stamp, twins
from tests.helpers import make_config, make_repo

GIT = ("git", "-c", "user.name=t", "-c", "user.email=t@x")
LINES = [f"line {n}\n" for n in range(1, 21)]


def sh(cwd, *args):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


def commit(repo, message):
    sh(repo, *GIT, "add", "-A")
    sh(repo, *GIT, "commit", "-q", "-m", message)


class TwinReposCase(unittest.TestCase):
    """One repo with two bases (the other base has three more lines at the top) and the same
    fix on each, checked out in two worktrees, plus a second repo's member."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        api = make_repo(self.dir / "api")
        (api / "app.py").write_text("".join(LINES))
        commit(api, "the file")
        sh(api, "git", "branch", "develop")
        sh(api, "git", "checkout", "-q", "-b", "trunk")
        (api / "app.py").write_text("# a\n# b\n# c\n" + "".join(LINES))
        commit(api, "trunk has more at the top")
        self.trees = {}
        for label, base in (("api#4144", "develop"), ("api#4143", "trunk")):
            tree = self.dir / label.replace("#", "-")
            sh(api, "git", "worktree", "add", "-q", "-b", f"fix-{base}", str(tree), base)
            path = tree / "app.py"
            path.write_text(path.read_text().replace("line 12\n", "line 12, now refused\n"))
            commit(tree, "the fix")
            self.trees[label] = tree
        web = make_repo(self.dir / "web")
        sh(web, "git", "checkout", "-q", "-b", "fix")
        (web / "Toast.js").write_text("const toast = 1;\n")
        commit(web, "the other side")
        self.trees["web#2200"] = web
        self.card_dir = self.dir / "card"

    def members(self):
        return [("api#4143", str(self.trees["api#4143"]), "trunk"),
                ("api#4144", str(self.trees["api#4144"]), "develop"),
                ("web#2200", str(self.trees["web#2200"]), "main")]

    def argv(self, *twin_flags):
        argv = ["prep", "--dir", str(self.card_dir), "--base", "develop"]
        for label, tree, base in self.members():
            argv += ["--member", label, tree, base]
        for pair in twin_flags:
            argv += ["--twin", *pair]
        return argv


class PrepTest(TwinReposCase):
    def test_the_twin_the_brief_names_is_left_out_whatever_the_card_s_base(self):
        # the card's base is develop, the twin's: the member reviewed is the one named
        done = prep.prepare(self.card_dir, "develop", [], members=self.members(),
                            twin_flags=[("api#4144", "api#4143")])
        diff = (self.card_dir / stamp.DIFF_FILE).read_text()
        self.assertIn("member api#4143, twin api#4144 (the same change on develop: not reviewed", diff)
        self.assertNotIn("member api#4144", diff)
        self.assertEqual(diff.count("now refused"), 1)
        self.assertIn("member web#2200", diff)
        self.assertEqual(done["twins"], {"api#4144": "api#4143"})
        self.assertEqual(twins.read(self.card_dir)["api#4144"], {"primary": "api#4143", "base": "develop"})

    def test_with_no_twin_named_both_are_reviewed_even_when_the_change_is_the_same(self):
        # who is a twin is the adapter's to say, never prep's by content
        done = prep.prepare(self.card_dir, "develop", [], members=self.members())
        diff = (self.card_dir / stamp.DIFF_FILE).read_text()
        self.assertEqual(done["twins"], {})
        self.assertFalse((self.card_dir / twins.TWINS_FILE).exists())
        self.assertIn("member api#4143", diff)
        self.assertIn("member api#4144", diff)

    def test_a_twin_flag_that_does_not_hold_is_refused(self):
        for pair, said in ((("api#4144", "api#9"), "both must be members"),
                           (("api#4144", "api#4144"), "names itself"),
                           (("web#2200", "api#4143"), "same repo")):
            with self.subTest(pair=pair), self.assertRaises(prep.PrepError) as caught:
                prep.prepare(self.card_dir, "develop", [], members=self.members(), twin_flags=[pair])
            self.assertIn(said, str(caught.exception))

    def test_the_command_tells_the_house_which_one_to_leave_alone(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(prep.main(self.argv(("api#4144", "api#4143"))), 0)
        self.assertIn("api#4144 is the twin of api#4143: review api#4143 only", out.getvalue())
        self.assertIn("name it in the orientation as api#4143's twin", out.getvalue())

    def test_the_lint_is_handed_the_twins_and_the_members_without_them(self):
        prep.prepare(self.card_dir, "develop", [], members=self.members(), twin_flags=[("api#4144", "api#4143")])
        options = {"review_members": [{"label": label} for label, _, _ in self.members()]}
        found = ledger.context({"id": "c-901", "options": options}, self.card_dir, None)
        self.assertEqual(found["members"], ["api#4143", "web#2200"])
        self.assertEqual(found["twins"], {"api#4144": "api#4143"})


class MemberTest(unittest.TestCase):
    ROWS = [{"key": "api:4143", "repo": "api", "pr": 4143, "head": "aaa", "group": "st-1"},
            {"key": "api:4144", "repo": "api", "pr": 4144, "head": "bbb", "group": "st-1",
             "twin_of": "api#4143"}]

    def test_twin_of_rides_on_the_member_and_only_when_said(self):
        members = {m["label"]: m for m in reviewfeature.members_of(self.ROWS)}
        self.assertEqual(members["api#4144"]["twin_of"], "api#4143")
        self.assertNotIn("twin_of", members["api#4143"])

    def test_a_push_on_the_twin_is_still_a_new_head(self):
        before = reviewfeature.composite_head(reviewfeature.members_of(self.ROWS))
        moved = [dict(self.ROWS[0]), dict(self.ROWS[1], head="ccc")]
        self.assertNotEqual(reviewfeature.composite_head(reviewfeature.members_of(moved)), before)
        self.assertIn("api#4144@ccc", reviewfeature.composite_head(reviewfeature.members_of(moved)))


SAMPLE = (Path(__file__).parent / "fixtures" / "review-feature-sample.md").read_text()
NAMED = "api#4149 is the twin of api#4150: the same change, reviewed there."
WITH_TWIN = SAMPLE.replace("path runs across both repos.\n", f"path runs across both repos.\n\n{NAMED}\n")


class LintTest(unittest.TestCase):
    MEMBERS = ["api#4150", "web#2200"]
    TWINS = {"api#4149": "api#4150"}

    def c32(self, text):
        doc = planformat.parse(text, "context.md")
        review = {"members": self.MEMBERS, "twins": self.TWINS}
        return [one["text"] for one in planreview.rules(doc, review) if one["rule"] == "C32"]

    def test_the_orientation_names_the_twin_with_its_member(self):
        self.assertEqual(self.c32(WITH_TWIN), [])
        [said] = self.c32(SAMPLE)
        self.assertIn("does not name api#4149 as the twin of api#4150", said)

    def test_a_finding_on_the_twin_is_refused_with_the_member_to_use(self):
        text = WITH_TWIN.replace("member: web#2200\nat: src/Details.js:12", "member: api#4149\nat: app/x.py:1")
        [said] = self.c32(text)
        self.assertIn("names api#4149, the twin of api#4150: a twin is not reviewed, so put it on api#4150", said)

    def test_a_verdict_for_the_twin_is_refused(self):
        verdict = WITH_TWIN[WITH_TWIN.index("```decision verdict-api-4150"):]
        verdict = verdict[:verdict.index("```\n", 4) + 4]
        text = WITH_TWIN + "\n" + verdict.replace("verdict-api-4150", "verdict-api-4149")
        [said] = self.c32(text)
        self.assertIn("verdict-api-4149 is a twin's verdict", said)


def script(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


class ApproveTest(unittest.TestCase):
    """His Approve: the twin gets no inline comment, one pointer to the reviewed member's
    pull request, and that member's verdict; the reviewed ones as before."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        work = self.cfg.adapters_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        self.answers = self.dir / "answers.log"
        script(work / "publish", f'if [ "$2" = "--answer" ]; then cat >> {self.answers}; echo >> {self.answers}; fi\n'
                                 f'echo \'{{"published": "review"}}\'\n')
        members = [{"label": "api#4149", "repo": "api", "pr": 4149, "head": "ccc333", "base": "develop",
                    "twin_of": "api#4150"},
                   {"label": "api#4150", "repo": "api", "pr": 4150, "head": "aaa111", "base": "trunk",
                    "url": "https://host.invalid/api/4150"},
                   {"label": "web#2200", "repo": "web", "pr": 2200, "head": "bbb222", "base": "main"}]
        options = {"review_key": "feature:st-41001", "kind": "review", "slot": "review", "review_group": "st-41001",
                   "review_members": members, "review_head": "h"}
        self.card = self.board.create("work", "Review: st-41001", repo="api,web", actor="drain",
                                      options=options)
        self.board.stage(self.card, "assigned", "human")
        self.board.stage(self.card, "building", "drain")
        self.board.stage(self.card, "review", "house", plan_ref="p.md", output_ref="https://example.invalid/pr")
        card_dir = self.cfg.card_dir(self.card)
        card_dir.mkdir(parents=True, exist_ok=True)
        (card_dir / "context.md").write_text(WITH_TWIN)
        stamp.save_rounds(card_dir, [{"round": 1, "head": "aaa111", "complete": True, "findings": []}])
        twins.write(card_dir, {"api#4149": {"primary": "api#4150", "base": "develop"}})

    def test_the_twin_gets_a_pointer_and_the_same_verdict_and_no_comment(self):
        self.board.approve(self.card, "outcome", "human", publish=adapters.publisher(self.cfg, "work"))
        review = json.loads(self.answers.read_text().splitlines()[-1])["review"]
        members = {m["member"]: m for m in review["members"]}
        twin, followed = members["api#4149"], members["api#4150"]
        self.assertEqual(twin["comments"], [])
        self.assertTrue(followed["comments"])
        self.assertEqual((twin["verdict"], twin["twin_of"], twin["pr"]), (followed["verdict"], "api#4150", 4149))
        self.assertIn("The same change as api#4150 (https://host.invalid/api/4150)", twin["pointer"])
        self.assertNotIn("\n", twin["pointer"])
        self.assertIn("api#4149: the twin of api#4150 (the same change on another base), reviewed there",
                      review["summary"])
        self.assertEqual([m["member"] for m in review["members"]], ["api#4149", "api#4150", "web#2200"])

    def test_a_twin_whose_member_left_before_approve_refuses_and_posts_nothing(self):
        card = self.board.get(self.card)
        kept = [m for m in card["options"]["review_members"] if m["label"] != "api#4150"]
        self.board.set_fields(self.card, {"options": {"review_members": kept}}, "drain")
        with self.assertRaises(Exception) as caught:
            self.board.approve(self.card, "outcome", "human", publish=adapters.publisher(self.cfg, "work"))
        self.assertIn("api#4149 (twin of api#4150)", str(caught.exception))
        self.assertFalse(self.answers.exists())
        self.assertEqual(self.board.get(self.card)["stage"], "review")


if __name__ == "__main__":
    unittest.main()
