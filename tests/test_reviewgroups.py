"""Lane GRP: a story's pull requests are reviewed together (GR-1), a lone side waits for its
sibling up to the space's `review_sibling_hours` (GR-3), and single cards are folded into a
feature card without ever silently taking one he is deciding (GR-4).

The work adapter is a stand-in, as in `tests/test_reviewcards.py`: a `review` script that
answers `scan` with the listing the test wrote, `branches <group> <repo>...` with the
branches the test says the other repos have, `story <group>` with a title, and `<id> poll`
with a pull request's state. Every pull request, branch and story here is invented.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from keel import reviewcards, reviewsettings
from keel.board import Board
from tests.helpers import make_config

MON_10 = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
STORY = "st-41001"


def script(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def pr(number, repo="api", head=None, group=STORY, author="Ana Example", title=None):
    row = {"key": f"{repo}:{number}", "repo": repo, "pr": number, "title": title or f"Invented change {number}",
           "author": author, "description": "Why it changes.", "created": "2026-09-20T09:00:00+00:00",
           "updated": "2026-09-21T09:00:00+00:00", "head": head or f"head-{number}",
           "branch": f"feature/{group}/x" if group else "feature/no-story/x", "base": "main",
           "url": f"https://example.invalid/{repo}/pr/{number}"}
    if group:
        row["group"] = group
    return row


class GroupCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.cfg = make_config(self.dir)
        self.cfg.work_hours, self.cfg.work_days = "00:00-24:00", "mon-sun"
        self.board = Board(self.cfg.db_path)
        self.addCleanup(self.board.close)
        work = self.cfg.adapters_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        self.listing, self.state = self.dir / "scan.json", self.dir / "poll.json"
        self.branch_file, self.story_file, self.log = self.dir / "branches.json", self.dir / "story.json", self.dir / "calls.log"
        script(work / "review", f'echo "review $*" >> {self.log}\n'
                                f'case "$1" in\n'
                                f'  scan) cat {self.listing} ;;\n'
                                f'  branches) cat {self.branch_file} ;;\n'
                                f'  story) cat {self.story_file} ;;\n'
                                f'  *) cat {self.state} ;;\n'
                                f'esac\n')
        self.lists([])
        self.branches({})
        self.story_file.write_text(json.dumps({"title": "Tell the user which machines were refused"}))
        self.state.write_text(json.dumps({"state": "open", "head": "head-1"}))
        patch = mock.patch.dict(reviewcards.LAST_SCANNED, {}, clear=True)
        patch.start()
        self.addCleanup(patch.stop)

    def lists(self, prs, open_groups=None, auto=None):
        self.listing.write_text(json.dumps({"prs": prs, "open_groups": open_groups or {}}))
        if auto is not None:
            reviewsettings.write(self.cfg, "work", "auto", "on" if auto else "off")

    def branches(self, found):
        self.branch_file.write_text(json.dumps({"branches": found}))

    def fetch(self, at=MON_10):
        reviewcards.LAST_SCANNED.clear()
        return reviewcards.upkeep(self.cfg, self.board, {"work"}, at=at)

    def cards(self, archived=True):
        return [c for c in self.board.list_cards(space="work", include_archived=archived)
                if c["options"].get("review_key")]

    def card(self, key):
        return next(c for c in self.cards() if c["options"]["review_key"] == key)

    def notes(self, card_id):
        return [e.get("text") or "" for e in self.board.events(card_id) if e["kind"] in ("note", "stage", "set")]

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []


class GroupingTest(GroupCase):
    """GR-1: two or more open pull requests of one story that need him are ONE card."""

    def test_two_repos_of_one_story_are_one_feature_card(self):
        self.lists([pr(4150), pr(2200, repo="web", author="Bo Example")])
        result = self.fetch()
        [card] = self.cards()
        self.assertEqual(result["filed"], [card["id"]])
        self.assertEqual(card["title"], f"Review: {STORY} · Tell the user which machines were refused")
        self.assertEqual(card["repo"], "api,web")
        self.assertEqual(card["stage"], "inbox")
        options = card["options"]
        self.assertEqual(options["review_key"], f"feature:{STORY}")
        self.assertEqual((options["kind"], options["slot"], options["review_group"]), ("review", "review", STORY))
        members = options["review_members"]
        self.assertEqual([(m["repo"], m["pr"], m["head"], m["branch"], m["author"]) for m in members],
                         [("api", 4150, "head-4150", f"feature/{STORY}/x", "Ana Example"),
                          ("web", 2200, "head-2200", f"feature/{STORY}/x", "Bo Example")])
        self.assertEqual([m["url"] for m in members], ["https://example.invalid/api/pr/4150",
                                                       "https://example.invalid/web/pr/2200"])
        self.assertEqual(members[0]["raised"], "2026-09-20T09:00:00+00:00")
        self.assertEqual(options["review_pr"]["author"], "Ana Example, Bo Example")
        self.assertIn(f"review story {STORY}", self.calls())

    def test_a_pull_request_with_no_story_stays_alone(self):
        self.lists([pr(4150, group=None), pr(4151, group=None)])
        self.fetch()
        self.assertEqual(sorted(c["options"]["review_key"] for c in self.cards()), ["api:4150", "api:4151"])
        self.assertFalse([c for c in self.calls() if c.startswith("review branches")])

    def test_a_story_title_the_tracker_cannot_give_falls_back_to_the_first_pr_s_title(self):
        self.story_file.write_text(json.dumps({"title": None}))
        self.lists([pr(4150, title="Refuse an uncoverable machine"), pr(2200, repo="web")])
        self.fetch()
        self.assertEqual(self.cards()[0]["title"], f"Review: {STORY} · Refuse an uncoverable machine")

    def test_it_is_filed_once(self):
        self.lists([pr(4150), pr(2200, repo="web")])
        self.fetch()
        self.fetch(MON_10 + timedelta(hours=1))
        self.assertEqual(len(self.cards()), 1)

    def test_a_member_that_joins_later_updates_the_card_and_a_posted_one_shows_new_commits(self):
        self.lists([pr(4150), pr(2200, repo="web")])
        self.fetch()
        [card] = self.cards()
        self.board.stage(card["id"], "assigned", "human")
        self.board.stage(card["id"], "building", "drain")
        self.board.stage(card["id"], "review", "house", plan_ref="p.md", output_ref="o")
        self.board.approve(card["id"], "outcome", "human", publish=lambda c: {"posted": True})
        head = reviewcards.composite_head(card["options"]["review_members"])
        self.board.set_fields(card["id"], {"options": {"review_posted": {"head": head, "round": 1}}}, "human")
        self.lists([pr(4150), pr(2200, repo="web"), pr(4152)])
        self.fetch(MON_10 + timedelta(hours=1))
        card = self.board.get(card["id"])
        self.assertEqual([m["label"] for m in card["options"]["review_members"]],
                         ["api#4150", "api#4152", "web#2200"])
        self.assertEqual(card["derived"]["review"], "new")
        self.assertTrue(any("api#4152 joined" in n for n in self.notes(card["id"])))

    def test_a_member_that_leaves_is_taken_off_with_a_note(self):
        self.lists([pr(4150), pr(4152), pr(2200, repo="web")])
        self.fetch()
        self.lists([pr(4150), pr(2200, repo="web")])
        self.fetch(MON_10 + timedelta(hours=1))
        [card] = self.cards()
        self.assertEqual([m["label"] for m in card["options"]["review_members"]], ["api#4150", "web#2200"])
        self.assertTrue(any("api#4152 left" in n for n in self.notes(card["id"])))

    def test_down_to_one_member_it_stays_the_feature_card_and_no_single_card_is_filed(self):
        self.lists([pr(4150), pr(2200, repo="web")])
        self.fetch()
        self.lists([pr(4150)])
        self.fetch(MON_10 + timedelta(hours=1))
        [card] = self.cards()
        self.assertEqual([m["label"] for m in card["options"]["review_members"]], ["api#4150"])
        self.assertEqual(card["repo"], "api")

    def test_a_posted_feature_card_sees_a_push_on_any_member(self):
        self.lists([pr(4150), pr(2200, repo="web")])
        self.fetch()
        [card] = self.cards()
        for stage, actor in (("assigned", "human"), ("building", "drain")):
            self.board.stage(card["id"], stage, actor)
        self.board.stage(card["id"], "review", "house", plan_ref="p.md", output_ref="o")
        self.board.approve(card["id"], "outcome", "human", publish=lambda c: {"posted": True})
        head = reviewcards.composite_head(card["options"]["review_members"])
        self.board.set_fields(card["id"], {"options": {"review_posted": {"head": head, "round": 1}}}, "human")
        self.fetch(MON_10 + timedelta(hours=1))
        self.assertEqual(self.board.get(card["id"])["derived"]["review"], "posted")
        self.lists([pr(4150), pr(2200, repo="web", head="head-2200b")])
        self.fetch(MON_10 + timedelta(hours=2))
        self.assertEqual(self.board.get(card["id"])["derived"]["review"], "new")

    def test_a_posted_feature_card_off_the_list_is_polled_member_by_member(self):
        self.lists([pr(4150), pr(2200, repo="web")])
        self.fetch()
        [card] = self.cards()
        for stage, actor in (("assigned", "human"), ("building", "drain")):
            self.board.stage(card["id"], stage, actor)
        self.board.stage(card["id"], "review", "house", plan_ref="p.md", output_ref="o")
        self.board.approve(card["id"], "outcome", "human", publish=lambda c: {"posted": True})
        head = reviewcards.composite_head(card["options"]["review_members"])
        self.board.set_fields(card["id"], {"options": {"review_posted": {"head": head, "round": 1}}}, "human")
        self.lists([])
        self.state.write_text(json.dumps({"members": {"api#4150": {"state": "merged", "head": "head-4150"},
                                                      "web#2200": {"state": "declined", "head": "head-2200"}}}))
        self.fetch(MON_10 + timedelta(hours=1))
        self.assertEqual(self.board.get(card["id"])["options"]["review_closed"], "merged")

    def test_auto_review_assigns_a_feature_card(self):
        self.lists([pr(4150), pr(2200, repo="web")], auto=True)
        self.fetch()
        self.assertEqual(self.cards()[0]["stage"], "assigned")


class WaitTest(GroupCase):
    """GR-3: one side raised while the other repo has a branch of the story and no pull
    request: held, then joined, released alone at the window, or reviewed now on his word."""

    def held(self):
        self.lists([pr(2200, repo="web")])
        self.branches({"api": [f"bug/{STORY}/refuse-machines"]})
        self.fetch()
        return self.card("web:2200")

    def test_a_branch_without_a_pull_request_holds_the_card(self):
        card = self.held()
        self.assertEqual(card["stage"], "inbox")
        wait = card["options"]["review_wait"]
        self.assertEqual((wait["story"], wait["sibling_repo"], wait["since"]),
                         (STORY, "api", MON_10.isoformat(timespec="seconds")))
        self.assertEqual(card["derived"]["review"], "held")
        with mock.patch.object(self.board, "now", return_value=(MON_10 + timedelta(hours=17)).isoformat()):
            self.assertEqual(self.board.get(card["id"])["derived"]["review_wait"]["hours_left"], 31)
        self.assertIn(f"review branches {STORY} web", self.calls())
        self.assertTrue(any("waiting for the api PR" in n for n in self.notes(card["id"])))

    def test_auto_review_does_not_start_a_held_card(self):
        self.lists([pr(2200, repo="web")], auto=True)
        self.branches({"api": [f"bug/{STORY}/refuse-machines"]})
        self.fetch()
        self.assertEqual(self.card("web:2200")["stage"], "inbox")

    def test_a_branch_that_already_has_an_open_pull_request_does_not_hold(self):
        """The api side is raised but is not his to review: waiting would never end in a
        feature card, so it is reviewed alone at once."""
        self.lists([pr(2200, repo="web")], open_groups={STORY: ["api", "web"]})
        self.branches({"api": [f"bug/{STORY}/refuse-machines"]})
        self.fetch()
        card = self.card("web:2200")
        self.assertNotIn("review_wait", card["options"])
        self.assertEqual(card["derived"]["review"], "waiting")

    def test_no_branch_elsewhere_does_not_hold(self):
        self.lists([pr(2200, repo="web")])
        self.fetch()
        self.assertEqual(self.card("web:2200")["derived"]["review"], "waiting")

    def test_the_branch_is_looked_up_once_per_held_card_per_poll(self):
        self.held()
        before = len([c for c in self.calls() if c.startswith("review branches")])
        self.fetch(MON_10 + timedelta(hours=1))
        self.fetch(MON_10 + timedelta(hours=2))
        self.assertEqual(len([c for c in self.calls() if c.startswith("review branches")]), before + 2)

    def test_the_sibling_raised_within_the_window_merges_into_one_feature_card_at_detected(self):
        held = self.held()
        self.lists([pr(2200, repo="web"), pr(4150)])
        self.fetch(MON_10 + timedelta(hours=5))
        feature = self.card(f"feature:{STORY}")
        self.assertEqual(feature["stage"], "inbox")
        self.assertEqual(feature["derived"]["review"], "waiting")
        folded = self.board.get(held["id"])
        self.assertTrue(folded["derived"]["archived"])
        self.assertEqual(folded["options"]["review_folded"], feature["id"])
        self.assertTrue(any(feature["id"] in n for n in self.notes(held["id"])))

    def test_the_window_running_out_releases_it_to_be_reviewed_alone(self):
        held = self.held()
        self.fetch(MON_10 + timedelta(hours=47))
        self.assertEqual(self.board.get(held["id"])["derived"]["review"], "held")
        self.fetch(MON_10 + timedelta(hours=48, minutes=1))
        card = self.board.get(held["id"])
        self.assertNotIn("review_wait", card["options"])
        self.assertEqual(card["derived"]["review"], "waiting")
        self.assertIn("reviewed alone: the api side was not raised in 48h", self.notes(held["id"])[-1])

    def test_the_window_is_the_space_s(self):
        self.cfg.spaces["work"].review_sibling_hours = 2
        held = self.held()
        self.fetch(MON_10 + timedelta(hours=3))
        self.assertIn("not raised in 2h", self.notes(held["id"])[-1])

    def test_a_released_card_with_auto_review_on_is_assigned(self):
        held = self.held()
        reviewsettings.write(self.cfg, "work", "auto", "on")
        self.fetch(MON_10 + timedelta(hours=49))
        self.assertEqual(self.board.get(held["id"])["stage"], "assigned")

    def test_review_now_anyway_ends_the_wait_and_it_is_never_held_again(self):
        held = self.held()
        self.board.set_fields(held["id"], {"options": {"review_wait": None, "review_alone": True}}, "human")
        self.assertEqual(self.board.get(held["id"])["derived"]["review"], "waiting")
        self.fetch(MON_10 + timedelta(hours=1))
        self.assertNotIn("review_wait", self.board.get(held["id"])["options"])


class FoldTest(GroupCase):
    """GR-4: a feature card forming over single cards takes the ones nobody is deciding."""

    def single(self, number=2200, repo="web"):
        self.lists([pr(number, repo=repo)])
        self.fetch()
        return self.card(f"{repo}:{number}")

    def join(self, at=MON_10 + timedelta(hours=1)):
        self.lists([pr(2200, repo="web"), pr(4150)])
        self.fetch(at)
        return self.card(f"feature:{STORY}")

    def test_an_inbox_single_card_is_folded_with_a_note(self):
        single = self.single()
        feature = self.join()
        self.assertTrue(self.board.get(single["id"])["derived"]["archived"])
        self.assertTrue(any(single["id"] in n for n in self.notes(feature["id"])))

    def test_a_single_card_at_his_gate_is_never_folded_silently(self):
        """c-480's case: the feature card is filed, and the single card gets a note; he
        decides."""
        single = self.single()
        self.board.stage(single["id"], "assigned", "human")
        self.board.stage(single["id"], "building", "drain")
        self.board.stage(single["id"], "review", "house", plan_ref="p.md", output_ref="o")
        feature = self.join()
        kept = self.board.get(single["id"])
        self.assertFalse(kept["derived"]["archived"])
        self.assertEqual(kept["stage"], "review")
        self.assertTrue(any(feature["id"] in n and "you decide" in n for n in self.notes(single["id"])))
        self.assertEqual(feature["stage"], "inbox")

    STAMP = (MON_10 + timedelta(hours=1)).isoformat()   # the board's clock for the fold and the dismissal
    MOVED = (MON_10 + timedelta(hours=2)).isoformat()   # the pull request's push, after both

    def pinned(self):
        return mock.patch.object(self.board, "now", return_value=self.STAMP)

    def push(self, *others):
        self.lists([pr(2200, repo="web", head="head-2200-b") | {"updated": self.MOVED}, *others])
        self.fetch(MON_10 + timedelta(hours=3))

    def test_a_folded_single_card_stays_folded_when_its_pull_request_moves(self):
        """The feature card reviews the new push; the single card coming back would review
        the same pull request twice."""
        single = self.single()
        with self.pinned():
            self.join()
        self.push(pr(4150))
        self.assertTrue(self.board.get(single["id"])["derived"]["archived"])

    def test_a_single_card_he_dismissed_for_the_feature_card_stays_dismissed(self):
        """c-480, 2026-09-25: at his gate when the feature card formed, so not folded; he
        dismissed it to take the feature review, and a later push must not bring it back."""
        single = self.single()
        self.board.stage(single["id"], "assigned", "human")
        self.board.stage(single["id"], "building", "drain")
        self.board.stage(single["id"], "review", "house", plan_ref="p.md", output_ref="o")
        with self.pinned():
            self.join()
            self.board.set_fields(single["id"], {"options": {"archived": True}}, "human")
        self.push(pr(4150))
        self.assertTrue(self.board.get(single["id"])["derived"]["archived"])

    def test_a_dismissed_single_card_alone_still_comes_back_on_new_activity(self):
        """RC-8 holds for a pull request no feature card covers."""
        single = self.single()
        with self.pinned():
            self.board.set_fields(single["id"], {"options": {"archived": True}}, "human")
        self.push()
        self.assertFalse(self.board.get(single["id"])["derived"]["archived"])

    def test_a_single_card_under_review_is_not_folded_either(self):
        single = self.single()
        self.board.stage(single["id"], "assigned", "human")
        self.join()
        self.assertFalse(self.board.get(single["id"])["derived"]["archived"])

    def test_a_posted_single_review_s_ledger_joins_the_feature_s(self):
        single = self.single()
        for stage, actor in (("assigned", "human"), ("building", "drain")):
            self.board.stage(single["id"], stage, actor)
        self.board.stage(single["id"], "review", "house", plan_ref="p.md", output_ref="o")
        self.board.approve(single["id"], "outcome", "human", publish=lambda c: {"posted": True})
        ledger = [{"id": "r1-f1", "path": "src/a.js", "line": 4, "choice": "drop", "claim": "x"}]
        self.board.set_fields(single["id"], {"options": {"review_posted": {"head": "old", "round": 1, "ledger": ledger}}}, "human")
        feature = self.join()
        self.assertTrue(self.board.get(single["id"])["derived"]["archived"])
        [carried] = feature["options"]["review_carried"]
        self.assertEqual((carried["member"], carried["head"]), ("web#2200", "old"))
        self.assertEqual(carried["ledger"][0]["member"], "web#2200")

    def test_members_already_posted_at_their_heads_file_no_feature_card(self):
        """Nothing is new on either side: both were reviewed alone, and a feature card now
        would only repeat them."""
        self.lists([pr(2200, repo="web", group=None), pr(4150, group=None)])
        self.fetch()
        for key in ("web:2200", "api:4150"):
            card = self.card(key)
            for stage, actor in (("assigned", "human"), ("building", "drain")):
                self.board.stage(card["id"], stage, actor)
            self.board.stage(card["id"], "review", "house", plan_ref="p.md", output_ref="o")
            self.board.approve(card["id"], "outcome", "human", publish=lambda c: {"posted": True})
            self.board.set_fields(card["id"], {"options": {"review_posted": {"head": f"head-{card['options']['pr']}",
                                                                             "round": 1}}}, "human")
        self.lists([pr(2200, repo="web"), pr(4150)])
        self.fetch(MON_10 + timedelta(hours=1))
        self.assertFalse([c for c in self.cards() if c["options"]["review_key"].startswith("feature:")])


if __name__ == "__main__":
    unittest.main()
