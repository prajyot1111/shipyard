"""The hourly snapshot, watched from the drain (c-750, `keel/backupdue.py`).

On 2026-10-11 the hourly job had not been started by launchd for 33 hours. Nothing had
failed: the state file said `last_error ""`, the job's last exit was 0, and the one check
that raises the staleness notice runs inside the job that was not running. `SilentStopTest`
is that morning, kept: the state file as it was, a drain passing, and nothing said.

No test here runs a backup: `subprocess.Popen` is patched in every one, the store is a
directory under the test's own temporary one, and `HOME` is the fence's throwaway. The one
real call into `bin/keel-backup` is its `notice close`, the board verb a success ends with,
against the test's own board (as `tests/test_notices.py` drives it).
"""

import json
import os
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from keel import backup, backupdue, doctor
from tests.helpers import ROOT, write_toml
from tests.test_drain import DrainCase

# The owner's Mac, 2026-10-11: the last run launchd started, and when it was noticed.
LAST = "2026-10-09T19:35:45Z"
SEEN = datetime(2026, 10, 11, 5, 30, tzinfo=timezone.utc)
KEY = "backup-stale"
STAMP = "%Y-%m-%dT%H:%M:%SZ"


class DueCase(DrainCase):
    def setUp(self):
        super().setUp()
        self.cfg.backup_store = f"file:{self.dir / 'store'}"
        self.cfg.backup_sets = ["keel"]
        self.bh = self.cfg.home / ".keel-backup"    # KEEL_BACKUP_HOME is not set: the fence scrubs it
        self.bh.mkdir(parents=True)
        self.at = SEEN
        self.board.now = lambda: self.at.isoformat(timespec="seconds")
        self.no_process = mock.patch.object(backup.subprocess, "Popen")
        self.popen = self.no_process.start()
        self.addCleanup(self.no_process.stop)

    def state(self, last_success=LAST, **more):
        (self.bh / "state.json").write_text(json.dumps({"last_success": last_success, **more}))

    def hours_ago(self, hours: float) -> str:
        stamp = (self.at - timedelta(hours=hours)).strftime(STAMP)
        self.state(stamp)
        return stamp

    def passes(self, minutes: float, every: float = 4) -> None:
        """Drain passes for `minutes` of the board's clock, one every `every` minutes."""
        until = self.at + timedelta(minutes=minutes)
        while self.at < until:
            self.at += timedelta(minutes=every)
            self.once()

    def awake(self) -> None:
        """Two passes half a minute apart: a drain passing on a machine that is awake."""
        self.once()
        self.at += timedelta(seconds=30)
        self.once()

    def runs(self) -> list[list[str]]:
        return [call.args[0] for call in self.popen.call_args_list]

    def notices(self) -> list[dict]:
        return [card for card in self.board.list_cards(stage=None)
                if (card["options"] or {}).get("notice_key") == KEY and card["stage"] != "done"]

    def tool_closes_the_notice(self) -> subprocess.CompletedProcess:
        """The tool's own `notice close backup-stale`, through the real `bin/kb`, on this
        test's board: the function `clear_broken` calls, and not a run."""
        env = dict(os.environ, KEEL_HOME=str(ROOT), KEEL_CONFIG=str(write_toml(self.dir)),
                   KEEL_BACKUP_HOME=str(self.bh), KEEL_BACKUP_STORE=self.cfg.backup_store,
                   KEEL_BACKUP_SETS="")
        env.pop("KEEL_CARD", None)
        self.no_process.stop()      # the one real process of this module, and it is not a backup
        try:
            return subprocess.run(["bash", str(ROOT / "bin" / "keel-backup"), "notice", "close", KEY],
                                  env=env, capture_output=True, text=True, timeout=60)
        finally:
            self.popen = self.no_process.start()


class OwnSuccessTest(DueCase):
    """r1.F6: a second install on an account that already has backup state. The drain read
    the account's `last_success` as this install's, so a recent success of the EARLIER
    install held it at "not due" while the page said a copy would be started within a few
    minutes. The due test now reads whose the success is, as the page does (`[backup]
    since`, `keel/backupstatus.py`)."""

    def test_an_earlier_installs_recent_success_does_not_hold_this_installs_first_copy(self):
        self.cfg.backup_since = (self.at - timedelta(minutes=30)).isoformat(timespec="seconds")
        self.hours_ago(50 / 60)
        self.awake()
        self.assertEqual(len(self.runs()), 1, "the first copy of this install is owed, and started")

    def test_this_installs_own_recent_success_is_not_due(self):
        self.cfg.backup_since = (self.at - timedelta(minutes=30)).isoformat(timespec="seconds")
        self.hours_ago(10 / 60)
        self.awake()
        self.assertEqual(self.runs(), [])

    def test_an_install_with_no_since_reads_the_success_as_it_always_did(self):
        """fc.D3: the drain once took the job file's time where the config had no `since`, so
        an install without the key started runs it never started before (`keel backup
        install` writes that file again). Only the key disowns a success (fc2.D7: on the
        page too, and the job file's time is read by nothing)."""
        fresh = self.hours_ago(50 / 60)
        for label in (backup.LABEL, backup.OLD_LABELS[backup.LABEL]):
            job = self.cfg.home / "services" / f"{label}.plist"
            job.parent.mkdir(exist_ok=True)
            job.write_text("<plist/>")      # written now: later than the success on file
        self.awake()
        said = backupdue.gather(self.cfg)["last"]
        self.assertEqual(self.runs(), [], "a success 50 minutes old, and no `since` to disown it")
        self.assertEqual(said, fresh, "and the doctor reads it as the drain does")

    def test_a_since_later_than_now_is_no_since(self):
        """fc.D3: a hand edit, or a clock that was ahead: believed, no success would ever be
        this install's, and the drain would start three runs an hour for good."""
        self.cfg.backup_since = (self.at + timedelta(days=2)).isoformat(timespec="seconds")
        self.hours_ago(10 / 60)
        self.awake()
        self.assertEqual(self.runs(), [])


class SilentStopTest(DueCase):
    """The reproduction: last success 33 hours old, no error recorded, a drain passing."""

    def test_a_job_launchd_stopped_starting_is_run_by_the_drain_and_said_on_the_board(self):
        self.state(last_error="")
        self.awake()
        self.assertEqual([argv[-2:] for argv in self.runs()],
                         [[str(self.cfg.root / "bin" / "keel-backup"), "snapshot"]],
                         "nothing started the snapshot launchd had stopped starting")
        self.assertIn("backup snapshot started: last success 33h ago", self.log_text())
        self.passes(minutes=125)
        found = self.notices()
        self.assertEqual(len(found), 1, "33 hours without a backup and the board says nothing")
        self.assertIn(LAST, found[0]["brief"])


class StartTest(DueCase):
    """The drain starts an overdue run, under the tool's own lock."""

    def test_the_run_is_the_tools_snapshot_detached_and_logged_where_the_job_logs(self):
        self.state()
        with mock.patch.object(backup.shutil, "which", return_value="/usr/bin/caffeinate"):
            self.awake()
        self.assertEqual(self.runs(), [["/usr/bin/caffeinate", "-i",
                                        str(self.cfg.root / "bin" / "keel-backup"), "snapshot"]])
        kwargs = self.popen.call_args.kwargs
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(kwargs["stdout"].name, str(self.bh / "logs" / "backup.out"))
        self.assertEqual(kwargs["stderr"].name, str(self.bh / "logs" / "backup.err"))
        self.assertEqual(kwargs["env"]["KEEL_BACKUP_STORE"], self.cfg.backup_store)
        self.assertEqual(kwargs["env"]["HOME"], str(self.cfg.home))

    def test_a_run_inside_the_interval_and_its_margin_is_not_overdue(self):
        self.hours_ago(1.2)
        self.awake()
        self.assertEqual(self.runs(), [])
        self.assertNotIn("backup snapshot started", self.log_text())

    def test_a_run_past_the_interval_and_its_margin_is_started(self):
        self.hours_ago(1.3)
        self.awake()
        self.assertEqual(len(self.runs()), 1)

    def test_a_backup_that_is_running_is_left_to_its_own_lock(self):
        self.state()
        (self.bh / ".lock").symlink_to(str(os.getpid()))
        self.awake()
        self.assertEqual(self.runs(), [])

    def test_a_backup_that_never_succeeded_is_started(self):
        self.awake()
        self.assertEqual(len(self.runs()), 1)
        self.assertIn("backup snapshot started: never succeeded", self.log_text())

    def test_a_config_with_no_store_or_no_sets_starts_nothing_and_writes_nothing(self):
        self.state()
        for store, sets in ((None, ["keel"]), (self.cfg.backup_store, [])):
            self.cfg.backup_store, self.cfg.backup_sets = store, sets
            self.once()
            self.passes(minutes=130)
        self.assertEqual(self.runs(), [])
        self.assertEqual(self.notices(), [])
        self.assertEqual(sorted(path.name for path in self.bh.iterdir()), ["state.json"])

    def test_a_start_that_raises_is_logged_and_the_pass_goes_on(self):
        self.state()
        self.popen.side_effect = OSError("no such tool")
        self.once()
        self.at += timedelta(seconds=30)
        summary = self.once()
        self.assertIn("houses", summary)
        self.assertIn("backup snapshot upkeep failed", self.log_text())
        self.passes(minutes=2, every=0.5)
        self.assertEqual(len(self.runs()), 1, "a start that raised is not tried every pass")


class WakeTest(DueCase):
    """A run is started on waking evidence, two passes close together, and one that ended
    with no success is tried again soon, a few times an hour (r1.F2)."""

    def test_the_very_first_pass_starts_nothing_and_the_next_one_does(self):
        self.state()
        self.once()
        self.assertEqual(self.runs(), [], "one pass is not yet a machine awake")
        self.at += timedelta(seconds=30)
        self.once()
        self.assertEqual(len(self.runs()), 1)

    def test_the_first_pass_after_a_long_gap_starts_nothing_and_the_next_one_does(self):
        """The lid opens after a night: the network may not be up for the first pass."""
        self.hours_ago(1.5)
        self.once()
        self.at += timedelta(hours=9)
        self.once()
        self.assertEqual(self.runs(), [])
        self.at += timedelta(seconds=30)
        self.once()
        self.assertEqual(len(self.runs()), 1)

    def test_single_passes_in_short_darkwakes_never_start_a_run(self):
        self.state()
        self.passes(minutes=180, every=15)
        self.assertEqual(self.runs(), [])
        self.assertEqual(self.notices(), [])

    def test_a_run_that_ended_with_no_success_is_tried_again_in_ten_minutes_three_times_an_hour(self):
        """No network on the first try costs ten minutes, not an hour; a run that keeps
        ending with no success is not started on every pass either."""
        self.state()
        self.once()
        for minutes, runs, why in ((4, 1, "the second pass"), (8, 1, "inside ten minutes of it"),
                                   (4, 2, "twelve minutes after"), (44, 3, "three in the hour, then none"),
                                   (4, 4, "the first start is an hour old")):
            self.passes(minutes=minutes)
            self.assertEqual(len(self.runs()), runs, why)

    def test_a_pass_that_fails_at_its_first_step_still_counts_and_still_starts_the_run(self):
        """The drain is the witness that the machine is awake, so the watch comes before
        anything in the pass that can raise (r1.F6)."""
        self.state()
        with mock.patch.object(self.fake, "agents_across", side_effect=RuntimeError("no listing")):
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError, "no listing"):
                    self.once()
                self.at += timedelta(seconds=30)
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual(json.loads((self.bh / backupdue.WATCH).read_text())["awake"], 30)

    def test_a_run_still_holding_the_lock_is_not_tried_again(self):
        self.state()
        self.once()
        self.passes(minutes=4)
        (self.bh / ".lock").symlink_to(str(os.getpid()))
        self.passes(minutes=56)
        self.assertEqual(len(self.runs()), 1)


class NoticeTest(DueCase):
    """One notice once no run has succeeded for three waking hours; the next success
    retires it."""

    def test_three_waking_hours_without_a_success_is_one_notice(self):
        last = self.hours_ago(1 + 1 / 60)
        self.once()
        self.passes(minutes=116)
        self.assertEqual(self.notices(), [], "under three hours since the last success")
        self.passes(minutes=8)
        found = self.notices()
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0]["topic"], found[0]["autonomy"]), ("notice", "attended"))
        self.assertIn(last, found[0]["brief"])
        self.assertIn(str(self.bh / "logs" / "backup.out"), found[0]["brief"])
        self.assertTrue(self.board.get(found[0]["id"])["derived"]["notice"])
        self.assertIn(f"backup overdue: {found[0]['id']}", self.log_text())
        self.passes(minutes=60)
        self.assertEqual(len(self.notices()), 1)

    def test_a_night_asleep_is_not_three_hours_overdue(self):
        """A laptop closed overnight: the drain's passes stop, and nine hours later the
        backup is nine hours older on a machine that was awake for none of them."""
        self.state()
        self.once()
        self.passes(minutes=60)
        self.at += timedelta(hours=9)
        self.once()
        self.passes(minutes=40)
        self.assertEqual(self.notices(), [])
        self.passes(minutes=24)
        self.assertEqual(len(self.notices()), 1, "two waking hours owed, either side of the night")

    def test_a_backup_that_is_running_is_not_said_to_be_missing(self):
        """A first copy or a big upload can run past two waking hours. The count goes on
        under it, and the card waits for it to end (r1.F5)."""
        self.state()
        (self.bh / ".lock").symlink_to(str(os.getpid()))
        self.once()
        self.passes(minutes=130)
        self.assertEqual(self.notices(), [])
        self.assertEqual(self.runs(), [])
        self.assertGreaterEqual(json.loads((self.bh / backupdue.WATCH).read_text())["awake"], 2 * 3600)
        (self.bh / ".lock").unlink()
        self.passes(minutes=4)
        self.assertEqual(len(self.notices()), 1, "it ended with no success, and the time was counted")

    def test_a_notice_the_tool_already_raised_is_the_one_notice(self):
        self.state()
        mine = self.board.create("personal", "Keel backup failed", autonomy="attended",
                                 topic="notice", options={"notice_key": KEY})
        self.once()
        self.passes(minutes=130)
        self.assertEqual([card["id"] for card in self.notices()], [mine])

    def test_a_notice_tapped_away_is_not_raised_again_for_the_same_missing_success(self):
        self.state()
        self.once()
        self.passes(minutes=125)
        self.board.stage(self.notices()[0]["id"], "done", "human")
        self.passes(minutes=60)
        self.assertEqual(self.notices(), [])

    def test_the_tools_close_retires_the_drains_card_and_a_fresh_stamp_begins_the_count_again(self):
        """WHAT THIS PROVES, AND WHAT IT DOES NOT (r1.F8). It proves two halves: the card the
        drain filed is one the tool's `notice close backup-stale` finds and stages done on a
        real board, and a fresh `last_success` makes the drain forget its count. It does NOT
        run a successful snapshot: the stamp is written by hand and the close is called by
        hand. That a whole successful run does both, one after the other, is `cmd_snapshot`'s
        last lines: `SuccessRetiresTest` below holds them on the script's text, and
        `bin/keel-backup-selftest` runs them for real ("a later success retires the failure
        card"), which needs gpg and is not in `make test`."""
        self.state()
        self.once()
        self.passes(minutes=125)
        self.assertEqual(len(self.notices()), 1)
        self.state(self.at.strftime(STAMP), last_error="")
        closed = self.tool_closes_the_notice()
        self.assertEqual(closed.returncode, 0, closed.stdout + closed.stderr)
        self.assertEqual(self.notices(), [])
        self.once()
        self.assertFalse((self.bh / backupdue.WATCH).exists())
        self.passes(minutes=180)
        self.assertEqual(self.notices(), [], "two hours past due, counted from nothing")
        self.passes(minutes=8)
        self.assertEqual(len(self.notices()), 1)


class SuccessRetiresTest(unittest.TestCase):
    """The link the drain's notice leans on, held on the tool's own text: a whole successful
    run stamps `last_success` and at once closes the `backup-stale` notice (r1.F8)."""

    def lines(self) -> list[str]:
        return [line.strip() for line in (ROOT / "bin" / "keel-backup").read_text().splitlines()]

    def test_a_whole_successful_run_stamps_the_success_and_then_clears_the_staleness_notice(self):
        lines = self.lines()
        stamped = [at for at, line in enumerate(lines)
                   if line == 'state_set last_success "$(now_iso)" last_error ""']
        self.assertEqual(len(stamped), 1, "last_success is stamped in exactly one place")
        self.assertEqual(lines[stamped[0] + 1], "clear_broken")

    def test_clearing_it_closes_the_key_the_drain_files_under(self):
        lines = self.lines()
        at = lines.index("clear_broken() {")
        self.assertEqual(lines[at + 1], f"close_notice {backupdue.NOTICE_KEY}")


class DoctorTest(DueCase):
    """The doctor reads what the drain counted, and writes nothing."""

    def report(self) -> dict:
        return {"config": {"path": "x", "ok": True}, "claude": {"ok": True},
                "backup": backupdue.gather(self.cfg)}

    def test_a_backup_overdue_is_a_problem_naming_the_last_success(self):
        self.state()
        self.once()
        self.passes(minutes=125)
        report = self.report()
        self.assertEqual(backupdue.line(report["backup"]),
                         f"backup        last good run {LAST}  OVERDUE")
        found = doctor.problems(report)
        self.assertEqual(len(found), 1, found)
        self.assertTrue(found[0].startswith(
            f"backup: no successful run since {LAST}, and over 2h awake with one owed ("), found[0])
        self.assertIn("keel backup status", found[0])

    def test_the_problem_says_what_was_counted_and_no_more(self):
        """Two waking hours with a run owed is what the count holds; after a night asleep
        it is not three hours awake, and the line does not say so (r1.F10)."""
        said = backupdue.problem({"writes": True, "overdue": True, "last": None, "log": "/x/backup.out"})
        self.assertEqual(said, "backup: no successful run yet, and over 2h awake with one owed "
                               "(keel backup status; the log is /x/backup.out)")

    def test_a_backup_on_time_is_a_line_and_no_problem(self):
        last = self.hours_ago(0.5)
        self.once()
        report = self.report()
        self.assertEqual(backupdue.line(report["backup"]), f"backup        last good run {last}")
        self.assertEqual(doctor.problems(report), [])

    def test_a_late_backup_on_a_machine_just_woken_is_not_yet_a_problem(self):
        self.state()
        before = sorted(path.name for path in self.bh.iterdir())
        report = self.report()
        self.assertEqual(doctor.problems(report), [])
        self.assertEqual(sorted(path.name for path in self.bh.iterdir()), before)

    def test_no_backup_set_up_is_said_and_is_no_problem(self):
        self.cfg.backup_store = None
        report = self.report()
        self.assertEqual(backupdue.line(report["backup"]), "backup        not set up here")
        self.assertEqual(doctor.problems(report), [])


class OrderTest(DueCase):
    """The run comes before the card: a board or a file that fails costs the notice, never
    the backup (r1.F3)."""

    def test_a_board_that_will_not_take_the_card_still_gets_its_backup_started(self):
        self.state()
        with mock.patch.object(self.board, "create", side_effect=RuntimeError("board is locked")):
            self.once()
            self.passes(minutes=130)
        self.assertEqual(len(self.runs()), 7, "three an hour, and the seventh as the third hour begins")
        self.assertIn("backup overdue notice failed: RuntimeError: board is locked", self.log_text())
        self.assertNotIn("backup snapshot upkeep failed", self.log_text())
        self.assertEqual(self.notices(), [])
        self.passes(minutes=4)
        self.assertEqual(len(self.notices()), 1, "said on the first pass the board takes it")

    def test_a_card_filed_and_then_not_recorded_is_still_one_card(self):
        self.state()
        write = backupdue.write

        def refuse_the_mark(paths, watch):
            if watch.get("noticed"):
                raise OSError("disk full")
            write(paths, watch)

        with mock.patch.object(backupdue, "write", side_effect=refuse_the_mark):
            self.once()
            self.passes(minutes=180)
        self.assertEqual(len(self.notices()), 1)
        self.assertEqual(len(self.runs()), 9, "three an hour for three hours")
        self.assertIn("backup overdue notice failed: OSError: disk full", self.log_text())

    def test_a_home_the_watch_cannot_be_written_to_starts_nothing_and_says_so(self):
        """Nothing could bound the starts, and the tool could record no success there."""
        self.state()
        with mock.patch.object(backupdue, "write", side_effect=OSError("read-only")):
            summary = self.once()
        self.assertIn("houses", summary)
        self.assertEqual(self.runs(), [])
        self.assertIn("backup snapshot upkeep failed", self.log_text())

    def test_a_start_that_raises_does_not_cost_the_notice(self):
        self.state()
        self.popen.side_effect = OSError("no such tool")
        self.once()
        self.passes(minutes=125)
        self.assertEqual(len(self.notices()), 1)


class EdgeTest(DueCase):
    """The edges the first round left untested (r1.F7)."""

    def awake_counted(self) -> float:
        return json.loads((self.bh / backupdue.WATCH).read_text())["awake"]

    def test_passes_exactly_five_minutes_apart_are_a_machine_awake(self):
        self.state()
        self.once()
        self.passes(minutes=20, every=5)
        self.assertEqual(self.awake_counted(), 20 * 60)
        self.assertEqual(len(self.runs()), 2, "at five minutes and, ten after it, at fifteen")

    def test_passes_a_second_over_five_minutes_apart_are_a_machine_asleep(self):
        self.state()
        self.once()
        self.passes(minutes=180, every=5 + 1 / 60)
        self.assertEqual(self.awake_counted(), 0)
        self.assertEqual(self.runs(), [])
        self.assertEqual(self.notices(), [])

    def test_a_drain_that_polls_slower_than_five_minutes_is_still_a_machine_awake(self):
        """With `poll_seconds` of 400 every pass is over five minutes after the last, so a
        fixed five minute gap never saw two passes together and never started a run (fix
        check 4). The gap is the larger of five minutes and a poll and a half plus a
        minute: 660 seconds here."""
        self.cfg.poll_seconds = 400
        self.state()
        self.once()
        self.passes(minutes=20, every=400 / 60)
        self.assertEqual(self.awake_counted(), 1200)
        self.assertEqual(len(self.runs()), 2, "on the second pass, and ten minutes after it")
        self.at += timedelta(seconds=660)
        self.once()
        self.assertEqual(self.awake_counted(), 1860, "a poll and a half and a minute apart is still awake")
        self.at += timedelta(seconds=661)
        self.once()
        self.assertEqual(self.awake_counted(), 1860, "a second over is asleep")

    def test_with_that_poll_single_passes_fifteen_minutes_apart_are_still_not_awake(self):
        """Three polls would have been twenty minutes, and a DarkWake's single pass every
        fifteen would have read as a machine awake all night."""
        self.cfg.poll_seconds = 400
        self.state()
        self.passes(minutes=180, every=15)
        self.assertEqual(self.awake_counted(), 0)
        self.assertEqual(self.runs(), [])
        self.assertEqual(self.notices(), [])

    def test_a_state_file_cut_short_reads_as_no_success_one_start_and_then_the_hold(self):
        (self.bh / "state.json").write_text('{"last_success": "2026-10-09T19:3')
        self.awake()
        self.assertEqual(len(self.runs()), 1)
        self.assertIn("backup snapshot started: never succeeded", self.log_text())
        self.passes(minutes=8)
        self.assertEqual(len(self.runs()), 1)
        self.assertNotIn("failed", self.log_text())

    def test_a_state_file_with_a_stamp_that_is_not_one_is_the_same(self):
        for value in ("yesterday", 17, None, ["2026-10-09T19:35:45Z"]):
            with self.subTest(value=value):
                (self.bh / "state.json").write_text(json.dumps({"last_success": value}))
                (self.bh / backupdue.WATCH).unlink(missing_ok=True)
                self.popen.reset_mock()
                self.awake()
                self.assertEqual(len(self.runs()), 1)
                self.assertNotIn("failed", self.log_text())

    def test_a_lock_left_by_a_dead_pid_does_not_hold_the_start(self):
        """The tool decides what a dead run's lock is worth (`tests/test_backuplock.py`);
        the drain only stays out of a live run's way."""
        self.state()
        lock = self.bh / ".lock"
        # 99999999 is past any pid a system gives. 0 is what the tool reads a lock that names
        # no pid as; to `kill` it is this process's own group, which is always there, so it
        # must not read as a live run
        for at, target in enumerate(("99999999", "0", "-1", "not a pid", "state.json"), start=1):
            lock.symlink_to(target)
            self.awake()
            self.assertEqual(len(self.runs()), at, repr(target))
            lock.unlink()
            self.at += timedelta(hours=1)

    def test_the_old_tools_lock_a_directory_with_a_pid_file_is_still_read(self):
        """A run of the tool as it was, across a deploy: live holds the start, dead does not."""
        self.state()
        lock = self.bh / ".lock"
        lock.mkdir()
        (lock / "pid").write_text(f"{os.getpid()}\n")
        self.awake()
        self.assertEqual(self.runs(), [])
        for at, text in enumerate(("99999999\n", "0\n", "-1\n", "not a pid\n", ""), start=1):
            (lock / "pid").write_text(text)
            self.at += timedelta(hours=1)
            self.awake()
            self.assertEqual(len(self.runs()), at, repr(text))


class WatchFileTest(DueCase):
    """The watch file is the drain's own note: whatever it holds, the pass goes on."""

    def watch(self) -> dict:
        return json.loads((self.bh / backupdue.WATCH).read_text())

    def goes_on(self) -> None:
        self.state()
        self.once()
        self.passes(minutes=8)
        self.assertNotIn("failed", self.log_text())
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual(self.watch()["seen"], self.at.timestamp())

    def test_a_watch_file_with_mistyped_fields_is_read_as_if_they_were_not_there(self):
        (self.bh / backupdue.WATCH).write_text(json.dumps(
            {"success": LAST, "seen": "x", "awake": None, "kicked": "soon", "noticed": 7}))
        self.goes_on()
        self.assertEqual(self.watch()["awake"], 8 * 60)
        self.assertEqual(self.notices(), [])

    def test_a_watch_file_of_garbage_is_begun_again(self):
        for text in ("not json {", "[1, 2]", '"a word"', ""):
            with self.subTest(text=text):
                (self.bh / backupdue.WATCH).write_text(text)
                self.popen.reset_mock()
                self.goes_on()
                (self.bh / backupdue.WATCH).unlink()

    def test_numbers_that_are_true_or_false_are_not_numbers(self):
        (self.bh / backupdue.WATCH).write_text(json.dumps(
            {"success": LAST, "seen": True, "awake": True, "kicked": False}))
        self.goes_on()
        self.assertEqual(self.watch()["awake"], 8 * 60)


if __name__ == "__main__":
    unittest.main()
