"""The noun guard (tests/nouns.py, c-630): it reads the literals a user could read, in both
languages, flags a ticket or change noun in one, and leaves data keys, comments and
docstrings alone. And the tree as it stands passes it, with no stale allowlist entry."""

import tempfile
import unittest
from pathlib import Path

from tests import nouns

PY = '''"""A docstring may say pull request, as history."""
# a comment may say story too
KEY = "story"
OPTION = "options.pr"
SAID = "the pull request merged"
LINE = f"waiting for the {repo} PR ({wait['story']} has a branch there)"
REF = "see sc-123"
MERGE = ("a merge request "
         "was opened")


def f():
    """The PRs here are history."""
    return "Open PRs"
'''

JS = r"""/* a block comment: Open story */
// a line comment: the pull request
var a = 'story', b = "open-pr", c = `${c.story} is ${'the pull request'}`;
var d = /PR #\d+/.test(x) ? 'draft PR #' : "no story yet";
var e = `waiting for ${repo} PR (${w.story})`;
"""


class GuardTest(unittest.TestCase):
    def test_python_literals_are_flagged_and_keys_and_docs_are_not(self):
        flagged = [text for _, text in nouns.python_literals(PY) if nouns.flagged(text)]
        self.assertEqual(flagged, ["the pull request merged", "waiting for the  PR ( has a branch there)",
                                   "see sc-123", "a merge request ", "Open PRs"])

    def test_javascript_literals_are_flagged_and_comments_and_regexes_are_not(self):
        flagged = [text for _, text in nouns.js_literals(JS) if nouns.flagged(text)]
        self.assertEqual(flagged, ["the pull request", "draft PR #", "no story yet", "waiting for   PR ( )"])

    def test_a_bare_identifier_is_a_data_key(self):
        for key in ("story", "open-pr", "options.pr", "tracker_ref", "links.story"):
            self.assertFalse(nouns.flagged(key), key)
        self.assertTrue(nouns.flagged("sc-12"))      # a ticket ref is never a key

    def test_the_allowlist_matches_a_piece_and_a_stale_entry_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "keel").mkdir()
            (root / "app").mkdir()
            (root / "keel" / "x.py").write_text('A = "the PR body"\nB = "Open story"\n')
            found, unused = nouns.hits(root, [("keel/x.py", "PR body", "a section name"),
                                              ("keel/y.py", "*", "gone")])
            self.assertEqual(found, ["keel/x.py:2: Open story"])
            self.assertEqual(unused, ["tests/nouns-allow: keel/y.py | * matches nothing"])

    def test_the_tree_passes(self):
        found, unused = nouns.hits()
        self.assertEqual(found, [])
        self.assertEqual(unused, [])


if __name__ == "__main__":
    unittest.main()
