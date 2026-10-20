"""The board's files: a copy a house hands him, and a file he hands a house.

Stage two of [the blackboard](<install>/history/docs/blackboard.md), K6 to K8. Stage one's `path` op
recorded a path, a size and who it came from, and served nothing at all. What is added here
is the BYTES, in both directions, and the rules that make serving them safe.

THE SERVER NEVER RESOLVES A PATH OUT OF THE OPS TEXT, and that is the whole design. A push
is text an agent wrote, so a path in it is a request, not a fact. The process that HAS the
file reads it (a house's own `keel board push`, in its own worktree, under its own confined
account), proves it sits under a root it is allowed to read, and hands the bytes over
in-process. The store then keeps a COPY under a name it generates itself, and the `path` op
keeps the original text only as the label he reads. Nothing on the store's side ever opens
a path a push named, which is what makes `path "/etc/shadow" size "1 KB" from house` a row with no
download rather than a hole.

The three rules on reading a file, all on the sending side:

- **Under a root, after resolution.** The card's own directory (`state/cards/<id>/`) and
  the CWD of the process pushing, which for a house IS its worktree. `Path.resolve()` runs
  FIRST and containment is checked against the result, so a symlink pointing out of the
  worktree fails the check rather than being followed through it.
- **Not a credential**, by the deck's own denylist (`artifacts.denied`), which is the same
  list the artifact route applies before it serves a byte.
- **16 MB**, the board's cap. Bigger than the deck's ordinary 8 MB artifact ceiling on
  purpose: a file the board accepted and then would not serve would be worse than a bigger
  read, so `artifacts.cap` raises the ceiling for a board's own directories and for nothing
  else.

HIS OWN DROP (K7) IS THE SEGMENTS' CONTROL, CALLED RATHER THAN COPIED. `POST /api/board/
<id>/inbox` is `keel/segments.py`'s upload route pointed at a board's directory: the same
caps, the same content-type table checked against the file's own magic bytes, the same
generated name, the same fingerprint de-duplication and the same same-origin rule. One
upload control in Keel, not two, so a defect fixed in one is fixed in both.
"""

import hashlib
import json
import re
import time
from pathlib import Path

from keel import artifacts, config as config_module, segments
from keel.config import Config

# The Reply shape and the two builders the door already knows how to send, re-exported so a
# caller (`keel/boards.py`) reaches the segments' contract through the board's own module.
Reply = segments.Reply
as_json = segments.as_json
refuse = segments.refuse
hint_of = segments.hint_of

MAX_BYTES = artifacts.BOARD_MAX_BYTES
CAP_SAID = "16MB"
# A bound on how much can pile up in one board's file directory. Without one, anything that
# can push can fill the disk one accepted file at a time. It is the frame cap's number,
# because a board that has run out of room has run out of room for files too.
MAX_FILES = 60
SLUG_MAX = 48
# Where a file waits between the attach that carried it and the push that names it. A dot
# directory under `state/boards/`, pruned on every attach, so a blob whose push never came
# is gone within the hour rather than kept forever (`bin/keel-backup` prunes it too: a
# restored one is a file nothing is ever going to push, like a restored fetch lock).
ATTACHED = ".attached"
STALE_SECONDS = 3600
TALKER_KEY = "talker"


class BoardFileError(Exception):
    """A file was refused; the message is the one line the caller prints or records."""


# ----- where a board's files live -----

def files_dir(cfg: Config, source: dict, board_directory: Path) -> Path:
    """The directory a board's own copies land in.

    A CARD'S board keeps them beside everything else that card stores
    (`state/cards/<id>/board-files/`), because the house that drew them reads and writes
    that directory already and a file it handed him is part of the card's own record. The
    TALKER'S boards belong to no card, so theirs live under the board
    (`state/boards/<b-id>/files/`).
    """
    if source.get("kind") == "card" and source.get("card"):
        return cfg.card_dir(str(source["card"])) / artifacts.BOARD_FILES
    return board_directory / artifacts.BOARD_TALKER_FILES


def inbox_dir(cfg: Config, source: dict, board_directory: Path) -> Path:
    """Where HIS drop lands: `state/cards/<id>/inbox/`, or the board's own `inbox/`.

    The card's directory rather than the board's, because the point of the drop is that the
    HOUSE finds it: the card's directory is the one place a house is always pointed at, and
    a note on the card names the file in it.
    """
    if source.get("kind") == "card" and source.get("card"):
        return cfg.card_dir(str(source["card"])) / artifacts.BOARD_INBOX
    return board_directory / artifacts.BOARD_INBOX


def source_key(source: dict) -> str:
    card = source.get("card")
    return str(card) if card else TALKER_KEY


# ----- naming a copy -----

def fingerprint(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()[:8]


def slug_of(path_text: str) -> str:
    """A safe filename from what the push called the file, suffix kept.

    The basename only, reduced to one alphabet, so there is no separator left to traverse
    with and nothing that can land on an existing name by accident. The SUFFIX survives
    (unlike the segments' upload, where a table decides it from the verified content type),
    because a board file may be any type and the suffix is what the artifact route reads
    the mime off.
    """
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(str(path_text or "")).name)
    name = name.strip("-._")[:SLUG_MAX].strip("-._")
    return name or "file"


def stored_name(path_text: str, blob: bytes) -> str:
    """`<fingerprint>-<slug>`: the same bytes under the same name is the same file, so a
    push repeated after a timeout stores one copy rather than two."""
    return f"{fingerprint(blob)}-{slug_of(path_text)}"


def said_size(count: int) -> str:
    """What the deck shows beside a file when a house did not say a size itself."""
    if count < 1024:
        return f"{count} B"
    if count < 1024 * 1024:
        return f"{count / 1024:.0f} KB"
    return f"{count / (1024 * 1024):.1f} MB"


# ----- reading a file on the sending side -----

def read_local(path_text: str, roots: list[Path], base: Path | None = None) -> bytes:
    """The bytes a `path` op names, or BoardFileError with the one line saying why not.

    Run by the process that is pushing, never by the store: see this module's own
    docstring. Resolution comes before containment, so a symlink that leaves the roots is
    refused rather than followed. A RELATIVE path is read against `base` when one is given
    (the talker's folder, C2), and against the working directory otherwise.
    """
    text = str(path_text or "").strip()
    if not text:
        raise BoardFileError("a path op with no path names no file")
    candidate = Path(text).expanduser()
    if base is not None and not candidate.is_absolute():
        candidate = Path(base) / candidate
    try:
        resolved = candidate.resolve()
    except OSError as error:
        raise BoardFileError(f"cannot read {text}: {error}") from None
    allowed = []
    for root in roots:
        try:
            allowed.append(Path(root).expanduser().resolve())
        except OSError:
            continue
    if not any(resolved == root or root in resolved.parents for root in allowed):
        where = ", ".join(str(root) for root in allowed) or "nowhere this side may read"
        raise BoardFileError(f"{text} is outside what may go on a board: {where}")
    if artifacts.denied(resolved):
        raise BoardFileError(f"{text} looks like a credential, so it is not put on a board")
    if not resolved.is_file():
        raise BoardFileError(f"{text} is not a file on this machine")
    size = resolved.stat().st_size
    if size > MAX_BYTES:
        raise BoardFileError(f"{text} is {said_size(size)}, and a board file is capped at {CAP_SAID}")
    try:
        return resolved.read_bytes()
    except OSError as error:
        raise BoardFileError(f"cannot read {text}: {error}") from None


def local_roots(cfg: Config | None, source: dict, cwd: Path | None = None) -> list[Path]:
    """The roots a `keel board push` on THIS machine may read a file from.

    The working directory is in the list because that is the house's worktree: the harness
    starts a house there and a confined one can reach nothing else. The card's directory
    joins it.
    """
    if source.get("kind") == "talker":
        return [talker_root(cfg)]
    roots = [Path(cwd or Path.cwd())]
    if cfg is not None and source.get("kind") == "card" and source.get("card"):
        roots.append(cfg.card_dir(str(source["card"])))
    return roots


def talker_root(cfg: Config | None) -> Path:
    """THE TALKER'S OWN FOLDER, `talker/` in this checkout, and the only place a talker's
    push may read a file from (C2). It used to be the working directory, which for the
    voice gateway is the whole checkout, `state/` and the board database included."""
    root = cfg.root if cfg is not None else config_module.package_root()
    return Path(root) / "talker"


def local_base(cfg: Config | None, source: dict, cwd: Path | None = None) -> Path | None:
    """What a relative path in a push is read against: the working directory, except for
    a talker running outside its own folder, whose relative paths are its folder's.

    Harbor's turns run in `talker/`, and its typed session in `talker/home/<n>`, so a
    relative path it writes is relative to one of those. A push run from anywhere else (the
    gateway's own working directory was the checkout) reads it against `talker/`.
    """
    here = Path(cwd or Path.cwd())
    if source.get("kind") != "talker":
        return here
    folder = talker_root(cfg)
    try:
        inside = here.resolve() == folder.resolve() or folder.resolve() in here.resolve().parents
    except OSError:
        inside = False
    return here if inside else folder


# ----- the staging area between an attach and its push -----

def attached_dir(cfg: Config, source: dict) -> Path:
    return artifacts.boards_root(cfg) / ATTACHED / source_key(source)


def staging_key(path_text: str) -> str:
    """The staged pair's name, from the PATH the push will name it by, so the push can find
    it without the ops text carrying anything the store generated."""
    return hashlib.sha256(str(path_text).encode()).hexdigest()[:16]


def prune(directory: Path) -> None:
    """Drop staged pairs older than an hour: a blob whose push never came."""
    if not directory.is_dir():
        return
    cutoff = time.time() - STALE_SECONDS
    for entry in directory.iterdir():
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            continue


def attach(cfg: Config, source: dict, path_text: str, blob: bytes) -> dict:
    """Stage one file's bytes for the push that is about to name it.

    `keel board push` makes it in process, before the push that names the file, so there
    is one place a board file enters the store.
    """
    if len(blob) > MAX_BYTES:
        raise BoardFileError(f"that file is {said_size(len(blob))}, and a board file is "
                             f"capped at {CAP_SAID}")
    if not blob:
        raise BoardFileError("that file is empty, so there is nothing to put on the board")
    directory = attached_dir(cfg, source)
    directory.mkdir(parents=True, exist_ok=True)
    prune(directory)
    key = staging_key(path_text)
    (directory / f"{key}.bin").write_bytes(blob)
    (directory / f"{key}.json").write_text(json.dumps({
        "path": str(path_text), "bytes": len(blob), "sha": fingerprint(blob),
        "stored": stored_name(path_text, blob)}) + "\n")
    return {"path": str(path_text), "bytes": len(blob), "stored": stored_name(path_text, blob)}


def take(cfg: Config, source: dict, path_text: str, destination: Path,
         who: str = "house") -> dict | None:
    """Move a staged file into the board's own directory; the record's entry, or None.

    None means nothing was attached for that path, which is how a `path` op from a caller
    that carried no bytes stays exactly what stage one made it: a metadata row the deck
    draws with no download under it.
    """
    directory = attached_dir(cfg, source)
    key = staging_key(path_text)
    blob_path, meta_path = directory / f"{key}.bin", directory / f"{key}.json"
    if not blob_path.is_file() or not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, ValueError):
        return None
    destination.mkdir(parents=True, exist_ok=True)
    if count_files(destination) >= MAX_FILES and not (destination / meta["stored"]).exists():
        raise BoardFileError(f"this board already holds {MAX_FILES} files; start another board")
    target = destination / str(meta["stored"])
    try:
        blob_path.replace(target)
        meta_path.unlink()
    except OSError as error:
        raise BoardFileError(f"could not put that file on the board: {error}") from None
    return entry_for(target, int(meta.get("bytes") or 0), who, name=Path(path_text).name)


def count_files(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return len([item for item in directory.iterdir() if item.is_file()])


def entry_for(target: Path, size: int, who: str, name: str = "") -> dict:
    """One row of a board record's `files` map: where the copy is, and what to call it.

    TWO NAMES, because they answer different questions. `stored` is the name on disk, which
    carries a fingerprint so two files can share a basename and neither is overwritten;
    `name` is what it is called on the board and what his browser saves it as, which is what
    the house or he called it. A fingerprint is right for a filename and wrong for a person.
    """
    return {"file": str(target), "name": name or target.name, "stored": target.name,
            "bytes": size, "from": who, "size": said_size(size)}


# ----- what the deck is handed -----

def links(cfg: Config, record: dict) -> dict:
    """`{path as written: {name, bytes, size, from, url}}` for one board's files.

    The URL is an ARTIFACT TOKEN minted at read time rather than stored: the token is the
    path plus an HMAC over it, so keeping one in `board.json` would outlive a rotated key
    and would be a second place the truth lived. A file that has been deleted under the
    board answers `url: null`, and the deck draws the row without a download.
    """
    out = {}
    for path_text, entry in (record.get("files") or {}).items():
        stored = entry.get("file")
        out[str(path_text)] = {
            "name": entry.get("name") or Path(str(stored or "")).name,
            "stored": entry.get("stored") or "", "bytes": entry.get("bytes") or 0,
            "size": entry.get("size") or said_size(int(entry.get("bytes") or 0)),
            "from": entry.get("from") or "", "url": artifacts.url(cfg, stored) if stored else None}
    return out


# ----- his own drop (K7) -----

def accept_upload(destination: Path, headers, rfile, same_origin: bool,
                  query: str) -> tuple[Reply | None, dict | None]:
    """The segments' upload control, pointed at a board's directory.

    Everything about the envelope is theirs and is called rather than copied: the
    same-origin rule, the content-type table checked against the file's own magic bytes,
    the 10 MB cap, the name generated here, and the fingerprint de-duplication that makes a
    phone retrying after a flaky connection one file rather than two.

    (refusal, None) or (None, {stored, bytes, duplicate}). The caller turns the second into
    a `file` frame and a note on the card, which is the half that is the BOARD'S.
    """
    if not same_origin:
        return refuse(403, segments.FOREIGN), None
    kind = segments.content_type(headers)
    if kind not in segments.INBOX_TYPES:
        return refuse(415, "a file put on the board must be sent as one of: "
                           + ", ".join(sorted(segments.INBOX_TYPES))), None
    if count_files(destination) >= MAX_FILES:
        return refuse(429, f"this board already holds {MAX_FILES} files, so nothing more is "
                           f"accepted until some are cleared"), None
    blob, stopped = segments.take_body(headers, rfile, segments.INBOX_MAX, "upload",
                                       segments.INBOX_CAP_SAID)
    if stopped is not None:
        return stopped, None
    magic, ext = segments.INBOX_TYPES[kind]
    if not blob.startswith(magic):
        return refuse(415, f"the bytes are not {kind}", unread=False), None
    waiting = already_there(destination, blob)
    if waiting:
        return None, {"stored": waiting, "bytes": len(blob), "duplicate": True}
    stored = segments.inbox_name(segments.hint_of(query), blob, ext)
    failed = segments.store(destination, stored, blob)
    if failed:
        return refuse(500, f"could not store it: {failed}", unread=False), None
    return None, {"stored": stored, "bytes": len(blob), "duplicate": False}


def already_there(destination: Path, blob: bytes) -> str | None:
    """The name this exact file already sits under, matched on the content fingerprint the
    generated name carries, exactly as the segments' inbox matches its own."""
    mark = f"-{segments.fingerprint(blob)}-"
    if not destination.is_dir():
        return None
    for item in sorted(destination.iterdir()):
        if item.is_file() and mark in item.name:
            return item.name
    return None
