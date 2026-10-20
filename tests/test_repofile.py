"""The lines Keel reads out of a repo's CLAUDE.md (keel/repofile.py, c-678): the prepare
command, the test command, the branch work lands on and how to run the app, each found by
its opening words, with the line it came from. A line still as the template wrote it, with
nothing in backticks, names nothing."""

import unittest
from pathlib import Path

from keel import repofile, repolayout

ROOT = Path(__file__).resolve().parent.parent
API = """# api: how to work in this repo

## Prepare and test
- Prepare a fresh copy: `npm ci`
- Run the tests: `npm test` (about 40 seconds)
- Check style before you finish: `npm run lint`

## Where work lands
- Finished work lands on `main`.

## Running the app
- Sessions run tests only until this section says how to run the app.
"""


class ParseTest(unittest.TestCase):
    def test_each_line_is_found_by_its_opening_words_with_its_line_number(self):
        found = repofile.parse(API)
        self.assertEqual(found["prepare"], {"value": "npm ci", "line": 4})
        self.assertEqual(found["test"], {"value": "npm test", "line": 5})
        self.assertEqual(found["lands"], {"value": "main", "line": 9})
        self.assertIsNone(found["run"], "tests only: the section does not say how to run the app")

    def test_a_run_line_is_the_run_rule(self):
        found = repofile.parse(API.replace("- Sessions run tests only until this section says how to run the app.",
                                           "- Run the app: `npm run dev -- --port 0` (never port 3000, which is yours)"))
        self.assertEqual(found["run"], {"value": "npm run dev -- --port 0", "line": 12})

    def test_the_template_names_nothing(self):
        text = repolayout.template(ROOT, "repo", key="api", space="work")
        self.assertEqual(repofile.parse(text), {"prepare": None, "test": None, "lands": None, "run": None})

    def test_the_words_may_be_starred_or_cased_differently_and_only_the_first_line_counts(self):
        found = repofile.parse("* **Run the tests:** `make test`\n- run the tests: `other`\n"
                               "- prepare a fresh copy: nothing needed\n")
        self.assertEqual(found["test"], {"value": "make test", "line": 1})
        self.assertIsNone(found["prepare"], "no command in backticks is no command")

    def test_nothing_and_no_file_name_nothing(self):
        self.assertEqual(repofile.parse(""), repofile.NOTHING)
        self.assertEqual(repofile.read(Path("/nonexistent/CLAUDE.md")), repofile.NOTHING)

    def test_a_value_is_one_line_and_never_starts_with_a_dash(self):
        """What is read here becomes a command Keel runs or a branch it names."""
        self.assertIsNone(repofile.parse("- Finished work lands on `--upload-pack=x`.")["lands"])
        self.assertIsNone(repofile.parse("- Finished work lands on `main; rm -rf x`.")["lands"])
        self.assertEqual(repofile.parse("- Finished work lands on `release/2.x`.")["lands"]["value"], "release/2.x")


if __name__ == "__main__":
    unittest.main()
