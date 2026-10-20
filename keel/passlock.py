"""One drain pass at a time per install (c-734 fix check; docs/atlas/30-drain.md, "The pass").

A tell asks for a pass of its own (`pausewake.ask_pass`, `keel drain --once`), beside the
loop's pass on its clock, so two passes could overlap, or stack when taps come fast. Every
pass (`drain.once`, the loop's included) holds an `fcntl.flock` on `<state>/drain-pass.lock`
for the whole pass.

- **An unscoped pass** (the loop's, a tell's) does not wait: one that finds the lock held
  does nothing and says so in the log, and the loop simply runs on its next tick.
- **A card-scoped pass** (`keel drain --once --card <id>`: Retry, create-and-start) is a
  tap waiting on its answer, so it never skips silently: it WAITS for the lock up to
  `WAIT_SECONDS`, then runs, and when the wait runs out it raises `Busy`, which the CLI
  turns into a non-zero exit and a sentence the tap reports as a failure. With `--no-wait`
  (Approve outcome's landing, which only nudges the drain) it skips at once instead.

A kick's carry (`drain.carry_pass`) is not a pass and takes no part in this: it has its own
lock. The lock is the kernel's, so it goes with the process that held it: a pass that dies
leaves nothing to clean up. A lock that cannot be used (the file cannot be opened, or
`flock` answers with an error other than "held", such as ENOLCK or ENOTSUP) lets the pass
run unguarded, as before this lock, rather than stop the drain, and says so once a process.
"""

from __future__ import annotations

import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path

LOCK_NAME = "drain-pass.lock"
SKIPPED = "pass skipped: another pass holds the pass lock"
# How long a card-scoped pass waits for the lock. The tap that runs it waits this long on
# top of the deck's usual wait for a keel command (`actions.CARD_PASS_SECONDS` is
# WAIT_SECONDS plus `actions.SLOW_SECONDS`, 180 s), so a pass that waited still has the
# whole budget a pass had before the lock (r2.F2). 90 s is half that usual wait: a pass
# under way (the log shows the long ones, `drain.pass_line`) mostly ends within it.
WAIT_SECONDS = 90
STEP_SECONDS = 0.2
UNUSABLE = "the pass lock cannot be used ({why}); passes run unguarded"
said: set[str] = set()      # what this process already logged about an unusable lock


class Busy(RuntimeError):
    """A card-scoped pass's wait for the lock ran out."""


def busy_sentence(card: str, waited: int) -> str:
    return (f"the drain pass for {card} did not run: another pass held the pass lock for "
            f"{waited}s; try again")


def path(cfg) -> Path:
    return Path(cfg.state_dir) / LOCK_NAME


def opened(cfg) -> int | str:
    """The lock file's descriptor, or why it cannot be opened."""
    try:
        where = path(cfg)
        where.parent.mkdir(parents=True, exist_ok=True)
        return os.open(where, os.O_RDWR | os.O_CREAT, 0o600)
    except (OSError, TypeError, AttributeError) as error:
        return f"{type(error).__name__}: {error}"


def take(fd: int) -> bool | str:
    """True when taken, False when another holds it, else why the lock is unusable."""
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    except OSError as error:
        return f"flock: {error.strerror or error}"
    return True


def unusable(why: str, say) -> bool:
    """Say once a process that the lock is unusable; the pass runs (True)."""
    if say is not None and why not in said:
        said.add(why)
        say(UNUSABLE.format(why=why))
    return True


def acquire(fd: int, wait: float, say) -> bool:
    """Take the lock, trying until `wait` seconds have passed (0: once)."""
    deadline = time.monotonic() + wait
    while True:
        got = take(fd)
        if isinstance(got, str):
            return unusable(got, say)
        if got or time.monotonic() >= deadline:
            return got
        time.sleep(STEP_SECONDS)


@contextmanager
def held(cfg, wait: float = 0, say=None):
    """Yields True for the pass that holds the lock (or runs unguarded), False when another
    pass held it for all of `wait`. `say` logs a line. Released when the block ends."""
    fd = opened(cfg)
    if isinstance(fd, str):
        yield unusable(fd, say)
        return
    try:
        yield acquire(fd, wait, say)
    finally:
        os.close(fd)        # closing the descriptor releases a lock it held
