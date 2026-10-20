"""The code-moved restart: the head this process loaded, and what the restart waits for
(c-557, r-25).

The drain re-execs its whole process when HEAD moves (`drain.run`), between passes. Where the
roles share one process (`keel run --roles drain,serve,fetch`: an install's default), that is
the deck's restart too. Two things were wrong with it:

- NOBODY COULD SEE IT. `os.execv` keeps the pid and the process start time, so `ps` said a
  process had run since 09-25 while it had re-exec'd many times, and r-25 was filed on that
  reading. So the process says the head it LOADED: `state/drain.json` holds it for
  `keel doctor` (`drain.announce`).
- IT CUT A LIVE CONVERSATION. A connected conversation's pipes do not survive an exec. So
  the restart waits while this process holds a conversation or is opening one
  (`housetalk.Sessions.busy`), or is answering a house call or a deck action (`CALLS`), and says
  once what it waits for. Nothing bounds the wait but the conversation itself: the idle
  hold's reaper (`housetalk.Sessions.watch`) closes one he stopped talking to, and nothing
  automatic ends one he is in.

A deck that runs WITHOUT the drain in its process follows its checkout itself
(`serve.follow_code`, c-637), with the same wait read through `busy`; with the drain beside
it, it leaves the restart to the drain's pass. The fetch role on its own does the same
between its passes (`fetchloop.run`, c-742), reading `stamp` and `moved` here: alone in its
process it holds no conversation, so it waits for nothing but the pass it is in; beside
another role its own restart is off (`cli.role_run`).
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


class InFlight:
    """The house calls and the deck actions this process is answering right now, by kind."""

    def __init__(self):
        self.lock = threading.Lock()
        self.counts: dict[str, int] = {}

    @contextmanager
    def held(self, what: str):
        with self.lock:
            self.counts[what] = self.counts.get(what, 0) + 1
        try:
            yield
        finally:
            with self.lock:
                self.counts[what] -= 1
                if not self.counts[what]:
                    del self.counts[what]

    def busy(self) -> str:
        """"" when nothing is in flight, else what is, in words."""
        with self.lock:
            kinds = sorted(self.counts)
        return f"{' and '.join(kinds)} in flight" if kinds else ""


CALLS = InFlight()
HOUSE_CALL = "a house call"
# A deck action on its request thread (c-637 review): a clone under `setup.repo.clone` takes
# minutes, and an exec would cut it and leave the page with no answer.
DECK_ACTION = "a deck action"

# One drain per process, so one value each: the head it started on, and what a pending
# restart waits for ("" when none is pending).
_state = {"loaded": None, "waiting": "", "since": None}


def started(head: str | None) -> None:
    _state.update(loaded=head, waiting="", since=None)


def loaded() -> str | None:
    return _state["loaded"]


def waiting() -> str:
    return _state["waiting"]


def waiting_since() -> str | None:
    """When the pending restart began to wait, ISO; None when none is pending."""
    return _state["since"]


def busy() -> str:
    """What this process is doing that an exec would cut, or ""."""
    from keel.housetalk import SESSIONS
    return SESSIONS.busy() or CALLS.busy()


def due(moved: str = "code") -> tuple[bool, str | None]:
    """The code (or the config, `moved`) moved: whether to exec now, and a line for the log when the wait starts or
    what it waits for changes (one line per reason, never one per pass)."""
    reason = busy()
    if not reason:
        _state.update(waiting="", since=None)
        return True, None
    line = None if reason == _state["waiting"] else f"{moved} moved since start; the restart waits: {reason}"
    if not _state["since"]:
        _state["since"] = datetime.now().astimezone().isoformat(timespec="seconds")
    _state["waiting"] = reason
    return False, line


def stamp(cfg) -> tuple:
    """What a process runs on: its checkout's head, and its config file as it stands (change
    time and size). Either is None when it cannot be read."""
    from keel import merging     # noqa: PLC0415 - merging is heavy, and only a loop asks
    try:
        found = Path(cfg.source).stat() if cfg.source else None
    except OSError:
        found = None
    return merging.code_head(cfg.root), (found.st_mtime_ns, found.st_size) if found else None


def moved(cfg, started: tuple) -> str | None:
    """"code" or "config" when that moved since `started` (a `stamp`), else None. What
    cannot be read is unknown, and unknown is never moved (`merging.code_head`). The fetch
    role's loop asks between passes (`fetchloop.run`, c-742)."""
    head, config = stamp(cfg)
    if head and started[0] and head != started[0]:
        return "code"
    if config and started[1] and config != started[1]:
        return "config"
    return None


def announced(state_dir: Path) -> dict | None:
    """What the drain alive on THIS machine said in `state/drain.json` (`drain.announce`):
    `head` it loaded, and `waiting` and `since` while its restart waits. None when no drain
    is alive or it did not say a head (older code)."""
    try:
        said = json.loads((Path(state_dir) / "drain.json").read_text())
        os.kill(int(said["pid"]), 0)
    except PermissionError:
        pass
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not said.get("head"):
        return None
    return {"head": str(said["head"]), "waiting": str(said.get("waiting") or ""),
            "since": said.get("since")}
