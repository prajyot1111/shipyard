"""The inline half of the plan format: a line of markdown cut into typed spans.

A house writes plain markdown inside every block. The deck never receives that markdown as
HTML: this module cuts it into spans (`text`, `code`, `strong`, `em`, `link`, `ref`) and the
page builds each span with `textContent`, exactly as the board builds a node. So a plan a
house wrote after reading a hostile page still has nowhere to hide a script.

Four kinds of reference are recognised in running text and turned into `ref` spans, because
they are what a plan points at (inventory item 5, 271 of 335 surfaces carry one):

- `c-NNN`, a card on this board;
- `ticket`, a tracker's ticket, in the shape the card's space names (`ticket_ref` in its
  pack's `[terms]`, `keel/terms.py`; the adapter names what it is, this module does not);
- `change`, the space's short change word and a number, such as `<change_short> #12`;
- `path:line` or `path:start-end`, a line of code. Inside backticks or not: the corpus puts
  them in backticks far more often than not, so a code span that is exactly a path with a
  line is a `ref` too, and keeps its code face.

The ticket and change refs are the card's space's (c-630): `spans(text, refs)` takes the
pattern `terms.refs` builds, and `planformat.parse(text, name, refs)` hands it to every span
of the document through `using`. With none, only cards and paths are linked.

The lint (`keel/planlint.py`) resolves every `path` ref against the worktree at HEAD.
"""

from __future__ import annotations

import contextvars
import re
from contextlib import contextmanager

CARD = r"c-\d{3,}"
# A path that has an extension starting with a letter, or is a build file that has none,
# then a line or a range. A build file is a capitalised name ending in `file` under a
# directory (`ci/<Name>file:9`), or one of the common ones bare (`Dockerfile:24`); a bare
# word like `Profile:2` in prose is not one. `12:30`, the ratio `4.5:1` and the version
# `3.12:40` are not one either; `https://x.y:80` is cut out before this runs because a link
# is matched first.
BUILD_FILES = r"(?:(?:[\w.-]+/)+[A-Z][a-z]+file|Dockerfile|Containerfile|Makefile|Procfile|Gemfile|Rakefile|Vagrantfile)"
PATH_LINE = rf"(?:{BUILD_FILES}|[A-Za-z0-9_][\w./-]*\.[A-Za-z][A-Za-z0-9]*):\d+(?:-\d+)?"


def ref_regex(ticket: str | None = None, change: str | None = None) -> re.Pattern:
    """The reference pattern: cards and paths, and a ticket and a change when their regex
    bodies are given (`terms.refs` gives a space's)."""
    kinds = [("card", CARD)] + [(kind, body) for kind, body in (("ticket", ticket), ("change", change))
                                if body] + [("path", PATH_LINE)]
    alternatives = "|".join(f"(?P<{kind}>{body})" for kind, body in kinds)
    return re.compile(rf"(?<![\w/-])(?:{alternatives})(?![\w-])")


REF = ref_regex()
_refs: contextvars.ContextVar = contextvars.ContextVar("planinline_refs", default=REF)


@contextmanager
def using(refs: re.Pattern | None):
    """Every `spans` call inside reads `refs` (None: cards and paths only)."""
    token = _refs.set(refs or REF)
    try:
        yield
    finally:
        _refs.reset(token)
PATH_ONLY = re.compile(rf"^{PATH_LINE}$")
# Markdown's own inline marks, in the order they are looked for. A code span first, so a
# `*` inside backticks is code and never emphasis.
INLINE = re.compile(
    r"(?P<code>`[^`\n]+`)"
    r"|(?P<img>!\[[^\]\n]*\]\([^)\s]+\))"
    r"|(?P<link>\[[^\]\n]+\]\([^)\s]+\))"
    r"|(?P<strong>\*\*[^*\n]+?\*\*)"
    r"|(?P<em>(?<![\w*])\*[^*\s][^*\n]*?\*(?![\w*]))"
    r"|(?P<url>https?://[^\s)<>]+)")


def ref_span(kind: str, value: str) -> dict:
    span = {"t": "ref", "kind": kind, "v": value}
    if kind == "path":
        path, _, lines = value.rpartition(":")
        start, _, end = lines.partition("-")
        span.update(path=path, start=int(start), end=int(end or start))
    elif kind == "change":
        span["n"] = int(value.rsplit("#", 1)[1])
    return span


def refs_in(text: str, refs: re.Pattern | None = None) -> list[dict]:
    """Plain text with its references lifted out: text and `ref` spans, in order."""
    out, at = [], 0
    for match in (refs or _refs.get()).finditer(text):
        if match.start() > at:
            out.append({"t": "text", "v": text[at:match.start()]})
        kind = match.lastgroup
        out.append(ref_span(kind, match.group(kind)))
        at = match.end()
    if at < len(text):
        out.append({"t": "text", "v": text[at:]})
    return out


def spans(text: str, refs: re.Pattern | None = None) -> list[dict]:
    """One line (or a paragraph joined with spaces) of inline markdown, as spans. `refs` is
    the space's reference pattern; None reads the one `using` set, or cards and paths."""
    if refs is not None:
        with using(refs):
            return spans(text)
    text = text or ""
    out, at = [], 0
    for match in INLINE.finditer(text):
        if match.start() > at:
            out.extend(refs_in(text[at:match.start()]))
        out.append(mark_span(match.lastgroup, match.group(0)))
        at = match.end()
    if at < len(text):
        out.extend(refs_in(text[at:]))
    return merge_text(out)


def mark_span(kind: str, raw: str) -> dict:
    if kind == "code":
        body = raw[1:-1]
        if PATH_ONLY.match(body):
            return dict(ref_span("path", body), code=True)
        return {"t": "code", "v": body}
    if kind == "strong":
        return {"t": "strong", "c": spans(raw[2:-2])}
    if kind == "em":
        return {"t": "em", "c": spans(raw[1:-1])}
    if kind == "url":
        return {"t": "link", "href": raw, "v": raw}
    label, _, href = raw.lstrip("!")[1:-1].partition("](")
    if kind == "img":
        return {"t": "link", "href": href, "v": label or href, "img": True}
    return {"t": "link", "href": href, "v": label}


def merge_text(out: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for span in out:
        if span["t"] == "text" and merged and merged[-1]["t"] == "text":
            merged[-1] = {"t": "text", "v": merged[-1]["v"] + span["v"]}
        elif span["t"] != "text" or span["v"]:
            merged.append(span)
    return merged


def plain(items: list[dict]) -> str:
    """The words a list of spans says, with no marks: what a quote is compared against."""
    words = []
    for span in items:
        if "c" in span:
            words.append(plain(span["c"]))
        else:
            words.append(str(span.get("v", "")))
    return "".join(words)


def walk_refs(items: list[dict]):
    """Every `ref` span in a list of spans, nested ones included."""
    for span in items:
        if span.get("t") == "ref":
            yield span
        if "c" in span:
            yield from walk_refs(span["c"])


def walk_links(items: list[dict]):
    for span in items:
        if span.get("t") == "link":
            yield span
        if "c" in span:
            yield from walk_links(span["c"])
