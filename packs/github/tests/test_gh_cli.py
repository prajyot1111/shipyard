"""The seam to gh: a failure is one sentence, every call has a clock and never prompts,
and nothing here asks gh for the credential behind its sign-in.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from ghfake import SLUG, TAPPED, GhCase, answer, git

import gh_cli
import gh_layer as gh_host
from keel.packkit import card as gh_card
from keel.packkit import cli as kit_cli
from keel.packkit import verbs as gh_main

LOUD = ("\x1b[31mX\x1b[0m Pull request octo/api#12 could not be read\n"
        "\n"
        "Usage:  gh pr view [<number> | <url> | <branch>] [flags]\n"
        "Flags:\n  --json fields\n")


class FailureTest(GhCase):
    def said(self, verb: str, *argv: str) -> str:
        """What a verb prints on stderr when it cannot finish; it must also exit 1."""
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gh_main.run(verb, list(argv)), 1)
        return err.getvalue()

    def shipping_card(self):
        card = self.card(stage="shipping", options={"pr": 12, "branch": "keel/c-41-tidy"})
        self.patch(mock.patch.object(gh_card, "load_card", lambda card_id: card))

    def test_a_gh_error_is_one_sentence_of_its_own_words_and_never_a_traceback(self):
        self.shipping_card()
        self.gh(answer("pr", "view", code=1, err=LOUD))
        self.assertEqual(self.said("ship", "c-41", "poll"),
                         "ship: gh pr view failed: Pull request octo/api#12 could not be read\n")

    def test_gh_missing_is_said(self):
        self.shipping_card()
        self.assertEqual(self.said("ship", "c-41", "poll"),
                         "ship: gh, GitHub's command line tool, is not installed on this machine, "
                         "so nothing can be asked of GitHub\n")

    def test_gh_not_signed_in_is_said_with_the_way_back(self):
        self.shipping_card()
        self.gh(answer("pr", "view", code=4, err="To get started with GitHub CLI, please run:  gh auth login\n"))
        self.assertEqual(self.said("ship", "c-41", "poll"),
                         "ship: gh is not signed in to GitHub: run `gh auth login` in a terminal, "
                         "then try again\n")

    def test_a_gh_that_does_not_answer_in_time_is_said(self):
        self.shipping_card()
        self.gh()
        real = subprocess.run

        def hangs(argv, **kwargs):
            if argv[0] == "gh":
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
            return real(argv, **kwargs)

        with mock.patch.object(kit_cli.subprocess, "run", side_effect=hangs):
            said = self.said("ship", "c-41", "poll")
        self.assertEqual(said, "ship: gh pr view gave no answer in 30 seconds: GitHub may be slow or "
                               "out of reach, so try again\n")

    def test_an_answer_that_is_not_json_is_said(self):
        self.shipping_card()
        self.gh(answer("pr", "view", out="<html>503</html>"))
        self.assertEqual(self.said("ship", "c-41", "poll"),
                         "ship: gh pr view answered something that is not JSON\n")

    def test_anything_unforeseen_is_still_one_line(self):
        with mock.patch.object(gh_card, "load_card", side_effect=RuntimeError("boom\nsecond line")):
            said = self.said("ship", "c-41", "poll")
        self.assertEqual(said, "ship: stopped on RuntimeError: boom second line\n")


class EveryCallTest(GhCase):
    def test_every_call_has_a_clock_never_prompts_and_is_given_no_terminal(self):
        seen = []

        def record(argv, **kwargs):
            seen.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")

        with mock.patch.object(kit_cli.subprocess, "run", side_effect=record):
            gh_host.find_open(SLUG, "b")
            gh_host.mine(SLUG)
            gh_host.issue_comments(SLUG, 12)
            gh_host.review_comments(SLUG, 12)
            gh_host.reviews(SLUG, 12)
            gh_host.set_ready(SLUG, 12)
            gh_host.set_body(SLUG, 12, "body")
            gh_host.comment(SLUG, 12, "text")
            gh_host.reply(SLUG, 12, 201, "text")
            gh_host.signed_in()
        self.assertEqual(len(seen), 10)
        for argv, kwargs in seen:
            self.assertEqual(argv[0], "gh")
            self.assertGreater(kwargs["timeout"], 0, argv)
            self.assertEqual(kwargs["env"]["GH_PROMPT_DISABLED"], "1")
            self.assertTrue("input" in kwargs or kwargs.get("stdin") == subprocess.DEVNULL, argv)

    def test_a_paged_listing_is_read_as_one_list(self):
        self.gh(answer("api", out='[{"id": 1}]\n[{"id": 2}, {"id": 3}]'))
        self.assertEqual([row["id"] for row in gh_cli.api("repos/octo/api/issues/12/comments")], [1, 2, 3])
        self.assertEqual(self.calls(), [["api", "--hostname", "github.com", "--paginate",
                                         "repos/octo/api/issues/12/comments"]])


class NoSecretTest(unittest.TestCase):
    def test_the_environment_gh_is_given_adds_no_credential(self):
        added = set(gh_cli.environment()) - set(os.environ)
        self.assertLessEqual(added, {"GH_PROMPT_DISABLED", "GH_NO_UPDATE_NOTIFIER", "NO_COLOR", "CLICOLOR"})



BRANCH = "shipyard/c-41-tidy-the-loader"
REPO = "github.com/octo/api"
SECRET = "ghp_c689NotARealTokenOnlyAMarker0000"
# What git may be run with by any verb of the pack. Only `push` and `worktree` write, and
# `fetch` writes remote-tracking refs alone.
GIT_VERBS = {"config", "remote", "symbolic-ref", "rev-parse", "show-ref", "check-ref-format", "fetch",
             "worktree", "ls-remote", "cat-file", "merge-base", "rev-list", "diff", "status", "push",
             "grep"}   # grep: whether a branch's tree is on LFS, read before each Ship push (r2.D1)


def is_read(call: list[str]) -> bool:
    """A gh call that changes nothing on GitHub."""
    if call[:1] == ["api"]:
        return "--method" not in call and "--input" not in call
    return call[:2] in (["pr", "view"], ["pr", "list"], ["auth", "status"], ["repo", "view"])


class EveryVerbTest(GhCase):
    """r1.F15: every verb of the pack is RUN, a card's whole life through, against the
    stand-in gh and the recording git, and everything that writes is counted. This is what
    holds "never merges, closes, deletes or forces" and "no credential": what was run and
    printed, not the words in the source."""

    def setUp(self):
        super().setUp()
        self.patch(mock.patch.dict(os.environ, {"GH_TOKEN": SECRET, "GITHUB_TOKEN": SECRET,
                                                "GH_ENTERPRISE_TOKEN": SECRET,
                                                "KEEL_SPACE_REPOS": str(self.repo)}))
        self.printed, self.ran = [], []

    def verb(self, card: dict, name: str, *argv: str, stdin: str = "") -> str:
        """Run one verb as its executable would; its stdout. What it printed and what git
        it ran are kept; the test's own git before it is not."""
        self.forget_git()
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(gh_card, "load_card", lambda card_id: card), \
                mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gh_main.run(name, list(argv))
        self.assertEqual(code, 0, f"{name} {argv}: {err.getvalue()}")
        self.printed += [out.getvalue(), err.getvalue()]
        self.ran += self.git_calls()
        return out.getvalue()

    def plan(self) -> None:
        pull = {"number": 12, "url": "https://github.com/octo/api/pull/12", "isDraft": True,
                "title": "Tidy the loader", "state": "OPEN", "headRefOid": "abc", "headRefName": BRANCH,
                "baseRefName": "main", "author": {"login": "octo-dev"}, "statusCheckRollup": [],
                "isCrossRepository": False, "headRepositoryOwner": {"login": "octo"},
                "headRepository": {"name": "api"}}
        said = {"id": 201, "user": {"login": "ana", "type": "User"}, "body": "Why 40?", "path": "loader.py",
                "line": 7, "in_reply_to_id": None, "created_at": "2026-10-01T10:00:00Z"}
        threads = {"data": {"repository": {"pullRequest": {"reviewThreads": {
            "nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}}
        # r2.F12: a gh that is ASKED for the credential hands it over, so a call that asks
        # would be recorded and would leak into everything the token test searches
        self.gh(answer("auth", "token", out=SECRET + "\n"), answer("auth", "git-credential", out=SECRET),
                answer("auth", "status", "--show-token", out=f"Token: {SECRET}\n"),
                answer("auth", "status", "-t", out=f"Token: {SECRET}\n"),
                answer("pr", "list", "--author", out=[]), answer("pr", "list", out=[]),
                answer("pr", "create", out="https://github.com/octo/api/pull/12\n"),
                answer("pr", "view", out=pull), answer("pr", "ready"), answer("pr", "edit"),
                answer("pr", "comment"), answer("api", "graphql", out=threads),
                answer("api", "repos/octo/api/pulls/12/comments/201/replies"),
                answer("api", "repos/octo/api/pulls/12/comments", out=[said]),
                answer("api", "repos/octo/api/issues/12/comments", out=[]),
                answer("api", "repos/octo/api/pulls/12/reviews", out=[]),
                answer("auth", "status", out="Logged in to github.com account octo-dev\n"),
                answer("repo", "view", "nameWithOwner,viewerPermission",
                       out={"nameWithOwner": "octo/api", "viewerPermission": "WRITE"}),
                answer("api", "user", out="octo-dev\n"))

    def a_card_s_whole_life(self) -> None:
        self.plan()
        self.verb(self.card(), "worktree", "c-41")
        tree = self.cfg.worktrees_dir / "c-41"
        card = self.card(options={"branch": BRANCH, "worktree": str(tree)})
        self.verb(card, "brief", "c-41")
        self.commit(tree, "change.txt")
        git(tree, "push", "-q", "-u", "origin", BRANCH)                  # the house's own push
        folder = self.cfg.card_dir("c-41")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "context.md").write_text("## PR body\n\n```copy\nThe loader is tidy.\n```\n")
        self.verb(card, "pr", "c-41", "--draft")
        card = self.card(options={"branch": BRANCH, "worktree": str(tree), "pr": 12})
        self.verb(card, "pr", "c-41", "--body")
        self.assertEqual(json.loads(self.verb(card, "publishable", "c-41")), {"publishable": True})
        review = dict(card, stage="review")
        self.verb(self.tapped(review), "publish", "c-41")               # Approve outcome
        shipping = dict(card, stage="shipping", options={**card["options"], "publishing": TAPPED})
        for part in ("poll", "diff", "method", "down"):
            self.verb(shipping, "ship", "c-41", part)
        self.verb(shipping, "ship", "mine", stdin=json.dumps([shipping]))
        self.commit(tree, "fix.txt")
        ship = {"ship": True, "replies": [{"handle": "cl201", "text": "It is the page size."},
                                          {"handle": "ci", "text": "Rerun is green."}]}
        self.verb(shipping, "publish", "c-41", "--answer", stdin=json.dumps(ship))
        self.kb.listed = [shipping]
        self.verb(shipping, "act", "verbs")
        self.verb(shipping, "act", "links", "c-41")
        self.verb(shipping, "logins", "check")
        self.assertTrue(all(row["ok"] for row in json.loads(self.verb(shipping, "ready"))))
        self.verb(dict(shipping, stage="done"), "ship", "c-41", "reap")

    def test_the_only_things_ever_written_to_github_are_these(self):
        self.a_card_s_whole_life()
        writes = [call for call in self.calls() if not is_read(call)]
        self.assertEqual(writes, [
            ["pr", "create", "-R", REPO, "--head", BRANCH, "--base", "main", "--title", "Tidy the loader",
             "--body-file", "-", "--draft"],
            ["pr", "edit", "12", "-R", REPO, "--body-file", "-"],
            ["pr", "ready", "12", "-R", REPO],                       # Approve outcome
            ["pr", "ready", "12", "-R", REPO],                       # Ship (the stand-in stays a draft)
            ["api", "--hostname", "github.com", "--method", "POST",
             "repos/octo/api/pulls/12/comments/201/replies", "--input", "-"],
            ["pr", "comment", "12", "-R", REPO, "--body-file", "-"]])
        self.assertFalse([call for call in self.asked_about_branches() if not is_read(call)])

    def test_the_only_push_git_is_ever_run_with_is_the_card_branch_to_itself_unforced(self):
        self.a_card_s_whole_life()
        self.assertLessEqual({call[0] for call in self.ran}, GIT_VERBS)
        self.assertEqual([call for call in self.ran if call[0] == "push"],
                         [["push", "origin", f"refs/heads/{BRANCH}:refs/heads/{BRANCH}"]])
        self.assertEqual({tuple(call[:2]) for call in self.ran if call[0] == "worktree"},
                         {("worktree", "prune"), ("worktree", "add"), ("worktree", "list"), ("worktree", "remove")})
        flags = {word for call in self.ran for word in call[1:] if word.startswith("-")}
        self.assertLessEqual(flags, {"--quiet", "--prune", "--verify", "--no-track", "-b", "--get", "--short",
                                     "--abbrev-ref", "--is-ancestor", "--count", "--porcelain", "--branch",
                                     "-e", "--left-right", "--fixed-strings", "--"})   # the LFS look (r2.D1)
        # a `+` refspec only ever fetches into this clone's remote-tracking refs
        for call in self.ran:
            for word in call[1:]:
                if word.startswith("+"):
                    self.assertEqual(call[0], "fetch", call)
                    self.assertRegex(word, r"^\+refs/heads/[^:]+:refs/remotes/origin/")

    def test_a_review_card_s_whole_life_writes_one_review_and_pushes_nothing(self):
        """c-730: the scan, the poll, the house's checkout, its brief, the gear and Approve:
        the one thing written to GitHub is the review, and git pushes nothing."""
        other = self.dir / "colleague"
        subprocess.run(["git", "clone", "-q", str(self.dir / "origin" / "api.git"), str(other)], check=True)
        head = self.commit(other, "theirs.txt")
        git(other, "push", "-q", "origin", "HEAD:refs/pull/12/head")
        pull = {"number": 12, "url": "https://github.com/octo/api/pull/12", "isDraft": False, "title": "Faster",
                "state": "OPEN", "headRefOid": head, "headRefName": "ana/faster", "baseRefName": "main",
                "isCrossRepository": True}
        self.gh(answer("pr", "list", "review-requested:@me", out=[dict(pull, author={"login": "ana"})]),
                answer("pr", "view", out=pull), answer("api", "user", out="octo-dev\n"),
                answer("api", "repos/octo/api/pulls/12/reviews", "POST", out={"id": 9}),
                answer("api", "repos/octo/api/pulls/12/reviews", out=[]))
        self.cfg.spaces["code"].review_scan = True
        self.patch(mock.patch.dict(os.environ, {"KEEL_SPACE": "code"}))
        card = self.card(id="c-50", stage="assigned", options={"kind": "review", "review_key": "api:12", "pr": 12,
                                                              "branch": "ana/faster", "base": "main"})
        self.verb(card, "review", "scan")
        self.verb(card, "worktree", "c-50")
        self.verb(card, "brief", "c-50")
        self.verb(card, "review", "c-50", "poll")
        answer_ = {"review": {"round": 1, "head": head, "verdict": "approve", "summary": "Good.",
                              "comments": [{"row": "f1", "path": "theirs.txt", "line": 1, "text": "Nice."}]}}
        self.verb(self.tapped(dict(card, stage="review")), "publish", "c-50", "--answer", stdin=json.dumps(answer_))
        writes = [call for call in self.calls() if not is_read(call)]
        self.assertEqual(writes, [["api", "--hostname", "github.com", "--method", "POST",
                                   "repos/octo/api/pulls/12/reviews", "--input", "-"]])
        self.assertLessEqual({call[0] for call in self.ran}, (GIT_VERBS - {"push"}) | {"checkout"})
        # the house's checkout only ever moves, detached, to the head GitHub names
        self.assertEqual({tuple(call) for call in self.ran if call[0] == "checkout"},
                         {("checkout", "--quiet", "--detach", head)})

    def test_a_token_in_the_environment_appears_in_nothing_the_pack_prints_runs_or_records(self):
        self.a_card_s_whole_life()
        everywhere = {"printed": "".join(self.printed), "gh was run with": self.log.read_text(),
                      "git was run with": json.dumps(self.ran), "the board": json.dumps([self.kb.notes,
                                                                                         self.kb.options])}
        for where, text in everywhere.items():
            self.assertNotIn(SECRET, text, where)
        self.assertFalse([call for call in self.calls() + self.asked_about_branches()
                          if call[:2] == ["auth", "token"] or "--show-token" in call or "-t" in call
                          or call[:2] == ["auth", "git-credential"]])


if __name__ == "__main__":
    unittest.main()
