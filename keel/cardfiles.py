"""The markdown files a card writes, read in the viewer (c-719).

A house writes more than its plan and its outcome: an appendix, a report, raw notes, the
answers to a review. Each was reachable only through an artifact token, which serves a
markdown file as a plain dark page with no boards, tables or callouts. This module lists
those files and answers which one a viewer page may read, so each opens on the card's own
viewer (`/file/<c-id>/<name>`, `keel/planroute.py`) through the same parser and the same
block renderer as the plan and the outcome, read only.

A name is a path RELATIVE to the card's folder, and a file is served only from inside it:
no absolute path, no `..`, no hidden component, nothing a symlink takes out of the folder,
nothing the artifact rules deny as a credential, markdown only, within the artifact size
cap. The page sends a name, never a path, and the name is checked again here on every read.
"""

from __future__ import annotations

import hashlib
import urllib.parse
from datetime import datetime
from pathlib import Path

from keel import artifacts

MARKDOWN = (".md", ".markdown")
# Folders under a card's own that are not the card's writing: Keel's record of what the user
# told the house (`tellhouse.TOLD_DIR`), and a board's files, which are always a download
# and never a page (`artifacts.BOARD_FILES`, `artifacts.BOARD_INBOX`).
SKIP_DIRS = frozenset({"told", artifacts.BOARD_FILES, artifacts.BOARD_INBOX})
# The record and the plan have pages of their own (Outcome or Context, and Plan).
OWN_PAGES = ("context.md",)
DEPTH = 3
LIMIT = 200
PAGE = "/file/"


class FileRefused(Exception):
    """The name does not name a markdown file inside the card's folder; one line why."""


def folder(cfg, card: dict) -> Path:
    return cfg.cards_dir / card["id"]


def listed(cfg, card: dict) -> list[dict]:
    """Every markdown file the card wrote, as `{name, url, bytes, at}`: the folder's own
    files first, then its folders', each by name; the record and the plan left out (they
    are the viewer's Outcome and Plan), and the named output added when it is one."""
    root = folder(cfg, card)
    if not root.is_dir():
        return []
    skip = {name for name in OWN_PAGES}
    plan = plan_name(cfg, card)
    if plan:
        skip.add(plan)
    names = [name for name in walk(root, root, 0) if name not in skip]
    named = output_name(cfg, card)
    if named and named not in names and named not in skip:
        names.append(named)
    out = []
    for name in sorted(names, key=lambda n: (n.count("/"), n.lower()))[:LIMIT]:
        try:
            path = resolve(cfg, card, name)
            stat = path.stat()
        except (FileRefused, OSError):     # r2.F11: refused, or gone since it was listed
            continue
        out.append({"name": name, "url": page_url(card["id"], name), "bytes": stat.st_size,
                    "mtime": stat.st_mtime_ns,
                    "at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds")})
    return out


def walk(root: Path, here: Path, depth: int):
    try:
        entries = sorted(here.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if entry.is_dir() and not entry.is_symlink():
            if depth + 1 < DEPTH and entry.name not in SKIP_DIRS:
                yield from walk(root, entry, depth + 1)
        elif entry.suffix.lower() in MARKDOWN:
            yield entry.relative_to(root).as_posix()


def resolve(cfg, card: dict, name: str) -> Path:
    """The file `name` names inside the card's folder, or `FileRefused` saying why not."""
    text = str(name or "").strip()
    parts = Path(text).parts
    if not text or Path(text).is_absolute() or text.startswith("~"):
        raise FileRefused("a card file is named by its path inside the card's folder")
    if any(part in ("..", ".") or part.startswith(".") for part in parts):
        raise FileRefused(f"{text} leaves the card's folder or names a hidden file")
    if Path(text).suffix.lower() not in MARKDOWN:
        raise FileRefused(f"{text} is not a markdown file")
    if parts[0].lower() in SKIP_DIRS:          # r2.F6: the card's folder may not mind case
        raise FileRefused(f"{text} is in {parts[0]}/, which is not the card's writing")
    root = folder(cfg, card).resolve()
    path = (root / text).resolve()
    if root not in path.parents:
        raise FileRefused(f"{text} is not inside {card['id']}'s folder")
    # r1.F2: the same rules again on the file a link resolves to, inside the folder
    landed = path.relative_to(root).parts
    if any(part.startswith(".") for part in landed) or landed[0].lower() in SKIP_DIRS:
        raise FileRefused(f"{text} leads to a hidden file or one that is not the card's writing")
    if path.suffix.lower() not in MARKDOWN:
        raise FileRefused(f"{text} leads to a file that is not markdown")
    if artifacts.denied(path):
        raise FileRefused(f"{text} is denied as a credential")
    try:
        size = path.stat().st_size if path.is_file() else None
    except OSError:                         # r2.F11: gone between the two looks
        size = None
    if size is None:
        raise FileRefused(f"{card['id']} has no file {text}")
    if size > artifacts.MAX_BYTES:
        raise FileRefused(f"{text} is larger than the deck serves; open it at the desk")
    return path


def inside(cfg, card: dict, path: str | Path | None) -> str | None:
    """The name a stored path has inside the card's folder, when it is a markdown file
    there the viewer may read; else None."""
    if not path or artifacts.HTTP.match(str(path)):
        return None
    full = artifacts.local_path(str(path), cfg.root)
    if full.suffix.lower() not in MARKDOWN:
        return None
    try:
        name = full.resolve().relative_to(folder(cfg, card).resolve()).as_posix()
        resolve(cfg, card, name)
    except (ValueError, OSError, FileRefused):
        return None
    return name


def output_name(cfg, card: dict) -> str | None:
    """The card's `output_ref`, when it names a markdown file inside its folder."""
    return inside(cfg, card, card.get("output_ref"))


def plan_name(cfg, card: dict) -> str | None:
    return inside(cfg, card, card.get("plan_ref"))


def page_url(card_id: str, name: str) -> str:
    return PAGE + card_id + "/" + urllib.parse.quote(name)


def output_page(cfg, card: dict) -> str | None:
    """The viewer's page for the card's named output, when it is a card file (c-719): the
    deck opens it there rather than as a plain artifact page. Read for every card on a state
    build, so anything that is not a local markdown name answers before the disk is asked
    (r1.F11)."""
    ref = str(card.get("output_ref") or "")
    if not ref or artifacts.HTTP.match(ref) or Path(ref).suffix.lower() not in MARKDOWN:
        return None
    name = output_name(cfg, card)
    if name in OWN_PAGES:
        # r2.F4: the card's own record is its Outcome (or Context) page, never a second link
        return ("/outcome/" if in_format(folder(cfg, card) / name) else "/context/") + card["id"]
    return page_url(card["id"], name) if name else None


def in_format(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4).startswith(b"---")
    except OSError:
        return False


def file_stamp(cfg, card: dict, name: str | None) -> str:
    """The `/file/` page's own part of its tag (r2.F5, r2.F7): a hash of the name (never the
    name, which may be anything but latin-1) and the file's size and mtime, so an edit to a
    file the list does not hold (deeper than the walk) moves the tag too."""
    if not name:
        return ""
    digest = hashlib.sha1(name.encode("utf-8", "replace")).hexdigest()[:12]
    try:
        stat = resolve(cfg, card, name).stat()
    except (FileRefused, OSError):
        return digest + "-none"
    return f"{digest}-{stat.st_size}-{stat.st_mtime_ns}"


def link_page(cfg, card: dict, base: Path | None, href: str) -> str | None:
    """A document's relative link to a markdown file in the card's folder, as its viewer
    page; None for anything else, which keeps its artifact token."""
    if not href or base is None or artifacts.HTTP.match(href) or href.startswith("#"):
        return None
    candidate = Path(href).expanduser()
    name = inside(cfg, card, candidate if candidate.is_absolute() else Path(base) / candidate)
    if not name or name in OWN_PAGES or name == plan_name(cfg, card):
        return None
    return page_url(card["id"], name)


def stamp(cfg, card: dict) -> str:
    """One short stamp of the list (names, sizes, times), so a cached answer that carries
    it is asked again when a file is written. `card` is the card's row, so a named output
    outside the walk counts too."""
    return stamp_of(listed(cfg, card))


def stamp_of(rows: list[dict]) -> str:
    """The stamp of a list already read (r1.F11: one `listed` per request)."""
    found = [(row["name"], row["bytes"], row["mtime"]) for row in rows]
    return hashlib.sha1(repr(found).encode()).hexdigest()[:12] if found else "0"
