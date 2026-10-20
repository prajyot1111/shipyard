"""Edits to an install's `config.toml` that keep every byte they do not change (c-618).

The deck's Setup view (`keel/onboarding.py`) adds a repo, removes one and turns a pack on
by editing the file a person also edits by hand, so nothing here re-serialises it: a
change is made to the text of one table and every comment, blank line and key order around
it is kept. Only plain `[table]` headers at column 0 are found; a table written inline
(`repos = {...}`) is refused with "edit by hand" rather than rewritten.

`write` is the one way the result reaches disk: refused when the file changed since it was
read, parsed before it is written, the old file kept under `config-backups/` (the last
ten), written in one rename keeping its mode, then loaded as Keel loads it, and put back
from the backup when that load fails.
"""

from __future__ import annotations

import hashlib
import math
import re
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from keel import atomicfile

BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
COMMENTED_TABLE = re.compile(r"^\s*#\s*\[")
KEEP_BACKUPS = 10


class EditError(Exception):
    """An edit that was not made; the message says why."""


def literal(value) -> str:
    """`value` as a TOML literal: a string, an int, a float (the Settings view's, c-633), a
    bool or a list of strings."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return repr(value)
    if isinstance(value, (str, Path)):
        return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        return "[" + ", ".join(literal(item) for item in value) + "]"
    raise EditError(f"{value!r} is not a value Setup writes (a string, a number, true or false, a list of strings)")


def key_text(key: str) -> str:
    return key if BARE_KEY.match(key) else literal(key)


def header_of(line: str) -> str | None:
    """The table a `[name]` line at column 0 opens, or None. `[[...]]` is not one."""
    if not line.startswith("[") or line.startswith("[["):
        return None
    head = line.split("#", 1)[0].strip()
    return head[1:-1].strip() if head.endswith("]") else None


def headers(lines: list[str]) -> list[tuple[int, str | None]]:
    """Each line that opens a table (`[x]` or `[[x]]`), outside a multi-line string."""
    found, inside = [], None
    for number, line in enumerate(lines):
        if inside is None and line.startswith("["):
            found.append((number, header_of(line)))
        for quote in ('"""', "'''"):
            if line.count(quote) % 2 and inside in (None, quote):
                inside = None if inside == quote else quote
    return found


def span(text: str, table: str) -> tuple[int, int] | None:
    """The lines of `[table]`: from its header to its last key line (the comments and
    blank lines that lead into the next table are not its own), or None."""
    lines = text.splitlines()
    opened = headers(lines)
    for index, (number, name) in enumerate(opened):
        if name == table:
            end = opened[index + 1][0] if index + 1 < len(opened) else len(lines)
            return number, own_end(lines, number, end)
    return None


def own_end(lines: list[str], start: int, end: int) -> int:
    """Where a table's own lines end: trailing blanks dropped, and a comment block that a
    blank line parts from the table (it leads into what follows) dropped with them."""
    def blank(n): return not lines[n].strip()
    def comment(n): return lines[n].lstrip().startswith("#")
    while True:
        while end - 1 > start and blank(end - 1):
            end -= 1
        top = end
        while top - 1 > start and comment(top - 1):
            top -= 1
        if top == end or top - 1 <= start or not blank(top - 1):
            return end
        end = top


def entry_line(lines: list[str], start: int, end: int, key: str) -> int | None:
    pattern = re.compile(rf"^\s*{re.escape(key_text(key))}\s*=")
    return next((n for n in range(start + 1, end) if pattern.match(lines[n])), None)


def refuse_inline(text: str, table: str) -> None:
    """`[a.b]` written inline as `b = {...}` under `[a]`: Setup does not rewrite that."""
    parent, _, leaf = table.rpartition(".")
    where = span(text, parent) if parent else None
    if where and entry_line(text.splitlines(), *where, leaf) is not None:
        raise EditError(f"[{table}] is written inline in [{parent}]; edit it by hand")


def joined(lines: list[str], ending: bool) -> str:
    return "\n".join(lines) + ("\n" if ending else "")


def set_entry(text: str, table: str, key: str, value) -> str:
    """`key = value` in `[table]`: replaced where it is, else added after the table's last
    key, else the table is added at the end of the file."""
    line = f"{key_text(key)} = {literal(value)}"
    where = span(text, table)
    if where is None:
        refuse_inline(text, table)
        return append_table(text, table, {key: value})
    lines = text.splitlines()
    found = entry_line(lines, *where, key)
    if found is not None:
        lines[found] = line
    else:
        lines.insert(where[1], line)
    return joined(lines, True)


def remove_entry(text: str, table: str, key: str) -> str:
    where = span(text, table)
    if where is None:
        refuse_inline(text, table)
        raise EditError(f"there is no [{table}] in the config")
    lines = text.splitlines()
    found = entry_line(lines, *where, key)
    if found is None:
        raise EditError(f"[{table}] has no {key}")
    del lines[found]
    return joined(lines, True)


def append_table(text: str, table: str, entries: dict, note: str = "") -> str:
    """`[table]` with `entries`, added after the last table of its family (`[spaces.x]`
    after the last `[spaces...]`), else at the end; refused when it exists."""
    if span(text, table) is not None:
        raise EditError(f"[{table}] is already in the config")
    refuse_inline(text, table)
    block = [f"# {line}" for line in note.splitlines()] + [f"[{table}]"]
    block += [f"{key_text(key)} = {literal(value)}" for key, value in entries.items()]
    lines = text.splitlines()
    family = table.split(".")[0]
    kin = [name for _, name in headers(lines) if name and name.split(".")[0] == family]
    if not kin:
        return text.rstrip("\n") + "\n\n" + "\n".join(block) + "\n"
    at = before_example(lines, *span(text, kin[-1]))
    lines[at:at] = [""] + block + ([""] if at < len(lines) and lines[at].strip() else [])
    return joined(lines, True)


def before_example(lines: list[str], start: int, end: int) -> int:
    """Where a new table goes after `[start, end)`: at its end, or above a commented-out
    example table (`# [spaces.work]`) its trailing comments carry, so the new table never
    lands inside an example."""
    top = end
    while top - 1 > start and lines[top - 1].lstrip().startswith("#"):
        top -= 1
    example = next((n for n in range(top, end) if COMMENTED_TABLE.match(lines[n])), None)
    return end if example is None else example


def remove_table(text: str, table: str) -> str:
    """`[table]` and its keys taken out; what surrounds it is kept."""
    where = span(text, table)
    if where is None:
        raise EditError(f"there is no [{table}] in the config")
    lines = text.splitlines()
    del lines[where[0]:where[1]]
    return joined(lines, True)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def backup(path: Path, text: str, folder: Path) -> Path:
    """The old file under `folder`, named by the UTC time; only the newest ten are kept."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    kept = folder / f"config.{stamp}.toml"
    atomicfile.write_text(kept, text, mode=path.stat().st_mode & 0o777)
    for old in sorted(folder.glob("config.*.toml"))[:-KEEP_BACKUPS]:
        old.unlink(missing_ok=True)
    return kept


def write(path: Path, text_read: str, new_text: str, backups: Path, check) -> Path:
    """Replace `path` with `new_text`; `check(path)` loads it as Keel does and raises on a
    config Keel would refuse, which puts the old file back. Returns the backup."""
    path = Path(path)
    current = path.read_text()
    if digest(current) != digest(text_read):
        raise EditError(f"{path} changed since it was read; nothing was written, try again")
    try:
        tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as error:
        raise EditError(f"the edit would not parse ({error}); nothing was written") from None
    mode = path.stat().st_mode & 0o777
    kept = backup(path, current, backups)
    atomicfile.write_text(path, new_text, mode=mode)
    try:
        check(path)
    except Exception as error:
        atomicfile.write_text(path, current, mode=mode)
        raise EditError(f"Shipyard would not load the edited config ({error}); the old one is back") from None
    return kept
