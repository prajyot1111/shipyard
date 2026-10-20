"""c-718, the drain's step for stacked cards (`keel/stackwatch.py`), through `upkeep`, with the
harness faked at its own boundary (`house.harness`, the listing and the relay), never above it:

- a parent dropped blocks its stacked card once, with one sentence, and not again; a parent
  done and archived later is landed, not dropped (r1.F5);
- a parent landed: the pack's `ship <id> restack` once for a card that records a change, then
  its idle house told once in its own session, one command per repo with that repo's head,
  each stopping before the rebase when the fork point cannot be found (r1.F3);
- a working house waits; a house at shipping that is not running is noted, never woken; a
  house that EXITS between the pass's snapshot and the tell is not resumed and not marked
  told, and is told on a later pass (r1.F4);
- a restack that fails backs off and, after `RESTACK_TRIES`, blocks once (r1.F11);
- a parent's branch that moved past what the card's worktree holds is told once per head,
  and the pass's room for turns is counted once (r1.F10).

Nothing here stops a session: the fake records every resume and stop, and none happens.
"""

import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
import unittest
from pathlib import Path
from unittest import mock

from keel import house, stacking, stackwatch
from keel.board import SHIPPING_OPTION, Board
from tests.helpers import SESSION, FakeHarness, make_config

PARENT_BRANCH = "feature/st-7/the-parser"
HEAD = "a" * 40
SHIP = """#!/bin/sh
echo "$@" >> "{log}"
if [ -f "{fail}" ]; then echo "the code host said no" >&2; exit 1; fi
if [ -f "{fail}.declined" ]; then
  echo '{{"base": "release", "retargeted": [], "kept": [{{"repo": "api", "pr": 50, "why": "it is declined", "state": "declined"}}]}}'
  exit 0
fi
echo '{{"base": "release", "retargeted": [{{"repo": "api", "pr": 50, "from": "{parent}", "to": "release"}}], "kept": []}}'
"""
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@x"]


def pack(directory: Path, log: Path, fail: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pack.toml").write_text('name = "work"\nversion = "1"\ndescription = "a pack"\n'
                                         '[adapter]\nspaces = ["work"]\n[capabilities]\nstacks = true\n')
    for verb, body in (("worktree", "#!/bin/sh\nexit 1\n"),
                       ("ship", SHIP.format(log=log, fail=fail, parent=PARENT_BRANCH))):
        (directory / verb).write_text(body)
        (directory / verb).chmod(0o755)
    return directory


def row(status="idle"):
    return {"id": SESSION[:8], "sessionId": SESSION, "name": "c", "pid": 4242,
            "state": "working" if status == "busy" else "done", "status": status, "kind": "bg"}


def sh(*args, cwd=None):
    return subprocess.run(list(args), cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class StackWatchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.log, self.failing = self.dir / "ship.log", self.dir / "fail"
        self.cfg = make_config(self.dir)
        self.cfg.spaces["work"].adapter_dir = pack(self.dir / "adapters" / "work", self.log, self.failing)
        self.board = Board(self.dir / "board.db", stacks=self.cfg.stacking)
        self.parent = self.board.create("work", "the parent", repo="api")
        self.board.set_fields(self.parent, {"options": {"branch": PARENT_BRANCH, "pr": 41}}, "cli")
        self.child = self.board.create("work", "the child", repo="api", after=self.parent)
        self.board.set_fields(self.child, {"options": {stacking.OPTION: stacking.STACKED}}, "human")
        self.fake = FakeHarness()
        self.fake.relay_answer = "sent"
        for patch in (mock.patch.object(house, "harness", self.fake),
                      mock.patch.object(house, "settings_for", lambda cfg, card: None)):
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        self.board.close()
        self.tmp.cleanup()

    def started(self, stage="building", pr=True, repo=None):
        self.board.conn.execute("UPDATE cards SET stage = ?, session_id = ? WHERE id = ?", (stage, SESSION, self.child))
        if repo:
            self.board.conn.execute("UPDATE cards SET repo = ? WHERE id IN (?, ?)", (repo, self.child, self.parent))
        if pr:
            self.board.set_fields(self.child, {"options": {"pr": 50, "branch": "feature/st-8/child"}}, "cli")

    def land(self, heads=None):
        self.board.set_fields(self.parent, {"options": {SHIPPING_OPTION: {"heads": heads or {"api": HEAD}}}}, "drain")
        self.board.conn.execute("UPDATE cards SET stage = 'done' WHERE id = ?", (self.parent,))

    def run_pass(self, rows=None, slots=3, live=None):
        """`rows` the pass's snapshot; `live` what the harness lists when asked again at the
        tell (the snapshot's rows unless a test says otherwise)."""
        snapshot = rows if rows is not None else [row()]
        self.fake.rows = list(snapshot if live is None else live)
        return stackwatch.upkeep(self.cfg, self.board, {"work"}, snapshot, slots)

    def notes(self):
        return [e["text"] for e in self.board.events(self.child) if e["kind"] == "note"]

    def restacks(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def told(self):
        folder = self.cfg.card_dir(self.child) / "told"
        return [path.read_text() for path in sorted(folder.glob("*.md"))] if folder.is_dir() else []


class DroppedTest(StackWatchCase):
    def test_a_dropped_parent_blocks_the_card_once(self):
        self.board.set_fields(self.parent, {"options": {"archived": True}}, "human")
        self.assertEqual(self.run_pass()["blocked"], 1)
        reason = self.board.get(self.child)["blocked_reason"]
        self.assertIn(f"{self.parent}, the card this one is stacked on, was dropped", reason)
        self.assertIn("options.stack=independent", reason)
        self.board.unblock(self.child, "human")
        self.assertEqual(self.run_pass()["blocked"], 0)
        self.assertIsNone(self.board.get(self.child)["blocked_reason"])

    def test_a_parent_that_merged_and_was_archived_is_landed(self):     # r1.F5
        self.started()
        self.land()
        self.board.set_fields(self.parent, {"options": {"archived": True}}, "human")
        said = self.run_pass()
        self.assertEqual((said["blocked"], said["restacked"], said["told"]), (0, 1, [self.child]))
        self.assertIsNone(self.board.get(self.child)["blocked_reason"])


class LandedTest(StackWatchCase):
    def test_landed_restacks_once_and_tells_the_idle_house_once(self):
        self.started()
        self.land()
        first = self.run_pass()
        self.assertEqual((first["restacked"], first["told"]), (1, [self.child]))
        self.assertEqual(self.restacks(), [f"{self.child} restack"])
        (prompt,) = self.told()
        self.assertIn("has merged into release", prompt)
        self.assertIn(f'fork=$(git merge-base HEAD {HEAD}) && test -n "$fork"', prompt)
        self.assertIn("--force-with-lease", prompt)
        again = self.run_pass()
        self.assertEqual((again["restacked"], again["told"], len(self.restacks()), len(self.told())), (0, [], 1, 1))
        self.assertEqual((self.fake.resumes, getattr(self.fake, "stops", [])), ([], []))

    def test_one_command_per_repo_with_that_repos_head(self):     # r1.F3
        other = "b" * 40
        self.started(repo="api,web")
        self.land({"api": HEAD, "web": other})
        self.run_pass()
        (prompt,) = self.told()
        lines = {line.split(":", 1)[0]: line for line in prompt.splitlines() if line.startswith("- ")}
        self.assertIn(f"fork=$(git merge-base HEAD {HEAD})", lines["- api"])
        self.assertIn(f"fork=$(git merge-base HEAD {other})", lines["- web"])
        self.assertNotIn(other, lines["- api"])

    def test_a_repo_the_parent_never_named_gets_no_line(self):     # c-772
        self.board.conn.execute("UPDATE cards SET repo = 'api,web' WHERE id = ?", (self.child,))
        self.started()
        self.land()
        self.run_pass()
        (prompt,) = self.told()
        lines = [line.split(":", 1)[0] for line in prompt.splitlines() if line.startswith("- ")]
        self.assertEqual(lines, ["- api"])
        self.assertNotIn("no pushed head", prompt)
        self.assertIn(stacking.OTHER_BASE, prompt)

    def test_a_repo_the_parent_named_and_never_pushed_still_says_so(self):     # c-772
        self.started(repo="api,web")
        self.land()
        self.run_pass()
        (prompt,) = self.told()
        lines = {line.split(":", 1)[0]: line for line in prompt.splitlines() if line.startswith("- ")}
        self.assertIn("no pushed head", lines["- web"])
        self.assertNotIn(stacking.OTHER_BASE, prompt)

    def test_a_head_the_worktree_lacks_stops_before_the_rebase_and_the_push(self):     # r1.F3
        origin, tree = self.dir / "origin.git", self.dir / "tree"
        sh("git", "init", "-q", "--bare", "-b", "release", str(origin))
        sh("git", "clone", "-q", str(origin), str(tree))
        (tree / "a").write_text("1\n")
        sh(*GIT, "-C", str(tree), "add", "a")
        sh(*GIT, "-C", str(tree), "commit", "-qm", "base")
        sh("git", "-C", str(tree), "push", "-q", "origin", "HEAD:release")
        sh("git", "-C", str(tree), "checkout", "-qb", "child")
        (tree / "b").write_text("2\n")
        sh(*GIT, "-C", str(tree), "commit", "-qam", "own", "--allow-empty")
        sh("git", "-C", str(tree), "push", "-qu", "origin", "child")
        before = sh("git", "-C", str(tree), "rev-parse", "HEAD")
        self.started()
        self.land({"api": "c" * 40})
        self.run_pass()
        command = self.told()[0].split("- api: `", 1)[1].split("`", 1)[0]
        done = subprocess.run(["sh", "-c", command], cwd=tree, capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(sh("git", "-C", str(tree), "rev-parse", "HEAD"), before)
        self.assertEqual(sh("git", "-C", str(origin), "rev-parse", "child"), before)

    def test_a_working_house_waits_and_is_told_later(self):
        self.started()
        self.land()
        self.assertEqual(self.run_pass(rows=[row("busy")])["told"], [])
        self.assertEqual((len(self.restacks()), self.told()), (1, []))
        self.assertEqual(self.run_pass()["told"], [self.child])

    def test_a_house_that_exited_since_the_snapshot_is_not_resumed(self):     # r1.F4
        self.started()
        self.land()
        resumed = []
        with mock.patch.object(house, "resume_card", lambda *a, **k: resumed.append(a[2]) or {}):
            said = self.run_pass(rows=[row()], live=[])   # listed in the snapshot, gone at the tell
        self.assertEqual((said["told"], resumed, self.fake.resumes, self.told()), ([], [], [], []))
        self.assertFalse(any("told the house" in note for note in self.notes()))
        self.assertEqual(self.run_pass()["told"], [self.child])

    def test_a_house_at_shipping_that_is_not_running_is_noted_never_woken(self):
        self.started(stage="shipping")
        self.land()
        said = self.run_pass(rows=[])
        self.assertEqual((said["told"], said["noted"], self.fake.resumes), ([], 1, []))
        self.assertTrue(any("only the user's Ship pushes" in note for note in self.notes()), self.notes())

    def test_a_card_that_never_started_needs_nothing(self):
        self.land()
        said = self.run_pass(rows=[])
        self.assertEqual((said["restacked"], said["noted"], self.restacks()), (0, 0, []))

    def test_a_failing_restack_backs_off_by_the_cards_own_marks_then_blocks_once(self):     # r1.F11, r2.F7
        self.started()
        self.land()
        self.failing.write_text("x")
        clock = [datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)]
        with mock.patch.object(self.board, "now", lambda: clock[0].isoformat()):
            self.run_pass()
            self.run_pass()                                   # backing off: not asked again
            self.assertEqual(len(self.restacks()), 1)
            failed = [m for m in stackwatch.marks(self.board, self.child, self.parent) if m["event"] == "restack-failed"]
            self.assertEqual([(m["n"], m["at"]) for m in failed], [(1, clock[0].isoformat())])
            for _ in range(stackwatch.RESTACK_TRIES - 1):
                clock[0] += timedelta(hours=1)
                self.run_pass()
        self.assertEqual(len(self.restacks()), stackwatch.RESTACK_TRIES)
        reason = self.board.get(self.child)["blocked_reason"]
        self.assertIn(f"failed {stackwatch.RESTACK_TRIES} times (", reason)
        self.run_pass()
        self.assertEqual(len(self.restacks()), stackwatch.RESTACK_TRIES)     # blocked: left for the owner
        self.assertFalse(hasattr(stackwatch, "FAILED"))                      # one store: the card

    def test_a_declined_change_blocks_once_and_holds_the_tell(self):     # r2.F6
        self.started()
        self.land()
        Path(str(self.failing) + ".declined").write_text("x")
        said = self.run_pass()
        self.assertEqual(said["told"], [])
        reason = self.board.get(self.child)["blocked_reason"]
        self.assertIn("#50 in api is no longer open (declined)", reason)
        self.assertIn("Reopen it, or open a new one", reason)
        self.assertEqual(self.run_pass()["told"], [])
        self.board.unblock(self.child, "human")
        self.assertEqual(self.run_pass()["told"], [self.child])
        self.assertIsNone(self.board.get(self.child)["blocked_reason"])


class ToldCommandTest(StackWatchCase):
    """r2.F10, r2.F3, r2.F4: the told command run as the house would, in real clones."""

    def setUp(self):
        super().setUp()
        self.origin, self.other, self.tree = self.dir / "origin.git", self.dir / "other", self.dir / "tree"
        sh("git", "init", "-q", "--bare", "-b", "release", str(self.origin))
        sh("git", "clone", "-q", str(self.origin), str(self.other))
        self.write(self.other, "a", "base")
        sh("git", "-C", str(self.other), "push", "-q", "origin", "HEAD:release")
        sh("git", "-C", str(self.other), "checkout", "-qb", PARENT_BRANCH)
        self.write(self.other, "p1", "the parent's first")
        self.parent_head = self.write(self.other, "p2", "the parent's second")
        sh("git", "-C", str(self.other), "push", "-q", "origin", PARENT_BRANCH)
        sh("git", "clone", "-q", "-b", PARENT_BRANCH, str(self.origin), str(self.tree))
        sh("git", "-C", str(self.tree), "checkout", "-qb", "child")
        self.write(self.tree, "c", "the child's own")
        sh("git", "-C", str(self.tree), "push", "-qu", "origin", "child")
        self.started()

    def write(self, tree, name, message):
        (tree / name).write_text(message + "\n")
        sh(*GIT, "-C", str(tree), "add", name)
        sh(*GIT, "-C", str(tree), "commit", "-qm", message)
        return sh("git", "-C", str(tree), "rev-parse", "HEAD")

    def merge_parent(self, squash=True, delete=False):
        sh("git", "-C", str(self.other), "fetch", "-q", "origin")
        sh("git", "-C", str(self.other), "checkout", "-q", "-B", "release", "origin/release")
        if squash:
            sh(*GIT, "-C", str(self.other), "merge", "-q", "--squash", f"origin/{PARENT_BRANCH}")
            sh(*GIT, "-C", str(self.other), "commit", "-qm", "the parent, squashed")
        else:
            sh(*GIT, "-C", str(self.other), "merge", "-q", "--no-ff", "-m", "merge the parent", f"origin/{PARENT_BRANCH}")
        sh("git", "-C", str(self.other), "push", "-q", "origin", "release")
        if delete:
            sh("git", "-C", str(self.other), "push", "-q", "origin", f":{PARENT_BRANCH}")

    def told_command(self):
        self.land({"api": self.parent_head})
        self.run_pass()
        return self.told()[0].split("- api: `", 1)[1].split("`\n", 1)[0]

    def run_it(self, command):
        return subprocess.run(["sh", "-c", command], cwd=self.tree, capture_output=True, text=True)

    def own_only(self):
        self.assertEqual(sh("git", "-C", str(self.origin), "log", "--format=%s", "release..child"), "the child's own")
        on_base = subprocess.run(["git", "-C", str(self.origin), "merge-base", "--is-ancestor", "release", "child"])
        self.assertEqual(on_base.returncode, 0)

    def test_after_a_squash_only_the_cards_own_commits_are_left(self):
        self.merge_parent(squash=True)
        done = self.run_it(self.told_command())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.own_only()

    def test_after_a_merge_commit_only_the_cards_own_commits_are_left(self):
        self.merge_parent(squash=False)
        done = self.run_it(self.told_command())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.own_only()

    def test_a_narrowed_refspec_with_a_stale_base_still_lands_on_the_fresh_base(self):     # r2.F3
        sh("git", "-C", str(self.tree), "fetch", "-q", "origin", "+refs/heads/release:refs/remotes/origin/release")
        sh("git", "-C", str(self.tree), "config", "remote.origin.fetch", "+refs/heads/child:refs/remotes/origin/child")
        self.merge_parent(squash=True)                                       # origin/release here is stale now
        done = self.run_it(self.told_command())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.own_only()

    def test_a_parent_head_the_clone_lacks_is_fetched_by_its_branch(self):     # r2.F4
        self.parent_head = self.write(self.other, "p3", "the parent's review fix")
        sh("git", "-C", str(self.other), "push", "-q", "origin", PARENT_BRANCH)
        self.merge_parent(squash=True)
        done = self.run_it(self.told_command())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.own_only()

    def test_a_parent_head_nobody_has_any_more_stops_before_the_rebase_and_says_what_to_do(self):     # r2.F4
        self.parent_head = self.write(self.other, "p3", "the parent's review fix")
        sh("git", "-C", str(self.other), "push", "-q", "origin", PARENT_BRANCH)
        self.merge_parent(squash=True, delete=True)
        sh("git", "-C", str(self.origin), "reflog", "expire", "--expire=now", "--all")
        sh("git", "-C", str(self.origin), "gc", "-q", "--prune=now")
        before = sh("git", "-C", str(self.tree), "rev-parse", "HEAD")
        command = self.told_command()
        self.assertIn("find the commit where your branch left it", self.told()[0])
        done = self.run_it(command)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(sh("git", "-C", str(self.tree), "rev-parse", "HEAD"), before)
        self.assertEqual(sh("git", "-C", str(self.origin), "rev-parse", "child"), before)


class MovedTest(StackWatchCase):
    def commit(self, tree, text):
        (tree / "f").write_text(text)
        sh(*GIT, "-C", str(tree), "add", "f")
        sh(*GIT, "-C", str(tree), "commit", "-qm", text)
        return sh("git", "-C", str(tree), "rev-parse", "HEAD")

    def test_a_parent_head_the_worktree_lacks_is_told_once(self):
        tree = self.dir / "tree"
        sh("git", "init", "-q", "-b", "main", str(tree))
        held = self.commit(tree, "1\n")
        self.started()
        self.board.set_fields(self.child, {"options": {"worktree": str(tree)}}, "cli")
        heads = lambda sha: self.board.set_fields(self.parent, {"options": {SHIPPING_OPTION: {"heads": {"api": sha}}}}, "drain")
        heads(held)
        self.assertEqual(self.run_pass()["told"], [])
        newer = self.commit(tree, "2\n")
        sh("git", "-C", str(tree), "reset", "-q", "--hard", held)
        heads(newer)
        self.assertEqual(self.run_pass()["told"], [self.child])
        self.assertIn(f"git merge origin/{PARENT_BRANCH}", self.told()[0])
        self.assertEqual(self.run_pass()["told"], [])

    def test_the_room_for_turns_is_counted_once(self):     # r1.F10
        trees = []
        for n in range(2):
            tree = self.dir / f"tree{n}"
            sh("git", "init", "-q", "-b", "main", str(tree))
            trees.append((tree, self.commit(tree, "1\n")))
        newer = self.commit(trees[0][0], "2\n")
        sh("git", "-C", str(trees[0][0]), "reset", "-q", "--hard", trees[0][1])
        self.started()
        self.board.set_fields(self.child, {"options": {"worktree": str(trees[0][0])}}, "cli")
        second = self.board.create("work", "the second", repo="api", after=self.parent)
        self.board.set_fields(second, {"options": {stacking.OPTION: stacking.STACKED}}, "human")
        self.board.conn.execute("UPDATE cards SET stage = 'building', session_id = ? WHERE id = ?", (SESSION, second))
        self.board.set_fields(second, {"options": {"worktree": str(trees[0][0])}}, "cli")
        self.board.set_fields(self.parent, {"options": {SHIPPING_OPTION: {"heads": {"api": newer}}}}, "drain")
        said = self.run_pass(slots=2)
        self.assertEqual(sorted(said["told"]), sorted([self.child, second]))


if __name__ == "__main__":
    unittest.main()
