import unittest

from reports.app import reports_for
from reports.search import search


class ReportsTest(unittest.TestCase):
    def test_lists_every_report(self):
        self.assertEqual(len(reports_for({})), 5)

    def test_search_matches_title_words(self):
        self.assertEqual([r.id for r in search("Monthly revenue")], [1])


if __name__ == "__main__":
    unittest.main()
