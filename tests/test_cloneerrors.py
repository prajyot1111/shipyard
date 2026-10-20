"""A failed copy of a repo, sorted into a kind with its sentence (keel/cloneerrors.py, c-678):
git's own words decide the kind, the address decides the host and the name, and nothing here
runs git or reaches a host."""

import unittest

from keel import cloneerrors

NO_PROMPT = "fatal: could not read Username for 'https://github.com': terminal prompts disabled"
AUTH = "remote: Invalid username or password.\nfatal: Authentication failed for 'https://github.com/maya-okafor/web.git/'"


class SortTest(unittest.TestCase):
    def test_a_private_github_repo_this_computer_is_not_signed_in_for(self):
        for said in (NO_PROMPT, AUTH):
            found = cloneerrors.sort("https://github.com/maya-okafor/web", said)
            self.assertEqual(found["kind"], "private")
            self.assertEqual(found["sentence"], "GitHub did not let this computer read maya-okafor/web. "
                             "Private repos need this computer to be signed in to GitHub.")
            self.assertEqual(found["git"], said.splitlines()[-1])
            self.assertEqual((found["host"], found["slug"]), ("github.com", "maya-okafor/web"))

    def test_a_private_repo_on_another_host(self):
        found = cloneerrors.sort("https://git.example.org/team/web.git",
                                 "fatal: Authentication failed for 'https://git.example.org/team/web.git/'")
        self.assertEqual(found["kind"], "host")
        self.assertEqual(found["sentence"], "git.example.org did not let this computer read that repo.")
        self.assertEqual(found["needs"], "git.example.org needs a key or a saved password for git. Set one up, then try again.")

    def test_no_repo_at_that_address(self):
        for said in ("remote: Repository not found.\nfatal: repository 'https://github.com/maya-okafor/wbe/' not found",
                     "fatal: unable to access 'https://githb.com/x/y/': Could not resolve host: githb.com",
                     "fatal: '/tmp/nowhere' does not appear to be a git repository"):
            found = cloneerrors.sort("https://github.com/maya-okafor/wbe", said)
            self.assertEqual(found["kind"], "nosuch", said)
            self.assertEqual(found["sentence"], "There is no repo at that address. Check the spelling, or open it "
                             "in your browser to make sure it exists.")

    def test_an_ssh_address_with_no_key_offers_the_https_one(self):
        said = "git@github.com: Permission denied (publickey).\nfatal: Could not read from remote repository."
        found = cloneerrors.sort("git@github.com:maya-okafor/web.git", said)
        self.assertEqual(found["kind"], "ssh")
        self.assertEqual(found["sentence"], "This address uses SSH, and this computer has no SSH key that host accepts.")
        self.assertEqual(found["https"], "https://github.com/maya-okafor/web.git")
        self.assertEqual(found["git"], "git@github.com: Permission denied (publickey).")

    def test_a_mistyped_repo_over_ssh_is_no_such_repo_not_a_missing_key(self):
        """git ends every SSH failure with "Could not read from remote repository": that line
        alone says nothing about a key (review F12)."""
        said = "ERROR: Repository not found.\nfatal: Could not read from remote repository.\n\nPlease make sure you have the correct access rights\nand the repository exists."
        found = cloneerrors.sort("git@github.com:maya-okafor/wbe.git", said)
        self.assertEqual(found["kind"], "nosuch")
        self.assertIn("There is no repo at that address.", found["sentence"])
        self.assertIsNone(found["https"])

    def test_a_host_this_computer_has_never_met_over_ssh_says_so(self):
        said = "Host key verification failed.\nfatal: Could not read from remote repository."
        found = cloneerrors.sort("ssh://git@git.example.org:2222/team/web.git", said)
        self.assertEqual(found["kind"], "hostkey")
        self.assertEqual(found["sentence"], "This computer has not connected to git.example.org over SSH before, so "
                         "the copy stopped before it began. Use the https address, or connect to it once in a "
                         "terminal and say yes when it asks whether to trust the host.")
        self.assertEqual(found["https"], "https://git.example.org/team/web.git")
        self.assertEqual(found["git"], "Host key verification failed.")

    def test_an_ssh_failure_that_says_nothing_more_is_said_in_gits_own_line(self):
        found = cloneerrors.sort("git@git.example.org:team/web.git",
                                 "ssh: connect to host git.example.org port 22: Connection refused\n"
                                 "fatal: Could not read from remote repository.")
        self.assertEqual(found["kind"], "other")

    def test_anything_else_is_said_in_gits_own_line(self):
        found = cloneerrors.sort("https://github.com/maya-okafor/api", "fatal: early EOF\nfatal: index-pack failed")
        self.assertEqual(found["kind"], "other")
        self.assertEqual(found["sentence"], "The copy failed: fatal: index-pack failed")
        self.assertEqual(cloneerrors.sort("https://x.example/a", "")["sentence"], "The copy failed: git gave no reason")


class AddressTest(unittest.TestCase):
    def test_the_short_name_is_filled_from_the_address(self):
        for url, name in (("https://github.com/maya-okafor/api", "api"),
                          ("https://github.com/maya-okafor/Web-App.git", "web-app"),
                          ("git@github.com:maya-okafor/web.git", "web"),
                          ("/srv/code/tide_api/", "tide_api"),
                          ("https://github.com/maya-okafor/9lives", "r9lives"),
                          ("https://example.org/", ""), ("", "")):
            self.assertEqual(cloneerrors.short_name(url), name, url)

    def test_the_host_and_the_slug_of_an_address(self):
        self.assertEqual(cloneerrors.host_of("https://user@code.example.com/a/b.git"), "code.example.com")
        self.assertEqual(cloneerrors.host_of("git@git.example.org:a/b.git"), "git.example.org")
        self.assertIsNone(cloneerrors.host_of("/srv/code/api"))
        self.assertEqual(cloneerrors.slug_of("https://github.com/a/b.git"), "a/b")
        self.assertEqual(cloneerrors.slug_of("git@github.com:a/b.git"), "a/b")
        self.assertIsNone(cloneerrors.https_of("https://github.com/a/b"), "already https")

    def test_an_address_is_shown_without_its_user_and_password(self):
        """A token in an address would otherwise be drawn on the page (review F13)."""
        for url, shown in (("https://sam:s3cret@git.example.org/team/web.git", "https://git.example.org/team/web.git"),
                           ("https://tok3n@code.example.com/a/b", "https://code.example.com/a/b"),
                           ("https://github.com/a/b", "https://github.com/a/b"),
                           ("git@github.com:a/b.git", "git@github.com:a/b.git"),
                           ("ssh://git@git.example.org:2222/a/b.git", "ssh://git@git.example.org:2222/a/b.git"),
                           ("/srv/code/api", "/srv/code/api"), ("", "")):
            self.assertEqual(cloneerrors.shown_address(url), shown, url)

    def test_an_address_that_carries_a_password_is_known(self):
        self.assertTrue(cloneerrors.has_password("https://sam:s3cret@git.example.org/team/web.git"))
        self.assertTrue(cloneerrors.has_password("ssh://git:s3cret@git.example.org/a/b.git"))
        for url in ("https://sam@git.example.org/team/web.git", "https://github.com/a/b", "git@github.com:a/b.git",
                    "/srv/code/a:b/api"):
            self.assertFalse(cloneerrors.has_password(url), url)

    def test_what_git_said_is_shown_without_a_secret(self):
        said = "fatal: unable to access 'https://sam:s3cret@git.example.org/team/web.git/': The requested URL returned error: 500"
        self.assertEqual(cloneerrors.scrubbed(said), "fatal: unable to access 'https://git.example.org/team/web.git/': "
                                                     "The requested URL returned error: 500")
        self.assertNotIn("s3cret", cloneerrors.sort("https://sam:s3cret@git.example.org/team/web.git", said)["git"])


if __name__ == "__main__":
    unittest.main()
