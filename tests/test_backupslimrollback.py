"""`keel backup slim`, the way back (c-724): the old archive each rewrite keeps, `--restore`,
`--purge`, the commit point of the newest snapshot, and what the kept archives cost.

Runs the real `bin/keel-backup slim` on a scratch store (`tests/backupslimcase.py`); which
old archives a purge takes is `keel/backupslimjournal.py`.
"""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.backupslimcase import (
    EARLY, LATE, NEW, OLD, SlimCase)


class RollbackTest(SlimCase):
    """r1.F7: a rewrite keeps the archive it replaced, in the store, until it is purged."""

    def test_the_old_archive_is_kept_beside_the_set_and_status_says_how_many(self):
        self.old_store()
        was = self.snapshots()
        self.slim()
        self.assertEqual(self.kept_old(), {OLD: was[str(self.blob(OLD).relative_to(self.store))],
                                           NEW: was[str(self.blob(NEW).relative_to(self.store))]})
        status = json.loads(self.tool("status", "--json").stdout)["sets"]["keel"]
        self.assertEqual((status["snapshots_kept"], status["mb"]), (2, 0), "retention counts the set alone")
        self.assertEqual(status["slim_old"], {"count": 2, "mb": 2})
        self.assertIn("2 old archives kept", self.tool("status").stdout)

    def test_restore_puts_the_old_archive_back_over_its_name_and_forgets_the_rewrite(self):
        self.old_store()
        was = self.snapshots()
        self.slim()
        done = self.tool("slim", "--restore", OLD, "--set", "keel")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.snapshots()[str(self.blob(OLD).relative_to(self.store))],
                         was[str(self.blob(OLD).relative_to(self.store))])
        self.assert_old(OLD)
        self.assert_slim(NEW)
        self.assertEqual((sorted(self.journal()["done"]), sorted(self.kept_old())), ([NEW], [NEW]))
        again = self.tool("slim", "--restore", OLD, "--set", "keel")
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("no old archive", again.stdout + again.stderr)

    def old_object(self, sid: str) -> Path:
        return self.store / "slim-old" / "keel" / f"{sid}.tar.gz.gpg"

    def test_restore_refuses_an_object_the_journal_does_not_record_as_the_old_archive(self):
        """r2.F1: whatever sits at slim-old/<id> is not put over the only good copy on its
        say-so. The journal's own record of the old archive's md5 is what vouches for it."""
        self.old_store()
        self.slim()
        self.old_object(OLD).write_bytes(b"not the old archive")
        before = self.objects()
        done = self.tool("slim", "--restore", OLD, "--set", "keel")
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("not the archive the journal recorded", done.stdout + done.stderr)
        self.assertEqual(self.objects(), before, "the name, the journal and the object are as they were")
        self.assert_slim(OLD)

    def test_restore_refuses_when_no_journal_entry_names_the_snapshot(self):
        self.old_store()
        self.slim("--limit", "1")
        self.old_object(NEW).write_bytes(b"somebody put this here")
        before = self.objects()
        done = self.tool("slim", "--restore", NEW, "--set", "keel")
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("the journal has no rewrite of", done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)
        self.assert_old(NEW)

    def test_a_snapshot_whose_slim_old_name_is_taken_is_left_and_the_way_out_is_safe(self):
        """r2.F1, slim_commit's return 4: the message names the one safe action, and that
        action removes the stray object and nothing else."""
        self.old_store()
        self.slim("--limit", "1")
        kept = self.kept_old()
        self.old_object(NEW).write_bytes(b"not this snapshot's old archive")
        was = self.snapshots()
        done = self.rewrite()
        said = done.stdout + done.stderr
        self.assertIn("is not this snapshot's old archive", said)
        self.assertIn(f"slim --purge --unproven {NEW} --set keel", said)
        self.assertNotIn("--restore", said.split("the way back")[0])
        self.assertEqual(self.snapshots(), was)
        cleared = self.tool("slim", "--purge", "--unproven", NEW, "--set", "keel")
        self.assertEqual(cleared.returncode, 0, cleared.stdout + cleared.stderr)
        self.assertEqual((self.kept_old(), self.snapshots()), (kept, was))
        self.slim()
        self.assert_slim(NEW)

    def test_purge_unproven_takes_nothing_while_the_snapshots_own_name_is_empty(self):
        """r3.F4: with nothing under the name, the object under slim-old/ may be all there
        is of that snapshot, whatever the journal does or does not say of it."""
        self.old_store()
        self.slim("--limit", "1")
        self.old_object(NEW).write_bytes(self.blob(NEW).read_bytes())
        self.blob(NEW).unlink()
        before = self.objects()
        done = self.tool("slim", "--purge", "--unproven", NEW, "--set", "keel")
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)

    def test_only_a_sets_writer_removes_an_unproven_object_or_restores(self):
        """r3.F4: the two per-id verbs on a set this host does not write."""
        self.old_store()
        self.slim("--limit", "1")
        self.old_object(NEW).write_bytes(b"somebody put this here")
        before = self.objects()
        for argv in (("--purge", "--unproven", NEW), ("--restore", OLD), ("--purge", "--id", OLD)):
            with self.subTest(argv=argv):
                done = self.tool("slim", *argv, "--set", "keel", KEEL_BACKUP_SETS="code")
                self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
                self.assertEqual(self.objects(), before)

    def test_restore_of_a_replace_that_had_reached_the_name_puts_the_old_archive_back(self):
        """r3.F4: killed after the new archive went over the name and before the journal
        said done. The restore is the way out of that too: the old archive is back, and the
        journal names neither a replace nor a rewrite of it."""
        self.old_store(OLD)
        was = self.snapshots()
        self.killed_at("replaced")
        self.assertNotEqual(self.snapshots(), was, "the name holds the new archive")
        done = self.tool("slim", "--restore", OLD, "--set", "keel")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.snapshots(), was)
        self.assertEqual((self.journal()["replacing"], self.journal()["done"]), (None, {}))
        self.assertEqual((self.kept_old(), [k for k in self.objects() if k.startswith("slim-tmp/")]), ({}, []),
                         "nothing of the replace is left but the name")
        self.slim()
        self.assert_slim(OLD)

    def test_purge_unproven_leaves_an_old_archive_the_journal_vouches_for(self):
        self.old_store(OLD)
        self.slim()
        before = self.objects()
        done = self.tool("slim", "--purge", "--unproven", OLD, "--set", "keel")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("the journal vouches for it", done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)

    def test_purge_removes_only_the_old_archives_whose_rewrite_the_journal_marks_done(self):
        self.old_store()
        self.slim("--limit", "1")
        self.killed_at("journaled")              # NEW: its old archive kept, its replace unfinished
        self.assertEqual(sorted(self.kept_old()), [OLD, NEW])
        done = self.tool("slim", "--purge", "--set", "keel")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(sorted(self.kept_old()), [NEW], done.stdout + done.stderr)
        self.assert_slim(OLD)
        self.assert_old(NEW)
        self.assertEqual(json.loads(self.tool("status", "--json").stdout)["sets"]["keel"]["slim_old"]["count"], 1)

    def test_purge_keeps_the_old_archive_of_a_name_that_holds_an_object_nobody_recorded(self):
        """r2.F9: the name holds neither the slimmed archive the journal recorded nor the
        old one. The kept archive may be the only good copy of that snapshot, so it stays."""
        self.old_store(OLD)
        self.slim()
        kept = self.kept_old()
        other = self.root / "other-tree"
        self.write_tree(other, {"state/cards/c-9/plan.md": b"something else entirely\n"})
        self.publish(OLD, other)
        done = self.tool("slim", "--purge", "--set", "keel")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.kept_old(), kept)

    def test_restore_of_a_snapshot_retention_removed_puts_nothing_back(self):
        """r2.F9, r3.F2: retention's own rule says the earlier of a day's two goes. Its kept
        archive is an orphan for the purge, not a way to bring the snapshot back."""
        self.old_store(EARLY, LATE)
        self.slim()
        self.blob(EARLY).unlink()               # the hourly job's prune
        before = self.objects()
        done = self.tool("slim", "--restore", EARLY, "--set", "keel")
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)

    def test_restore_fills_an_empty_name_that_retention_would_keep(self):
        """r3.F2: an empty name is not proof that retention emptied it. Retention keeps this
        snapshot, so something else lost it, and the kept archive is its only copy: the
        restore puts it back."""
        self.old_store()
        was = self.snapshots()
        self.slim()
        self.blob(OLD).unlink()
        done = self.tool("slim", "--restore", OLD, "--set", "keel")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.objects()[str(self.blob(OLD).relative_to(self.store))],
                         was[str(self.blob(OLD).relative_to(self.store))])
        self.assert_old(OLD)
        self.assertNotIn(OLD, self.journal()["done"])

    def test_purge_of_one_id_removes_that_kept_archive_and_no_other(self):
        """r3.F5: the set-wide purge removes the way back for every rewritten snapshot of the
        set. One id can be let go by name, under the same rules as the purge."""
        self.old_store()
        self.slim()
        done = self.tool("slim", "--purge", "--id", OLD, "--set", "keel")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(sorted(self.kept_old()), [NEW])

    def test_purge_of_one_id_takes_nothing_the_purge_would_not(self):
        self.old_store()
        self.slim("--limit", "1")
        other = self.root / "other-tree"
        self.write_tree(other, {"state/cards/c-9/plan.md": b"something else entirely\n"})
        self.publish(OLD, other)                 # the name holds an object nobody recorded
        before = self.objects()
        for sid in (OLD, NEW):                  # one the purge keeps, one with nothing kept
            with self.subTest(sid=sid):
                done = self.tool("slim", "--purge", "--id", sid, "--set", "keel")
                self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
                self.assertEqual(self.objects(), before)
        alone = self.tool("slim", "--id", OLD, "--set", "keel")
        self.assertNotEqual(alone.returncode, 0)
        self.assertEqual(self.objects(), before)

    def test_only_a_sets_writer_purges_its_old_archives(self):
        """r2.F3: the kept old archives are the only way back from a rewrite, and a host
        that merely holds the store's login is not the one to remove them."""
        self.old_store(OLD)
        self.slim()
        before = self.objects()
        done = self.tool("slim", "--purge", "--set", "keel", KEEL_BACKUP_SETS="code")
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("does not write the keel set", done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)

    def test_purge_takes_the_old_archive_of_a_snapshot_retention_has_removed(self):
        self.old_store(EARLY, LATE)
        self.slim()
        self.blob(EARLY).unlink()               # the hourly job's prune
        self.assertEqual(self.tool("slim", "--purge", "--set", "keel").returncode, 0)
        self.assertEqual(self.kept_old(), {})

    def test_purge_keeps_the_only_copy_of_a_snapshot_retention_would_keep(self):
        """r3.F2: the name is empty and retention's rule keeps the snapshot, so the purge
        does not take the one copy left of it; it says the restore puts it back."""
        self.old_store()
        self.slim()
        self.blob(OLD).unlink()
        done = self.tool("slim", "--purge", "--set", "keel")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(sorted(self.kept_old()), [OLD])
        self.assertIn(f"slim --restore {OLD} --set keel", done.stdout + done.stderr)

    def emptied_day(self) -> None:
        """A day's two snapshots, both slimmed, both names then empty."""
        self.old_store(EARLY, LATE)
        self.slim()
        for sid in (EARLY, LATE):
            self.blob(sid).unlink()

    def test_restore_and_purge_agree_on_which_of_a_days_two_emptied_names_retention_took(self):
        """Both ask retention about the set with every snapshot the journal vouches a kept
        archive for counted back in. Of the day's two it keeps the later: the earlier is
        not restored and its archive is the purge's; the later is restored."""
        self.emptied_day()
        before = self.objects()
        early = self.tool("slim", "--restore", EARLY, "--set", "keel")
        self.assertNotEqual(early.returncode, 0, early.stdout + early.stderr)
        self.assertEqual(self.objects(), before)
        self.assertEqual(self.tool("slim", "--purge", "--set", "keel").returncode, 0)
        self.assertEqual(sorted(self.kept_old()), [LATE])
        late = self.tool("slim", "--restore", LATE, "--set", "keel")
        self.assertEqual(late.returncode, 0, late.stdout + late.stderr)
        self.assert_old(LATE)

    def test_a_stray_object_under_slim_old_is_not_a_snapshot_retention_is_asked_about(self):
        """Only an archive the journal vouches for stands for a snapshot. With a stray object
        under the later id, the earlier snapshot is the day's only one, retention keeps it,
        and purge and restore both say so: its archive stays, and goes back."""
        self.emptied_day()
        self.old_object(LATE).write_bytes(b"not the archive the journal recorded")
        done = self.tool("slim", "--purge", "--set", "keel")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(sorted(self.kept_old()), [EARLY, LATE], done.stdout + done.stderr)
        back = self.tool("slim", "--restore", EARLY, "--set", "keel")
        self.assertEqual(back.returncode, 0, back.stdout + back.stderr)
        self.assert_old(EARLY)

    def test_the_hourly_run_neither_counts_nor_prunes_the_kept_old_archives(self):
        self.old_tree(self.live)
        self.old_store(EARLY, LATE)             # one day, ten days back: retention keeps the later
        self.slim()
        took = self.tool("snapshot")
        self.assertEqual(took.returncode, 0, took.stdout + took.stderr)
        self.assertIn("1 pruned, 2 kept", took.stdout)
        self.assertEqual(sorted(self.kept_old()), [EARLY, LATE])


class JournalLostTest(SlimCase):
    """r3.F1: slim.json gone or unreadable after a rewrite is done. The kept old archive
    is then the only copy of the original, nothing in slim.json says so, and the tool must
    neither remove it on a guess nor be unable to put it back."""

    def slimmed(self) -> tuple[Path, dict]:
        self.old_store()
        was = self.snapshots()
        self.slim()
        return self.store / "sets" / "keel" / "slim.json", was

    def lost(self, journal: Path, how: str) -> None:
        if how == "absent":
            journal.unlink()
        else:
            journal.write_text('{"done": {"2026')

    def test_with_no_readable_journal_the_kept_archive_is_not_removed_and_is_still_restored(self):
        for how in ("absent", "corrupt"):
            with self.subTest(how=how):
                shutil.rmtree(self.store)
                shutil.rmtree(self.home / "work", ignore_errors=True)
                self.store.mkdir()
                journal, was = self.slimmed()
                self.lost(journal, how)
                before = self.objects()
                gone = self.tool("slim", "--purge", "--unproven", NEW, "--set", "keel")
                self.assertNotEqual(gone.returncode, 0, gone.stdout + gone.stderr)
                self.assertEqual(self.objects(), before, "nothing is removed on a journal nobody can read")
                back = self.tool("slim", "--restore", NEW, "--set", "keel")
                self.assertEqual(back.returncode, 0, back.stdout + back.stderr)
                self.assertIn("slim.json.prev", back.stdout + back.stderr, "it says which journal it went by")
                key = str(self.blob(NEW).relative_to(self.store))
                self.assertEqual(self.objects()[key], was[key])
                self.assert_old(NEW)

    def test_the_previous_journal_cannot_vouch_for_an_archive_it_did_not_record(self):
        journal, _was = self.slimmed()
        journal.unlink()
        (self.store / "slim-old" / "keel" / f"{NEW}.tar.gz.gpg").write_bytes(b"not the archive it recorded")
        before = self.objects()
        back = self.tool("slim", "--restore", NEW, "--set", "keel")
        self.assertNotEqual(back.returncode, 0, back.stdout + back.stderr)
        self.assertEqual(self.objects(), before)

    def test_the_local_copy_serves_when_the_store_has_lost_both(self):
        journal, was = self.slimmed()
        journal.unlink()
        Path(str(journal) + ".prev").unlink()
        back = self.tool("slim", "--restore", NEW, "--set", "keel")
        self.assertEqual(back.returncode, 0, back.stdout + back.stderr)
        key = str(self.blob(NEW).relative_to(self.store))
        self.assertEqual(self.objects()[key], was[key])
        self.assertIn("was written back as the store's journal", back.stdout + back.stderr)
        self.assertEqual(sorted(self.journal()["done"]), [OLD], "and the store has a journal again")

    def test_a_restore_by_the_local_copy_that_stops_does_not_say_it_wrote_the_journal(self):
        """The write is said where it is made. Here the local copy covers the store's kept
        archives, and the restore then stops on an object that copy did not record."""
        journal, _was = self.slimmed()
        journal.unlink()
        Path(str(journal) + ".prev").unlink()
        (self.store / "slim-old" / "keel" / f"{NEW}.tar.gz.gpg").write_bytes(b"not the archive it recorded")
        before = self.objects()
        back = self.tool("slim", "--restore", NEW, "--set", "keel")
        said = back.stdout + back.stderr
        self.assertNotEqual(back.returncode, 0, said)
        self.assertIn("going by this machine's copy", said)
        self.assertNotIn("written back", said)
        self.assertEqual(self.objects(), before)

    def test_a_local_copy_older_than_the_stores_kept_archives_is_not_written_back(self):
        """The local copy is only as new as this machine's last slim. If the store keeps an
        old archive that copy has no entry for, writing it back as the store's journal would
        make that archive one nobody recorded, there for --purge --unproven to take."""
        self.old_store()
        self.slim("--limit", "1")
        local = self.home / "work" / "keel" / "slim.json.prev"
        stale = local.read_text()               # knows the first rewrite, not the second
        self.slim()
        local.write_text(stale)
        journal = self.store / "sets" / "keel" / "slim.json"
        journal.unlink()
        Path(str(journal) + ".prev").unlink()
        before = self.objects()
        back = self.tool("slim", "--restore", OLD, "--set", "keel")
        said = back.stdout + back.stderr
        self.assertNotEqual(back.returncode, 0, said)
        self.assertIn(NEW, said, "it names the kept archive the copy does not know")
        self.assertEqual(self.objects(), before)
        gone = self.tool("slim", "--purge", "--unproven", NEW, "--set", "keel")
        self.assertNotEqual(gone.returncode, 0, gone.stdout + gone.stderr)
        self.assertEqual(self.objects(), before)

    def test_a_second_copy_of_what_the_name_holds_goes_without_a_journal(self):
        """The one case with no journal to ask: the object under slim-old/ is, byte for
        byte, what the snapshot's own name holds, so removing it loses nothing."""
        self.old_store(OLD)
        twin = self.store / "slim-old" / "keel" / f"{OLD}.tar.gz.gpg"
        twin.parent.mkdir(parents=True)
        shutil.copy(self.blob(OLD), twin)
        was = self.snapshots()
        done = self.tool("slim", "--purge", "--unproven", OLD, "--set", "keel")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((self.kept_old(), self.snapshots()), ({}, was))

    def test_a_run_that_finds_copies_and_no_journal_names_the_way_back_not_a_removal(self):
        journal, _was = self.slimmed()
        journal.unlink()
        before = self.objects()
        done = self.tool("slim", "--set", "keel", "--dry-run")
        said = done.stdout + done.stderr
        self.assertNotEqual(done.returncode, 0, said)
        self.assertIn("slim --restore", said)
        self.assertNotIn("--unproven", said)
        self.assertEqual(self.objects(), before)


class AskedForTest(SlimCase):
    """r3.F9: what the verb is given is checked before anything is touched."""

    def test_an_id_that_is_not_a_snapshot_id_reaches_no_path(self):
        """An id is spliced into the keys. On a folder store one with `../` in it made the
        slim-old key and the snapshot's own key the same file, a real snapshot, which
        `--purge --unproven` then removed."""
        self.old_store()
        self.slim("--limit", "1")
        before = self.objects()
        real = str(self.blob(NEW).relative_to(self.store))[: -len(".tar.gz.gpg")]
        for argv in (("--purge", "--unproven", f"../../{real}"), ("--restore", f"../../{real}"),
                     ("--restore", "latest"), ("--purge", "--unproven", OLD + "x")):
            with self.subTest(argv=argv):
                done = self.tool("slim", *argv, "--set", "keel")
                self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
                self.assertEqual(self.objects(), before)

    def test_two_things_asked_for_at_once_are_refused(self):
        self.old_store()
        self.slim("--limit", "1")
        before = self.objects()
        for argv in (("--purge", "--restore", OLD), ("--purge", "--approved"), ("--restore", OLD, "--dry-run"),
                     ("--dry-run", "--approved"), ("--restore", OLD, "--approved")):
            with self.subTest(argv=argv):
                done = self.tool("slim", *argv, "--set", "keel")
                self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
                self.assertEqual(self.objects(), before)


class SizeKnobTest(SlimCase):
    def test_a_threshold_that_is_not_a_number_is_the_built_in_one(self):
        """r3.F8: the override is read by every hourly run, with no gate. A stray value that
        is not a number once made the comparison an error, which is no warning at all."""
        self.old_tree(self.live)
        took = self.tool("snapshot", KEEL_BACKUP_SIZE_WARN_MB="lots")
        self.assertEqual(took.returncode, 0, took.stdout + took.stderr)
        self.assertNotIn("integer", took.stderr, "the comparison did not fail on it")


class CommitPointTest(SlimCase):
    def newest_in_the_old_shape(self) -> tuple[str, dict, dict]:
        """The tool's own newest snapshot, put back in the old shape under the same id, with
        a latest.json that says something a rewrite must put right. Returns the id, what
        latest.json said of the tool's own archive, and what it says now."""
        self.old_tree(self.live)
        took = self.tool("snapshot")
        self.assertEqual(took.returncode, 0, took.stdout + took.stderr)
        latest = self.store / "sets" / "keel" / "latest.json"
        before = json.loads(latest.read_text())
        sid = before["snapshot"]
        fat = self.root / "fat"
        self.old_tree(fat)
        (fat / "state" / "board.db").unlink()
        for never in ("odd", "repos"):          # the tool never packed what is under no root
            shutil.rmtree(fat / never)
        subprocess.run(["bash", "-c", 'gpg --batch --quiet --no-tty --pinentry-mode loopback '
                        '--passphrase-file "$1" --decrypt "$2" | tar -xzf - -C "$3" state/board.db',
                        "_", str(self.key), str(self.blob(sid)), str(fat)], check=True, capture_output=True)
        self.publish(sid, fat)                  # the same id, in the old shape
        wrong = dict(before, manifest="0" * 64, files=99)
        latest.write_text(json.dumps(wrong))
        return sid, before, wrong

    def test_the_newest_snapshots_latest_json_names_what_it_now_holds(self):
        """The hourly change test reads `manifest` from `latest.json`: after the newest
        snapshot is rewritten it is the rewritten archive's, so an unchanged tree is skipped."""
        sid, before, _wrong = self.newest_in_the_old_shape()
        self.slim()
        after = json.loads((self.store / "sets" / "keel" / "latest.json").read_text())
        self.assertEqual((after["snapshot"], after["manifest"], after["files"], after["host"]),
                         (sid, before["manifest"], before["files"], before["host"]))
        again = self.tool("snapshot")
        self.assertIn("unchanged since " + sid, again.stdout + again.stderr)

    def test_restoring_the_newest_snapshot_puts_latest_json_back_to_what_it_said(self):
        """r2.F9: the restore's half. latest.json describes the old archive again, in the
        store and in the copy the hourly job reads, so its change test is not fooled by a
        manifest that is the slimmed archive's."""
        sid, _before, wrong = self.newest_in_the_old_shape()
        fat = self.snapshots()
        self.slim()
        done = self.tool("slim", "--restore", sid, "--set", "keel")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.snapshots(), fat)
        for where in (self.store / "sets" / "keel", self.home / "work" / "keel"):
            self.assertEqual(json.loads((where / "latest.json").read_text()), wrong, str(where))


class SizeTest(SlimCase):
    def test_the_size_warning_counts_what_a_slim_keeps_and_status_shows_it_apart(self):
        """r2.F13: until the purge the store holds every rewritten snapshot twice, and the
        one alarm about the store's size summed the sets alone."""
        said = self.root / "kb-said"
        kb = self.live / "bin" / "kb"                    # a scratch install's board: it only writes down
        kb.parent.mkdir()
        kb.write_text(f'#!/bin/bash\nprintf \'%s\\n\' "$*" >> "{said}"\nif [ "$1" = list ]; then echo "[]"; fi\n')
        kb.chmod(0o755)
        self.old_store(OLD)
        self.slim()
        self.old_tree(self.live)
        took = self.tool("snapshot", KEEL_BACKUP_SIZE_WARN_MB="0")
        self.assertEqual(took.returncode, 0, took.stdout + took.stderr)
        status = json.loads(self.tool("status", "--json").stdout)
        self.assertEqual((status["store_mb"], status["slim_old_mb"]), (0, 1))
        raised = [line for line in said.read_text().splitlines() if line.startswith("create") and "backup-size" in line]
        self.assertEqual(len(raised), 1, said.read_text())
        self.assertIn("slim-old/", raised[0])
        self.assertIn("slim-old", self.tool("status").stdout)


if __name__ == "__main__":
    unittest.main()
