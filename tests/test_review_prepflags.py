"""`keel-review`'s parser takes its flags only as written (c-730 fix check): a shortened flag
is never expanded, so the board fence's reading of a fork house's review step is the
parser's own."""

import unittest

from keel.review import prep


class AbbreviationTest(unittest.TestCase):
    def test_a_shortened_flag_is_refused_and_the_brief_s_own_forms_parse(self):
        with self.assertRaises(SystemExit):
            prep.parser().parse_args(["prep", "--d", "/s/cards/c-9", "--base", "main"])
        with self.assertRaises(SystemExit):
            prep.parser().parse_args(["draft", "--dir", "/s/c", "F1", "--comm", "x"])
        said = prep.parser().parse_args(["prep", "--dir", "/s/c", "--base", "main", "--worktree", "/w", "--since"])
        self.assertEqual((said.dir, said.base, said.worktree), ("/s/c", "main", ["/w"]))
        said = prep.parser().parse_args(["draft", "--dir", "/s/c", "F1", "--comment", "One point."])
        self.assertEqual((said.id, said.comment), ("F1", "One point."))


if __name__ == "__main__":
    unittest.main()
