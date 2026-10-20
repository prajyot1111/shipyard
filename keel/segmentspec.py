"""What a segment's `segment.md` may say, checked (c-634, c-628 S6).

A segment is a directory found by listing (`keel/fetch.py`, `keel/deckstate.py`), and its
`segment.md` frontmatter was read loosely and only for `logins` (`keel/logins.py`). This is
the one place that says what the frontmatter may hold:

- `name`: the directory's own name.
- `space`: a space this config has. It describes the segment; the space its tools load
  under is `worker.md`'s, which already fails closed (`fetch.read_worker`).
- `cadence`: hourly, daily or none (a service segment, such as voice, fetches nothing).
- `card-span`: how many deck columns its tile spans, a small whole number.
- `logins`: the login rows a refused key marks (`keel/logins.py`).

And something to look at: a `fetch.py`, an `app/index.html`, or a `service.json`.

A segment that fails is REPORTED, never skipped (decision `invalid`): `keel doctor` prints
a line per problem, and `tests/test_segmentspec.py` holds every shipped segment to it. The
fetch role still runs it, since a typo here must never stop a working segment's updates.
"""

from __future__ import annotations

from pathlib import Path

from keel import fetch

SPEC = "segment.md"
KEYS = ("name", "space", "cadence", "card-span", "logins")
CADENCES = ("hourly", "daily", "none")
SPAN_MAX = 4
SOMETHING = ("fetch.py", "app/index.html", "service.json")


def check(directory: Path, spaces) -> list[str]:
    """What is wrong with the segment in `directory`, one sentence each; empty when nothing.
    `spaces` is the config's space names."""
    directory = Path(directory)
    spec = directory / SPEC
    if not spec.is_file():
        return [f"it has no {SPEC}"]
    fields, _body = fetch.parse_frontmatter(spec.read_text(encoding="utf-8"))
    out = []
    if fields.get("name") != directory.name:
        out.append(f"name is {fields.get('name') or 'missing'}, and the directory is {directory.name}")
    if fields.get("space") not in set(spaces):
        out.append(f"space {fields.get('space') or 'is missing'}"
                   + ("" if not fields.get("space") else " is not a space here")
                   + f" (the spaces: {', '.join(sorted(spaces)) or 'none'})")
    out += [f"{key} is not a segment.md key (the keys: {', '.join(KEYS)})"
            for key in fields if key not in KEYS]
    if "cadence" in fields and fields["cadence"] not in CADENCES:
        out.append(f"cadence {fields['cadence']} is not one of {', '.join(CADENCES)}")
    span = fields.get("card-span")
    if span is not None and not (span.isdigit() and 1 <= int(span) <= SPAN_MAX):
        out.append(f"card-span {span} is not a whole number from 1 to {SPAN_MAX}")
    if not any((directory / part).is_file() for part in SOMETHING):
        out.append(f"there is nothing to look at ({', '.join(SOMETHING)})")
    return out


def report(cfg) -> dict[str, list[str]]:
    """`{segment name: problems}` for every segment the deck would list (`segment_roots`,
    the first root that has a name winning), the ones with no problem included."""
    found: dict[str, Path] = {}
    for root in cfg.segment_roots:
        if not root.is_dir():
            continue
        for directory in sorted(root.iterdir()):
            if directory.is_dir() and not directory.name.startswith((".", "_")):
                found.setdefault(directory.name, directory)
    spaces = list(cfg.spaces)
    return {name: check(found[name], spaces) for name in sorted(found)}


def problems(found: dict[str, list[str]]) -> list[str]:
    """Doctor's lines: `segment <name>: <problem>`."""
    return [f"segment {name}: {problem}" for name, said in found.items() for problem in said]


def line(found: dict[str, list[str]]) -> str:
    bad = [name for name, said in found.items() if said]
    if not found:
        return "segments      none"
    return (f"segments      {len(found)}, " + (f"{len(bad)} with problems: {', '.join(bad)}" if bad
                                               else "each segment.md valid"))
