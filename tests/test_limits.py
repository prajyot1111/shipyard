"""The machine's own drain: the `[keel]` limits, the browser slot, the memory gate, each
house's peak memory, and houses reniced behind voice (`<install>/history/docs/vps-plan.md` "Limits on the box")."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keel import config as config_module
from keel import machine
from keel.board import Refused
from tests.helpers import SESSION, background_row
from tests.test_drain import DrainCase

ROOT = Path(__file__).resolve().parent.parent

TOML = """
[keel]
host = "mac"
houses_max = 3
reviews_max = 2
browsers_max = 1
memory_floor_mb = 2048
house_mb = 700
house_nice = 10

[spaces.personal]
config_dir = "/p"

[spaces.work]
config_dir = "/w"
"""

# What a config from the two-machine days still carries (c-622).
OLD_HOSTS = """
[hosts.box]
spaces = ["personal"]
houses_max = 9
browsers_max = 4
"""


def load(text: str, host: str | None = None):
    env = {"KEEL_HOST": host} if host else {}
    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env):
        path = Path(tmp) / "keel.toml"
        path.write_text(text)
        return config_module.load(path, ensure=False)


class LimitsTest(unittest.TestCase):
    def test_the_limits_are_the_keel_table_s(self):
        cfg = load(TOML)
        self.assertEqual((cfg.host, cfg.houses_max, cfg.reviews_max, cfg.browsers_max),
                         ("mac", 3, 2, 1))
        self.assertEqual((cfg.memory_floor_mb, cfg.house_mb, cfg.house_nice), (2048, 700, 10))
        self.assertEqual(cfg.served_spaces(), ["personal", "work"])

    def test_a_limit_left_out_takes_its_default(self):
        cfg = load('[keel]\nhost = "mac"\n[spaces.personal]\nconfig_dir = "/p"\n')
        self.assertEqual((cfg.browsers_max, cfg.memory_floor_mb, cfg.house_nice), (None, 0, 0))

    def test_an_old_host_table_is_ignored_and_said_and_keel_host_picks_nothing(self):
        """c-622: `[hosts.<name>]` and `KEEL_HOST` chose a machine's table when Keel ran on
        two. One machine serves every space with the `[keel]` limits, and the old table is a
        warning rather than a config that will not load."""
        cfg = load(TOML + OLD_HOSTS, host="box")
        self.assertEqual((cfg.host, cfg.houses_max, cfg.browsers_max), ("mac", 3, 1))
        self.assertEqual(cfg.served_spaces(), ["personal", "work"])
        self.assertIn("[hosts]: Shipyard runs on one machine now (c-622), so it is ignored",
                      cfg.warnings)
        self.assertTrue(any(line.startswith("KEEL_HOST is set") for line in cfg.warnings),
                        "r1.F2: the variable nothing reads is named")
        load(TOML + "\n[hosts.desk]\nhouse_max = 2\n")   # a typo in a dead table is no error

    def test_this_machines_old_host_limits_fill_what_keel_leaves_out(self):
        """c-622 r1.F5: a limit that lived only in `[hosts.<this host>]` is carried, named,
        and `[keel]` wins where it says."""
        cfg = load('[keel]\nhost = "mac"\nhouses_max = 3\n[spaces.personal]\nconfig_dir = "/p"\n'
                   "[hosts.mac]\nhouses_max = 2\nhouse_nice = 10\nbrowsers_max = 1\n")
        self.assertEqual((cfg.houses_max, cfg.house_nice, cfg.browsers_max), (3, 10, 1))
        carried = [line for line in cfg.warnings if "carried as [keel]" in line]
        self.assertEqual(len(carried), 2, cfg.warnings)
        self.assertTrue(any("house_nice = 10" in line for line in carried))


class MachineTest(unittest.TestCase):
    def test_linux_available_memory(self):
        text = "MemTotal:       12000000 kB\nMemFree:  100 kB\nMemAvailable:    2097152 kB\n"
        self.assertEqual(machine.meminfo_available(text), 2048)
        self.assertIsNone(machine.meminfo_available("MemTotal: 1 kB\n"))

    def test_mac_available_memory_is_free_inactive_and_speculative(self):
        text = ("Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
                "Pages free:                               64.\n"
                "Pages active:                           9999.\n"
                "Pages inactive:                          128.\n"
                "Pages speculative:                        64.\n")
        self.assertEqual(machine.vm_stat_available(text), 4)
        self.assertIsNone(machine.vm_stat_available("nothing"))


    def test_the_real_machine_answers(self):
        """One live reading of this machine, so a changed `ps` or `vm_stat` shows up here."""
        self.assertGreater(machine.available_mb() or 0, 0)
        table = machine.process_table()
        self.assertIn(os.getpid(), table)
        self.assertGreater(machine.tree_mb(table, os.getpid()), 0)

    def test_renice_raises_and_never_lowers(self):
        mine = os.getpriority(os.PRIO_PROCESS, 0)
        with mock.patch.object(machine.os, "setpriority") as setting:
            self.assertEqual(machine.renice([os.getpid()], mine + 5), 1)
            setting.assert_called_once_with(os.PRIO_PROCESS, os.getpid(), mine + 5)
            self.assertEqual(machine.renice([os.getpid()], mine), 0)
            self.assertEqual(machine.renice([999999999], 19), 0)


class BrowserSlotTest(DrainCase):
    def test_one_browser_at_a_time_and_the_card_behind_it_still_starts(self):
        self.cfg.browsers_max = 1
        running = self.housed(options={"browser": True})
        self.fake.rows = [background_row(running, SESSION)]
        waiting = self.assigned("wants a browser", options={"browser": True})
        plain = self.assigned("no browser")
        summary = self.once()
        self.assertEqual([s["name"] for s in self.fake.starts], [plain])
        self.assertEqual(self.board.get(waiting)["stage"], "assigned")
        self.assertEqual(summary["browsers"], 1)
        self.assertIn(f"browser slot full at 1; {waiting} waits", self.log_text())

    def test_two_browser_cards_in_one_pass_start_one(self):
        self.cfg.browsers_max = 1
        first = self.assigned("first", options={"browser": "true"})
        self.assigned("second", options={"browser": True})
        summary = self.once()
        self.assertEqual([s["name"] for s in self.fake.starts], [first])
        self.assertIn("browsers=1", " ".join(f"{k}={v}" for k, v in summary.items()))


class MemoryGateTest(DrainCase):
    def setUp(self):
        super().setUp()
        self.cfg.memory_floor_mb, self.cfg.house_mb = 2048, 700

    def test_under_the_floor_nothing_starts(self):
        self.machine.memory = 1900
        card = self.assigned()
        summary = self.once()
        self.assertEqual((self.fake.starts, summary["memory"]), ([], "1900MB"))
        self.assertEqual(self.board.get(card)["stage"], "assigned")
        self.assertIn("memory gate: 1900 MB available, under 2048; starting nothing", self.log_text())

    def test_each_start_takes_a_house_off_the_reading(self):
        self.machine.memory = 2600
        first, second = self.assigned("first"), self.assigned("second")
        summary = self.once()
        self.assertEqual([s["name"] for s in self.fake.starts], [first])
        self.assertEqual(self.board.get(second)["stage"], "assigned")
        self.assertEqual(summary["memory"], "1900MB")

    def test_unreadable_memory_with_a_floor_starts_nothing(self):
        self.machine.memory = None
        self.assigned()
        self.assertEqual((self.once()["started"], self.fake.starts), (0, []))
        self.assertIn("available memory unreadable", self.log_text())

    def test_a_named_card_is_refused_too(self):
        self.machine.memory = 100
        card = self.assigned()
        with self.assertRaises(Refused):
            self.once(card=card)

    def test_a_resume_waits_for_memory_and_a_block_does_not(self):
        exited = self.housed()
        self.machine.memory = 1000
        summary = self.once()
        self.assertEqual((summary["resumed"], self.fake.resumes), (0, []))
        self.assertIsNone(self.board.get(exited)["blocked_reason"])
        self.machine.memory = 4000
        self.assertEqual(self.once()["resumed"], 1)
        self.machine.memory = 1000
        self.assertEqual(self.once()["blocked"], 1)


class TendTest(DrainCase):
    """Peak memory on the card, and the house's tree reniced behind voice."""

    def live(self, pid=500) -> str:
        card = self.housed()
        self.fake.rows = [dict(background_row(card, SESSION), pid=pid)]
        return card

    def test_peak_is_recorded_and_only_rewritten_when_it_grows(self):
        card = self.live()
        self.machine.table = {500: (1, 400 * 1024), 501: (500, 100 * 1024), 900: (1, 9 * 1024 * 1024)}
        self.once()
        self.assertEqual(self.board.get(card)["options"]["peak_mb"], 500)
        sets = lambda: [e for e in self.board.events(card) if e["kind"] == "set"]
        self.machine.table[501] = (500, 120 * 1024)
        self.once()
        self.assertEqual((self.board.get(card)["options"]["peak_mb"], len(sets())), (500, 1))
        self.machine.table[501] = (500, 300 * 1024)
        self.once()
        self.assertEqual((self.board.get(card)["options"]["peak_mb"], len(sets())), (700, 2))
        self.machine.table[501] = (500, 1024)
        self.once()
        self.assertEqual(self.board.get(card)["options"]["peak_mb"], 700)

    def test_the_tree_is_reniced_only_when_the_host_asks(self):
        self.live()
        self.machine.table = {500: (1, 1024), 501: (500, 1024)}
        self.once()
        self.assertEqual(self.machine.reniced, [])
        self.cfg.house_nice = 10
        self.once()
        self.assertEqual([(sorted(p), n) for p, n in self.machine.reniced], [([500, 501], 10)])

    def test_a_failing_read_never_fails_the_pass(self):
        self.live()
        self.machine.process_table = lambda: 1 / 0
        card = self.assigned()
        self.assertEqual(self.once()["started"], 1)
        self.assertEqual(self.board.get(card)["stage"], "building")
        self.assertIn("tending houses failed", self.log_text())


if __name__ == "__main__":
    unittest.main()
