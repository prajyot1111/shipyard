"""The csr sidecar: a house's session declared to the session index, naming its card.

csr (`smart-resume`, the session index under `~/.claude/tools/smart-resume`) reads one small
JSON file per session from `~/.claude/session-origin/<session id>.json` as GROUND TRUTH for
how the session was launched and which work item it belongs to (its `provenance.py`,
`read_sidecar`):

    {"provenance": "house", "origin_ref": "c-450", "topic": "boards"}

Without it a Keel house is classified from its first prompt, which carries none of the
markers csr looks for, so it was indexed as a human session with no work item (c-263,
inverted: Keel is the declared source and csr the consumer). `provenance` is `house`, one
of csr's machine-driven kinds, so the house is shown as evidence under its card rather than
as a conversation he had.

Two rules keep this a guest in csr's directory. The file is written only where the
directory already EXISTS, so a machine without csr (the box) gets nothing created; and a
file that cannot be written is skipped, never a failed launch, because the index is a
convenience and the house is the work. One file per session: a launch writes one, and so
does a resume that mints a new session id.
"""

import json
import os
from pathlib import Path

SIDECAR_DIR = (".claude", "session-origin")
PROVENANCE = "house"


def sidecar_dir(home: Path) -> Path:
    return home.joinpath(*SIDECAR_DIR)


def body(card: dict) -> dict:
    found = {"provenance": PROVENANCE, "origin_ref": card["id"]}
    if card.get("topic"):
        found["topic"] = card["topic"]
    return found


def declare(home: Path, card: dict, session_id: str | None) -> Path | None:
    """Write the sidecar for `session_id`; the path written, or None when there is no csr
    directory here, no session, or the file could not be written."""
    directory = sidecar_dir(home)
    if not session_id or not directory.is_dir():
        return None
    path = directory / f"{session_id}.json"
    partial = directory / f".{session_id}.json.part"
    try:
        partial.write_text(json.dumps(body(card)) + "\n")
        os.replace(partial, path)
    except OSError:
        partial.unlink(missing_ok=True)
        return None
    return path
