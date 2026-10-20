"""A house's background jobs: seeing them while it lives, ending them when it is stopped.

A background Bash call (`run_in_background`) runs in a shell the harness starts as the
leader of its own process session, so everything that shell starts shares its session id.
`claude stop` ends the Claude session and deliberately leaves those shells running: c-526's
wait loop (`while pgrep -f ...`, which matched itself) outlived its stop until it was killed
by hand. So every path that stops a house comes through `stop` here (c-534), which ends
them, and a test holds every caller of `harness.stop` to that.

Everything is read from the harness's own job record, `<config dir>/jobs/<short id>/`:

- `state.json`, while the session lives: `inFlight.tasks` counts what is running and `fan`
  lists each task (`id`, `kind`, `label`, `startedAt` in epoch ms). A `shell` in the fan is
  a background Bash call.
- `adopt.json`, written when the session exits: `shells`, each with its `taskId`, `pid`,
  `startTimeTicks` (the kernel's start time of that pid, in clock ticks since boot, the
  22nd field of `/proc/<pid>/stat`) and `command`.

By pid, never by pattern. A recorded pid is ended only once it is PROVEN to be the same
process: on Linux its start ticks must equal the record's; elsewhere its `ps -o lstart`
must fall within a few seconds of the task's `startedAt`. A pid that cannot be proven is
left alone and said so, because a reused pid is somebody else's process.

Not called by voice's pause (`housetalk.stop_house`): that stop hands the session to a
conversation and wakes the same session afterwards, so its jobs are live work.
"""

import json
import os
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

from keel import harness

JOBS_DIR = "jobs"
STATE_FILE = "state.json"
ADOPT_FILE = "adopt.json"
SHELL_KIND = "shell"
# The listing's `state` for a session in a turn. NOT its `status`: probed 2026-09-26 on
# 2.1.283, a session idle at its prompt with a background shell still running is listed
# `status: busy`, `state: done`, which is exactly the house c-526 was.
WORKING = "working"
# How long a stop waits for the harness to write `adopt.json`, and only when the session had
# a job in flight: c-526's was written 48 ms after its state said stopped.
ADOPT_WAIT = 10.0
ADOPT_PAUSE = 0.2
# SIGTERM first, then SIGKILL for whatever is still there after the grace.
GRACE = 3.0
GRACE_PAUSE = 0.1
# How far `ps -o lstart` (whole seconds) may sit from the task's `startedAt` off Linux.
START_SLACK = 5.0
LABEL_CHARS = 120
PROC = Path("/proc")

ENDED, GONE, UNPROVEN, SURVIVED = "ended", "gone", "unproven", "survived"


# ----- the record -----

def config_root(config_dir) -> Path:
    """The config dir a session of `config_dir` lives in; None is the caller's own."""
    if config_dir is not None:
        return Path(config_dir).expanduser()
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or harness.DEFAULT_CONFIG_DIR).expanduser()


def job_dir(config_dir, bg_id: str) -> Path:
    return config_root(config_dir) / JOBS_DIR / bg_id


def read(path: Path) -> dict:
    """A JSON object from the harness's record, or {} for anything else: the files are the
    harness's and undocumented, so a missing or changed one means nothing is known."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def fan(config_dir, bg_id: str) -> list[dict]:
    """Every background shell the session's state lists, running or not."""
    tasks = read(job_dir(config_dir, bg_id) / STATE_FILE).get("fan") or []
    return [task for task in tasks if isinstance(task, dict) and task.get("kind") == SHELL_KIND]


def running(config_dir, bg_id: str) -> list[dict]:
    """The background shells a LIVE session has in flight: `{id, label, started_at}`, the
    last in epoch ms. Empty for a stopped session, whose state keeps its fan but no longer
    counts anything in flight."""
    if not bg_id:
        return []
    state = read(job_dir(config_dir, bg_id) / STATE_FILE)
    if not (state.get("inFlight") or {}).get("tasks"):
        return []
    return [{"id": task.get("id"), "label": (task.get("label") or "")[:LABEL_CHARS],
             "started_at": task.get("startedAt")} for task in fan(config_dir, bg_id)]


BUSY_STATUS = "busy"
IDLE_STATUS = "idle"


def working(row: dict | None) -> bool:
    """THE rule for "is the listed house in a turn", which landing, resume, rotation, the deck
    and Bosun's read all ask (r-26): a listed PROCESS (`has_process`) whose `state` is
    `working`. Never its `status`, which says busy for an idle house whose background job
    still runs (c-535: c-532's review session sat 46 minutes on a polling loop, and its
    landing refused it as working). Never a row with no process either: probed 2026-09-29 on
    2.1.284, c-561's superseded session 735f0cab stayed listed `state: working` with no
    `status` and no `pid` for two days, and every landing behind it was refused. A row with
    no `state` at all, from a harness that does not write one, falls back to `status`, so a
    house mid-turn is never taken for idle. And never a row whose `status` says `idle`: seen
    2026-09-30 on 2.1.285 (the c-600 sandbox run, house e4d96586), a house whose turn had
    ended (its Stop fired, its log at the prompt, `tempo: idle` in its state.json) stayed
    listed `state: working` for as long as it was watched, and every tap for it was held.
    `idle` is the one status that cannot hide a turn: a turn in progress lists `busy`."""
    if not row:
        return False
    if "state" in row:
        return row.get("state") == WORKING and has_process(row) and row.get("status") != IDLE_STATUS
    return row.get("status") == BUSY_STATUS


def has_process(row: dict | None) -> bool:
    """Does the listing name a process for this row: every live background row carries its
    `pid` (2.1.284). A row from a harness that writes no `state` is taken as live, as before."""
    if not row:
        return False
    return row.get("pid") is not None or "state" not in row


def ghost(row: dict | None) -> bool:
    """A row the harness lists as working with no process behind it (r-26): not working by
    `working`, and what `keel doctor` names (`keel/ghosts.py`)."""
    return bool(row) and row.get("state") == WORKING and not has_process(row)


def row_said(row: dict) -> str:
    """The listed row in words, for a refusal or a note: which session, and what the harness
    says of it, so nobody has to run `claude agents` to see what stopped a move."""
    session = row.get("sessionId") or "unknown"
    bg_id = row.get("id") or session[:8]
    return (f"{bg_id} (session {session}): state {row.get('state') or 'none'}, "
            f"status {row.get('status') or 'none'}, pid {row.get('pid') or 'none'}")


def of_row(config_dir, row: dict | None) -> list[dict]:
    """`running` for a house the harness lists outside a turn (`state` not `working`): an
    idle house with a job of its own still going, which is what the deck draws and the
    drain notes. Its `status` says busy while the job runs, so it is not asked."""
    if not row or row.get("state") == WORKING:
        return []
    return running(config_dir, row.get("id") or (row.get("sessionId") or "")[:8])


def survivors(config_dir, bg_id: str, since_ms: int) -> list[dict] | None:
    """The shells `adopt.json` says outlived an exit at or after `since_ms`, or None when
    there is no such record yet."""
    adopt = read(job_dir(config_dir, bg_id) / ADOPT_FILE)
    written = adopt.get("writtenAtMs")
    if not isinstance(written, (int, float)) or written < since_ms:
        return None
    return [shell for shell in adopt.get("shells") or [] if isinstance(shell, dict)]


def await_survivors(config_dir, bg_id: str, since_ms: int, wait: float) -> list[dict]:
    """`survivors`, polled for up to `wait` seconds; none when the record never came."""
    deadline = time.monotonic() + wait
    while True:
        found = survivors(config_dir, bg_id, since_ms)
        if found is not None:
            return found
        if time.monotonic() >= deadline:
            return []
        time.sleep(ADOPT_PAUSE)


# ----- the process -----

def start_ticks(pid: int) -> int | None:
    """The kernel's start time of `pid` in clock ticks since boot, or None where there is no
    `/proc` or no such process. The command field can hold spaces and parentheses, so the
    fields are counted from the LAST `)`."""
    try:
        text = (PROC / str(pid) / "stat").read_text()
    except OSError:
        return None
    fields = text[text.rfind(")") + 2:].split()
    try:
        return int(fields[19])          # field 22 overall; fields[0] here is field 3
    except (IndexError, ValueError):
        return None


def started_epoch(pid: int) -> float | None:
    """When `pid` started, in epoch seconds, from `ps -o lstart` (whole seconds, local
    time), or None when ps cannot say."""
    try:
        done = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="], capture_output=True,
                              text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    text = " ".join(done.stdout.split())
    try:
        return datetime.strptime(text, "%a %b %d %H:%M:%S %Y").timestamp()
    except ValueError:
        return None


def alive(pid: int) -> bool:
    """The process exists and is not a zombie: a killed one whose parent has not reaped it
    yet is over, whatever `kill -0` says."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    try:
        text = (PROC / str(pid) / "stat").read_text()
    except OSError:
        return True                     # no /proc here, or it went between the two looks
    return text[text.rfind(")") + 2:][:1] != "Z"


def proven(shell: dict, started_ms) -> bool | None:
    """True when the live `pid` is the recorded shell, False when it is provably another
    process, None when this machine cannot tell."""
    pid = shell.get("pid")
    if PROC.is_dir():
        ticks = start_ticks(pid)
        recorded = shell.get("startTimeTicks") or shell.get("procStart")
        try:
            return ticks is not None and ticks == int(recorded)
        except (TypeError, ValueError):
            return None
    began = started_epoch(pid)
    if began is None or not isinstance(started_ms, (int, float)):
        return None
    return abs(began - started_ms / 1000) <= START_SLACK


def all_pids() -> list[int]:
    if PROC.is_dir():
        return [int(name) for name in os.listdir(PROC) if name.isdigit()]
    try:
        done = subprocess.run(["ps", "-A", "-o", "pid="], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(word) for word in done.stdout.split() if word.isdigit()]


def session_of(pid: int) -> int | None:
    try:
        return os.getsid(pid)
    except OSError:
        return None


def in_session(sid: int) -> list[int]:
    """Every live process whose session id is `sid`."""
    return [pid for pid in all_pids() if session_of(pid) == sid and alive(pid)]


def members(leader: int) -> list[int]:
    """Every process in the session `leader` leads (the shell and all it started), found by
    session id; just the leader when it does not lead one."""
    if session_of(leader) != leader:
        return [leader] if alive(leader) else []
    return in_session(leader)


def signal_all(pids: list[int], sig: int) -> None:
    for pid in pids:
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def end_session(leader: int, grace: float = GRACE) -> bool:
    """SIGTERM every process of the session, SIGKILL whatever is left after `grace`; True
    when none is left. The session id outlives its leader, so the members are looked up
    again by that id rather than remembered."""
    signal_all(members(leader), signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not in_session(leader) and not alive(leader):
            return True
        time.sleep(GRACE_PAUSE)
    signal_all(in_session(leader) + ([leader] if alive(leader) else []), signal.SIGKILL)
    time.sleep(GRACE_PAUSE)
    return not in_session(leader) and not alive(leader)


def end(shell: dict, started_ms, grace: float = GRACE) -> dict:
    """End one recorded shell if it is still that shell: `{task, pid, label, outcome}`."""
    pid = shell.get("pid")
    out = {"task": shell.get("taskId"), "pid": pid,
           "label": (shell.get("description") or shell.get("command") or "")[:LABEL_CHARS]}
    if not isinstance(pid, int) or pid <= 1 or not alive(pid):
        return dict(out, outcome=GONE)
    if not proven(shell, started_ms):
        return dict(out, outcome=UNPROVEN if alive(pid) else GONE)
    return dict(out, outcome=ENDED if end_session(pid, grace) else SURVIVED)


# ----- the stop -----

def stop(bg_id: str, config_dir, claude_stop, wait: float = ADOPT_WAIT,
         grace: float = GRACE) -> list[dict]:
    """`claude stop <bg_id>`, then end every background shell it left running. Returns one
    `end` answer per recorded shell; a failed stop raises `harness.HarnessError` and ends
    nothing. The wait for `adopt.json` is spent only when the session had a job in flight.

    `claude_stop` is the caller's own `harness.stop`, passed rather than imported here: a
    test replaces a module's `harness` with a fake, and the stop has to be that fake's."""
    in_flight = bool(running(config_dir, bg_id))
    started = {task.get("id"): task.get("startedAt") for task in fan(config_dir, bg_id)}
    since_ms = int(time.time() * 1000)
    claude_stop(bg_id, config_dir)
    shells = await_survivors(config_dir, bg_id, since_ms, wait if in_flight else 0)
    return [end(shell, started.get(shell.get("taskId")), grace) for shell in shells]


def said(ended: list[dict]) -> str:
    """What a stop did to the jobs, for the card's note: "" when there were none to end."""
    parts = []
    for job in ended:
        what = f"background job {job['task']} (pid {job['pid']})"
        if job["outcome"] == ENDED:
            parts.append(f"ended its {what}")
        elif job["outcome"] == UNPROVEN:
            parts.append(f"left {what} running: that pid could not be proven to be the job")
        elif job["outcome"] == SURVIVED:
            parts.append(f"could not end {what}: it outlived SIGKILL")
    return "; ".join(parts)


def stopped(bg_id: str, ended: list[dict]) -> str:
    """`session <id> stopped`, and what the stop did to its jobs."""
    tail = said(ended)
    return f"{bg_id} stopped" + (f"; {tail}" if tail else "")


# ----- the drain's note -----

IDLE_MARK = "idle with its background job"


def noted(board, card_id: str, task_id: str) -> bool:
    marker = f"{IDLE_MARK} {task_id}"
    return any(event["kind"] == "note" and marker in (event["text"] or "")
               for event in board.events(card_id))


def note_idle(board, card: dict, config_dir, row: dict | None) -> int:
    """Note once per job, on the card, that its house is idle while that job still runs.
    Returns how many notes it wrote."""
    count = 0
    for job in of_row(config_dir, row):
        if not job["id"] or noted(board, card["id"], job["id"]):
            continue
        since = ""
        if isinstance(job["started_at"], (int, float)):
            since = " since " + datetime.fromtimestamp(job["started_at"] / 1000).astimezone() \
                .isoformat(timespec="minutes")
        board.note(card["id"], f"{IDLE_MARK} {job['id']} still running{since}: {job['label']}", "drain")
        count += 1
    return count
