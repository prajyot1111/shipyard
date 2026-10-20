"""Ship on a card at shipping (`publish --answer`): the card's own branch pushed as a plain
fast-forward to a bare origin in a temporary directory, a draft marked ready, and each
kept reply posted once, in the thread of the line comment it answers or as a general
comment. Nothing is ever forced, a shared branch is never pushed, nothing is merged, and a
pull request that is no longer open is never written to.

git is the recording one on PATH (`ghfake`), so what is asserted about a push is the
command git was really run with.
"""

import json
import subprocess
import unittest
from unittest import mock

from ghfake import NOT_FOUND, SLUG, TAPPED, GhCase, answer, default_branch, git, protection

from gh_cli import GithubError
from keel.packkit import card as gh_card
from keel.packkit import pulls as gh_pulls
from keel.packkit import ship as gh_ship

BRANCH = "shipyard/c-41-tidy-the-loader"
REPO = "github.com/octo/api"
SHIP_KEYS = {"shipping", "shipped", "pr", "pushed", "skipped", "ready", "posted", "sent"}
LINES = "repos/octo/api/pulls/12/comments"
TALK = "repos/octo/api/issues/12/comments"
REPLIES_201 = "repos/octo/api/pulls/12/comments/201/replies"
REPLY_201 = ["api", "--hostname", "github.com", "--method", "POST", REPLIES_201, "--input", "-"]
COMMENT = ["pr", "comment", "12", "-R", REPO, "--body-file", "-"]
PUSH = ["push", "origin", f"refs/heads/{BRANCH}:refs/heads/{BRANCH}"]


def pull(draft: bool = False, state: str | None = "OPEN", number: int = 12, repo: str = "api",
         branch: str = BRANCH, fork: bool | None = False) -> dict:
    return {"number": number, "url": f"https://github.com/octo/{repo}/pull/{number}", "isDraft": draft,
            "title": "Tidy the loader", "state": state, "headRefOid": "abc", "headRefName": branch,
            "baseRefName": "main", "isCrossRepository": fork}


def line(number: int, who: str, text: str, under: int | None = None) -> dict:
    return {"id": number, "user": {"login": who, "type": "User"}, "body": text, "path": "loader.py",
            "line": 7, "in_reply_to_id": under, "created_at": "2026-10-01T10:00:00Z",
            "updated_at": "2026-10-01T10:00:00Z"}


def talk(number: int, who: str, text: str) -> dict:
    return {"id": number, "user": {"login": who, "type": "User"}, "body": text}


ME = answer("api", "user", out="octo-dev\n")           # who gh is signed in as


class ShipCase(GhCase):
    def setUp(self):
        super().setUp()
        self.tree = self.branch(BRANCH)
        self.shipping = self.card(stage="shipping", options={
            "branch": BRANCH, "pr": 12, "worktree": str(self.tree), "publishing": TAPPED})

    def plan(self, *first: dict, draft: bool = False, state: str = "OPEN", lines=(), talked=()) -> None:
        self.gh(*first, ME, answer("pr", "view", out=pull(draft, state)), answer("pr", "ready"),
                answer("api", REPLIES_201), answer("api", LINES, out=list(lines)),
                answer("api", TALK, out=list(talked)), answer("pr", "comment"))
        self.forget_git()

    def ship(self, *replies: tuple[str, str], card: dict | None = None) -> dict:
        answer_ = {"ship": True, "replies": [{"handle": h, "text": t} for h, t in replies],
                   "lease": {"api": "0" * 40}}
        return gh_pulls.publish(card or self.shipping, answer_)

    def writes(self) -> list[list[str]]:
        """The gh calls that change something on GitHub."""
        return [call for call in self.calls() if call[:2] in (["pr", "ready"], ["pr", "comment"])
                or "POST" in call]

    def said(self) -> list[str]:
        """The words of each reply posted, in order, as GitHub was handed them."""
        out = []
        for one in self.records():
            if one["argv"][:2] == ["pr", "comment"]:
                out.append(one["stdin"])
            elif "POST" in one["argv"]:
                out.append(json.loads(one["stdin"])["body"])
        return out

    def refused(self, pattern: str, *replies, card: dict | None = None) -> None:
        """A Ship that is refused whole: nothing pushed, nothing written on GitHub."""
        with self.assertRaisesRegex(GithubError, pattern):
            self.ship(*replies, card=card)
        self.assertEqual((self.git_calls("push"), self.writes()), ([], []))


class PushTest(ShipCase):
    def test_ship_pushes_the_card_branch_marks_the_draft_ready_and_answers_in_the_contracts_shape(self):
        head = self.commit(self.tree)
        self.plan(draft=True)
        result = self.ship()
        self.assertEqual(set(result), SHIP_KEYS)
        self.assertEqual(self.origin_head(BRANCH), head)
        self.assertEqual(result, {"shipping": True, "shipped": True, "pr": 12, "pushed": {"api": head},
                                  "skipped": [], "ready": ["api"], "posted": [], "sent": []})
        self.assertEqual(self.writes(), [["pr", "ready", "12", "-R", REPO]])

    def test_the_one_push_git_is_run_with_is_plain_and_names_only_the_card_branch(self):
        self.commit(self.tree)
        self.plan()
        self.ship()
        self.assertEqual(self.git_calls("push"), [PUSH])

    def fake_lfs(self, code: int = 0) -> None:
        """r2.D1: a stand-in `git-lfs` on the PATH (no real LFS): git runs it for `git lfs`."""
        lfs = self.bin / "git-lfs"
        lfs.write_text(f"#!/bin/sh\necho 'lfs said no' >&2\nexit {code}\n")
        lfs.chmod(0o755)

    def lfs_attribute(self) -> None:
        (self.tree / ".gitattributes").write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n")
        git(self.tree, "add", ".gitattributes")
        git(self.tree, "commit", "-q", "-m", "track binaries with LFS")

    def test_a_repo_on_lfs_has_its_objects_pushed_by_git_lfs_before_the_branch(self):
        """r2.D1: a kit push runs with hooks off, which skips git-lfs's own pre-push hook, so
        the kit runs `git lfs push` itself first, hooks off too."""
        self.fake_lfs()
        self.lfs_attribute()
        self.plan()
        self.ship()
        calls = [call for call in self.git_calls() if call[:1] in (["lfs"], ["push"])]
        self.assertEqual(calls, [["lfs", "push", "origin", BRANCH], PUSH])

    def test_a_repo_without_lfs_never_runs_git_lfs(self):
        self.fake_lfs()
        self.commit(self.tree)
        self.plan()
        self.ship()
        self.assertEqual([call for call in self.git_calls() if call[:1] == ["lfs"]], [])
        self.assertEqual(self.git_calls("push"), [PUSH])

    def test_a_repo_on_lfs_with_no_git_lfs_installed_is_refused_before_anything_is_pushed(self):
        """r2.D1: pushing it would push the pointers without their objects."""
        self.lfs_attribute()
        self.plan()
        self.refused("git-lfs is needed to ship .* install it")

    def test_a_git_lfs_push_that_fails_refuses_the_ship_before_the_branch_is_pushed(self):
        self.fake_lfs(code=1)
        self.lfs_attribute()
        self.plan()
        self.refused("git lfs push of .* failed, so nothing was pushed .*lfs said no")

    def test_a_branch_rewritten_on_the_remote_refuses_the_whole_ship(self):
        self.commit(self.tree)
        rewritten = self.others_push(BRANCH, rewrite=True)
        self.plan(draft=True)
        self.refused("has diverged from .* on the remote .*nothing was pushed", ("ci", "Fixed."))
        self.assertEqual(self.origin_head(BRANCH), rewritten)

    def test_a_remote_that_is_ahead_pushes_nothing_and_still_posts(self):
        theirs = self.others_push(BRANCH)
        self.plan()
        result = self.ship(("ci", "Rerun is green."))
        self.assertEqual((result["pushed"], result["skipped"], result["posted"]), ({}, ["api"], ["ci"]))
        self.assertEqual((self.origin_head(BRANCH), self.git_calls("push")), (theirs, []))

    def test_a_push_the_remote_rejects_after_the_look_is_not_forced_and_posts_nothing(self):
        """r1.F14: a colleague pushes between the look at the remote and the push."""
        self.commit(self.tree)
        self.plan()
        real, theirs = gh_card.git, []

        def raced(repo, *args, **kwargs):
            if args[0] == "push":
                theirs.append(self.others_push(BRANCH))
            return real(repo, *args, **kwargs)

        with mock.patch.object(gh_card, "git", side_effect=raced):
            with self.assertRaisesRegex(GithubError, f"git push of {BRANCH} in api failed, so no reply was posted"):
                self.ship(("ci", "Fixed."))
        self.assertEqual(self.origin_head(BRANCH), theirs[0])
        self.assertEqual(self.writes(), [])
        self.assertEqual([call for call in self.git_calls("push") if call[1] == "origin" and ":" in call[2]], [PUSH])

    def test_a_worktree_on_another_branch_pushes_nothing(self):
        git(self.tree, "checkout", "-q", "-b", "something-else")
        self.plan()
        self.refused("worktree is on something-else, not shipyard/c-41")

    def test_a_push_git_has_no_sign_in_for_says_how_to_give_it_one(self):
        self.commit(self.tree)
        self.plan()
        real = gh_card.git

        def no_password(repo, *args, **kwargs):
            if args[0] == "push":
                return subprocess.CompletedProcess(args, 128, stdout="", stderr=(
                    "fatal: could not read Username for 'https://github.com': terminal prompts disabled\n"))
            return real(repo, *args, **kwargs)

        with mock.patch.object(gh_card, "git", side_effect=no_password):
            with self.assertRaisesRegex(GithubError, r"in api failed, so no reply was posted: could not read Username.*"
                                                     r"run `gh auth setup-git`"):
                self.ship(("ci", "Fixed."))
        self.assertEqual(self.writes(), [])


class StillOpenTest(ShipCase):
    """r1.F6: every pull request the Ship would touch is read first, and each must be open."""

    def test_a_merged_pull_request_refuses_the_whole_ship(self):
        self.commit(self.tree)
        before = self.origin_head(BRANCH)
        self.plan(state="MERGED", draft=False)
        self.refused("pull request #12 of octo/api is merged on GitHub, so nothing was pushed", ("ci", "Fixed."))
        self.assertEqual(self.origin_head(BRANCH), before)

    def test_a_closed_pull_request_refuses_the_whole_ship(self):
        self.commit(self.tree)
        before = self.origin_head(BRANCH)
        self.plan(state="CLOSED", draft=True)
        self.refused("pull request #12 of octo/api is closed on GitHub, so nothing was pushed", ("ci", "Fixed."))
        self.assertEqual(self.origin_head(BRANCH), before)

    def test_a_branch_gone_from_the_remote_is_a_refusal_and_is_never_made_again(self):
        self.commit(self.tree)
        git(self.dir / "origin" / "api.git", "update-ref", "-d", f"refs/heads/{BRANCH}")
        self.plan()
        self.refused(f"{BRANCH} is no longer on the remote of api", ("ci", "Fixed."))
        self.assertIsNone(self.origin_head(BRANCH))


    def test_a_pull_request_from_another_branch_than_the_card_s_refuses(self):
        """r2.F6: the open check is on the number and the push is on the card's branch;
        the two must be the same pull request."""
        self.commit(self.tree)
        self.plan(answer("pr", "view", out=pull(branch="someone-elses")))
        self.refused("pull request #12 of octo/api is from the branch someone-elses, not this card's "
                     f"{BRANCH}", ("ci", "Fixed."))

    def test_a_pull_request_from_a_fork_refuses(self):
        self.commit(self.tree)
        for fork in (True, None):           # None: GitHub did not say, which is not a no
            self.plan(answer("pr", "view", out=pull(fork=fork)))
            self.refused("pull request #12 of octo/api is not from a branch of octo/api itself")

    def test_a_state_github_does_not_name_is_never_read_as_open(self):
        self.commit(self.tree)
        for state in ("LOCKED_AWAY", None):
            self.plan(answer("pr", "view", out=pull(state=state)))
            self.refused("GitHub did not say whether pull request #12 of octo/api is open")

    def test_a_remote_that_cannot_be_asked_at_ship_is_a_refusal_not_a_push_on_hope(self):
        self.commit(self.tree)
        before = self.origin_head(BRANCH)
        self.plan()
        real = gh_card.git

        def deaf(repo, *args, **kwargs):
            if args[0] == "ls-remote":
                return subprocess.CompletedProcess(args, 128, stdout="", stderr="fatal: unable to access\n")
            return real(repo, *args, **kwargs)

        with mock.patch.object(gh_card, "git", side_effect=deaf):
            self.refused(f"the remote of api could not be asked whether {BRANCH} is still there.*try again")
        self.assertEqual(self.origin_head(BRANCH), before)


class SharedBranchTest(ShipCase):
    """r1.F5, r1.F13: what is shared is the usual names, the card's base, and what GITHUB
    says: the repository's default branch and a branch it reports protected. Each case
    names a branch only one of those rules refuses, and the origin never moves."""

    def on(self, branch: str, **options) -> dict:
        """A card at shipping whose pull request is from `branch`, with a commit to push."""
        if branch != BRANCH:
            git(self.tree, "checkout", "-q", "-b", branch)
            git(self.tree, "push", "-q", "origin", branch)
        self.commit(self.tree)
        return self.card(stage="shipping", options={"branch": branch, "pr": 12, "worktree": str(self.tree),
                                                    "publishing": TAPPED, **options})

    def never_pushed(self, branch: str, pattern: str, *first: dict, **options) -> None:
        card = self.on(branch, **options)
        before = self.origin_head(branch)
        self.plan(*first, answer("pr", "view", out=pull(branch=branch)))
        self.refused(pattern, ("ci", "Fixed."), card=card)
        self.assertEqual(self.origin_head(branch), before)

    def test_a_usual_shared_name(self):
        card = self.card(stage="shipping", options={"branch": "main", "pr": 12, "worktree": str(self.repo),
                                                    "publishing": TAPPED})
        before = self.origin_head("main")
        self.plan(answer("pr", "view", out=pull(branch="main")))
        self.refused("main is a shared branch of api .a usual shared name.: this pack never pushes it", card=card)
        self.assertEqual(self.origin_head("main"), before)

    def test_a_release_or_hotfix_branch_by_its_prefix(self):
        self.never_pushed("release/2.0", "release/2.0 is a shared branch of api .a usual shared name.")

    def test_the_card_s_base_when_it_is_no_usual_name(self):
        self.never_pushed("next", "next is a shared branch of api .the card's base.", base="next")

    def test_github_s_default_branch_when_it_is_no_usual_name(self):
        self.never_pushed("dev", "dev is a shared branch of api .GitHub's default branch.", default_branch("dev"))
        self.assertIn(["repo", "view", REPO, "--json", "defaultBranchRef"], self.asked_about_branches())

    def test_a_branch_github_reports_protected_whatever_its_name(self):
        self.never_pushed(BRANCH, f"{BRANCH} is a shared branch of api .protected on GitHub.",
                          protection(SLUG, BRANCH, True))
        self.assertIn(["api", "--hostname", "github.com", f"repos/octo/api/branches/{BRANCH}"],
                      self.asked_about_branches())

    def test_a_default_branch_that_cannot_be_read_refuses_and_main_is_never_assumed(self):
        unread = answer("repo", "view", "defaultBranchRef", code=1, err="error connecting to api.github.com\n")
        self.never_pushed(BRANCH, "GitHub could not say which branch of octo/api is its default.*"
                                  "nothing is cut, pushed or opened on a guess; try again", unread)

    def test_a_protection_that_cannot_be_read_refuses(self):
        unread = answer("api", f"repos/octo/api/branches/{BRANCH}", code=1, err="gh: Server Error (HTTP 502)\n")
        self.never_pushed(BRANCH, f"GitHub could not say whether {BRANCH} is protected", unread)

    def test_a_branch_github_has_never_heard_of_is_not_protected(self):
        """A card's new branch, before its first push: gh's not-found answer is no refusal."""
        self.gh(answer("api", f"repos/octo/api/branches/{BRANCH}", code=1, err=NOT_FOUND))
        gh_ship.shared.refuse(self.shipping, "api", BRANCH)


class ReplyTest(ShipCase):
    def test_a_reply_to_a_line_comment_goes_into_its_thread_and_any_other_is_a_general_comment(self):
        self.plan(lines=[line(201, "ana", "Why 40?")])
        result = self.ship(("cl201", "It is the page size."), ("ci", "Rerun is green."))
        self.assertEqual(self.writes(), [REPLY_201, COMMENT])
        self.assertEqual(self.said(), [f"It is the page size.\n\n{gh_ship.marker('cl201', 'It is the page size.')}",
                                       f"Rerun is green.\n\n{gh_ship.marker('ci', 'Rerun is green.')}"])
        self.assertRegex(self.said()[0], r"\n\n<!-- keel:reply cl201 [0-9a-f]{12} -->$")
        self.assertEqual(result["posted"], ["cl201", "ci"])
        self.assertEqual(result["sent"], [{"handle": "cl201", "text": "It is the page size."},
                                          {"handle": "ci", "text": "Rerun is green."}])

    def test_a_reply_to_a_reply_goes_under_the_thread_s_first_comment(self):
        self.plan(lines=[line(201, "ana", "Why 40?"), line(203, "ana", "And here?", under=201)])
        self.ship(("cl203", "Same reason."))
        self.assertEqual(self.writes(), [REPLY_201])

    def test_a_general_comment_or_a_review_with_a_line_comment_s_number_is_never_put_in_its_thread(self):
        """r1.F10: the three kinds have their own handles, so the same number in two of
        GitHub's id spaces cannot send a reply into the wrong place."""
        self.plan(lines=[line(201, "ana", "Why 40?")])
        self.ship(("cg201", "To the conversation."), ("cr201", "To the review."))
        self.assertEqual(self.writes(), [COMMENT, COMMENT])


class SaidOnceTest(ShipCase):
    """r1.F7: what was already said is known by the HANDLE it answered (a hidden marker in
    the reply), never by its words."""

    def test_the_same_words_to_another_item_in_a_later_round_are_posted(self):
        earlier = talk(9, "octo-dev", f"Fixed.\n\n{gh_ship.marker('ci', 'Fixed.')}")
        self.plan(talked=[earlier, talk(101, "ana", "And the other one?")])
        result = self.ship(("cg101", "Fixed."))
        self.assertEqual(self.said(), [f"Fixed.\n\n{gh_ship.marker('cg101', 'Fixed.')}"])
        self.assertEqual(result["posted"], ["cg101"])

    def test_the_same_words_to_two_items_in_one_ship_are_both_posted(self):
        self.plan(lines=[line(201, "ana", "Why 40?")])
        result = self.ship(("cg101", "Done."), ("cg102", "Done."), ("cl201", "Done."))
        self.assertEqual(self.writes(), [COMMENT, COMMENT, REPLY_201])
        self.assertEqual(result["posted"], ["cg101", "cg102", "cl201"])

    def test_words_the_author_wrote_by_hand_do_not_stand_in_for_a_reply(self):
        self.plan(talked=[talk(9, "octo-dev", "Fixed.")])
        self.assertEqual(self.ship(("ci", "Fixed."))["posted"], ["ci"])

    def test_a_retry_after_a_failure_halfway_posts_only_what_did_not_land(self):
        replies = (("cl201", "It is the page size."), ("ci", "Rerun is green."))
        self.plan(answer("pr", "comment", code=1, err="gh: Server Error (HTTP 502)\n"),
                  lines=[line(201, "ana", "Why 40?")])
        with self.assertRaisesRegex(GithubError, "gh pr comment failed: Server Error .HTTP 502."):
            self.ship(*replies)
        landed = line(204, "octo-dev", self.said()[0], under=201)
        self.log.unlink()
        self.plan(lines=[line(201, "ana", "Why 40?"), landed])
        result = self.ship(*replies)
        self.assertEqual(self.writes(), [COMMENT])
        self.assertEqual(result["posted"], ["ci"])
        self.assertEqual([one["handle"] for one in result["sent"]], ["cl201", "ci"])

    def test_the_mirror_retry_a_general_reply_landed_and_the_line_reply_did_not(self):
        """r2.F8: the marker of a reply that landed in the conversation is found there."""
        replies = (("ci", "Rerun is green."), ("cl201", "It is the page size."))
        self.plan(answer("api", REPLIES_201, code=1, err="gh: Server Error (HTTP 502)\n"),
                  lines=[line(201, "ana", "Why 40?")])
        with self.assertRaisesRegex(GithubError, "gh api failed: Server Error .HTTP 502."):
            self.ship(*replies)
        landed = talk(9, "octo-dev", self.said()[0])
        self.log.unlink()
        self.plan(lines=[line(201, "ana", "Why 40?")], talked=[landed])
        result = self.ship(*replies)
        self.assertEqual(self.writes(), [REPLY_201])
        self.assertEqual(result["posted"], ["cl201"])
        self.assertEqual([one["handle"] for one in result["sent"]], ["ci", "cl201"])

    def test_the_marker_is_this_exact_line(self):
        """Pinned to a literal: what is digested decides whether a retry matches."""
        self.assertEqual(gh_ship.marker("ci", "Fixed."), "<!-- keel:reply ci 13079c2612a9 -->")
        self.assertEqual(gh_ship.marker("cl201", " It is the page size.\n"),
                         "<!-- keel:reply cl201 ecf3965a2299 -->")

    def test_markers_are_looked_for_under_the_signed_in_account_whoever_opened_the_pull_request(self):
        """r2.F7: the replies are posted as whoever gh is signed in as, so that is whose
        markers count. The pull request's author is never asked."""
        mine = talk(9, "octo-dev", f"Fixed.\n\n{gh_ship.marker('ci', 'Fixed.')}")
        theirs = talk(8, "the-author", f"Fixed.\n\n{gh_ship.marker('cg101', 'Fixed.')}")
        self.plan(talked=[theirs, mine])
        result = self.ship(("ci", "Fixed."), ("cg101", "Fixed."))
        self.assertEqual((result["posted"], len(self.writes())), (["cg101"], 1))
        self.assertFalse([call for call in self.calls() if "author" in call])
        self.assertIn(["api", "--hostname", "github.com", "user", "--jq", ".login"], self.calls())

    def test_an_account_that_cannot_be_read_refuses_before_anything_is_pushed(self):
        self.commit(self.tree)
        for unread in (answer("api", "user", code=1, err="gh: Server Error (HTTP 502)\n"),
                       answer("api", "user", out="\n")):
            self.plan(unread)
            self.refused("gh could not say which account is signed in.*nothing was pushed", ("ci", "Fixed."))

    def test_a_comment_with_no_author_is_nobody_s_even_when_no_account_is_named(self):
        """A marker under a comment with no author stops no reply. It bites where the
        account is not named at all: a missing author equal to a missing account would
        otherwise read as the account's own comment."""
        ghost = {"id": 9, "user": None, "body": f"Fixed.\n\n{gh_ship.marker('ci', 'Fixed.')}"}
        nameless = {"id": 10, "user": {"login": None}, "body": f"Fixed.\n\n{gh_ship.marker('ci', 'Fixed.')}"}
        self.plan(talked=[ghost, nameless])
        for me in ("octo-dev", "", None):
            self.assertTrue(gh_ship.Thread(SLUG, 12, me).post("ci", "Fixed."), repr(me))
        self.assertEqual(len(self.writes()), 3)

    def test_a_marker_someone_else_wrote_stops_nothing(self):
        planted = talk(9, "stranger", f"hello\n\n{gh_ship.marker('ci', 'Fixed.')}")
        self.plan(talked=[planted])
        self.assertEqual(self.ship(("ci", "Fixed."))["posted"], ["ci"])


class TwoReposTest(ShipCase):
    """r1.F14: a card with a pull request in each of two repos."""

    def setUp(self):
        super().setUp()
        self.cfg.spaces["code"].repos["web"] = self.make_repo("web")
        self.web = self.branch(BRANCH, key="web")
        self.both = self.card(repo="api,web", stage="shipping", options={
            "branch": BRANCH, "pr": 12, "publishing": TAPPED,
            "prs": {"api": {"pr": 12, "branch": BRANCH}, "web": {"pr": 5, "branch": BRANCH}},
            "worktrees": {"api": str(self.tree), "web": str(self.web)}})
        self.extra = (answer("pr", "view", "5", out=pull(draft=True, number=5, repo="web")),
                      answer("api", "repos/octo/web/pulls/5/comments", out=[]),
                      answer("api", "repos/octo/web/issues/5/comments", out=[]))

    def test_each_repo_s_branch_is_pushed_each_draft_readied_and_a_reply_goes_where_its_handle_names(self):
        heads = {"api": self.commit(self.tree), "web": self.commit(self.web)}
        self.plan(*self.extra)
        result = self.ship(("web.cg7", "On the web side."), ("ci", "Green."), card=self.both)
        self.assertEqual(result["pushed"], heads)
        self.assertEqual((self.origin_head(BRANCH), self.origin_head(BRANCH, "web")), (heads["api"], heads["web"]))
        self.assertEqual(result["ready"], ["web"])
        self.assertEqual(self.writes(), [["pr", "ready", "5", "-R", "github.com/octo/web"],
                                         ["pr", "comment", "5", "-R", "github.com/octo/web", "--body-file", "-"],
                                         COMMENT])
        self.assertEqual(result["posted"], ["web.cg7", "ci"])

    def test_one_of_the_two_merged_refuses_both(self):
        self.commit(self.tree)
        self.plan(answer("pr", "view", "5", out=pull(state="MERGED", number=5, repo="web")))
        self.refused("pull request #5 of octo/web is merged on GitHub", card=self.both)

    def test_the_second_repo_diverged_refuses_before_the_first_is_pushed(self):
        """r2.F5: every check, for every repo, runs before any push."""
        self.commit(self.tree)
        self.commit(self.web)
        before = self.origin_head(BRANCH)
        self.others_push(BRANCH, rewrite=True, key="web")
        self.plan(*self.extra)
        self.refused("the web worktree has diverged", ("ci", "Fixed."), card=self.both)
        self.assertEqual(self.origin_head(BRANCH), before)

    def test_the_second_repo_s_branch_gone_refuses_before_the_first_is_pushed(self):
        self.commit(self.tree)
        before = self.origin_head(BRANCH)
        git(self.dir / "origin" / "web.git", "update-ref", "-d", f"refs/heads/{BRANCH}")
        self.plan(*self.extra)
        self.refused(f"{BRANCH} is no longer on the remote of web", ("ci", "Fixed."), card=self.both)
        self.assertEqual(self.origin_head(BRANCH), before)

    def test_the_second_repo_s_push_rejected_says_which_repo_and_which_were_already_pushed(self):
        head = self.commit(self.tree)
        self.commit(self.web)
        self.plan(*self.extra)
        real = gh_card.git

        def raced(repo, *args, **kwargs):
            if args[0] == "push" and str(repo) == str(self.web):
                self.others_push(BRANCH, key="web")
            return real(repo, *args, **kwargs)

        with mock.patch.object(gh_card, "git", side_effect=raced):
            with self.assertRaisesRegex(GithubError, f"git push of {BRANCH} in web failed, so no reply was "
                                                     f"posted: .*; already pushed: api"):
                self.ship(("ci", "Fixed."), card=self.both)
        self.assertEqual(self.origin_head(BRANCH), head)
        self.assertEqual(self.writes(), [])

    def test_a_reply_naming_a_repo_the_card_has_no_pull_request_in_refuses_before_any_push(self):
        self.commit(self.tree)
        self.plan()
        self.refused("names web, which is not one of this card's other", ("web.cg5", "Done."))


if __name__ == "__main__":
    unittest.main()
