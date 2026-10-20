"""The blackboard: the line language a house draws with, the store, and the index.

A BOARD IS ONE MODEL. One diagram (groups, nodes, edges, marks) and the attachments that
hang off it: a note, a step, a table, a snippet, a file, each one on a NODE or on the board
itself. The deck shows that one model three ways (diagram, outline, walk); it is not a
filmstrip of pictures, and `frame` is gone from the grammar. His words, 2026-09-21: "the
talker adds a bunch of content, diagrams, ladders, flows, multiple frames; hard to consume;
one view that can be viewed in different ways, like diagrammatic and list, but not multiple
frames", and "if I ask for a second thing that doesn't fit with the first but still belongs
to the house, it can be another board, not a frame". The second thing is `board new`.

A house (or the talker) pushes LINES, one op per line, and the deck renders them. Nothing
an agent sends is HTML, SVG, script or a coordinate: the agent says WHAT exists and how it
connects, this module says whether that is a legal thing to say, and `app/ui.board.js`
decides where it goes on the screen. Three reasons, in the order they weigh:

- **Safety.** A house may have read a hostile page. Its output must never run in the
  deck's origin, where the approve verbs live. A line language has no place to hide a
  script, and the deck builds every node with `createElement`/`textContent`.
- **Speed.** Output tokens are the latency. Twenty lines arrive in a couple of seconds; a
  hand-written SVG does not.
- **It cannot break the board.** A line that does not parse is SKIPPED with its reason
  recorded (`skipped.log`) and everything around it is drawn without it. There is no way
  for one bad line to cost the rest of a push.

There is no erase. Re-declaring a node id updates it, `mark` highlights, attachments
append, and a picture that does not belong on this one is `board new`. The one way to draw
a board over is a REDRAW, a push that names the board (`--board b-NNN`, c-604): it writes a
`# redraw` marker and the model starts afresh there, so the outcome's redrawn plan board is
the built picture alone rather than the plan's with the build's appended to it. That is what makes a
board a record rather than a document: the ops are append-only, so what he was shown at the
time can always be replayed.

THE GRAMMAR IS SHARED, and this module is the half that decides. `app/ui.board.js` parses
the same lines to render them, and the two are held together by `docs/atlas/45-board.md`
(the written grammar) plus `tests/test_boards.py`, which runs both sides over the same
fixture of good and bad lines (`tests/fixtures/board-lines.txt`).

THE STORE is `state/boards/<b-id>/`: `board.json` (the record), `ops.log` (every accepted
line, append-only, with a `# push <n> <ts> <actor>` marker at each push) and `skipped.log`
(what was refused and why). Ids are `b-<n>`, minted the way a card's is. The whole tree is
under `state/`, which is what the `keel` backup set archives ([the backup](85-backup.md)).

THE LIVE BOARD of a source is its newest board that is not closed, ordered by `updated`,
which is why `open` bumps that field: reopening an older board is what makes it live
again. A push with no live board creates one.

A PUSH THAT SAYS THE SAME THING TWICE IN TEN SECONDS LANDS ONCE. One block written in a
spoken answer is READ TWICE, by the stream as the fence closes and by the pass over the
finished text, and on b-003 that drew the same six ops onto the board twice, 6 ms apart.
The pen compares normalised op sequences now (`keel/boardpen.py`), and this side holds the
same rule under it, because a cap the store does not hold is a cap a caller can get past by
being a different caller (`dup_of`).

THE FILES ARE `keel/boardfiles.py` AND NOT THIS MODULE. A `path` op is still one line of
grammar here; the bytes behind it are read by whoever is pushing, staged, and taken into the
board's own directory as the push folds (`fold`). The record's `files` map is what turns the
row the deck draws into a download, and nothing in this module ever opens a path a push
named. His own drop the other way (`inbox`) is the segments' upload control pointed at the
same directory.
"""

import contextlib
import fcntl
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from keel import boardfiles, boardgrammar, deckevents, sentences

DIRNAME = "boards"
BOARD_FILE = "board.json"
OPS_FILE = "ops.log"
SKIPPED_FILE = "skipped.log"
ID_PREFIX = "b-"
ID_RE = re.compile(r"^b-(\d+)$")
# THE TRASH (lane BD). A deleted board is MOVED under `state/boards/.trash/<b-id>/`, so every
# reader here that walks `state/boards/` or opens `<b-id>/` stops seeing it without being
# told; `keel/boardtrash.py` holds the delete, the restore and the purge. A purged board
# leaves `<b-id>.purged` behind, so its id is never minted again.
TRASH_DIR = ".trash"
TRASHED_RE = re.compile(r"^b-(\d+)(?:\.purged)?$")
DELETED_MARK = "is in the trash"

# ----- the vocabulary. Every name here is part of the grammar the deck parses too. -----

# What an attachment IS. Each one hangs on a node or on the board, and the deck shows it in
# the node's panel (diagram), under that node's heading (outline) or, for a step, as one
# stop on the walk.
ATTACH_KINDS = ("note", "step", "table", "code", "file")
# A CLOSED set of 24. An icon is a shape the deck already knows how to draw; a name it
# does not know falls back to `box` rather than refusing the line, because a wrong picture
# is a smaller failure than a missing node.
ICONS = ("laptop", "server", "cloud", "database", "phone", "mic", "speaker", "globe",
         "network", "lock", "key", "file", "folder", "git-branch", "bot", "user", "clock",
         "list", "cpu", "hard-drive", "shield", "box", "terminal", "zap")
FALLBACK_ICON = "box"
MARKS = ("accent", "good", "warn", "crit")
# `->` one way, `<->` both, `--` neither: a line that only says these two are connected.
ARROWS = {"->": "to", "<->": "both", "--": "none"}
OPS = ("board", "group", "node", "edge", "mark", "note", "step", "table", "cols", "row",
       "code", "lang", "line", "path")
# The word that means the BOARD rather than a node, wherever an attachment names where it
# hangs. It wins over a node that happens to be called `board`, because a rule he can
# predict beats one he has to look up.
BOARD_TARGET = "board"

# THE TWO OPS THAT WERE RETIRED WITH THE FRAMES, answered by name rather than by "that is
# not an op". A house or a talker carrying the old grammar in its head gets told what to
# write instead, on the line it got wrong, which is the whole value of a skip reason.
RETIRED = {
    "frame": "frames are gone: attach to a node or start a new board with `board new \"<title>\"`",
    "text": "text is gone: a note is `note <node|board> \"<text>\"`",
}

# The caps. They are here rather than in the renderer because a cap the SERVER does not
# hold is a cap an agent can talk its way past.
MAX_NODES = 12          # per board; a second picture is `board new`
MAX_TEXT = 240          # one quoted string
MAX_NAME = 48           # a node, group or language name
MAX_LINE = 800          # one raw line
MAX_CELLS = 6           # columns in a table
MAX_PUSH_LINES = 400    # lines in one push
MAX_ATTACH = 120        # attachments on one board

ACTORS = ("house", "talker", "human", "cli", "drain", "voice", "bosun")
PUSH_MARK = "# push "
# A REDRAW (`keel board push --board b-NNN`, c-604) opens with this marker instead, and every
# reader of `ops.log` (`build` here, `foldInto` in `app/ui.board.js`) starts the model afresh
# at it: the board shows the redrawn picture alone, and the lines before it stay in the log as
# the record of what was drawn earlier.
REDRAW_MARK = "# redraw "
LOCK_FILE = ".lock"
TEMP_PREFIX = ".tmp-"        # what the backup set already excludes by name
# How long one caller's identical push is treated as the same push said twice. Ten seconds
# is the whole width of the window it has to close: the stream's reading and the finished
# text's reading of one spoken block are milliseconds apart, and two deliberate pushes of
# the very same lines that far apart are a mistake either way.
DUP_SECONDS = 10


class BadLine(Exception):
    """One line is not a legal thing to say. The message is the reason recorded beside it."""


class TooManyNodes(BadLine):
    """The board is full, which is the one refusal a push does not survive.

    Every other bad line costs one line, because the rest of the push still means what it
    said. A thirteenth node does not: what follows it is a diagram with holes in it and then
    every attachment hanging on a node that was dropped, refused one at a time. `plan_push`
    turns this into a `BoardError` over the whole push, so nothing is drawn and the reason
    names the way out.
    """


class BoardError(Exception):
    """A verb was refused; the message is the one line the caller prints."""


# ----- parsing one line -----

TOKEN = re.compile(r'"([^"]*)"|(\S+)')
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
FENCE = "```"


def tokenize(line: str) -> list[tuple[str, bool]]:
    """The line as (text, was it quoted) pairs. A quoted string may hold spaces.

    An odd number of quote marks is refused rather than guessed at: the alternative is a
    label that silently swallows the rest of the line.
    """
    if line.count('"') % 2:
        raise BadLine("it has an unclosed quote")
    return [(m.group(1), True) if m.group(1) is not None else (m.group(2), False)
            for m in TOKEN.finditer(line)]


def check_text(value: str, what: str) -> str:
    if len(value) > MAX_TEXT:
        raise BadLine(f"the {what} is longer than {MAX_TEXT} characters")
    if CONTROL.search(value):
        raise BadLine(f"the {what} holds a control character")
    return value


def check_name(value: str, what: str) -> str:
    if len(value) > MAX_NAME:
        raise BadLine(f"the {what} is longer than {MAX_NAME} characters")
    if not NAME_RE.match(value):
        raise BadLine(f"{value!r} is not a {what}: letters, digits, dot, dash, colon and underscore")
    return value


def cells_of(rest: str, what: str) -> list[str]:
    """`A | B | C` as a list, for the two table ops. Not tokenized: a cell is free text."""
    parts = [part.strip() for part in rest.split("|")]
    parts = [part for part in parts if part]
    if not parts:
        raise BadLine(f"{what} needs at least one cell, separated by |")
    if len(parts) > MAX_CELLS:
        raise BadLine(f"{what} holds more than {MAX_CELLS} cells")
    return [check_text(part, "cell") for part in parts]


def parse_where(token: tuple[str, bool], op: str) -> str:
    """Where an attachment hangs: the word `board`, or a node id. Never quoted."""
    if token[1]:
        raise BadLine(f"{op} hangs on an unquoted <node|board>, not a quoted string")
    if token[0] == BOARD_TARGET:
        return BOARD_TARGET
    return check_name(token[0], "node id")


def parse_node(t: list[tuple[str, bool]]) -> dict:
    """`node <id> <icon> "label" [in <group>] ["sub label"]`."""
    if len(t) < 4 or t[1][1] or t[2][1] or not t[3][1]:
        raise BadLine('node wants: node <id> <icon> "label" [in <group>] ["sub label"]')
    op = {"op": "node", "id": check_name(t[1][0], "node id"),
          "icon": t[2][0] if t[2][0] in ICONS else FALLBACK_ICON,
          "label": check_text(t[3][0], "label"), "group": None, "sub": None}
    rest = t[4:]
    if rest and not rest[0][1] and rest[0][0] == "in":
        if len(rest) < 2 or rest[1][1]:
            raise BadLine("`in` wants the name of a group declared on this board")
        op["group"] = check_name(rest[1][0], "group id")
        rest = rest[2:]
    if rest:
        if len(rest) != 1 or not rest[0][1]:
            raise BadLine('the only thing after a node label or its group is a quoted "sub label"')
        op["sub"] = check_text(rest[0][0], "sub label")
    return op


def parse_edge(t: list[tuple[str, bool]]) -> dict:
    """`edge <a> -> <b> ["label"]`, also `<->` and `--`."""
    if len(t) not in (4, 5) or t[1][1] or t[2][1] or t[3][1] or t[2][0] not in ARROWS:
        raise BadLine('edge wants: edge <a> -> <b> ["label"], with -> or <-> or --')
    op = {"op": "edge", "a": check_name(t[1][0], "node id"), "b": check_name(t[3][0], "node id"),
          "arrow": ARROWS[t[2][0]], "label": None}
    if len(t) == 5:
        if not t[4][1]:
            raise BadLine("an edge label is quoted")
        op["label"] = check_text(t[4][0], "edge label")
    return op


def parse_path(t: list[tuple[str, bool]]) -> dict:
    """`path <node|board> "<path>" size "<size>" from <who>`: one file on the board.

    The GRAMMAR is all that is here. The bytes behind the path are read and carried by
    whoever is pushing and taken into the board's own directory by `fold` (see
    `keel/boardfiles.py`): nothing on this side ever opens what this line says, so a path
    naming something it should not is a row with no download rather than a way in.
    """
    if (len(t) != 7 or not t[2][1] or t[3][1] or t[3][0] != "size" or not t[4][1]
            or t[5][1] or t[5][0] != "from" or t[6][1]):
        raise BadLine('path wants: path <node|board> "<path>" size "<size>" from <who>')
    return {"op": "path", "at": parse_where(t[1], "path"),
            "path": check_text(t[2][0], "path"),
            "size": check_text(t[4][0], "size"), "from": check_name(t[6][0], "source")}


def parse_attached(op: str, t: list[tuple[str, bool]], field: str, what: str) -> dict:
    """The four attachments that open with a place and a quoted string."""
    if len(t) != 3 or not t[2][1]:
        raise BadLine(f'{op} wants: {op} <node|board> "<{what}>"')
    return {"op": op, "at": parse_where(t[1], op), field: check_text(t[2][0], what)}


def one_quoted(op: str, t: list[tuple[str, bool]], field: str, what: str) -> dict:
    if len(t) != 2 or not t[1][1]:
        raise BadLine(f'{op} wants one quoted {what}: {op} "<{what}>"')
    return {"op": op, field: check_text(t[1][0], what)}


def one_name(op: str, t: list[tuple[str, bool]], field: str, what: str) -> dict:
    if len(t) != 2 or t[1][1]:
        raise BadLine(f"{op} wants one unquoted {what}: {op} <{what}>")
    return {"op": op, field: check_name(t[1][0], what)}


BOARD_MODES = ("new", "rename")


def parse_board(t: list[tuple[str, bool]]) -> dict:
    """`board "<title>"` is the TOPIC; `board new` forces a second board; `board rename`
    renames this one.

    THE TITLE IS THE TOPIC (2026-09-21). `board "<title>"` used to mean "call this board
    that", so a push that opened by saying what it was about RENAMED whatever board
    happened to be live. Harbor did exactly that on the box: "How drawing on the board
    works" landed on "The memory tier system", renamed it, ran into the twelve node cap
    three nodes in and then refused 25 attachments hanging on nodes it had dropped. Nothing
    about that push was ill-formed. It said what it was about in the one op that exists for
    saying so.

    So a title that is not this board's title starts ANOTHER board (`fold`), the same title
    continues it, and renaming is its own word. It is a control op rather than a model op,
    which is why `apply_op` only ever takes the title from it.
    """
    if len(t) == 2 and t[1][1]:
        return {"op": "board", "mode": "topic", "title": check_text(t[1][0], "title")}
    if len(t) == 3 and not t[1][1] and t[1][0] in BOARD_MODES and t[2][1]:
        return {"op": "board", "mode": t[1][0], "title": check_text(t[2][0], "title")}
    raise BadLine('board wants: board "<title>", or board new|rename "<title>"')


def parse_line(raw: str) -> dict | None:
    """One line as an op, None for a blank or a comment, BadLine with the reason.

    A `#` line is a comment, which is also what the `# push <n>` markers in `ops.log` are,
    so reading a board back through this function skips its own markers. A ``` line is
    skipped for the same reason: a fence that survived the strip on the way out of a spoken
    answer is a stray mark, not an op, and answering it with "that is not an op" is how
    b-003 ended up with the reason in its skipped log twice.
    """
    if len(raw) > MAX_LINE:
        raise BadLine(f"the line is longer than {MAX_LINE} characters")
    text = raw.strip()
    if not text or text.startswith("#") or text.startswith(FENCE):
        return None
    head = text.split(None, 1)[0]
    if head in RETIRED:
        raise BadLine(RETIRED[head])
    if head in ("cols", "row"):
        cells = cells_of(text[len(head):], head)
        return {"op": "cols", "cols": cells} if head == "cols" else {"op": "row", "cells": cells}
    t = tokenize(text)
    if head == "board":
        return parse_board(t)
    if head == "group":
        if len(t) != 3 or t[1][1] or not t[2][1]:
            raise BadLine('group wants: group <id> "<label>"')
        return {"op": "group", "id": check_name(t[1][0], "group id"),
                "label": check_text(t[2][0], "label")}
    if head == "node":
        return parse_node(t)
    if head == "edge":
        return parse_edge(t)
    if head == "mark":
        if len(t) != 3 or t[1][1] or t[2][1] or t[2][0] not in MARKS:
            raise BadLine(f"mark wants: mark <node> {'|'.join(MARKS)}")
        return {"op": "mark", "id": check_name(t[1][0], "node id"), "status": t[2][0]}
    if head == "note":
        return parse_attached("note", t, "text", "text")
    if head == "step":
        return parse_attached("step", t, "text", "step")
    if head == "table":
        return parse_attached("table", t, "title", "title")
    if head == "code":
        return parse_attached("code", t, "title", "title")
    if head == "line":
        return one_quoted("line", t, "text", "line")
    if head == "lang":
        return one_name("lang", t, "lang", "language")
    if head == "path":
        return parse_path(t)
    raise BadLine(f"{head!r} is not an op; one of {', '.join(OPS)}")


# ----- the model one push builds, and what each op may do to it -----

def new_model() -> dict:
    """ONE model per board: one diagram and the attachments hanging off it."""
    return {"title": "", "groups": [], "nodes": [], "edges": [], "attachments": []}


def node_by(model: dict, node_id: str) -> dict | None:
    for node in model["nodes"]:
        if node["id"] == node_id:
            return node
    return None


def last_attachment(model: dict, kind: str) -> dict | None:
    """The newest attachment of this kind, which is the one `cols`/`row` and `lang`/`line`
    continue. A house writes a table and then its rows; nothing else would be meant."""
    for attachment in reversed(model["attachments"]):
        if attachment["kind"] == kind:
            return attachment
    return None


def new_attachment(model: dict, kind: str, at: str, **rest) -> dict:
    if len(model["attachments"]) >= MAX_ATTACH:
        raise BadLine(f"this board already holds {MAX_ATTACH} attachments; start another "
                      f"board with `board new \"<title>\"`")
    attachment = {"n": len(model["attachments"]) + 1, "kind": kind, "at": at, **rest}
    model["attachments"].append(attachment)
    return attachment


def where_of(model: dict, op: dict) -> str:
    """The node an attachment hangs on, or `board`. An unknown node is a skip.

    Declaring the node first is the rule, and it is the one that keeps an attachment from
    being orphaned by a typo: a note on `deckk` would otherwise sit on the board looking
    like it belonged to the diagram and belong to nothing.
    """
    at = op["at"]
    if at == BOARD_TARGET:
        return BOARD_TARGET
    if node_by(model, at) is None:
        raise BadLine(f"no node called {at!r} on this board; declare it before hanging "
                      f"{op['op']} on it, or hang it on `board`")
    return at


def apply_op(model: dict, op: dict) -> None:
    """Fold one op into the model.

    Everything that can only be judged against what came before is judged here: the node
    cap, an attachment on a node nobody declared, an edge to a node nobody declared, a
    group nobody opened, a row before its table. Each one raises `BadLine`, so it is
    skipped with its reason exactly like a line that did not parse.
    """
    kind = op["op"]
    if kind == "board":
        model["title"] = op["title"]
    elif kind == "group":
        if node_by(model, op["id"]) is not None:
            raise BadLine(same_id(op["id"], "a node", "group"))
        for group in model["groups"]:
            if group["id"] == op["id"]:
                group["label"] = op["label"]
                return
        model["groups"].append({"id": op["id"], "label": op["label"]})
    elif kind == "node":
        apply_node(model, op)
    elif kind == "edge":
        for end in ("a", "b"):
            if node_by(model, op[end]) is None:
                raise BadLine(f"no node called {op[end]!r} on this board; declare it before the edge")
        model["edges"].append({"a": op["a"], "b": op["b"], "arrow": op["arrow"],
                               "label": op["label"]})
    elif kind == "mark":
        node = node_by(model, op["id"])
        if node is None:
            raise BadLine(f"no node called {op['id']!r} on this board to mark")
        node["mark"] = op["status"]
    elif kind in ("note", "step"):
        new_attachment(model, kind, where_of(model, op), text=op["text"])
    elif kind == "table":
        new_attachment(model, "table", where_of(model, op), title=op["title"], cols=[], rows=[])
    elif kind == "code":
        new_attachment(model, "code", where_of(model, op), title=op["title"], lang="", lines=[])
    elif kind == "path":
        new_attachment(model, "file", where_of(model, op), path=op["path"], size=op["size"],
                       **{"from": op["from"]})
    elif kind in ("cols", "row"):
        apply_table(model, op)
    else:
        apply_code(model, op)


def same_id(name: str, taken: str, kind: str) -> str:
    """A group and a node may not share an id (c-602): the drawing keyed them together and a
    node in a group of its own name hung the page."""
    return (f"{taken} is already called {name!r} on this board; give the {kind} another id "
            f"(say {'g_' + name if kind == 'group' else name + '_node'!r}): a group and a node "
            f"may not share one")


def apply_node(model: dict, op: dict) -> None:
    if any(g["id"] == op["id"] for g in model["groups"]):
        raise BadLine(same_id(op["id"], "a group", "node"))
    if op["group"] and not any(g["id"] == op["group"] for g in model["groups"]):
        raise BadLine(f"no group called {op['group']!r} has been declared on this board")
    existing = node_by(model, op["id"])
    if existing is None and len(model["nodes"]) >= MAX_NODES:
        raise TooManyNodes(f"a board holds at most {MAX_NODES} nodes and this push would "
                           f"pass that, so nothing was drawn; start another board with "
                           f"`board new \"<title>\"`, or open the push with a title of "
                           f"its own")
    if existing is None:
        model["nodes"].append({"id": op["id"], "icon": op["icon"], "label": op["label"],
                               "group": op["group"], "sub": op["sub"], "mark": None})
        return
    # RE-DECLARING IS THE UPDATE. There is no erase, so this is how a label is corrected;
    # the mark survives, because marking and naming are separate acts.
    existing.update(icon=op["icon"], label=op["label"], group=op["group"], sub=op["sub"])


def apply_table(model: dict, op: dict) -> None:
    table = last_attachment(model, "table")
    if table is None:
        raise BadLine(f"{op['op']} continues a table; open one with "
                      f"`table <node|board> \"<title>\"` first")
    if op["op"] == "cols":
        table["cols"] = op["cols"]
        return
    if not table["cols"]:
        raise BadLine("a table wants its `cols` line before any row")
    table["rows"].append(op["cells"])


def apply_code(model: dict, op: dict) -> None:
    block = last_attachment(model, "code")
    if block is None:
        raise BadLine(f"{op['op']} continues a snippet; open one with "
                      f"`code <node|board> \"<title>\"` first")
    if op["op"] == "lang":
        block["lang"] = op["lang"]
    else:
        block["lines"].append(op["text"])


def build(lines) -> dict:
    """A model from lines already accepted, so a push folds onto what the board holds.

    Nothing here can fail: every line in `ops.log` was accepted by this same code when it
    was written, and a line that somehow cannot be is dropped rather than raised, because
    a board that will not open is worse than a board missing an op.
    """
    model = new_model()
    for raw in lines:
        if raw.startswith(REDRAW_MARK):
            model = new_model()
            continue
        try:
            op = parse_line(raw)
            if op is not None:
                apply_op(model, op)
        except BadLine:
            continue
    return model


def labels_of(model: dict) -> list[str]:
    """What `find` scores a board's content on: its node labels and sub labels."""
    out = []
    for node in model["nodes"]:
        out.append(node["label"])
        if node["sub"]:
            out.append(node["sub"])
    return out


def said_of(model: dict) -> list[str]:
    """The words the attachments carry, for `find`: a title, a note, a step."""
    out = []
    for attachment in model["attachments"]:
        for key in ("title", "text"):
            if attachment.get(key):
                out.append(attachment[key])
    return out


# ----- reading a push back the same way twice -----
#
# ONE FUNCTION, in `keel/sentences.py`, because it is about reading a BLOCK rather than
# about the board, and because the voice gateway compares the same sequences from an
# interpreter that must not import the store. Named here so a reader of this file finds it
# where they look for it.
normalise = sentences.normalise
signature = sentences.signature


# ----- is this the same topic -----

TOPIC_NOISE = re.compile(r"[^\w\s]+")


def topic_key(text) -> str:
    """A title reduced to what it is ABOUT: case, punctuation and spacing folded away.

    He is not the one typing these. A model writes the title again from its own memory of
    the conversation, and "the memory-tier system." is the same topic as "The memory tier
    system". Folding nothing would make every push a new board; folding words would make
    two real topics one.
    """
    return " ".join(TOPIC_NOISE.sub(" ", str(text or "").lower()).split())


def same_topic(one, other) -> bool:
    return topic_key(one) == topic_key(other)


# ----- the store -----

def now() -> str:
    """A stamp to the microsecond, because `updated` is what ORDERS boards.

    Two boards touched in the same second would otherwise tie, and the tie-break would
    decide which one a push continues. `open` exists precisely to change that answer.
    """
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="microseconds")


def seconds_since(stamp: str) -> float:
    """How long ago that stamp was, or a large number when it cannot be read."""
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(stamp)).total_seconds()
    except (TypeError, ValueError):
        return float("inf")


def root(cfg) -> Path:
    return Path(cfg.state_dir) / DIRNAME


def board_dir(cfg, board_id: str) -> Path:
    if not ID_RE.match(board_id or ""):
        raise BoardError(f"{board_id!r} is not a board id; they look like b-001")
    return root(cfg) / board_id


def next_id(cfg) -> str:
    """The next `b-<n>`, counting the trash and what was purged from it, so an id an
    embed or a link still names is never handed to another board."""
    highest = 0
    base = root(cfg)
    for directory, pattern in ((base, ID_RE), (base / TRASH_DIR, TRASHED_RE)):
        if not directory.is_dir():
            continue
        for entry in directory.iterdir():
            match = pattern.match(entry.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return f"{ID_PREFIX}{highest + 1:03d}"


@contextlib.contextmanager
def store_lock(cfg):
    """One writer at a time across the whole store, on `state/boards/.lock`.

    Every write here is a read, a change and a whole-file rewrite: `next_id` scans the
    directory and `create` then makes one, and a push reads `ops.log`, appends to it and
    rewrites `board.json` from the model it built before appending. Two of those at once
    mint the same `b-<n>` and leave a record counting nodes the log does not hold. The
    drain, the deck and a house all write here, so the lock is a FILE lock rather than a
    thread lock: `flock` is per open file description, which serialises threads of one
    process and processes on one host alike.

    The verbs take it; the helpers under them never do, because `flock` on a second
    descriptor in the same process blocks against the first and would deadlock the push
    that is already holding it.
    """
    base = root(cfg)
    base.mkdir(parents=True, exist_ok=True)
    handle = (base / LOCK_FILE).open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


# ----- who may change a board -----

def caller_source(caller: dict | None) -> dict | None:
    """The source a caller OWNS, or None when it is him and owns them all.

    The card is the fact that cannot be restated: `KEEL_CARD` is what the harness gives a
    house's own shell, and over HTTP it is what the caller carried. An actor of `talker`
    with no card owns the talker's boards. Everything else is him, at his own terminal or
    on the deck, and `keel/actions.py` makes a remote caller prove that with the token.
    """
    caller = caller or {}
    card = caller.get("card")
    if card:
        return {"kind": "card", "card": str(card)}
    if caller.get("actor") == "talker":
        return {"kind": "talker", "card": None}
    return None


def who(caller: dict | None) -> str:
    own = caller_source(caller)
    if own is None:
        return "you"
    return own["card"] if own["kind"] == "card" else "the talker"


def may_change(source: dict, caller: dict | None) -> None:
    """Refuse a caller a board whose SOURCE is not its own.

    Reading is open: a house may look at any board, exactly as it may `kb show` any card.
    Writing is not. `open` makes a board its source's live board again, so the next push
    lands there; `close` ends a sitting; `new --from` forks one. Each of those changes a
    record that belongs to somebody else's conversation, and until this existed a house
    scoped to one card could do all three to the talker's board and to every other card's.
    """
    own = caller_source(caller)
    if own is None:
        return
    if own["kind"] != source.get("kind") or own["card"] != source.get("card"):
        want = "a card's board" if source.get("kind") == "card" else "the talker's board"
        if source.get("kind") == "card":
            want = f"{source.get('card')}'s board"
        raise BoardError(f"{who(caller)} may only change its own boards, and that is {want}")


def read_record(cfg, board_id: str) -> dict:
    path = board_dir(cfg, board_id) / BOARD_FILE
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as error:
        if (root(cfg) / TRASH_DIR / board_id / BOARD_FILE).is_file():
            # SAID BY NAME, so an embed, a lint and a link can tell "he deleted it" from
            # "it never existed" (BD-2), and the words before the colon carry it.
            raise BoardError(f"{board_id} {DELETED_MARK}, restorable for 30 days: "
                             f"keel board restore {board_id}") from None
        raise BoardError(f"no board called {board_id}: {error}") from None


def write_record(cfg, record: dict) -> None:
    """The record, written whole and moved into place, so a reader never sees half of it."""
    directory = board_dir(cfg, record["id"])
    directory.mkdir(parents=True, exist_ok=True)
    temp = directory / f"{TEMP_PREFIX}{BOARD_FILE}"
    temp.write_text(json.dumps(record, indent=1) + "\n")
    os.replace(temp, directory / BOARD_FILE)


def lines_at(lines: list[str], at) -> int:
    """How many of a board's `ops.log` lines were there at `at` (an ISO stamp): the lines
    before the first push or redraw marker stamped later (c-604 review). An approved plan's
    embed is pinned to this, derived from the markers the log already carries, so a redraw at
    the built head never changes what his approved plan shows."""
    from datetime import datetime    # noqa: PLC0415
    def when(stamp):
        try:
            moment = datetime.fromisoformat(str(stamp))
        except ValueError:
            return None
        return moment if moment.tzinfo else moment.astimezone()
    cut = when(at)
    if cut is None:
        return len(lines)
    for number, line in enumerate(lines):
        if line.startswith((PUSH_MARK, REDRAW_MARK)):
            parts = line.split()
            stamped = when(parts[3]) if len(parts) > 3 else None
            if stamped is not None and stamped > cut:
                return number
    return len(lines)


def ops_lines(cfg, board_id: str) -> list[str]:
    path = board_dir(cfg, board_id) / OPS_FILE
    if not path.is_file():
        return []
    return path.read_text(errors="replace").splitlines()


def records(cfg) -> list[dict]:
    """Every board's record, newest first by `updated`. An unreadable one is left out."""
    base = root(cfg)
    if not base.is_dir():
        return []
    out = []
    for entry in sorted(base.iterdir()):
        if not ID_RE.match(entry.name) or not entry.is_dir():
            continue
        try:
            out.append(json.loads((entry / BOARD_FILE).read_text()))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda r: (r.get("updated") or "", r["id"]), reverse=True)


def same_source(record: dict, source: dict) -> bool:
    return (record.get("source") or {}).get("kind") == source["kind"] and \
        (record.get("source") or {}).get("card") == source["card"]


def live_record(cfg, source: dict) -> dict | None:
    """The source's newest board that is not closed, which is the one a push appends to."""
    for record in records(cfg):
        if same_source(record, source) and not record.get("closed"):
            return record
    return None


def create(cfg, source: dict, title: str, actor: str) -> dict:
    """A new board for this source. Takes the store lock; `new_board` is the inner half
    for a verb that is already holding it."""
    with store_lock(cfg):
        return new_board(cfg, source, title, actor)


def new_board(cfg, source: dict, title: str, actor: str) -> dict:
    stamp = now()
    record = {"id": next_id(cfg), "title": title, "summary": "", "source": source,
              "actor": actor, "created": stamp, "updated": stamp, "closed": None,
              "nodes": 0, "attachments": 0, "labels": [], "said": [], "files": {},
              "last_push": None}
    directory = board_dir(cfg, record["id"])
    directory.mkdir(parents=True, exist_ok=True)
    (directory / OPS_FILE).touch()
    write_record(cfg, record)
    return record


# ----- the push -----

def source_of(card: str | None, talker: bool) -> dict:
    if talker == bool(card):
        raise BoardError("a push names its source: --card c-NNN or --talker")
    return {"kind": "talker" if talker else "card", "card": card}


def push_check(source: dict, caller: dict | None) -> None:
    """A caller may only draw on its own source. The same rule every writing verb keeps
    (`may_change`), said in the words a push wants."""
    own = caller_source(caller)
    if own is None:
        return
    if own["kind"] == "card" and source["kind"] == "talker":
        raise BoardError(f"--talker is not a house's to push; this house is {own['card']}")
    if own["kind"] == "talker" and source["kind"] == "card":
        raise BoardError("the talker draws on its own boards; a card's board is its house's")
    if own["card"] != source["card"]:
        raise BoardError(f"this house is {own['card']}, so it cannot push to {source['card']}'s board")


def title_from(model: dict, record: dict, given: str | None, card_title: str | None) -> str:
    """The board's name: what was asked for, what the `board` op said, the first group's or
    node's label, then the card's own title. A board with none of those is still a board."""
    first = (model["groups"][0]["label"] if model["groups"]
             else model["nodes"][0]["label"] if model["nodes"] else "")
    for candidate in (given, model["title"], record.get("title"), first, card_title):
        if candidate and candidate != "Untitled board":
            return str(candidate)[:MAX_TEXT]
    return "Untitled board"


def path_ops(ops_text: str) -> list[str]:
    """Every path a `path` op in this push names, in order, each one once.

    What `keel board push` walks before it sends anything: one file read and staged per
    path, so the bytes are in the store before the line that names them arrives.
    """
    out = []
    for raw in (ops_text or "").splitlines():
        try:
            op = parse_line(raw)
        except BadLine:
            # A PREVIOUS-GRAMMAR `path` IS A PATH TOO (review F5): the store translates it,
            # so the bytes it names must travel with the push or the row lands with no
            # download under it (B12).
            old = boardgrammar.translate(raw)
            try:
                op = parse_line(old["line"]) if old and old["line"] else None
            except BadLine:
                op = None
        if op and op.get("op") == "path" and op["path"] not in out:
            out.append(op["path"])
    return out


def push(cfg, ops_text: str, *, card: str | None = None, talker: bool = False,
         title: str | None = None, actor: str = "cli", caller: dict | None = None,
         card_title: str | None = None, placed: dict | None = None, new: bool = False,
         board_id: str | None = None) -> dict:
    """Fold a push onto the source's live board, creating one when there is none.

    Every line is judged, in order, against the board as it stands. What is accepted goes
    to `ops.log` and what is not goes to `skipped.log` with its reason, and the push
    succeeds either way: a house that got one line wrong still drew the rest.

    The whole fold is under the store lock, because it reads `ops.log`, appends to it and
    then rewrites `board.json` from the model it built: two at once leave the record
    counting nodes the log does not hold.

    `placed` is for a file that is ALREADY where it belongs (his own drop, which lands in
    the card's inbox before the line naming it is pushed). Everything else a `path` op
    names is taken out of the staging area `boardfiles.attach` wrote it to.

    `new` (`keel board push --new`) starts a FRESH board even when one is live, and inside
    that push every `board` line starts another one: a house with three flows writes one
    file and makes one call, not a push and a `board new` per board. The board that was
    live stays open, exactly as it does after `board new` (B3 and B6 of the blackboard):
    nothing he did not ask to close is closed, and the newest board is the live one.

    `board_id` (`keel board push --board b-NNN`, c-604) REDRAWS that board: its content is
    replaced by this push's, under the same id, and the earlier lines stay in its log. It is
    how an outcome shows a plan board at the built head as one picture.
    """
    source = source_of(card, talker)
    push_check(source, caller)
    if board_id and new:
        raise BoardError("--board redraws one board and --new starts another; give one of them")
    raw_lines = ops_text.splitlines()
    if len(raw_lines) > MAX_PUSH_LINES:
        raise BoardError(f"one push carries at most {MAX_PUSH_LINES} lines; this one has {len(raw_lines)}")
    with store_lock(cfg):
        if board_id:
            return redraw(cfg, source, board_id, raw_lines, title, actor, card_title, placed)
        return fold(cfg, source, raw_lines, title, actor, card_title, placed, new)


def redraw(cfg, source: dict, board_id: str, raw_lines: list[str], title: str | None,
           actor: str, card_title: str | None, placed: dict | None = None) -> dict:
    """A push that names its board, with the store lock held: the board is drawn over.

    Only the source's own board may be redrawn, and not a closed one (its sitting is over;
    `keel board open` makes it live again). A redraw that accepted no line writes nothing, so
    a push that went wrong never blanks the picture it meant to replace.
    """
    record = read_record(cfg, board_id)
    if not same_source(record, source):
        raise BoardError(f"{board_id} is not this source's board, so this push cannot redraw it")
    if record.get("closed"):
        raise BoardError(f"{board_id} is closed; `keel board open {board_id}` first")
    sig = signature("\n".join(raw_lines))
    if dup_of(record, sig, actor):
        return duplicate_result(cfg, record, sig, actor)
    plan = plan_push(cfg, record, raw_lines, card_title, redraw=True)
    return write_plan(cfg, source, plan, title, actor, card_title, sig, placed)


def dup_of(record: dict | None, sig: str, actor: str) -> bool:
    """Has this exact caller just pushed these exact ops.

    The store's half of the duplicate rule. `keel/boardpen.py` holds the other half, which
    is what stops the second push being ATTEMPTED at all; this one is here because a cap
    the store does not hold is one a caller can get past, and because the two readings of a
    spoken block can arrive through two different doors.
    """
    was = (record or {}).get("last_push") or {}
    return bool(was.get("sig") == sig and was.get("by") == actor
                and seconds_since(was.get("at")) < DUP_SECONDS)


def fold(cfg, source: dict, raw_lines: list[str], title: str | None, actor: str,
         card_title: str | None, placed: dict | None = None, new: bool = False) -> dict:
    """The push itself, with the store lock already held.

    TWO PASSES, AND THE FIRST ONE TOUCHES NOTHING. `plan_push` decides what this push would
    do, including which lines land on which board and whether any board would be taken past
    its node cap; `write_plan` then does it. They are apart so that a push that cannot fit
    draws NOTHING rather than half of it: the cap used to refuse the thirteenth node and
    carry on, and what followed was every attachment hanging on a node that had been
    dropped, refused one at a time.

    ONE PUSH MAY CROSS BOARDS, two ways. `board new "<title>"` says so outright, and a
    `board "<title>"` whose title is not this board's topic does it by meaning it: the
    title is what a board is ABOUT, so a new title is a new board.
    """
    live = live_record(cfg, source)
    sig = signature("\n".join(raw_lines))
    if dup_of(live, sig, actor):
        return duplicate_result(cfg, live, sig, actor)
    plan = plan_push(cfg, None if new else live, raw_lines, card_title, split=new)
    return write_plan(cfg, source, plan, title, actor, card_title, sig, placed)


def open_segment(cfg, record: dict | None, start: str | None, redraw: bool = False) -> dict:
    """One board's share of a push, before any of it is written.

    `record` is the board it continues, or None for one this push will mint. `start` is the
    title it is minted under, which is also written into its own log as its first line, so
    a board always says what it is called in the ops that make it up.
    """
    lines = ops_lines(cfg, record["id"]) if record else []
    return {"record": record, "start": start, "model": new_model() if redraw else build(lines),
            "at": len(lines), "had": len(lines), "ops": [], "skipped": [], "files": [],
            "over": "", "translated": 0, "redraw": redraw}


def segment_title(segment: dict) -> str:
    """What the board this segment is on is CALLED, for the topic comparison.

    The model's title is the last `board` line in its log, which is the name a board that
    named itself has. A board named after its first label, or after its card, has none, so
    the record's title is the fallback and it is the one the deck shows.
    """
    return segment["model"]["title"] or (segment["record"] or {}).get("title") or ""


def starts_a_board(segment: dict, op: dict, split: bool = False) -> bool:
    """Does this `board` line mean "another board", rather than "this one".

    A board with nothing on it yet is always NAMED rather than left behind: the first push
    of all, and the board `board new` has just minted, have nothing to start away from, and
    a talker whose every push opens with a title would otherwise collect blanks.
    """
    if not segment["had"] and not segment["ops"]:
        return False
    if op["mode"] == "new":
        return True
    if op["mode"] == "rename":
        return False
    if split:
        return True          # `--new`: every board line in the file is a board of its own
    return not same_topic(op["title"], segment_title(segment))


def plan_push(cfg, live: dict | None, raw_lines: list[str], card_title: str | None,
              split: bool = False, redraw: bool = False) -> list[dict]:
    """What this push would do, decided before a byte of it is written.

    Raises `BoardError` when a board would be taken past its node cap, naming the two ways
    out. Everything else that is wrong is still one skipped line with its reason.
    """
    segments = [open_segment(cfg, live, None, redraw)]
    here = segments[0]
    for raw in raw_lines:
        try:
            op = parse_line(raw)
        except BadLine as why:
            raw, op = read_previous(here, raw, why)
            if op is None:
                continue
        if op is None:
            continue
        if redraw and op["op"] == "board" and op["mode"] == "new":
            here["skipped"].append((raw.strip(), "a redraw is one board; draw another with "
                                                 "`keel board push --new`"))
            continue
        if not redraw and op["op"] == "board" and starts_a_board(here, op, split):
            here = open_segment(cfg, None, op["title"])
            segments.append(here)
            # ITS OWN LOG NAMES IT, whichever form started it, so replaying that log is
            # enough to know what the board is called.
            here["ops"].append(f'board "{op["title"]}"')
            here["model"]["title"] = op["title"]
            continue
        try:
            apply_op(here["model"], op)
        except TooManyNodes as why:
            here["over"] = str(why)
            continue
        except BadLine as why:
            here["skipped"].append((raw.strip(), str(why)))
            continue
        if op["op"] == "path":
            here["files"].append(op)
        here["ops"].append(raw.strip())
    for segment in segments:
        if segment["over"]:
            raise BoardError(segment["over"])
    return segments


def read_previous(segment: dict, raw: str, why: BadLine) -> tuple[str, dict | None]:
    """A line this grammar refused, read as the PREVIOUS grammar (C4): (the line to write,
    its op), or (raw, None) with the line accounted for in the skipped rows.

    A house started before a grammar change still writes the old one, so its bare steps and
    notes hang on the board and its frame lines are dropped with a row saying so, rather
    than 21 of 27 lines refused (b-003). What is written to `ops.log` is the translated line,
    so the deck reads it in the grammar it knows.
    """
    old = boardgrammar.translate(raw)
    if old is None:
        segment["skipped"].append((raw.strip(), str(why)))
        return raw, None
    segment["translated"] += 1
    if old["line"] is None:
        segment["skipped"].append((raw.strip(), old["why"]))
        return raw, None
    try:
        return old["line"], parse_line(old["line"])
    except BadLine as again:
        segment["skipped"].append((raw.strip(), str(again)))
        return raw, None


def write_plan(cfg, source: dict, segments: list[dict], title: str | None, actor: str,
               card_title: str | None, sig: str, placed: dict | None) -> dict:
    """Do what the plan says, board by board. The result names the LAST one, because that
    is the live one and the one his link should open.

    A SEGMENT THAT DREW NOTHING IS NOT WRITTEN, and that is the common case now: a push that
    opens with a new topic leaves a first segment holding only the `board` line that sent it
    elsewhere. Writing it would bump the old board's `updated`, which is what ORDERS boards
    and decides which one is live, so a push that never touched it would reorder his list and
    name it among the boards it drew on. A push that says nothing at all still answers with
    the live board, because the caller asked about something.
    """
    drew = [s for s in segments if s["ops"] or s["skipped"]] or segments[:1]
    results = []
    for segment in drew:
        if segment["record"] is None:
            segment["record"] = new_board(cfg, source, segment["start"] or title
                                          or "Untitled board", actor)
            segment["at"] = 0
        results.append(shut_sitting(cfg, segment, source, title, actor, card_title, sig,
                                    placed))
    last = results[-1]
    last["boards"] = [result["board"] for result in results]
    # THE REPORT IS THE WHOLE PUSH'S (C1). What he hears is built from these counts, so a
    # push that refused lines on its first board and drew cleanly on its second must not
    # answer with the second board's clean count alone.
    last["accepted"] = sum(result["accepted"] for result in results)
    last["skipped"] = sum(result["skipped"] for result in results)
    last["reasons"] = [why for result in results for why in result["reasons"]]
    last["translated"] = sum(segment["translated"] for segment in segments)
    return last


def shut_sitting(cfg, sitting: dict, source: dict, title: str | None, actor: str,
                 card_title: str | None, sig: str, placed: dict | None = None) -> dict:
    """Write one board's share of a push: the files, the ops, the skips, the record, the
    event. The board exists by now, which is what a `path` op needs before its bytes can be
    taken into that board's own directory."""
    record, model = sitting["record"], sitting["model"]
    files = dict(record.get("files") or {})
    for op in sitting["files"]:
        entry = take_file(cfg, source, record, op, actor, placed)
        if entry is not None:
            files[op["path"]] = entry
    stamp = now()
    directory = board_dir(cfg, record["id"])
    line_no = sitting["at"]
    if sitting["ops"]:
        # ONE MARKER PER PUSH, where there used to be one per frame. It is what `since` and
        # the live channel count in, and what says who drew and when when the log is read
        # back by a person.
        mark = REDRAW_MARK if sitting.get("redraw") else PUSH_MARK
        lines = [f"{mark}{line_no + 1} {stamp} {actor}", *sitting["ops"]]
        with (directory / OPS_FILE).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        line_no += len(lines)
    if sitting["skipped"]:
        with (directory / SKIPPED_FILE).open("a", encoding="utf-8") as handle:
            for raw, why in sitting["skipped"]:
                handle.write(f"{stamp}\t{why}\t{raw}\n")
    record["title"] = title_from(model, record, title, card_title)
    record["nodes"] = len(model["nodes"])
    record["attachments"] = len(model["attachments"])
    record["labels"] = labels_of(model)
    record["said"] = said_of(model)
    record["files"] = files
    record["updated"] = stamp
    if sitting["ops"]:
        record["last_push"] = {"sig": sig, "at": stamp, "by": actor}
    if actor in ACTORS:
        record["actor"] = actor
    write_record(cfg, record)
    # An open board page is TOLD, rather than finding out on its own poll up to five
    # seconds later: this is the half that covers a push made inside the deck's process
    # (a fence in a spoken answer, his own drop). A push from a shell is another process
    # and publishes nothing, which is what the stream's own sweep is for
    # (`serve.pump_events`).
    if sitting["ops"]:
        deckevents.HUB.board(record["id"], line_no)
    return result_of(cfg, record, accepted=len(sitting["ops"]),
                     skipped=[why for _, why in sitting["skipped"]])


def result_of(cfg, record: dict, accepted: int, skipped: list[str],
              duplicate: bool = False) -> dict:
    return {"board": record["id"], "title": record["title"], "nodes": record["nodes"],
            "attachments": record["attachments"], "accepted": accepted,
            "skipped": len(skipped), "reasons": skipped, "duplicate": duplicate,
            "files": len(record.get("files") or {}), "url": board_link(cfg, record)}


def duplicate_result(cfg, record: dict, sig: str, actor: str) -> dict:
    """The same push, said twice inside ten seconds: recorded and not drawn.

    It answers `ok`, because from the caller's side the ops ARE on the board, and saying no
    would have a house tell him it could not draw something he is already looking at. The
    `dup` row in `skipped.log` is where the second reading is accounted for.
    """
    with (board_dir(cfg, record["id"]) / SKIPPED_FILE).open("a", encoding="utf-8") as handle:
        handle.write(f"{now()}\tdup\tthe same ops from {actor} within {DUP_SECONDS}s "
                     f"({sig})\n")
    return result_of(cfg, record, accepted=0, skipped=[], duplicate=True)


def take_file(cfg, source: dict, record: dict, op: dict, actor: str,
              placed: dict | None) -> dict | None:
    """The record's entry for one accepted `path` op, or None when no bytes arrived.

    None is stage one's behaviour, deliberately kept: the row is drawn with no download
    under it. A caller that could not carry the file (an older `keel board`, a push typed
    by hand) still gets its metadata row rather than a refusal, and the one that DID carry
    it gets the download. `keel board push` refuses on this side of the hop when a file it
    was asked to carry could not be read, which is where a person can still do something
    about it.
    """
    if placed and op["path"] in placed:
        return placed[op["path"]]
    from_who = op.get("from") or actor
    return boardfiles.take(cfg, source, op["path"],
                           boardfiles.files_dir(cfg, source, board_dir(cfg, record["id"])),
                           from_who)


def deck_base(cfg) -> str:
    """Where the deck answers, for the link a push hands back: this machine's own deck."""
    return f"http://127.0.0.1:{cfg.serve_port}"


def board_link(cfg, record: dict) -> str:
    """The deck URL of the board, which is one page with three views now rather than a
    frame he has to be pointed at."""
    return deck_base(cfg) + f"/board/{record['id']}"


# ----- the index -----

def row_of(cfg, record: dict) -> dict:
    live = live_record(cfg, record.get("source") or {"kind": "talker", "card": None})
    return {"id": record["id"], "title": record.get("title") or "", "summary": record.get("summary") or "",
            "source": record.get("source") or {}, "actor": record.get("actor") or "",
            "created": record.get("created"), "updated": record.get("updated"),
            "closed": record.get("closed"), "nodes": record.get("nodes") or 0,
            "attachments": record.get("attachments") or 0, "pushed": pushed_at(record),
            "live": bool(live and live["id"] == record["id"])}


def pushed_at(record: dict) -> str | None:
    """When the board was last DRAWN on (c-602): its last push, else when it was made.
    `updated` moves on open and close too, so it cannot say whether a plan board was redrawn."""
    return ((record.get("last_push") or {}).get("at")) or record.get("created")


def listing(cfg, card: str | None = None, limit: int = 0) -> list[dict]:
    rows = [row_of(cfg, record) for record in records(cfg)
            if card is None or (record.get("source") or {}).get("card") == card]
    return rows[:limit] if limit else rows


# What a match is worth, by where it was found. A title match beats a label match because
# what he remembers about a board is what it was called, not what was inside it.
WEIGHTS = {"title": 4, "summary": 2, "said": 2, "label": 1}


def score(record: dict, words: list[str]) -> int:
    fields = {"title": [record.get("title") or ""], "summary": [record.get("summary") or ""],
              "said": list(record.get("said") or []), "label": list(record.get("labels") or [])}
    # WHOLE WORDS, not substrings. A substring search scores "at" against "What", which
    # is how a search for "nothing at all here" matched a board about the memory system.
    haystacks = {name: set(re.split(r"\W+", " ".join(values).lower())) for name, values in fields.items()}
    total = 0
    for word in words:
        for name, weight in WEIGHTS.items():
            if word in haystacks[name]:
                total += weight
    return total


def find(cfg, text: str, limit: int = 0) -> list[dict]:
    """Boards matching these words, best first, so the talker can offer the older board.

    A whole-word search over the four places a board says what it is about. There is no
    stemming and no ranking model on purpose: the corpus is his own boards, tens of them,
    and a rule he can predict beats a score he cannot. Both sides are cut on non-word
    characters, so `MEMORY.md` in a search finds `MEMORY.md` in a node label.
    """
    # A one-letter word is dropped: "a" is in almost every label, so leaving it in makes
    # every board a match for any sentence.
    words = [word for word in re.split(r"\W+", text.lower()) if len(word) > 1]
    if not words:
        raise BoardError("find needs something to look for")
    scored = []
    for record in records(cfg):
        points = score(record, words)
        if points:
            scored.append((points, record))
    scored.sort(key=lambda pair: (pair[0], pair[1].get("updated") or ""), reverse=True)
    rows = [dict(row_of(cfg, record), score=points) for points, record in scored]
    return rows[:limit] if limit else rows


def show(cfg, board_id: str) -> dict:
    record = read_record(cfg, board_id)
    return dict(row_of(cfg, record), ops=ops_lines(cfg, board_id))


def reopen(cfg, board_id: str, caller: dict | None = None) -> dict:
    """Make this board its source's live board again, so the next push continues it."""
    with store_lock(cfg):
        record = read_record(cfg, board_id)
        may_change(record.get("source") or {}, caller)
        record["closed"] = None
        record["updated"] = now()
        write_record(cfg, record)
        return row_of(cfg, record)


def copy_to_new(cfg, board_id: str, title: str | None = None, actor: str = "cli",
                caller: dict | None = None) -> dict:
    """A new live board holding this one's ops: continue a shape without editing a record.

    THE COPY BELONGS TO THE CALLER, always. Reading a board is open to anyone, so a house
    may take a shape it can see; what it may not do is put a board on somebody else's
    source, because that board would become that source's live one and the next push there
    would land on it. Only he, who owns every source, gets a copy on the original's.
    """
    with store_lock(cfg):
        old = read_record(cfg, board_id)
        source = caller_source(caller) or old.get("source") or {"kind": "talker", "card": None}
        fresh = new_board(cfg, source,
                          title or f"{old.get('title') or 'Untitled board'} (copy)", actor)
        return finish_copy(cfg, board_id, fresh)


def finish_copy(cfg, board_id: str, fresh: dict) -> dict:
    lines = ops_lines(cfg, board_id)
    if lines:
        (board_dir(cfg, fresh["id"]) / OPS_FILE).write_text("\n".join(lines) + "\n")
    model = build(lines)
    fresh["nodes"] = len(model["nodes"])
    fresh["attachments"] = len(model["attachments"])
    fresh["labels"] = labels_of(model)
    fresh["said"] = said_of(model)
    # The copy shows the same files, pointing at the same stored copies. They are not
    # duplicated on disk: a board is a record of what was shown, and a fork of it was shown
    # the same file.
    fresh["files"] = dict(read_record(cfg, board_id).get("files") or {})
    write_record(cfg, fresh)
    return row_of(cfg, fresh)


def close(cfg, board_id: str, summary: str | None = None, caller: dict | None = None) -> dict:
    """Close a board and write what it was about, so `find` has something to score."""
    with store_lock(cfg):
        return end(cfg, board_id, summary, caller)


def end(cfg, board_id: str, summary: str | None, caller: dict | None) -> dict:
    record = read_record(cfg, board_id)
    may_change(record.get("source") or {}, caller)
    record["closed"] = now()
    record["updated"] = record["closed"]
    record["summary"] = summary or " · ".join(record.get("labels") or []) or record.get("title") or ""
    record["summary"] = record["summary"][:MAX_TEXT]
    write_record(cfg, record)
    return row_of(cfg, record)


# ----- what the deck reads -----

def api_board(cfg, board_id: str, since: int = 0) -> dict:
    """One board for the deck: the record, and the accepted lines after `since`.

    The cursor is a LINE COUNT over `ops.log`, markers included, because that is the one
    number both ends can agree on without the deck holding a model. An open board asks for
    what came after the last line it has, on the deck's own polling cadence, and appends it.

    `files` rides WHOLE on every answer rather than after the cursor: it is a handful of
    rows keyed by the path the deck already parsed out of the ops, and its token URLs are
    minted per request, so there is nothing about it to catch up on.
    """
    record = read_record(cfg, board_id)
    lines = ops_lines(cfg, board_id)
    since = max(0, min(int(since or 0), len(lines)))
    return dict(row_of(cfg, record), lines=lines[since:], since=since, next=len(lines),
                files=boardfiles.links(cfg, record))


def inbox(cfg, board, board_id: str, headers, rfile, same_origin: bool, query: str):
    """`POST /api/board/<id>/inbox`: one file HE put on the board (K7).

    The envelope is the segments' (`boardfiles.accept_upload`): same caps, same type table,
    same generated name, same de-duplication, same same-origin rule. What is the board's is
    what happens after it lands: the file goes to the card's own `inbox/`, a `path` op is
    pushed `from you` so it appears on the board like anything else, and the CARD gets a
    note, because a note is what a house reads at its next turn and the board is not
    something a house watches.
    """
    try:
        record = read_record(cfg, board_id)
    except BoardError as error:
        return boardfiles.refuse(404, str(error))
    source = record.get("source") or {}
    # A DROP LANDS ON THE BOARD HE IS LOOKING AT, or it does not land. A push goes to its
    # source's LIVE board, so dropping a file on an older or closed one would file it
    # somewhere he is not looking and say it had worked.
    live = live_record(cfg, source)
    if not live or live["id"] != board_id:
        return boardfiles.refuse(409, f"{board_id} is not the live board for this source, so a "
                                      f"file dropped here would land on another one; open it first")
    destination = boardfiles.inbox_dir(cfg, source, board_dir(cfg, board_id))
    stopped, stored = boardfiles.accept_upload(destination, headers, rfile, same_origin, query)
    if stopped is not None:
        return stopped
    # The row is named what HE called the file, not the name the store generated: the stamp
    # and the fingerprint are right for a filename and wrong for a person reading a board.
    # `slug_of` is what makes that name safe to put in a quoted op.
    name = boardfiles.slug_of(boardfiles.hint_of(query or "") or stored["stored"])
    target = destination / stored["stored"]
    entry = boardfiles.entry_for(target, stored["bytes"], "you", name=name)
    result = push(cfg, f'path board "{target}" size "{entry["size"]}" from you',
                  card=source.get("card"), talker=source.get("kind") == "talker",
                  actor="human", placed={str(target): entry})
    note_arrival(board, source, target, stored)
    return boardfiles.as_json(200, {"ok": True, "stored": stored["stored"],
                                    "bytes": stored["bytes"], "duplicate": stored["duplicate"],
                                    "board": board_id, "attachments": result["attachments"]})


def note_arrival(board, source: dict, target, stored: dict) -> None:
    """Tell the card its house has something new to read. Never fatal: the file is on disk
    and on the board either way, and a board that refused a drop because the note could not
    be written would be refusing for the wrong reason."""
    card = source.get("card")
    if not card or stored.get("duplicate"):
        return
    try:
        board.note(card, f"the user put a file on the board: {target}", "human")
    except Exception:  # noqa: BLE001 - the drop stands without its note
        return


def card_board(cfg, card_id: str) -> dict | None:
    """What a card's pane shows beside plan, output and context: EVERY board that card has,
    newest first, led by the live one. None when it has never been drawn on.

    A CARD HAS AS MANY BOARDS AS IT HAS PICTURES. His words: "a user flow diagram and then a
    database schema diagram both belong to the same story but are different, and the node cap
    would hamper cramming them into one". The pane used to carry the newest one and a count,
    which was the shape of a card having ONE board and a bit of history; one topic per board
    made the rest of them real, so they are listed.

    The newest row's fields stay at the top level, because that is the live board and it is
    what the block leads with.
    """
    rows = listing(cfg, card=card_id)
    if not rows:
        return None
    return dict(rows[0], count=len(rows), boards=rows)


# ----- the verbs -----

def push_from(cfg, args, actor: str) -> dict:
    ops = read_ops(args)
    source = source_of(args.card, args.talker)
    carry(cfg, source, ops, attach=lambda path, blob: boardfiles.attach(cfg, source, path, blob))
    return push(cfg, ops, card=args.card, talker=args.talker, title=args.title,
                actor=actor, caller=local_caller(), card_title=card_title(cfg, args.card),
                new=args.new, board_id=args.board)


def carry(cfg, source: dict, ops: str, attach) -> list[dict]:
    """Read and hand over every file this push names, BEFORE any of it is sent.

    A push whose file could not be read is refused whole, here, where the person or the
    house that named it can still do something about it. The alternative, drawing the row
    and leaving the download broken, is a board that says a file is there when it is not,
    and a board is a record.
    """
    carried = []
    roots = boardfiles.local_roots(cfg, source)
    base = boardfiles.local_base(cfg, source)
    for path_text in path_ops(ops):
        try:
            carried.append(attach(path_text, boardfiles.read_local(path_text, roots,
                                                                   base=base)))
        except boardfiles.BoardFileError as refusal:
            raise BoardError(f"nothing was drawn: {refusal}") from None
    return carried


def local_caller() -> dict:
    """Who is running `keel board` on this machine, in the two facts the rule reads.

    The same environment `kb` resolves an actor from, so a verb run here is held to
    exactly what the same verb would be held to when it travels to another machine's deck.
    """
    return {"actor": actor_of(), "card": os.environ.get("KEEL_CARD")}


def read_ops(args) -> str:
    """The ops: a file when `--file` names one, else stdin.

    A CONFINED HOUSE cannot pipe. The board fence (`bin/keel-board-fence`) allows one plain
    command with no redirect, no heredoc and no pipe, which is the whole point of it, so a
    house with no shell writes its lines to a file in its card directory and names that
    file here. The talker's gateway uses the same door for the same reason.
    """
    if args.file:
        try:
            return Path(args.file).expanduser().read_text(errors="replace")
        except OSError as error:
            raise BoardError(f"cannot read {args.file}: {error}") from None
    import sys
    if sys.stdin is None or sys.stdin.isatty():
        raise BoardError("nothing to draw: give the ops on stdin, or name a file with --file")
    return sys.stdin.read()


def card_title(cfg, card: str | None) -> str | None:
    """The card's own title, the last fallback for a board's name. A board is worth having
    even when the board cannot be read, so this never raises."""
    if not card:
        return None
    try:
        from keel.board import open_board
        board = open_board(cfg)
        try:
            return board.get(card)["title"]
        finally:
            board.close()
    except Exception:  # noqa: BLE001 - a name is not worth failing a push over
        return None


def render_push(result: dict) -> str:
    files = result.get("files") or 0
    if result.get("duplicate"):
        return f"{result['board']}  already drawn (the same ops within {DUP_SECONDS}s)  {result['url']}"
    line = (f"{result['board']}  {result['nodes']} nodes  "
            f"{result['attachments']} attachments")
    if files:
        line += f"  {files} file{'s' if files != 1 else ''}"
    line += f"  {result['url']}"
    if len(result.get("boards") or []) > 1:
        line += f"\nalso drew: {', '.join(result['boards'][:-1])}"
    if result.get("skipped"):
        line += f"\n{result['skipped']} line(s) skipped: " + "; ".join(result.get("reasons") or [])
    return line


def render_rows(rows: list[dict]) -> str:
    out = []
    for row in rows:
        source = row["source"].get("card") or "talker"
        date = (row.get("updated") or "")[:10]
        flags = []
        if row.get("live"):
            flags.append("live")
        if row.get("closed"):
            flags.append("closed")
        if row.get("deleted"):
            flags.append(f"deleted by {row['deleted'].get('by')}, purged {str(row.get('purge_at') or '')[:10]}")
        tail = f"  [{', '.join(flags)}]" if flags else ""
        out.append(f"{row['id']}  {date}  {source:<8} {row['nodes']:>2} nodes "
                   f"{row['attachments']:>3} attached  {row['title']}{tail}")
    return "\n".join(out) or "no boards"


def render_show(payload: dict) -> str:
    return "\n".join(payload["ops"]) or "(nothing drawn yet)"


def render_row(row: dict) -> str:
    return render_rows([row])


# ----- `keel board <verb>` -----

def build_parser():
    import argparse
    parser = argparse.ArgumentParser(prog="keel board", description="the blackboard: draw, find, continue")
    subs = parser.add_subparsers(dest="verb", required=True)

    sub = subs.add_parser("push", help="append ops (stdin, or --file) to the source's live board")
    sub.add_argument("--card", metavar="c-NNN", help="the card whose board this is")
    sub.add_argument("--talker", action="store_true", help="the talker's own board, linked to no card")
    sub.add_argument("--title", help="name the board (otherwise the `board` op, the card)")
    sub.add_argument("--file", metavar="path", help="read the ops from this file instead of stdin")
    sub.add_argument("--new", action="store_true",
                     help="start a fresh board even when one is live; every `board` line starts another")
    sub.add_argument("--board", metavar="b-NNN",
                     help="redraw this board: the push replaces what it shows, under the same id")

    sub = subs.add_parser("list", help="every board, newest first")
    sub.add_argument("--card", metavar="c-NNN", help="only this card's boards")
    sub.add_argument("--limit", type=int, default=0, metavar="N")
    sub.add_argument("--deleted", action="store_true", help="the trash instead: what the user can restore")

    sub = subs.add_parser("find", help="boards matching these words, best first")
    sub.add_argument("text", help="the words to look for")
    sub.add_argument("--limit", type=int, default=0, metavar="N")

    sub = subs.add_parser("show", help="print one board's ops")
    sub.add_argument("id")

    sub = subs.add_parser("open", help="make this board its source's live board again")
    sub.add_argument("id")

    sub = subs.add_parser("new", help="a new live board holding a copy of another one's ops")
    sub.add_argument("--from", dest="from_board", required=True, metavar="b-NNN")
    sub.add_argument("--title")

    sub = subs.add_parser("close", help="close a board and write its summary")
    sub.add_argument("id")
    sub.add_argument("--summary", help="what it was about (default: its node labels)")

    sub = subs.add_parser("delete", help="move boards to the trash, restorable for 30 days "
                                         "(a house: its own card's; the talker: its own)")
    sub.add_argument("ids", nargs="+", metavar="b-NNN")

    sub = subs.add_parser("restore", help="bring a board back from the trash (the user's alone)")
    sub.add_argument("id")

    for name in ("push", "list", "find", "show", "open", "new", "close", "delete", "restore"):
        subs.choices[name].add_argument("--json", action="store_true")
    return parser


def trash():
    """`keel/boardtrash.py`, imported late: it imports this module."""
    from keel import boardtrash                    # noqa: PLC0415 - the one circular import
    return boardtrash


def list_rows(cfg, args) -> list[dict]:
    if getattr(args, "deleted", False):
        return trash().trashed(cfg)
    return listing(cfg, card=args.card, limit=args.limit)


# One row per verb: the handler, and how the payload prints.
HANDLERS = {
    "push": (push_from, render_push),
    "list": (lambda cfg, a, actor: list_rows(cfg, a), render_rows),
    "find": (lambda cfg, a, actor: find(cfg, a.text, limit=a.limit), render_rows),
    "show": (lambda cfg, a, actor: show(cfg, a.id), render_show),
    "open": (lambda cfg, a, actor: reopen(cfg, a.id, caller=local_caller()), render_row),
    "new": (lambda cfg, a, actor: copy_to_new(cfg, a.from_board, a.title, actor,
                                              caller=local_caller()), render_row),
    "close": (lambda cfg, a, actor: close(cfg, a.id, a.summary, caller=local_caller()), render_row),
    "delete": (lambda cfg, a, actor: trash().delete(cfg, a.ids, trash().local_caller(cfg)),
               lambda payload: trash().render_deleted(payload)),
    "restore": (lambda cfg, a, actor: trash().restore(cfg, a.id, trash().local_caller(cfg)), render_row),
}


def main(argv: list[str]) -> int:
    """`keel board <verb>`, against this machine's board."""
    import sys
    from keel import config as config_module
    args = build_parser().parse_args(argv)
    handler, render = HANDLERS[args.verb]
    try:
        config = config_module.load()
        if config.scratch:
            print(f"keel board: {config.scratch_note}", file=sys.stderr)
        payload = handler(config, args, actor_of())
    except (BoardError, config_module.ConfigError) as refusal:
        print(f"keel board: {refusal}", file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001 - one line, as a refusal reads
        print(f"keel board: {error}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        print(render(payload))
    return 0


def actor_of() -> str:
    """Who is drawing, by the same rule `kb` uses: the environment says it, not the line.

    `KEEL_CARD` means a house. `KEEL_TALKER` is what the talker's own session carries, so
    its boards are recorded as the talker's rather than as a terminal's. Anything else is
    a person at a terminal.
    """
    if os.environ.get("KEEL_CARD"):
        return "house"
    if os.environ.get("KEEL_TALKER"):
        return "talker"
    return "cli"
