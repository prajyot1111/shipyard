"""`worktree` and `brief`: where a card's house works and what it is told (what it is
fenced from is `test_gh_fence`). And the pack itself: that it loads, what it declares, and that a new
install lists it and draws the general flow for a space on it.
"""

import subprocess
import unittest

from ghfake import PACK, GhCase, answer, default_branch, git

from gh_cli import GithubError
from keel.packkit import brief as gh_brief
from keel.packkit import cut as gh_cut
from keel import flows, packs, packsetup, readiness, terms

BRANCH = "shipyard/c-41-tidy-the-loader"


class WorktreeTest(GhCase):
    def test_the_worktree_is_cut_from_the_remote_s_base_on_the_branch_keel_names(self):
        self.gh()
        (tree,) = gh_cut.worktrees_for(self.card())
        self.assertEqual(tree, self.cfg.worktrees_dir / "c-41")
        self.assertEqual(git(tree, "rev-parse", "--abbrev-ref", "HEAD"), BRANCH)
        self.assertEqual(git(tree, "rev-parse", "HEAD"), git(self.repo, "rev-parse", "origin/main"))
        self.assertEqual(self.kb.options, [("c-41", "branch", BRANCH), ("c-41", "worktree", str(tree))])

    def test_the_new_branch_does_not_track_the_base_so_a_bare_push_cannot_be_aimed_at_it(self):
        self.gh()
        (tree,) = gh_cut.worktrees_for(self.card())
        upstream = subprocess.run(["git", "-C", str(tree), "rev-parse", "--abbrev-ref", "@{upstream}"],
                                  capture_output=True, text=True)
        self.assertNotEqual(upstream.returncode, 0, upstream.stdout)

    def test_the_cut_is_from_the_default_branch_github_names_not_the_clone_s_record(self):
        """r2.F9: the clone records `main` as the default; the repository's default is now
        `trunk-2`, which has a commit main lacks."""
        other = self.dir / "trees" / "trunk"
        git(self.repo, "worktree", "add", "-q", "-b", "trunk-2", str(other), "origin/main")
        newer = self.commit(other, "on-trunk.txt")
        git(other, "push", "-q", "origin", "trunk-2")
        self.gh(default_branch("trunk-2"))
        (tree,) = gh_cut.worktrees_for(self.card())
        self.assertEqual(git(tree, "rev-parse", "HEAD"), newer)

    def test_a_default_branch_github_cannot_name_cuts_nothing_and_says_try_again(self):
        self.gh(answer("repo", "view", "defaultBranchRef", code=1, err="error connecting to api.github.com\n"))
        with self.assertRaisesRegex(GithubError, "so nothing is cut, pushed or opened on a guess; try again"):
            gh_cut.worktrees_for(self.card())
        self.assertFalse((self.cfg.worktrees_dir / "c-41").exists())

    def test_the_brief_still_reads_the_clone_s_record_when_github_cannot_be_asked(self):
        """A read-only verb may fall back: the brief names a base without gh."""
        self.assertIn("cut from `origin/main`", gh_brief.compose(self.card(options={"branch": BRANCH}), ["/t"]))

    def test_a_worktree_already_there_is_reused(self):
        self.gh()
        first = gh_cut.worktrees_for(self.card())
        again = gh_cut.worktrees_for(self.card(options={"branch": BRANCH, "worktree": str(first[0])}))
        self.assertEqual(first, again)
        self.assertEqual(len(self.kb.options), 2)

    def test_a_card_is_never_cut_on_a_shared_branch(self):
        self.gh()
        with self.assertRaisesRegex(GithubError, "main is a shared branch of api"):
            gh_cut.worktrees_for(self.card(options={"branch": "main"}))

    def test_a_card_with_no_repo_needs_no_worktree(self):
        with self.assertRaisesRegex(GithubError, "has no repo"):
            gh_cut.worktrees_for(self.card(repo=""))

    def test_a_base_that_is_not_a_branch_name_never_reaches_git(self):
        """r1.F8: `options.base` is free text, and git would read this one as an option."""
        self.gh()
        self.forget_git()
        with self.assertRaisesRegex(GithubError, "--upload-pack=x.*is not a branch name"):
            gh_cut.worktrees_for(self.card(options={"base": "--upload-pack=x"}))
        self.assertFalse([call for call in self.git_calls() if "--upload-pack=x" in call])
        self.assertFalse((self.cfg.worktrees_dir / "c-41").exists())

    def test_a_branch_that_is_not_a_branch_name_never_reaches_git(self):
        self.gh()
        for bad in ("--detach", ":main", "+main", "a b", "a..b"):
            self.forget_git()
            with self.assertRaisesRegex(GithubError, "is not a branch name"):
                gh_cut.worktrees_for(self.card(options={"branch": bad}))
            self.assertFalse([call for call in self.git_calls() if bad in call and call[0] != "check-ref-format"])


class BriefTest(GhCase):
    def brief(self, card: dict) -> str:
        """The brief as one run of words: where a line wraps is not what it says."""
        return " ".join(gh_brief.compose(card, ["/trees/c-41"]).split())

    def test_the_brief_names_the_branch_the_push_the_draft_and_what_is_never_the_house_s(self):
        said = self.brief(self.card(options={"branch": BRANCH}))
        for part in ("`/trees/c-41` on branch `shipyard/c-41-tidy-the-loader`, cut from `origin/main`",
                     f"git push -u origin {BRANCH}", f"{PACK / 'pr'} c-41 --draft",
                     "Approve outcome marks it ready"):
            self.assertIn(part, said)

    def test_the_brief_says_what_reads_each_command_and_that_it_is_no_wall(self):
        """r1.F2: the house text may not promise more than the guard holds."""
        said = " ".join(self.brief(self.card(options={"branch": BRANCH})).split())
        self.assertNotIn("each is refused if you try", said)
        self.assertIn("Keel reads each command before it runs", said)
        self.assertIn("It is a fence, not a wall", said)

    def test_a_house_at_shipping_is_told_never_to_push(self):
        said = self.brief(self.card(stage="shipping", options={"branch": BRANCH}))
        self.assertIn("never push: it is refused at shipping", said)
        self.assertNotIn("git push -u", said)


class ShortClockTest(GhCase):
    """A verb that only reads gives GitHub a short clock for the default branch, then takes
    the clone's record; a verb that writes waits the whole clock and takes no other answer."""

    def asked(self, **kwargs) -> list:
        from unittest import mock

        import gh_layer as gh_host
        from keel.packkit import shared as gh_shared
        gh_shared.forget()
        with mock.patch.object(gh_host, "default_branch", return_value="main") as asked:
            gh_shared.base_in(self.card(), "api", **kwargs)
        return [call.kwargs for call in asked.call_args_list]

    def test_a_read_asks_with_five_seconds_and_a_write_with_the_whole_clock(self):
        import gh_cli
        from keel.packkit import shared as gh_shared
        self.assertEqual(gh_shared.READ_SECONDS, 5)
        self.assertEqual(self.asked(), [{"timeout": 5}])
        self.assertEqual(self.asked(writing=True), [{"timeout": gh_cli.SECONDS}])

    def test_the_clock_reaches_gh_itself(self):
        from unittest import mock

        import gh_layer as gh_host
        from keel.packkit import cli as kit_cli
        self.gh()
        with mock.patch.object(kit_cli.subprocess, "run", wraps=kit_cli.subprocess.run) as ran:
            self.assertEqual(gh_host.default_branch("octo/api", timeout=5), "main")
        self.assertEqual(ran.call_args.kwargs["timeout"], 5)

    def test_a_read_that_github_does_not_answer_in_time_names_the_clone_s_base(self):
        from unittest import mock

        import gh_layer as gh_host
        from keel.packkit import shared as gh_shared
        gh_shared.forget()
        slow = GithubError("gh repo view gave no answer in 5 seconds")
        with mock.patch.object(gh_host, "default_branch", side_effect=slow):
            self.assertEqual(gh_shared.base_in(self.card(), "api"), "main")
            with self.assertRaises(GithubError):
                gh_shared.base_in(self.card(), "api", writing=True)


class PackTest(GhCase):
    def test_the_pack_loads_and_declares_a_code_host_and_reviews_that_start_off(self):
        pack = packs.read(PACK)
        self.assertEqual(pack.capabilities, frozenset({"codehost", "reviews"}))   # c-730: reviews too
        self.assertEqual(pack.routes, ("reviews",))
        self.assertEqual(pack.space.get("review_scan"), False)      # a space asks for them, or has none
        self.assertEqual([step.id for step in pack.setup], ["connect"])
        for verb in ("worktree", "brief", "guard", "pr", "publishable", "publish", "ship", "act", "logins",
                     "review", "providers/reviews"):
            self.assertTrue(packs.executable(PACK, verb), verb)
        self.assertEqual(pack.guard_tools, ("gh",))
        self.assertFalse(packs.executable(PACK, "deny"), "the guard reads commands; no deny list is handed out")

    def test_each_requirement_comes_back_from_the_engine_with_its_own_fix(self):
        """c-688: `packs.checks` returns a requirement's `fix`, `command` and `done_when`, so
        Setup, the first-run step and doctor can show them. A `command` is written only
        where one line really does the fix."""
        rows = {row["name"]: row for row in packs.checks(packs.load(PACK))}
        self.assertEqual(list(rows), ["gh", "GitHub sign-in", "GitHub address", "GitHub access"])
        for name, row in rows.items():
            self.assertTrue(row.get("fix"), name)
        self.assertIn("brew install gh", rows["gh"]["fix"])
        self.assertEqual((rows["GitHub sign-in"]["command"], rows["GitHub sign-in"]["done_when"]),
                         ("gh auth login", "`gh auth status` names your account on github.com."))
        self.assertEqual(rows["gh"]["done_when"], "`gh --version` prints a version.")
        self.assertIn("github.com address", rows["GitHub address"]["done_when"])
        # no one line installs gh on every system, sets a remote without its address, or grants access
        self.assertEqual([name for name, row in rows.items() if "command" in row], ["GitHub sign-in"])
        self.assertEqual([name for name, row in rows.items() if "action" in row], [])
        # c-730: reviewing needs gh, the sign-in and a GitHub address; reading is enough, so
        # write access holds up only the code host
        self.assertEqual({name: row["for"] for name, row in rows.items()},
                         {"gh": ["codehost", "reviews"], "GitHub sign-in": ["codehost", "reviews"],
                          "GitHub address": ["codehost", "reviews"], "GitHub access": ["codehost"]})
        self.assertIn("review", rows["gh"]["why"])

    def test_a_new_install_lists_it_beside_the_packs_that_were_there(self):
        names = [pack.name for pack in packs.available(packs.PACKAGE)]
        for name in ("github", "sandbox"):      # the packs that ship with the core (c-722)
            self.assertIn(name, names)
        row = next(row for row in packsetup.rows(self.cfg)[0] if row["name"] == "github")
        self.assertEqual([check["name"] for check in row["checks"]],
                         ["gh", "GitHub sign-in", "GitHub address", "GitHub access"])
        # c-730: Where finished work goes asks about review requests under a pack that has them
        self.assertEqual(row["capabilities"], ["codehost", "reviews"])
        self.assertEqual(packsetup.example_space(packs.read(PACK)), {"pack": "github", "config_dir": "~/.claude"})

    def test_a_space_on_it_ships_by_keel_s_general_flow_in_github_s_words(self):
        space = self.cfg.spaces["code"]
        self.assertIsNone(readiness.refusal(self.cfg, space, "codehost"))
        self.assertTrue(flows.hosted(self.cfg, space))
        self.assertEqual(flows.default_of(self.cfg, space), flows.GENERAL)
        self.assertEqual(terms.of(self.cfg, "code")["codehost_name"], "GitHub")


if __name__ == "__main__":
    unittest.main()
