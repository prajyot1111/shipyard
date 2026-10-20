"""What a house is doing, in words a person can hear (V5).

A connected turn (`keel/converse.py`) runs the house's own turn as a stream, and every
tool the house picks up arrives as a record while it is still working. This module turns
one of those records into one short sentence and leaves it in the voice gateway's progress
inbox. It decides nothing about whether that sentence is SPOKEN: the gateway owns the
silence gate, the repeat budget, the shape guard and the `narrate` judge, and this module
owns only the vocabulary.

THE OUTPUT IS A CLOSED SET, WHICH IS THE WHOLE OF THE EGRESS ARGUMENT. Every sentence this
module can produce is a value in `TEMPLATES`, chosen by a key from `TOOL_ACTIONS` or
`BASH_ACTIONS`. Nothing read out of a tool's input can reach the sentence, so a file path, a
card id, a branch name or a secret in a command line cannot be spoken even by accident, and
cannot be written into the voice segment's data directory to be spoken later. The gateway's
shape guard is the second line; this is the first, and it is the one that holds by
construction rather than by screening.

SILENCE BEATS A WRONG WORD. A tool that is not in `TOOL_ACTIONS` produces NO line at all
rather than a vague one: "still on it" said about something we could not name is worth less
than the four seconds of quiet it replaces, and a wrong verb is worse than both. The Bash
allowlist works the other way round, because a shell command is always SOME work being done:
a verb it names gets that verb's sentence, and a verb it does not falls to `run`.

THE ACTION IS THE THING COMPARED, NEVER THE SENTENCE (V5, "never the same progress line
twice in a row" and "nothing when nothing changed"). Two reads in a row render the same
string, so comparing strings would catch that pair by accident and miss the pair where one
template is reworded. `same_action` is what the gateway calls, and it compares the key.

A SUBAGENT'S TOOLS ARE NOT THE HOUSE'S. A record carrying `parent_tool_use_id` came from
something the house handed out, and the house's own `Task` call already said so ("handing
part of it out"). Narrating the fan-out's own reads would be narrating one action twice at
two depths.
"""

import json
import os
import time
from pathlib import Path

# ----- the vocabulary -----

# THE HARD GATE. A tool that is not a key here produces nothing, whatever it did. The value
# is an action key, except for Bash, whose action is read from the command's own first word.
BASH = "bash"
TOOL_ACTIONS = {
    "Edit": "edit",
    "Write": "edit",
    "MultiEdit": "edit",
    "NotebookEdit": "edit",
    "Read": "read",
    "Glob": "search",
    "Grep": "search",
    "Task": "fan_out",
    "Agent": "fan_out",
    "WebFetch": "look_up",
    "WebSearch": "look_up",
    "Bash": BASH,
}

# THE VERB ALLOWLIST, for the one tool whose work is named by its argument rather than by
# its own name. A command's first bare word only: `git commit -m "..."` is `git`, and what
# follows is never looked at, because the message, the paths and the branch are exactly the
# things that must not travel. An unlisted verb is still real work, so it falls to `run`.
BASH_ACTIONS = {
    "git": "version_control",
    "make": "test",
    "pytest": "test",
    "tox": "test",
    "cat": "read",
    "head": "read",
    "tail": "read",
    "less": "read",
    "ls": "read",
    "wc": "read",
    "grep": "search",
    "rg": "search",
    "find": "search",
    "kb": "card",
    "keel": "card",
}
BASH_FALLBACK = "run"
# `cd <somewhere> && <the real verb>` is the commonest shape a house writes, and the verb
# that matters is the one after it. One hop only: a command that chains twice is narrated by
# its second verb, which is still an honest answer to "what is it doing".
CHAIN = ("&&", ";", "||")
SKIP_VERBS = ("cd", "source", ".", "exec", "time", "env", "sudo")

# ONE SENTENCE PER ACTION, and every sentence this module can say is on this list.
#
# They are written to clear `filler.progress_guard` by construction: ASCII, well under its
# eighteen words and hundred and forty characters, no digit (which is the shape of a card id
# or a count), no question mark, and no capital past the first word (which is the shape of a
# proper noun he never said out loud). They are checked against it by `tests/test_narration.py`
# rather than trusted to stay that way.
#
# "Still on it" leads every one of them because that is the sentence's actual job: the answer
# has not arrived and the wait is not broken. What follows is the only new information, and
# it is an action rather than an object (V5: names actions, never paths or identifiers).
TEMPLATES = {
    "edit": "Still on it, editing a file.",
    "read": "Still on it, reading the code.",
    "search": "Still on it, looking through the code.",
    "test": "Still on it, running the tests.",
    "version_control": "Still on it, working through git.",
    "card": "Still on it, updating the card.",
    "fan_out": "Still on it, handing part of it out.",
    "look_up": "Still on it, looking something up.",
    "run": "Still on it, running something.",
}


def bash_action(command: str) -> str:
    """The action key a shell command names: its first meaningful verb, or `run`.

    `cd x && make test` is the tests, not a directory change. Only the verb is ever read,
    so nothing else in the command can influence what comes back.
    """
    words = str(command or "").split()
    while words and words[0] in SKIP_VERBS:
        cut = next((i for i, word in enumerate(words) if word in CHAIN), None)
        if cut is None:
            return BASH_FALLBACK
        words = words[cut + 1:]
    if not words:
        return BASH_FALLBACK
    verb = os.path.basename(words[0])
    return BASH_ACTIONS.get(verb, BASH_FALLBACK)


def action_of(tool: str, tool_input: dict | None = None) -> str | None:
    """The action key for one tool call, or None when there is nothing worth saying."""
    action = TOOL_ACTIONS.get(str(tool or ""))
    if action is None:
        return None
    if action == BASH:
        return bash_action((tool_input or {}).get("command", ""))
    return action


# ----- reading the stream -----

def tool_calls(record: dict) -> list[tuple[str, dict]]:
    """Every tool the house itself picked up in one `stream-json` record.

    The record shapes are recorded in `state/cards/c-317/probe/README.md`, from a real
    turn against Claude Code 2.1.278: a tool call is an `assistant` record whose message
    content holds `{"type": "tool_use", "name": ..., "input": {...}}`. A record carrying
    `parent_tool_use_id` is a SUBAGENT's, and is not the house's own work.
    """
    if not isinstance(record, dict) or record.get("type") != "assistant":
        return []
    if record.get("parent_tool_use_id"):
        return []
    content = (record.get("message") or {}).get("content")
    if not isinstance(content, list):
        return []
    return [(str(block.get("name") or ""), block.get("input") or {})
            for block in content
            if isinstance(block, dict) and block.get("type") == "tool_use"]


def actions_in(record: dict) -> list[tuple[str, str]]:
    """The (tool, action) pairs one stream record names, in order; empty when it names none.

    The tool name travels beside the action because the shadow log is read by a person
    asking "what was it doing when it said that", and `Bash` against `git` is a different
    question from `Edit` against `edit`. It is never spoken and never reaches a sentence.
    """
    found = []
    for tool, tool_input in tool_calls(record):
        action = action_of(tool, tool_input if isinstance(tool_input, dict) else {})
        if action:
            found.append((tool, action))
    return found


# ----- the rule the gateway asks this module for -----

def same_action(previous: str | None, current: str | None) -> bool:
    """V5's "never the same progress line twice in a row", compared by ACTION.

    Two reads running render one string, so comparing the strings would catch that by
    accident; comparing the key says what was meant and survives a reworded template.
    """
    return bool(current) and previous == current


def sentence(action: str | None) -> str:
    """The one sentence for an action key, or "" when there is none."""
    return TEMPLATES.get(str(action or ""), "")


# ----- leaving the line where the gateway looks -----

def leave(directory: str | Path, action: str, *, turn: str = "", tool: str = "") -> Path | None:
    """Write one narration line into a progress inbox; the path written, or None.

    The record is the shape `harbor_voice.harbormsg.SayInbox` reads (`text`, `at`, `turn`),
    with `action` and `tool` beside them so the gateway's seat can ask the `narrate` judge
    about the ACTION and can tell a house activity line from a `bin/keel-voice progress`
    one. Written to a `.part` and renamed, so a half-written line never reads.

    KEEL DOES NOT KNOW WHERE THAT INBOX IS. The gateway passes the directory to
    `keel converse`, because the voice segment's layout is the gateway's to know and
    `keel/` never imports `harbor_voice` (different interpreters, and the dependency would
    only ever run one way).

    IT NEVER RAISES. This is called from inside a turn that is answering him; a progress
    line that cannot be written is a quieter wait, never a failed turn.
    """
    text = sentence(action)
    if not text or not directory:
        return None
    try:
        inbox = Path(directory)
        inbox.mkdir(parents=True, exist_ok=True)
        path = inbox / f"{time.time():.6f}-{os.getpid()}.json"
        part = path.with_suffix(".part")
        part.write_text(json.dumps({"text": text, "at": time.time(), "turn": turn,
                                    "action": action, "tool": tool}))
        part.rename(path)
        return path
    except OSError:
        return None


def leave_part(directory: str | Path, text: str, *, turn: str = "") -> Path | None:
    """Write one PART OF THE ANSWER into the same inbox; the path written, or None (V12).

    A part is not narration and the record says so. It carries `part: true` and no
    `action`, which is exactly what the gateway's watch loop reads to tell the two apart:
    a narration line waits for the four second silence gate, obeys the repeat rule and the
    per-turn budget, and is spoken in HARBOR's voice; a part is the house's own answer
    arriving, so it is spoken at once, in the HOUSE's voice, and no budget applies to it
    (V8). Once a part has been spoken the turn's narration is over, because the answer has
    started and nothing should be said over it.

    IT TRAVELS DOWN THE CHANNEL THAT ALREADY EXISTS, deliberately. The progress inbox is
    already stamped with the turn id, already claimed by the loop that is waiting for this
    turn's answer, and already the one thing `keel/` writes and the gateway reads. A second
    channel for the same turn would be a second thing to claim, a second thing to drain at
    the next `begin()`, and a second place for a line to be left behind.

    THE EGRESS ARGUMENT IS DIFFERENT HERE, AND IT IS THE SAME ONE V4 ALREADY MADE. The
    closed vocabulary above exists because a NARRATION line is the gateway talking about a
    house, and nothing a tool was given may reach it. A part is the house's ANSWER, which
    has always been spoken in full and written to the card: this is the same words, earlier.
    """
    said = " ".join(str(text or "").split())
    if not said or not directory:
        return None
    try:
        inbox = Path(directory)
        inbox.mkdir(parents=True, exist_ok=True)
        path = inbox / f"{time.time():.6f}-{os.getpid()}.json"
        part = path.with_suffix(".part")
        part.write_text(json.dumps({"text": said, "at": time.time(), "turn": turn,
                                    "part": True}))
        part.rename(path)
        return path
    except OSError:
        return None


class Narrator:
    """One connected turn's narration: reads records, leaves lines, says nothing twice.

    Held by `keel/converse.py` for the length of one streamed turn and thrown away with it.
    The repeat rule is enforced HERE as well as at the gateway on purpose: a line that will
    never be spoken should not be written, because the inbox keeps only the freshest record
    per silence window and a run of duplicates would push the one different line out of it.

    IT ALSO CARRIES THE ANSWER'S PARTS NOW (V12), for one reason: they go in the same
    inbox, under the same turn id, and this is the object that knows both. `on_record` is
    the one-shot path's way in (records straight off the stream) and `on_action` /
    `on_part` are the kept-alive path's, whose events have already been decoded by the
    machine half. All three end in `leave` or `leave_part`.
    """

    def __init__(self, directory: str | Path | None, turn: str = ""):
        self.dir = directory
        self.turn = turn
        self.last: str | None = None
        self.left = 0
        # WHAT THIS TURN GOT AS FAR AS, in order and without repeats. It is the record a
        # turn that is ENDED rather than answered leaves on the card (`converse.record_stopped`):
        # action keys, so a partial record can name what happened without naming a file.
        self.seen: list[str] = []
        # AND WHAT OF THE ANSWER HAS ALREADY BEEN HANDED OVER (V12). The caller reads it to
        # answer one question it cannot answer any other way: whether anything has already
        # been spoken, which is what decides that a failed turn must not be asked again.
        self.parts: list[str] = []

    def on_action(self, action: str, tool: str = "") -> bool:
        """One action the house took; True when a line was written."""
        if not action or same_action(self.last, action):
            return False
        self.last = action
        if action not in self.seen:
            self.seen.append(action)
        if self.dir and leave(self.dir, action, turn=self.turn, tool=tool) is not None:
            self.left += 1
            return True
        return False

    def on_part(self, text: str) -> bool:
        """One finished sentence of the answer; True when it was written."""
        said = " ".join(str(text or "").split())
        if not said:
            return False
        self.parts.append(said)
        return self.dir is not None and leave_part(self.dir, said, turn=self.turn) is not None

    def on_record(self, record: dict) -> list[str]:
        """Feed one stream record; the action keys actually written."""
        return [action for tool, action in actions_in(record)
                if self.on_action(action, tool)]
