"""`keel backup slim` (c-724): the retained snapshots rewritten without what the backup now
leaves out. This module: the dry run, the rewrite, what an archive can hold, and the sums.

The end-to-end tests run the real `bin/keel-backup` against a scratch store (a folder, and
once more through rclone's own local backend), scratch keys and a scratch backup home, all
under one temporary directory (`tests/backupslimcase.py` is the fixture). The sums are
`keel/backupslim.py` and `keel/backupslimreport.py`. The other concerns have a module each:
`test_backupslimapproval.py`, `test_backupslimrecovery.py`, `test_backupslimrollback.py`
and `test_backupslimlocks.py`. The clock is read once, in the fixture, to place the
snapshots' ids where the tool's retention keeps them; a run is asserted on what the
store holds afterwards.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from keel import backupslim
from tests.backupslimcase import (
    BSDTAR, by_rule, DROPPED, ENCRYPT, find_of, KEPT, member, NEW, OLD, RCLONE, ROOT,
    SCRATCH, sha, SlimCase, TOOL)
from tests.helpers import write_toml


class DryRunTest(SlimCase):
    def test_the_dry_run_writes_nothing_and_its_numbers_are_what_the_rewrite_removes(self):
        self.old_store()
        before = self.objects()
        dry = self.dry()
        self.assertEqual(self.objects(), before, "a dry run writes nothing to the store")
        self.assertTrue(dry["dry_run"])
        told = dry["sets"]["keel"]
        self.assertEqual({r["rule"]: (r["files"], r["bytes"]) for r in told["rules"]},
                         {rule: (2 * n, 2 * size) for rule, (n, size) in by_rule().items()})
        self.assertEqual([(s["id"], s["state"]) for s in told["run"]],
                         [(OLD, "would-slim"), (NEW, "would-slim")])
        self.assertGreater(dry["estimate"]["seconds"], 0)

        real = self.slim()["sets"]["keel"]
        self.assertEqual(real["rules"], told["rules"])
        self.assertEqual((real["dropped_files"], real["dropped_bytes"]),
                         (told["dropped_files"], told["dropped_bytes"]))
        self.assertEqual([(s["id"], s["state"]) for s in real["run"]],
                         [(OLD, "slimmed"), (NEW, "slimmed")])
        for sid in (OLD, NEW):
            self.assert_slim(sid)

    def test_the_dry_run_says_it_in_words_per_snapshot_and_in_total(self):
        self.old_store(OLD)
        done = self.tool("slim", "--set", "keel", "--dry-run")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        for said in (OLD, "node_modules", "state/cards/*/scratch", "*.mp4", "1.4MB",
                     "nothing was written to the store", "estimate"):
            self.assertIn(said, done.stdout)


class RewriteTest(SlimCase):
    def test_a_rewritten_snapshot_restores_and_verifies_and_keeps_its_id(self):
        self.old_store()
        ids = sorted(self.snapshots())
        self.slim()
        self.assertEqual(sorted(self.snapshots()), ids,
                         "no snapshot is deleted, added or renamed")
        into = self.root / "restored"
        done = self.tool("restore", "--set", "keel", "--snapshot", OLD, "--into", str(into))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((into / "state/cards/c-1/plan.md").read_bytes(), KEPT["state/cards/c-1/plan.md"])
        self.assertFalse((into / "state/logs").exists())
        self.assertEqual(self.tool("verify", "--set", "keel").returncode, 0)
        self.assertEqual([k for k in self.objects() if k.startswith("slim-tmp/")], [],
                         "no temporary object is left in the store")

    def test_a_snapshot_taken_under_todays_rules_is_examined_once_and_never_written(self):
        """The scan over an unpacked snapshot lists what the scan over the live tree listed."""
        self.old_tree(self.live)
        took = self.tool("snapshot")
        self.assertEqual(took.returncode, 0, took.stdout + took.stderr)
        blobs = self.snapshots()
        self.assertEqual([s["state"] for s in self.slim()["sets"]["keel"]["run"]], ["nothing"])
        self.assertEqual(self.snapshots(), blobs)
        self.assertEqual(self.slim()["sets"]["keel"]["run"], [], "the journal says it was looked at")

    def test_a_log_of_what_each_snapshot_lost_is_kept(self):
        self.old_store(OLD)
        self.slim()
        lines = [json.loads(line) for line in (self.home / "logs" / "slim.jsonl").read_text().splitlines()]
        self.assertEqual([(line["set"], line["id"], line["state"]) for line in lines],
                         [("keel", OLD, "slimmed")])
        self.assertIn("state/logs/", [node["path"] for node in lines[0]["nodes"]])
        journal = json.loads((self.store / "sets" / "keel" / "slim.json").read_text())
        self.assertEqual(journal["done"][OLD]["dropped_files"], len(DROPPED))

    def test_a_cards_scratch_goes_whole_on_the_archives_own_word(self):
        """c-752: the scan leaves a card's scratch out whole, a checkout in it or plain
        copies, so one tree goes, under one rule, and nothing but the archive is asked."""
        self.old_store(OLD)
        told = self.slim()["sets"]["keel"]
        node = [n for n in told["run"][0]["nodes"] if n["path"].startswith(SCRATCH)]
        self.assertEqual([(n["path"], n["rule"], n["files"]) for n in node],
                         [(SCRATCH + "/", "state/cards/*/scratch", 3)])
        self.assert_slim(OLD)

    def test_status_keeps_its_count_and_its_newest_and_reads_the_new_sizes(self):
        self.old_store()
        self.slim()
        status = json.loads(self.tool("status", "--json").stdout)["sets"]["keel"]
        self.assertEqual((status["snapshots_kept"], status["last_snapshot"]), (2, NEW))
        self.assertEqual(status["mb"], 0, "two films of 1.4MB each are gone from the listing")

    def test_too_little_free_disk_stops_the_run_before_anything_is_fetched(self):
        self.old_store(OLD)
        before = self.objects()
        done = self.rewrite(KEEL_BACKUP_SLIM_DISK_FLOOR_MB="999999999")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("free", done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)


class UnpackedWholeTest(SlimCase):
    """r1.F3: the proof compares two unpacked trees, so what unpacking itself lost has to be
    caught before it: the archive's own member list against the tree it unpacked to."""

    def test_two_names_that_differ_only_in_case_are_not_folded_into_one(self):
        probe = self.root / "CaseProbe"
        probe.write_text("x")
        if not (self.root / "caseprobe").exists():
            self.skipTest("this volume tells names apart by case, so nothing folds")
        self.publish_members(OLD, [(member("state/cards/c-1/Notes.md"), b"one\n"),
                                   (member("state/cards/c-1/notes.md"), b"two\n")])
        self.left_as_it_was(OLD, "names 1 path the unpacked tree does not hold")

    def test_a_directory_that_cannot_be_listed_is_not_read_as_empty(self):
        if os.geteuid() == 0:
            self.skipTest("root lists every directory")
        self.publish_members(OLD, [(member("odd/sealed", 0o000, tarfile.DIRTYPE), None),
                                   (member("odd/sealed/inside.txt"), b"kept by the rules\n")])
        self.left_as_it_was(OLD, "could not be read")


class OddArchiveTest(SlimCase):
    """r1.F9: what an archive can hold that the fixture tree does not."""

    def test_names_with_a_space_and_a_newline_are_kept_or_dropped_as_whole_names(self):
        kept = {"state/cards/c-1/a b.md": b"spaced\n", "state/cards/c-1/two\nlines.md": b"split\n"}
        self.publish_members(OLD, [(member(name), data) for name, data in kept.items()]
                             + [(member("state/logs/odd \n name.log"), b"a log\n")])
        self.slim()
        files, _dirs = self.unpack(OLD)
        for name, data in kept.items():
            self.assertEqual(files.get(name), sha(data), repr(name))
        self.assertNotIn("state/logs/odd \n name.log", files)
        self.assertEqual(len(files), len(KEPT) + 1 + len(kept))

    def test_a_name_this_disk_cannot_hold_leaves_the_snapshot_as_it_was_or_keeps_the_file(self):
        """Bytes that are not UTF-8: a disk that takes any bytes unpacks them, APFS refuses
        the name. Where the disk holds it, the file is in the rewritten snapshot; where it
        does not, the dry run says the snapshot could not be read whole and the object is
        left byte for byte. Never neither, and each leg is asserted where it applies."""
        raw = self.root / "raw.tar"
        self.publish_members(OLD)
        name = "state/cards/c-1/caf\udce9.md"
        with tarfile.open(raw, "a", format=tarfile.GNU_FORMAT, errors="surrogateescape") as tar:
            info = member(name)
            info.size = 4
            tar.addfile(info, io.BytesIO(b"odd\n"))
        subprocess.run(["bash", "-c", 'gzip -9nc "$1" | ' + ENCRYPT, "_", str(raw), str(self.key), str(self.blob(OLD))],
                       check=True, capture_output=True)
        try:
            (self.root / os.fsencode("caf\udce9.md").decode("utf-8", "surrogateescape")).write_bytes(b"")
            holds = True
        except OSError:
            holds = False
        if not holds:
            self.left_as_it_was(OLD, "left as it is")
            return
        self.slim()
        listed = subprocess.run(["bash", "-c", 'gpg --batch --quiet --no-tty --pinentry-mode loopback '
                                 '--passphrase-file "$1" --decrypt "$2" | tar -tzf -', "_", str(self.key),
                                 str(self.blob(OLD))], capture_output=True, check=True).stdout
        self.assertIn(b"caf\xe9.md", listed)
        self.assertNotIn(b"keel.out.log", listed, "and it is slim")

    def test_a_real_file_named_like_a_resource_fork_is_kept_or_the_snapshot_is_left(self):
        """r2.F7: `._x` beside `x` that is not AppleDouble is somebody's file. Measured on
        macOS 27 (bsdtar 3.5.3): tar tries to fold it into `x` as metadata, fails, and
        exits 1 whatever the order, leaving `x` alone when `._x` came first. GNU tar
        unpacks both. So: both files are in the rewritten snapshot, or it is not rewritten."""
        name = "state/cards/c-1/._plan.md"
        self.publish_members(OLD, [(member(name), b"a real file, not AppleDouble\n")])
        before = self.snapshots()
        self.rewrite()
        if BSDTAR:
            self.assertEqual(self.snapshots(), before, "tar could not unpack it whole, so it is left")
        else:
            files, _dirs = self.unpack(OLD)
            self.assertEqual(files.get(name), sha(b"a real file, not AppleDouble\n"))
            self.assertNotIn("state/logs/keel.out.log", files, "and it is slim")

    def test_a_link_in_an_archive_is_not_guessed_at(self):
        self.publish_members(OLD, [(member("state/cards/c-1/latest", kind=tarfile.SYMTYPE, link="plan.md"), None)])
        self.left_as_it_was(OLD, "neither files nor directories")

    def test_a_hard_link_stays_two_files_with_one_content(self):
        tree = self.root / "old-tree"
        self.old_tree(tree)
        os.link(tree / "state/cards/c-1/plan.md", tree / "state/cards/c-1/plan-again.md")
        self.publish(OLD, tree)
        self.slim()
        files, _dirs = self.unpack(OLD)
        self.assertEqual(files["state/cards/c-1/plan-again.md"], files["state/cards/c-1/plan.md"])
        self.assertEqual(len(files), len(KEPT) + 2)


class KeyTest(SlimCase):
    def test_with_the_wrong_key_nothing_is_read_and_nothing_is_written(self):
        self.old_store(OLD)
        self.key.write_text("not the passphrase")
        self.left_as_it_was(OLD, "does not decrypt")

    def test_with_no_key_the_set_is_skipped(self):
        self.old_store(OLD)
        self.key.unlink()
        before = self.objects()
        for mode in ("--dry-run", "--approved"):
            done = self.tool("slim", "--set", "keel", mode)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertIn("no passphrase here", done.stdout)
        self.assertEqual(self.objects(), before)


class FailedProofTest(SlimCase):
    def test_a_rewritten_archive_that_is_missing_a_kept_file_never_reaches_the_store(self):
        """r1.F9: the proof, end to end. A tar that packs one member fewer than it was told
        stands in for whatever might lose a file between the unpacked tree and the new
        archive; the dry run packed honestly, so the approval is in order."""
        self.old_store(OLD)
        bin_dir = self.root / "short-tar"
        bin_dir.mkdir()
        real = shutil.which("tar")
        stub = bin_dir / "tar"
        stub.write_text('#!/bin/bash\ncase "$*" in *-cf*--no-recursion*) list="${@: -1}"\n'
                        f'  python3 -c \'import sys; names = open(sys.argv[1], "rb").read().split(b"\\0"); '
                        'keep = [n for n in names if n and not n.endswith(b"plan.md")]; '
                        'open(sys.argv[1], "wb").write(b"".join(n + b"\\0" for n in keep))\' "$list" ;; esac\n'
                        f'exec "{real}" "$@"\n')
        stub.chmod(0o755)
        before = self.objects()
        self.dry()
        done = self.tool("slim", "--set", "keel", "--approved", PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        said = done.stdout + done.stderr
        self.assertNotEqual(done.returncode, 0, said)
        self.assertIn("kept by the rules but missing", said)
        self.assertIn("state/cards/c-1/plan.md", said)
        self.assertEqual(self.objects(), before, "no object was written: not the name, not a copy, not the journal")


@unittest.skipUnless(RCLONE, "rclone is not installed")
class RcloneStoreTest(SlimCase):
    STORE_KIND = "rclone"

    def test_the_same_rewrite_through_rclone(self):
        self.old_store()
        told = self.slim()["sets"]["keel"]
        self.assertEqual([s["state"] for s in told["run"]], ["slimmed", "slimmed"])
        for sid in (OLD, NEW):
            self.assert_slim(sid)
        self.assertEqual(self.tool("verify", "--set", "keel").returncode, 0)


class ScanFailsTest(SlimCase):
    def test_a_directory_list_that_fails_fails_the_scan(self):
        """r1.F11: a directory pass that failed, with the file pass fine, must not read as
        a short list, or every directory it did not print is one the rules had dropped. Run
        with a tool whose directory list fails: the snapshot is not planned at all."""
        self.old_store(OLD)
        before = self.objects()
        tool = self.changed_tool("keel_dir_list()  { keel_find d; }\n", "keel_dir_list()  { return 1; }\n")
        done = subprocess.run(["bash", str(tool), "slim", "--set", "keel", "--dry-run", "--json"],
                              env=self.env(), capture_output=True, text=True, timeout=300)
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual([s["state"] for s in json.loads(done.stdout)["sets"]["keel"]["run"]], ["failed"])
        self.assertFalse((self.home / "slim-approved.json").exists()
                         and json.loads((self.home / "slim-approved.json").read_text())["sets"]["keel"])
        self.assertEqual(self.objects(), before)


class RulesTest(unittest.TestCase):
    def test_the_rules_are_read_from_the_scans_own_find(self):
        names = [rule.pattern for rule in backupslim.rules(find_of("keel_find"))]
        for rule in {rule for rule, _data in DROPPED.values()} | {"board.db", ".git", "state/voice/pcm"}:
            self.assertIn(rule, names)
        self.assertNotIn("state/cards/*/*/scratch", names, "a test that narrows a rule is not one")

    def test_a_name_is_tried_before_a_path(self):
        rules = backupslim.rules(find_of("keel_find"))
        self.assertEqual(backupslim.rule_of("state/cards/c-1/scratch/node_modules", rules), "node_modules")
        self.assertEqual(backupslim.rule_of("state/cards/c-1/scratch/clip.WAV", rules), "*.wav")
        self.assertEqual(backupslim.rule_of("state/cards/c-1/scratch", rules), "state/cards/*/scratch")
        self.assertEqual(backupslim.rule_of("state/nothing/names/this", rules), backupslim.UNNAMED)


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tree = Path(self.tmp.name) / "old"
        for rel in ("state/a.md", "state/logs/x.log", "state/board.db", "other/b.md"):
            (self.tree / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.tree / rel).write_text(rel)

    def plan(self, kept):
        return backupslim.plan(self.tree, set(kept), ["state"], {"state/board.db"},
                               backupslim.rules("find -path 'state/logs' -prune -o ! -name 'board.db'"))

    def test_every_path_the_set_stages_is_kept_by_name_even_under_a_root(self):
        """r2.F12: the set stages more than its canary. A staged file the scan does not
        list, under a root the scan walks, is kept because the set says it stages it."""
        staged = self.tree / "state" / "repos" / "memory.bundle"
        staged.parent.mkdir()
        staged.write_text("a bundle")
        found = backupslim.plan(self.tree, {"state", "state/a.md"}, ["state"],
                                {"state/board.db", "state/repos/memory.bundle"},
                                backupslim.rules("find -path 'state/logs' -prune -o ! -name 'board.db'"))
        self.assertEqual(found.drop_files, {"state/logs/x.log"})
        self.assertIn("state/repos/memory.bundle", found.members)
        self.assertIn("state/repos", found.members)

    def test_only_what_the_scan_left_out_under_a_root_is_dropped(self):
        found = self.plan({"state", "state/a.md"})
        self.assertEqual((found.drop_files, found.drop_dirs), ({"state/logs/x.log"}, {"state/logs"}))
        self.assertEqual(found.summary["nodes"],
                         [{"path": "state/logs/", "rule": "state/logs", "files": 1,
                           "bytes": len("state/logs/x.log")}])
        self.assertEqual(found.summary["outside"]["files"], 1, "other/b.md is kept, and counted")
        self.assertEqual(found.members, ["other", "other/b.md", "state", "state/a.md", "state/board.db"])

    def test_an_archive_naming_what_the_tree_does_not_hold_is_told_apart(self):
        """r1.F3, with a made-up listing: a volume that folds case unpacks two members into
        one file and tar says nothing."""
        files, dirs, others = backupslim.walk(self.tree)
        named = {path: "file" for path in files} | {path: "dir" for path in dirs}
        self.assertEqual(backupslim.unpacked_whole(named, files, dirs, others), [])
        named["state/A.md"] = "file"
        self.assertIn("state/A.md", "\n".join(backupslim.unpacked_whole(named, files, dirs, others)))
        del named["state/A.md"], named["other/b.md"]
        self.assertIn("other/b.md", "\n".join(backupslim.unpacked_whole(named, files, dirs, others)))

    def archive_of(self, extra: dict) -> Path:
        """The tree, as an archive, with members a disk may fold away."""
        raw = Path(self.tmp.name) / "a.tar.gz"
        with tarfile.open(raw, "w:gz") as tar:
            for path in sorted(self.tree.rglob("*")):
                tar.add(path, arcname=str(path.relative_to(self.tree)), recursive=False)
            for name, data in extra.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return raw

    def whole(self, extra: dict) -> tuple[int, str]:
        """The tool's own question (`members`): is the unpacked tree the archive, path for path?"""
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            rc = backupslim.main(["members", "--archive", str(self.archive_of(extra)), "--tree", str(self.tree)])
        return rc, said.getvalue()

    def test_a_member_named_like_a_resource_fork_is_ignored_only_when_it_is_one_and_was_folded(self):
        """r2.F7. macOS tar writes a file's extended attributes as an AppleDouble `._name`
        member and folds it back in on unpacking. Only that is not a path of its own: the
        magic says it is AppleDouble, and its absence from the tree says it was folded."""
        apple = bytes.fromhex("00051607") + b"\0" * 28
        self.assertEqual(self.whole({"state/._a.md": apple})[0], 0, "AppleDouble, folded into a.md")
        rc, said = self.whole({"state/._a.md": b"a real file that unpacking swallowed\n"})
        self.assertEqual(rc, 1, "not AppleDouble: a file the tree has lost")
        self.assertIn("state/._a.md", said)
        (self.tree / "state" / "._a.md").write_bytes(apple)
        self.assertEqual(self.whole({"state/._a.md": apple})[0], 0, "in the tree: a file like any other")

    def test_a_directory_the_walk_cannot_list_raises(self):
        if os.geteuid() == 0:
            self.skipTest("root lists every directory")
        sealed = self.tree / "state" / "logs"
        sealed.chmod(0o000)
        self.addCleanup(sealed.chmod, 0o755)
        with self.assertRaises(OSError):
            backupslim.walk(self.tree)

    def test_a_snapshot_the_scan_would_keep_whole_drops_nothing(self):
        found = self.plan({"state", "state/a.md", "state/logs", "state/logs/x.log"})
        self.assertEqual((found.drop_files, found.drop_dirs), (set(), set()))

    def rewritten(self, found) -> Path:
        """The kept members copied out with their modes and times, as a faithful rewrite
        unpacks: directories last, so writing into one does not move its time."""
        new = Path(tempfile.mkdtemp(dir=self.tmp.name))
        for rel in found.members:
            if (self.tree / rel).is_dir():
                (new / rel).mkdir(parents=True, exist_ok=True)
            else:
                shutil.copy2(self.tree / rel, new / rel)
        for rel in reversed(found.members):
            if (self.tree / rel).is_dir():
                shutil.copystat(self.tree / rel, new / rel)
        return new

    def test_the_proof_refuses_a_kept_file_or_directory_whose_mode_or_time_alone_moved(self):
        """r1.F9, r1.F10: content is not the whole of a file, and a directory restored 0755
        that was 0700 is not the directory that was backed up."""
        found = self.plan({"state", "state/a.md"})
        for rel, change in (("state/a.md", lambda p: p.chmod(0o600)),
                            ("state/a.md", lambda p: os.utime(p, (5, 5))),
                            ("state", lambda p: p.chmod(0o700)),
                            ("state", lambda p: os.utime(p, (5, 5)))):
            new = self.rewritten(found)
            self.assertEqual(backupslim.prove(self.tree, new, found.drop_files, found.drop_dirs)[0], [])
            change(new / rel)
            said = "\n".join(backupslim.prove(self.tree, new, found.drop_files, found.drop_dirs)[0])
            self.assertIn("    " + rel, said)

    def test_where_tar_carries_whole_seconds_a_fraction_of_one_is_not_a_difference(self):
        found = self.plan({"state", "state/a.md"})
        new = self.rewritten(found)
        was = (self.tree / "state/a.md").stat().st_mtime_ns
        os.utime(new / "state/a.md", ns=(was // 10**9 * 10**9, was // 10**9 * 10**9))
        os.utime(self.tree / "state/a.md", ns=(was // 10**9 * 10**9 + 5, was // 10**9 * 10**9 + 5))
        prove = backupslim.prove
        self.assertNotEqual(prove(self.tree, new, found.drop_files, found.drop_dirs)[0], [])
        self.assertEqual(prove(self.tree, new, found.drop_files, found.drop_dirs, whole_seconds=True)[0], [])

    def test_the_proof_refuses_a_missing_an_extra_and_a_changed_file(self):
        found = self.plan({"state", "state/a.md"})
        new = self.rewritten(found)
        self.assertEqual(backupslim.prove(self.tree, new, found.drop_files, found.drop_dirs)[0], [])
        (new / "state/a.md").write_text("changed/a.md")
        (new / "state/extra.md").write_text("x")
        (new / "other/b.md").unlink()
        problems = "\n".join(backupslim.prove(self.tree, new, found.drop_files, found.drop_dirs)[0])
        for said in ("state/a.md", "state/extra.md", "other/b.md"):
            self.assertIn(said, problems)


class OwnModulesTest(SlimCase):
    def test_the_sums_are_the_tools_own_whatever_directory_it_is_run_from(self):
        """`python -m` looks in the current directory first. Run from another checkout's
        root, a slim would do its sums with that checkout's modules and its bash with its
        own; here the other one's would drop nothing and approve everything."""
        elsewhere = self.root / "another-checkout"
        (elsewhere / "keel").mkdir(parents=True)
        (elsewhere / "keel" / "__init__.py").write_text("")
        (elsewhere / "keel" / "backupslim.py").write_text("raise SystemExit(0)\n")
        self.old_store(OLD)
        done = subprocess.run(["bash", str(TOOL), "slim", "--set", "keel", "--dry-run", "--json"], cwd=elsewhere,
                              env=self.env(), capture_output=True, text=True, timeout=300)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual([s["state"] for s in json.loads(done.stdout)["sets"]["keel"]["run"]], ["would-slim"])


class DispatchTest(SlimCase):
    def test_keel_backup_slim_reaches_the_tool_with_the_configs_store_and_every_flag(self):
        """r1.F15: `keel backup slim ...` through the launcher and `backup.main`, against the
        scratch store the config names, asserted on what the dry run says."""
        self.old_store()
        config = write_toml(self.live)
        with open(config, "a") as toml:
            toml.write(f'[backup]\nstore = "file:{self.store}"\nsets = ["keel"]\n')
        env = {k: v for k, v in self.env().items() if not k.startswith("KEEL_BACKUP_")}
        env.update(KEEL_CONFIG=str(config), KEEL_BACKUP_HOME=str(self.home),
                   KEEL_BACKUP_SLIM_DISK_FLOOR_MB="16")
        env.pop("KEEL_HOME")
        done = subprocess.run([sys.executable, str(ROOT / "bin" / "keel"), "backup", "slim", "--dry-run",
                               "--set", "keel", "--limit", "1"], env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn(f"[keel] {OLD}", done.stdout)
        self.assertIn("would drop", done.stdout)
        self.assertIn("keel: 1 of 2 snapshots examined", done.stdout)
        self.assertNotIn(NEW, done.stdout, "--limit 1 reached the tool")
        self.assertIn("nothing was written to the store", done.stdout)


if __name__ == "__main__":
    unittest.main()
