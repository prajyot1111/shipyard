"""His "Scan now" on the Reviews page (2026-09-25): the review fetcher looks at once, on the
machine that holds the space, instead of waiting out its cadence (15 minutes in work hours,
hourly outside). The tap leaves an ask in `state/review-scan.json` (through the adapter's
`act do reviews scan_now`); the drain's next pass scans when it is due OR asked, then records
when it scanned and clears the ask, so the page can say "scanned 2 min ago"."""

from datetime import timedelta

from keel import reviewcards, reviewsettings
from tests.test_reviewgroups import MON_10, GroupCase, pr


class ScanNowTest(GroupCase):
    def test_an_ask_scans_before_the_cadence_is_due_and_is_cleared(self):
        self.fetch()                                    # the first pass looks: never looked yet
        self.lists([pr(4150, group=None)])
        reviewcards.upkeep(self.cfg, self.board, {"work"}, at=MON_10 + timedelta(minutes=2))  # not due: nothing
        self.assertEqual(self.cards(), [])
        reviewsettings.ask_scan(self.cfg, "work", MON_10 + timedelta(minutes=3))
        self.assertIn("asked", reviewsettings.scan_state(self.cfg, "work"))
        reviewcards.upkeep(self.cfg, self.board, {"work"}, at=MON_10 + timedelta(minutes=4))
        self.assertEqual([c["options"]["review_key"] for c in self.cards()], ["api:4150"])
        state = reviewsettings.scan_state(self.cfg, "work")
        self.assertNotIn("asked", state)
        self.assertEqual(state["last"], (MON_10 + timedelta(minutes=4)).isoformat())

    def test_every_scan_records_when_it_looked(self):
        self.fetch()
        self.assertEqual(reviewsettings.scan_state(self.cfg, "work")["last"], MON_10.isoformat())

    def test_an_ask_for_an_unknown_space_is_refused(self):
        with self.assertRaises(reviewsettings.SettingError):
            reviewsettings.ask_scan(self.cfg, "nowhere")
