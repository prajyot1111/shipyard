"""What the talker's own output says about it, and whether it is healthy.

`keel/talker.py` runs the server; this module watches it. Three things, all of them there
because the talker sat alive and useless for two days with nothing saying so (c-444):

THE OUTPUT IS READ IN CHUNKS, NOT LINES. Server mode's "Enable Remote Control? (y/n)" ends
with no newline, and the old relay iterated `child.stdout` by line, so the prompt never
reached the log and no detector built on that loop could ever have fired. `Relay.feed`
takes whatever bytes arrived, echoes them at once, and scans a short rolling tail so a
session URL split across two reads is still found.

A PROMPT IS A FAULT, NEVER A QUESTION TO ANSWER. A trailing "(y/n)" with no session URL
seen this run writes `state/talker.fault` and a FAULT line in the log. Nothing is ever
typed into it: the child's stdin is closed (`talker.spawn`), and consent is asserted in
the config file before launch (`keel/claudejson.py`), which is where it belongs.

EVERY RUN IS SCOPED BY ITS START STAMP. `state/talker-started` is written when `start`
launches the server, and a session file older than it is a previous run's. Without it a
talker with no session showed the last run's dead URL as if it were current.

`verdict` is pure: facts in, a state and its reason out. `talker.health` gathers the facts.
"""

import re
import time
from pathlib import Path

from keel import atomicfile

STARTED = "talker-started"   # state file: the epoch the current run was launched at
FAULT = "talker.fault"       # state file: why the current run cannot serve, one line
NO_SESSION_AFTER = 60        # seconds a running server may go without a session URL
STAMP_SLACK = 1.0            # seconds: the stamp and the session file are two clocks' readings
TAIL = 512                   # bytes of output kept across reads for matching
PROMPT_RE = re.compile(r"(Enable Remote Control\?[^\n]*|[^\n]*\(y/n\))\s*$", re.IGNORECASE)
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


# ----- the stamp and the fault file -----

def started_path(state_dir: Path) -> Path:
    return state_dir / STARTED


def fault_path(state_dir: Path) -> Path:
    return state_dir / FAULT


def mark_start(state_dir: Path, now: float | None = None) -> float:
    """A new run begins: stamp it, and forget the last run's fault."""
    when = time.time() if now is None else now
    atomicfile.write_text(started_path(state_dir), f"{when:.3f}\n")
    fault_path(state_dir).unlink(missing_ok=True)
    return when


def started_at(state_dir: Path) -> float | None:
    try:
        return float(started_path(state_dir).read_text().strip())
    except (OSError, ValueError):
        return None


def write_fault(state_dir: Path, text: str) -> None:
    atomicfile.write_text(fault_path(state_dir), text.strip() + "\n")


def read_fault(state_dir: Path) -> str:
    try:
        return fault_path(state_dir).read_text().strip()
    except OSError:
        return ""


# ----- the relay -----

class Relay:
    """Scans the server's output as it arrives. `feed` returns what it found in this chunk:
    a session id (the caller records it) and a prompt (the caller faults on it)."""

    def __init__(self, session_re: re.Pattern):
        self.session_re = session_re
        self.tail = ""
        self.session: str | None = None   # the newest session id seen THIS run

    def feed(self, chunk: bytes) -> dict:
        text = self.tail + ANSI_RE.sub("", chunk.decode("utf-8", "replace"))
        found = {}
        # Only an id something follows: one that runs to the end of this read may be the
        # first half of a longer one, and the tail carries it into the next read.
        ids = [m.group(1) for m in self.session_re.finditer(text) if m.end() < len(text)]
        if ids and ids[-1] != self.session:
            self.session = found["session"] = ids[-1]
        prompt = PROMPT_RE.search(text)
        if prompt and self.session is None:
            found["prompt"] = " ".join(prompt.group(1).split())
        self.tail = text[-TAIL:]
        return found


# ----- the verdict -----

def verdict(installed: bool, running: bool, now: float, started: float | None,
            session_at: float | None, session: str, fault: str) -> dict:
    """The talker's state from its facts. `ok` is False only for a fault: a talker that is
    not installed on this machine is not one, and neither is a server still inside its
    first minute. `session_at` is the session file's mtime (None when there is none)."""
    current = (bool(session) and session_at is not None
               and (started is None or session_at >= started - STAMP_SLACK))
    if not running:
        if not installed:
            return {"state": "not-installed", "ok": True, "reason": "no talker service on this machine"}
        return {"state": "stopped", "ok": False,
                "reason": "installed here and not running" + (f": {fault}" if fault else "")}
    if fault:
        return {"state": "fault", "ok": False, "reason": fault}
    if current:
        return {"state": "serving", "ok": True, "reason": f"session {session}", "session": session}
    age = None if started is None else now - started
    if age is not None and age < NO_SESSION_AFTER:
        return {"state": "starting", "ok": True, "reason": f"started {int(age)}s ago, no session yet"}
    stale = f" (the recorded {session} is from an earlier run)" if session else ""
    since = f"{int(age)}s" if age is not None else "an unknown time"
    return {"state": "no-session", "ok": False,
            "reason": f"running for {since} with no session URL{stale}"}
