"""`pr`, `publishable` and `publish` on GitHub: the exact gh call each makes, and what each
answers. The branch and its remote are real git in a temporary directory; gh is the
stand-in on PATH, so the calls asserted here are the ones a real gh would be given.
"""

import contextlib
import io
import unittest
from unittest import mock

from ghfake import TAPPED, GhCase, answer, default_branch

from gh_cli import GithubError
from keel.packkit import card as gh_card
from keel.packkit import pulls as gh_pulls
from keel.packkit import verbs as gh_main

BRANCH = "shipyard/c-41-tidy-the-loader"
REPO = "github.com/octo/api"
FIELDS = "number,url,isDraft,title,state,headRefOid,headRefName,baseRefName,isCrossRepository"
URL = "https://github.com/octo/api/pull/12"


def pull(draft: bool = True, state: str = "OPEN", head: str = "abc123", number: int = 12,
         owner: str = "octo", fork: bool = False, repo: str = "api") -> dict:
    return {"number": number, "url": f"https://github.com/octo/{repo}/pull/{number}", "isDraft": draft,
            "title": "Tidy the loader", "state": state, "headRefOid": head, "headRefName": BRANCH,
            "baseRefName": "main", "isCrossRepository": fork, "headRepositoryOwner": {"login": owner},
            "headRepository": {"name": repo}}


NONE_OPEN = answer("pr", "list", out=[])
ONE_OPEN = answer("pr", "list", out=[pull()])
CREATED = answer("pr", "create", out=f"{URL}\n")
LIST_CALL = ["pr", "list", "-R", REPO, "--head", BRANCH, "--state", "open", "--json", FIELDS,
             "--limit", "100"]
VIEW_CALL = ["pr", "view", "12", "-R", REPO, "--json", FIELDS]
CREATE_CALL = ["pr", "create", "-R", REPO, "--head", BRANCH, "--base", "main", "--title", "Tidy the loader",
               "--body-file", "-", "--draft"]


class PullCase(GhCase):
    def setUp(self):
        super().setUp()
        self.fresh = self.card(options={"branch": BRANCH})
        self.opened = self.card(options={"branch": BRANCH, "pr": 12})

    def record(self, text: str) -> None:
        folder = self.cfg.card_dir("c-41")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "context.md").write_text(text)

    def verb(self, name: str, *argv: str, card: dict) -> tuple[int, str, str]:
        """A verb as its executable runs it: (exit, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(gh_card, "load_card", lambda card_id: card), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gh_main.run(name, list(argv))
        return code, out.getvalue(), err.getvalue()


class OpenTest(PullCase):
    def test_pr_opens_a_draft_from_the_cards_branch_with_its_title_and_brief(self):
        self.branch(BRANCH)
        self.gh(NONE_OPEN, CREATED, answer("pr", "view", out=pull()))
        result = gh_pulls.open_drafts(self.fresh)
        self.assertEqual(self.calls(), [LIST_CALL, CREATE_CALL, VIEW_CALL])
        self.assertEqual(self.records()[-2]["stdin"], "Make it tidy.\n\nShipyard card c-41.\n")
        self.assertEqual(result["opened"], [{"id": 12, "url": URL, "draft": True, "title": "Tidy the loader",
                                             "state": "open", "head": "abc123", "branch": BRANCH,
                                             "base": "main", "own": True, "repo": "api"}])
        self.assertEqual(self.kb.options, [("c-41", "pr", 12)])
        self.assertEqual(self.kb.notes, [("c-41", f"draft pull request #12: {URL}")])

    def test_the_body_is_what_the_house_wrote_under_pr_body_in_the_record(self):
        self.branch(BRANCH)
        self.record("# Outcome\n\n## PR body\n\n```copy PR body\n## What\n\nThe loader is tidy.\n```\n\n"
                    "## Risk\nnone\n")
        self.gh(NONE_OPEN, CREATED, answer("pr", "view", out=pull()))
        gh_pulls.open_drafts(self.fresh)
        self.assertEqual(self.records()[-2]["stdin"], "## What\n\nThe loader is tidy.")

    def test_the_base_is_the_cards_own_when_it_names_one(self):
        self.branch(BRANCH)
        self.gh(NONE_OPEN, CREATED, answer("pr", "view", out=pull()))
        gh_pulls.open_drafts(self.card(options={"branch": BRANCH, "base": "next"}))
        self.assertEqual(self.calls()[1][6:8], ["--base", "next"])

    def test_a_pull_request_already_open_on_the_branch_is_found_and_none_is_opened(self):
        self.branch(BRANCH)
        self.gh(ONE_OPEN)
        result = gh_pulls.open_drafts(self.fresh)
        self.assertEqual(self.calls(), [LIST_CALL])
        self.assertEqual(result["opened"][0]["id"], 12)
        self.assertEqual(self.kb.options, [("c-41", "pr", 12)])

    def test_a_fork_s_pull_request_on_the_same_branch_name_is_never_the_card_s(self):
        """r1.F4: `--head` matches a branch name in anyone's fork. Only a pull request whose
        head is the repository itself is the card's; a stranger's is passed over, and the
        card's own, listed after it, is the one recorded."""
        self.branch(BRANCH)
        strangers = [pull(number=7, owner="stranger", fork=True), pull(number=8, owner="OCTO", fork=True)]
        self.gh(answer("pr", "list", out=strangers), CREATED, answer("pr", "view", out=pull()))
        result = gh_pulls.open_drafts(self.fresh)
        self.assertEqual(self.calls(), [LIST_CALL, CREATE_CALL, VIEW_CALL])
        self.assertEqual((result["opened"][0]["id"], self.kb.options), (12, [("c-41", "pr", 12)]))
        self.kb.options.clear()
        self.gh(answer("pr", "list", out=[*strangers, pull(number=12)]))
        self.assertIsNone(gh_pulls.missing(self.fresh))
        self.assertEqual(self.kb.options, [("c-41", "pr", 12)])

    def test_the_card_s_own_pull_request_is_found_after_the_repository_was_renamed_or_moved(self):
        """r2.F10: ownership is GitHub's own answer (not cross-repository), never a
        comparison of names: the clone's address keeps the old name after a rename."""
        self.branch(BRANCH)
        self.gh(answer("pr", "list", out=[pull(owner="new-owner", repo="api-renamed")]), CREATED)
        result = gh_pulls.open_drafts(self.fresh)
        self.assertEqual((result["opened"][0]["id"], self.calls()), (12, [LIST_CALL]))

    def test_the_draft_is_opened_into_the_default_branch_github_names_not_the_clone_s_record(self):
        """r2.F9: the clone still records `main`; GitHub says the default is `trunk-2`."""
        self.branch(BRANCH)
        self.gh(default_branch("trunk-2"), NONE_OPEN, CREATED, answer("pr", "view", out=pull()))
        gh_pulls.open_drafts(self.fresh)
        self.assertEqual(self.calls()[1][6:8], ["--base", "trunk-2"])

    def test_a_default_branch_github_cannot_name_opens_nothing_and_says_try_again(self):
        self.branch(BRANCH)
        self.gh(answer("repo", "view", "defaultBranchRef", code=1, err="error connecting to api.github.com\n"),
                NONE_OPEN, CREATED)
        with self.assertRaisesRegex(GithubError, "GitHub could not say which branch of octo/api is its default "
                                                 ".*so nothing is cut, pushed or opened on a guess; try again"):
            gh_pulls.open_drafts(self.fresh)
        self.assertEqual(self.calls(), [])

    def test_a_branch_that_is_not_pushed_is_refused_and_nothing_is_opened(self):
        self.branch(BRANCH, pushed=False)
        self.gh(NONE_OPEN, CREATED)
        with self.assertRaisesRegex(GithubError, "is not on the remote yet: push it first"):
            gh_pulls.open_drafts(self.fresh)
        self.assertEqual(self.calls(), [LIST_CALL])

    def test_a_shared_branch_never_gets_a_pull_request_of_its_own(self):
        self.gh(NONE_OPEN, CREATED)
        with self.assertRaisesRegex(GithubError, "main is a shared branch of api"):
            gh_pulls.open_drafts(self.card(options={"branch": "main"}))
        self.assertEqual(self.calls(), [])

    def test_a_research_card_opens_none(self):
        self.gh(NONE_OPEN, CREATED)
        with self.assertRaisesRegex(GithubError, "research card"):
            gh_pulls.open_drafts(self.card(options={"branch": BRANCH, "kind": "research"}))
        self.assertEqual(self.calls(), [])


class TwoReposTest(PullCase):
    """r1.F14: a card with a repo beside its primary one."""

    def setUp(self):
        super().setUp()
        self.cfg.spaces["code"].repos["web"] = self.make_repo("web")
        self.both = self.card(repo="api,web", options={"branch": BRANCH})

    def test_a_draft_opens_in_each_repo_that_is_pushed_and_the_other_is_skipped_and_said(self):
        self.branch(BRANCH)
        self.branch(BRANCH, pushed=False, key="web")
        self.gh(NONE_OPEN, CREATED, answer("pr", "view", out=pull()))
        result = gh_pulls.open_drafts(self.both)
        self.assertEqual([one["repo"] for one in result["opened"]], ["api"])
        self.assertEqual(result["skipped"], [{"repo": "web", "why": f"branch {BRANCH} is not on the remote "
                                                                    f"yet: push it first"}])
        self.assertEqual(self.kb.options, [("c-41", "pr", 12), ("c-41", "prs", {"api": {"pr": 12, "branch": BRANCH}})])
        self.assertEqual(self.kb.notes, [("c-41", f"api draft pull request #12: {URL}")])

    def test_approve_marks_every_repo_s_draft_ready_and_lists_each(self):
        card = dict(self.both, options={"branch": BRANCH, "pr": 12, "prs": {
            "api": {"pr": 12, "branch": BRANCH}, "web": {"pr": 5, "branch": BRANCH}}})
        self.gh(answer("pr", "view", "5", out=pull(number=5, repo="web", head="b" * 40)),
                answer("pr", "view", out=pull(head="a" * 40)), answer("pr", "ready"))
        result = gh_pulls.publish(self.tapped(card))
        # both are read before either is marked, so one that cannot be marked stops both
        self.assertEqual([call[:3] for call in self.calls()[:2]], [["pr", "view", "12"], ["pr", "view", "5"]])
        self.assertEqual(self.calls()[2:], [["pr", "ready", "12", "-R", REPO],
                                            ["pr", "ready", "5", "-R", "github.com/octo/web"]])
        self.assertEqual(result["heads"], {"api": "a" * 40, "web": "b" * 40})
        self.assertEqual([(one["repo"], one["pr"]) for one in result["prs"]], [("api", 12), ("web", 5)])

    def test_one_repo_with_no_pull_request_refuses_the_whole_and_marks_none(self):
        card = dict(self.both, options={"branch": BRANCH, "pr": 12})
        self.gh(NONE_OPEN, answer("pr", "view", out=pull()), answer("pr", "ready"))
        with self.assertRaisesRegex(GithubError, "has no pull request in web to mark ready"):
            gh_pulls.publish(self.tapped(card))
        self.assertFalse([call for call in self.calls() if call[:2] == ["pr", "ready"]])


class ReadyAndBodyTest(PullCase):
    def test_ready_marks_the_draft_ready(self):
        self.gh(answer("pr", "view", out=pull()), answer("pr", "ready"))
        (done,) = gh_pulls.make_ready(self.opened)
        self.assertEqual(self.calls(), [VIEW_CALL, ["pr", "ready", "12", "-R", REPO]])
        self.assertEqual((done["id"], done["draft"], done["repo"]), (12, False, "api"))

    def test_one_already_ready_is_left_alone(self):
        self.gh(answer("pr", "view", out=pull(draft=False)), answer("pr", "ready"))
        gh_pulls.make_ready(self.opened)
        self.assertEqual(self.calls(), [VIEW_CALL])

    def test_one_whose_state_github_does_not_name_is_never_marked(self):
        self.gh(answer("pr", "view", out=pull(state="LOCKED_AWAY")), answer("pr", "ready"))
        with self.assertRaisesRegex(GithubError, "GitHub did not say whether pull request #12 of octo/api is open"):
            gh_pulls.make_ready(self.opened)
        self.assertEqual(self.calls(), [VIEW_CALL])

    def test_one_closed_on_github_is_refused(self):
        self.gh(answer("pr", "view", out=pull(state="CLOSED")))
        with self.assertRaisesRegex(GithubError, "closed on GitHub without being merged"):
            gh_pulls.make_ready(self.opened)

    def test_body_puts_the_records_body_on_the_pull_request(self):
        self.record("## PR body\n\n```copy\nThe final words.\n```\n")
        self.gh(answer("pr", "edit"))
        gh_pulls.refresh_bodies(self.opened)
        self.assertEqual(self.calls(), [["pr", "edit", "12", "-R", REPO, "--body-file", "-"]])
        self.assertEqual(self.records()[0]["stdin"], "The final words.")

    def test_body_is_refused_while_the_record_has_none(self):
        self.gh(answer("pr", "edit"))
        with self.assertRaisesRegex(GithubError, "has no PR body in context.md yet"):
            gh_pulls.refresh_bodies(self.opened)
        self.assertEqual(self.calls(), [])


class PublishableTest(PullCase):
    def test_a_branch_not_on_the_remote_is_not_publishable(self):
        self.branch(BRANCH, pushed=False)
        self.gh()
        self.assertIn(f"branch {BRANCH} is not on the remote", gh_pulls.missing(self.fresh))
        self.assertEqual(self.calls(), [])

    def test_commits_the_remote_does_not_have_are_not_publishable(self):
        self.commit(self.branch(BRANCH))
        self.gh()
        self.assertIn("has commits the remote does not", gh_pulls.missing(self.opened))

    def test_no_open_pull_request_is_not_publishable(self):
        self.branch(BRANCH)
        self.gh(NONE_OPEN)
        self.assertIn(f"no pull request is open from {BRANCH}", gh_pulls.missing(self.fresh))

    def test_pushed_with_an_open_pull_request_is_publishable_and_the_one_found_is_recorded(self):
        self.branch(BRANCH)
        self.gh(ONE_OPEN)
        self.assertIsNone(gh_pulls.missing(self.fresh))
        self.assertEqual(self.kb.options, [("c-41", "pr", 12)])

    def test_the_deck_s_line_for_a_card_at_the_gate_with_no_pull_request(self):
        self.assertIn("no pull request is open for it", gh_pulls.unpublished(self.card(stage="review")))
        self.assertIsNone(gh_pulls.unpublished(self.card(stage="review", options={"pr": 12})))


class PublishTest(PullCase):
    def test_approve_marks_it_ready_and_answers_shipping_with_the_head(self):
        self.gh(answer("pr", "view", out=pull(head="f" * 40)), answer("pr", "ready"))
        result = gh_pulls.publish(self.tapped(self.opened))
        self.assertEqual(result, {"pr": 12, "url": URL, "draft": False, "shipping": True,
                                  "heads": {"api": "f" * 40}})
        self.assertEqual(self.kb.notes, [("c-41", f"published: pull request #12 ready for review ({URL})")])
        self.assertEqual(self.calls(), [VIEW_CALL, ["pr", "ready", "12", "-R", REPO]])

    def test_a_research_card_publishes_nothing_and_asks_github_nothing(self):
        self.gh()
        result = gh_pulls.publish(self.tapped(self.card(options={"kind": "research"})))
        self.assertEqual(result, {"published": "nothing", "kind": "research"})
        self.assertEqual(self.calls(), [])

    def test_at_shipping_publish_runs_only_inside_ship_and_pr_never(self):
        self.gh()
        shipping = self.card(stage="shipping", options={"branch": BRANCH, "pr": 12})
        for name, argv in (("publish", ["c-41"]), ("pr", ["c-41", "--draft"])):
            code, _, err = self.verb(name, *argv, card=shipping)
            self.assertEqual((code, "only your Ship pushes" in err), (1, True), name)
        self.assertEqual(self.calls(), [])

    def test_the_engine_s_own_publish_works_for_a_card_at_review_and_pr_ready_never(self):
        """r1.F3, r1.F14: Approve outcome runs `publish` as a process of the engine's own.
        c-738 r1.F2: `pr --ready` is refused by the verb itself, at every stage, and asks
        GitHub nothing: only `publish` marks a draft ready."""
        at_review = dict(self.opened, stage="review")
        self.gh(answer("pr", "view", out=pull()), answer("pr", "ready"))
        code, out, err = self.verb("publish", "c-41", card=self.tapped(at_review))
        self.assertEqual((code, err), (0, ""))
        self.assertIn('"shipping": true', out)
        for card in (self.opened, at_review):
            code, out, err = self.verb("pr", "c-41", "--ready", card=card)
            self.assertEqual((code, out), (1, ""))
            self.assertIn("Approve outcome", err)
            # c-738 r1.F3: outside the user's tap (no marker the handed nonce matches) publish is refused
            for outside in (card, dict(card, options={**card["options"], "kind": "research"})):
                code, out, err = self.verb("publish", "c-41", card=outside)
                self.assertEqual((code, out, "inside your Approve outcome or your Ship" in err), (1, "", True))
        self.assertEqual([call[:2] for call in self.calls()].count(["pr", "ready"]), 1)


if __name__ == "__main__":
    unittest.main()
