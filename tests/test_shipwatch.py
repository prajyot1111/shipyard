"""SH-2 and SH-3: the pull request watcher's rules, as pure functions over the card's record.

What the adapter saw on the code host (a "sight", `packs/work/prsight.py`) is folded into
`options.shipping` (`shipwatch.fold`); `shipwatch.due` says when the waiting items become a
batch; `shipwatch.poll_every` says how often to look. Every time here is invented and
every pull request is too.
"""

import unittest
from datetime import datetime, timedelta, timezone

from keel import shipwatch

MON_10 = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)      # a Monday, in work hours
HOURS = shipwatch.WorkHours(start=9 * 60, end=19 * 60, days=(0, 1, 2, 3, 4), tz=timezone.utc)


def stamp(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


def sight(comments=(), reviews=(), ci=None, state="open", behind=0, approvals=0, head="aaa111"):
    return {"state": state, "url": "https://example.invalid/pr/7", "head": head, "behind": behind,
            "approvals": approvals, "comments": list(comments), "reviews": list(reviews),
            "ci": ci or {"state": "none"}}


def comment(number: int, at: datetime, author="Ana Example", text="please rename this"):
    return {"id": number, "author": author, "at": stamp(at), "text": text,
            "path": "app/thing.py", "line": 40, "parent": None}


def baseline(at=MON_10, **kwargs) -> dict:
    """The record after the first look: everything already there is seen, nothing waits."""
    shipped, events = shipwatch.fold({"since": stamp(at), "round": 0}, sight(**kwargs), at)
    assert events == [] and not shipped["pending"]
    return shipped


class CadenceTest(unittest.TestCase):
    """c-600: 2 minutes while items wait, 3 while told items are open or it moved in the last
    hour, 10 in work hours, hourly at night and at weekends."""

    def test_waiting_items_are_looked_at_every_two_minutes_at_any_hour(self):
        shipped = {"pending": [{"handle": "c1"}]}
        for at in (MON_10, MON_10.replace(hour=22), MON_10 + timedelta(days=5)):
            self.assertEqual(shipwatch.poll_every(at, shipped, HOURS), timedelta(minutes=2), at)

    def test_open_told_items_or_recent_activity_is_every_three_minutes(self):
        told = {"told": [{"handle": "c1"}, {"handle": "c2"}], "posted": {"c1": "x"}}
        self.assertEqual(shipwatch.poll_every(MON_10, told, HOURS), timedelta(minutes=3))
        answered = {"told": [{"handle": "c1"}], "posted": {"c1": "x"}}
        self.assertEqual(shipwatch.poll_every(MON_10, answered, HOURS), timedelta(minutes=10))
        moved = {"activity_at": stamp(MON_10 - timedelta(minutes=50))}
        self.assertEqual(shipwatch.poll_every(MON_10, moved, HOURS), timedelta(minutes=3))
        approved = {"since": stamp(MON_10 - timedelta(minutes=5))}
        self.assertEqual(shipwatch.poll_every(MON_10, approved, HOURS), timedelta(minutes=3),
                         "a pull request just made ready is watched closely (e2e: 14 min to see a merge)")

    def test_work_hours_without_recent_activity_is_every_ten_minutes(self):
        shipped = {"activity_at": stamp(MON_10 - timedelta(minutes=61))}
        self.assertEqual(shipwatch.poll_every(MON_10, shipped, HOURS), timedelta(minutes=10))
        self.assertEqual(shipwatch.poll_every(MON_10, {}, HOURS), timedelta(minutes=10))

    def test_quiet_nights_and_weekends_are_hourly(self):
        quiet = {"activity_at": stamp(MON_10 - timedelta(days=1))}
        for at in (MON_10.replace(hour=22), MON_10 + timedelta(days=5), MON_10.replace(hour=8, minute=59)):
            self.assertEqual(shipwatch.poll_every(at, quiet, HOURS), timedelta(hours=1), at)

    def test_his_ship_counts_as_activity(self):
        shipped = {"shipped_at": stamp(MON_10 - timedelta(minutes=10))}
        self.assertEqual(shipwatch.poll_every(MON_10, shipped, HOURS), timedelta(minutes=3))

    def test_a_first_look_is_due_at_once(self):
        self.assertTrue(shipwatch.poll_due(MON_10, None, {}, HOURS))
        just = MON_10 - timedelta(minutes=1)
        self.assertFalse(shipwatch.poll_due(MON_10, just, {}, HOURS))
        self.assertTrue(shipwatch.poll_due(MON_10, MON_10 - timedelta(minutes=10), {}, HOURS))

    def test_work_hours_come_from_the_config_words(self):
        hours = shipwatch.WorkHours.parse("08:30-17:00", "mon-thu")
        self.assertEqual((hours.start, hours.end, hours.days), (8 * 60 + 30, 17 * 60, (0, 1, 2, 3)))
        with self.assertRaises(ValueError):
            shipwatch.WorkHours.parse("9-5", "mon-fri")
        with self.assertRaises(ValueError):
            shipwatch.WorkHours.parse("09:00-17:00", "funday")


class FoldTest(unittest.TestCase):
    def test_the_first_look_is_a_baseline_that_flags_nothing(self):
        old = comment(1, MON_10 - timedelta(days=2))
        shipped = baseline(comments=[old], reviews=[{"author": "Bo", "state": "changes_requested"}])
        self.assertEqual(shipped["seen"]["comments"], [1])
        self.assertEqual(shipped["facts"]["comments"], 1)

    def test_the_first_look_tells_what_came_after_the_card_entered_shipping(self):
        """c-604: the sandbox's comment and failed check ten seconds after Approve were taken
        as baseline on the first look and never told (the chip said "1 comment, checks
        failed" with no rows). Only what is no later than `since` is baseline."""
        after = MON_10 + timedelta(seconds=10)
        old = comment(1, MON_10 - timedelta(days=1))
        new, events = shipwatch.fold(
            {"since": stamp(MON_10), "round": 0},
            sight(comments=[old, comment(2, after)],
                  reviews=[{"author": "Bo", "state": "changes_requested", "at": stamp(after), "state_at": stamp(after)}],
                  ci={"state": "failed", "name": "unit", "at": stamp(after)}),
            MON_10 + timedelta(minutes=2))
        self.assertEqual(events, [])
        self.assertEqual(sorted(item["handle"] for item in new["pending"]), ["c2", "ci", "review-bo"])
        self.assertEqual(new["seen"]["comments"], [1, 2])
        again, _ = shipwatch.fold(new, sight(comments=[old, comment(2, after)],
                                             reviews=[{"author": "Bo", "state": "changes_requested", "at": stamp(after), "state_at": stamp(after)}],
                                             ci={"state": "failed", "name": "unit", "at": stamp(after)}),
                                  MON_10 + timedelta(minutes=4))
        self.assertEqual(len(again["pending"]), 3, "nothing is added twice")

    def test_an_old_review_the_reviewer_took_part_in_since_is_not_told_again(self):
        """c-604 review: the host's `at` moves whenever the reviewer takes part; only the time
        the review's STATE was set (`state_at`) says it is new."""
        after = MON_10 + timedelta(minutes=1)
        old = {"author": "Bo", "state": "changes_requested", "at": stamp(after),
               "state_at": stamp(MON_10 - timedelta(days=1))}
        bare = {"author": "Cy", "state": "changes_requested", "at": stamp(after)}
        new, _ = shipwatch.fold({"since": stamp(MON_10), "round": 0}, sight(reviews=[old, bare]), after)
        self.assertEqual(new["pending"], [])

    def test_an_old_comment_edited_after_the_approve_is_told_as_edited(self):
        edited = dict(comment(1, MON_10 - timedelta(days=1)), updated=stamp(MON_10 + timedelta(seconds=30)))
        untouched = dict(comment(2, MON_10 - timedelta(days=1)), updated=stamp(MON_10 - timedelta(days=1)))
        new, _ = shipwatch.fold({"since": stamp(MON_10), "round": 0}, sight(comments=[edited, untouched]),
                                MON_10 + timedelta(minutes=1))
        self.assertEqual([(i["handle"], i.get("edited")) for i in new["pending"]], [("c1", True)])

    def test_a_failed_check_from_before_the_approve_is_baseline(self):
        shipped = baseline(ci={"state": "failed", "at": stamp(MON_10 - timedelta(hours=1))})
        self.assertEqual(shipped["pending"], [])

    def test_a_new_comment_by_someone_else_waits_in_the_batch(self):
        shipped = baseline()
        new, events = shipwatch.fold(shipped, sight(comments=[comment(9, MON_10)]), MON_10)
        self.assertEqual(events, [])
        self.assertEqual([item["handle"] for item in new["pending"]], ["c9"])
        self.assertEqual(new["pending"][0]["text"], "please rename this")
        self.assertEqual(new["facts"]["waiting"], 1)
        self.assertEqual(new["activity_at"], stamp(MON_10))
        again, _ = shipwatch.fold(new, sight(comments=[comment(9, MON_10)]), MON_10 + timedelta(minutes=5))
        self.assertEqual(len(again["pending"]), 1, "a comment already seen is not added twice")

    def test_merged_and_declined_are_events(self):
        shipped = baseline()
        self.assertEqual(shipwatch.fold(shipped, sight(state="merged"), MON_10)[1], ["merged"])
        self.assertEqual(shipwatch.fold(shipped, sight(state="declined"), MON_10)[1], ["declined"])

    def test_the_facts_are_what_the_deck_chip_says(self):
        shipped = baseline(behind=3, approvals=1, ci={"state": "passed"})
        self.assertEqual(shipped["facts"], {"state": "open", "comments": 0, "approvals": 1,
                                            "ci": "passed", "behind": 3, "waiting": 0, "draft": False})

    def test_nothing_new_changes_nothing(self):
        shipped = baseline(comments=[comment(1, MON_10)])
        again, _ = shipwatch.fold(shipped, sight(comments=[comment(1, MON_10)]), MON_10 + timedelta(hours=1))
        self.assertEqual(again, shipped)


class DebounceTest(unittest.TestCase):
    def watch(self, shipped, looks):
        """Fold each (at, sight) in turn, checking `due` at every minute in between; the
        instants at which a batch went, and the batches."""
        batches = []
        start, end = looks[0][0], looks[-1][0] + timedelta(hours=3)
        pending_looks = list(looks)
        at = start
        while at <= end:
            while pending_looks and pending_looks[0][0] <= at:
                _, seen = pending_looks.pop(0)
                shipped, _ = shipwatch.fold(shipped, seen, at)
            if shipwatch.due(shipped, at):
                items, shipped = shipwatch.take_batch(shipped, at)
                batches.append((at, [item["handle"] for item in items]))
            at += timedelta(minutes=1)
        return batches

    def test_a_comment_every_minute_for_four_minutes_makes_one_batch(self):
        """Looked at every two minutes, as the watcher does while items wait."""
        said = [comment(100 + n, MON_10 + timedelta(minutes=n)) for n in range(4)]
        looks = [(MON_10 + timedelta(minutes=2 * k),
                  sight(comments=[c for c in said if shipwatch.parse(c["at"]) <= MON_10 + timedelta(minutes=2 * k)]))
                 for k in range(0, 6)]
        batches = self.watch(baseline(MON_10 - timedelta(minutes=1)), looks)
        self.assertEqual(len(batches), 1, batches)
        went, handles = batches[0]
        self.assertEqual(len(handles), 4)
        self.assertEqual(went, MON_10 + timedelta(minutes=3 + 5), "the quiet window runs from the last comment")

    def test_the_thirty_minute_cap_sends_the_batch_while_comments_keep_coming(self):
        said = [comment(200 + n, MON_10 + timedelta(minutes=n)) for n in range(0, 90, 3)]
        looks = [(MON_10 + timedelta(minutes=2 * k),
                  sight(comments=[c for c in said if shipwatch.parse(c["at"]) <= MON_10 + timedelta(minutes=2 * k)]))
                 for k in range(0, 45)]
        batches = self.watch(baseline(MON_10 - timedelta(minutes=1)), looks)
        self.assertEqual(batches[0][0], MON_10 + timedelta(minutes=30))

    def test_a_submitted_review_asking_for_changes_starts_at_once(self):
        shipped = baseline()
        new, _ = shipwatch.fold(shipped, sight(reviews=[{"author": "Bo Example", "state": "changes_requested",
                                                         "at": stamp(MON_10)}]), MON_10)
        self.assertTrue(shipwatch.due(new, MON_10))
        self.assertEqual(new["pending"][0]["handle"], "review-bo-example")

    def test_an_approval_with_comments_starts_at_once_and_a_bare_approval_waits_for_nothing(self):
        shipped = baseline()
        bare, _ = shipwatch.fold(shipped, sight(reviews=[{"author": "Bo", "state": "approved"}], approvals=1), MON_10)
        self.assertFalse(shipwatch.due(bare, MON_10))
        self.assertEqual(bare["pending"], [])
        self.assertEqual(bare["facts"]["approvals"], 1)
        with_words, _ = shipwatch.fold(shipped, sight(comments=[comment(5, MON_10, author="Bo")],
                                                      reviews=[{"author": "Bo", "state": "approved"}]), MON_10)
        self.assertTrue(shipwatch.due(with_words, MON_10))

    def test_a_ci_failure_waits_five_minutes_and_a_green_rerun_takes_it_back(self):
        shipped = baseline(ci={"state": "running"})
        failed = sight(ci={"state": "failed", "name": "a check", "url": "https://example.invalid/ci/1"})
        new, _ = shipwatch.fold(shipped, failed, MON_10)
        self.assertEqual([item["handle"] for item in new["pending"]], ["ci"])
        self.assertFalse(shipwatch.due(new, MON_10 + timedelta(minutes=4)))
        self.assertTrue(shipwatch.due(new, MON_10 + timedelta(minutes=5)))
        green, _ = shipwatch.fold(new, sight(ci={"state": "passed"}), MON_10 + timedelta(minutes=3))
        self.assertEqual(green["pending"], [])
        again, _ = shipwatch.fold(new, failed, MON_10 + timedelta(minutes=4))
        self.assertEqual(len(again["pending"]), 1, "the same failure is one item")

    def test_a_failed_checks_quiet_is_timed_from_the_hosts_own_time(self):
        """c-605: the timer started at the drain's first look, not when the check failed."""
        shipped = baseline(ci={"state": "running"})
        failed = sight(ci={"state": "failed", "name": "unit", "at": stamp(MON_10 + timedelta(minutes=1))})
        new, _ = shipwatch.fold(shipped, failed, MON_10 + timedelta(minutes=4))
        self.assertEqual(new["ci_at"], stamp(MON_10 + timedelta(minutes=1)))
        self.assertEqual(new["pending"][0]["at"], stamp(MON_10 + timedelta(minutes=1)))
        self.assertFalse(shipwatch.due(new, MON_10 + timedelta(minutes=5)))
        self.assertTrue(shipwatch.due(new, MON_10 + timedelta(minutes=6)))
        ahead = sight(ci={"state": "failed", "name": "unit", "at": stamp(MON_10 + timedelta(hours=1))})
        clamped, _ = shipwatch.fold(shipped, ahead, MON_10)
        self.assertEqual(clamped["ci_at"], stamp(MON_10), "a host clock ahead never waits longer")

    def test_taking_the_batch_tells_it_and_clears_the_wait(self):
        shipped = baseline()
        new, _ = shipwatch.fold(shipped, sight(comments=[comment(3, MON_10)]), MON_10)
        items, taken = shipwatch.take_batch(new, MON_10)
        self.assertEqual([item["handle"] for item in items], ["c3"])
        self.assertEqual(taken["round"], 1)
        self.assertEqual([(i["handle"], i["batch"]) for i in taken["told"]], [("c3", 1)])
        self.assertEqual(taken["pending"], [])
        for timer in ("first_at", "last_at", "urgent", "ci_at"):
            self.assertNotIn(timer, taken)
        self.assertEqual(taken["facts"]["waiting"], 0)
        later, _ = shipwatch.fold(taken, sight(comments=[comment(3, MON_10), comment(4, MON_10)]), MON_10)
        self.assertEqual([item["handle"] for item in later["pending"]], ["c4"],
                         "an arrival while the house works waits for the next batch")
        _, second = shipwatch.take_batch(later, MON_10 + timedelta(minutes=9))
        self.assertEqual([(i["handle"], i["batch"]) for i in second["told"]], [("c3", 1), ("c4", 2)])

    def test_a_check_that_fails_again_replaces_its_row_and_is_open_again(self):
        told = {"told": [{"handle": "ci", "batch": 1}], "posted": {"ci": "d1"}, "round": 1,
                "pending": [{"kind": "ci", "handle": "ci"}]}
        _, taken = shipwatch.take_batch(told, MON_10)
        self.assertEqual([(i["handle"], i["batch"]) for i in taken["told"]], [("ci", 2)])
        self.assertEqual(taken["posted"], {})


class ConfigTest(unittest.TestCase):
    def load(self, extra: str):
        import tempfile
        from pathlib import Path

        from keel import config
        from tests.helpers import write_toml
        with tempfile.TemporaryDirectory() as tmp:
            path = write_toml(Path(tmp))
            text = path.read_text().replace("[keel]\n", "[keel]\n" + extra, 1)
            path.write_text(text)
            return config.load(path, ensure=False)

    def test_the_defaults_are_nine_to_seven_on_weekdays(self):
        hours = self.load("").ship_hours
        self.assertEqual((hours.start, hours.end, hours.days), (540, 1140, (0, 1, 2, 3, 4)))

    def test_keel_toml_sets_them_and_a_typo_is_warned_about_at_load(self):
        cfg = self.load('work_hours = "10:00-16:00"\nwork_days = "tue-sat"\n')
        self.assertEqual(cfg.ship_hours.days, (1, 2, 3, 4, 5))
        typo = self.load('work_hours = "ten to four"\n')    # c-633: the default, and a warning
        self.assertEqual(typo.work_hours, "09:00-19:00")
        self.assertIn("work_hours", typo.warnings[0])


if __name__ == "__main__":
    unittest.main()
