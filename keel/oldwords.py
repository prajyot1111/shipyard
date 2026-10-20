"""Text a board already holds, in the words of the release that wrote it (c-699).

The engine was named Keel in what it said to the user until c-699, and Shipyard since. A
board keeps every note, block and event as it was written, so a sentence stored before the
change still names Keel. Any code that recognises its own stored sentence (to say a thing
once, or to find the fix for a block) reads both wordings through here, so an upgrade
neither repeats a note nor loses a fix.

The rule for a new sentence: if code compares stored text with it, the comparison goes
through `same` or `holds`, never `==` or `in` on the sentence alone.
"""
from __future__ import annotations

NAME = "Shipyard"
EARLIER = "Keel"


def before(text: str) -> str:
    """`text` as the earlier release worded it."""
    return text.replace(NAME, EARLIER)


def same(stored: str | None, now: str) -> bool:
    """Is `stored` this sentence, in today's wording or the earlier one."""
    return stored is not None and stored in (now, before(now))


def holds(stored: str | None, piece: str) -> bool:
    """Does `stored` carry `piece`, in today's wording or the earlier one."""
    stored = stored or ""
    return piece in stored or before(piece) in stored
