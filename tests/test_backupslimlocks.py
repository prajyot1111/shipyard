"""`keel backup slim`, the locks (c-724): one slim at a time, the backup's own lock around
a replace, the hourly job in between, the record of a killed run's unpacked work, the
tests' seam, and the reads that take no lock (verify, pull).

Runs the real `bin/keel-backup` on a scratch store (`tests/backupslimcase.py`).
"""

import hashlib
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.backupslimcase import (
    EARLY, KEPT, KEPT_DIRS, LATE, MidReplace, NEW, OLD, RCLONE, SlimCase, TOOL)


class LockTest(SlimCase):
    def hold(self, name=".lock", pid=None) -> Path:
        """One of the tool's locks, held as the tool holds one: a link whose target is the
        holder's pid (c-750)."""
        lock = self.home / name
        os.symlink(str(pid or os.getpid()), lock)
        return lock

    def dead_pid(self) -> int:
        gone = subprocess.Popen(["true"])
        gone.wait()
        return gone.pid

    def test_a_second_slim_stands_down_while_one_runs(self):
        self.old_store(OLD)
        before = self.objects()
        self.hold(".slim-lock")
        done = self.rewrite()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("another run holds", done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)
        self.assertEqual(os.readlink(self.home / ".slim-lock"), str(os.getpid()), "the running one's lock is left")

    def test_stale_locks_are_broken_by_the_tools_one_lock_and_nothing_is_left(self):
        """r1.F16, then c-750: the slim has no lock rule of its own. Both of its locks are
        taken through lock_take, which is where a stale one is renamed away and broken."""
        self.old_store(OLD)
        for name in (".lock", ".slim-lock"):
            os.utime(self.hold(name, self.dead_pid()), (1, 1), follow_symlinks=False)
        self.slim()
        self.assert_slim(OLD)
        self.assertEqual(sorted(p.name for p in self.home.iterdir() if "lock" in p.name), [])

    def test_a_dead_slims_young_lock_is_left_as_the_backups_own_would_be(self):
        """The shared rule: a lock whose owner is gone is broken only once it is older than
        any real run. Until then a slim says so and writes nothing."""
        self.old_store(OLD)
        before = self.objects()
        self.hold(".slim-lock", self.dead_pid())
        done = self.rewrite()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("dead pid", done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)

    def test_a_run_that_cannot_have_the_backups_lock_writes_nothing(self):
        self.old_store(OLD)
        before = self.objects()
        self.hold()
        done = self.rewrite()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("lock", done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)

    def test_a_snapshot_pruned_while_the_lock_was_waited_for_is_not_put_back(self):
        self.old_store(OLD)
        lock = self.hold()
        self.dry()
        run = subprocess.Popen(["bash", str(TOOL), "slim", "--set", "keel", "--approved"], text=True,
                               env=self.env(KEEL_BACKUP_SLIM_LOCK_WAIT="120"),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        said = []
        for line in run.stdout:                 # until the run says it is waiting, not a sleep
            said.append(line)
            if "waiting for the backup's lock" in line:
                break
        self.blob(OLD).unlink()                 # the hourly job's retention, under its lock
        lock.unlink()
        said.append(run.stdout.read())
        self.assertEqual(run.wait(timeout=120), 0, "".join(said))
        run.stdout.close()
        self.assertFalse(self.blob(OLD).exists(), "".join(said))
        self.assertIn("left as the store has it", "".join(said))


class SweepTest(SlimCase):
    """r1.F8, r2.F5: what the next slim does with the record of a dead run's unpacked work
    (.slim-lock.work: its pid, the temp root it ran under, its directory). A record goes
    only when its directory is gone."""

    def dead_pid(self) -> int:
        dead = subprocess.Popen(["true"])
        dead.wait()
        return dead.pid

    def recorded(self, pid: int, root: Path, where: Path) -> Path:
        """A stale slim lock and the record beside it, as a killed run leaves them."""
        os.symlink(str(pid), self.home / ".slim-lock")
        os.utime(self.home / ".slim-lock", (1, 1), follow_symlinks=False)
        record = self.home / ".slim-lock.work"
        record.write_text(f"{pid}\t{root}\t{where}\n")
        return record

    def swept(self, record: Path, pid: int) -> str:
        self.old_store(OLD)
        done = self.tool("slim", "--set", "keel", "--dry-run")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return done.stdout + done.stderr

    def test_a_directory_outside_the_temp_root_its_record_names_is_left_and_stays_recorded(self):
        pid = self.dead_pid()
        mine = self.root / "elsewhere" / "keel-backup.abcdef"
        (mine / "keep").mkdir(parents=True)
        record = self.recorded(pid, self.scratch, mine)
        said = self.swept(record, pid)
        self.assertTrue((mine / "keep").exists())
        self.assertIn(str(mine), record.read_text(), "somebody can still find it")
        self.assertIn(f"left {mine}", said)

    def test_a_directory_not_named_as_the_tool_names_its_own_is_left_and_stays_recorded(self):
        pid = self.dead_pid()
        mine = self.scratch / "not-the-tools"
        (mine / "keep").mkdir(parents=True)
        record = self.recorded(pid, self.scratch, mine)
        self.swept(record, pid)
        self.assertTrue((mine / "keep").exists())
        self.assertIn(str(mine), record.read_text())

    def test_a_link_is_never_followed_and_stays_recorded(self):
        pid = self.dead_pid()
        target = self.root / "somebodys"
        (target / "keep").mkdir(parents=True)
        link = self.scratch / "keel-backup.abcdef"
        link.symlink_to(target)
        record = self.recorded(pid, self.scratch, link)
        self.swept(record, pid)
        self.assertTrue((target / "keep").exists())
        self.assertTrue(link.is_symlink())
        self.assertIn(str(link), record.read_text())

    def test_the_work_of_a_pid_that_is_running_is_left_and_stays_recorded(self):
        """A stale lock is broken by its age; the record's pid may still be some live
        process (a pid handed out again), and its directory is then not this run's to judge."""
        mine = self.scratch / "keel-backup.abcdef"
        (mine / "keep").mkdir(parents=True)
        record = self.home / ".slim-lock.work"
        record.write_text(f"{os.getpid()}\t{self.scratch}\t{mine}\n")
        self.swept(record, os.getpid())
        self.assertTrue((mine / "keep").exists())
        self.assertIn(str(mine), record.read_text())

    def test_work_left_under_another_temp_root_is_removed_by_a_run_with_a_different_one(self):
        """The record carries the temp root the dead run used: launchd and a terminal do
        not share one, and the next run compares against the record's, not its own."""
        self.old_store(OLD)
        self.killed_at("journaled")
        left = list(self.scratch.glob("keel-backup.*"))
        self.assertEqual(len(left), 1)
        other = self.root / "another-tmp"
        other.mkdir()
        done = self.tool("slim", "--set", "keel", "--approved", TMPDIR=str(other))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(list(self.scratch.glob("keel-backup.*")), [])
        self.assertFalse((self.home / ".slim-lock.work").exists(), "nothing is left to record")

    def test_a_slim_that_ends_before_its_record_is_written_does_not_leave_its_lock(self):
        """r3.F6: the lock is this run's from the moment it is taken, whatever became of the
        record beside it. Left behind, it names a dead pid and refuses the next slim for
        half an hour. Here the record cannot be written at all."""
        self.old_store(OLD)
        (self.home / ".slim-lock.work").mkdir()
        done = self.tool("slim", "--set", "keel", "--dry-run")
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse(os.path.lexists(self.home / ".slim-lock"), "the lock went with the run")
        (self.home / ".slim-lock.work").rmdir()
        self.dry()

    def test_a_dead_run_that_had_this_runs_pid_does_not_cost_this_run_its_own_record(self):
        """r3.F6: this run's line is written before the sweep, so the sweep tells it from a
        dead run's line under the same pid by the directory each names."""
        self.old_store(OLD)
        gone = self.scratch / "keel-backup.abcdef"
        (gone / "left").mkdir(parents=True)
        script = (f'printf \'%s\\t%s\\t%s\\n\' $$ "{self.scratch}" "{gone}" > "{self.home}/.slim-lock.work"; '
                  f'exec bash "{TOOL}" slim --set keel --dry-run')
        done = subprocess.run(["bash", "-c", script], env=self.env(), capture_output=True, text=True, timeout=300)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse(gone.exists(), "the dead run's work is removed")
        self.assertFalse((self.home / ".slim-lock.work").exists(), "and this run took its own line out")
        self.assertEqual(list(self.scratch.glob("keel-backup.*")), [])

    def test_a_record_whose_directory_is_already_gone_is_dropped(self):
        pid = self.dead_pid()
        record = self.recorded(pid, self.scratch, self.scratch / "keel-backup.abcdef")
        self.swept(record, pid)
        self.assertFalse(record.exists())

    def test_a_run_that_is_not_a_slim_leaves_a_slim_lock_that_names_its_pid(self):
        """A dead slim's stale lock names a pid the system can hand to an hourly run. That
        run is not a slim, and the lock and the record are not its own to release."""
        gone = self.scratch / "keel-backup.abcdef"
        script = (f'ln -s $$ "{self.home}/.slim-lock"; '
                  f'printf \'%s\\t%s\\t%s\\n\' $$ "{self.scratch}" "{gone}" > "{self.home}/.slim-lock.work"; '
                  f'exec bash "{TOOL}" status')
        done = subprocess.run(["bash", "-c", script], env=self.env(), capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(os.path.lexists(self.home / ".slim-lock"), "the slim lock is still there")
        self.assertIn(str(gone), (self.home / ".slim-lock.work").read_text())


class HourlyBetweenTest(SlimCase):
    """r1.F1: the backup's lock is held only around the replace, so the hourly job can run
    while a snapshot is being read and proven. What it does then must not be undone."""

    def held(self, during, step="prepared") -> str:
        """A rewrite held at `step` (the tool's test seam) while `during` runs, then let go."""
        self.dry()
        run = subprocess.Popen(["bash", str(TOOL), "slim", "--set", "keel", "--approved"], text=True,
                               env=self.env(KEEL_BACKUP_SLIM_TEST="1", KEEL_BACKUP_SLIM_HOLD_AT=step),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        said = []
        for line in run.stdout:                 # until the run says it is holding, not a sleep
            said.append(line)
            if f"holding at {step}" in line:
                break
        during()
        (self.home / ".slim-go").touch()
        said.append(run.stdout.read())
        run.wait(timeout=120)
        run.stdout.close()
        return "".join(said)

    def hourly(self) -> None:
        took = self.tool("snapshot")
        self.assertEqual(took.returncode, 0, took.stdout + took.stderr)
        self.took = took.stdout

    def pending(self, sid: str) -> None:
        """What a publish that could not be proven leaves: the blob and its proof, waiting."""
        where = self.home / "work" / "keel" / "pending"
        where.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.blob(sid), where / f"{sid}.tar.gz.gpg")
        (where / f"{sid}.json").write_text(json.dumps({"snapshot": sid, "set": "keel"}))

    def test_a_snapshot_the_hourly_run_pruned_meanwhile_is_not_put_back(self):
        early, late = EARLY, LATE               # one day, ten days back: retention keeps the later
        self.old_tree(self.live)
        self.old_store(early, late)
        said = self.held(self.hourly)
        self.assertIn("1 pruned", self.took)
        self.assertFalse(self.blob(early).exists(), said)
        self.assertIn("left as the store has it", said)
        self.assert_slim(late)
        self.assertEqual(sorted(self.kept_old()), [late], "nothing of the pruned one was written")

    def test_a_snapshot_the_hourly_run_left_alone_is_rewritten_and_its_new_one_untouched(self):
        self.old_tree(self.live)
        self.old_store()
        self.held(self.hourly)
        new = sorted(set(self.snapshots()) - {str(self.blob(s).relative_to(self.store)) for s in (OLD, NEW)})
        self.assertEqual(len(new), 1, "the hourly run published its own snapshot")
        for sid in (OLD, NEW):
            self.assert_slim(sid)
        self.assertIn("unchanged since", self.tool("snapshot").stdout)

    def test_an_hourly_run_started_while_the_replace_holds_the_lock_stands_down(self):
        """r2.F9: inside step 3 the backup's own lock is held. An hourly run that starts
        then publishes nothing and fails nothing; the next one is an ordinary run."""
        self.old_tree(self.live)
        self.old_store()

        def during():
            took = self.tool("snapshot")
            self.during = (took.returncode, len(self.snapshots()), took.stdout + took.stderr)

        self.held(during, step="uploaded")
        self.assertEqual(self.during[:2], (0, 2), self.during[2])
        for sid in (OLD, NEW):
            self.assert_slim(sid)
        later = self.tool("snapshot")
        self.assertEqual((later.returncode, len(self.snapshots())), (0, 3), later.stdout + later.stderr)

    def test_a_snapshot_with_a_publish_pending_is_not_read_this_run(self):
        self.old_store()
        self.pending(OLD)
        self.dry()
        done = self.tool("slim", "--set", "keel", "--approved")
        self.assertIn("a publish of it is pending", done.stdout + done.stderr)
        self.assert_old(OLD)
        self.assert_slim(NEW)

    def test_a_publish_that_becomes_pending_while_it_is_read_is_seen_under_the_lock(self):
        self.old_store(OLD)
        said = self.held(lambda: self.pending(OLD))
        self.assertIn("a publish of it is pending", said)
        self.assert_old(OLD)
        self.assertEqual(self.kept_old(), {})


class SeamTest(SlimCase):
    def test_the_kill_seam_needs_its_second_word(self):
        """r1.F12: a stray KEEL_BACKUP_SLIM_DIE_AT in someone's environment kills nothing."""
        self.old_store(OLD)
        done = self.rewrite(KEEL_BACKUP_SLIM_DIE_AT="journaled")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assert_slim(OLD)


    def test_the_hold_seam_needs_its_second_word(self):
        """r2.F9: a stray KEEL_BACKUP_SLIM_HOLD_AT holds nothing: the run goes through."""
        self.old_store(OLD)
        done = self.rewrite(KEEL_BACKUP_SLIM_HOLD_AT="journaled")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn("holding at", done.stdout + done.stderr)
        self.assert_slim(OLD)


@unittest.skipUnless(RCLONE, "rclone is not installed")
class SeamOffAFolderTest(SlimCase):
    STORE_KIND = "rclone"

    def test_the_kill_seam_is_dead_on_any_store_but_a_folder(self):
        self.old_store(OLD)
        done = self.rewrite(KEEL_BACKUP_SLIM_TEST="1",
                         KEEL_BACKUP_SLIM_DIE_AT="journaled")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assert_slim(OLD)


@unittest.skipUnless(RCLONE, "rclone is not installed")
class ReadDuringAReplaceTest(MidReplace, SlimCase):
    """r1.F13: the weekly verify and the nightly pull take no backup lock, so one can list a
    snapshot, and fetch it a moment after a slim has put a new archive over its name. That
    is not an unreadable backup: each lists once more and fetches again before it fails."""
    STORE_KIND = "rclone"

    def replaced_at_first_fetch(self) -> tuple[str, str]:
        """A PATH whose rclone puts another whole archive over the snapshot's name just
        before the first fetch of it, as a slim's replace would; and that archive's md5."""
        slim_tree = self.root / "slim-tree"
        self.write_tree(slim_tree, KEPT, KEPT_DIRS)
        shutil.copy(self.board, slim_tree / "state" / "board.db")
        self.publish(OLD, slim_tree)
        other = self.root / "other.gpg"
        self.blob(OLD).rename(other)
        self.old_store(OLD)
        bin_dir = self.root / "swap-bin"
        bin_dir.mkdir()
        stub = bin_dir / "rclone"
        stub.write_text(f'#!/bin/bash\nif [ ! -e "{bin_dir}/done" ]; then case "$*" in *copyto*{OLD}.tar.gz.gpg*) '
                        f'touch "{bin_dir}/done"; cp "{other}" "{self.blob(OLD)}" ;; esac; fi\n'
                        f'exec "{RCLONE}" "$@"\n')
        stub.chmod(0o755)
        return f"{bin_dir}{os.pathsep}{os.environ['PATH']}", hashlib.md5(other.read_bytes()).hexdigest()

    def test_the_verify_fetches_once_more_instead_of_calling_the_set_unreadable(self):
        path, _md5 = self.replaced_at_first_fetch()
        done = self.tool("verify", "--set", "keel", PATH=path)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("verify ok", done.stdout)

    def test_the_pull_fetches_once_more_and_holds_what_the_store_holds_now(self):
        path, md5 = self.replaced_at_first_fetch()
        done = self.tool("pull", PATH=path, KEEL_BACKUP_PULL="1")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        mirrored = self.home / "mirror" / self.blob(OLD).relative_to(self.store)
        self.assertEqual(hashlib.md5(mirrored.read_bytes()).hexdigest(), md5)


@unittest.skipUnless(RCLONE, "rclone is not installed")
class StillCorruptTest(SlimCase):
    """r2.F9: the other leg of r1.F13. A fetch that does not match is tried once more
    against a fresh listing, and a snapshot that still does not match fails as it always did."""
    STORE_KIND = "rclone"
    JUNK = b"not what the store holds"

    def corrupting(self, replaced: bool) -> str:
        """A PATH whose rclone hands back other bytes for every fetch of the snapshot. With
        `replaced`, the store's own object also changes just before the first fetch, as a
        slim's replace would change it, so the second fetch is really made."""
        other = self.root / "other.gpg"
        slim_tree = self.root / "slim-tree"
        self.write_tree(slim_tree, KEPT, KEPT_DIRS)
        shutil.copy(self.board, slim_tree / "state" / "board.db")
        self.publish(OLD, slim_tree)
        self.blob(OLD).rename(other)
        self.old_store(OLD)
        bin_dir = self.root / "bad-bin"
        bin_dir.mkdir()
        stub = bin_dir / "rclone"
        swap = (f'if [ ! -e "{bin_dir}/done" ]; then case "$*" in *copyto*{OLD}.tar.gz.gpg*) '
                f'touch "{bin_dir}/done"; cp "{other}" "{self.blob(OLD)}" ;; esac; fi\n') if replaced else ""
        stub.write_text(f'''#!/bin/bash
{swap}"{RCLONE}" "$@"; rc=$?
case "$*" in *copyto*{OLD}.tar.gz.gpg*)
  dest="${{@: -1}}"
  if [ -f "$dest" ] && [ "$dest" != "{self.blob(OLD)}" ]; then printf '%s' '{self.JUNK.decode()}' > "$dest"; fi ;;
esac
exit $rc
''')
        stub.chmod(0o755)
        return f"{bin_dir}{os.pathsep}{os.environ['PATH']}"

    def test_the_verify_still_fails_when_no_fetch_matches_what_the_store_lists(self):
        for replaced in (False, True):
            with self.subTest(replaced=replaced):
                shutil.rmtree(self.root / "bad-bin", ignore_errors=True)
                done = self.tool("verify", "--set", "keel", PATH=self.corrupting(replaced))
                self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
                self.assertNotIn("verify ok", done.stdout)

    def test_the_pull_still_fails_and_mirrors_nothing_it_could_not_prove(self):
        for replaced in (False, True):
            with self.subTest(replaced=replaced):
                shutil.rmtree(self.root / "bad-bin", ignore_errors=True)
                done = self.tool("pull", PATH=self.corrupting(replaced), KEEL_BACKUP_PULL="1")
                self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
                held = [path for path in (self.home / "mirror").rglob("*") if path.is_file()
                        and path.read_bytes() == self.JUNK]
                self.assertEqual(held, [])


if __name__ == "__main__":
    unittest.main()
