"""The gateway restarts on its own new code, and only when it is quiet (c-538, r-14).

WHY. The drain and the deck notice that main moved and restart themselves; this process did
not, so a deploy that changed `voice/` left the old gateway answering until someone
restarted it by hand (dev.keel.voice ran from 09-24 through c-523's deploy on 09-26).

HOW. At start the watch notes the stamp of the paths the gateway runs on
(`refresh.GATEWAY_PATHS` in `keel/refresh.py`, which is the list and says why each is on
it, as HEAD has them). Every `CHECK_SECONDS` it reads the stamp again. Once it moved, it asks the
gateway what is still going on (`Gateway.busy`): a turn in flight, a voice hold (the pin),
a held half sentence, an open conversation, a capture waiting for its refine. While any of
those is true it waits, saying why once. When none is, it asks the server to shut down; the
process ends as it would on a stop (a kept-alive Harbor process is dropped on the way out)
and its service, systemd's `Restart=always` or launchd's `KeepAlive`, starts it again on the
new code. On one machine the checkout moves by its own deploy, and this watch sees it.

A stamp that cannot be read is unknown, and unknown never restarts anything: the drain's rule.
An unknown start takes the first stamp a later look can read, and that look moves nothing.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from . import drawing                                                  # noqa: F401
# `drawing` has put this package's own checkout on the path.
from keel import refresh                                               # noqa: E402

CHECK_SECONDS = 30.0


class CodeWatch:
    """One per serving process, started by `server.serve` and never by a test's gateway."""

    def __init__(self, root: Path, busy, stop, log, interval: float = CHECK_SECONDS,
                 read=None):
        self.read = read or (lambda: refresh.stamp(root, refresh.GATEWAY_PATHS))
        self.busy = busy          # () -> "" when quiet, else what it is still doing
        self.stop = stop          # () -> None: ask the server to shut down
        self.log = log
        self.interval = interval
        self.started = self.read()
        self.restarting = False
        self._waiting_for = ""
        self._done = threading.Event()

    def moved(self) -> bool:
        """A stamp unreadable at start is taken from the first look that can read one, and
        that look is never a move (review r1.F2: a start whose stamp could not be read must
        not leave the watch off for the life of the process)."""
        now = self.read()
        if not self.started:
            self.started = now
            return False
        return bool(now and now != self.started)

    def check(self) -> str:
        """One look: "" when the code has not moved, "waiting" while the gateway is busy,
        "restart" once it asked the server to stop."""
        if self.restarting or not self.moved():
            return "restart" if self.restarting else ""
        why = self.busy()
        if why:
            if why != self._waiting_for:
                self.log(f"[{now()}] voice: its code moved since start; restarting once quiet ({why})")
            self._waiting_for = why
            return "waiting"
        self.log(f"[{now()}] voice: its code moved since start and nothing is going on; restarting on it")
        self.restarting = True
        self.stop()
        return "restart"

    def _loop(self) -> None:
        while not self._done.wait(self.interval):
            try:
                if self.check() == "restart":
                    return
            except Exception as exc:                                    # noqa: BLE001
                # A watch that raised must not take the gateway with it.
                self.log(f"[{now()}] voice: the code watch raised: {exc.__class__.__name__}: {exc}")

    def start(self) -> "CodeWatch":
        threading.Thread(target=self._loop, name="voice-codewatch", daemon=True).start()
        return self

    def close(self) -> None:
        self._done.set()


def stamp_line(watch: CodeWatch) -> str:
    """What the startup log says about it."""
    return ("  code watch: restarts on new gateway code once quiet" if watch.started
            else "  code watch: no stamp for the gateway's code yet; it takes the first it can read")


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")
