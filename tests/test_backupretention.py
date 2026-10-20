"""The keel set's retention (c-752): hourly snapshots for a day, one a day to thirty days,
one a month beyond, and the newest of all whatever its age.

The rule is `retained_deletions` in `bin/keel-backup`, and it is asked here the way the
hourly job asks it: a made-up listing is written into a scratch store, by name alone
(retention reads nothing of a snapshot but the time in its id), the real `snapshot` run
is made over it, and the test reads which names the store still holds. The ids are placed
from the fixture's one reading of the clock (`tests/backupslimcase.py`), so no date makes
this fail.

The listing sits on the two edges the change moved: a day's two snapshots just past 24
hours old, and a month's two just past 30 days. The harbor set is run over the same
listing and keeps all of it, which is what 7 and 90 keep, so the change is the keel set's
alone.
"""

import unittest

from tests.backupslimcase import GPG, SlimCase, day, hours_ago


def just_past_a_day() -> tuple[str, str]:
    """Two snapshots of one calendar day, an hour apart, both 25 to 27 hours old."""
    older = 26 if hours_ago(26)[:8] == hours_ago(25)[:8] else 27
    return hours_ago(older), hours_ago(older - 1)


def just_past_thirty_days() -> tuple[str, str]:
    """Two snapshots on two days of one calendar month, both 31 to 34 days old."""
    older = 32 if day(32)[:6] == day(31)[:6] else 33
    return day(older), day(older - 1)


LAST_DAY = [hours_ago(20), hours_ago(5), hours_ago(1)]
DAY_OLDER, DAY_NEWEST = just_past_a_day()
EARLY, LATE = day(3), day(3, 1)                 # one day, three days back
ALONE = day(9)                                  # a day's only snapshot
MONTH_OLDER, MONTH_NEWEST = just_past_thirty_days()
LISTING = [*LAST_DAY, DAY_OLDER, DAY_NEWEST, EARLY, LATE, ALONE, MONTH_OLDER, MONTH_NEWEST]


@unittest.skipUnless(GPG, "gpg is not installed")
class RetentionTest(SlimCase):
    def named(self, name: str, sid: str):
        return self.store / "sets" / name / "snapshots" / sid[:4] / sid[4:6] / f"{sid}.tar.gz.gpg"

    def survivors(self, name: str, **env) -> set:
        """What the set's hourly run leaves of the listing."""
        for sid in LISTING:
            self.named(name, sid).parent.mkdir(parents=True, exist_ok=True)
            self.named(name, sid).write_bytes(b"a name is all retention reads\n")
        took = self.tool("snapshot", KEEL_BACKUP_SETS=name, **env)
        self.assertEqual(took.returncode, 0, took.stdout + took.stderr)
        kept = {sid for sid in LISTING if self.named(name, sid).exists()}
        self.assertIn(f"{len(LISTING) - len(kept)} pruned, {len(kept) + 1} kept", took.stdout,
                      "what is left is the survivors and the run's own snapshot, the newest of all")
        return kept

    def test_keel_keeps_hourly_for_a_day_daily_for_thirty_and_monthly_beyond(self):
        self.old_tree(self.live)
        kept = self.survivors("keel")
        self.assertLessEqual(set(LAST_DAY), kept, "every snapshot of the last day is kept")
        self.assertEqual(kept & {DAY_OLDER, DAY_NEWEST}, {DAY_NEWEST}, "an hour past a day old: the day's newest alone")
        self.assertEqual(kept & {EARLY, LATE}, {LATE}, "three days old: the day's newest alone")
        self.assertIn(ALONE, kept)
        self.assertEqual(kept & {MONTH_OLDER, MONTH_NEWEST}, {MONTH_NEWEST},
                         "a day past thirty days old: the month's newest alone")

    def test_harbor_keeps_what_seven_days_and_ninety_keep(self):
        """The same listing, another set: every snapshot of it is inside harbor's week of
        hourly copies or is the only one of its day inside its ninety days of dailies."""
        harbor = self.root / "harbor"
        self.write_tree(harbor, {"segments/fathom/data/index.json": b'{"asks": []}\n'})
        kept = self.survivors("harbor", KEEL_HARBOR_HOME=str(harbor))
        self.assertEqual(kept, set(LISTING))


if __name__ == "__main__":
    unittest.main()
