"""The `finding` block (lane FC, FC-1): one review finding, whole.

A review card's outcome used to split a finding across three places: a row in ONE findings
batch (post, edit or drop), its drafted comment in a `copy comment <row>` block further
down, and its code in a Snippets section at the end. He read a row, scrolled for its words,
scrolled again for its code. Each finding is now one block, and the deck draws it as one
card (`app/ui.planfinding.js`), its code pulled from the member's worktree at render
(`keel/planexcerpt.py`), so a house never copies code into the outcome and it cannot drift.

    ```finding r1-f1
    severity: high                      critical | high | medium | low
    member: cloud#4150                  a feature card's member pull request (lane GRP)
    at: app/loader.py:40                or 40-44: where the comment is posted
    claim: the one line it says
    evidence: why it holds
    verifier: kept                      kept | unverified | disputed, and when disputed:
      for: the reviewer's side
      against: the verifier's side
    suggestion: what to do about it
    comment:
      The words to post, as written: its lines and
      its paragraphs kept.
    choice: post                        post | edit | drop, the recommendation
    because: why that choice
    ```

Permissive and honest like every block (`keel/planblocks.py`): it always comes back, with
what is wrong in `problems`, which the lint reads as C29 (`planlint.rule_for`).
"""

from __future__ import annotations

import re

from keel.planblocks import ID_RE, KV, Block
from keel.planinline import ref_span, spans

CHOICES = ("post", "edit", "drop")
SEVERITIES = ("critical", "high", "medium", "low")
VERIFIER_WORDS = ("kept", "unverified", "disputed")
AT = re.compile(r"^`?(?P<v>[\w./-]+:\d+(?:-\d+)?)`?$")
SPAN_FIELDS = ("claim", "evidence", "suggestion", "because")


def parse(info: str, lines: list[str]) -> Block:
    block = Block(type="finding", id=(info.split()[0] if info.split() else "").lower(), choices=list(CHOICES))
    for key, value, under in pairs(lines):
        field(block, key, value, under)
    checks(block)
    return block


def pairs(lines: list[str]) -> list[tuple]:
    """(key, value, indented lines under it). `comment:` is different: its value is every
    line under it, blank ones too, so a comment keeps its paragraphs."""
    out, comment = [], None
    for raw in lines:
        indented = raw[:1] in (" ", "\t")
        if comment is not None and (indented or not raw.strip()):
            comment.append(raw.strip())
            continue
        comment = None
        if not raw.strip():
            continue
        if indented and out:
            out[-1][2].append(raw.strip())
            continue
        match = KV.match(raw.strip())
        key = match["key"].lower() if match else ""
        value = match["value"].strip() if match else raw.strip()
        if key == "comment":
            comment = [value] if value else []
            out.append(("comment", comment, []))
        else:
            out.append((key, value, []))
    return out


def field(block: Block, key: str, value, under: list[str]) -> None:
    if key == "comment":
        block["comment"] = unwrapped(value)
    elif key == "severity":
        block["severity"] = value.lower()
    elif key == "member":
        block["member"] = value
    elif key == "at":
        at_of(block, value)
    elif key == "verifier":
        block["verifier"] = value.lower()
        for side, words in (sided(line) for line in under):
            if side:
                block[side] = spans(words)
    elif key in ("choice", "rec", "recommend"):
        block["rec"] = value.lower()
    elif key in SPAN_FIELDS:
        block[key] = spans(" ".join([value, *under]).strip())
    else:
        block.problem(f"a finding does not know the line {str(value)[:40]!r}")


LIST_LINE = re.compile(r"^([-*+]|\d+[.)])\s")


def unwrapped(lines: list[str]) -> str:
    """A comment as it is posted: its paragraphs kept, and a line the house wrapped at the
    fence's width joined to the one before, as markdown reads it (a list item, and a
    fenced code sample, keep their lines)."""
    out, fenced = [], False
    for line in lines:
        if line.startswith("```"):
            fenced = not fenced
        joins = out and out[-1] and line and not fenced and not line.startswith("```") \
            and not LIST_LINE.match(line) and not out[-1].startswith("```")
        if joins:
            out[-1] += " " + line
        else:
            out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out).strip("\n"))


def sided(line: str) -> tuple[str | None, str]:
    match = KV.match(line)
    if match and match["key"].lower() in ("for", "against"):
        return match["key"].lower(), match["value"].strip()
    return None, ""


def at_of(block: Block, value: str) -> None:
    match = AT.match(value)
    if not match:
        block.problem(f"finding {block['id']} says where with `at: path:line` (path/to/file.py:40, or 40-44), "
                      f"not {value[:40]!r}")
        return
    ref = ref_span("path", match["v"])
    block.update(path=ref["path"], start=ref["start"], end=ref["end"], at=[ref])


def checks(block: Block) -> None:
    name = f"finding {block['id'] or '(no id)'}"
    if not ID_RE.match(block["id"] or ""):
        block.problem("a finding needs an id in its info string: ```finding <id>")
    if block.get("severity") not in SEVERITIES:
        block.problem(f"{name}'s severity is one of {', '.join(SEVERITIES)}, not {block.get('severity')!r}")
    if "path" not in block and not any("`at:" in p for p in block.get("problems", [])):
        block.problem(f"{name} names no `at: path:line` to post its comment at")
    if not block.get("claim"):
        block.problem(f"{name} has no `claim:`, the one line it says")
    if not str(block.get("comment") or "").strip():
        block.problem(f"{name} has no drafted `comment:`, the words to post")
    if block.get("verifier") not in VERIFIER_WORDS:
        block.problem(f"{name}'s verifier word is one of {', '.join(VERIFIER_WORDS)}, "
                      f"not {block.get('verifier')!r}")
    elif block["verifier"] == "disputed" and not (block.get("for") and block.get("against")):
        block.problem(f"{name} is disputed: give both sides, an indented `for:` and `against:`")
    if block.get("rec") not in CHOICES:
        block.problem(f"{name}'s `choice:` is post, edit or drop, not {block.get('rec')!r}")
