"""Lane RC, RC-1 and RC-5: the review fetcher, a drain step on the machine that holds the
work space.

The work adapter is a stand-in: a `review` script in the test's own adapters directory that
answers `scan` with the listing the test wrote and `<id> poll` with a pull request's state,
which is what the code host stand-in in `packs/work/tests/test_review_cards.py` makes the
real adapter print. Nothing starts a session. Every pull request is invented.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from keel import drain, house, reviewcards, reviewsettings
from keel.board import Board, Refused
from tests.helpers import FakeHarness, FakeMachine, make_config

MON_10 = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)


def script(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def pr(number=4150, head="head-1", repo="api", author="Ana Example", title="Tidy the loader"):
    return {"key": f"{repo}:{number}", "repo": repo, "pr": number, "title": title, "author": author,
            "description": "The loader reads its page cap once.", "created": "2026-09-20T09:00:00+00:00",
            "updated": "2026-09-21T09:00:00+00:00", "head": head, "branch": "feature/st-41001/tidy",
            "base": "main", "url": f"https://example.invalid/pr/{number}"}


class FetcherCase(unittest.TestCase):
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
        self.listing, self.state, self.log = self.dir / "scan.json", self.dir / "poll.json", self.dir / "calls.log"
        script(work / "review", f'echo "review $*" >> {self.log}\n'
                                f'if [ "$1" = scan ]; then cat {self.listing}; else cat {self.state}; fi\n')
        self.lists([pr()])
        self.polls("open", "head-1")
        patch = mock.patch.dict(reviewcards.LAST_SCANNED, {}, clear=True)
        patch.start()
        self.addCleanup(patch.stop)

    def lists(self, prs, auto=None, model=None):
        """The adapter's listing, which carries no settings (lane RETIRE, RT-2): auto review and
        the review model are the space's own (`keel/reviewsettings.py`), set here as the
        deck's gear sets them."""
        self.listing.write_text(json.dumps({"prs": prs}))
        if auto is not None:
            reviewsettings.write(self.cfg, "work", "auto", "on" if auto else "off")
        if model is not None:
            reviewsettings.write(self.cfg, "work", "model", model)

    def polls(self, state, head):
        self.state.write_text(json.dumps({"state": state, "head": head, "url": "https://example.invalid/pr/4150"}))

    def fetch(self, at=MON_10):
        reviewcards.LAST_SCANNED.clear()
        return reviewcards.upkeep(self.cfg, self.board, {"work"}, at=at)

    def review_cards(self):
        return [c for c in self.board.list_cards(space="work") if c["options"].get("review_key")]

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []


class FilingTest(FetcherCase):
    def test_one_review_card_per_pull_request_in_the_inbox(self):
        result = self.fetch()
        [card] = self.review_cards()
        self.assertEqual(result["filed"], [card["id"]])
        self.assertEqual(card["stage"], "inbox")
        self.assertEqual(card["title"], "Review: Tidy the loader")
        self.assertEqual((card["repo"], card["model"], card["autonomy"]), ("api", "sonnet", "autonomous"))
        options = card["options"]
        self.assertEqual({k: options[k] for k in ("kind", "review_key", "slot", "pr", "branch", "base")},
                         {"kind": "review", "review_key": "api:4150", "slot": "review", "pr": 4150,
                          "branch": "feature/st-41001/tidy", "base": "main"})
        self.assertEqual(options["review_pr"]["author"], "Ana Example")
        self.assertEqual(options["review_pr"]["created"], "2026-09-20T09:00:00+00:00")
        self.assertIn("The loader reads its page cap once.", card["brief"])

    def test_it_is_idempotent_across_passes_and_across_stages(self):
        self.fetch()
        self.fetch(MON_10 + timedelta(hours=1))
        [card] = self.review_cards()
        for stage in ("assigned", "building", "review"):
            self.board.stage(card["id"], stage, "human" if stage == "assigned" else "drain",
                             plan_ref="p.md", output_ref="o")
            self.fetch(MON_10 + timedelta(hours=2))
        self.board.set_fields(card["id"], {"options": {"archived": True}}, "human")
        self.fetch(MON_10 + timedelta(hours=3))
        self.assertEqual(len(self.review_cards()), 1)

    def test_a_card_waits_in_the_inbox_until_he_assigns_it(self):
        self.fetch()
        [card] = self.review_cards()
        fake = FakeHarness()
        with mock.patch.object(house, "harness", fake), mock.patch.object(drain, "harness", fake), \
                mock.patch.object(drain, "machine", FakeMachine()), mock.patch.object(house, "APP_LINK_PAUSE", 0), \
                mock.patch.object(reviewcards, "now", return_value=MON_10 + timedelta(minutes=1)):
            drain.once(self.cfg, board=self.board, spaces=["work"])
            self.assertEqual(self.board.get(card["id"])["stage"], "inbox")
            self.assertEqual(fake.starts, [])

    def test_auto_review_on_files_it_at_assigned_and_off_at_the_inbox(self):
        self.lists([pr(4150), pr(4151)], auto=True)
        self.fetch()
        self.assertEqual({c["stage"] for c in self.review_cards()}, {"assigned"})
        self.lists([pr(4152)], auto=False)
        self.fetch(MON_10 + timedelta(hours=1))
        self.assertEqual(self.board.get(self.review_cards()[-1]["id"])["stage"], "inbox")

    def test_a_pull_request_from_a_fork_waits_for_his_tap_even_with_auto_review_on(self):
        """c-730 r1.F1: a fork's code is not his team's, and on a public host a stranger's fork
        can ask for his review without him, so its card is never started by itself, and it
        says where the code comes from."""
        self.lists([dict(pr(4150), fork=True), pr(4151)], auto=True)
        self.fetch()
        cards = {c["options"]["review_key"]: c for c in self.review_cards()}
        fork, own = cards["api:4150"], cards["api:4151"]
        self.assertEqual((fork["stage"], own["stage"]), ("inbox", "assigned"))
        self.assertTrue(fork["options"]["review_fork"])
        self.assertNotIn("review_fork", own["options"])
        self.assertIn("comes from a fork", fork["brief"])
        self.assertIn("reads that code and never runs it", fork["brief"])          # r2.F3
        self.assertIn("from a fork, so it waits for your Review", self.board.events(fork["id"])[-1]["text"])

    def test_the_review_model_is_the_new_card_s_model(self):
        self.lists([pr()], model="opus")
        self.fetch()
        self.assertEqual(self.review_cards()[0]["model"], "opus")

    def test_the_settings_are_the_space_s_own_not_the_listing_s(self):
        """RT-2: keel.toml's `review_auto` and `review_model` decide; a listing in the old
        shape that still says settings (the scanner's flag files) is not read."""
        self.cfg.spaces["work"].review_auto = True
        self.cfg.spaces["work"].review_model = "opus"
        self.listing.write_text(json.dumps({"prs": [pr()], "settings": {"auto": False, "model": "sonnet"}}))
        self.fetch()
        [card] = self.review_cards()
        self.assertEqual((card["stage"], card["model"]), ("assigned", "opus"))

    def test_the_cadence_is_the_watcher_s(self):
        reviewcards.upkeep(self.cfg, self.board, {"work"}, at=MON_10)
        reviewcards.upkeep(self.cfg, self.board, {"work"}, at=MON_10 + timedelta(minutes=5))
        self.assertEqual([c for c in self.calls() if c == "review scan"], ["review scan"])
        reviewcards.upkeep(self.cfg, self.board, {"work"}, at=MON_10 + timedelta(minutes=16))
        self.assertEqual(len([c for c in self.calls() if c == "review scan"]), 2)


class ClosedAndNewTest(FetcherCase):
    def test_a_pull_request_closed_before_review_makes_the_card_a_notice(self):
        self.fetch()
        [card] = self.review_cards()
        self.lists([])
        self.polls("merged", "head-1")
        result = self.fetch(MON_10 + timedelta(hours=1))
        # The board's clock is pinned to the fetch: read at the wall clock, the fixture's
        # pull request has been quiet past `review_backlog_days` since 2026-10-06 (c-669).
        with mock.patch.object(self.board, "now", return_value=(MON_10 + timedelta(hours=1)).isoformat()):
            card = self.board.get(card["id"])
        self.assertEqual(result["notices"], 1)
        self.assertTrue(card["derived"]["notice"])
        self.assertTrue(card["derived"]["needs_you"])
        self.fetch(MON_10 + timedelta(hours=2))
        self.assertEqual(len([c for c in self.calls() if c.endswith("poll")]), 1)

    def test_one_that_merely_left_the_list_is_left_as_it_is(self):
        self.fetch()
        self.lists([])
        self.fetch(MON_10 + timedelta(hours=1))
        self.assertFalse(self.review_cards()[0]["derived"]["notice"])

    def posted_card(self, head="head-1"):
        self.fetch()
        [card] = self.review_cards()
        self.board.stage(card["id"], "assigned", "human")
        self.board.stage(card["id"], "building", "drain")
        self.board.stage(card["id"], "review", "house", plan_ref="p.md", output_ref="o")
        self.board.approve(card["id"], "outcome", "human", publish=lambda c: {"posted": True})
        self.board.set_fields(card["id"], {"options": {"review_posted": {"head": head, "round": 1}}}, "human")
        return card["id"]

    def test_new_commits_after_a_posted_review_show_on_the_card(self):
        card_id = self.posted_card()
        self.lists([pr(head="head-2")])
        result = self.fetch(MON_10 + timedelta(hours=1))
        card = self.board.get(card_id)
        self.assertEqual(result["new"], 1)
        self.assertEqual(card["options"]["review_new"]["head"], "head-2")
        self.assertEqual(card["stage"], "done")
        self.assertIn("new commits since your review", [e.get("text") or "" for e in self.board.events(card_id)][-1])

    def test_an_approved_pull_request_off_the_list_is_polled_for_its_head(self):
        card_id = self.posted_card()
        self.lists([])
        self.polls("open", "head-3")
        self.fetch(MON_10 + timedelta(hours=1))
        self.assertEqual(self.board.get(card_id)["options"]["review_new"]["head"], "head-3")

    def test_the_same_head_says_nothing_and_a_closed_one_is_left_alone_after(self):
        card_id = self.posted_card()
        self.fetch(MON_10 + timedelta(hours=1))
        self.assertNotIn("review_new", self.board.get(card_id)["options"])
        self.lists([])
        self.polls("merged", "head-1")
        self.fetch(MON_10 + timedelta(hours=2))
        self.assertEqual(self.board.get(card_id)["options"]["review_closed"], "merged")
        self.fetch(MON_10 + timedelta(hours=3))
        self.assertEqual(len([c for c in self.calls() if c.endswith("poll")]), 1)


if __name__ == "__main__":
    unittest.main()


class DismissTest(FetcherCase):
    """RC-8 (2026-09-24): his Dismiss review hides the card, and the fetcher never files a
    second one for the pull request; NEW ACTIVITY on it after the dismissal (a push, a
    comment, a reviewer asked, the host's own update stamp, or a new head this fetcher saw)
    brings the SAME card back, as the deck's line for Dismiss review says."""

    DISMISSED = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)

    def dismiss(self):
        [card] = self.review_cards()
        with mock.patch.object(self.board, "now", return_value=self.DISMISSED.isoformat()):
            self.board.set_fields(card["id"], {"options": {"archived": True}}, "human")
        return card["id"]

    def test_a_dismissed_review_is_not_filed_again_while_its_pull_request_is_still(self):
        self.fetch()
        card_id = self.dismiss()
        self.fetch(MON_10 + timedelta(hours=4))
        self.fetch(MON_10 + timedelta(hours=5))
        [card] = self.review_cards()
        self.assertEqual(card["id"], card_id)
        self.assertTrue(card["derived"]["archived"])

    def test_activity_from_before_the_dismissal_does_not_bring_it_back(self):
        self.fetch()
        card_id = self.dismiss()
        self.lists([pr() | {"updated": (self.DISMISSED - timedelta(minutes=30)).isoformat()}])
        self.fetch(MON_10 + timedelta(hours=4))
        self.assertTrue(self.board.get(card_id)["derived"]["archived"])

    def test_new_activity_after_the_dismissal_brings_the_same_card_back(self):
        self.fetch()
        card_id = self.dismiss()
        later = (self.DISMISSED + timedelta(hours=2)).isoformat()
        self.lists([pr() | {"updated": later}])
        self.fetch(MON_10 + timedelta(hours=4))
        [card] = self.review_cards()
        self.assertEqual(card["id"], card_id)
        self.assertFalse(card["derived"]["archived"])
        self.assertNotIn("archived", card["options"])
        self.assertEqual(card["options"]["review_pr"]["activity"], later)
        notes = [e["text"] for e in self.board.events(card_id) if e["kind"] == "note"]
        self.assertTrue(any("since you dismissed" in (n or "") for n in notes), notes)

    def test_a_new_head_after_the_dismissal_brings_it_back_too(self):
        self.fetch()
        card_id = self.dismiss()
        self.lists([pr(head="head-2")])
        self.fetch(MON_10 + timedelta(hours=4))
        self.assertFalse(self.board.get(card_id)["derived"]["archived"])

    def test_a_card_archived_before_this_rule_with_no_dismissal_event_stays_put(self):
        self.fetch()
        [card] = self.review_cards()
        with self.board.tx():
            self.board.conn.execute("UPDATE cards SET options = json_set(options, '$.archived', json('true')) "
                                    "WHERE id = ?", (card["id"],))
        self.lists([pr(head="head-2")])
        self.fetch(MON_10 + timedelta(hours=4))
        self.assertTrue(self.board.get(card["id"])["derived"]["archived"])


class ReReviewTest(FetcherCase):
    """RC-5: his Re-review starts a new round on the SAME card: back to assigned, the round
    counted, the new commits taken; the drain then starts it fresh in the review pool."""

    def posted_with_new_commits(self):
        self.fetch()
        [card] = self.review_cards()
        card_id = card["id"]
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        self.board.stage(card_id, "review", "house", plan_ref="p.md", output_ref="o")
        self.board.approve(card_id, "outcome", "human", publish=lambda c: {"posted": True})
        self.board.set_fields(card_id, {"options": {"review_posted": {"head": "head-1", "round": 1,
                                                                       "ledger": []}}}, "human")
        self.lists([pr(head="head-2")])
        self.fetch(MON_10 + timedelta(hours=1))
        return card_id

    def test_re_review_is_a_new_round_on_the_same_card(self):
        card_id = self.posted_with_new_commits()
        card = self.board.rereview(card_id, "human")
        self.assertEqual(card["stage"], "assigned")
        self.assertEqual(card["options"]["review_round"], 2)
        self.assertNotIn("review_new", card["options"])
        self.assertEqual(card["options"]["review_posted"]["head"], "head-1")
        self.assertEqual(len(self.review_cards()), 1)

    def test_only_he_re_reviews_and_only_a_posted_card_with_new_commits(self):
        card_id = self.posted_with_new_commits()
        for actor in ("house", "drain", "cli"):
            with self.assertRaisesRegex(Refused, "the user's"):
                self.board.rereview(card_id, actor)
        other = self.board.create("work", "not a review", repo="api", actor="human")
        with self.assertRaisesRegex(Refused, "not a review card"):
            self.board.rereview(other, "human")
        self.board.set_fields(card_id, {"options": {"review_new": None}}, "human")
        with self.assertRaisesRegex(Refused, "no new commits"):
            self.board.rereview(card_id, "human")


class ReviewStateTest(FetcherCase):
    """`derived.review`: the one word the Reviews list, `kb` and the voice digest read."""

    def test_the_word_follows_the_card(self):
        self.fetch()
        [card] = self.review_cards()
        word = lambda: self.board.get(card["id"])["derived"]["review"]
        self.assertEqual(word(), "waiting")
        self.board.stage(card["id"], "assigned", "human")
        self.assertEqual(word(), "reviewing")
        self.board.stage(card["id"], "building", "drain")
        self.board.stage(card["id"], "review", "house", plan_ref="p.md", output_ref="o")
        self.assertEqual(word(), "gate")
        self.board.approve(card["id"], "outcome", "human", publish=lambda c: {"posted": True})
        self.assertIsNone(self.board.get(card["id"])["derived"]["review_severity"])
        self.board.set_fields(card["id"], {"options": {"review_posted": {"head": "head-1", "severity": "high"}}}, "human")
        self.assertEqual(word(), "posted")
        self.assertEqual(self.board.get(card["id"])["derived"]["review_severity"], "high")
        self.board.set_fields(card["id"], {"options": {"review_new": {"head": "head-2"}}}, "drain")
        self.assertEqual(word(), "new")
        self.board.set_fields(card["id"], {"options": {"review_closed": "merged"}}, "drain")
        self.assertEqual(word(), "closed")
        other = self.board.create("work", "not a review", repo="api", actor="human")
        self.assertIsNone(self.board.get(other)["derived"]["review"])


class BacklogTest(FetcherCase):
    """A review card at the inbox backlogs when its pull request has been quiet longer than
    `[spaces.work] review_backlog_days` (15): derived from the activity stamp the fetcher
    refreshes on every poll, never a stored move; his override still wins."""

    NOW = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)

    def quiet(self, days, **over):
        at = (self.NOW - timedelta(days=days)).isoformat()
        return pr(**over) | {"created": at, "updated": at}

    def card_now(self):
        [card] = self.review_cards()
        with mock.patch.object(self.board, "now", return_value=self.NOW.isoformat()):
            return self.board.get(card["id"])

    def test_a_pull_request_quiet_for_20_days_is_backlog_and_one_active_today_is_not(self):
        self.lists([self.quiet(20)])
        self.fetch(self.NOW)
        card = self.card_now()
        self.assertTrue(card["derived"]["backlog"])
        self.assertFalse(card["derived"]["needs_you"])
        self.assertEqual(card["options"]["review_pr"]["backlog_days"], 15)
        self.assertEqual(card["derived"]["backlog_since"], (self.NOW - timedelta(days=20)).isoformat())

    def test_a_new_comment_or_push_brings_it_out_on_the_next_poll_and_quiet_drops_it_back(self):
        self.lists([self.quiet(20)])
        self.fetch(self.NOW)
        self.assertTrue(self.card_now()["derived"]["backlog"])
        self.lists([self.quiet(20) | {"updated": (self.NOW - timedelta(hours=1)).isoformat()}])
        self.fetch(self.NOW + timedelta(minutes=16))
        self.assertFalse(self.card_now()["derived"]["backlog"])
        self.lists([self.quiet(20, head="head-9")])
        self.fetch(self.NOW + timedelta(hours=1))
        self.assertFalse(self.card_now()["derived"]["backlog"], "a new head is activity even when the host's stamp is old")

    def test_the_override_wins_both_ways(self):
        self.lists([self.quiet(20)])
        self.fetch(self.NOW)
        card = self.review_cards()[0]
        self.board.set_fields(card["id"], {"options": {"backlog": "active"}}, "human")
        self.assertFalse(self.card_now()["derived"]["backlog"])
        self.board.set_fields(card["id"], {"options": {"backlog": "backlog"}}, "human")
        self.lists([self.quiet(1)])
        self.fetch(self.NOW + timedelta(hours=1))
        self.assertTrue(self.card_now()["derived"]["backlog"])

    def test_his_own_note_does_not_move_this_rule_which_reads_the_pull_request_alone(self):
        """c-673 restarts the outcome gate's clock at his action; this rule is not that one."""
        self.lists([self.quiet(20)])
        self.fetch(self.NOW)
        quiet = self.card_now()["derived"]["backlog_since"]
        with mock.patch.object(self.board, "now", return_value=self.NOW.isoformat()):
            self.board.note(self.review_cards()[0]["id"], "looked", "human")
        card = self.card_now()
        self.assertTrue(card["derived"]["backlog"])
        self.assertEqual(card["derived"]["backlog_since"], quiet)

    def test_only_the_inbox_backlogs_a_review_card_and_review_still_assigns_it(self):
        self.lists([self.quiet(20)])
        self.fetch(self.NOW)
        card = self.review_cards()[0]
        self.board.stage(card["id"], "assigned", "human")
        self.assertFalse(self.card_now()["derived"]["backlog"])

    def test_the_first_run_files_an_old_open_one_into_the_backlog_and_nothing_for_a_closed_one(self):
        """What the adapter lists is what is open and his (a closed pull request is not
        listed): an old quiet one gets its card, in the backlog; the closed one none."""
        self.lists([self.quiet(40, number=4100)])
        self.fetch(self.NOW)
        card = self.card_now()
        self.assertEqual((card["options"]["review_key"], card["stage"]), ("api:4100", "inbox"))
        self.assertTrue(card["derived"]["backlog"])
        self.assertEqual(len(self.review_cards()), 1)

    def test_the_days_come_from_the_space(self):
        self.cfg.spaces["work"].review_backlog_days = 30
        self.lists([self.quiet(20)])
        self.fetch(self.NOW)
        self.assertFalse(self.card_now()["derived"]["backlog"])
