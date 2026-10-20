"""`ship <id> poll` and its neighbours: what GitHub says about a card's pull request, in the
engine's words, and the exact gh calls that read it. The sight is handed to the engine's
own reader (`shipwatch.fold`), so a change on the engine's side that parts them fails here.
"""

import unittest
from datetime import datetime, timezone

from ghfake import GhCase, answer, git

import gh_layer as gh_host
from gh_cli import GithubError
from keel.packkit import sight as gh_sight
from keel.packkit import verbs as gh_main
from keel import shipwatch

BRANCH = "shipyard/c-41-tidy-the-loader"
REPO = "github.com/octo/api"
SIGHT_FIELDS = ("number,url,isDraft,title,state,headRefOid,headRefName,baseRefName,isCrossRepository,"
                "author,statusCheckRollup")
SIGHT_KEYS = {"state", "draft", "url", "head", "base", "behind", "comments", "reviews", "approvals", "ci"}
MINE_KEYS = {"repo", "pr", "title", "branch", "draft", "updated", "url", "worktree", "cards", "matched_by"}
URL = "https://github.com/octo/api/pull/12"
LINES, TALK, REVIEWS = (f"repos/octo/api/{part}" for part in
                        ("pulls/12/comments", "issues/12/comments", "pulls/12/reviews"))
PAGED = ["api", "--hostname", "github.com", "--paginate"]


def who(name: str, kind: str = "User") -> dict:
    return {"login": name, "type": kind}


def pull(state: str = "OPEN", draft: bool = False, checks=(), base: str = "main", number: int = 12,
         repo: str = "api") -> dict:
    return {"number": number, "url": f"https://github.com/octo/{repo}/pull/{number}", "isDraft": draft,
            "title": "Tidy the loader", "state": state, "headRefOid": "abc123", "headRefName": BRANCH,
            "baseRefName": base, "author": {"login": "octo-dev"}, "statusCheckRollup": list(checks)}


def threads(*nodes: dict, more: str | None = None) -> dict:
    return {"data": {"repository": {"pullRequest": {"reviewThreads": {
        "nodes": list(nodes), "pageInfo": {"hasNextPage": bool(more), "endCursor": more}}}}}}


def thread(name: str, resolved: bool, *ids: int, more: str | None = None) -> dict:
    return {"id": name, "isResolved": resolved, "comments": {
        "nodes": [{"databaseId": one} for one in ids], "pageInfo": {"hasNextPage": bool(more), "endCursor": more}}}


TALKED = [
    {"id": 101, "user": who("ana"), "body": "Looks close.", "created_at": "2026-10-01T10:00:00Z",
     "updated_at": "2026-10-01T10:05:00Z"},
    {"id": 102, "user": who("octo-dev"), "body": "Thanks.", "created_at": "2026-10-01T10:06:00Z"},
    {"id": 103, "user": who("coverage[bot]", "Bot"), "body": "Coverage 91%.", "created_at": "2026-10-01T10:07:00Z"},
]
ON_LINES = [
    {"id": 201, "user": who("ana"), "body": "Why 40?", "path": "loader.py", "line": 7,
     "in_reply_to_id": None, "created_at": "2026-10-01T10:01:00Z", "updated_at": "2026-10-01T10:01:00Z"},
    {"id": 202, "user": who("ben"), "body": "Old thread.", "path": "loader.py", "line": None,
     "original_line": 3, "in_reply_to_id": None, "created_at": "2026-10-01T09:00:00Z"},
    {"id": 203, "user": who("octo-dev"), "body": "Page size.", "path": "loader.py", "line": 7,
     "in_reply_to_id": 201, "created_at": "2026-10-01T10:02:00Z"},
    {"id": 205, "user": who("ana"), "body": "Then name it.", "path": "loader.py", "line": 7,
     "in_reply_to_id": 201, "created_at": "2026-10-01T10:02:30Z"},
]
THREADS = threads(thread("T1", True, 202), thread("T2", False, 201, 203, 205))
SUBMITTED = [
    {"id": 301, "user": who("ana"), "state": "CHANGES_REQUESTED", "body": "Two things before this goes.",
     "submitted_at": "2026-10-01T10:03:00Z"},
    {"id": 302, "user": who("ben"), "state": "APPROVED", "body": "", "submitted_at": "2026-10-01T09:30:00Z"},
    {"id": 303, "user": who("cy"), "state": "APPROVED", "body": "", "submitted_at": "2026-10-01T09:40:00Z"},
    {"id": 304, "user": who("cy"), "state": "DISMISSED", "body": "", "submitted_at": "2026-10-01T09:50:00Z"},
    {"id": 305, "user": who("ana"), "state": "COMMENTED", "body": "", "submitted_at": "2026-10-01T10:04:00Z"},
]


class SightCase(GhCase):
    def setUp(self):
        super().setUp()
        self.tree = self.branch(BRANCH)
        self.shipping = self.card(stage="shipping", options={"branch": BRANCH, "pr": 12,
                                                             "worktree": str(self.tree)})

    def plan(self, *first: dict, talked=TALKED, lines=ON_LINES, **over) -> None:
        self.gh(*first, answer("pr", "view", out=pull(**over)), answer("api", "graphql", out=THREADS),
                answer("api", LINES, out=lines), answer("api", TALK, out=talked),
                answer("api", REVIEWS, out=SUBMITTED))


class PollTest(SightCase):
    def test_poll_reads_the_pull_request_with_these_gh_calls(self):
        self.plan()
        gh_sight.sight(self.shipping)
        calls = self.calls()
        self.assertEqual(calls[0], ["pr", "view", "12", "-R", REPO, "--json", SIGHT_FIELDS])
        self.assertEqual(calls[1], [*PAGED, LINES])
        self.assertEqual(calls[2][:4] + calls[2][-6:],
                         ["api", "graphql", "--hostname", "github.com", "-f", "owner=octo", "-f", "name=api",
                          "-F", "number=12"])
        self.assertEqual(calls[3:], [[*PAGED, REVIEWS], [*PAGED, TALK]])

    def test_the_sight_is_other_people_s_live_words_their_standing_reviews_and_the_checks(self):
        self.plan()
        sight = gh_sight.sight(self.shipping)
        self.assertEqual(set(sight), SIGHT_KEYS)
        self.assertEqual((sight["state"], sight["draft"], sight["url"], sight["head"], sight["base"]),
                         ("open", False, URL, "abc123", "main"))
        # the author's own (102, 203), the bot's (103) and the resolved thread's (202) are left
        # out; the words a review was submitted with (301) arrive as a comment. Each kind
        # has an id space of its own: g for the conversation, l for a line, r for a review
        self.assertEqual([c["id"] for c in sight["comments"]], ["g101", "l201", "l205", "r301"])
        self.assertEqual(sight["comments"][1], {
            "id": "l201", "author": "ana", "at": "2026-10-01T10:01:00Z", "text": "Why 40?",
            "path": "loader.py", "line": 7, "parent": None, "updated": "2026-10-01T10:01:00Z"})
        # a reply names the comment it is under by that comment's HANDLE, which is what the
        # house is told and can look up
        self.assertEqual(sight["comments"][2]["parent"], "cl201")
        self.assertEqual(sight["comments"][0]["updated"], "2026-10-01T10:05:00Z")
        # ana asks for changes, ben approved, cy's approval was dismissed
        self.assertEqual({r["author"]: r["state"] for r in sight["reviews"]},
                         {"ana": "changes_requested", "ben": "approved"})
        self.assertEqual(sight["approvals"], 1)
        self.assertEqual(sight["ci"], {"state": "none"})
        self.assertEqual(sight["behind"], 0)

    def test_one_number_in_two_of_github_s_id_spaces_is_two_comments_with_two_handles(self):
        """r1.F10: a general comment, a line comment and a review may share a number."""
        same = [dict(TALKED[0], id=201)]
        self.plan(talked=same)
        sight = gh_sight.sight(self.shipping)
        self.assertEqual([c["id"] for c in sight["comments"]], ["g201", "l201", "l205", "r301"])
        now = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
        shipped, _ = shipwatch.fold({"since": "2026-09-30T00:00:00+00:00"}, sight, now)
        self.assertEqual(sorted(item["handle"] for item in shipped["pending"]),
                         ["cg201", "cl201", "cl205", "cr301", "review-ana"])

    def test_comments_come_in_the_order_they_were_said(self):
        """r2.F11: by when, not by how the ids sort (`g10` before `g9`)."""
        said = [dict(TALKED[0], id=10, created_at="2026-10-01T10:30:00Z"),
                dict(TALKED[0], id=9, created_at="2026-10-01T09:00:00Z")]
        self.plan(talked=said)
        self.assertEqual([c["id"] for c in gh_sight.sight(self.shipping)["comments"]],
                         ["g9", "l201", "l205", "r301", "g10"])

    def test_a_state_github_does_not_name_is_no_sight_at_all(self):
        self.plan(state="LOCKED_AWAY")
        with self.assertRaisesRegex(GithubError, "GitHub did not say whether pull request #12 of octo/api is open"):
            gh_sight.sight(self.shipping)

    def test_the_engine_s_own_reader_takes_the_sight(self):
        self.plan()
        now = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
        shipped, events = shipwatch.fold({"since": "2026-09-30T00:00:00+00:00"}, gh_sight.sight(self.shipping), now)
        self.assertEqual(events, [])
        self.assertEqual(sorted(item["handle"] for item in shipped["pending"]),
                         ["cg101", "cl201", "cl205", "cr301", "review-ana"])
        self.assertEqual(shipped["facts"]["approvals"], 1)
        again, _ = shipwatch.fold(shipped, gh_sight.sight(self.shipping), now)
        self.assertEqual(len(again["pending"]), len(shipped["pending"]))
        self.assertEqual(sorted(shipwatch.whole_texts(gh_sight.sight(self.shipping))),
                         ["cg101.md", "cl201.md", "cl205.md", "cr301.md"])

    def test_merged_and_closed_are_said_in_the_engine_s_words(self):
        for theirs, ours in (("MERGED", "merged"), ("CLOSED", "declined"), ("OPEN", "open")):
            self.log.unlink(missing_ok=True)
            self.plan(state=theirs)
            self.assertEqual(gh_sight.sight(self.shipping)["state"], ours)

    def test_behind_counts_the_base_s_commits_the_branch_lacks(self):
        other = self.dir / "trees" / "mainline"
        git(self.repo, "worktree", "add", "-q", "-b", "mainline", str(other), "origin/main")
        self.commit(other, "landed.txt")
        git(other, "push", "-q", "origin", "mainline:main")
        self.plan()
        self.assertEqual(gh_sight.sight(self.shipping)["behind"], 1)

    def test_a_base_github_names_that_is_no_branch_name_never_reaches_git(self):
        """r1.F8: the base a pull request names comes from GitHub, and is checked like the card's."""
        self.plan(base="--upload-pack=x")
        self.forget_git()
        self.assertIsNone(gh_sight.sight(self.shipping)["behind"])
        self.assertFalse([call for call in self.git_calls() if any("upload-pack" in word for word in call)])

    def test_a_card_with_no_pull_request_is_refused(self):
        self.gh()
        with self.assertRaisesRegex(GithubError, "has no pull request"):
            gh_sight.sight(self.card(stage="shipping"))

    def test_a_card_with_a_pull_request_in_each_of_two_repos_is_seen_as_both(self):
        """r1.F14: the aggregate is merged only when all are, and declined when any is."""
        self.cfg.spaces["code"].repos["web"] = self.make_repo("web")
        self.branch(BRANCH, key="web")
        both = self.card(repo="api,web", stage="shipping", options={
            "branch": BRANCH, "pr": 12, "prs": {"api": {"pr": 12, "branch": BRANCH},
                                                "web": {"pr": 5, "branch": BRANCH}}})
        web = (answer("api", "repos/octo/web/pulls/5/comments", out=[]),
               answer("api", "repos/octo/web/issues/5/comments", out=[]),
               answer("api", "repos/octo/web/pulls/5/reviews", out=[]))
        self.plan(answer("pr", "view", "5", out=pull(state="MERGED", number=5, repo="web")), *web)
        sight = gh_sight.sight(both)
        self.assertEqual((sight["state"], sight["url"]), ("open", URL))
        self.assertEqual([(p["repo"], p["pr"], p["primary"], p["state"]) for p in sight["prs"]],
                         [("api", 12, True, "open"), ("web", 5, False, "merged")])
        self.assertEqual(set(sight["prs"][1]), SIGHT_KEYS | {"repo", "pr", "primary"})
        self.plan(answer("pr", "view", "5", out=pull(state="CLOSED", number=5, repo="web")), *web)
        self.assertEqual(gh_sight.sight(both)["state"], "declined")
        self.plan(answer("pr", "view", "5", out=pull(state="MERGED", number=5, repo="web")), *web, state="MERGED")
        self.assertEqual(gh_sight.sight(both)["state"], "merged")


class ResolvedTest(GhCase):
    """r1.F11: the resolved threads are read to the end, however many there are."""

    def test_threads_past_the_first_page_and_comments_past_a_thread_s_first_page_are_read(self):
        self.gh(answer("api", "graphql", "id=T9", "after=C2", out={"data": {"node": {"comments": {
                    "nodes": [{"databaseId": 903}], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}),
                answer("api", "graphql", "id=T9", out={"data": {"node": {"comments": {
                    "nodes": [{"databaseId": 902}], "pageInfo": {"hasNextPage": True, "endCursor": "C2"}}}}}),
                answer("api", "graphql", "after=CUR1", out=threads(thread("T9", True, 901, more="C1"),
                                                                    thread("T8", False, 801, more="C9"))),
                answer("api", "graphql", out=threads(thread("T1", True, 202), thread("T2", False, 201),
                                                     more="CUR1")))
        self.assertEqual(gh_host.resolved("octo/api", 12), {202, 901, 902, 903})
        calls = self.calls()
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[1][-2:], ["-f", "after=CUR1"])
        self.assertEqual([calls[2][-4:], calls[3][-4:]],
                         [["-f", "id=T9", "-f", "after=C1"], ["-f", "id=T9", "-f", "after=C2"]])

    def test_a_listing_that_never_ends_is_refused_rather_than_read_as_whole(self):
        self.gh(answer("api", "graphql", out=threads(thread("T1", True, 202), more="AGAIN")))
        with self.assertRaisesRegex(GithubError, "more review threads than can be read"):
            gh_host.resolved("octo/api", 12)


class ChecksTest(unittest.TestCase):
    def test_the_head_s_checks_as_one_word(self):
        run = lambda status, conclusion: {"__typename": "CheckRun", "name": "tests", "status": status,   # noqa: E731
                                          "conclusion": conclusion, "detailsUrl": "https://ci/1",
                                          "completedAt": "2026-10-01T11:00:00Z"}
        status = lambda state: {"__typename": "StatusContext", "context": "lint", "state": state,       # noqa: E731
                                "targetUrl": "https://ci/2"}
        self.assertEqual(gh_host.checks_of([]), {"state": "none"})
        self.assertEqual(gh_host.checks_of([run("COMPLETED", "SUCCESS"), run("COMPLETED", "SKIPPED"),
                                             status("SUCCESS")]), {"state": "passed"})
        self.assertEqual(gh_host.checks_of([run("COMPLETED", "SUCCESS"), run("IN_PROGRESS", "")]),
                         {"state": "running"})
        self.assertEqual(gh_host.checks_of([status("PENDING")]), {"state": "running"})
        self.assertEqual(gh_host.checks_of([run("IN_PROGRESS", ""), run("COMPLETED", "FAILURE")]),
                         {"state": "failed", "name": "tests", "url": "https://ci/1",
                          "at": "2026-10-01T11:00:00Z"})
        self.assertEqual(gh_host.checks_of([status("ERROR")])["name"], "lint")


class MineAndLinksTest(SightCase):
    def test_mine_lists_the_account_s_open_pull_requests_matched_to_cards_by_branch(self):
        self.gh(answer("pr", "list", out=[
            {"number": 12, "title": "Tidy the loader", "headRefName": BRANCH, "isDraft": False,
             "updatedAt": "2026-10-01T10:00:00Z", "url": URL},
            {"number": 15, "title": "By hand", "headRefName": "by-hand", "isDraft": True,
             "updatedAt": "2026-10-01T11:00:00Z", "url": "https://github.com/octo/api/pull/15"}]))
        found = gh_sight.mine([self.shipping, self.card(id="c-42", options={"archived": True, "branch": "by-hand"})],
                              "code")["prs"]
        self.assertEqual(self.calls(), [["pr", "list", "-R", REPO, "--author", "@me", "--state", "open", "--json",
                                         "number,title,headRefName,isDraft,updatedAt,url", "--limit", "100"]])
        self.assertEqual([set(row) for row in found], [MINE_KEYS, MINE_KEYS])
        self.assertEqual((found[0]["cards"], found[0]["matched_by"], found[0]["worktree"]),
                         (["c-41"], "branch", str(self.tree)))
        self.assertEqual((found[1]["cards"], found[1]["matched_by"], found[1]["worktree"]), ([], None, None))

    def test_the_deck_s_links_are_built_without_asking_github(self):
        self.gh()
        self.assertEqual(gh_main.links_for(self.shipping),
                         {"pr": URL, "prs": [{"repo": "api", "pr": 12, "url": URL}]})
        self.assertEqual(self.records(), [])


class DiffAndReapTest(SightCase):
    def test_diff_is_the_branch_against_its_base(self):
        self.gh()
        self.assertIn("+change.txt", gh_sight.diff(self.shipping))

    def test_reap_takes_a_done_card_s_clean_worktree_and_keeps_one_with_changes(self):
        self.gh()
        done = dict(self.shipping, stage="done")
        (self.tree / "scratch.txt").write_text("not committed\n")
        kept = gh_sight.reap(done)
        self.assertEqual((kept["removed"], kept["kept"][0]["why"]), ([], "it has uncommitted changes"))
        (self.tree / "scratch.txt").unlink()
        self.assertEqual(gh_sight.reap(done), {"removed": [str(self.tree)], "kept": []})
        self.assertFalse(self.tree.exists())

    def test_reap_is_only_for_a_done_card_and_never_takes_the_clone_itself(self):
        self.gh()
        with self.assertRaisesRegex(GithubError, "only a done card's worktree is reaped"):
            gh_sight.reap(self.shipping)
        clone = self.card(stage="done", options={"worktree": str(self.repo)})
        self.assertEqual(gh_sight.reap(clone)["kept"][0]["why"], "git does not list it as a worktree of api")
        self.assertTrue((self.repo / ".git").exists())

    def test_down_has_nothing_to_stop(self):
        self.assertEqual(gh_sight.down(self.shipping), {"down": [], "failed": [], "worktrees": [str(self.tree)]})


if __name__ == "__main__":
    unittest.main()
