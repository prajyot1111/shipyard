"""The Back up step says what is really happening (c-757, `keel/backupstatus.py`).

On 2026-10-12 the first teammate to set the product up turned backup on and read "Done"
above a spinner ("The hourly job is writing it now.") and a grey "First proof on Sunday".
No copy was ever written: every snapshot needs gpg, his Mac had none, and nothing checked.
Each class here is one way that screen was wrong, kept as it was reproduced: on a scratch
install from `shipyard init`, through the page's own verb (`firstrun.backup.on`) and the
step's own state (`firstrunsteps.backup_state`, what `/api/state` carries).

The stand-ins are `tests/test_backupsetup.py`'s: the backup's home is a temp folder
(`KEEL_BACKUP_HOME`), the service manager is a fake that starts no job, and the tool is a
fake that records how it was called. `DiesTest` alone runs the real `bin/keel-backup`, the
way `tests/test_backuplock.py` does: against that temp home, with a program of the test's
own first on PATH at the point it is made to die. The clock is the board's, pinned, and
"when backup was turned on" is the config's `[backup] since`, which the turn-on writes.
"""

import contextlib
import fcntl
import io
import json
import os
import shutil
import signal
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from keel import actions, backup, backupstatus, firstrunsteps, prereqs, readiness
from keel.board import open_board
from tests.helpers import ROOT
from tests.test_backupsetup import Case

ZONE = timezone(timedelta(hours=5, minutes=30))
ON = datetime(2026, 10, 12, 10, 0, tzinfo=ZONE)             # a Monday morning: backup is turned on
STAMP = "%Y-%m-%dT%H:%M:%SZ"


def stamp(at: datetime) -> str:
    """A time as the tool writes it into `state.json`."""
    return at.astimezone(timezone.utc).strftime(STAMP)


class StepCase(Case):
    def turn_on(self, quiet: bool = False):
        """Backup turned on at `ON`. `quiet`: the run the turn-on starts records nothing."""
        if quiet:
            (self.fake / "snapshot-quiet").write_text("")
        (self.fake / "stamp").write_text(stamp(ON))     # when the fake tool says its run succeeded
        return self.on(self.dir / "copies", at=ON)

    def kept(self, at: datetime) -> None:
        """A copy in the store, written at `at`: the tool names a snapshot by its time."""
        sid = at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        where = self.dir / "copies" / "sets" / "keel" / "snapshots" / sid[:4] / sid[4:6]
        where.mkdir(parents=True, exist_ok=True)
        (where / f"{sid}.tar.gz.gpg").write_bytes(b"a name is all this reads\n")

    def state(self, **fields) -> None:
        self.own.mkdir(exist_ok=True)
        (self.own / "state.json").write_text(json.dumps(fields))

    def step(self, now: datetime = ON, again: bool = False) -> tuple:
        """`(done, why, extra)` of the Back up step as the state carries it at `now`.
        `again`: a later look by the same deck, with what it kept from the one before."""
        if not again:
            readiness.forget()      # the store's listing is a kept reading (r1.F12)
        cfg = self.cfg()
        with open_board(cfg) as board:
            board.now = lambda: now.isoformat(timespec="seconds")
            return firstrunsteps.backup_state(cfg, {}, board)

    def shown(self, now: datetime = ON) -> dict:
        return self.step(now)[2]["backup"]

    def copy(self, now: datetime = ON) -> dict:
        return self.shown(now).get("copy") or {}

    def proof(self, now: datetime = ON) -> dict:
        return self.shown(now).get("proof") or {}


class NoGpgTest(StepCase):
    """Backup turned on with no gpg where its jobs look: it was turned on, and every run
    after it died at the encryption."""

    def setUp(self):
        super().setUp()
        (self.dir / "empty").mkdir()
        self.looks_in(self.dir / "empty")
        nowhere = mock.patch.object(prereqs.shutil, "which", return_value=None)
        nowhere.start()
        self.addCleanup(nowhere.stop)

    def test_turn_on_is_refused_and_points_at_the_check(self):
        before = (self.home / "config.toml").read_text()
        with self.assertRaises(actions.ActionError) as caught:
            self.on(self.dir / "copies")
        self.assertEqual(str(caught.exception), "Backup needs gpg, and this computer has none where the backup "
                                                "looks. The Check this computer step has its row, with how to "
                                                "install it.")
        self.assertEqual(caught.exception.detail, {"kind": "gpg", "step": "prerequisites"})
        self.assertEqual((self.home / "config.toml").read_text(), before)
        self.assertEqual((self.ran, self.loaded), ([], []), "nothing was set up and no job was loaded")
        self.assertFalse((self.dir / "copies").exists(), "refused before the folder was made")

    def test_the_step_says_so_before_the_tap(self):
        found = self.shown()
        self.assertEqual((found["on"], found["gpg"]["ok"], found["gpg"]["required"]), (False, False, False))


class FirstCopyTest(StepCase):
    """A first copy that never starts: the turn-on loaded the jobs and left the first run to
    the service manager, and the page said "writing it now" whatever happened."""

    def test_turning_backup_on_starts_the_first_copy_itself(self):
        self.turn_on()
        folder = self.dir / "copies"
        self.assertEqual([line.split()[0] for line in self.ran], ["argv=init", "argv=snapshot"],
                         "the fake manager runs nothing: the copy is the turn-on's own start")
        self.assertIn(f"store=file:{folder} sets=keel", self.ran[1])
        self.assertEqual(self.started, [backup.LABEL])

    def test_the_run_reads_as_written_once_it_has_recorded_its_success(self):
        self.turn_on()
        done, why, extra = self.step()
        self.assertEqual(self.copy()["state"], "written")
        self.assertEqual((done, extra.get("sure"), extra.get("word")), (True, None, None))
        self.assertEqual(why, f"backup is on, and the first copy is written, into {self.dir / 'copies'}")

    def test_a_run_that_holds_the_tools_lock_reads_as_writing_and_the_step_as_pending(self):
        self.turn_on(quiet=True)
        (self.own / ".lock").symlink_to(str(os.getpid()))
        self.assertEqual(self.copy(ON + timedelta(minutes=3))["state"], "writing")
        done, why, extra = self.step(ON + timedelta(minutes=3))
        self.assertEqual((done, extra["sure"], extra["word"]), (True, False, "copy pending"))
        self.assertEqual(why, f"backup is on, into {self.dir / 'copies'}. The first copy is being written "
                              "in the background")
        self.assertIn("You can go on to the next step.", self.copy(ON + timedelta(minutes=3))["said"])

    def test_a_copy_that_never_started_is_not_shown_as_being_written(self):
        """No run, no lock, no success, no error: nothing is writing it, so the page does not
        say so. Soon after the turn-on that is a copy still to come; later it is said."""
        self.turn_on(quiet=True)
        soon = self.copy(ON + timedelta(minutes=3))
        self.assertEqual((soon["state"], soon["late"]), ("none", False))
        done, why, _ = self.step(ON + timedelta(minutes=3))
        self.assertEqual((done, why), (True, f"backup is on, into {self.dir / 'copies'}. The first copy has not started "
                                             "yet: Shipyard starts it by itself, in the background"))
        late = self.copy(ON + timedelta(minutes=25))
        self.assertEqual((late["state"], late["late"]), ("none", True))
        self.assertEqual(late["said"], "No copy has been written since backup was turned on 25 minutes ago, "
                                       "and none is being written now.")
        done, why, _ = self.step(ON + timedelta(minutes=25))
        self.assertEqual((done, why), (False, "backup is on, but no copy has been written and none is being written"))

    def test_a_start_that_cannot_be_made_does_not_undo_the_turn_on(self):
        """r1.F15: and the answer says so, and the step never says a copy is being written."""
        with mock.patch.object(backup, "start", side_effect=OSError(8, "Exec format error")):
            done = self.on(self.dir / "copies", at=ON)
        self.assertEqual(done["folder"], str(self.dir / "copies"))
        self.assertEqual(self.cfg().backup_store, f"file:{self.dir / 'copies'}")
        self.assertIs(done["started"], False)
        self.assertEqual(done["note"], f"backup is on, into {self.dir / 'copies'}")
        at_once = self.copy(ON + timedelta(seconds=10))
        self.assertEqual((at_once["state"], at_once["late"]), ("none", False))
        self.assertNotIn("being written now", at_once["said"])
        later = self.copy(ON + timedelta(minutes=11))
        self.assertEqual((later["state"], later["late"]), ("none", True))

    def test_the_first_minute_says_writing_only_while_a_run_holds_the_lock(self):
        """r1.F1: "writing" was assumed for a minute after the turn-on, with no run at all."""
        self.turn_on(quiet=True)
        soon = self.copy(ON + timedelta(seconds=10))
        self.assertEqual((soon["state"], soon["late"]), ("none", False))
        self.assertEqual(soon["said"], "No copy is being written right now. Shipyard starts one by itself within a "
                                       "few minutes. You can go on to the next step.")
        (self.own / ".lock").symlink_to(str(os.getpid()))
        self.assertEqual(self.copy(ON + timedelta(seconds=10))["state"], "writing")

    def test_a_first_run_that_failed_says_when_the_next_is_started(self):
        """r1.F6: true to the drain (`keel/backupdue.py`): with no success on file it starts
        one after two passes awake, then every ten minutes, three an hour at most."""
        self.turn_on(quiet=True)
        self.state(last_error="could not list the store", last_error_at=stamp(ON + timedelta(seconds=20)))
        copy = self.copy(ON + timedelta(minutes=3))
        self.assertEqual((copy["state"], copy["at"]), ("failed", None))
        self.assertEqual(copy["fix"], "Shipyard starts another within a minute or two while this computer is awake, "
                                      "then again about every ten minutes, up to three an hour. The run's log is "
                                      f"{self.own / 'logs' / 'backup.out'}.")

    def test_a_run_that_failed_after_a_copy_says_the_hourly_run_tries_again(self):
        """r1.F6: with a success under 75 minutes old the drain starts nothing: the hourly
        job is what tries again."""
        self.turn_on()
        self.state(last_success=stamp(ON), last_error="[keel] publish failed", last_error_at=stamp(ON + timedelta(hours=1)))
        copy = self.copy(ON + timedelta(minutes=70))
        self.assertEqual((copy["state"], copy["at"]), ("failed", "2026-10-12T04:30:00+00:00"))
        self.assertEqual(copy["fix"], f"The next hourly run tries again. The run's log is {self.own / 'logs' / 'backup.out'}.")


class VerdictTest(StepCase):
    """r1.F3 and r1.F4, one rule: the step is done once backup is on and a copy of this
    install's has ever been written, and it never goes back. What is wrong after that (the
    folder gone, the last run failed, the proof failed) makes it done and not confirmed,
    with a word of its own; the step is never "Done" over a row that says otherwise."""

    def copied(self, **more) -> None:
        self.turn_on()
        self.state(last_success=stamp(ON), **more)

    def verdict(self, now: datetime = ON + timedelta(hours=2)) -> tuple:
        done, why, extra = self.step(now)
        return done, why, extra.get("sure"), extra.get("word")

    def test_a_copy_and_nothing_wrong_is_done(self):
        self.copied()
        self.assertEqual(self.verdict(), (True, f"backup is on, and the first copy is written, into {self.dir / 'copies'}",
                                          None, None))

    def test_a_run_that_failed_after_a_copy_leaves_the_step_done_and_says_so(self):
        self.copied(last_error="could not list the store. Check the disk.", last_error_at=stamp(ON + timedelta(hours=1)))
        self.assertEqual(self.verdict(), (True, "backup is on and has a copy, but the last run stopped: could not "
                                                "list the store", False, "last run failed"))

    def test_a_folder_that_went_away_is_not_done_over_a_row_that_says_no_copy_is_made(self):
        self.copied()
        shutil.rmtree(self.dir / "copies")
        self.assertEqual(self.verdict(), (True, f"backup is on, but {self.dir / 'copies'} is not there or cannot be "
                                                "written, so no copy is being made", False, "folder missing"))

    def test_a_failed_proof_is_not_done_over_a_row_that_says_it_failed(self):
        failed = ON + timedelta(days=6)
        self.copied(last_verify_error=f"keel unreadable at {stamp(failed)}", last_verify_error_at=stamp(failed))
        self.assertEqual(self.verdict(failed + timedelta(hours=3)),
                         (True, "backup is on and has a copy, but the last restore proof failed", False, "proof failed"))

    def test_the_folder_is_said_before_the_run_and_the_run_before_the_proof(self):
        failed = ON + timedelta(days=6)
        self.copied(last_error="could not list the store", last_error_at=stamp(failed),
                    last_verify_error="keel unreadable", last_verify_error_at=stamp(failed))
        self.assertEqual(self.verdict(failed + timedelta(hours=3))[3], "last run failed")
        shutil.rmtree(self.dir / "copies")
        self.assertEqual(self.verdict(failed + timedelta(hours=3))[3], "folder missing")

    def test_a_missed_proof_stays_on_its_row(self):
        self.copied()
        self.kept(ON)
        monday = datetime(2026, 10, 19, 9, 0, tzinfo=ZONE)
        self.assertEqual(self.proof(monday)["state"], "missed")
        self.assertEqual(self.verdict(monday)[2:], (None, None))

    def test_with_no_copy_yet_a_failed_first_run_is_not_done(self):
        self.turn_on(quiet=True)
        self.state(last_error="could not list the store", last_error_at=stamp(ON + timedelta(seconds=20)))
        self.assertEqual(self.verdict(ON + timedelta(minutes=3)),
                         (False, "backup is on, but the last run wrote no copy: could not list the store", None, None))

    def test_off_is_not_done(self):
        self.assertEqual(self.verdict()[0], False)


class SinceTest(StepCase):
    """r1.F5: the turn-on's time was the hourly job file's time. `keel backup install`
    writes that file again, and from then on this install's own copies read as an earlier
    install's: "No copy has been written since backup was turned on N minutes ago"."""

    def test_the_turn_on_records_its_time_in_the_config(self):
        self.turn_on()
        self.assertEqual(self.cfg().backup_since, "2026-10-12T04:30:00+00:00")
        self.assertEqual(self.shown()["since"], "2026-10-12T04:30:00+00:00")

    def test_writing_the_job_files_again_changes_nothing_on_the_page(self):
        self.turn_on(quiet=True)
        self.state(last_success=stamp(ON + timedelta(seconds=40)), last_verify=stamp(ON + timedelta(days=6)))
        later = ON + timedelta(days=6, hours=6)
        before = self.step(later)
        self.assertEqual(before[2]["backup"]["copy"]["state"], "written")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(backup.install(backup.paths_from(self.cfg())), 0)    # `keel backup install`
        self.assertEqual(self.step(later), before)

    def without_the_key(self) -> None:
        config = self.home / "config.toml"
        config.write_text("".join(line for line in config.read_text().splitlines(keepends=True)
                                  if not line.startswith("since =")))
        self.assertIsNone(self.cfg().backup_since)

    def test_an_install_with_no_key_takes_every_stamp_as_its_own(self):
        """fc2.D7: the page fell back to the job file's time and disowned by it, while the
        drain read the stamps raw: the page promised a copy "within a few minutes" that the
        drain, holding a fresh success, would not start. One rule for both: the key alone."""
        self.turn_on(quiet=True)
        self.without_the_key()
        for path in (self.home / "services").glob("dev.shipyard.backup*"):
            os.utime(path, (ON.timestamp(), ON.timestamp()))
        self.state(last_success=stamp(ON - timedelta(minutes=50)))
        found = self.shown(ON + timedelta(minutes=3))
        self.assertIsNone(found["since"])
        self.assertEqual((found["copy"]["state"], found["copy"]["at"]), ("written", "2026-10-12T03:40:00+00:00"))
        self.assertEqual(self.step(ON + timedelta(minutes=3))[0], True)

    def test_a_turn_on_that_fails_takes_the_key_back_out(self):
        before = (self.home / "config.toml").read_text()
        self.manager.fails = {backup.VERIFY_LABEL}
        with self.assertRaises(actions.ActionError):
            self.on(self.dir / "copies", at=ON)
        self.assertEqual((self.home / "config.toml").read_text(), before)
        self.assertNotIn("since =", before)

    def test_a_since_later_than_now_is_no_since(self):
        """fc.D3: a hand edit, or a clock that was ahead at the turn-on. Believed, it disowned
        every success this install would ever write, for good."""
        self.turn_on(quiet=True)
        config = self.home / "config.toml"
        config.write_text(config.read_text().replace('since = "2026-10-12T04:30:00+00:00"',
                                                     'since = "2031-01-01T00:00:00+00:00"'))
        self.state(last_success=stamp(ON + timedelta(seconds=40)))
        later = ON + timedelta(minutes=3)
        self.assertIsNone(self.shown(later)["since"])
        self.assertEqual(self.copy(later)["state"], "written")

    def test_a_since_that_is_not_a_time_is_no_since(self):
        self.turn_on(quiet=True)
        config = self.home / "config.toml"
        config.write_text(config.read_text().replace('since = "2026-10-12T04:30:00+00:00"', 'since = "last tuesday"'))
        self.assertIsNone(backupstatus.since(self.cfg()), "no refusal, and no other time in its place")
        self.state(last_success=stamp(ON - timedelta(days=9)))
        self.assertEqual(self.copy(ON + timedelta(minutes=3))["state"], "written")


class DiesTest(StepCase):
    """A snapshot that dies before publishing. Only a failed publish left its reason in the
    state file; every other death (a lock that cannot be made, no gpg, a full disk) left
    the page nothing to show. And (r1.F2, r1.F8) what the record must NOT do: say a run
    failed that failed no backup, or write over a success."""

    def env(self, sets: str = "", **more) -> dict:
        env = dict(os.environ, KEEL_HOME=str(ROOT), KEEL_CONFIG=str(self.home / "config.toml"),
                   KEEL_BACKUP_HOME=str(self.own), KEEL_BACKUP_SETS=sets, KEEL_BACKUP_HOST="scratch",
                   KEEL_BACKUP_STORE=f"file:{self.dir / 'copies'}", KEEL_BACKUP_STATE_DIR=str(self.home / "state"),
                   PATH=f"{self.dir / 'shim'}{os.pathsep}{os.environ['PATH']}")
        env.pop("KEEL_CARD", None)
        env.update(more)
        return env

    def shim(self, name: str, text: str) -> None:
        """A program of the test's own, first on the run's PATH."""
        (self.dir / "shim").mkdir(exist_ok=True)
        (self.dir / "shim" / name).write_text(text)
        (self.dir / "shim" / name).chmod(0o755)

    def tool(self, *argv: str, sets: str = "", **more) -> subprocess.CompletedProcess:
        """One run of the REAL tool against the test's own backup home."""
        return subprocess.run(["bash", str(ROOT / "bin" / "keel-backup"), *argv], env=self.env(sets, **more),
                              capture_output=True, text=True, timeout=120)

    def snapshot(self, shim: str, text: str, sets: str = "") -> subprocess.CompletedProcess:
        self.shim(shim, text)
        return self.tool("snapshot", sets=sets)

    def left(self) -> dict:
        """The tool's state file as the run left it."""
        try:
            return json.loads((self.own / "state.json").read_text())
        except FileNotFoundError:
            return {}

    def test_a_run_that_dies_before_publishing_leaves_its_reason_for_the_step(self):
        self.turn_on(quiet=True)
        died = self.snapshot("ln", "#!/bin/sh\necho 'ln: No space left on device' >&2\nexit 1\n")
        self.assertNotEqual(died.returncode, 0, died.stdout + died.stderr)
        copy = self.copy(ON + timedelta(minutes=3))
        self.assertEqual(copy["state"], "failed")
        self.assertIn("could not make the lock", copy["said"])
        done, why, _ = self.step(ON + timedelta(minutes=3))
        self.assertFalse(done)
        self.assertIn("backup is on, but the last run wrote no copy: could not make the lock", why)

    def test_a_run_with_no_gpg_says_gpg_and_not_only_that_encryption_was_refused(self):
        self.turn_on(quiet=True)
        died = self.snapshot("gpg", "#!/bin/sh\nexit 127\n", sets="keel")
        self.assertNotEqual(died.returncode, 0, died.stdout + died.stderr)
        self.assertIn("gpg did not run", self.copy(ON + timedelta(minutes=3)).get("said", ""))

    def test_a_mistyped_run_by_hand_records_no_failed_backup(self):
        """r1.F8 (1): an unknown flag, or a set this host does not write, failed no backup."""
        self.turn_on(quiet=True)
        for argv in (("snapshot", "--nope"), ("snapshot", "--set", "code")):
            with self.subTest(argv=argv):
                died = self.tool(*argv, sets="keel")
                self.assertNotEqual(died.returncode, 0, died.stdout + died.stderr)
                self.assertNotIn("last_error", self.left())
        self.assertEqual(self.copy(ON + timedelta(minutes=3))["state"], "none")

    def test_a_run_that_finds_the_lock_held_is_not_a_failure(self):
        """r1.F14: the turn-on's start against the service manager's, or the drain's: the one
        that loses says so, exits 0 and records nothing."""
        self.turn_on(quiet=True)
        (self.own / ".lock").symlink_to(str(os.getpid()))
        lost = self.tool("snapshot")
        self.assertEqual(lost.returncode, 0, lost.stdout + lost.stderr)
        self.assertIn("another run holds", lost.stdout)
        self.assertEqual(self.left(), {})

    def test_a_run_that_was_stopped_records_no_failure(self):
        """r1.F14: a signal is a job being stopped, not a backup that failed."""
        self.turn_on(quiet=True)
        self.shim("ln", '#!/bin/sh\n/bin/ln "$@"; code=$?\ncase "$*" in *"/.lock") kill -TERM $PPID ;; esac\nexit $code\n')
        stopped = self.tool("snapshot")
        self.assertEqual(stopped.returncode, -signal.SIGTERM, stopped.stdout + stopped.stderr)
        self.assertEqual(self.left(), {})

    @unittest.skipUnless(shutil.which("gpg"), "gpg is not installed")
    def test_a_success_empties_the_reason_and_nothing_after_it_writes_one_back(self):
        """r1.F14: a real run that succeeds empties a recorded `last_error`. r1.F8 (2): and a
        non-zero exit AFTER the success was written does not write "the run stopped" over it.
        The run is made to fail there by an `awk` of the test's own, which the tool's closing
        sums call, and which fails only once the state file holds a success."""
        self.turn_on(quiet=True)
        self.state(last_error="could not list the store", last_error_at=stamp(ON + timedelta(seconds=20)))
        state = self.own / "state.json"
        self.shim("awk", f'#!/bin/sh\nif grep -q last_success "{state}" 2>/dev/null; then touch "{self.dir}/after"; exit 1; fi\n'
                         'exec /usr/bin/awk "$@"\n')
        ran = self.tool("snapshot", sets="keel")
        self.assertTrue((self.dir / "after").exists(), "the run never reached its closing sums: the test proves nothing")
        left = self.left()
        self.assertTrue(left.get("last_success"), ran.stdout + ran.stderr)
        self.assertEqual(left.get("last_error"), "", f"exit {ran.returncode}: {ran.stdout[-400:]}{ran.stderr[-400:]}")

    def test_a_proof_that_dies_anywhere_leaves_its_reason(self):
        """r1.F2: only two paths of the weekly proof stamped a failure, so one that died
        elsewhere (here, settings it could not read) was later shown as "did not run"."""
        self.turn_on()
        self.kept(ON)
        died = self.tool("verify", sets="keel", KEEL_BACKUP_STATE_DIR=str(self.home / "elsewhere"))
        self.assertNotEqual(died.returncode, 0, died.stdout + died.stderr)
        left = self.left()
        self.assertIn("could not read the backup settings", left.get("last_verify_error", ""))
        self.assertTrue(left.get("last_verify_error_at"))
        self.assertEqual(left.get("last_success"), stamp(ON), "the record took a lock and kept the other keys")

    @unittest.skipUnless(shutil.which("gpg"), "gpg is not installed")
    def test_a_proof_that_passed_is_not_written_over_by_what_fails_after_it(self):
        """fc.D2: the record stayed armed after `last_verify` was stamped, so a non-zero exit
        after it (here the closing line, written to a reader that has gone) put "the proof
        stopped" over a proof that passed. The reader is stopped by a `date` of the test's
        own, which the closing line calls, and only once the state file holds the proof."""
        self.turn_on(quiet=True)
        cfg = self.cfg()
        with open_board(cfg) as board:      # the proof reads a card back, so the board has one
            board.create(next(iter(cfg.spaces)), "a card to read back")
        made = self.tool("snapshot", sets="keel")
        self.assertEqual(made.returncode, 0, made.stdout[-400:] + made.stderr[-400:])
        reader = subprocess.Popen(["cat"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
        self.addCleanup(reader.wait)
        self.addCleanup(reader.kill)
        state = self.own / "state.json"
        self.shim("date", f'#!/bin/sh\nif grep -q \'"last_verify"\' "{state}" 2>/dev/null; then\n'
                          f'  kill -9 {reader.pid} 2>/dev/null\n'
                          f'  while :; do case "$(ps -o stat= -p {reader.pid} 2>/dev/null)" in ""|Z*) break ;; esac; done\n'
                          f'  touch "{self.dir}/after"\nfi\nexec /bin/date "$@"\n')
        # SIGPIPE stays ignored, as under a job: the write fails and the tool exits on it
        ran = subprocess.Popen(["bash", str(ROOT / "bin" / "keel-backup"), "verify"], env=self.env("keel"),
                               stdout=reader.stdin, stderr=subprocess.PIPE, text=True, restore_signals=False)
        self.addCleanup(ran.wait)
        self.addCleanup(ran.kill)
        reader.stdin.close()
        said = ran.communicate(timeout=120)[1]
        self.assertTrue((self.dir / "after").exists(), f"the proof never passed: the test proves nothing\n{said[-600:]}")
        self.assertNotEqual(ran.returncode, 0, "nothing failed after the stamp: the test proves nothing")
        left = self.left()
        self.assertTrue(left.get("last_verify"))
        self.assertEqual(left.get("last_verify_error"), "", f"exit {ran.returncode}: {said[-400:]}")

    def test_a_filesystem_that_refuses_the_lock_still_takes_the_record(self):
        """fc.D4: `flock` is refused on some filesystems (a network home). Unguarded, the
        record died there, and with it every run: the state was written unlocked before
        this card, and still is where no lock can be had."""
        self.turn_on(quiet=True)
        stub = self.dir / "stub"
        stub.mkdir()
        (stub / "sitecustomize.py").write_text(
            "import errno, fcntl\n\n\ndef refused(*args):\n"
            "    raise OSError(errno.ENOTSUP, 'Operation not supported')\n\n\nfcntl.flock = refused\n")
        self.shim("ln", "#!/bin/sh\necho 'ln: No space left on device' >&2\nexit 1\n")
        died = self.tool("snapshot", PYTHONPATH=str(stub))
        self.assertNotEqual(died.returncode, 0, died.stdout + died.stderr)
        self.assertIn("could not make the lock", self.left().get("last_error", ""), died.stderr[-600:])

    def test_a_mistyped_proof_by_hand_records_nothing(self):
        self.turn_on(quiet=True)
        died = self.tool("verify", "--nope", sets="keel")
        self.assertNotEqual(died.returncode, 0, died.stdout + died.stderr)
        self.assertEqual(self.left(), {})

    def test_a_record_waits_for_the_one_being_written(self):
        """r1.F8 (3), fc.D5: the state file was read, changed and written with no lock, by runs
        that hold different locks or none (a proof, a death before the lock), and the later
        write lost the other's key. The test is the other writer: it holds the record's lock,
        and a run that has a failure to record must not finish until it is let go. The three
        seconds are what "not finished" is read from: a slow machine can only make a tool
        with no lock pass this, never fail one that has it."""
        self.turn_on(quiet=True)
        self.state(last_verify_error="keel unreadable")
        self.shim("ln", "#!/bin/sh\necho 'ln: No space left on device' >&2\nexit 1\n")
        with open(self.own / "state.json.lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            run = subprocess.Popen(["bash", str(ROOT / "bin" / "keel-backup"), "snapshot"], env=self.env(),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.addCleanup(run.wait)
            self.addCleanup(run.kill)
            with self.assertRaises(subprocess.TimeoutExpired, msg="the record did not wait for the lock"):
                run.wait(timeout=3)
            self.assertEqual(self.left(), {"last_verify_error": "keel unreadable"})
            (self.own / "state.json").write_text(json.dumps({"last_verify_error": "written under the lock"}))
        self.assertNotEqual(run.wait(timeout=120), 0)
        left = self.left()
        self.assertIn("could not make the lock", left.get("last_error", ""))
        self.assertEqual(left["last_verify_error"], "written under the lock", "read after the lock, not before")


class ProofTest(StepCase):
    """The proof row said "First proof on Sunday" until a proof passed, whatever happened:
    a proof that failed was never read (`last_verify_error`), and no date was ever said."""

    def test_before_the_first_proof_it_names_the_real_day(self):
        self.turn_on()
        proof = self.proof()
        self.assertEqual((proof["state"], proof["said"]),
                         ("waiting", "First proof on Sunday 18 October, once there is a copy to prove."))
        self.assertEqual(proof["next"], "2026-10-18T04:30:00+05:30")

    def test_a_proof_that_failed_is_shown_as_failed_with_its_reason(self):
        self.turn_on()
        failed = datetime(2026, 10, 18, 4, 31, tzinfo=ZONE)
        self.state(last_success=stamp(ON), last_verify_error=f"keel unreadable at {stamp(failed)}",
                   last_verify_error_at=stamp(failed))
        proof = self.proof(failed + timedelta(hours=5))
        self.assertEqual((proof["state"], proof["said"]),
                         ("failed", f"The last restore proof failed: keel unreadable at {stamp(failed)}"))
        self.assertIn("It runs again by itself on Sunday 25 October.", proof["fix"])

    def test_a_proof_that_passed_says_when_and_when_the_next_is_due(self):
        self.turn_on()
        proved = datetime(2026, 10, 18, 4, 32, tzinfo=ZONE)
        self.state(last_success=stamp(ON), last_verify=stamp(proved), last_verify_error="")
        proof = self.proof(proved + timedelta(days=1))
        self.assertEqual((proof["state"], proof["said"]), ("proved", "The next one is due Sunday 25 October."))
        self.assertEqual(proof["at"], "2026-10-17T23:02:00+00:00")

    def test_a_proof_that_was_due_and_did_not_run_is_shown_as_missed(self):
        self.turn_on()
        self.kept(ON)
        self.state(last_success=stamp(ON))
        monday = datetime(2026, 10, 19, 9, 0, tzinfo=ZONE)
        proof = self.proof(monday)
        self.assertEqual((proof["state"], proof["said"]),
                         ("missed", "The restore proof due Sunday 18 October did not run."))
        self.assertIn("It runs again by itself on Sunday 25 October.", proof["fix"])
        self.assertEqual(self.proof(datetime(2026, 10, 18, 6, 0, tzinfo=ZONE))["state"], "waiting",
                         "an hour and a half past the time is a laptop still asleep, not a miss")

    def test_a_backup_turned_on_after_the_last_due_date_has_missed_nothing(self):
        """Turned on on a Monday, with its copy written: the proof due the day before was
        due before this backup existed. The row waits, and names the next day."""
        self.turn_on()
        self.kept(ON)
        self.state(last_success=stamp(ON + timedelta(minutes=2)))
        proof = self.proof(ON + timedelta(minutes=4))
        self.assertEqual((proof["state"], proof["said"]), ("waiting", "First proof on Sunday 18 October."))

    def test_a_copy_written_after_a_look_is_seen_by_the_next_one(self):
        """fc.D1: the store's listing is kept for five minutes, and "no copy" was kept with it,
        so the row said "once there is a copy to prove" beside "First copy written". Two
        looks by one deck, with nothing forgotten between them."""
        self.turn_on(quiet=True)
        self.assertEqual(self.proof()["said"], "First proof on Sunday 18 October, once there is a copy to prove.")
        self.kept(ON + timedelta(minutes=2))
        self.state(last_success=stamp(ON + timedelta(minutes=2)))
        found = self.step(ON + timedelta(minutes=4), again=True)[2]["backup"]
        self.assertEqual(found["copy"]["state"], "written")
        self.assertEqual(found["proof"]["said"], "First proof on Sunday 18 October.")

    def test_a_folder_with_no_copy_is_not_listed_on_every_look(self):
        """fc2.D6: a success on file and no copy in the folder (a set that had not changed
        stamps a success and writes nothing; a folder that went away). The fix for D1 read
        the folder again on every look, for as long as that lasted, and undid the keep."""
        self.turn_on(quiet=True)
        self.state(last_success=stamp(ON + timedelta(minutes=2)))
        looks = []

        def listed(folder, began):
            looks.append(folder)
            return None

        with mock.patch.object(backupstatus, "first_kept", listed):
            self.step(ON + timedelta(minutes=4))
            for minutes in (5, 6):
                found = self.step(ON + timedelta(minutes=minutes), again=True)[2]["backup"]
        self.assertLessEqual(len(looks), 2, "three looks, and the folder listed on each")
        self.assertIn("once there is a copy to prove", found["proof"]["said"])

    def test_a_proof_due_before_there_was_a_copy_to_prove_was_not_missed(self):
        """On for a week with no copy (no gpg, say), and its first copy written the Monday
        after: on the Sunday there was nothing to prove, so nothing was missed."""
        self.turn_on()
        monday = datetime(2026, 10, 19, 9, 0, tzinfo=ZONE)
        self.kept(monday - timedelta(hours=1))
        self.state(last_success=stamp(monday - timedelta(hours=1)))
        proof = self.proof(monday)
        self.assertEqual((proof["state"], proof["said"]),
                         ("waiting", "First proof on Sunday 25 October."))

    def test_an_earlier_installs_copies_in_the_folder_are_not_a_copy_to_prove(self):
        """A second install into a folder that holds the first one's copies: those were
        there before this backup was on, and are not what its proof was owed for."""
        self.turn_on()
        self.kept(ON - timedelta(days=20))
        monday = datetime(2026, 10, 19, 9, 0, tzinfo=ZONE)
        self.kept(monday - timedelta(hours=1))
        self.state(last_success=stamp(monday - timedelta(hours=1)))
        self.assertEqual(self.proof(monday)["state"], "waiting")


class SecondInstallTest(StepCase):
    """A second install on an account that already has backup state. The backup's home is
    one per user account, so the new install read the old one's copy and proof as its own:
    "First copy written" and a proven restore, for a folder with nothing in it."""

    def setUp(self):
        super().setUp()
        self.own.mkdir()
        (self.own / "backup.key").write_text("an-older-key")
        earlier = ON - timedelta(days=9)
        self.state(last_success=stamp(earlier), last_verify=stamp(earlier), last_error="",
                   last_verify_error=f"keel unreadable at {stamp(earlier)}")

    def test_an_earlier_installs_copy_is_not_this_ones(self):
        self.turn_on(quiet=True)
        copy = self.copy(ON + timedelta(minutes=3))
        self.assertEqual((copy["state"], copy["at"], self.shown(ON + timedelta(minutes=3))["first"]), ("none", None, None))
        self.assertEqual(self.step(ON + timedelta(minutes=25))[0], False, "and the step is not done on its account")

    def test_an_earlier_installs_proof_and_its_failure_are_not_this_ones(self):
        self.turn_on(quiet=True)
        proof = self.proof(ON + timedelta(minutes=3))
        self.assertEqual((proof["state"], proof["at"]), ("waiting", None))

    def test_an_earlier_installs_failed_run_is_not_this_ones(self):
        earlier = ON - timedelta(days=9)
        self.state(last_error="[keel] publish failed at " + stamp(earlier), last_error_at=stamp(earlier))
        self.turn_on(quiet=True)
        self.assertEqual(self.copy(ON + timedelta(minutes=3))["state"], "none")

    def test_this_installs_own_copy_is_shown(self):
        self.turn_on(quiet=True)
        self.state(last_success=stamp(ON + timedelta(seconds=40)))
        self.assertEqual(self.copy(ON + timedelta(minutes=3))["state"], "written")


class WordsTest(StepCase):
    """`same_disk` from what the test states (r1.F16: it leaned on the real home and the
    temp folder sharing a device), and the readings a folder store cannot give."""

    def devices(self, **by_name):
        """`os.stat` answering a device per folder name; a name not given cannot be read."""
        def stat(path, *args, **more):
            name = os.path.basename(str(path))
            if name not in by_name:
                raise PermissionError(13, "Permission denied", str(path))
            return SimpleNamespace(st_dev=by_name[name])
        return mock.patch.object(backupstatus.os, "stat", stat)

    def test_a_folder_on_the_installs_own_disk_is_said_and_one_on_another_is_not(self):
        cfg, folder = self.cfg(), self.dir / "copies"
        folder.mkdir()
        with self.devices(install=7, copies=7):
            self.assertIs(backupstatus.same_disk(cfg, str(folder)), True)
        with self.devices(install=7, copies=9):
            self.assertIs(backupstatus.same_disk(cfg, str(folder)), False)

    def test_a_folder_that_is_not_there_yet_is_read_from_the_nearest_one_that_is(self):
        cfg = self.cfg()
        (self.dir / "disk").mkdir()
        with self.devices(install=7, disk=9):
            self.assertIs(backupstatus.same_disk(cfg, str(self.dir / "disk" / "not" / "made" / "yet")), False)

    def test_a_disk_that_cannot_be_read_is_not_guessed(self):
        cfg = self.cfg()
        with self.devices(install=7):
            self.assertIsNone(backupstatus.same_disk(cfg, str(self.dir)))
        self.assertIsNone(backupstatus.same_disk(cfg, None))

    def test_the_step_carries_it_before_and_after_the_turn_on(self):
        with mock.patch.object(backupstatus, "same_disk", return_value=True):
            self.assertIs(self.shown()["same_disk"], True)
            self.turn_on()
            self.assertIs(self.shown()["same_disk"], True)

    def test_a_file_in_the_store_that_is_not_a_copy_is_not_read_as_one(self):
        """r1.F14: a name that is not the tool's is passed over, not an error."""
        self.turn_on()
        self.kept(ON)
        (self.dir / "copies" / "sets" / "keel" / "snapshots" / "2026" / "10" / "notes.tar.gz.gpg").write_text("x")
        self.assertEqual(backupstatus.first_kept(str(self.dir / "copies"), None),
                         ON.astimezone(timezone.utc))

    def test_a_store_that_is_not_a_folder_reads_with_no_folder(self):
        """r1.F14: an rclone store: nothing is listed, and a proof is never said to be missed."""
        self.turn_on()
        cfg = self.cfg()
        cfg.backup_store = "rclone:drive:shipyard"
        self.assertIsNone(backupstatus.first_kept(None, None))
        found = backupstatus.status(cfg, datetime(2026, 10, 26, 9, 0, tzinfo=ZONE))
        self.assertEqual((found["folder"], found["writable"], found["same_disk"]), (None, None, None))
        self.assertEqual((found["copy"]["state"], found["proof"]["state"]), ("written", "waiting"))
        self.assertEqual(backupstatus.verdict(found)[:2],
                         (True, "backup is on, and the first copy is written, into rclone:drive:shipyard"))
