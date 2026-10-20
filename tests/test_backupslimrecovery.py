"""`keel backup slim`, recovery (c-724): what a run that stopped anywhere leaves in the
store, and what the next run does with it.

Runs the real `bin/keel-backup slim` on a scratch store (`tests/backupslimcase.py`), killed
at a step through the tool's test seam or with a store whose writes fail; the journal is
`keel/backupslimjournal.py`.
"""

import json
import os
import shutil
import subprocess
import unittest

from tests.backupslimcase import (
    EARLY, LATE, MidReplace, NEW, OLD, RCLONE, SlimCase, TOOL)


class ResumeTest(SlimCase):
    def test_limit_does_one_and_the_next_run_does_only_the_rest(self):
        self.old_store()
        first = self.slim("--limit", "1")["sets"]["keel"]
        self.assertEqual([s["id"] for s in first["run"]], [OLD])
        self.assertEqual(first["left"], 1)
        self.assert_slim(OLD)
        self.assert_old(NEW)
        held = self.objects()[str(self.blob(OLD).relative_to(self.store))]
        second = self.slim()["sets"]["keel"]
        self.assertEqual([s["id"] for s in second["run"]], [NEW])
        self.assertEqual(second["slim_before"], 1)
        self.assertEqual(self.objects()[str(self.blob(OLD).relative_to(self.store))], held,
                         "a snapshot already slim is not fetched or written again")
        self.assertEqual(self.slim()["sets"]["keel"]["run"], [])

    def test_a_run_killed_at_any_step_leaves_every_snapshot_whole_and_the_next_finishes(self):
        for step in ("uploaded", "journaled", "replaced"):
            with self.subTest(step=step):
                self.reset()
                self.old_store()
                self.killed_at(step)
                files, _dirs = self.unpack(OLD)             # whole: it decrypts and unpacks
                self.assertEqual("state/logs/keel.out.log" in files, step != "replaced",
                                 "old until the replace, new from it")
                self.assert_old(NEW)
                self.again()
                for sid in (OLD, NEW):
                    self.assert_slim(sid)
                self.assertEqual([k for k in self.objects() if k.startswith("slim-tmp/")], [])
                journal = json.loads((self.store / "sets" / "keel" / "slim.json").read_text())
                self.assertEqual((sorted(journal["done"]), journal.get("replacing")), ([OLD, NEW], None))


    def test_a_killed_runs_unpacked_snapshot_is_removed_by_the_next_run(self):
        """r1.F8: a kill skips the trap, and what it leaves under the temp root is a whole
        decrypted snapshot. The slim lock names the directory, so the next run removes it."""
        self.old_store(OLD)
        self.killed_at("journaled")
        left = list(self.scratch.glob("keel-backup.*"))
        self.assertEqual(len(left), 1)
        self.assertTrue(list(left[0].rglob("board.db")), "the killed run left its unpacked tree")
        self.again()
        self.assertEqual(list(self.scratch.glob("keel-backup.*")), [])

    def test_a_run_killed_once_the_old_archive_is_kept_is_done_again_from_there(self):
        """r3.F4: the first step inside the lock. The kept copy is in the store, nothing
        else of the replace is, and the journal names no replace: the next run rewrites the
        snapshot, finding its old archive already kept and proven."""
        self.old_store(OLD)
        was = self.snapshots()
        self.killed_at("kept")
        self.assertEqual((self.snapshots(), list(self.kept_old().values())), (was, list(was.values())))
        self.assertIsNone(self.journal()["replacing"])
        self.again()
        self.assert_slim(OLD)
        self.assertEqual(list(self.kept_old().values()), list(was.values()), "the same kept copy, not a second one")

    def test_a_snapshot_retention_removed_mid_replace_is_not_put_back(self):
        """r2.F4: a run killed mid-replace leaves a lock the hourly job breaks half an hour
        on, and its prune can then remove the snapshot. The next slim finds the name empty
        and retention's own rule saying the snapshot goes: the journal entry and both
        copies go with it, and nothing is written back."""
        early, late = EARLY, LATE               # one day, ten days back: retention keeps the later
        self.old_store(early, late)
        self.killed_at("journaled")
        self.blob(early).unlink()               # the hourly job's prune
        done = self.tool("slim", "--set", "keel", "--approved")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("retention has removed it", done.stdout)
        self.assertFalse(self.blob(early).exists(), "it is not put back")
        self.assertEqual([k for k in self.objects() if early in k], [], "no copy of it is left behind")
        self.assertEqual((self.journal()["replacing"], early in self.journal()["done"]), (None, False))
        self.assert_slim(late)

    def test_a_name_emptied_while_retention_keeps_the_snapshot_is_filled_from_the_proven_copy(self):
        """Why the new archive is put under a temporary name first. Retention would keep
        this snapshot, so it was not retention that emptied its name, and dropping the
        copies would lose it: the proven new archive goes back."""
        self.old_store(OLD)
        self.killed_at("journaled")
        self.blob(OLD).unlink()
        self.assertEqual(self.again()["sets"]["keel"]["run"], [])
        self.assert_slim(OLD)
        self.assertEqual([k for k in self.objects() if k.startswith("slim-tmp/")], [])


@unittest.skipUnless(RCLONE, "rclone is not installed")
class StoreFailsTest(MidReplace, SlimCase):
    """r1.F9: each write of the replace failing in turn. Whatever fails, the snapshot's own
    name holds a whole archive, and the next run with a store that answers finishes."""
    STORE_KIND = "rclone"

    def failing(self, when: str, said: str):
        self.old_store(OLD)
        was = self.snapshots()
        self.dry()
        done = self.tool("slim", "--set", "keel", "--approved", PATH=self.stub_rclone(when))
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn(said, done.stdout + done.stderr)
        self.assertEqual(self.snapshots(), was, "the snapshot's own name was not written")
        self.assert_old(OLD)
        self.again()
        self.assert_slim(OLD)
        self.assertEqual([k for k in self.objects() if k.startswith("slim-tmp/")], [])

    def test_the_put_under_the_temporary_name_fails(self):
        self.failing("*copyto*new.gpg*slim-tmp/*", "could not be proven in the store under its temporary name")

    def test_the_old_archive_cannot_be_kept(self):
        self.failing("*copyto*slim-old/*", "its old archive could not be kept")

    def test_the_journal_cannot_be_written(self):
        self.failing("*copyto*slim.json*", "the journal could not be written")

    def test_the_put_over_the_name_fails(self):
        self.failing("*copyto*new.gpg*sets/keel/snapshots/*", "does not hold it as rewritten")

    def test_a_kept_copy_that_cannot_be_proven_is_not_left_where_the_old_archive_belongs(self):
        """r2.F1: the store said yes and holds something else under slim-old/. Left there,
        it would be taken for the way back; the snapshot's own name still holds the archive
        that was fetched, so the copy is removed."""
        self.old_store(OLD)
        was = self.snapshots()
        self.dry()
        bin_dir = self.root / "half-keep"
        bin_dir.mkdir()
        stub = bin_dir / "rclone"
        stub.write_text(f'#!/bin/bash\n"{RCLONE}" "$@"; rc=$?\ncase "$*" in *copyto*slim-old/*) '
                        f'printf half > "{self.store}/slim-old/keel/{OLD}.tar.gz.gpg" ;; esac\nexit $rc\n')
        stub.chmod(0o755)
        done = self.tool("slim", "--set", "keel", "--approved", PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((self.kept_old(), self.snapshots()), ({}, was), done.stdout + done.stderr)

    def test_an_unproven_kept_copy_that_cannot_be_removed_is_said_with_the_way_to_remove_it(self):
        """r3.F4: the store holds something else under slim-old/ and will not delete it. The
        snapshot is not written, the stop names the one verb that removes that object, and
        once it has, the next slim goes through."""
        self.old_store(OLD)
        was = self.snapshots()
        self.dry()
        bin_dir = self.root / "stuck-keep"
        bin_dir.mkdir()
        stub = bin_dir / "rclone"
        stub.write_text(f'#!/bin/bash\ncase "$*" in *deletefile*slim-old/*) echo "Failed: no" >&2; exit 1 ;; esac\n'
                        f'"{RCLONE}" "$@"; rc=$?\ncase "$*" in *copyto*slim-old/*) '
                        f'printf half > "{self.store}/slim-old/keel/{OLD}.tar.gz.gpg" ;; esac\nexit $rc\n')
        stub.chmod(0o755)
        done = self.tool("slim", "--set", "keel", "--approved", PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        said = done.stdout + done.stderr
        self.assertNotEqual(done.returncode, 0, said)
        self.assertIn(f"slim --purge --unproven {OLD} --set keel", said)
        self.assertEqual((self.snapshots(), list(self.kept_old())), (was, [OLD]))
        cleared = self.tool("slim", "--purge", "--unproven", OLD, "--set", "keel")
        self.assertEqual(cleared.returncode, 0, cleared.stdout + cleared.stderr)
        self.assertEqual((self.snapshots(), self.kept_old()), (was, {}))
        self.again()
        self.assert_slim(OLD)

    def test_a_temporary_object_the_store_lists_with_another_md5_is_not_trusted(self):
        """The upload said yes and the store holds something else under the temporary name."""
        self.old_store(OLD)
        was = self.snapshots()
        self.dry()
        bin_dir = self.root / "half-put"
        bin_dir.mkdir()
        stub = bin_dir / "rclone"
        stub.write_text(f'#!/bin/bash\n"{RCLONE}" "$@"; rc=$?\ncase "$*" in *copyto*new.gpg*slim-tmp/*) '
                        f'printf half > "{self.store}/slim-tmp/keel/{OLD}.new" ;; esac\nexit $rc\n')
        stub.chmod(0o755)
        done = self.tool("slim", "--set", "keel", "--approved", PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("could not be proven in the store under its temporary name", done.stdout + done.stderr)
        self.assertEqual(self.snapshots(), was)
        self.again()
        self.assert_slim(OLD)


class OneKeyTest(SlimCase):
    def test_a_replace_on_a_folder_store_reads_only_the_objects_it_writes(self):
        """r2.F15: each write is proven by that one object's md5. A listing of the set
        hashes every object in it; with another snapshot made unreadable once the replace
        is under way, a listing would fail and the replace would not go through."""
        if os.geteuid() == 0:
            self.skipTest("root reads every file")
        self.old_store()
        self.dry("--limit", "1")
        self.addCleanup(self.blob(NEW).chmod, 0o600)
        run = subprocess.Popen(["bash", str(TOOL), "slim", "--set", "keel", "--approved", "--limit", "1"], text=True,
                               env=self.env(KEEL_BACKUP_SLIM_TEST="1", KEEL_BACKUP_SLIM_HOLD_AT="kept"),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in run.stdout:
            if "holding at kept" in line:
                break
        self.blob(NEW).chmod(0o000)
        (self.home / ".slim-go").touch()
        said = run.stdout.read()
        run.wait(timeout=120)
        run.stdout.close()
        self.blob(NEW).chmod(0o600)
        self.assert_slim(OLD)
        self.assertEqual((sorted(self.journal()["done"]), self.journal()["replacing"]), ([OLD], None), said)


class KilledInFinishTest(SlimCase):
    def test_a_run_killed_after_the_replace_is_proven_is_finished_by_the_next(self):
        """r1.F9: inside slim_finish, at each of its writes."""
        for step in ("latest", "cleaned"):
            with self.subTest(step=step):
                self.reset()
                self.old_store(OLD)
                self.killed_at(step)
                self.assert_slim(OLD)
                self.assertEqual(self.journal()["replacing"]["id"], OLD, "the journal still names the replace")
                self.assertEqual(self.again()["sets"]["keel"]["run"], [])
                self.assertEqual((sorted(self.journal()["done"]), self.journal()["replacing"]), ([OLD], None))
                self.assertEqual([k for k in self.objects() if k.startswith("slim-tmp/")], [])
                self.assertEqual(sorted(self.kept_old()), [OLD])


@unittest.skipUnless(RCLONE, "rclone is not installed")
class ListingFailsTest(MidReplace, SlimCase):
    """r1.F4: a listing that failed is not an empty listing."""
    STORE_KIND = "rclone"

    def test_a_temp_listing_that_fails_stops_the_run_and_the_only_copy_stays(self):
        self.mid_replace(name_holds="nothing")
        before = self.objects()
        done = self.rewrite(PATH=self.stub_rclone("*lsjson*slim-tmp*"))
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.objects(), before, "nothing is removed and the journal still names the replace")
        self.again()
        self.assert_slim(OLD)


class JournalMissingTest(MidReplace, SlimCase):
    def test_copies_in_the_store_with_no_journal_stop_the_run_and_nothing_is_swept(self):
        """r2.F11: slim.json absent from a store that holds a slim's temporary object is a
        lost journal, not an empty one. Read as empty, the proven new copy was swept."""
        self.mid_replace(name_holds="old")
        (self.store / "sets" / "keel" / "slim.json").unlink()
        before = self.objects()
        done = self.rewrite()
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("slim.json", done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)


@unittest.skipUnless(RCLONE, "rclone is not installed")
class JournalUnprovenTest(MidReplace, SlimCase):
    STORE_KIND = "rclone"

    def deaf(self, after: int) -> str:
        """A PATH whose rclone says yes to a put of slim.json and does nothing, from the
        put numbered `after` on (0 is the first)."""
        bin_dir = self.root / "deaf"
        bin_dir.mkdir()
        stub = bin_dir / "rclone"
        stub.write_text(f'''#!/bin/bash
case "$*" in *copyto*slim.json*)
  n="$(cat "{bin_dir}/n" 2>/dev/null || echo 0)"; echo $((n + 1)) > "{bin_dir}/n"
  if [ "$n" -ge {after} ]; then exit 0; fi ;;
esac
exec "{RCLONE}" "$@"
''')
        stub.chmod(0o755)
        return f"{bin_dir}{os.pathsep}{os.environ['PATH']}"

    def test_a_journal_put_the_store_does_not_show_stops_before_the_name_is_written(self):
        """r2.F11: the store said yes to the journal that names the replace and does not
        hold it. The put over the snapshot's name does not go ahead on a journal nobody
        can read back."""
        self.old_store(OLD)
        was = self.snapshots()
        self.dry()
        done = self.tool("slim", "--set", "keel", "--approved", PATH=self.deaf(1))
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("the journal", done.stdout + done.stderr)
        self.assertEqual(self.snapshots(), was, "the name was not written")
        self.assertEqual((self.journal()["done"], self.journal()["replacing"]), ({}, None), "the first journal is all it holds")
        self.again()
        self.assert_slim(OLD)

    def test_a_first_journal_the_store_does_not_show_stops_before_any_copy_is_made(self):
        """r2.F11: no copy goes into the store before a journal is there to say what it is."""
        self.old_store(OLD)
        before = self.objects()
        self.dry()
        done = self.tool("slim", "--set", "keel", "--approved", PATH=self.deaf(0))
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)


class JournalUnreadTest(MidReplace, SlimCase):
    def test_a_journal_that_does_not_parse_stops_the_run_and_nothing_is_removed(self):
        self.mid_replace(name_holds="nothing")
        (self.store / "sets" / "keel" / "slim.json").write_text('{"done": {"2026')
        before = self.objects()
        done = self.rewrite()
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("slim.json", done.stdout + done.stderr)
        self.assertEqual(self.objects(), before, "a journal read as empty would have removed the temp object")

    def test_a_snapshot_gone_with_its_temp_copy_unproven_stops_and_names_the_copy(self):
        entry = self.mid_replace(name_holds="nothing")
        tmp = self.store / "slim-tmp" / "keel" / f"{OLD}.new"
        tmp.write_bytes(tmp.read_bytes()[:500])
        before = self.objects()
        done = self.rewrite()
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn(f"slim-tmp/keel/{OLD}.new", done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)
        self.assertEqual(entry["id"], OLD)


class NothingLeftTest(MidReplace, SlimCase):
    def test_a_replace_with_no_copy_left_anywhere_is_forgotten(self):
        """r2.F9: the name is empty and neither copy is held. There is nothing of that
        snapshot left to protect or to put back, so the journal stops naming it."""
        self.mid_replace(name_holds="nothing")
        (self.store / "slim-tmp" / "keel" / f"{OLD}.new").unlink()
        done = self.tool("slim", "--set", "keel", "--approved")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((self.journal()["replacing"], self.journal()["done"]), (None, {}))
        self.assertEqual(self.snapshots(), {})


@unittest.skipUnless(RCLONE, "rclone is not installed")
class RefillFailsTest(MidReplace, SlimCase):
    STORE_KIND = "rclone"

    def test_a_put_over_an_empty_name_that_fails_leaves_the_proven_copy_for_the_next_run(self):
        """r2.F9: the recovery's own write failing. The copy it was filling the name from
        is still in the store, the journal still names the replace, and the next run does it."""
        self.mid_replace(name_holds="nothing")
        before = self.objects()
        done = self.tool("slim", "--set", "keel", "--approved",
                         PATH=self.stub_rclone("*copyto*slim-back.gpg*sets/keel/snapshots/*"))
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)
        again = self.tool("slim", "--set", "keel", "--approved")
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assert_slim(OLD)
        self.assertEqual((sorted(self.journal()["done"]), self.journal()["replacing"]), ([OLD], None))


@unittest.skipUnless(RCLONE, "rclone is not installed")
class RetentionUnansweredTest(MidReplace, SlimCase):
    STORE_KIND = "rclone"

    def test_an_empty_name_is_not_judged_while_retention_cannot_be_asked(self):
        """r3.F4: whether an empty name is retention's work decides between removing every
        copy of a snapshot and putting it back. A listing that fails is no answer."""
        self.mid_replace(name_holds="nothing")
        before = self.objects()
        done = self.tool("slim", "--set", "keel", "--approved", PATH=self.stub_rclone("*lsjson*sets/keel/snapshots"))
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)
        again = self.tool("slim", "--set", "keel", "--approved")
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assert_slim(OLD)


class HalfWrittenTest(MidReplace, SlimCase):
    """r1.F5: a put over a name is not assumed atomic. A name that holds neither archive
    is filled from a copy proven in the store, or the run stops and names the good copies."""

    def test_a_name_truncated_mid_replace_gets_the_new_archive_from_its_proven_copy(self):
        self.old_store(OLD)
        self.killed_at("journaled")
        self.blob(OLD).write_bytes(self.blob(OLD).read_bytes()[:1000])
        self.assertEqual(self.again()["sets"]["keel"]["run"], [])
        self.assert_slim(OLD)
        self.assertEqual((sorted(self.journal()["done"]), self.journal()["replacing"]), ([OLD], None))

    def test_with_no_proven_new_copy_it_stops_and_names_the_old_archive_and_restore_puts_it_back(self):
        self.old_store(OLD)
        was = self.snapshots()
        self.killed_at("journaled")
        self.blob(OLD).write_bytes(b"half")
        tmp = self.store / "slim-tmp" / "keel" / f"{OLD}.new"
        tmp.write_bytes(tmp.read_bytes()[:500])
        before = self.objects()
        done = self.rewrite()
        said = done.stdout + done.stderr
        self.assertNotEqual(done.returncode, 0, said)
        self.assertIn(f"slim-old/keel/{OLD}.tar.gz.gpg", said)
        self.assertIn("--restore", said)
        self.assertNotIn("othing was touched", said)
        self.assertEqual(self.objects(), before)
        back = self.tool("slim", "--restore", OLD, "--set", "keel")
        self.assertEqual(back.returncode, 0, back.stdout + back.stderr)
        self.assertEqual(self.snapshots(), was)
        self.assertIsNone(self.journal()["replacing"])

    def test_with_no_good_copy_at_all_it_stops_and_removes_nothing(self):
        self.mid_replace(name_holds="half")
        tmp = self.store / "slim-tmp" / "keel" / f"{OLD}.new"
        tmp.write_bytes(tmp.read_bytes()[:500])
        before = self.objects()
        done = self.rewrite()
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("no copy", done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)


if __name__ == "__main__":
    unittest.main()
