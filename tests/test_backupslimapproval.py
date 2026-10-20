"""`keel backup slim`, the approval (c-724): a rewrite does what the dry run showed and
nothing else, and a snapshot slimmed under older rules is looked at again.

Runs the real `bin/keel-backup slim` on a scratch store (`tests/backupslimcase.py`); the
sums are `keel/backupslimapproval.py` and `keel/backupslimjournal.py`.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import unittest

from keel import backupslim
from tests.backupslimcase import (
    by_rule, DROPPED, KEPT, NEW, OLD, sha, SlimCase, TOOL)


class ApprovalTest(SlimCase):
    """r1.F2, r1.F6: the rewrite does what the dry run showed, and nothing it did not."""

    def approval(self) -> dict:
        return json.loads((self.home / "slim-approved.json").read_text())["sets"]["keel"]

    def test_a_bare_slim_rewrites_nothing_and_says_the_two_words(self):
        self.old_store(OLD)
        before = self.objects()
        done = self.tool("slim", "--set", "keel")
        self.assertNotEqual(done.returncode, 0)
        for word in ("--dry-run", "--approved"):
            self.assertIn(word, done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)

    def test_the_dry_run_writes_what_it_showed_beside_the_keys_and_not_in_the_store(self):
        self.old_store(OLD)
        before = self.objects()
        self.dry()
        self.assertEqual(self.objects(), before)
        entry = self.approval()[OLD]
        self.assertEqual((entry["md5"], entry["state"], entry["dropped_files"]),
                         (before[str(self.blob(OLD).relative_to(self.store))], "would-slim", len(DROPPED)))
        self.assertNotIn("live", entry)
        self.assertEqual({r["rule"]: (r["files"], r["bytes"]) for r in entry["rules"]}, by_rule())

    def test_a_snapshot_the_dry_run_has_not_shown_is_not_fetched_or_written(self):
        self.old_store()
        self.dry("--limit", "1")
        done = self.tool("slim", "--set", "keel", "--approved", "--json")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual([(s["id"], s["state"]) for s in json.loads(done.stdout)["sets"]["keel"]["run"]],
                         [(OLD, "slimmed"), (NEW, "unapproved")])
        self.assert_old(NEW)

    def test_a_rewrite_that_nothing_was_approved_for_is_a_failure_and_says_what_to_run(self):
        """r2.F8: `--approved` that rewrote nothing because the dry run showed none of it
        has not done what was asked, and a job that ran it must not read it as done."""
        self.old_store()
        before = self.objects()
        done = self.tool("slim", "--set", "keel", "--approved")
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("slim --dry-run --set keel", done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)

    def test_an_approval_file_that_does_not_parse_stops_the_rewrite(self):
        """r2.F8: a damaged file is not an empty one."""
        self.old_store()
        self.dry()
        path = self.home / "slim-approved.json"
        path.write_text(path.read_text()[:-40])
        before = self.objects()
        done = self.tool("slim", "--set", "keel", "--approved", "--json")
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["sets"]["keel"]["run"], [], "no snapshot was judged on it")
        self.assertIn(str(path), done.stderr)
        self.assertEqual(self.objects(), before)
        self.slim()                              # the dry run writes it afresh
        self.assert_slim(OLD)

    def test_an_object_that_changed_since_the_dry_run_is_refused(self):
        self.old_store(OLD)
        self.dry()
        tree = self.root / "old-tree"
        (tree / "state/cards/c-1/later.md").write_text("written after the dry run\n")
        self.publish(OLD, tree)
        before = self.objects()
        done = self.tool("slim", "--set", "keel", "--approved")
        self.assertIn("another object than the dry run read", done.stdout + done.stderr)
        self.assertIn("run the dry run again", done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)

    def test_a_plan_that_drops_more_than_the_dry_run_showed_is_refused(self):
        """The rules and the object are the same, and the scan would still drop more: here
        because the approval names fewer dropped files than the scan finds, which is how a
        scan gone wrong or a hand-edited approval looks. Nothing is written."""
        self.old_store(OLD)
        self.dry()
        path = self.home / "slim-approved.json"
        approved = json.loads(path.read_text())
        approved["sets"]["keel"][OLD]["dropped_files"] -= 1
        path.write_text(json.dumps(approved))
        before = self.objects()
        done = self.tool("slim", "--set", "keel", "--approved")
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("not what the dry run showed", done.stdout + done.stderr)
        self.assertEqual(self.objects(), before)

    def test_a_plan_that_drops_other_paths_with_the_same_sums_is_refused(self):
        """r2.F2: equal counts and bytes by rule are not the same files. The dry run records
        a digest of the dropped paths themselves and of the roots it found, and the rewrite
        compares them."""
        self.old_store(OLD)
        self.dry()
        path = self.home / "slim-approved.json"
        for key in ("paths_digest", "roots_digest"):
            with self.subTest(key=key):
                approved = json.loads(path.read_text())
                was = approved["sets"]["keel"][OLD][key]
                approved["sets"]["keel"][OLD][key] = sha(b"other paths, the same sums")
                path.write_text(json.dumps(approved))
                before = self.objects()
                done = self.tool("slim", "--set", "keel", "--approved")
                self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
                self.assertEqual(self.objects(), before)
                approved["sets"]["keel"][OLD][key] = was
                path.write_text(json.dumps(approved))
        self.assertEqual(self.tool("slim", "--set", "keel", "--approved").returncode, 0)
        self.assert_slim(OLD)

    def test_the_check_tells_two_drop_sets_of_equal_size_apart(self):
        where = self.root / "plans"
        where.mkdir()
        summary = {"dropped_files": 1, "dropped_dirs": 0, "dropped_bytes": 3, "nodes": [],
                   "rules": [{"rule": "*.log", "files": 1, "bytes": 3, "trees": 1}]}
        (where / "plan.json").write_text(json.dumps(summary))
        (where / "roots").write_text("state\n")
        (where / "rules").write_text("find\n")
        approval = where / "approved.json"

        def run(verb, dropped, *more):
            (where / "dropped.json").write_text(json.dumps({"files": [dropped], "dirs": []}))
            return backupslim.main([verb, "--file", str(approval), "--set", "keel", "--id", OLD,
                                    "--plan", str(where / "plan.json"), "--dropped", str(where / "dropped.json"),
                                    "--roots", str(where / "roots"), *more])

        self.assertEqual(run("approve", "state/a.log", "--md5", "m", "--bytes", "9", "--rules",
                             str(where / "rules"), "--at", "2026-09-01T00:00:00Z"), 0)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run("check", "state/a.log"), 0)
            self.assertEqual(run("check", "state/b.log"), 1, "another file of the same size, under the same rule")

    def test_a_root_added_since_the_dry_run_refuses_the_rewrite_before_anything_is_fetched(self):
        """r2.F2: what decides a drop is more than the find's own text. The roots function
        is in the digest too, so a root added between the reading and the rewrite stops
        the snapshot at the gate, where nothing has been fetched."""
        self.old_store(OLD)
        self.dry()
        before = self.objects()
        tool = self.changed_tool("  if [ -d state ]; then printf '%s\\n' state; fi\n",
                                 "  if [ -d state ]; then printf '%s\\n' state; fi\n"
                                 "  if [ -d odd ]; then printf '%s\\n' odd; fi\n")
        done = subprocess.run(["bash", str(tool), "slim", "--set", "keel", "--approved", "--json"],
                              env=self.env(), capture_output=True, text=True, timeout=300)
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        run = json.loads(done.stdout)["sets"]["keel"]["run"]
        self.assertEqual([(s["id"], s["state"]) for s in run], [(OLD, "refused")])
        self.assertIn("rules have changed", run[0]["note"])
        self.assertEqual(self.objects(), before)

    def test_the_roots_are_the_same_roots_in_whatever_order_a_shell_lists_them(self):
        """r3.F7: the roots come from a glob, and a glob's order is the locale's."""
        where = self.root / "plans"
        where.mkdir()
        (where / "plan.json").write_text(json.dumps({"dropped_files": 0, "dropped_dirs": 0, "dropped_bytes": 0}))
        (where / "dropped.json").write_text(json.dumps({"files": [], "dirs": []}))
        (where / "rules").write_text("find\n")
        approval = where / "approved.json"

        def run(verb, roots, *more):
            (where / "roots").write_text(roots)
            return backupslim.main([verb, "--file", str(approval), "--set", "keel", "--id", OLD,
                                    "--plan", str(where / "plan.json"), "--dropped", str(where / "dropped.json"),
                                    "--roots", str(where / "roots"), *more])

        self.assertEqual(run("approve", "segments/b/data\nsegments/A/data\nstate\n", "--md5", "m", "--bytes", "9",
                             "--rules", str(where / "rules"), "--at", "2026-09-01T00:00:00Z"), 0)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run("check", "state\nsegments/A/data\nsegments/b/data\n"), 0)
            self.assertEqual(run("check", "state\nsegments/A/data\n"), 1, "a root fewer is still a difference")

    def test_the_rules_digest_does_not_depend_on_which_bash_runs_the_tool(self):
        """r3.F7: the digest is of the functions as the tool's file writes them, not as one
        bash prints them back. Another bash on the PATH once turned every slimmed snapshot
        into one slimmed under older rules, to be fetched and read again."""
        found = {}
        for path in ("/bin/bash", "/opt/homebrew/bin/bash", "/usr/local/bin/bash", shutil.which("bash")):
            if path and os.path.exists(path):
                version = subprocess.run([path, "-c", "echo $BASH_VERSION"], capture_output=True, text=True).stdout.strip()
                found.setdefault(version, path)
        if len(found) < 2:
            self.skipTest(f"one bash on this machine ({', '.join(found) or 'none found'}), so there is nothing to compare")
        self.old_store(OLD)
        digests = {}
        for version, path in found.items():
            done = subprocess.run([path, str(TOOL), "slim", "--set", "keel", "--dry-run"], env=self.env(),
                                  capture_output=True, text=True, timeout=300)
            self.assertEqual(done.returncode, 0, f"bash {version}: " + done.stdout + done.stderr)
            digests[version] = self.approval()[OLD]["rules_digest"]
        self.assertEqual(len(set(digests.values())), 1, digests)

    def test_live_git_is_an_unknown_argument(self):
        """c-752: the live tree is no longer asked anything, so the flag that asked it is
        gone, and a run told it reads nothing and writes nothing."""
        self.old_store(OLD)
        done = self.tool("slim", "--set", "keel", "--dry-run", "--live-git")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("unknown argument: --live-git", done.stdout + done.stderr)
        self.assertFalse((self.home / "slim-approved.json").exists())

    def refused(self, tool=TOOL) -> str:
        """The rewrite refuses the one snapshot and writes nothing; why, in its words."""
        before = self.objects()
        done = subprocess.run(["bash", str(tool), "slim", "--set", "keel", "--approved", "--json"],
                              env=self.env(), capture_output=True, text=True, timeout=300)
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        run = json.loads(done.stdout)["sets"]["keel"]["run"]
        self.assertEqual([(s["id"], s["state"]) for s in run], [(OLD, "refused")])
        self.assertEqual(self.objects(), before)
        return run[0]["note"]

    def test_an_approval_that_names_trees_on_the_live_trees_word_is_refused(self):
        """An approval file from before c-752 may name directories to treat as checkouts.
        Nothing plants them any more, so the rewrite could not do what that dry run showed:
        it refuses the snapshot and asks for a new dry run, whatever else the entry says."""
        self.old_store(OLD)
        self.dry()
        path = self.home / "slim-approved.json"
        data = json.loads(path.read_text())
        data["sets"]["keel"][OLD]["live"] = ["state/cards/c-1/out"]
        path.write_text(json.dumps(data))
        note = self.refused()
        self.assertIn("the live tree", note)
        self.assertIn("run the dry run again", note)

    def test_an_approval_written_under_the_scratch_checkout_rule_is_refused(self):
        """The approval files that exist were written while the scan dropped a directory of
        a card's scratch that held `.git`. That rule's text is part of what decides a drop,
        so every one of them is refused at the gate for the rules having changed."""
        self.old_store(OLD)
        before_c752 = self.changed_tool(
            "       -o \\( -path 'state/cards/*/scratch' ! -path 'state/cards/*/*/scratch' -type d \\) \\\n",
            "       -o \\( -path 'state/cards/*/scratch/*' ! -path 'state/cards/*/scratch/*/*' -type d \\\n"
            "             -exec sh -c 'test -e \"$1/.git\"' _ {} \\; \\) \\\n")
        shown = subprocess.run(["bash", str(before_c752), "slim", "--set", "keel", "--dry-run", "--json"],
                               env=self.env(), capture_output=True, text=True, timeout=300)
        self.assertEqual(shown.returncode, 0, shown.stdout + shown.stderr)
        self.assertEqual(self.approval()[OLD]["state"], "would-slim")
        self.assertIn("rules have changed", self.refused())


class OlderRulesTest(SlimCase):
    """r2.F6: a snapshot slimmed once is looked at again when what decides a drop has
    changed since. The journal keeps the digest each was slimmed under."""

    def aged(self) -> None:
        """The journal as a slim under older rules left it."""
        path = self.store / "sets" / "keel" / "slim.json"
        data = json.loads(path.read_text())
        for entry in data["done"].values():
            entry["rules_digest"] = sha(b"the rules as they were")
        path.write_text(json.dumps(data))

    def test_a_snapshot_slimmed_under_other_rules_is_examined_again_and_said(self):
        self.old_store(OLD)
        self.slim()
        self.assertEqual(self.dry()["sets"]["keel"]["examined"], 0, "slim under today's rules: not read again")
        self.aged()
        shown = self.tool("slim", "--set", "keel", "--dry-run")
        self.assertIn("1 slimmed under older rules", shown.stdout)
        again = self.dry()["sets"]["keel"]
        self.assertEqual((again["examined"], again["older_rules"], [s["state"] for s in again["run"]]),
                         (1, 1, ["nothing"]))

    def test_one_found_slim_under_todays_rules_too_keeps_its_way_back(self):
        """Nothing more to drop: the entry takes today's digest and keeps what vouches for
        the kept old archive, so a restore still goes through."""
        self.old_store(OLD)
        self.slim()
        self.aged()
        self.slim()
        self.assertEqual(self.dry()["sets"]["keel"]["examined"], 0)
        done = self.tool("slim", "--restore", OLD, "--set", "keel")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assert_old(OLD)

    def test_a_second_rewrite_waits_for_the_first_ones_old_archive_to_be_purged(self):
        """A rule added since drops more. The archive the first rewrite replaced is still
        kept, and it is never written over: the snapshot is left with the purge named, and
        is rewritten once that archive is gone."""
        self.old_store(OLD)
        self.slim()
        kept, was = self.kept_old(), self.snapshots()
        tool = self.changed_tool("         ! -name 'merged-tests.log' \\\n",
                                 "         ! -name 'merged-tests.log' ! -name 'evidence.log' \\\n")

        def run(*argv):
            return subprocess.run(["bash", str(tool), "slim", "--set", "keel", *argv], env=self.env(),
                                  capture_output=True, text=True, timeout=300)

        self.assertIn("1 slimmed under older rules", run("--dry-run").stdout)
        left = run("--approved")
        self.assertIn(f"slim --purge --id {OLD} --set keel", left.stdout + left.stderr)
        self.assertEqual((self.kept_old(), self.snapshots()), (kept, was))
        self.assertEqual(run("--purge", "--id", OLD).returncode, 0)
        done = run("--approved")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        files, _dirs = self.unpack(OLD)
        self.assertEqual(set(files), set(KEPT) - {"state/cards/c-1/evidence.log"} | {"state/board.db"})


if __name__ == "__main__":
    unittest.main()
