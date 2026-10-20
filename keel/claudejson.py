"""A config dir's `.claude.json`: read it, write it whole, and assert the talker's consent.

EVERY WRITE IS ATOMIC. The file is Claude Code's own global config for that config dir, and
Keel rewrites it while `claude` processes are alive on the same dir: the Remote Control
server, and every voice turn the gateway runs under the talker's config. `Path.write_text`
truncates and then writes, so a `claude` reading in that window saw an empty or half file,
and one writing back its in-memory copy afterwards could reset the whole thing. That is one
of the two ways `remoteDialogSeen` could have vanished from the box's talker config
(c-444). So a write goes to a temporary file in the same directory, is flushed and
fsynced, gets mode 0600, and is renamed over the target: a reader sees the old file or the
new one, never part of either.

A FILE THAT DOES NOT PARSE IS NEVER WRITTEN OVER. It still holds the login
(`oauthAccount`), and a minimal dict written on top of a corrupt file would drop it, which
costs an interactive `/login` on the box. `read` raises `Unreadable` instead, and every
caller decides what that means.
"""

import json
from pathlib import Path

from keel import atomicfile

NAME = ".claude.json"
MODE = 0o600
# Server mode asks "Enable Remote Control? (y/n)" on a stdin nobody answers when this is
# absent (c-444). He consented once for the talker's config dir; asserting it is recording
# that consent where the server reads it, not answering the question for him.
CONSENT_KEY = "remoteDialogSeen"


class Unreadable(Exception):
    """The file exists and does not parse as a JSON object."""


def read(path: Path) -> dict:
    """The file's object, `{}` when there is no file; `Unreadable` when it does not parse."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return {}
    try:
        data = json.loads(text)
    except ValueError as error:
        raise Unreadable(f"{path}: {error}") from error
    if not isinstance(data, dict):
        raise Unreadable(f"{path}: not a JSON object")
    return data


def write(path: Path, data: dict) -> None:
    """Replace `path` with `data` in one rename, mode 0600 (`keel/atomicfile.py`)."""
    atomicfile.write_text(path, json.dumps(data, indent=2) + "\n", mode=MODE)


def ensure_consent(path: Path) -> bool:
    """`remoteDialogSeen: true` in the file, every other key left as it was (so
    `hasUsedRemoteControl` stays whatever it is). True when it had to be written, False
    when it was already there. `Unreadable` propagates: nothing is written over it."""
    data = read(path)
    if data.get(CONSENT_KEY) is True:
        return False
    data[CONSENT_KEY] = True
    write(path, data)
    return True
