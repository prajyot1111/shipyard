"""Artifact tokens: how the deck names a file without letting the browser name a path.

The page never sends a filesystem path. It sends a token this server minted: the path
plus an HMAC over it, both urlsafe, so the only reachable files are the ones the state
document already handed out. A token is minted only for a file under one of the roots
(`state/cards/`, `segments_dir`, `state/boards/`, and every `artifact_roots` entry in
the config) that is
not a credential by name, directory or suffix, and `untoken` checks the same rules again
before a byte is served. The key is `<state_dir>/artifact.key`, created 0600 on first use
and stable across restarts, so a token pasted into a phone's browser survives the server
restarting under it.

The roots are configured rather than fixed because a card's `plan_ref` points wherever the
tool that wrote the plan put it: a plan archive, a worktree's own artifact directory, a
review surface's source file. Every one of those is outside `state/cards/`, so a fixed pair
of roots meant the deck rendered "Open plan" as a link that did nothing.

The markdown renderer resolves a relative image or link against the directory of the
document it is rendering, and mints a token for it under exactly those rules, so a context
file's `![shot](assets/shot.png)` is a picture on the phone rather than literal text. What
lands in `src` is always the token this module minted, never a string from the document.
"""

import base64
import contextlib
import contextvars
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import stat
import subprocess
from pathlib import Path

from keel.config import Config

KEY_NAME = "artifact.key"
SIGNATURE_BYTES = 16
MAX_BYTES = 8 * 1024 * 1024

# THE BOARD'S OWN FILE DIRECTORIES (`keel/boardfiles.py`), which are a root of their own and
# carry a higher ceiling. A board accepts a file at 16 MB, and a file it accepted and then
# refused to serve would be worse than a bigger read, so `cap` raises the limit for these
# three directories and for nothing else. The names live here rather than there because this
# module is the one that decides what may be served and how much of it.
BOARDS_DIRNAME = "boards"            # state/boards, which keel/boards.py owns
BOARD_FILES = "board-files"          # a card's board: state/cards/<id>/board-files/
BOARD_TALKER_FILES = "files"         # the talker's: state/boards/<b-id>/files/
BOARD_INBOX = "inbox"                # what HE put on the board, on either source
BOARD_MAX_BYTES = 16 * 1024 * 1024

# THE DENYLIST, WHICH IS A REACHABLE SURFACE NOW AND NOT A COURTESY. It used to cover the
# files the deck itself linked. Since the board carries a file a HOUSE named
# (`keel/boardfiles.py`), it has to cover what an agent can reach for from inside a
# worktree, so it is a list of SHAPES rather than of filenames: any component of the path,
# any name, any prefix, any suffix. It is deliberately broader than it strictly needs to
# be, because a file called `id_map.py` that cannot go on a board is a smaller loss than
# one private key that can.
DENY_DIRS = frozenset({".ssh", ".aws", ".gnupg", "secrets", ".password-store",
                       # A credentials directory anywhere: `~/.config/keel/credentials/`,
                       # a project's own, a service account drop.
                       "credentials",
                       # `.git/config` carries remote URLs with tokens in them; `.claude/`
                       # carries a session's settings, its hooks and its environment; the
                       # docker config carries registry auth.
                       ".git", ".claude", ".docker"})
DENY_NAMES = frozenset({"headers.txt", ".env", "credentials", "id_rsa", "id_ed25519", ".netrc",
                        ".npmrc", ".pypirc", "token", "human.token", "cookies.txt",
                        "artifact.key",
                        # The per-card settings file Keel writes beside everything else in
                        # a card's own directory (`house.settings_for`): the hooks, the
                        # space's deny list and the house's environment.
                        "settings.json", "settings.local.json"})
# A PREFIX is for a family whose members are invented locally: `.env.production`,
# `.env.local`, and every `id_<algorithm>` key pair including its `.pub`.
DENY_PREFIXES = (".env", "id_")
DENY_SUFFIX = frozenset({".key", ".pem", ".p12", ".pfx", ".keychain", ".keychain-db", ".token"})

KINDS = {
    ".html": "html", ".htm": "html", ".md": "markdown", ".markdown": "markdown",
    ".txt": "text", ".log": "text", ".json": "text", ".yaml": "text", ".yml": "text",
    ".diff": "text", ".patch": "text", ".py": "text", ".js": "text", ".sh": "text",
    ".csv": "text", ".tsv": "text", ".toml": "text", ".ini": "text", ".jsonl": "text",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image", ".svg": "image",
    ".webp": "image", ".pdf": "pdf",
}
MIME = {
    "html": "text/html; charset=utf-8", "markdown": "text/html; charset=utf-8",
    "text": "text/plain; charset=utf-8", "pdf": "application/pdf",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".svg": "image/svg+xml", ".webp": "image/webp",
    # SOUND, because some work can only be judged by ear (c-316: a house speaks in its own
    # voice, and no test can say whether the handoff is heard). A linked clip in a card's
    # markdown becomes a token URL like any other local asset, and with a type the phone
    # recognises it plays where he is reading rather than downloading as a blob.
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
}


# ----- the key -----

def key(cfg: Config) -> bytes:
    path = cfg.state_dir / KEY_NAME
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.urlsafe_b64encode(secrets.token_bytes(32)))
        path.chmod(0o600)
    return path.read_bytes().strip()


# ----- what may be served -----

def boards_root(cfg: Config) -> Path:
    """`state/boards/`, the blackboard's store. A talker board's files live under it, and
    nothing there is served except through a token this module minted for it."""
    return cfg.state_dir / BOARDS_DIRNAME


# The roots one deck build resolved (`roots_held`), so the few hundred links it mints do not
# each resolve every root again: that was a fifth of a cold `/api/state` (c-540). Held for
# the one build and dropped after it, never a module cache that could outlive a symlink.
HELD_ROOTS: contextvars.ContextVar = contextvars.ContextVar("held_roots", default=None)
# And every path it resolved, by the same rule (c-638): a card's links resolved each of its
# files from `/` up, an lstat per component, about 10,000 of them and 2.2 s of a 3.4 s
# `/api/state` on a 636-card board. Inside the `with`, a directory is resolved once and each
# file below it costs one lstat, its own (`resolved`). A path found missing is held too, and
# so is everything under it, never asked of the disk again: refs left from another machine
# (`/home/ubuntu/...`) sit under macOS's `/home` automount, where each look cost 11 ms.
HELD_PATHS: contextvars.ContextVar = contextvars.ContextVar("held_paths", default=None)


@contextlib.contextmanager
def roots_held(cfg: Config):
    """Resolve the roots, and each path once, for everything inside the `with` (in this
    thread)."""
    mark = HELD_ROOTS.set((id(cfg), resolved_roots(cfg)))
    paths = HELD_PATHS.set({})
    try:
        yield
    finally:
        HELD_PATHS.reset(paths)
        HELD_ROOTS.reset(mark)


def resolved(path: Path) -> Path:
    """`path.resolve()`, kept for the one build that holds it (`roots_held`). The same answer
    as `os.path.realpath`: the parent resolved (kept), then this component, followed when it
    is a symlink. A relative path, or one with `.` or `..` in it, is resolved whole."""
    memo = HELD_PATHS.get()
    path = Path(path)
    if memo is None or not path.is_absolute() or any(part in (".", "..") for part in path.parts):
        return path.resolve()
    return held(memo, path)[0]


def held(memo: dict, path: Path) -> tuple[Path, bool]:
    """`path` resolved, and whether it exists, from the build's memo or one lstat."""
    key = str(path)
    if key not in memo:
        if path.parent == path:
            memo[key] = (path.resolve(), True)
        else:
            parent, there = held(memo, path.parent)
            here = parent / path.name
            if not there:
                memo[key] = (here, False)
            else:
                try:
                    mode = os.lstat(here).st_mode
                except OSError:
                    memo[key] = (here, False)
                else:
                    memo[key] = (here.resolve(), True) if stat.S_ISLNK(mode) else (here, True)
    return memo[key]


def missing(path: Path) -> bool:
    """True when the build holding the memo already knows `path` does not exist; never asks
    the disk outside one, and False whenever it cannot tell."""
    memo = HELD_PATHS.get()
    path = Path(path)
    if memo is None or not path.is_absolute() or any(part in (".", "..") for part in path.parts):
        return False
    return not held(memo, path)[1]


def roots(cfg: Config) -> list[Path]:
    """Every tree a file may be served from: the three implicit ones, then the config's."""
    held = HELD_ROOTS.get()
    if held is not None and held[0] == id(cfg):
        return held[1]
    return resolved_roots(cfg)


def resolved_roots(cfg: Config) -> list[Path]:
    configured = [Path(root).expanduser().resolve() for root in cfg.artifact_roots]
    return [cfg.cards_dir.resolve(), cfg.segments_dir.resolve(), boards_root(cfg).resolve(),
            *configured]


def board_file(cfg: Config, path: str | Path) -> bool:
    """Is this one of a board's own files: a copy a house handed him, or a file he dropped.

    Named by the DIRECTORY it sits in rather than by a flag on the request, so the ceiling
    below cannot be raised by anything a caller says. A segment's `inbox/` is not this: it
    is under `segments_dir`, not under a card or a board.
    """
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return False
    parent = resolved.parent
    if parent.name in (BOARD_FILES, BOARD_INBOX) and cfg.cards_dir.resolve() in parent.parents:
        return True
    return (parent.name in (BOARD_TALKER_FILES, BOARD_INBOX)
            and boards_root(cfg).resolve() in parent.parents)


DOWNLOAD_TYPE = "application/octet-stream"
# What may appear in a filename this server puts in a header. The quoted form takes no
# quote and no control character, and the name came off a path a HOUSE wrote, so it is
# reduced to one alphabet here rather than trusted.
FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")
# The two shapes KEEL ITSELF generates in front of a stored name: `<fingerprint>-<name>`
# for a board file (`keel/boardfiles.py`) and `<stamp>-<fingerprint>-<name>` for an upload
# (`keel/segments.py`). Both are right for a filename on disk, where two files may share a
# basename, and wrong for the name his browser saves it under.
GENERATED_PREFIX = re.compile(r"^(?:\d{8}T\d{6}Z-)?[0-9a-f]{8}-(?=.)")


# A PAGE A HOUSE WROTE RUNS IN AN OPAQUE ORIGIN (c-451, review item 1). An artifact is a
# file under a card's directory or a segment, and a house chose its bytes: served as HTML or
# SVG in the deck's own origin, its script held his cookie and could POST `/api/action` with
# it, approving its own gate the moment he opened the plan. A CSP sandbox WITHOUT
# `allow-same-origin` gives the document an opaque origin: its scripts still run (a plan may
# be interactive), but nothing it sends is same-origin and no cookie goes with it.
#
# THE TOKENS ARE LAVISH'S OWN, minus nothing that matters: its artifact frame is sandboxed
# `allow-scripts allow-forms allow-popups allow-downloads`, and a CSP sandbox is intersected
# with the frame's, so a narrower one here would take forms and links out of a plan inside
# lavish. None of the four gives the document back an origin: a popup inherits the sandbox
# (no `allow-popups-to-escape-sandbox`), and a form it submits says `Origin: null`, which
# the deck's human path refuses (`deckauth.exact_origin`).
SANDBOX = "sandbox allow-scripts allow-forms allow-popups allow-downloads"
SCRIPTABLE = ("html", "svg", "xml")


def served_headers(content_type: str) -> dict:
    """The headers every artifact reply carries: never sniffed, and a sandbox on any type a
    browser would run script in."""
    headers = {"X-Content-Type-Options": "nosniff"}
    if any(word in (content_type or "").lower() for word in SCRIPTABLE):
        headers["Content-Security-Policy"] = SANDBOX
    return headers


def download_headers(path: str | Path) -> dict:
    """The headers that make a file a download rather than a page.

    `nosniff` matters as much as the type: without it a browser that disagrees with
    `application/octet-stream` may sniff the bytes, decide they are HTML and render them,
    which is the whole defence undone by one heuristic.
    """
    name = GENERATED_PREFIX.sub("", Path(str(path)).name)
    name = FILENAME_SAFE.sub("-", name).strip() or "file"
    return {"Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-Type-Options": "nosniff"}


def cap(cfg: Config, path: str | Path) -> int:
    """How many bytes the deck will serve of this file: the board's 16 MB for a board's own
    file, and this module's 8 MB for everything else."""
    return BOARD_MAX_BYTES if board_file(cfg, path) else MAX_BYTES


def under_root(path: Path, cfg: Config) -> bool:
    resolved_path = resolved(path)
    # `root in resolved.parents` built a Path per ancestor per root; the parts say the same.
    parts = resolved_path.parts
    return any(parts[:len(root.parts)] == root.parts for root in roots(cfg))


def denied(path: Path) -> bool:
    """True for anything that looks like a credential, wherever it lives.

    Four tests, and the first one is over EVERY component of the path: a secret in
    `myproj/credentials/service.json` is as much a secret as one in `./credentials`, and the
    directory is the only thing that says so.
    """
    parts = {part.lower() for part in path.parts}
    if parts & DENY_DIRS:
        return True
    name = path.name.lower()
    if name in DENY_NAMES or path.suffix.lower() in DENY_SUFFIX:
        return True
    return any(name.startswith(prefix) for prefix in DENY_PREFIXES)


def local_path(ref: str | Path, home: Path) -> Path:
    """A stored local ref as a path on this machine: absolute as it is, relative against
    the Keel home (`cfg.root`) of the machine reading it, never against the process cwd.

    `kb` has stored `plan_ref` absolute since c-574; a ref stored relative before that
    (c-573's `state/cards/c-573/plan.md`) named a file under the checkout, and read against
    the cwd it only worked when the reader happened to run from there."""
    path = Path(str(ref)).expanduser()
    return path if path.is_absolute() else home / path


def allowed(path: str | Path, cfg: Config) -> bool:
    path = Path(path).expanduser()
    return path.is_absolute() and not denied(path) and under_root(path, cfg)


def kind(path: str | Path) -> str:
    return KINDS.get(Path(path).suffix.lower(), "binary")


def mime(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    return MIME.get(suffix) or MIME.get(kind(path)) or "application/octet-stream"


# ----- tokens -----

def _pad(text: str) -> str:
    return text + "=" * (-len(text) % 4)


def token(cfg: Config, path: str | Path) -> str:
    raw = str(resolved(Path(path).expanduser())).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    signature = hmac.new(key(cfg), raw, hashlib.sha256).digest()[:SIGNATURE_BYTES]
    return body + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")


def untoken(cfg: Config, text: str) -> Path | None:
    """The path a token names, when it was minted here and is still allowed; else None."""
    try:
        body, signature = str(text).split(".", 1)
        raw = base64.urlsafe_b64decode(_pad(body))
        got = base64.urlsafe_b64decode(_pad(signature))
    except (ValueError, TypeError):
        return None
    want = hmac.new(key(cfg), raw, hashlib.sha256).digest()[:SIGNATURE_BYTES]
    if not hmac.compare_digest(want, got):
        return None
    path = Path(raw.decode(errors="replace"))
    return path if allowed(path, cfg) else None


def servable(cfg: Config, path: str | Path) -> Path | None:
    """The file a stored path names, when the deck may serve it: the path itself, or the
    `index.html` inside it when the path is a directory (a published artifact folder)."""
    found = local_path(path, cfg.root)
    if missing(found):
        return None
    if found.is_dir():
        found = found / "index.html"
    if not allowed(found, cfg) or not found.is_file():
        return None
    return resolved(found)


def url(cfg: Config, path: str | Path | None) -> str | None:
    """`/api/artifact/<token>` for a servable file, the URL itself for a URL, else None."""
    if not path:
        return None
    text = str(path)
    if re.match(r"^https?://", text):
        return text
    resolved = servable(cfg, text)
    return "/api/artifact/" + token(cfg, resolved) if resolved else None


# ----- markdown, just enough for a plan or a context file -----

SPANS = (
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
)
IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
HTTP = re.compile(r"^https?://", re.I)

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root{{color-scheme:dark}}
html,body{{margin:0;background:#171D23;color:#EAF2F8;font:13px/1.55 -apple-system,BlinkMacSystemFont,Inter,system-ui,sans-serif}}
body{{padding:16px;max-width:820px}}
h1,h2,h3{{font-size:15px;font-weight:600;margin:20px 0 8px}}h1{{margin-top:0}}
p,ul,ol,pre{{margin:0 0 12px}}li{{margin:2px 0}}
code{{font:11px ui-monospace,"SF Mono",Menlo,monospace;background:#26303A;padding:1px 4px}}
pre{{background:#1E262E;padding:12px;overflow-x:auto}}pre code{{background:transparent;padding:0}}
a{{color:#8FE7D7}}hr{{border:0;border-top:1px solid #33404C;margin:16px 0}}
img{{display:block;max-width:100%;height:auto;margin:0 0 12px;border:1px solid #33404C;background:#1E262E}}
.unserved{{color:#8AA0B4;border-bottom:1px dotted #4A5A68}}
table{{border-collapse:collapse;width:100%;margin:0 0 12px;font-size:12px}}
th,td{{border:1px solid #33404C;padding:6px 8px;text-align:left;vertical-align:top}}
th{{background:#1E262E;font-weight:600}}
</style></head><body>{body}</body></html>"""


def attr(value: str) -> str:
    """Escaped text (`html.escape(..., quote=False)` ran first) made safe in an attribute."""
    return value.replace('"', "&quot;")


def unserved(text: str, why: str) -> str:
    """What a picture or link the deck will not serve reads as: the words, and the reason."""
    return f'<span class="unserved" title="{attr(why)}">{text}</span>'


def target(cfg: Config | None, base_dir: Path | None, raw: str) -> tuple[str | None, str]:
    """The token URL for a path a document names, or None and the reason there is none.

    A relative path resolves against the directory of the document being rendered, which
    is what makes `assets/shot.png` beside a context file work; everything else goes
    through the same root and denylist rules as any other artifact.
    """
    text = html.unescape(raw)
    if HTTP.match(text):
        return None, "the deck serves its own files only, and this one is remote"
    if text.startswith("#"):
        return None, "a link into the document itself has nowhere to go here"
    if cfg is None or (base_dir is None and not Path(text).expanduser().is_absolute()):
        return None, "this document was rendered without a directory to resolve against"
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = Path(base_dir) / candidate
    resolved = servable(cfg, candidate)
    if resolved is not None:
        return "/api/artifact/" + token(cfg, resolved), ""
    if not allowed(candidate, cfg):
        return None, "outside the trees the deck serves, or denied as a credential"
    return None, "no such file"


def image_tag(match: re.Match, cfg: Config | None, base_dir: Path | None) -> str:
    alt, link, why = match.group(1), *target(cfg, base_dir, match.group(2))
    if link is None:
        return unserved(alt or match.group(2), why)
    return f'<img src="{link}" alt="{attr(alt)}">'


def link_tag(match: re.Match, cfg: Config | None, base_dir: Path | None) -> str:
    text, raw = match.group(1), match.group(2)
    if HTTP.match(html.unescape(raw)):
        return f'<a href="{attr(raw)}">{text}</a>'
    link, why = target(cfg, base_dir, raw)
    return f'<a href="{link}">{text}</a>' if link else unserved(text, why)


def inline(text: str, cfg: Config | None = None, base_dir: Path | None = None) -> str:
    out = html.escape(text, quote=False)
    for pattern, replacement in SPANS:
        out = pattern.sub(replacement, out)
    out = IMAGE.sub(lambda m: image_tag(m, cfg, base_dir), out)
    return LINK.sub(lambda m: link_tag(m, cfg, base_dir), out)


PIPE_ROW = re.compile(r"^\s*\|.*\|\s*$")
PIPE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
LI_CLOSE = "</li>"


def row_cells(line: str) -> list[str]:
    """One table row's cells. A cell may carry an escaped pipe, which is not a divider."""
    inner = line.strip().strip("|")
    return [cell.strip().replace("\\|", "|") for cell in UNESCAPED_PIPE.split(inner)]


def table_html(rows: list[str], inl) -> str:
    """A pipe table: the first row is the header, the second is its rule, the rest is body.

    A short row is padded and a long one is not truncated, because a table that loses a
    cell silently is worse than one that renders ragged.
    """
    header = row_cells(rows[0])
    width = len(header)
    out = ["<table><thead><tr>", *(f"<th>{inl(cell)}</th>" for cell in header), "</tr></thead><tbody>"]
    for line in rows[2:]:
        cells = row_cells(line)
        cells += [""] * (width - len(cells))
        out.append("<tr>" + "".join(f"<td>{inl(cell)}</td>" for cell in cells) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def markdown_html(text: str, title: str = "", base_dir: Path | None = None,
                  cfg: Config | None = None) -> str:
    """Headings, fenced code, lists, pipe tables, rules and paragraphs; no more.

    `base_dir` is the directory of the document itself and `cfg` the config whose roots say
    what may be served: with both, a relative image or link becomes a token URL. Without
    them (a plain render, a test) the picture becomes its alt text and the link its words.

    An indented line under a list item continues that item rather than starting a
    paragraph, which is what a wrapped bullet is; without it a wrapped item's second line
    fell out of the list.
    """
    def inl(piece: str) -> str:
        return inline(piece, cfg, base_dir)

    blocks, para, fence, code_lines, list_tag = [], [], False, [], None

    def flush_para():
        if para:
            blocks.append("<p>" + inl(" ".join(para)) + "</p>")
            para.clear()

    def close_list():
        nonlocal list_tag
        if list_tag:
            blocks.append(f"</{list_tag}>")
            list_tag = None

    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if line.startswith("```"):
            if fence:
                blocks.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
                code_lines = []
            else:
                flush_para()
                close_list()
            fence = not fence
            continue
        if fence:
            code_lines.append(line)
            continue
        if PIPE_ROW.match(line) and index < len(lines) and PIPE_RULE.match(lines[index]):
            flush_para()
            close_list()
            rows = [line]
            while index < len(lines) and PIPE_ROW.match(lines[index]):
                rows.append(lines[index])
                index += 1
            blocks.append(table_html(rows, inl))
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        item = re.match(r"^\s*([-*]|\d+[.)])\s+(.*)$", line)
        if heading:
            flush_para()
            close_list()
            level = min(len(heading.group(1)), 3)
            blocks.append(f"<h{level}>{inl(heading.group(2))}</h{level}>")
        elif re.match(r"^\s*(-{3,}|\*{3,})\s*$", line):
            flush_para()
            close_list()
            blocks.append("<hr>")
        elif item:
            flush_para()
            tag = "ol" if item.group(1)[0].isdigit() else "ul"
            if list_tag != tag:
                close_list()
                blocks.append(f"<{tag}>")
                list_tag = tag
            blocks.append(f"<li>{inl(item.group(2))}</li>")
        elif not line.strip():
            flush_para()
            close_list()
        elif (list_tag and not para and line[:1].isspace()
              and blocks and blocks[-1].endswith(LI_CLOSE)):
            blocks[-1] = blocks[-1][:-len(LI_CLOSE)] + " " + inl(line.strip()) + LI_CLOSE
        else:
            para.append(line.strip())
    if fence:
        blocks.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
    flush_para()
    close_list()
    return PAGE.format(title=html.escape(title or "artifact"), body="\n".join(blocks))


# ----- lavish surfaces -----
#
# Lavish is one server per machine that every invocation reuses, and it writes every
# session it opens to `~/.lavish-axi/state.json`: the key, the file behind it, its status.
# That file is on disk and outlives the server, which exits about thirty minutes after the
# last browser and poll disconnect, so a surface opened yesterday is still findable this
# morning even though nothing is listening: the deck's proxy starts lavish again on the
# first request for it. The format below was read off the real file on 2026-09-17.
#
# The URL handed out is a path on the deck's own origin (`/session/<key>`), never the
# `http://127.0.0.1:4387/...` the state file records. The human opens the deck from his
# phone over the tailnet, where 127.0.0.1 is his phone.

SURFACE_PREFIX = "/session/"
_surface_cache: tuple[tuple, dict[str, str]] | None = None


def lavish_sessions(cfg: Config) -> dict[str, str]:
    """`{resolved file: /session/<key>}` for every lavish session that has not ended.

    Cached against the state file's mtime and size, because the state document asks this
    once per card and the file is a hundred sessions long.
    """
    global _surface_cache
    path = cfg.lavish_state_file
    try:
        stat = path.stat()
    except OSError:
        return {}
    stamp = (str(path), stat.st_mtime_ns, stat.st_size)
    if _surface_cache is not None and _surface_cache[0] == stamp:
        return _surface_cache[1]
    try:
        sessions = (json.loads(path.read_text()) or {}).get("sessions") or {}
    except (OSError, ValueError, AttributeError):
        return {}
    newest: dict[str, tuple[str, str]] = {}
    for key_, session in sessions.items() if isinstance(sessions, dict) else []:
        if not isinstance(session, dict) or session.get("status") == "ended":
            continue
        file = session.get("file") or ""
        if not file:
            continue
        when = str(session.get("updated_at") or "")
        resolved = str(Path(file).expanduser().resolve())
        if resolved not in newest or when >= newest[resolved][0]:
            newest[resolved] = (when, str(session.get("key") or key_))
    found = {file: SURFACE_PREFIX + key_ for file, (_, key_) in newest.items()}
    _surface_cache = (stamp, found)
    return found


LAVISH = "lavish-axi"
LAVISH_SECONDS = 30


class LavishError(Exception):
    """Lavish would not do what was asked; the message is one line."""


def end_surface(plan_ref: str) -> dict:
    """End the lavish session on this plan, so the house's own poll returns."""
    try:
        result = subprocess.run([LAVISH, "end", plan_ref], capture_output=True, text=True,
                                timeout=LAVISH_SECONDS)
    except (OSError, subprocess.SubprocessError) as error:
        raise LavishError(f"lavish is not reachable, so nothing was ended: {error}") from None
    if result.returncode != 0:
        said = (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")
        raise LavishError(f"lavish would not end the session: {said.splitlines()[-1]}")
    return {"ended": plan_ref, "message": result.stdout.strip()}


def lavish_surface(cfg: Config, path: str | Path | None) -> str | None:
    """The live surface for an artifact lavish has a session for, as a path on this origin.

    None when the file has no session, when lavish ended it, or when the path is a URL: the
    deck then falls back to `links.plan`, the static token for the file itself.
    """
    if not path:
        return None
    text = str(path)
    if HTTP.match(text):
        return None
    try:
        found = str(resolved(local_path(text, cfg.root)))
    except OSError:
        return None
    return lavish_sessions(cfg).get(found)
