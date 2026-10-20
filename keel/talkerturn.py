"""The phone talker rotates when Harbor's memory moved, at a turn boundary (c-538, r-14).

A Remote Control conversation keeps the memory it started with, and nothing local shows
its turns (the transcript is empty, `claude agents` does not list it reliably), so the
drain could only rotate it by age. Two pieces make "at its next turn boundary" a fact:

- **The run's memory.** `state/talker-memory` is `{run, memory}`: the stamp of
  the memory had when this run began (`refresh.memory_stamp`: the install's memory repo
  once it holds the talker's memory, c-722, else `refresh.MEMORY_PATHS` on main). `do_fresh`
  writes it for the new run; a run with none takes the stamp there now, which is never a change.
- **The turn hooks.** `UserPromptSubmit` and `Stop` in Harbor's config dir run
  `keel talker turn start|over`, which writes the session's last event into
  `state/talker-turn` (`{run, sessions: {id: {event, at}}}`). Only the server's own process
  sets `KEEL_TALKER_TURNS` (`talker.spawn`; not `KEEL_TALKER`, the board's word for the
  talker), so a voice turn, which shares the config dir, exits the hook in the shell and
  pays nothing, and a `keel talker shell` thread is not counted.

`due` is the drain's reading: the stamp moved, every session of this run has ended its
turn, and no voice hold is live. A run whose hooks never fired has no record and is never
rotated for memory: the daily age reset still is. A turn that started and never stopped
(a killed server) holds the rotation until that reset too, never a guess that it is over.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from keel import atomicfile, refresh

MEMORY_FILE = "talker-memory"
TURN_FILE = "talker-turn"
ENV = "KEEL_TALKER_TURNS"
EVENTS = ("start", "over")
DUE = "Harbor's memory changed on main"


def read_json(path: Path) -> dict:
    try:
        found = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomicfile.write_text(path, json.dumps(doc, indent=1) + "\n")


def record_run(paths, run: int | None = None) -> str | None:
    """Write the memory stamp this run starts on; the stamp, or None when git cannot say."""
    memory = refresh.memory_stamp(paths.root, paths.install)
    if memory is not None:
        write_json(paths.state_dir / MEMORY_FILE,
                   {"run": paths.run_index() if run is None else run, "memory": memory})
    return memory


def run_memory(paths, record: bool = True) -> str | None:
    """The stamp this run started on, taking main's now for a run that has none (and, with
    `record`, writing it down: the drain's reading does, `status` does not)."""
    doc = read_json(paths.state_dir / MEMORY_FILE)
    if doc.get("run") == paths.run_index() and doc.get("memory"):
        return str(doc["memory"])
    return record_run(paths) if record else refresh.memory_stamp(paths.root, paths.install)


def hook(paths, event: str, payload: dict) -> None:
    """One turn event of a talker session, from its hook. Never raises: a hook that fails
    must not fail his turn."""
    session = str((payload or {}).get("session_id") or "")
    if event not in EVENTS or not session:
        return
    path = paths.state_dir / TURN_FILE
    try:
        doc = read_json(path)
        if doc.get("run") != paths.run_index():
            doc = {"run": paths.run_index(), "sessions": {}}
        doc.setdefault("sessions", {})[session] = {"event": event, "at": time.time()}
        write_json(path, doc)
    except OSError:
        pass


def between_turns(paths) -> bool:
    """True when this run's sessions have all ended their last turn; False when a turn is
    running or no hook of this run has said anything yet (unknown is never idle)."""
    doc = read_json(paths.state_dir / TURN_FILE)
    sessions = doc.get("sessions") if doc.get("run") == paths.run_index() else None
    if not sessions:
        return False
    return all((one or {}).get("event") == "over" for one in sessions.values())


def due(paths, holding: bool) -> str | None:
    """Why the talker should rotate for its memory now, or None."""
    started = run_memory(paths)
    memory = refresh.memory_stamp(paths.root, paths.install)
    if not (started and memory) or started == memory:
        return None
    if holding or not between_turns(paths):
        return None
    return DUE


def state(paths, holding: bool = False) -> str:
    """One line for `keel talker status`, which reads and writes nothing."""
    started = run_memory(paths, record=False)
    memory = refresh.memory_stamp(paths.root, paths.install)
    if not (started and memory):
        return "memory: unknown (no git stamp)"
    if started == memory:
        return "memory: this run has main's"
    if holding:
        return "memory: changed on main; rotates once no voice hold is live"
    if between_turns(paths):
        return "memory: changed on main; rotates on the drain's next pass"
    return "memory: changed on main; rotates at the next turn boundary its hooks report"
