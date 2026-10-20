"""Capture: what he said becomes an inbox card, with no model anywhere in the loop.

THE WHOLE PATH IS ONE `kb create`. He speaks, the speech model transcribes, and this file
shells out to the board once. Nothing here reads the board, nothing here asks a model
whether the words are an idea or a question, and nothing here can assign, stage or start
anything: a capture is an inbox card, always (`card-it-means-inbox`). Measured cost of a
`kb` write on this machine is tens of milliseconds, which is what lets the ack be spoken
inside a second of him letting go.

HIS WORDS GO ON THE CARD VERBATIM, as a quote, and nothing is written underneath: that
slot is the refine's (refine.py), one turn later and off the hot path. The title is the
first sentence clipped, because a card needs one and a clipped first sentence is the
cheapest honest one; the refine tidies it and never touches the quote.

THE SPACE IS WHATEVER THE MESSAGE SAID, and nothing else. There is no server-side space
state to drift: the page sends `space` with every capture, an unknown value falls to
`config.CAPTURE_SPACE_DEFAULT`, and a spoken first word can override both. "Work" or
"personal" as the first word, followed by a pause, files the capture there. The speech
model writes that pause as a colon, a full stop or a comma (nobody can speak a colon), so
all three are accepted; the word is stripped for the TITLE only and stays in the quote,
which is the verbatim record.

THE ACTOR IS `voice`, via `kb --actor voice`. The human actor needs the deck's token and
this process must never hold it.
"""
from __future__ import annotations

import json
import re

from . import config, snapshot

# "Work. Remind me to ..." and "personal: the trip needs ...". One word, one pause mark,
# then something. A bare "work" with nothing after it is not a prefix, it is the capture.
_PREFIX = re.compile(r"^\s*(work|personal)\s*[:.,]\s+(?=\S)", re.I)

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# What a capture with no usable words in it is called. It should not happen (an empty
# transcript never reaches the dispatcher), and a card with an empty title is refused by
# nothing and findable by nobody.
UNTITLED = "Voice capture"


class CaptureFailed(RuntimeError):
    """`kb` refused, or answered something that carries no card id. The message is kb's
    own words where it had any, because that is what the log wants."""


def space_of(said: str, space: str = "") -> tuple[str, str]:
    """(the space to file in, the text the title is cut from).

    The spoken prefix wins over the page's toggle: it is the more recent and the more
    deliberate of the two. An unknown `space` is the default, never an error, because a
    capture must not be lost to a stale page sending a word this build does not know.
    """
    chosen = str(space or "").strip().lower()
    if chosen not in config.CAPTURE_SPACES:
        chosen = config.CAPTURE_SPACE_DEFAULT
    text = " ".join(str(said or "").split())
    found = _PREFIX.match(text)
    if found:
        return found.group(1).lower(), text[found.end():]
    return chosen, text


def title_of(text: str, limit: int | None = None) -> str:
    """The first sentence, clipped to `CAPTURE_TITLE_CHARS` on a word boundary."""
    limit = limit or config.CAPTURE_TITLE_CHARS
    first = _SENTENCE_END.split(" ".join(str(text or "").split()), maxsplit=1)[0]
    # A leading dash would read as a flag to kb's parser, and a trailing full stop is
    # noise in a title.
    first = first.lstrip("-> ").rstrip(" .")
    if not first:
        return UNTITLED
    if len(first) <= limit:
        return first
    room = limit - 3
    cut = first[:room + 1]
    cut = cut[:cut.rfind(" ")] if " " in cut[room // 2:] else first[:room]
    return cut.rstrip(" ,;:") + "..."


def brief_of(said: str) -> str:
    """His words as a quote, then a blank line. The refine writes under it."""
    return "> " + " ".join(str(said or "").split()) + "\n\n"


def command(said: str, space: str = "", repairs=None) -> tuple[list[str], str]:
    """(the argv after `kb`, the space it files in). Pure, so the selftest can read it."""
    where, rest = space_of(said, space)
    argv = ["--actor", "voice", "create", "--space", where, "--topic", "voice",
            "--title", title_of(rest), "--brief", brief_of(said),
            "--option", "source=voice", "--option", "capture=raw"]
    heard = [{"heard": a, "readAs": b} for a, b in (repairs or [])]
    if heard:
        argv += ["--option", "heard=" + json.dumps(heard)]
    return argv, where


def create(argv: list) -> dict:
    """One `kb` write as the voice actor, and the card it printed.

    THROUGH `snapshot._kb`, the same helper the warm board uses: `config.KB` by absolute
    path, `KEEL_HOME` passed explicitly, `--json` on the end, and kb's own stderr as the
    error. A `kb` that silently wrote to a different board than the one the deck shows
    would be a capture that looked kept and was not.

    PUBLIC BECAUSE IT HAS A SECOND CALLER: `harbormsg.queue_answer` files an answer he
    could not hear the same way a capture files an idea, and one helper means one place
    where the actor, the board and the failure wording are decided.
    """
    try:
        card = snapshot._kb(*argv)
    except Exception as exc:                                            # noqa: BLE001
        raise CaptureFailed(f"{exc.__class__.__name__}: {exc}") from exc
    card_id = str((card or {}).get("id") or "") if isinstance(card, dict) else ""
    if not card_id:
        raise CaptureFailed("kb create answered without a card id")
    return card


def file(said: str, space: str = "", repairs=None) -> dict:
    """File one capture. Returns {"id", "space", "title"}; raises CaptureFailed."""
    if not " ".join(str(said or "").split()):
        raise CaptureFailed("nothing was said")
    argv, where = command(said, space, repairs)
    card = create(argv)
    return {"id": str(card.get("id")), "space": where,
            "title": argv[argv.index("--title") + 1]}
