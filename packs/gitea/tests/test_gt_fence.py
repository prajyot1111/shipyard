"""Gitea's half of the guard (`gt_fence.py`): a call to Gitea's API is refused to a house,
however it is written, and git's credential helpers run by name are the sign-in's. The
refusals every pack's guard makes are the conformance suite's (`GiteaGuard`)."""

import unittest

import suitefence  # noqa: F401

import gt_fence
import test_conformance


def said(command: str) -> str | None:
    return gt_fence.problem(command, None, lambda: {"options": {}})


class ApiTest(unittest.TestCase):
    def test_curl_or_wget_to_the_api_is_refused_whatever_the_method(self):
        for command in ("curl https://box/api/v1/repos/octo/api/pulls",
                        "curl -X POST -d @x https://box/API/V1/repos/octo/api/issues/3/comments",
                        "wget -qO- http://box:3000/code/api/v1/user",
                        "echo x | bash -c 'curl https://box/api/v1/user'",
                        "env -u X curl https://box/api/v1/user"):
            self.assertIn("code host's API", said(command) or "", command)

    def test_curl_to_any_other_address_stays_open(self):
        for command in ("curl https://pypi.org/simple/", "wget https://box/octo/api/archive/main.zip",
                        'git commit -m "curl https://box/api/v1/user"'):
            self.assertIsNone(said(command), command)

    def test_through_xargs_the_address_cannot_be_read_and_is_refused(self):
        self.assertIn("xargs", said("echo https://box/api/v1/user | xargs curl") or "")

    def test_git_s_credential_helpers_by_name_are_the_sign_in_s(self):
        for command in ("git-credential-store get", "git credential-store erase"):
            self.assertIn("sign-in", said(command) or "", command)

    def test_a_line_it_cannot_read_is_refused_when_it_names_the_api(self):
        self.assertIn("could not be read", said("curl 'https://box/api/v1/user") or "")


WRITES = ("tea pulls merge 5", "tea pr close 3", "tea comment 3 'Looks good'", "tea pulls create --title x",
          "tea pulls approve 5", "tea issues close 2", "tea login add", "tea logins list", "tea repos delete x",
          "cd x && tea pr merge 5", "bash -c 'tea pulls merge 5'", "echo 5 | xargs tea pulls merge",
          "tea pulls merge --title --help 5", "tea pulls merge --message -h 5", "tea pulls merge 5 --help",
          "tea comment 3 --help", "tea issues --mentions list --comments close 3", "tea notifications -m read")
# what was once open to a house as a read, refused since r2.D3: a house reads with git
ONCE_READS = ("tea pulls list", "tea pulls", "tea pr ls --state all", "tea pulls 5", "tea issues list --repo o/r",
              "tea issues 7 --comments", "tea pulls list --output json", "tea whoami", "tea notifications",
              "tea --version", "tea help", "tea pulls list --help", "tea pulls --help --weird")
HELP = ("tea", "tea --help", "tea -h", "tea pulls --help", "tea issues -h")


class TeaTest(unittest.TestCase):
    """r2.D3: tea is refused outright, reads included, in process and through the house hook;
    a house reads with git and the pack's own verbs do the host's writes. Only help with no
    other flag (`tea --help`, `tea <group> --help`) runs."""

    def test_every_tea_line_is_refused_with_one_plain_sentence(self):
        for command in (*WRITES, *ONCE_READS):
            self.assertIn("tea is not available to a house", said(command) or "", command)

    def test_only_help_with_no_other_flag_runs(self):
        for command in HELP:
            self.assertIsNone(said(command), command)
        self.assertIsNone(said('git commit -m "tea pulls merge 5"'))

    def test_tea_named_by_the_shell_or_by_a_path_is_still_refused(self):
        """r2.F2: a command word the shell fills in, followed by any tea command or alias, is read
        as tea; a path, `env` and `command` are too."""
        for command in ("$(which tea) pr merge 5", '"$TEA" issue close 3', "$(which tea) comment 3 x",
                        "$TEA c 3 x", "$TEA login add", "$TEA releases delete v1", "$TEA ms close m",
                        "$(which tea) pulls list", "/usr/local/bin/tea pulls merge 5", "env tea pulls list",
                        "command tea pr close 3", "\"$TEA\" --login work pr merge 5"):
            self.assertIsNotNone(said(command), command)

    def test_a_shell_filled_word_is_read_as_tea_when_any_word_after_it_is_a_tea_command(self):
        """r2.D4: a flag tea takes, with its value, before the command does not hide it; a
        shell-filled git line with no tea word still runs."""
        for command in ('"$TEA" --limit 5 pr merge 7', '"$TEA" -m x issue close 3',
                        "$(which tea) --state open pulls merge 5"):
            self.assertIn("may be tea", said(command) or "", command)
        for command in ('"$GIT" status', '"$GIT" log --oneline -5'):
            self.assertIsNone(said(command), command)

    def test_a_shell_filled_word_before_a_tea_command_is_said_to_be_unread(self):
        """r2.D1: `"$GIT" clone url` is refused as possibly tea, and the sentence says so."""
        refused = said('"$GIT" clone https://box/octo/api.git') or ""
        self.assertIn("could not be read", refused)
        self.assertIn("may be tea", refused)

    def test_through_the_hook_every_tea_line_is_exit_2_and_one_line_and_help_runs(self):
        hook = test_conformance.GiteaGuard("test_the_sign_in_is_refused").hook
        for command in ("tea pulls merge 5", "tea pr close 3", "tea comment 3 x", "tea pulls list",
                        "tea notifications -m read"):
            done = hook(command)
            self.assertEqual((done.returncode, len(done.stderr.strip().splitlines())), (2, 1), command)
        self.assertEqual(hook("tea pulls --help").returncode, 0)


if __name__ == "__main__":
    unittest.main()
