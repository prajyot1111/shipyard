"""The fenced blocks of the plan format: one small grammar per block kind.

A fenced block names its kind in its info string (the B17 pattern the board already uses)
and carries a small body of `key: value` lines. Every parser here is PERMISSIVE about what
it reads and HONEST about what it did not like: a block always comes back, with anything
wrong said in its `problems`, and `keel/planlint.py` turns those into refusals. One bad
option costs that option, never the plan, which is the board's "one bad line costs one
line" (B4) carried over.

The kinds, and the shape each returns, are specified in `docs/plan-format.md`.
"""

from __future__ import annotations

import re

from keel import boards, planmermaid
from keel.planinline import spans

KV = re.compile(r"^(?P<key>[A-Za-z][\w-]*)(?:\s+(?P<arg>[A-Za-z0-9][\w.-]*))?\s*:\s?(?P<value>.*)$")
ID_RE = re.compile(r"^[A-Za-z0-9][\w.-]{0,47}$")
# A batch row's key may hold a dot (`webapp-react.c21`, the watcher's handle for an item
# from a card's second pull request); every other block keys its lines by `KV`. Such a key
# is kept as written, since its repo part routes the reply, and may run past ID_RE's 48
# (`<repo>.review-<a 30 character reviewer slug>`).
ROW = re.compile(r"^(?P<key>[A-Za-z0-9][\w-]*\.[\w.-]*)\s*:\s?(?P<value>.*)$")
ROW_MAX = 96
STEP_STATES = ("todo", "doing", "done", "blocked")
TONES = ("good", "warn", "bad", "accent")
FRAMES = ("phone", "desktop", "wide")
YES = ("yes", "true", "on", "1")
NO = ("no", "false", "off", "0")
BOARD_REF = re.compile(r"^(?:board\s+)?(b-\d+)$")
MAX_OPTIONS = 4


class Block(dict):
    """A block is a dict (it goes to the page as JSON) with a problem list beside it."""

    def problem(self, text: str) -> None:
        self.setdefault("problems", []).append(text)


def pairs(lines: list[str]):
    """`key: value` lines, each with the indented lines under it: (key, arg, value, under)."""
    out, current = [], None
    for raw in lines:
        if not raw.strip():
            continue
        if raw[:1] in (" ", "\t") and current is not None:
            current[3].append(raw.strip())
            continue
        match = KV.match(raw.strip())
        if match:
            current = (match["key"].lower(), match["arg"], match["value"].strip(), [])
        else:
            current = ("", None, raw.strip(), [])
        out.append(current)
    return out


def flag(value: str, default: bool) -> bool:
    low = (value or "").strip().lower()
    return True if low in YES else False if low in NO else default


def option_of(arg: str | None, value: str, under: list[str], block: Block) -> dict:
    option = {"id": arg or "", "label": spans(value), "text": value}
    body = []
    for line in under:
        match = KV.match(line)
        key = match["key"].lower() if match else ""
        if key in ("gets", "cost", "summary"):
            option[key] = spans(match["value"].strip())
        elif key in ("pro", "con"):
            option.setdefault(key + "s", []).append(spans(match["value"].strip()))
        else:
            body.append(line)
    if body:
        option["body"] = spans(" ".join(body))
    if not option["id"] or not ID_RE.match(option["id"]):
        block.problem(f"an option needs an id: `option a: <label>` (got {value[:40]!r})")
    return option


def recommend(block: Block, rec: str | None, options: list[dict], what: str) -> None:
    ids = [o["id"] for o in options]
    if not rec:
        block.problem(f"{what} carries no recommendation: add `rec: <option id>`")
    elif rec not in ids:
        block.problem(f"{what} recommends {rec!r}, which is not one of its options ({', '.join(ids)})")
    else:
        block["rec"] = rec


def decision(info: str, lines: list[str]) -> Block:
    block = Block(type="decision", id=info.split()[0] if info.split() else "", options=[],
                  other=True)
    rec = None
    for key, arg, value, under in pairs(lines):
        if key == "q":
            block["q"] = spans(value)
            block["q_text"] = value
        elif key in ("why", "context"):
            block["why"] = spans(" ".join([value, *under]).strip())
        elif key == "option":
            block["options"].append(option_of(arg, value, under, block))
        elif key in ("rec", "recommend"):
            rec = value.split()[0] if value.split() else ""
        elif key == "because":
            block["because"] = spans(" ".join([value, *under]).strip())
        elif key == "other":
            block["other"] = flag(value, True)
        elif key == "after":
            block["after"] = value.strip()
        else:
            block.problem(f"a decision does not know the line {value[:40]!r}")
    if not ID_RE.match(block["id"] or ""):
        block.problem("a decision needs an id in its info string: ```decision <id>")
    if "q" not in block:
        block.problem(f"decision {block['id']} has no `q:` line saying what is asked")
    if len(block["options"]) < 2:
        block.problem(f"decision {block['id']} has {len(block['options'])} option(s); a decision offers at least two")
    if len(block["options"]) > MAX_OPTIONS:
        block.problem(f"decision {block['id']} has {len(block['options'])} options; at most {MAX_OPTIONS}")
    for option in block["options"]:
        if "cost" not in option:
            block.problem(f"option {option['id']} of {block['id']} says no `cost:`; its cost is as visible as its benefit")
    recommend(block, rec, block["options"], f"decision {block['id']}")
    if rec and not block.get("because"):
        block.problem(f"decision {block['id']} recommends {rec} without a `because:`")
    return block


def batch(info: str, lines: list[str]) -> Block:
    """Many small verdicts at once (triage, review findings): one row per item."""
    block = Block(type="batch", id=info.split()[0] if info.split() else "", rows=[], choices=[])
    for key, arg, value, under in pairs(lines):
        if key == "q":
            block["q"] = spans(value)
        elif key == "choices":
            block["choices"] = [c.strip() for c in value.split(",") if c.strip()]
        elif key and arg is None and ID_RE.match(key):
            block["rows"].append(batch_row(key, value, block))
        elif not key and (row := ROW.match(value)) and len(row["key"]) <= ROW_MAX:
            block["rows"].append(batch_row(row["key"], row["value"].strip(), block))
        else:
            block.problem(f"a batch does not know the line {value[:40]!r}")
    if len(block["choices"]) < 2:
        block.problem(f"batch {block['id']} needs `choices:` with at least two")
    for row in block["rows"]:
        if row.get("rec") not in block["choices"]:
            block.problem(f"row {row['id']} of {block['id']} recommends {row.get('rec')!r}, not one of the choices")
    if not ID_RE.match(block["id"] or ""):
        block.problem("a batch needs an id in its info string: ```batch <id>")
    return block


def batch_row(key: str, value: str, block: Block) -> dict:
    parts = [p.strip() for p in value.split("|")]
    row = {"id": key, "text": spans(parts[0])}
    if len(parts) > 1:
        row["rec"] = parts[1]
    if len(parts) > 2:
        row["why"] = spans(parts[2])
    return row


def options(info: str, lines: list[str]) -> Block:
    block = Block(type="options", id=info.split()[0] if info.split() else "", options=[])
    rec = None
    for key, arg, value, under in pairs(lines):
        if key == "option":
            block["options"].append(option_of(arg, value, under, block))
        elif key in ("rec", "recommend"):
            rec = value.split()[0] if value.split() else ""
        elif key == "decision":
            block["decision"] = value.strip()
        else:
            block.problem(f"an options block does not know the line {value[:40]!r}")
    if len(block["options"]) < 2:
        block.problem("an options block compares at least two options")
    recommend(block, rec, block["options"], "the options block")
    return block


def compare(info: str, lines: list[str]) -> Block:
    """Current against target, as the same system on both sides (C3): paired rows."""
    block = Block(type="compare", title=spans(info), left="", right="", rows=[])
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        match = KV.match(line)
        if match and match["key"].lower() in ("left", "right") and "|" not in line:
            block[match["key"].lower()] = match["value"].strip()
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) != 3:
            block.problem(f"a compare row is `aspect | left | right`, got {line[:40]!r}")
            continue
        aspect, left, right = cells
        if aspect.lower() == "image":
            block["rows"].append({"image": True, "left": left, "right": right})
        else:
            block["rows"].append({"aspect": spans(aspect), "left": spans(left), "right": spans(right)})
        if not left or not right:
            block.problem(f"compare row {aspect[:30]!r} is missing a side; both sides say something")
    if not block["left"] or not block["right"]:
        block.problem("a compare names both sides: `left: <label>` and `right: <label>`")
    if not block["rows"]:
        block.problem("a compare holds at least one row")
    return block


def questions(info: str, lines: list[str]) -> Block:
    block = Block(type="questions", items=[])
    for key, arg, value, under in pairs(lines):
        text = " ".join([value, *under]).strip()
        if key == "q":
            block["items"].append({"q": spans(text), "q_text": text})
        elif key in ("rec", "recommend") and block["items"]:
            block["items"][-1]["rec"] = spans(text)
        elif key == "why" and block["items"]:
            block["items"][-1]["why"] = spans(text)
        elif key == "none":
            block["none"] = spans(text)
        else:
            block.problem(f"a questions block does not know the line {value[:40]!r}")
    return block


STEP = re.compile(r"^(?:\[(?P<state>\w+)\]\s*)?(?P<rest>.+)$")


def steps(info: str, lines: list[str]) -> Block:
    block = Block(type="steps", items=[], title=spans(info))
    for raw in lines:
        line = raw.strip().lstrip("-*").strip()
        if not line:
            continue
        match = STEP.match(line)
        state = (match["state"] or "todo").lower()
        title, _, body = match["rest"].partition("|")
        if state not in STEP_STATES:
            block.problem(f"a step's state is one of {', '.join(STEP_STATES)}, got {state!r}")
            state = "todo"
        item = {"title": spans(title.strip()), "state": state}
        if body.strip():
            item["body"] = spans(body.strip())
        block["items"].append(item)
    return block


def stats(info: str, lines: list[str]) -> Block:
    block = Block(type="stats", tiles=[])
    for raw in lines:
        if not raw.strip():
            continue
        cells = [c.strip() for c in raw.split("|")]
        tile = {"label": cells[0], "value": cells[1] if len(cells) > 1 else ""}
        if len(cells) > 2 and cells[2]:
            tile["sub"] = cells[2]
        if len(cells) > 3 and cells[3]:
            tile["tone"] = cells[3] if cells[3] in TONES else ""
        block["tiles"].append(tile)
    if not 1 <= len(block["tiles"]) <= 6:
        block.problem("a stats block holds one to six tiles")
    return block


def copy(info: str, lines: list[str]) -> Block:
    return Block(type="copy", title=info.strip() or "Copy", text="\n".join(lines).strip("\n"))


def code(kind: str, info: str, lines: list[str]) -> Block:
    """```<lang> [path[:lines]] [| why]```: the path and the reason sit above the code (C8)."""
    head, _, why = info.partition("|")
    words = head.split()
    block = Block(type="code", lang=kind, text="\n".join(lines))
    if words:
        block["path"] = words[0]
    if why.strip():
        block["why"] = spans(why.strip())
    return block


def diff(info: str, lines: list[str]) -> Block:
    block = code("diff", info, lines)
    block["type"] = "diff"
    return block


def mermaid(info: str, lines: list[str]) -> Block:
    """A flowchart, a sequence or a state diagram, TRANSLATED into board ops (B2 keeps a
    third party's parser off the deck's origin), and drawn by the board's own renderer."""
    result = planmermaid.translate("\n".join(lines))
    block = Block(type="diagram", source="mermaid", kind=result["kind"], ops=result["ops"],
                  title=spans(info.strip()) if info.strip() else [])
    for problem in result["problems"]:
        block.problem(problem)
    return block


def board(info: str, lines: list[str]) -> Block:
    """A live board by id (`b-12`), or board ops drawn in place."""
    body = [line for line in lines if line.strip()]
    if len(body) == 1 and BOARD_REF.match(body[0].strip()):
        # the id as the store spells it (`b-001`), so `b-1` and `b-001` are one board
        number = int(BOARD_REF.match(body[0].strip()).group(1)[2:])
        return Block(type="board", ref=f"b-{number:03d}",
                     title=spans(info.strip()) if info.strip() else [])
    block = Block(type="diagram", source="board", kind="board", ops=body,
                  title=spans(info.strip()) if info.strip() else [])
    nodes = set()
    for line in body:
        try:
            op = boards.parse_line(line)
        except boards.BadLine as error:
            block.problem(f"board line {line.strip()[:40]!r}: {error}")
            continue
        if op and op.get("op") == "node":
            nodes.add(op["id"])
    if len(nodes) > boards.MAX_NODES:
        block.problem(f"a board holds at most {boards.MAX_NODES} nodes; this one names {len(nodes)}: split it")
    return block


def finding(info: str, lines: list[str]) -> Block:
    """One review finding, whole (lane FC): `keel/planfinding.py`."""
    from keel import planfinding       # imported late: it imports this module's grammar
    return planfinding.parse(info, lines)


def details(info: str, lines: list[str], parse_body) -> Block:
    return Block(type="details", summary=spans(info.strip() or "Details"), blocks=parse_body(lines))


SIMPLE = {"decision": decision, "batch": batch, "options": options, "compare": compare,
          "questions": questions, "steps": steps, "stats": stats, "copy": copy,
          "diff": diff, "mermaid": mermaid, "board": board, "finding": finding}
KINDS = (*SIMPLE, "details", "code")


def fenced(kind: str, info: str, lines: list[str], parse_body) -> Block:
    """The block a fence of this kind (its info string's first word) makes."""
    kind = (kind or "").lower()
    if kind in SIMPLE:
        return SIMPLE[kind](info, lines)
    if kind == "details":
        return details(info, lines, parse_body)
    return code(kind or "text", info, lines)
