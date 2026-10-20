"""`bin/keel-backup`'s lock (c-750).

Two things start a snapshot by themselves now, the scheduled job and the drain
(`keel/backupdue.py`), and both can meet a dead run's lock on the same wake. The lock is a
symlink at the lock's name whose target is the holder's pid: made in one step, so it is
born signed, and a second `ln -s` at the name fails. A stale one is broken by renaming it
away. What the tool used before, a directory with a `pid` file inside, is still read where
one is found (a run of the old tool, across a deploy).

The races are made to happen: `meanwhile` gives another run one turn at a named point of
this one's. Every test runs the real tool's `snapshot` against a home, a store and a board
of its own, with no sets (`KEEL_BACKUP_SETS=""`): the run takes the lock, says the host
writes nothing and ends, so no archive is made and no store is read.
"""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from keel.board import Board
from tests.helpers import ROOT, write_toml

BACKUP = ROOT / "bin" / "keel-backup"
BREAK_AGE = 1800        # bin/keel-backup lock_take: a dead pid's lock younger than this is left
TOOLS = {"judged": ("date", "+%s"), "holding": ("date", "-u"), "renamed": ("mv", None),
         "linked": ("ln", "-sn")}


def dead_pid() -> int:
    """A pid that named a process a moment ago and names none now."""
    done = subprocess.Popen(["true"])
    done.wait()
    return done.pid


class LockCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.home = self.dir / "backup-home"
        self.home.mkdir()
        self.lock = self.home / ".lock"
        self.shim = self.dir / "shim"
        self.env = dict(os.environ, KEEL_HOME=str(ROOT), KEEL_CONFIG=str(write_toml(self.dir)),
                        KEEL_BACKUP_HOME=str(self.home), KEEL_BACKUP_SETS="",
                        KEEL_BACKUP_STORE=f"file:{self.dir / 'store'}")
        self.env.pop("KEEL_CARD", None)

    def left_by(self, pid: int, age: int, at: Path | None = None) -> None:
        """A lock naming `pid`, made `age` seconds ago. `at`: under another name."""
        lock = at or self.lock
        lock.symlink_to(str(pid))
        then = lock.lstat().st_mtime - age
        os.utime(lock, (then, then), follow_symlinks=False)

    def old_tool_left(self, pid: int | None, age: int, at: Path | None = None) -> None:
        """The old tool's lock: a directory with a `pid` file (None: without one)."""
        lock = at or self.lock
        lock.mkdir()
        if pid is not None:
            (lock / "pid").write_text(f"{pid}\n")
        then = lock.stat().st_mtime - age
        os.utime(lock, (then, then))

    def held_by(self) -> str:
        """Who the lock names now: its link's target, or a directory's pid file."""
        if self.lock.is_symlink():
            return os.readlink(self.lock)
        return (self.lock / "pid").read_text().strip()

    def meanwhile(self, does: str, at: str = "judged") -> str:
        """A PATH on which another run gets one turn, `does`, at one point of this one's run.
        The turn is a command of the test's own, first on PATH, that the tool calls at
        exactly that point; it does its real work and then lets the other run in:

        judged   in `lock_take`, after the lock found was judged and before it is broken
                 (`date +%s`, asked for the lock's age)
        renamed  in `lock_take`, after the lock was renamed away to be broken and before
                 the renamed one is read (the `mv` of the lock itself)
        linked   in `lock_take`, the instant after this run made its own lock (`ln -sn`)
        holding  once this run holds the lock and is at work (`date -u`, the first line it
                 says)

        Called once per point; each call returns the PATH with every turn set up so far."""
        tool, first = TOOLS[at]
        first = first or str(self.lock)
        self.shim.mkdir(exist_ok=True)
        (self.shim / tool).write_text(
            "#!/bin/sh\n"
            f'if [ "$1" = "{first}" ] && [ ! -e "{self.shim}/done-{at}" ]; then\n'
            f'  touch "{self.shim}/done-{at}"\n'
            f'  /bin/{tool} "$@"; code=$?\n'
            f"  {does}\n"
            "  exit $code\n"
            "fi\n"
            f'exec /bin/{tool} "$@"\n')
        (self.shim / tool).chmod(stat.S_IRWXU)
        return f"{self.shim}{os.pathsep}{self.env['PATH']}"

    def takes(self, pid: int, aged: bool = False) -> str:
        """For `meanwhile`: another run makes the lock its own. `aged`: and it is made to
        look years old, so only what the tool judged before that turn, and never the lock's
        age, can tell it from the stale one."""
        old = f'; touch -h -t 202001010000 "{self.lock}"' if aged else ""
        return f'rm -rf "{self.lock}"; /bin/ln -s {pid} "{self.lock}"{old}'

    def had_its_turn(self, *points: str) -> None:
        for at in points:
            self.assertTrue((self.shim / f"done-{at}").exists(),
                            f"the tool never reached {at!r}, where the other run waits: the test proves nothing")

    def snapshot(self, path: str | None = None) -> subprocess.CompletedProcess:
        env = dict(self.env, PATH=path) if path else self.env
        return subprocess.run(["bash", str(BACKUP), "snapshot"], env=env, capture_output=True,
                              text=True, timeout=60)

    def ran(self, done: subprocess.CompletedProcess) -> bool:
        """The run got past `lock_take` and did its (empty) work."""
        return "writes no backup sets" in done.stdout

    def cards(self) -> list[str]:
        """The titles of the cards on the board the tool files its notices on."""
        path = self.dir / "state" / "board.db"
        if not path.exists():
            return []
        with Board(path) as board:
            return [card["title"] for card in board.list_cards(stage=None)]

    def left_over(self) -> list[str]:
        return sorted(path.name for path in self.home.iterdir() if path.name.startswith(".lock"))


class TakeTest(LockCase):
    def test_the_lock_is_a_link_naming_the_run_while_it_works_and_is_gone_after(self):
        seen = self.dir / "seen"
        done = self.snapshot(path=self.meanwhile(
            f'[ -L "{self.lock}" ] && readlink "{self.lock}" > "{seen}"', at="holding"))
        self.had_its_turn("holding")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(self.ran(done))
        self.assertTrue(seen.read_text().strip().isdigit(), "the lock was not a link to a pid")
        self.assertEqual(self.left_over(), [])

    def test_a_live_runs_lock_is_never_broken_however_old(self):
        self.left_by(os.getpid(), age=BREAK_AGE * 4)
        done = self.snapshot()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("another run holds", done.stdout)
        self.assertFalse(self.ran(done))
        self.assertEqual(self.held_by(), str(os.getpid()))

    def test_a_lock_that_cannot_be_made_for_any_other_reason_is_a_failed_backup_and_says_so(self):
        """A full disk, a home that cannot be written: `ln` fails and the name is still
        free. That is not a lost race; the run fails and the board hears it."""
        self.shim.mkdir()
        (self.shim / "ln").write_text("#!/bin/sh\necho 'ln: No space left on device' >&2\nexit 1\n")
        (self.shim / "ln").chmod(stat.S_IRWXU)
        done = self.snapshot(path=f"{self.shim}{os.pathsep}{self.env['PATH']}")
        self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("could not make the lock", done.stderr)
        self.assertFalse(self.ran(done))
        self.assertEqual(self.cards(), ["Keel backup failed"])

    def test_a_lock_gone_the_instant_it_was_made_is_made_again(self):
        """A breaker that had judged an older lock renames this run's away and has not put
        it back yet: the name is free, so the run takes it again rather than standing down."""
        done = self.snapshot(path=self.meanwhile(f'rm -f "{self.lock}"', at="linked"))
        self.had_its_turn("linked")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(self.ran(done))
        self.assertEqual(self.left_over(), [])

    def test_a_lock_released_as_this_run_reached_for_it_is_taken_not_called_a_failure(self):
        """`ln` fails because a run holds the name, and by the time the tool looks, that run
        has finished and the name is free. That looks exactly like a full disk; one more
        try tells them apart."""
        self.left_by(os.getpid(), age=5)
        done = self.snapshot(path=self.meanwhile(f'rm -f "{self.lock}"', at="linked"))
        self.had_its_turn("linked")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(self.ran(done))
        self.assertEqual(self.cards(), [])
        self.assertEqual(self.left_over(), [])

    def test_a_run_stopped_the_instant_it_made_its_lock_takes_it_away_with_it(self):
        """TERM lands between the `ln` and the next line. The lock names this run, so the
        run removes it on its way out, whatever it had noted down about holding it."""
        done = self.snapshot(path=self.meanwhile("kill -TERM $PPID", at="linked"))
        self.had_its_turn("linked")
        self.assertEqual(done.returncode, -15, done.stdout + done.stderr)
        self.assertFalse(self.ran(done))
        self.assertEqual(self.left_over(), [], "a dead run's lock, good for half an hour of nothing")
        self.assertEqual(self.cards(), [], "a signal is not a failure worth a card")

    def test_a_run_removes_only_a_lock_that_still_names_it(self):
        """While this run worked, its lock was broken and another run took the name."""
        done = self.snapshot(path=self.meanwhile(self.takes(os.getpid()), at="holding"))
        self.had_its_turn("holding")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(self.ran(done))
        self.assertEqual(self.held_by(), str(os.getpid()), "this run removed a lock that was another's by then")


class StaleLockTest(LockCase):
    def test_a_dead_runs_old_lock_is_broken_and_the_run_goes_on_and_releases_it(self):
        self.left_by(dead_pid(), age=BREAK_AGE + 60)
        done = self.snapshot()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("broke a stale lock", done.stdout)
        self.assertTrue(self.ran(done))
        self.assertEqual(self.left_over(), [], "the lock, and the name it was renamed to, are gone")

    def test_a_dead_runs_young_lock_is_left_where_it_is(self):
        pid = dead_pid()
        self.left_by(pid, age=60)
        done = self.snapshot()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("leaving it for now", done.stdout)
        self.assertFalse(self.ran(done))
        self.assertEqual(self.held_by(), str(pid))

    def test_a_link_that_names_no_pid_is_a_dead_runs(self):
        self.lock.symlink_to("somewhere/else")
        then = self.lock.lstat().st_mtime - BREAK_AGE - 60
        os.utime(self.lock, (then, then), follow_symlinks=False)
        done = self.snapshot()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(self.ran(done))
        self.assertEqual(self.left_over(), [])

    def test_a_lock_a_live_run_took_while_this_one_went_to_break_it_is_put_back(self):
        """Two breakers. This one judges the dead run's lock; before it reaches the break
        the other has broken it and holds the name. This one renames THAT away, reads whom
        it names, and puts it back."""
        self.left_by(dead_pid(), age=BREAK_AGE + 60)
        done = self.snapshot(path=self.meanwhile(self.takes(os.getpid(), aged=True)))
        self.had_its_turn("judged")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("another run took the lock", done.stdout)
        self.assertFalse(self.ran(done))
        self.assertEqual(self.left_over(), [".lock"])
        self.assertEqual(self.held_by(), str(os.getpid()), "a live run's lock was taken from under it")

    def test_a_third_run_that_took_the_name_meanwhile_keeps_it(self):
        """Three runs. As above, and before the mistaken rename can be put back a third run
        has made the name its own. Nothing is put back over it or inside it."""
        self.left_by(dead_pid(), age=BREAK_AGE + 60)
        self.meanwhile(self.takes(os.getpid(), aged=True))
        path = self.meanwhile(f'/bin/ln -s {os.getppid()} "{self.lock}"', at="renamed")
        done = self.snapshot(path=path)
        self.had_its_turn("judged", "renamed")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("another run took the lock", done.stdout)
        self.assertFalse(self.ran(done))
        self.assertEqual(self.left_over(), [".lock"], "the renamed copy is gone")
        self.assertEqual(self.held_by(), str(os.getppid()))


class OldToolLockTest(LockCase):
    """A directory at the name is the old tool's lock, from a run across the deploy."""

    def test_a_live_old_run_is_stood_down_for_and_nothing_is_made_inside_its_lock(self):
        self.old_tool_left(os.getpid(), age=BREAK_AGE * 4)
        done = self.snapshot()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("another run holds", done.stdout)
        self.assertFalse(self.ran(done))
        self.assertEqual(sorted(path.name for path in self.lock.iterdir()), ["pid"],
                         "`ln -s` at a directory's name makes the link inside it")
        self.assertEqual(self.held_by(), str(os.getpid()))

    def test_a_dead_old_runs_stale_lock_is_broken_and_the_run_goes_on(self):
        self.old_tool_left(dead_pid(), age=BREAK_AGE + 60)
        done = self.snapshot()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("broke a stale lock", done.stdout)
        self.assertTrue(self.ran(done))
        self.assertEqual(self.left_over(), [])

    def test_a_dead_old_runs_young_lock_and_one_it_never_signed_are_left(self):
        for pid in (dead_pid(), None):
            with self.subTest(pid=pid):
                self.old_tool_left(pid, age=60)
                done = self.snapshot()
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                self.assertIn("leaving it for now", done.stdout)
                self.assertEqual(sorted(path.name for path in self.lock.iterdir()), ["pid"] if pid else [])
                for path in self.lock.iterdir():
                    path.unlink()
                self.lock.rmdir()


class LeftoverTest(LockCase):
    """A breaker killed between its rename and its next step leaves `.lock.stale.<pid>`."""

    def test_what_a_dead_breaker_left_is_swept_once_it_is_a_minute_old(self):
        self.left_by(dead_pid(), age=120, at=self.home / f".lock.stale.{dead_pid()}")
        self.old_tool_left(dead_pid(), age=120, at=self.home / f".lock.stale.{dead_pid()}")
        done = self.snapshot()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(self.ran(done))
        self.assertEqual(self.left_over(), [])

    def test_a_breaker_still_at_work_and_one_that_just_died_keep_theirs(self):
        self.left_by(dead_pid(), age=120, at=self.home / f".lock.stale.{os.getpid()}")
        young = dead_pid()
        self.left_by(dead_pid(), age=10, at=self.home / f".lock.stale.{young}")
        (self.home / ".lock.stale.notes").mkdir()
        done = self.snapshot()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.left_over(), sorted([f".lock.stale.{os.getpid()}", f".lock.stale.{young}",
                                                   ".lock.stale.notes"]))


if __name__ == "__main__":
    unittest.main()
