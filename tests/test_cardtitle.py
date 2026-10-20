"""A card filed from the user's own words gets a short title (keel/cardtitle.py, c-729).

The stranger run's first card was filed with its whole sentence as the title, so the branch
and the merge subject on main carried it: "Merge keel/c-005-in-notes-api-add-a-way-to-
delete-a-note into main: In notes-api add a way to delete a note". The words stay, as the
brief; the title is what a list, a branch and a merge subject can carry."""

import unittest

from keel import cardtitle, merging


class ShortTitleTest(unittest.TestCase):
    def test_the_repo_it_names_and_the_asking_go_and_the_rest_is_cut_at_a_word(self):
        self.assertEqual(cardtitle.short("In notes-api add a way to delete a note", "notes-api"),
                         "Add a way to delete a note")
        self.assertEqual(cardtitle.short("please, in the notes-api repo: fix the typo in the README.", "notes-api"),
                         "Fix the typo in the README")
        self.assertEqual(cardtitle.short("Can you make the login page remember which account was used last time, "
                                         "and show it first when someone comes back to the page tomorrow?"),
                         "Make the login page remember which account was used")
        self.assertEqual(cardtitle.short("Add a test for the parser. It fails on empty input today."),
                         "Add a test for the parser")

    def test_a_short_title_is_kept_as_it_is(self):
        self.assertEqual(cardtitle.short("Fix the README typo"), "Fix the README typo")
        self.assertEqual(cardtitle.short("   "), "")

    def test_filed_from_words_the_words_are_the_brief(self):
        title, brief = cardtitle.from_words("In notes-api add a way to delete a note", "It should ask first.", "notes-api")
        self.assertEqual(title, "Add a way to delete a note")
        self.assertEqual(brief, "In notes-api add a way to delete a note\n\nIt should ask first.")
        self.assertEqual(cardtitle.from_words("Fix the README typo", "", None), ("Fix the README typo", ""))

    def test_the_merge_subject_carries_a_short_title_whatever_the_card_was_filed_with(self):
        card = {"id": "c-5", "title": "In notes-api add a way to delete a note, and make the list page show "
                                      "a confirmation before anything is removed for good"}
        subject = merging.merge_message(card, "shipyard/c-5-in-notes-api-add")
        self.assertEqual(subject, "Merge shipyard/c-5-in-notes-api-add: In notes-api add a way to delete a note, "
                                  "and make the list page show a (c-5)")
        self.assertEqual(merging.merge_message({"id": "c-6", "title": "Fix the README typo"}, "b"),
                         "Merge b: Fix the README typo (c-6)")


if __name__ == "__main__":
    unittest.main()
