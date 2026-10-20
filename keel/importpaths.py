"""The path rewrite `shipyard import` makes (c-620): pure functions, no file and no board.

A board copied off another machine stores absolute paths under that machine's state root:
`/home/ubuntu/keel/state/cards/c-1/plan.md` from the box, `/Users/<him>/keel/state/...` from
the laptop. The OLD ROOTS are found from the stored values themselves, as every prefix that
ends in `/<checkout>/state/` (the old checkout's name, `keel` unless the old config says
otherwise, and the first such prefix in the path), so a work path that merely has a `state/`
in it is never taken for a root. Each maps to the install's `<dir>/state/`; `--root OLD=NEW`
maps one by hand, and names a root that is not shaped so.

Only a VALUE under an old root moves: a string that starts with one. A path mentioned inside
free text (a brief, a note, an event's words) is counted, never rewritten.
docs/atlas/87-import.md has the whole of it.
"""

from __future__ import annotations

import re
from collections import Counter

DEFAULT_CHECKOUT = "keel"


def root_pattern(checkout: str = DEFAULT_CHECKOUT) -> re.Pattern:
    """A `/.../<checkout>/state/` prefix that starts a path: not inside a word, a URL or
    another path."""
    return re.compile(r"(?<![\w.~/:-])(/(?:[^/\s\"'<>|`()\[\]{},;]+/)*?"
                      + re.escape(checkout) + r"/state/)")


class RootError(ValueError):
    """A `--root` that is not `OLD=NEW` with both sides absolute."""


def roots_in(text: str, checkout: str = DEFAULT_CHECKOUT) -> list[str]:
    """Every state root a string mentions, in order."""
    return root_pattern(checkout).findall(text or "")


def strings(value):
    """Every string inside a JSON value, depth first."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def find_roots(values, own: str | None = None, checkout: str = DEFAULT_CHECKOUT) -> Counter:
    """How often each old state root is mentioned across `values` (strings or JSON values);
    the install's own root is never an old one."""
    found, pattern = Counter(), root_pattern(checkout)
    for value in values:
        for text in strings(value):
            found.update(root for root in pattern.findall(text) if root != own)
    return found


def with_slash(path: str) -> str:
    return path if path.endswith("/") else path + "/"


def parse_root(item: str) -> tuple[str, str]:
    """`OLD=NEW`, each made to end in `/`."""
    old, sep, new = item.partition("=")
    if not sep or not old.startswith("/") or not new.startswith("/"):
        raise RootError(f"--root wants OLD=NEW with both paths absolute, not {item!r}")
    return with_slash(old), with_slash(new)


def mapping(found, target: str, overrides=()) -> dict[str, str]:
    """Every old root to `target`, unless an override names it (an override may also add a
    root nothing stored mentions)."""
    chosen = {root: with_slash(target) for root in found}
    chosen.update(dict(overrides))
    return chosen


def ordered(roots: dict[str, str]) -> list[tuple[str, str]]:
    """Longest first, so a root inside another root wins."""
    return sorted(roots.items(), key=lambda pair: len(pair[0]), reverse=True)


def moved(value: str, roots: dict[str, str]) -> str | None:
    """`value` under its new root when it starts with an old one, else None."""
    for old, new in ordered(roots):
        if value.startswith(old):
            return new + value[len(old):]
    return None


def rewrite(value, roots: dict[str, str], where: str = "$"):
    """`(new value, [(where, old, new)])`: every string in a JSON value that starts with an
    old root moved, everything else kept as it is."""
    if isinstance(value, str):
        new = moved(value, roots)
        return (new, [(where, value, new)]) if new is not None else (value, [])
    if isinstance(value, dict):
        out, changes = {}, []
        for key, item in value.items():
            out[key], found = rewrite(item, roots, f"{where}.{key}")
            changes += found
        return out, changes
    if isinstance(value, list):
        out, changes = [], []
        for index, item in enumerate(value):
            new, found = rewrite(item, roots, f"{where}[{index}]")
            out.append(new)
            changes += found
        return out, changes
    return value, []


def leftovers(value, roots) -> list[str]:
    """Every string in a JSON value still stored under one of `roots` (a value, not a mention)."""
    return [text for text in strings(value) if any(text.startswith(old) for old in roots)]


def mentions(text: str, roots) -> int:
    """How many times free text mentions an old root (counted, never rewritten)."""
    return sum((text or "").count(old) for old in roots)
