"""What a house is doing now, as the harness wrote it down: its job record and the tail of
its transcript (c-599, the live strip; `keel/livestrip.py` draws the line from these).

Two files, both the harness's own and both read, never written:

- **The job record**, `<config dir>/jobs/<short id>/state.json`, which `keel/housejobs.py`
  already reads for the background shells. Probed 2026-09-30 on 2.1.285: besides `state`,
  `inFlight` and `fan` it carries `detail` (the harness's own one line of what the session
  is doing, "running baseline E2E card test on sandbox"), `updatedAt`, and `linkScanPath`,
  the transcript's path.
- **The transcript**, `<config dir>/projects/<cwd, every non-alphanumeric a dash>/<session
  uuid>.jsonl`, one JSON record per line (`tests/fixtures/harness/live-tail.jsonl` is real
  lines of one, trimmed). Only its LAST `TAIL_BYTES` are read: a house's transcript runs to
  megabytes and the strip wants its newest tool, its newest todo list, and when its turn
  began. Each record carries an ISO `timestamp`; an assistant record's `message.content`
  holds `tool_use` blocks (`name`, `input`) and a `stop_reason`; a user record is either a
  prompt (a string, or text blocks) or a `tool_result`; `system` with `subtype:
  turn_duration` closes a turn.

THE TURN IS HIS (c-604). Only a genuine prompt starts one: `origin.kind` is `human`, or the
record has no `origin` and is neither `isMeta` nor a harness injection. A `<task-notification>`
(`origin.kind: task-notification`), a subagent's hand-back (`origin.kind: peer`, `isMeta`) and
a tool's result do not: they used to restart the clock, so an idle house read `in turn 8m`. A
turn ends at `turn_duration`, at the assistant's final message (`stop_reason: end_turn`, no
tool use) or at an API error record. A house that goes on working after it (a notification or
a hand-back woke it) is in a NEW turn, clocked from that record, rather than reading `turn
ended` while it works; `[Request interrupted by user]` and a compaction summary start none. Probed 2026-09-30 on 2.1.285 in
the box's transcripts.

A tail is parsed again only when the file's size or mtime moved (`TAILS`): the strip asks
every few seconds while he watches, and a house that is thinking writes nothing. The memo
is this process's, keyed by path, and is not a store: losing it costs one read.

Facts only. Nothing here decides a house is stuck: a tool with no result yet is "running"
with its age, and the reader decides what an age means.
"""

import json
import os
import re
import threading
from pathlib import Path

from keel import housejobs, permpause

TAIL_BYTES = 256 * 1024
WHAT_CHARS = 90
TODO_CHARS = 70
TURN_END = "turn_duration"
# The tools whose input is a todo list the house keeps: TodoWrite rewrites the whole list;
# TaskCreate and TaskUpdate edit one task at a time (newer harnesses).
TODO_WRITE = "TodoWrite"
TASK_CREATE, TASK_UPDATE = "TaskCreate", "TaskUpdate"
DONE, ACTIVE = "completed", "in_progress"
# The input field that says best what a tool call is doing, per tool; anything else says
# its first short string.
WHAT_FIELDS = ("description", "command", "file_path", "pattern", "url", "query", "prompt",
               "subject", "path", "skill")
TAIL_MEMO_MAX = 64
# An MCP tool's input is whatever that server takes (a mail body, a document): only its name
# is shown. And a token-shaped literal is hidden even where no flag names it.
MCP_PREFIX = "mcp__"
TOKEN_LIKE = re.compile(r"\b(?:gh[pousr]_|github_pat_|sk-|xox[abprs]-|glpat-|AKIA)[\w-]{6,}|\b[A-Za-z0-9_\-]{32,}\b")
# User records the harness writes that are not a prompt: a hook's feedback, a command's
# output. They carry on the turn rather than start one.
INJECTED = ("<local-command", "<command-", "<bash-", "<task-notification", "[Request interrupted by user")
# The `origin.kind` of a prompt he (or Keel on his behalf) sent; any other origin is the
# harness's own (a task notification, a peer session's message or hand-back).
HUMAN_ORIGIN = "human"
END_TURN = "end_turn"
# The harness's own record of a failed model call ends the turn too (c-604 review).
API_ERROR_STOP = "stop_sequence"

_lock = threading.Lock()
TAILS: dict[str, tuple[int, int, dict]] = {}
PATHS: dict[str, Path] = {}     # session uuid -> its transcript, found once


# ----- the job record -----

def job(config_dir, bg_id: str) -> dict:
    """The harness's job record for this session, the fields the strip reads; {} when it
    has none (an older harness, or a session never started with `--bg`)."""
    if not bg_id:
        return {}
    state = housejobs.read(housejobs.job_dir(config_dir, bg_id) / housejobs.STATE_FILE)
    if not state:
        return {}
    fan = [task for task in state.get("fan") or [] if isinstance(task, dict)]
    in_flight = (state.get("inFlight") or {}).get("tasks") or 0
    return {"state": state.get("state"), "detail": safe(state.get("detail"), WHAT_CHARS * 2),
            "tempo": state.get("tempo"), "updated_at": state.get("updatedAt"),
            "in_flight": in_flight if isinstance(in_flight, int) else 0,
            "agents": [task_of(task) for task in fan if task.get("kind") == "agent"] if in_flight else [],
            "transcript": state.get("linkScanPath") if isinstance(state.get("linkScanPath"), str) else None}


def task_of(task: dict) -> dict:
    return {"label": safe(task.get("label"), TODO_CHARS), "started_at": task.get("startedAt")}


# ----- where the transcript is -----

def project_dir(cwd: str) -> str:
    """The harness's directory name for a working directory: every character that is not a
    letter or a digit becomes a dash (`/home/bosun/.claude/jobs` is
    `-home-bosun--claude-jobs`, as listed on the box)."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def transcript_path(config_dir, session_id: str, cwd: str | None, recorded: str | None = None) -> Path | None:
    """The session's transcript: the path the job record names, else the one its cwd
    gives, else the one file of that name in any project directory. None when none is."""
    if recorded and Path(recorded).is_file():
        return Path(recorded)
    if not session_id:
        return None
    with _lock:
        held = PATHS.get(session_id)
    if held is not None and held.is_file():
        return held
    projects = housejobs.config_root(config_dir) / "projects"
    found = None
    if cwd and (projects / project_dir(cwd) / f"{session_id}.jsonl").is_file():
        found = projects / project_dir(cwd) / f"{session_id}.jsonl"
    elif projects.is_dir():
        found = next(iter(sorted(projects.glob(f"*/{session_id}.jsonl"))), None)
    if found is not None:
        with _lock:
            if len(PATHS) >= TAIL_MEMO_MAX:
                PATHS.clear()
            PATHS[session_id] = found
    return found


# ----- the tail -----

def tail(path: Path | None) -> dict:
    """The tail's facts (`parse`), read again only when the file moved; {} for no file."""
    if path is None:
        return {}
    try:
        stat = os.stat(path)
    except OSError:
        return {}
    key = str(path)
    with _lock:
        held = TAILS.get(key)
    if held and held[0] == stat.st_size and held[1] == stat.st_mtime_ns:
        return held[2]
    facts = parse(read_tail(path, stat.st_size))
    if held and facts["wrote_at"] is None:
        # the tail held no whole record (one newest record bigger than TAIL_BYTES): what
        # was known stands, rather than an empty house
        facts = held[2]
    with _lock:
        if len(TAILS) >= TAIL_MEMO_MAX:
            TAILS.clear()           # a handful of houses; never a pile
        TAILS[key] = (stat.st_size, stat.st_mtime_ns, facts)
    return facts


def read_tail(path: Path, size: int) -> list[str]:
    """The whole lines in the last TAIL_BYTES: the first, cut in the middle, is dropped."""
    try:
        with open(path, "rb") as handle:
            start = max(0, size - TAIL_BYTES)
            handle.seek(start)
            raw = handle.read(size - start)
    except OSError:
        return []
    lines = raw.decode("utf-8", errors="replace").splitlines()
    return lines[1:] if start > 0 else lines


def parse(lines: list[str]) -> dict:
    """The newest facts in these transcript lines, oldest first:

    - `tool`: the newest tool call of the house itself (never a subagent's), `{name, what,
      at, done}`, `done` once its result is in the tail;
    - `todos`: the newest todo list, `{done, total, active}` (`active` is the task in hand);
    - `turn_at`: when the newest prompt reached it, `turn_ended_at` when that turn closed
      (None while it runs);
    - `wrote_at`: the newest record's time, whatever it was.
    """
    tool, results, tasks, todos = None, set(), {}, None
    turn_at = turn_ended_at = wrote_at = woke_at = None
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("isSidechain"):
            continue
        at = record.get("timestamp")
        wrote_at = at or wrote_at
        kind = record.get("type")
        if kind == "system" and record.get("subtype") == TURN_END:
            turn_ended_at = at
        elif kind == "user":
            content = (record.get("message") or {}).get("content")
            done = result_ids(content)
            if done:
                results |= done
            elif genuine(record, content):
                turn_at, turn_ended_at, woke_at = at, None, None
            elif turn_ended_at is not None and prompt(content):
                woke_at = at                # an injected record after the turn ended: it may wake it
        elif kind == "assistant":
            if turn_ended_at is not None and (woke_at or not final(record)):
                # WOKEN (c-604 review): a task notification or a hand-back after the turn
                # ended, and the house answering it: a NEW turn, clocked from the wake
                turn_at, turn_ended_at = woke_at or at, None
            woke_at = None
            if final(record):
                turn_ended_at = at
            for block in tool_uses(record):
                name = str(block.get("name") or "tool")
                tool = {"id": block.get("id"), "name": name, "what": what_of(block.get("input"), name), "at": at}
                todos = todo_step(block, tasks, todos)
    if tool is not None:
        tool["done"] = tool.pop("id") in results
    return {"tool": tool, "todos": todos, "turn_at": turn_at, "turn_ended_at": turn_ended_at,
            "wrote_at": wrote_at}


def result_ids(content) -> set:
    if not isinstance(content, list):
        return set()
    return {block.get("tool_use_id") for block in content
            if isinstance(block, dict) and block.get("type") == "tool_result"}


def genuine(record: dict, content) -> bool:
    """A user record that starts a turn: a prompt, sent by a person (or Keel for him), not
    one the harness injected."""
    if not prompt(content) or record.get("isMeta") or record.get("isCompactSummary") or injected(content):
        return False
    origin = record.get("origin")
    return not isinstance(origin, dict) or origin.get("kind") in (None, HUMAN_ORIGIN)


def final(record: dict) -> bool:
    """The assistant's last message of a turn: it stopped at end_turn with no tool in hand,
    or it is the harness's record of a failed call (`isApiErrorMessage`, `stop_sequence`)."""
    stop = (record.get("message") or {}).get("stop_reason")
    ended = stop == END_TURN or stop == API_ERROR_STOP or bool(record.get("isApiErrorMessage"))
    return ended and not tool_uses(record)


def prompt(content) -> bool:
    """A user record that is a prompt: text, not a tool's result."""
    if isinstance(content, str):
        return bool(content.strip())
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "text" for block in content)


def injected(content) -> bool:
    text = content if isinstance(content, str) else next(
        (b.get("text") or "" for b in content if isinstance(b, dict) and b.get("type") == "text"), "")
    return text.lstrip().startswith(INJECTED)


def tool_uses(record: dict) -> list[dict]:
    content = (record.get("message") or {}).get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict) and block.get("type") == "tool_use"]


def what_of(given, tool: str = "") -> str:
    """One short, redacted line of what a tool call is doing, from the input field that says
    it (a Bash call's description before its command). Nothing for an MCP tool, whose input
    is another server's body, and nothing from a field this list does not name."""
    if not isinstance(given, dict) or tool.startswith(MCP_PREFIX):
        return ""
    for name in WHAT_FIELDS:
        value = given.get(name)
        if isinstance(value, str) and value.strip():
            return safe(value, WHAT_CHARS) or ""
    return ""


def safe(text, limit: int) -> str | None:
    """`clip` after the secrets are hidden: the permission pause's rules
    (`permpause.redact`), then any token-shaped literal."""
    if not isinstance(text, str):
        return None
    return clip(TOKEN_LIKE.sub("[redacted]", permpause.redact(text)), limit)


def todo_step(block: dict, tasks: dict, todos: dict | None) -> dict | None:
    """The todo list after this tool call: a TodoWrite replaces it, a TaskCreate adds one
    (numbered in order, as the harness numbers them), a TaskUpdate sets one's status."""
    name, given = block.get("name"), block.get("input") or {}
    if not isinstance(given, dict):
        return todos
    if name == TODO_WRITE and isinstance(given.get("todos"), list):
        tasks.clear()
        for number, item in enumerate(given["todos"], 1):
            if isinstance(item, dict):
                tasks[str(number)] = {"status": item.get("status"),
                                      "text": safe(item.get("activeForm") or item.get("content"), TODO_CHARS)}
        return counted(tasks)
    if name == TASK_CREATE:
        tasks[str(len(tasks) + 1)] = {"status": "pending",
                                      "text": safe(given.get("activeForm") or given.get("subject"), TODO_CHARS)}
        return counted(tasks)
    if name == TASK_UPDATE and str(given.get("taskId")) in tasks:
        task = tasks[str(given["taskId"])]
        if given.get("status"):
            task["status"] = given["status"]
        return counted(tasks)
    return todos


def counted(tasks: dict) -> dict:
    items = [task for task in tasks.values() if task.get("status") != "deleted"]
    active = next((task["text"] for task in items if task.get("status") == ACTIVE and task.get("text")), None)
    return {"done": sum(1 for task in items if task.get("status") == DONE), "total": len(items),
            "active": clip(active, TODO_CHARS) if active else None}


def clip(text, limit: int) -> str | None:
    if not isinstance(text, str):
        return None
    line = " ".join(text.split())
    return line if len(line) <= limit else line[:limit - 1].rstrip() + "…"
