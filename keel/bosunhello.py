"""Whether the user has said anything in Bosun's session (c-678, the first run's Meet Bosun).

The first-run design hands the uncertain parts of setup to a conversation in Bosun's own
session, so the page has to know one thing about that session: the user has been in it. It
knows from the harness's own record, the session's transcript, never from a terminal pane:
`said(cfg)` is true once a transcript of a session Bosun has had (`state/console.json`: the
one it runs now and the ones its history names) holds a user message that is the user's own.

Not the user's: what Keel typed to start or resume it (`consolehandoff.KEEL_PROMPTS`), what
the harness put there (a reminder, a slash-command echo, a compaction summary, a meta
record, which is how a relayed drain message is recorded), a tool's result, and anything in
a subagent's thread. The rule is `consolehandoff.said`'s, which the handoff note uses for the
last messages its user sent.

It is asked on every state, so it reads each transcript once and then only what was added:
per file it keeps how far it read and whether it found one. A line caught half written is
read on the next ask. Found is kept for the life of the process, and once a hello is found
for a console no transcript is looked for again (review F11); `forget` drops it (the suite).

A transcript this user cannot open, or a folder of sessions it cannot list (a Bosun under
another Unix user keeps both to itself), is not "no hello": `hidden(cfg)` says Keel cannot
see into the session, and the step says that rather than ask for a hello it could never
find (review F20).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from keel import console, consolehandoff
from keel.config import Config

_read: dict[str, int] = {}       # transcript -> the offset read up to (whole lines only)
_found: set[str] = set()         # transcripts that hold a message of the user's
_said: set[str] = set()          # consoles (their config dir) where a hello was found
_closed: set[str] = set()        # transcripts this user could not open


def forget() -> None:
    _read.clear()
    _found.clear()
    _said.clear()
    _closed.clear()


def own(record) -> bool:
    """One transcript record is a message the user typed."""
    if not isinstance(record, dict) or record.get("type") != "user":
        return False
    if record.get("isSidechain") or record.get("isMeta") or record.get("isCompactSummary"):
        return False
    message = record.get("message") if isinstance(record.get("message"), dict) else {}
    text = consolehandoff.text_of(message.get("content"))
    return bool(text) and not text.startswith(consolehandoff.HARNESS_WRAPPERS) \
        and text not in consolehandoff.KEEL_PROMPTS


def sessions(cfg: Config) -> list[str]:
    """The session Bosun runs now, then the earlier ones its history names, newest first."""
    data = console.read_state(cfg)
    named = [data.get("session_id")] + [row.get("session") for row in reversed(data.get("history") or [])
                                        if isinstance(row, dict)]
    return list(dict.fromkeys(one for one in named if one))


def scan(path: Path) -> bool:
    """Read what was added to one transcript since the last ask; true once it holds a
    message of the user's."""
    key = str(path)
    if key in _found:
        return True
    try:
        with open(path, "rb") as handle:
            handle.seek(_read.get(key, 0))
            added = handle.read()
    except PermissionError:
        _closed.add(key)
        return False
    except OSError:
        return False
    _closed.discard(key)
    whole = added[:added.rfind(b"\n") + 1]          # a line still being written waits
    _read[key] = _read.get(key, 0) + len(whole)
    for line in whole.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if own(record):
            _found.add(key)
            return True
    return False


def said(cfg: Config) -> bool:
    """The user has typed into a session of Bosun's. False where there is no console."""
    if console.SPACE not in cfg.spaces:
        return False
    where = console.config_dir(cfg)
    if str(where) in _said:
        return True
    for session in sessions(cfg):
        path = console.transcript_of(where, session)
        if path is not None and scan(path):
            _said.add(str(where))
            return True
    return False


def hidden(cfg: Config) -> bool:
    """Keel cannot see into Bosun's session from here: no hello was found, and a transcript
    of a session Bosun has had could not be opened, or the folder its sessions are kept in
    cannot be listed by this user. False where Bosun never started."""
    if console.SPACE not in cfg.spaces or said(cfg) or not sessions(cfg):
        return False
    where = console.config_dir(cfg)
    projects = where / "projects"
    if projects.exists() and not os.access(projects, os.R_OK | os.X_OK):
        return True
    paths = [console.transcript_of(where, session) for session in sessions(cfg)]
    return any(path is not None and str(path) in _closed for path in paths)
