"""The segment tier of the deck: a segment's own files, and the two drops it accepts.

`keel/serve.py` owns the door and hands `/segments/...` here. What lives in this module is
everything about a segment that is not the static app:

    GET  /segments/<name>/data/<file>    one data file the segment's app reads
    GET  /segments/<name>/summary.json   the segment's own summary
    GET  /segments/<name>/inbox          what is waiting in the upload inbox
    POST /segments/<name>/decisions      one journal drop into data/inbox/
    POST /segments/<name>/inbox          one file (a PDF, a screenshot) into inbox/

A segment app is static files that can only read, so a decision taken on a phone lives in
that phone's localStorage until something carries it back, and an invoice picked in the
Swiggy app has nowhere to go. These two routes are that door: they know nothing about what
a decision MEANS, they validate the envelope, write it under a name generated here, and
stop. The segment's own `fetch.py` folds it in on its next pass.

The contract is the old dashboard's, verbatim, because the three apps were written against
it and are static files nobody is going to rewrite: the same paths, the same names
(`<stamp>-<fingerprint>-decisions.json`, `<stamp>-<fingerprint>-<hint>.pdf`), the same
fingerprint de-duplication, the same caps, and the same answer shapes. The one place this
is STRICTER is the data read: `data/inbox/`, `data/inbox-applied/` and `data/asks/` are
refused by name, a dotfile is refused, and the deck's credential denylist applies, so a
route that exists to hand a phone a JSON file cannot hand it anything else.

Two inboxes, and the difference is not cosmetic. A decisions journal lands in
`data/inbox/`, which is the fold's door and what `changed_only` watches. An uploaded file
lands in `inbox/` at the segment root, which is where `instamart/fetch.py` reads invoices
from. Both are picked up within a minute: the first through `inbox_has_work`, the second
through `sources_changed` (it sits outside `data/`).
"""

import hashlib
import json
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from keel import artifacts
from keel.config import Config

NAME = r"([\w.-]+)"
DATA_ROUTE = re.compile(rf"^/segments/{NAME}/data/{NAME}$")
FILE_ROUTE = re.compile(rf"^/segments/{NAME}/(summary\.json)$")
DECISIONS_ROUTE = re.compile(rf"^/segments/{NAME}/decisions$")
INBOX_ROUTE = re.compile(rf"^/segments/{NAME}/inbox$")

# Names under data/ this route will not hand out whatever the request says. They are the
# segment's own working directories rather than its published data: the drops waiting to
# be folded, the drops already folded, and the asks a worker card is answering. None of
# them is a file, so `is_file()` would refuse them anyway; they are named here so the rule
# is a rule rather than an accident of the directory layout.
RESERVED = frozenset({"inbox", "inbox-applied", "asks", "taken"})

SEG_MIME = {".json": "application/json; charset=utf-8", ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
            ".txt": "text/plain; charset=utf-8", ".csv": "text/csv; charset=utf-8",
            ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
            ".pdf": "application/pdf"}

DECISIONS_MAX = 1024 * 1024          # a year of decisions is a few tens of KB
DECISIONS_CAP_SAID = "1024KB"        # the cap as the apps have always shown it
DECISIONS_MAX_ENTRIES = 20000
DECISIONS_MAX_FILES = 200
DECISIONS_DIR = ("data", "inbox")
APPLIED_DIR = "inbox-applied"

# WHY THIS IS A TABLE, AND WHAT IT MAY NEVER CONTAIN. The upload route's only defence
# beyond the same-origin check is that the browser must preflight the request, which it
# does because none of these content types is one a cross-origin page may send without
# asking first (application/x-www-form-urlencoded, multipart/form-data, text/plain). So:
# never add text/plain, never add a form type, and never relax the check to a prefix match
# like "image/*". A prefix match would accept a type nobody vetted the day a browser adds
# one, and the defence would be gone with nothing here having changed.
INBOX_TYPES = {"application/pdf": (b"%PDF-", "pdf"),
               "image/png": (b"\x89PNG\r\n\x1a\n", "png"),
               # Only the JFIF/Exif start-of-image marker, not any three-byte prefix: the
               # point of checking bytes at all is that the declared type is a claim and
               # the header is evidence.
               "image/jpeg": (b"\xff\xd8\xff", "jpg")}
INBOX_MAX = 10 * 1024 * 1024
INBOX_CAP_SAID = "10MB"
# A bound on how much can pile up before a fetcher drains it. Without one, anything that
# can reach this route can fill the disk one accepted upload at a time.
INBOX_MAX_FILES = 200
UPLOADS_DIR = "inbox"

FOREIGN = "that did not come from the deck's own page, so it was not stored"
DRAIN_CHUNK = 65536


class Reply(NamedTuple):
    """One answer, plus whether the request body was left unread.

    An unread body ends the connection rather than being left for the next request on it
    to parse as its own request line.
    """
    status: int
    body: bytes
    content_type: str
    unread: bool = False


def as_json(status: int, payload: dict, unread: bool = False) -> Reply:
    return Reply(status, json.dumps(payload).encode(), "application/json; charset=utf-8", unread)


def refuse(status: int, error: str, unread: bool = True, **extra) -> Reply:
    return as_json(status, {"ok": False, "error": error, **extra}, unread)


# ----- where a segment's files are -----

def segment_dir(cfg: Config, name: str) -> Path | None:
    """The segment called `name`, resolved through `Config.segment_roots`, or None.

    Resolved BEFORE containment is checked, because a symlink named like a segment could
    otherwise point anywhere on disk and this would happily serve through it.
    """
    if ".." in name or not re.fullmatch(r"[\w.-]+", name):
        return None
    for root in cfg.segment_roots:
        target = root / name
        try:
            resolved = target.resolve()
        except OSError:
            continue
        if root not in resolved.parents or not resolved.is_dir():
            continue
        return resolved
    return None


def readable(root: Path, name: str) -> Path | None:
    """`root/name` when it is a file this route may hand over, else None.

    Four rules, in order: the name is one plain component, it is not a dotfile, it is not
    one of the segment's own working directories, and it is not something that looks like
    a credential (the deck's own denylist, the same one the artifact route applies).
    """
    if "/" in name or name.startswith(".") or name in RESERVED:
        return None
    target = (root / name)
    try:
        resolved = target.resolve()
    except OSError:
        return None
    if root.resolve() not in resolved.parents or artifacts.denied(resolved):
        return None
    return resolved if resolved.is_file() else None


def mime(path: Path) -> str:
    return SEG_MIME.get(path.suffix.lower(), "application/octet-stream")


def serve_file(path: Path | None) -> Reply:
    if path is None:
        return refuse(404, "no such segment file", unread=False)
    try:
        return Reply(200, path.read_bytes(), mime(path))
    except OSError:
        return refuse(404, "no such segment file", unread=False)


# ----- naming and de-duplication -----

def fingerprint(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()[:8]


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def decisions_dir(segment: Path) -> Path:
    return segment.joinpath(*DECISIONS_DIR)


def decisions_name(blob: bytes) -> str:
    """The name the fold expects, unchanged from the old dashboard's: each segment's
    `apply_inbox` globs `data/inbox/*.json` and folds whatever it finds."""
    return f"{stamp()}-{fingerprint(blob)}-decisions.json"


def decisions_pending(segment: Path) -> list[str]:
    box = decisions_dir(segment)
    if not box.is_dir():
        return []
    return sorted(path.name for path in box.iterdir()
                  if path.is_file() and path.name.endswith(".json") and not path.name.startswith("."))


def already_dropped(segment: Path, blob: bytes) -> str | None:
    """The name this exact journal is already stored under, pending or applied.

    Matched on the content fingerprint rather than the generated filename, so a phone that
    posts, times out after the write landed, and retries is recognised as the same journal
    instead of filing a second copy.
    """
    mark = f"-{fingerprint(blob)}-"
    for name in decisions_pending(segment):
        if mark in name:
            return name
    applied = decisions_dir(segment).parent / APPLIED_DIR
    if applied.is_dir():
        for path in sorted(applied.iterdir()):
            if path.is_file() and mark in path.name:
                return path.name
    return None


def valid_journal(blob: bytes) -> str | None:
    """Why these bytes are not a decisions journal, or None if they are one.

    Validated before anything is written, so what lands on disk is always something a
    fetcher can read.
    """
    try:
        blob.decode("utf-8")
    except UnicodeDecodeError:
        return "a journal must be UTF-8 JSON"
    try:
        doc = json.loads(blob)
    except ValueError:
        return "that is not JSON"
    if not isinstance(doc, dict):
        return "a journal is a JSON object"
    entries = doc.get("entries")
    if not isinstance(entries, list):
        return "a journal needs an entries list"
    if not entries:
        return "there is nothing in it to apply"
    if len(entries) > DECISIONS_MAX_ENTRIES:
        return f"more than {DECISIONS_MAX_ENTRIES} entries"
    for entry in entries:
        if not isinstance(entry, dict):
            return "every entry is an object"
        if not isinstance(entry.get("k"), str) or not entry["k"].strip():
            return "every entry needs a key"
        if not isinstance(entry.get("t"), str) or not entry["t"].strip():
            return "every entry needs a timestamp"
    return None


def uploads_dir(segment: Path) -> Path:
    return segment / UPLOADS_DIR


def inbox_name(hint: str, blob: bytes, ext: str = "pdf") -> str:
    """The stored filename, generated here and never taken from the request.

    The client's name is a hint for a human reading a directory listing, nothing more: it
    is reduced to its basename, stripped to a safe alphabet and truncated, so there is no
    separator left to traverse with and no way to land on an existing file. The extension
    comes from the TABLE, keyed by the content type that was verified against the file's
    own magic bytes, never from the hint.
    """
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(str(hint or "")).name)
    known = "|".join(suffix for _, suffix in INBOX_TYPES.values())
    slug = re.sub(rf"\.(?:{known}|jpeg)$", "", slug, flags=re.I).strip("-._")[:48].strip("-._")
    return f"{stamp()}-{fingerprint(blob)}-{slug or 'upload'}.{ext}"


def inbox_pending(segment: Path) -> list[dict]:
    """What is waiting in a segment's inbox for its fetcher to pick up.

    Everything finished, not only what matches one extension: a segment's own fetcher is
    what decides what a file in its inbox means, and a listing that quietly omitted
    anything would report an empty inbox that is not empty. A partial upload, written as
    `<name>.part`, is the one thing skipped, because it is not a file yet.
    """
    box = uploads_dir(segment)
    if not box.is_dir():
        return []
    out = []
    for path in sorted(box.iterdir()):
        if not path.is_file() or path.name.endswith(".part") or path.name.startswith("."):
            continue
        info = path.stat()
        at = datetime.fromtimestamp(info.st_mtime, timezone.utc).astimezone()
        out.append({"name": path.name, "bytes": info.st_size,
                    "uploadedAt": at.isoformat(timespec="seconds")})
    return out


def already_waiting(segment: Path, blob: bytes) -> str | None:
    """The name this exact file is already stored under, if it is. Matched on the content
    fingerprint, so a phone retrying after a flaky connection is recognised as the same
    upload rather than filing a second copy of the same invoice."""
    mark = f"-{fingerprint(blob)}-"
    for pending in inbox_pending(segment):
        if mark in pending["name"]:
            return pending["name"]
    return None


def store(box: Path, name: str, blob: bytes) -> str | None:
    """Write `blob` into `box/name`, or the failure's class name.

    Written aside and moved in, so a fetcher running mid-post never reads half a journal
    and takes it as the whole of one.
    """
    try:
        box.mkdir(parents=True, exist_ok=True)
        part = box / (name + ".part")
        part.write_bytes(blob)
        part.replace(box / name)
    except OSError as error:
        return error.__class__.__name__
    return None


# ----- reading a body -----

def declared(headers) -> int:
    try:
        return int(headers.get("Content-Length") or 0)
    except ValueError:
        return -1


def content_type(headers) -> str:
    return (headers.get("Content-Type") or "").split(";")[0].strip().lower()


def drain(rfile, limit: int) -> None:
    """Read and discard up to `limit` bytes, so a refusal of an over-large body is not a
    connection reset in the middle of the phone's upload."""
    left = limit
    while left > 0:
        chunk = rfile.read(min(DRAIN_CHUNK, left))
        if not chunk:
            return
        left -= len(chunk)


def hint_of(query: str) -> str:
    for part in query.split("&"):
        key, _, value = part.partition("=")
        if key == "name":
            return urllib.parse.unquote_plus(value)
    return ""


# ----- the routes -----

def get(cfg: Config, path: str) -> Reply:
    """A segment GET. The whole `/segments/` prefix belongs to the deck, so a path that
    matches none of these routes is a 404 here rather than a 503 from the lavish proxy."""
    match = DATA_ROUTE.match(path)
    if match:
        segment = segment_dir(cfg, match.group(1))
        if segment is None:
            return refuse(404, "no such segment", unread=False)
        return serve_file(readable(segment / "data", match.group(2)))
    match = FILE_ROUTE.match(path)
    if match:
        segment = segment_dir(cfg, match.group(1))
        if segment is None:
            return refuse(404, "no such segment", unread=False)
        return serve_file(readable(segment, match.group(2)))
    match = INBOX_ROUTE.match(path)
    if match:
        # What is sitting in a segment's inbox, uploaded but not yet picked up. The app
        # needs this to say "waiting" honestly: its own data file only changes when the
        # fetcher runs, so without this an upload would look like it had vanished.
        segment = segment_dir(cfg, match.group(1))
        if segment is None:
            return refuse(404, "no such segment", unread=False)
        pending = inbox_pending(segment)
        return as_json(200, {"ok": True, "pending": pending, "count": len(pending)})
    return refuse(404, "not a segment route", unread=False)


def post(cfg: Config, path: str, headers, rfile, same_origin: bool) -> Reply | None:
    """A segment POST, or None when the path is not one this tier accepts."""
    bare, _, query = path.partition("?")
    match = DECISIONS_ROUTE.match(bare)
    if match:
        return post_decisions(cfg, match.group(1), headers, rfile, same_origin)
    match = INBOX_ROUTE.match(bare)
    if match:
        return post_inbox(cfg, match.group(1), headers, rfile, same_origin, query)
    return None


def take_body(headers, rfile, cap: int, what: str, unit: str) -> tuple[bytes | None, Reply | None]:
    """The request body, or the refusal that stops it being read. `unit` is the cap as the
    old dashboard worded it, which is what the apps have always shown a person."""
    size = declared(headers)
    if size <= 0:
        return None, refuse(400, f"empty {what}", unread=False)
    if size > cap:
        drain(rfile, cap)
        return None, refuse(413, f"too large, the cap is {unit}")
    blob = rfile.read(size)
    if len(blob) != size:
        return None, refuse(400, f"the {what} ended early", unread=False)
    return blob, None


def post_decisions(cfg: Config, name: str, headers, rfile, same_origin: bool) -> Reply:
    """Accept one decisions journal into `segments/<name>/data/inbox/`.

    This route knows nothing about what a decision means: it validates the envelope (a
    list of keyed, timestamped entries), writes it under a name generated here, and stops.
    """
    segment = segment_dir(cfg, name)
    if segment is None:
        return refuse(404, "no such segment")
    if not same_origin:
        return refuse(403, FOREIGN)
    if content_type(headers) != "application/json":
        return refuse(415, "a journal must be sent as application/json")
    if len(decisions_pending(segment)) >= DECISIONS_MAX_FILES:
        return refuse(429, f"{DECISIONS_MAX_FILES} journals are already waiting to be read, "
                           f"so nothing more is accepted until they are")
    blob, stopped = take_body(headers, rfile, DECISIONS_MAX, "journal", DECISIONS_CAP_SAID)
    if stopped is not None:
        return stopped
    why = valid_journal(blob)
    if why:
        return refuse(400, why, unread=False)
    entries = len(json.loads(blob)["entries"])

    box = decisions_dir(segment)
    seen = already_dropped(segment, blob)
    if seen:
        return as_json(200, {"ok": True, "stored": seen, "entries": entries,
                             "duplicate": True, "pending": len(decisions_pending(segment))})
    stored = decisions_name(blob)
    failed = store(box, stored, blob)
    if failed:
        return refuse(500, f"could not store it: {failed}", unread=False)
    return as_json(200, {"ok": True, "stored": stored, "entries": entries,
                         "duplicate": False, "pending": len(decisions_pending(segment))})


def post_inbox(cfg: Config, name: str, headers, rfile, same_origin: bool, query: str) -> Reply:
    """Accept one file, of a type `INBOX_TYPES` names, into `segments/<name>/inbox/`.

    One file per request, so a batch reports per file rather than all or nothing. The body
    is the file itself, which is why there is no multipart parsing here.
    """
    segment = segment_dir(cfg, name)
    if segment is None:
        return refuse(404, "no such segment")
    if not same_origin:
        return refuse(403, FOREIGN)
    kind = content_type(headers)
    if kind not in INBOX_TYPES:
        return refuse(415, "an upload must be sent as one of: " + ", ".join(sorted(INBOX_TYPES)))
    if len(inbox_pending(segment)) >= INBOX_MAX_FILES:
        return refuse(429, f"the inbox already holds {INBOX_MAX_FILES} files waiting to be "
                           f"read, so nothing more is accepted until it is emptied")
    blob, stopped = take_body(headers, rfile, INBOX_MAX, "upload", INBOX_CAP_SAID)
    if stopped is not None:
        return stopped
    # The declared type is a claim, the file's own header is evidence. A PNG sent as
    # application/pdf is a mismatch worth refusing, not a file to quietly re-label, because
    # the sender and this server disagree about what it is and the fetcher would inherit
    # that disagreement.
    magic, ext = INBOX_TYPES[kind]
    if not blob.startswith(magic):
        return refuse(415, f"the bytes are not {kind}", unread=False)

    waiting = already_waiting(segment, blob)
    if waiting:
        return as_json(200, {"ok": True, "stored": waiting, "bytes": len(blob),
                             "duplicate": True, "pending": len(inbox_pending(segment))})
    stored = inbox_name(hint_of(query), blob, ext)
    failed = store(uploads_dir(segment), stored, blob)
    if failed:
        return refuse(500, f"could not store it: {failed}", unread=False)
    return as_json(200, {"ok": True, "stored": stored, "bytes": len(blob),
                         "duplicate": False, "pending": len(inbox_pending(segment))})
