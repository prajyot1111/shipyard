"""One verdict for "is Keel healthy": the pure fold, the facts it is fed, and the field on
the deck's state document. Nothing here reaches a live process: the talker and the voice
gateway are only asked where this machine has them installed, and under the fence it has
neither."""

import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from keel import health
from tests.helpers import make_config

TALKER_OK = {"state": "serving", "ok": True, "reason": "session session_01"}
DRAIN_OK = {"alive": True, "age_seconds": 20}
def verdict(**facts):
    base = {"talker": TALKER_OK, "voice": {"installed": True, "ok": True}, "drain": DRAIN_OK,
            "backup": {"writes": False, "pulls": False}}
    base.update(facts)
    return health.verdict(base)


class VerdictTest(unittest.TestCase):
    def test_all_well_is_green_with_no_reasons(self):
        self.assertEqual(verdict(), {"level": "green", "reasons": []})

    def test_a_talker_fault_is_red(self):
        found = verdict(talker={"state": "no-session", "ok": False, "reason": "running 300s"})
        self.assertEqual(found, {"level": "red", "reasons": ["talker: no-session"]})

    def test_a_talker_still_starting_is_amber(self):
        found = verdict(talker={"state": "starting", "ok": True, "reason": "started 5s ago"})
        self.assertEqual(found, {"level": "amber", "reasons": ["talker: starting"]})

    def test_a_talker_not_installed_here_says_nothing(self):
        self.assertEqual(verdict(talker={"state": "not-installed", "ok": True, "reason": ""})["level"],
                         "green")

    def test_a_voice_gateway_installed_and_silent_is_red(self):
        found = verdict(voice={"installed": True, "ok": False})
        self.assertEqual(found, {"level": "red", "reasons": ["voice: not answering"]})
        self.assertEqual(verdict(voice={"installed": False, "ok": False})["level"], "green")

    def test_a_drain_quiet_for_minutes_is_amber_then_red(self):
        self.assertEqual(verdict(drain={"alive": False, "age_seconds": 400}),
                         {"level": "amber", "reasons": ["drain: no pass in over 5 minutes"]})
        self.assertEqual(verdict(drain={"alive": False, "age_seconds": 2000}),
                         {"level": "red", "reasons": ["drain: no pass in over 15 minutes"]})
        self.assertEqual(verdict(drain={"alive": False, "age_seconds": None}),
                         {"level": "red", "reasons": ["drain: no pass logged"]})

    def test_backup_staleness_is_red_and_a_late_pull_amber(self):
        stale = {"writes": True, "success_age": 7 * 3600, "pulls": False}
        self.assertEqual(verdict(backup=stale),
                         {"level": "red", "reasons": ["backup: no successful run in over 6h"]})
        late = {"writes": False, "pulls": True, "pull_age": 50 * 3600}
        self.assertEqual(verdict(backup=late),
                         {"level": "amber", "reasons": ["backup pull: none in over 48h"]})
        never = {"writes": True, "success_age": None, "pulls": False}
        self.assertEqual(verdict(backup=never)["level"], "red")

    def test_the_worst_item_sets_the_level_and_every_reason_is_kept(self):
        found = verdict(voice={"installed": True, "ok": False}, talker=None)
        self.assertEqual(found["level"], "red")
        self.assertEqual(found["reasons"], ["voice: not answering", "talker: unknown"])

    def test_a_fact_that_could_not_be_read_is_amber(self):
        self.assertEqual(verdict(talker=None),
                         {"level": "amber", "reasons": ["talker: unknown"]})


NOW = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc).timestamp()


class ServicesTest(unittest.TestCase):
    """The deck's services block (F4): one row per service with its state, its level and
    the instant its age counts from, so the page can say "passing, 20s" without a refetch."""

    def rows(self, **facts):
        base = {"talker": dict(TALKER_OK, since=NOW - 3 * 3600),
                "voice": {"installed": True, "ok": True},
                "drain": {"alive": True, "age_seconds": 20, "at": "2026-09-24T09:59:40+00:00"},
                "backup": {"writes": True, "success_age": 1800, "pulls": False}}
        base.update(facts)
        return {row["name"]: row for row in health.services(base, NOW)}


    def test_a_fault_carries_the_verdicts_own_level(self):
        rows = self.rows(talker={"state": "no-session", "ok": False, "reason": "x"},
                         drain={"alive": False, "age_seconds": 2000, "at": "2026-09-24T09:26:40+00:00"},
                         voice={"installed": True, "ok": False},
                         backup={"writes": True, "success_age": 7 * 3600, "pulls": False})
        self.assertEqual((rows["talker"]["state"], rows["talker"]["level"]), ("no-session", "red"))
        self.assertEqual((rows["drain"]["state"], rows["drain"]["level"]), ("quiet", "red"))
        self.assertEqual((rows["voice"]["state"], rows["voice"]["level"]), ("not answering", "red"))
        self.assertEqual(rows["backup"]["level"], "red")

    def test_a_service_this_machine_does_not_run_says_so_and_has_no_level(self):
        rows = self.rows(talker={"state": "not-installed", "ok": True, "reason": ""},
                         voice={"installed": False, "ok": False},
                         backup={"writes": False, "pulls": False})
        for name in ("talker", "voice", "backup"):
            self.assertEqual(rows[name]["level"], "off", name)
            self.assertIsNone(rows[name]["at"], name)
        self.assertEqual(rows["talker"]["state"], "not installed here")


    def test_the_puller_reads_its_last_pull(self):
        rows = self.rows(backup={"writes": False, "pulls": True, "pull_age": 3600})
        self.assertEqual((rows["backup"]["state"], rows["backup"]["at"]), ("last pull", "2026-09-24T09:00:00+00:00"))

    def test_current_carries_the_services_beside_the_verdict(self):
        facts = {"talker": TALKER_OK, "voice": {"installed": False}, "drain": DRAIN_OK,
                 "backup": {"writes": False, "pulls": False}}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(health, "gather", return_value=facts):
            found = health.current(make_config(Path(tmp)))
        self.assertEqual(found["level"], "green")
        self.assertEqual([row["name"] for row in found["services"]], ["talker", "voice", "drain", "backup"])

class GatherTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = make_config(Path(tmp.name))
        self.bh = self.cfg.home / ".keel-backup"
        self.bh.mkdir(parents=True)

    def stamp(self, hours_ago: float) -> str:
        return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_backup_ages_come_from_the_tools_state_file(self):
        self.cfg.backup_sets = ["keel"]
        self.cfg.backup_pull = True
        (self.bh / "state.json").write_text(json.dumps(
            {"last_success": self.stamp(1), "last_pull": self.stamp(30)}))
        facts = health.gather(self.cfg)
        self.assertTrue(facts["backup"]["writes"] and facts["backup"]["pulls"])
        self.assertAlmostEqual(facts["backup"]["success_age"], 3600, delta=60)
        self.assertAlmostEqual(facts["backup"]["pull_age"], 30 * 3600, delta=60)

    def test_nothing_installed_here_is_not_asked(self):
        with mock.patch.object(health.voice, "health") as probe:
            facts = health.gather(self.cfg)
        probe.assert_not_called()
        self.assertEqual(facts["talker"]["state"], "not-installed")
        self.assertFalse(facts["voice"]["installed"])

class StateFieldTest(unittest.TestCase):
    def test_the_state_document_carries_one_health_field(self):
        from keel import serve
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(Path(tmp))
            found = {"level": "amber", "reasons": ["talker: starting"]}
            with mock.patch.object(health, "current", return_value=found):
                doc = serve.with_code_state(cfg, {"cards": []})
        self.assertEqual(doc["health"], found)


if __name__ == "__main__":
    unittest.main()
