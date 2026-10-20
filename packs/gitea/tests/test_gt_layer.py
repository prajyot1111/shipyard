"""What is Gitea's own in the layer, beyond the contract the conformance suite holds: the
address a repo is cloned from, a draft as a title, a token's missing scope, and a reply on a
Gitea with no replies call."""

import os
import unittest
from unittest import mock

import suitefence  # noqa: F401

import gt_layer
from gt_layer import ScopeMissing
from keel.packkit.layer import GENERAL, LINES
from keel.packkit.world import World
from test_conformance import WorldServed, git_env

REPO = "octo/api"


class AddressTest(unittest.TestCase):
    def test_an_http_address_names_owner_repo_and_where_gitea_is_served(self):
        found = gt_layer.address("https://git.example.org:3000/code/octo/api.git")
        self.assertEqual((str(found), found.base), ("octo/api", "https://git.example.org:3000/code"))
        self.assertEqual(gt_layer.address("http://box/octo/api").base, "http://box")

    def test_ssh_a_path_or_an_address_without_owner_and_repo_is_none(self):
        for address in ("git@box:octo/api.git", "ssh://box/octo/api", "/srv/api.git", "https://box/api"):
            self.assertIsNone(gt_layer.address(address), address)

    def test_a_name_or_password_written_into_an_address_is_never_shown(self):
        self.assertEqual(gt_layer.shown("https://me:hunter2@box/octo/api.git"), "https://box/octo/api.git")
        self.assertNotIn("hunter2", gt_layer.HOST.elsewhere("https://me:hunter2@box/octo/api.git"))


def diff(path: str, *hunks: str, new: bool = False, gone: bool = False) -> str:
    """One file's part of a unified diff, as git writes it."""
    head = [f"diff --git a/{path} b/{path}", "--- /dev/null" if new else f"--- a/{path}",
            "+++ /dev/null" if gone else f"+++ b/{path}"]
    return "\n".join(head + list(hunks)) + "\n"


class ChangedLinesTest(unittest.TestCase):
    """c-739: the lines of a diff a review comment may go on, as GitHub takes them: added or
    context lines a hunk of that file shows, numbered as the change leaves the file."""

    def test_the_lines_a_diff_shows_are_its_added_and_context_lines(self):
        table = {
            "a mixed hunk": (diff("a.py", "@@ -3,4 +3,4 @@ def f():", " k3", "-old4", "+new4", " k5", " k6"),
                             {"a.py": {3, 4, 5, 6}}),
            "two hunks in one file": (diff("a.py", "@@ -1,2 +1,3 @@", " k1", "+n2", " k3",
                                           "@@ -20,1 +21,2 @@", " k21", "+n22"), {"a.py": {1, 2, 3, 21, 22}}),
            "two files": (diff("a.py", "@@ -1 +1 @@", "-o", "+n") + diff("b.py", "@@ -5,0 +6,2 @@", "+x", "+y"),
                          {"a.py": {1}, "b.py": {6, 7}}),
            "a deleted file": (diff("gone.py", "@@ -1,2 +0,0 @@", "-x", "-y", gone=True), {}),
            "a one-line new file": (diff("n.txt", "@@ -0,0 +1 @@", "+only", new=True), {"n.txt": {1}}),
            "no newline at the end": (diff("a.py", "@@ -1,2 +1,2 @@", " k1", "-old", "\\ No newline at end of file",
                                           "+new", "\\ No newline at end of file"), {"a.py": {1, 2}}),
            # a form feed is not a line's end: read as one, it ends the hunk a row early, and the
            # added line `++ b/other.py` is then read as a file's header
            "a form feed in a context line": (diff("a.py", "@@ -1 +1,2 @@", " page\f break", "+++ b/other.py",
                                                   "@@ -10 +11 @@", " k11"), {"a.py": {1, 2, 11}}),
        }
        for name, (text, lines) in table.items():
            self.assertEqual(gt_layer.in_hunks(text), lines, name)


class GiteaWaysTest(WorldServed, unittest.TestCase):
    def setUp(self):
        served = self.stand_in()
        patcher = mock.patch.dict(os.environ, git_env(served.git_config()))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo = gt_layer.Repo(REPO, served.base, None)
        self.world = World()
        self.world.repo(REPO)

    def test_a_draft_is_a_title_marked_wip_and_ready_takes_the_mark_off(self):
        self.host_serve(self.world)
        made = gt_layer.open_pr(self.repo, "Tidy the loader", "feature", "main", "Body.", draft=True)
        self.assertEqual((made["title"], made["draft"]), ("WIP: Tidy the loader", True))
        gt_layer.set_ready(self.repo, made["id"])
        after = gt_layer.get(self.repo, made["id"])
        self.assertEqual((after["title"], after["draft"]), ("Tidy the loader", False))

    def test_a_gitea_that_sends_no_draft_field_is_read_by_the_title_s_mark(self):
        """r1.F4: a pull request is a draft when Gitea says so or when its title carries the mark."""
        drafted = self.world.add_change(REPO, "feature", draft=True)
        ready = self.world.add_change(REPO, "other")
        self.world.data["fail"]["no_draft_field"] = True
        self.host_serve(self.world)
        self.assertEqual((gt_layer.get(self.repo, drafted)["draft"], gt_layer.get(self.repo, ready)["draft"]),
                         (True, False))

    def test_a_token_without_a_scope_is_named_with_the_token_to_make(self):
        number = self.world.add_change(REPO, "feature")
        self.world.data["fail"]["scope"] = "read:issue"
        self.host_serve(self.world)
        with self.assertRaises(ScopeMissing) as said:
            gt_layer.said(self.repo, number, parts=(GENERAL,))
        self.assertEqual(said.exception.needs, ("read:issue",))
        self.assertIn("access token that is not allowed read:issue (it is allowed write:repository)",
                      str(said.exception))
        self.assertIn("write:repository, write:issue and read:user", str(said.exception))

    def test_on_a_gitea_with_no_replies_call_a_reply_is_a_comment_on_the_same_line(self):
        """A Gitea with no replies call answers 404, or 405 (r1.F6); either way the reply lands."""
        for status in (404, 405):
            world = World()
            world.repo(REPO)
            number = world.add_change(REPO, "feature")
            first = world.say(REPO, number, "ana", "Why 40?", "loader.py", 7)
            world.data["fail"]["replies"] = status
            self.host_serve(world)
            gt_layer.reply(self.repo, number, first, "Page size.")
            lines = {one["body"]: one for one in gt_layer.said(self.repo, number, parts=(LINES,))[LINES]}
            self.assertEqual((lines["Page size."]["path"], lines["Page size."]["line"],
                              lines["Page size."]["parent"]), ("loader.py", 7, first), status)
            self.assertEqual([one["op"] for one in self.host_seen(world).writes], ["post_review"], status)


if __name__ == "__main__":
    unittest.main()
