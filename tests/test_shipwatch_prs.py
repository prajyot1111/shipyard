"""SH-10: a card may carry one pull request per repo, and the watcher folds them as one.

The adapter's sight for a card with more than one pull request carries `prs`, one sight
per pull request with its `repo` (the card's primary first, marked `primary`). The fold
keeps what it has seen per pull request, the batch and its debounce stay ONE across them
(a round takes everything waiting, whichever pull request it came from), a handle from a
pull request other than the primary is `<repo>.<handle>` so its reply goes to the right
one, and the card's events are merged only when ALL merged, declined when ANY was. Every
pull request here is invented.
"""

import unittest
from datetime import datetime, timedelta, timezone

from keel import shipwatch

MON_10 = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)


def stamp(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


def one(repo, pr, comments=(), reviews=(), ci=None, state="open", behind=0, approvals=0,
        primary=False, head="aaa111"):
    return {"repo": repo, "pr": pr, "primary": primary, "state": state,
            "url": f"https://example.invalid/{repo}/pr/{pr}", "head": head, "behind": behind,
            "approvals": approvals, "comments": list(comments), "reviews": list(reviews),
            "ci": ci or {"state": "none"}}


def two(api=None, web=None) -> dict:
    """A card's sight with its two pull requests, api #4150 the primary, web #2190."""
    first = one("api", 4150, primary=True, **(api or {}))
    second = one("web", 2190, head="bbb222", **(web or {}))
    return {"state": "open", "url": first["url"], "head": first["head"], "prs": [first, second]}


def comment(number: int, at: datetime, author="Ana Example"):
    return {"id": number, "author": author, "at": stamp(at), "text": "please rename this",
            "path": "src/thing.js", "line": 4, "parent": None}


def baseline(sight: dict) -> dict:
    shipped, events = shipwatch.fold({"since": stamp(MON_10), "round": 0}, sight, MON_10)
    assert events == [] and not shipped["pending"]
    return shipped


class TwoPullRequestsTest(unittest.TestCase):
    def test_the_first_look_baselines_every_pull_request(self):
        shipped = baseline(two(api={"comments": [comment(11, MON_10)]},
                               web={"comments": [comment(21, MON_10)]}))
        self.assertEqual(shipped["seen"]["comments"], [11])
        self.assertEqual(shipped["seen_other"]["web"]["comments"], [21])

    def test_comments_on_both_wait_in_one_batch_and_the_second_is_named_by_its_repo(self):
        shipped = baseline(two())
        new, events = shipwatch.fold(shipped, two(api={"comments": [comment(11, MON_10)]},
                                                  web={"comments": [comment(21, MON_10)]}), MON_10)
        self.assertEqual(events, [])
        self.assertEqual([i["handle"] for i in new["pending"]], ["c11", "web.c21"])
        self.assertEqual(new["pending"][1]["repo"], "web")
        self.assertEqual(new["facts"]["waiting"], 2)
        later = MON_10 + timedelta(minutes=31)
        self.assertTrue(shipwatch.due(new, later))
        items, taken = shipwatch.take_batch(new, later)
        self.assertEqual(len(items), 2, "one round covers both pull requests")
        self.assertEqual(taken["round"], 1)

    def test_a_review_and_a_failed_check_on_the_second_are_its_own_items(self):
        shipped = baseline(two(web={"ci": {"state": "running"}}))
        new, _ = shipwatch.fold(shipped, two(
            api={"reviews": [{"author": "Bo", "state": "changes_requested", "at": stamp(MON_10)}]},
            web={"reviews": [{"author": "Bo", "state": "changes_requested", "at": stamp(MON_10)}],
                 "ci": {"state": "failed", "name": "build"}}), MON_10)
        self.assertEqual(sorted(i["handle"] for i in new["pending"]),
                         ["review-bo", "web.ci", "web.review-bo"])

    def test_the_card_merges_only_when_every_pull_request_has(self):
        shipped = baseline(two())
        self.assertEqual(shipwatch.fold(shipped, two(api={"state": "merged"}), MON_10)[1], [])
        self.assertEqual(shipwatch.fold(shipped, two(api={"state": "merged"}, web={"state": "merged"}),
                                        MON_10)[1], ["merged"])
        self.assertEqual(shipwatch.fold(shipped, two(web={"state": "declined"}), MON_10)[1], ["declined"])

    def test_the_facts_sum_across_and_keep_each_pull_request(self):
        shipped = baseline(two(api={"comments": [comment(11, MON_10)], "approvals": 1, "behind": 2,
                                      "ci": {"state": "passed"}},
                               web={"state": "merged", "behind": 5, "ci": {"state": "failed"}}))
        facts = shipped["facts"]
        self.assertEqual((facts["state"], facts["comments"], facts["approvals"], facts["ci"], facts["behind"]),
                         ("open", 1, 1, "failed", 5))
        self.assertEqual([(p["repo"], p["pr"], p["state"]) for p in facts["prs"]],
                         [("api", 4150, "open"), ("web", 2190, "merged")])

    def test_a_second_pull_request_joining_a_watched_card_is_baselined_alone(self):
        """A card watched on one pull request (the old record shape) that gains a second:
        what the first already saw stays seen, and the second's past flags nothing."""
        single = {"state": "open", "url": "u", "head": "aaa111", "behind": 0, "approvals": 0,
                  "comments": [comment(11, MON_10)], "reviews": [], "ci": {"state": "none"}}
        shipped, _ = shipwatch.fold({"since": stamp(MON_10), "round": 0}, single, MON_10)
        new, _ = shipwatch.fold(shipped, two(api={"comments": [comment(11, MON_10)]},
                                             web={"comments": [comment(21, MON_10)]}), MON_10)
        self.assertEqual(new["pending"], [])
        newer, _ = shipwatch.fold(new, two(api={"comments": [comment(11, MON_10), comment(12, MON_10)]},
                                           web={"comments": [comment(21, MON_10)]}), MON_10)
        self.assertEqual([i["handle"] for i in newer["pending"]], ["c12"])


if __name__ == "__main__":
    unittest.main()


class WholeTextTest(unittest.TestCase):
    """c-580: a comment is never cut without saying so, and its whole text is kept."""

    def long_comment(self, number: int) -> dict:
        return dict(comment(number, MON_10), text="word " * 500)

    def test_a_long_comment_is_cut_to_the_cap_and_names_its_whole_file(self):
        sight = baseline(two())
        shipped, _ = shipwatch.fold(sight, two(web={"comments": [self.long_comment(21)]}), MON_10)
        (item,) = shipped["pending"]
        self.assertEqual(item["handle"], "web.c21")
        self.assertLessEqual(len(item["text"]), shipwatch.TEXT_MAX)
        self.assertTrue(item["text"].endswith("[cut: full text in comments/web.c21.md]"))

    def test_a_short_comment_is_kept_as_it_is(self):
        sight = baseline(two())
        shipped, _ = shipwatch.fold(sight, two(api={"comments": [comment(11, MON_10)]}), MON_10)
        self.assertEqual(shipped["pending"][0]["text"], "please rename this")

    def test_every_comment_on_every_pull_request_has_its_whole_text(self):
        texts = shipwatch.whole_texts(two(api={"comments": [comment(11, MON_10)]},
                                          web={"comments": [self.long_comment(21)]}))
        self.assertEqual(sorted(texts), ["c11.md", "web.c21.md"])
        self.assertIn("word " * 500, texts["web.c21.md"])
        self.assertIn("on `src/thing.js:4`", texts["c11.md"])

    def test_a_handle_is_made_safe_before_it_is_a_file_name(self):
        self.assertEqual(shipwatch.comment_file("../web app.c1"), "-web-app.c1.md")
