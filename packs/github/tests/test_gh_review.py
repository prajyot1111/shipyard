"""Review cards on GitHub (c-730): `review scan`, `review <id> poll`, the read-only house a
review card gets, and the review your Approve posts. gh is the stand-in on PATH, so each
call asserted here is the one a real gh would be given; git is real, in a temporary
directory whose bare origin plays GitHub, `refs/pull/<n>/head` included.
"""

import contextlib
import io
import json
import os
import subprocess
import unittest
from unittest import mock

from ghfake import TAPPED, GhCase, answer, git

import gh_layer
from gh_cli import GithubError
from keel.packkit import brief as gh_brief
from keel.packkit import card as gh_card
from keel.packkit import cut as gh_cut
from keel.packkit import pulls as gh_pulls
from keel.packkit import review as gh_review
from keel.packkit import verbs as gh_main

REPO = "github.com/octo/api"
LIST = ["pr", "list", "-R", REPO, "--search", "review-requested:@me", "--state", "open", "--json",
        gh_layer.LIST_FIELDS, "--limit", "100"]
REVIEWS = "repos/octo/api/pulls/12/reviews"


def asked(number: int = 12, head: str = "f00d", fork: bool = False) -> dict:
    """One pull request as `gh pr list --json` answers it."""
    return {"number": number, "title": "Faster loader", "body": "It reads the file once.",
            "author": {"login": "ana", "name": "Ana", "is_bot": False}, "createdAt": "2026-10-01T10:00:00Z",
            "updatedAt": "2026-10-02T09:00:00Z", "url": f"https://github.com/octo/api/pull/{number}",
            "headRefName": "ana/faster-loader", "headRefOid": head, "baseRefName": "main",
            "isCrossRepository": fork, "isDraft": False}


def viewed(state: str = "OPEN", head: str = "f00d") -> dict:
    return {"number": 12, "url": "https://github.com/octo/api/pull/12", "isDraft": False, "title": "Faster loader",
            "state": state, "headRefOid": head, "headRefName": "ana/faster-loader", "baseRefName": "main",
            "isCrossRepository": True}


class ReviewCase(GhCase):
    def setUp(self):
        super().setUp()
        self.patch(mock.patch.dict(os.environ, {"KEEL_SPACE": "code"}))
        self.cfg.spaces["code"].review_scan = True

    def review_card(self, **over) -> dict:
        """A card as the drain files it (`reviewcards.card_options`)."""
        options = {"kind": "review", "review_key": "api:12", "slot": "review", "pr": 12,
                   "branch": "ana/faster-loader", "base": "main", "tracker_mode": "none"}
        base = {"id": "c-50", "title": "Review: Faster loader", "stage": "assigned"}
        return self.card(**{**base, **over, "options": {**options, **over.get("options", {})}})

    def pull_head(self, number: int = 12) -> str:
        """A colleague's commit, published by the origin only as `refs/pull/<n>/head`, as
        GitHub publishes every pull request's head (a fork's too)."""
        other = self.dir / "colleague"
        if not other.exists():
            subprocess.run(["git", "clone", "-q", str(self.dir / "origin" / "api.git"), str(other)], check=True)
        git(other, "checkout", "-q", "-B", "work", "origin/main")
        self.commit(other, f"pr-{number}-{len(list(other.iterdir()))}.txt")
        git(other, "push", "-q", "origin", f"+HEAD:refs/pull/{number}/head")
        return git(other, "rev-parse", "HEAD")

    def verb(self, name: str, *argv: str, card: dict, stdin: str = "") -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(gh_card, "load_card", lambda card_id: card), \
                mock.patch("sys.stdin", io.StringIO(stdin)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gh_main.run(name, list(argv))
        return code, out.getvalue(), err.getvalue()


class ScanTest(ReviewCase):
    def test_a_pull_request_that_asks_for_your_review_is_a_row_in_the_engine_s_words(self):
        self.gh(answer("pr", "list", "review-requested:@me", out=[asked(), asked(14, "beef", fork=True)]))
        found = gh_review.scan()
        self.assertEqual(self.calls(), [LIST])
        self.assertEqual(found["open_groups"], {})
        self.assertEqual(found["prs"][0], {
            "key": "api:12", "repo": "api", "pr": 12, "title": "Faster loader", "author": "ana",
            "description": "It reads the file once.", "created": "2026-10-01T10:00:00Z",
            "updated": "2026-10-02T09:00:00Z", "head": "f00d", "branch": "ana/faster-loader", "base": "main",
            "url": "https://github.com/octo/api/pull/12", "group": None, "fork": False})
        # r1.F1: a fork's is a row too, marked, so the drain never starts it by itself
        self.assertEqual((found["prs"][1]["key"], found["prs"][1]["fork"]), ("api:14", True))

    def test_only_the_space_s_github_repos_are_asked_and_the_space_is_the_one_keel_names(self):
        elsewhere = self.dir / "repos" / "elsewhere"
        subprocess.run(["git", "init", "-q", str(elsewhere)], check=True)
        git(elsewhere, "remote", "add", "origin", "https://gitlab.example/octo/elsewhere.git")
        self.cfg.spaces["code"].repos["elsewhere"] = elsewhere
        self.gh(answer("pr", "list", "review-requested:@me", out=[]))
        self.assertEqual(gh_review.scan(), {"prs": [], "open_groups": {}})
        self.assertEqual(self.calls(), [LIST])
        with mock.patch.dict(os.environ, {"KEEL_SPACE": "personal"}), self.assertRaises(GithubError) as said:
            gh_review.scan()
        self.assertIn("not on this pack", str(said.exception))

    def test_one_repo_that_cannot_be_asked_is_skipped_with_a_line_and_the_rest_are_scanned(self):
        """r1.F3: a failing repo does not cost the space's other review cards their pass; a
        scan where every repo fails is still a failure, never an empty list."""
        self.cfg.spaces["code"].repos["web"] = self.make_repo("web")
        self.gh(answer("pr", "list", "github.com/octo/web", code=1, err="HTTP 403: rate limit exceeded\n"),
                answer("pr", "list", "review-requested:@me", out=[asked()]))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            found = gh_review.scan()
        self.assertEqual([row["key"] for row in found["prs"]], ["api:12"])
        self.assertIn("web was not scanned", err.getvalue())
        self.assertIn("rate limit exceeded", err.getvalue())
        self.gh(answer("pr", "list", code=1, err="HTTP 403: rate limit exceeded\n"))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(GithubError):
            gh_review.scan()

    def test_poll_says_where_one_card_s_pull_request_stands_and_never_guesses_open(self):
        self.gh(answer("pr", "view", out=viewed("MERGED", "c0de")))
        self.assertEqual(gh_review.poll(self.review_card()),
                         {"state": "merged", "head": "c0de", "url": "https://github.com/octo/api/pull/12"})
        self.gh(answer("pr", "view", out=viewed("WEIRD")))
        with self.assertRaises(GithubError):
            gh_review.poll(self.review_card())


class HouseTest(ReviewCase):
    def test_the_house_is_a_checkout_detached_at_the_pull_request_s_head_and_moves_on_a_rereview(self):
        head = self.pull_head()
        self.gh(answer("pr", "view", out=viewed(head=head)))
        (tree,) = gh_cut.worktrees_for(self.review_card())
        self.assertEqual(git(tree, "rev-parse", "HEAD"), head)
        self.assertEqual(git(tree, "rev-parse", "--abbrev-ref", "HEAD"), "HEAD")      # detached: no branch
        self.assertNotIn("ana/faster-loader", git(self.repo, "branch", "--list"))
        self.assertEqual(self.kb.options, [("c-50", "worktree", str(tree)), ("c-50", "review_head", head)])
        newer = self.pull_head()
        self.gh(answer("pr", "view", out=viewed(head=newer)))
        card = self.review_card(options={"worktree": str(tree), "review_head": head})
        self.assertEqual(gh_cut.worktrees_for(card), [tree])
        self.assertEqual(git(tree, "rev-parse", "HEAD"), newer)

    def test_the_brief_is_the_read_only_house_and_the_review_ending(self):
        tree = str(self.cfg.worktrees_dir / "c-50")
        card = self.review_card(options={"review_pr": {"url": "https://github.com/octo/api/pull/12"}})
        text = gh_brief.compose(card, [tree])
        for said in ("pull request #12", "`ana/faster-loader` into `main`", tree, "Never edit, commit or push",
                     "kind: review", "kb stage c-50 review --plan", "--output https://github.com/octo/api/pull/12"):
            self.assertIn(said, text)
        self.assertNotIn("--draft", text)

    def test_a_fork_s_brief_says_its_code_is_read_and_never_run(self):
        """c-730 r2.F3: the house of a fork's pull request is confined; its brief says so and
        does not offer it gh, which its fence refuses."""
        tree = str(self.cfg.worktrees_dir / "c-50")
        text = gh_brief.compose(self.review_card(options={"review_fork": True}), [tree])
        self.assertIn("comes from a fork", text)
        self.assertIn("Read it, and never run any of it", text)
        self.assertNotIn("gh pr diff", text)
        self.assertIn("gh pr diff", gh_brief.compose(self.review_card(), [tree]))

    def test_a_review_card_opens_readies_and_publishes_no_pull_request_of_its_own(self):
        card = self.review_card(stage="review")
        self.assertIsNone(gh_pulls.missing(card))
        self.assertIsNone(gh_pulls.unpublished(card))
        code, _, err = self.verb("pr", "c-50", "--draft", card=card)
        self.assertEqual(code, 1)
        self.assertIn("review card", err)
        code, _, err = self.verb("pr", "c-50", "--ready", card=card)     # refused to every card (c-738 r1.F2)
        self.assertEqual(code, 1)
        self.assertIn("Approve outcome", err)
        code, _, err = self.verb("publish", "c-50", card=self.tapped(card))
        self.assertEqual(code, 1)
        self.assertIn("the review you kept", err)
        # c-738 r1.F3: its house runs no publish at all, a review handed or not
        code, _, err = self.verb("publish", "c-50", "--answer", card=card, stdin=json.dumps(ANSWER))
        self.assertEqual((code, "inside your Approve outcome or your Ship" in err), (1, True))
        self.assertEqual(self.calls(), [])


ANSWER = {"review": {"round": 1, "head": "f00d", "verdict": "changes", "severity": "high",
                     "summary": "Two things before this lands.",
                     "comments": [{"row": "f1", "path": "loader.py", "line": 7, "text": "This reads twice."},
                                  {"row": "f2", "path": "cache.py", "line": 3, "text": "Unbounded."}],
                     "ledger": [{"row": "f1"}]}}
MARK = "<!-- keel:review c-50 round 1 -->"


class PostTest(ReviewCase):
    def plan(self, *rules):
        self.gh(*rules, answer("pr", "view", out=viewed()), answer("api", "user", out="me\n"))

    def publish(self, answer_=ANSWER) -> tuple[int, str, str]:
        return self.verb("publish", "c-50", "--answer", card=self.tapped(self.review_card(stage="review")),
                         stdin=json.dumps(answer_))

    def test_approve_posts_one_review_with_the_findings_inline_the_summary_and_the_verdict(self):
        self.plan(answer("api", REVIEWS, "POST",
                         out={"id": 901, "html_url": "https://github.com/octo/api/pull/12#pullrequestreview-901"}),
                  answer("api", REVIEWS, out=[]))
        code, out, err = self.publish()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out), {"published": "review", "pr": 12, "comments": 2, "verdict": "changes"})
        posts = [one for one in self.records() if "POST" in one["argv"]]
        self.assertEqual([one["argv"] for one in posts], [
            ["api", "--hostname", "github.com", "--method", "POST", REVIEWS, "--input", "-"]])
        sent = json.loads(posts[0]["stdin"])
        self.assertEqual(sent, {"body": f"Two things before this lands.\n\n{MARK}", "event": "REQUEST_CHANGES",
                                "commit_id": "f00d", "comments": [
                                    {"path": "loader.py", "line": 7, "side": "RIGHT", "body": "This reads twice."},
                                    {"path": "cache.py", "line": 3, "side": "RIGHT", "body": "Unbounded."}]})
        posted = dict((key, value) for _, key, value in self.kb.options)["review_posted"]
        self.assertEqual({key: posted[key] for key in ("head", "round", "verdict", "severity", "review")},
                         {"head": "f00d", "round": 1, "verdict": "changes", "severity": "high", "review": 901})
        self.assertEqual(posted["ledger"], [{"row": "f1"}])

    def test_a_retry_finds_the_review_that_landed_and_posts_nothing_twice(self):
        landed = [{"id": 901, "user": {"login": "me"}, "body": f"Two things.\n\n{MARK}", "state": "CHANGES_REQUESTED"},
                  {"id": 5, "user": {"login": "ana"}, "body": MARK}]       # someone else's copy of the words is not ours
        self.plan(answer("api", REVIEWS, out=landed))
        code, _, err = self.publish()
        self.assertEqual((code, err), (0, ""))
        self.assertFalse([one for one in self.records() if "POST" in one["argv"]])
        self.assertEqual(dict((key, value) for _, key, value in self.kb.options)["review_posted"]["review"], 901)

    def test_a_finding_github_will_not_put_on_its_line_goes_into_the_summary_instead(self):
        self.plan(answer("api", REVIEWS, "POST", err="gh: Unprocessable Entity (HTTP 422)\n", code=1, times=1),
                  answer("api", REVIEWS, "POST", out={"id": 902}), answer("api", REVIEWS, out=[]))
        code, _, err = self.publish()
        self.assertEqual((code, err), (0, ""))
        posts = [json.loads(one["stdin"]) for one in self.records() if "POST" in one["argv"]]
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[1]["comments"], [])
        self.assertIn("**`loader.py:7`**\n\nThis reads twice.", posts[1]["body"])
        self.assertTrue(posts[1]["body"].endswith(MARK))

    def test_a_review_that_landed_is_recorded_even_on_a_pull_request_merged_since(self):
        """r1.F4: the post landed, its record did not, and the pull request was merged before
        the retry: the retry records what landed and posts nothing."""
        landed = [{"id": 901, "user": {"login": "me"}, "body": f"Two things.\n\n{MARK}"}]
        self.gh(answer("pr", "view", out=viewed("MERGED")), answer("api", "user", out="me\n"),
                answer("api", REVIEWS, out=landed))
        code, _, err = self.publish()
        self.assertEqual((code, err), (0, ""))
        self.assertFalse([one for one in self.records() if "POST" in one["argv"]])
        self.assertEqual(dict((key, value) for _, key, value in self.kb.options)["review_posted"]["review"], 901)

    def test_a_post_github_refuses_for_another_reason_is_said_and_not_tried_again(self):
        """r1.F7 (1): only GitHub's refusal of a line folds the findings; any other failure
        is said, once, and nothing more is posted or recorded."""
        self.plan(answer("api", REVIEWS, "POST", err="gh: Server Error (HTTP 502)\n", code=1),
                  answer("api", REVIEWS, out=[]))
        code, _, err = self.publish()
        self.assertEqual(code, 1)
        self.assertIn("HTTP 502", err)
        self.assertEqual(len([one for one in self.records() if "POST" in one["argv"]]), 1)
        self.assertNotIn("review_posted", [key for _, key, _ in self.kb.options])

    def test_a_refused_line_with_no_finding_on_a_line_is_not_posted_twice(self):
        """r1.F7 (2): a 422 on a review that put nothing on a line has nothing to fold."""
        general = {"review": dict(ANSWER["review"], comments=[{"row": "f1", "text": "Overall fine."}])}
        self.plan(answer("api", REVIEWS, "POST", err="gh: Unprocessable Entity (HTTP 422)\n", code=1),
                  answer("api", REVIEWS, out=[]))
        code, _, err = self.publish(general)
        self.assertEqual(code, 1)
        self.assertIn("HTTP 422", err)
        self.assertEqual(len([one for one in self.records() if "POST" in one["argv"]]), 1)

    def test_nothing_is_posted_on_a_pull_request_that_is_no_longer_open(self):
        self.gh(answer("pr", "view", out=viewed("CLOSED")), answer("api", "user", out="me\n"),
                answer("api", REVIEWS, out=[]))          # nothing of this round landed
        code, _, err = self.publish()
        self.assertEqual(code, 1)
        self.assertIn("is declined, so no review was posted", err)
        self.assertFalse([one for one in self.records() if "POST" in one["argv"]])


if __name__ == "__main__":
    unittest.main()
