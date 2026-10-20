"""The fetch role's loop: `keel fetch` and `keel run --roles fetch` (c-742).

`keel/fetch.py` is what a pass does (the fetchers, the asks, the recurring cards); this is
what runs the passes. Every fetcher on start and then hourly; every minute in between, the
fetchers whose inputs moved, then the asks, then the recurring cards. A pass's exception is
logged and never leaves the loop.

Two things a role that is a process of its own needs, and that the old engine's one process
gave it for free:

- **It says what its first pass will file** (`say_first_pass`): the lines of
  `keel/fetchpreview.py`, in `fetch.log`, before the first pass of every start.
- **It follows its code and its config** (`follow_moves`): between passes, never during
  one, it execs onto a moved checkout or config file (`restart.stamp`, `restart.moved`).
  `follow` is off wherever another role shares the process (`cli.role_run`): the drain's
  restart, or the deck's, is then the whole process's, and each waits for what an exec
  would cut.
"""

from __future__ import annotations

import os
import sys
import time
import traceback

from keel import config as config_module
from keel import fetch, restart
from keel.config import Config


def say_first_pass(cfg: Config) -> None:
    """Before the first pass of a start: what it will file, one log line each, so a role
    that starts after a long gap has said so before a card appears. Never fails a start."""
    try:
        from keel import fetchpreview     # noqa: PLC0415 - only a start asks
        for line in fetchpreview.lines(cfg):
            fetch.log(cfg, f"first pass: {line}")
    except Exception:  # noqa: BLE001 - saying it is not the pass
        fetch.log(cfg, "first pass: could not be previewed:\n" + traceback.format_exc().strip())


def follow_moves(cfg: Config, started: tuple) -> tuple:
    """Exec onto moved code or a moved config (`restart.moved`), between passes, so no
    fetcher is cut: on its own the fetch role has no drain beside it to restart the process.
    A config that does not load is said once and the running one kept. Returns the stamp to
    compare with next."""
    moved = restart.moved(cfg, started)
    if moved == "config":
        try:
            config_module.load(cfg.source, ensure=False)
        except Exception as error:  # noqa: BLE001 - anything load raises keeps the running config
            fetch.log(cfg, f"config moved but does not load: {error}; keeping the running one")
            return restart.stamp(cfg)
    if moved:
        fetch.log(cfg, f"{moved} moved since start; restarting between passes")
        os.execv(sys.executable, [sys.executable, *sys.argv])
    return started


# The lock a pass files under. A segment's name never begins with a dot (`fetch.segments`),
# so this is never a fetcher's lock.
FILING = ".filing"


def file_cards(cfg: Config, segment: str | None = None) -> tuple[dict, dict, str]:
    """What a pass files after its fetchers: the asks' cards, then the recurring cards (none
    on a run narrowed to one segment). Returns (asks, recurring, why it filed nothing: ""
    when it filed, else the reason, which `keel fetch --once` says and exits 1 on, r2.F3).

    UNDER ONE LOCK (r1.F3), the fetchers' own protocol (`fetch.take_lock`). Filing reads and
    then writes: a recurring key is read as due and then its card created, a segment's asks
    are listed and then moved one by one. Two roles on one install (the service, and a
    `shipyard fetch` someone left running) interleaved there filed a recurring card twice
    and split one segment's asks over two errand cards. A pass that finds the lock held
    files nothing and says so: the other role is filing the same things."""
    lock = fetch.lock_path(cfg, FILING)
    state = fetch.take_lock(lock)
    if state != "taken":
        why = "another fetch role is filing" if state == "held" else f"its lock {lock} is unusable"
        fetch.log(cfg, f"filing skipped: {why}")
        return {}, {}, why
    try:
        created = fetch.asks(cfg, segment)
        return created, fetch.due_cards(cfg) if segment is None else {}, ""
    finally:
        fetch.release_lock(lock)


def run(cfg: Config, segment: str | None = None, follow: bool = True) -> None:
    """The loop. One log line per segment run, and a pass's exception never leaves it."""
    started = restart.stamp(cfg)
    fetch.log(cfg, f"fetch up: segments={cfg.segments_dir} locks={cfg.fetch_locks} "
                   f"full={fetch.FULL_SECONDS}s pass={fetch.PASS_SECONDS}s")
    if segment is None:
        say_first_pass(cfg)
    due = 0.0
    while True:
        if follow:
            started = follow_moves(cfg, started)
        try:
            full = time.monotonic() >= due
            fetch.once(cfg, segment, changed_only=not full)
            if full:
                due = time.monotonic() + fetch.FULL_SECONDS
            file_cards(cfg, segment)
        except Exception:  # noqa: BLE001 - the loop is the thing that must not die
            fetch.log(cfg, "pass failed:\n" + traceback.format_exc().strip())
        time.sleep(fetch.PASS_SECONDS)
