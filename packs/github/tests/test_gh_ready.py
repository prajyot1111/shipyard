"""What the GitHub pack needs on the machine: each requirement ready, and each one failing
with its reason and its fix; and gh's sign-in as a row of Keel's Logins list.

The requirements are run the way the engine runs them (`packs.checks`: each `[[requires]]`
check by `sh -c` in the pack's directory), and the specific sentences are read from
`gh_ready.rows`, which is what `./ready` prints. gh is the stand-in on PATH (`ghfake`).
"""

import os
import subprocess
import tomllib
import unittest
from unittest import mock

from ghfake import PACK, SLUG, GhCase, answer, git

import gh_ready
from keel.packkit import cli as kit_cli
from keel import packs

SIGNED_IN = answer("auth", "status")
SEES = answer("repo", "view", out={"nameWithOwner": SLUG, "viewerPermission": "WRITE"})
SIGNED_OUT = answer("auth", "status", code=1,
                    err="You are not logged into any GitHub hosts. To log in, run: gh auth login\n")
NOT_FOUND = answer("repo", "view", code=1,
                   err="GraphQL: Could not resolve to a Repository with the name 'octo/api'. (repository)\n")


class RequirementCase(GhCase):
    def setUp(self):
        super().setUp()
        self.patch(mock.patch.dict(os.environ, {"KEEL_SPACE_REPOS": str(self.repo)}))

    def checks(self) -> dict:
        """The pack's `[[requires]]` as the engine runs them: {name: ok}."""
        found = packs.checks(packs.read(PACK), {"KEEL_SPACE_REPOS": os.environ["KEEL_SPACE_REPOS"]})
        return {one["name"]: one["ok"] for one in found}

    def rows(self) -> dict:
        return {one["name"]: one for one in gh_ready.rows()}


class ReadyTest(RequirementCase):
    def test_all_four_are_ready_with_gh_installed_signed_in_and_able_to_see_the_repo(self):
        self.gh(SIGNED_IN, SEES)
        self.assertEqual(self.checks(), {"gh": True, "GitHub sign-in": True, "GitHub address": True,
                                         "GitHub access": True})
        self.assertEqual(self.calls(), [
            ["auth", "status", "--hostname", "github.com"],
            ["repo", "view", "github.com/octo/api", "--json", "nameWithOwner,viewerPermission"]])

    def test_a_space_with_no_repo_yet_has_no_address_or_access_to_fail(self):
        self.gh(SIGNED_IN)
        with mock.patch.dict(os.environ, {"KEEL_SPACE_REPOS": ""}):
            found = self.rows()
        self.assertTrue(found["address"]["ok"] and found["access"]["ok"])
        self.assertIn("no repo yet", found["address"]["why"])


class FailingTest(RequirementCase):
    def test_gh_missing_fails_with_the_install_line_for_macos_and_linux(self):
        self.assertEqual(self.checks(), {"gh": False, "GitHub sign-in": False, "GitHub address": True,
                                         "GitHub access": False})
        found = self.rows()
        self.assertIn("gh, GitHub's command line tool, is not installed", found["gh"]["why"])
        for line in ("brew install gh", "sudo apt install gh", "Shipyard never installs it for you"):
            self.assertIn(line, found["gh"]["fix"])
        self.assertIn("not installed yet", found["sign-in"]["why"])

    def test_not_signed_in_fails_with_the_terminal_sign_in(self):
        self.gh(SIGNED_OUT, SEES)
        self.assertEqual(self.checks()["GitHub sign-in"], False)
        found = self.rows()["sign-in"]
        self.assertIn("not signed in to GitHub", found["why"])
        self.assertIn("gh auth login", found["fix"])
        self.assertIn("sign in with your browser", found["fix"])

    def test_a_remote_that_is_not_github_fails_naming_the_repo_and_its_address(self):
        git(self.repo, "remote", "set-url", "origin", "https://gitlab.example/team/api.git")
        self.gh(SIGNED_IN, SEES)
        self.assertEqual(self.checks()["GitHub address"], False)
        found = self.rows()["address"]
        self.assertIn("api is not a GitHub repository", found["why"])
        self.assertIn("https://gitlab.example/team/api.git", found["why"])
        self.assertIn("remote set-url origin https://github.com/OWNER/REPO.git", found["fix"])

    def test_an_account_that_cannot_see_the_repo_fails_naming_both(self):
        self.gh(SIGNED_IN, NOT_FOUND, answer("api", "user", out="octo-other\n"))
        self.assertEqual(self.checks()["GitHub access"], False)
        found = self.rows()["access"]
        self.assertEqual(found["why"], "You are signed in to GitHub as octo-other, which cannot see octo/api.")
        for part in ("gh auth switch", "gh auth login", "give octo-other access"):
            self.assertIn(part, found["fix"])
        self.assertIn(["api", "--hostname", "github.com", "user", "--jq", ".login"], self.calls())

    def test_a_sign_in_that_cannot_be_checked_in_time_says_so(self):
        self.gh(SIGNED_IN)
        timed_out = subprocess.TimeoutExpired("gh", gh_ready.CALL_SECONDS)
        with mock.patch.object(kit_cli.subprocess, "run", side_effect=timed_out):
            found = gh_ready.signed_in()
        self.assertFalse(found["ok"])
        self.assertIn("could not be checked", found["why"])
        self.assertIn(f"gave no answer in {gh_ready.CALL_SECONDS} seconds", found["why"])

    def test_an_account_that_can_only_read_the_repo_fails_with_a_sentence_of_its_own(self):
        """r1.F9: seeing a repository is not being able to push to it."""
        for permission in ("READ", "TRIAGE"):
            self.gh(SIGNED_IN, answer("repo", "view", out={"nameWithOwner": SLUG, "viewerPermission": permission}),
                    answer("api", "user", out="octo-dev\n"))
            found = self.rows()["access"]
            self.assertEqual(found["why"], "You are signed in to GitHub as octo-dev, which can read octo/api "
                                           "but cannot push to it.")
            self.assertIn("write access", found["fix"])
            self.assertEqual(self.checks()["GitHub access"], False)

    def test_an_account_that_may_push_passes(self):
        for permission in ("WRITE", "MAINTAIN", "ADMIN"):
            self.gh(SIGNED_IN, answer("repo", "view", out={"nameWithOwner": SLUG, "viewerPermission": permission}))
            self.assertTrue(self.rows()["access"]["ok"], permission)

    def test_a_failure_that_is_not_github_s_not_found_never_blames_the_account(self):
        """r1.F9: a rate limit, a server error or the network is "could not be checked"."""
        for said in ("gh: API rate limit exceeded (HTTP 403)\n", "gh: Server Error (HTTP 502)\n",
                     "error connecting to api.github.com\n"):
            self.log.unlink(missing_ok=True)
            self.gh(SIGNED_IN, answer("repo", "view", code=1, err=said), answer("api", "user", out="octo-dev\n"))
            found = self.rows()["access"]
            self.assertFalse(found["ok"])
            self.assertIn("could not be checked", found["why"])
            self.assertNotIn("cannot see", found["why"])
            self.assertNotIn(["api", "--hostname", "github.com", "user", "--jq", ".login"], self.calls())

    def test_the_whole_access_check_stays_inside_the_engine_s_ten_seconds(self):
        """r1.F9: every gh call of the check, the account's name included, is on the short
        clock, and together they cannot outlast the engine's stop."""
        clocks, real = [], subprocess.run

        def timed(argv, **kwargs):
            if argv[0] == "gh":
                clocks.append(kwargs["timeout"])
            return real(argv, **kwargs)

        self.gh(SIGNED_IN, NOT_FOUND, answer("api", "user", out="octo-other\n"))
        with mock.patch.object(kit_cli.subprocess, "run", side_effect=timed):
            self.assertIn("octo-other", gh_ready.access()["why"])
        self.assertEqual(len(clocks), 2)
        self.assertLess(sum(clocks), packs.CHECK_SECONDS)


class ManifestTest(unittest.TestCase):
    def test_every_requirement_is_a_check_with_a_reason_and_a_fix(self):
        needs = tomllib.loads((PACK / "pack.toml").read_text())["requires"]
        self.assertEqual([need["check"] for need in needs],
                         [f"./ready {name}" for name in gh_ready.NAMES])
        for need in needs:
            for key in ("why", "fix"):
                self.assertTrue(need[key].strip().endswith("."), f"{need['name']} {key}")
            # c-730: reviewing reads, so write access holds up only the code host
            self.assertEqual(need["for"], ["codehost"] if need["name"] == "GitHub access" else ["codehost", "reviews"])


class LoginRowTest(GhCase):
    def row(self) -> dict:
        (found,) = gh_ready.login_rows()
        self.assertEqual(set(found), {"id", "label", "state", "why", "where", "fix"})
        return found

    def test_a_working_sign_in_is_good(self):
        self.gh(SIGNED_IN)
        self.assertEqual(self.row()["state"], "good")

    def test_no_sign_in_is_expired_with_the_command_that_brings_it_back(self):
        self.gh(SIGNED_OUT)
        found = self.row()
        self.assertEqual((found["state"], found["fix"]), ("expired", "gh auth login"))

    def test_no_gh_is_missing(self):
        found = self.row()
        self.assertEqual(found["state"], "missing")
        self.assertIn("brew install gh", found["fix"])

    def test_a_gh_that_cannot_answer_is_unknown_never_expired(self):
        self.gh(answer("auth", "status", code=1, err="error connecting to api.github.com\n"))
        self.assertEqual(self.row()["state"], "unknown")


if __name__ == "__main__":
    unittest.main()
